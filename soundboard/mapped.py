"""Long sounds stay on disk: their decoded cache files are memory-mapped, not read in.

A board of 100 three-minute songs held ~3.5 GB of int16 audio in RAM from the start,
almost none of it playing. A mapped file costs no RAM until its pages are read, and
what has been read is the system's file cache, which Windows takes back when it needs
the memory (it isn't counted as the app's own memory either).

The catch is the audio thread: reading a page that isn't in memory yet waits for the
disk, and on a slow drive that's a stutter. So a press warms the sound first (warm):
the first second is read on the pressing thread, and the system is asked to read
the rest in the background (PrefetchVirtualMemory), so the audio thread only ever
finds pages already in memory.

Windows can't delete or replace a mapped file while any array still points into
it. library.unlink_cache (deletes) and store_cached (replaces) cope with that: what
can't go now is left for prune_cache, which runs after each load and at start-up.
"""
from __future__ import annotations

import ctypes
import logging
import mmap
import sys
import threading
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

SR = 48000
FRAME_BYTES = 4                   # int16 stereo
MAP_MIN_BYTES = 30 * SR * FRAME_BYTES   # sounds over ~30 s are mapped...
RAM_BUDGET = 512 * 2**20          # ...and every sound once this much was read into RAM
WARM_S = 1.0                      # read on the pressing thread before it plays

_lock = threading.Lock()
_held = 0   # bytes read into RAM by load() this session (only grows: a cap, not a count)


def load(path: Path) -> np.ndarray:
    """np.load of a cache file: mapped read-only if it's long or the RAM budget is
    spent, else read in. A plain ndarray either way (a np.memmap subclass would run
    Python code on every slice the audio thread takes)."""
    global _held
    size = path.stat().st_size
    with _lock:
        in_ram = size < MAP_MIN_BYTES and _held + size <= RAM_BUDGET
        if in_ram:
            _held += size
    if in_ram:
        return np.load(path)
    return np.asarray(np.load(path, mmap_mode="r"))


def adopt(data: np.ndarray, path: Path) -> np.ndarray:
    """`data` was just written to `path` (store_cached): the mapped file instead of
    the copy in RAM when load() would map it, so a sound decoded, imported or given
    effects just now doesn't stay in RAM until the next start."""
    global _held
    with _lock:
        in_ram = data.nbytes < MAP_MIN_BYTES and _held + data.nbytes <= RAM_BUDGET
        if in_ram:
            _held += data.nbytes
    if in_ram:
        return data
    try:
        return np.asarray(np.load(path, mmap_mode="r"))
    except (OSError, ValueError):
        return data


def is_mapped(a: np.ndarray) -> bool:
    """Does `a` (or what it's a view of) live in a mapped file?"""
    while a is not None:
        if isinstance(a, (np.memmap, mmap.mmap)):
            return True
        a = getattr(a, "base", None)
    return False


# PrefetchVirtualMemory (Windows 8+): reads the ranges in with large I/Os in the
# background, into the file cache, so the audio thread's reads are soft faults
if sys.platform == "win32":
    class _Range(ctypes.Structure):
        _fields_ = [("VirtualAddress", ctypes.c_void_p), ("NumberOfBytes", ctypes.c_size_t)]

    try:
        _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _prefetch = _k32.PrefetchVirtualMemory
        _prefetch.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(_Range),
                              ctypes.c_ulong]
        _prefetch.restype = ctypes.c_int
        _k32.GetCurrentProcess.restype = ctypes.c_void_p
        _proc = _k32.GetCurrentProcess()
    except (OSError, AttributeError):
        _prefetch = None
else:
    _prefetch = None

_scratch = ctypes.create_string_buffer(int(WARM_S * SR) * FRAME_BYTES)
_scratch_lock = threading.Lock()


def warm(a: np.ndarray, frame: int = 0) -> None:
    """Get a mapped sound ready to play from `frame`: its first second is read now
    (with the GIL released: ctypes.memmove, so a slow disk holds up only this
    thread, never the audio callback), the rest is prefetched in the background,
    from `frame` on and then what's before it (loops come back to the start).
    Does nothing for audio in RAM."""
    if not len(a) or not a.flags.c_contiguous or not is_mapped(a):
        return
    try:
        base = a.ctypes.data
        row = a.strides[0]
        frame = min(max(int(frame), 0), len(a) - 1)
        at = base + frame * row
        end = base + a.nbytes
        if _prefetch is not None:
            ranges = [(at, end - at)] + ([(base, at - base)] if at > base else [])
            arr = (_Range * len(ranges))(*[_Range(p, n) for p, n in ranges])
            _prefetch(_proc, len(ranges), arr, 0)
        n = min(end - at, len(_scratch))
        with _scratch_lock:
            ctypes.memmove(_scratch, at, n)
    except Exception:  # noqa: BLE001 - a hint only: playing works without it
        log.debug("couldn't warm a mapped sound", exc_info=True)
