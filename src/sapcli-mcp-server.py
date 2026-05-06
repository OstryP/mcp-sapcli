"""
Export sapcli commands as MCP tools.

This script is kept for backwards compatibility.
Prefer running via the installed entry point: sapcli-mcp
"""

import os
import sys

# Ensure src/ is on the path when running this script directly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sapclimcp.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
