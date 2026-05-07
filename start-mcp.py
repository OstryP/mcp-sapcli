"""Launch the sapcli MCP server with default config.

Requires: pip install -e . (or uv pip install -e .)

This is a convenience launcher that:
- Sets SAP_COOKIE_I7D placeholder if not provided (prevents config loader failure)
- Captures stderr to a temp file (required for clean MCP stdio transport)
  and displays it only on non-zero exit (so startup errors are visible)
- Defaults to --stdio --experimental with local sapcli-mcp.json config

For direct usage, prefer the installed entry point: sapcli-mcp
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    if not os.environ.get('SAP_COOKIE_I7D'):
        os.environ['SAP_COOKIE_I7D'] = 'NOT_SET'

    config = os.path.join(HERE, 'sapcli-mcp.json')

    # Capture stderr to a file so MCP stdio transport stays clean,
    # but we can still surface errors on startup failure.
    fd, stderr_log = tempfile.mkstemp(suffix='.log', prefix='sapcli-mcp-')
    try:
        with os.fdopen(fd, 'w') as stderr_file:
            exit_code = subprocess.call(
                [sys.executable, '-m', 'sapclimcp',
                 '--stdio', '--config', config, '--experimental'],
                stderr=stderr_file,
            )

        if exit_code != 0:
            try:
                with open(stderr_log, 'r') as f:
                    error_output = f.read().strip()
                if error_output:
                    print(
                        f"MCP server failed (exit {exit_code}):\n{error_output}",
                        file=sys.stderr,
                    )
                else:
                    print(
                        f"MCP server exited with code {exit_code} (no details)",
                        file=sys.stderr,
                    )
            except OSError:
                pass
    finally:
        try:
            os.unlink(stderr_log)
        except OSError:
            pass

    sys.exit(exit_code)


if __name__ == '__main__':
    main()
