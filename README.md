# Orbit

OSS client daemon for [Gravity](https://github.com/RokctAI/gravity). Install, connect, and edit repos in any IDE.

## Install

```bash
pip install -e .
```

## Usage

```bash
orbit login          # Authenticate with Gravity server
orbit mount          # Fetch allowed repos → local workspace
orbit status         # Show connection and sync state
orbit widget         # Launch the floating minimal status bar

```

## Floating Status Bar Widget

Orbit features a premium, minimal, borderless status bar widget that floats on top of your desktop (typically snaps just above the taskbar on Windows/dock on Mac).

### Features
- **Token Counter**: Recursively counts the active workspace's token count using `tiktoken`.
- **Workspace Setup**: If no workspace is selected, a "Set Workspace" button prompts you to pick your active directory using a folder picker. Login options appear once configured.
- **Auto-sizing Window**: Automatically adapts its width dynamically to fit your username, flag, status dot, and token string cleanly.
- **Status Indicator**: Minimal color dot (green/red) indicating server/internet connectivity.
- **Identity & Location**: Displays the system username and dynamically geolocates your IP to download and display your country flag.
- **Interactions**:
  - Drag-and-drop to position the widget anywhere on the desktop (Left-click and hold).
  - Double-click to toggle between **Expanded** and **Compact** view modes.
  - Right-click for the context menu (Force Refresh, Change Workspace, Login/Logout, Exit Widget).
  - Click the small `×` on the far right to close.

### Customization
Customize colors, default sizing, and refresh rates by editing:
`~/.orbit/widget_theme.json`


### macOS Compatibility
The widget is fully compatible with macOS out-of-the-box. If using Homebrew Python, you may need to install the Tkinter dependency once by running:
```bash
brew install python-tk
```

## Phase 2

Orbit connects to a Gravity server (FastAPI) running on your VPS. In Phase 1, only Gravity's local CLI is functional. Orbit commands are placeholders that will be implemented when Gravity gains its server mode.

