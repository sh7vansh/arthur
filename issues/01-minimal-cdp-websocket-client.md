# 01 — Minimal CDP WebSocket Client & Session Dispatcher

**What to build:** An asynchronous, thread-safe Chrome DevTools Protocol (CDP) WebSocket client that connects to Chromium's remote debugging endpoint, correlates auto-incrementing numeric command IDs with awaiting futures, multiplexes target sessions (`sessionId`) across a single connection, and dispatches asynchronous CDP event streams to registered listeners.

**Blocked by:** None — can start immediately.

**Status:** closed

- [x] Connects to Chromium's DevTools WebSocket endpoint via lightweight async transport.
- [x] Provides generic `call(method, params, session_id)` interface resolving responses and propagating errors.
- [x] Correlates request IDs with awaiting futures for concurrent command execution.
- [x] Supports target session multiplexing via `Target.attachToTarget` (with `flatten: true`).
- [x] Dispatches incoming CDP domain events to registered event callbacks.
- [x] Gracefully detects connection drops and raises structured `BrowserUnavailableError`.
- [x] Unit & mock-server test suite passing.
