# Spec: Arthur — Lightweight Headless Chromium Runtime for Gloria

**Status:** `ready-for-agent`

---

## Problem Statement

Gloria and autonomous AI agents require programmatic browser control, but existing solutions like Chrome Bridge rely on Chrome extension MV3 injection, Native Messaging hosts, enterprise policies, and local socket IPC. When running autonomous agents or containerized workloads, this introduces excessive moving parts, installation brittleness, and dependency on user-interactive Chrome sessions.

Agents need a self-owned, lightweight headless Chromium instance that eliminates all extension and native-host machinery while preserving the familiar, token-efficient Python REPL execution model, semantic Ref-ID snapshots, and MCP `execute_python` tool interface.

## Solution

Arthur is a standalone, lightweight headless Chromium runtime for Gloria and AI agents. It connects directly to Chromium via Chrome DevTools Protocol (CDP) WebSockets, manages its own ephemeral Chromium subprocess, retains persistent Python REPL state across executions, generates concise semantic Ref-ID DOM snapshots, and exposes a drop-in MCP `execute_python` tool interface.

Under the hood:
```text
Gloria / Agent ──▶ MCP (execute_python) ──▶ PythonReplSession ──▶ Arthur Browser API ──▶ CDP WebSocket ──▶ Chromium (--headless=new)
```

---

## User Stories

1. As an AI agent, I want to execute Python scripts in a persistent session via the `execute_python` MCP tool, so that variables, helper functions, and browser state persist across successive turns.
2. As an AI agent, I want to call `browser.snapshot()`, so that I receive a compact, token-efficient semantic tree of interactive elements with assigned Ref-IDs (`[#1]`, `[#2]`).
3. As an AI agent, I want to interact with elements by Ref-ID (e.g. `browser.click(1)` or `browser.type('[#2]', 'query')`), so that I don't have to craft fragile XPath or CSS selectors.
4. As an AI agent, I want to interact with elements using CSS selectors (e.g. `browser.click('#submit-btn')`), so that I have selector fallback when needed.
5. As an AI agent, I want `browser.type(ref, text, press_enter=True)` to dispatch realistic keystrokes and optionally submit forms with the Enter key, so that search bars and inputs trigger appropriate JavaScript event handlers.
6. As an AI agent, I want `browser.select(ref, value)` to select options in `<select>` elements, so that dropdown menus can be manipulated seamlessly.
7. As an AI agent, I want `browser.hover(ref)` to move the mouse pointer over elements, so that hover-activated dropdowns and tooltips appear.
8. As an AI agent, I want `browser.scroll(x, y)` to scroll the viewport or specific elements, so that lazy-loaded content becomes visible in subsequent snapshots.
9. As an AI agent, I want `browser.navigate(url)` to load web pages and wait for page load completion, so that I can browse the web reliably.
10. As an AI agent, I want `browser.new_tab(url)` and `browser.tabs()` to manage multiple concurrent tabs, so that I can perform cross-site or multi-page workflows.
11. As an AI agent, I want `browser.eval_js(expression)` to execute arbitrary JavaScript within the page context and return the serialized result, so that I can inspect custom DOM attributes or execute page scripts.
12. As an AI agent, I want `browser.screenshot()` to capture viewport images, so that visual page state can be verified.
13. As an AI agent, when an element is stale or missing due to a DOM mutation, I want to receive an `ElementNotFoundError` with fuzzy match suggestions from recent snapshot history, so that I can self-heal without wasting turns.
14. As an AI agent, when an unhandled exception occurs in my Python REPL execution, I want an automatic `[diagnostic_auto_snapshot]` appended to the error output, so that I immediately see the current DOM state without an extra roundtrip.
15. As an AI agent, I want stdout, stderr, and return values to be bounded by token budget limits with clean string defanging, so that context windows are never blown by huge responses or image beacons.
16. As a developer running Arthur, I want the system to automatically locate a local Chromium binary across standard paths or environment overrides, so that no manual configuration is required.
17. As a developer running Arthur, I want Chromium to run in an isolated temporary user-data directory with ephemeral port allocation, so that concurrent or sequential instances do not conflict.
18. As a developer running Arthur, I want all Chromium subprocesses and temporary directories to be automatically cleaned up on process exit or termination signals, so that no orphaned browser processes linger in the system.
19. As Gloria, I want Arthur to expose a standard FastMCP stdio server, so that Gloria can plug Arthur directly into `mcp-proxy` or agent client configs as a drop-in replacement for Chrome Bridge.

---

## Implementation Decisions

### 1. Direct CDP WebSocket Transport (`arthur.cdp`)
- Implement a minimal, async/sync CDP client using a lightweight WebSocket library (`websockets`).
- Support generic command dispatch:
  ```python
  await cdp.call("Page.navigate", {"url": url}, session_id=session_id)
  ```
- Correlate numeric request `id`s with `asyncio.Future` objects for concurrent command execution and error propagation.
- Handle target session multiplexing via `Target.attachToTarget` (with `flatten: true`), allowing multiple tabs to be controlled across a single root WebSocket connection using `sessionId`.
- Restrict CDP domain usage strictly to `Browser`, `Target`, `Page`, `Runtime`, `DOM`, and `Input`.

### 2. Chromium Lifecycle & Ephemeral Sandbox (`arthur.launcher`)
- Automatic binary discovery probing `CHROMIUM_PATH`, `CHROME_PATH`, system paths (`chromium`, `google-chrome`, `google-chrome-stable`, `chromium-browser`, `/usr/bin/chromium`), and Flatpak/Snap fallback paths.
- Launch Chromium with `--headless=new`, `--remote-debugging-port=0` (ephemeral port), `--no-first-run`, `--no-default-browser-check`, `--disable-background-networking`, `--disable-dev-shm-usage`, and a dedicated temporary `user-data-dir`.
- Parse the assigned DevTools port/WebSocket URL from `DevToolsActivePort` file in the user data directory.
- Register `atexit` and POSIX signal handlers (`SIGINT`, `SIGTERM`) to terminate the Chromium subprocess tree and purge the temporary user data directory.

### 3. In-Page Semantic Snapshot Generator (`arthur.dom`)
- Evaluate an adapted in-page traversal script via CDP `Runtime.evaluate` to generate the semantic DOM outline.
- Compute accessible roles (`button`, `link`, `textbox`, `combobox`, `checkbox`, `heading`, etc.) and accessible names (`aria-label`, `aria-labelledby`, `<label>`, placeholder, title, text).
- Assign Ref-IDs (`[#1]`, `[#2]`) and maintain an in-page registry (`window.__AG_REGISTRY__`) mapping Ref-IDs to element references and viewport bounding boxes (center `x, y`, `width, height`).
- Store recent snapshot history to provide fuzzy match suggestions in `ElementNotFoundError` payloads when an element reference becomes stale.

### 4. CDP Synthetic Input Simulation (`arthur.input`)
- For `click(ref)` / `hover(ref)`: Resolve the element's center coordinates from the in-page registry and dispatch CDP `Input.dispatchMouseEvent` (`mousePressed`, `mouseReleased`, `mouseMoved`).
- For `type(ref, text, press_enter)`: Focus the target element, dispatch `Input.dispatchKeyEvent` sequences for each character, and dispatch `Enter` if requested.
- For `select(ref, value)` / `scroll(x, y)`: Dispatch corresponding CDP/DOM actions.

### 5. Synchronous Python API Facade (`arthur.browser`)
- Run the asynchronous CDP event loop in a dedicated background daemon thread.
- Expose a thread-safe, synchronous Python API (`browser` and `tab` objects) so agent scripts can execute standard synchronous code without requiring top-level `asyncio.run()`.
- Standardize error types: `BrowserUnavailableError`, `ElementNotFoundError`, `NavigationTimeoutError`, `ActionInterceptionError`.

### 6. Persistent REPL Engine & Output Budgeting (`arthur.repl`)
- Reuse Chrome Bridge's AST statement/expression execution engine (`exec` for statements, `eval` for trailing expressions).
- Pre-inject the synchronous `browser` instance into the persistent globals dictionary.
- Format execution output using `OutputBudgetFormatter` with configurable character caps, token estimates, and image beacon defanging.
- Apply execution timeout watchdog via `ExecutionTimeoutContext`.
- Automatically capture `browser.snapshot()` and format as `[diagnostic_auto_snapshot]` whenever an unhandled exception occurs in user code.

### 7. FastMCP Server & Packaging (`arthur.server`)
- Expose FastMCP server with `execute_python(code)` tool.
- Provide CLI entrypoints: `arthur mcp` (stdio server) and `arthur repl` (interactive runner).
- Package via `pyproject.toml` with `uv` support, specifying minimal dependencies (`mcp`, `websockets`).

---

## Testing Decisions

### Seam Strategy
- **Primary Seam:** Test at the highest public Python facade — the `Arthur` synchronous `Browser` API and the `execute_python` REPL session.
- Tests will run against a real local headless Chromium instance launched via Arthur's lifecycle manager.
- Local HTML test fixtures will be served via a lightweight local HTTP server or `file://` URLs to test:
  1. **Lifecycle**: Clean process startup, port discovery, and teardown.
  2. **CDP Transport**: Command dispatch, event listeners, and target session switching.
  3. **Snapshots**: Semantic role resolution, accessible naming, Ref-ID indexing, and viewport filtering.
  4. **Actions**: Clicking buttons, typing into textboxes with Enter submission, selecting dropdowns, and scrolling.
  5. **Stale References & Diagnostics**: Catching mutated DOM references with fuzzy suggestions and auto-snapshot on exception.
  6. **REPL State Persistence**: Verifying variables and browser references persist across successive `execute()` calls.
  7. **MCP Protocol**: Verifying `execute_python` tool serialization over stdio.

---

## Out of Scope

- Chrome extension packaging, background service workers, and popup UIs.
- Native Messaging host manifests and shell wrappers.
- Interactive X11 / noVNC desktop UI streaming (handled by Gloria container level).
- Multi-browser engine abstraction (Firefox, WebKit / Playwright emulation).
- Full CDP protocol code generation (generic `cdp.call(method, params)` is preferred).

---

## Further Notes

- Arthur is designed as a direct drop-in replacement for Chrome Bridge in Gloria's `start-mcp-proxy.sh` and standalone agent workflows.
