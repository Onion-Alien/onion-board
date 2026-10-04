"""Our own filter maths: everything the app used to import from scipy.

  sosfilt / lfilter   run IIR filters (a cascade of biquads / one transfer function),
                      with the same arguments, state (`zi`) and dtypes as scipy's
  sosfilt_bank        many filters over the same input at once (a vocoder's bands)
  butter              Butterworth low / high / band-pass design, as biquads
  matched_biquad      peak and shelf EQ bands that keep their analog shape all the
                      way up to Nyquist (see below)
  sos_response        a filter's complex frequency response at given frequencies
  running_min         sliding-window minimum in O(n)
  SmoothSos           a filter with memory whose design can change without a click

Running a recursive filter in numpy
-----------------------------------
An IIR filter's every output sample depends on the previous ones, so it can't be
written as one whole-array numpy expression, and a per-sample Python loop is far
too slow for the audio thread. scipy does the loop in C. We don't need to: a linear
filter is a state-space system (state s, matrices A B C D)

    y[n]   = C s[n] + D x[n]
    s[n+1] = A s[n] + B x[n]

and unrolling it over a chunk of L samples gives the chunk's outputs and the next
chunk's starting state as plain matrix products:

    y_chunk = T x_chunk + O s          T: L x L, the impulse response as a Toeplitz matrix
    s_next  = A^L s + K x_chunk        O: the state's free decay, K: what the input adds

Those matrices are worked out once per filter design (cached), so filtering is a
handful of BLAS matrix multiplies over all chunks at once. The only part left that
goes chunk by chunk is the short state vector, and even that is done without a
loop over chunks: the states form a linear recurrence, which is solved with a
parallel prefix scan (log2(chunks) steps, each one matrix product over every chunk).

The state is kept in scipy's own layout (transposed direct form II per biquad), so
`zi` arrays carry over unchanged and blocks join without a seam.

Matched EQ bands
----------------
The textbook (RBJ cookbook) biquads use the bilinear transform, which squeezes the
whole analog frequency axis into 0..Nyquist: a band near the top gets narrower and
lop-sided ("cramping"), and every response is forced flat at Nyquist. Here the
poles are the analog filter's own (impulse invariance, exact) and the zeros are
fitted so the digital magnitude follows the analog one across the whole audible
range (in the spirit of M. Vicanek's "Matched Second Order Digital Filters",
2016). So a 12 kHz shelf at 44.1 kHz sounds like the 12 kHz shelf it says it is.
"""
from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

F32 = np.float32


# --------------------------------------------------------------------------- design

def _sections_ss(sos: np.ndarray):
    """A cascade of biquads as one state-space system (A, B, C, D), float64, with the
    state ordered like scipy's zi: section 0's two DF2T delays, then section 1's..."""
    a_m = np.zeros((0, 0))
    b_v = np.zeros(0)
    c_v = np.zeros(0)
    d = 1.0
    for row in np.asarray(sos, np.float64):
        b0, b1, b2, a0, a1, a2 = row / row[3]
        ak = np.array([[-a1, 1.0], [-a2, 0.0]])
        bk = np.array([b1 - a1 * b0, b2 - a2 * b0])
        ck = np.array([1.0, 0.0])
        # series: previous cascade (a_m, b_v, c_v, d) feeds this section
        n = len(b_v)
        top = np.hstack([a_m, np.zeros((n, 2))])
        bottom = np.hstack([np.outer(bk, c_v), ak])
        a_m = np.vstack([top, bottom])
        b_v = np.concatenate([b_v, bk * d])
        c_v = np.concatenate([b0 * c_v, ck])
        d = b0 * d
    return a_m, b_v, c_v, d


def _tf_ss(b: np.ndarray, a: np.ndarray):
    """One transfer function b/a as a state-space system in scipy lfilter's DF2T layout."""
    b = np.asarray(b, np.float64)
    a = np.asarray(a, np.float64)
    if a[0] == 0:
        raise ValueError("a[0] must not be 0")
    n = max(len(a), len(b))
    b = np.pad(b, (0, n - len(b))) / a[0]
    a = np.pad(a, (0, n - len(a))) / a[0]
    k = n - 1
    a_m = np.zeros((k, k))
    if k:
        a_m[:, 0] = -a[1:]
        a_m[np.arange(k - 1), np.arange(1, k)] = 1.0
    b_v = b[1:] - a[1:] * b[0]
    c_v = np.zeros(k)
    if k:
        c_v[0] = 1.0
    return a_m, b_v, c_v, float(b[0])


class _Plan:
    """The block matrices of one filter, or of a bank of filters of the same order
    run side by side, transposed for signals laid out as rows (one row per
    channel, time along the row). Leading axis: the filter in the bank.

    The products with the signal (T, K) run in the signal's dtype; everything that
    touches the state stays float64. The state of a cascade of low-frequency
    biquads is badly conditioned (a 60 Hz shelf's poles sit at radius 0.996), and
    rounding A^L to float32 alone would make the filter drift by ~1e-3."""

    __slots__ = ("L", "S", "D", "TT", "OT", "KT", "ApowT", "_squares")

    def __init__(self, systems, dtype):
        s = len(systems[0][1])
        # cost per sample ~ L (Toeplitz) + 2S (state in and out); per chunk, the
        # Python and scan overhead: so chunks of 64 at least, longer for big states
        L = 64
        while L < 4 * s and L < 256:
            L *= 2
        t, o, k, apow = zip(*(self._blocks(ss, L) for ss in systems))
        self.L, self.S = L, s
        self.D = np.array([ss[3] for ss in systems])
        self.TT = np.ascontiguousarray(np.stack(t).transpose(0, 2, 1), dtype)  # (F, L, L)
        self.OT = np.ascontiguousarray(np.stack(o).transpose(0, 2, 1))         # (F, S, L)
        self.KT = np.ascontiguousarray(np.stack(k), dtype)                     # (F, L, S)
        self.ApowT = np.ascontiguousarray(np.stack(apow).transpose(0, 1, 3, 2))
        self._squares: dict[int, list[np.ndarray]] = {}

    @staticmethod
    def _blocks(ss, L):
        a_m, b_v, c_v, d = ss
        s = len(b_v)
        apow = np.empty((L + 1, s, s))
        apow[0] = np.eye(s)
        for k in range(1, L + 1):
            apow[k] = apow[k - 1] @ a_m
        o = apow[:L].transpose(0, 2, 1) @ c_v                 # (L, S): C A^k
        h = np.empty(L)                                       # impulse response
        h[0] = d
        h[1:] = o[:L - 1] @ b_v
        lag = np.arange(L)[:, None] - np.arange(L)[None, :]
        t = np.where(lag >= 0, h[np.clip(lag, 0, None)], 0.0)
        kk = apow[L - 1::-1] @ b_v                            # (L, S): A^(L-1-m) B
        return t, o, kk, apow

    def square(self, r: int, i: int) -> np.ndarray:
        """(A^r)^(2^i), transposed; built on first use. Thread-safe: a longer list is
        built aside and swapped in whole. (Appending to the shared list wasn't: the
        main output and the send device run the same plan on two audio threads, and both
        appending the same square left [P, P², P², …] for good.)"""
        sq = self._squares.get(r)
        if sq is None or len(sq) <= i:
            sq = list(sq or [self.ApowT[:, r]])
            while len(sq) <= i:
                sq.append(sq[-1] @ sq[-1])
            self._squares[r] = sq
        return sq[i]

    def run(self, x: np.ndarray, s: np.ndarray):
        """x (M, n) contiguous in this plan's dtype, the input of every filter in the
        bank; state s (F, M, S) float64 -> (y (F, M, n), new state)."""
        m, n = x.shape
        S, L, F = self.S, self.L, len(self.D)
        if S == 0:
            return x[None] * self.D.astype(x.dtype)[:, None, None], s
        if n == 0:
            return np.empty((F, m, 0), x.dtype), s
        # equal chunks of at most L (480 samples -> 8 x 60), so usually no remainder
        r = -(-n // -(-n // L))
        full = n // r
        y = np.empty((F, m, n), x.dtype)
        xc = x[:, :full * r].reshape(m * full, r)           # one row per chunk
        u = (xc @ self.KT[:, L - r:]).astype(np.float64).reshape(F, m, full, S)
        u[:, :, 0] += s @ self.ApowT[:, r]
        # prefix scan: u[j] <- sum_{i<=j} (A^r)^(j-i) u[i] = the state after chunk j
        k, i = 1, 0
        while k < full:
            u[:, :, k:] += u[:, :, :-k] @ self.square(r, i)[:, None]
            k *= 2
            i += 1
        starts = np.empty_like(u)
        starts[:, :, 0] = s
        starts[:, :, 1:] = u[:, :, :-1]
        yc = xc @ self.TT[:, :r, :r]                        # (F, chunks, r)
        yc += starts.reshape(F, m * full, S) @ self.OT[:, :, :r]
        y[:, :, :full * r] = yc.reshape(F, m, full * r)
        s = u[:, :, -1]
        rem = n - full * r
        if rem:
            xr = x[:, full * r:]
            yr = xr @ self.TT[:, :rem, :rem]
            yr += s @ self.OT[:, :, :rem]
            y[:, :, full * r:] = yr
            s = s @ self.ApowT[:, rem] + xr @ self.KT[:, L - rem:]
        return y, s


_plans: dict = {}


def _plan(kind: str, coeffs: tuple[np.ndarray, ...], dtype) -> _Plan:
    """The cached plan for these coefficients. A plain dict (its get / set are atomic
    under the GIL, so the audio thread never waits on a lock); a design that loses a
    race is simply built twice."""
    key = (kind, dtype.char) + tuple((c.shape, c.tobytes()) for c in coeffs)
    p = _plans.get(key)
    if p is None:
        if kind == "sos":
            systems = [_sections_ss(coeffs[0])]
        elif kind == "bank":
            systems = [_sections_ss(sos) for sos in coeffs[0]]
        else:
            systems = [_tf_ss(*coeffs)]
        if len(_plans) > 256:                   # many designs (a slider dragged a long
            _plans.clear()                      # way): start over, it's only a cache
        p = _plans[key] = _Plan(systems, dtype)
    return p


def _work_dtype(*arrays) -> np.dtype:
    dt = np.result_type(*arrays)
    if dt.kind == "c":
        raise TypeError("complex signals aren't supported")
    return np.dtype(np.float32) if dt == np.float32 else np.dtype(np.float64)


def _filter(kind, coeffs, x, axis, zi, k):
    """Run a filter of k state values per section (sos: 2 per section; tf: the
    order) along `axis`, with scipy's zi layout for that kind."""
    x = np.asarray(x)
    if x.ndim == 0:
        raise ValueError("x must have at least one dimension")
    zi_in = None if zi is None else np.asarray(zi)
    dt = _work_dtype(x, *coeffs, *(() if zi_in is None else (zi_in,)))
    p = _plan(kind, coeffs, dt)
    a = axis % x.ndim
    last = a == x.ndim - 1
    xs = x if last else x.swapaxes(a, -1)                # time on the last axis
    rest = xs.shape[:-1]
    m = math.prod(rest)
    x2 = np.ascontiguousarray(xs.reshape(m, xs.shape[-1]), dtype=dt)
    if zi_in is None:
        s = np.zeros((1, m, p.S))
    elif kind == "sos":                                  # (sections, *x with axis -> 2)
        z = zi_in if last else zi_in.swapaxes(a + 1, -1)
        if z.shape != (len(coeffs[0]),) + rest + (2,):
            raise ValueError(f"zi has shape {zi_in.shape}; it needs one (2 delays) per "
                             f"section and channel, with 2 in place of the filtered axis")
        s = z.reshape(len(coeffs[0]), m, 2).transpose(1, 0, 2).reshape(m, p.S)
    else:                                                # x's shape with axis -> order
        z = zi_in if last else zi_in.swapaxes(a, -1)
        if z.shape != rest + (k,):
            raise ValueError(f"zi has shape {zi_in.shape}; it needs the filter order ({k}) "
                             f"in place of the filtered axis")
        s = z.reshape(m, k)
    y2, s = p.run(x2, np.ascontiguousarray(s, dtype=np.float64).reshape(1, m, p.S))
    y2, s = y2[0], s[0].astype(dt, copy=False)
    y = y2.reshape(xs.shape)
    if not last:
        y = y.swapaxes(a, -1)
    if zi is None:
        return y
    if kind == "sos":
        n_sec = len(coeffs[0])
        zf = s.reshape(m, n_sec, 2).transpose(1, 0, 2).reshape((n_sec,) + rest + (2,))
        return y, (zf if last else zf.swapaxes(a + 1, -1))
    zf = s.reshape(rest + (k,))
    return y, (zf if last else zf.swapaxes(a, -1))


def sosfilt(sos, x, axis: int = -1, zi=None):
    """Filter x along `axis` through a cascade of biquads (rows b0 b1 b2 a0 a1 a2).

    Same contract as scipy.signal.sosfilt: with zi (shape (sections, *x.shape with
    `axis` replaced by 2)) it returns (y, final state), so the next block carries on
    seamlessly. Float32 in with float32 coefficients and state stays float32;
    anything else runs in float64."""
    sos = np.atleast_2d(np.asarray(sos))
    if sos.ndim != 2 or sos.shape[1] != 6:
        raise ValueError("sos must have shape (sections, 6)")
    return _filter("sos", (sos,), x, axis, zi, 2)


def lfilter(b, a, x, axis: int = -1, zi=None):
    """Filter x along `axis` with the transfer function b(z)/a(z). Same contract as
    scipy.signal.lfilter (zi: x's shape with `axis` replaced by the filter order)."""
    b = np.atleast_1d(np.asarray(b))
    a = np.atleast_1d(np.asarray(a))
    return _filter("tf", (b, a), x, axis, zi, max(len(a), len(b)) - 1)


def sosfilt_bank(bank, x, state=None):
    """Run several biquad cascades side by side over the same input, in one go: a
    filter bank (a vocoder's bands). bank: (filters, sections, 6), every filter with
    the same number of sections; x: 1-D, or (channels, n) with time last.

    Returns (y, state): y has shape (filters, *x.shape), and state (opaque, float64)
    goes back in with the next block so it carries on seamlessly (None: start
    from silence). Much cheaper than one sosfilt call per filter."""
    bank = np.asarray(bank)
    if bank.ndim != 3 or bank.shape[2] != 6:
        raise ValueError("bank must have shape (filters, sections, 6)")
    x = np.asarray(x)
    dt = _work_dtype(x, bank)
    p = _plan("bank", (bank,), dt)
    x2 = np.ascontiguousarray(x.reshape(-1, x.shape[-1]), dtype=dt)
    if state is None:
        state = np.zeros((len(bank), len(x2), p.S))
    y, state = p.run(x2, state)
    return y.reshape((len(bank),) + x.shape), state


_BTYPES = {"low": "low", "lowpass": "low", "high": "high", "highpass": "high",
           "band": "band", "bandpass": "band"}


def butter(order: int, wn, btype: str = "low", fs: float | None = None) -> np.ndarray:
    """Butterworth filter as biquads (float64, shape (sections, 6)).

    wn is the -3 dB frequency (a (low, high) pair for band-pass): in Hz when fs is
    given, otherwise as a fraction of Nyquist. Designed like scipy's butter (analog
    prototype, pre-warped bilinear transform); each section is normalised to unit
    gain where the filter passes (DC, Nyquist or the band's centre) and the sections
    run from the poles farthest from the unit circle to the nearest, which keeps
    the intermediate levels in check."""
    kind = _BTYPES.get(btype)
    if kind is None:
        raise ValueError(f"unknown btype {btype!r}")
    order = int(order)
    if order < 1:
        raise ValueError("order must be at least 1")
    w = np.atleast_1d(np.asarray(wn, np.float64))
    if fs is not None:
        w = w / (fs / 2)
    if len(w) != (2 if kind == "band" else 1):
        raise ValueError("band-pass needs (low, high); low / high-pass one frequency")
    if np.any(w <= 0) or np.any(w >= 1):
        raise ValueError("critical frequencies must be between 0 and Nyquist")
    if kind == "band" and w[0] >= w[1]:
        raise ValueError("band-pass needs low < high")
    # analog prototype poles (left half plane), pre-warped for the bilinear transform
    k = np.arange(order)
    proto = np.exp(1j * np.pi * (2 * k + order + 1) / (2 * order))
    warped = 4.0 * np.tan(np.pi * w / 2.0)          # bilinear with fs = 2 (normalised)
    if kind == "low":
        poles = proto * warped[0]
        ref = 1.0                                   # unity gain at DC (z = 1)
    elif kind == "high":
        poles = warped[0] / proto
        ref = -1.0                                  # ...at Nyquist
    else:
        bw = warped[1] - warped[0]
        w0 = math.sqrt(warped[0] * warped[1])
        half = proto * bw / 2
        root = np.sqrt(half * half - w0 * w0 + 0j)
        poles = np.concatenate([half + root, half - root])
        # the analog centre w0 lands on the digital centre
        ref = np.exp(1j * 2 * np.arctan(w0 / 4.0))
    zp = (4.0 + poles) / (4.0 - poles)
    # one section per conjugate pair (upper half plane, plus the real poles)
    pairs = [p for p in zp if p.imag > 1e-12]
    reals = sorted((p.real for p in zp if abs(p.imag) <= 1e-12), key=abs)
    sections = []
    for p in pairs:
        sections.append(([p, p.conjugate()], abs(p)))
    while len(reals) >= 2:                         # band-pass of odd order: real pairs
        p1, p2 = reals.pop(), reals.pop()
        sections.append(([p1, p2], max(abs(p1), abs(p2))))
    if reals:
        sections.append(([reals[0]], abs(reals[0])))
    sections.sort(key=lambda s: s[1])
    out = []
    for ps, _ in sections:
        if len(ps) == 2:
            a = np.real(np.poly(ps))
            if kind == "low":
                b = np.array([1.0, 2.0, 1.0])       # zeros at z = -1
            elif kind == "high":
                b = np.array([1.0, -2.0, 1.0])      # zeros at z = +1
            else:
                b = np.array([1.0, 0.0, -1.0])      # one at +1, one at -1
        else:
            a = np.array([1.0, -ps[0].real, 0.0])
            b = np.array([1.0, 1.0 if kind == "low" else -1.0, 0.0])
        g = abs(np.polyval(b[::-1], 1 / ref) / np.polyval(a[::-1], 1 / ref))
        out.append(np.concatenate([b / g, a]))
    return np.array(out)


def sos_response(sos, freqs, fs: float) -> np.ndarray:
    """Complex frequency response of a biquad cascade at `freqs` (Hz)."""
    z = np.exp(-2j * np.pi * np.asarray(freqs, np.float64) / fs)   # z^-1
    h = np.ones_like(z)
    for b0, b1, b2, a0, a1, a2 in np.asarray(sos, np.float64):
        h *= (b0 + (b1 + b2 * z) * z) / (a0 + (a1 + a2 * z) * z)
    return h


# --------------------------------------------------------------------------- EQ bands

def _analog(kind: str, gain_db: float, q: float):
    """Analog prototype (numerator, denominator) coefficients, highest power first,
    in s normalised to the band's frequency (the RBJ cookbook's analog filters)."""
    a = 10 ** (gain_db / 40)
    if kind == "peak":
        return (1.0, a / q, 1.0), (1.0, 1 / (a * q), 1.0)
    r = math.sqrt(a) / q
    if kind == "lowshelf":
        return (a, a * r, a * a), (a, r, 1.0)
    if kind == "highshelf":
        return (a * a, a * r, a), (1.0, r, a)
    raise ValueError(f"unknown band kind {kind!r}")


@lru_cache(maxsize=1024)
def _matched(kind: str, f0: float, gain_db: float, rate: float, q: float) -> tuple:
    num, den = _analog(kind, gain_db, q)
    w = 2 * math.pi * min(f0, rate * 0.45) / rate   # the band's frequency, rad/sample
    # poles: the analog ones mapped exactly (z = e^(s T))
    zp = np.exp(np.roots(den).astype(complex) * w)
    a1 = float(-(zp[0] + zp[1]).real)
    a2 = float((zp[0] * zp[1]).real)
    # what |b(e^jw)|^2 must be for the whole filter to have the analog magnitude, on
    # a log-spaced grid from 10 Hz to Nyquist (how we hear: every octave counts alike)
    om = np.geomspace(2 * math.pi * 10 / rate, math.pi, _GRID)
    s = 1j * om / w
    e = np.exp(-1j * om)
    target = (np.abs(np.polyval(num, s) / np.polyval(den, s)) ** 2
              * np.abs(1 + a1 * e + a2 * e * e) ** 2)
    # |b(e^jw)|^2 is a quadratic in cos w: fit it, weighted toward equal error in dB
    v = np.vander(np.cos(om), 3)
    wt = 1 / target
    for _ in range(3):
        p = np.linalg.lstsq(v * wt[:, None], target * wt, rcond=None)[0]
        wt = 1 / np.sqrt(target * np.maximum(v @ p, target * 1e-3))
    p2 = p[0]
    # factor back: b0+b1+b2 = |b(1)|, b0-b1+b2 = |b(-1)|, 4 b0 b2 = p2
    r0 = math.sqrt(max(p[0] + p[1] + p[2], 1e-30))
    r1 = math.sqrt(max(p[0] - p[1] + p[2], 1e-30))
    sm = (r0 + r1) / 2
    disc = math.sqrt(max(sm * sm - p2, 0.0))
    # the larger root first: zeros inside the unit circle (minimum phase)
    return ((sm + disc) / 2, (r0 - r1) / 2, (sm - disc) / 2, 1.0, a1, a2)


_GRID = 256


def matched_biquad(kind: str, f0: float, gain_db: float, rate: float,
                   q: float = 1 / math.sqrt(2)) -> np.ndarray:
    """One EQ band ('peak', 'lowshelf' or 'highshelf') as a biquad row
    (b0 b1 b2 1 a1 a2, float64) that follows its analog shape up to Nyquist.

    The poles are the analog filter's own (impulse invariance, exact); the zeros
    are then fitted so the digital magnitude matches the analog one across the
    audible range, in the least-squares sense on a dB scale. That's the idea of
    M. Vicanek's "Matched Second Order Digital Filters" (2016), which pins three
    frequencies; fitting all of them at least halves its worst error again. For this
    app's bands the result is within ~0.3 dB of the analog EQ everywhere
    (tests/test_eq.py); the cookbook's bilinear designs are off by up to ~2 dB at
    12 kHz.

    q is the band's width for a peak and the shelf's slope for shelves
    (1/sqrt 2 = the cookbook's slope 1). Cached: the same band costs nothing twice."""
    return np.array(_matched(kind, float(f0), float(gain_db), float(rate), float(q)))


# --------------------------------------------------------------------------- misc

def running_min(x: np.ndarray, size: int) -> np.ndarray:
    """out[i] = min(x[i : i + size]) for every full window (len(x) - size + 1 values).

    van Herk / Gil-Werman: cut x into blocks of `size`, take running minima forward
    and backward inside each block; every window is then one block's suffix and the
    next block's prefix. Three passes, whatever the window size."""
    x = np.asarray(x)
    n = len(x)
    if size < 1 or size > n:
        raise ValueError("size must be between 1 and len(x)")
    if size == 1:
        return x.copy()
    blocks = -(-n // size)
    fill = np.inf if x.dtype.kind == "f" else np.iinfo(x.dtype).max
    g = np.full(blocks * size, fill, dtype=x.dtype)
    g[:n] = x
    g = g.reshape(blocks, size)
    pre = np.minimum.accumulate(g, axis=1).ravel()
    suf = np.minimum.accumulate(g[:, ::-1], axis=1)[:, ::-1].ravel()
    k = n - size + 1
    return np.minimum(suf[:k], pre[size - 1: size - 1 + k])


class SmoothSos:
    """A biquad cascade with memory, for one stream of blocks.

    `run(x, sos)` filters each block, carrying the state over so blocks join without
    a seam. Pass the same array object while the design stays put; when `sos` is a
    different object than last block's (or None: straight through), the output
    crossfades from the old filter's to the new one's over `fade` samples instead of
    switching at once: dragging an EQ slider or turning a knob doesn't click, even on
    a bass shelf. The fade runs its full length however small the blocks are (the old
    filter keeps running, with its own memory, until it's done: at 64-frame blocks a
    fade that ended with its block lasted 1.3 ms and still clicked). A design that
    comes in mid-fade waits for it to end, then fades in the same way, so dragging a
    slider moves the sound in ~20 ms steps, each one smooth. The very first block of a
    stream starts directly (there's nothing to fade from), unless `fresh` is cleared
    (an EQ switched on mid-stream fades in from the dry signal)."""

    def __init__(self, fade: int = 1024):
        self.fade = fade
        self.reset()

    def reset(self):
        self.sos = None
        self.zi = None
        self.fresh = True
        self._old = self._old_zi = None   # the design fading out (None: dry)
        self._pos = -1                    # samples into the fade; -1: not fading

    @property
    def fading(self) -> bool:
        return self._pos >= 0

    @property
    def idle(self) -> bool:
        """Straight through, with no fade under way: safe to drop."""
        return self.sos is None and not self.fading

    def _zeros(self, sos, x, axis):
        shape = list(x.shape)
        shape[axis] = 2
        dt = _work_dtype(x, sos)
        return np.zeros([len(sos)] + shape, dt)

    def _filt(self, sos, x, axis, zi):
        if sos is None:
            return x, None
        return sosfilt(sos, x, axis=axis, zi=zi)

    def run(self, x: np.ndarray, sos, axis: int = 0) -> np.ndarray:
        n = x.shape[axis]
        if n == 0:
            return x                       # take any change with the next real block
        if sos is not self.sos and not self.fading:
            old, zi = self.sos, self.zi
            same_shape = old is not None and sos is not None and len(old) == len(sos)
            self.sos = sos
            # the new design picks up the old one's memory (it describes the same
            # recent signal), which keeps its start-up transient small
            self.zi = None if sos is None else (
                zi.copy() if same_shape else self._zeros(sos, x, axis))
            if not self.fresh:
                self._old, self._old_zi, self._pos = old, zi, 0
        self.fresh = False
        new_y, self.zi = self._filt(self.sos, x, axis, self.zi)
        if not self.fading:
            return new_y
        old_y, self._old_zi = self._filt(self._old, x, axis, self._old_zi)
        k = np.arange(self._pos + 1, self._pos + n + 1, dtype=np.float64)
        ramp = 0.5 - 0.5 * np.cos(np.pi * np.minimum(k, self.fade) / self.fade)
        self._pos += n
        if self._pos >= self.fade:          # done: the old design stops here
            self._old = self._old_zi = None
            self._pos = -1
        shape = [1] * x.ndim
        shape[axis] = n
        ramp = ramp.astype(np.result_type(new_y, old_y)).reshape(shape)
        return old_y + (new_y - old_y) * ramp
