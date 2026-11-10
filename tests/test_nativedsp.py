"""The C++ audio maths (native/dsp/obdsp.cpp) against the Python versions it stands in
for: the same output, block by block, whatever the knobs and block sizes. Runs where the
DLL is built (scripts/buildtools/build_dsp.py) and skips elsewhere."""
import threading
import time

import numpy as np
import pytest

from soundboard.audio import dsp, livefx, nativedsp
from soundboard.audio.sendfx import SmartMono
from soundboard.voicefx.builtin import Compressor, Distortion, Echo, Flanger, Reverb
from soundboard.voicefx.builtin.parts import _envelope, _harmonics, _Oversampled, _PitchTracker

needs_dll = pytest.mark.skipif(nativedsp.LIB is None, reason="obdsp isn't built here")
F32 = np.float32
TOLERANCE_DB = -100.0   # float rounding, far under anything anyone can hear


def signal(n, seed=1, stereo=False):
    rng = np.random.default_rng(seed)
    t = np.arange(n) / 48000
    m = 0.3 * np.sin(2 * np.pi * 220 * t) + 0.1 * rng.standard_normal(n)
    m[n // 3:n // 2] = 0.0   # silence in the middle: tails ring out
    if stereo:
        return np.stack([m, np.roll(m, 37) * 0.7], 1).astype(F32)
    return m.astype(F32)


def diff_db(a, b):
    worst = float(np.max(np.abs(np.asarray(a, np.float64) - np.asarray(b, np.float64)), initial=0))
    return 20 * np.log10(max(worst, 1e-30))


@pytest.fixture
def switch(monkeypatch):
    """A callable: True runs what follows in C++, False in Python."""
    real = (nativedsp.LIB, nativedsp.HOLD)

    def use(native: bool):
        lib, hold = real if native else (None, None)
        monkeypatch.setattr(nativedsp, "LIB", lib)
        monkeypatch.setattr(nativedsp, "HOLD", hold)
        dsp._plans.clear()
    yield use
    dsp._plans.clear()


def both(switch, make, feed):
    """`feed(make())` once in C++, once in Python."""
    switch(True)
    a = feed(make())
    switch(False)
    b = feed(make())
    switch(True)
    return a, b


def blocks(effect, x, sizes, rate=48000):
    out, i, k = [], 0, 0
    while i < len(x):
        n = sizes[k % len(sizes)]
        out.append(effect.run(x[i:i + n].copy(), rate))
        i += n
        k += 1
    return np.concatenate(out)


@needs_dll
@pytest.mark.parametrize("sizes", [[480], [64], [4096], [2000, 7, 480, 1], [1024, 512, 3000]])
@pytest.mark.parametrize("rate", [48000, 44100, 96000])
def test_reverb_matches_python(switch, sizes, rate):
    x = signal(rate)
    for values in ({}, {"size": 0, "tone": 1500, "mix": 1, "predelay": 0},
                   {"size": 1, "tone": 12000, "mix": 0.5, "predelay": 100}):
        a, b = both(switch, lambda v=values: Reverb(rate, v),
                    lambda e: blocks(e, x, sizes, rate))
        assert a.dtype == F32 and len(a) == len(x)
        assert diff_db(a, b) < TOLERANCE_DB


@needs_dll
def test_reverb_moved_knobs_and_light_mode(switch):
    x = signal(48000)

    def feed(e):
        out = []
        for i, at in enumerate(range(0, len(x), 480)):
            e.p = e._values({"size": (i % 50) / 50, "tone": 2000 + 100 * (i % 90), "mix": 0.5,
                             "predelay": (i // 10) % 100})
            if i % 40 == 20:
                e.set_light(not e.light)
            out.append(e.run(x[at:at + 480].copy(), 48000))
        return np.concatenate(out)

    a, b = both(switch, lambda: Reverb(48000, {}), feed)
    assert diff_db(a, b) < TOLERANCE_DB


@needs_dll
def test_reverb_rings_out_like_python(switch):
    x = np.zeros(480, F32)

    def feed(e):
        e.run(signal(4800), 48000)
        rung = []
        for _ in range(1500):
            e.run(x, 48000)
            rung.append(e.rung_out(livefx.REST_FLOOR))
        return np.array(rung)

    a, b = both(switch, lambda: Reverb(48000, {}), feed)
    assert a.any() and not a[0]
    assert abs(int(np.argmax(a)) - int(np.argmax(b))) <= 1


@needs_dll
@pytest.mark.parametrize("fx", [{"reverb": 0.55},
                                {"bass": 6, "reverb": 0.5, "echo": 0.4, "crunch": 0.3},
                                {"muffle": 0.8, "reverb": 0.3, "bass": 4}])
def test_live_effects_match_python(switch, fx):
    """Stereo, with silence (the resting path), a Stop all (the flush) and the knobs going
    back to 0 (the fade-out)."""
    x = signal(96000, stereo=True)
    x[48000:] = 0.0

    def feed(f):
        out = []
        for i, at in enumerate(range(0, len(x), 480)):
            if i == 70:
                f.flush()
            out.append(f.process(x[at:at + 480].copy(), {} if i > 150 else fx).copy())
        return np.concatenate(out)

    a, b = both(switch, lambda: livefx.LiveFx(48000), feed)
    assert a.shape == x.shape
    assert diff_db(a, b) < TOLERANCE_DB


@needs_dll
@pytest.mark.parametrize("dtype", [np.float32, np.float64])
@pytest.mark.parametrize("n", [1, 63, 480, 5000])
def test_filters_match_python(switch, dtype, n):
    x = signal(n * 5).astype(dtype)
    sos = dsp.butter(4, 300, btype="high", fs=48000)
    b, a = [0.2, 0.3], [1.0, -0.5]

    def run(f, zero):
        zi, out = zero, []
        for at in range(0, len(x), n):
            y, zi = f(x[at:at + n], zi)
            out.append(y)
        return np.concatenate(out), zi

    def feed(_):
        s, zs = run(lambda c, z: dsp.sosfilt(sos, c, zi=z), np.zeros((2, 2)))
        t, zt = run(lambda c, z: dsp.lfilter(b, a, c, zi=z), np.zeros(1))
        return s, zs, t, zt, dsp.sosfilt(sos.astype(F32), x.astype(F32))

    got, want = both(switch, lambda: None, feed)
    for p, q in zip(got, want):
        assert diff_db(p, q) < TOLERANCE_DB


@needs_dll
def test_filter_bank_matches_python(switch):
    bank = np.stack([dsp.butter(2, f, btype="low", fs=48000) for f in (200, 2000, 8000)])
    x = signal(4800, stereo=True).T.astype(np.float64)

    def feed(_):
        y, s = dsp.sosfilt_bank(bank, x[:, :2400])
        z, s = dsp.sosfilt_bank(bank, x[:, 2400:], s)
        return np.concatenate([y, z], axis=2), s

    (a, sa), (b, sb) = both(switch, lambda: None, feed)
    assert diff_db(a, b) < TOLERANCE_DB and diff_db(sa, sb) < TOLERANCE_DB


@needs_dll
@pytest.mark.parametrize("filters, rows, sections", [(1, 2, 1), (3, 1, 2), (16, 2, 3), (2, 40, 1),
                                                     (5, 3, 9)])
def test_side_by_side_filters_match_one_at_a_time(switch, filters, rows, sections):
    """(5, 3, 9): more sections than fit side by side, so it goes one at a time."""
    bank = np.stack([np.vstack([dsp.butter(2, 200 + 150 * f + 40 * k, fs=48000)
                                for k in range(sections)]) for f in range(filters)])
    x = np.stack([signal(2000, seed=r + 1) for r in range(rows)]).astype(np.float64)

    def feed(_):
        y, s = dsp.sosfilt_bank(bank, x[:, :1000])
        z, s = dsp.sosfilt_bank(bank, x[:, 1000:], s)
        return np.concatenate([y, z], axis=2), s

    (a, sa), (b, sb) = both(switch, lambda: None, feed)
    assert diff_db(a, b) < TOLERANCE_DB and diff_db(sa, sb) < TOLERANCE_DB


def smooth_stream(x, designs, sizes, fast, axis=0, poke=False):
    """A SmoothSos over x in blocks of `sizes` (cycled), the design switching to
    designs[k] at block k; the output, every block's rung_out and the final zi. `poke`
    reads and writes zi now and then, as the echo's tone filter does."""
    f = dsp.SmoothSos(fade=300)
    f.FAST = fast
    out, rung, sos, i, k, shortcut = [], [], None, 0, 0, 0
    while i < x.shape[axis]:
        sos = designs.get(k, sos)
        m = sizes[k % len(sizes)]
        part = np.take(x, range(i, min(i + m, x.shape[axis])), axis=axis)
        out.append(np.asarray(f.run(part, sos, axis=axis)).copy())
        shortcut += f._fast is not None
        if poke and k % 11 == 5 and f.zi is not None:
            f.zi = f.zi.copy()
        rung.append(f.rung_out(1e-6))
        i, k = i + m, k + 1
    assert (shortcut > k // 2) == fast    # the shortcut takes most blocks, or none
    return np.concatenate(out, axis=axis), rung, f.zi


@pytest.mark.parametrize("native", [True, False])
@pytest.mark.parametrize("shape", ["mono", "stereo", "stereo-last", "float64"])
@pytest.mark.parametrize("sizes", [[480], [1, 63, 512, 7, 480, 1000]])
@pytest.mark.parametrize("poke", [False, True])
def test_steady_filter_is_bit_identical(switch, native, shape, sizes, poke):
    """SmoothSos's steady-state shortcut against every block through sosfilt: the same
    bits, with knobs moving mid-stream (fades), a switch to straight through and back,
    a design with more sections, float32 and float64 designs."""
    if native and nativedsp.LIB is None:
        pytest.skip("obdsp isn't built here")
    switch(native)
    x = signal(48000, stereo=shape != "mono")
    axis = 0
    if shape == "stereo-last":
        x, axis = np.ascontiguousarray(x.T), 1
    if shape == "float64":
        x = x.astype(np.float64)
    lo = dsp.butter(2, 900, fs=48000)
    designs = {0: lo, 20: dsp.butter(2, 400, btype="high", fs=48000).astype(F32),
               21: dsp.butter(2, 500, btype="high", fs=48000), 40: None,
               50: np.vstack([lo, dsp.butter(2, 3000, fs=48000)]), 75: lo}
    got = smooth_stream(x, designs, sizes, True, axis, poke)
    want = smooth_stream(x, designs, sizes, False, axis, poke)
    assert got[0].dtype == want[0].dtype and got[0].shape == want[0].shape
    assert got[0].tobytes() == want[0].tobytes()
    assert got[1] == want[1]
    assert got[2] is not None and got[2].dtype == want[2].dtype
    assert got[2].shape == want[2].shape and got[2].tobytes() == want[2].tobytes()


@pytest.mark.parametrize("native", [True, False])
def test_steady_filter_layout_change_carries_on(switch, native):
    """Blocks that change dtype mid-stream still join exactly as through sosfilt."""
    if native and nativedsp.LIB is None:
        pytest.skip("obdsp isn't built here")
    switch(native)
    x = signal(9600)
    sos = dsp.butter(2, 700, fs=48000)

    def feed(fast):
        f = dsp.SmoothSos()
        f.FAST = fast
        out = []
        for k, at in enumerate(range(0, len(x), 480)):
            part = x[at:at + 480]
            out.append(f.run(part.astype(np.float64) if k % 3 == 1 else part, sos))
        return np.concatenate(out)

    assert feed(True).tobytes() == feed(False).tobytes()


@needs_dll
def test_filter_leaves_the_callers_state_alone():
    zi = np.ones((1, 2))
    keep = zi.copy()
    dsp.sosfilt(dsp.butter(2, 300, fs=48000), np.ones(480), zi=zi)
    assert (zi == keep).all()


@needs_dll
@pytest.mark.parametrize("sizes", [[480], [1], [1000, 3]])
def test_oversampling_and_crunch_match_python(switch, sizes):
    x = signal(9600)

    def os_feed(o):
        out, i, k = [], 0, 0
        while i < len(x):
            n = sizes[k % len(sizes)]
            out.append(o.run(x[i:i + n].copy(), lambda z: np.tanh(z * 3)))
            i += n
            k += 1
        return np.concatenate(out)

    a, b = both(switch, lambda: _Oversampled(48000), os_feed)
    assert a.dtype == F32 and diff_db(a, b) < TOLERANCE_DB
    a, b = both(switch, lambda: Distortion(48000, {"drive": 24}), lambda e: blocks(e, x, sizes))
    assert diff_db(a, b) < TOLERANCE_DB


@needs_dll
def test_echo_matches_python(switch):
    x = signal(48000)
    a, b = both(switch, lambda: Echo(48000, {"delay": 40, "tone": 3000, "feedback": 0.7}),
                lambda e: blocks(e, x, [480, 2000, 1]))
    assert diff_db(a, b) < TOLERANCE_DB


@needs_dll
def test_echo_moved_knobs_match_python(switch):
    x = signal(48000)

    def feed(e):
        out = []
        for i, at in enumerate(range(0, len(x), 480)):
            e.p = e._values({"delay": 100 + 10 * (i // 20), "tone": 12000 if i % 60 > 30 else 3000,
                             "feedback": 0.5, "mix": 0.5})
            out.append(e.run(x[at:at + 480].copy(), 48000))
        return np.concatenate(out)

    a, b = both(switch, lambda: Echo(48000, {}), feed)
    assert a.dtype == F32 and diff_db(a, b) < TOLERANCE_DB


@needs_dll
@pytest.mark.parametrize("sizes", [[480], [1], [7, 2000]])
def test_compressor_matches_python(switch, sizes):
    x = signal(48000)
    x[20000:24000] *= 3     # over the threshold, and back

    def feed(e):
        out, i, k = [], 0, 0
        while i < len(x):
            n = sizes[k % len(sizes)]
            if k % 10 == 5:
                e.p = e._values({"boost": k % 24, "threshold": -30, "ratio": 8})
            out.append(e.run(x[i:i + n].copy(), 48000))
            i += n
            k += 1
        return np.concatenate(out)

    a, b = both(switch, lambda: Compressor(48000, {}), feed)
    # (its level is in float32 dB: one rounding at 60 dB is a little more than elsewhere)
    assert a.dtype == F32 and diff_db(a, b) < -90


@needs_dll
@pytest.mark.parametrize("sizes", [[480], [64], [2000, 1]])
def test_smart_mono_matches_python(switch, sizes):
    m = signal(48000)
    side = np.roll(signal(48000, seed=2), 11)
    # in phase, then a band out of phase (it flips), then back
    x = np.stack([m, m], 1).astype(F32)
    x[16000:32000, 1] = -m[16000:32000]
    x[32000:, 1] = side[32000:]

    def feed(e):
        out, i, k = [], 0, 0
        while i < len(x):
            n = sizes[k % len(sizes)]
            out.append(e.process(x[i:i + n].copy()))
            i += n
            k += 1
        return np.concatenate(out)

    a, b = both(switch, lambda: SmartMono(48000), feed)
    assert a.dtype == F32 and a.shape == x.shape
    assert diff_db(a, b) < TOLERANCE_DB


@needs_dll
def test_harmonics_match_python(switch):
    rng = np.random.default_rng(3)
    ph = np.cumsum(np.full(480, 2 * np.pi * 110 / 48000)) + 1.0
    old, amps = rng.random(40), rng.random(40)
    a, b = both(switch, lambda: None, lambda _: _harmonics(ph, old, amps))
    assert diff_db(a, b) < -200


@needs_dll
def test_envelope_matches_python(switch):
    t = np.random.default_rng(4).random(50)
    lens = np.full(50, 48)
    a, b = both(switch, lambda: None, lambda _: _envelope(t, 1.0, lens, 48000, 0.004, 0.15))
    assert diff_db(a, b) < -200


@needs_dll
def test_flanger_matches_python(switch):
    x = signal(48000)

    def feed(e):
        out = []
        for i, at in enumerate(range(0, len(x), 480)):
            e.p = e._values({"rate": 2, "depth": 1 + (i // 10) % 6, "feedback": (i // 30) * 0.2,
                             "mix": 0.5})
            out.append(e.run(x[at:at + 480].copy(), 48000))
        return np.concatenate(out)

    a, b = both(switch, lambda: Flanger(48000, {}), feed)
    assert a.dtype == F32 and diff_db(a, b) < TOLERANCE_DB


@needs_dll
@pytest.mark.parametrize("rate", [48000, 44100, 16000])
@pytest.mark.parametrize("hz", [0, 80, 110, 220, 440, 900, 3000])
def test_pitch_tracker_matches_python(switch, rate, hz):
    """Once its window is full of sound (before that, on a run of exact zeros, the Python
    version's answer comes from its FFT's rounding noise)."""
    t = np.arange(rate) / rate
    x = 0.2 * np.sin(2 * np.pi * hz * t) + 0.1 * np.sin(4 * np.pi * hz * t)
    x = (x + 0.002 * np.random.default_rng(5).standard_normal(rate)).astype(F32)

    def feed(tr):
        return np.array([tr.update(x[at:at + 480]) for at in range(0, rate - 480, 480)])

    a, b = both(switch, lambda: _PitchTracker(rate), feed)
    full = _PitchTracker(rate).window // 480 + 1
    assert ((a[full:] > 0) == (b[full:] > 0)).all()
    assert np.max(np.abs(a[full:] - b[full:]), initial=0) < 1e-6


@needs_dll
def test_a_bad_call_is_refused_and_changes_nothing():
    lib = nativedsp.HOLD
    x, y, s = np.zeros(8, F32), np.zeros(8, F32), np.zeros(2)
    c = np.array([1.0, 0, 0, 0, 0])
    xp, yp = x.ctypes.data, y.ctypes.data
    for args in ((None, 1, 1, xp, yp, 4, 1, 8, s.ctypes.data),
                 (c.ctypes.data, 0, 1, xp, yp, 4, 1, 8, s.ctypes.data),
                 (c.ctypes.data, 1, 1, xp, yp, 3, 1, 8, s.ctypes.data),
                 (c.ctypes.data, 1, 1, xp, yp, 4, 1, -8, s.ctypes.data)):
        assert lib.ob_sos(*args) < 0
    r = nativedsp.Reverb(48000, 480, dsp.butter(2, 150, btype="high", fs=48000).astype(F32))
    assert lib.ob_reverb_run(r.at, r.bytes - 1, xp, yp, 8, .8, .5, 0, .5, 8, 4) < 0
    assert lib.ob_reverb_run(r.at, r.bytes, xp, yp, 8, .8, .5, 10 ** 7, .5, 8, 4) < 0
    assert lib.ob_reverb_run(r.at, r.bytes, xp, yp, 8, .8, .5, 0, .5, 9, 4) < 0
    assert lib.ob_reverb_run(None, r.bytes, xp, yp, 8, .8, .5, 0, .5, 8, 4) < 0
    r.mem[0] = 0.0   # a state that lost its header
    assert lib.ob_reverb_run(r.at, r.bytes, xp, yp, 8, .8, .5, 0, .5, 8, 4) < 0
    with pytest.raises(ValueError):
        nativedsp.check(-1)


@needs_dll
def test_a_long_call_lets_other_threads_run():
    """Python's lock is free during the reverb: another Python thread gets on with it."""
    x = np.zeros(48000 * 120, F32)
    e = Reverb(48000, {})
    counted, stop = [0], threading.Event()

    def count():
        while not stop.is_set():
            counted[0] += 1

    t = threading.Thread(target=count, daemon=True)
    t.start()
    time.sleep(0.05)
    before = counted[0]
    took = time.perf_counter()
    e.run(x, 48000)
    took = time.perf_counter() - took
    during = counted[0] - before
    stop.set()
    t.join(5)
    assert took > 0.01
    assert during > 1000   # (holding the lock it would be a handful at most)


def test_it_runs_without_the_dll(switch):
    """A run from source, or a DLL that wouldn't load: the Python versions, same calls."""
    switch(False)
    e = Reverb(48000, {})
    assert e.native is None
    assert len(e.run(signal(480), 48000)) == 480
    assert not e.rung_out(1e-12)
    assert len(dsp.sosfilt(dsp.butter(2, 300, fs=48000), signal(480))) == 480


def test_a_broken_dll_falls_back(monkeypatch, tmp_path):
    bad = tmp_path / nativedsp.NAME
    bad.write_bytes(b"not a library")
    monkeypatch.setattr(nativedsp, "_path", lambda: bad)
    assert nativedsp._load() == (None, None)
