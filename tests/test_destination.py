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


def test_mono_is_one_channel_that_doesnt_cancel():
    d = Dest("t", "t", mono=True)
    x = _tone(440)
    x[:, 1] *= -1                  # out of phase: a plain average would be silence
    y = _run(x, d)
    assert np.array_equal(y[:, 0], y[:, 1])
    tail = slice(RATE // 2, None)
    assert np.sqrt((y[tail, 0] ** 2).mean()) > 0.9 * np.sqrt((x[tail, 0] ** 2).mean())


def test_compressor_tames_loud_keeps_quiet():
    d = Dest("t", "t", comp=1.0)
    loud = _run(_tone(440, level=0.9), d)
    quiet = _run(_tone(440, level=0.05), d)
    assert np.abs(loud[RATE // 2:]).max() < 0.35      # 0.9 (-4 dB RMS) squeezed 4:1
    assert 0.049 < np.abs(quiet[RATE // 2:]).max() < 0.051   # under the threshold: untouched
    p = Processor(RATE)
    y = p.process(_tone(440, seconds=0.01, level=0.9), d)
    assert np.all(np.isfinite(y))


def test_compressor_holds_through_silence():
    """A pause mustn't wind the gain back up (the next hit would come in too loud)."""
    d = Dest("t", "t", comp=1.0)
    p = Processor(RATE)
    for _ in range(100):
        p.process(_tone(440, seconds=0.01, level=0.9), d)
    g = p.g
    for _ in range(100):
        p.process(np.zeros((480, 2), np.float32), d)
    assert p.g == g


def test_lowcut_removes_sub_bass_keeps_bass():
    d = Dest("t", "t", lowcut=70)
    sub, kick, body = _run(_tone(40), d), _run(_tone(100), d), _run(_tone(1000), d)
    tail = slice(RATE // 2, None)
    rms = lambda y: 20 * np.log10(np.sqrt((y[tail, 0] ** 2).mean()) / (0.3 / np.sqrt(2)))  # noqa: E731
    assert rms(sub) < -30
    assert rms(kick) > -1.0 and abs(rms(body)) < 0.1


def test_harmonics_follow_the_level():
    """The saturator runs on the envelope-normalised band: a bass line 20 dB quieter
    gets harmonics 20 dB quieter, not a different sound."""
    d = Dest("t", "t", bass=1.0, lowcut=70)
    loud, quiet = _run(_tone(50, level=0.5), d), _run(_tone(50, level=0.05), d)
    tail = slice(RATE // 2, None)
    diff = _band_db(loud[tail], 100, 350) - _band_db(quiet[tail], 100, 350)
    assert abs(diff - 20) < 1.0


def test_cut_shares_and_makeup():
    x = _tone(40) + _tone(1000)                    # half the power under the cut
    s = destination.cut_shares(x, RATE)
    assert set(s) == {c for c in destination.LOWCUTS if c}
    assert 0.45 < s[70] < 0.55
    assert abs(destination.makeup(s[70]) - np.sqrt(2)) < 0.1
    assert destination.cut_shares(_tone(2000), RATE)[90] < 0.01
    assert destination.makeup(0.0) == 1.0
    cap = 10 ** (destination.MAKEUP_MAX_DB / 20)
    assert destination.makeup(1.0) == cap and destination.makeup(0.9999) == cap
    assert destination.cut_shares(np.zeros((500, 2), np.float32), RATE) == {}
    assert destination.cut_shares(np.zeros((RATE, 2), np.float32), RATE) == {}
    ints = (x * 32767).astype(np.int16)
    assert abs(destination.cut_shares(ints, RATE)[70] - s[70]) < 0.01
    for rate in (16000, 44100):                    # a sound decoded at another rate
        assert 0.4 < destination.cut_shares(x, rate)[70] < 0.6


def test_game_mode_sends_a_bass_song_at_its_level_without_the_sub():
    """The whole point, on a synthetic 808 track: most of the power under 70 Hz. With
    the sound's make-up (as Engine._render applies it) the mode sends the part a
    voice chat keeps at the level it had, where the old mode lost ~10 dB of it."""
    t = np.arange(4 * RATE) / RATE
    beat = np.exp(-(t % 0.5) * 6)                  # a hit every half second
    x = (0.5 * beat * np.sin(2 * np.pi * 45 * t) + 0.08 * np.sin(2 * np.pi * 600 * t)
         + 0.05 * np.sin(2 * np.pi * 2500 * t)).astype(np.float32)
    x = np.repeat(x[:, None], 2, axis=1)
    game = destination.BUILTIN_BY_KEY["game"]
    g = destination.makeup(destination.cut_shares(x, RATE)[game.lowcut])
    y = _run(x * np.float32(g), game)
    tail = slice(RATE, None)
    kept = _band_db(y[tail], 300, 3000) - _band_db(x[tail], 300, 3000)
    assert kept > 6                                 # the audible part comes up, not down
    assert _band_db(y[tail], 20, 60) - _band_db(x[tail], 20, 60) < -20   # the sub is gone
    assert _band_db(y[tail], 100, 300) - _band_db(x[tail], 100, 300) > 10  # harmonics


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
    assert bad.ceiling == 0 and bad.bass == 0 and bad.lowcut == 0   # old configs: no cut
    assert Dest.from_dict({"lowcut": 74}).lowcut == 70           # hand-edited: nearest
    assert Dest.from_dict({"lowcut": "x"}).lowcut == 0
    assert Dest.from_dict({"lowcut": 1e9}).lowcut == max(destination.LOWCUTS)
    assert Dest("k", "k", lowcut=80).active
    d = Dest.from_dict(m.to_dict())
    assert d == m


def test_one_mode_per_voice_engine_and_old_keys_still_resolve():
    """Configs saved by 1.5.1 and earlier store dest.mode: every key it had still
    picks the same kind of mode ("game" was Vivox all along, now named so)."""
    for key in ("off", "discord", "steam", "game", "game_lo"):
        assert resolve({"mode": key}).key == key
    assert resolve({"mode": "game"}).label == "Vivox"
    assert [d.key for d in BUILTIN] == ["off", "discord", "game", "eos", "webrtc", "steam",
                                        "unity", "game_lo"]
    for d in BUILTIN[1:]:
        # tuned on the bench: the cut and make-up, harmonics, never a compressor
        assert d.mono and d.lowcut in (80, 90) and d.bass > 0 and d.comp == 0, d.key
        assert d.note and len(d.label) <= 40, d.key
    assert {d.key: d.ceiling for d in BUILTIN if d.ceiling} == {
        "steam": 12000, "unity": 12000, "game_lo": 8000}
    from soundboard import voicesdk
    assert set(voicesdk.SIGNATURES.values()) <= set(destination.BUILTIN_BY_KEY)
    assert set(voicesdk.NAMES) <= set(destination.BUILTIN_BY_KEY)
    assert {k for k, _ in voicesdk.VOICE_APPS.values()} <= set(destination.BUILTIN_BY_KEY)


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


def test_custom_that_is_not_a_list_is_ignored():
    """An imported settings file can hold {"custom": 5}: every start then raised in
    destination.apply() while the main window was being built."""
    for custom in (5, True, "abc", {"key": "x"}, None):
        assert all_modes(custom) == list(BUILTIN)
        assert resolve({"mode": "discord", "custom": custom}).key == "discord"
    for bad in (5, "off", [1, 2], None):
        assert resolve(bad) is OFF


def test_from_dict_survives_nan_and_infinity():
    inf, nan = float("inf"), float("nan")
    d = Dest.from_dict({"key": "k", "ceiling": inf, "bass": nan, "comp": inf})
    assert d.ceiling == 0 and d.bass == 0.0 and d.comp == 0.0
    assert Dest.from_dict({"key": "k", "ceiling": nan}).ceiling == 0
    assert Dest.from_dict({"key": "k", "ceiling": -inf, "bass": 10 ** 400}).ceiling == 0
