"""The voice-chat processing simulation behaves like the real thing does to music,
the Discord check names each kind of it, and, through the real codec, the send
stage keeps the listener's decoder from clipping and mono from cancelling."""
import numpy as np
import pytest

from soundboard import chatcheck, chatsim, codecsim
from soundboard.engine import soft_limit
from soundboard.sendfx import Limiter, SmartMono

SR = 48000
needs_ffmpeg = pytest.mark.skipif(codecsim.available() is None,
                                  reason="ffmpeg with libopus not installed")


def _db(x):
    return 20 * np.log10(max(float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))), 1e-12))


def _heard(y, delay_s=0.4, gain=0.7):
    d = int(delay_s * SR)
    out = np.zeros((len(y) + d + SR // 2, 2), np.float32)
    out[d:d + len(y)] = y * gain
    return out


@pytest.fixture(scope="module")
def sig():
    return chatcheck.test_signal()


# ---------------------------------------------------------------- the simulation

def test_suppression_pulls_steady_music_down():
    x = codecsim.multitone(4.0, level=0.3)
    y = chatsim.process(x, ("suppress",))
    assert _db(y[3 * SR:]) < _db(x[3 * SR:]) - 10


def test_gate_cuts_quiet_parts_and_keeps_loud():
    x = codecsim.pink_noise(2.0, level=0.3)
    x[SR:] *= 0.003                                   # a fade tail at about -60 dBFS
    y = chatsim.process(x, ("gate",))
    assert abs(_db(y[:SR // 2]) - _db(x[:SR // 2])) < 0.5
    assert _db(y[int(1.5 * SR):]) < -100


def test_agc_lifts_a_quiet_stretch():
    x = codecsim.pink_noise(6.0, level=0.03)
    y = chatsim.process(x, ("agc",))
    assert _db(y[5 * SR:]) > _db(x[5 * SR:]) + 6


# ---------------------------------------------------------------- the check names it

@pytest.mark.parametrize("stages, want", [
    ((), []),
    (("suppress",), ["suppression"]),
    (("agc",), ["agc"]),
    (("gate",), ["gate"]),
    (chatsim.STAGES, ["suppression", "gate"]),     # Studio fixes suppression + AGC together
])
def test_check_names_what_the_simulation_does(sig, stages, want):
    assert chatcheck.analyze(sig, _heard(chatsim.process(sig, stages)))["issues"] == want


# ---------------------------------------------------------------- through the codec

def _brick_walled(seconds=4.0):
    """A modern loud master with a voice on top: what used to clip on the other end."""
    m = codecsim.pink_noise(seconds, level=1.0, seed=1)[:, 0].astype(np.float64)
    t = np.arange(len(m)) / SR
    kick = np.zeros(len(m))
    for k0 in np.arange(0, seconds, 0.5):
        i = int(k0 * SR)
        tt = t[i:] - k0
        kick[i:] += np.sin(2 * np.pi * (50 + 80 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 8)
    x = np.tanh((m * 0.6 + kick * 0.9) * 2.5)
    x /= np.abs(x).max()
    return (np.repeat(x[:, None], 2, 1) + codecsim.speech_like(seconds, level=0.4)).astype(
        np.float32)


def _send(x):
    lim, mono = Limiter(SR), SmartMono(SR)
    return np.concatenate([lim.process(mono.process(x[i:i + 480])) for i in range(0, len(x), 480)])


@needs_ffmpeg
def test_send_stage_keeps_the_listeners_decoder_from_clipping():
    x = _brick_walled()
    # a 48 kHz game stack with no capture high-pass (Vivox's takes the kick's sub-bass,
    # and with it most of the overshoot)
    p = codecsim.PROFILES["eos"]
    old = codecsim.roundtrip(soft_limit(x.copy()), p)
    new = codecsim.roundtrip(_send(x), p)
    clip = lambda y: float(np.mean(np.abs(y) >= 0.999))   # noqa: E731
    assert clip(old) > 0.001 and clip(new) < clip(old) / 5


@needs_ffmpeg
def test_mono_survives_the_codec_where_a_plain_average_cancels():
    t = np.arange(3 * SR) / SR
    x = np.stack([np.sin(2 * np.pi * 150 * t), -np.sin(2 * np.pi * 150 * t)], 1) * 0.3
    x = x.astype(np.float32)
    p = codecsim.PROFILES["discord"]
    plain = codecsim.roundtrip(x, p)          # the codec's own mono capture averages
    ours = codecsim.roundtrip(_send(x), p)
    assert _db(plain[SR:]) < -40 and _db(ours[SR:]) > _db(x[SR:]) - 3


def test_spectral_distance_sees_noise_the_band_energy_misses():
    x = codecsim.pink_noise(2.0, level=0.3)
    rng = np.random.default_rng(3)
    # the same energy per band over the whole clip, but different frame by frame:
    # 20 ms frames shuffled around
    y = x.copy()
    n = int(0.02 * SR)
    idx = rng.permutation(len(x) // n)
    y[: len(idx) * n] = x[: len(idx) * n].reshape(len(idx), n, 2)[idx].reshape(-1, 2)
    assert codecsim.spectral_distance_db(x[:, 0], x[:, 0]) == 0.0
    assert codecsim.spectral_distance_db(x[:, 0].astype(float), y[:, 0].astype(float)) > 1.0
