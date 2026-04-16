"""
Export sapcli commands as MCP tools.
"""

import argparse
import os

from fastmcp import FastMCP

from sapclimcp.mcptools import transform_sapcli_commands
from sapclimcp.config import load_config, ConnectionManager

# List of verified and supported sapcli commands exposed as MCP tools
VERIFIED_COMMANDS = [
    "abap_package_list",
    "abap_package_stat",
    "abap_package_create",
    "abap_program_create",
    "abap_program_read",
    "abap_program_write",
    "abap_program_activate",
    "abap_gcts_repolist",
    "abap_class_read",
    "abap_class_write",
    "abap_interface_write",
    "abap_include_write",
    "abap_aunit_run",
    "abap_atc_run",
    "abap_ddl_read",
    "abap_ddl_write",
]

MCP_SERVER_INSTRUCTIONS = """
    This server connects to various SAP products and allows you to read and
    write their contents.
    For ABAP functions you can use features that requires HTTP or RFC.
    Both HTTP and RFC requires:
    - ASHOST   : Application Server host name
    - CLIENT   : ABAP Client (3 upper case letters+digits)
    - USER     : user name (case insensitive)
    - PASSWORD : password (case sensitive)
    For HTTP features (ADT, gCTS both use HTTP), you must provide:
    - HTTPPORT   : the HTTP port
    - USE_SSL    : true for HTTPS; false for naked HTTP
    - VERIFY_SSL : true to check ABAP server cert validity; otherwise false
    For RFC features, you must have the PyRFC library with NWRFC SDK
    installed on your machine and then you must provide:
    - SYSNR : 2 digits from 00 to 99 which will be translated to port
"""

MCP_SERVER_INSTRUCTIONS_MANAGED = """
    This server connects to SAP ABAP systems via ADT (ABAP Development Tools)
    REST API. Connections are managed server-side — you do not need to provide
    credentials.

    Available systems: {systems}
    Default system: {default}

    Use the optional 'system' parameter to target a specific system.
    If omitted, the default system is used.
"""


def parse_args():
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

    return parser.parse_args()


def create_mcp_server(
    name: str = "sapcli",
    experimental: bool = False,
    config_path: str | None = None,
) -> FastMCP:
    """Create and initialize the MCP server with sapcli commands.

    Args:
        name: Name for the MCP server instance.
        experimental: If True, expose all meaningful commands; otherwise only verified ones.
        config_path: Optional path to JSON config file with system definitions.

    Returns:
        Initialized FastMCP server with registered sapcli tools.
    """
    connection_manager = None

    if config_path:
        server_config = load_config(config_path)
        connection_manager = ConnectionManager(server_config)

    if connection_manager is not None:
        instructions = MCP_SERVER_INSTRUCTIONS_MANAGED.format(
            systems=', '.join(connection_manager.system_names),
            default=connection_manager.default_system or '(none)',
        )
    else:
        instructions = MCP_SERVER_INSTRUCTIONS

    mcp = FastMCP(name=name, instructions=instructions)
    allowed_commands = None if experimental else VERIFIED_COMMANDS
    transform_sapcli_commands(mcp, allowed_commands, connection_manager=connection_manager)
    return mcp


if __name__ == "__main__":
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
