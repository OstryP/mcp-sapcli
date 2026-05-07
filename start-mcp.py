"""Launch the sapcli MCP server with default config.

This is a convenience launcher that:
- Sets SAP_COOKIE_I7D placeholder if not provided (prevents config loader failure)
- Suppresses stderr (required for clean MCP stdio transport)
- Defaults to --stdio --experimental with local sapcli-mcp.json config

For direct usage, prefer the installed entry point: sapcli-mcp
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    if not os.environ.get('SAP_COOKIE_I7D'):
        os.environ['SAP_COOKIE_I7D'] = 'NOT_SET'

    config = os.path.join(HERE, 'sapcli-mcp.json')
    sys.exit(subprocess.call(
        [sys.executable, '-m', 'sapclimcp',
         '--stdio', '--config', config, '--experimental'],
        stderr=subprocess.DEVNULL,
    ))


if __name__ == '__main__':
    main()
