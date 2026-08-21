"""FastMCP Server exposing execute_python tool for Arthur."""

import logging
from typing import Optional

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    try:
        from mcp.server import MCPServer as FastMCP
    except ImportError:
        from mcp.server.mcpserver import MCPServer as FastMCP

from arthur.repl import PythonReplSession

logger = logging.getLogger("arthur.server")

API_DOCS = r"""# Arthur - Headless Chromium Runtime API Reference

The synchronous `browser` module is pre-injected in all REPL executions.

## 1. Page Orientation & Snapshots
- `print(browser.snapshot())`
  Generates a Semantic DOM outline with integer Ref-IDs (`[#1]`, `[#2]`, etc.).
  Always run this first to discover interactive elements on the page.
- `print(browser.url, browser.title)` -> Current page location and title

## 2. Element Interactions
All interaction methods accept polymorphic target references: integer Ref-IDs (`14`), string Ref-IDs (`"[#14]"` or `"#14"`), or CSS selectors (`"button.submit"`):
- `browser.click(14)` or `browser.click("[#14]")`
- `browser.type(2, "search query", clear=True, press_enter=True)`
- `browser.select(5, "option_value")`
- `browser.hover(8)`
- `browser.scroll(x=0, y=500)` or `browser.scroll(target="[#container]")`

## 3. Tabs & Navigation
- `browser.tabs` -> List[Tab] handles for all open tabs
- `browser.active_tab` -> Current active Tab handle
- `browser.get_tab(tab_id)` / `browser.tab(tab_id)` -> Scoped Tab handle by ID
- `browser.navigate("https://example.com", timeout=30.0)` -> Navigates active tab
- `browser.new_tab("https://example.com")` -> Opens a new tab
- `browser.close_tab(tab_id)` -> Safely closes the specified tab

## 4. Extraction & JavaScript Execution
- `text = browser.get_text(3)` -> Extracted inner text content
- `attr = browser.get_attribute(3, "href")` -> Value of element attribute
- `result = browser.eval_js("document.title")` -> Evaluates JS in page context
- `png_bytes = browser.screenshot()` -> Captures raw PNG screenshot bytes

## 5. Synchronization & Waiting
- `browser.wait_for(10, state="visible", timeout=10.0)` -> Waits for element ('visible', 'hidden', 'attached')
- `browser.wait_for_url(r"github\.com/settings", timeout=15.0)` -> Waits for regex URL match

## 6. Fast Native Media Control (Zero-DOM)
Direct control over HTML5 video/audio and MediaSession:
- `browser.media.status()` -> Returns dict with found, paused, title, artist, duration, currentTime, etc.
- `browser.media.play()` -> Resume playback
- `browser.media.pause()` -> Pause playback
- `browser.media.toggle()` -> Toggle play/pause
- `browser.media.seek(15.0)` -> Relative seek (+15s or -10s)
- `browser.media.set_volume(0.8)` -> Set volume (0.0 to 1.0)
"""

WORKFLOW_GUIDE = r"""# Arthur Automation Workflow & Best Practices

## Recommended Multi-Step Pattern
Write complete Python subroutines to batch actions into a single round-trip:

```python
# 1. Orientation
snapshot = browser.snapshot()
print(snapshot)

# 2. Targeted Actions
browser.type("[#search_input]", "Python MCP", press_enter=True)
browser.wait_for("[#search_results]", timeout=5.0)

# 3. Data Extraction
titles = browser.eval_js('''
    Array.from(document.querySelectorAll('.result-title')).map(el => el.innerText)
''')
print("Found titles:", titles)
```

## Resilience & Self-Healing
1. State Persistence: Variables, imports, and custom functions persist across agent tool calls.
2. Single-Turn Diagnostics: If an element is not found, Arthur automatically attaches a `[diagnostic_auto_snapshot]` and fuzzy match suggestions to the error payload.
3. Defanging: Tracking beacons and active script injection tags are sanitized to protect token limits.
"""

TOOL_DESCRIPTION = r"""Execute Python code to control headless Chromium via the pre-injected synchronous `browser` instance.
Variables, imports, and state persist across calls.

CORE API CHEATSHEET:
1. Orientation:
   print(browser.snapshot())          # Get DOM outline with [#N] Ref-IDs
   print(browser.url, browser.title)  # Current URL & document title
2. Interactions (accepts Ref-ID '[#14]', int 14, or CSS selector):
   browser.click(14)                  # Click element
   browser.type(2, "query", clear=True, press_enter=True) # Type text
   browser.select(5, "value")         # Choose dropdown option
   browser.hover(8)                   # Hover over element
   browser.scroll(x=0, y=500)         # Scroll page or container
3. Tabs & Navigation:
   browser.navigate("https://...")    # Navigate current tab
   browser.new_tab("https://...")     # Open new tab
   tabs = browser.tabs                # List all open tabs
   browser.active_tab                 # Active Tab handle
   tab = browser.get_tab(id)          # Scoped tab handle
   browser.close_tab(id)              # Close tab
4. Extraction & JavaScript:
   text = browser.get_text(3)         # Extract text
   attr = browser.get_attribute(3, "href") # Get attribute
   res = browser.eval_js("document.title") # Execute JS in page context
   png_bytes = browser.screenshot()   # Capture PNG screenshot
5. Synchronization:
   browser.wait_for(10, timeout=10.0, state="visible")
   browser.wait_for_url(r"github\.com/pulls", timeout=15.0)
6. Native Media Fast-Paths (Zero-DOM):
   browser.media.status()             # State of HTML5 video/audio
   browser.media.toggle()             # Toggle play/pause
   browser.media.play() / pause()
   browser.media.seek(15.0)           # Relative seek in seconds
   browser.media.set_volume(0.8)      # Set volume (0.0 - 1.0)
7. Diagnostics & Help:
   browser.help()                     # Formatted SDK quick reference
"""

DEFAULT_INSTRUCTIONS = (
    "You have full procedural control over a lightweight headless Chromium browser via the 'execute_python' tool.\n\n"
    "ENVIRONMENT CAPABILITIES:\n"
    "- Persistent Python REPL: Variables, imports, helper functions, and state persist across successive calls.\n"
    "- Injected SDK: The synchronous `browser` (and `chrome`) instance is pre-injected and ready to use.\n\n"
    "RECOMMENDED WORKFLOW:\n"
    "1. Orientation: Always inspect the page with `print(browser.snapshot())` to obtain the Semantic DOM outline and element Ref-IDs (`[#1]`, `[#2]`).\n"
    "2. Targeted Actions: Interact polymorphically using Ref-IDs or selectors, e.g. `browser.click(14)`, `browser.type('[#2]', 'search query', press_enter=True)`.\n"
    "3. Multi-Step Subroutines: Write complete loops and workflows (form fills, pagination, data extraction) in a single script for high throughput.\n"
    "4. Synchronization: Use `browser.wait_for('[#5]')` and `browser.wait_for_url(r'...')` to handle dynamic page changes.\n"
    "5. Self-Healing: If an element is not found, inspect the automatic `[diagnostic_auto_snapshot]` or fuzzy match suggestions in the error payload."
)

_GLOBAL_SESSION = PythonReplSession()


def execute_python(code: str) -> str:
    """Execute Python code in a persistent browser automation session.

    Args:
        code: Python source code string to execute.

    Returns:
        Formatted tagged output with [stdout], [result], or [error] diagnostics.
    """
    return _GLOBAL_SESSION.execute(code)


def create_mcp_server(
    session: Optional[PythonReplSession] = None,
    name: str = "arthur",
    instructions: str = DEFAULT_INSTRUCTIONS,
) -> FastMCP:
    """Create and configure FastMCP server instance."""
    repl_session = session or _GLOBAL_SESSION

    server = FastMCP(
        name=name,
        instructions=instructions,
    )

    @server.tool(
        name="execute_python",
        description=TOOL_DESCRIPTION,
    )
    def _execute_python(code: str) -> str:
        """Execute Python code in a persistent browser automation session."""
        return repl_session.execute(code)

    # MCP Resources for clients that inspect documentation
    try:
        @server.resource("arthur://docs/api")
        def get_api_docs() -> str:
            """Complete Arthur Python SDK API Reference."""
            return API_DOCS

        @server.resource("arthur://docs/workflow")
        def get_workflow_guide() -> str:
            """Arthur Automation Workflow Guide, Patterns, and Best Practices."""
            return WORKFLOW_GUIDE
    except Exception:
        pass

    # MCP Prompts for interactive client workflows
    try:
        @server.prompt()
        def browser_automation(goal: str = "") -> str:
            """Guide the model through executing a complete browser automation task."""
            goal_text = f"Goal: {goal}\n\n" if goal else ""
            return (
                f"You are controlling a headless Chromium browser using Arthur.\n"
                f"{goal_text}"
                f"Standard Execution Flow:\n"
                f"1. Run `print(browser.snapshot())` via `execute_python` to inspect the page DOM and Ref-IDs.\n"
                f"2. Perform the required actions (`browser.click(N)`, `browser.type(N, '...')`, etc.).\n"
                f"3. Verify completion and report extracted data.\n\n"
                f"API Cheatsheet:\n"
                f"{API_DOCS}"
            )

        @server.prompt()
        def media_control(action: str = "status") -> str:
            """Quick prompt to inspect or control browser media playback."""
            return (
                f"Control active browser media playback using `execute_python`.\n"
                f"Requested Action: {action}\n\n"
                f"Examples:\n"
                f"- Inspect: `print(browser.media.status())`\n"
                f"- Toggle: `browser.media.toggle()`\n"
                f"- Play/Pause: `browser.media.play()` or `browser.media.pause()`\n"
                f"- Seek: `browser.media.seek(15.0)`\n"
                f"- Volume: `browser.media.set_volume(0.8)`\n"
            )
    except Exception:
        pass

    return server


def run_mcp_server(
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8000,
    stateless: bool = False,
) -> None:
    """Run FastMCP server."""
    server = create_mcp_server()
    if transport == "streamable-http":
        server.run(
            transport=transport,
            host=host,
            port=port,
            stateless_http=stateless,
        )  # type: ignore[arg-type]
    elif transport == "sse":
        server.run(
            transport=transport,
            host=host,
            port=port,
        )  # type: ignore[arg-type]
    else:
        server.run(transport=transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    run_mcp_server()


