"""The Discord / game guides, the Discord check's plumbing (with a fake Discord
capture) and the cable-format fix on the Setup tab. Offscreen, fake devices."""
from types import SimpleNamespace

import numpy as np
import pytest

from soundboard.audio import appaudio
from soundboard.mic import cableformat
from soundboard.sim import chatcheck
from soundboard.ui.setup import chatguide, steamguide
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
    from soundboard.ui.kit import busy
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
    wiz.go(wiz.discord_index)
    g = chatguide.GameGuide(wiz, w, "CABLE Output")
    assert "noise" in _text(g).lower()
    g.setParent(None)
    g = chatguide.MeetingGuide(wiz, w, "CABLE Output")
    text = _text(g)
    assert all(app in text for app in ("Zoom", "Teams", "browser", "Who's listening"))
    g.setParent(None)
    for cls in (chatguide.DiscordGuide, chatguide.GameGuide, chatguide.MeetingGuide,
                steamguide.SteamGuide):
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


def test_check_that_fails_to_start_says_so_and_can_run_again(wizard, monkeypatch):
    """Making the test sound (or finding Discord) raising on the worker: the check
    reports it instead of staying 'running' with nothing left to finish it."""
    w, _ = wizard
    w.engine.main_stream = object()
    monkeypatch.setattr(appaudio, "supported", lambda: (True, ""))
    monkeypatch.setattr(chatguide, "find_discord", lambda: object())

    def broken():
        raise ImportError("DLL load failed while importing _generator")
    monkeypatch.setattr(chatcheck, "test_signal", broken)
    got = []
    c = chatguide.ChatCheck(w.engine)
    c.done.connect(got.append)
    c.start()
    assert process_events(chatguide.QApplication.instance(), lambda: got, timeout=5)
    assert "_generator" in got[0]["error"] and not c.running
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
    w.micctl._check_cable_format()
    assert w.micctl.cable_bad == [bad]
    w.statusctl._update_status()
    assert "44.1 kHz" in w.setup_hint.text()
    assert w.micctl.fix_cable_format()
    assert state["set"] == [(bad.name, 48000)]
    assert w.micctl.cable_bad == []


@pytest.mark.parametrize("rate", [44100, 96000])
def test_cable_end_ok_only_at_48k(rate):
    assert not cableformat.CableEnd("x", "render", "i", rate, 24, 2).ok
    assert cableformat.CableEnd("x", "render", "i", 48000, 24, 2).ok


@pytest.mark.windows   # Windows' struct layouts (a 4-byte long)
def test_with_rate_rewrites_rate_and_byte_rate():
    from soundboard.audio.appaudio import WAVEFORMATEX
    wf = WAVEFORMATEX(1, 2, 44100, 44100 * 4, 4, 16, 0)
    raw = bytearray(bytes(wf))
    out = cableformat._with_rate(raw, 48000)
    assert cableformat._parse(out) == (48000, 16, 2)
    assert WAVEFORMATEX.from_buffer_copy(bytes(out)).nAvgBytesPerSec == 48000 * 4


def _discord(**kw):
    from soundboard.mic import discordcfg
    base = dict(client="Discord", profile="CUSTOM", krisp=True, suppression=False,
                echo=True, agc=False, bypass=False, vad=False, input_device="default",
                stamp=0.0, auto=True)
    return discordcfg.Settings(**{**base, **kw})


def test_setting_changes_name_each_switch_from_and_to():
    rows = chatguide.setting_changes(
        _discord(), _discord(krisp=False, echo=False, auto=False, ptt=True))
    assert ("Noise Suppression", "Krisp", "None") in rows
    assert ("Echo Cancellation", "On", "Off") in rows
    assert ("Input Mode", "Voice Activity", "Push to Talk") in rows
    # on Push to Talk the sensitivity switch isn't there: no "auto: On -> Off" row
    assert not any(r[0].startswith("Automatically") for r in rows)
    assert chatguide.setting_changes(_discord(), _discord()) == []
    rows = chatguide.setting_changes(_discord(profile="VOICE_ISOLATION"), _discord())
    assert ("Input Profile", "Voice Isolation", "Custom") in rows


def test_guide_cheers_with_what_changed_once_discord_is_fixed(wizard, monkeypatch):
    """Fix Discord: once the guide sees the settings come right, a window with Bun
    says exactly what changed; closing it closes the guide too."""
    w, wiz = wizard
    monkeypatch.setattr(chatguide.DiscordGuide, "_read_settings", lambda self: None)
    g = chatguide.DiscordGuide(wiz, w, "CABLE Output")
    g._settings_in(1, [_discord()])
    assert g.fixed is None
    g._settings_in(2, [_discord(krisp=False, echo=False, auto=False)])
    app = chatguide.QApplication.instance()
    assert process_events(app, lambda: g.fixed is not None, timeout=2)
    t = g.fixed.table.text()
    assert "Noise Suppression" in t and "Krisp" in t and "None" in t
    assert "Echo Cancellation" in t and "Automatic Gain Control" not in t
    assert g.fixed.bun.celebrate
    g._settings_in(3, [_discord(krisp=False, echo=False, auto=False, agc=True)])
    g._settings_in(4, [_discord(krisp=False, echo=False, auto=False)])
    process_events(app, lambda: False, timeout=0.2)
    shown = g.fixed
    shown.accept()
    assert g.result() == chatguide.QDialog.DialogCode.Accepted
    g.done(0)


# ---------------------------------------------------------------- Bun sets Discord up

class _Setup:
    """discordtalk stood in: what set_up finds, and what was asked of it."""

    def __init__(self, monkeypatch, first, then=None):
        from soundboard.mic import discordtalk
        from soundboard.ui.kit import busy
        self.calls, self.closed, self.opened, self.fixed, self.toasts = [], [], [], [], []
        self.untoasted: list[str] = []
        answers = [first, then or first]

        def set_up(saved, root, on_mic, **k):
            self.calls.append(saved)
            return dict(answers[min(len(self.calls) - 1, 1)])
        monkeypatch.setattr(discordtalk, "set_up", set_up)
        monkeypatch.setattr(discordtalk, "installed", lambda: True)
        monkeypatch.setattr(discordtalk, "close_clients",
                            lambda dirs: self.closed.append(list(dirs)) or True)
        monkeypatch.setattr(busy, "open_url", lambda url, *a, **k: self.opened.append(url))
        monkeypatch.setattr(busy, "toast", lambda w, text, *a, **k: self.toasts.append(text))
        monkeypatch.setattr(chatguide.toastmod, "close",
                            lambda w, key: self.untoasted.append(key))
        monkeypatch.setattr(chatguide.DiscordFixed, "exec",
                            lambda box: self.fixed.append(box.table.text()) or 0)


def _talking():
    from soundboard.mic import discordcfg
    return discordcfg.Settings(client="Discord", profile="CUSTOM", krisp=True,
                               suppression=False, echo=True, agc=True, bypass=False,
                               vad=False, input_device="default", stamp=0.0)


def _sound():
    from dataclasses import replace
    return replace(_talking(), krisp=False, echo=False, agc=False)


def _run(qapp, monkeypatch, wiz_window, first, then=None, close=True):
    w = wiz_window
    fake = _Setup(monkeypatch, first, then)
    asked = []
    monkeypatch.setattr(chatguide.DiscordSetUp, "_ask_to_close",
                        lambda self: asked.append(1) or close)
    done = []
    chatguide.set_up_discord(w, then=lambda: done.append(1))
    assert process_events(qapp, lambda: done, timeout=5)
    return fake, asked


def test_set_up_discord_saves_talk_writes_and_shows_what_changed(qapp, wizard, monkeypatch):
    w, _wiz = wizard
    w.cfg.discord_talk = {}
    fake, asked = _run(qapp, monkeypatch, w, {
        "done": [("Discord", _talking(), _sound())], "running": [], "failed": [],
        "talk": {"discord": {"noiseCancellation": True}}})
    assert not asked and fake.closed == []
    assert w.cfg.discord_talk == {"discord": {"noiseCancellation": True}}   # to put back
    assert fake.opened == [chatguide.DISCORD_VOICE_URL]   # Discord, on its voice page
    assert fake.fixed and "Echo" in fake.fixed[0]          # exactly what changed
    assert fake.untoasted == ["discord-setup"]   # no "setting up…" left under the box


def test_an_open_discord_is_asked_about_then_closed_and_set(qapp, wizard, monkeypatch):
    w, _wiz = wizard
    fake, asked = _run(qapp, monkeypatch, w,
                       {"done": [], "running": ["discord"], "failed": [], "talk": {}},
                       {"done": [("Discord", _talking(), _sound())], "running": [],
                        "failed": [], "talk": {}})
    assert asked == [1] and fake.closed == [["discord"]] and len(fake.calls) == 2
    assert fake.opened == [chatguide.DISCORD_VOICE_URL] and fake.fixed


def test_not_now_leaves_an_open_discord_alone(qapp, wizard, monkeypatch):
    w, _wiz = wizard
    fake, asked = _run(qapp, monkeypatch, w,
                       {"done": [], "running": ["discord"], "failed": [], "talk": {}},
                       close=False)
    assert asked == [1] and fake.closed == [] and len(fake.calls) == 1
    assert fake.opened == [] and fake.fixed == []
    assert fake.untoasted == ["discord-setup"]   # its "setting up…" goes with the box
    assert getattr(w, "_discord_setup", None) is None   # can be asked again


def test_an_already_right_discord_just_says_so(qapp, wizard, monkeypatch):
    w, _wiz = wizard
    fake, _asked = _run(qapp, monkeypatch, w,
                        {"done": [], "running": [], "failed": [], "talk": {}})
    assert fake.opened == [] and fake.fixed == []
    assert any("already set up" in t for t in fake.toasts)


def test_a_failed_set_up_falls_back_to_the_guide(qapp, wizard, monkeypatch):
    w, _wiz = wizard
    shown = []
    monkeypatch.setattr(chatguide, "show_guide", lambda which, *a: shown.append(which))
    fake = _Setup(monkeypatch, {"done": [], "running": [], "failed": ["Discord"],
                                "talk": {}})
    chatguide.set_up_discord(w, then=lambda: shown.append("then"))
    assert process_events(qapp, lambda: shown, timeout=5)
    assert shown == ["discord"] and fake.fixed == []   # the guide, not then on top


def test_the_discord_guide_offers_to_do_it(wizard):
    w, wiz = wizard
    g = chatguide.DiscordGuide(wiz, w, "CABLE Output")
    assert g.btn_auto.text() == "Set it up for me" and g.btn_auto.toolTip()
    g.done(0)


# ---------------------------------------------------------- Clean mic takes over

class _Clean:
    """The Voice tab's Clean mic stood in: ok (in this copy), and its switch."""

    def __init__(self, on=False, ok=True):
        self.on, self.ok, self.asked = on, ok, []

    def is_on(self):
        return self.on

    def set_on(self, on):
        self.asked.append(on)
        self.on = on


def _boxes(monkeypatch):
    """Each DiscordFixed shown: (its Clean mic words or None, its Open Clean mic button)."""
    shown = []
    monkeypatch.setattr(chatguide.DiscordFixed, "exec", lambda box: shown.append(
        (box.clean.text() if box.clean else None,
         box.btn_clean.text() if box.btn_clean else None)) or 0)
    return shown


def _set_up_with(qapp, monkeypatch, w, voice):
    """Bun sets Discord up with this Voice tab stood in (put back before the window
    closes: closing it shuts the real one down)."""
    done = []
    with monkeypatch.context() as m:
        m.setattr(w, "voice", voice, raising=False)
        chatguide.set_up_discord(w, then=lambda: done.append(1))
        assert process_events(qapp, lambda: done, timeout=5)


def test_setting_discord_up_turns_clean_mic_on_in_its_place(qapp, wizard, monkeypatch):
    """Bun turns Discord's noise filter off: Clean mic goes on instead, and the box says
    so with a button to it (to turn it off again there)."""
    w, _wiz = wizard
    clean = _Clean()
    fake = _Setup(monkeypatch, {"done": [("Discord", _talking(), _sound())],
                                "running": [], "failed": [], "talk": {}})
    shown = _boxes(monkeypatch)
    _set_up_with(qapp, monkeypatch, w, SimpleNamespace(clean=clean))
    assert clean.asked == [True] and clean.on
    words, button = shown[0]
    assert "Bun turned on" in words and "Clean mic" in words
    assert button == "Open Clean mic"
    assert fake.calls


@pytest.mark.parametrize("make, noisy, says", [
    (lambda: _Clean(on=True), True, "is on"),     # already on: left alone
    (_Clean, False, "Turn on"),                   # Discord's filter was off already
    (lambda: _Clean(ok=False), True, None),       # no Clean mic in this copy
    (lambda: None, True, None),                   # the Voice tab switched off
])
def test_clean_mic_is_left_alone_when_it_should_be(qapp, wizard, monkeypatch, make,
                                                   noisy, says):
    w, _wiz = wizard
    clean, before = make(), _talking() if noisy else _sound()
    voice = SimpleNamespace(clean=clean) if clean is not None else SimpleNamespace()
    _Setup(monkeypatch, {"done": [("Discord", before, _sound())], "running": [],
                         "failed": [], "talk": {}})
    shown = _boxes(monkeypatch)
    _set_up_with(qapp, monkeypatch, w, voice)
    if clean is not None:
        assert clean.asked == []
    words, button = shown[0]
    if says is None:
        assert words is None and button is None
    else:
        assert says in words and button is not None


def test_open_clean_mic_shows_its_card_on_the_voice_tab(monkeypatch):
    opened, current = [], []
    mw = SimpleNamespace(tabctl=SimpleNamespace(tab_on=lambda key: key == "voice"),
                         tabs=SimpleNamespace(setCurrentWidget=current.append),
                         voice=SimpleNamespace(_open_card=opened.append))
    monkeypatch.setattr(chatguide.usage, "used", lambda key: None)
    chatguide.open_clean_mic(mw)
    assert current == [mw.voice] and opened == ["clean"]
    mw.tabctl = SimpleNamespace(tab_on=lambda key: False)   # the tab off: nowhere to go
    chatguide.open_clean_mic(mw)
    assert opened == ["clean"]


def test_the_guides_say_clean_mic_is_on_or_how_to_turn_it_on():
    on = SimpleNamespace(voice=SimpleNamespace(clean=_Clean(on=True)))
    assert "is on" in chatguide.clean_mic_tip(on)
    assert "Turn on" in chatguide.clean_mic_tip(None)
    assert "Turn on" in chatguide.clean_mic_tip(SimpleNamespace(voice=SimpleNamespace(
        clean=_Clean())))
