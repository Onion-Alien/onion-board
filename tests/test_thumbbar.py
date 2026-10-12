"""The buttons in the taskbar's hover preview. No real taskbar is touched: the
tests run on Qt's offscreen platform, where ThumbBar never talks to Windows."""
import ctypes
import sys

import pytest
from test_mainwindow import window  # noqa: F401

from soundboard import thumbbar


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
    window.thumbbar.click(thumbbar.PAUSE)
    window.thumbbar.click(thumbbar.STOP)
    assert calls == ["pause", "stop"]


def test_pause_button_turns_into_play_while_paused(window, monkeypatch):  # noqa: F811
    sid = next(iter(window._meta), None)
    if sid is None:
        pytest.skip("no sounds on the test board")
    states = {sid: (0.5, False)}
    monkeypatch.setattr(window.engine, "playing", lambda: dict(states))
    window.tick()
    assert not window.thumbbar.paused   # playing: Pause
    states[sid] = (0.5, True)
    window.tick()
    assert window.thumbbar.paused       # all paused: Play
    states.clear()
    window.tick()
    assert not window.thumbbar.paused   # nothing at all: back to Pause
