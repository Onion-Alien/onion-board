"""Edit sound's effects on a sound that's playing: it's made again in the background and
swapped in where it is (Engine.swap); Cancel puts the saved one back, Save keeps it
playing, and Reset effects goes plain at once."""
import time

import numpy as np
import pytest
from test_mainwindow import window  # noqa: F401

from soundboard.audio.engine import SR, SWAP_FADE_S, Engine
from soundboard.ui.kit import worker
from soundboard.ui.window import editcontrol


class FakeStream:
    def stop(self):
        pass

    def close(self):
        pass


def engine_with(*outs):
    e = Engine()
    for o in outs:
        setattr(e, f"{o}_stream", FakeStream())
        e.names[o] = f"fake {o}"
    return e


def song(seconds, value=0.25):
    return np.full((int(seconds * SR), 2), value, np.float32)


def test_swap_goes_on_from_the_same_point():
    e = engine_with("main")
    old = e.play("a", song(4.0), 0.7, fade_out=2.0)
    e.seek("a", 0.5)
    e.set_paused("a", True)
    assert e.swap("a", song(2.0, 0.5))
    new = e._current("a")
    assert new is not old and old.stopping
    assert old.fade_out == SWAP_FADE_S             # a quick crossfade, not its long fade
    assert new.progress() == pytest.approx(0.5, abs=0.01)
    assert new.paused and new.gain == 0.7 and new.fade_out == 2.0
    assert set(new.data) == {"main"}


def test_swap_needs_it_playing():
    e = engine_with("main")
    assert not e.swap("a", song(1.0))
    e.play("a:preview", song(1.0), 1.0)
    assert not e.swap("b", song(1.0))


@pytest.fixture
def live(window, monkeypatch, qapp):  # noqa: F811
    """s0 playing; renders and the worker run in place; swaps recorded."""
    for _ in range(50):   # the board's own loads first
        qapp.processEvents()
        if "s0" in window.audio:
            break
        time.sleep(0.02)
    saved = song(1.0)
    window.audio["s0"] = saved
    monkeypatch.setattr(window.engine, "state", lambda sid: (0.4, False) if sid == "s0" else None)
    swaps, stops = [], []
    monkeypatch.setattr(window.engine, "swap", lambda sid, data: swaps.append((sid, data)) or True)
    real_stop = window.engine.stop
    monkeypatch.setattr(window.engine, "stop", lambda sid: (stops.append(sid), real_stop(sid)))
    made = song(0.7, 0.5)
    monkeypatch.setattr(editcontrol, "render_fx", lambda m, cancel, progress: made)
    monkeypatch.setattr(worker, "run", lambda fn, signal=None, name="", error=None, owner=None:
                        worker.call(fn, signal, name, error=error, owner=owner))
    d = window.editctl.edit("s0", "effects")
    return window, d, saved, made, swaps, stops


def faster(d):
    d.effects.load({"speed": 1.5})
    d.effects.changed.emit()


def test_a_change_plays_at_once_and_cancel_puts_it_back(live, qapp):
    win, d, saved, made, swaps, _stops = live
    faster(d)
    win.editctl._live_now()
    qapp.processEvents()
    assert swaps == [("s0", made)] and win.audio["s0"] is made
    assert "playing sound has your changes" in d.fx_note.text()
    d.reject()
    qapp.processEvents()
    assert swaps[-1] == ("s0", saved) and win.audio["s0"] is saved
    assert win.meta("s0").fx == {}


def test_save_keeps_it_playing(live, qapp):
    win, d, _saved, made, swaps, stops = live
    faster(d)
    win.editctl._live_now()
    d.accept()
    qapp.processEvents()
    assert win.meta("s0").fx["speed"] == 1.5
    assert "s0" not in stops                       # not stopped, not made a third time
    assert win.audio["s0"] is made and swaps == [("s0", made)]


def test_reset_goes_plain_at_once(live, qapp):
    win, d, saved, made, swaps, _stops = live
    faster(d)
    win.editctl._live_now()
    d.btn_reset.click()                            # no wait: the saved audio is right here
    assert swaps[-1] == ("s0", saved) and d.effects.fx() == {}


def test_nothing_happens_when_it_isnt_playing(live, qapp, monkeypatch):
    win, d, saved, _made, swaps, _stops = live
    monkeypatch.setattr(win.engine, "state", lambda sid: None)
    faster(d)
    win.editctl._live_now()
    assert swaps == [] and win.audio["s0"] is saved


def test_reset_effects_stands_out_only_with_effects_on(win_only):
    d = win_only.editctl.edit("s0", "effects")
    assert not d.btn_reset.property("nudge")
    faster(d)
    assert d.btn_reset.property("nudge") and d._reset_glow.is_on()
    d.btn_reset.click()
    assert not d.btn_reset.property("nudge") and not d._reset_glow.is_on()
    start, _end = d.effects.trim.values()
    d.effects.load({"start": start + 0.01})   # a trim alone: Reset keeps it
    d.effects.changed.emit()
    assert not d.btn_reset.property("nudge")


@pytest.fixture
def win_only(window):  # noqa: F811
    return window
