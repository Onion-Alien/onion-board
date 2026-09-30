"""Proximity chat models (soundboard.proxsim) and the game profiles that use them."""
import sys
from pathlib import Path

import numpy as np
import pytest

from soundboard import chatsim, codecsim, proxsim, realproc
from soundboard.codecsim import PROFILES, analyze, pink_noise

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

SR = 48000


def _band_db(y, lo, hi):
    y = np.asarray(y, np.float64)
    y = y.mean(axis=1) if y.ndim == 2 else y
    spec = np.abs(np.fft.rfft(y)) ** 2
    f = np.fft.rfftfreq(len(y), 1 / SR)
    return float(10 * np.log10(spec[(f >= lo) & (f < hi)].sum() + 1e-20))


# ---- falloff

def test_linear_falloff_is_halfway_at_half_range():
    assert proxsim.gain_db("svc", 24) == pytest.approx(-6.02, abs=0.05)
    assert proxsim.gain("svc", 48) == 0.0 and proxsim.gain("svc", 60) == 0.0


def test_unity_log_rolloff_halves_per_doubling():
    assert proxsim.gain_db("unity_3d", 2) == pytest.approx(-6.02, abs=0.05)
    assert proxsim.gain_db("unity_3d", 4) == pytest.approx(-12.04, abs=0.05)


def test_vivox_positional_is_6db_down_and_silent_past_32m():
    assert proxsim.gain_db("vivox_3d", 0.5) == pytest.approx(-6.02, abs=0.05)
    assert proxsim.gain("vivox_3d", 32) == 0.0


def test_ranges_by_variant():
    assert proxsim.gain("pma_voice", 5, "whisper") == 0.0     # whisper reaches 3
    assert proxsim.gain("pma_voice", 5, "shout") > 0.5         # shout reaches 15


def test_radio_ignores_distance():
    assert proxsim.gain("pma_voice", 500, "radio") == 1.0


def test_vrchat_boosts_close_up():
    assert proxsim.gain_db("vrchat", 0.5) == pytest.approx(15.0)


# ---- filters

def test_lethal_occlusion_cutoff_follows_the_decompiled_formula():
    # 2500 / (d / 25), clamped to 900-4000
    assert proxsim.cutoff_hz("lethal", 25, "occluded") == pytest.approx(2500)
    assert proxsim.cutoff_hz("lethal", 5, "occluded") == 4000
    assert proxsim.cutoff_hz("lethal", 200, "occluded") == 900
    assert proxsim.cutoff_hz("lethal", 5) == 10000          # line of sight


def test_walkie_and_radio_take_the_bass_and_the_top_off():
    x = pink_noise(2.0, level=0.3)
    for spec in ("lethal:walkie", "pma_voice:radio"):
        y = proxsim.apply(x, spec)
        assert _band_db(y, 40, 150) < _band_db(x, 40, 150) - 10, spec
        assert _band_db(y, 8000, 16000) < _band_db(x, 8000, 16000) - 15, spec
        assert abs(_band_db(y, 1000, 2000) - _band_db(x, 1000, 2000)) < 4, spec


def test_behind_a_wall_is_duller_than_in_sight():
    x = pink_noise(2.0, level=0.3)
    seen = proxsim.apply(x, "lethal", 10)
    wall = proxsim.apply(x, "lethal", 10, "occluded")
    assert _band_db(wall, 5000, 10000) < _band_db(seen, 5000, 10000) - 6


def test_vent_resonance_peaks_near_2khz():
    x = pink_noise(2.0, level=0.1)
    y = proxsim.apply(x, "crewlink:vent")
    assert _band_db(y, 1900, 2100) - _band_db(x, 1900, 2100) > 10


def test_apply_shape_and_bad_names():
    y = proxsim.apply(pink_noise(0.5), "svc", 10)
    assert y.shape == (SR // 2, 2) and y.dtype == np.float32
    with pytest.raises(ValueError):
        proxsim.apply(pink_noise(0.1), "nope")
    with pytest.raises(ValueError):
        proxsim.apply(pink_noise(0.1), "svc:walkie")


# ---- the profile catalogue

def test_every_profile_is_runnable():
    stages = set(chatsim.STAGES) | set(realproc.STAGES)
    for key, p in PROFILES.items():
        assert set(p.cleanup) <= stages, key
        assert p.confidence in ("measured", "sourced", "estimate"), key
        assert p.rate in (8000, 12000, 16000, 24000, 32000, 48000), key   # Opus' rates
        assert p.frame_ms in (10, 20, 40, 60), key
        if p.proximity:
            proxsim.apply(np.zeros(480, np.float32), p.proximity, 1.0)


@pytest.mark.skipif(codecsim.available() is None, reason="ffmpeg with libopus not installed")
def test_cbr_profile_round_trips():
    x = pink_noise(1.0, level=0.2)
    r = analyze(x, codecsim.roundtrip(x, PROFILES["mumble"]))
    assert abs(r["level_db"]) < 3 and r["bandwidth_hz"] > 15000


@pytest.mark.skipif(codecsim.available() is None, reason="ffmpeg with libopus not installed")
def test_photon_and_steam_share_a_12khz_ceiling():
    x = pink_noise(1.0, level=0.2)
    for key in ("photon", "steam"):
        r = analyze(x, codecsim.roundtrip(x, PROFILES[key]))
        assert 10000 < r["bandwidth_hz"] < 12600, key


# ---- the real-game round trip lines a friend's recording up by its chirp

def test_find_chirps_in_a_noisy_recording():
    import game_roundtrip as gr
    rng = np.random.default_rng(3)
    rec = rng.normal(0, 0.05, 20 * SR).astype(np.float32)
    c = gr.chirp() * 0.3
    for at in (2 * SR, 11 * SR):
        rec[at:at + len(c)] += c
    found = gr.find_chirps(rec, 2, min_gap_s=5)
    assert [abs(f - t) < 48 for f, t in zip(found, (2 * SR, 11 * SR))] == [True, True]
