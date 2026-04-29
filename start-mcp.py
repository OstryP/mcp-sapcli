"""Launch the sapcli MCP server.

Sets a placeholder for SAP_COOKIE_I7D if not already provided
externally, so the config loader doesn't fail on startup.
Cookie acquisition is an external concern — users provide it
via environment variable before launching.
"""

import os
import sys


def main():
    if not os.environ.get('SAP_COOKIE_I7D'):
        os.environ['SAP_COOKIE_I7D'] = 'NOT_SET'

    server = os.path.join(os.path.dirname(__file__), 'src', 'sapcli-mcp-server.py')
    config = os.path.join(os.path.dirname(__file__), 'sapcli-mcp.json')
    os.execv(sys.executable, [
        sys.executable, server, '--stdio', '--config', config, '--experimental',
    ])


if __name__ == '__main__':
    main()
