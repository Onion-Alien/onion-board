"""The engine mustn't keep audio alive that nothing else holds: an effects preview, a
link's Play once, a TTS clip. The library holds its own sounds, so those stay cached."""
import gc
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
