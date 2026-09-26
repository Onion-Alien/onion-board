import json

import numpy as np

import library
from library import SR, Config, SoundMeta, level_gain, trim_silence


def sine(db, seconds=2.0, hz=440):
    t = np.arange(int(seconds * SR)) / SR
    a = 10 ** (db / 20)
    return np.stack([np.sin(2 * np.pi * hz * t) * a] * 2, 1).astype(np.float32)


# ---------------------------------------------------------------- level_gain

def test_silence_gets_unity_gain():
    assert level_gain(np.zeros((SR, 2), np.float32)) == 1.0
    assert level_gain(np.zeros((0, 2), np.float32)) == 1.0


def test_quiet_sound_is_brought_up_to_target():
    x = sine(-25)                    # -28 dB RMS: within the 6x gain clamp of the target
    g = level_gain(x)
    rms = np.sqrt(((x * g).mean(axis=1) ** 2).mean())
    assert abs(20 * np.log10(rms) - library.TARGET_RMS_DB) < 1.0


def test_loud_sound_is_brought_down_and_gain_is_clamped():
    assert level_gain(sine(-1)) < 1.0
    assert 0.1 <= level_gain(sine(-90)) <= 6.0


def test_leading_silence_does_not_skew_the_level():
    x = sine(-30, seconds=1.0)
    padded = np.concatenate([np.zeros((5 * SR, 2), np.float32), x])
    assert abs(level_gain(x) - level_gain(padded)) / level_gain(x) < 0.05


# ---------------------------------------------------------------- trim_silence

def test_trim_keeps_a_small_pad_around_the_sound():
    x = np.zeros((SR, 2), np.float32)
    x[20000:30000] = 0.5
    y = trim_silence(x, pad_s=0.05)
    pad = int(0.05 * SR)
    assert len(y) == 10000 + 2 * pad - 1


def test_trim_all_silence_is_empty():
    assert len(trim_silence(np.zeros((1000, 2), np.float32))) == 0


# ---------------------------------------------------------------- Config

def test_config_round_trip(app_dir):
    c = Config(sound_vol=1.5, stop_hotkey="ctrl+alt+x", latency="high",
               sounds=[SoundMeta(id="abc", name="Boom", file="x.wav", hotkey="f5")])
    c.save()
    assert not (app_dir / "config.tmp").exists()          # atomic replace cleaned up
    d = Config.load()
    assert d.sound_vol == 1.5 and d.stop_hotkey == "ctrl+alt+x" and d.latency == "high"
    assert d.sounds[0] == c.sounds[0]


def test_unknown_and_missing_fields_are_tolerated(app_dir):
    raw = {"sound_vol": 0.5, "future_setting": 1,
           "sounds": [{"id": "a", "name": "n", "file": "f", "future_field": True}]}
    library.CONFIG_PATH.write_text(json.dumps(raw), encoding="utf-8")
    c = Config.load()
    assert c.sound_vol == 0.5
    assert c.mon_vol == 0.7                                  # default kept
    assert c.sounds[0].id == "a" and c.sounds[0].volume == 1.0


def test_missing_config_gives_defaults(app_dir):
    assert Config.load() == Config()


def test_corrupt_config_gives_defaults_and_is_logged(app_dir, caplog):
    library.CONFIG_PATH.write_text("{not json", encoding="utf-8")
    with caplog.at_level("ERROR"):
        c = Config.load()
    assert c == Config()
    assert "unreadable" in caplog.text
