"""The local control API (soundboard.control.remote): a real server on a free 127.0.0.1 port,
driven over HTTP while the Qt event loop answers."""
import http.client
import json
import socket
import threading
import time

import numpy as np
import pytest

from conftest import process_events
from soundboard.control import remote
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


@pytest.mark.windows   # Windows takes a just-closed port again at once
def test_the_server_sleeps_until_asked_and_stops_at_once(qapp, monkeypatch):
    """It used to wake 4 times a second to see whether it should stop; now it waits
    for a connection, and stopping wakes it straight away, so the same port can be
    taken again at once (a restart with a new key)."""
    looks = []
    real = remote._Server.service_actions
    monkeypatch.setattr(remote._Server, "service_actions",
                        lambda self: looks.append(1) or real(self))
    c = remote.RemoteControl(lambda a, p: (200, {}))
    assert c.start(0, TOKEN)
    port = c.port
    time.sleep(0.6)
    assert looks == []                                  # nothing came: still asleep
    assert call(qapp, c, f"/api/status?token={TOKEN}")[0] == 200
    t0 = time.monotonic()
    c.stop()
    assert time.monotonic() - t0 < 0.5 and not c.running
    assert c.start(port, TOKEN) and c.port == port
    c.stop()


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
    w.playctl.play = played.append
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


def test_status_says_whether_hotkeys_are_on(qapp, window):
    # a Stream Deck key showing the hotkeys switch reads it from here
    w = window
    d = lambda action, **p: remote.dispatch(w, action, p)   # noqa: E731
    w.hkctl.set_hotkeys_on(True)
    assert d("status")[1]["hotkeys"] is True
    assert d("hotkeys", on="0") == (200, {"hotkeys": False})
    assert d("status")[1]["hotkeys"] is False


def test_pause_on_sets_instead_of_flipping(qapp, window):
    w = window
    state = {"paused": False}
    w.engine.playing = lambda: {"s0": (0.3, state["paused"])}

    def pause_all(on=None):
        state["paused"] = (not state["paused"]) if on is None else on
        return state["paused"]
    w.engine.pause_all = pause_all
    d = lambda action, **p: remote.dispatch(w, action, p)   # noqa: E731
    assert d("pause", on="1") == (200, {"paused": True})
    assert d("pause", on="1") == (200, {"paused": True})     # already paused: stays
    assert d("status")[1]["paused"]
    assert d("pause", on="0") == (200, {"paused": False})
    assert d("pause", on="0") == (200, {"paused": False})
    assert d("pause") == (200, {"paused": True})              # no on=: flips
    assert d("pause", on="toggle") == (200, {"paused": False})
    assert d("pause", on="maybe") == (400, remote.BAD_ON)

def test_a_ringing_watch_alarm_shows_as_its_pad_and_stops_with_it(qapp, window):
    from soundboard.ui.triggers import triggershost
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
    assert w.remctl.apply_remote() == "" and w.remote.running
    assert len(w.cfg.api_token) >= 24                    # made on first use
    w.cfg.api_enabled = False
    w.remctl.apply_remote()
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


def test_start_up_waits_answer_requests_and_nothing_else(qapp, ctl):
    """Behind Windows' own loading screen nothing handles events: the update check as
    the app starts still answers a Stream Deck press at once (remote.answer_waiting),
    without running timers or anything else early."""
    from PySide6.QtCore import QTimer

    from soundboard.ui.window.updatecontrol import UpdateControl
    fired = []
    QTimer.singleShot(0, lambda: fired.append(1))
    out = {}

    def press():
        c = http.client.HTTPConnection(remote.HOST, ctl.port, timeout=5)
        c.request("GET", "/api/stop", headers={"Authorization": f"Bearer {TOKEN}"})
        out["status"] = c.getresponse().status
        c.close()
    t = threading.Thread(target=press)
    t.start()
    end = time.monotonic() + 2.5   # a slow GitHub
    assert UpdateControl._wait(lambda: t.join(2.5), lambda: time.monotonic() > end, "test")
    assert out.get("status") == 200 and ctl.calls == [("stop", {})]
    assert not fired   # (the event loop's own, later)
    process_events(qapp, lambda: bool(fired))


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
    w.playctl.play = played.append
    d = lambda action, **p: remote.dispatch(w, action, p)   # noqa: E731

    assert d("last") == (404, {"error": "nothing has played yet"})
    w.playctl._last_sid = "s1"
    assert d("last")[0] == 200 and played == ["s1"]

    status, body = d("play", name="airhron")
    assert status == 404 and body["did_you_mean"] == ["Airhorn"]

    live = bool(w.engine.sending)
    assert d("live") == (200, {"live": not live})            # no on=: toggle
    assert d("live", on="1") == (200, {"live": True}) and w.btn_air.isChecked()
    assert d("live", on="0") == (200, {"live": False}) and not w.engine.sending
    assert d("live", on="maybe")[0] == 400
    d("live", on="1")

    assert d("voice", on="on")[1]["voice"] is True
    assert d("voice", on="off")[1]["voice"] is False
    mic = bool(w.cfg.mic_enabled)
    assert d("mic", on="toggle") == (200, {"mic": not mic})
    d("mic", on="1" if mic else "0")

    assert d("volume", set="40") == (200, {"volume": 40})
    assert d("volume", step="up") == (200, {"volume": 50})
    assert d("volume", step="down")[1] == {"volume": 40}
    assert d("volume", set="loud")[0] == 400 and d("volume")[0] == 400
    assert d("volume", set="-5")[1] == {"volume": 0}
    top = w.vol_sound.spin.maximum()     # the help and errors give the real range
    assert d("volume", set="99999")[1] == {"volume": top}
    assert f"0-{top}" in remote.ENDPOINTS["volume"] and f"0-{top}" in remote.__doc__
    assert f"0-{top}" in remote.ENDPOINTS["radio_volume"]   # same kind of box
    assert f"0-{top}" in d("volume")[1]["error"]
    d("volume", set="0")

    w.catctl.new_category(name="Memes")
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

    from soundboard.ui.setup import streamguide
    w = window
    w.cfg.api_port = 0
    g = streamguide.StreamerGuide(w, w)
    try:
        # the Stream Deck step links to the file build.ps1 packs for every release
        from PySide6.QtWidgets import QLabel
        url = streamguide.STREAM_DECK_PLUGIN
        assert url.endswith("/releases/latest/download/com.onionalien.onionboard.streamDeckPlugin")
        assert any(f"href='{url}'" in lbl.text() for lbl in g.findChildren(QLabel))
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
        w.remctl.apply_remote()


def test_the_real_window_answers_over_http(qapp, window):
    w = window
    w.cfg.api_enabled, w.cfg.api_port = True, 0
    assert w.remctl.apply_remote() == ""
    try:
        auth = {"X-Token": w.cfg.api_token}
        status, body = call(qapp, w.remote, "/api/help", auth)
        assert status == 200 and "/api/live" in body["endpoints"]
        status, body = call(qapp, w.remote, "/api/volume?step=up", auth)
        assert status == 200 and body["volume"] == w.vol_sound.spin.value()
        assert call(qapp, w.remote, "/api/play?name=Nope", auth)[0] == 404
    finally:
        w.cfg.api_enabled = False
        w.remctl.apply_remote()


def test_live_speed_pitch_and_effects_go_through_the_popup(qapp, window):
    """A phone moves the PC's own sliders: the engine and the â© button follow."""
    w = window
    d = lambda action, **p: remote.dispatch(w, action, p)   # noqa: E731
    s = d("status")[1]
    assert (s["speed"], s["pitch"], s["keep_pitch"], s["effects"]) == (1.0, 0.0, True, {})

    assert d("speed", set="1.5")[1]["speed"] == 1.5 and w.engine.sound_speed == 1.5
    assert d("speed", step="up")[1]["speed"] == 2.0                 # the next quick speed
    assert d("speed", step="up")[1]["speed"] == 2.0                 # the top of the range
    assert d("speed", step="down")[1]["speed"] == 1.5
    assert d("speed", set="9")[1]["speed"] == 2.0                   # no Redline from a phone
    assert d("speed", set="fast")[0] == 400 and d("speed")[0] == 400
    assert d("speed", keep="0")[1]["keep_pitch"] is False and not w.engine.sound_keep_pitch
    assert d("pitch", set="-3")[1]["pitch"] == -3 and w.engine.sound_pitch == -3
    assert d("pitch", step="up")[1]["pitch"] == -2
    assert w.speed_btn.text().startswith("2x -2")      # the PC's button shows it

    assert d("effects", bass="6", echo="5")[1]["effects"] == {"bass": 6.0, "echo": 1.0}
    assert w.engine.sound_fx == {"bass": 6.0, "echo": 1.0}
    assert d("effects", bass="loud")[0] == 400
    body = d("effects")[1]                                         # alone: what there is
    assert "Nightcore" in body["presets"] and body["effects"] == {"bass": 6.0, "echo": 1.0}
    assert {"key": "bass", "label": "Bass", "lo": -12, "hi": 18, "unit": "dB"} in body["knobs"]
    body = d("effects", preset="nightcore")[1]                     # its speed too
    assert body["preset"] == "Nightcore" and w.speed_btn.fx_presets["Nightcore"].isChecked()
    assert (body["speed"], body["keep_pitch"]) == (1.3, False)
    assert d("effects", preset="Nope")[0] == 404
    assert d("effects", reset="1")[1]["effects"] == {}

    d("effects", bass="3")
    s = d("reset")[1]
    assert (s["speed"], s["pitch"], s["effects"]) == (1.0, 0.0, {})
    assert w.engine.sound_speed == 1.0 and w.engine.sound_fx == {}


def test_mode_lists_and_switches_whos_listening(qapp, window):
    w = window
    d = lambda action, **p: remote.dispatch(w, action, p)   # noqa: E731
    st, body = d("mode")
    assert st == 200 and body["mode"] == "off"
    assert {"off", "discord", "steam"} <= {m["key"] for m in body["modes"]}
    assert d("mode", set="Discord")[1]["mode"] == "discord"
    assert w.cfg.dest["mode"] == "discord" and w.engine.dest.key == "discord"
    assert w.mode_btn.currentData() == "advanced"      # one exact mode: Advanced
    assert d("mode", set="steam voice")[1]["mode"] == "steam"         # by its label too
    assert d("mode", set="nope")[0] == 404 and w.cfg.dest["mode"] == "steam"
    s = d("status")[1]
    assert s["mode"] == "steam" and s["mode_label"] == "Steam voice"
    assert s["simple"] == "advanced"
    st, body = d("mode", simple="Clean")
    assert st == 200 and body["simple"] == "clean" and body["mode"] == "off"
    assert {q["key"] for q in body["simples"]} == {"game", "voice", "clean", "advanced"}
    assert d("mode", simple="game")[1]["simple"] == "game" and w.engine.dest.key == "game"
    assert w.mode_btn.currentData() == "game"
    assert d("mode", simple="nope")[0] == 404
    assert "radio" in s and "available" in s["radio"]


def test_voices_say_queue_and_hear(qapp, window):
    """The Voice tab, the play queue and Hear what they hear, from a button."""
    from soundboard import voicefx
    w = window
    d = lambda action, **p: remote.dispatch(w, action, p)   # noqa: E731
    st, body = d("voices")
    names = [v["name"] for v in body["voices"]]
    assert st == 200 and names[:len(voicefx.PRESETS)] == list(voicefx.PRESETS)
    assert "Custom" not in names            # My own mix opens a window: not from a button
    st, body = d("voice", name="chipmunk")
    assert st == 200 and body == {"voice": True, "voice_name": "Chipmunk"}
    assert w.voice.fx.btn_power.isChecked() and d("status")[1]["voice_name"] == "Chipmunk"
    st, body = d("voice", name="chipmonk")
    assert st == 404 and body["did_you_mean"][0] == "Chipmunk"   # the closest first
    assert d("voice", on="0")[1]["voice"] is False

    said, stopped = [], []
    w.voice.speech.ctl.say = said.append
    w.voice.speech.ctl.stop_speaking = lambda: stopped.append(True)
    assert d("say", text="  hello   chat ") == (200, {"saying": "hello chat"})
    assert said == ["hello chat"] and "hello chat" in w.voice.speech.said_log.toPlainText()
    assert d("say")[0] == 400 and d("say", text="x" * 501)[0] == 400
    assert d("say", stop="1") == (200, {"stopped": True}) and stopped

    for sid in ("s0", "s1"):
        w.audio[sid] = np.zeros((48000, 2), np.float32)
    assert d("queue") == (200, {"queue": []})
    w.catctl.new_category(name="Memes")
    assert d("queue", category="memes")[0] == 404     # nothing in it yet
    for sid in ("s0", "s1"):
        w.catctl.toggle_tag(sid, "Memes")
    played = []
    w.playctl.play = lambda sid, now=False: played.append(sid)
    w.playctl._pads_playing = lambda: bool(played)
    st, body = d("queue", category="Memes")
    assert st == 200 and played == ["s0"] and body["queue"] == [{"id": "s1", "name": "Airhorn"}]
    st, body = d("queue", name="boom")
    assert st == 200 and [q["id"] for q in body["queue"]] == ["s1", "s0"]
    assert [q["name"] for q in d("status")[1]["queue"]] == ["Airhorn", "Boom"]
    assert d("queue", name="nope")[0] == 404 and d("queue", category="Nope")[0] == 404
    assert d("queue", clear="1") == (200, {"queue": []})
    played.clear()                                     # nothing playing: it plays at once
    st, body = d("queue", name="boom")
    assert st == 200 and body["playing"] == "s0" and "queued" not in body and body["queue"] == []
    st, body = d("queue", name="airhorn")              # now something is: it waits
    assert st == 200 and body["queued"] == "s1" and "playing" not in body
    d("queue", clear="1")

    assert d("hear", on="1") == (200, {"hear": True}) and w.engine.mic_check
    assert w.btn_check.isChecked() and d("status")[1]["hear"] is True
    assert d("hear") == (200, {"hear": False}) and not w.engine.mic_check
    assert d("hear", on="maybe")[0] == 400

    w.tabctl.set_tab_on("voice", False)
    assert d("voices")[0] == 409 and d("say", text="hi")[0] == 409
    assert d("voice", name="Chipmunk")[0] == 409 and "voice_name" in d("status")[1]


def test_settings_key_show_says_hide_and_turning_off_hides_it(qapp, window):
    from PySide6.QtWidgets import QLineEdit, QPushButton

    from soundboard.ui.settings.settings import SettingsDialog
    w = window
    w.cfg.api_port = 0
    d = SettingsDialog(w, "remote")
    try:
        d.remote_on.setChecked(True)
        key = next(e for e in d.findChildren(QLineEdit) if e.accessibleName() == "Key")
        show = next(b for b in d.findChildren(QPushButton) if b.text() == "Show")
        assert key.echoMode() == QLineEdit.Password
        show.click()
        assert key.echoMode() == QLineEdit.Normal and show.text() == "Hide"
        d.remote_on.setChecked(False)                 # off: the key is hidden again
        assert key.echoMode() == QLineEdit.Password and show.text() == "Show"
        assert not show.isChecked()
    finally:
        d.close()
        w.cfg.api_enabled = False
        w.remctl.apply_remote()


def test_a_volume_that_isnt_a_finite_number_is_refused(qapp):
    """?set=inf made round() raise OverflowError: a 500 instead of a 400."""
    from PySide6.QtWidgets import QSpinBox
    spin = QSpinBox()
    spin.setRange(0, 100)
    spin.setValue(40)
    for bad in ("inf", "-inf", "1e999", "nan", "loud"):
        status, _body = remote.set_volume(spin, {"set": bad})
        assert status == 400
    assert spin.value() == 40
    assert remote.set_volume(spin, {"set": "70"}) is None and spin.value() == 70


def test_key_image_draws_the_pad_as_a_stream_deck_key(qapp, window):
    import base64

    from PySide6.QtGui import QImage
    w = window
    d = lambda action, **p: remote.dispatch(w, action, p)   # noqa: E731

    def picture(body):
        assert body["image"].startswith("data:image/png;base64,")
        img = QImage()
        assert img.loadFromData(base64.b64decode(body["image"].split(",", 1)[1]), "PNG")
        return img
    status, body = d("key_image", id="s0")
    assert status == 200 and body["id"] == "s0"
    img = picture(body)
    assert (img.width(), img.height()) == (144, 144)
    assert img.pixelColor(72, 72).alpha() == 255          # the card fills the key
    # outside the key's curve: the card colour, never the window's darker background
    from soundboard.ui.kit.widgets import pad_colours
    card = pad_colours()["card"].name()
    corners = ((0, 0), (143, 0), (0, 143), (143, 143))
    assert [img.pixelColor(x, y).name() for x, y in corners] == [card] * 4
    lit = d("key_image", id="s0", playing="1")[1]
    assert lit["image"] != body["image"]                  # lit up while it plays
    assert picture(d("key_image", name="airhorn", size="9999")[1]).width() == 288
    assert d("key_image", id="nope")[0] == 404
    assert d("key_image", id="s0", size="big")[0] == 400
    # the sound list tells a plugin when to fetch it again
    looks = {s["id"]: s["look"] for s in d("sounds")[1]}
    assert looks["s0"] == body["look"]
    w.meta("s0").color = "#123456"
    assert d("sounds")[1][0]["look"] != body["look"]


def test_key_names_wrap_onto_two_lines(qapp):
    # a key is narrower than a card: one line left "Sad Trom…"
    from PySide6.QtGui import QFont, QFontMetrics

    from soundboard.control.keyimage import two_lines
    fm = QFontMetrics(QFont())
    narrow = fm.horizontalAdvance("Sad Trombone") - 1
    assert two_lines("Sad Trombone", fm, narrow) == "Sad\nTrombone"
    assert two_lines("Bruh", fm, 500) == "Bruh"
    long = two_lines("one two three four five six seven", fm, fm.horizontalAdvance("one two"))
    assert long.startswith("one two\n") and long.endswith("…") and long.count("\n") == 1
    assert "\n" not in two_lines("Supercalifragilistic", fm, 20)


def test_key_image_draws_stop_random_and_the_switches_as_cards_too(qapp, window):
    from soundboard.control import keyimage
    w = window
    d = lambda action, **p: remote.dispatch(w, action, p)   # noqa: E731
    tag = d("status")[1]["keys"]
    for kind in keyimage.CONTROLS:
        status, body = d("key_image", control=kind, on="1")
        assert status == 200 and body["image"].startswith("data:image/png;base64,")
        assert body["on"] is True and body["look"] == tag
    off = d("key_image", control="mic", on="0")[1]
    assert off["on"] is False and off["image"] != d("key_image", control="mic", on="1")[1]["image"]
    d("hotkeys", on="0")                               # no on=: as it is now
    assert d("key_image", control="hotkeys")[1]["on"] is False
    assert d("key_image", control="nope")[0] == 404
    assert d("key_image", control="mic", on="maybe") == (400, remote.BAD_ON)
    w.cfg.theme = "Light" if w.cfg.theme != "Light" else "Dark"
    assert d("status")[1]["keys"] != tag               # a plugin draws them again


def test_a_keys_hotkey_shows_even_when_it_is_a_combo(qapp, monkeypatch):
    # a key is always laid out 96 wide, and the board's own rule (a badge only when it
    # takes under 68 % of the footer) left "Ctrl+Alt+7" off every key
    from PySide6.QtGui import QFontMetrics

    from soundboard.control import keyimage
    from soundboard.sounds.library import SoundMeta
    from soundboard.ui.kit import widgets
    from soundboard.ui.kit.hotkeypick import pretty_key

    seen = []
    board = widgets.Pad._footer

    def spy(self, foot, name_font):
        out = board(self, foot, name_font)
        seen.append((foot.width(), out[0]))
        return out
    monkeypatch.setattr(widgets.Pad, "_footer", spy)

    def badge_pixels(hotkey):
        meta = SoundMeta(id="k", name="Airhorn", file="", hotkey=hotkey, duration=2.0)
        img = keyimage._card(meta, False, 144)[0].toImage()
        ink = widgets.pad_colours()["badge"]
        return sum(img.pixelColor(x, y) == ink for x in range(0, 72) for y in range(110, 144))

    assert badge_pixels("") == 0
    width, font = seen[-1]
    fm = QFontMetrics(font)
    # one the board's rule drops but that fits the key's footer (which one depends on
    # the font: CI has no real fonts)
    combo = next(c for c in ("ctrl+alt+7", "alt+a", "ctrl+7", "f12+a")
                 if 0.68 * width < fm.horizontalAdvance(pretty_key(c)) + 12 <= width)
    assert badge_pixels(combo) > 0


def test_a_small_keys_length_is_drawn_bigger(qapp):
    """A 72 px key is the 96 px card drawn smaller: its length was a few pixels high.
    It grows on a small key: its ink is taller than half of a 144 px key's."""
    from soundboard.control import keyimage
    from soundboard.sounds.library import SoundMeta
    from soundboard.ui.kit import widgets

    def ink_rows(size):
        """How many pixel rows the footer's right half (the length) has ink in."""
        meta = SoundMeta(id="k", name="Airhorn", file="", duration=12.4)
        img = keyimage._card(meta, False, size)[0].toImage()
        bg = widgets.pad_colours()["card"].lightness()
        top, left = size * 2 // 3, size // 2
        return sum(any(img.pixelColor(x, y).lightness() > bg + 60
                       for x in range(left, size - 2)) for y in range(top, size - 2))

    big, small = ink_rows(144), ink_rows(72)
    assert big > 0
    assert small >= big / 2 * 1.25
