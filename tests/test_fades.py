"""Per-sound fade in / fade out in the engine (Voice.fade_in / fade_out)."""
import numpy as np

from soundboard.engine import SR, START_FADE_S
from tests.test_engine import engine_with


def dc(seconds=1.0, level=0.5):
    """A constant signal: the output is the fade envelope times `level`. (It starts
    away from zero, so without a fade-in of its own it rises over START_FADE_S.)"""
    return np.full((int(seconds * SR), 2), level, np.float32)


RISE = int(START_FADE_S * SR) + 1


def run(e, blocks, n=480):
    out = np.zeros((n, 2), np.float32)
    got = []
    for _ in range(blocks):
        e._main(out, n)
        got.append(out[:, 0].copy())
    return np.concatenate(got)


def test_fade_in_rises_from_silence_over_its_length():
    e = engine_with("main")
    e.play("a", dc(), 1.0, fade_in=0.1)          # 4800 frames = 10 blocks
    y = run(e, 12)
    assert y[0] < 0.01
    assert 0.2 < y[2400] < 0.3                   # half way up
    assert np.allclose(y[4800:], 0.5)
    assert np.all(np.diff(y[:4800]) >= -1e-6)    # never dips


def test_no_fades_is_unchanged():
    e = engine_with("main")
    e.play("a", dc(), 1.0)
    y = run(e, 2)
    assert np.allclose(y[RISE:], 0.5) and y[0] < 0.01   # only the 2 ms anti-pop rise


def test_stop_fades_out_over_the_sounds_fade_out():
    e = engine_with("main")
    v = e.play("a", dc(), 1.0, fade_out=0.05)    # 2400 frames = 5 blocks
    run(e, 1)
    e.stop("a")
    assert e.any_playing()                       # still heard while it fades
    y = run(e, 6)
    assert 0.2 < y[1200] < 0.3 and y[0] > 0.45
    assert np.all(y[2400:] == 0)
    assert v.finished and not e.any_playing()


def test_one_shot_fades_before_its_natural_end():
    e = engine_with("main")
    e.play("a", dc(0.2), 1.0, fade_out=0.05)     # 9600 frames, last 2400 fade
    y = run(e, 22)
    assert np.allclose(y[RISE:7000], 0.5)
    assert 0.2 < y[9600 - 1200] < 0.3
    assert y[9599] < 0.01 and np.all(y[9600:] == 0)


def test_loop_does_not_fade_at_each_wrap():
    e = engine_with("main")
    e.play("a", dc(0.05), 1.0, loop=True, fade_out=0.02)
    assert np.allclose(run(e, 20)[RISE:], 0.5)


def test_stop_all_skips_the_fade_out():
    e = engine_with("main")
    v = e.play("a", dc(), 1.0, fade_out=2.0)
    run(e, 1)
    e.stop_all()
    y = run(e, 2)
    assert np.all(y[480:] == 0) and v.finished


def test_pause_during_fade_in_then_resume_finishes_the_fade():
    e = engine_with("main")
    e.play("a", dc(), 1.0, fade_in=0.1)
    run(e, 2)
    e.set_paused("a", True)
    assert np.all(run(e, 3)[480:] == 0)
    e.set_paused("a", False)
    y = run(e, 15)
    assert np.allclose(y[-480:], 0.5)
