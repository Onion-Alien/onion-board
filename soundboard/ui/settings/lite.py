"""Lite mode (Settings > Appearance): one switch for slower PCs.

It turns off what only decorates and still costs CPU while the app is open:

- every animation that asks `toast.animations_on()` (toasts, the guide's fades, the
  backdrop's glide, the theme cover's fade, the pads' hover glow, flashes);
- the header logo's breathing glow, sheen and embers (a still glow instead);
- Bun's idle moves: every Bun holds still `REST_S` after he's shown or stirred (a
  sound, the mic, a click still move him, then he settles again), and so does Hoot;
- the themes' textures (Plain, whatever Theme style says; that choice is kept).
- the window's full-pace tick for the mic alone: with nothing playing, the mic
  meters follow 5 times a second instead of 24 (most mics hear the room, which
  kept it at full pace for as long as the window was open);
- the meters and the playing screen while something plays: 15 updates a second
  instead of 24 (`tickcontrol.TICK_LITE_MS`). Each meter update also repaints the
  window behind it, so this is most of what the window costs while it's quiet.
- the audio's block: every stream (mic, send device, headphones, stream output) calls
  back every 20 ms instead of 10 (`engineparts.LITE_BLOCK_S`), so the audio
  callbacks cost about half; your voice goes out ~20 ms later. The streams reopen
  when it's switched (`DeviceControl.set_lite_block`), a short gap like an Audio
  buffering change. Straight into my mic keeps its own 10 ms.

Everything still works the same; it only looks calmer (and your voice is that little
bit later). `on()` is read wherever one
of those starts, so turning it on or off applies at once (`set_on`), except Hoot's
rest, which takes the next start of the Triggers tab.

`slow_pc()` says whether this PC looks slow enough to suggest lite mode (once, in a
toast: it's never switched on by itself).
"""
from __future__ import annotations

import os
import sys

REST_S = 1.0          # lite mode: Bun and Hoot settle this long after a stir
SLOW_CORES = 4        # this many logical CPUs or fewer counts as a slower PC
SLOW_RAM_GB = 6.0     # ... and so does less RAM than this

_on = False


def on() -> bool:
    return _on


def set_on(value: bool) -> None:
    global _on
    _on = bool(value)


def rest_s(usual: float | None) -> float | None:
    """How long a mascot moves after a stir: `usual` (None: always), or REST_S in
    lite mode when that's shorter."""
    if not _on:
        return usual
    return REST_S if usual is None else min(usual, REST_S)


def ram_gb() -> float | None:
    """This PC's RAM in GB (None when it can't be read)."""
    if sys.platform != "win32":
        try:
            return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2 ** 30
        except (AttributeError, OSError, ValueError):
            return None
    import ctypes

    class _Mem(ctypes.Structure):   # MEMORYSTATUSEX
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    m = _Mem()
    m.dwLength = ctypes.sizeof(_Mem)
    try:
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return m.ullTotalPhys / 2 ** 30
    except (AttributeError, OSError):
        pass
    return None


def slow_pc(cores: int | None = None, ram: float | None = None) -> bool:
    """Few CPUs or little RAM: worth suggesting lite mode."""
    cores = os.cpu_count() if cores is None else cores
    ram = ram_gb() if ram is None else ram
    return bool((cores and cores <= SLOW_CORES) or (ram and ram < SLOW_RAM_GB))
