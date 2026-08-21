# 04 — Synthetic Input Simulation over CDP

**What to build:** Coordinate-accurate clicking, keystroke typing with optional Enter key submission, option selection, hovering, and scrolling targeting Ref-IDs or CSS selectors using native CDP input events (`Input.dispatchMouseEvent`, `Input.dispatchKeyEvent`).

**Blocked by:** 03 (In-Page Semantic Snapshot Generator).

**Status:** closed

- [x] Resolves Ref-ID or CSS selector to viewport coordinates via page registry.
- [x] Dispatches mouse click and hover via `Input.dispatchMouseEvent`.
- [x] Focuses target and dispatches individual keystrokes via `Input.dispatchKeyEvent`.
- [x] Handles `press_enter=True` to dispatch the Enter key sequence.
- [x] Selects `<select>` dropdown options by value or text.
- [x] Scrolls viewport or element via `scroll(x, y)` / wheel events.
- [x] Integration tests passing on interactive form, button, and navigation fixtures.
