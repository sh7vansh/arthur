# 03 — In-Page Semantic Snapshot Generator & Ref-ID Registry

**What to build:** In-page DOM engine evaluation via CDP `Runtime.evaluate` that generates compact, token-efficient semantic text snapshots with interactive roles, accessible names, Ref-IDs (`[#1]`, `[#2]`), element bounding coordinates, and historical state for stale reference detection.

**Blocked by:** 01 (Minimal CDP WebSocket Client), 02 (Headless Chromium Process Lifecycle).

**Status:** closed

- [x] Injects and evaluates DOM engine in target page context via CDP `Runtime.evaluate`.
- [x] Resolves accessible roles (`button`, `link`, `textbox`, `combobox`, `checkbox`, `heading`, etc.) and accessible names.
- [x] Assigns sequential Ref-IDs (`[#1]`, `[#2]`) and stores element references & bounding rect coordinates in `window.__AG_REGISTRY__`.
- [x] Returns compact semantic text snapshot representation.
- [x] Detects stale Ref-IDs upon query and returns structured `ElementNotFoundError` with fuzzy match suggestions.
- [x] Integration tests passing against local HTML test fixtures.
