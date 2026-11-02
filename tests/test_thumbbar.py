"""The buttons in the taskbar's hover preview. No real taskbar is touched: the
tests run on Qt's offscreen platform, where ThumbBar never talks to Windows."""
import ctypes
import sys

import pytest
from test_mainwindow import window  # noqa: F401

from soundboard.win import thumbbar


def test_offscreen_never_listens(qapp):
    tb = thumbbar.ThumbBar(None, {})
    assert tb._created == 0
    assert tb.native_event(0) is False   # not even read: the address is never used


def test_each_button_runs_its_action():
    hits = []
    tb = thumbbar.ThumbBar(None, {i: (lambda i=i: hits.append(i)) for i in thumbbar.ORDER})
    for i in thumbbar.ORDER:
        tb.click(i)
    tb.click(99)   # not ours: ignored
    assert hits == list(thumbbar.ORDER)


@pytest.mark.skipif(sys.platform != "win32", reason="HICONs are Windows only")
def test_buttons_have_icons_and_tips(window):  # noqa: F811
    tb = window.thumbbar
    btns = tb.buttons()
    try:
        assert [b.iId for b in btns] == list(thumbbar.ORDER)
        assert all(b.hIcon and b.szTip for b in btns)
        assert btns[-1].szTip == thumbbar.live_tip(True)
        # a few words on the small hover flyout: the long forms live in the rail's tooltips
        assert all(len(b.szTip) <= 32 for b in btns), [b.szTip for b in btns]
    finally:
        for b in btns:
            ctypes.windll.user32.DestroyIcon(ctypes.c_void_p(b.hIcon))


def test_live_button_follows_the_master_switch(window):  # noqa: F811
    assert window.thumbbar.live
    window.thumbbar.click(thumbbar.LIVE)
    assert not window.engine.sending and not window.thumbbar.live
    window.thumbbar.click(thumbbar.LIVE)
    assert window.engine.sending and window.thumbbar.live


def test_stop_and_pause_buttons(window, monkeypatch):  # noqa: F811
    calls = []
    monkeypatch.setattr(window.engine, "stop_all", lambda: calls.append("stop"))
    monkeypatch.setattr(window.engine, "pause_all", lambda: calls.append("pause"))
    monkeypatch.setattr(window.engine, "playing", lambda: {"x": (0.5, False)})
    window.thumbbar.click(thumbbar.PAUSE)
    window.thumbbar.click(thumbbar.STOP)
    assert calls == ["pause", "stop"]


def test_pause_button_turns_into_play_while_paused(window, monkeypatch):  # noqa: F811
    sid = next(iter(window._meta), None)
    if sid is None:
        pytest.skip("no sounds on the test board")
    states = {sid: (0.5, False)}
    monkeypatch.setattr(window.engine, "playing", lambda: dict(states))
    window.tickctl.tick()
    assert not window.thumbbar.paused   # playing: Pause
    states[sid] = (0.5, True)
    window.tickctl.tick()
    assert window.thumbbar.paused       # all paused: Play
    states.clear()
    window.tickctl.tick()
    assert not window.thumbbar.paused   # nothing at all: back to Pause


class _FakeRadio:
    """Just enough of the Radio tab: a station on or off, and what was played."""

    def __init__(self, station=None):
        self.player = type("P", (), {"station": station})()
        self.played = []

    def is_active(self):
        return self.player.station is not None

    def stop(self):
        self.player.station = None

    def play(self, s):
        self.played.append(s)
        self.player.station = s

    def __getattr__(self, name):   # the rest (the window's shutdown, ...): nothing
        return lambda *a, **k: None


def _fake_sounds(win, monkeypatch, states):
    def pause_all():
        resume = bool(states) and all(p for _x, p in states.values())
        for sid in states:
            states[sid] = (0.5, not resume)
    monkeypatch.setattr(win.engine, "playing", lambda: dict(states))
    monkeypatch.setattr(win.engine, "pause_all", pause_all)


def test_pause_stops_the_radio_and_play_brings_it_back(window, monkeypatch):  # noqa: F811
    _fake_sounds(window, monkeypatch, {})
    monkeypatch.setattr(window, "radio", _FakeRadio("station-a"))
    window.thumbbar.click(thumbbar.PAUSE)
    assert not window.radio.is_active()
    window.tickctl.tick()
    assert window.thumbbar.paused   # only the radio was on: Play
    window.thumbbar.click(thumbbar.PAUSE)
    assert window.radio.played == ["station-a"]
    window.tickctl.tick()
    assert not window.thumbbar.paused


def test_pause_pauses_a_sound_and_the_radio_together(window, monkeypatch):  # noqa: F811
    sid = next(iter(window._meta), None)
    if sid is None:
        pytest.skip("no sounds on the test board")
    states = {sid: (0.5, False)}
    _fake_sounds(window, monkeypatch, states)
    monkeypatch.setattr(window, "radio", _FakeRadio("station-a"))
    window.thumbbar.click(thumbbar.PAUSE)
    assert states[sid][1] and not window.radio.is_active()
    window.tickctl.tick()
    assert window.thumbbar.paused
    window.thumbbar.click(thumbbar.PAUSE)
    assert not states[sid][1] and window.radio.played == ["station-a"]


def test_stop_all_forgets_the_paused_station(window, monkeypatch):  # noqa: F811
    _fake_sounds(window, monkeypatch, {})
    monkeypatch.setattr(window, "radio", _FakeRadio("station-a"))
    window.thumbbar.click(thumbbar.PAUSE)
    window.playctl.stop_all()
    window.thumbbar.click(thumbbar.PAUSE)   # nothing left to bring back
    assert window.radio.played == []


class _Win:
    def devicePixelRatioF(self):
        return 1.0


def _counting_bar(monkeypatch):
    tb = thumbbar.ThumbBar(_Win(), {})
    tb._added = True
    pushed = []

    def push(slot):
        pushed.append(slot)
        tb._shown = tb._look()
    monkeypatch.setattr(tb, "_push", push)
    monkeypatch.setattr(thumbbar, "light_windows", lambda: False)
    return tb, pushed


def test_buttons_are_pushed_only_when_they_look_different(qapp, monkeypatch):
    tb, pushed = _counting_bar(monkeypatch)
    tb.refresh()
    assert pushed == [thumbbar.SLOT_UPDATE]
    for _ in range(5):   # a setting nothing to do with them: Windows isn't asked again
        tb.refresh()
    assert len(pushed) == 1
    tb.set_live(False)
    assert len(pushed) == 2
    monkeypatch.setattr(thumbbar, "light_windows", lambda: True)   # light mode
    tb.refresh()
    assert len(pushed) == 3


def test_settings_changes_in_a_row_refresh_once_later(qapp, monkeypatch):
    from PySide6.QtTest import QTest
    tb, pushed = _counting_bar(monkeypatch)
    refreshed = []
    monkeypatch.setattr(tb, "refresh", lambda: refreshed.append(1))
    for _ in range(5):
        tb._settle()
    assert not refreshed                 # never inside the broadcast itself
    QTest.qWait(thumbbar.SETTLE_MS + 300)
    assert refreshed == [1]
