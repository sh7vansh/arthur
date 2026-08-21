"""Tests for arthur.browser — Synchronous Python Browser API & Tab Management."""

import urllib.parse
import pytest

from arthur.browser import Browser, Tab
from arthur.errors import ElementNotFoundError, NavigationTimeoutError


@pytest.fixture
def browser():
    b = Browser()
    yield b
    b.close()


def test_browser_lifecycle_and_navigation(browser: Browser):
    html = """
    <!DOCTYPE html>
    <html>
    <head><title>Arthur Browser Test</title></head>
    <body>
        <h1>Arthur Running Synchronously</h1>
        <p>Testing synchronous API facade.</p>
        <button id="btn">Click Here</button>
        <div id="output">Initial</div>
        <script>
            document.getElementById('btn').onclick = () => {
                document.getElementById('output').innerText = 'Clicked!';
            };
        </script>
    </body>
    </html>
    """
    data_url = "data:text/html;charset=utf-8," + urllib.parse.quote(html)

    browser.navigate(data_url)
    snap = browser.snapshot()

    assert 'PAGE: "Arthur Browser Test"' in snap
    assert 'heading[level=1]: "Arthur Running Synchronously"' in snap
    assert 'button [#1] "Click Here"' in snap

    # Test click
    browser.click(1)
    out = browser.eval_js("document.getElementById('output').innerText")
    assert out == "Clicked!"

    # Test get_text
    txt = browser.get_text("h1")
    assert txt == "Arthur Running Synchronously"


def test_browser_form_interactions(browser: Browser):
    html = """
    <!DOCTYPE html>
    <html>
    <body>
        <input id="txt" type="text" value="old text" />
        <select id="sel">
            <option value="a">Option A</option>
            <option value="b">Option B</option>
        </select>
    </body>
    </html>
    """
    data_url = "data:text/html;charset=utf-8," + urllib.parse.quote(html)
    browser.navigate(data_url)
    browser.snapshot()

    # Test type with clear
    browser.type(1, "new value", clear=True)
    val = browser.eval_js("document.getElementById('txt').value")
    assert val == "new value"

    # Test select
    browser.select(2, "Option B")
    sel_val = browser.eval_js("document.getElementById('sel').value")
    assert sel_val == "b"


def test_browser_multi_tab_management(browser: Browser):
    html1 = "data:text/html;charset=utf-8," + urllib.parse.quote("<html><head><title>Tab 1</title></head><body><h1>Tab 1</h1></body></html>")
    html2 = "data:text/html;charset=utf-8," + urllib.parse.quote("<html><head><title>Tab 2</title></head><body><h1>Tab 2</h1></body></html>")

    browser.navigate(html1)
    assert len(browser.tabs) >= 1

    t2 = browser.new_tab(html2)
    assert t2 is not None
    assert len(browser.tabs) >= 2

    # Switch / get tab
    t1 = browser.get_tab(1)
    assert t1 is not None

    # Screenshot
    ss = browser.screenshot()
    assert isinstance(ss, bytes)
    assert len(ss) > 0
    # PNG signature check: \x89PNG\r\n\x1a\n
    assert ss.startswith(b"\x89PNG")


def test_browser_wait_for_and_timeout(browser: Browser):
    html = """
    <!DOCTYPE html>
    <html>
    <body>
        <div id="delayed" style="display:none;">Delayed Content</div>
        <script>
            setTimeout(() => {
                document.getElementById('delayed').style.display = 'block';
            }, 100);
        </script>
    </body>
    </html>
    """
    data_url = "data:text/html;charset=utf-8," + urllib.parse.quote(html)
    browser.navigate(data_url)

    # Wait for element to become visible
    assert browser.wait_for("#delayed", state="visible", timeout=2.0) is True

    # Timeout waiting for nonexistent element
    with pytest.raises(NavigationTimeoutError):
        browser.wait_for("#never-exists", timeout=0.2)
