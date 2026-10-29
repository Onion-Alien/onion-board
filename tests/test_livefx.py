"""Live effects on the sounds bus (soundboard.audio.livefx)."""
import numpy as np

from soundboard.audio import livefx

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
