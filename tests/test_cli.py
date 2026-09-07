# Copyright (c) 2026, Rokct Intelligence (pty) Ltd.
# For license information, please see license.txt

"""CLI entry points: headless import, version, login/status, mount dispatch, widget without Tk."""

import json
import os
import subprocess
import sys
import textwrap

import pytest
from click.testing import CliRunner

import orbit
import orbit.config as cfg

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_cli(args, **kwargs):
    from orbit.cli import cli

    return CliRunner().invoke(cli, args, catch_exceptions=False, **kwargs)


def test_cli_runs_headless_without_tk_in_a_fresh_interpreter(tmp_path):
    """`orbit status` must work when tkinter cannot be imported at all."""
    script = textwrap.dedent(
        """
        import sys
        sys.modules["tkinter"] = None      # make `import tkinter` fail, even if Tk is installed
        sys.modules["keyring"] = None
        import orbit.cli
        assert "orbit.widget" not in sys.modules, "widget (and Tk) must not be imported eagerly"
        from click.testing import CliRunner
        r = CliRunner().invoke(orbit.cli.cli, ["status"])
        assert r.exit_code == 0, r.output
        assert "Orbit Status" in r.output, r.output
        r = CliRunner().invoke(orbit.cli.cli, ["--version"])
        assert r.exit_code == 0, r.output
        print("OK", r.output.strip())
        """
    )
    env = dict(os.environ, HOME=str(tmp_path), PYTHONPATH=REPO_ROOT)
    for var in (
        cfg.ENV_TOKEN,
        cfg.ENV_SERVER,
        cfg.ENV_GRAVITY_URL,
        cfg.ENV_GRAVITY_PREFIX,
    ):
        env.pop(var, None)
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_version_single_source_of_truth_is_version_json():
    with open(os.path.join(REPO_ROOT, "version.json"), encoding="utf-8") as f:
        expected = json.load(f)["version"]
    assert orbit.__version__ == expected
    result = _run_cli(["--version"])
    assert result.exit_code == 0
    assert expected in result.output


def test_status_when_not_logged_in():
    result = _run_cli(["status"])
    assert result.exit_code == 0
    assert "Not connected" in result.output


def test_login_then_status_uses_keyring_and_gravity_prefix(
    isolated_config, fake_keyring
):
    result = _run_cli(
        ["login", "--server", "https://platform.rokct.ai/", "--token", "tok123"]
    )
    assert result.exit_code == 0, result.output
    assert "https://platform.rokct.ai/gravity" in result.output

    on_disk = json.loads(isolated_config.read_text(encoding="utf-8"))
    assert on_disk["server"] == "https://platform.rokct.ai"
    assert "token" not in on_disk
    assert fake_keyring[(cfg.KEYRING_SERVICE, cfg.KEYRING_USERNAME)] == "tok123"

    result = _run_cli(["status"])
    assert "Server: https://platform.rokct.ai" in result.output
    assert "Gravity API: https://platform.rokct.ai/gravity" in result.output
    assert "configured (token from OS keyring)" in result.output


def test_status_reports_the_token_source_the_vfs_will_use(
    isolated_config, fake_keyring, monkeypatch
):
    cfg.save_orbit_config({"server": "https://platform.rokct.ai"})
    result = _run_cli(["status"])
    assert "no token" in result.output

    isolated_config.write_text(
        json.dumps({"server": "https://platform.rokct.ai", "token": "plain"}),
        encoding="utf-8",
    )
    assert "config.json (plaintext" in _run_cli(["status"]).output

    monkeypatch.setenv(cfg.ENV_TOKEN, "envtok")
    assert "ORBIT_TOKEN environment variable" in _run_cli(["status"]).output


# ---------------------------------------------------------------------------
# status / mount: where the repository list comes from
# ---------------------------------------------------------------------------


def _fake_gravity(monkeypatch, repos=None):
    """Route the CLI's Gravity calls to test_vfs.FakeGravity (no real network)."""
    import urllib.request

    from tests.test_vfs import FakeGravity

    fake = FakeGravity(repos=repos)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return fake


def test_status_warns_when_server_cannot_list_repos_and_no_override(
    isolated_config, fake_keyring, monkeypatch
):
    import orbit.vfs as vfs

    cfg.save_orbit_config({"server": "https://platform.rokct.ai", "token": "tok"})
    fake = _fake_gravity(monkeypatch)  # today's server: 422 without repo_name

    result = _run_cli(["status"])
    assert result.exit_code == 0, result.output
    assert "no repository list available" in result.output
    assert "no repository-enumeration route" in result.output
    assert "NOT verified" in result.output
    assert '"repos"' in result.output and "config.json" in result.output
    assert vfs.REPO_LIST_NOTICE_NAME in result.output
    for name in vfs.DEFAULT_REPOS:
        assert name in result.output
    assert fake.requests[-1]["path"].endswith("/v1/workspace/list")


def test_status_reports_repos_from_config_override_without_network(
    isolated_config, fake_keyring
):
    cfg.save_orbit_config(
        {"server": "https://platform.rokct.ai", "token": "tok", "repos": ["rcore"]}
    )
    result = _run_cli(["status"])
    assert result.exit_code == 0, result.output
    assert "Repos: 1 from 'repos' in ~/.orbit/config.json (rcore)" in result.output
    assert "fallback" not in result.output


def test_status_reports_repos_listed_by_the_server(
    isolated_config, fake_keyring, monkeypatch
):
    cfg.save_orbit_config({"server": "https://platform.rokct.ai", "token": "tok"})
    _fake_gravity(monkeypatch, repos=["rcore", {"path": "control"}])
    result = _run_cli(["status"])
    assert "Repos: 2 listed by the Gravity server (rcore, control)" in result.output
    assert "fallback" not in result.output


def test_status_reports_unreachable_server_plainly(isolated_config, fake_keyring):
    # conftest blocks urlopen entirely: the server cannot be reached.
    cfg.save_orbit_config({"server": "https://platform.rokct.ai", "token": "tok"})
    result = _run_cli(["status"])
    assert result.exit_code == 0, result.output
    assert "could not reach Gravity" in result.output
    assert "NOT verified" in result.output


def test_widget_without_display_prints_friendly_message(monkeypatch):
    import types

    class TclError(Exception):
        pass

    def run_widget():
        raise TclError("no display name and no $DISPLAY environment variable")

    monkeypatch.setitem(
        sys.modules, "orbit.widget", types.SimpleNamespace(run_widget=run_widget)
    )
    from orbit.cli import cli

    result = CliRunner().invoke(cli, ["widget"])
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert "could not open a window" in result.output
    assert "DISPLAY" in result.output
    assert "Traceback" not in result.output


def test_widget_without_tk_prints_friendly_message_not_traceback(monkeypatch):
    monkeypatch.setitem(sys.modules, "tkinter", None)
    monkeypatch.delitem(sys.modules, "orbit.widget", raising=False)

    from orbit.cli import cli

    result = CliRunner().invoke(cli, ["widget"])
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert "Tk" in result.output
    assert "python3-tk" in result.output
    assert "Traceback" not in result.output


# ---------------------------------------------------------------------------
# mount: platform dispatch (VFS thread and the wait loop are stubbed)
# ---------------------------------------------------------------------------


@pytest.fixture
def mount_env(isolated_config, fake_keyring, monkeypatch):
    import orbit.cli as cli_mod

    cfg.save_orbit_config({"server": "https://platform.rokct.ai", "token": "t"})
    calls = []
    monkeypatch.setattr(
        cli_mod, "_start_vfs_thread", lambda port: calls.append(("vfs", port))
    )
    monkeypatch.setattr(
        cli_mod,
        "_wait_until_interrupted",
        lambda label, unmount: calls.append(("wait", label)),
    )
    monkeypatch.setattr("time.sleep", lambda *_: None)
    return calls


class FakeRun:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr
        self.commands = []

    def __call__(self, cmd, **_kwargs):
        self.commands.append(list(cmd))
        return self


def test_mount_not_logged_in(mount_env, isolated_config):
    isolated_config.write_text("{}", encoding="utf-8")
    result = _run_cli(["mount"])
    assert "Not logged in" in result.output
    assert mount_env == []


def test_mount_windows_path_is_preserved(mount_env, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    run = FakeRun(stdout="Drive Z: is now connected to http://127.0.0.1:8080/.")
    monkeypatch.setattr("subprocess.run", run)

    result = _run_cli(["mount"])
    assert result.exit_code == 0, result.output
    assert run.commands[0] == [
        "net",
        "use",
        "*",
        "http://127.0.0.1:8080/",
        "/persistent:no",
    ]
    assert "mounted at Z:" in result.output
    assert ("vfs", 8080) in mount_env and ("wait", "Z:") in mount_env


def test_mount_windows_failure_gives_webclient_hint(mount_env, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        "subprocess.run", FakeRun(returncode=2, stderr="System error 67")
    )
    result = _run_cli(["mount"])
    assert "System error 67" in result.output
    assert "net start WebClient" in result.output
    assert not any(c[0] == "wait" for c in mount_env)


def test_mount_macos_uses_mount_webdav(mount_env, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    run = FakeRun(returncode=0)
    monkeypatch.setattr("subprocess.run", run)

    result = _run_cli(["mount", "--port", "9090"])
    assert result.exit_code == 0, result.output
    cmd = run.commands[0]
    assert cmd[0] == "mount_webdav"
    assert "http://127.0.0.1:9090/" in cmd
    assert cmd[-1] == os.path.join(str(tmp_path), "Gravity")
    assert ("vfs", 9090) in mount_env
    assert "mounted at" in result.output


def test_mount_warns_about_the_unverified_fallback_repo_list(mount_env, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("shutil.which", lambda name: None)
    _fake_gravity(monkeypatch)
    result = _run_cli(["mount"])
    assert result.exit_code == 0, result.output
    assert "no repository list available" in result.output
    assert "config.json" in result.output


def test_mount_linux_without_gio_prints_exact_commands(mount_env, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("shutil.which", lambda name: None)
    result = _run_cli(["mount"])
    assert result.exit_code == 0, result.output
    assert "gio mount dav://127.0.0.1:8080/" in result.output
    assert "mount -t davfs http://127.0.0.1:8080/" in result.output
    assert "not auto-mounted" in result.output
    assert "Success!" not in result.output
    assert ("wait", "http://127.0.0.1:8080/") in mount_env


def test_mount_linux_with_gio_mounts(mount_env, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/gio")
    run = FakeRun(returncode=0)
    monkeypatch.setattr("subprocess.run", run)
    result = _run_cli(["mount"])
    assert run.commands[0] == ["gio", "mount", "dav://127.0.0.1:8080/"]
    assert "Mounted with gio" in result.output


def test_mount_unknown_platform_is_actionable(mount_env, monkeypatch):
    monkeypatch.setattr(sys, "platform", "freebsd14")
    result = _run_cli(["mount"])
    assert result.exit_code == 0, result.output
    assert "not supported on 'freebsd14'" in result.output
    assert "http://127.0.0.1:8080/" in result.output
