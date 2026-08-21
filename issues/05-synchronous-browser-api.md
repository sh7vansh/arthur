# 05 — Synchronous Python Browser API & Tab Management

**What to build:** An ergonomic, synchronous Python `Browser` and `Tab` facade (`browser.navigate()`, `browser.snapshot()`, `browser.click()`, `browser.type()`, `browser.new_tab()`, `browser.tabs()`, `browser.eval_js()`, `browser.screenshot()`) executing the CDP event loop in a background thread.

**Blocked by:** 04 (Synthetic Input Simulation).

**Status:** closed

- [x] Runs async CDP event loop in a dedicated background daemon thread.
- [x] Exposes synchronous methods (`navigate`, `snapshot`, `click`, `type`, `select`, `hover`, `scroll`, `screenshot`, `eval_js`).
- [x] Supports multi-tab creation, listing, switching, and closing.
- [x] Handles page load navigation synchronization and timeouts.
- [x] Standardizes structured exceptions (`BrowserUnavailableError`, `ElementNotFoundError`, `NavigationTimeoutError`).
- [x] Full end-to-end browser integration tests passing.
