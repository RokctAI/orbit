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
import xml.etree.ElementTree as ET
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

# The server-provided repository list is cached briefly because WebDAV
# clients issue a root PROPFIND on nearly every interaction.
REPO_LIST_TTL_SECONDS = 60
_REPO_LIST_CACHE: Dict[str, Any] = {"expires": 0.0, "repos": None}


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


def _write_failure_from_response(res):
    """Map a Gravity write response body to ``(http_status, message)`` or None.

    Gravity answers a failed patch with HTTP 200 and a body such as
    ``{"status": false, "conflict": true, "conflicts": [...], "message": ...}``
    so a 2xx transport status alone does not mean the save landed.
    """
    if not isinstance(res, dict):
        return 500, "Unexpected response from Gravity"
    if res.get("conflict"):
        conflicts = ", ".join(str(c) for c in res.get("conflicts") or [])
        detail = res.get("message") or "Merge conflict"
        return 409, f"{detail} ({conflicts})" if conflicts else detail
    if not res.get("status", True):
        return 500, str(res.get("message") or "Gravity rejected the change")
    return None


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

    def _list_repos(self):
        """Repository names for the drive root.

        Order: ``repos`` in ~/.orbit/config.json (explicit user override),
        then the Gravity server (``GET /v1/workspace/list`` with no
        ``repo_name``; consumed when the server provides a ``repos`` list),
        then DEFAULT_REPOS as an offline fallback.
        """
        config = self._get_config()
        configured = _repo_names_from_payload({"repos": config.get("repos")})
        if configured:
            return configured

        now = time.monotonic()
        cached: Optional[List[str]] = _REPO_LIST_CACHE.get("repos")
        if cached is not None and now < float(_REPO_LIST_CACHE.get("expires") or 0):
            return list(cached)

        res, err = self._api_request("GET", "/v1/workspace/list")
        names = _repo_names_from_payload(res) if not err else []
        if not names:
            names = list(DEFAULT_REPOS)

        _REPO_LIST_CACHE["repos"] = list(names)
        _REPO_LIST_CACHE["expires"] = now + REPO_LIST_TTL_SECONDS
        return names

    def _api_request(self, method, endpoint, params=None, data=None):
        import uuid

        config = self._get_config()
        # Base URL is {server}/gravity by default (production nginx prefix);
        # see orbit.config.resolve_gravity_base_url for overrides.
        url = gravity_api_url(endpoint, config)
        token = config.get("token", "")
        if not url:
            return None, "Not logged in"

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
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8")), None
        except urllib.error.HTTPError as e:
            try:
                err_msg = json.loads(e.read().decode("utf-8")).get("detail", str(e))
            except Exception:
                err_msg = str(e)
            return None, err_msg
        except Exception as e:
            return None, str(e)

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
            # the server, then the DEFAULT_REPOS offline fallback.
            repos = self._list_repos()
            xml_response = self._render_collection("/", repos if depth == "1" else [])
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

        raw_content = res.get("content", "")
        if self._response_is_binary(res, file_path):
            try:
                content = base64.b64decode(raw_content)
            except Exception:
                content = raw_content.encode("utf-8", errors="ignore")
            VFS_FILE_CACHE[path] = content
        else:
            VFS_FILE_CACHE[path] = raw_content
            content = raw_content.encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

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
            if (
                not is_special_file
                and isinstance(original_content, (bytes, bytearray))
                and original_content == body
            ):
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
            else:
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
            self.send_error(500, f"Failed to save changes to Gravity: {err}")
            return

        failure = _write_failure_from_response(res)
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

    def _render_collection(self, prefix, folders):
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

        lines.append("</d:multistatus>")
        return "\n".join(lines)

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
