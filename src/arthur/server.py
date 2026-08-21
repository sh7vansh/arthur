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
        description=(
            "Execute Python code in a persistent browser automation session. "
            "State, variables, imports, and functions persist across calls. "
            "The synchronous `browser` instance is pre-injected to control browser tabs, "
            "inspect DOM snapshots, and perform page actions."
        ),
    )
    def _execute_python(code: str) -> str:
        return repl_session.execute(code)

    return server


def run_mcp_server(transport: str = "stdio") -> None:
    """Run FastMCP server."""
    server = create_mcp_server()
    server.run(transport=transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    run_mcp_server()
