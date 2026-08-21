"""Asynchronous, thread-safe Chrome DevTools Protocol (CDP) WebSocket client."""

import asyncio
import inspect
import json
import logging
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

import websockets
from websockets.asyncio.client import ClientConnection, connect

from arthur.errors import BrowserUnavailableError, CDPError

logger = logging.getLogger("arthur.cdp")

EventListener = Callable[[Dict[str, Any]], Any]


class CDPClient:
    """Asynchronous CDP WebSocket client with session multiplexing and event dispatching."""

    def __init__(self):
        self._ws: Optional[ClientConnection] = None
        self._ws_url: Optional[str] = None
        self._next_id: int = 0
        self._pending_requests: Dict[int, asyncio.Future[Dict[str, Any]]] = {}
        self._receive_task: Optional[asyncio.Task[None]] = None
        self._closed: bool = False
        self._lock = asyncio.Lock()

        # Listeners:
        # global: method -> list of callbacks
        self._global_listeners: Dict[str, List[EventListener]] = {}
        # session-scoped: (session_id, method) -> list of callbacks
        self._session_listeners: Dict[Tuple[str, str], List[EventListener]] = {}

    @property
    def is_connected(self) -> bool:
        """Return True if WebSocket is connected and open."""
        return self._ws is not None and not self._closed

    async def connect(self, ws_url: str, max_size: int = 64 * 1024 * 1024) -> None:
        """Connect to Chromium's DevTools WebSocket endpoint."""
        async with self._lock:
            if self.is_connected:
                return

            self._ws_url = ws_url
            self._closed = False
            try:
                self._ws = await connect(
                    ws_url,
                    max_size=max_size,
                    ping_interval=20,
                    ping_timeout=20,
                )
            except Exception as e:
                self._closed = True
                raise BrowserUnavailableError(
                    f"Failed to connect to Chromium DevTools endpoint at {ws_url}: {e}"
                ) from e

            loop = asyncio.get_running_loop()
            self._receive_task = loop.create_task(self._receive_loop())

    async def _receive_loop(self) -> None:
        """Background loop reading and dispatching CDP messages."""
        try:
            assert self._ws is not None
            async for raw_message in self._ws:
                try:
                    if isinstance(raw_message, bytes):
                        raw_message = raw_message.decode("utf-8")
                    message = json.loads(raw_message)
                except Exception as e:
                    logger.warning("Failed to decode CDP message: %s", e)
                    continue

                self._handle_incoming_message(message)
        except (websockets.ConnectionClosed, asyncio.CancelledError):
            pass
        except Exception as e:
            logger.debug("CDP receive loop error: %s", e)
        finally:
            await self._handle_disconnect()

    def _handle_incoming_message(self, message: Dict[str, Any]) -> None:
        """Route responses to pending futures or events to registered listeners."""
        req_id = message.get("id")
        if req_id is not None:
            future = self._pending_requests.pop(req_id, None)
            if future is not None and not future.done():
                if "error" in message:
                    err_info = message["error"]
                    code = err_info.get("code")
                    msg = err_info.get("message", "CDP command failed")
                    data = err_info.get("data")
                    future.set_exception(CDPError(msg, code=code, data=data))
                else:
                    future.set_result(message.get("result", {}))
            return

        method = message.get("method")
        if method:
            params = message.get("params", {})
            session_id = message.get("sessionId")
            self._dispatch_event(method, params, session_id)

    def _dispatch_event(
        self, method: str, params: Dict[str, Any], session_id: Optional[str]
    ) -> None:
        """Dispatch CDP events to matching callbacks."""
        # 1. Global method listeners
        listeners = list(self._global_listeners.get(method, []))
        # Wildcard global listeners
        listeners.extend(self._global_listeners.get("*", []))

        # 2. Session-specific listeners
        if session_id:
            listeners.extend(self._session_listeners.get((session_id, method), []))
            listeners.extend(self._session_listeners.get((session_id, "*"), []))

        for listener in listeners:
            try:
                res = listener(params)
                if inspect.isawaitable(res):
                    async def _runner(awaitable: Any) -> None:
                        await awaitable

                    asyncio.create_task(_runner(res))
            except Exception as e:
                logger.error("Error in CDP event listener for %s: %s", method, e)

    async def _handle_disconnect(self) -> None:
        """Cleanup pending futures and state when connection drops."""
        self._closed = True
        self._ws = None

        exc = BrowserUnavailableError("Chromium DevTools WebSocket disconnected.")
        for fut in list(self._pending_requests.values()):
            if not fut.done():
                fut.set_exception(exc)
        self._pending_requests.clear()

    async def call(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        timeout: Optional[float] = 30.0,
    ) -> Dict[str, Any]:
        """Send a CDP command and await response."""
        if not self.is_connected or self._ws is None:
            raise BrowserUnavailableError()

        async with self._lock:
            self._next_id += 1
            req_id = self._next_id

            payload: Dict[str, Any] = {
                "id": req_id,
                "method": method,
                "params": params if params is not None else {},
            }
            if session_id:
                payload["sessionId"] = session_id

            loop = asyncio.get_running_loop()
            future: asyncio.Future[Dict[str, Any]] = loop.create_future()
            self._pending_requests[req_id] = future

            try:
                await self._ws.send(json.dumps(payload))
            except Exception as e:
                self._pending_requests.pop(req_id, None)
                self._closed = True
                raise BrowserUnavailableError(f"Failed to send CDP command: {e}") from e

        try:
            if timeout is not None and timeout > 0:
                return await asyncio.wait_for(future, timeout=timeout)
            return await future
        except asyncio.TimeoutError:
            self._pending_requests.pop(req_id, None)
            raise TimeoutError(f"CDP command '{method}' timed out after {timeout:.1f}s")

    def on(
        self,
        event: str,
        callback: EventListener,
        session_id: Optional[str] = None,
    ) -> None:
        """Register an event callback."""
        if session_id:
            key = (session_id, event)
            self._session_listeners.setdefault(key, []).append(callback)
        else:
            self._global_listeners.setdefault(event, []).append(callback)

    def off(
        self,
        event: str,
        callback: EventListener,
        session_id: Optional[str] = None,
    ) -> None:
        """Unregister an event callback."""
        if session_id:
            key = (session_id, event)
            if key in self._session_listeners:
                self._session_listeners[key] = [
                    cb for cb in self._session_listeners[key] if cb != callback
                ]
                if not self._session_listeners[key]:
                    del self._session_listeners[key]
        else:
            if event in self._global_listeners:
                self._global_listeners[event] = [
                    cb for cb in self._global_listeners[event] if cb != callback
                ]
                if not self._global_listeners[event]:
                    del self._global_listeners[event]

    def once(
        self,
        event: str,
        callback: EventListener,
        session_id: Optional[str] = None,
    ) -> EventListener:
        """Register a one-shot event callback and return the unregister-able wrapper."""
        def _wrapper(params: Dict[str, Any]) -> Any:
            self.off(event, _wrapper, session_id=session_id)
            return callback(params)

        self.on(event, _wrapper, session_id=session_id)
        return _wrapper

    async def wait_for_event(
        self,
        event: str,
        predicate: Optional[Callable[[Dict[str, Any]], bool]] = None,
        session_id: Optional[str] = None,
        timeout: Optional[float] = 15.0,
    ) -> Dict[str, Any]:
        """Wait until a matching CDP event is received."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Dict[str, Any]] = loop.create_future()

        def _on_event(params: Dict[str, Any]) -> None:
            if predicate is None or predicate(params):
                if not future.done():
                    future.set_result(params)

        self.on(event, _on_event, session_id=session_id)
        try:
            if timeout is not None and timeout > 0:
                return await asyncio.wait_for(future, timeout=timeout)
            return await future
        finally:
            self.off(event, _on_event, session_id=session_id)

    async def attach_to_target(self, target_id: str, flatten: bool = True) -> str:
        """Attach to a target and return the assigned sessionId."""
        result = await self.call(
            "Target.attachToTarget",
            {"targetId": target_id, "flatten": flatten},
        )
        return str(result.get("sessionId", ""))

    async def detach_from_target(self, session_id: str) -> None:
        """Detach from a target session."""
        await self.call("Target.detachFromTarget", {"sessionId": session_id})

    async def close(self) -> None:
        """Close connection and clean up tasks."""
        self._closed = True
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        if self._receive_task is not None:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        await self._handle_disconnect()
