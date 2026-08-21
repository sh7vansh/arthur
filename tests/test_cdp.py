"""Tests for arthur.cdp — Minimal CDP WebSocket Client & Session Dispatcher."""

import asyncio
import json
import pytest
import websockets
from websockets.asyncio.server import serve

from arthur.cdp import CDPClient
from arthur.errors import BrowserUnavailableError, CDPError


class MockCDPServer:
    """Mock CDP WebSocket server for unit testing CDPClient."""

    def __init__(self):
        self.server = None
        self.port = None
        self.ws_url = None
        self.active_sockets = set()
        self.received_messages = []
        self.custom_handlers = {}

    async def start(self):
        async def handler(websocket):
            self.active_sockets.add(websocket)
            try:
                async for raw_msg in websocket:
                    msg = json.loads(raw_msg)
                    self.received_messages.append(msg)
                    msg_id = msg.get("id")
                    method = msg.get("method")
                    session_id = msg.get("sessionId")

                    if method in self.custom_handlers:
                        await self.custom_handlers[method](websocket, msg)
                    elif msg_id is not None:
                        # Default response
                        response = {
                            "id": msg_id,
                            "result": {"acknowledged": True, "method": method},
                        }
                        if session_id:
                            response["sessionId"] = session_id
                        await websocket.send(json.dumps(response))
            except websockets.ConnectionClosed:
                pass
            finally:
                self.active_sockets.discard(websocket)

        self.server = await serve(handler, "127.0.0.1", 0)
        # Extract allocated port
        sockets = self.server.sockets
        self.port = sockets[0].getsockname()[1]
        self.ws_url = f"ws://127.0.0.1:{self.port}"

    async def broadcast_event(self, method: str, params: dict, session_id: str = None):
        msg = {"method": method, "params": params}
        if session_id:
            msg["sessionId"] = session_id
        payload = json.dumps(msg)
        for ws in list(self.active_sockets):
            await ws.send(payload)

    async def stop(self):
        for ws in list(self.active_sockets):
            await ws.close()
        if self.server:
            self.server.close()
            await self.server.wait_closed()


@pytest.fixture
async def mock_server():
    server = MockCDPServer()
    await server.start()
    yield server
    await server.stop()


@pytest.mark.asyncio
async def test_cdp_client_connect_and_call(mock_server):
    client = CDPClient()
    await client.connect(mock_server.ws_url)
    assert client.is_connected

    result = await client.call("Page.enable")
    assert result == {"acknowledged": True, "method": "Page.enable"}
    assert len(mock_server.received_messages) == 1
    assert mock_server.received_messages[0]["method"] == "Page.enable"

    await client.close()
    assert not client.is_connected


@pytest.mark.asyncio
async def test_cdp_client_call_with_session_id(mock_server):
    client = CDPClient()
    await client.connect(mock_server.ws_url)

    result = await client.call(
        "Page.navigate", {"url": "https://example.com"}, session_id="session-123"
    )
    assert result == {"acknowledged": True, "method": "Page.navigate"}
    sent_msg = mock_server.received_messages[0]
    assert sent_msg["sessionId"] == "session-123"
    assert sent_msg["params"]["url"] == "https://example.com"

    await client.close()


@pytest.mark.asyncio
async def test_cdp_client_propagates_cdp_error(mock_server):
    async def error_handler(ws, msg):
        await ws.send(
            json.dumps(
                {
                    "id": msg["id"],
                    "error": {
                        "code": -32000,
                        "message": "Cannot navigate to invalid URL",
                        "data": "Details",
                    },
                }
            )
        )

    mock_server.custom_handlers["Page.navigate"] = error_handler

    client = CDPClient()
    await client.connect(mock_server.ws_url)

    with pytest.raises(CDPError) as exc_info:
        await client.call("Page.navigate", {"url": "invalid://"})

    assert "Cannot navigate to invalid URL" in str(exc_info.value)
    assert exc_info.value.code == -32000

    await client.close()


@pytest.mark.asyncio
async def test_cdp_client_event_dispatching(mock_server):
    client = CDPClient()
    await client.connect(mock_server.ws_url)

    global_events = []
    session_events = []

    def on_load(params):
        global_events.append(params)

    def on_session_load(params):
        session_events.append(params)

    client.on("Page.loadEventFired", on_load)
    client.on("Page.loadEventFired", on_session_load, session_id="session-1")

    # Broadcast event without session
    await mock_server.broadcast_event("Page.loadEventFired", {"timestamp": 123.45})
    await asyncio.sleep(0.05)

    assert len(global_events) == 1
    assert global_events[0]["timestamp"] == 123.45
    assert len(session_events) == 0

    # Broadcast event with session-1
    await mock_server.broadcast_event(
        "Page.loadEventFired", {"timestamp": 678.90}, session_id="session-1"
    )
    await asyncio.sleep(0.05)

    assert len(global_events) == 2
    assert len(session_events) == 1
    assert session_events[0]["timestamp"] == 678.90

    # Test removing listener
    client.off("Page.loadEventFired", on_load)
    await mock_server.broadcast_event("Page.loadEventFired", {"timestamp": 999.99})
    await asyncio.sleep(0.05)

    assert len(global_events) == 2

    await client.close()


@pytest.mark.asyncio
async def test_cdp_client_wait_for_event(mock_server):
    client = CDPClient()
    await client.connect(mock_server.ws_url)

    async def trigger_event():
        await asyncio.sleep(0.05)
        await mock_server.broadcast_event(
            "Page.domContentEventFired", {"timestamp": 555.55}
        )

    asyncio.create_task(trigger_event())
    event_data = await client.wait_for_event("Page.domContentEventFired", timeout=2.0)
    assert event_data["timestamp"] == 555.55

    await client.close()


@pytest.mark.asyncio
async def test_cdp_client_connection_drop_raises_browser_unavailable(mock_server):
    client = CDPClient()
    await client.connect(mock_server.ws_url)

    # Abruptly stop server
    await mock_server.stop()
    await asyncio.sleep(0.05)

    assert not client.is_connected

    with pytest.raises(BrowserUnavailableError):
        await client.call("Page.enable")
