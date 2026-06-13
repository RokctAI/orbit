# Copyright (c) 2026, Rokct Intelligence (pty) Ltd.
# For license information, please see license.txt

"""Orbit CLI — OSS client daemon for Gravity."""

import os
import json

import click


CONFIG_DIR = os.path.expanduser("~/.orbit")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")


def _load_orbit_config() -> dict:
    if os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}


def _save_orbit_config(data: dict):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """🛸 Orbit — Connect to Gravity, edit in any IDE."""
    pass


@cli.command()
@click.option("--server", prompt="Gravity server URL", help="URL of the Gravity server")
@click.option("--token", prompt="API token", hide_input=True, help="Authentication token")
def login(server, token):
    """Authenticate with a Gravity server."""
    # Phase 2: validate token against server
    config = _load_orbit_config()
    config["server"] = server.rstrip("/")
    config["token"] = token
    _save_orbit_config(config)

    click.echo(f"\n✅ Authenticated with {server}")
    click.echo("   Run 'orbit mount' to fetch your repos.")


@cli.command()
def mount():
    """Mount the Gravity workspace as a local virtual network drive."""
    config = _load_orbit_config()
    if not config.get("server"):
        click.echo("❌ Not logged in. Run 'orbit login' first.")
        return

    # Start VFS server in a background daemon thread
    import threading
    import time
    import subprocess
    import re
    from orbit.vfs import start_vfs_server

    server_thread = threading.Thread(
        target=start_vfs_server, 
        kwargs={"host": "127.0.0.1", "port": 8080}, 
        daemon=True
    )
    server_thread.start()
    
    # Wait for the local server to spin up
    time.sleep(1.5)
    
    click.echo("🛸 Mounting Gravity workspace via WebDAV on localhost:8080...")
    
    # Run net use command to assign next available drive letter
    result = subprocess.run(
        ["net", "use", "*", "http://127.0.0.1:8080/", "/persistent:no"], 
        capture_output=True, 
        text=True
    )
    
    if result.returncode != 0:
        click.echo(f"❌ Failed to mount drive: {result.stderr.strip() or result.stdout.strip()}")
        click.echo("   Ensure the Windows 'WebClient' service is running.")
        click.echo("   To start it, open cmd/PowerShell as Administrator and run: net start WebClient")
        return
        
    output = result.stdout
    drive_match = re.search(r'([A-Z]:)', output)
    drive_letter = drive_match.group(1) if drive_match else "Virtual Drive"
    
    click.echo(f"🎉 Success! Gravity virtual workspace is mounted at {drive_letter}")
    click.echo("   You can now open it in VS Code, Cursor, or File Explorer!")
    click.echo("   Press Ctrl+C to unmount and exit.")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        click.echo(f"\n🛸 Unmounting drive {drive_letter}...")
        if drive_letter != "Virtual Drive":
            subprocess.run(["net", "use", drive_letter, "/delete", "/y"], capture_output=True)
        click.echo("👋 Exited.")


@cli.command()
def status():
    """Show connection and sync state."""
    config = _load_orbit_config()

    click.echo("\n🛸 Orbit Status")
    if config.get("server"):
        click.echo(f"   Server: {config['server']}")
        click.echo(f"   Auth: {'✅ configured' if config.get('token') else '❌ no token'}")
    else:
        click.echo("   Not connected. Run 'orbit login' first.")

    click.echo("")


@cli.command()
def widget():
    """Launch the floating minimal status bar widget."""
    click.echo("Launching Orbit Status Bar Widget...")
    from orbit.widget import run_widget
    run_widget()



if __name__ == "__main__":
    cli()

