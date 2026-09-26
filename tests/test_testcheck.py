import numpy as np

from testcheck import analyze, summary_html

RATE = 48000


def _mic(seconds=6.0, seed=0):
    """Speech-like: bursts of band-limited noise with gaps."""
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    x = rng.standard_normal(n) * 0.1
    env = np.zeros(n)
    for start in range(RATE // 2, n, RATE):           # 0.5 s bursts every second
        env[start:start + RATE // 2] = 1
    return (x * env).astype(np.float32)


def _sound(seconds=6.0):
    t = np.arange(int(seconds * RATE)) / RATE
    return (0.2 * np.sin(2 * np.pi * 330 * t)).astype(np.float32)


def test_voice_and_sound_both_detected():
    mic = _mic()
    delay = int(0.1 * RATE)
    voice = np.zeros_like(mic)
    voice[delay:] = 0.5 * mic[:-delay]
    out = np.stack([voice + _sound()] * 2, 1)
    r = analyze(out, RATE, mic, RATE, sound_vol=1.0)
    assert r["talked"] and r["voice_in"] and r["sounds_in"]
    assert "diff" in r


def test_voice_missing_from_output_is_reported():
    mic = _mic()
    out = np.stack([_sound()] * 2, 1)
    r = analyze(out, RATE, mic, RATE, sound_vol=1.0)
    assert r["talked"] and not r["voice_in"]
    assert "NOT reaching" in summary_html(r, None)


def test_silent_mic_means_did_not_talk():
    mic = np.zeros(6 * RATE, np.float32)
    out = np.stack([_sound()] * 2, 1)
    r = analyze(out, RATE, mic, RATE, sound_vol=1.0)
    assert not r["talked"] and r["sounds_in"]


def test_no_mic_recording_only_checks_sounds():
    out = np.stack([_sound()] * 2, 1)
    r = analyze(out, RATE, None, RATE, sound_vol=1.0)
    assert r["sounds_in"] and not r["talked"]


def test_loud_sounds_produce_advice():
    mic = _mic()
    voice = 0.2 * mic                            # sounds ~28 dB louder than the voice
    out = np.stack([voice + 4 * _sound()] * 2, 1)
    r = analyze(out, RATE, mic, RATE, sound_vol=1.0)
    assert r["voice_in"] and r["diff"] > 20 and "drown" in r["advice"]
