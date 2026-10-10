"""The engine mustn't keep audio alive that nothing else holds: an effects preview, a
link's Play once, a TTS clip. The library holds its own sounds, so those stay cached."""
import gc
import time
import weakref

import numpy as np

from soundboard.engine import SR, Engine
from tests.test_engine import FakeStream


def _engine(rate=SR):
    e = Engine()
    e.mon_stream = FakeStream()
    e.names["mon"] = "fake mon"
    e.rates["mon"] = rate
    return e


def _song(seconds=2.0):
    t = np.arange(int(seconds * SR)) / SR
    x = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    return np.stack([x, x], 1)


def _finish(e):
    e.stop_all()
    with e.lock:
        e.voices = ()


def test_effects_preview_audio_is_freed_after_it_stops():
    for rate in (SR, 44100):
        e = _engine(rate)
        data = _song()
        dead = weakref.ref(data)
        assert e.play("pad1~fx:preview", data, 1.0, preview=True) is not None
        e.data_for("pad1~fx:preview", data, rate)   # the copy a 44.1 kHz press makes
        assert "pad1~fx" in e._shares
        _finish(e)
        del data
        gc.collect()
        e.playing()   # the UI's poll sweeps what died
        assert dead() is None, rate
        assert "pad1~fx" not in e._shares
        assert not e._cache and e._cache_bytes == 0


def test_library_sounds_stay_cached_while_the_library_holds_them():
    e = _engine(44100)
    data = _song()
    e.prepare("pad1", data)
    shares = e._shares["pad1"][2]
    gc.collect()
    e.playing()
    assert e.cut_shares("pad1", data) is shares
    assert e._cached("pad1", data, 44100, SR) is not None


def test_forget_drops_the_sounds_effects_preview_too():
    e = _engine(44100)
    pad, fx = _song(), _song() * 0.5
    e.prepare("pad1", pad)
    e.cut_shares("pad1~fx", fx)
    e.data_for("pad1~fx:preview", fx, 44100)
    e.forget("pad1")
    assert not e._shares and not e._cache and e._cache_bytes == 0


def _mapped_song(tmp_path, seconds=2.0, name="song"):
    i16 = (_song(seconds) * 32767).astype(np.int16)
    path = tmp_path / f"{name}.npy"   # Windows: a mapped file can't be replaced
    np.save(path, i16)
    return np.asarray(np.load(path, mmap_mode="r"))


def test_a_long_song_on_disk_is_not_copied_into_ram_at_load(tmp_path):
    for rate in (SR, 44100):
        e = _engine(rate)
        song = _mapped_song(tmp_path, name=f"song{rate}")
        e.prepare("song", song)
        assert "song" in e._shares          # cut shares still worked out once
        assert not e._cache and e._cache_bytes == 0, rate


def test_its_first_press_plays_at_once_and_makes_the_copy_for_next_time(tmp_path):
    e = _engine(44100)
    song = _mapped_song(tmp_path)
    e.prepare("song", song)
    v = e.play("song", song, 1.0)
    assert v.data["mon"] is song and v.step["mon"] == SR / 44100   # reads the source
    end = time.monotonic() + 10
    while e._cached("song", song, 44100, SR) is None and time.monotonic() < end:
        time.sleep(0.01)
    copy = e._cached("song", song, 44100, SR)
    assert copy is not None and abs(len(copy) - len(song) * 44100 / SR) <= 2
    _finish(e)
    v = e.play("song", song, 1.0)
    assert v.data["mon"] is copy and "mon" not in v.step


def test_short_sounds_in_ram_are_still_copied_at_load():
    e = _engine(44100)
    clip = (_song(0.5) * 32767).astype(np.int16)
    e.prepare("clip", clip)
    assert e._cached("clip", clip, 44100, SR) is not None
