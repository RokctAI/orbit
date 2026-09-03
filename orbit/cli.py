# Copyright (c) 2026 RokctAI
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# Copyright (c) 2026, Rokct Intelligence (pty) Ltd.
# For license information, please see license.txt

"""Orbit CLI — OSS client daemon for Gravity.

Every command except ``widget`` runs headless: Tk is only imported, lazily,
by ``orbit widget`` so ``orbit status``/``login``/``mount`` work on servers
and CI runners without a display or the tkinter package.
"""

import os
import sys

import click

from orbit import __version__

# Shared, Tk-free config/credential/URL resolution (keyring first, plaintext
# file fallback, ORBIT_* env overrides) used by the CLI, the VFS and the widget.
from orbit.config import (
    load_orbit_config as _load_orbit_config,
    resolve_gravity_base_url as _resolve_gravity_base_url,
    save_orbit_config as _save_orbit_config,
    token_source as _token_source,
)

TOKEN_SOURCE_LABELS = {
    "env": "ORBIT_TOKEN environment variable",
    "keyring": "OS keyring",
    "file": "~/.orbit/config.json (plaintext; no keyring available)",
}


@click.group()
@click.version_option(version=__version__, prog_name="orbit")
def cli():
    """🛸 Orbit — Connect to Gravity, edit in any IDE."""
    pass


@cli.command()
@click.option("--server", prompt="Gravity server URL", help="URL of the Gravity server")
@click.option(
    "--token", prompt="API token", hide_input=True, help="Authentication token"
)
def login(server, token):
    """Authenticate with a Gravity server."""
    # Phase 2: validate token against server
    config = _load_orbit_config()
    config["server"] = server.rstrip("/")
    config["token"] = token
    _save_orbit_config(config)

    click.echo(f"\n✅ Authenticated with {server}")
    click.echo(f"   Gravity API: {_resolve_gravity_base_url(config)}")
    click.echo("   Run 'orbit mount' to fetch your repos.")


# ---------------------------------------------------------------------------
# mount helpers (one per platform so each stays small and testable)
# ---------------------------------------------------------------------------

DAVFS_HINT = (
    "   davfs2:  sudo mount -t davfs {url} /mnt/gravity   "
    "(install with: sudo apt install davfs2)"
)
GIO_HINT = "   GNOME/KDE: gio mount dav://127.0.0.1:{port}/   (then open it in your file manager)"


def _start_vfs_thread(port):
    """Start the local WebDAV bridge in a background daemon thread."""
    import threading
    from orbit.vfs import start_vfs_server

    def run_vfs_safely():
        try:
            start_vfs_server(host="127.0.0.1", port=port)
        except Exception as e:
            sys.stderr.write(f"VFS Server error: {e}\n")

    server_thread = threading.Thread(target=run_vfs_safely, daemon=True)
    server_thread.start()
    return server_thread


def _mount_windows(url):
    """Map the WebDAV URL to the next free drive letter with ``net use``."""
    import re
    import subprocess

    result = subprocess.run(
        ["net", "use", "*", url, "/persistent:no"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        click.echo(
            f"❌ Failed to mount drive: {result.stderr.strip() or result.stdout.strip()}"
        )
        click.echo("   Ensure the Windows 'WebClient' service is running.")
        click.echo(
            "   To start it, open cmd/PowerShell as Administrator and run: net start WebClient"
        )
        return None

    output = result.stdout
    drive_match = re.search(r"([A-Z]:)", output)
    drive_letter = drive_match.group(1) if drive_match else "Virtual Drive"

    def unmount():
        if drive_letter != "Virtual Drive":
            subprocess.run(
                ["net", "use", drive_letter, "/delete", "/y"], capture_output=True
            )

    return drive_letter, unmount


def _mount_macos(url):
    """Mount the WebDAV URL at ~/Gravity with ``mount_webdav`` (ships with macOS)."""
    import subprocess

    mount_point = os.path.expanduser("~/Gravity")
    try:
        os.makedirs(mount_point, exist_ok=True)
    except Exception as e:
        click.echo(f"❌ Could not create mount point {mount_point}: {e}")
        return None

    result = subprocess.run(
        ["mount_webdav", "-S", "-v", "Gravity", url, mount_point],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        click.echo(
            f"❌ mount_webdav failed: {result.stderr.strip() or result.stdout.strip()}"
        )
        click.echo(f"   The WebDAV bridge is still running at {url}")
        click.echo("   Connect manually: Finder → Go → Connect to Server… → " + url)
        click.echo(f"   or: mount_webdav -S -v Gravity {url} {mount_point}")
        return url, _noop_unmount

    def unmount():
        if (
            subprocess.run(
                ["diskutil", "unmount", mount_point], capture_output=True
            ).returncode
            != 0
        ):
            subprocess.run(["umount", mount_point], capture_output=True)

    return mount_point, unmount


def _mount_linux(url, port):
    """Mount via GVfs (``gio``) when available; otherwise print the exact commands."""
    import shutil
    import subprocess

    dav_url = f"dav://127.0.0.1:{port}/"
    if shutil.which("gio"):
        result = subprocess.run(
            ["gio", "mount", dav_url], capture_output=True, text=True
        )
        if result.returncode == 0:
            gvfs_dir = f"/run/user/{os.getuid()}/gvfs/dav:host=127.0.0.1,port={port}"
            click.echo(
                f"   Mounted with gio; it appears in your file manager (or at {gvfs_dir})."
            )

            def unmount():
                subprocess.run(["gio", "mount", "-u", dav_url], capture_output=True)

            return dav_url, unmount
        click.echo(
            f"⚠️  gio mount failed: {result.stderr.strip() or result.stdout.strip()}"
        )

    click.echo(f"   The WebDAV bridge is running at {url} — mount it with one of:")
    click.echo(GIO_HINT.format(port=port))
    click.echo(DAVFS_HINT.format(url=url))
    return url, _noop_unmount


def _noop_unmount():
    return None


def _mount_for_platform(url, port):
    """Dispatch on the current OS. Returns ``(label, unmount_callable)`` or None."""
    platform = sys.platform
    if platform.startswith("win"):
        return _mount_windows(url)
    if platform == "darwin":
        return _mount_macos(url)
    if platform.startswith("linux"):
        return _mount_linux(url, port)

    click.echo(f"⚠️  Automatic mounting is not supported on '{platform}'.")
    click.echo(f"   The WebDAV bridge is running at {url} — connect to it with your")
    click.echo("   platform's WebDAV client (any client that speaks WebDAV class 1/2).")
    return url, _noop_unmount


def _wait_until_interrupted(label, unmount):
    import time

    click.echo("   Press Ctrl+C to unmount and exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        click.echo(f"\n🛸 Unmounting {label}...")
        try:
            unmount()
        except Exception as e:
            click.echo(f"   (unmount failed: {e})")
        click.echo("👋 Exited.")


@cli.command()
@click.option(
    "--port",
    default=8080,
    show_default=True,
    type=int,
    help="Local port for the WebDAV bridge.",
)
def mount(port):
    """Mount the Gravity workspace as a local virtual network drive."""
    import time

    config = _load_orbit_config()
    if not config.get("server"):
        click.echo("❌ Not logged in. Run 'orbit login' first.")
        return

    url = f"http://127.0.0.1:{port}/"
    _start_vfs_thread(port)

    # Wait for the local server to spin up
    time.sleep(1.5)

    click.echo(f"🛸 Mounting Gravity workspace via WebDAV on localhost:{port}...")

    mounted = _mount_for_platform(url, port)
    if mounted is None:
        return
    label, unmount = mounted

    if label == url:
        # Nothing was mounted automatically; the bridge is serving and the
        # exact mount commands were printed above.
        click.echo(f"🛸 WebDAV bridge is serving at {url} (not auto-mounted).")
    else:
        click.echo(f"🎉 Success! Gravity virtual workspace is mounted at {label}")
        click.echo("   You can now open it in VS Code, Cursor, or your file manager!")
    _wait_until_interrupted(label, unmount)


@cli.command()
def status():
    """Show connection and sync state."""
    config = _load_orbit_config()

    click.echo("\n🛸 Orbit Status")
    if config.get("server"):
        click.echo(f"   Server: {config['server']}")
        click.echo(f"   Gravity API: {_resolve_gravity_base_url(config)}")
        # Same resolution the VFS/widget use, so this cannot report a token
        # that the mount would not actually send.
        source = _token_source(config)
        if config.get("token") and source:
            click.echo(
                f"   Auth: ✅ configured (token from {TOKEN_SOURCE_LABELS[source]})"
            )
        else:
            click.echo(
                "   Auth: ❌ no token (checked ORBIT_TOKEN, the OS keyring and ~/.orbit/config.json)"
            )
    else:
        click.echo("   Not connected. Run 'orbit login' first.")

    click.echo("")


TK_INSTALL_HINTS = (
    "   Debian/Ubuntu: sudo apt install python3-tk",
    "   Fedora:        sudo dnf install python3-tkinter",
    "   macOS (brew):  brew install python-tk",
    "   Windows:       re-run the python.org installer and tick 'tcl/tk and IDLE'",
)


@cli.command()
def widget():
    """Launch the floating minimal status bar widget."""
    click.echo("Launching Orbit Status Bar Widget...")
    try:
        from orbit.widget import run_widget
    except ImportError as e:
        if getattr(e, "name", None) in ("tkinter", "_tkinter") or "tkinter" in str(e):
            click.echo(
                "❌ The Orbit widget needs Tk (tkinter), which is not available",
                err=True,
            )
            click.echo(
                "   in this Python installation. Install it and try again:", err=True
            )
            for hint in TK_INSTALL_HINTS:
                click.echo(hint, err=True)
            click.echo("   (orbit login / mount / status work without Tk.)", err=True)
            sys.exit(1)
        raise

    try:
        run_widget()
    except Exception as e:
        # tkinter.TclError is raised when Tk is installed but there is no
        # display to open (SSH session, container, CI). Avoid importing Tk
        # here just to name the class.
        if type(e).__name__ == "TclError":
            click.echo(f"❌ The Orbit widget could not open a window: {e}", err=True)
            click.echo(
                "   It needs a graphical session (DISPLAY on Linux). "
                "orbit login / mount / status work without one.",
                err=True,
            )
            sys.exit(1)
        raise


if __name__ == "__main__":
    cli()
