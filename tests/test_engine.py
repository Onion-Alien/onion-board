"""Engine logic without opening any audio device: streams are stood in by plain
objects, and the callbacks are driven by hand."""
import time
from types import SimpleNamespace

import numpy as np
import pytest

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


def engine_with(*outs, send_stage=False):
    """An engine with fake output streams. The send stage (limiter delay, mono
    crossovers) is off unless asked for, so render tests can compare exact samples;
    test_sendfx covers it."""
    e = Engine()
    e.send_mono = e.limiter_on = send_stage
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


def test_solo_mode_stops_the_other_sounds_but_not_previews_or_cues():
    e = engine_with("main", "mon")
    other = e.play("b", tone(), 1.0)
    prev = e.play("c:preview", tone(), 1.0, preview=True)
    cue = e.play("__cue__", tone(), 1.0, preview=True)
    first = e.play("a", tone(), 1.0, mode="solo")
    assert other.stopping and not prev.stopping and not cue.stopping
    again = e.play("a", tone(), 1.0, mode="solo")              # restarts itself
    assert first.stopping and not again.stopping


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


# ---------------------------------------------------------------- aux sources (captured programs)

def test_aux_source_goes_to_the_cable_and_only_to_headphones_when_asked():
    e = engine_with("main", "mon")
    src = e.add_aux(("app", "music.exe"))
    src.ring_main.prefill = src.ring_mon.prefill = 0
    e.feed_aux(src, np.full((480, 2), 0.25, np.float32))
    out = np.zeros((480, 2), np.float32)
    e._main(out, 480)
    assert out.any() and src.level > 0.2                    # live by default: others hear it
    e._mon(out, 480)
    assert not out.any()                                     # not in your headphones by default
    src.monitor = True
    e.feed_aux(src, np.full((480, 2), 0.25, np.float32))
    e._mon(out, 480)
    assert out.any()
    src.live = False
    e.feed_aux(src, np.full((480, 2), 0.25, np.float32))
    out.fill(0)
    e._main(out, 480)
    assert not out.any()


def test_aux_source_volume_on_air_and_removal():
    e = engine_with("main")
    src = e.add_aux("a")
    src.ring_main.prefill = 0
    src.vol = 0.5
    assert not e.aux_on_air()
    e.feed_aux(src, np.full((480, 2), 0.5, np.float32))
    assert e.aux_on_air()
    out = np.zeros((480, 2), np.float32)
    e._main(out, 480)
    assert abs(float(out[:, 0].max()) - 0.25) < 0.02
    e.add_aux("a")                                           # same key replaces, never doubles
    assert [a.key for a in e.aux] == ["a"]
    e.remove_aux("a")
    assert e.aux == () and not e.aux_on_air()
    e._main(out, 480)                                        # nothing to read: silence
    assert not out.any()


def test_a_sent_program_gets_its_bass_level_back_like_a_sound():
    """A mode's low cut takes a bass-heavy song's sub-bass: a pad is given that level
    back, and a program sent from the Apps tab now is too."""
    from soundboard import destination
    e = engine_with("main")
    e.dest = destination.BUILTIN_BY_KEY["discord"]
    src = e.add_aux(("app", "music.exe"))
    t = np.arange(SR * 3) / SR
    song = (0.4 * np.sin(2 * np.pi * 45 * t) + 0.1 * np.sin(2 * np.pi * 1000 * t))
    song = np.stack([song, song], 1).astype(np.float32)
    for i in range(0, len(song), 480):
        e.feed_aux(src, song[i:i + 480])
    pad = destination.makeup(destination.cut_shares(song, SR)[e.dest.lowcut])
    assert pad > 2.0                                       # mostly sub-bass: a big make-up
    for _ in range(100):                                   # glides there, never steps
        g = src.gain("main", e.dest.lowcut)
    assert g == pytest.approx(pad, rel=0.05)
    assert src.gain("main", 0) < g                         # no mode, no make-up
    e.dest = None
    out = np.zeros((480, 2), np.float32)
    e._main(out, 480)                                      # and none is used without one


# ---------------------------------------------------------------- audit fixes

def test_cancelled_test_record_never_finishes():
    e = engine_with("main")
    e.start_test_record(1.0)
    assert e.recording
    e.cancel_test_record()
    assert not e.recording
    out = np.zeros((480, 2), np.float32)
    e._main(out, 480)                            # a block after cancelling...
    assert e.rec_done is None                    # ...is not taken for a finished test


def test_test_record_finishes_after_its_length():
    e = engine_with("main")
    e.start_test_record(0.02)                    # 960 frames
    out = np.zeros((480, 2), np.float32)
    e._main(out, 480)
    assert e.recording and e.rec_done is None
    e._main(out, 480)
    assert not e.recording and e.rec_done[0].shape == (960, 2)


def test_callback_errors_are_reported_again_after_a_reopen(caplog):
    e = engine_with("main")
    e._last_cb["main"] = time.monotonic()
    with caplog.at_level("ERROR"):
        e._guard("main", RuntimeError("one"))
        e._guard("main", RuntimeError("two"))
        assert e.check_streams() == ["main"]     # grew since the last check: refresh
        assert e.check_streams() == []
        e.errors.pop("main")                     # what set_main_device does on reopen
        e._stream_opened("main")                 # ...and a new stream starts counting
        e._guard("main", RuntimeError("three"))
    assert caplog.text.count("exception in main audio callback") == 2
    assert "three" in e.errors_snapshot()["main"]
    assert e.cb_errors["main"] == 3              # still a running total for diagnostics
    assert e.check_streams() == ["main"]


def test_errors_snapshot_is_a_copy():
    e = Engine()
    e.errors["main"] = "gone"
    snap = e.errors_snapshot()
    e.errors["mic"] = "also gone"
    assert snap == {"main": "gone"}


def fake_devices(monkeypatch, rate=44100, start_fails=False):
    made = []

    class Stream:
        def __init__(self, **kw):
            self.closed = False
            made.append(self)

        def start(self):
            if start_fails:
                raise RuntimeError("device busy")

        def stop(self):
            pass

        def close(self):
            self.closed = True

    monkeypatch.setattr(eng, "find_device", lambda kind, name: 7)
    monkeypatch.setattr(eng.sd, "query_devices",
                        lambda idx=None: {"default_samplerate": rate, "max_output_channels": 2,
                                          "max_input_channels": 1})
    monkeypatch.setattr(eng.sd, "OutputStream", Stream)
    monkeypatch.setattr(eng.sd, "InputStream", Stream)
    return made


def test_failed_start_closes_the_stream_and_keeps_the_rate(monkeypatch):
    made = fake_devices(monkeypatch, start_fails=True)
    e = Engine()
    e.set_main_device("busy")
    e.set_mic_device("busy mic")
    assert len(made) == 2 and all(s.closed for s in made)     # nothing leaked
    assert e.rates == {"main": SR, "mon": SR, "mic": SR, "obs": SR}
    assert "device busy" in e.errors["main"] and "device busy" in e.errors["mic"]
    assert e.main_stream is None and e.mic_stream is None


def test_opening_one_output_leaves_the_other_playing(monkeypatch):
    e = Engine()
    e.mon_stream = FakeStream()
    ring = e.ring_rmon
    ring.write(np.full((4800, 2), 0.1, np.float32))
    e.set_main_device("no such device")          # fails (a retry every few seconds)...
    assert ring.count == 4800                    # ...without resetting the headphones
    fake_devices(monkeypatch, rate=44100)
    e.set_main_device("cable")                   # opens at a new rate
    assert e.main_stream is not None and e.rates["main"] == 44100
    assert e.ring_rmain.max_fill == int(44100 * e.ring_rmain.max_s)
    assert ring.count == 4800                    # the other output is still untouched


def test_reopened_output_resumes_sounds_still_playing_on_the_other(monkeypatch):
    e = engine_with("main", "mon")
    v = e.play("a", tone(1.0), 1.0, loop=True)
    for _ in range(10):
        e._render("main", 480)
        e._render("mon", 480)
    e._close("mon_stream")                       # the watchdog found it stalled...
    for _ in range(20):
        e._render("main", 480)
    fake_devices(monkeypatch, rate=SR)
    e.set_mon_device("headphones")               # ...and reopened it
    assert "mon" not in v.done and v.gate["mon"] == 0.0
    assert v.pos["mon"] == v.pos["main"]         # picks up where the other output is
    first = e._render("mon", 480)
    assert np.abs(first[:48]).max() < 0.1        # fades in, no click
    assert np.abs(e._render("mon", 480)).max() > 0.4


def test_a_device_rescan_keeps_sounds_playing_where_they_were(monkeypatch):
    """Plugging in headphones rescans the devices, which closes every stream at
    once: the sounds used to end there."""
    e = engine_with("main", "mon")
    v = e.play("a", tone(2.0), 1.0)
    done = e.play("b", tone(0.01), 1.0)
    for _ in range(10):
        e._render("main", 480)
        e._render("mon", 480)
    at = v.pos["main"]
    assert done.finished
    e.shutdown()                                 # the rescan: everything closed
    assert v.finished
    fake_devices(monkeypatch, rate=SR)
    e.set_main_device("cable")
    assert "main" not in v.done and v.pos["main"] == at
    e.set_mon_device("headphones")
    assert "mon" not in v.done and v.pos["mon"] == at
    assert done.finished                         # what had ended stays ended
    e._render("main", 480)
    assert np.abs(e._render("main", 480)).max() > 0.4
    e.shutdown()
    fake_devices(monkeypatch, rate=44100)        # back at another rate: its data is
    e.set_main_device("cable")                   # useless, so it stays done
    assert "main" in v.done


def test_reopened_output_at_another_rate_leaves_sounds_done(monkeypatch):
    e = engine_with("main", "mon")
    v = e.play("a", tone(1.0), 1.0, loop=True)
    e._render("main", 480)
    e._close("mon_stream")
    fake_devices(monkeypatch, rate=44100)
    e.set_mon_device("headphones")
    assert "mon" in v.done                       # its data is for the old rate
    assert not e._render("mon", 480).any()
    e.set_mon_device("headphones")               # reopened again at the same new rate:
    assert "mon" in v.done                       # the data is still for the old one


def test_seek_survives_a_render_in_flight():
    e = engine_with("main")
    v = e.play("a", tone(1.0), 1.0)
    n = len(v.data["main"])
    out = np.zeros((480, 2), np.float32)
    e._main(out, 480)
    v.seek(0.5)                                  # as if the UI seeks mid-block...
    v.pos["main"] = 960                          # ...and the block then writes its pos back
    assert abs(v.progress() - 0.5) < 0.01        # the pending seek is what the UI sees
    e._main(out, 480)
    assert v.pos["main"] == n // 2 + 480         # applied at the top of the next block
    assert not v.seek_to


def test_empty_looped_sound_finishes():
    e = engine_with("main")
    v = e.play("a", np.zeros((0, 2), np.float32), 1.0, loop=True)
    e._main(np.zeros((480, 2), np.float32), 480)
    assert v.finished and not e.any_playing()


def test_play_skips_an_output_closed_while_it_resampled(monkeypatch):
    e = engine_with("main", "mon")
    e.rates["mon"] = 44100
    real = e._cached

    def slow(sid, data, rate, src_rate=SR):
        if rate == 44100:
            e._close("mon_stream")   # the watchdog, between picking outputs and adding the voice
        return real(sid, data, rate, src_rate)

    monkeypatch.setattr(e, "_cached", slow)
    v = e.play("a", tone(), 1.0)
    assert "mon" in v.done and not v.finished
    e._close("main_stream")
    assert not e.any_playing()


def test_play_gives_up_when_every_output_went_away_or_changed_rate(monkeypatch):
    e = engine_with("main")
    real = e._cached

    def slow(sid, data, rate, src_rate=SR):
        e.rates["main"] = 44100      # reopened at another rate meanwhile
        return real(sid, data, rate, src_rate)

    monkeypatch.setattr(e, "_cached", slow)
    assert e.play("a", tone(), 1.0) is None
    assert e.voices == ()


def test_eq_and_destination_drop_their_state_when_turned_off():
    e = engine_with("main")
    x = np.zeros((64, 2), np.float32)
    from soundboard.eq import EQ
    e._eqs[("main", "sounds")] = EQ(e.rates["main"])   # idle: nothing left to fade out
    e._dests["main"] = object()
    e.eq_gains = None
    e.dest = None
    assert e._eq("main", "sounds", x) is x and e._dest("main", x) is x
    assert e._eqs == {} and e._dests == {}


def test_a_low_cut_gives_each_sound_back_its_own_sub_bass():
    """With a mode that cuts the sub-bass, a bass-heavy sound is turned up by what the
    cut takes from *it*; a sound with no sub-bass playing alongside isn't."""
    from soundboard import destination
    t = np.arange(SR) / SR
    boom = np.stack([np.sin(2 * np.pi * 40 * t) * 0.3 + np.sin(2 * np.pi * 800 * t) * 0.1] * 2,
                    1).astype(np.float32)
    e = engine_with("main")
    vb = e.play("boom", boom, 1.0, mode="overlap")
    vt = e.play("beep", tone(1.0), 1.0, mode="overlap")
    assert vb.makeup(70) > 2.5 and abs(vt.makeup(70) - 1.0) < 0.01

    def render(dest):
        e.dest = dest
        for v in e.voices:
            v.pos["main"] = 0
        return e._render("main", 480)
    plain = render(None)
    game = destination.BUILTIN_BY_KEY["game"]
    cut = render(game)
    only_beep = tone(1.0)[:480]
    boost = (cut - only_beep)[:, 0] / (plain - only_beep)[:, 0].clip(1e-6)
    assert abs(np.median(boost[np.abs(plain - only_beep)[:, 0] > 1e-3]) - vb.makeup(70)) < 0.01
    assert render(destination.BUILTIN_BY_KEY["discord"]) is not None


# ---------------------------------------------------------------- the logo's "playing" level

def test_play_level_counts_everything_playing_but_not_the_mic():
    """The header logo and the taskbar icon glow with level_play: the radio and a
    captured program count even when only you hear them; your voice doesn't."""
    e = engine_with("main", "mon")
    e.ring_main.prefill = 0
    out = np.zeros((480, 2), np.float32)
    e._mic(np.full((480, 1), 0.5, np.float32))
    e._main(out, 480)
    assert out.any() and e.level_main > 0.4 and e.level_play == 0   # talking: not playing
    e.radio_live = False                                             # radio for you only
    e.ring_rmain.prefill = e.ring_rmon.prefill = 0
    e.feed_radio(np.full((480, 2), 0.25, np.float32))
    e._main(out, 480)
    assert e.level_play > 0.2
    e.level_play = 0.0
    src = e.add_aux("prog")
    src.live = False                                                 # a program, not sent
    src.ring_main.prefill = src.ring_mon.prefill = 0
    e.feed_aux(src, np.full((480, 2), 0.3, np.float32))
    e._mon(out, 480)
    assert e.level_play > 0.25


def test_mic_gate_mutes_the_mic_only_while_a_sound_plays():
    e = engine_with("main")
    mic = np.full((480, 2), 0.5, np.float32)
    silent = np.zeros((480, 2), np.float32)

    def mic_level():
        return float(np.abs(e._send_bus("main", silent.copy(), mic)).max())
    assert mic_level() > 0.4                     # off: the mic always goes out
    e.mic_gate = True
    assert mic_level() > 0.4                     # on, nothing playing
    v = e.play("a", tone(), 1.0)
    for _ in range(5):                           # fades out over a few blocks, no click
        mic_level()
    assert mic_level() == 0.0
    v.stopping = True
    v.done.add("main")                           # the sound ended
    for _ in range(5):
        mic_level()
    assert mic_level() > 0.4


def test_a_broken_block_from_a_program_is_silenced():
    """A captured program handing over NaN / Inf must not reach the send chain's
    filters (one NaN there silences the call until a restart)."""
    a = eng.AuxSource("app", {"main": SR, "mon": SR})
    x = np.full((960, 2), 0.1, np.float32)
    x[5, 0], x[9, 1] = np.nan, np.inf
    a.feed(x, True, True)
    assert np.isfinite(a.level)
    got = a.ring_main.read(480)
    assert got is None or np.isfinite(got).all()
    y = np.array([[np.nan, -np.inf], [0.2, 0.2]], np.float32)
    assert np.isfinite(eng.finite(y)).all() and y[1, 0] == np.float32(0.2)


@pytest.mark.parametrize("name", [
    "CABLE Input (VB-Audio Virtual Cable)", "CABLE-A Output (VB-Audio Cable A)",
    "Hi-Fi Cable Input (VB-Audio Hi-Fi Cable)", "VoiceMeeter Input (VB-Audio VoiceMeeter VAIO)",
    "Line 1 (Virtual Audio Cable)",
])
def test_is_virtual_cables(name):
    assert eng.is_virtual(name)


@pytest.mark.parametrize("name", [
    "Speakers (HyperX Virtual Surround Sound)", "Microphone (HyperX Virtual Surround Sound)",
    "Headphones (Logitech G Virtual Surround)", "Speakers (Realtek High Definition Audio)",
])
def test_is_virtual_leaves_real_headsets(name):
    assert not eng.is_virtual(name)


def _wait_resampled(e, key, timeout=10.0):
    end = time.monotonic() + timeout
    while key not in e._cache and time.monotonic() < end:
        time.sleep(0.01)
    assert key in e._cache


def test_play_never_resamples_on_the_calling_thread(monkeypatch):
    """A 44.1 kHz device and a sound not resampled yet: the press plays at once from
    the source (read at the output's rate) and the copy is made on a thread."""
    e = engine_with("main")
    e.rates["main"] = 44100
    x = tone(2.0)
    v = e.play("a", x, 1.0)
    assert v.data["main"] is x and v.step["main"] == pytest.approx(SR / 44100)
    out = np.zeros((4410, 2), np.float32)
    e._main(out, 4410)   # 0.1 s at 44.1 kHz: still the 440 Hz tone, same level
    ref = eng.resample(x, SR, 44100)[:4410]
    assert np.max(np.abs(out[200:] - ref[200:])) < 0.01
    assert v.pos["main"] == pytest.approx(4410 * SR / 44100, abs=1)
    _wait_resampled(e, ("a", 44100))
    v2 = e.play("a", x, 1.0)       # next press: the cached copy
    assert v2.step == {} and len(v2.data["main"]) == round(len(x) * 44100 / SR)


def test_a_stepped_voice_ends_and_seeks_like_any_other():
    e = engine_with("main")
    e.rates["main"] = 44100
    x = tone(0.2)
    v = e.play("a", x, 1.0, fade_out=0.05)
    assert e.state("a") is not None
    e.seek("a", 0.5)
    e._main(np.zeros((441, 2), np.float32), 441)
    assert 0.5 <= v.progress() < 0.6
    for _ in range(20):
        e._main(np.zeros((441, 2), np.float32), 441)
    assert v.finished


def test_cut_shares_is_worked_out_once_per_sound(monkeypatch):
    calls = []
    real = eng.destination.cut_shares
    monkeypatch.setattr(eng.destination, "cut_shares",
                        lambda d, r: calls.append(1) or real(d, r))
    e = engine_with("main")
    x = tone(1.0)
    e.prepare("a", x)
    for _ in range(3):
        e.play("a", x, 1.0)
    assert len(calls) == 1
    y = tone(1.0)                  # new audio for the sound (effects re-rendered)
    e.play("a", y, 1.0)
    assert len(calls) == 2
    e.forget("a")
    assert "a" not in e._shares


def test_callback_keeps_pace_beside_busy_python():
    """numpy lets go of the GIL in every operation on a stereo block; with another
    thread busy in Python, the cable's callback used to wait a switch interval to get
    it back each time (15 ms a block at 1 ms, over its 10 ms budget). With the app's
    interval it stays near its own cost."""
    import sys
    import threading

    from soundboard.app import SWITCH_S
    e = engine_with("main", send_stage=True)
    for i in range(3):
        e.play(f"s{i}", (tone(5.0) * 20000).astype(np.int16), 0.5, mode="overlap")
    out = np.zeros((480, 2), np.float32)
    old = sys.getswitchinterval()
    stop = threading.Event()

    def busy():
        x = 0
        while not stop.is_set():
            for i in range(1000):
                x += i * i

    sys.setswitchinterval(SWITCH_S)
    th = threading.Thread(target=busy, daemon=True)
    th.start()
    try:
        took = []
        for _ in range(60):
            t = time.perf_counter()
            e._cb_main(out, 480, None, 0)
            took.append(time.perf_counter() - t)
            time.sleep(0.003)
    finally:
        stop.set()
        th.join()
        sys.setswitchinterval(old)
    assert np.median(took) < 0.005   # 10 ms is the whole budget; it was 15 ms


def test_hear_my_voice_alone_leaves_the_sounds_out_of_your_headphones():
    e = engine_with("main", "mon")
    e.mic_check = e.mon_voice_only = True
    e.ring_mon.prefill = 0
    e.play("s", tone(), 1.0)
    out = np.zeros((480, 2), np.float32)
    e._mon(out, 480)
    assert not out.any()                      # a sound playing: not heard here
    e._mic(np.full((480, 1), 0.25, np.float32))
    e._mon(out, 480)
    assert out.max() == pytest.approx(0.25 * e.mic_vol * e.mon_vol, rel=0.05)
    e.mon_voice_only = False                  # the mixer's Hear what they hear: everything
    e._mon(out, 480)
    assert out.any()


def test_device_delay_is_unknown_until_the_streams_are_open():
    e = Engine()
    assert e.device_delay() is None


# ---------------------------------------------------------------- the mic

def test_a_mic_live_on_one_channel_goes_out_on_both():
    """An audio interface's input 1 (or a headset adapter) is live on the left only:
    voice chat's mono mix used to halve it, and mic check was one-sided."""
    e = engine_with("main")
    e.ring_main.prefill = 0
    t = np.arange(480) / SR
    voice = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    block = np.zeros((480, 2), np.float32)
    block[:, 0] = voice
    raw = block.copy()
    for _ in range(30):
        e._mic(block)
    assert np.array_equal(block, raw)            # PortAudio's own buffer is left alone
    out = e.ring_main.read(480)
    assert np.allclose(out[:, 0], out[:, 1]) and np.abs(out[:, 1]).max() > 0.25


def test_a_real_stereo_mic_is_left_as_it_is():
    e = engine_with("main")
    e.ring_main.prefill = 0
    t = np.arange(480) / SR
    block = np.stack([0.3 * np.sin(2 * np.pi * 220 * t),
                      0.1 * np.sin(2 * np.pi * 330 * t)], 1).astype(np.float32)
    for _ in range(30):
        e._mic(block)
    assert e._mic_dead is None
    out = e.ring_main.read(480)
    assert not np.allclose(out[:, 0], out[:, 1])


def test_stopping_mic_check_isnt_taken_for_clock_drift():
    """Mic check off leaves the headphones' mic ring unfed; running it dry counted as a
    glitch, and two switched drift tracking (slight stretching) on for no reason."""
    e = engine_with("main", "mon")
    block = np.full((480, 1), 0.1, np.float32)
    out = np.zeros((480, 2), np.float32)
    for _ in range(3):                           # mic check on, then off, twice
        e.mic_check = True
        for _ in range(5):
            e._mic(block)
            e._mon(out, 480)
        e.mic_check = False
        for _ in range(5):
            e._mic(block)
            e._mon(out, 480)
    assert e.ring_mon.underruns == 0 and not e.ring_mon.track_drift


def test_mic_check_hears_the_limiter_too():
    e = engine_with("main", "mon", send_stage=True)
    e.mic_check = True
    e.ring_mon.prefill = 0
    e.play("s", (tone(1.0) * 32767).astype(np.int16), 1.0)
    out = np.zeros((480, 2), np.float32)
    for _ in range(20):
        e._mon(out, 480)
    assert ("mon", "Limiter") in e._send


def test_the_finished_test_recording_is_joined_off_the_audio_thread():
    e = engine_with("main")
    e.start_test_record(0.02)
    out = np.zeros((480, 2), np.float32)
    e._main(out, 480)
    e._main(out, 480)
    assert isinstance(e._rec_done[0], list)      # the callback only handed it over
    data, rate = e.rec_done
    assert data.shape == (960, 2) and rate == e.rates["main"]


def test_quiet_sounds_bus_skips_its_filters_then_wakes_for_a_sound(monkeypatch):
    """With nothing playing, the send stage stops filtering silence after QUIET_S (a
    voice chat mode cost ~1 ms of every 10 ms block on zeros); a sound brings it back
    at once, shaped as before."""
    from soundboard import destination
    e = engine_with("main")
    e.dest = destination.BUILTIN_BY_KEY["discord"]
    calls = []
    real = destination.Processor.process

    def counted(self, x, d):
        calls.append(len(x))
        return real(self, x, d)
    monkeypatch.setattr(destination.Processor, "process", counted)
    out = np.zeros((480, 2), np.float32)
    for _ in range(int(e.QUIET_S * SR / 480) + 5):
        e._main(out, 480)
    n = len(calls)
    e._main(out, 480)
    assert len(calls) == n and np.all(out == 0)    # skipped: only silence
    e.play("a", tone(0.05), 1.0)
    e._main(out, 480)
    assert len(calls) == n + 1 and np.abs(out).max() > 0.01
