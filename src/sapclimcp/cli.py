"""CLI entry point for the sapcli MCP server."""

import argparse
import os
import sys

from sapclimcp.config import ConfigError
from sapclimcp.server import create_mcp_server


def parse_args(argv: list[str] | None = None):
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="MCP server exposing sapcli commands as tools"
    )

    parser.add_argument(
        "--experimental",
        action="store_true",
        help="Expose all meaningful sapcli commands as tools (not just verified ones)"
    )

    parser.add_argument(
        "--config",
        default=None,
        help="Path to JSON config file with system definitions "
             "(env: SAPCLI_MCP_CONFIG)"
    )

    parser.add_argument(
        "--stdio",
        action="store_true",
        help="Run in stdio transport mode (for Claude Code / MCP clients)"
    )

    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host address to bind to (default: 127.0.0.1, HTTP mode only)"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to listen on (default: 8000, HTTP mode only)"
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None):
    """Run the sapcli MCP server."""
    args = parse_args(argv)
    config_path = args.config or os.environ.get('SAPCLI_MCP_CONFIG')

    try:
        server = create_mcp_server(
            experimental=args.experimental,
            config_path=config_path,
        )
    except ConfigError as exc:
        sys.exit(f"Configuration error: {exc}")

    if args.stdio:
        server.run(transport="stdio")
    else:
        server.run(transport="http", host=args.host, port=args.port)
