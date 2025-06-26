"""
Main entry point for the Screeny MCP server.

This allows the server to be run as:
- python -m screeny (development)
- mcp-server-screeny (installed via pipx/uvx)
"""

from screeny import main

if __name__ == "__main__":
    main()
