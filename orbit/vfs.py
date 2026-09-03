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

import os
import json
import base64
import difflib
import hashlib
import urllib.request
import urllib.parse
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
import email.utils
import time
from typing import Any, Dict, List, Optional

# Shared, Tk-free config/credential/URL resolution (see orbit/config.py). The
# second form covers running vfs.py as a loose script (python orbit/vfs.py).
try:
    from .config import gravity_api_url, load_orbit_config
except ImportError:
    from config import gravity_api_url, load_orbit_config  # ty: ignore[unresolved-import]

try:
    from .config import BINARY_EXTENSIONS
except ImportError:
    try:
        from config import BINARY_EXTENSIONS  # ty: ignore[unresolved-import]
    except ImportError:
        # Fallback list kept consistent with orbit/config.py's BINARY_EXTENSIONS
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

# Global cache for tracking raw file content on-read to compute delta patches on-write
# Cache entries are always `bytes` for binary files and `str` for text files.
VFS_FILE_CACHE = {}

# Offline fallback for the list of repositories shown at the root of the
# drive. It is used only when neither the ``repos`` field of
# ~/.orbit/config.json nor the Gravity server supplies a list.
#
# FLAGGED (not removed, per project policy): this list has drifted from the
# server's gravity.json, which no longer contains paas_driver, paas_manager,
# paas_pos, paas_webapp or RokctAI_frontend. Those entries will 404 on the
# server if opened. Prefer setting ``"repos": [...]`` in config.json until
# Gravity exposes a repository list.
DEFAULT_REPOS = [
    "rcore",
    "control",
    "shared-workflows",
    "rpanel",
    "paas_customer",
    "paas_driver",
    "paas_manager",
    "paas_pos",
    "paas_webapp",
    "RokctAI_frontend",
    "bench",
    "The-Open-Language-Project",
]

# Where the drive-root repository list came from (see resolve_repo_list).
REPO_SOURCE_CONFIG = "config"  # "repos" in ~/.orbit/config.json
REPO_SOURCE_SERVER = "server"  # GET /v1/workspace/list without repo_name
REPO_SOURCE_FALLBACK = "fallback"  # DEFAULT_REPOS, unverified

# When the list is the DEFAULT_REPOS fallback the drive root also carries this
# read-only file, so an unverified (possibly phantom) repository is never
# presented as real without the explanation sitting right next to it.
REPO_LIST_NOTICE_NAME = "00-ORBIT-REPO-LIST-UNAVAILABLE.txt"
_REPO_LIST_NOTICE_MTIME = time.time()

# The server-provided repository list is cached briefly because WebDAV
# clients issue a root PROPFIND on nearly every interaction.
REPO_LIST_TTL_SECONDS = 60
_REPO_LIST_CACHE: Dict[str, Any] = {
    "expires": 0.0,
    "repos": None,
    "source": None,
    "detail": "",
}


def _repo_names_from_payload(payload: Any) -> List[str]:
    """Extract repository names from a config/server payload.

    Accepts ``{"repos": [...]}``/``{"repositories": [...]}`` or a bare list;
    items may be strings or dicts with a ``path`` (gravity.json style) or
    ``name`` key. Unknown shapes yield an empty list.
    """
    candidates = None
    if isinstance(payload, dict):
        for key in ("repos", "repositories"):
            if isinstance(payload.get(key), list):
                candidates = payload[key]
                break
    elif isinstance(payload, list):
        candidates = payload

    names: List[str] = []
    for item in candidates or []:
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = item.get("path") or item.get("name") or ""
        else:
            continue
        name = str(name).strip().strip("/")
        if name and name not in names:
            names.append(name)
    return names


def _reset_repo_list_cache():
    _REPO_LIST_CACHE["expires"] = 0.0
    _REPO_LIST_CACHE["repos"] = None
    _REPO_LIST_CACHE["source"] = None
    _REPO_LIST_CACHE["detail"] = ""


def _fallback_detail(err) -> str:
    """Plain-language reason why the server did not supply a repository list."""
    status = getattr(err, "status", None)
    if status == 422:
        return (
            "this Gravity server has no repository-enumeration route "
            "(GET /v1/workspace/list requires repo_name)"
        )
    if status == 401:
        return f"Gravity rejected the session token ({err})"
    if status is not None:
        return f"Gravity answered HTTP {status} ({err})"
    return f"could not reach Gravity ({err})"


def resolve_repo_list(config, request=None):
    """Work out the repositories to show at the drive root.

    Returns ``(names, source, detail)`` where ``source`` is one of
    :data:`REPO_SOURCE_CONFIG`, :data:`REPO_SOURCE_SERVER` or
    :data:`REPO_SOURCE_FALLBACK`. ``detail`` is a human-readable reason
    (only meaningful for the fallback), so ``orbit status`` and the VFS root
    can tell the user exactly why the list is not authoritative.

    Order: ``repos`` in ~/.orbit/config.json (explicit user override), then
    the Gravity server (consumed when the server provides a ``repos`` list),
    then :data:`DEFAULT_REPOS`. ``request`` is ``(method, endpoint) ->
    (payload, err)`` and defaults to :func:`gravity_api_request` with
    ``config``.
    """
    configured = _repo_names_from_payload({"repos": config.get("repos")})
    if configured:
        return configured, REPO_SOURCE_CONFIG, ""

    if request is None:

        def request(method, endpoint):
            return gravity_api_request(method, endpoint, config=config)

    res, err = request("GET", "/v1/workspace/list")
    if err:
        return list(DEFAULT_REPOS), REPO_SOURCE_FALLBACK, _fallback_detail(err)

    names = _repo_names_from_payload(res)
    if names:
        return names, REPO_SOURCE_SERVER, ""
    return (
        list(DEFAULT_REPOS),
        REPO_SOURCE_FALLBACK,
        "the Gravity server answered without a repository list",
    )


def repo_list_notice_text(detail: str) -> str:
    """Body of the notice file served at the drive root in fallback mode."""
    repos = "\n".join(f"    {name}" for name in DEFAULT_REPOS)
    return (
        "Orbit could not get the list of repositories from Gravity.\n"
        "\n"
        f"Reason: {detail or 'unknown'}\n"
        "\n"
        "The folders next to this file are Orbit's built-in fallback list\n"
        "(DEFAULT_REPOS in orbit/vfs.py). It has NOT been verified against the\n"
        "server: some of these repositories may no longer exist there, and\n"
        "opening one of those fails with a Gravity error.\n"
        "\n"
        f"{repos}\n"
        "\n"
        "To fix this, tell Orbit which repositories you have by adding a\n"
        '"repos" list to ~/.orbit/config.json, for example:\n'
        "\n"
        '    {"server": "https://platform.rokct.ai", "repos": ["rcore", "control"]}\n'
        "\n"
        "then run `orbit mount` again. `orbit status` shows which list is in use.\n"
    )


class GravityError(str):
    """A failed Gravity API call.

    Behaves as the error message (so ``if err:`` and f-strings keep working)
    and additionally carries the HTTP ``status`` and the decoded JSON
    ``body`` when the failure was an HTTP error response, so callers can map
    e.g. a 409 conflict to a 409 for the editor instead of a generic 500.
    """

    status: Optional[int]
    body: Any

    def __new__(cls, message, status=None, body=None):
        text = str(message or "")
        if not text:
            text = f"HTTP {status}" if status else "Unknown Gravity error"
        obj = super().__new__(cls, text)
        obj.status = status
        obj.body = body
        return obj


def _error_from_http(e: urllib.error.HTTPError) -> GravityError:
    body: Any = None
    try:
        raw = e.read().decode("utf-8")
        body = json.loads(raw) if raw.strip() else None
    except Exception:
        body = None

    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, str) and detail:
        message = detail
    elif isinstance(detail, dict) and detail.get("message"):
        message = str(detail["message"])
    elif isinstance(body, dict) and body.get("message"):
        message = str(body["message"])
    else:
        message = str(e)
    return GravityError(message, status=e.code, body=body)


def gravity_api_request(
    method, endpoint, params=None, data=None, config=None, timeout=30
):
    """Call the Gravity API. Returns ``(payload, None)`` or ``(None, GravityError)``.

    The base URL is ``{server}/gravity`` by default (production nginx
    prefix); see :func:`orbit.config.resolve_gravity_base_url` for overrides.
    """
    import uuid

    if config is None:
        config = load_orbit_config()
    url = gravity_api_url(endpoint, config)
    token = config.get("token", "")
    if not url:
        return None, GravityError("Not logged in")

    if params:
        url += "?" + urllib.parse.urlencode(params)

    trace_id = f"trace_{uuid.uuid4().hex}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-trace-id": trace_id,
    }

    req_data = None
    if data:
        req_data = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(url, headers=headers, method=method, data=req_data)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        return None, _error_from_http(e)
    except Exception as e:
        return None, GravityError(str(e) or type(e).__name__)


def _git_blob_sha(content: bytes) -> str:
    """SHA-1 of ``content`` as a git blob object (what ``index`` lines carry)."""
    header = b"blob %d\0" % len(content)
    return hashlib.sha1(header + content).hexdigest()


def build_unified_patch(original: str, modified: str, rel_path: str) -> str:
    """Return a ``git apply``-able unified diff turning ``original`` into ``modified``.

    The server applies this with ``git apply --ignore-whitespace --3way`` so
    the patch must be well formed: ``a/``/``b/`` prefixed headers, an
    ``index`` line carrying the pre/post-image blob ids (which is what lets
    ``--3way`` fall back to a merge), exactly one newline per line, and the
    ``\\ No newline at end of file`` marker where the content lacks one.

    Returns ``""`` when there is nothing to change.
    """
    old_lines = original.splitlines(keepends=True)
    new_lines = modified.splitlines(keepends=True)
    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{rel_path}",
            tofile=f"b/{rel_path}",
            lineterm="",
        )
    )
    if not diff_lines:
        return ""

    old_sha = _git_blob_sha(original.encode("utf-8"))
    new_sha = _git_blob_sha(modified.encode("utf-8"))
    out = [
        f"diff --git a/{rel_path} b/{rel_path}\n",
        f"index {old_sha}..{new_sha} 100644\n",
    ]
    for idx, line in enumerate(diff_lines):
        if idx < 2 or line.startswith("@@"):
            # ---/+++ headers and hunk headers carry no newline (lineterm="").
            out.append(line + "\n")
        elif line.endswith("\n"):
            # Content lines keep their own newline (splitlines(keepends=True)).
            out.append(line)
        else:
            out.append(line + "\n\\ No newline at end of file\n")
    return "".join(out)


def _direct_children(files, dir_path):
    """Split a flat server listing into the direct sub-directories and files of ``dir_path``.

    The server returns every file in the repository with its full relative
    path (``src/lib/util.py``). WebDAV clients walk the tree one level at a
    time, so for ``dir_path`` we return ``(subdir_names, file_entries)`` for
    its immediate children only; nested files are represented by their first
    path component as a collection.
    """
    prefix = dir_path.strip("/")
    prefix = prefix + "/" if prefix else ""
    subdirs = []
    children = []
    for entry in files:
        rel_path = str(entry.get("path", ""))
        if not rel_path.startswith(prefix):
            continue
        rel = rel_path[len(prefix) :]
        if not rel:
            continue
        if "/" in rel:
            name = rel.split("/", 1)[0]
            if name and name not in subdirs:
                subdirs.append(name)
        else:
            children.append(entry)
    return subdirs, children


def _result_reports_no_changes(outcome) -> bool:
    """Whether a per-repo ``results`` value says nothing was committed.

    Gravity reports ``"No changes to push"`` (or, for paired public/private
    repositories, ``"Public: No Changes, Private: No Changes"``) when its
    commit step found nothing to commit. A value that mentions a push
    (``"Pushed successfully"``, ``"Public: Pushed, Private: No Changes"``)
    means at least one side landed.
    """
    text = str(outcome or "").lower()
    return "no changes" in text and "pushed" not in text


def _response_reports_no_changes(res) -> bool:
    if not isinstance(res, dict) or not isinstance(res.get("results"), dict):
        return False
    return any(_result_reports_no_changes(v) for v in res["results"].values())


def _write_failure_from_response(res, content_changed=True):
    """Map a Gravity write response body to ``(http_status, message)`` or None.

    Gravity answers a failed patch with HTTP 200 and a body such as
    ``{"status": false, "conflict": true, "conflicts": [...], "message": ...}``
    so a 2xx transport status alone does not mean the save landed.

    ``content_changed`` says whether the client *knows* it sent content that
    differs from what the server has (a non-empty patch, or binary bytes that
    differ from the cached copy). In that case a ``"No changes to push"``
    result is a contradiction: the server dropped the change (seen with a
    Gravity older than this client), and reporting success would make the
    editor believe a save that never landed.
    """
    if not isinstance(res, dict):
        return 500, "Unexpected response from Gravity"
    if res.get("conflict"):
        conflicts = ", ".join(str(c) for c in res.get("conflicts") or [])
        detail = res.get("message") or "Merge conflict"
        return 409, f"{detail} ({conflicts})" if conflicts else detail
    if not res.get("status", True):
        return 500, str(res.get("message") or "Gravity rejected the change")
    if content_changed and isinstance(res.get("results"), dict):
        for repo, outcome in res["results"].items():
            if _result_reports_no_changes(outcome):
                return 500, (
                    f"Gravity answered '{outcome}' for {repo} although modified "
                    "content was sent, so the change was NOT persisted. The "
                    "Gravity server is probably older than this client; the "
                    "file on the server is unchanged."
                )
    return None


def _write_failure_from_error(err):
    """Map a failed ``POST /v1/workspace/file`` to ``(http_status, message)``.

    A 409 from Gravity (``detail: {"message", "conflicts"}``) stays a 409 for
    the editor; every other failure is a 500.
    """
    status = getattr(err, "status", None)
    body = getattr(err, "body", None)
    if status == 409:
        payload = body
        if isinstance(body, dict) and isinstance(body.get("detail"), dict):
            payload = body["detail"]
        if isinstance(payload, dict):
            conflicts = ", ".join(str(c) for c in payload.get("conflicts") or [])
            detail = payload.get("message") or str(err) or "Merge conflict"
            return 409, f"{detail} ({conflicts})" if conflicts else detail
        return 409, str(err) or "Merge conflict"
    return 500, str(err)


def _is_binary_path(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    return ext in BINARY_EXTENSIONS


class OrbitWebDAVHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        # Suppress spammy terminal logs for smooth console output
        pass

    def _get_config(self):
        # Shared loader: resolves the token from ORBIT_TOKEN, then the OS
        # keyring (where `orbit login`/the widget store it), then the
        # plaintext file, so the VFS is authenticated after a normal login.
        return load_orbit_config()

    def _list_repos_with_source(self):
        """``(names, source, detail)`` for the drive root (see resolve_repo_list).

        The config override is never cached (it is a local file read); the
        server answer, including a fallback decision, is cached for
        REPO_LIST_TTL_SECONDS.
        """
        config = self._get_config()
        configured = _repo_names_from_payload({"repos": config.get("repos")})
        if configured:
            return configured, REPO_SOURCE_CONFIG, ""

        now = time.monotonic()
        cached: Optional[List[str]] = _REPO_LIST_CACHE.get("repos")
        if cached is not None and now < float(_REPO_LIST_CACHE.get("expires") or 0):
            return (
                list(cached),
                _REPO_LIST_CACHE.get("source") or REPO_SOURCE_FALLBACK,
                str(_REPO_LIST_CACHE.get("detail") or ""),
            )

        names, source, detail = resolve_repo_list(config, self._api_request)

        _REPO_LIST_CACHE["repos"] = list(names)
        _REPO_LIST_CACHE["source"] = source
        _REPO_LIST_CACHE["detail"] = detail
        _REPO_LIST_CACHE["expires"] = now + REPO_LIST_TTL_SECONDS
        return names, source, detail

    def _list_repos(self):
        """Repository names for the drive root.

        Order: ``repos`` in ~/.orbit/config.json (explicit user override),
        then the Gravity server (``GET /v1/workspace/list`` with no
        ``repo_name``; consumed when the server provides a ``repos`` list),
        then DEFAULT_REPOS as an offline fallback.
        """
        return self._list_repos_with_source()[0]

    def _repo_list_notice(self):
        """``(text, file_entry)`` for the root notice, or ``(None, None)``
        when the repository list is authoritative (config or server)."""
        _names, source, detail = self._list_repos_with_source()
        if source != REPO_SOURCE_FALLBACK:
            return None, None
        text = repo_list_notice_text(detail)
        entry = {
            "path": REPO_LIST_NOTICE_NAME,
            "size": len(text.encode("utf-8")),
            "mtime": _REPO_LIST_NOTICE_MTIME,
        }
        return text, entry

    def _api_request(self, method, endpoint, params=None, data=None):
        """Call Gravity as the logged-in user; see :func:`gravity_api_request`.

        Errors come back as :class:`GravityError` (a ``str`` carrying the
        HTTP status), so ``if err:`` keeps working for every caller.
        """
        return gravity_api_request(
            method, endpoint, params=params, data=data, config=self._get_config()
        )

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("DAV", "1, 2")
        self.send_header("MS-Author-Via", "DAV")
        self.send_header(
            "Allow",
            "OPTIONS, GET, HEAD, PUT, DELETE, PROPFIND, PROPPATCH, LOCK, UNLOCK",
        )
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_PROPFIND(self):
        depth = self.headers.get("Depth", "1")
        path = urllib.parse.unquote(self.path).strip("/")

        # Route matching
        parts = [p for p in path.split("/") if p]

        if not parts:
            # Root directory (List of repositories): config override, then
            # the server, then the DEFAULT_REPOS offline fallback. In
            # fallback mode the notice file sits next to the folders.
            repos = self._list_repos()
            _text, notice = self._repo_list_notice()
            xml_response = self._render_collection(
                "/",
                repos if depth == "1" else [],
                [notice] if depth == "1" and notice else [],
            )
        elif len(parts) == 1 and parts[0] == REPO_LIST_NOTICE_NAME:
            _text, notice = self._repo_list_notice()
            if notice is None:
                self.send_error(404, "Not found")
                return
            xml_response = self._render_file_metadata(
                f"/{REPO_LIST_NOTICE_NAME}", notice
            )
        elif len(parts) == 1:
            xml_response = self._propfind_repo(parts[0], depth)
        else:
            xml_response = self._propfind_path(parts[0], "/".join(parts[1:]), depth)

        if xml_response is None:
            return

        self.send_response(207, "Multi-Status")
        self.send_header("Content-Type", 'text/xml; charset="utf-8"')
        encoded_xml = xml_response.encode("utf-8")
        self.send_header("Content-Length", str(len(encoded_xml)))
        self.end_headers()
        self.wfile.write(encoded_xml)

    def _propfind_repo(self, repo_name, depth):
        """Repository folder: its direct files and sub-directories."""
        if depth == "0":
            return self._render_single_dir(f"/{repo_name}/")

        res, err = self._api_request(
            "GET", "/v1/workspace/list", {"repo_name": repo_name}
        )
        if err:
            self.send_error(500, f"Gravity error: {err}")
            return None
        subdirs, children = _direct_children(res.get("files", []), "")
        return self._render_files(f"/{repo_name}/", children, subdirs)

    def _propfind_path(self, repo_name, file_path, depth):
        """A file or sub-directory inside a repository."""
        res, err = self._api_request(
            "GET", "/v1/workspace/list", {"repo_name": repo_name}
        )
        if err:
            self.send_error(404, "Not found")
            return None

        files = res.get("files", [])
        matched = [f for f in files if f["path"] == file_path]

        # Check if it is a folder path
        is_sub_dir = any(f["path"].startswith(file_path + "/") for f in files)

        if is_sub_dir:
            if depth == "0":
                return self._render_single_dir(f"/{repo_name}/{file_path}/")
            subdirs, children = _direct_children(files, file_path)
            return self._render_files(f"/{repo_name}/{file_path}/", children, subdirs)
        if matched:
            return self._render_file_metadata(f"/{repo_name}/{file_path}", matched[0])

        self.send_error(404, "Not found")
        return None

    def do_GET(self):
        path = urllib.parse.unquote(self.path).strip("/")
        parts = [p for p in path.split("/") if p]
        if len(parts) == 1 and parts[0] == REPO_LIST_NOTICE_NAME:
            text, _notice = self._repo_list_notice()
            if text is None:
                self.send_error(404, "Not found")
                return
            self._send_bytes(text.encode("utf-8"), "text/plain; charset=utf-8")
            return
        if len(parts) < 2:
            self.send_error(403, "Access Denied")
            return

        repo_name = parts[0]
        file_path = "/".join(parts[1:])

        res, err = self._api_request(
            "GET", "/v1/workspace/file", {"repo_name": repo_name, "path": file_path}
        )
        if err:
            self.send_error(404, f"File not found: {err}")
            return

        cached = self._decode_file_response(res, file_path)
        VFS_FILE_CACHE[path] = cached
        content = cached if isinstance(cached, bytes) else cached.encode("utf-8")
        self._send_bytes(content, "application/octet-stream")

    def _send_bytes(self, content, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    @classmethod
    def _decode_file_response(cls, res, file_path):
        """Content of a ``/v1/workspace/file`` body: ``bytes`` for binary, ``str`` for text."""
        raw_content = res.get("content", "")
        if cls._response_is_binary(res, file_path):
            try:
                return base64.b64decode(raw_content)
            except Exception:
                return raw_content.encode("utf-8", errors="ignore")
        return raw_content

    def _server_has_content(self, repo_name, file_path, body):
        """Re-read ``file_path`` from Gravity and compare it with ``body``.

        Used after a write the server claims changed nothing, when the
        client had no cached copy to know whether that claim is plausible.
        """
        res, err = self._api_request(
            "GET", "/v1/workspace/file", {"repo_name": repo_name, "path": file_path}
        )
        if err:
            return False
        remote = self._decode_file_response(res, file_path)
        if isinstance(remote, bytes) != isinstance(body, bytes):
            remote = remote.encode("utf-8") if isinstance(remote, str) else remote
            body = body.encode("utf-8") if isinstance(body, str) else body
        return remote == body

    @staticmethod
    def _response_is_binary(res, file_path):
        """Whether a ``/v1/workspace/file`` body carries base64 binary content.

        Gravity reports ``"encoding": "utf-8" | "base64"`` and is
        authoritative when present (it base64-encodes anything that is not
        valid UTF-8, whatever the extension). ``is_binary`` and the extension
        list are kept as fallbacks for older servers that omit ``encoding``.
        """
        encoding = res.get("encoding")
        if encoding:
            return str(encoding).lower() == "base64"
        return bool(res.get("is_binary")) or _is_binary_path(file_path)

    def do_PUT(self):
        path = urllib.parse.unquote(self.path).strip("/")
        parts = [p for p in path.split("/") if p]
        if len(parts) < 2:
            self.send_error(403, "Access Denied")
            return

        repo_name = parts[0]
        file_path = "/".join(parts[1:])

        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length)

        is_special_file = file_path.endswith("hooks.py") or file_path.endswith(
            "modules.txt"
        )
        original_content = VFS_FILE_CACHE.get(path)
        # Whether the client *knows* the content it sends differs from what
        # the server has: True (a real patch / differing bytes), False (a
        # full-content write identical to the cached copy) or None (nothing
        # cached, so unknown). See _write_failure_from_response.
        content_changed: Optional[bool] = None
        # Binary if the extension says so, if the server delivered it as
        # binary on read (bytes in the cache), or if the body is not UTF-8.
        is_binary = _is_binary_path(file_path) or isinstance(
            original_content, (bytes, bytearray)
        )
        body_text = None
        if not is_binary:
            try:
                body_text = raw_body.decode("utf-8")
            except UnicodeDecodeError:
                is_binary = True

        if is_binary:
            # Binary content must never go through a lossy UTF-8 decode. Keep the
            # raw bytes as-is and diff/store them as bytes, matching how do_GET
            # caches binary content (see _is_binary_path usage above).
            body = raw_body
            if isinstance(original_content, (bytes, bytearray)):
                content_changed = bytes(original_content) != body
                if not is_special_file and not content_changed:
                    self.send_response(204)
                    self.end_headers()
                    return

            content_to_send = base64.b64encode(body).decode("ascii")
            change_type = "modified"
        else:
            body = body_text if body_text is not None else ""

            if not is_special_file and isinstance(original_content, str):
                # Send a git-apply-able patch (see build_unified_patch) rather
                # than the whole file.
                diff_text = build_unified_patch(original_content, body, file_path)
                if not diff_text:
                    self.send_response(204)
                    self.end_headers()
                    return

                content_to_send = diff_text
                change_type = "patch"
                content_changed = True
            else:
                if isinstance(original_content, str):
                    content_changed = original_content != body
                content_to_send = body
                change_type = "modified"

        data = {
            "repo_name": repo_name,
            "path": file_path,
            "content": content_to_send,
            "type": change_type,
            "is_binary": is_binary,
        }
        res, err = self._api_request("POST", "/v1/workspace/file", data=data)
        if err:
            # Keep Gravity's status where it means something to the editor
            # (409 conflict); anything else is a generic failure.
            status, message = _write_failure_from_error(err)
            self.send_error(status, f"Failed to save changes to Gravity: {message}")
            return

        if content_changed is None and _response_reports_no_changes(res):
            # Nothing was cached, so we cannot tell from here whether "No
            # changes to push" is honest (a no-op save) or a dropped write.
            # Ask the server what it has now.
            content_changed = not self._server_has_content(repo_name, file_path, body)

        failure = _write_failure_from_response(
            res, content_changed=bool(content_changed)
        )
        if failure is not None:
            # Gravity answered 200 but did not apply the change (e.g. a patch
            # conflict). Tell the editor, and keep the cache at the content
            # the server actually has so the next diff is computed correctly.
            status, message = failure
            self.send_error(status, f"Gravity did not save the file: {message}")
            return

        VFS_FILE_CACHE[path] = body
        self.send_response(204)
        self.end_headers()

    def do_PROPPATCH(self):
        # Return standard success XML response for property updates
        path = self.path
        xml_res = f"""<?xml version="1.0" encoding="utf-8" ?>
<d:multistatus xmlns:d="DAV:">
  <d:response>
    <d:href>{path}</d:href>
    <d:propstat>
      <d:prop><d:lockdiscovery/></d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
</d:multistatus>"""
        self.send_response(207, "Multi-Status")
        self.send_header("Content-Type", 'text/xml; charset="utf-8"')
        encoded = xml_res.encode("utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_LOCK(self):
        # Return mock lock token success for Windows/Office compliance
        path = self.path
        xml_res = f"""<?xml version="1.0" encoding="utf-8" ?>
<d:prop xmlns:d="DAV:">
  <d:lockdiscovery>
    <d:activelock>
      <d:locktype><d:write/></d:locktype>
      <d:lockscope><d:exclusive/></d:lockscope>
      <d:depth>Infinity</d:depth>
      <d:owner><d:href>Orbit</d:href></d:owner>
      <d:timeout>Second-3600</d:timeout>
      <d:locktoken><d:href>opaquelocktoken:{path}-lock</d:href></d:locktoken>
    </d:activelock>
  </d:lockdiscovery>
</d:prop>"""
        self.send_response(200)
        self.send_header("Content-Type", 'text/xml; charset="utf-8"')
        self.send_header("Lock-Token", f"<opaquelocktoken:{path}-lock>")
        encoded = xml_res.encode("utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_UNLOCK(self):
        self.send_response(204)
        self.end_headers()

    def _render_collection(self, prefix, folders, files=()):
        lines = []
        lines.append('<?xml version="1.0" encoding="utf-8" ?>')
        lines.append('<d:multistatus xmlns:d="DAV:">')

        # Self entry
        lines.append("  <d:response>")
        lines.append(f"    <d:href>{prefix}</d:href>")
        lines.append("    <d:propstat>")
        lines.append("      <d:prop>")
        lines.append("        <d:resourcetype><d:collection/></d:resourcetype>")
        lines.append("      </d:prop>")
        lines.append("      <d:status>HTTP/1.1 200 OK</d:status>")
        lines.append("    </d:propstat>")
        lines.append("  </d:response>")

        # Children
        for folder in folders:
            href = f"{prefix}{folder}/"
            lines.append("  <d:response>")
            lines.append(f"    <d:href>{href}</d:href>")
            lines.append("    <d:propstat>")
            lines.append("      <d:prop>")
            lines.append(f"        <d:displayname>{folder}</d:displayname>")
            lines.append("        <d:resourcetype><d:collection/></d:resourcetype>")
            lines.append("      </d:prop>")
            lines.append("      <d:status>HTTP/1.1 200 OK</d:status>")
            lines.append("    </d:propstat>")
            lines.append("  </d:response>")

        for f in files:
            lines.extend(self._file_response_lines(f"{prefix}{f['path']}", f))

        lines.append("</d:multistatus>")
        return "\n".join(lines)

    @staticmethod
    def _file_response_lines(href, file_info):
        dt = datetime.fromtimestamp(file_info.get("mtime", 0))
        http_date = email.utils.format_datetime(dt)
        name = os.path.basename(file_info["path"])
        return [
            "  <d:response>",
            f"    <d:href>{href}</d:href>",
            "    <d:propstat>",
            "      <d:prop>",
            f"        <d:displayname>{name}</d:displayname>",
            f"        <d:getcontentlength>{file_info['size']}</d:getcontentlength>",
            "        <d:resourcetype/>",
            f"        <d:getlastmodified>{http_date}</d:getlastmodified>",
            "      </d:prop>",
            "      <d:status>HTTP/1.1 200 OK</d:status>",
            "    </d:propstat>",
            "  </d:response>",
        ]

    def _render_single_dir(self, href):
        name = [x for x in href.split("/") if x][-1]
        lines = [
            '<?xml version="1.0" encoding="utf-8" ?>',
            '<d:multistatus xmlns:d="DAV:">',
            "  <d:response>",
            f"    <d:href>{href}</d:href>",
            "    <d:propstat>",
            "      <d:prop>",
            f"        <d:displayname>{name}</d:displayname>",
            "        <d:resourcetype><d:collection/></d:resourcetype>",
            "      </d:prop>",
            "      <d:status>HTTP/1.1 200 OK</d:status>",
            "    </d:propstat>",
            "  </d:response>",
            "</d:multistatus>",
        ]
        return "\n".join(lines)

    def _render_files(self, prefix, files, subdirs=()):
        """Render a directory: its sub-directories (as collections) and direct files.

        ``files`` must be the *direct* children of ``prefix`` (see
        ``_direct_children``); entries are named by their basename, so the
        href keeps the full path (``/repo/src/app.py``) instead of flattening
        nested files to the repository root.
        """
        lines = []
        lines.append('<?xml version="1.0" encoding="utf-8" ?>')
        lines.append('<d:multistatus xmlns:d="DAV:">')

        # Folder self response
        lines.append("  <d:response>")
        lines.append(f"    <d:href>{prefix}</d:href>")
        lines.append("    <d:propstat>")
        lines.append("      <d:prop>")
        lines.append("        <d:resourcetype><d:collection/></d:resourcetype>")
        lines.append("      </d:prop>")
        lines.append("      <d:status>HTTP/1.1 200 OK</d:status>")
        lines.append("    </d:propstat>")
        lines.append("  </d:response>")

        # Sub-directories as collections
        for folder in subdirs:
            lines.append("  <d:response>")
            lines.append(f"    <d:href>{prefix}{folder}/</d:href>")
            lines.append("    <d:propstat>")
            lines.append("      <d:prop>")
            lines.append(f"        <d:displayname>{folder}</d:displayname>")
            lines.append("        <d:resourcetype><d:collection/></d:resourcetype>")
            lines.append("      </d:prop>")
            lines.append("      <d:status>HTTP/1.1 200 OK</d:status>")
            lines.append("    </d:propstat>")
            lines.append("  </d:response>")

        # File list
        for f in files:
            path_part = f["path"]
            if prefix.endswith(path_part + "/"):
                continue
            name = os.path.basename(path_part)

            # Map mtime to HTTP date format
            dt = datetime.fromtimestamp(f.get("mtime", 0))
            http_date = email.utils.format_datetime(dt)

            lines.append("  <d:response>")
            lines.append(f"    <d:href>{prefix}{name}</d:href>")
            lines.append("    <d:propstat>")
            lines.append("      <d:prop>")
            lines.append(f"        <d:displayname>{name}</d:displayname>")
            lines.append(
                f"        <d:getcontentlength>{f['size']}</d:getcontentlength>"
            )
            lines.append("        <d:resourcetype/>")
            lines.append(f"        <d:getlastmodified>{http_date}</d:getlastmodified>")
            lines.append("      </d:prop>")
            lines.append("      <d:status>HTTP/1.1 200 OK</d:status>")
            lines.append("    </d:propstat>")
            lines.append("  </d:response>")

        lines.append("</d:multistatus>")
        return "\n".join(lines)

    def _render_file_metadata(self, href, file_info):
        dt = datetime.fromtimestamp(file_info.get("mtime", 0))
        http_date = email.utils.format_datetime(dt)
        name = os.path.basename(file_info["path"])
        lines = [
            '<?xml version="1.0" encoding="utf-8" ?>',
            '<d:multistatus xmlns:d="DAV:">',
            "  <d:response>",
            f"    <d:href>{href}</d:href>",
            "    <d:propstat>",
            "      <d:prop>",
            f"        <d:displayname>{name}</d:displayname>",
            f"        <d:getcontentlength>{file_info['size']}</d:getcontentlength>",
            "        <d:resourcetype/>",
            f"        <d:getlastmodified>{http_date}</d:getlastmodified>",
            "      </d:prop>",
            "      <d:status>HTTP/1.1 200 OK</d:status>",
            "    </d:propstat>",
            "  </d:response>",
            "</d:multistatus>",
        ]
        return "\n".join(lines)


def start_vfs_server(host="127.0.0.1", port=8080):
    server = HTTPServer((host, port), OrbitWebDAVHandler)
    print(f"🛸 Orbit Local VFS server starting at http://{host}:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
