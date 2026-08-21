"""Synthetic input simulation over Chrome DevTools Protocol."""

import json
from typing import Any, Dict, Optional, Union

from arthur.cdp import CDPClient
from arthur.dom import resolve_target_coordinates
from arthur.errors import CDPError, ElementNotFoundError


async def cdp_click(
    cdp: CDPClient,
    target: Union[int, str],
    button: str = "left",
    click_count: int = 1,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Dispatch coordinate-accurate mouse click targeting a Ref-ID or CSS selector."""
    coord = await resolve_target_coordinates(cdp, target, session_id=session_id)
    x = float(coord["x"])
    y = float(coord["y"])

    # 1. Move mouse to target
    await cdp.call(
        "Input.dispatchMouseEvent",
        {"type": "mouseMoved", "x": x, "y": y},
        session_id=session_id,
    )

    # 2. Press and release
    for i in range(click_count):
        await cdp.call(
            "Input.dispatchMouseEvent",
            {
                "type": "mousePressed",
                "x": x,
                "y": y,
                "button": button,
                "clickCount": i + 1,
            },
            session_id=session_id,
        )
        await cdp.call(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseReleased",
                "x": x,
                "y": y,
                "button": button,
                "clickCount": i + 1,
            },
            session_id=session_id,
        )

    return {
        "status": "ok",
        "action": "click",
        "target": coord.get("targetLabel", str(target)),
        "x": x,
        "y": y,
    }


async def cdp_hover(
    cdp: CDPClient,
    target: Union[int, str],
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Dispatch mouse move to hover over target element."""
    coord = await resolve_target_coordinates(cdp, target, session_id=session_id)
    x = float(coord["x"])
    y = float(coord["y"])

    await cdp.call(
        "Input.dispatchMouseEvent",
        {"type": "mouseMoved", "x": x, "y": y},
        session_id=session_id,
    )

    return {
        "status": "ok",
        "action": "hover",
        "target": coord.get("targetLabel", str(target)),
        "x": x,
        "y": y,
    }


async def cdp_type(
    cdp: CDPClient,
    target: Union[int, str],
    text: str,
    clear: bool = True,
    press_enter: bool = False,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Focus target and dispatch keystrokes or text insertion."""
    # Focus via coordinate click
    await cdp_click(cdp, target, session_id=session_id)

    if clear:
        # Clear existing text
        await cdp.call(
            "Runtime.evaluate",
            {
                "expression": """
                (() => {
                    const el = document.activeElement;
                    if (el) {
                        if ('value' in el) el.value = '';
                        else if (el.isContentEditable) el.innerText = '';
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                })()
                """
            },
            session_id=session_id,
        )

    # Insert text via Input.insertText for full Unicode and speed
    if text:
        await cdp.call(
            "Input.insertText",
            {"text": text},
            session_id=session_id,
        )

    if press_enter:
        await cdp.call(
            "Input.dispatchKeyEvent",
            {
                "type": "rawKeyDown",
                "key": "Enter",
                "code": "Enter",
                "windowsVirtualKeyCode": 13,
                "nativeVirtualKeyCode": 13,
            },
            session_id=session_id,
        )
        await cdp.call(
            "Input.dispatchKeyEvent",
            {
                "type": "keyUp",
                "key": "Enter",
                "code": "Enter",
                "windowsVirtualKeyCode": 13,
                "nativeVirtualKeyCode": 13,
            },
            session_id=session_id,
        )
        # Form submit fallback if needed
        await cdp.call(
            "Runtime.evaluate",
            {
                "expression": """
                (() => {
                    const el = document.activeElement;
                    if (el && el.form) {
                        if (typeof el.form.requestSubmit === 'function') {
                            el.form.requestSubmit();
                        } else {
                            el.form.submit();
                        }
                    }
                })()
                """
            },
            session_id=session_id,
        )

    return {
        "status": "ok",
        "action": "type",
        "target": str(target),
        "text": text,
    }


async def cdp_select(
    cdp: CDPClient,
    target: Union[int, str],
    value: str,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Select option in a <select> element by value or visible text."""
    expr = f"""
    ((target, value) => {{
        let el = null;
        if (typeof target === 'number') {{
            el = window.__AG_REGISTRY__?.refMap?.get(target);
        }} else if (typeof target === 'string') {{
            const m = target.match(/^\\[#\\s*(\\d+)\\]$/) || target.match(/^#(\\d+)$/);
            if (m) el = window.__AG_REGISTRY__?.refMap?.get(parseInt(m[1], 10));
            else el = document.querySelector(target);
        }}
        if (!el || el.tagName !== 'SELECT') {{
            return {{ __error: {{ code: 'ELEMENT_NOT_FOUND', target: String(target), message: 'Element is not a <select> dropdown' }} }};
        }}
        let found = false;
        for (const opt of el.options) {{
            if (opt.value === value || opt.text === value) {{
                opt.selected = true;
                found = true;
                break;
            }}
        }}
        if (found) {{
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            return {{ status: 'ok', action: 'select', value, target: String(target) }};
        }}
        return {{ __error: {{ code: 'ELEMENT_NOT_FOUND', target: String(target), message: 'Option \"' + value + '\" not found' }} }};
    }})({json.dumps(target)}, {json.dumps(value)})
    """

    res = await cdp.call(
        "Runtime.evaluate",
        {"expression": expr, "returnByValue": True, "awaitPromise": True},
        session_id=session_id,
    )
    val = res.get("result", {}).get("value", {})
    if "__error" in val:
        err = val["__error"]
        if err.get("code") == "ELEMENT_NOT_FOUND":
            raise ElementNotFoundError(target=str(target))
        raise CDPError(err.get("message", "Failed to select option"))

    return val  # type: ignore[no-any-return]


async def cdp_scroll(
    cdp: CDPClient,
    x: int = 0,
    y: int = 500,
    target: Optional[Union[int, str]] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Scroll viewport or specific element."""
    if target is not None:
        coord = await resolve_target_coordinates(cdp, target, session_id=session_id)
        cx = float(coord["x"])
        cy = float(coord["y"])
        await cdp.call(
            "Input.dispatchMouseEvent",
            {"type": "mouseWheel", "x": cx, "y": cy, "deltaX": x, "deltaY": y},
            session_id=session_id,
        )
    else:
        await cdp.call(
            "Runtime.evaluate",
            {
                "expression": f"window.scrollBy({{ left: {x}, top: {y}, behavior: 'instant' }})"
            },
            session_id=session_id,
        )

    return {"status": "ok", "action": "scroll", "x": x, "y": y}


async def cdp_press_key(
    cdp: CDPClient,
    key: str,
    code: Optional[str] = None,
    session_id: Optional[str] = None,
) -> None:
    """Dispatch key press (down + up)."""
    await cdp.call(
        "Input.dispatchKeyEvent",
        {"type": "rawKeyDown", "key": key, "code": code or key},
        session_id=session_id,
    )
    await cdp.call(
        "Input.dispatchKeyEvent",
        {"type": "keyUp", "key": key, "code": code or key},
        session_id=session_id,
    )
