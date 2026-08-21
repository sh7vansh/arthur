"""Tests for arthur.server & arthur.cli — FastMCP Server & CLI Entrypoints."""

import pytest
from arthur.cli import build_parser, main
from arthur.repl import PythonReplSession
from arthur.server import create_mcp_server


def test_create_mcp_server():
    session = PythonReplSession()
    server = create_mcp_server(session)
    assert server is not None
    assert server.name == "arthur"


@pytest.mark.asyncio
async def test_mcp_execute_python_tool():
    session = PythonReplSession()
    server = create_mcp_server(session)

    # In FastMCP, tools can be called directly or via server.get_tool
    tool_fn = None
    # Check server tools
    if hasattr(server, "_tool_manager"):
        # MCP 1.x / 2.x
        tool = server._tool_manager.get_tool("execute_python")
        if tool:
            tool_fn = tool.fn

    if tool_fn is None:
        # Fallback to direct execute_python tool call
        from arthur.server import execute_python
        res = execute_python("x = 100\nx + 23")
    else:
        res = tool_fn("x = 100\nx + 23")

    assert "[result]\n123" in res


def test_cli_parser():
    parser = build_parser()

    args_mcp = parser.parse_args(["mcp"])
    assert args_mcp.command == "mcp"

    args_repl_c = parser.parse_args(["repl", "-c", "print('hi')"])
    assert args_repl_c.command == "repl"
    assert args_repl_c.code == "print('hi')"

    args_repl_file = parser.parse_args(["repl", "test.py"])
    assert args_repl_file.command == "repl"
    assert args_repl_file.file == "test.py"
