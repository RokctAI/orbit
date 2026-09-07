# Orbit

OSS client daemon for [Gravity](https://github.com/RokctAI/gravity). Install, connect, and edit repos in any IDE.

## Install

```bash
pip install -e .
```

The CLI (`orbit login`, `orbit mount`, `orbit status`) runs headless: Tk is only
needed for `orbit widget`, and it is imported lazily, so the other commands work
on servers and CI runners without tkinter.

## Usage

```bash
orbit login          # Authenticate with Gravity server
orbit mount          # Serve the Gravity workspace over WebDAV and mount it
orbit status         # Show connection and sync state
orbit widget         # Launch the floating minimal status bar
orbit --version      # Version comes from version.json (single source of truth)
```

### Mounting

`orbit mount` starts a local WebDAV bridge on `http://127.0.0.1:8080/`
(`--port` to change it) and then mounts it for your platform:

- **Windows**: mapped to the next free drive letter with `net use` (needs the
  `WebClient` service running).
- **macOS**: mounted at `~/Gravity` with `mount_webdav`; if that fails, use
  Finder → Go → Connect to Server… with the URL above.
- **Linux**: mounted with `gio mount dav://127.0.0.1:8080/` when GVfs is
  available; otherwise the exact `gio` and davfs2 (`mount -t davfs`) commands
  are printed and the bridge keeps running until Ctrl+C.

### Configuration

Settings live in `~/.orbit/config.json`. The Gravity session token is stored in
the OS keyring (service `gravity`) and only written to the file when no keyring
is available. Resolution order, shared by the CLI, the VFS and the widget:

| Setting | Resolution order |
| --- | --- |
| Token | `ORBIT_TOKEN` env → OS keyring → `token` in `config.json` |
| Server origin | `ORBIT_SERVER` env → `server` in `config.json` |
| Gravity API base | `ORBIT_GRAVITY_URL` env → `gravity_url` → `{server}` + prefix |
| Prefix | `ORBIT_GRAVITY_PREFIX` env → `gravity_prefix` → `/gravity` (production nginx) |

Set `gravity_prefix` to `""` (or `gravity_url` to e.g. `http://127.0.0.1:8000`)
to talk to a Gravity container directly.

The repositories shown at the root of the mounted drive come from the `repos`
list in `config.json` if present, otherwise from the server when it provides a
list, otherwise from a built-in offline fallback. The fallback is not verified
against the server (it may name repositories that no longer exist there), so
when it is in use `orbit status` and `orbit mount` say so, and the drive root
carries a `00-ORBIT-REPO-LIST-UNAVAILABLE.txt` file explaining how to set
`"repos": [...]` in `config.json`.

### Saves that did not land

A save is only reported to the editor as successful when Gravity actually
persisted it. A conflict comes back as HTTP 409 (whether Gravity answers 409
itself or a 200 body with `"conflict": true`), and a `"No changes to push"`
answer to content the client knows it changed is reported as a failed save
rather than silently accepted (this happens against a Gravity server older
than this client).

## Native diff helpers (`orbit_diff_rs`)

`orbit_diff_rs/` is a small pyo3 crate (text unified diff, zstd-compressed
bsdiff binary patches) that Gravity imports to apply binary patches. Build a
wheel with [maturin](https://www.maturin.rs/):

```bash
pip install maturin
cd orbit_diff_rs && maturin build --release   # wheel lands in target/wheels/
```

## Tests

```bash
pip install -e ".[test]"
python -m pytest -q
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

