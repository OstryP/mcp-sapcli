"""Wrapper: refresh SAP cookie then start the MCP server.

Expects to live at: projects/mcp-sapcli/start-mcp.py
with refresh_sso_cookie.py at: projects/../tools/refresh_sso_cookie.py
(i.e. the standard Claude workspace layout).

Cookie resolution order:
  1. SAP_COOKIE_I7D already set in environment → use it directly
  2. Try running SAPCLI_COOKIE_SCRIPT to refresh → set SAP_COOKIE_I7D
  3. If refresh fails → start server anyway (will fail on first tool call)
"""

import os
import subprocess
import sys

COOKIE_SCRIPT = os.environ.get(
    'SAPCLI_COOKIE_SCRIPT',
    os.path.normpath(os.path.join(
        os.path.dirname(__file__), '..', '..', 'tools', 'refresh_sso_cookie.py'
    )),
)


def main():
    if not os.environ.get('SAP_COOKIE_I7D'):
        result = subprocess.run(
            [sys.executable, COOKIE_SCRIPT, '--sap-only',
             'https://i7daci.bss.net.sap:443/sap/bc/adt/?sap-client=001'],
            capture_output=True, text=True,
            timeout=90,
        )
        if result.returncode == 0 and result.stdout.strip():
            os.environ['SAP_COOKIE_I7D'] = result.stdout.strip()
        else:
            print(
                'Warning: cookie refresh failed, server will start without auth. '
                'Set SAP_COOKIE_I7D manually or run refresh_sso_cookie.py first.',
                file=sys.stderr,
            )
            os.environ['SAP_COOKIE_I7D'] = 'EXPIRED'

    server = os.path.join(os.path.dirname(__file__), 'src', 'sapcli-mcp-server.py')
    config = os.path.join(os.path.dirname(__file__), 'sapcli-mcp.json')
    # os.execv on Windows spawns a child and waits (vs. replacing the process
    # on Unix). Acceptable for stdio MCP — the parent is transparent.
    os.execv(sys.executable, [
        sys.executable, server, '--stdio', '--config', config, '--experimental',
    ])


if __name__ == '__main__':
    main()
