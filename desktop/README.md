# AgentHub Desktop

A lightweight Windows desktop client for AgentHub, built with Tauri.

## Architecture

The desktop app is a **client only** — it connects to the VM-hosted AgentHub backend via HTTP. It does not bundle a second backend or database.

- Uses system WebView2 on Windows (no bundled Chromium)
- Settings stored in `%APPDATA%\agent-hub-desktop\`
- Loads the remote AgentHub UI in a WebView window

## Prerequisites

- **Rust**: Install from https://rustup.rs/
- **Node.js**: Install from https://nodejs.org/ (for Tauri CLI)
- **WebView2 Runtime**: Pre-installed on Windows 10+, or download from https://developer.microsoft.com/microsoft-edge/webview2/

## Build Instructions

```powershell
# Navigate to desktop directory
cd desktop

# Install Node dependencies
npm install

# Development mode (requires running backend)
npm run dev

# Production build
npm run build
```

## Build Output

After `npm run build`:

- **Installer**: `src-tauri/target/release/bundle/nsis/AgentHub Desktop Setup X.X.X.exe`
- **Portable**: `src-tauri/target/release/bundle/app/AgentHub Desktop_x64.zip`

## First-Run Flow

1. App launches → shows settings page
2. Enter VM URL (e.g., `http://192.168.1.100:8080`) and API key
3. App validates connection via `/api/health`
4. On success, loads the remote AgentHub UI
5. On failure, shows error and allows retry

## Settings

Settings are stored in Tauri's store API at:
`%APPDATA%\agent-hub-desktop\tauri\settings.json`

- `serverUrl`: The AgentHub backend URL
- `apiKey`: Your API key from `.env`

## Connection Handling

- Periodic health check every 30 seconds
- Status indicator in title bar (green/red)
- Manual reconnect button in settings bar
- Auto-reconnect on connection loss

## Troubleshooting

- **"Failed to connect"**: Verify the VM is running and accessible from your Windows machine
- **"Auth Error"**: Check your API key matches the `.env` file on the VM
- **WebView2 not found**: Install the WebView2 runtime from Microsoft
