import math

import numpy as np
import pytest

from soundboard import dsp


def _direct_sos(sos, x):
    """Textbook per-sample DF2T, float64: the reference the block engine must equal."""
    y = np.asarray(x, np.float64).copy()
    for b0, b1, b2, a0, a1, a2 in np.asarray(sos, np.float64):
        b0, b1, b2, a1, a2 = b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0
        z1 = z2 = 0.0
        out = np.empty_like(y)
        for n, v in enumerate(y):
            o = b0 * v + z1
            z1 = b1 * v - a1 * o + z2
            z2 = b2 * v - a2 * o
            out[n] = o
        y = out
    return y


def _gain_db(sos, hz, rate):
    return 20 * np.log10(np.abs(dsp.sos_response(sos, np.atleast_1d(hz), rate)))


@pytest.mark.parametrize("n", [0, 1, 7, 60, 64, 65, 480, 1000])
def test_sosfilt_equals_the_per_sample_recursion(n):
    rng = np.random.default_rng(n)
    sos = np.vstack([dsp.butter(4, 0.02), dsp.matched_biquad("peak", 3000, 6, 48000, 1.1)])
    x = rng.standard_normal(n)
    assert np.allclose(dsp.sosfilt(sos, x), _direct_sos(sos, x), atol=1e-10)


def test_blocks_of_any_size_join_without_a_seam():
    rng = np.random.default_rng(3)
    sos = dsp.butter(8, 0.01)
    x = rng.standard_normal((3000, 2))
    whole = dsp.sosfilt(sos, x, axis=0)
    zi = np.zeros((len(sos), 2, 2))
    parts, i = [], 0
    for size in (1, 5, 64, 479, 480, 481, 1490):
        y, zi = dsp.sosfilt(sos, x[i:i + size], axis=0, zi=zi)
        parts.append(y)
        i += size
    assert i == len(x)
    assert np.allclose(np.concatenate(parts), whole, atol=1e-10)


def test_zi_layout_and_dtypes_follow_scipy():
    sos = dsp.butter(2, 0.1).astype(np.float32)          # 1 section
    x = np.ones((50, 3), np.float32)
    y, zf = dsp.sosfilt(sos, x, axis=0, zi=np.zeros((1, 2, 3), np.float32))
    assert y.dtype == np.float32 and zf.dtype == np.float32 and zf.shape == (1, 2, 3)
    y, zf = dsp.sosfilt(sos, x.T, zi=np.zeros((1, 3, 2), np.float32))   # time last
    assert zf.shape == (1, 3, 2)
    assert dsp.sosfilt(sos.astype(np.float64), x, axis=0).dtype == np.float64
    with pytest.raises(ValueError):
        dsp.sosfilt(sos, x, axis=0, zi=np.zeros((1, 3, 2)))
    y, zf = dsp.lfilter([0.5], [1, -0.5], np.ones(10), zi=np.zeros(1))
    assert zf.shape == (1,)
    y, zf = dsp.lfilter([1, 2, 1], [1, -0.5, 0.1], np.ones((10, 4)), axis=0,
                        zi=np.zeros((2, 4)))
    assert zf.shape == (2, 4)


def test_lfilter_one_pole_matches_its_closed_form():
    a = 0.9
    y = dsp.lfilter([1 - a], [1, -a], np.ones(200))
    assert np.allclose(y, 1 - a ** np.arange(1, 201))


def test_float32_is_more_accurate_than_it_needs_to_be():
    """The state stays float64 inside: a 60 Hz shelf in float32 over a second of
    audio, block by block, stays within 1e-5 of the float64 result."""
    rng = np.random.default_rng(1)
    x = (rng.standard_normal((48000, 2)) * 0.3).astype(np.float32)
    sos = np.array([dsp.matched_biquad("lowshelf", 60, 6, 48000),
                    dsp.matched_biquad("peak", 150, 4, 48000, 1.1)], np.float32)
    ref = dsp.sosfilt(sos.astype(np.float64), x.astype(np.float64), axis=0)
    zi = np.zeros((2, 2, 2), np.float32)
    out = []
    for i in range(0, len(x), 480):
        y, zi = dsp.sosfilt(sos, x[i:i + 480], axis=0, zi=zi)
        out.append(y)
    assert np.max(np.abs(np.concatenate(out) - ref)) < 1e-5


@pytest.mark.parametrize("btype,wn", [("low", 1000), ("high", 100), ("band", (300, 3000))])
@pytest.mark.parametrize("order", [1, 2, 3, 4, 8, 13])
def test_butter_is_butterworth(btype, wn, order):
    rate = 48000
    sos = dsp.butter(order, wn, btype, fs=rate)
    for row in sos:
        assert np.all(np.abs(np.roots(row[3:])) < 1)
    edges = np.atleast_1d(wn)
    assert np.allclose(_gain_db(sos, edges, rate), -3.0103, atol=0.01)   # -3 dB edges
    if btype == "low":
        assert abs(_gain_db(sos, 0.0, rate)[0]) < 1e-6
        assert _gain_db(sos, 8000, rate)[0] < -15 * order
    elif btype == "high":
        assert abs(_gain_db(sos, 24000, rate)[0]) < 1e-6
        assert _gain_db(sos, 25, rate)[0] < -11 * order
    else:
        assert abs(_gain_db(sos, math.sqrt(300 * 3000), rate)[0]) < 0.5


def test_butter_matches_scipy_when_it_is_installed():
    signal = pytest.importorskip("scipy.signal")
    f = np.linspace(1, 23999, 300)
    for args in [(4, 0.05, "low"), (13, 0.004, "high"), (2, (0.01, 0.03), "band"),
                 (3, (0.2, 0.6), "band"), (8, 0.5, "low")]:
        ours = dsp.sos_response(dsp.butter(*args), f, 48000)
        theirs = dsp.sos_response(signal.butter(*args, output="sos"), f, 48000)
        assert np.allclose(np.abs(ours), np.abs(theirs), atol=1e-9)


def test_sosfilt_matches_scipy_when_it_is_installed():
    signal = pytest.importorskip("scipy.signal")
    rng = np.random.default_rng(0)
    sos = signal.butter(6, (0.01, 0.2), "band", output="sos")
    x = rng.standard_normal((2, 5000))
    zi = rng.standard_normal((len(sos), 2, 2))
    y1, z1 = signal.sosfilt(sos, x, zi=zi)
    y2, z2 = dsp.sosfilt(sos, x, zi=zi)
    assert np.allclose(y1, y2, atol=1e-10) and np.allclose(z1, z2, atol=1e-10)


@pytest.mark.parametrize("kind", ["peak", "lowshelf", "highshelf"])
def test_matched_bands_are_stable_and_minimum_phase_everywhere(kind):
    for rate in (22050, 44100, 48000, 96000):
        for f0 in (20, 60, 160, 1000, 2500, 6000, 12000, 20000):
            for g in (-24, -12, -0.5, 0, 0.5, 12, 24):
                for q in (0.5, 0.707, 1.1, 3):
                    row = dsp.matched_biquad(kind, f0, g, rate, q)
                    assert np.all(np.isfinite(row))
                    assert np.all(np.abs(np.roots(row[3:])) < 1), (f0, g, rate, q)
                    assert np.all(np.abs(np.roots(row[:3])) <= 1 + 1e-9), (f0, g, rate, q)


def test_a_matched_band_at_zero_gain_is_a_wire():
    row = dsp.matched_biquad("peak", 1000, 0, 48000, 1.1)
    f = np.geomspace(20, 23000, 50)
    assert np.max(np.abs(_gain_db(row[None], f, 48000))) < 1e-6


def test_running_min_matches_brute_force():
    rng = np.random.default_rng(5)
    x = rng.standard_normal(1000)
    for w in (1, 2, 3, 10, 64, 999, 1000):
        brute = np.lib.stride_tricks.sliding_window_view(x, w).min(axis=1)
        assert np.array_equal(dsp.running_min(x, w), brute)
    assert np.array_equal(dsp.running_min(np.array([3, 1, 2], np.int16), 2), [1, 1])


def test_smooth_sos_starts_directly_then_crossfades_changes():
    x = np.ones((2000, 1), np.float32)
    f = dsp.SmoothSos(fade=500)
    half = np.array([[0.5, 0, 0, 1, 0, 0]], np.float32)       # a plain gain of 0.5
    y = f.run(x, half)
    assert np.allclose(y, 0.5)                                 # first block: no fade
    y = f.run(x, None)                                         # off: fade to dry
    assert y[0, 0] < 0.51 and np.allclose(y[500:], 1.0)
    assert np.all(np.diff(y[:500, 0]) >= 0)
    assert f.run(x, None) is x                                 # then straight through


def test_a_filter_bank_equals_one_sosfilt_per_filter_block_by_block():
    rng = np.random.default_rng(9)
    edges = np.geomspace(120, 7500, 9)
    bank = np.stack([dsp.butter(2, (edges[i], edges[i + 1]), "band", fs=48000)
                     for i in range(8)])
    x = rng.standard_normal((2, 2000))
    want = np.stack([dsp.sosfilt(sos, x) for sos in bank])
    state, got = None, []
    for i in range(0, 2000, 480):
        y, state = dsp.sosfilt_bank(bank, x[:, i:i + 480], state)
        got.append(y)
    assert np.allclose(np.concatenate(got, axis=-1), want, atol=1e-10)
