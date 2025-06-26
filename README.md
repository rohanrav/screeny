# Screeny MCP Server

A **macOS-only MCP server** that enables LLMs to capture screenshots of specific application windows, providing visual context for development and debugging tasks.

> [!IMPORTANT]
> Requires **Screen Capture permission** - must be granted before running window approval setup. Read setup instructions below.

### Available Tools

- `listWindows` - Lists all approved application windows available for screenshot capture.

  - Only shows user approved windows

- `takeScreenshot` - Captures a screenshot of a specific window by its ID.
  - **Captures windows in background** - no need to bring window to front, but cannot capture minimized windows
  - **Provides actual pixel data** - full-fidelity image, not OCR or text extraction

### Resources

- `screeny://info` - Server information and configuration details

## Configuration

### Claude Desktop

1. Open Claude settings → Developer → Edit Config
2. Add configuration:

<details>
<summary><strong>Using uvx (recommended)</strong></summary>

```json
{
  "mcpServers": {
    "screeny": {
      "command": "uvx",
      "args": ["mcp-server-screeny"]
    }
  }
}
```

> **Note:** If you get a "spawn uvx ENOENT" error, replace `"uvx"` with the full path to uvx (find it with `which uvx` in terminal).

</details>

<details>
<summary><strong>Using pipx installation</strong></summary>

First install with: `pipx install mcp-server-screeny`

```json
{
  "mcpServers": {
    "screeny": {
      "command": "mcp-server-screeny",
      "args": []
    }
  }
}
```

> **Note:** If you get an `ENOENT` error, replace `"mcp-server-screeny"` with the full path to the executable (find it with `which mcp-server-screeny` in your terminal).

</details>

### Cursor

1. Open Cursor settings → Tools & Integrations → MCP Tools
2. Add configuration:

<details>
<summary><strong>Using uvx (recommended)</strong></summary>

```json
{
  "screeny": {
    "command": "uvx",
    "args": ["mcp-server-screeny"]
  }
}
```

> **Note:** If you get a "spawn uvx ENOENT" error, replace `"uvx"` with the full path to uvx (find it with `which uvx` in terminal).

</details>

<details>
<summary><strong>Using pipx installation</strong></summary>

First install with: `pipx install mcp-server-screeny`

```json
{
  "screeny": {
    "command": "mcp-server-screeny",
    "args": []
  }
}
```

> **Note:** If you get an `ENOENT` error, replace `"mcp-server-screeny"` with the full path to the executable (find it with `which mcp-server-screeny` in your terminal).

</details>

## Setup

### 1. Grant Screen Capture Permission (Required)

**Important:** Grant permission before running window approval.

> **Note**: MCP hosts may not prompt for Screen Capture permission automatically. Manually add your MCP host:
>
> 1. Open **System Settings** > **Privacy & Security** > **Screen & System Audio Recording**
> 2. Click the **"+"** button
> 3. Navigate to and select your MCP host application (e.g., Claude Desktop, Cursor)
> 4. **Restart the MCP host application** after granting permission

### 2. Window Approval (Required)

After configuring your MCP client above, approve which windows can be captured:

```bash
# Interactive approval
mcp-server-screeny --setup

# Auto-approve all current windows
mcp-server-screeny --setup --allow-all
```

Approvals are saved to `~/.screeny/approved_windows.json`. Re-run setup when you want to update the list of approved windows.

## Security & Privacy

- Only user-approved windows can be captured
- All processing stays local on your machine
- Screenshots are temporary and deleted immediately after use

## Troubleshooting

### Permission Issues

```bash
# Test window detection and permissions
mcp-server-screeny --debug

# Re-run setup if windows changed
mcp-server-screeny --setup
```

### Common Issues

**"Quartz framework not available"**

- Solution: Install dependencies with `pip install -e .` or ensure internet connection for automatic installation

**"No approved windows found"**

- Solution: Run `mcp-server-screeny --setup` first

**"Screen Recording permission required" or "No windows found"**

- Solution: Grant Screen Recording permission in System Settings > Privacy & Security > Screen & System Audio Recording
  - Click "+" button and manually add your MCP host (Claude Desktop, Cursor, etc.)
  - Restart your MCP host application after granting permissions
- Try running setup again after granting permissions

## Contributing

Pull requests are welcome! Feel free to contribute new ideas, bug fixes, or enhancements.

## Requirements

- Python 3.10+
- macOS (uses Quartz framework)

## License

MIT License
