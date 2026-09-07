# Copyright (c) 2026, Rokct Intelligence (pty) Ltd.
# For license information, please see license.txt

"""Token and Gravity base-URL resolution shared by the CLI, VFS and widget."""

import json

import orbit.config as cfg

SERVICE = (cfg.KEYRING_SERVICE, cfg.KEYRING_USERNAME)


def _file(path):
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Token resolution
# ---------------------------------------------------------------------------


def test_login_stores_token_in_keyring_and_vfs_side_reads_it_back(
    isolated_config, fake_keyring
):
    cfg.save_orbit_config({"server": "https://control.example.com", "token": "SECRET"})

    on_disk = _file(isolated_config)
    assert on_disk == {"server": "https://control.example.com"}, (
        "token must not be written in plaintext"
    )
    assert fake_keyring[SERVICE] == "SECRET"

    # This is the lookup the VFS performs before every request.
    assert cfg.resolve_token() == "SECRET"
    assert cfg.load_orbit_config()["token"] == "SECRET"


def test_token_falls_back_to_plaintext_file_when_keyring_unavailable(isolated_config):
    cfg.save_orbit_config({"server": "https://x.example", "token": "PLAIN"})

    assert _file(isolated_config)["token"] == "PLAIN"
    assert cfg.resolve_token() == "PLAIN"
    assert cfg.load_orbit_config()["token"] == "PLAIN"


def test_keyring_token_beats_plaintext_token(isolated_config, fake_keyring):
    isolated_config.parent.mkdir(parents=True)
    isolated_config.write_text(json.dumps({"token": "old-plaintext"}), encoding="utf-8")
    fake_keyring[SERVICE] = "from-keyring"

    assert cfg.resolve_token() == "from-keyring"


def test_env_token_overrides_keyring_and_file(
    isolated_config, fake_keyring, monkeypatch
):
    isolated_config.parent.mkdir(parents=True)
    isolated_config.write_text(json.dumps({"token": "file"}), encoding="utf-8")
    fake_keyring[SERVICE] = "keyring"
    monkeypatch.setenv(cfg.ENV_TOKEN, "env-token")

    assert cfg.resolve_token() == "env-token"
    assert cfg.load_orbit_config()["token"] == "env-token"


def test_no_token_anywhere_yields_empty_and_no_token_key(isolated_config):
    cfg.save_orbit_config({"server": "https://x.example"})
    assert cfg.resolve_token() == ""
    assert "token" not in cfg.load_orbit_config()


def test_empty_token_clears_keyring_entry(fake_keyring):
    fake_keyring[SERVICE] = "stale"
    cfg.save_orbit_config({"server": "https://x.example", "token": ""})
    assert SERVICE not in fake_keyring
    assert cfg.resolve_token() == ""


def test_broken_keyring_backend_is_tolerated(
    isolated_config, fake_keyring, monkeypatch
):
    def explode(*_args, **_kwargs):
        raise RuntimeError("NoKeyringError")

    import sys

    broken = sys.modules["keyring"]
    setattr(broken, "get_password", explode)
    setattr(broken, "set_password", explode)

    cfg.save_orbit_config({"server": "https://x.example", "token": "T"})
    # Falls back to the plaintext file rather than losing the login.
    assert _file(isolated_config)["token"] == "T"
    assert cfg.resolve_token() == "T"


# ---------------------------------------------------------------------------
# Server / Gravity base URL resolution
# ---------------------------------------------------------------------------


def test_default_gravity_base_is_server_plus_gravity_prefix():
    config = {"server": "https://platform.rokct.ai"}
    assert cfg.resolve_gravity_base_url(config) == "https://platform.rokct.ai/gravity"
    assert cfg.gravity_api_url("/v1/workspace/list", config) == (
        "https://platform.rokct.ai/gravity/v1/workspace/list"
    )
    assert cfg.gravity_api_url("v1/handshake", config) == (
        "https://platform.rokct.ai/gravity/v1/handshake"
    )


def test_trailing_slashes_are_normalised():
    config = {"server": "https://platform.rokct.ai/", "gravity_prefix": "/gravity/"}
    assert (
        cfg.gravity_api_url("/v1/verify", config)
        == "https://platform.rokct.ai/gravity/v1/verify"
    )


def test_empty_prefix_gives_direct_to_container_url():
    config = {"server": "http://127.0.0.1:8000", "gravity_prefix": ""}
    assert cfg.gravity_api_url("/v1/workspace/list", config) == (
        "http://127.0.0.1:8000/v1/workspace/list"
    )


def test_custom_prefix_is_normalised():
    config = {"server": "https://x.example", "gravity_prefix": "api/gravity"}
    assert cfg.resolve_gravity_base_url(config) == "https://x.example/api/gravity"


def test_gravity_url_config_field_wins_over_server():
    config = {"server": "https://x.example", "gravity_url": "http://gravity:8000/"}
    assert cfg.gravity_api_url("/v1/verify", config) == "http://gravity:8000/v1/verify"


def test_env_gravity_url_overrides_config(monkeypatch):
    monkeypatch.setenv(cfg.ENV_GRAVITY_URL, "http://localhost:9000")
    config = {"server": "https://x.example", "gravity_url": "http://ignored"}
    assert (
        cfg.gravity_api_url("/v1/verify", config) == "http://localhost:9000/v1/verify"
    )


def test_env_prefix_override_including_empty(monkeypatch):
    config = {"server": "https://x.example"}
    monkeypatch.setenv(cfg.ENV_GRAVITY_PREFIX, "")
    assert cfg.resolve_gravity_base_url(config) == "https://x.example"
    monkeypatch.setenv(cfg.ENV_GRAVITY_PREFIX, "g")
    assert cfg.resolve_gravity_base_url(config) == "https://x.example/g"


def test_env_server_override(monkeypatch):
    monkeypatch.setenv(cfg.ENV_SERVER, "https://staging.example/")
    assert (
        cfg.resolve_server({"server": "https://prod.example"})
        == "https://staging.example"
    )
    assert cfg.resolve_gravity_base_url({"server": "https://prod.example"}) == (
        "https://staging.example/gravity"
    )


def test_no_server_configured_yields_empty_urls(isolated_config):
    assert cfg.resolve_server() == ""
    assert cfg.resolve_gravity_base_url() == ""
    assert cfg.gravity_api_url("/v1/verify") == ""


def test_widget_and_vfs_share_the_same_resolution_helpers(
    isolated_config, fake_keyring
):
    """The widget's load/save must be the shared implementation, not a copy."""
    import importlib.util

    spec = importlib.util.find_spec("orbit.widget")
    assert spec is not None and spec.origin is not None
    with open(spec.origin, encoding="utf-8") as f:
        source = f.read()
    assert "_shared_load_orbit_config()" in source
    assert "_shared_save_orbit_config(data)" in source
    assert 'f"{server}/gravity/v1' not in source, (
        "widget must build URLs via gravity_api_url"
    )
