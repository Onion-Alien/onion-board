"""destination.cut_shares of the long sounds, kept on disk between starts.

Working them out takes ~17 ms per 3-minute song and reads 4 MB spread over its mapped
cache file, for every song at every start (100 songs: ~1.7 s of CPU and ~400 MB of
page-ins). They only change when the cache file does, so they're saved next to the
cache files, keyed by the file's name, size and modified time (an effects re-bake
writes a new file). Only mapped sounds use it: a short sound in RAM costs ~3 ms.

An older app ignores the file; a missing or broken one just means working them out.
"""
from __future__ import annotations

import json
import logging
import os
import threading

import numpy as np

from soundboard import destination

log = logging.getLogger(__name__)

NAME = "cut-shares.json"
SAVE_AFTER_S = 2.0   # one write for a whole load, not one per song
VERSION = 1          # bump if cut_shares changes how it measures

_lock = threading.Lock()
_dirs: dict[str, dict] = {}   # cache folder -> {file name: [size, mtime_ns, rate, shares]}
_timer: threading.Timer | None = None


def _file_of(a: np.ndarray) -> str | None:
    """The file a mapped array lives in, or None."""
    while a is not None:
        if isinstance(a, np.memmap):
            return a.filename
        a = getattr(a, "base", None)
    return None


def _table(folder: str) -> dict:
    t = _dirs.get(folder)
    if t is None:
        t = {}
        try:
            with open(os.path.join(folder, NAME), encoding="utf-8") as f:
                raw = json.load(f)
            if raw.get("version") == VERSION and raw.get("cuts") == list(destination.LOWCUTS):
                t = raw.get("files") or {}
        except FileNotFoundError:
            pass
        except Exception:  # noqa: BLE001 - worked out again instead
            log.debug("couldn't read %s", NAME, exc_info=True)
        _dirs[folder] = t
    return t


def _key(path: str) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_size, st.st_mtime_ns


def lookup(data: np.ndarray, rate: int) -> dict | None:
    """The saved shares of a mapped sound, if its file hasn't changed since."""
    path = _file_of(data)
    if path is None:
        return None
    key = _key(path)
    if key is None:
        return None
    with _lock:
        hit = _table(os.path.dirname(path)).get(os.path.basename(path))
    if not hit or hit[:3] != [key[0], key[1], rate]:
        return None
    return {int(c): float(s) for c, s in hit[3].items()}


def remember(data: np.ndarray, rate: int, shares: dict) -> None:
    """Save a mapped sound's shares (written a moment later, with the rest of a load)."""
    path = _file_of(data)
    key = path and _key(path)
    if not key:
        return
    global _timer
    with _lock:
        _table(os.path.dirname(path))[os.path.basename(path)] = [
            key[0], key[1], rate, {str(c): float(s) for c, s in shares.items()}]
        if _timer is None:
            _timer = threading.Timer(SAVE_AFTER_S, save)
            _timer.daemon = True
            _timer.name = "cut-shares"
            _timer.start()


def save() -> None:
    """Write every folder's table, leaving out files that are gone."""
    global _timer
    with _lock:
        _timer = None
        todo = {d: dict(t) for d, t in _dirs.items()}
    for folder, table in todo.items():
        table = {n: v for n, v in table.items() if os.path.exists(os.path.join(folder, n))}
        out = os.path.join(folder, NAME)
        tmp = out + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                json.dump({"version": VERSION, "cuts": list(destination.LOWCUTS),
                           "files": table}, f, separators=(",", ":"))
            os.replace(tmp, out)
        except OSError:
            log.debug("couldn't save %s", NAME, exc_info=True)
