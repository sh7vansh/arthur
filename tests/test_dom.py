"""Tests for arthur.dom — In-Page Semantic Snapshot Generator & Ref-ID Registry."""

import pytest
from arthur.cdp import CDPClient
from arthur.dom import (
    DOMSnapshotResult,
    generate_snapshot,
    get_dom_metrics,
    resolve_target_coordinates,
)
from arthur.errors import ElementNotFoundError
from arthur.launcher import launch_chromium


@pytest.fixture(scope="module")
def chromium_browser():
    inst = launch_chromium()
    yield inst
    inst.close()


@pytest.mark.asyncio
async def test_snapshot_generator_basic(chromium_browser):
    client = CDPClient()
    await client.connect(chromium_browser.ws_url)

    html = """
    <!DOCTYPE html>
    <html>
    <head><title>Arthur Test Page</title></head>
    <body>
        <h1>Welcome to Arthur</h1>
        <p>This is a test paragraph.</p>
        <form>
            <label for="username">Username</label>
            <input id="username" type="text" placeholder="Enter username" />
            <button type="submit">Log In</button>
            <a href="https://example.com/forgot">Forgot Password?</a>
        </form>
    </body>
    </html>
    """
    import urllib.parse
    data_url = "data:text/html;charset=utf-8," + urllib.parse.quote(html)

    # Attach to the initial page target
    targets = await client.call("Target.getTargets")
    page_target = [t for t in targets["targetInfos"] if t["type"] == "page"][0]
    session_id = await client.attach_to_target(page_target["targetId"])

    await client.call("Page.enable", session_id=session_id)
    await client.call("Page.navigate", {"url": data_url}, session_id=session_id)
    await client.wait_for_event("Page.loadEventFired", session_id=session_id)

    res: DOMSnapshotResult = await generate_snapshot(client, session_id=session_id)

    assert "PAGE: \"Arthur Test Page\"" in res.snapshot
    assert "heading[level=1]" in res.snapshot
    assert "textbox [#1]" in res.snapshot
    assert "Username" in res.snapshot
    assert "button [#2]" in res.snapshot
    assert "Log In" in res.snapshot
    assert "link [#3]" in res.snapshot
    assert "Forgot Password?" in res.snapshot
    assert res.total_interactive == 3

    # Test coordinate resolution
    coord = await resolve_target_coordinates(client, 1, session_id=session_id)
    assert coord["x"] > 0
    assert coord["y"] > 0
    assert coord["tagName"] == "INPUT"

    # Test resolving by CSS selector
    coord_css = await resolve_target_coordinates(client, "button", session_id=session_id)
    assert coord_css["x"] > 0
    assert coord_css["y"] > 0
    assert coord_css["tagName"] == "BUTTON"

    # Test metrics
    metrics = await get_dom_metrics(client, session_id=session_id)
    assert metrics["refCount"] >= 3
    assert metrics["title"] == "Arthur Test Page"

    await client.detach_from_target(session_id)
    await client.close()


@pytest.mark.asyncio
async def test_stale_ref_suggestions(chromium_browser):
    client = CDPClient()
    await client.connect(chromium_browser.ws_url)

    html = """
    <!DOCTYPE html>
    <html>
    <body>
        <div id="container">
            <button id="btn1">Submit Order</button>
        </div>
    </body>
    </html>
    """
    import urllib.parse
    data_url = "data:text/html;charset=utf-8," + urllib.parse.quote(html)

    targets = await client.call("Target.getTargets")
    page_target = [t for t in targets["targetInfos"] if t["type"] == "page"][0]
    session_id = await client.attach_to_target(page_target["targetId"])

    await client.call("Page.enable", session_id=session_id)
    await client.call("Page.navigate", {"url": data_url}, session_id=session_id)
    await client.wait_for_event("Page.loadEventFired", session_id=session_id)

    # Initial snapshot creates Ref [#1]
    await generate_snapshot(client, session_id=session_id)

    # Mutate DOM to replace button with a new one
    await client.call(
        "Runtime.evaluate",
        {
            "expression": """
            document.getElementById('container').innerHTML = '<button id="btn2">Submit Order</button>';
            """
        },
        session_id=session_id,
    )

    # Check that query for stale ref returns stale error info
    with pytest.raises(ElementNotFoundError) as exc_info:
        await resolve_target_coordinates(client, 1, session_id=session_id)

    assert exc_info.value.stale is True

    await client.detach_from_target(session_id)
    await client.close()


@pytest.mark.asyncio
async def test_snapshot_roles_and_attributes(chromium_browser):
    client = CDPClient()
    await client.connect(chromium_browser.ws_url)

    html = """
    <!DOCTYPE html>
    <html>
    <head><title>Form Components</title></head>
    <body>
        <div role="search">
            <input type="search" aria-label="Site Search" placeholder="Search..." value="query" />
        </div>
        <select id="country" aria-label="Country Selector">
            <option value="us">United States</option>
            <option value="ca" selected>Canada</option>
        </select>
        <input type="checkbox" id="subscribe" checked />
        <label for="subscribe">Subscribe to newsletter</label>
        <input type="radio" id="opt1" name="radio-group" disabled />
        <label for="opt1">Option 1</label>
    </body>
    </html>
    """
    import urllib.parse
    data_url = "data:text/html;charset=utf-8," + urllib.parse.quote(html)

    targets = await client.call("Target.getTargets")
    page_target = [t for t in targets["targetInfos"] if t["type"] == "page"][0]
    session_id = await client.attach_to_target(page_target["targetId"])

    await client.call("Page.enable", session_id=session_id)
    await client.call("Page.navigate", {"url": data_url}, session_id=session_id)
    await client.wait_for_event("Page.loadEventFired", session_id=session_id)

    res = await generate_snapshot(client, session_id=session_id)
    assert 'searchbox [#1] "Site Search"' in res.snapshot
    assert 'value="query"' in res.snapshot
    assert 'combobox [#2] "Country Selector"' in res.snapshot
    assert 'checkbox [#3] "Subscribe to newsletter" (checked)' in res.snapshot
    assert 'radio [#4] "Option 1" (disabled)' in res.snapshot

    await client.detach_from_target(session_id)
    await client.close()

