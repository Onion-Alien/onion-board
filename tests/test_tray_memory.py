"""The app's memory while it sits in the tray, and the caches that stay small."""
import ctypes
import sys
import time

import numpy as np
import pytest

from test_mainwindow import window  # noqa: F401 - the real window, offscreen

from soundboard.audio import mapped, soundcache
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
@pytest.mark.parametrize("where", ["tray", "minimised"])
def test_a_while_in_the_tray_leaves_the_apps_memory_in_ram(window, monkeypatch, where):  # noqa: F811
    """30 s in the tray or minimised, the app used to hand all of its memory back to
    Windows (EmptyWorkingSet). Every thread then had to get its part back at once, the
    mic's too: on a slow PC that held the whole app for 7 to 31 s each time it was
    minimised, and the next hotkey waited for its sound to be read back in. Windows
    takes what a PC short of memory needs by itself, the least used first."""
    touched = np.ones(64 << 20, np.uint8)        # 64 MB in RAM now
    assert touched.sum()
    monkeypatch.setattr(window.engine, "playing", dict)
    monkeypatch.setattr(window.radio, "is_active", lambda: False)
    monkeypatch.setattr(window.engine, "aux", ())
    monkeypatch.setattr(window, "isVisible", lambda: where == "minimised")
    monkeypatch.setattr(window, "isMinimized", lambda: where == "minimised")
    window.tickctl._set_tick_rate()              # out of sight
    before = _working_set()
    real = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: real() + 3600)   # ...for an hour
    for _i in range(3):
        window.tickctl.tick()
    monkeypatch.setattr(time, "monotonic", real)
    assert _working_set() > before - (32 << 20)
    assert touched[123] == 1


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
