"""
Export sapcli commands as MCP tools.

This script is kept for backwards compatibility.
Prefer running via the installed entry point: sapcli-mcp
"""

if __name__ == "__main__":
    import os
    import sys

    # Add src/ to path for uninstalled usage
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from sapclimcp.cli import main
    main()
