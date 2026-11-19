# Copyright (c) 2026, Rokct Intelligence (pty) Ltd.
# For license information, please see license.txt

"""`orbit pr`: the PR opens with an intent the user confirmed."""

import pytest
from click.testing import CliRunner

import orbit.config as cfg
import orbit.vfs as vfs


@pytest.fixture
def gravity(monkeypatch, isolated_config):
    cfg.save_orbit_config({"server": "https://platform.rokct.ai", "token": "tok"})
    calls = []
    state = {
        "draft": {
            "status": True,
            "intent": "fix: typo; docs: add install step",
            "commits": [
                {"subject": "docs: add install step"},
                {"subject": "fix: typo"},
            ],
        }
    }

    def fake(method, endpoint, params=None, data=None, config=None, timeout=30):
        calls.append((method, endpoint, params, data))
        if endpoint == "/v1/workspace/pr-draft":
            return state["draft"], None
        if endpoint == "/v1/workspace/open-pr":
            return {
                "status": True,
                "pr_results": {"plain": "https://github.com/x/plain/pull/1"},
            }, None
        raise AssertionError(endpoint)

    monkeypatch.setattr(vfs, "gravity_api_request", fake)
    return calls, state


def run(args, input=None):
    from orbit.cli import cli

    return CliRunner().invoke(cli, args, input=input, catch_exceptions=False)


def opened(calls):
    return [c[3] for c in calls if c[1] == "/v1/workspace/open-pr"]


def test_user_confirms_the_drafted_intent(gravity):
    calls, _ = gravity
    result = run(["pr", "plain"], input="\ny\n")
    assert result.exit_code == 0, result.output
    assert "- fix: typo" in result.output
    assert opened(calls) == [
        {
            "repo_name": "plain",
            "intent": "fix: typo; docs: add install step",
            "title": "",
        }
    ]
    assert "pull/1" in result.output


def test_user_rewrites_the_intent(gravity):
    calls, _ = gravity
    result = run(["pr", "plain"], input="Make the install step correct.\ny\n")
    assert result.exit_code == 0, result.output
    assert opened(calls)[0]["intent"] == "Make the install step correct."


def test_declining_opens_nothing(gravity):
    calls, _ = gravity
    result = run(["pr", "plain"], input="\nn\n")
    assert "Cancelled." in result.output
    assert opened(calls) == []


def test_intent_flag_skips_the_draft(gravity):
    calls, _ = gravity
    result = run(["pr", "plain", "--intent", "Ship the fix.", "--yes"])
    assert result.exit_code == 0, result.output
    assert [c[1] for c in calls] == ["/v1/workspace/open-pr"]
    assert opened(calls)[0]["intent"] == "Ship the fix."


def test_no_commits_means_no_pr(gravity):
    calls, state = gravity
    state["draft"] = {"status": True, "intent": "", "commits": []}
    result = run(["pr", "plain"])
    assert "no new commits" in result.output
    assert opened(calls) == []


def test_requires_login(isolated_config):
    result = run(["pr", "plain"])
    assert result.exit_code == 1
    assert "orbit login" in result.output
