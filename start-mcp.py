"""Wrapper: refresh SAP cookie then start the MCP server."""

import os
import subprocess
import sys


def main():
    cookie_script = os.path.join(
        os.path.dirname(__file__), '..', '..', 'tools', 'refresh_sso_cookie.py'
    )
    cookie_script = os.path.normpath(cookie_script)

    result = subprocess.run(
        [sys.executable, cookie_script, '--sap-only',
         'https://i7daci.bss.net.sap:443/sap/bc/adt/?sap-client=001'],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f'Cookie refresh failed: {result.stderr}', file=sys.stderr)
        sys.exit(1)

    os.environ['SAP_COOKIE_I7D'] = result.stdout.strip()

    server = os.path.join(os.path.dirname(__file__), 'src', 'sapcli-mcp-server.py')
    config = os.path.join(os.path.dirname(__file__), 'sapcli-mcp.json')
    os.execv(sys.executable, [
        sys.executable, server, '--stdio', '--config', config, '--experimental',
    ])


if __name__ == '__main__':
    main()
