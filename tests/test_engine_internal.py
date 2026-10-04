"""The engine's own playback (test recording, cues, setup tune, previews) and the
Record-6s test with the voice changer on. No devices: streams are stand-ins and
the callbacks are driven by hand."""
import numpy as np
import pytest

from soundboard.engine import SR, Engine, is_fixed
from soundboard.testcheck import analyze, summary_html
from soundboard.voicefx import VoiceChain


class FakeStream:
    def stop(self):
        pass

    def close(self):
        pass


def engine_with(*outs):
    e = Engine()
    for o in outs:
        setattr(e, f"{o}_stream", FakeStream())
        e.names[o] = f"fake {o}"
    return e


def sine(hz=440.0, seconds=1.0, amp=0.3):
    t = np.arange(int(seconds * SR)) / SR
    return np.stack([np.sin(2 * np.pi * hz * t)] * 2, 1).astype(np.float32) * amp


def peak_hz(x):
    m = x[len(x) // 4: 3 * len(x) // 4, 0].astype(np.float64)
    spec = np.abs(np.fft.rfft(m * np.hanning(len(m))))
    return float(np.argmax(spec) * SR / len(m))


# ---------------------------------------------------------------- live speed / pitch

def test_the_apps_own_voices_are_fixed():
    for sid in ("__test__", "__cue__", "__setup__", "abc:preview", "abc~fx:preview"):
        assert is_fixed(sid)
    for sid in ("abc", "tts", "preview", "abc:previewx"):
        assert not is_fixed(sid)


@pytest.mark.parametrize("sid", ["__test__", "__cue__", "__setup__", "abc~fx:preview"])
def test_live_speed_leaves_the_apps_own_playback_alone(sid):
    """The 6 s "what they heard" playback took 3 s at 2x live speed; cues, the setup
    tune and the Edit dialog's preview were sped up (and pitch-shifted) too."""
    e = engine_with("main", "mon")
    e.sound_speed, e.sound_pitch = 2.0, 5.0
    v = e.play(sid, sine(440, 1.0), 1.0, preview=True)
    out = np.zeros((480, 2), np.float32)
    blocks = []
    while not v.finished and len(blocks) < 500:
        e._mon(out, 480)
        blocks.append(out.copy())
    assert abs(len(blocks) * 480 / SR - 1.0) < 0.02        # 1 s, not 0.5 s
    y = np.concatenate(blocks)
    assert abs(peak_hz(y) - 440) < 10                       # no pitch shift either


def test_live_speed_still_applies_to_sounds_playing_alongside():
    e = engine_with("main", "mon")
    e.sound_speed, e.sound_keep_pitch = 2.0, False
    snd = e.play("a", sine(440, 1.0), 1.0)
    cue = e.play("__cue__", sine(660, 1.0), 1.0, preview=True)
    out = np.zeros((480, 2), np.float32)
    for _ in range(10):
        e._mon(out, 480)
    assert abs(snd.pos["mon"] - 9600) < 2 and cue.pos["mon"] == 4800


def test_live_effects_shape_the_sounds_but_not_the_apps_own_playback():
    def level(sid, fx):
        e = engine_with("main", "mon")
        e.sound_fx = fx
        e.play(sid, sine(8000, 0.5), 1.0, preview=sid.startswith("__"))
        out = np.zeros((480, 2), np.float32)
        blocks = []
        for _ in range(40):
            e._mon(out, 480)
            blocks.append(out.copy())
        y = np.concatenate(blocks)[4800:]
        return float(np.sqrt(np.mean(y ** 2))), e
    dry, _ = level("a", {})
    muffled, e = level("a", {"muffle": 1.0})
    assert muffled < 0.1 * dry and "mon" in e._sfx
    cue, _ = level("__cue__", {"muffle": 1.0})
    assert cue > 0.8 * dry


# ---------------------------------------------------------------- Record-6s test

def _speech(seconds=7.0, seed=0):
    """Voiced, gliding pitch in syllables."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = np.arange(n) / SR
    f = 120 + 40 * np.sin(2 * np.pi * 0.7 * t) + 15 * np.sin(2 * np.pi * 2.3 * t)
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = sum(np.sin(k * ph) / k for k in range(1, 20)) * 0.05 + rng.standard_normal(n) * 0.01
    return (x * ((t % 0.5) < 0.3)).astype(np.float32)


def _record_test(effects=None, replace=False):
    e = engine_with("main", "mic")
    if effects or replace:
        ch = VoiceChain()
        ch.configure({"enabled": True, "effects": effects or {}})
        ch.replace = replace
        e.voice_chain = ch
    mic = _speech()
    e.start_test_record(6.0)
    out = np.zeros((480, 2), np.float32)
    i = 0
    while e.rec_done is None:
        e._mic(mic[i:i + 480, None])
        i += 480
        e._main(out, 480)
    data, rate = e.rec_done
    m = e.take_mic_recording()
    return analyze(data, rate, m[0], m[1], 1.0), m[0]


def test_test_recording_keeps_the_raw_and_the_sent_mic():
    _r, m = _record_test({"pitch": {"on": True, "semitones": 5, "mix": 1}})
    assert m.ndim == 2 and m.shape[1] == 2
    assert not np.allclose(m[:, 0], m[:, 1])              # raw vs changed


@pytest.mark.parametrize("effects", [
    None,
    {"pitch": {"on": True, "semitones": 5, "mix": 1}},
    {"robot": {"on": True}},
    {"radio": {"on": True}},
])
def test_record_test_finds_the_voice_through_the_voice_changer(effects):
    """It correlated the output with the raw mic, so a changed voice read as "Your
    voice is NOT reaching the output"."""
    r, _m = _record_test(effects)
    assert r["talked"] and r["voice_in"] and not r["replaced"]
    assert "VOICE is in the output" in summary_html(r, None)


def test_record_test_with_the_computer_voice_muting_the_mic():
    r, _m = _record_test(replace=True)
    assert r["talked"] and not r["voice_in"] and r["replaced"]
    html = summary_html(r, None)
    assert "Computer voice" in html and "send" not in html
