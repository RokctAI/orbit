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


"""Orbit -- OSS client daemon for Gravity."""

import json as _json
import os as _os

# Distribution name as declared in pyproject.toml.
DIST_NAME = "orbit-client"


def _read_version() -> str:
    """Return the package version.

    ``version.json`` at the repository root is the single source of truth (it
    is what the shared release pipeline bumps). ``pyproject.toml`` reads
    ``orbit.__version__`` dynamically at build time, and the CLI's
    ``--version`` reads it at run time. When running from an installed wheel
    (no ``version.json`` on disk) the version recorded in the package
    metadata at build time is used instead.
    """
    version_file = _os.path.join(
        _os.path.dirname(_os.path.abspath(__file__)), _os.pardir, "version.json"
    )
    try:
        with open(version_file, "r", encoding="utf-8") as f:
            value = _json.load(f).get("version")
        if value:
            return str(value)
    except Exception:
        pass
    try:
        from importlib.metadata import version as _dist_version

        return _dist_version(DIST_NAME)
    except Exception:
        return "0.0.0"


__version__ = _read_version()
