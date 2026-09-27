"""The voice chat check: each kind of damage Discord's processing does is recognised,
and a clean path is called clean."""
import numpy as np
import pytest

from soundboard import chatcheck as cc

SR = cc.SR


def _heard(x, delay_s=0.4, gain=0.6, noise=1e-4, seed=0):
    """What a playback would capture: delayed, at some output volume, a little hiss."""
    rng = np.random.default_rng(seed)
    d = int(delay_s * SR)
    out = np.zeros((len(x) + d + SR // 2, 2), np.float32)
    out[d:d + len(x)] = x * gain
    out += rng.standard_normal(out.shape).astype(np.float32) * noise
    return out


def _env(x, fn):
    """Apply a per-sample gain curve fn(t seconds) to x."""
    t = np.arange(len(x)) / SR
    return (x * fn(t)[:, None]).astype(np.float32)


@pytest.fixture(scope="module")
def sig():
    return cc.test_signal()


def test_signal_shape_and_parts(sig):
    assert sig.shape == (int(cc.LENGTH_S * SR), 2)
    assert np.abs(sig).max() <= 0.36
    lvl = lambda a, b: 20 * np.log10(np.sqrt((sig[int(a * SR):int(b * SR), 0] ** 2).mean()))
    assert lvl(3.0, 3.6) < lvl(1.0, 2.0) - 20      # the quiet part really is quiet


def test_clean_path_is_clean(sig):
    r = cc.analyze(sig, _heard(sig))
    assert r["issues"] == []
    assert r["lag_s"] == pytest.approx(0.4, abs=0.01)
    assert r["fidelity"] > 0.95


def test_nothing_played_back(sig):
    r = cc.analyze(sig, np.zeros((SR * 7, 2), np.float32))
    assert r["issues"] == ["not_heard"]
    rng = np.random.default_rng(1)   # something else entirely (another app's audio)
    r = cc.analyze(sig, rng.standard_normal((SR * 7, 2)).astype(np.float32) * 0.1)
    assert r["issues"] == ["not_heard"]


def test_noise_suppression_fading_steady_music(sig):
    # steady content fades out within a second or so; the drums come through
    fade = lambda t: np.where(t < 2.5, np.clip(1 - (t - 0.5) / 1.2, 0.05, 1), 1.0)
    r = cc.analyze(sig, _heard(_env(sig, fade)))
    assert "suppression" in r["issues"]


def test_noise_suppression_garbling(sig):
    # a denoiser that keeps the level but not the waveform: random-phase resynthesis
    rng = np.random.default_rng(3)
    x = sig[:, 0].astype(np.float64)
    n = 1024
    out = np.zeros_like(x)
    win = np.hanning(n)
    for i in range(0, len(x) - n, n // 2):
        spec = np.fft.rfft(x[i:i + n] * win)
        spec = np.abs(spec) * np.exp(1j * rng.uniform(0, 6.28, len(spec)))
        out[i:i + n] += np.fft.irfft(spec, n) * win
    g = np.repeat(out[:, None], 2, axis=1).astype(np.float32)
    r = cc.analyze(sig, _heard(g))
    assert "suppression" in r["issues"]


def test_gate_cuts_the_quiet_part(sig):
    gate = lambda t: np.where((t > 2.52) & (t < 3.8), 0.0, 1.0)
    r = cc.analyze(sig, _heard(_env(sig, gate)))
    assert r["issues"] == ["gate"]


def test_agc_lifts_quiet_and_pumps(sig):
    def agc(t):
        g = np.ones_like(t)
        q = (t >= 2.5) & (t < 3.8)
        g[q] = 10 ** (np.minimum((t[q] - 2.5) * 20, 18) / 20)        # rises while quiet
        d = t >= 3.8
        g[d] = 10 ** (18 * np.exp(-(t[d] - 3.8) / 0.25) / 20)        # then settles back
        return g
    r = cc.analyze(sig, _heard(_env(sig, agc)))
    assert "agc" in r["issues"]
    assert "gate" not in r["issues"]


def test_other_voices_in_the_playback_dont_break_it(sig):
    rng = np.random.default_rng(5)
    h = _heard(sig)
    talk = rng.standard_normal(len(h)) * 0.02 * (np.sin(np.arange(len(h)) / SR * 6) > 0)
    r = cc.analyze(sig, h + talk[:, None].astype(np.float32))
    assert r["issues"] == []


def test_opus_alone_is_not_flagged(sig):
    # if the Mic Test round-trips through the codec, that's not a setting to fix
    from soundboard import codecsim
    if codecsim.available() is None:
        pytest.skip("ffmpeg with libopus not installed")
    for key in ("discord", "discord_low"):
        back = codecsim.roundtrip(sig, codecsim.PROFILES[key])
        assert cc.analyze(sig, back)["issues"] == [], key
