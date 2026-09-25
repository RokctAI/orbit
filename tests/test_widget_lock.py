# Copyright (c) 2026, Rokct Intelligence (pty) Ltd.
# For license information, please see license.txt

"""Single-instance handoff for ``orbit widget``.

A relaunch must never quit silently: it either takes the lock over from the
running widget or starts without it.
"""

import socket
import threading
import time

import pytest

pytest.importorskip("tkinter")  # orbit.widget imports Tk at module level

from orbit import widget  # noqa: E402


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_takes_over_from_a_slow_running_instance():
    """The old widget answers EXIT late (busy Tk thread); the new launch waits."""
    port = _free_port()
    old = socket.socket()
    old.bind(("127.0.0.1", port))
    old.listen(1)

    def slow_old_instance():
        conn, _ = old.accept()
        conn.recv(1024)
        time.sleep(1.5)  # well past the old fixed 0.5 s wait
        conn.close()
        old.close()

    threading.Thread(target=slow_old_instance, daemon=True).start()
    lock = widget.acquire_instance_lock(port=port, timeout=5)
    try:
        assert lock is not None
    finally:
        if lock is not None:
            lock.close()


def test_starts_without_lock_when_port_is_unavailable(tmp_path, monkeypatch):
    """A port held by something that is not the widget must not stop a launch."""
    monkeypatch.setattr(widget, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(widget, "WIDGET_LOG_FILE", str(tmp_path / "widget.log"))
    port = _free_port()
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", port))  # bound, not listening: nothing answers
    try:
        assert widget.acquire_instance_lock(port=port, timeout=0.5) is None
    finally:
        blocker.close()
    assert "unavailable" in open(widget.WIDGET_LOG_FILE, encoding="utf-8").read()
