# 02 — Headless Chromium Process Lifecycle & Ephemeral Sandbox

**What to build:** Cross-platform Chromium binary discovery, ephemeral `--user-data-dir` sandboxing, launching modern `--headless=new` with ephemeral port allocation, DevToolsActivePort/WebSocket discovery, and guaranteed zero-leak process termination on exit or POSIX signals.

**Blocked by:** None — can start immediately.

**Status:** closed

- [x] Discovers local Chromium binary across `CHROMIUM_PATH`, system paths (`chromium`, `google-chrome`, etc.), and sandbox fallbacks.
- [x] Creates isolated temporary user data directory per session.
- [x] Launches Chromium subprocess with `--headless=new`, `--remote-debugging-port=0`, `--no-first-run`, and minimal memory flags.
- [x] Reads assigned DevTools port / WebSocket URL reliably from `DevToolsActivePort`.
- [x] Registers `atexit` and signal handlers (`SIGINT`, `SIGTERM`) to kill subprocess tree and purge temporary user directory.
- [x] Unit & lifecycle integration tests passing.
