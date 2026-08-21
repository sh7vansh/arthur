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

## What is Arthur?

**Arthur** is a single-command headless browser runtime and Model Context Protocol (MCP) server for AI agents.

It connects directly to Chromium via **Chrome DevTools Protocol (CDP) WebSockets** without requiring browser extensions, virtual displays (X11/VNC), or heavy automation drivers. One command launches the MCP server, boots an isolated headless Chromium process, and provides your AI agent with full procedural browser control.

```text
Agent / MCP Client
       │
       ▼  execute_python(code)
FastMCP Server (stdio / Streamable HTTP)
       │
       ▼
Python REPL Session (stateful memory & auto-snapshots)
       │
       ▼
Arthur Browser API (synchronous facade)
       │
       ▼  CDP WebSockets
Headless Chromium (--headless=new)
```

---

## Quickstart

You don't need to clone the repository or install dependencies manually. Arthur runs instantly via `uvx`.

### 1. Local Desktop (Claude Desktop, Cursor, Goose)

Add Arthur to your MCP settings file (e.g. `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "arthur": {
      "command": "uvx",
      "args": ["arthur-runtime", "mcp"]
    }
  }
}
```

*When your AI agent calls the browser, Arthur automatically discovers local Chrome/Chromium, starts the headless browser, executes actions, and cleans up when finished.*

---

### 2. Docker Container (Self-Contained Streamable HTTP)

Run Arthur in a lightweight, self-contained Debian Slim container with headless Chromium, `tini` PID 1 process management, and native multi-arch support (`amd64` / `arm64`):

#### Run via Docker:
```bash
docker run -d \
  --name arthur \
  -p 8000:8000 \
  --shm-size=1g \
  --restart unless-stopped \
  sh7vansh/arthur:latest
```

#### Or Run via Docker Compose:
```bash
docker compose up -d
```

#### Connect Your MCP Client:
```json
{
  "mcpServers": {
    "arthur": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

---

### 3. Remote Server / Cloud (Direct Python via `uvx`)

To run Arthur on a remote VM, VPS, or cloud server without Docker:

#### Start the Server:
```bash
uvx arthur-runtime mcp --transport streamable-http --stateless --host 0.0.0.0 --port 8000
```

#### Connect Your MCP Client:
```json
{
  "mcpServers": {
    "arthur": {
      "url": "http://YOUR_SERVER_IP:8000/mcp"
    }
  }
}
```

*Stateless Streamable HTTP is resilient to network drops and works seamlessly behind Nginx, Cloudflare Tunnels, and AWS ALBs while keeping browser tabs and Python variables in server memory.*

---

### 4. Interactive Terminal Shell (For Testing)

Test the browser directly from your terminal:

```bash
uvx arthur-runtime repl
```
```text
Arthur Interactive REPL (Type 'exit()' or press Ctrl+D to exit)
Global 'browser' instance is available.
arthur> browser.navigate('https://example.com')
arthur> print(browser.snapshot())
arthur> browser.click(1)
```

---

## How It Works

Arthur handles the entire browser lifecycle in a single self-contained process:

1. **Automatic Discovery**: Locates installed Chrome, Chromium, Brave, or Edge on Linux, macOS, or Windows.
2. **Ephemeral Sandbox**: Boots Chromium with `--headless=new` and an isolated temporary user-data directory.
3. **CDP WebSockets**: Communicates directly over local WebSockets for low-latency element targeting and input simulation.
4. **Automatic Teardown**: Gracefully shuts down the Chromium subprocess and purges temporary files when the session ends.

---

## Python API Reference

When your AI agent uses the `execute_python` tool, the synchronous `browser` instance is pre-injected:

```python
# Navigation & Page State
browser.navigate("https://example.com", timeout=30.0)
print(browser.snapshot())                # Semantic Ref-ID outline ([#1], [#2])
print(browser.url, browser.title)

# Interactions (Ref-ID, String Ref, or CSS Selector)
browser.click(1)                         # Click Ref-ID #1
browser.click("button.submit-btn")       # CSS selector fallback
browser.type(2, "search query", press_enter=True)
browser.select(3, "Option Value")
browser.hover(1)
browser.scroll(x=0, y=500)

# Waiting & Synchronization
browser.wait_for(1, state="visible", timeout=10.0)
browser.wait_for_url(r"^https://example\.com/dashboard", timeout=15.0)

# Page Evaluation & Inspection
result = browser.eval_js("window.innerWidth")
png_bytes = browser.screenshot()
text = browser.get_text(1)
attr = browser.get_attribute(1, "data-custom")

# Fast Native Media Control (Zero-DOM)
state = browser.media.status()           # HTML5 media state & player metadata
browser.media.toggle()                   # Toggle play/pause
browser.media.play()                     # Resume playback
browser.media.pause()                    # Pause playback
browser.media.seek(15.0)                 # Seek relative seconds (+15s / -10s)
browser.media.set_volume(0.8)            # Set volume level (0.0 to 1.0)

# Multi-Tab Control & Help
new_tab = browser.new_tab("https://google.com")
all_tabs = browser.tabs
active = browser.active_tab
browser.close_tab(2)
print(browser.help())                    # Built-in formatted SDK quick reference
```

---

## Key Features

- **Semantic Ref-ID Snapshots**: Generates compact, token-efficient accessible DOM trees with assigned numbers (`[#1]`, `[#2]`), avoiding brittle XPath or long CSS selectors.
- **Fast Media Controller (`browser.media`)**: Zero-DOM media playback manipulation that penetrates open Shadow DOM roots without expensive snapshot recalculation.
- **Persistent Python REPL**: State, variables, imports, and custom functions persist across agent tool calls.
- **Single-Turn Self-Healing**: Automatically attaches a diagnostic DOM snapshot (`[diagnostic_auto_snapshot]`) and fuzzy suggestions whenever an error occurs, allowing agents to self-heal in a single turn.
- **MCP Resources & Prompts**: Built-in MCP resources (`arthur://docs/api`, `arthur://docs/workflow`) and structured prompts (`browser_automation`, `media_control`) for intelligent agent onboarding.
- **Token Budgeting & Defanging**: Truncates large outputs to prevent context window explosion and sanitizes tracking image beacons (`[IMAGE_BLOCKED]`).

---

## Local Development

If you want to contribute or build from source:

```bash
# Clone and install dependencies
git clone https://github.com/sh7vansh/arthur.git
cd arthur
uv sync --all-extras

# Run tests
uv run pytest

# Run type checker
uv run mypy src
```

---

## License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.
