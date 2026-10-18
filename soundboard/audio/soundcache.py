"""The engine's sound cache: each sound's copy at a device's rate (resampled once,
off the audio thread) and its destination low-cut shares, kept while the sound lives.

A mixin Engine inherits: the fields live on the engine, as they did, and `prepare`
reads its open outputs and rates. Nothing here runs on an audio callback; play()
takes a ready copy (`_cached`) or asks for one on a thread (`_resample_soon`).
"""
from __future__ import annotations

import logging
import threading
import weakref
from typing import TYPE_CHECKING
from collections import OrderedDict

import numpy as np
import soxr

from soundboard.mic import destination, sharestore
from soundboard.audio import mapped
from soundboard.audio.engineparts import I16_SCALE, SR

# the engine's logger, as before the move (log lines and filters keep their name)
log = logging.getLogger("soundboard.audio.engine")

CACHE_BUDGET = 192 << 20               # bytes of resampled copies kept for non-48 kHz devices


def resample(data: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst or not len(data):
        return data
    return np.ascontiguousarray(soxr.resample(data, src, dst, quality="VHQ"), dtype=np.float32)


class SoundCache:
    """Resampled copies and cut shares of the sounds (see the module)."""

    if TYPE_CHECKING:   # the engine's own (Engine.__init__, the audio path), used here
        rates: dict[str, int]

        def active_outputs(self) -> set: ...

    def _init_cache(self):
        """The cache's fields (Engine.__init__ calls this)."""
        # (sid, rate) -> (weak ref to the source array, resampled copy); LRU, bounded by
        # CACHE_BUDGET. The source is held weakly, here and in _shares: the library keeps
        # its sounds alive, while a preview's or a link's audio is only held by its voice
        # and must be freed when that ends (an effects preview of a song is ~70 MB)
        self._cache: OrderedDict[tuple[str, int], tuple[weakref.ref, np.ndarray]] = OrderedDict()
        self._cache_bytes = 0
        self._cache_lock = threading.Lock()
        self._resampling: set[tuple[str, int]] = set()   # cache keys being made on a thread
        # sid -> (source array, src rate, destination.cut_shares): worked out once per
        # sound (at load, by prepare), not on every press
        self._shares: dict[str, tuple[weakref.ref, int, dict]] = {}
        # a source array died: its entries get dropped on the next _sweep. The weakref
        # callback only appends here: it can fire on any thread, even one holding
        # _cache_lock, so it mustn't take a lock itself
        self._dead: list[None] = []
        # sid -> times forget() was called: a prepare still running when its sound is
        # removed mustn't put the audio back afterwards (it'd hold a mapped cache file
        # open, so the file couldn't be deleted until the app closed)
        self._forgets: dict[str, int] = {}

    # ----------------------------------------------------------------- sample cache
    def data_for(self, sid: str, data: np.ndarray, rate: int, src_rate: int = SR) -> np.ndarray:
        """Audio for `sid` at `rate`, resampled once and cached."""
        if rate == src_rate:
            return data
        key = (sid.split(":")[0], rate)   # "abc:preview" shares abc's cache
        with self._cache_lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
        # the cache holds a reference to the source array and compares identity with
        # `is`: comparing id() alone could match a *new* array that happens to be
        # allocated at a freed one's address (e.g. successive test recordings)
        if hit and hit[0]() is data:
            return hit[1]
        self._sweep()
        gen = self._forgets.get(key[0], 0)
        if data.dtype == np.int16:   # library audio: resample in float, keep the copy compact
            f = data.astype(np.float32)   # in place from here: a song's float copy is
            f *= I16_SCALE                # ~70 MB, and each temporary would be another
            out = resample(f, src_rate, rate)
            del f
            if not out.flags.writeable:
                out = out.copy()
            if len(out) and float(np.max(np.abs(out))) > 1.0:   # resampling overshot
                from soundboard.sounds.library import _under_full_scale  # (it imports us)
                out = _under_full_scale(out)
            out *= 32767.0
            np.rint(out, out=out)
            np.clip(out, -32768, 32767, out=out)
            out = out.astype(np.int16)
        else:
            out = resample(data, src_rate, rate)
        with self._cache_lock:
            if self._forgets.get(key[0], 0) != gen:
                return out   # forgotten meanwhile: use it, don't keep it
            old = self._cache.pop(key, None)
            if old is not None:
                self._cache_bytes -= old[1].nbytes
            self._cache[key] = (self._ref(data), out)
            self._cache_bytes += out.nbytes
            while self._cache_bytes > CACHE_BUDGET and len(self._cache) > 1:
                _, (_, dropped) = self._cache.popitem(last=False)
                self._cache_bytes -= dropped.nbytes
        return out

    def _cached(self, sid: str, data: np.ndarray, rate: int, src_rate: int) -> np.ndarray | None:
        """data_for's answer if it's ready without any work, else None."""
        if rate == src_rate:
            return data
        with self._cache_lock:
            hit = self._cache.get((sid.split(":")[0], rate))
        return hit[1] if hit and hit[0]() is data else None

    def _resample_soon(self, sid: str, data: np.ndarray, rate: int, src_rate: int):
        """Make data_for's copy on a thread (once per sound and rate at a time)."""
        key = (sid.split(":")[0], rate)
        with self._cache_lock:
            if key in self._resampling:
                return
            self._resampling.add(key)

        def run():
            try:
                self.data_for(sid, data, rate, src_rate)
            except Exception:  # noqa: BLE001 - the next press reads the source again
                log.debug("resampling %s failed", sid, exc_info=True)
            finally:
                with self._cache_lock:
                    self._resampling.discard(key)

        threading.Thread(target=run, daemon=True, name="resample").start()

    def cut_shares(self, sid: str, data: np.ndarray, src_rate: int = SR) -> dict:
        """destination.cut_shares of a sound, worked out once (~12 ms for a song)."""
        key = sid.split(":")[0]
        hit = self._shares.get(key)
        if hit is not None and hit[0]() is data and hit[1] == src_rate:
            return hit[2]
        self._sweep()
        gen = self._forgets.get(key, 0)
        shares = sharestore.lookup(data, src_rate)   # a long song's, from the last start
        if shares is None:
            shares = destination.cut_shares(data, src_rate)
            sharestore.remember(data, src_rate, shares)   # (does nothing unless mapped)
        with self._cache_lock:
            if self._forgets.get(key, 0) == gen:   # not forgotten meanwhile
                self._shares[key] = (self._ref(data), src_rate, shares)
        return shares

    def _ref(self, data: np.ndarray) -> weakref.ref:
        dead = self._dead   # not self: the ref mustn't keep the engine alive
        return weakref.ref(data, lambda _r: dead.append(None))

    def _sweep(self):
        """Drop the cache and shares entries whose source array is gone."""
        if not self._dead:
            return
        with self._cache_lock:
            self._dead.clear()
            for k in [k for k, v in self._shares.items() if v[0]() is None]:
                del self._shares[k]
            for k in [k for k, v in self._cache.items() if v[0]() is None]:
                self._cache_bytes -= self._cache.pop(k)[1].nbytes

    def prepare(self, sid: str, data: np.ndarray):
        """Pre-resample for the currently open outputs (call off the UI thread), as
        long as the copies fit in CACHE_BUDGET. Past it, each new copy would only push
        out an earlier one: a big board on a 44.1 kHz headset resampled every song at
        every start and threw most of them away. Those are made when pressed instead
        (play reads the source at the device's rate meanwhile).
        Long sounds on disk (mapped) aren't copied here at all: a copy reads the whole
        file and keeps it in RAM, which undoes mapping it (8 songs cost 242 MB and
        1.8 s at every start on a 44.1 kHz headset). Their copy is made on first press."""
        self.cut_shares(sid, data)
        if mapped.is_mapped(data):
            return
        for o in self.active_outputs():
            rate = self.rates[o]
            if self._cached(sid, data, rate, SR) is None:
                need = data.nbytes * rate / SR
                if self._cache_bytes + need > CACHE_BUDGET:
                    continue
            self.data_for(sid, data, rate)

    def forget(self, sid: str):
        with self._cache_lock:
            for s in (sid, sid + "~fx"):   # and its effects preview
                self._forgets[s] = self._forgets.get(s, 0) + 1
                self._shares.pop(s, None)
                for k in [k for k in self._cache if k[0] == s]:
                    self._cache_bytes -= self._cache.pop(k)[1].nbytes
