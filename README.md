<div align="center">

# Arthur

### Lightweight Headless Chromium Runtime & MCP Server for AI Agents

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP Standard](https://img.shields.io/badge/MCP-Standard%20Compatible-green.svg)](https://modelcontextprotocol.io/)
[![Built with uv](https://img.shields.io/badge/built%20with-uv-purple.svg)](https://github.com/astral-sh/uv)

<p align="center">
  Direct CDP WebSockets • Semantic Ref-ID Snapshots • Persistent Python REPL • FastMCP Server
</p>

</div>

---

## Overview

**Arthur** is a standalone, lightweight headless Chromium runtime engineered specifically for AI agents (such as Gloria, Claude, and autonomous coding assistants).

Traditional browser automation tools either carry heavy driver overhead (Playwright/Puppeteer) or require brittle browser extension bridges with native messaging hosts and local desktop displays. Arthur eliminates all extension machinery by connecting directly to Chromium via **Chrome DevTools Protocol (CDP) WebSockets**, managing an ephemeral sandboxed Chromium process, retaining persistent Python REPL state across executions, and generating concise, token-efficient semantic DOM snapshots with assigned **Ref-IDs** (`[#1]`, `[#2]`).

```text
+------------------------+
|  AI Agent / MCP Client |
+-----------+------------+
            |  execute_python(code)
            v
+------------------------+
|   FastMCP stdio/HTTP   |
+-----------+------------+
            |
            v
+--------------------------------------------------------+
|                  PythonReplSession                     |
|  * AST Statement/Expression Execution (exec/eval)      |
|  * In-Memory Variable & Function Persistence           |
|  * Token Budgeting & Telemetry Defanging               |
|  * Single-Turn Diagnostic Auto-Snapshots on Errors     |
+---------------------------+----------------------------+
                            |
                            v
+--------------------------------------------------------+
|            Synchronous Browser & Tab API               |
|  * browser.navigate()  * browser.snapshot()            |
|  * browser.click(ref)  * browser.type(ref, text)       |
|  * browser.wait_for()  * browser.new_tab()             |
+---------------------------+----------------------------+
                            |  Thread-Safe Bridge
                            v
+--------------------------------------------------------+
|                 _AsyncCDPRunner (Daemon)               |
|  * CDPClient (Direct WebSocket Transport)              |
|  * In-Page Semantic DOM Engine (Accessible Ref-IDs)    |
|  * Synthetic Input Simulator (Coordinate-Accurate)     |
+---------------------------+----------------------------+
                            |  ws://127.0.0.1:<port>/devtools/browser/...
                            v
+--------------------------------------------------------+
|        Headless Chromium Process (--headless=new)      |
|  * Ephemeral Sandbox (--user-data-dir)                 |
|  * Zero X11/VNC, Zero Extension, Zero Native Hosts     |
+--------------------------------------------------------+
```

---

## Why Arthur?

| Feature | Arthur | Playwright / Puppeteer | Extension-Based Bridges |
| :--- | :--- | :--- | :--- |
| **Transport** | **Direct CDP WebSockets** | CDP / Automation Driver | Extension IPC / Native Messaging |
| **Agent Interface** | **Persistent Python REPL + MCP** | Per-action API / Custom | Custom Tool Schema / Extension |
| **DOM Inspection** | **Compact Ref-ID Semantic Trees** | Full raw HTML or accessibility dumps | DOM injection scripts |
| **Self-Healing** | **Auto Diagnostic Snapshot on Error** | Manual retry logic | Requires extra agent turns |
| **Process Footprint** | **Minimal (~25MB Python + Chromium)** | Heavy node/driver dependencies | User desktop Chrome required |
| **Headless / Containers** | **Native `--headless=new` (Zero GUI)** | Supported | Difficult (requires virtual displays) |
| **Token Budgeting** | **Built-in truncation & defanging** | None | Ad-hoc |

---

## Quickstart

### 1. Instant Zero-Clone Execution via `uvx`

No repository cloning or manual environment management is required:

```bash
# Run MCP Server (stdio transport)
uvx --from git+https://github.com/sh7vansh/arthur arthur mcp

# Run Interactive Terminal REPL
uvx --from git+https://github.com/sh7vansh/arthur arthur repl

# Run One-Shot Command
uvx --from git+https://github.com/sh7vansh/arthur arthur repl -c "browser.navigate('https://example.com'); print(browser.snapshot())"
```

---

### 2. Connect to MCP Clients (Claude Desktop, Cursor, etc.)

Add Arthur to your MCP settings configuration (e.g. `claude_desktop_config.json`):

#### Using `uvx` (Zero-Clone):
```json
{
  "mcpServers": {
    "arthur": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/sh7vansh/arthur",
        "arthur",
        "mcp"
      ]
    }
  }
}
```

#### Using Local Repository:
```json
{
  "mcpServers": {
    "arthur": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/Arthur",
        "run",
        "arthur",
        "mcp"
      ]
    }
  }
}
```

---

## Local Installation

### Prerequisites
- **Python 3.10+**
- **[uv](https://astral.sh/uv/)** package manager
- **Google Chrome** or **Chromium** (Arthur automatically discovers existing local installations)

```bash
# Clone the repository
git clone https://github.com/sh7vansh/arthur.git
cd arthur

# Install dependencies in an isolated virtual environment
uv sync --all-extras
```

---

## Key Capabilities

### 1. In-Page Semantic DOM Engine & Ref-IDs
Arthur evaluates an in-page accessibility parser that extracts the visible DOM, calculates WAI-ARIA accessible roles/names, and generates a compact, token-efficient semantic tree with assigned numeric **Ref-IDs**:

```text
PAGE: "Example Domain" (https://example.com)
  - heading[level=1] "Example Domain"
  - paragraph: "This domain is for use in illustrative examples in documents."
  - link [#1] "More information..." (href="https://www.iana.org/domains/example")
```

Agents target elements directly using Ref-IDs (`1`, `"[#1]"`), avoiding brittle CSS or XPath selectors.

### 2. Coordinate-Accurate Synthetic Input
Translates high-level agent actions into coordinate-precise CDP events:
- **`browser.click(target)`**: Resolves bounding center coordinates and dispatches `Input.dispatchMouseEvent`.
- **`browser.type(target, text, press_enter=True)`**: Focuses the element, clears existing input, inserts text, and simulates real key events.
- **`browser.select(target, value)`**: Handles `<select>` dropdown menus.
- **`browser.hover(target)`** & **`browser.scroll(x, y)`**: Simulates mouse hover and viewport/element scrolling.

### 3. Persistent Stateful Python REPL
The `execute_python` tool retains variables, functions, and imports across successive agent turns:
```python
# Turn 1: Define helper and fetch data
import json
browser.navigate("https://news.ycombinator.com")
titles = browser.eval_js("[...document.querySelectorAll('.titleline > a')].map(a => a.innerText)")

# Turn 2: State persists across tool calls
print(f"Captured {len(titles)} articles:")
print(titles[:3])
```

### 4. Single-Turn Self-Healing & Diagnostics
- **Diagnostic Auto-Snapshot**: When an unhandled exception occurs, Arthur automatically captures the latest DOM snapshot (`[diagnostic_auto_snapshot]`) and appends it to the error payload, allowing the agent to self-heal in a single turn without extra roundtrips.
- **Fuzzy Suggestions**: If an element reference becomes stale after a dynamic DOM mutation, Arthur provides fuzzy match suggestions from snapshot history.

### 5. Output Budgeting & Telemetry Defanging
All execution output passes through a strict budgeting pipeline:
- Prevents context window explosion by truncating output exceeding token/character limits.
- Automatically defangs tracking image beacons (`![beacon](url)` -> `[IMAGE_BLOCKED]`) and unsafe active HTML tags.

---

## Python API Reference

The synchronous `browser` instance is pre-injected into the REPL environment:

```python
# --- Navigation & Inspection ---
browser.navigate("https://example.com", timeout=30.0)
snapshot_text = browser.snapshot()
current_url = browser.url
page_title = browser.title

# --- Synthetic Interactions (Ref-ID, String Ref, or CSS Selector) ---
browser.click(1)                          # Click Ref-ID #1
browser.click("[#1]")                     # String Ref-ID format
browser.click("button.submit-btn")        # CSS selector fallback
browser.type(2, "search query", press_enter=True)
browser.select(3, "Option Value")
browser.hover(1)
browser.scroll(x=0, y=500)

# --- Synchronization & Waiting ---
browser.wait_for(1, state="visible", timeout=10.0)
browser.wait_for_url(r"^https://example\.com/dashboard", timeout=15.0)

# --- Evaluation & Captures ---
result = browser.eval_js("window.innerWidth")
png_bytes = browser.screenshot()
text_content = browser.get_text(1)
attr_value = browser.get_attribute(1, "data-custom")

# --- Multi-Tab Management ---
new_tab = browser.new_tab("https://google.com")
tabs = browser.tabs                       # List of open Tab instances
active = browser.active_tab
tab_2 = browser.get_tab(2)
browser.close_tab(2)
```

---

## Remote Deployment & Transports

Arthur supports multiple network transports for remote, cloud, and containerized deployments.

### 1. Stateless Streamable HTTP (Recommended for Remote / Cloud)

For remote servers, VMs, Docker containers, Cloudflare Tunnels, and reverse proxies, **Stateless Streamable HTTP is the most reliable transport**.

#### Why Stateless HTTP is Superior for Remote Setups:
- **Resilient to Network Drops**: Unlike stateful SSE connections that drop or report "Session Expired" when a network glitch occurs between agent turns, stateless HTTP treats each tool execution as an independent request.
- **Proxy & Tunnel Friendly**: Works cleanly behind Nginx, Cloudflare Tunnels, AWS ALBs, and Ngrok without hitting idle connection timeouts (e.g. 60s stream timeouts).
- **Preserved Backend State**: While the HTTP wire transport is stateless, Arthur's in-memory Python REPL session, Chromium browser instance, cookies, and open tabs remain fully persistent on the server.

#### Starting Stateless Streamable HTTP:
```bash
# Start server on remote host (listening on 0.0.0.0:8000)
uv run arthur mcp --transport streamable-http --stateless --host 0.0.0.0 --port 8000
```

#### Client Configuration:
```json
{
  "mcpServers": {
    "arthur": {
      "url": "http://remote-server-ip:8000/mcp"
    }
  }
}
```

---

### 2. SSH Stdio Tunneling (Zero-Port Remote Access)

Run Arthur securely over SSH without opening public firewall ports:

```json
{
  "mcpServers": {
    "remote-arthur": {
      "command": "ssh",
      "args": [
        "user@remote-host",
        "uvx --from git+https://github.com/sh7vansh/arthur arthur mcp"
      ]
    }
  }
}
```

---

### 3. Server-Sent Events (`/sse`)

For legacy MCP clients requiring standard SSE endpoints:

```bash
uv run arthur mcp --transport sse --host 0.0.0.0 --port 8000
```
- **Endpoint**: `http://<host>:8000/sse`

---

## Testing & Development

Run the test suite to validate CDP WebSocket transport, headless Chromium lifecycle, in-page DOM operations, and persistent REPL execution:

```bash
# Run pytest test suite
uv run pytest

# Run type checker
uv run mypy src
```

---

## License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.
