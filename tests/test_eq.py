import numpy as np
from scipy.signal import sosfilt

from soundboard import eq


def test_flat_designs_to_nothing():
    assert eq.design([0] * 7, 48000) is None
    assert eq.design([0.04, 0, 0, 0, 0, 0, 0], 48000) is None
    assert np.all(eq.response_db([0] * 7, np.array([100.0, 1000.0])) == 0)


def test_sos_is_float32_and_one_section_per_band():
    sos = eq.design(eq.PRESETS["Music — bass boost"], 48000)
    assert sos.dtype == np.float32
    assert sos.shape == (len(eq.BANDS), 6)


def test_bass_boost_boosts_bass_not_treble():
    g = eq.PRESETS["Music — bass boost"]
    db = eq.response_db(g, np.array([60.0, 3000.0]))
    assert db[0] > 4          # +7 dB shelf, some overlap from the 150 band
    assert abs(db[1]) < 1.5   # mids roughly untouched


def test_every_preset_is_stable_at_every_common_rate():
    rng = np.random.default_rng(0)
    noise = (rng.standard_normal((48000, 2)) * 0.5).astype(np.float32)
    for name, gains in eq.PRESETS.items():
        for rate in (44100, 48000, 96000):
            f = eq.EQ(rate)
            y = f.process(noise, gains)
            assert y.dtype == np.float32, name
            assert np.all(np.isfinite(y)), name
            assert np.max(np.abs(y)) < 40, f"{name} @ {rate} blew up"


def test_float32_matches_float64_reference():
    """Design/state in float32 must not change the sound measurably."""
    rng = np.random.default_rng(1)
    x = (rng.standard_normal((4800, 2)) * 0.3).astype(np.float32)
    gains = eq.PRESETS["Voice — deep radio host"]      # includes the 60 Hz shelf
    y32 = eq.EQ(48000).process(x, gains)
    sos64 = np.array([eq._biquad(k, f, g, 48000, q=1.1 if k == "peak" else 1.0)
                      for (f, k), g in zip(eq.BANDS, gains)])
    y64 = sosfilt(sos64, x.astype(np.float64), axis=0)
    assert np.max(np.abs(y32 - y64)) < 1e-3


def test_state_carries_between_blocks_without_a_seam():
    gains = eq.PRESETS["Music — club / loud"]
    t = np.arange(9600) / 48000
    x = np.stack([np.sin(2 * np.pi * 200 * t)] * 2, 1).astype(np.float32)
    whole = eq.EQ(48000).process(x, gains)
    f = eq.EQ(48000)
    parts = np.concatenate([f.process(x[:4800], gains), f.process(x[4800:], gains)])
    assert np.allclose(whole, parts, atol=1e-5)


def test_switching_off_then_on_restarts_state_cleanly():
    f = eq.EQ(48000)
    x = np.ones((100, 2), np.float32)
    f.process(x, eq.PRESETS["Music — bass boost"])
    assert f.process(x, None) is x           # off: passthrough
    y = f.process(x, eq.PRESETS["Music — bass boost"])
    assert np.all(np.isfinite(y))
