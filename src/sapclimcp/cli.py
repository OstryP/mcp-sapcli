"""CLI entry point for the sapcli MCP server."""

import os

from sapclimcp.server import create_mcp_server, parse_args


def main():
    """Run the sapcli MCP server."""
    if not os.environ.get('SAP_COOKIE_I7D'):
        os.environ['SAP_COOKIE_I7D'] = 'NOT_SET'

    args = parse_args()
    config_path = args.config or os.environ.get('SAPCLI_MCP_CONFIG')
    server = create_mcp_server(
        experimental=args.experimental,
        config_path=config_path,
    )
    if args.stdio:
        server.run(transport="stdio")
    else:
        server.run(transport="http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
