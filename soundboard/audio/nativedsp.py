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

ABI = 2
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
        ("ob_envelope", [vp, vp, i64, vp, ci, c_double, c_double, vp], ci),
        ("ob_flanger", [vp, vp, i64, i64, vp, vp], ci),
        ("ob_yin", [vp, i64, ci, ci, ci, c_double, vp], c_double),
        ("ob_reverb_bytes", [ci], i64),
        ("ob_reverb_init", [vp, i64, ci, ci, vp], ci),
        ("ob_reverb_run", [vp, i64, vp, vp, i64, c_double, c_double, ci, c_float, ci, ci], ci),
        ("ob_reverb_rung_out", [vp, i64, c_float], ci),
        ("ob_reverb_clear", [vp, i64, ci, ci], ci),
        ("ob_vocoder", [vp, vp, i64, vp, i64, vp, c_double, c_double, c_double, vp, vp, ci, ci,
                        vp, vp, vp], ci),
        ("ob_shaper", [vp, ci, ci, vp, vp, vp, vp, i64, ci, c_double, c_double, c_double,
                       c_double], ci),
        ("ob_deess", [vp, vp, vp, i64, ci, ci, vp, vp] + [c_double] * 7, ci),
        ("ob_limiter", [vp, vp, i64, ci, c_double, ci, c_double, c_double, vp, vp, vp, vp, vp,
                        i64], ci),
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

    __slots__ = ("c", "b", "a", "F", "sections", "S", "D", "at")
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
        self.at = self.c.ctypes.data if self.c is not None else 0

    def step(self, x: np.ndarray, s: np.ndarray, at: int) -> np.ndarray:
        """run() for a cascade (sos) with the state moved on in place, for a stream that
        runs block after block: no copy of it, no addresses looked up but x's and y's.
        s: (F, M, S) C-contiguous float64 that the caller owns, at: s.ctypes.data."""
        m, n = x.shape
        y = np.empty((self.F, m, n), x.dtype)
        lib = LIB if n * m * self.F * self.sections >= RELEASE_FROM else HOLD
        check(lib.ob_sos(self.at, self.F, self.sections, x.ctypes.data, y.ctypes.data,
                         x.itemsize, m, n, at))
        return y

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


_addrs: dict[int, tuple[np.ndarray, int]] = {}


def _inout(a: np.ndarray) -> int:
    """The address of a state or coefficient array that lives from block to block (checked
    the first time). Remembered: `.ctypes.data` costs ~0.6 us, and a voice effect passes
    half a dozen of these every block. Holding the array keeps its id from being reused."""
    hit = _addrs.get(id(a))
    if hit is not None and hit[0] is a:
        return hit[1]
    if a.dtype not in (np.float32, np.float64) or not a.flags.c_contiguous or not a.flags.writeable:
        raise ValueError("a state array must be contiguous, writable float32 / float64")
    if len(_addrs) > 512:      # effects come and go: start over, it's only a cache
        _addrs.clear()
    at = a.ctypes.data
    _addrs[id(a)] = (a, at)
    return at


def sos_coefs(sos: np.ndarray) -> np.ndarray:
    """(filters, sections, 6) -> (filters, sections, 5) doubles, as ob_sos reads them (the
    same rounding as Iir's)."""
    sos = np.asarray(sos, np.float64)
    return np.ascontiguousarray((sos / sos[:, :, 3:4])[:, :, [0, 1, 2, 4, 5]], np.float64)


def vocoder(x: np.ndarray, table: np.ndarray, phase: np.ndarray, step: float, scale: float,
            nz: float, noise: np.ndarray, bank: np.ndarray, bstate: np.ndarray,
            env: np.ndarray, estate: np.ndarray) -> np.ndarray:
    """synth.Robot's wet signal for one block. phase: one double; bank: sos_coefs of the
    band filters; bstate: (bands, 2, 2 * sections) doubles; env: sos_coefs of the one-pole;
    estate: (1, 2 * bands, 2) float32. The states are updated in place."""
    x = np.ascontiguousarray(x, np.float32)
    noise = np.ascontiguousarray(noise, np.float64)
    y = np.empty(len(x), np.float32)
    bands, sections = bank.shape[:2]
    if bstate.size != bands * 4 * sections or estate.size != 4 * bands or env.shape[1] != 1:
        raise ValueError("vocoder state of the wrong size")
    check(HOLD.ob_vocoder(x.ctypes.data, y.ctypes.data, len(x), _inout(table), len(table) - 1,
                          _inout(phase), step, scale, nz, noise.ctypes.data, _inout(bank), bands,
                          sections, _inout(bstate), _inout(env), _inout(estate)))
    return y


def shaper(h: np.ndarray, factor: int, up: np.ndarray, down: np.ndarray, x: np.ndarray,
           kind: int, a0: float, a1: float, b0: float = 1.0, b1: float = 1.0) -> np.ndarray:
    """parts._Oversampled.run with a tanh bend: kind 0 Distortion's, 1 Studio polish's
    warmth (ob_shaper). up, down: the lowpasses' memories, updated."""
    x = np.ascontiguousarray(x, np.float32)
    y = np.empty(len(x), np.float32)
    check(HOLD.ob_shaper(_inout(h), len(h), factor, _inout(up), _inout(down), x.ctypes.data,
                         y.ctypes.data, len(x), kind, a0, a1, b0, b1))
    return y


def deess(top: np.ndarray, rest: np.ndarray, chunk: int, rate: int, state: np.ndarray,
          allow: float, floor: float, gate: float, rise: float, fall: float, attack: float,
          release: float) -> np.ndarray:
    """polish.Polish._deess after its filters. state: (level, gain) doubles, updated."""
    top = np.ascontiguousarray(top, np.float32)
    rest = np.ascontiguousarray(rest, np.float32)
    if len(rest) != len(top) or state.dtype != np.float64 or len(state) != 2:
        raise ValueError("de-esser: bad sizes")
    y = np.empty(len(top), np.float32)
    at = _inout(state)
    check(HOLD.ob_deess(top.ctypes.data, rest.ctypes.data, y.ctypes.data, len(top), chunk, rate,
                        at, at + 8, allow, floor, gate, rise, fall, attack, release))
    return y


def limiter(x: np.ndarray, look: int, ceiling: float, rate: int, attack: float, release: float,
            lg: np.ndarray, need: np.ndarray, mins: np.ndarray, held: np.ndarray,
            work: np.ndarray) -> np.ndarray:
    """polish.Polish._limit. lg: one double; need, mins, held: its float32 histories
    (2 look - 1, look - 1, look); work: float32 scratch. All but work are updated."""
    x = np.ascontiguousarray(x, np.float32)
    if (len(need) != 2 * look - 1 or len(mins) != look - 1 or len(held) != look
            or need.dtype != np.float32 or mins.dtype != np.float32 or held.dtype != np.float32
            or work.dtype != np.float32):
        raise ValueError("limiter: bad state")
    y = np.empty(len(x), np.float32)
    check(HOLD.ob_limiter(x.ctypes.data, y.ctypes.data, len(x), look, ceiling, rate, attack,
                          release, _inout(lg), _inout(need), _inout(mins), _inout(held),
                          _inout(work), len(work)))
    return y
