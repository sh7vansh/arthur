"""CLI entrypoints for Arthur (mcp server and repl runner)."""

import argparse
import sys
from typing import List, Optional

from arthur.repl import PythonReplSession
from arthur.server import run_mcp_server


def build_parser() -> argparse.ArgumentParser:
    """Build Arthur command line argument parser."""
    parser = argparse.ArgumentParser(
        prog="arthur",
        description="Arthur — Lightweight Headless Chromium Runtime for Gloria and AI Agents",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # MCP command
    mcp_parser = subparsers.add_parser("mcp", help="Run Arthur FastMCP server")
    mcp_parser.add_argument(
        "--transport",
        type=str,
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
        help="MCP transport protocol (default: stdio)",
    )

    # REPL command
    repl_parser = subparsers.add_parser("repl", help="Run Python REPL session")
    repl_parser.add_argument(
        "-c", "--code", type=str, help="Python code string to execute"
    )
    repl_parser.add_argument(
        "file", nargs="?", type=str, help="Python script file to execute"
    )

    return parser


def run_repl(code: Optional[str] = None, file_path: Optional[str] = None) -> None:
    """Run code in persistent REPL session or interactive loop."""
    session = PythonReplSession()

    if code:
        out = session.execute(code)
        print(out)
        return

    if file_path:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            file_code = f.read()
        out = session.execute(file_code)
        print(out)
        return

    if not sys.stdin.isatty():
        input_code = sys.stdin.read()
        if input_code.strip():
            out = session.execute(input_code)
            print(out)
        return

    # Interactive loop
    print("Arthur Interactive REPL (Type 'exit()' or press Ctrl+D to exit)")
    print("Global 'browser' instance is available.")
    while True:
        try:
            line = input("arthur> ")
            if line.strip() in ("exit()", "quit()"):
                break
            if not line.strip():
                continue
            out = session.execute(line)
            print(out)
        except (EOFError, KeyboardInterrupt):
            print("\nExiting Arthur REPL.")
            break


def main(argv: Optional[List[str]] = None) -> None:
    """Main CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "mcp":
        run_mcp_server(transport=args.transport)
    elif args.command == "repl":
        run_repl(code=args.code, file_path=args.file)
    else:
        # Default behavior: if code is piped in, run repl; otherwise show help
        if not sys.stdin.isatty():
            run_repl()
        else:
            parser.print_help()


if __name__ == "__main__":
    main()
