"""Clean mic: background noise (fans, keyboards, a TV) taken out of your mic.

RNNoise (BSD-3, licenses/RNNoise-BSD-3.txt) does it: a small neural network that keeps
the voice and drops the rest, 48 kHz, 10 ms at a time, about 5% of one CPU core. Its
rnnoise.dll comes from scripts/buildtools/fetch_rnnoise.py: build.ps1 bundles it as the
frozen app's rnnoise folder; a source run finds it where that script leaves it
(build/rnnoise). Without it Clean mic just isn't offered (`available()`).

Strong is DeepFilterNet (voicefx.deepfilter), an optional download: the Cleaner hands
the mic to it once it's there and running, and cleans with RNNoise (Normal) while it
starts or after it has stopped (`note` says why).

The voice chain runs a `Cleaner` first on every mic block (VoiceChain.set_clean), so
the voice changer, AI voices and speech recognition all get the cleaned mic.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import threading
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

RATE = 48000
FRAME = 480          # RNNoise's frame: 10 ms at 48 kHz
DELAY = 960          # its output trails its input by two frames (measured: 20 ms)
SCALE = 32768.0      # it works on 16-bit sample values held in floats
STRENGTHS = ("light", "normal", "strong")
DEFAULT = "normal"
LIGHT_DRY = 10 ** (-12 / 20)   # Light: the mic as it was, 12 dB under the cleaned one
NAME = "rnnoise.dll"
DIR = (Path(sys._MEIPASS) / "rnnoise" if hasattr(sys, "_MEIPASS")   # pyright: ignore[reportAttributeAccessIssue]
       else Path(__file__).resolve().parents[2] / "build" / "rnnoise")

_lock = threading.Lock()
_lib: ctypes.CDLL | None = None
_tried = False
_why = ""


def _load() -> ctypes.CDLL | None:
    """rnnoise.dll, loaded once (any thread); None when it's missing or won't load."""
    global _lib, _tried, _why
    if _tried:
        return _lib
    with _lock:
        if _tried:
            return _lib
        path = DIR / NAME
        try:
            if not path.is_file():
                raise OSError(f"{path} is missing")
            lib = ctypes.CDLL(str(path))
            lib.rnnoise_create.restype = ctypes.c_void_p
            lib.rnnoise_create.argtypes = [ctypes.c_void_p]
            lib.rnnoise_destroy.restype = None
            lib.rnnoise_destroy.argtypes = [ctypes.c_void_p]
            lib.rnnoise_process_frame.restype = ctypes.c_float
            lib.rnnoise_process_frame.argtypes = [ctypes.c_void_p,
                                                  ctypes.POINTER(ctypes.c_float),
                                                  ctypes.POINTER(ctypes.c_float)]
            lib.rnnoise_get_frame_size.restype = ctypes.c_int
            if lib.rnnoise_get_frame_size() != FRAME:
                raise OSError("unexpected RNNoise frame size")
            _lib = lib
        except (OSError, AttributeError) as ex:
            _why = str(ex)
            log.info("Clean mic unavailable: %s", ex)
        _tried = True
    return _lib


def available() -> bool:
    """RNNoise is here and loads: Clean mic can be offered."""
    return _load() is not None


def why() -> str:
    """Why it isn't available (for the log), or ""."""
    _load()
    return _why


def clean_settings(raw) -> dict:
    """The saved {"on": bool, "strength": "light" | "normal" | "strong"}, damaged values
    replaced."""
    raw = raw if isinstance(raw, dict) else {}
    s = raw.get("strength")
    return {"on": raw.get("on") is True, "strength": s if s in STRENGTHS else DEFAULT}


class Cleaner:
    """One mic's noise remover. `process(mono)` (the audio thread) returns a block of
    the same length, the cleaned voice `latency()` seconds late. At another rate than
    48 kHz the mic is resampled there and back. Raises RuntimeError when RNNoise isn't
    available or won't start."""

    def __init__(self, rate: int, strength: str = DEFAULT):
        lib = _load()
        if lib is None:
            raise RuntimeError(f"RNNoise isn't available: {_why}")
        state = lib.rnnoise_create(None)
        if not state:
            raise RuntimeError("RNNoise didn't start")
        self._lib, self._state = lib, state
        self.rate = int(rate)
        self.strength = DEFAULT
        self._deep = None   # voicefx.deepfilter.Stream while Strong is picked
        self.note = ""      # why Strong stopped (RNNoise cleans instead), for the card
        self.set_strength(strength)
        self._frame = np.zeros(FRAME, np.float32)
        self._ptr = self._frame.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        self._pending = np.zeros(0, np.float32)    # 48 kHz samples short of a frame
        self._dry = np.zeros(DELAY, np.float32)   # the input the output trails (Light)
        self._up = self._down = None
        prime = FRAME
        if self.rate != RATE:
            import soxr
            # low quality: still flat to ~17 kHz, plenty for a voice, and next to no
            # delay (~0.5 ms there and back; medium and high added 20-30 ms)
            self._up = soxr.ResampleStream(self.rate, RATE, 1, dtype="float32", quality="LQ")
            self._down = soxr.ResampleStream(RATE, self.rate, 1, dtype="float32", quality="LQ")
            prime = int(np.ceil(FRAME * self.rate / RATE)) + 64   # and their slack
        # what goes out, at the mic's rate: started with silence so a block can always
        # be answered in full while the next frame fills
        self._out = np.zeros(prime, np.float32)
        self._prime = prime
        self._late = 0     # silence added since, when the resamplers were slow to start
        self.level = 0.0   # the cleaned voice's peak, for the tab's meter (any thread reads)

    def set_strength(self, strength: str):
        self.strength = strength if strength in STRENGTHS else DEFAULT
        self._mix = LIGHT_DRY if self.strength == "light" else 0.0
        if self.strength == "strong" and self._deep is None:
            from soundboard.voicefx import deepfilter
            self.note = ""
            self._deep = deepfilter.Stream()
        elif self.strength != "strong" and self._deep is not None:
            self._deep.close()
            self._deep = None

    def latency(self) -> float:
        deep = self._deep
        own = deep.latency() if deep is not None and deep.ready else DELAY / RATE
        return own + (self._prime + self._late) / self.rate

    def process(self, mono: np.ndarray) -> np.ndarray:
        n = len(mono)
        x = np.asarray(mono, np.float32)
        if self._up is not None:
            x = self._up.resample_chunk(x)
        deep = self._deep
        if deep is not None:
            if len(self._pending) and deep.ready:
                x = np.concatenate([self._pending, x])
                self._pending = np.zeros(0, np.float32)
            y = deep.feed(x)
            if deep.error:   # Strong has stopped: Normal from now on
                self.note = deep.error
                deep.close()
                self._deep = None
            elif y is not None:
                return self._send(y, n)
        if len(self._pending):
            x = np.concatenate([self._pending, x])
        whole = len(x) // FRAME * FRAME
        self._pending = x[whole:].copy()
        if whole:
            y = np.empty(whole, np.float32)
            frame, ptr, state, run = self._frame, self._ptr, self._state, \
                self._lib.rnnoise_process_frame
            mix = self._mix
            for i in range(0, whole, FRAME):
                frame[:] = x[i:i + FRAME]
                frame *= SCALE
                run(state, ptr, ptr)
                out = y[i:i + FRAME]
                np.multiply(frame, 1.0 / SCALE, out=out)
                if mix:   # Light: some of the mic as it was, lined up with the output
                    out += self._dry[:FRAME] * np.float32(mix)
                self._dry = np.concatenate([self._dry[FRAME:], x[i:i + FRAME]])
            return self._send(y, n)
        return self._send(np.zeros(0, np.float32), n)

    def _send(self, y: np.ndarray, n: int) -> np.ndarray:
        """Cleaned 48 kHz samples in, `n` at the mic's rate out."""
        if len(y):
            if self._down is not None:
                y = self._down.resample_chunk(y)
            self._out = np.concatenate([self._out, y])
        got = self._out
        if len(got) >= n:
            res, self._out = got[:n], got[n:]
        else:   # (the resamplers held back more than the slack: that much later for good)
            self._late += n - len(got)
            res = np.concatenate([np.zeros(n - len(got), np.float32), got])
            self._out = np.zeros(0, np.float32)
        if len(res):
            self.level = float(np.max(np.abs(res)))
        return res

    def close(self):
        if self._deep is not None:
            self._deep.close()
            self._deep = None
        state, self._state = self._state, None
        if state:
            self._lib.rnnoise_destroy(state)

    def __del__(self):
        try:
            self.close()
        except Exception:  # noqa: BLE001 - at interpreter exit the library may be gone
            pass


def clean_clip(mono: np.ndarray, rate: int, strength: str = DEFAULT) -> np.ndarray:
    """A whole recording cleaned (Hear the difference's After), lined up with the
    recording and the same length. Off the UI thread: ~5% of the clip's length (Strong:
    about a third; it raises RuntimeError when it can't run)."""
    m = np.asarray(mono, np.float32)
    if rate != RATE:
        import soxr
        m = soxr.resample(m, rate, RATE).astype(np.float32)
    if strength == "strong":
        from soundboard.voicefx import deepfilter
        out = deepfilter.clean_clip(m)
        if rate != RATE:
            import soxr
            out = soxr.resample(out, RATE, rate).astype(np.float32)
        n = len(mono)
        if len(out) < n:
            out = np.concatenate([out, np.zeros(n - len(out), np.float32)])
        return out[:n]
    c = Cleaner(RATE, strength)
    try:
        lag = DELAY + c._prime
        m = np.concatenate([m, np.zeros(lag, np.float32)])
        out = np.concatenate([c.process(m[i:i + 4800]) for i in range(0, len(m), 4800)])
        out = out[lag:]
    finally:
        c.close()
    if rate != RATE:
        import soxr
        out = soxr.resample(out, RATE, rate).astype(np.float32)
    n = len(mono)
    return out[:n] if len(out) >= n else np.concatenate([out, np.zeros(n - len(out), np.float32)])
