# 07 — FastMCP Server & stdio CLI

**What to build:** A FastMCP server exposing the `execute_python(code)` tool over stdio, CLI entrypoints (`arthur mcp` and `arthur repl`), and `pyproject.toml` configuration with minimal dependencies (`mcp`, `websockets`), ready for Gloria to use out of the box.

**Blocked by:** 06 (Persistent REPL Engine).

**Status:** closed

- [x] Implements FastMCP server exposing `execute_python(code)` matching Gloria's tool schema and instructions.
- [x] Provides CLI command `arthur mcp` to run the stdio MCP server.
- [x] Provides CLI command `arthur repl` to run interactive or one-shot script execution.
- [x] Configures `pyproject.toml` with `uv` support and minimal dependencies (`mcp`, `websockets`).
- [x] End-to-end MCP client simulation test passing.
