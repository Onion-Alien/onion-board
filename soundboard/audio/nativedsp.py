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
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

ABI = 3
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
        ("ob_harmonics", [vp, i64, ci, vp, vp, vp], ci),
        ("ob_cubic", [vp, i64, ci, c_double, c_double, i64, i64, c_float, ci, vp], ci),
        ("ob_ring_cubic", [vp, i64, ci, i64, i64, vp, i64, i64, vp], ci),
        ("ob_limiter_work", [ci, ci, i64], i64),
        ("ob_limiter", [vp, vp, i64, ci, ci, c_float, c_double, vp, vp, vp, vp, vp, vp], ci),
        ("ob_leveler", [vp, vp, i64, ci, ci, vp, vp], ci),
        ("ob_envelope", [vp, vp, i64, vp, ci, c_double, c_double, vp], ci),
        ("ob_flanger", [vp, vp, i64, i64, vp, vp], ci),
        ("ob_yin", [vp, i64, ci, ci, ci, c_double, vp], c_double),
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


LIB: Any
HOLD: Any
LIB, HOLD = _load()


def check(code: int) -> None:
    """A bad call changed nothing, but its block has no output: never carry on with it."""
    if code < 0:
        raise ValueError(f"native audio maths refused a call ({code})")


class Iir:
    """Drop-in for dsp._Plan: filters rows of samples, with the same state layout."""

    __slots__ = ("c", "b", "a", "F", "sections", "S", "D")
    c: Any
    b: Any
    a: Any

    def __init__(self, sos: np.ndarray | None = None, tf: tuple[Any, Any] = (None, None)):
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


def cubic(src: np.ndarray, pos0: float, step: float, off: int, n: int,
          dst: np.ndarray | None = None, g: float = 1.0) -> np.ndarray:
    """dsp.hermite read from `src` ((len,) or (len, ch) float32) at pos0 + step * k for
    k < n, from frames floor(pos) + off - 1 .. + 2. With `dst` the frames are added to
    it times `g`; without, a new array gets them."""
    src = np.ascontiguousarray(src, np.float32)
    ch = src.shape[1] if src.ndim == 2 else 1
    add = dst is not None
    if dst is None:
        dst = np.empty((n,) + src.shape[1:], np.float32)
    elif not (dst.flags.c_contiguous and dst.dtype == np.float32 and len(dst) >= n
              and dst.shape[1:] == src.shape[1:]):
        raise ValueError("cubic: dst must be contiguous float32 shaped like src")
    check(HOLD.ob_cubic(src.ctypes.data, len(src), ch, float(pos0), float(step), int(off),
                        int(n), float(g), int(add), dst.ctypes.data))
    return dst


def ring_cubic(buf: np.ndarray, r: int, avail: int, last: np.ndarray, m: int,
               n: int) -> np.ndarray:
    """Ring.read's stretch of m frames to n, read straight from the ring `buf` ((cap, ch)
    float32) at read position r: frames [last, buf[r], buf[r + 1], ...], wrapping at the
    end, the last of the first `avail` repeating past them."""
    out = np.empty((n, buf.shape[1]), np.float32)
    check(HOLD.ob_ring_cubic(buf.ctypes.data, len(buf), buf.shape[1], r, avail,
                             last.ctypes.data, m, n, out.ctypes.data))
    return out


class Limiter:
    """sendfx.Limiter's slow path. Its state lives here, at fixed addresses (finding an
    array's address costs about a microsecond a call): need (2 * la), box (la), fhist
    (hold - 1) and delay ((la, 2)), views of one array, updated in place by each call."""

    __slots__ = ("la", "hold", "need", "box", "fhist", "delay", "env", "work", "wn", "_at")

    def __init__(self, la: int, hold: int):
        self.la, self.hold = la, hold
        mem = np.ones(5 * la + hold - 1, np.float32)
        self.need = mem[:2 * la]
        self.box = mem[2 * la:3 * la]
        self.fhist = mem[3 * la:3 * la + hold - 1]
        self.delay = mem[3 * la + hold - 1:].reshape(la, 2)
        self.delay[:] = 0.0
        self.env = np.zeros(2)
        self.work = np.empty(0, np.float32)
        self.wn = -1   # the block size `work` was sized for
        self._at = [a.ctypes.data for a in (self.need, self.box, self.fhist, self.delay,
                                            self.env)] + [0]

    def run(self, x: np.ndarray, ceiling: float, rel: float,
            env_db: float) -> tuple[np.ndarray, float, float]:
        """-> (out, the released gain at the last sample, the block's deepest cut), dB."""
        n = len(x)
        x = np.ascontiguousarray(x, np.float32)
        if n != self.wn:
            size = HOLD.ob_limiter_work(self.la, self.hold, n)
            check(size)
            if len(self.work) < size:
                self.work = np.empty(size, np.float32)
                self._at[5] = self.work.ctypes.data
            self.wn = n
        out = np.empty((n, 2), np.float32)
        env = self.env
        env[0] = env_db
        need, box, fhist, delay, at_env, work = self._at
        check(HOLD.ob_limiter(x.ctypes.data, out.ctypes.data, n, self.la, self.hold, ceiling, rel,
                              need, box, fhist, delay, at_env, work))
        return out, float(env[0]), float(env[1])


def leveler(x: np.ndarray, rate: int, state: int, tune: int) -> np.ndarray:
    """sendfx.VoiceLeveler's block: x levelled (x itself when there's nothing to do).
    state, tune: the addresses of its 5 and 9 doubles (ob_leveler)."""
    x = np.ascontiguousarray(x, np.float32)
    y = np.empty_like(x)
    r = HOLD.ob_leveler(x.ctypes.data, y.ctypes.data, len(x), x.shape[1] if x.ndim == 2 else 1,
                        rate, state, tune)
    check(r)
    return y if r else x


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
        if len(self.work) < 10 * n:
            self.work = np.empty(10 * n)
        lib = LIB if n >= RELEASE_FROM // 16 else HOLD
        check(lib.ob_smartmono(self.c.ctypes.data, self.fstate.ctypes.data, self.bands.ctypes.data,
                               k, *self.tune, x.ctypes.data, out.ctypes.data, n,
                               self.work.ctypes.data))
        return out


def harmonics(ph: np.ndarray, old: np.ndarray, amps: np.ndarray) -> np.ndarray:
    """Harmonics 1.. of the phases, each gliding from old[k] to amps[k] over the block."""
    ph = np.ascontiguousarray(ph, np.float64)
    old = np.ascontiguousarray(old, np.float64)
    amps = np.ascontiguousarray(amps, np.float64)
    wave = np.empty(len(ph))
    check(HOLD.ob_harmonics(ph.ctypes.data, len(ph), len(amps), old.ctypes.data, amps.ctypes.data,
                            wave.ctypes.data))
    return wave


def envelope(target: np.ndarray, lengths: np.ndarray, g: float, rate: int, attack: float,
             release: float) -> np.ndarray:
    target = np.ascontiguousarray(target, np.float64)
    lengths = np.ascontiguousarray(lengths, np.int64)
    out = np.empty(len(target))
    now = c_double(g)
    check(HOLD.ob_envelope(target.ctypes.data, lengths.ctypes.data, len(target),
                           ctypes.addressof(now), rate, attack, release, out.ctypes.data))
    return out


def flanger(xf: np.ndarray, yf: np.ndarray, h: int, n: int, delay: np.ndarray,
            fbs: np.ndarray) -> None:
    check(HOLD.ob_flanger(xf.ctypes.data, yf.ctypes.data, h, n, delay.ctypes.data, fbs.ctypes.data))


def yin(h: np.ndarray, dec: int, tmin: int, tmax: int, sr: float, work: np.ndarray) -> float:
    """The pitch of h in Hz (0: none). `work`: yin_work(len(h), dec) doubles."""
    h = np.ascontiguousarray(h, np.float32)
    r = HOLD.ob_yin(h.ctypes.data, len(h), dec, tmin, tmax, sr, work.ctypes.data)
    if r < 0:
        check(-1)
    return r


def yin_work(n: int, dec: int) -> np.ndarray:
    return np.empty(3 * (n // dec + 1))
