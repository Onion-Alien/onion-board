"""The send stage: the limiter never lets a peak past its ceiling and leaves quiet
audio untouched, the mono downmix rescues what a plain average cancels and leaves
mono alone, the ducker lowers sounds only while you talk, and the engine runs all
of it on the cable (and on your headphones only in 'hear what they hear')."""
import numpy as np
import pytest

from soundboard import codecsim, sendfx
from soundboard.sendfx import Ducker, Limiter, SmartMono
from tests.test_engine import engine_with

SR = 48000
BLOCK = 480


def blocks(proc, x, n=BLOCK):
    return np.concatenate([proc.process(x[i:i + n]) for i in range(0, len(x), n)])


def db(r):
    return 20 * np.log10(max(float(r), 1e-12))


def rms(x):
    return float(np.sqrt(np.mean(np.asarray(x, np.float64) ** 2)))


# ---------------------------------------------------------------- limiter

def test_forward_min():
    x = np.array([5, 4, 3, 9, 1, 2, 8, 7, 6], float)
    assert list(sendfx._forward_min(x, 2)[:7]) == [3, 3, 1, 1, 1, 2, 6]


@pytest.mark.parametrize("n", [480, 441, 64, 1024])
def test_limiter_holds_the_ceiling_whatever_the_block_size(n):
    x = codecsim.pink_noise(2, level=1.8)
    x[SR // 2:SR // 2 + 3] = 4.0          # a spike
    y = blocks(Limiter(SR), x, n)
    assert np.abs(y).max() <= 10 ** (sendfx.CEILING_DB / 20) + 1e-6


def test_limiter_is_transparent_below_the_ceiling():
    lim = Limiter(SR)
    x = codecsim.pink_noise(1, level=0.4)
    y = blocks(lim, x)
    la = lim.la
    assert np.array_equal(y[la:], x[:len(y) - la])       # just delayed


def test_limiter_turns_down_instead_of_bending_the_wave():
    # a loud sine: limiting by gain keeps it a sine (no new harmonics)
    t = np.arange(SR) / SR
    x = np.repeat((np.sin(2 * np.pi * 440 * t) * 1.5)[:, None], 2, axis=1).astype(np.float32)
    y = blocks(Limiter(SR), x)[SR // 2:, 0]
    spec = np.abs(np.fft.rfft(y * np.hanning(len(y))))
    f = np.fft.rfftfreq(len(y), 1 / SR)
    fund = spec[(f > 430) & (f < 450)].max()
    harm = spec[(f > 1300) & (f < 1340)].max()          # 3rd harmonic: what a clipper makes
    assert db(harm / fund) < -60


def test_limiter_recovers_after_a_peak():
    x = np.full((SR, 2), 0.2, np.float32)
    x[1000:1010] = 1.0
    lim = Limiter(SR)
    blocks(lim, x)
    assert lim.env_db > -0.01          # a second later the gain is back to unity


# ---------------------------------------------------------------- mono

def test_mono_of_identical_channels_is_unchanged_in_level():
    x = codecsim.pink_noise(2, level=0.3)
    y = blocks(SmartMono(SR), x)
    assert np.array_equal(y[:, 0], y[:, 1])
    assert abs(db(rms(y[SR:, 0]) / rms(x[SR:, 0]))) < 0.1


def test_mono_rescues_out_of_phase_bass():
    t = np.arange(3 * SR) / SR
    x = np.stack([np.sin(2 * np.pi * 80 * t), -0.9 * np.sin(2 * np.pi * 80 * t)], 1)
    x = x.astype(np.float32)
    plain = db(rms(x[SR:].mean(axis=1)) / rms(x[SR:]))
    smart = db(rms(blocks(SmartMono(SR), x)[SR:, 0]) / rms(x[SR:]))
    assert plain < -20 and smart > -1.0


def test_mono_gives_wide_stereo_its_power_back():
    a = codecsim.pink_noise(3, level=0.3, seed=1)[:, 0]
    b = codecsim.pink_noise(3, level=0.3, seed=2)[:, 0]
    x = np.stack([a, b], 1)
    plain = db(rms(x[SR:].mean(axis=1)) / rms(x[SR:]))
    smart = db(rms(blocks(SmartMono(SR), x)[SR:, 0]) / rms(x[SR:]))
    assert plain < -2 and smart > -0.5


def test_mono_keeps_a_hard_panned_sound():
    # a game that takes only the left channel would lose this entirely
    t = np.arange(2 * SR) / SR
    x = np.stack([np.zeros_like(t), np.sin(2 * np.pi * 440 * t) * 0.5], 1).astype(np.float32)
    y = blocks(SmartMono(SR), x)
    assert rms(y[SR:, 0]) > 0.15 and np.array_equal(y[:, 0], y[:, 1])


# ---------------------------------------------------------------- ducker

def _talk(level=0.1, n=BLOCK, seed=0):
    return (np.random.default_rng(seed).standard_normal((n, 2)) * level).astype(np.float32)


def test_ducker_lowers_while_talking_and_comes_back():
    d = Ducker(SR)
    quiet = _talk(0.0005)
    for _ in range(50):                        # learn the noise floor
        assert d.process(quiet, BLOCK, -12.0) == 1.0
    for _ in range(30):                        # talk for 0.3 s
        g = d.process(_talk(0.1), BLOCK, -12.0)
    assert db(float(g[-1, 0])) == pytest.approx(-12.0, abs=0.5)
    for _ in range(300):                       # quiet again for 3 s
        g = d.process(quiet, BLOCK, -12.0)
    assert g == 1.0


def test_ducker_off_or_no_mic_does_nothing():
    assert Ducker(SR).process(_talk(0.2), BLOCK, 0.0) == 1.0
    assert Ducker(SR).process(None, BLOCK, -12.0) == 1.0


# ---------------------------------------------------------------- in the engine

def test_engine_sends_mono_and_limited():
    e = engine_with("main", send_stage=True)
    t = np.arange(SR) / SR
    x = np.stack([np.sin(2 * np.pi * 80 * t), -np.sin(2 * np.pi * 80 * t)], 1) * 1.5
    e.play("a", x.astype(np.float32), 1.0)
    out = np.zeros((BLOCK, 2), np.float32)
    got = []
    for _ in range(80):
        e._main(out, BLOCK)
        got.append(out.copy())
    y = np.concatenate(got)
    assert np.array_equal(y[:, 0], y[:, 1])
    assert np.abs(y).max() <= 10 ** (sendfx.CEILING_DB / 20) + 1e-6
    assert rms(y[SR // 2:]) > 0.3            # the anti-phase bass came through


def test_engine_ducks_sounds_under_the_mic():
    e = engine_with("main", send_stage=True)
    e.duck_db = -20.0
    e.ring_main.prefill = 0
    e.play("a", np.full((SR * 2, 2), 0.1, np.float32), 1.0, loop=True)
    out = np.zeros((BLOCK, 2), np.float32)
    for _ in range(40):                                   # silent mic: full level
        e.ring_main.write(np.zeros((BLOCK, 2), np.float32))
        e._main(out, BLOCK)
    before = rms(out)
    for i in range(40):                                   # talking
        e.ring_main.write(_talk(0.05, seed=i))
        e._main(out, BLOCK)
    e.mic_vol = 0.0     # measure the sounds alone on the last block
    for i in (98, 99):  # (the mic fades out over the first)
        e.ring_main.write(_talk(0.05, seed=i))
        e._main(out, BLOCK)
    assert db(rms(out[-200:]) / before) < -15   # past the limiter's delay: sounds alone


# ---------------------------------------------------------------- voice leveler

def _speech(seconds, level_db, seed=0, rate=SR):
    """Speech-like: noise in syllables (~4 a second) with short gaps, at an RMS
    of about level_db while sounding, two channels."""
    rng = np.random.default_rng(seed)
    n = int(seconds * rate)
    t = np.arange(n) / rate
    env = np.clip(np.sin(2 * np.pi * 4 * t), 0, None) ** 0.5
    x = rng.normal(0, 1, n) * env
    x *= 10 ** (level_db / 20) / rms(x)
    return np.stack([x, x], 1).astype(np.float32)


def _talk_db(y):
    """The level of the blocks that are talking (as the leveler sees them)."""
    fr = y[: len(y) // BLOCK * BLOCK, 0].reshape(-1, BLOCK).astype(np.float64)
    r = 10 * np.log10(np.mean(fr ** 2, 1) + 1e-12)
    talk = r > r.max() - 20
    return 10 * np.log10(np.mean(10 ** (r[talk] / 10)))


@pytest.mark.parametrize("level", [-34.0, -26.0, -12.0])
def test_leveler_brings_quiet_and_loud_voices_to_one_volume(level):
    lv = sendfx.VoiceLeveler(SR)
    y = blocks(lv, _speech(6, level))
    assert abs(_talk_db(y[SR * 3:]) - lv.TARGET_DB) < 2.5


def test_leveler_follows_you_leaning_back_from_the_mic():
    lv = sendfx.VoiceLeveler(SR)
    x = np.concatenate([_speech(4, -20, 1), _speech(6, -32, 2)])   # 12 dB quieter
    y = blocks(lv, x)
    assert abs(_talk_db(y[SR * 2:SR * 4]) - _talk_db(y[SR * 7:])) < 3.0   # was 12 dB apart


def test_leveler_holds_in_pauses_so_the_room_is_not_pulled_up():
    lv = sendfx.VoiceLeveler(SR)
    rng = np.random.default_rng(3)
    hiss = (rng.normal(0, 10 ** (-60 / 20), (SR * 4, 1)) * [1, 1]).astype(np.float32)
    blocks(lv, _speech(3, -26))
    g = lv.gain_db
    y = blocks(lv, hiss)
    assert abs(lv.gain_db - g) < 0.01            # silence: the gain doesn't move
    assert db(rms(y[SR:])) < -60 + g + 0.5


def test_leveler_catches_a_shout_at_once():
    lv = sendfx.VoiceLeveler(SR)
    blocks(lv, _speech(3, -34))                  # quiet mic: turned well up
    assert lv.gain_db > 10
    y = blocks(lv, _speech(1, -6, 5))            # then a shout
    assert np.abs(y[BLOCK * 2:]).max() <= 10 ** (lv.PEAK_DB / 20) + 1e-4


def test_engine_levels_the_voice_it_sends():
    e = engine_with("main", send_stage=True)
    e.main_stream = object()
    e.ring_main.prefill = 0
    e.rates["mic"] = SR
    e.voice_level = True
    x = _speech(4, -36)
    sent = []
    out = np.zeros((BLOCK, 2), np.float32)
    for i in range(0, len(x), BLOCK):
        e._mic(x[i:i + BLOCK])
        e._main(out, BLOCK)
        sent.append(out.copy())
    y = np.concatenate(sent)
    assert _talk_db(y[SR * 2:]) > -36 + 10       # turned up (off, it stays where it was)


# ------------------------------------------------- per-block shortcuts (same samples)

def _talk_blocks(seed=4, n=300):
    """A mic that talks, pauses and shouts now and then, as (BLOCK, 2) blocks."""
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        level = (0.002, 0.08, 0.6)[(i // 25) % 3 if i % 50 else 2]
        out.append((rng.standard_normal((BLOCK, 2)) * level).astype(np.float32))
    return out


def test_limiter_at_rest_shortcut_gives_the_same_samples():
    """At rest (gain 1, histories all 1s) the limiter skips re-checking them every
    block: what comes out is what checking each block gives."""
    fast, slow = Limiter(SR), Limiter(SR)
    for i, x in enumerate(_talk_blocks()):
        slow._open = False   # (checks its histories, as before the shortcut)
        if i % 40 == 7:   # silence through the rest path too
            a, b = fast.silence(BLOCK), slow.silence(BLOCK)
            assert (a is None) == (b is None)
            if a is None:
                continue
        else:
            a, b = fast.process(x), slow.process(x)
        assert np.array_equal(a, b), i
        assert fast.env_db == slow.env_db and fast.reduction_db == slow.reduction_db


def test_ducker_moves_the_same_whether_its_gain_is_used_or_not():
    """The sounds bus is silence: Ducker.process(ramp=False) makes no gain array but
    moves exactly as before, and a gain held still is the old ramp's value."""
    a, b = Ducker(SR), Ducker(SR)
    held = 0
    for i, m in enumerate(_talk_blocks()):
        ga = a.process(m, BLOCK, -12.0)
        gb = b.process(m, BLOCK, -12.0, ramp=i % 3 != 0)
        assert (a.gain_db, a.floor_db, a.held, a.talking) == (
            b.gain_db, b.floor_db, b.held, b.talking)
        if i % 3 == 0:
            assert gb == 1.0
        if isinstance(ga, np.ndarray) and ga.shape == (1, 1):
            held += 1
            old = (10 ** (np.linspace(a.gain_db, a.gain_db, BLOCK + 1)[1:] / 20)).astype(
                np.float32)[:, None]
            assert np.array_equal(np.broadcast_to(ga, old.shape), old)
            mix = np.ones((BLOCK, 2), np.float32) * 0.3
            assert np.array_equal(mix * ga, mix * old)
    assert held > 10   # (it did hold down while talking)


def test_mean_square_is_numpys_mean():
    rng = np.random.default_rng(9)
    for shape in ((480, 2), (441, 1), (7, 2), (1, 1)):
        for _ in range(200):
            x = (rng.standard_normal(shape) * rng.uniform(1e-5, 2)).astype(np.float32)
            assert sendfx._mean_square(x) == float(np.mean(np.square(x, dtype=np.float64)))
