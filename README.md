# Arthur ⚡

Lightweight Headless Chromium Runtime for Gloria and AI Agents.

Arthur is a standalone, lightweight headless Chromium runtime that connects directly to Chromium via Chrome DevTools Protocol (CDP) WebSockets, manages an ephemeral Chromium subprocess, retains persistent Python REPL state across executions, generates concise semantic Ref-ID DOM snapshots, and exposes a drop-in MCP `execute_python` tool interface.

## Features

- **Direct CDP WebSocket Transport**: Zero extension, zero native messaging host, zero X11/VNC dependency.
- **Subprocess & Sandbox Lifecycle**: Ephemeral `--user-data-dir`, modern `--headless=new` launch with `--remote-debugging-port=0`, and leak-proof cleanup on exit or signals.
- **In-Page Semantic DOM Engine**: Compact, token-efficient semantic trees with accessible roles, accessible names, Ref-IDs (`[#1]`, `[#2]`), and bounding rects.
- **CDP Synthetic Input Simulation**: Coordinate-accurate clicks, keystrokes with `press_enter`, dropdown select, hover, and scroll.
- **Synchronous Python API**: Ergonomic `browser.*` and `tab.*` facade backed by a background daemon CDP loop.
- **Persistent Python REPL**: AST statement/expression execution retaining state across calls with diagnostic auto-snapshots on exceptions and token budget caps.
- **FastMCP stdio Server & CLI**: Ready-to-use MCP server exposing `execute_python(code)` for Gloria and agent orchestration.

## Installation

```bash
uv sync --all-extras
```

## Usage

### Run MCP Server
```bash
uv run arthur mcp
```

### Run Interactive / One-Shot REPL
```bash
uv run arthur repl
uv run arthur repl -c "browser.navigate('https://example.com'); print(browser.snapshot())"
```
