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
@click.option("--workspace", default="~/orbit", help="Local workspace directory")
def mount(workspace):
    """Fetch allowed repos → local workspace."""
    config = _load_orbit_config()
    if not config.get("server"):
        click.echo("❌ Not logged in. Run 'orbit login' first.")
        return

    workspace = os.path.expanduser(workspace)
    os.makedirs(workspace, exist_ok=True)

    # Phase 2: fetch repo list from Gravity server API
    click.echo(f"\n🛸 Connecting to {config['server']}...")
    click.echo("   ⏳ Phase 2: Server-side mount coming soon.")
    click.echo(f"   Workspace ready at: {workspace}")


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


if __name__ == "__main__":
    cli()
