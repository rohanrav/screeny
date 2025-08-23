import argparse
import sys

from .server import serve, setup_mode, debug_mode

__version__ = "0.3.6"
__all__ = ["serve", "setup_mode", "debug_mode"]


def main():
    """Screeny MCP Server - macOS window enumeration and screenshot capture"""
    parser = argparse.ArgumentParser(description="Screeny MCP Server")
    parser.add_argument('--setup', action='store_true',
                        help='Run interactive window approval setup')
    parser.add_argument('--allow-all', action='store_true',
                        help='When used with --setup, approve all windows automatically')
    parser.add_argument('--debug', action='store_true',
                        help='Run debug mode to test window enumeration')
    parser.add_argument('--version', action='version', version=f'screeny {__version__}',
                        help='Show version information')

    if len(sys.argv) > 1:
        args = parser.parse_args()
        if args.setup:
            setup_mode(allow_all=args.allow_all)
            return
        elif args.allow_all:
            print("❌ --allow-all can only be used with --setup")
            print("💡 Try: mcp-server-screeny --setup --allow-all")
            return
        elif args.debug:
            debug_mode()
            return

    serve()


if __name__ == "__main__":
    main()
