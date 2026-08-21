# Arthur

### Lightweight Headless Chromium Runtime & FastMCP Server for AI Agents

[![GitHub](https://img.shields.io/badge/GitHub-sh7vansh%2Farthur-blue?logo=github)](https://github.com/sh7vansh/arthur)
[![Docker Pulls](https://img.shields.io/docker/pulls/sh7vansh/arthur)](https://hub.docker.com/r/sh7vansh/arthur)
[![Multi-Arch](https://img.shields.io/badge/Architecture-amd64%20%7C%20arm64-success)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

**Arthur** is a containerized, self-contained headless Chromium browser runtime and Model Context Protocol (MCP) server designed specifically for autonomous AI agents.

It communicates directly with Chromium via **Chrome DevTools Protocol (CDP) WebSockets** without requiring browser extensions, virtual displays (X11/VNC), or heavy test drivers like Playwright or Selenium.

---

## ⚡ Key Features

- **🚀 Instant FastMCP Server**: Pre-configured Stateless Streamable HTTP transport on port `8000`.
- **🏷️ Semantic Ref-ID Snapshots**: Generates token-efficient, accessible DOM outlines with sequential element tags (`[#1]`, `[#2]`).
- **🧠 Persistent Python REPL**: Agent state, variables, imports, and helper functions persist across successive tool calls.
- **🛡️ Container-Hardened**: Built on Debian Slim, runs as an unprivileged non-root user (`arthur`), with `tini` PID 1 zombie process reaping.
- **🌐 Native Multi-Arch**: Pre-compiled and optimized for both `linux/amd64` (Intel/AMD) and `linux/arm64` (Apple Silicon, AWS Graviton).

---

## 🚀 Quickstart

### 1. Run via Docker CLI

```bash
docker run -d \
  --name arthur \
  -p 8000:8000 \
  --shm-size=1g \
  --restart unless-stopped \
  sh7vansh/arthur:latest
```

### 2. Run via Docker Compose

```yaml
services:
  arthur:
    image: sh7vansh/arthur:latest
    container_name: arthur-mcp
    restart: unless-stopped
    ports:
      - "8000:8000"
    shm_size: "1gb"
    environment:
      - PYTHONUNBUFFERED=1
```

```bash
docker compose up -d
```

---

## 🔌 Connecting Your AI Agent / MCP Client

Arthur exposes an MCP endpoint over Streamable HTTP at `/mcp`. Add Arthur to your MCP configuration (Claude Desktop, Cursor, Goose, Cline, etc.):

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

## 💻 How AI Agents Interact with Arthur

When an AI agent invokes the `execute_python` tool, Arthur provides a synchronous `browser` instance with full procedural control:

```python
# 1. Navigation & DOM Inspection
browser.navigate("https://example.com")
print(browser.snapshot())  # Prints compact Ref-ID DOM outline

# 2. Targeted Interactions using Ref-IDs or Selectors
browser.click(1)                                    # Click element [#1]
browser.type(2, "search query", press_enter=True)   # Type into input [#2]
browser.select(3, "Option Value")                   # Choose dropdown option
browser.scroll(x=0, y=500)                          # Scroll down

# 3. Dynamic Synchronization
browser.wait_for(1, state="visible", timeout=10.0)
browser.wait_for_url(r"^https://example\.com/dashboard")

# 4. Multi-Tab Management & Evaluation
eval_result = browser.eval_js("window.innerWidth")
new_tab = browser.new_tab("https://news.ycombinator.com")
```

---

## ⚙️ Environment Variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `ARTHUR_NO_SANDBOX` | `1` | Disables Chromium SUID sandbox inside container environments. |
| `ARTHUR_CHROME_ARGS`| *None* | Optional additional CLI flags to forward to Chromium. |
| `PYTHONUNBUFFERED` | `1` | Forces real-time logging output without buffering. |

---

## 🔗 Links & Source Code

- **GitHub Repository**: [sh7vansh/arthur](https://github.com/sh7vansh/arthur)
- **PyPI Package**: [`arthur-runtime`](https://pypi.org/project/arthur-runtime/)
- **License**: [MIT](https://github.com/sh7vansh/arthur/blob/main/LICENSE)
