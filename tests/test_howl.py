"""The howl stopper: Hear what they hear on speakers squealed (the mic heard itself)."""
from __future__ import annotations

import time

import numpy as np
from conftest import said
from test_engine import engine_with
from test_mainwindow import window  # noqa: F401  (the real MainWindow)

from soundboard import howl
from soundboard.howl import HowlGuard

SR = 48000
T = np.arange(SR * 3) / SR
RNG = np.random.default_rng(1)


def first_howl(sig, rate=SR, block=480):
    """Seconds into `sig` the guard first says it's howling, or None."""
    g = HowlGuard(rate)
    for i in range(0, len(sig), block):
        if g.feed(sig[i:i + block]):
            return i / rate
    return None


def voice(f0):
    """A voiced sound: a harmonic series on the pitch track `f0` (Hz per sample)."""
    ph = 2 * np.pi * np.cumsum(f0) / SR
    return sum(np.sin(k * ph) / k for k in range(1, 15)) / 3


def test_a_growing_squeal_is_caught_within_a_second_or_so():
    squeal = np.minimum(0.02 * np.exp(T * 3), 0.7) * np.sin(2 * np.pi * 1730 * T)
    at = first_howl(squeal + 0.003 * RNG.standard_normal(len(T)))
    assert at is not None and at < 1.5


def test_a_squeal_over_talking_is_caught():
    talk = 0.08 * voice(150 + 40 * np.sin(2 * np.pi * 1.3 * T))
    assert first_howl(0.6 * np.sin(2 * np.pi * 2400 * T) + talk) is not None


def test_at_a_low_mic_rate_too():
    t = np.arange(16000 * 2) / 16000
    assert first_howl(0.5 * np.sin(2 * np.pi * 900 * t), 16000, 160) is not None


def test_a_saturated_loop_without_a_clear_note_is_caught():
    assert first_howl(np.clip(3 * RNG.standard_normal(len(T)), -1, 1)) is not None


def test_talking_singing_and_shouting_are_left_alone():
    pitch = 150 + 40 * np.sin(2 * np.pi * 1.3 * T)
    assert first_howl(0.4 * voice(pitch)) is None
    assert first_howl(0.5 * voice(440 * (1 + 0.015 * np.sin(2 * np.pi * 5.5 * T)))) is None
    gaps = (np.sin(2 * np.pi * 4 * T) > -0.3).astype(float)   # syllables
    assert first_howl(np.clip(4.5 * voice(pitch) * gaps, -1, 1)) is None
    whistle = 1500 * (1 + 0.02 * np.sin(2 * np.pi * 5 * T))
    assert first_howl(0.5 * np.sin(2 * np.pi * np.cumsum(whistle) / SR)) is None


def test_quiet_notes_are_left_alone():
    assert first_howl(0.05 * np.sin(2 * np.pi * 1000 * T)) is None


def test_speakers_are_told_from_headsets_that_say_they_are_speakers():
    """Windows' form factors from a real PC: the USB headset reports 1 (speakers),
    the screens 9 (audio over HDMI). PortAudio's MME names stop at 31 characters."""
    ffs = {"Headphones  (Example Gaming Headset)": 1,
           "Speakers (Realtek High Definition Audio)": 1,
           "1 - Monitor (HD Audio Device)": 9,
           "Speakers (Example Headset)": 1,
           "Headphones (Realtek Audio)": 3}
    assert howl.is_speaker("Speakers (Realtek High Definiti", ffs)
    assert howl.is_speaker("Speakers (Realtek High Definition Audio)", ffs)
    assert howl.is_speaker("1 - Monitor (HD Audio Device)", ffs)
    assert not howl.is_speaker("Headphones  (Example Gaming Hea", ffs)
    assert not howl.is_speaker("Speakers (Example Headset)", ffs)
    assert not howl.is_speaker("Headphones (Realtek Audio)", ffs)
    assert not howl.is_speaker("Unknown device", ffs)
    assert not howl.is_speaker(None, ffs)
    assert not howl.is_speaker("Speakers (Realtek High Definition Audio)", {})


def test_the_engine_stops_playing_the_mic_back_once_it_squeals():
    e = engine_with("main", "mon")
    e.mic_check = True
    t = np.arange(480) / SR
    out = np.zeros((480, 2), np.float32)
    for i in range(200):                          # 2 s of a steady squeal
        block = (0.6 * np.sin(2 * np.pi * 1730 * (t + i * 480 / SR)))[:, None]
        e._mic(block.astype(np.float32))
        e._mon(out, 480)
        if not e.mic_check:
            break
    assert not e.mic_check and e.howl_stopped
    assert i * 480 / SR < 1.5
    e.ring_mon.prefill = 0
    e._mic(np.zeros((480, 1), np.float32))
    e._mon(out, 480)
    assert np.abs(out).max() < 1e-3               # the mic is no longer played back


def test_the_engine_never_stops_for_talking():
    e = engine_with("main", "mon")
    e.mic_check = True
    talk = 0.4 * voice(150 + 40 * np.sin(2 * np.pi * 1.3 * T))
    for i in range(0, len(talk), 480):
        e._mic(talk[i:i + 480, None].astype(np.float32))
    assert e.mic_check and not e.howl_stopped


def test_the_window_unticks_the_switch_and_says_why(window):  # noqa: F811
    window.btn_check.setChecked(True)
    window.engine.mic_check = False               # what the audio thread did
    window.engine.howl_stopped = True
    window.tickctl.tick()
    assert not window.btn_check.isChecked() and not window.engine.howl_stopped
    assert "started to squeal" in said(window)


def test_turning_it_on_with_speakers_warns(window, monkeypatch, qapp):  # noqa: F811
    from soundboard import appaudio
    monkeypatch.setattr(appaudio, "output_form_factors", lambda: {"Speakers (Realtek)": 1})
    window.engine.names["mon"] = "Speakers (Realtek)"
    window.btn_check.setChecked(True)
    for _ in range(200):
        qapp.processEvents()
        if "looks like speakers" in said(window):
            break
        time.sleep(0.01)
    assert "looks like speakers" in said(window)
    window.btn_check.setChecked(False)
