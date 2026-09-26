"""The local control API (soundboard.remote): a real server on a free 127.0.0.1 port,
driven over HTTP while the Qt event loop answers."""
import http.client
import json
import socket
import threading
import time

import numpy as np
import pytest

from conftest import process_events
from soundboard import remote
from test_mainwindow import window as main_window  # noqa: F401  (the real MainWindow)

TOKEN = "test-token-123"


@pytest.fixture
def window(main_window):  # noqa: F811
    return main_window


def call(qapp, ctl, path, headers=None, method="GET", host=None):
    """Make the request on a thread, spinning Qt until it's answered."""
    out = {}

    def run():
        c = http.client.HTTPConnection(remote.HOST, ctl.port, timeout=5)
        h = dict(headers or {})
        if host is not None:
            h["Host"] = host
        c.request(method, path, headers=h)
        r = c.getresponse()
        out["status"], out["body"] = r.status, json.loads(r.read() or b"null")
        c.close()
    t = threading.Thread(target=run)
    t.start()
    assert process_events(qapp, lambda: not t.is_alive())
    return out["status"], out["body"]


@pytest.fixture
def ctl(qapp):
    calls = []

    def dispatch(action, params):
        calls.append((action, params))
        return 200, {"ok": action}
    c = remote.RemoteControl(dispatch)
    assert c.start(0, TOKEN) and c.port
    c.calls = calls
    yield c
    c.stop()
    assert not c.running


def test_needs_the_token_every_way_it_can_be_sent(qapp, ctl):
    assert call(qapp, ctl, "/api/status")[0] == 401
    assert call(qapp, ctl, "/api/status?token=wrong")[0] == 401
    assert call(qapp, ctl, f"/api/status?token={TOKEN}") == (200, {"ok": "status"})
    assert call(qapp, ctl, "/api/status", {"X-Token": TOKEN})[0] == 200
    assert call(qapp, ctl, "/api/pause", {"Authorization": f"Bearer {TOKEN}"},
                method="POST")[0] == 200
    assert [a for a, _ in ctl.calls] == ["status", "status", "pause"]
    assert all("token" not in p for _, p in ctl.calls)   # never passed on


def test_refuses_other_hosts_and_unknown_endpoints(qapp, ctl):
    auth = {"X-Token": TOKEN}
    assert call(qapp, ctl, "/api/status", auth, host="evil.example.com")[0] == 403
    assert call(qapp, ctl, "/api/status", auth, host=f"localhost:{ctl.port}")[0] == 200
    status, body = call(qapp, ctl, "/api/format-disk", auth)
    assert status == 404 and "/api/play" in body["endpoints"]
    assert not any(a == "format-disk" for a, _ in ctl.calls)


def test_a_taken_port_is_reported(qapp, ctl):
    other = remote.RemoteControl(lambda a, p: (200, {}))
    assert not other.start(ctl.port, TOKEN) and "in use" in other.error
    assert not other.running


def test_a_client_that_goes_quiet_is_dropped(qapp, monkeypatch):
    monkeypatch.setattr(remote, "IDLE_S", 0.3)
    c = remote.RemoteControl(lambda a, p: (200, {}))
    assert c.start(0, TOKEN)
    try:
        assert c._server.daemon_threads      # a stuck handler can't hold up quitting
        s = socket.create_connection((remote.HOST, c.port), timeout=5)
        s.sendall(b"GET /api/status HTTP/1.1\r\n")          # ...and never finishes
        t0 = time.monotonic()
        assert s.recv(1024) == b""                          # the server hung up
        assert time.monotonic() - t0 < 4
        s.close()
    finally:
        c.stop()


def test_window_endpoints(qapp, window):
    w = window
    for sid in ("s0", "s1"):
        w.audio[sid] = np.zeros((480, 2), np.float32)
    played, stopped = [], []
    w.play = played.append
    w.engine.stop = stopped.append
    d = lambda action, **p: remote.dispatch(w, action, p)   # noqa: E731
    status, sounds = d("sounds")
    assert status == 200 and [s["name"] for s in sounds] == ["Boom", "Airhorn"]
    assert d("play", name="airhorn") == (200, {"playing": "s1", "name": "Airhorn"})
    assert d("play", id="s0")[0] == 200 and played == ["s1", "s0"]
    assert d("play", name="nope")[0] == 404 and d("play")[0] == 400
    assert d("stop", id="s1") == (200, {"stopped": "s1"}) and stopped == ["s1"]
    assert d("random")[0] == 200 and played[-1] in ("s0", "s1")
    assert d("random", category="Nope")[0] == 404
    assert d("categories") == (200, [])
    assert d("status")[1]["version"]


def test_window_starts_it_only_when_turned_on(qapp, window):
    w = window
    assert not w.remote.running and w.cfg.api_token == ""
    w.cfg.api_enabled, w.cfg.api_port = True, 0
    assert w.apply_remote() == "" and w.remote.running
    assert len(w.cfg.api_token) >= 24                    # made on first use
    w.cfg.api_enabled = False
    w.apply_remote()
    assert not w.remote.running
