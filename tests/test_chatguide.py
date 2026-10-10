"""The Discord / game guides, the Discord check's plumbing (with a fake Discord
capture) and the cable-format fix on the Setup tab. Offscreen, fake devices."""
import numpy as np
import pytest

from soundboard import appaudio, cableformat, chatcheck
from soundboard.ui import chatguide, setupwizard
from tests import test_setupwizard as _sw
from tests.conftest import process_events

devices, wizard = _sw.devices, _sw.wizard   # the guide's fixtures, shared


def _text(dlg) -> str:
    return " ".join(lbl.text() for lbl in dlg.findChildren(chatguide.QLabel))


def test_discord_guide_says_studio_and_names_the_mic(wizard):
    w, wiz = wizard
    g = chatguide.DiscordGuide(wiz, w, "CABLE Output (VB-Audio Virtual Cable)")
    t = _text(g)
    assert "Studio" in t and "CABLE Output (VB-Audio Virtual Cable)" in t
    assert "Automatically determine input sensitivity" in t
    g.done(0)


def test_check_keeps_the_focus_on_its_button(wizard, monkeypatch):
    """Clicking Check Discord greys it out without setEnabled(False), which would move
    the keyboard focus to the next control; a second click while checking does nothing."""
    from soundboard.ui import busy
    w, wiz = wizard
    g = chatguide.DiscordGuide(wiz, w, "CABLE Output")
    starts = []
    monkeypatch.setattr(g, "_start_check", lambda: starts.append(1))
    g.check()
    assert busy.is_busy(g.btn_check) and g.btn_check.isEnabled()
    assert g.btn_check.text() == "Checking…"
    g.check()                        # a double click
    from tests.conftest import process_events
    process_events(chatguide.QApplication.instance(), lambda: starts, timeout=2)
    g._checked({"issues": []})
    assert not busy.is_busy(g.btn_check) and g.btn_check.text() == "Check again"
    assert len(starts) == 1
    g.done(0)


def test_game_guide_and_freeing(wizard, monkeypatch):
    w, wiz = wizard
    wiz.go(3)
    g = chatguide.GameGuide(wiz, w, "CABLE Output")
    assert "noise" in _text(g).lower()
    g.setParent(None)
    g = chatguide.MeetingGuide(wiz, w, "CABLE Output")
    text = _text(g)
    assert all(app in text for app in ("Zoom", "Teams", "browser", "Who's listening"))
    g.setParent(None)
    for cls in (chatguide.DiscordGuide, chatguide.GameGuide, chatguide.MeetingGuide,
                setupwizard.SteamGuide):
        monkeypatch.setattr(cls, "exec", lambda self: 0)
    for which in ("discord", "game", "meeting", "steam"):
        wiz.show_guide(which)
    assert not wiz.findChildren(chatguide.DiscordGuide)
    assert not wiz.findChildren(chatguide.GameGuide)
    assert not wiz.findChildren(chatguide.MeetingGuide)


def test_result_text_covers_every_issue():
    for issue in chatcheck.ISSUES:
        html = chatguide.result_html({"issues": [issue]}, "CABLE Output")
        assert "<li" in html
    assert "clean" in chatguide.result_html({"issues": []}, "CABLE Output")
    assert "nope" in chatguide.result_html({"issues": [], "error": "nope"}, "x")


def test_error_text_and_device_names_are_shown_as_typed(wizard):
    """A device called "Mic <USB> & Co" or an error quoting markup isn't read as HTML."""
    vm = "Mic <USB> & Co"
    html = chatguide.result_html({"issues": ["not_heard"]}, vm)
    assert "Mic &lt;USB&gt; &amp; Co" in html and vm not in html
    html = chatguide.result_html({"issues": [], "error": "bad <b>value</b>"}, vm)
    assert "bad &lt;b&gt;value&lt;/b&gt;" in html
    w, wiz = wizard
    for cls in (chatguide.DiscordGuide, chatguide.GameGuide, chatguide.MeetingGuide):
        g = cls(wiz, w, vm)
        assert "Mic &lt;USB&gt; &amp; Co" in _text(g) and vm not in _text(g)
        g.done(0)


def test_check_without_discord_explains(wizard, monkeypatch):
    w, _ = wizard
    w.engine.main_stream = object()   # the fake devices don't open real streams
    monkeypatch.setattr(appaudio, "supported", lambda: (True, ""))
    monkeypatch.setattr(chatguide, "find_discord", lambda: None)
    got = []
    c = chatguide.ChatCheck(w.engine)
    c.done.connect(got.append)
    c.start()
    assert process_events(chatguide.QApplication.instance(), lambda: got, timeout=5)
    assert "Let's Check" in got[0]["error"] and not c.running
    w.engine.main_stream = None


class _FakeCapture:
    """Plays Discord: 'captures' whatever the engine tapped, 0.3 s late, halved."""

    engine = None
    made = []
    opening = False   # Windows still opening it (start(wait=False) returned already)

    def __init__(self, pid, sink, include_tree=True, name=""):
        self.sink, self.error = sink, None
        self.waited = None
        _FakeCapture.made.append(self)

    def start(self, timeout=6.0, wait=True):
        self.start_waited = wait
        return True

    @property
    def ready(self):
        return not _FakeCapture.opening

    def stop(self, wait=True):
        self.waited = wait
        tap = np.concatenate(self.engine.main_tap or [np.zeros((1, 2), np.float32)])
        self.sink(np.zeros((int(0.3 * chatcheck.SR), 2), np.float32))
        self.sink(tap * 0.5)


def test_check_runs_end_to_end_with_a_clean_discord(wizard, monkeypatch):
    w, _ = wizard
    e = w.engine
    e.main_stream = object()
    monkeypatch.setattr(appaudio, "supported", lambda: (True, ""))
    monkeypatch.setattr(chatguide, "find_discord",
                        lambda: appaudio.App(pid=4242, exe="Discord.exe"))
    _FakeCapture.engine = e
    monkeypatch.setattr(appaudio, "AppCapture", _FakeCapture)
    played = []
    monkeypatch.setattr(e, "play", lambda *a, **k: played.append(k.get("only")))
    got = []
    c = chatguide.ChatCheck(e)
    c.done.connect(got.append)
    c.start()
    app = chatguide.QApplication.instance()
    assert process_events(app, lambda: played, timeout=5)
    assert played == ["main"] and c.running
    # what the main output would have sent while the test played
    e.main_tap.extend(np.array_split(chatcheck.test_signal(), 200))
    c._timer.stop()
    c._finish()
    assert c.running and not got                  # the comparison runs on a worker
    assert process_events(app, lambda: got, timeout=10)
    assert got[0]["issues"] == [] and not c.running
    assert e.main_tap is None
    e.main_stream = None


def test_check_never_waits_on_the_window_thread(wizard, monkeypatch):
    """Finding Discord runs on a worker, the capture is started without waiting and
    polled, and stopping it doesn't wait either (Windows can take seconds to open
    it). Cancelling while it opens drops the check without a result."""
    import threading
    w, _ = wizard
    e = w.engine
    e.main_stream = object()
    monkeypatch.setattr(appaudio, "supported", lambda: (True, ""))
    where = []

    def find():
        where.append(threading.current_thread() is threading.main_thread())
        return appaudio.App(pid=4242, exe="Discord.exe")
    monkeypatch.setattr(chatguide, "find_discord", find)
    _FakeCapture.engine, _FakeCapture.made, _FakeCapture.opening = e, [], True
    monkeypatch.setattr(appaudio, "AppCapture", _FakeCapture)
    played = []
    monkeypatch.setattr(e, "play", lambda *a, **k: played.append(1))
    got = []
    c = chatguide.ChatCheck(e)
    c.done.connect(got.append)
    c.start()
    app = chatguide.QApplication.instance()
    assert process_events(app, lambda: _FakeCapture.made, timeout=5)
    assert where == [False]
    cap = _FakeCapture.made[0]
    assert cap.start_waited is False
    process_events(app, lambda: False, timeout=0.2)
    assert not played and c.running              # still opening: nothing played yet
    e.main_tap = []
    c.cancel()
    assert cap.waited is False and not c.running and e.main_tap is None
    _FakeCapture.opening = False
    process_events(app, lambda: False, timeout=0.2)
    assert not played and not got
    # a check whose capture never opens gives up with a message
    _FakeCapture.opening = True
    monkeypatch.setattr(chatguide, "CONNECT_S", 0.1)
    c.start()
    assert process_events(app, lambda: got, timeout=5)
    assert "in time" in got[0]["error"] and not played and not c.running
    _FakeCapture.opening = False
    e.main_stream = None


def test_setup_tab_offers_and_applies_the_cable_fix(wizard, monkeypatch):
    w, _ = wizard
    bad = cableformat.CableEnd("CABLE Output (VB-Audio Virtual Cable)", "capture", "{id}",
                               44100, 16, 2)
    state = {"ends": [bad], "set": []}
    monkeypatch.setattr(cableformat, "cable_ends", lambda names_hint=None: state["ends"])

    def set_rate(end, rate=cableformat.RATE):
        state["set"].append((end.name, rate))
        state["ends"] = []
        return True
    monkeypatch.setattr(cableformat, "set_rate", set_rate)
    w.cfg.main_device = "CABLE Input (VB-Audio Virtual Cable)"
    w._check_cable_format()
    assert w.cable_bad == [bad]
    w._update_status()
    assert "44.1 kHz" in w.setup_hint.text()
    assert w.fix_cable_format()
    assert state["set"] == [(bad.name, 48000)]
    assert w.cable_bad == []


@pytest.mark.parametrize("rate", [44100, 96000])
def test_cable_end_ok_only_at_48k(rate):
    assert not cableformat.CableEnd("x", "render", "i", rate, 24, 2).ok
    assert cableformat.CableEnd("x", "render", "i", 48000, 24, 2).ok


@pytest.mark.windows   # Windows' struct layouts (a 4-byte long)
def test_with_rate_rewrites_rate_and_byte_rate():
    from soundboard.appaudio import WAVEFORMATEX
    wf = WAVEFORMATEX(1, 2, 44100, 44100 * 4, 4, 16, 0)
    raw = bytearray(bytes(wf))
    out = cableformat._with_rate(raw, 48000)
    assert cableformat._parse(out) == (48000, 16, 2)
    assert WAVEFORMATEX.from_buffer_copy(bytes(out)).nAvgBytesPerSec == 48000 * 4
