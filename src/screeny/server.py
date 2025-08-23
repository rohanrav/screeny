import subprocess
import tempfile
import os
import json
import ast
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent, ImageContent
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData, INVALID_PARAMS, INTERNAL_ERROR
from pydantic import BaseModel, Field, model_validator

from .image_compression import compress_to_base64_cap

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".screeny"
CONFIG_FILE = CONFIG_DIR / "approved_windows.json"
SETTINGS_FILE = CONFIG_DIR / "config.json"

mcp = FastMCP(
    "Screeny",
    instructions="""Use this server to capture screenshots of specific application windows on macOS, providing visual context for development and debugging tasks.

WORKFLOW:
1. Call 'list_windows' once to discover available windows and their IDs
2. Use 'take_screenshot' with any valid window ID from the list_windows results.

Note: Server requires the user to setup (Screen Recording permission and window approval) before use.
Screenshots are compressed to prevent transmission issues."""
)


class WindowInfo(BaseModel):
    """Information about a macOS window."""

    id: Annotated[str, Field(description="Unique window ID")]
    app: Annotated[str, Field(
        description="Application name that owns the window")]
    title: Annotated[str, Field(description="Window title")]
    approved: Annotated[bool, Field(
        default=False, description="Whether this window is approved for screenshots")]


class ScreenshotRequest(BaseModel):
    """Parameters for taking a screenshot of a window."""

    window_id: Annotated[str, Field(
        description="The window ID from listWindows to capture")]

    @model_validator(mode='before')
    @classmethod
    def _coerce_from_string(cls, input_value):
        """Allow callers to pass a stringified request.

        Accepts either:
        - a dict-like object {"window_id": "..."}
        - a JSON string that parses to that shape
        - a Python-literal dict string (e.g., "{'window_id': '...'}")

        If parsing fails, raise a clear validation error.
        """
        if isinstance(input_value, str):
            try:
                parsed = json.loads(input_value)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                try:
                    parsed = ast.literal_eval(input_value)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    pass
            raise ValueError(
                "request must be an object or a JSON/Python-dict string representing that object"
            )
        return input_value


class WindowSetupRequest(BaseModel):
    """Parameters for window setup operations."""

    approve_all: Annotated[bool, Field(
        default=False, description="Approve all windows without prompting")]


def ensure_config_dir():
    """Ensure the config directory exists"""
    CONFIG_DIR.mkdir(exist_ok=True)


def load_settings() -> Dict[str, Any]:
    """Load settings from persistent storage (advanced options)."""
    if not SETTINGS_FILE.exists():
        return {}
    try:
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load settings: {e}")
        return {}


def save_settings(settings: Dict[str, Any]):
    """Save settings to persistent storage (advanced options)."""
    ensure_config_dir()
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save settings: {e}")


def get_active_max_b64_kb() -> int:
    """Resolve the active base64 size cap (KB) with defaults and clamping.

    Priority: env var SCREENY_MAX_B64_KB > settings file > default (250).
    Always clamp to [100, 900].
    """
    env_val = os.environ.get('SCREENY_MAX_B64_KB')
    if env_val:
        try:
            val = int(env_val)
        except ValueError:
            val = 250
    else:
        settings = load_settings()
        val = int(settings.get('max_b64_kb', 250))

    val = max(100, min(900, val))
    return val


def load_approved_windows() -> Dict[str, Dict[str, Any]]:
    """Load approved windows from persistent storage"""
    if not CONFIG_FILE.exists():
        return {}

    try:
        with open(CONFIG_FILE, 'r') as f:
            data = json.load(f)
            return data.get('approved_windows', {})
    except Exception as e:
        logger.warning(f"Failed to load config: {e}")
        return {}


def save_approved_windows(windows: Dict[str, Dict[str, Any]]):
    """Save approved windows to persistent storage"""
    ensure_config_dir()
    try:
        config = {
            'approved_windows': windows,
            'last_updated': datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save config: {e}")


def _is_user_application_window(window: Dict[str, Any]) -> bool:
    """
    Check if a window represents a user application window worth capturing.
    """
    owner_name = window.get("kCGWindowOwnerName", "")
    window_name = window.get("kCGWindowName", "")
    window_number = window.get("kCGWindowNumber")
    window_layer = window.get("kCGWindowLayer", 0)

    return (
        owner_name and
        window_name and
        window_number and
        window_layer <= 2 and
        len(window_name.strip()) > 0 and
        window_name != "Desktop" and
        not owner_name.startswith("com.apple.") and
        owner_name not in ["WindowServer", "Dock", "Wallpaper",
                           "SystemUIServer", "Control Center"]
    )


def get_all_windows() -> List[WindowInfo]:
    """
    Get all available windows using macOS Quartz framework.
    Returns real window IDs that work with screencapture -l.
    """
    try:
        from Quartz import CGWindowListCopyWindowInfo, kCGWindowListOptionAll, kCGNullWindowID
        window_list = CGWindowListCopyWindowInfo(
            kCGWindowListOptionAll, kCGNullWindowID)

        windows = []
        for window in window_list:
            if _is_user_application_window(window):
                windows.append(
                    WindowInfo(
                        id=str(window.get("kCGWindowNumber")),
                        app=window.get("kCGWindowOwnerName", ""),
                        title=window.get("kCGWindowName", ""),
                        approved=False
                    )
                )

        # If no windows found, it's likely a permission issue
        if len(windows) == 0:
            raise RuntimeError(
                "No windows found. Most likely cause: Screen Capture permission not granted to MCP host.\n"
                "Fix: System Settings → Privacy & Security → Screen & System Audio Recording → '+' → Add your MCP host → Restart MCP host"
            )

        return windows

    except ImportError as e:
        logger.error("❌ Quartz framework not available!")
        logger.error(
            "   pyobjc-framework-Quartz is required but failed to import.")
        logger.error("   Try: pip install pyobjc-framework-Quartz")
        raise RuntimeError(
            "Quartz framework required but not available") from e
    except Exception as e:
        logger.error(f"❌ Failed to enumerate windows: {e}")
        raise RuntimeError(f"Window enumeration failed: {e}") from e


def setup_windows_interactive() -> Dict[str, Dict[str, Any]]:
    """Interactive terminal-based window approval with user prompts"""
    print("\n🪟 Screeny Window Approval Setup")
    print("=" * 40)

    try:
        current_windows = get_all_windows()
    except RuntimeError as e:
        print(f"❌ Cannot enumerate windows: {e}")
        return {}

    if not current_windows:
        print("❌ No windows found. Make sure you have applications open.")
        return {}

    print(f"Found {len(current_windows)} open windows:")
    print()

    approved = {}
    for i, window in enumerate(current_windows, 1):
        print(f"{i:2d}. {window.app} - {window.title}")

        while True:
            choice = input(
                f"    Approve this window? [y/n/s(kip remaining)/a(ll)/q(uit)]: ").lower().strip()
            if choice in ['y', 'yes']:
                window_dict = window.model_dump()
                window_dict['approved'] = True
                approved[window.id] = window_dict
                print("    ✅ Approved")
                break
            elif choice in ['n', 'no']:
                print("    ❌ Skipped")
                break
            elif choice in ['s', 'skip']:
                print(
                    f"\n⏭️ Skipping remaining {len(current_windows) - i} windows...")
                print(
                    f"✅ Setup complete with {len(approved)} approved windows.")
                return approved
            elif choice in ['a', 'all']:
                print("    ✅ Approving all remaining windows...")
                for remaining_window in current_windows[i-1:]:
                    window_dict = remaining_window.model_dump()
                    window_dict['approved'] = True
                    approved[remaining_window.id] = window_dict
                print(f"    ✅ Approved {len(current_windows) - i + 1} windows")
                return approved
            elif choice in ['q', 'quit']:
                print("\n🛑 Setup cancelled")
                return approved
            else:
                print(
                    "    Please enter y (yes), n (no), s (skip remaining), a (approve all), or q (quit)")

    print(f"\n✅ Setup complete! Approved {len(approved)} windows.")
    return approved


def setup_windows_approve_all() -> Dict[str, Dict[str, Any]]:
    """Auto-approve all current windows without prompting"""
    try:
        current_windows = get_all_windows()
    except RuntimeError as e:
        print(f"❌ Cannot enumerate windows: {e}")
        return {}

    if not current_windows:
        print("❌ No windows found. Make sure you have applications open.")
        return {}

    approved = {}
    for window in current_windows:
        window_dict = window.model_dump()
        window_dict['approved'] = True
        approved[window.id] = window_dict

    print(f"✅ Auto-approved all {len(approved)} windows.")
    return approved


def take_screenshot_direct(window_id: str, tmp_path: str) -> subprocess.CompletedProcess:
    """
    Take screenshot using direct window capture (requires Screen Recording permission).
    """
    logger.info(f"Taking screenshot of window {window_id}")
    result = subprocess.run(
        ['screencapture', '-x', '-l', window_id, tmp_path],
        capture_output=True, text=True, timeout=10
    )
    return result


def setup_mode(allow_all: bool = False):
    """Interactive setup mode for window approval"""
    print("🚀 Screeny Setup Mode")
    print("This will help you approve windows for screenshot capture.")
    print()

    if allow_all:
        print("🔓 Auto-approving all windows...")
        approved = setup_windows_approve_all()
    else:
        print("🔒 Interactive approval mode...")
        print("💡 Tip: Use 'a' to approve all remaining, or 's' to skip remaining")
        print()
        approved = setup_windows_interactive()

    if approved:
        save_approved_windows(approved)
        print(f"\n💾 Configuration saved to: {CONFIG_FILE}")
        print("\n📋 Summary:")
        for window in approved.values():
            print(f"   - {window['app']}: {window['title']}")
        print("\n💡 Grant Screen Recording permission when prompted!")

        print("\n⚙️  Advanced options (optional):")
        adv = input("    Open advanced options now? [y/N]: ").lower().strip()
        if adv in ['y', 'yes']:
            print("\n   Select image size preset (affects stability and clarity):")
            print("     1) Tiny   (50 KB)   — most stable; fine text will blur")
            print(
                "     2) Small  (100 KB)  — recommended default; balanced clarity and stability")
            print("     3) Medium (250 KB)  — more detail; may be slower and heavier")
            print(
                "     4) Large  (500 KB)  — high detail; may trigger client summarization")
            print("     5) XL     (750 KB)  — maximum detail; most error-prone")
            preset = input("   Enter 1/2/3/4/5 [default: 3]: ").strip()
            mapping = {'1': 50, '2': 100, '3': 250, '4': 500, '5': 750}
            max_kb = mapping.get(preset if preset in mapping else '3', 250)
            settings = load_settings()
            settings['max_b64_kb'] = max_kb
            save_settings(settings)
            print(
                f"\n✅ Saved advanced setting: max base64 size = {max_kb} KB (stored in {SETTINGS_FILE})")
    else:
        print("\n❌ No windows approved. Run setup again when ready.")
        print("💡 Tip: Use --allow-all flag to approve all windows automatically:")
        print("   mcp-server-screeny --setup --allow-all")


def debug_mode():
    """Debug mode to test window enumeration and permissions"""
    print("🔍 Screeny Debug Mode")
    print("=" * 30)

    print("\n1. Testing Quartz framework...")
    try:
        windows = get_all_windows()
        print(f"✅ Quartz: Found {len(windows)} windows with real IDs")

        print("\n2. Current windows:")
        for w in windows[:10]:
            print(f"   - [{w.id}] {w.app}: {w.title}")
        if len(windows) > 10:
            print(f"   ... and {len(windows) - 10} more")

    except RuntimeError as e:
        print(f"❌ Quartz: {e}")
        return

    print("\n3. Recommendations:")
    print("   ✅ Quartz working optimally!")
    print("   💡 Grant Screen Recording permission when taking screenshots for best UX")


def get_current_approved_windows() -> Dict[str, Dict[str, Any]]:
    """Load approved windows from disk and validate they're still open"""
    approved = load_approved_windows()
    if not approved:
        return {}

    current_windows = get_all_windows()
    current_window_map = {w.id: w for w in current_windows}

    still_open_approved = {}

    for window_id, window_info in approved.items():
        if window_info.get('approved') and window_id in current_window_map:
            current_window = current_window_map[window_id]

            old_title = window_info['title']
            new_title = current_window.title

            if old_title != new_title:
                logger.info(
                    f"Updated title for window {window_id}: '{old_title}' -> '{new_title}'")
                window_info['title'] = new_title

            still_open_approved[window_id] = window_info

    save_approved_windows(still_open_approved)
    if len(still_open_approved) < len(approved):
        removed_count = len(approved) - len(still_open_approved)
        logger.info(
            f"Removed {removed_count} closed windows from approved list")

    return still_open_approved


@mcp.tool(
    annotations={
        "title": "List Approved Windows",
        "readOnlyHint": True,
        "openWorldHint": False
    }
)
def list_windows() -> list[TextContent]:
    """
    List all currently approved windows available for screenshot capture.

    Call this once per session to discover available window IDs for use with 'take_screenshot'.
    Re-call if encountering screenshot errors (window closed, new apps opened, etc.).

    Args: None

    Returns: JSON with:
    - approved_windows: Array of window objects (id, app, title, approved status)
    - total_approved: Count of approved windows  
    - message: Next steps guidance
    """
    try:
        approved_windows = get_current_approved_windows()
    except RuntimeError as e:
        raise McpError(ErrorData(
            code=INTERNAL_ERROR,
            message=f"Unexpected error listing approved windows: {str(e)}"
        ))

    if not approved_windows:
        raise McpError(ErrorData(
            code=INVALID_PARAMS,
            message='No approved windows found. Run setup: "mcp-server-screeny --setup" or "uvx mcp-server-screeny --setup"'
        ))

    result_data = {
        'approved_windows': list(approved_windows.values()),
        'total_approved': len(approved_windows),
        'message': 'Use takeScreenshot with a window ID to capture.'
    }

    return [TextContent(
        type="text",
        text=json.dumps(result_data, indent=2)
    )]


@mcp.tool(
    annotations={
        "title": "Take Window Screenshot",
        "readOnlyHint": True,
        "openWorldHint": False
    }
)
def take_screenshot(request: ScreenshotRequest) -> list[ImageContent | TextContent]:
    """
    Take a screenshot of a specific window by its ID using direct capture.

    Requires calling 'list_windows' once per session to obtain valid window IDs.
    If screenshot fails, re-call 'list_windows' to refresh available windows.

    Args:
    - window_id (str): Exact window ID string from list_windows results

    Returns:
    - ImageContent: Base64-encoded screenshot (JPEG)
    - TextContent: Capture metadata (window info, timestamp)

    Note: Can capture windows in background but not minimized windows.
    Images are always compressed to JPEG and capped to ≤500KB including base64 overhead (configurable).
    """
    final_window_id = request.window_id

    if not final_window_id or not isinstance(final_window_id, str):
        raise McpError(ErrorData(
            code=INVALID_PARAMS,
            message="window_id must be a non-empty string"
        ))

    try:
        approved_windows = get_current_approved_windows()
    except RuntimeError as e:
        raise McpError(ErrorData(
            code=INTERNAL_ERROR,
            message=str(e)
        ))

    if not approved_windows:
        raise McpError(ErrorData(
            code=INVALID_PARAMS,
            message='No approved windows found. Run setup: "mcp-server-screeny --setup" or "uvx mcp-server-screeny --setup"'
        ))

    if final_window_id not in approved_windows:
        raise McpError(ErrorData(
            code=INVALID_PARAMS,
            message=f"Window ID '{final_window_id}' not found in currently open approved windows. Run listWindows to see available windows, or run setup to approve new windows."
        ))

    window_info = approved_windows[final_window_id]

    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
        tmp_path = tmp_file.name

    try:
        result = take_screenshot_direct(final_window_id, tmp_path)

        if result.returncode != 0:
            if "not permitted" in result.stderr.lower() or "not authorized" in result.stderr.lower():
                raise McpError(ErrorData(
                    code=INTERNAL_ERROR,
                    message=f"Screen Capture permission required. Grant permission in System Settings → Privacy & Security → Screen & System Audio Recording"
                ))
            elif "can't create" in result.stderr.lower() or "doesn't exist" in result.stderr.lower():
                raise McpError(ErrorData(
                    code=INTERNAL_ERROR,
                    message=f"Cannot capture '{window_info['title']}' - window appears minimized or closed. Restore window from dock and try again."
                ))
            else:
                raise McpError(ErrorData(
                    code=INTERNAL_ERROR,
                    message=f"Screenshot failed for '{window_info['title']}': {result.stderr}"
                ))

        tmp_file_path = Path(tmp_path)
        if not tmp_file_path.exists() or tmp_file_path.stat().st_size == 0:
            raise McpError(ErrorData(
                code=INTERNAL_ERROR,
                message=f"Screenshot file empty or missing for '{window_info['title']}'"
            ))

        # Always compress to JPEG and ensure final base64 payload within configured cap
        configured_kb = get_active_max_b64_kb()
        base64_max_bytes = configured_kb * 1024
        base64_data, mime_type, base64_size_bytes, chosen_scale, chosen_quality, used_fallback = compress_to_base64_cap(
            tmp_path, base64_max_bytes)

        if not base64_data:
            raise McpError(ErrorData(
                code=INTERNAL_ERROR,
                message=(
                    f"Compression could not fit under cap (cap={configured_kb}KB). "
                    f"Try a smaller window area or reduce configured size preset."
                )
            ))

        base64_size_kb = (base64_size_bytes + 1023) // 1024

        metadata = {
            "window_id": final_window_id,
            "app": window_info['app'],
            "title": window_info['title'],
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "base64_size_kb": base64_size_kb,
            "cap_kb": configured_kb,
            "chosen_scale": chosen_scale,
            "chosen_quality": chosen_quality,
            "used_fallback": used_fallback
        }

        return [
            ImageContent(
                type="image",
                data=base64_data,
                mimeType=mime_type
            ),
            TextContent(
                type="text",
                text=f"Screenshot captured: {window_info['app']} - {window_info['title']}\n\nMetadata:\n{json.dumps(metadata, indent=2)}"
            )
        ]

    except subprocess.TimeoutExpired:
        raise McpError(ErrorData(
            code=INTERNAL_ERROR,
            message=f"Screenshot timed out for '{window_info['title']}'"
        ))
    except Exception as e:
        logger.error(f"Unexpected error taking screenshot: {e}")
        raise McpError(ErrorData(
            code=INTERNAL_ERROR,
            message=f"Unexpected error taking screenshot: {str(e)}"
        ))
    finally:
        try:
            if Path(tmp_path).exists():
                os.unlink(tmp_path)
        except Exception as e:
            logger.warning(f"Failed to clean up temp file {tmp_path}: {e}")


@mcp.resource("screeny://info")
def get_server_info() -> str:
    """Get information about the Screeny MCP server"""
    return json.dumps({
        "name": "Screeny MCP Server",
        "version": "0.3.6",
        "description": "Capture screenshots of specific application windows, providing visual context for development and debugging tasks",
        "capabilities": [
            "List application windows on macOS",
            "Capture screenshots of specific application windows",
            "Return screenshots as Base64-encoded JPEG images",
            "Provide window metadata for analysis"
        ],
        "requirements": [
            "macOS only",
            "pyobjc-framework-Quartz",
            "Screen Recording permission"
        ],
        "tools": ["listWindows", "takeScreenshot"],
        "resources": ["screeny://info"],
        "config_file": str(CONFIG_FILE),
        "settings_file": str(SETTINGS_FILE),
        "max_b64_kb": get_active_max_b64_kb()
    }, indent=2)


def serve() -> None:
    """Run the Screeny MCP server."""
    logger.info("Starting Screeny MCP Server...")
    mcp.run()
