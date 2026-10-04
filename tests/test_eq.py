import numpy as np

from soundboard import dsp, eq


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
    y64 = dsp.sosfilt(eq._rows(gains, 48000), x.astype(np.float64), axis=0)
    assert np.max(np.abs(y32 - y64)) < 1e-3


def test_state_carries_between_blocks_without_a_seam():
    gains = eq.PRESETS["Music — club / loud"]
    t = np.arange(9600) / 48000
    x = np.stack([np.sin(2 * np.pi * 200 * t)] * 2, 1).astype(np.float32)
    whole = eq.EQ(48000).process(x, gains)
    f = eq.EQ(48000)
    parts = np.concatenate([f.process(x[:4800], gains), f.process(x[4800:], gains)])
    # float32 state: the split rounds differently by up to ~1e-5 (-98 dB), and how much
    # depends on the CPU's vector path (it failed on one CI runner, passed on the next).
    # A real seam, the state lost at the split, is ~0.77.
    assert np.allclose(whole, parts, atol=1e-4)
    lost = eq.EQ(48000).process(x[4800:], gains)
    assert np.abs(lost - whole[4800:]).max() > 0.1   # ...which this test would catch


def test_switching_off_then_on_restarts_state_cleanly():
    f = eq.EQ(48000)
    x = np.ones((100, 2), np.float32)
    f.process(x, eq.PRESETS["Music — bass boost"])
    for _ in range(11):                      # off: fades to dry over ~1024 samples
        f.process(x, None)
    assert f.idle and f.process(x, None) is x   # then passthrough
    y = f.process(x, eq.PRESETS["Music — bass boost"])
    assert np.all(np.isfinite(y))


def _bend(v):
    """The largest bend in a waveform (second difference): where a click shows."""
    return np.max(np.abs(np.diff(v, 2)))


def _sine(n, hz=80, rate=48000):
    t = np.arange(n) / rate
    return np.stack([np.sin(2 * np.pi * hz * t)] * 2, 1).astype(np.float32) * 0.5


def test_a_change_fades_over_its_full_length_even_in_small_blocks():
    """At 64-frame blocks the fade used to end with its block: 1.3 ms, still a click.
    Now it runs the whole ~20 ms, so tiny and big blocks sound the same."""
    x = _sine(9600)
    before, after = [0, 0, 0, 0, 0, 0, 0], [12, 12, 0, 0, 0, 0, 0]

    def run(block):
        f, out = eq.EQ(48000), []
        for i in range(0, 4800, block):
            out.append(f.process(x[i:i + block], before))
        for i in range(4800, 9600, block):
            out.append(f.process(x[i:i + block], after))
        return np.concatenate(out)[:, 0]
    small, big = run(64), run(4800)
    assert np.allclose(small, big, atol=1e-4)            # the same fade either way
    steady = _bend(big[200:4700])
    assert _bend(small[4790:5900]) < 3 * steady           # no click at the change


def test_turning_the_eq_off_and_on_fades_instead_of_clicking():
    """Unticking EQ (gains None) used to switch straight to the dry sound and a
    re-enabled EQ started at full strength: both clicked on a bass boost."""
    x = _sine(19200)
    boost = [12, 12, 0, 0, 0, 0, 0]
    f, out = eq.EQ(48000, fade_in=True), []
    for i in range(0, 19200, 64):
        gains = boost if i < 4800 or i >= 9600 else None    # on, off, on again
        out.append(f.process(x[i:i + 64], gains))
    y = np.concatenate(out)[:, 0]
    steady = _bend(y[2000:4700])
    for at in (0, 4800, 9600):
        assert _bend(y[max(at - 10, 0):at + 1500]) < 3 * steady, at
    assert np.allclose(y[7000:9600], x[7000:9600, 0], atol=1e-6)   # off: dry
    assert not f.idle


def test_the_engine_fades_its_eq_out_before_dropping_it():
    from soundboard.engine import Engine
    e = Engine.__new__(Engine)
    e._eqs, e.rates = {}, {"main": 48000}
    e.eq_gains, e.eq_target = [12, 12, 0, 0, 0, 0, 0], "all"
    x = _sine(64)
    e._eq("main", "sounds", x)
    assert ("main", "sounds") in e._eqs
    e.eq_gains = None
    e._eq("main", "sounds", x)
    assert ("main", "sounds") in e._eqs                  # still fading out
    for _ in range(40):   # the fade in ends first (1024 samples), then the fade out
        y = e._eq("main", "sounds", x)
    assert ("main", "sounds") not in e._eqs and y is x   # done: dropped, passthrough


def test_bands_follow_the_analog_eq_up_to_nyquist():
    """The matched design keeps every band's analog shape: within 0.4 dB of the
    analog EQ across the audible range, at every common rate, even the 12 kHz
    shelf at 44.1 kHz (the cookbook design was up to ~2 dB off there)."""
    for rate in (44100, 48000, 96000):
        f = np.geomspace(20, min(20000, rate * 0.45), 400)
        for i, (f0, kind) in enumerate(eq.BANDS):
            q = eq.PEAK_Q if kind == "peak" else eq.SHELF_SLOPE
            for g in (-12, -5, 5, 12):
                gains = [0.0] * 7
                gains[i] = g
                num, den = dsp._analog(kind, g, q)
                s = 1j * f / f0
                want = 20 * np.log10(np.abs(np.polyval(num, s) / np.polyval(den, s)))
                got = eq.response_db(gains, f, rate)
                assert np.max(np.abs(got - want)) < 0.4, (rate, f0, g)


def test_moving_a_slider_doesnt_click():
    """A big gain change mid-stream crossfades instead of switching coefficients
    at once: the step it leaves in the waveform is far smaller."""
    t = np.arange(4800) / 48000
    x = np.stack([np.sin(2 * np.pi * 80 * t)] * 2, 1).astype(np.float32) * 0.5
    before, after = [0, 0, 0, 0, 0, 0, 0.5], [12, 12, 0, 0, 0, 0, 0.5]
    f = eq.EQ(48000)
    y = np.concatenate([f.process(x[:2400], before), f.process(x[2400:], after)])[:, 0]
    # the same change made abruptly: the new coefficients pick up the old state
    a, z = dsp.sosfilt(eq.design(before, 48000), x[:2400], axis=0,
                       zi=np.zeros((7, 2, 2), np.float32))
    b, _ = dsp.sosfilt(eq.design(after, 48000), x[2400:], axis=0, zi=z)
    hard = np.concatenate([a, b])[:, 0]

    def click(v):   # the largest bend in the waveform around the change
        return np.max(np.abs(np.diff(v[2390:2420], 2)))
    assert click(y) < 0.5 * click(hard)


def test_turning_bands_flat_fades_back_to_the_dry_signal():
    x = np.full((3000, 2), 0.25, np.float32)
    f = eq.EQ(48000)
    f.process(x, eq.PRESETS["Music — bass boost"])
    y = f.process(x, eq.PRESETS["Flat (off)"])          # fades out over this block
    assert np.allclose(y[-1], 0.25, atol=1e-6)
    assert f.process(x, eq.PRESETS["Flat (off)"]) is x   # then straight through


def test_eq_panel_copes_with_damaged_gains(qapp):
    """A NaN, a string or a huge number in eq_gains made int(round(g * 2)) raise while
    the main window was built, on every launch."""
    from soundboard.ui.panel import EqPanel
    p = EqPanel(True, "voice", "Custom", [float("nan"), "x", 1e308, None, True, -3, 2.5])
    assert p.gains() == [0.0, 0.0, eq.MAX_DB, 0.0, 0.0, -3.0, 2.5]
    for bad in ([1, 2], None, 5, "flat"):
        p = EqPanel(False, "voice", "Custom", bad)
        assert p.gains() == [0.0] * 7
    p.set_gains([float("inf")] * 7)
    assert p.gains() == [0.0] * 7 and not p.chk_on.isChecked()
