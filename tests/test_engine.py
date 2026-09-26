"""Engine logic without opening any audio device: streams are stood in by plain
objects, and the callbacks are driven by hand."""
import time
from types import SimpleNamespace

import numpy as np

from soundboard import engine as eng
from soundboard.engine import SR, Engine, is_xrun


class FakeStream:
    def __init__(self):
        self.closed = False

    def stop(self):
        pass

    def close(self):
        self.closed = True


def tone(seconds=0.5):
    t = np.arange(int(seconds * SR)) / SR
    return np.stack([np.sin(2 * np.pi * 440 * t)] * 2, 1).astype(np.float32) * 0.5


def engine_with(*outs):
    e = Engine()
    for o in outs:
        setattr(e, f"{o}_stream", FakeStream())
        e.names[o] = f"fake {o}"
    return e


# ---------------------------------------------------------------- routing

def test_no_outputs_means_no_voice():
    assert Engine().play("a", tone(), 1.0) is None


def test_preview_never_falls_through_to_the_cable():
    e = engine_with("main")                      # cable open, no headphones
    assert e.play("a", tone(), 1.0, preview=True) is None
    e = engine_with("main", "mon")
    v = e.play("a", tone(), 1.0, preview=True)
    assert v is not None and v.outs == {"mon"}
    v = e.play("b", tone(), 1.0)
    assert v.outs == {"main", "mon"}


def test_modes():
    e = engine_with("main")
    a = e.play("a", tone(), 1.0, mode="overlap")
    b = e.play("a", tone(), 1.0, mode="overlap")
    assert a is not b and len(e.voices) == 2
    c = e.play("a", tone(), 1.0, mode="restart")
    assert a.stopping and b.stopping and not c.stopping
    assert e.play("a", tone(), 1.0, mode="toggle") is None     # playing -> stops it
    assert c.stopping


# ---------------------------------------------------------------- rendering

def test_render_plays_data_then_finishes_and_is_pruned():
    e = engine_with("main")
    d = tone(0.02)                               # 960 frames
    v = e.play("a", d, 1.0)
    out = np.zeros((480, 2), np.float32)
    e._main(out, 480)
    assert np.allclose(out, d[:480])
    e._main(out, 480)
    assert v.finished
    e._main(out, 480)
    assert np.all(out == 0)
    e.playing()
    assert v not in e.voices


def test_voices_tuple_is_replaced_not_mutated():
    e = engine_with("main")
    before = e.voices
    e.play("a", tone(), 1.0)
    assert isinstance(e.voices, tuple) and e.voices is not before and before == ()


def test_stop_fades_out_within_one_block():
    e = engine_with("main")
    e.play("a", tone(), 1.0)
    out = np.zeros((480, 2), np.float32)
    e._main(out, 480)
    e.stop("a")
    e._main(out, 480)
    fade = int(eng.FADE_S * SR)
    assert abs(out[0, 0]) > 0 and np.all(out[fade:] == 0)
    assert np.all(np.abs(out[fade - 1]) < 0.01)


def test_loop_wraps_and_pause_holds_position():
    e = engine_with("main")
    d = tone(0.005)                              # 240 frames, shorter than a block
    v = e.play("a", d, 1.0, loop=True)
    out = np.zeros((480, 2), np.float32)
    e._main(out, 480)
    assert np.allclose(out[:240], d) and np.allclose(out[240:], d)
    e.set_paused("a", True)
    e._main(out, 480)                            # fade to silence
    p = v.pos["main"]
    e._main(out, 480)
    assert np.all(out == 0) and v.pos["main"] == p


def test_seek_and_state():
    e = engine_with("main")
    v = e.play("a", tone(1.0), 1.0)
    assert e.seek("a", 0.5)
    assert abs(v.progress() - 0.5) < 0.01
    assert e.state("a") == (v.progress(), False)
    assert e.state("zzz") is None


# ---------------------------------------------------------------- int16 sources

def test_int16_data_renders_scaled_like_float():
    e = engine_with("main")
    d = tone(0.02)
    i16 = np.clip(d * 32767, -32768, 32767).astype(np.int16)
    e.play("f", d, 0.5)
    e.play("i", i16, 0.5, mode="overlap")
    out = np.zeros((480, 2), np.float32)
    e._main(out, 480)
    assert np.allclose(out, d[:480], atol=1e-3)          # 0.5 + 0.5 = the same tone once


def test_int16_data_is_resampled_and_cached_as_int16():
    e = engine_with("main")
    e.rates["main"] = 44100
    i16 = np.clip(tone(0.1) * 32767, -32768, 32767).astype(np.int16)
    out = e.data_for("x", i16, 44100)
    assert out.dtype == np.int16 and abs(len(out) - 4410) <= 2
    assert e._cache_bytes == out.nbytes


def test_resample_cache_evicts_least_recently_used(monkeypatch):
    monkeypatch.setattr(eng, "CACHE_BUDGET", 3 * 4410 * 2 * 4 + 10)   # room for 3 copies
    e = engine_with("main")
    e.rates["main"] = 44100
    arrays = {k: tone(0.1) * (i + 1) / 10 for i, k in enumerate("abcd")}
    for k in "abc":
        e.data_for(k, arrays[k], 44100)
    e.data_for("a", arrays["a"], 44100)                    # touch a: b is now the oldest
    e.data_for("d", arrays["d"], 44100)
    assert set(k for k, _ in e._cache) == {"a", "c", "d"}
    assert e._cache_bytes == sum(v[1].nbytes for v in e._cache.values())


# ---------------------------------------------------------------- cache

def test_resample_cache_is_keyed_on_the_array_object_not_its_address():
    e = engine_with("main")
    e.rates["main"] = 44100
    a = tone(0.1)
    ra = e.data_for("x", a, 44100)
    assert e.data_for("x", a, 44100) is ra       # hit
    b = tone(0.1) * 0.1                          # different content, same shape
    rb = e.data_for("x", b, 44100)
    assert rb is not ra and not np.allclose(rb, ra)
    e.forget("x")
    assert ("x", 44100) not in e._cache


# ---------------------------------------------------------------- guards

def test_callback_exception_is_contained_counted_and_logged(caplog):
    e = engine_with("main")
    e.play("a", tone(), 1.0)
    e.sound_vol = "not a number"                 # will raise inside the mix
    out = np.ones((480, 2), np.float32)
    with caplog.at_level("ERROR"):
        for _ in range(3):
            e._cb_main(out, 480, None, None)
    assert np.all(out == 0)
    assert e.cb_errors["main"] == 3
    assert "main" in e.errors
    assert caplog.text.count("exception in main audio callback") == 1   # logged once


def test_xrun_flags_are_counted():
    flags = SimpleNamespace(output_underflow=True, output_overflow=False,
                            input_underflow=False, input_overflow=False, priming_output=False)
    priming = SimpleNamespace(output_underflow=False, output_overflow=False,
                              input_underflow=False, input_overflow=False, priming_output=True)
    assert is_xrun(flags) and not is_xrun(priming) and not is_xrun(None)
    e = engine_with("main")
    out = np.zeros((480, 2), np.float32)
    e._cb_main(out, 480, None, flags)
    e._cb_main(out, 480, None, priming)
    assert e.xruns["main"] == 1


def test_watchdog_reopens_a_stalled_stream():
    e = engine_with("main")
    s = e.main_stream
    e._last_cb["main"] = time.monotonic()
    assert e.check_streams() == []               # fresh: nothing to do
    e._last_cb["main"] = time.monotonic() - 10
    assert e.check_streams() == ["main"]
    assert s.closed and e.stalls == 1
    assert "main" in e.errors                    # "fake main" can't actually be opened


def test_watchdog_retries_a_failed_device_only_every_few_seconds():
    e = Engine()
    e.names["main"] = "no such device"
    e._last_try["main"] = time.monotonic()
    assert e.check_streams() == []
    e._last_try["main"] = time.monotonic() - eng.RETRY_S - 1
    e.check_streams()
    assert "main" in e.errors and e.main_stream is None
    assert time.monotonic() - e._last_try["main"] < 1


def test_close_marks_voices_done_on_that_output():
    e = engine_with("main", "mon")
    v = e.play("a", tone(), 1.0)
    e._close("mon_stream")
    assert "mon" in v.done and not v.finished
    e._close("main_stream")
    assert v.finished


def test_sounds_only_keeps_the_mic_out_of_the_cable():
    e = Engine()
    e.main_stream = object()             # stands in for an open cable output
    e.ring_main.prefill = 0
    e.mic_enabled = False                # "send my mic" unticked
    e._mic(np.full((480, 1), 0.5, np.float32))
    assert e.level_mic > 0.4             # the mic is still heard (meter, live voice)
    out = np.zeros((480, 2), np.float32)
    e._main(out, 480)
    assert not out.any()                 # but nothing of it reaches the cable
    e.mic_enabled = True
    e._mic(np.full((480, 1), 0.5, np.float32))
    e._main(out, 480)
    assert out.any()


def test_computer_voice_mode_keeps_the_real_voice_out_of_the_cable():
    """Talking as the computer voice: your real voice is heard by the speech
    recognizer (the tap) but none of it reaches the cable, only the spoken lines."""
    from soundboard.voicefx import VoiceChain
    e = Engine()
    e.main_stream = object()             # stands in for an open cable output
    e.ring_main.prefill = 0
    e.voice_chain = chain = VoiceChain()
    heard = []
    chain.tap = lambda m, rate: heard.append(m.copy())
    chain.replace = True                 # what SpeechController.start_live sets
    out = np.zeros((480, 2), np.float32)
    for _ in range(5):
        e._mic(np.full((480, 1), 0.5, np.float32))
        e._main(out, 480)
        assert not out.any()             # the cable gets silence while you talk
    assert heard and heard[0].max() == 0.5   # but the recognizer hears you
    e.play("tts", tone(), 1.0, mode="overlap")
    e._mic(np.full((480, 1), 0.5, np.float32))
    e._main(out, 480)
    assert out.any()                     # the robot voice does go out
