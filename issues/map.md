# Map: Arthur — Lightweight Headless Chromium Runtime for Gloria

## Destination

A standalone, fully-tested, lightweight repository (`Arthur`) providing an MCP `execute_python` server backed by a self-managed headless Chromium process over direct CDP WebSockets, with persistent Python REPL state, semantic Ref-ID DOM snapshots, and zero Chrome extension/native-host machinery.

**Canonical Spec:** [Spec: Arthur — Lightweight Headless Chromium Runtime for Gloria](./spec-arthur-headless-runtime.md) (`ready-for-agent`)

## Notes

- **Domain:** Headless Browser Automation, Chrome DevTools Protocol (CDP), Model Context Protocol (MCP), Python REPL Runtime.
- **Consult Skills:** `google-antigravity-sdk`, `chrome-bridge`, `agy-customizations`.
- **Standing Preferences:**
  - Keep Arthur minimal, clean, and standalone. Do not build a Playwright competitor.
  - Expose the exact `execute_python(code)` MCP tool interface with synchronous `browser` API and Ref-IDs (`[#1]`, `[#2]`).
  - Zero extension, zero native messaging, zero X11/VNC dependency.
  - Direct CDP over WebSocket (`Browser`, `Target`, `Page`, `Runtime`, `DOM`, `Input`).

## Decisions so far

- [01: Minimal CDP WebSocket Client & Session Dispatcher](./01-minimal-cdp-websocket-client.md) — Built async, thread-safe CDP WebSocket client with session multiplexing and event dispatching.
- [02: Headless Chromium Process Lifecycle & Ephemeral Sandbox](./02-chromium-process-lifecycle.md) — Implemented cross-platform binary discovery, ephemeral `--user-data-dir`, DevToolsActivePort detection, and atexit/signal teardown.
- [03: In-Page Semantic Snapshot Generator & Ref-ID Registry](./03-semantic-snapshot-generator.md) — In-page DOM engine generating compact accessible role/name snapshots with sequential Ref-IDs (`[#1]`, `[#2]`) and coordinate tracking.
- [04: Synthetic Input Simulation over CDP](./04-cdp-synthetic-input.md) — Built coordinate hit-tested clicks, keystroke typing with `press_enter`, `<select>` option picking, hover, and scroll.
- [05: Synchronous Python Browser API & Tab Management](./05-synchronous-browser-api.md) — Built synchronous Python `Browser` and `Tab` facade backed by a background daemon CDP event loop thread.
- [06: Persistent REPL Engine & Output Budgeting](./06-persistent-repl-engine.md) — Built stateful REPL engine with statement/expression AST splitting, pre-injected `browser`, output token caps, and diagnostic auto-snapshot on exception.
- [07: FastMCP Server & stdio CLI](./07-fastmcp-server-and-cli.md) — Built FastMCP server exposing `execute_python(code)` for Gloria and CLI entrypoints (`arthur mcp` and `arthur repl`).

## Frontier Tickets

*(All current frontier tickets completed)*

## Blocked Tickets

*(None)*

## Not yet specified

- Target auto-attachment policy and handler for multi-window / popup target creation (`Target.setAutoAttach`).
- Network request blocking (e.g. lightweight ad/tracker filter list evaluation if desired).
- Screenshot format and compression tuning for agent token optimization.

## Out of scope

- Chrome extension packaging, native messaging hosts, or browser popup UIs.
- Interactive X11 / noVNC desktop UI integration (managed by Gloria's host container).
- Multi-browser engine support (Firefox, WebKit / Playwright emulation).
- Full CDP protocol code generation (maintain a minimal, generic call interface).
