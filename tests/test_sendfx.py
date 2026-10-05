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
