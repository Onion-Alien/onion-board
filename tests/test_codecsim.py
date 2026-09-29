import numpy as np
import pytest

from soundboard import codecsim
from soundboard.codecsim import (PROFILES, align, analyze, mono_loss_db, multitone, pink_noise,
                                 roundtrip, speech_like)

RATE = 48000
FF = codecsim.available()
needs_ffmpeg = pytest.mark.skipif(FF is None, reason="ffmpeg with libopus not installed")


def _tone(hz, seconds=2.0, level=0.2):
    t = np.arange(int(seconds * RATE)) / RATE
    x = (level * np.sin(2 * np.pi * hz * t)).astype(np.float32)
    return np.repeat(x[:, None], 2, axis=1)


# ---- analysis, no codec needed

def test_identity_is_transparent():
    x = pink_noise(2.0)
    r = analyze(x, x)
    assert abs(r["level_db"]) < 0.01
    assert r["lag"] == 0
    assert r["snr_db"] > 60
    assert r["bandwidth_hz"] >= 20000
    assert all(d is not None and abs(d) < 0.01 for _, _, d in r["bands"])


def test_align_finds_codec_delay():
    x = pink_noise(2.0)
    delay = 1234
    back = np.concatenate([np.zeros((delay, 2), np.float32), x * 0.5])
    o, b, lag = align(x, back)
    assert lag == delay
    assert len(o) == len(b) == len(x)
    r = analyze(x, back)
    assert abs(r["level_db"] - (-6.02)) < 0.1
    assert r["snr_db"] > 60          # gain-matched: a quieter copy is still a perfect copy


def test_lowpassed_copy_reports_ceiling_and_band_loss():
    x = pink_noise(2.0)
    spec = np.fft.rfft(x[:, 0])
    f = np.fft.rfftfreq(len(x), 1 / RATE)
    spec[f > 8000] = 0
    y = np.fft.irfft(spec, len(x)).astype(np.float32)
    back = np.repeat(y[:, None], 2, axis=1)
    r = analyze(x, back)
    assert 7500 <= r["bandwidth_hz"] <= 8250
    bands = {lo: d for lo, _, d in r["bands"]}
    assert abs(bands[1000]) < 0.5           # 1–3 kHz untouched
    assert bands[10000] < -40                # 10–14 kHz gone


def test_multitone_puts_a_tone_in_every_band():
    x = multitone(1.0)
    spec = np.abs(np.fft.rfft(x[:, 0]))
    f = np.fft.rfftfreq(len(x), 1 / RATE)
    for lo, hi in codecsim.BANDS:
        m = (f >= lo) & (f < hi)
        assert spec[m].max() > 0.2 * spec.max()


def test_mono_loss():
    same = pink_noise(1.0)
    assert abs(mono_loss_db(same)) < 0.01
    flipped = same.copy()
    flipped[:, 1] *= -1
    assert mono_loss_db(flipped) <= -59
    rng = np.random.default_rng(0)
    unrelated = rng.standard_normal((RATE, 2)).astype(np.float32)
    assert -3.5 < mono_loss_db(unrelated) < -2.5


# ---- the real thing

@needs_ffmpeg
def test_discord_keeps_a_1khz_tone():
    x = _tone(1000)
    back = roundtrip(x, PROFILES["discord"], FF)
    r = analyze(x, back)
    assert abs(r["level_db"]) < 1.5
    assert r["snr_db"] > 15


@needs_ffmpeg
def test_steam_ceiling_is_12khz():
    x = pink_noise(3.0)
    r = analyze(x, roundtrip(x, PROFILES["steam"], FF))
    assert 10500 <= r["bandwidth_hz"] <= 12500
    bands = {lo: d for lo, _, d in r["bands"]}
    assert bands[14000] < -30
    assert bands[1000] > -3


@needs_ffmpeg
def test_multitone_ceiling_not_fooled_by_codec_noise():
    """A tone's spectral leakage must not count as input energy above the ceiling,
    or Opus' noise filling up there reads as 'carried'."""
    x = multitone(3.0)
    r = analyze(x, roundtrip(x, PROFILES["steam"], FF))
    assert r["bandwidth_hz"] <= 12500


@needs_ffmpeg
def test_steam_drops_a_15khz_tone_discord_keeps_it():
    x = _tone(15000)
    steam = analyze(x, roundtrip(x, PROFILES["steam"], FF))
    discord = analyze(x, roundtrip(x, PROFILES["discord"], FF))
    assert steam["level_db"] < -20
    assert discord["level_db"] > -6


@needs_ffmpeg
def test_speech_like_survives_low_bitrate():
    x = speech_like(3.0)
    r = analyze(x, roundtrip(x, PROFILES["discord_low"], FF))
    assert abs(r["level_db"]) < 3
    bands = {lo: d for lo, _, d in r["bands"]}
    assert bands[300] is not None and bands[300] > -3


@needs_ffmpeg
def test_stereo_in_gives_stereo_shape_out():
    x = pink_noise(1.0)
    back = roundtrip(x, PROFILES["discord"], FF)
    assert back.ndim == 2 and back.shape[1] == 2 and back.dtype == np.float32
    assert abs(len(back) - len(x)) < RATE // 4


def _rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(np.square(x))) + 1e-12)


def test_discord_highpass_matches_the_real_call_measurement():
    # measured through real Discord: -33 dB at 70 Hz, -19 at 80, -6 at 90, flat from 100
    hp = PROFILES["discord"].highpass_hz
    assert hp
    for hz, want in ((70, -33.1), (80, -18.9), (90, -5.8), (150, -0.9), (1000, -0.4)):
        x = _tone(hz)
        y = codecsim.highpass(x, hp)
        cut = RATE // 2   # past the filter's settling
        got = _rms_db(y[cut:, 0]) - _rms_db(x[cut:, 0])
        assert abs(got - want) < 2.0, (hz, got, want)


def test_highpass_is_only_on_the_measured_profiles():
    assert all(PROFILES[k].highpass_hz for k in ("discord", "discord_low", "discord_128"))
    assert not any(PROFILES[k].highpass_hz for k in ("steam", "vivox", "vivox_siren7"))


@needs_ffmpeg
def test_discord_roundtrip_drops_sub_bass_keeps_bass():
    low = roundtrip(_tone(60, level=0.3), PROFILES["discord"], FF)
    mid = roundtrip(_tone(200, level=0.3), PROFILES["discord"], FF)
    assert _rms_db(low[RATE // 2:]) - _rms_db(_tone(60, level=0.3)) < -20
    assert abs(_rms_db(mid[RATE // 2:-RATE // 4]) - _rms_db(_tone(200, level=0.3))) < 3
