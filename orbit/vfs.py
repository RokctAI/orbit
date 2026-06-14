# Copyright (c) 2026, Rokct Intelligence (pty) Ltd.
# For license information, please see license.txt

import os
import json
import urllib.request
import urllib.parse
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
import xml.etree.ElementTree as ET
from datetime import datetime
import email.utils


class OrbitWebDAVHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        # Suppress spammy terminal logs for smooth console output
        pass

    def _get_config(self):
        config_file = os.path.expanduser("~/.orbit/config.json")
        if os.path.isfile(config_file):
            try:
                with open(config_file, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _api_request(self, method, endpoint, params=None, data=None):
        config = self._get_config()
        server = config.get("server", "").rstrip("/")
        token = config.get("token", "")
        if not server:
            return None, "Not logged in"

        url = f"{server}{endpoint}"
        if params:
            url += "?" + urllib.parse.urlencode(params)

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
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

        xml_response = ""
        if not parts:
            # Root directory (List of repositories)
            # Fetch config or active projects from local gravity.json
            repos = [
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

            xml_response = self._render_collection("/", repos if depth == "1" else [])
        elif len(parts) == 1:
            # Repository folder (List files from Gravity)
            repo_name = parts[0]
            if depth == "0":
                xml_response = self._render_single_dir(f"/{repo_name}/")
            else:
                res, err = self._api_request(
                    "GET", "/v1/workspace/list", {"repo_name": repo_name}
                )
                if err:
                    self.send_error(500, f"Gravity error: {err}")
                    return
                xml_response = self._render_files(
                    f"/{repo_name}/", res.get("files", [])
                )
        else:
            # File or subdirectory path
            repo_name = parts[0]
            file_path = "/".join(parts[1:])

            # Request file listing or specific file info
            res, err = self._api_request(
                "GET", "/v1/workspace/list", {"repo_name": repo_name}
            )
            if err:
                self.send_error(404, "Not found")
                return

            files = res.get("files", [])
            matched = [f for f in files if f["path"] == file_path]

            # Check if it is a folder path
            is_sub_dir = any(f["path"].startswith(file_path + "/") for f in files)

            if is_sub_dir:
                if depth == "0":
                    xml_response = self._render_single_dir(f"/{repo_name}/{file_path}/")
                else:
                    children = []
                    for f in files:
                        if f["path"].startswith(file_path + "/"):
                            sub_rel = f["path"][len(file_path) + 1 :]
                            if "/" not in sub_rel:
                                children.append(f)
                    xml_response = self._render_files(
                        f"/{repo_name}/{file_path}/", children
                    )
            elif matched:
                xml_response = self._render_file_metadata(
                    f"/{repo_name}/{file_path}", matched[0]
                )
            else:
                self.send_error(404, "Not found")
                return

        self.send_response(207, "Multi-Status")
        self.send_header("Content-Type", 'text/xml; charset="utf-8"')
        encoded_xml = xml_response.encode("utf-8")
        self.send_header("Content-Length", str(len(encoded_xml)))
        self.end_headers()
        self.wfile.write(encoded_xml)

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

        content = res.get("content", "").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_PUT(self):
        path = urllib.parse.unquote(self.path).strip("/")
        parts = [p for p in path.split("/") if p]
        if len(parts) < 2:
            self.send_error(403, "Access Denied")
            return

        repo_name = parts[0]
        file_path = "/".join(parts[1:])

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8", errors="ignore")

        data = {
            "repo_name": repo_name,
            "path": file_path,
            "content": body,
            "type": "modified",
        }
        res, err = self._api_request("POST", "/v1/workspace/file", data=data)
        if err:
            self.send_error(500, f"Failed to save changes to Gravity: {err}")
            return

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

    def _render_files(self, prefix, files):
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
