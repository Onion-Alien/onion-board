"""The C++ audio maths (native/dsp/obdsp.cpp), or None when it isn't there.

`LIB` releases Python's lock for the call, `HOLD` keeps it. Waiting to get the lock back
can cost more than a short filter does (another thread may hold it for a whole switch
interval), so calls that take a few microseconds hold it, and only a long one lets go.

Everything has a Python version, which runs when the DLL is missing or won't load: a run
from source, or a platform it isn't built for. ONIONBOARD_NO_NATIVE_DSP=1 asks for that."""
from __future__ import annotations

import ctypes
import logging
import os
import sys
from ctypes import c_double, c_float, c_int, c_int64, c_void_p
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

ABI = 1
NAME = "obdsp.dll" if sys.platform == "win32" else "libobdsp.so"

# a filter over fewer samples times sections than this holds the lock (see above)
RELEASE_FROM = 16384


def _path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "dsp" / NAME
    return Path(__file__).resolve().parents[2] / "build" / "dsp" / NAME


def _declare(lib):
    i64, vp, ci = c_int64, c_void_p, c_int
    for name, args, res in (
        ("ob_abi", [], ci),
        ("ob_sos", [vp, ci, ci, vp, vp, ci, i64, i64, vp], ci),
        ("ob_tf", [vp, vp, ci, vp, vp, ci, i64, i64, vp], ci),
        ("ob_os_up", [vp, ci, ci, vp, vp, i64, vp], ci),
        ("ob_os_down", [vp, ci, ci, vp, vp, i64, vp], ci),
        ("ob_echo", [vp, i64, vp, vp, vp, i64, c_float, c_float, vp, ci, vp], ci),
        ("ob_compressor", [vp, vp, i64, vp, ci, ci, c_double, c_double, c_double, c_double,
                           c_double, c_float, c_float], ci),
        ("ob_smartmono", [vp, vp, vp, c_double, c_double, c_double, c_double, vp, vp, i64, vp],
         ci),
        ("ob_reverb_bytes", [ci], i64),
        ("ob_reverb_init", [vp, i64, ci, ci, vp], ci),
        ("ob_reverb_run", [vp, i64, vp, vp, i64, c_double, c_double, ci, c_float, ci, ci], ci),
        ("ob_reverb_rung_out", [vp, i64, c_float], ci),
        ("ob_reverb_clear", [vp, i64, ci, ci], ci),
    ):
        f = getattr(lib, name)
        f.argtypes, f.restype = args, res


def _load():
    if os.environ.get("ONIONBOARD_NO_NATIVE_DSP"):
        log.info("native audio maths switched off: using the Python versions")
        return None, None
    path = _path()
    try:
        lib, hold = ctypes.CDLL(str(path)), ctypes.PyDLL(str(path))
        _declare(lib)
        _declare(hold)
        if lib.ob_abi() != ABI:
            raise OSError(f"it's version {lib.ob_abi()}, this app needs {ABI}")
    except (OSError, AttributeError) as ex:
        # expected from source; in an installed copy it means more CPU, not a broken app
        log.log(logging.WARNING if getattr(sys, "frozen", False) else logging.INFO,
                "native audio maths not loaded (%s): using the Python versions", ex)
        return None, None
    return lib, hold


LIB, HOLD = _load()


def check(code: int) -> None:
    """A bad call changed nothing, but its block has no output: never carry on with it."""
    if code < 0:
        raise ValueError(f"native audio maths refused a call ({code})")


class Iir:
    """Drop-in for dsp._Plan: filters rows of samples, with the same state layout."""

    __slots__ = ("c", "b", "a", "F", "sections", "S", "D")

    def __init__(self, sos: np.ndarray | None = None, tf: tuple | None = None):
        if sos is not None:         # (filters, sections, 6)
            self.F, self.sections = sos.shape[:2]
            self.c = np.ascontiguousarray(
                (sos / sos[:, :, 3:4])[:, :, [0, 1, 2, 4, 5]], np.float64)
            self.S = 2 * self.sections
            self.b = self.a = None
        else:                       # (b, a), the same length, divided by a[0]
            b, a = tf
            self.F, self.sections, self.c = 1, 0, None
            self.b = np.ascontiguousarray(b, np.float64)
            self.a = np.ascontiguousarray(a[1:], np.float64)
            self.S = len(a) - 1
        self.D = range(self.F)      # (only its length is read)

    def run(self, x: np.ndarray, s: np.ndarray):
        """x (M, n) contiguous float32 or float64; state s (F, M, S) float64 ->
        (y (F, M, n), new state). The caller's `s` is left as it was."""
        m, n = x.shape
        y = np.empty((self.F, m, n), x.dtype)
        s = s.copy()
        if not n or not m:
            return y, s
        lib = LIB if n * m * self.F * max(self.sections, 1) >= RELEASE_FROM else HOLD
        if self.c is not None:
            r = lib.ob_sos(self.c.ctypes.data, self.F, self.sections, x.ctypes.data,
                           y.ctypes.data, x.itemsize, m, n, s.ctypes.data)
        else:
            r = lib.ob_tf(self.b.ctypes.data, self.a.ctypes.data, self.S, x.ctypes.data,
                          y.ctypes.data, x.itemsize, m, n, s.ctypes.data)
        check(r)
        return y, s


class Reverb:
    """The state block of one reverb channel (obdsp.cpp's Reverb), freed with this object."""

    __slots__ = ("mem", "bytes", "at")

    def __init__(self, rate: int, pre: int, hp: np.ndarray):
        self.bytes = int(LIB.ob_reverb_bytes(rate))
        check(self.bytes)
        self.mem = np.zeros(self.bytes // 8 + 1, np.float64)
        self.at = self.mem.ctypes.data
        row = np.ascontiguousarray((hp[0] / hp[0][3])[[0, 1, 2, 4, 5]], np.float64)
        check(HOLD.ob_reverb_init(self.at, self.bytes, rate, pre, row.ctypes.data))

    def run(self, x: np.ndarray, g: float, a: float, pre: int, mix: float,
            combs: int, aps: int) -> np.ndarray:
        x = np.ascontiguousarray(x, np.float32)
        y = np.empty(len(x), np.float32)
        check(LIB.ob_reverb_run(self.at, self.bytes, x.ctypes.data, y.ctypes.data, len(x),
                                g, a, pre, mix, combs, aps))
        return y

    def rung_out(self, floor: float) -> bool:
        r = HOLD.ob_reverb_rung_out(self.at, self.bytes, floor)
        check(r)
        return bool(r)

    def clear_from(self, combs: int, aps: int) -> None:
        check(HOLD.ob_reverb_clear(self.at, self.bytes, combs, aps))


class Oversampled:
    """The two lowpasses of parts._Oversampled, over its own history arrays."""

    @staticmethod
    def up(h: np.ndarray, factor: int, hist: np.ndarray, x: np.ndarray) -> np.ndarray:
        x = np.ascontiguousarray(x, np.float32)
        y = np.empty(len(x) * factor, np.float32)
        check(HOLD.ob_os_up(h.ctypes.data, len(h), factor, hist.ctypes.data, x.ctypes.data,
                            len(x), y.ctypes.data))
        return y

    @staticmethod
    def down(h: np.ndarray, factor: int, hist: np.ndarray, z: np.ndarray) -> np.ndarray:
        z = np.ascontiguousarray(z, np.float32)
        n = len(z) // factor
        y = np.empty(n, np.float32)
        check(HOLD.ob_os_down(h.ctypes.data, len(h), factor, hist.ctypes.data, z.ctypes.data,
                              n, y.ctypes.data))
        return y


def echo(line: np.ndarray, at: int, x: np.ndarray, y: np.ndarray, mix: float, fb: float,
         sos: np.ndarray | None, z: np.ndarray | None) -> int:
    """Echo's steady stretch: y gets the output; returns the line's new oldest sample."""
    pos = c_int64(at)
    check(HOLD.ob_echo(line.ctypes.data, len(line), ctypes.addressof(pos), x.ctypes.data,
                       y.ctypes.data, len(x), mix, fb, None if sos is None else sos.ctypes.data,
                       0 if sos is None else len(sos), None if z is None else z.ctypes.data))
    return pos.value


def sos_rows(sos: np.ndarray) -> np.ndarray:
    """(sections, 6) as ob_echo reads it: b0 b1 b2 a1 a2, divided by a0."""
    sos = np.asarray(sos, np.float64)
    return np.ascontiguousarray((sos / sos[:, 3:4])[:, [0, 1, 2, 4, 5]])


class SmartMono:
    """sendfx.SmartMono's state, and its one call."""

    __slots__ = ("c", "fstate", "bands", "work", "tune")

    def __init__(self, bank: np.ndarray, flip: float, unflip: float, max_gain: float):
        self.c = np.ascontiguousarray((bank / bank[:, :, 3:4])[:, :, [0, 1, 2, 4, 5]], np.float64)
        self.fstate = np.zeros((4, 2, 8))
        self.bands = np.zeros((3, 5))
        self.bands[:, 3:] = 1.0      # polarity +, gain 1
        self.work = np.empty(0)
        self.tune = (flip, unflip, max_gain)

    def run(self, x: np.ndarray, k: float) -> np.ndarray:
        n = len(x)
        x = np.ascontiguousarray(x, np.float32)
        out = np.empty((n, 2), np.float32)
        if len(self.work) < 8 * n:
            self.work = np.empty(8 * n)
        lib = LIB if n >= RELEASE_FROM // 16 else HOLD
        check(lib.ob_smartmono(self.c.ctypes.data, self.fstate.ctypes.data, self.bands.ctypes.data,
                               k, *self.tune, x.ctypes.data, out.ctypes.data, n,
                               self.work.ctypes.data))
        return out
