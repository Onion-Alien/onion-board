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


def test_a_ringing_watch_alarm_shows_as_its_pad_and_stops_with_it(qapp, window):
    from soundboard.ui import triggershost
    assert remote.RING == triggershost.RING
    w = window
    ring = f"s0{remote.RING}trigger1"
    w.engine.playing = lambda: {ring: (0.3, False)}
    stopped = []
    w.engine.stop = stopped.append
    d = lambda action, **p: remote.dispatch(w, action, p)   # noqa: E731
    assert d("status")[1]["playing"] == ["s0"]
    assert [s["playing"] for s in d("sounds")[1]] == [True, False]
    assert d("stop", id="s0") == (200, {"stopped": "s0"}) and stopped == ["s0", ring]
    stopped.clear()
    d("stop", id="s1")                   # another pad: the alarm rings on
    assert stopped == ["s1"]


def test_window_starts_it_only_when_turned_on(qapp, window):
    w = window
    assert not w.remote.running and w.cfg.api_token == ""
    w.cfg.api_enabled, w.cfg.api_port = True, 0
    assert w.apply_remote() == "" and w.remote.running
    assert len(w.cfg.api_token) >= 24                    # made on first use
    w.cfg.api_enabled = False
    w.apply_remote()
    assert not w.remote.running


def test_a_request_answered_busy_never_runs_later(qapp, ctl, monkeypatch):
    """A Stream Deck that retries on "busy" mustn't get the sound played twice."""
    monkeypatch.setattr(remote, "ANSWER_S", 0.2)
    out = {}

    def run():
        c = http.client.HTTPConnection(remote.HOST, ctl.port, timeout=5)
        c.request("GET", "/api/stop", headers={"Authorization": f"Bearer {TOKEN}"})
        out["status"] = c.getresponse().status
        c.close()
    t = threading.Thread(target=run)
    t.start()
    t.join(5)                  # the UI thread is "busy": no events processed meanwhile
    assert out["status"] == 503
    process_events(qapp, lambda: False, timeout=0.3)
    assert ctl.calls == []


def test_a_port_out_of_range_is_reported_not_raised(qapp):
    c = remote.RemoteControl(lambda a, p: (200, {}))
    assert not c.start(70000, TOKEN) and "isn't a valid port" in c.error
    assert not c.running


def test_help_lists_every_endpoint(qapp, window):
    status, body = remote.dispatch(window, "help", {})
    assert status == 200 and set(body["endpoints"]) == {f"/api/{a}" for a in remote.ACTIONS}
    assert remote.ACTIONS == tuple(remote.ENDPOINTS)


def test_window_streamer_endpoints(qapp, window):
    """The hotkey actions a streamer wants on a button: live / mute, voice, mic, volume,
    category, last sound, and the answers when a name is wrong."""
    w = window
    w.audio["s1"] = np.zeros((480, 2), np.float32)
    played = []
    w.play = played.append
    d = lambda action, **p: remote.dispatch(w, action, p)   # noqa: E731

    assert d("last") == (404, {"error": "nothing has played yet"})
    w._last_sid = "s1"
    assert d("last")[0] == 200 and played == ["s1"]

    status, body = d("play", name="airhron")
    assert status == 404 and body["did_you_mean"] == ["Airhorn"]

    live = bool(w.engine.sending)
    assert d("live") == (200, {"live": not live})            # no on=: toggle
    assert d("live", on="1") == (200, {"live": True}) and w.btn_air.isChecked()
    assert d("live", on="0") == (200, {"live": False}) and not w.engine.sending
    assert d("live", on="maybe")[0] == 400
    d("live", on="1")

    assert d("voice", on="on") == (200, {"voice": True})
    assert d("voice", on="off") == (200, {"voice": False})
    mic = bool(w.cfg.mic_enabled)
    assert d("mic", on="toggle") == (200, {"mic": not mic})
    d("mic", on="1" if mic else "0")

    assert d("volume", set="40") == (200, {"volume": 40})
    assert d("volume", step="up") == (200, {"volume": 50})
    assert d("volume", step="down")[1] == {"volume": 40}
    assert d("volume", set="loud")[0] == 400 and d("volume")[0] == 400
    assert d("volume", set="-5")[1] == {"volume": 0}

    w.new_category(name="Memes")
    assert d("category", name="memes") == (200, {"category": "Memes"})
    assert d("category", name="") == (200, {"category": ""})
    assert d("category", name="Nope")[0] == 404
    assert d("category", step="sideways")[0] == 400 and d("category")[0] == 400

    s = d("status")[1]
    assert {"live", "voice", "mic", "volume", "paused"} <= set(s) and s["volume"] == 0


def test_setup_prompt_holds_the_api_and_the_sounds_but_the_key_only_if_asked(window):
    cfg = window.cfg
    cfg.api_token = "secret-key-xyz"
    p = remote.setup_prompt(cfg, 7474)
    assert "secret-key-xyz" not in p and remote.KEY_PLACEHOLDER in p
    assert "http://127.0.0.1:7474" in p and "/api/play?name=Boom" in p
    assert "- Airhorn" in p and all(f"/api/{a}" in p for a in remote.ACTIONS)
    assert "Streamer.bot" in p and "Stream Deck" in p
    p = remote.setup_prompt(cfg, 7474, cfg.api_token)
    assert "token=secret-key-xyz" in p and remote.KEY_PLACEHOLDER not in p


def test_setup_prompts_random_link_names_only_a_real_category(window):
    cfg = window.cfg
    cfg.categories = []   # a made-up "Memes" there answered 404
    p = remote.setup_prompt(cfg, 7474)
    assert "/api/random?category=&token=" in p and "category=Memes" not in p
    cfg.categories = ["Game sounds"]
    assert "/api/random?category=Game%20sounds&token=" in remote.setup_prompt(cfg, 7474)


def test_streamer_guide_turns_it_on_and_copies_working_links(qapp, window):
    from PySide6.QtWidgets import QApplication

    from soundboard.ui import streamguide
    w = window
    w.cfg.api_port = 0
    g = streamguide.StreamerGuide(w, w)
    try:
        assert not g.btn_play.isEnabled() and g.btn_on.isVisibleTo(g)
        g.turn_on()
        assert w.remote.running and w.cfg.api_enabled and not g.btn_on.isVisibleTo(g)
        g.sound.setCurrentText("Airhorn")
        g.btn_play.click()
        url = QApplication.clipboard().text()
        assert url.startswith("http://127.0.0.1:") and "/api/play?name=Airhorn&token=" in url
        assert url.endswith(w.cfg.api_token)
        panic = next(b for b in g.link_btns if b.text() == "Panic mute")
        panic.click()
        assert "/api/live?on=toggle&token=" in QApplication.clipboard().text()
    finally:
        g.close()
        w.cfg.api_enabled = False
        w.apply_remote()


def test_the_real_window_answers_over_http(qapp, window):
    w = window
    w.cfg.api_enabled, w.cfg.api_port = True, 0
    assert w.apply_remote() == ""
    try:
        auth = {"X-Token": w.cfg.api_token}
        status, body = call(qapp, w.remote, "/api/help", auth)
        assert status == 200 and "/api/live" in body["endpoints"]
        status, body = call(qapp, w.remote, "/api/volume?step=up", auth)
        assert status == 200 and body["volume"] == w.vol_sound.spin.value()
        assert call(qapp, w.remote, "/api/play?name=Nope", auth)[0] == 404
    finally:
        w.cfg.api_enabled = False
        w.apply_remote()
