import numpy as np

from soundboard.testcheck import analyze, summary_html

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


def test_sounds_only_summary_doesnt_ask_for_the_voice():
    r = {"talked": False, "voice_in": False, "sounds_in": True, "advice": ""}
    html = summary_html(r, None, mic_sent=False)
    assert "Sounds only" in html and "Didn't hear you talk" not in html


def _buzz(seconds=6.0, hz=100.0):
    """A robot voice: a fixed-pitch buzz (periodic, so a plain correlation peaks every
    10 ms), shaped by the talking bursts of _mic()."""
    t = np.arange(int(seconds * RATE)) / RATE
    saw = sum(np.sin(2 * np.pi * hz * k * t) / k for k in range(1, 40)) * 0.1
    env = (np.abs(_mic(seconds)) > 0).astype(np.float64)
    return (saw * env).astype(np.float32)


def test_periodic_voice_changer_output_is_found():
    sent = _buzz()
    delay = int(0.05 * RATE)
    out = np.zeros_like(sent)
    out[delay:] = sent[:-delay]
    out = np.stack([out + _sound()] * 2, 1)
    r = analyze(out, RATE, np.stack([_mic(), sent], 1), RATE, sound_vol=1.0)
    assert r["talked"] and r["voice_in"] and r["sounds_in"]


def test_raw_mic_decides_talked_and_the_sent_one_is_looked_for():
    """(n, 2) = raw mic, mic as sent. The output holds the sent one, not the raw."""
    raw, sent = _mic(seed=1), _mic(seed=2)
    out = np.stack([0.5 * sent + _sound()] * 2, 1)
    assert analyze(out, RATE, np.stack([raw, sent], 1), RATE, 1.0)["voice_in"]
    assert not analyze(out, RATE, raw, RATE, 1.0)["voice_in"]


def test_muted_real_voice_is_explained_not_blamed_on_send():
    mic = np.stack([_mic(), np.zeros(6 * RATE, np.float32)], 1)
    r = analyze(np.stack([_sound()] * 2, 1), RATE, mic, RATE, sound_vol=1.0)
    assert r["talked"] and r["replaced"] and not r["voice_in"] and r["sounds_in"]
    html = summary_html(r, None)
    assert "Computer voice" in html and "NOT reaching" not in html
