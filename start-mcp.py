"""Launch the sapcli MCP server.

Sets a placeholder for SAP_COOKIE_I7D if not already provided
externally, so the config loader doesn't fail on startup.
Cookie acquisition is an external concern — users provide it
via environment variable before launching.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    if not os.environ.get('SAP_COOKIE_I7D'):
        os.environ['SAP_COOKIE_I7D'] = 'NOT_SET'

    src_dir = os.path.join(HERE, 'src')
    env = os.environ.copy()
    env['PYTHONPATH'] = src_dir + os.pathsep + env.get('PYTHONPATH', '')

    server = os.path.join(HERE, 'src', 'sapcli-mcp-server.py')
    config = os.path.join(HERE, 'sapcli-mcp.json')
    sys.exit(subprocess.call(
        [sys.executable, server, '--stdio', '--config', config],
        env=env,
        stderr=subprocess.DEVNULL,
    ))


if __name__ == '__main__':
    main()
