"""Edit sound's big waveform as a seek bar: a click or drag on its time ruler, or a
drag of the playhead, moves the playing sound there (without fighting the handles,
the splices or the right-drag pan); and a trim or splices changed while it plays go
on from the same spot in the file, or the start of what's kept when that was cut."""
import time

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from soundboard.audio import soundfx
from soundboard.ui.kit import worker
from soundboard.ui.sounds import dialogs
from soundboard.ui.sounds.trim import RULER_H, Waveform
from soundboard.ui.window import editcontrol
from test_live_effects import engine_with, song
from test_mainwindow import window  # noqa: F401

LEFT = Qt.MouseButton.LeftButton
NO = Qt.KeyboardModifier.NoModifier
L = 120.0


# ------------------------------------------------------------------ where it is

def test_a_trim_moved_past_the_spot_goes_to_its_start():
    """Playing at 0:30, the trim set to start at 1:00: from 1:00, not 1:30."""
    old, new = {}, {"start": 60.0}
    frac = soundfx.frac_at(old, L, 30.0)
    assert soundfx.time_at(new, L, soundfx.moved_frac(old, new, L, frac)) == pytest.approx(60.0)
    # still inside what's kept: it carries on from there
    at = soundfx.moved_frac(old, {"start": 10.0}, L, frac)
    assert soundfx.time_at({"start": 10.0}, L, at) == pytest.approx(30.0)


def test_splices_go_to_the_next_one_that_plays():
    fx = {"splices": [[10, 20], [50, 60], [80, 90]], "joined": True}
    assert soundfx.time_at(fx, L, soundfx.frac_at(fx, L, 30.0)) == pytest.approx(50.0)
    assert soundfx.time_at(fx, L, soundfx.frac_at(fx, L, 55.0)) == pytest.approx(55.0)
    assert soundfx.frac_at(fx, L, 100.0) == 0.0          # past the last: the first again
    back = {**fx, "reverse": True}
    assert soundfx.time_at(back, L, soundfx.frac_at(back, L, 55.0)) == pytest.approx(55.0)


def test_swap_goes_on_from_where_its_told():
    e = engine_with("main")
    e.play("a", song(4.0), 1.0)
    e.seek("a", 0.25)
    assert e.swap("a", song(4.0, 0.5), at=lambda frac: frac + 0.5)
    assert e._current("a").progress() == pytest.approx(0.75, abs=0.01)


# ------------------------------------------------------------------ the gestures

def _wave(playing: float | None = 30.0) -> Waveform:
    w = Waveform(np.full(200, 0.5, np.float32), L)
    w.set_big(True)
    w.resize(800, 160)
    w.set_play(playing)
    return w


def _scrubs(w):
    got = []
    w.scrubbed.connect(lambda t, done: got.append((round(t, 1), done)))
    return got


def test_a_click_on_the_ruler_moves_it_there_not_a_handle(qapp):
    w = _wave()
    got = _scrubs(w)
    QTest.mouseClick(w, LEFT, NO, QPoint(round(w._x(90.0)), RULER_H // 2))
    assert got and got[-1][1] and got[-1][0] == pytest.approx(90.0, abs=0.5)
    assert (w.start, w.end) == (0.0, L)              # the handles stayed


def test_dragging_the_ruler_scrubs(qapp):
    w = _wave()
    got = _scrubs(w)
    y = RULER_H // 2
    QTest.mousePress(w, LEFT, NO, QPoint(round(w._x(20.0)), y))
    QTest.mouseMove(w, QPoint(round(w._x(40.0)), y))
    w.set_play(5.0)                                  # (the timer: not while it's held)
    assert w.play == pytest.approx(40.0, abs=0.5)
    QTest.mouseRelease(w, LEFT, NO, QPoint(round(w._x(60.0)), y))
    assert [d for _t, d in got] == [False, False, True]
    assert got[-1][0] == pytest.approx(60.0, abs=0.5)


def test_the_playhead_drags_but_a_handle_under_it_wins(qapp):
    w = _wave(30.0)
    got = _scrubs(w)
    y = 100
    QTest.mousePress(w, LEFT, NO, QPoint(round(w._x(30.0)), y))
    QTest.mouseMove(w, QPoint(round(w._x(70.0)), y))
    QTest.mouseRelease(w, LEFT, NO, QPoint(round(w._x(70.0)), y))
    assert got[-1] == (pytest.approx(70.0, abs=0.5), True) and (w.start, w.end) == (0.0, L)
    w.set_play(0.0)                                  # on the start handle: the handle
    got.clear()
    QTest.mousePress(w, LEFT, NO, QPoint(round(w._x(0.0)), y))
    QTest.mouseMove(w, QPoint(round(w._x(20.0)), y))
    QTest.mouseRelease(w, LEFT, NO, QPoint(round(w._x(20.0)), y))
    assert not got and w.start == pytest.approx(20.0, abs=0.5)


def test_nothing_playing_clicks_still_trim_and_splice(qapp):
    w = _wave(None)
    got = _scrubs(w)
    QTest.mouseClick(w, LEFT, NO, QPoint(round(w._x(30.0)), 100))
    assert w.start == pytest.approx(30.0, abs=0.5) and not got
    w.set_cutting(True)
    w.set_play(50.0)
    for t in (60.0, 80.0):                           # away from the playhead: splices
        QTest.mouseClick(w, LEFT, NO, QPoint(round(w._x(t)), 100))
    assert len(w.splices) == 1 and not got


def test_right_drag_still_pans_from_the_ruler(qapp):
    w = _wave()
    got = _scrubs(w)
    w.zoom(4.0)
    before = w.view[0]
    right = Qt.MouseButton.RightButton
    QTest.mousePress(w, right, NO, QPoint(400, RULER_H // 2))
    QTest.mouseMove(w, QPoint(200, RULER_H // 2))
    QTest.mouseRelease(w, right, NO, QPoint(200, RULER_H // 2))
    assert w.view[0] > before and not got


# ------------------------------------------------------------------ the playing sound

@pytest.fixture
def playing(window, monkeypatch, qapp):  # noqa: F811
    """s0 (120 s) playing 25% of the way through, in Advanced; seeks and swaps recorded."""
    for _ in range(50):
        qapp.processEvents()
        if "s0" in window.audio:
            break
        time.sleep(0.02)
    window.audio["s0"] = song(1.0)
    monkeypatch.setattr(dialogs, "original_length", lambda m: L)
    monkeypatch.setattr(window.engine, "state", lambda sid: (0.25, False) if sid == "s0" else None)
    seeks, swaps = [], []
    monkeypatch.setattr(window.engine, "seek", lambda sid, frac: seeks.append((sid, frac)) or True)
    monkeypatch.setattr(window.engine, "swap",
                        lambda sid, data, at=None: swaps.append((sid, at)) or True)
    monkeypatch.setattr(editcontrol, "render_fx", lambda m, cancel, progress: song(0.5, 0.5))
    monkeypatch.setattr(worker, "run", lambda fn, signal=None, name="", error=None, owner=None:
                        worker.call(fn, signal, name, error=error, owner=owner))
    window.meta("s0").fx = {}
    d = window.editctl.edit("s0", "trim")
    return window, d, seeks, swaps


def test_the_ruler_seeks_the_playing_pad(playing):
    win, d, seeks, _swaps = playing
    d.effects.trim.seek_to.emit(90.0, True)
    assert seeks and seeks[-1][0] == "s0" and seeks[-1][1] == pytest.approx(0.75)
    d.effects.trim.set_values(60.0, 0.0, emit=True)   # trimmed and swapped in, then a seek
    win.editctl._live_now()                        # outside what plays: its start
    d.effects.trim.seek_to.emit(30.0, True)
    assert seeks[-1][1] == pytest.approx(0.0)
    d.close()


def test_a_trim_past_the_spot_swaps_in_from_its_start(playing):
    """The owner's case: playing at 0:30, the trim moved to start at 1:00."""
    win, d, _seeks, swaps = playing
    d.effects.trim.set_values(60.0, 0.0, emit=True)
    win.editctl._live_now()
    assert swaps and swaps[-1][0] == "s0" and swaps[-1][1] is not None
    assert swaps[-1][1](0.25) == pytest.approx(0.0)   # 0:30 -> the start of what's kept
    win.editctl._show_playing()                    # and the playhead says the same
    assert d.effects.trim.wave.play == pytest.approx(60.0 + 0.25 * 60.0)
    d.close()
    QApplication.processEvents()
