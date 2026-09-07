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

"""Shared configuration, credential and URL resolution for Orbit.

This module is deliberately free of any GUI (Tk) import so that the CLI and
the WebDAV VFS can use it on headless machines. The widget imports from here
too, so all three faces of Orbit agree on:

* where the config file lives (``~/.orbit/config.json``),
* where the Gravity session token is stored (OS keyring first, plaintext
  config file as a fallback, ``ORBIT_TOKEN`` as an override), and
* how the Gravity API base URL is derived from the stored ``server`` value
  (``{server}/gravity`` by default, which is what the production nginx proxy
  expects; configurable for a direct-to-container URL).
"""

import json
import os
from typing import Any, Dict, Optional

# Path to Orbit Config
CONFIG_DIR = os.path.expanduser("~/.orbit")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
THEME_FILE = os.path.join(CONFIG_DIR, "widget_theme.json")

# Keyring slot used for the Gravity session token.
KEYRING_SERVICE = "gravity"
KEYRING_USERNAME = "token"

# Environment overrides (highest priority).
ENV_TOKEN = "ORBIT_TOKEN"
ENV_SERVER = "ORBIT_SERVER"
ENV_GRAVITY_URL = "ORBIT_GRAVITY_URL"
ENV_GRAVITY_PREFIX = "ORBIT_GRAVITY_PREFIX"

# Production nginx proxies ``/gravity/`` to the Gravity container, so the
# API lives at ``{server}/gravity/v1/...``. Set ``gravity_prefix`` to ``""``
# in config.json (or ``ORBIT_GRAVITY_PREFIX=""``) to talk to a container
# directly, or set ``gravity_url`` / ``ORBIT_GRAVITY_URL`` to a full base URL.
DEFAULT_GRAVITY_PREFIX = "/gravity"

# File extensions treated as binary by the widget and the VFS (base64 on the
# wire, never diffed as text). Shared here so both agree.
BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".pdf",
    ".docx",
    ".xlsx",
    ".pptx",
    ".zip",
    ".tar",
    ".gz",
    ".db",
    ".sqlite",
    ".bin",
}


# ---------------------------------------------------------------------------
# Plaintext config file
# ---------------------------------------------------------------------------


def read_config_file(path: Optional[str] = None) -> Dict[str, Any]:
    """Read ``config.json`` as-is (no keyring lookup). Returns ``{}`` on any error."""
    path = path or CONFIG_FILE
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def write_config_file(data: Dict[str, Any], path: Optional[str] = None) -> bool:
    """Write ``config.json``. Returns True on success, False on any error."""
    path = path or CONFIG_FILE
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Keyring
# ---------------------------------------------------------------------------


def _keyring() -> Any:
    """Return the ``keyring`` module, or None if it is not importable."""
    try:
        import keyring

        return keyring
    except Exception:
        return None


def keyring_get_token() -> Optional[str]:
    """Return the token stored in the OS keyring, or None if absent/unavailable."""
    kr = _keyring()
    if kr is None:
        return None
    try:
        value = kr.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except Exception:
        return None
    return value or None


def keyring_set_token(token: str) -> bool:
    """Store the token in the OS keyring. Returns False if that was not possible."""
    kr = _keyring()
    if kr is None:
        return False
    try:
        kr.set_password(KEYRING_SERVICE, KEYRING_USERNAME, token)
        return True
    except Exception:
        return False


def keyring_delete_token() -> bool:
    """Remove the token from the OS keyring. Returns False if that was not possible."""
    kr = _keyring()
    if kr is None:
        return False
    try:
        kr.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Token resolution
# ---------------------------------------------------------------------------


def resolve_token(config: Optional[Dict[str, Any]] = None) -> str:
    """Return the Gravity session token, or ``""`` if none is available.

    Resolution order:

    1. ``ORBIT_TOKEN`` environment variable (override, e.g. for CI/servers),
    2. the OS keyring (where ``orbit login`` and the widget store it),
    3. the ``token`` field of the plaintext config file (legacy / no-keyring
       fallback written by :func:`save_orbit_config`).
    """
    env_token = os.environ.get(ENV_TOKEN, "").strip()
    if env_token:
        return env_token

    stored = keyring_get_token()
    if stored:
        return stored

    if config is None:
        config = read_config_file()
    return str(config.get("token") or "")


def token_source(config: Optional[Dict[str, Any]] = None) -> str:
    """Where :func:`resolve_token` found the token: ``"env"``, ``"keyring"``,
    ``"file"`` or ``""`` when there is none. Used by ``orbit status`` so it
    reports exactly what the VFS and the widget will send."""
    if os.environ.get(ENV_TOKEN, "").strip():
        return "env"
    if keyring_get_token():
        return "keyring"
    if config is None:
        config = read_config_file()
    if str(config.get("token") or ""):
        return "file"
    return ""


def load_orbit_config() -> Dict[str, Any]:
    """Load the config file and attach the resolved ``token`` (see :func:`resolve_token`)."""
    config = read_config_file()
    token = resolve_token(config)
    if token:
        config["token"] = token
    elif "token" in config:
        config.pop("token", None)
    return config


def save_orbit_config(data: Dict[str, Any]) -> None:
    """Persist config. The ``token`` goes to the keyring; everything else to the file.

    If the keyring is unavailable the token is written to the plaintext file
    so that a login still works; :func:`resolve_token` reads it back from
    there. An empty/None token clears the keyring entry.
    """
    write_data = dict(data)
    token = write_data.pop("token", None)

    if token is not None:
        if token:
            if not keyring_set_token(str(token)):
                write_data["token"] = token
        else:
            keyring_delete_token()

    write_config_file(write_data)


# ---------------------------------------------------------------------------
# Server / Gravity base URL resolution
# ---------------------------------------------------------------------------


def resolve_server(config: Optional[Dict[str, Any]] = None) -> str:
    """Return the configured server origin (no trailing slash), or ``""``.

    ``ORBIT_SERVER`` overrides the ``server`` field of the config file.
    """
    env_server = os.environ.get(ENV_SERVER, "").strip()
    if env_server:
        return env_server.rstrip("/")
    if config is None:
        config = read_config_file()
    return str(config.get("server") or "").strip().rstrip("/")


def _normalise_prefix(prefix: Any) -> str:
    text = str(prefix or "").strip().strip("/")
    return "/" + text if text else ""


def resolve_gravity_base_url(config: Optional[Dict[str, Any]] = None) -> str:
    """Return the Gravity API base URL (no trailing slash), or ``""`` if unknown.

    Resolution order:

    1. ``ORBIT_GRAVITY_URL`` env var or ``gravity_url`` config field: a full
       base URL, used verbatim (e.g. ``http://127.0.0.1:8000`` for a
       direct-to-container connection).
    2. ``{server}{prefix}`` where ``prefix`` is ``ORBIT_GRAVITY_PREFIX``, the
       ``gravity_prefix`` config field, or ``/gravity`` by default (the path
       the production nginx proxies to the Gravity container).

    Endpoints are appended to this, e.g. ``{base}/v1/workspace/list``.
    """
    if config is None:
        config = read_config_file()

    explicit = os.environ.get(ENV_GRAVITY_URL, "").strip()
    if not explicit:
        explicit = str(config.get("gravity_url") or "").strip()
    if explicit:
        return explicit.rstrip("/")

    server = resolve_server(config)
    if not server:
        return ""

    prefix = os.environ.get(ENV_GRAVITY_PREFIX)
    if prefix is None:
        prefix = config.get("gravity_prefix", DEFAULT_GRAVITY_PREFIX)
    return server + _normalise_prefix(prefix)


def gravity_api_url(path: str, config: Optional[Dict[str, Any]] = None) -> str:
    """Build a full Gravity API URL for ``path`` (e.g. ``/v1/workspace/list``).

    Returns ``""`` when no server is configured.
    """
    base = resolve_gravity_base_url(config)
    if not base:
        return ""
    return base + "/" + path.lstrip("/")
