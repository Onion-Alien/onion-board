"""The decoded-audio cache: each sound's audio as int16 .npy files in CACHE_DIR
(<sid>.npy as imported, <sid>.<fx_key>.npy with its effects), rendering effects into
it, and cleaning out what no sound uses any more.

Audio in memory is int16 stereo at SR ((n, 2), the engine scales it on the fly).
That is half the RAM of float32 and it round-trips losslessly through the cache
folder, so after the first run a sound loads by reading one file instead of
decoding and resampling it again.
"""
from __future__ import annotations

import contextlib
import logging
import struct
import time
import uuid
from collections.abc import Callable
from pathlib import Path

import numpy as np

from soundboard.audio import mapped
from soundboard.sounds import paths
from soundboard.sounds.config import SoundMeta
from soundboard.sounds.levels import _i16, to_int16
from soundboard.sounds.saving import _replace

log = logging.getLogger("soundboard.sounds.library")


CACHE_GRACE_S = 600   # prune_cache leaves a new sound's cache this long (an import in flight)
# cache files a delete was refused for (still mapped, see _unlink): not new imports, so
# prune_cache retries them at once instead of after CACHE_GRACE_S
_refused: set[Path] = set()


_NPY_HEAD = 128   # a streamed cache file's header, written last when the length is known


def _npy_header(f, frames: int) -> None:
    """The .npy header of (frames, 2) int16, padded to _NPY_HEAD bytes (np.load reads it)."""
    h = f"{{'descr': '<i2', 'fortran_order': False, 'shape': ({frames}, 2), }}"
    h = h.ljust(_NPY_HEAD - 11) + "\n"
    f.seek(0)
    f.write(b"\x93NUMPY\x01\x00" + struct.pack("<H", len(h)) + h.encode("latin1"))


def cache_path(sid: str, fx_key: str = "") -> Path:
    """<sid>.npy is the decoded original; <sid>.<fx_key>.npy the version with its
    effects baked in (the key changes whenever the effects do)."""
    return paths.CACHE_DIR / (f"{sid}.{fx_key}.npy" if fx_key else f"{sid}.npy")


def load_cached(sid: str, fx_key: str = "") -> np.ndarray | None:
    """The cached int16 audio for a sound, or None if there is none (or it's damaged).
    A long one stays on disk, memory-mapped (soundboard.audio.mapped)."""
    p = cache_path(sid, fx_key)
    if not p.exists():
        return None
    try:
        data = mapped.load(p)
        if data.dtype == np.int16 and data.ndim == 2 and data.shape[1] == 2:
            return data
        log.warning("cache %s has the wrong shape/dtype; ignoring it", p.name)
    except Exception:  # noqa: BLE001
        log.warning("cache %s is unreadable; ignoring it", p.name, exc_info=True)
    return None


def store_cached(sid: str, data: np.ndarray, fx_key: str = "") -> np.ndarray:
    """Write a sound's audio to the cache (atomically) and return it as int16 (a long
    one mapped from the file written, soundboard.audio.mapped)."""
    i16 = to_int16(data)
    try:
        paths.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        dest = cache_path(sid, fx_key)
        tmp = dest.with_name(f"{dest.stem}.{uuid.uuid4().hex[:8]}.tmp.npy")   # unique per writer
        try:
            np.save(tmp, i16)
            _replace(tmp, dest)   # another writer's replace can hold dest a moment
        finally:
            tmp.unlink(missing_ok=True)
        _refused.discard(dest)   # a new file there: in use again, not a leftover
    except OSError:   # e.g. dest is mapped by audio still in use: prune_cache tidies up
        log.warning("couldn't write cache for %s", sid, exc_info=True)
        return i16
    return mapped.adopt(i16, dest)   # a long one: the file, not this copy


class Cancelled(Exception):
    """A render given up on partway (render_cached's `cancel`): a newer one replaced it."""


REVERSE_CHUNK = 1 << 20   # frames swapped at a time when a render is reversed on disk


def _reverse_frames(path: Path, frames: int) -> None:
    """Reverse the frames of a (frames, 2) int16 .npy in place, a piece at a time."""
    if frames < 2:
        return
    mm = np.load(path, mmap_mode="r+")
    lo, hi = 0, frames
    while hi - lo > 1:
        k = min(REVERSE_CHUNK, (hi - lo) // 2)
        a = mm[lo:lo + k][::-1].copy()
        mm[lo:lo + k] = mm[hi - k:hi][::-1]
        mm[hi - k:hi] = a
        lo, hi = lo + k, hi - k
    mm.flush()
    del mm   # unmapped now: Windows can't rename a file that's still mapped


def render_cached(sid: str, data: np.ndarray, fx: dict | None,
                  cancel: Callable[[], bool] | None = None,
                  progress: Callable[[float], None] | None = None) -> np.ndarray:
    """Render a sound's effects (soundfx.render_into) straight into its cache file for
    these effects and return it as int16 (a long one mapped, soundboard.audio.mapped). Only
    a few seconds of it are in memory at a time, however long it is. If the file
    can't be written it's rendered in memory instead, like store_cached does.
    cancel: asked between pieces; True stops the render (raises Cancelled, nothing
    kept). A 2-hour song's pitch shift takes minutes, and each edit saved meanwhile
    started another one alongside it. progress(frac): how far it is, 0..1, now and
    then (from the rendering thread)."""
    from soundboard.audio import soundfx
    key = soundfx.key(fx)
    if not key:
        return to_int16(data)   # nothing to render (never trimmed either)
    dest = cache_path(sid, key)
    tmp = dest.with_name(f"{dest.stem}.{uuid.uuid4().hex[:8]}.tmp.npy")
    try:
        paths.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(tmp, "wb") as f:
            n = 0

            def start():
                nonlocal n
                f.seek(0)
                f.truncate()
                f.write(bytes(_NPY_HEAD))
                n = 0

            def put(x):
                nonlocal n
                if cancel is not None and cancel():
                    raise Cancelled
                f.write(_i16(x).tobytes())        # x is in [-1, 1]: no limiter
                n += len(x)

            soundfx.render_into(data, fx, start, put, cancel, progress)
            _npy_header(f, n)
        if soundfx.clean(fx)["reverse"]:
            _reverse_frames(tmp, n)
        tmp.replace(dest)
        _refused.discard(dest)
    except OSError:   # e.g. dest is mapped by audio still in use: prune_cache tidies up
        log.warning("couldn't write the effects cache for %s; rendering in memory", sid,
                    exc_info=True)
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        return to_int16(soundfx.render(data, fx))
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise
    out = load_cached(sid, key)
    return out if out is not None else to_int16(soundfx.render(data, fx))


def cache_keep(sounds: list[SoundMeta]) -> set[str]:
    """Cache file stems still in use: every original, and each sound's current effects."""
    from soundboard.audio import soundfx
    keep = set()
    for m in sounds:
        keep.add(m.id)
        k = soundfx.key(m.fx)
        if k:
            keep.add(f"{m.id}.{k}")
    return keep


def prune_cache(keep: set[str]):
    """Delete cache files that aren't in `keep` (see cache_keep): removed sounds and
    effects versions that were replaced. Recent files of a sound `keep` doesn't know
    are left alone, like thumbs.prune does: an import still running has stored its
    cache (or is writing its .tmp.npy) before the sound joins the library."""
    ids = {k.split(".")[0] for k in keep}
    try:
        files = list(paths.CACHE_DIR.glob("*.npy"))
    except OSError:
        log.debug("cache prune failed", exc_info=True)
        return
    for p in files:
        if p.stem in keep:
            continue
        fresh = ((p.name.split(".")[0] not in ids or p.name.endswith(".tmp.npy"))
                 and p not in _refused)
        try:
            if fresh and time.time() - p.stat().st_mtime < CACHE_GRACE_S:
                continue
        except OSError:
            continue
        _unlink(p)


def _unlink(p: Path) -> bool:
    """Delete a cache file. False if it can't go yet: Windows refuses while a mapped
    array still points into it (a sound just removed, still on its way out of the
    engine). It isn't in cache_keep any more, so the next prune_cache takes it (at
    once, not after CACHE_GRACE_S: it's in _refused)."""
    try:
        p.unlink(missing_ok=True)
    except OSError:
        log.debug("cache file %s is still in use; left for later", p.name)
        _refused.add(p)
        return False
    _refused.discard(p)
    return True


def unlink_cache(sid: str) -> None:
    """Delete every cache file of a sound (its original and effects versions)."""
    try:
        files = list(paths.CACHE_DIR.glob(f"{sid}*.npy"))
    except OSError:
        return
    for c in files:
        if c.stem == sid or c.stem.startswith(sid + "."):
            _unlink(c)
