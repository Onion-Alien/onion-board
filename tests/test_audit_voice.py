"""Regression tests for voice-changer, speech-service, add-on install and key-press
fixes (Tone fade-out, Shout at low rates, the computer voice's tail, a bad hello,
a hung install's grandchildren, hiss creep rate, extended keys)."""

import json
import socket
import sys
import time

import numpy as np
import pytest

from soundboard import modules, voicefx
from soundboard.speech import protocol, service

SR = 48000


def _sine(f, secs, rate=SR, amp=0.3):
    t = np.arange(int(rate * secs)) / rate
    return (amp * np.sin(2 * np.pi * f * t)).astype(np.float32)


# --------------------------------------------------------------------------- Tone

def test_tone_fade_to_flat_finishes_and_the_next_setting_takes():
    tone = voicefx.REGISTRY["tone"](SR, {"bass": 12, "presence": 0, "treble": 12})
    block = 256
    x = _sine(100, 0.2)
    for i in range(0, len(x), block):
        tone.run(x[i:i + block], SR)
    tone.set_values({"bass": 0, "presence": 0, "treble": 0})
    tone.run(x[:block], SR)                     # the fade to dry starts
    assert tone.f.f.fading
    for i in range(0, len(x), block):           # ...and runs its course
        tone.run(x[i:i + block], SR)
    assert tone.f.f.idle
    silence = np.zeros(block, np.float32)
    assert np.max(np.abs(tone.run(silence, SR))) < 1e-6
    # a new setting now takes effect (it doesn't sit behind a stranded fade)
    tone.set_values({"bass": 6, "presence": 0, "treble": 0})
    lo = _sine(60, 0.5)
    out = np.concatenate([tone.run(lo[i:i + block], SR)
                          for i in range(0, len(lo), block)])
    tail = slice(len(lo) // 2, None)
    gain_db = 20 * np.log10(np.sqrt(np.mean(out[tail] ** 2)) /
                            np.sqrt(np.mean(lo[tail] ** 2)))
    assert gain_db > 3


# --------------------------------------------------------------------------- Shout

def test_shout_runs_at_8khz():
    rate = 8000
    e = voicefx.REGISTRY["shout"](rate, {"threshold": -40, "drive": 14})
    x = _sine(300, 0.3, rate, amp=0.8)
    y = np.concatenate([e.run(x[i:i + 160], rate) for i in range(0, len(x), 160)])
    assert y.shape == x.shape and np.all(np.isfinite(y))


# --------------------------------------------------------------------------- render

def test_render_keeps_the_end_of_the_line():
    chain = voicefx.VoiceChain()
    chain.configure({"enabled": True,
                     "effects": {"pitch": {"on": True, "semitones": 5}}})
    # there is a delay to flush (render uses fresh effects like this one)
    assert voicefx.REGISTRY["pitch"](SR, {"on": True, "semitones": 5}).latency() > 0.02
    # silence, then a burst right at the end of the clip
    burst = _sine(220, 0.08)
    clip = np.concatenate([np.zeros(SR // 2, np.float32), burst])
    out = chain.render(clip, SR)
    assert out.shape == clip.shape and np.all(np.isfinite(out))
    end = out[-len(burst) // 2:]                # the burst's second half is there
    assert np.sqrt(np.mean(end ** 2)) > 0.05


# --------------------------------------------------------------------------- hello

def _hello_result(payload: bytes):
    a, b = socket.socketpair()
    try:
        a.sendall(protocol._HEAD.pack(protocol.JSON, len(payload)) + payload)
        return service._handshake(b, "tok", 2.0)
    finally:
        a.close()
        b.close()


def test_a_deeply_nested_hello_is_just_rejected():
    deep = b"[" * 4000           # under HELLO_MAX, but past the recursion limit
    assert len(deep) <= service.HELLO_MAX
    assert _hello_result(deep) is None
    assert _hello_result(b"\xff\xfe") is None   # not UTF-8
    good = json.dumps({"type": "hello", "token": "tok"}).encode()
    assert _hello_result(good) == {"type": "hello", "token": "tok"}


# --------------------------------------------------------------------------- install

@pytest.mark.skipif(sys.platform != "win32", reason="job objects are Windows")
def test_a_hung_install_steps_grandchild_is_killed_too(tmp_path, monkeypatch):
    monkeypatch.setattr(modules, "INSTALL_STEP_TIMEOUT_S", 0.5)
    # the step starts a grandchild that keeps its output pipe, then exits itself
    code = ("import subprocess, sys; "
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], "
            "stdout=sys.stdout, stderr=sys.stderr)")
    info = modules.ModuleInfo(id="orphan", name="orphan", version="1", description="",
                              kind="service", path=tmp_path,
                              install_steps=[["{base_python}", "-c", code]])
    lines = []
    t0 = time.monotonic()
    assert not modules.install(info, lines.append)
    assert time.monotonic() - t0 < 15
    assert "internet connection" in lines[-1]


# --------------------------------------------------------------------------- hiss

def test_hiss_estimate_creeps_about_3_db_a_second_at_any_rate():
    for rate in (16000, 48000):
        e = voicefx.REGISTRY["cleanup"](rate, {"gate": 0, "hiss": 0.5})
        e.run(np.zeros(1024, np.float32), rate)        # makes the STFT
        frames_per_s = rate / e.stft.hop
        db_per_s = 10 * np.log10(e.creep) * frames_per_s
        assert db_per_s == pytest.approx(3.0, rel=0.01)


# --------------------------------------------------------------------------- keys

@pytest.mark.skipif(sys.platform != "win32", reason="SendInput is Windows")
def test_win_menu_printscreen_numlock_are_extended_keys():
    from soundboard import winkeys as wk
    for vk in (0x5B, 0x5C, 0x5D, 0x2C, 0x90):
        assert wk.key_input(vk, up=False).ki.dwFlags & wk.KEYEVENTF_EXTENDEDKEY
