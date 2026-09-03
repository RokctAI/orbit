# Copyright (c) 2026, Rokct Intelligence (pty) Ltd.
# For license information, please see license.txt

"""WebDAV VFS: request construction, path translation and repo listing.

The handler is driven over real HTTP (a live ``HTTPServer`` on a random
port); only the outbound call to Gravity (``urllib.request.urlopen``) is
replaced by an in-process fake that records what the VFS sent.
"""

import base64
import email.message
import http.client
import io
import json
import os
import shutil
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import HTTPServer

import pytest

import orbit.config as cfg
import orbit.vfs as vfs

SERVER = "https://platform.rokct.ai"
TOKEN = "gravity_sec_test"


class FakeGravity:
    """Stands in for the Gravity API behind ``urllib.request.urlopen``."""

    def __init__(self, files=None, contents=None, repos=None):
        self.files = files or []
        self.contents = contents or {}
        self.repos = repos  # None -> behave like today's server (422 without repo_name)
        self.requests = []
        # What POST /v1/workspace/file answers (HTTP 200 either way, like Gravity).
        self.write_response = {
            "status": True,
            "message": "Workspace changes processed",
            "results": {"control": "Pushed successfully"},
        }
        # ``(http_status, json_body)`` to answer the write with an HTTP error
        # instead (the current Gravity raises 409 on a patch conflict).
        self.write_error = None
        # Keys served in the pre-"encoding" shape ({"content", "is_binary"}).
        self.legacy_keys = set()

    def __call__(self, req, timeout=None):
        parsed = urllib.parse.urlparse(req.full_url)
        query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        body = json.loads(req.data.decode("utf-8")) if req.data else None
        self.requests.append(
            {
                "method": req.get_method(),
                "url": req.full_url,
                "path": parsed.path,
                "query": query,
                "auth": req.get_header("Authorization"),
                "body": body,
            }
        )

        if parsed.path.endswith("/v1/workspace/list"):
            if "repo_name" not in query:
                if self.repos is None:
                    return self._error(req.full_url, 422, "Field required: repo_name")
                return self._json({"repos": self.repos})
            return self._json({"files": self.files})

        if parsed.path.endswith("/v1/workspace/file"):
            if req.get_method() == "POST":
                if self.write_error is not None:
                    code, payload = self.write_error
                    return self._error_body(req.full_url, code, payload)
                return self._json(self.write_response)
            key = (query.get("repo_name"), query.get("path"))
            if key not in self.contents:
                return self._error(req.full_url, 404, "File not found")
            content = self.contents[key]
            if key in self.legacy_keys:
                # Older server shape: no "encoding", only "is_binary".
                if isinstance(content, bytes):
                    payload = base64.b64encode(content).decode("ascii")
                    return self._json({"content": payload, "is_binary": True})
                return self._json({"content": content, "is_binary": False})
            # Current Gravity contract: {"status", "content", "encoding"}.
            if isinstance(content, bytes):
                payload = base64.b64encode(content).decode("ascii")
                return self._json(
                    {"status": True, "content": payload, "encoding": "base64"}
                )
            return self._json({"status": True, "content": content, "encoding": "utf-8"})

        return self._error(req.full_url, 404, "Not Found")

    @staticmethod
    def _json(payload):
        # io.BytesIO already supports the context-manager protocol urlopen callers use.
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    @classmethod
    def _error(cls, url, code, detail):
        cls._error_body(url, code, {"detail": detail})

    @staticmethod
    def _error_body(url, code, payload):
        raise urllib.error.HTTPError(
            url,
            code,
            http.client.responses.get(code, "Error"),
            email.message.Message(),
            io.BytesIO(json.dumps(payload).encode()),
        )


FILES = [
    {"path": "README.md", "size": 5, "mtime": 1700000000},
    {"path": "src/app.py", "size": 11, "mtime": 1700000001},
    {"path": "src/lib/util.py", "size": 7, "mtime": 1700000002},
    {"path": "src/my file.py", "size": 3, "mtime": 1700000003},
    {"path": "docs/app.py", "size": 4, "mtime": 1700000004},
    {"path": "data.blob", "size": 6, "mtime": 1700000005},
]

ORIGINAL_APP = "import os\n\n\ndef main():\n    print('hi')\n\n\nmain()\n"


@pytest.fixture
def logged_in(fake_keyring):
    """A normal login: server in the file, token in the keyring only."""
    cfg.save_orbit_config({"server": SERVER, "token": TOKEN})


@pytest.fixture
def gravity(monkeypatch):
    fake = FakeGravity(
        files=FILES,
        contents={
            ("control", "src/app.py"): ORIGINAL_APP,
            ("control", "src/my file.py"): "x=1",
            ("control", "src/lib/util.py"): "util\n",
            ("control", "docs/app.py"): "doc\n",
            ("control", "logo.png"): b"\x89PNG\r\n\x1a\n\x00\x01",
            ("control", "data.blob"): b"\x00\x01\x02\xff\xfe\xfd",
            ("control", "no-newline.txt"): "first\nlast",
        },
    )
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return fake


@pytest.fixture
def dav():
    vfs.VFS_FILE_CACHE.clear()
    vfs._reset_repo_list_cache()
    server = HTTPServer(("127.0.0.1", 0), vfs.OrbitWebDAVHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = "127.0.0.1", server.server_port

    def call(method, path, headers=None, body=None):
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data

    yield call
    server.shutdown()
    server.server_close()
    vfs.VFS_FILE_CACHE.clear()
    vfs._reset_repo_list_cache()


def _hrefs(xml):
    import re

    return re.findall(r"<d:href>([^<]*)</d:href>", xml.decode("utf-8"))


# ---------------------------------------------------------------------------
# Request construction: prefix + token
# ---------------------------------------------------------------------------


def test_requests_use_gravity_prefix_and_keyring_token(logged_in, gravity, dav):
    status, _ = dav("PROPFIND", "/control/", headers={"Depth": "1"})
    assert status == 207

    req = gravity.requests[-1]
    assert req["url"].startswith(SERVER + "/gravity/v1/workspace/list?")
    assert req["query"] == {"repo_name": "control"}
    assert req["auth"] == f"Bearer {TOKEN}"


def test_direct_to_container_prefix_is_honoured(logged_in, gravity, dav, monkeypatch):
    monkeypatch.setenv(cfg.ENV_GRAVITY_URL, "http://127.0.0.1:8000")
    status, _ = dav("PROPFIND", "/control/", headers={"Depth": "1"})
    assert status == 207
    assert gravity.requests[-1]["url"].startswith(
        "http://127.0.0.1:8000/v1/workspace/list?"
    )


def test_not_logged_in_is_reported_not_sent(gravity, dav):
    status, body = dav("PROPFIND", "/control/", headers={"Depth": "1"})
    assert status == 500
    assert b"Not logged in" in body
    assert gravity.requests == []


# ---------------------------------------------------------------------------
# Repository listing at the drive root
# ---------------------------------------------------------------------------


def test_root_lists_repos_from_server_when_it_provides_them(logged_in, gravity, dav):
    gravity.repos = [{"path": "rcore", "url": "x"}, "control", {"name": "bench"}]
    status, xml = dav("PROPFIND", "/", headers={"Depth": "1"})
    assert status == 207
    assert _hrefs(xml) == ["/", "/rcore/", "/control/", "/bench/"]
    assert gravity.requests[-1]["path"].endswith("/v1/workspace/list")
    assert "repo_name" not in gravity.requests[-1]["query"]


def test_root_falls_back_to_default_repos_when_server_cannot_list(
    logged_in, gravity, dav
):
    # Today's Gravity requires repo_name on /v1/workspace/list (422 without it).
    status, xml = dav("PROPFIND", "/", headers={"Depth": "1"})
    assert status == 207
    hrefs = _hrefs(xml)
    assert hrefs[: 1 + len(vfs.DEFAULT_REPOS)] == ["/"] + [
        f"/{name}/" for name in vfs.DEFAULT_REPOS
    ]
    # The unverified list is never presented as real without saying so.
    assert hrefs[-1] == f"/{vfs.REPO_LIST_NOTICE_NAME}"
    text = xml.decode("utf-8")
    notice_block = text.split(f"<d:href>/{vfs.REPO_LIST_NOTICE_NAME}</d:href>", 1)[1]
    assert "<d:resourcetype/>" in notice_block.split("</d:response>", 1)[0]


def test_root_notice_explains_the_fallback_and_how_to_fix_it(logged_in, gravity, dav):
    status, body = dav("GET", f"/{vfs.REPO_LIST_NOTICE_NAME}")
    assert status == 200
    text = body.decode("utf-8")
    assert "could not get the list of repositories" in text
    assert "no repository-enumeration route" in text, "422 must be explained"
    assert "NOT been verified" in text
    assert '"repos"' in text and "config.json" in text
    for name in vfs.DEFAULT_REPOS:
        assert name in text

    status, xml = dav(
        "PROPFIND", f"/{vfs.REPO_LIST_NOTICE_NAME}", headers={"Depth": "0"}
    )
    assert status == 207
    assert _hrefs(xml) == [f"/{vfs.REPO_LIST_NOTICE_NAME}"]
    assert f"<d:getcontentlength>{len(body)}</d:getcontentlength>" in xml.decode()

    # Not writable: it is an explanation, not a workspace file.
    assert dav("PUT", f"/{vfs.REPO_LIST_NOTICE_NAME}", body=b"x")[0] == 403


def test_root_notice_names_an_unreachable_server(logged_in, dav):
    # conftest blocks the network: the server cannot be reached at all.
    status, body = dav("GET", f"/{vfs.REPO_LIST_NOTICE_NAME}")
    assert status == 200
    assert "could not reach Gravity" in body.decode("utf-8")


def test_root_notice_is_absent_when_the_list_is_authoritative(logged_in, gravity, dav):
    gravity.repos = ["rcore", "control"]
    status, xml = dav("PROPFIND", "/", headers={"Depth": "1"})
    assert _hrefs(xml) == ["/", "/rcore/", "/control/"]
    assert dav("GET", f"/{vfs.REPO_LIST_NOTICE_NAME}")[0] == 404
    assert (
        dav("PROPFIND", f"/{vfs.REPO_LIST_NOTICE_NAME}", headers={"Depth": "0"})[0]
        == 404
    )

    vfs._reset_repo_list_cache()
    config = cfg.load_orbit_config()
    config["repos"] = ["alpha"]
    cfg.save_orbit_config(config)
    status, xml = dav("PROPFIND", "/", headers={"Depth": "1"})
    assert _hrefs(xml) == ["/", "/alpha/"]
    assert dav("GET", f"/{vfs.REPO_LIST_NOTICE_NAME}")[0] == 404


def test_resolve_repo_list_reports_its_source():
    config = {"server": SERVER, "token": TOKEN}

    def unsupported(method, endpoint):
        return None, vfs.GravityError("Field required: repo_name", status=422)

    names, source, detail = vfs.resolve_repo_list(config, unsupported)
    assert (names, source) == (list(vfs.DEFAULT_REPOS), vfs.REPO_SOURCE_FALLBACK)
    assert "no repository-enumeration route" in detail

    def offline(method, endpoint):
        return None, vfs.GravityError("<urlopen error [Errno 111] refused>")

    _names, source, detail = vfs.resolve_repo_list(config, offline)
    assert source == vfs.REPO_SOURCE_FALLBACK
    assert detail.startswith("could not reach Gravity")

    def listing(method, endpoint):
        return {"repos": ["rcore"]}, None

    assert vfs.resolve_repo_list(config, listing) == (
        ["rcore"],
        vfs.REPO_SOURCE_SERVER,
        "",
    )
    assert vfs.resolve_repo_list(dict(config, repos=["x"]), listing) == (
        ["x"],
        vfs.REPO_SOURCE_CONFIG,
        "",
    )


def test_root_prefers_repos_from_config_file_without_calling_server(
    logged_in, gravity, dav
):
    config = cfg.load_orbit_config()
    config["repos"] = ["alpha", "beta/", " gamma "]
    cfg.save_orbit_config(config)

    status, xml = dav("PROPFIND", "/", headers={"Depth": "1"})
    assert status == 207
    assert _hrefs(xml) == ["/", "/alpha/", "/beta/", "/gamma/"]
    assert gravity.requests == []


def test_server_repo_list_is_cached(logged_in, gravity, dav):
    gravity.repos = ["rcore"]
    dav("PROPFIND", "/", headers={"Depth": "1"})
    dav("PROPFIND", "/", headers={"Depth": "1"})
    list_calls = [r for r in gravity.requests if "repo_name" not in r["query"]]
    assert len(list_calls) == 1


def test_repo_names_from_payload_shapes():
    assert vfs._repo_names_from_payload(
        {"repos": ["a", {"path": "b"}, {"name": "c"}, 7]}
    ) == ["a", "b", "c"]
    assert vfs._repo_names_from_payload({"repositories": ["x"]}) == ["x"]
    assert vfs._repo_names_from_payload(["a", "a", ""]) == ["a"]
    assert vfs._repo_names_from_payload({"files": []}) == []
    assert vfs._repo_names_from_payload(None) == []


# ---------------------------------------------------------------------------
# Path translation
# ---------------------------------------------------------------------------


def test_repo_root_keeps_tree_structure(logged_in, gravity, dav):
    """Nested files must not be flattened to the repo root; dirs are collections."""
    status, xml = dav("PROPFIND", "/control/", headers={"Depth": "1"})
    assert status == 207
    hrefs = _hrefs(xml)
    assert hrefs[0] == "/control/"
    assert "/control/README.md" in hrefs
    assert "/control/data.blob" in hrefs
    assert "/control/src/" in hrefs and "/control/docs/" in hrefs
    assert "/control/app.py" not in hrefs, "src/app.py was advertised at the repo root"
    assert not any(h.endswith("util.py") for h in hrefs)
    text = xml.decode("utf-8")
    src_block = text.split("<d:href>/control/src/</d:href>", 1)[1].split(
        "</d:response>", 1
    )[0]
    assert "<d:collection/>" in src_block


def test_subdirectory_propfind_lists_direct_children_and_subdirs(
    logged_in, gravity, dav
):
    status, xml = dav("PROPFIND", "/control/src/", headers={"Depth": "1"})
    assert status == 207
    hrefs = _hrefs(xml)
    assert hrefs[0] == "/control/src/"
    assert "/control/src/app.py" in hrefs
    assert "/control/src/my file.py" in hrefs
    assert "/control/src/lib/" in hrefs, (
        "nested directory must be listed as a collection"
    )
    assert not any(h.endswith("util.py") for h in hrefs), (
        "nested file must not be flattened"
    )


def test_same_basename_in_different_directories_do_not_collide(logged_in, gravity, dav):
    assert dav("GET", "/control/src/app.py")[1] == ORIGINAL_APP.encode("utf-8")
    assert dav("GET", "/control/docs/app.py")[1] == b"doc\n"
    assert dav("GET", "/control/src/lib/util.py")[1] == b"util\n"
    status, xml = dav("PROPFIND", "/control/src/lib/util.py", headers={"Depth": "0"})
    assert status == 207
    assert _hrefs(xml) == ["/control/src/lib/util.py"]


def test_direct_children_helper():
    subdirs, children = vfs._direct_children(FILES, "")
    assert subdirs == ["src", "docs"]
    assert [c["path"] for c in children] == ["README.md", "data.blob"]
    subdirs, children = vfs._direct_children(FILES, "src")
    assert subdirs == ["lib"]
    assert [c["path"] for c in children] == ["src/app.py", "src/my file.py"]
    assert vfs._direct_children(FILES, "src/lib") == ([], [FILES[2]])


def test_get_translates_dav_path_to_repo_and_relative_path(logged_in, gravity, dav):
    status, body = dav("GET", "/control/src/app.py")
    assert status == 200
    assert body == ORIGINAL_APP.encode("utf-8")
    req = gravity.requests[-1]
    assert req["path"].endswith("/v1/workspace/file")
    assert req["query"] == {"repo_name": "control", "path": "src/app.py"}
    assert req["auth"] == f"Bearer {TOKEN}"


def test_get_decodes_percent_encoded_paths(logged_in, gravity, dav):
    status, body = dav("GET", "/control/src/my%20file.py")
    assert status == 200
    assert body == b"x=1"
    assert gravity.requests[-1]["query"]["path"] == "src/my file.py"


def test_get_missing_file_is_404_and_root_get_is_forbidden(logged_in, gravity, dav):
    assert dav("GET", "/control/nope.txt")[0] == 404
    assert dav("GET", "/control")[0] == 403


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def _git_apply_like_gravity(tmp_path, rel_path, original, patch):
    """Apply ``patch`` exactly the way gravity/server.py's apply_patch does."""
    repo = tmp_path / "repo"
    (repo / os.path.dirname(rel_path)).mkdir(parents=True, exist_ok=True)
    (repo / rel_path).write_text(original, encoding="utf-8", newline="")
    assert _git("init", "-q", cwd=repo).returncode == 0
    _git("config", "user.email", "t@example.com", cwd=repo)
    _git("config", "user.name", "t", cwd=repo)
    _git("add", ".", cwd=repo)
    assert _git("commit", "-q", "-m", "base", cwd=repo).returncode == 0
    patch_file = tmp_path / "change.patch"
    patch_file.write_text(patch, encoding="utf-8", newline="")
    result = _git("apply", "--ignore-whitespace", "--3way", str(patch_file), cwd=repo)
    return result, (repo / rel_path).read_bytes()


NEW_APP = "import os\nimport sys\n\n\ndef main():\n    print('hi')\n    print('bye')\n\n\nmain()\n"


@pytest.mark.skipif(
    shutil.which("git") is None, reason="git is required to verify the patch"
)
def test_put_text_sends_a_patch_that_git_apply_accepts(
    logged_in, gravity, dav, tmp_path
):
    dav("GET", "/control/src/app.py")
    new_body = NEW_APP.encode("utf-8")
    status, _ = dav(
        "PUT",
        "/control/src/app.py",
        headers={"Content-Length": str(len(new_body))},
        body=new_body,
    )
    assert status == 204

    post = gravity.requests[-1]
    assert post["method"] == "POST"
    assert post["path"].endswith("/v1/workspace/file")
    assert post["body"]["repo_name"] == "control"
    assert post["body"]["path"] == "src/app.py"
    assert post["body"]["type"] == "patch"
    assert post["body"]["is_binary"] is False

    patch = post["body"]["content"]
    assert patch.startswith("diff --git a/src/app.py b/src/app.py\nindex ")
    assert "\n--- a/src/app.py\n+++ b/src/app.py\n@@ " in patch
    assert "\n\n" not in patch, "each patch line must end in exactly one newline"
    assert "+import sys\n" in patch and "+    print('bye')\n" in patch

    result, applied = _git_apply_like_gravity(
        tmp_path, "src/app.py", ORIGINAL_APP, patch
    )
    assert result.returncode == 0, result.stderr
    assert applied == new_body


@pytest.mark.skipif(
    shutil.which("git") is None, reason="git is required to verify the patch"
)
def test_put_patch_handles_missing_newline_at_end_of_file(
    logged_in, gravity, dav, tmp_path
):
    dav("GET", "/control/no-newline.txt")
    new_body = b"first\nmiddle\nlast"
    status, _ = dav(
        "PUT",
        "/control/no-newline.txt",
        headers={"Content-Length": str(len(new_body))},
        body=new_body,
    )
    assert status == 204
    patch = gravity.requests[-1]["body"]["content"]
    assert "\\ No newline at end of file" in patch

    result, applied = _git_apply_like_gravity(
        tmp_path, "no-newline.txt", "first\nlast", patch
    )
    assert result.returncode == 0, result.stderr
    assert applied == new_body


def test_build_unified_patch_is_empty_for_identical_content():
    assert vfs.build_unified_patch("a\n", "a\n", "x.txt") == ""


def test_put_unchanged_text_is_a_noop(logged_in, gravity, dav):
    dav("GET", "/control/src/app.py")
    before = len(gravity.requests)
    body = ORIGINAL_APP.encode("utf-8")
    status, _ = dav(
        "PUT",
        "/control/src/app.py",
        headers={"Content-Length": str(len(body))},
        body=body,
    )
    assert status == 204
    assert len(gravity.requests) == before


def test_put_surfaces_server_conflict_and_keeps_cache_at_server_content(
    logged_in, gravity, dav
):
    dav("GET", "/control/src/app.py")
    gravity.write_response = {
        "status": False,
        "conflict": True,
        "conflicts": ["control/src/app.py"],
        "message": "Merge conflict occurred.",
    }
    new_body = NEW_APP.encode("utf-8")
    status, body = dav(
        "PUT",
        "/control/src/app.py",
        headers={"Content-Length": str(len(new_body))},
        body=new_body,
    )
    assert status == 409, "a conflict answered with HTTP 200 must not become a 204"
    assert b"Merge conflict" in body
    assert vfs.VFS_FILE_CACHE["control/src/app.py"] == ORIGINAL_APP

    # The next save must still be diffed against what the server has.
    gravity.write_response = {"status": True, "results": {"control": "OK"}}
    status, _ = dav(
        "PUT",
        "/control/src/app.py",
        headers={"Content-Length": str(len(new_body))},
        body=new_body,
    )
    assert status == 204
    assert "+import sys\n" in gravity.requests[-1]["body"]["content"]
    assert vfs.VFS_FILE_CACHE["control/src/app.py"] == NEW_APP


def test_put_against_old_server_no_changes_reply_is_not_reported_as_saved(
    logged_in, gravity, dav
):
    """Deploy skew: an older Gravity answers 200/"No changes to push" and drops
    the patch. Three successive saves must not all be told "saved"."""
    dav("GET", "/control/src/app.py")
    # Exact body the older server returns for a write it did not commit.
    gravity.write_response = {
        "status": True,
        "message": "Workspace changes processed",
        "results": {"control": "No changes to push"},
    }
    new_body = NEW_APP.encode("utf-8")
    status, body = dav(
        "PUT",
        "/control/src/app.py",
        headers={"Content-Length": str(len(new_body))},
        body=new_body,
    )
    assert status == 500, "a dropped write must not be reported as a save"
    assert b"No changes to push" in body and b"NOT persisted" in body
    assert gravity.requests[-1]["body"]["type"] == "patch"
    # Cache stays at the server's content so the next save re-sends the change.
    assert vfs.VFS_FILE_CACHE["control/src/app.py"] == ORIGINAL_APP

    status, _ = dav(
        "PUT",
        "/control/src/app.py",
        headers={"Content-Length": str(len(new_body))},
        body=new_body,
    )
    assert status == 500
    assert "+import sys\n" in gravity.requests[-1]["body"]["content"]


def test_put_binary_against_old_server_no_changes_reply_fails(logged_in, gravity, dav):
    dav("GET", "/control/logo.png")
    gravity.write_response = {
        "status": True,
        "results": {"control": "No changes to push"},
    }
    payload = b"\x89PNG\r\n\x1a\n\xff\x00"
    status, _ = dav(
        "PUT",
        "/control/logo.png",
        headers={"Content-Length": str(len(payload))},
        body=payload,
    )
    assert status == 500
    assert vfs.VFS_FILE_CACHE["control/logo.png"] == b"\x89PNG\r\n\x1a\n\x00\x01"


def test_put_paired_repo_partial_push_is_a_save(logged_in, gravity, dav):
    """Paired public/private repos: one side pushed means the change landed."""
    dav("GET", "/control/src/app.py")
    gravity.write_response = {
        "status": True,
        "results": {"control": "Public: Pushed, Private: No Changes"},
    }
    new_body = NEW_APP.encode("utf-8")
    status, _ = dav(
        "PUT",
        "/control/src/app.py",
        headers={"Content-Length": str(len(new_body))},
        body=new_body,
    )
    assert status == 204
    assert vfs.VFS_FILE_CACHE["control/src/app.py"] == NEW_APP


def test_put_without_cache_verifies_a_no_changes_reply_against_the_server(
    logged_in, gravity, dav
):
    """With nothing cached the client cannot know whether "No changes" is
    honest, so it re-reads the file: identical -> saved, different -> failed."""
    gravity.write_response = {
        "status": True,
        "results": {"control": "No changes to push"},
    }

    body = ORIGINAL_APP.encode("utf-8")  # what the server already has: a no-op save
    status, _ = dav(
        "PUT",
        "/control/src/app.py",
        headers={"Content-Length": str(len(body))},
        body=body,
    )
    assert status == 204
    assert gravity.requests[-1]["method"] == "GET", "the reply must be verified"
    assert vfs.VFS_FILE_CACHE["control/src/app.py"] == ORIGINAL_APP

    vfs.VFS_FILE_CACHE.clear()
    body = NEW_APP.encode("utf-8")  # differs from the server: the write was dropped
    status, resp = dav(
        "PUT",
        "/control/src/app.py",
        headers={"Content-Length": str(len(body))},
        body=body,
    )
    assert status == 500
    assert b"NOT persisted" in resp
    assert "control/src/app.py" not in vfs.VFS_FILE_CACHE


def test_write_failure_from_response_shapes():
    old_server = {
        "status": True,
        "message": "Workspace changes processed",
        "results": {"control": "No changes to push"},
    }
    assert vfs._write_failure_from_response(old_server)[0] == 500
    assert vfs._write_failure_from_response(old_server, content_changed=False) is None
    assert (
        vfs._write_failure_from_response(
            {"status": True, "results": {"control": "Pushed successfully"}}
        )
        is None
    )
    assert (
        vfs._write_failure_from_response(
            {
                "status": True,
                "results": {"x": "Public: No Changes, Private: No Changes"},
            }
        )[0]
        == 500
    )
    assert (
        vfs._write_failure_from_response({"status": False, "conflict": True})[0] == 409
    )
    assert vfs._write_failure_from_response("nonsense")[0] == 500


def test_put_conflict_answered_with_http_409_stays_a_409(logged_in, gravity, dav):
    """The current Gravity raises 409 on a patch conflict; it must reach the
    editor as 409, not be flattened into a 500."""
    dav("GET", "/control/src/app.py")
    gravity.write_error = (
        409,
        {
            "detail": {
                "message": "Merge conflict occurred.",
                "conflicts": ["control/src/app.py"],
            }
        },
    )
    new_body = NEW_APP.encode("utf-8")
    status, body = dav(
        "PUT",
        "/control/src/app.py",
        headers={"Content-Length": str(len(new_body))},
        body=new_body,
    )
    assert status == 409
    assert b"Merge conflict occurred." in body
    assert b"control/src/app.py" in body
    assert vfs.VFS_FILE_CACHE["control/src/app.py"] == ORIGINAL_APP


def test_put_other_http_errors_are_still_500(logged_in, gravity, dav):
    dav("GET", "/control/src/app.py")
    gravity.write_error = (500, {"detail": "Sync failed for control: Git Push Error"})
    new_body = NEW_APP.encode("utf-8")
    status, body = dav(
        "PUT",
        "/control/src/app.py",
        headers={"Content-Length": str(len(new_body))},
        body=new_body,
    )
    assert status == 500
    assert b"Git Push Error" in body


def test_api_request_preserves_http_status_and_body(logged_in, gravity):
    gravity.write_error = (409, {"detail": {"message": "Merge conflict occurred."}})
    payload, err = vfs.gravity_api_request(
        "POST", "/v1/workspace/file", data={"repo_name": "control"}
    )
    assert payload is None
    assert isinstance(err, vfs.GravityError)
    assert err.status == 409
    assert err.body == {"detail": {"message": "Merge conflict occurred."}}
    assert str(err) == "Merge conflict occurred."
    assert bool(err), "errors must stay truthy for `if err:` callers"

    _payload, err = vfs.gravity_api_request("GET", "/v1/workspace/list")
    assert err.status == 422
    assert str(err) == "Field required: repo_name"

    _payload, err = vfs.gravity_api_request("GET", "/v1/workspace/file", {"path": "x"})
    assert err.status == 404


def test_api_request_without_login_or_network_has_no_status(gravity):
    _payload, err = vfs.gravity_api_request("GET", "/v1/workspace/list")
    assert err == "Not logged in" and err.status is None


def test_put_surfaces_status_false_without_conflict_as_500(logged_in, gravity, dav):
    dav("GET", "/control/src/app.py")
    gravity.write_response = {"status": False, "message": "Rejected"}
    new_body = NEW_APP.encode("utf-8")
    status, body = dav(
        "PUT",
        "/control/src/app.py",
        headers={"Content-Length": str(len(new_body))},
        body=new_body,
    )
    assert status == 500
    assert b"Rejected" in body
    assert vfs.VFS_FILE_CACHE["control/src/app.py"] == ORIGINAL_APP


def test_put_binary_sends_base64_full_content(logged_in, gravity, dav):
    payload = b"\x89PNG\r\n\x1a\n\xff\x00"
    status, _ = dav(
        "PUT",
        "/control/logo.png",
        headers={"Content-Length": str(len(payload))},
        body=payload,
    )
    assert status == 204
    post = gravity.requests[-1]
    assert post["body"]["is_binary"] is True
    assert post["body"]["type"] == "modified"
    assert base64.b64decode(post["body"]["content"]) == payload


def test_get_binary_returns_raw_bytes(logged_in, gravity, dav):
    status, body = dav("GET", "/control/logo.png")
    assert status == 200
    assert body == b"\x89PNG\r\n\x1a\n\x00\x01"
    assert vfs.VFS_FILE_CACHE["control/logo.png"] == body


def test_get_trusts_server_encoding_for_binary_without_known_extension(
    logged_in, gravity, dav
):
    raw = b"\x00\x01\x02\xff\xfe\xfd"
    status, body = dav("GET", "/control/data.blob")
    assert status == 200
    assert body == raw, "base64 text was delivered to the editor instead of the bytes"
    assert vfs.VFS_FILE_CACHE["control/data.blob"] == raw


def test_get_falls_back_to_is_binary_for_older_servers(logged_in, gravity, dav):
    gravity.legacy_keys.add(("control", "data.blob"))
    raw = b"\x00\x01\x02\xff\xfe\xfd"
    status, body = dav("GET", "/control/data.blob")
    assert status == 200
    assert body == raw


def test_put_binary_without_known_extension_is_not_decoded_lossily(
    logged_in, gravity, dav
):
    dav("GET", "/control/data.blob")
    new_raw = b"\x00\x01\x02\xff\xfe\xfd\x80"
    status, _ = dav(
        "PUT",
        "/control/data.blob",
        headers={"Content-Length": str(len(new_raw))},
        body=new_raw,
    )
    assert status == 204
    post = gravity.requests[-1]["body"]
    assert post["is_binary"] is True
    assert base64.b64decode(post["content"]) == new_raw


def test_put_non_utf8_body_for_unknown_file_is_sent_as_binary(logged_in, gravity, dav):
    new_raw = b"\xff\xfe\x00binary"
    status, _ = dav(
        "PUT",
        "/control/fresh.dat",
        headers={"Content-Length": str(len(new_raw))},
        body=new_raw,
    )
    assert status == 204
    post = gravity.requests[-1]["body"]
    assert post["is_binary"] is True
    assert base64.b64decode(post["content"]) == new_raw
