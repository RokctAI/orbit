# Copyright (c) 2026, Rokct Intelligence (pty) Ltd.
# For license information, please see license.txt

"""Shared fixtures.

Every test runs against an isolated ``~/.orbit`` under ``tmp_path`` with the
``ORBIT_*`` environment overrides cleared and *no* OS keyring, unless the
test opts into ``fake_keyring`` (an in-memory stand-in for a working OS
keyring). Only the network (``urllib.request.urlopen``) is ever mocked; the
real config, CLI and VFS code paths are exercised.
"""

import sys
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

import orbit.config as orbit_config

ENV_VARS = (
    orbit_config.ENV_TOKEN,
    orbit_config.ENV_SERVER,
    orbit_config.ENV_GRAVITY_URL,
    orbit_config.ENV_GRAVITY_PREFIX,
)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Point orbit.config at a throwaway ~/.orbit and block the real keyring."""
    config_dir = tmp_path / ".orbit"
    monkeypatch.setattr(orbit_config, "CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(orbit_config, "CONFIG_FILE", str(config_dir / "config.json"))
    monkeypatch.setattr(
        orbit_config, "THEME_FILE", str(config_dir / "widget_theme.json")
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    # ``None`` in sys.modules makes ``import keyring`` raise ImportError.
    monkeypatch.setitem(sys.modules, "keyring", None)

    # No test may reach a real Gravity. Tests that need a server replace this
    # with an in-process fake (see ``gravity`` in test_vfs.py).
    def no_network(req, timeout=None):
        raise urllib.error.URLError("network access is disabled in tests")

    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    return config_dir / "config.json"


@pytest.fixture
def fake_keyring(monkeypatch, isolated_config):
    """An in-memory module that behaves like a working OS keyring."""
    store = {}

    def get_password(service, username):
        return store.get((service, username))

    def set_password(service, username, password):
        store[(service, username)] = password

    def delete_password(service, username):
        if (service, username) not in store:
            raise RuntimeError("PasswordDeleteError")
        del store[(service, username)]

    module = SimpleNamespace(
        get_password=get_password,
        set_password=set_password,
        delete_password=delete_password,
    )
    monkeypatch.setitem(sys.modules, "keyring", module)
    return store
