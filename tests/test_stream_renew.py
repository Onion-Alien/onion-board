"""Changing the audio block or latency with a sound playing: the streams change places and
the sound goes on (Lite mode's switch cut the song and made it jump)."""
from types import SimpleNamespace

import numpy as np
import pytest

from soundboard.audio import engine as eng
from soundboard.audio.engine import SR, Engine
from soundboard.ui.window.devicecontrol import DeviceControl


@pytest.fixture
def devices(monkeypatch):
    log = []
    streams = []
    refuse = SimpleNamespace(opens=0, start=False)   # how many opens to refuse, and starts

    class Stream:
        latency = 0.16

        def __init__(self, **kw):
            if refuse.opens > 0:
                refuse.opens -= 1
                raise eng.sd.PortAudioError("device busy")
            self.kw = kw
            self.n = len(streams)
            self.closed = False
            streams.append(self)
            log.append(("open", self.n))

        def start(self):
            if refuse.start:
                refuse.start = False
                raise eng.sd.PortAudioError("won't start")
            log.append(("start", self.n))

        def stop(self):
            log.append(("stop", self.n))

        def abort(self):
            log.append(("abort", self.n))

        def close(self):
            self.closed = True
            log.append(("close", self.n))

    monkeypatch.setattr(eng, "find_device", lambda kind, name: 7)
    monkeypatch.setattr(eng.sd, "query_devices",
                        lambda idx=None: {"default_samplerate": SR, "max_output_channels": 2,
                                          "max_input_channels": 1})
    monkeypatch.setattr(eng.sd, "OutputStream", Stream)
    monkeypatch.setattr(eng.sd, "InputStream", Stream)
    return SimpleNamespace(log=log, streams=streams, refuse=refuse)


def song(seconds=10.0):
    return np.zeros((int(seconds * SR), 2), np.float32)


def playing(devices, loop=False):
    """A sound two seconds in on the headphones, and the log from here on."""
    e = Engine()
    e.set_mon_device("headphones")
    v = e.play("a", song(), 1.0, loop=loop)
    v.pos["mon"] = 2 * SR
    v.gate["mon"] = 1.0
    devices.log.clear()
    return e, v


def test_the_new_stream_opens_before_the_old_one_stops(devices):
    e, _v = playing(devices)
    old = e.mon_stream
    e.change_block(0.02)
    assert devices.log == [("open", 1), ("abort", 0), ("start", 1), ("close", 0)]
    assert e.mon_stream is devices.streams[1] and e.mon_stream is not old and old.closed
    assert e.mon_stream.kw["blocksize"] == round(SR * 0.02)


def test_the_sound_goes_on_from_what_was_heard(devices):
    e, v = playing(devices)
    e.change_block(0.02)
    assert "mon" not in v.done and not v.cut
    # what was queued in the old stream was never heard: played again by the new one
    assert v.pos["mon"] == 2 * SR - int(0.16 * SR)
    assert v.gate["mon"] == 0.0   # (a short fade in, so the change doesn't tick)


def test_a_paused_sound_stays_where_it_is(devices):
    e, v = playing(devices)
    v.paused = True
    e.change_block(0.02)
    assert v.pos["mon"] == 2 * SR and v.gate["mon"] == 1.0


def test_a_loop_that_just_came_round_goes_back_before_its_end(devices):
    e, v = playing(devices, loop=True)
    v.pos["mon"] = int(0.06 * SR)
    e.change_block(0.02)
    assert v.pos["mon"] == len(v.data["mon"]) - int(0.1 * SR)


def test_a_one_shot_just_started_goes_back_to_its_start(devices):
    e, v = playing(devices)
    v.pos["mon"] = int(0.06 * SR)
    e.change_block(0.02)
    assert v.pos["mon"] == 0


def test_straight_into_the_mic_is_left_alone(devices):
    """It takes neither the block nor the latency. Reopening it stopped what others hear."""
    e = Engine()
    direct = SimpleNamespace(stop=lambda: pytest.fail("stopped"),
                             close=lambda: pytest.fail("closed"))
    e.main_stream, e.main_direct, e.names["main"] = direct, True, eng.directmic.DEVICE
    e.change_block(0.02)
    assert e.main_stream is direct
    e.latency = "high"
    e.reopen_all()
    assert e.main_stream is direct


def test_a_device_that_refuses_a_second_stream_reopens_the_plain_way(devices):
    e, v = playing(devices)
    devices.refuse.opens = 1
    e.change_block(0.02)
    assert devices.log == [("stop", 0), ("close", 0), ("open", 1), ("start", 1)]
    assert e.mon_stream is devices.streams[1] and "mon" not in e.errors
    assert "mon" in v.cut or "mon" not in v.done   # found its place again, as any reopen


def test_a_new_stream_that_wont_start_reopens_the_plain_way(devices):
    e, _v = playing(devices)
    devices.refuse.start = True
    e.change_block(0.02)
    assert devices.streams[1].closed   # (not left open)
    assert e.mon_stream is devices.streams[2] and "mon" not in e.errors


def test_the_mic_changes_over_the_same_way(devices):
    e = Engine()
    e.set_mic_device("mic")
    devices.log.clear()
    e.change_block(0.02)
    assert devices.log == [("open", 1), ("abort", 0), ("start", 1), ("close", 0)]
    assert e.mic_stream is devices.streams[1]
    assert e.mic_stream.kw["blocksize"] == round(e.rates["mic"] * 0.02)


def test_a_latency_change_keeps_the_sound_going_too(devices):
    e, v = playing(devices)
    e.latency = "high"
    e.reopen_all()
    assert e.mon_stream.kw["latency"] == eng.BUFFER["high"]
    assert "mon" not in v.done and v.pos["mon"] == 2 * SR - int(0.16 * SR)


def test_another_rate_reopens_the_plain_way(devices, monkeypatch):
    e, _v = playing(devices)
    monkeypatch.setattr(eng.sd, "query_devices",
                        lambda idx=None: {"default_samplerate": 44100, "max_output_channels": 2,
                                          "max_input_channels": 1})
    e.change_block(0.02)
    assert devices.log[:2] == [("stop", 0), ("close", 0)]
    assert e.rates["mon"] == 44100


def _opened_by(monkeypatch, engine, changed_only):
    plan = {"mic": "mic", "main": "cable", "mon": "phones", "obs": None,
            "copies": [], "vm": None}
    opened = []
    for name in ("mic", "main", "mon", "obs"):
        monkeypatch.setattr(engine, f"set_{name}_device",
                            lambda n, _k=name: opened.append(_k))
    monkeypatch.setattr(engine, "set_copy_devices", lambda n: None)
    mw = SimpleNamespace(engine=engine,
                         micctl=SimpleNamespace(_cable_ends=lambda main, vm: []))
    DeviceControl._open_devices(SimpleNamespace(mw=mw), plan, changed_only=changed_only)
    return opened


def test_closing_the_guide_with_nothing_changed_leaves_the_streams_open(monkeypatch):
    e = Engine()
    e.names.update(mic="mic", main="cable", mon="phones", obs=None)
    e.mic_stream = e.main_stream = e.mon_stream = object()
    assert _opened_by(monkeypatch, e, True) == ["obs"]   # (none wanted, none open: no cost)


def test_closing_the_guide_opens_what_changed_or_isnt_open(monkeypatch):
    e = Engine()
    e.names.update(mic="mic", main="other cable", mon="phones", obs=None)
    e.main_stream = e.mon_stream = object()   # (the mic isn't open)
    assert _opened_by(monkeypatch, e, True) == ["mic", "main", "obs"]


def test_a_recovery_still_reopens_everything(monkeypatch):
    e = Engine()
    e.names.update(mic="mic", main="cable", mon="phones", obs=None)
    e.mic_stream = e.main_stream = e.mon_stream = object()
    assert _opened_by(monkeypatch, e, False) == ["mic", "main", "mon", "obs"]
