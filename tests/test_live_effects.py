"""Edit sound's effects on a sound that's playing: what can't run live is made again in
the background and swapped in where it is (Engine.swap); Cancel puts the saved one back,
Save keeps it playing, and Reset effects goes plain at once. (What can run live:
test_edit_live_preview.)"""
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


def backwards(d):
    d.effects.load({"reverse": True})   # (made again: it can't run live)
    d.effects.changed.emit()


def test_a_change_plays_at_once_and_cancel_puts_it_back(live, qapp):
    win, d, saved, made, swaps, _stops = live
    backwards(d)
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
    backwards(d)
    win.editctl._live_now()
    d.accept()
    qapp.processEvents()
    assert win.meta("s0").fx["reverse"]
    assert "s0" not in stops                       # not stopped, not made a third time
    assert win.audio["s0"] is made and swaps == [("s0", made)]


def test_reset_goes_plain_at_once(live, qapp):
    win, d, saved, made, swaps, _stops = live
    backwards(d)
    win.editctl._live_now()
    d.btn_reset.click()                            # no wait: the saved audio is right here
    assert swaps[-1] == ("s0", saved) and d.effects.fx() == {}


def test_reset_of_a_saved_effect_goes_plain(live, qapp):
    """The pad was saved with effects: Reset makes it plain ('' is the plain sound's
    key, not "nothing to make"), instead of waiting at 0% for ever."""
    win, d, _saved, made, swaps, _stops = live
    d.reject()
    win.meta("s0").fx = {"pitch": -8.0}
    d = win.editctl.edit("s0", "effects")
    d.btn_reset.click()
    qapp.processEvents()
    assert swaps == [("s0", made)] and win.audio["s0"] is made
    assert "playing sound has your changes" in d.fx_note.text()


def test_nothing_happens_when_it_isnt_playing(live, qapp, monkeypatch):
    win, d, saved, _made, swaps, _stops = live
    monkeypatch.setattr(win.engine, "state", lambda sid: None)
    backwards(d)
    win.editctl._live_now()
    assert swaps == [] and win.audio["s0"] is saved


def test_reset_effects_stands_out_only_with_effects_on(win_only):
    d = win_only.editctl.edit("s0", "effects")
    assert not d.btn_reset.property("nudge")
    backwards(d)
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


def test_trim_shows_where_it_plays(live, qapp):
    """The trim's playhead follows the playing sound, inside its trim (and from the
    end when it plays backwards); gone once nothing plays."""
    win, d, _saved, _made, _swaps, _stops = live
    trim = d.effects.trim
    win.editctl._show_playing()
    assert trim.wave.play == pytest.approx(0.4 * trim.length)   # state(): 40% in
    n = trim.length / 4   # (a short test sound: a trim off the start only)
    trim.show_playing(0.5, {"start": n})
    assert trim.wave.play == pytest.approx(2.5 * n)
    trim.show_playing(0.25, {"start": n, "reverse": True})
    assert trim.wave.play == pytest.approx(3.25 * n)
    trim.show_playing(None)
    assert trim.wave.play is None


@pytest.fixture
def pad_live(live, monkeypatch):
    """s0 playing with its own effects (Edit sound: Bass +3, Reverb), its window closed;
    s1 a plain song."""
    win, d, *_rest = live
    d.reject()
    win.meta("s0").fx = {"pitch": -8.0, "live": [{"bass": 3.0}],
                         "effects": {"reverb": {"on": True, "mix": 0.3}}}
    win.meta("s1").fx = {}
    playing = {"s0": (0.4, False)}
    monkeypatch.setattr(win.engine, "playing", lambda: playing)
    monkeypatch.setattr(win.engine, "state", lambda sid: playing.get(sid))
    win.current = None
    return (*live, playing)


def test_live_controls_show_the_song_plus_their_own_layer(pad_live, qapp):
    """A song with Bass +3 shows +3; dragged to +5, the layer is +2; the next song,
    plain, shows +2 (the first song's own +3 went with it)."""
    win, _d, _saved, _made, swaps, _stops, playing = pad_live
    sp, e = win.speed_btn, win.engine
    sp._open()
    assert sp.values() == (1.0, -8.0, True)
    assert sp.fx_values() == {"bass": 3.0, "reverb": 0.3}
    assert sp._sub.text() == win.meta("s0").name
    sp.fx["bass"].set_value(5.0)
    sp._fx_edited()
    sp.pitch.set_value(-6.0)
    sp._edited()
    assert e.sound_fx == {"bass": 2.0} and e.sound_pitch == 2.0   # the layer only
    assert win.meta("s0").fx["live"] == [{"bass": 3.0}] and not swaps   # the pad as it was
    playing.clear()
    playing["s1"] = (0.0, False)                 # the next song
    win.editctl._pad_follow()
    assert sp.fx_values() == {"bass": 2.0} and sp.values()[:2] == (1.0, 2.0)
    assert sp._sub.text() == sp._sub_all
    sp.pop.hide()                                # closed: the layer, as it is
    assert sp.fx_values() == {"bass": 2.0} and e.sound_fx == {"bass": 2.0}


def test_closing_shows_the_layer_alone(pad_live, qapp):
    win, *_rest = pad_live
    sp = win.speed_btn
    sp._open()
    assert sp.fx_values() == {"bass": 3.0, "reverb": 0.3}
    sp.pop.hide()
    assert sp.values()[:2] == (1.0, 0.0) and sp.fx_values() == {}
    assert sp._sub.text() == sp._sub_all


def test_live_merged_adds_db_and_keeps_the_strongest():
    from soundboard.audio import soundfx
    stages = [{"bass": 3.0, "reverb": 0.2}, {"bass": 4.0, "reverb": 0.5}]
    assert soundfx.live_merged(stages) == {"bass": 7.0, "reverb": 0.5}
    assert soundfx.live_merged([{"bass": 15.0}, {"bass": 15.0}]) == {"bass": 18.0}


def test_live_view_reads_the_sounds_own_effects():
    from soundboard.audio import soundfx
    assert soundfx.live_view({}) == soundfx.NO_LIVE_VIEW
    speed, pitch, knobs = soundfx.live_view(
        {"speed": 1.5, "pitch": 2.0, "effects": {"echo": {"on": True, "mix": 0.4},
                                                 "distortion": {"on": True, "drive": 18.0},
                                                 "reverb": {"on": False, "mix": 0.9}}})
    assert (speed, pitch) == (1.5, 2.0) and knobs == {"echo": 0.4, "crunch": 0.5}


def test_live_controls_show_an_advanced_edit_as_it_plays(live, qapp, monkeypatch):
    """Reverb turned on with Add effect in the Advanced view plays at once; Live controls
    show it while it plays unsaved, after Save, and the saved sound again after Cancel."""
    win, d, saved, made, swaps, _stops = live
    monkeypatch.setattr(win.engine, "playing", lambda: {"s0": (0.4, False)})
    win.current = None
    sp = win.speed_btn
    d.switch.advanced.click()
    d.effects.turn_on("reverb")                  # (Add effect's tile)
    win.editctl._live_now()
    qapp.processEvents()
    assert swaps[-1] == ("s0", made)             # it plays with it, not saved yet
    sp._open()
    assert sp.fx_values().get("reverb", 0) > 0   # the knobs show what plays
    d.accept()
    qapp.processEvents()
    assert win.meta("s0").fx["effects"]["reverb"]["on"]
    win.editctl._pad_follow(force=True)
    assert sp.fx_values().get("reverb", 0) > 0
    sp.pop.hide()


def test_live_controls_go_back_with_a_cancelled_edit(live, qapp, monkeypatch):
    win, d, saved, made, swaps, _stops = live
    monkeypatch.setattr(win.engine, "playing", lambda: {"s0": (0.4, False)})
    win.current = None
    sp = win.speed_btn
    d.effects.turn_on("reverb")
    win.editctl._live_now()
    sp._open()
    assert sp.fx_values().get("reverb", 0) > 0
    d.reject()                                   # not saved: back to what was saved
    qapp.processEvents()
    win.editctl._pad_follow(force=True)
    assert "reverb" not in sp.fx_values() and win.audio["s0"] is saved
    sp.pop.hide()
