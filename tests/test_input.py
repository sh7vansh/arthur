"""Tests for arthur.input — Synthetic Input Simulation over CDP."""

import urllib.parse
import pytest

from arthur.cdp import CDPClient
from arthur.dom import generate_snapshot
from arthur.input import (
    cdp_click,
    cdp_hover,
    cdp_press_key,
    cdp_scroll,
    cdp_select,
    cdp_type,
)
from arthur.launcher import launch_chromium


@pytest.fixture(scope="module")
def chromium_browser():
    inst = launch_chromium()
    yield inst
    inst.close()


@pytest.mark.asyncio
async def test_input_click_and_type(chromium_browser):
    client = CDPClient()
    await client.connect(chromium_browser.ws_url)

    html = """
    <!DOCTYPE html>
    <html>
    <body>
        <input id="input1" type="text" placeholder="Type here" />
        <button id="submit-btn" onclick="document.getElementById('status').innerText = 'Submitted: ' + document.getElementById('input1').value">Submit</button>
        <div id="status">Ready</div>
    </body>
    </html>
    """
    data_url = "data:text/html;charset=utf-8," + urllib.parse.quote(html)

    targets = await client.call("Target.getTargets")
    page_target = [t for t in targets["targetInfos"] if t["type"] == "page"][0]
    session_id = await client.attach_to_target(page_target["targetId"])

    await client.call("Page.enable", session_id=session_id)
    await client.call("Page.navigate", {"url": data_url}, session_id=session_id)
    await client.wait_for_event("Page.loadEventFired", session_id=session_id)

    # 1. Snapshot
    snap = await generate_snapshot(client, session_id=session_id)
    assert 'textbox [#1]' in snap.snapshot
    assert 'button [#2] "Submit"' in snap.snapshot

    # 2. Type text into input [#1]
    await cdp_type(client, 1, "Hello Arthur!", clear=True, session_id=session_id)

    # Verify input value
    val_res = await client.call(
        "Runtime.evaluate",
        {"expression": "document.getElementById('input1').value"},
        session_id=session_id,
    )
    assert val_res["result"]["value"] == "Hello Arthur!"

    # 3. Click button [#2]
    await cdp_click(client, 2, session_id=session_id)

    status_res = await client.call(
        "Runtime.evaluate",
        {"expression": "document.getElementById('status').innerText"},
        session_id=session_id,
    )
    assert status_res["result"]["value"] == "Submitted: Hello Arthur!"

    await client.detach_from_target(session_id)
    await client.close()


@pytest.mark.asyncio
async def test_input_type_press_enter_form_submit(chromium_browser):
    client = CDPClient()
    await client.connect(chromium_browser.ws_url)

    html = """
    <!DOCTYPE html>
    <html>
    <body>
        <form onsubmit="event.preventDefault(); document.getElementById('res').innerText = 'FormSubmitted:' + document.getElementById('q').value;">
            <input id="q" type="text" />
            <input type="submit" value="Search" />
        </form>
        <div id="res">Waiting</div>
    </body>
    </html>
    """
    data_url = "data:text/html;charset=utf-8," + urllib.parse.quote(html)

    targets = await client.call("Target.getTargets")
    page_target = [t for t in targets["targetInfos"] if t["type"] == "page"][0]
    session_id = await client.attach_to_target(page_target["targetId"])

    await client.call("Page.enable", session_id=session_id)
    await client.call("Page.navigate", {"url": data_url}, session_id=session_id)
    await client.wait_for_event("Page.loadEventFired", session_id=session_id)

    await generate_snapshot(client, session_id=session_id)

    # Type with press_enter=True
    await cdp_type(client, 1, "Query123", press_enter=True, session_id=session_id)

    res = await client.call(
        "Runtime.evaluate",
        {"expression": "document.getElementById('res').innerText"},
        session_id=session_id,
    )
    assert res["result"]["value"] == "FormSubmitted:Query123"

    await client.detach_from_target(session_id)
    await client.close()


@pytest.mark.asyncio
async def test_input_select_dropdown(chromium_browser):
    client = CDPClient()
    await client.connect(chromium_browser.ws_url)

    html = """
    <!DOCTYPE html>
    <html>
    <body>
        <select id="flavor" onchange="document.getElementById('chosen').innerText = this.value">
            <option value="vanilla">Vanilla</option>
            <option value="chocolate">Chocolate</option>
            <option value="strawberry">Strawberry</option>
        </select>
        <div id="chosen">none</div>
    </body>
    </html>
    """
    data_url = "data:text/html;charset=utf-8," + urllib.parse.quote(html)

    targets = await client.call("Target.getTargets")
    page_target = [t for t in targets["targetInfos"] if t["type"] == "page"][0]
    session_id = await client.attach_to_target(page_target["targetId"])

    await client.call("Page.enable", session_id=session_id)
    await client.call("Page.navigate", {"url": data_url}, session_id=session_id)
    await client.wait_for_event("Page.loadEventFired", session_id=session_id)

    await generate_snapshot(client, session_id=session_id)

    await cdp_select(client, 1, "chocolate", session_id=session_id)

    res = await client.call(
        "Runtime.evaluate",
        {"expression": "document.getElementById('chosen').innerText"},
        session_id=session_id,
    )
    assert res["result"]["value"] == "chocolate"

    await client.detach_from_target(session_id)
    await client.close()


@pytest.mark.asyncio
async def test_input_hover_and_scroll(chromium_browser):
    client = CDPClient()
    await client.connect(chromium_browser.ws_url)

    html = """
    <!DOCTYPE html>
    <html>
    <body style="height: 3000px;">
        <button id="hover-target" onmouseenter="document.getElementById('hover-status').innerText = 'Hovered!'">Hover Me</button>
        <div id="hover-status">Not Hovered</div>
    </body>
    </html>
    """
    data_url = "data:text/html;charset=utf-8," + urllib.parse.quote(html)

    targets = await client.call("Target.getTargets")
    page_target = [t for t in targets["targetInfos"] if t["type"] == "page"][0]
    session_id = await client.attach_to_target(page_target["targetId"])

    await client.call("Page.enable", session_id=session_id)
    await client.call("Page.navigate", {"url": data_url}, session_id=session_id)
    await client.wait_for_event("Page.loadEventFired", session_id=session_id)

    await generate_snapshot(client, session_id=session_id)

    # Hover
    await cdp_hover(client, 1, session_id=session_id)
    hover_res = await client.call(
        "Runtime.evaluate",
        {"expression": "document.getElementById('hover-status').innerText"},
        session_id=session_id,
    )
    assert hover_res["result"]["value"] == "Hovered!"

    # Scroll
    await cdp_scroll(client, x=0, y=400, session_id=session_id)
    scroll_res = await client.call(
        "Runtime.evaluate",
        {"expression": "window.scrollY"},
        session_id=session_id,
    )
    assert scroll_res["result"]["value"] >= 400

    await client.detach_from_target(session_id)
    await client.close()
