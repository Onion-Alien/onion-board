"""Live effects on the sounds bus (soundboard.audio.livefx)."""
import numpy as np
import pytest

from soundboard.audio import livefx
from soundboard.voicefx.builtin import Reverb

RATE = 48000
BLOCK = 512


def _tone(hz: float, seconds: float = 0.5) -> np.ndarray:
    t = np.arange(int(RATE * seconds)) / RATE
    x = (0.3 * np.sin(2 * np.pi * hz * t)).astype(np.float32)
    return np.stack([x, x], axis=1)


def _run(fx: dict, x: np.ndarray) -> np.ndarray:
    f = livefx.LiveFx(RATE)
    return np.concatenate([f.process(x[i:i + BLOCK], fx) for i in range(0, len(x), BLOCK)])


def _rms(x):
    return float(np.sqrt(np.mean(x[len(x) // 2:] ** 2)))   # the settled half


def test_clean_keeps_only_knobs_off_zero_and_clamps():
    assert livefx.clean({"bass": 0, "reverb": 2, "nope": 1, "echo": "x"}) == {"reverb": 1.0}
    assert livefx.clean(None) == {}
    for amounts in livefx.PRESETS.values():   # their speed and pitch aren't knobs
        assert livefx.clean(amounts) == {k: v for k, v in amounts.items()
                                         if k not in livefx.TUNING}


def test_a_preset_with_a_speed_sets_all_three_and_a_stream_gets_the_pitch():
    nightcore = livefx.PRESETS["Nightcore"]
    assert livefx.tuning(nightcore) == (1.3, 0.0, False)
    assert livefx.tuning(nightcore, has_speed=False) == (1.0, 5, True)   # +4.5 st
    assert livefx.tuning(livefx.PRESETS["Chipmunk"]) == (1.0, 7, True)
    assert livefx.tuning(livefx.PRESETS["Bass boosted"]) is None


def test_every_knob_and_preset_keeps_shape_and_stays_finite():
    x = _tone(220)
    cases = [{q.key: q.hi} for q in livefx.PARAMS] + list(livefx.PRESETS.values())
    for fx in cases:
        y = _run(fx, x)
        assert y.shape == x.shape and y.dtype == np.float32, fx
        assert np.isfinite(y).all(), fx


def test_bass_boosts_lows_and_muffle_cuts_highs():
    low, high = _tone(60), _tone(8000)
    assert _rms(_run({"bass": 12}, low)) > 3 * _rms(low)
    assert _rms(_run({"bass": 12}, high)) < 1.1 * _rms(high)
    assert _rms(_run({"muffle": 1}, high)) < 0.05 * _rms(high)


def test_reverb_and_echo_ring_on_after_the_sound_stops():
    x = np.concatenate([_tone(440, 0.1), np.zeros((RATE // 2, 2), np.float32)])
    for fx in ({"reverb": 0.8}, {"echo": 0.8}):
        y = _run(fx, x)
        assert np.abs(y[int(RATE * 0.15):]).max() > 0.01, fx


def test_back_to_zero_goes_idle_and_passes_straight_through():
    f = livefx.LiveFx(RATE)
    x = _tone(440)
    for i in range(0, len(x), BLOCK):
        f.process(x[i:i + BLOCK], {"bass": 6, "echo": 0.5})
    for i in range(0, len(x), BLOCK):
        y = f.process(x[i:i + BLOCK], {})
    assert f.idle and np.array_equal(y, x[i:i + BLOCK])


def test_volume_scales_and_a_boost_never_clips():
    assert livefx.clean({"volume": 100}) == {}
    assert livefx.clean({"volume": 900}) == {"volume": 400.0}
    x = _tone(440)
    assert abs(_rms(_run({"volume": 50}, x)) - _rms(x) / 2) < 1e-3
    loud = _run({"volume": 400}, x)
    assert _rms(loud) > 2 * _rms(x) and np.abs(loud).max() <= 1.0
    f = livefx.LiveFx(RATE)
    f.process(x[:BLOCK], {"volume": 200})
    assert not f.idle
    back = f.process(x[BLOCK:2 * BLOCK], {})   # glides back to 100 %, then idles
    assert np.isfinite(back).all() and f.idle
    assert np.array_equal(f.process(x[:BLOCK], {}), x[:BLOCK])


# ---- resting on silence: an effect left on costs nothing while nothing plays

ALL_ON = {"bass": 6.0, "treble": -3.0, "muffle": 0.3, "reverb": 1.0, "echo": 1.0,
          "crunch": 0.7, "volume": 150.0}


def _song(seconds: float, seed: int = 0) -> np.ndarray:
    """Shaped like real sound: a chord with a beat and a little noise, two channels."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(RATE * seconds)) / RATE
    beat = 0.4 + 0.6 * (np.sin(2 * np.pi * 2 * t) > 0)
    left = sum(np.sin(2 * np.pi * hz * t) for hz in (110, 277, 880)) / 3
    right = sum(np.sin(2 * np.pi * hz * t) for hz in (165, 330, 1320)) / 3
    x = np.stack([left, right], axis=1) * beat[:, None]
    return (0.6 * x + 0.02 * rng.standard_normal(x.shape)).astype(np.float32)


def _play(x: np.ndarray, fx: dict, rest: bool, block: int = BLOCK, f=None):
    f = f or livefx.LiveFx(RATE)
    f.REST = rest
    y = np.concatenate([f.process(x[i:i + block], fx) for i in range(0, len(x), block)])
    return y, f


@pytest.mark.parametrize("fx, block, quiet", [
    ({"reverb": 1.0}, 480, 10), ({"reverb": 1.0}, 64, 10), ({"reverb": 0.1}, 480, 10),
    ({"echo": 1.0}, 480, 12), ({"crunch": 1.0}, 480, 2), ({"crunch": 1.0}, 64, 2),
    ({"bass": 18.0}, 480, 2), ({"muffle": 1.0}, 480, 2), ({"volume": 400.0}, 480, 2),
    (ALL_ON, 480, 20)])   # (the echo's repeats go through the reverb: the longest tail)
def test_resting_on_silence_changes_nothing_you_could_hear(fx, block, quiet):
    """Sound, a silence long enough to rest in, then sound again: the same as running
    every block, to within REST_FLOOR's order (a 16-bit step is 3e-5)."""
    x = np.concatenate([_song(0.5), np.zeros((RATE * quiet, 2), np.float32), _song(0.5, 1)])
    old, _ = _play(x, fx, rest=False, block=block)
    new, f = _play(x[:RATE * quiet], fx, rest=True, block=block)
    assert f.resting(fx)
    more, _ = _play(x[RATE * quiet:], fx, rest=True, block=block, f=f)
    new = np.concatenate([new, more])
    assert np.abs(old - new).max() < 1e-5
    assert np.array_equal(new[:RATE // 2], old[:RATE // 2])   # the sound and its first tail


def test_a_tail_rings_out_in_full_before_it_rests():
    fx = {"reverb": 1.0}
    x = np.concatenate([_song(0.5), np.zeros((RATE * 15, 2), np.float32)])
    y, f = _play(x, fx, rest=True)
    assert f.resting(fx)
    silent = np.flatnonzero(np.abs(y).max(axis=1))[-1] / RATE
    assert silent > 2.0                               # a big room still rang for seconds
    old, _ = _play(x, fx, rest=False)
    assert np.abs(old - y).max() < 1e-5


def test_a_rested_chain_does_no_work_and_needs_no_new_block(monkeypatch):
    calls = []
    monkeypatch.setattr(Reverb, "run", lambda self, x, rate, real=Reverb.run: (
        calls.append(1), real(self, x, rate))[1])
    fx = {"reverb": 0.5}
    f = livefx.LiveFx(RATE)
    zeros = np.zeros((BLOCK, 2), np.float32)
    while not f.resting(fx):
        f.process(zeros, fx)
    calls.clear()
    assert all(f.process(zeros, fx) is zeros for _ in range(100))   # no new array at all
    assert not calls
    assert np.abs(f.process(_song(0.1)[:BLOCK], fx)).max() > 0 and calls   # awake at once
    assert not f.resting(fx)


def _rested(fx: dict) -> livefx.LiveFx:
    f = livefx.LiveFx(RATE)
    f.process(_song(0.2)[:BLOCK], fx)
    zeros = np.zeros((BLOCK, 2), np.float32)
    for _ in range(3000):
        f.process(zeros, fx)
        if f.resting(fx):
            return f
    raise AssertionError("it never rested")


def test_a_knob_moved_while_resting_acts_as_it_would_awake():
    was, now = {"reverb": 0.5, "bass": 6.0}, {"reverb": 0.8, "bass": -6.0, "volume": 50.0}
    x = _song(0.5)
    a, b = _rested(was), _rested(was)
    a.REST = False
    zeros = np.zeros((BLOCK, 2), np.float32)
    assert a.process(zeros, now).shape == b.process(zeros, now).shape
    assert not b.resting(now)
    ya, _ = _play(x, now, rest=False, f=a)
    yb, _ = _play(x, now, rest=True, f=b)
    assert np.abs(ya - yb).max() < 1e-5

    # off: it fades out and goes, as it would awake
    f = _rested(was)
    for _ in range(10):
        f.process(zeros, {})
    assert f.idle


def test_a_flush_while_resting_still_starts_from_silence():
    fx = {"reverb": 0.5}
    f = _rested(fx)
    f.flush()
    assert not f.resting(fx)
    zeros = np.zeros((BLOCK, 2), np.float32)
    for _ in range(4):        # the fade, then a fresh effect
        f.process(zeros, fx)
    fresh = livefx.LiveFx(RATE)
    fresh.process(zeros, fx)
    x = _song(0.3)
    a, _ = _play(x, fx, rest=True, f=f)
    b, _ = _play(x, fx, rest=True, f=fresh)
    assert np.array_equal(a, b)
