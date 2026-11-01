"""Edit sound's changes on a playing sound, heard at once: what can run live (speed,
pitch, Live controls' knobs, boost) is a live stage on the playing sound
(Engine.set_sound_live) instead of a new copy made first; Save still bakes it in."""
import numpy as np
import pytest
from test_live_effects import engine_with, live, song  # noqa: F401
from test_mainwindow import window  # noqa: F401

from soundboard.audio import livefx, soundfx
from soundboard.audio.engine import SR
from soundboard.ui.window import editcontrol


def music(seconds=1.5):
    """A few notes with a click on each beat: something echo, reverb, the shelves and
    the distortion all change."""
    t = np.arange(int(seconds * SR)) / SR
    x = sum(np.sin(2 * np.pi * f * t) for f in (110, 440, 1320, 5000)) * 0.12
    x[SR // 8::SR // 4] += 0.4   # (not on its first sample: that would get a fade-in)
    return np.stack([x, x * 0.8], 1).astype(np.float32)   # (silent at 0: no fade-in)


def played(e, sid, blocks=600):
    return np.concatenate([e._render("mon", 480) for _ in range(blocks)])


@pytest.mark.parametrize("fx", [
    {"live": [{"bass": 9.0, "treble": -4.0, "echo": 0.6}]},
    {"live": [{"reverb": 0.7, "crunch": 0.4}, {"muffle": 0.5, "volume": 160.0}],
     "gain_db": 6.0},
])
def test_the_live_stage_sounds_like_the_baked_sound(fx):
    """The same LiveFx code, run on the playing sound, gives what Save bakes: within
    -54 dB of it, its echo / reverb tail included (the bake trims that tail)."""
    x = music()
    baked = soundfx.render(x, fx)
    e = engine_with("mon")
    e.set_sound_live("a", soundfx.live_split(fx)[1])
    v = e.play("a", x, 1.0)
    y = played(e, "a")
    assert v.finished                          # the tail rang out, then it ended
    loud = np.flatnonzero(np.abs(y).max(1) > 1e-3)
    assert abs(loud[-1] - len(baked)) < 0.15 * SR   # about as long as the baked one
    n = len(baked)
    assert np.abs(y[:n] - baked).max() < 2e-3


def test_a_stage_reaches_the_playing_sound_and_fades_off():
    e = engine_with("mon")
    v = e.play("a", song(2.0), 1.0)
    p = e.play("a:preview", song(2.0), 1.0, preview=True)
    e._render("mon", 480)
    stage = (1.0, 0.0, ({"bass": 6.0},), 1.0)
    e.set_sound_live("a", stage)
    assert v.live == stage and p.live is None    # (a preview is left alone)
    e._render("mon", 480)
    e.set_sound_live("a", None)
    assert v.live == livefx.NO_STAGE and "a" not in e.sound_live
    v2 = e.play("a", song(2.0), 1.0, mode="overlap")
    assert v2.live is None                       # the next press: plain again


def test_set_later_leaves_the_playing_copy_its_stage():
    """Save: the copy playing keeps its stage until the baked one swaps in under it."""
    e = engine_with("mon")
    stage = (1.25, 0.0, (), 1.0)
    e.set_sound_live("a", stage)
    v = e.play("a", song(2.0), 1.0)
    e.set_sound_live("a", None, now=False)
    assert v.live == stage
    assert e.swap("a", song(2.0))
    assert e._current("a").live is None


def test_speed_reads_the_sound_faster():
    e = engine_with("mon")
    e.set_sound_live("a", (2.0, 0.0, (), 1.0))
    v = e.play("a", song(1.0), 1.0)
    for _ in range(25):                          # 0.25 s at 2x: half of it
        e._render("mon", 480)
    assert v.progress() == pytest.approx(0.5, abs=0.02)


def test_live_split_and_delta():
    base, stage = soundfx.live_split({"speed": 1.5, "pitch": 2.0, "gain_db": 6.0,
                                      "reverse": True, "live": [{"bass": 4.0}]})
    assert soundfx.key(base) == soundfx.key({"reverse": True})
    speed, semis, stages, gain = stage
    assert speed == 1.5 and stages == ({"bass": 4.0},) and gain == pytest.approx(2.0, 0.01)
    assert semis == pytest.approx(2.0 - 12 * np.log2(1.5), abs=1e-3)   # keeps its pitch
    assert soundfx.live_split({"speed": 1.5, "tape": True})[1][1] == 0.0   # record-style
    assert soundfx.live_split({"reverse": True})[1] is None
    # a Nightcore pad a bit faster: the saved sound read faster, no new copy needed
    d = soundfx.live_delta({"speed": 1.25, "tape": True}, {"speed": 1.5, "tape": True})
    assert d[0] == pytest.approx(1.2) and d[1] == 0.0
    assert soundfx.live_delta({"speed": 1.25}, {"speed": 1.25, "start": 0.5}) is None


@pytest.fixture
def counted(live, monkeypatch):  # noqa: F811
    """The live fixture, counting the copies made while it plays."""
    win, d, saved, made, swaps, stops = live
    renders = []
    monkeypatch.setattr(editcontrol, "render_fx",
                        lambda m, cancel, progress: renders.append(m.fx) or made)
    return win, d, saved, made, swaps, renders


def edit(d, fx):
    d.effects.load(fx)
    d.effects.changed.emit()


@pytest.mark.parametrize("fx", [{"speed": 1.5}, {"pitch": 3.0}, {"gain_db": 6.0},
                                {"live": [{"bass": 6.0, "echo": 0.4}]}])
def test_a_live_change_is_heard_at_once(counted, qapp, fx):
    """No copy made, no wait, no bar: the playing sound gets a live stage at once."""
    win, d, saved, _made, swaps, renders = counted
    edit(d, fx)
    qapp.processEvents()
    assert win.engine.sound_live["s0"] == soundfx.live_split(fx)[1]
    assert not renders and not swaps and win.audio["s0"] is saved
    assert not win.editctl._live_due and d.live_bar.isHidden()
    assert "playing sound has your changes" in d.fx_note.text()
    d.reject()                                   # Cancel: plain again, nothing saved
    qapp.processEvents()
    assert "s0" not in win.engine.sound_live and win.meta("s0").fx == {}


def test_reset_after_a_live_change_is_plain_at_once(counted, qapp):
    win, d, _saved, _made, swaps, renders = counted
    edit(d, {"speed": 1.5, "live": [{"bass": 6.0}]})
    d.btn_reset.click()
    assert "s0" not in win.engine.sound_live and not renders and not swaps


def test_save_bakes_a_live_change_in(counted, qapp):
    win, d, _saved, made, swaps, renders = counted
    edit(d, {"speed": 1.5})
    d.accept()
    qapp.processEvents()
    assert win.meta("s0").fx["speed"] == 1.5
    assert renders == [win.meta("s0").fx]        # baked once, on Save
    assert swaps == [("s0", made)] and "s0" not in win.engine.sound_live


def test_a_trim_is_still_made_first_with_the_knobs_on_top(counted, qapp):
    """What can't run live (a trim) is made in the background; the speed on top is
    heard at once meanwhile and stays on the new copy."""
    win, d, _saved, made, swaps, renders = counted
    start, _end = d.effects.trim.values()
    edit(d, {"speed": 1.5, "start": start + 0.1})
    assert win.engine.sound_live["s0"][0] == 1.5    # the speed already
    assert "s0" in win.editctl._live_due and not renders
    win.editctl._live_now()
    qapp.processEvents()
    assert renders and renders[0]["speed"] == 1.0   # the copy has no speed baked in
    assert swaps == [("s0", made)] and win.engine.sound_live["s0"][0] == 1.5


def test_volume_is_heard_at_once_and_cancel_puts_it_back(counted, qapp, monkeypatch):
    win, d, *_rest = counted
    gains = []
    monkeypatch.setattr(win.engine, "set_gain", lambda sid, g: gains.append((sid, g)))
    d.vol.setValue(40)
    assert gains[-1] == ("s0", pytest.approx(win.gain_for(win.meta("s0"), volume=0.4)))
    d.reject()
    qapp.processEvents()
    assert gains[-1] == ("s0", pytest.approx(win.gain_for(win.meta("s0"))))
