"""Memory given back while the window sits in the tray, and the caches that stay small."""
import ctypes
import sys
import time

import numpy as np
import pytest

from test_mainwindow import window  # noqa: F401 - the real window, offscreen

from soundboard.audio import mapped, soundcache
from soundboard.core import memtrim
from soundboard.sounds import thumbs
from soundboard.speech import aipreview


def _working_set() -> int:
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t)] + [
                        (f"x{i}", ctypes.c_size_t) for i in range(6)]
    c = Counters()
    c.cb = ctypes.sizeof(c)
    k32 = ctypes.WinDLL("kernel32")
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL("psapi")
    psapi.GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD)
    assert psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb)
    return c.WorkingSetSize


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' working set")
def test_release_hands_the_working_set_back():
    touched = np.ones(64 << 20, np.uint8)   # 64 MB in RAM now
    assert touched.sum()
    before = _working_set()
    assert memtrim.release()
    assert _working_set() < before - (32 << 20)
    assert touched[123] == 1                 # still ours: read back when used


def _tray(window, monkeypatch, playing):  # noqa: F811
    calls = []
    monkeypatch.setattr(memtrim, "release", lambda: calls.append(1) or True)
    monkeypatch.setattr(window.engine, "playing", lambda: dict(playing))
    monkeypatch.setattr(window.radio, "is_active", lambda: False)
    monkeypatch.setattr(window.engine, "aux", ())
    monkeypatch.setattr(window, "isVisible", lambda: False)
    window.tickctl._tray_since, window.tickctl._given_back = None, False
    window.tickctl._set_tick_rate()            # to the tray
    return calls


def test_the_tray_gives_memory_back_once_after_a_while(window, monkeypatch):  # noqa: F811
    calls = _tray(window, monkeypatch, {})
    window.tickctl.tick()
    assert not calls                           # not straight away: it may be shown again
    window.tickctl._tray_since = time.monotonic() - memtrim.AFTER_S - 1
    window.tickctl.tick()
    assert calls == [1]
    window.tickctl._set_tick_rate()            # (app state changes while in the tray)
    assert window.tickctl._tray_since is None  # once per trip to the tray
    window.tickctl.tick()
    assert calls == [1]

    monkeypatch.setattr(window, "isVisible", lambda: True)
    window.tickctl._set_tick_rate()            # shown...
    assert window.tickctl._tray_since is None
    monkeypatch.setattr(window, "isVisible", lambda: False)
    window.tickctl._set_tick_rate()            # ...and back to the tray: again later
    window.tickctl._tray_since = time.monotonic() - memtrim.AFTER_S - 1
    window.tickctl.tick()
    assert calls == [1, 1]


def test_never_while_a_sound_plays_from_the_tray(window, monkeypatch):  # noqa: F811
    playing = {"s0": (0.5, False)}
    calls = _tray(window, monkeypatch, playing)
    window.tickctl._tray_since = time.monotonic() - memtrim.AFTER_S - 1
    window.tickctl.tick()
    assert not calls                           # the audio thread would read pages back
    playing["s0"] = (0.5, True)                # paused: fine
    window.tickctl.tick()
    assert calls == [1]


def test_ai_voice_previews_keep_only_the_last_few(monkeypatch):
    monkeypatch.setattr(aipreview, "_cache", type(aipreview._cache)())
    monkeypatch.setattr(aipreview, "sample", lambda: np.zeros(1600, np.float32))
    monkeypatch.setattr(aipreview, "render", lambda m, v, x: np.zeros(2400, np.float32))
    for i in range(aipreview.KEEP + 5):
        aipreview.make(None, {"mix": i})
    assert len(aipreview._cache) == aipreview.KEEP
    assert aipreview.cached({"mix": 0}) is None                    # the oldest went
    assert aipreview.cached({"mix": aipreview.KEEP + 4}) is not None
    aipreview.make(None, {"mix": 5})           # used again: kept as the newest
    aipreview.make(None, {"mix": 99})
    assert aipreview.cached({"mix": 5}) is not None


def test_the_caches_together_stay_under_a_gigabyte():
    """Sounds read into RAM, their resampled copies, the pads' pictures and the voice
    previews: everything the app keeps that grows with use."""
    total = (mapped.RAM_BUDGET + soundcache.CACHE_BUDGET + thumbs.MAX_BYTES
             + thumbs.MAX_FITTED_BYTES + aipreview.KEEP * (2 << 20))
    assert total <= 1 << 30


def test_minimised_gives_memory_back_too(window, monkeypatch):  # noqa: F811
    calls = _tray(window, monkeypatch, {})
    monkeypatch.setattr(window, "isVisible", lambda: True)
    monkeypatch.setattr(window, "isMinimized", lambda: True)
    window.tickctl._set_tick_rate()
    window.tickctl._tray_since = time.monotonic() - memtrim.AFTER_S - 1
    window.tickctl.tick()
    assert calls == [1]


@pytest.mark.parametrize("load, collects", [(50, True), (None, True), (85, False)])
def test_no_collection_on_a_pc_short_of_memory(monkeypatch, load, collects):
    from soundboard.core import hangwatch
    calls = []
    monkeypatch.setattr(hangwatch, "memory_load", lambda: load)
    monkeypatch.setattr(memtrim.gc, "collect", lambda *a: calls.append(1) or 0)
    memtrim.release()
    assert bool(calls) == collects   # (it would read the paged-out objects back)
