import numpy as np

from soundboard import destination
from soundboard.destination import BUILTIN, OFF, Dest, Processor, all_modes, resolve

RATE = 48000


def _tone(hz, seconds=1.0, level=0.3):
    t = np.arange(int(seconds * RATE)) / RATE
    x = (level * np.sin(2 * np.pi * hz * t)).astype(np.float32)
    return np.repeat(x[:, None], 2, axis=1)


def _run(x, d, block=480):
    p = Processor(RATE)
    return np.concatenate([p.process(x[i:i + block].copy(), d) for i in range(0, len(x), block)])


def _band_db(x, lo, hi):
    spec = np.abs(np.fft.rfft(x[:, 0] * np.hanning(len(x))))
    f = np.fft.rfftfreq(len(x), 1 / RATE)
    m = (f >= lo) & (f < hi)
    return 10 * np.log10((spec[m] ** 2).sum() + 1e-20)


def test_off_is_identity_and_cheap():
    x = _tone(440)
    p = Processor(RATE)
    y = p.process(x, None)
    assert y is x
    assert p.process(x, OFF) is x


def test_ceiling_lowpasses():
    d = Dest("t", "t", ceiling=8000)
    hi = _run(_tone(14000), d)
    lo = _run(_tone(1000), d)
    assert 20 * np.log10(np.abs(hi[RATE // 2:]).max() / 0.3) < -30
    assert abs(20 * np.log10(np.abs(lo[RATE // 2:]).max() / 0.3)) < 1


def test_bass_adds_harmonics_where_codecs_keep_them():
    d = Dest("t", "t", bass=1.0)
    x = _tone(50)
    y = _run(x, d)
    before, after = _band_db(x, 100, 350), _band_db(y, 100, 350)
    assert after - before > 20                     # harmonics appeared in 100-350 Hz
    assert abs(_band_db(y, 40, 60) - _band_db(x, 40, 60)) < 2.0   # fundamental near-untouched
    assert np.abs(y).max() < 1.0


def test_bass_leaves_midrange_alone():
    d = Dest("t", "t", bass=1.0)
    x = _tone(1000)
    y = _run(x, d)
    # skip the onset: the tone's abrupt start is a real click with real bass in it
    assert np.abs(y[RATE // 4:] - x[RATE // 4:]).max() < 1e-3


def test_mono_averages_channels():
    d = Dest("t", "t", mono=True)
    x = _tone(440)
    x[:, 1] *= -1                                   # out of phase: mono should cancel
    y = _run(x, d)
    assert np.abs(y).max() < 1e-6
    assert np.array_equal(y[:, 0], y[:, 1])


def test_compressor_tames_loud_keeps_quiet():
    d = Dest("t", "t", comp=1.0)
    loud = _run(_tone(440, level=0.9), d)
    quiet = _run(_tone(440, level=0.05), d)
    assert np.abs(loud[RATE // 2:]).max() < 0.75      # 0.9 squeezed
    assert 0.06 < np.abs(quiet[RATE // 2:]).max() < 0.08   # only the 3 dB make-up
    p = Processor(RATE)
    y = p.process(_tone(440, seconds=0.01, level=0.9), d)
    assert np.all(np.isfinite(y))


def test_changing_amount_keeps_filter_memory():
    x = _tone(60, seconds=0.5)
    p = Processor(RATE)
    p.process(x[:2400].copy(), Dest("t", "t", bass=0.5, ceiling=12000))
    lp, ce = p._lp, p._ceil
    p.process(x[2400:4800].copy(), Dest("t", "t", bass=0.9, ceiling=12000))
    assert p._lp is lp and p._ceil is ce
    p.process(x[4800:7200].copy(), Dest("t", "t", bass=0.9, ceiling=8000))
    assert p._ceil is not ce                      # a new ceiling needs a new filter


def test_blockwise_equals_one_shot():
    """State carried between callbacks: chopping into blocks changes nothing."""
    d = Dest("t", "t", bass=0.8, ceiling=12000, mono=True)
    x = _tone(70, seconds=0.3) + _tone(5000, seconds=0.3, level=0.1)
    whole = Processor(RATE).process(x.copy(), d)
    blocks = _run(x, d, block=256)
    assert np.abs(whole - blocks).max() < 1e-4


def test_builtin_modes_and_custom_resolution():
    assert resolve(None) is OFF
    assert resolve({"mode": "nope"}) is OFF
    assert resolve({"mode": "steam"}).ceiling == 12000
    keys = [d.key for d in BUILTIN]
    assert keys[0] == "off" and len(keys) == len(set(keys))
    custom = [{"key": "mumble", "label": "Mumble", "ceiling": 16000, "bass": 0.3, "comp": 2,
               "mono": True},
              {"key": "discord", "label": "dupe of a builtin"},
              "garbage", {"key": "bad", "ceiling": "x", "bass": "y"}]
    modes = all_modes(custom)
    assert [d.key for d in modes] == keys + ["mumble", "bad"]
    m = resolve({"mode": "mumble", "custom": custom})
    assert m.custom and m.comp == 1.0 and m.ceiling == 16000 and m.mono
    bad = resolve({"mode": "bad", "custom": custom})
    assert bad.ceiling == 0 and bad.bass == 0
    d = Dest.from_dict(m.to_dict())
    assert d == m


def test_apply_sets_engine_dest():
    class Cfg:
        dest = {"mode": "discord"}

    class Eng:
        dest = None
    e = Eng()
    assert destination.apply(Cfg(), e).key == "discord"
    assert e.dest is not None and e.dest.mono
    Cfg.dest = {"mode": "off"}
    destination.apply(Cfg(), e)
    assert e.dest is None


def test_every_builtin_runs_at_odd_rates():
    x = np.random.default_rng(0).standard_normal((1000, 2)).astype(np.float32) * 0.2
    for rate in (44100, 48000, 96000, 16000):
        for d in BUILTIN:
            y = Processor(rate).process(x.copy(), d)
            assert y.shape == x.shape and y.dtype == np.float32 and np.all(np.isfinite(y))
