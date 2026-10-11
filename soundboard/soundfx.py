"""Per-sound effects: speed, pitch, EQ, boost, reverse and any voice effect, baked
into the sound's audio once (off the audio thread) and kept in the decoded cache.

A sound's settings are a plain dict stored on its SoundMeta (`fx`), so the config
stays readable and new keys can be added without a migration:

    {"speed": 1.0,        0.25..4   playback speed (length changes, pitch doesn't)
     "pitch": 0.0,        -24..24   semitones (pitch changes, length doesn't)
     "tape": False,       speed also moves the pitch, like a record player
     "eq": [0.0] * 7,     dB per eq.BANDS band
     "gain_db": 0.0,      -24..36   boost; above 0 dBFS the sound clips (that's the point)
     "reverse": False,
     "start": 0.0,        seconds into the original where the sound starts (trim)
     "end": 0.0,          seconds into the original where it ends; 0 = the very end
     "effects": {type: {"on": bool, param: value, ...}}}   any voicefx effect,
                                                            modules' included

The trim is applied first, to the original, so the file itself is never cut and
the trim can be moved or undone at any time.

Speed and pitch are independent: pitch is a high-quality resample (which also
changes length), then a phase vocoder stretches the result to the length the
speed asks for. With `tape` on and no extra pitch the stretch is skipped
entirely, so nightcore / slowed versions are a pure resample.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import logging
import math

import numpy as np
import soxr

from soundboard import dsp, eq, voicefx
from soundboard.engine import SR

log = logging.getLogger(__name__)

F32 = np.float32
SPEED_RANGE = (0.25, 4.0)
PITCH_RANGE = (-24.0, 24.0)
GAIN_RANGE = (-24.0, 36.0)
MAX_TRIM_S = 24 * 3600.0
MIN_TRIM_S = 0.05     # the shortest trimmed sound
TAIL_S = 3.0          # room left for echo / reverb tails (trimmed back to the sound)
BLOCK = 2048          # effects run in blocks like they do on the mic


def neutral() -> dict:
    return {"speed": 1.0, "pitch": 0.0, "tape": False, "eq": [0.0] * len(eq.BANDS),
            "gain_db": 0.0, "reverse": False, "start": 0.0, "end": 0.0, "effects": {}}


def clean(fx: dict | None) -> dict:
    """Settings with every key present, in range, and unknown keys dropped."""
    out = neutral()
    fx = fx if isinstance(fx, dict) else {}

    def num(key, lo, hi):
        try:
            v = float(fx.get(key, out[key]))
        except (TypeError, ValueError, OverflowError):
            return out[key]
        # NaN would slip through min/max: a hand-edited config gets the default
        return float(min(max(v, lo), hi)) if math.isfinite(v) else out[key]

    out["speed"] = num("speed", *SPEED_RANGE)
    out["pitch"] = num("pitch", *PITCH_RANGE)
    out["gain_db"] = num("gain_db", *GAIN_RANGE)
    out["start"] = num("start", 0.0, MAX_TRIM_S)
    out["end"] = num("end", 0.0, MAX_TRIM_S)
    if out["end"] and out["end"] <= out["start"] + MIN_TRIM_S:
        out["end"] = 0.0   # nothing (or next to nothing) left: keep the whole sound
    out["tape"] = bool(fx.get("tape", False))
    out["reverse"] = bool(fx.get("reverse", False))
    g = fx.get("eq")
    if isinstance(g, list) and len(g) == len(eq.BANDS):
        try:
            out["eq"] = [float(min(max(float(v), -eq.MAX_DB), eq.MAX_DB))
                         if math.isfinite(float(v)) else 0.0 for v in g]
        except (TypeError, ValueError, OverflowError):
            pass
    effs = fx.get("effects")
    if isinstance(effs, dict):
        out["effects"] = {str(k): dict(v) for k, v in effs.items() if isinstance(v, dict)}
    return out


def _active_effects(fx: dict) -> list[str]:
    return [t for t, cfg in fx["effects"].items() if cfg.get("on") and t in voicefx.REGISTRY]


def is_trimmed(fx: dict | None) -> bool:
    f = clean(fx)
    return f["start"] >= 1e-3 or f["end"] >= 1e-3


def is_neutral(fx: dict | None) -> bool:
    """True if these settings leave the sound exactly as it is."""
    f = clean(fx)
    return (not is_trimmed(f) and abs(f["speed"] - 1) < 1e-3 and abs(f["pitch"]) < 1e-3
            and abs(f["gain_db"]) < 1e-3 and not f["reverse"]
            and eq.design(f["eq"], SR) is None and not _active_effects(f))


def key(fx: dict | None) -> str:
    """Short stable id of the settings ('' for none): the cache file suffix."""
    if is_neutral(fx):
        return ""
    f = clean(fx)
    for k in ("start", "end"):   # untrimmed sounds keep the keys (and caches) they had
        if not f[k]:
            del f[k]
    text = json.dumps(f, sort_keys=True)
    return hashlib.blake2b(text.encode(), digest_size=6).hexdigest()


def summary(fx: dict | None) -> str:
    """A few words for a tooltip: '0.8x, -3 st, EQ, +12 dB'."""
    if is_neutral(fx):
        return ""
    f = clean(fx)
    bits = []
    if is_trimmed(f):
        bits.append(f"trimmed {fmt_s(f['start'])}–{fmt_s(f['end']) if f['end'] else 'end'}")
    if abs(f["speed"] - 1) >= 1e-3:
        bits.append(f"{f['speed']:.2g}x" + (" tape" if f["tape"] else ""))
    if abs(f["pitch"]) >= 1e-3:
        bits.append(f"{f['pitch']:+g} st")
    if eq.design(f["eq"], SR) is not None:
        bits.append("EQ")
    if abs(f["gain_db"]) >= 1e-3:
        bits.append(f"{f['gain_db']:+g} dB")
    bits += [voicefx.REGISTRY[t].name for t in _active_effects(f)]
    if f["reverse"]:
        bits.append("reversed")
    return ", ".join(bits)


def fmt_s(s: float) -> str:
    """0:03.2 style: minutes, seconds and a tenth (trim points need the tenth)."""
    s = max(0.0, s)
    m, sec = divmod(s, 60)
    return f"{int(m)}:{sec:04.1f}"


def trim(x: np.ndarray, fx: dict | None) -> np.ndarray:
    """The part of (n, 2) audio at SR that the trim keeps (all of it if untrimmed)."""
    f = clean(fx)
    a = min(int(round(f["start"] * SR)), len(x))
    b = int(round(f["end"] * SR)) if f["end"] else len(x)
    b = min(max(b, a), len(x))
    if b - a < int(MIN_TRIM_S * SR):   # a trim past the end of this sound: ignore it
        return x
    return x[a:b]


# --------------------------------------------------------------------------- streaming
#
# A sound is rendered a piece at a time (CHUNK frames, ~2.7 s), every step carrying its
# state from one piece to the next: the int16 to float conversion, the resample, the
# stretch, the EQ, the effects, the boost and the clip. A two-hour sound used to be
# converted to float32 whole (2.8 GB) and copied by each step; now only a few pieces
# are in memory at once, and library.render_cached writes each one straight into the
# cache file. Two things wait for the end: the effects' tail (the last TAIL_S is held
# to be trimmed) and reverse, which needs the end first: library.render_cached
# reverses the finished file on disk, render() the array.
#
# The result is what rendering the whole array at once gave, with one exception: the
# EQ's filters keep their memory as float32 between pieces (as they do between the
# mic's blocks), where one call over the whole sound kept it as float64. That moves a
# sample by at most one int16 step (tests/test_soundfx.py checks it).

CHUNK = 64 * BLOCK    # frames per piece; a whole number of BLOCKs (the effects' grid)


def _pieces(x: np.ndarray):
    """(n, 2) int16 or float audio as float32 pieces (int16 scaled to [-1, 1])."""
    chunk = CHUNK
    for i in range(0, len(x), chunk):
        y = x[i:i + chunk]
        yield y.astype(F32) * F32(1 / 32767.0) if y.dtype == np.int16 else y.astype(F32)


def _exactly(pieces, n: int):
    """The pieces cut (or padded with silence) to n frames in all."""
    left = n
    for p in pieces:
        if left <= 0:
            return
        if len(p) > left:
            p = p[:left]
        left -= len(p)
        yield p
    if left > 0:
        yield np.zeros((left, 2), F32)


def _rechunk(pieces, size: int):
    """The same audio in pieces of exactly `size` frames (the last one shorter)."""
    held: list[np.ndarray] = []
    have = 0
    for p in pieces:
        held.append(p)
        have += len(p)
        if have < size:
            continue
        x = np.concatenate(held) if len(held) > 1 else held[0]
        cut = have - have % size
        for i in range(0, cut, size):
            yield x[i:i + size]
        held = [x[cut:]] if cut < have else []
        have -= cut
    if have:
        yield np.concatenate(held) if len(held) > 1 else held[0]


class _Window:
    """A stream of pieces read as [pad zeros, x, pad zeros] (n frames of x), one range
    at a time, never going back: what's before a range's start is dropped."""

    def __init__(self, pieces, n: int, pad: int):
        self._it = self._padded(pieces, n, np.zeros((pad, 2), F32))
        self._buf = np.zeros((0, 2), F32)
        self._at = 0           # padded position of _buf[0]

    @staticmethod
    def _padded(pieces, n, z):
        yield z
        yield from _exactly(pieces, n)
        yield z

    def get(self, a: int, b: int) -> np.ndarray:
        if a > self._at:
            self._buf = self._buf[a - self._at:]
            self._at = a
        held, end = [self._buf], self._at + len(self._buf)
        while end < b:
            p = next(self._it)
            held.append(p)
            end += len(p)
        if len(held) > 1:
            self._buf = np.concatenate(held)
        return self._buf[:b - self._at]


def _stretch(pieces, n: int, factor: float, n_fft: int = 2048, hop: int = 512,
             chunk: int = 64):
    """stretch() of the n frames the pieces hold, given out in pieces as they're done."""
    out_len = int(round(n * factor))
    ha = hop / factor                        # analysis hop (fractional)
    win = np.hanning(n_fft + 1)[:-1].astype(F32)
    src = _Window(pieces, n, n_fft)
    n_frames = int(np.ceil((n + n_fft) / ha)) + 1
    starts = np.minimum(np.round(np.arange(n_frames) * ha).astype(np.int64), n + n_fft)
    lead = int(round(n_fft * factor))         # the zero padding, stretched
    sent = 0
    # overlap-add accumulators for one chunk of frames plus the overlap it leaves;
    # acc[0] is output-timeline position `base` (output frame 0 is `lead`)
    acc = np.zeros((chunk * hop + n_fft, 2), np.float64)
    wacc = np.zeros(chunk * hop + n_fft, np.float64)
    bins = np.arange(n_fft // 2 + 1)
    omega = 2 * np.pi * bins / n_fft         # expected phase advance per sample
    idx = np.arange(n_fft)
    win2 = win.astype(np.float64) ** 2
    prev_ang = None
    prev_phase = None
    prev_start = 0
    for c0 in range(0, n_frames, chunk):
        st = starts[c0:c0 + chunk]
        k = len(st)
        span = src.get(int(st[0]), int(st[-1]) + n_fft)
        frames = span[(st - st[0])[:, None] + idx]         # (k, n_fft, 2)
        spec = np.fft.rfft(frames * win[None, :, None], axis=1)
        mid = spec[..., 0] + spec[..., 1]
        ang = np.angle(mid)
        mag = np.abs(spec)
        # true hop between consecutive frames (the rounding makes it vary by a sample)
        d = np.diff(np.concatenate([[prev_start], st])).astype(np.float64)
        pa = np.vstack([ang[:1] if prev_ang is None else prev_ang[None], ang[:-1]])
        dphi = ang - pa - omega[None] * d[:, None]
        dphi = (dphi + np.pi) % (2 * np.pi) - np.pi
        inst = omega[None] + dphi / np.maximum(d, 1)[:, None]
        adv = inst * hop
        if prev_phase is None:
            adv[0] = ang[0]                                # first frame keeps its phase
            base = 0.0
        else:
            base = prev_phase
        phase = base + np.cumsum(adv, axis=0)
        # identity phase locking: bins follow their nearest peak's rotation
        mm = np.abs(mid)
        peak = np.zeros_like(mm, dtype=bool)
        peak[:, 1:-1] = (mm[:, 1:-1] >= mm[:, :-2]) & (mm[:, 1:-1] > mm[:, 2:])
        peak[:, 0] = peak[:, -1] = True
        ar = np.broadcast_to(bins, mm.shape)
        left = np.maximum.accumulate(np.where(peak, ar, 0), axis=1)
        right = np.where(peak, ar, bins[-1] + n_fft)[:, ::-1]
        right = np.minimum.accumulate(right, axis=1)[:, ::-1]
        right = np.minimum(right, bins[-1])
        near = np.where((ar - left) <= (right - ar), left, right)
        rows = np.arange(k)[:, None]
        locked = phase[rows, near] + ang - ang[rows, near]
        rot = np.exp(1j * locked)[..., None]
        out = np.fft.irfft(mag * rot, n=n_fft, axis=1) * win[None, :, None]
        for j in range(k):
            o = j * hop
            acc[o:o + n_fft] += out[j]
            wacc[o:o + n_fft] += win2
        prev_ang, prev_phase, prev_start = ang[-1], phase[-1], st[-1]
        # everything before the next frame's start is final: normalise and give it out
        base = c0 * hop
        done = k * hop if c0 + k < n_frames else k * hop + n_fft
        w = wacc[:done]
        w[w < 1e-3] = 1.0
        a, b = max(base, lead), min(base + done, lead + out_len)
        if a < b:
            yield (acc[a - base:b - base] / w[a - base:b - base, None]).astype(F32)
            sent += b - a
        keep = len(acc) - done
        acc[:keep] = acc[done:].copy()
        acc[keep:] = 0.0
        wacc[:keep] = wacc[done:].copy()
        wacc[keep:] = 0.0
    if sent < out_len:
        yield np.zeros((out_len - sent, 2), F32)


def stretch(x: np.ndarray, factor: float, n_fft: int = 2048, hop: int = 512,
            chunk: int = 64) -> np.ndarray:
    """Make (n, 2) float32 audio `factor` times longer without changing its pitch.

    Phase vocoder with identity phase locking (each bin keeps its phase relation
    to the nearest spectral peak), which keeps it from sounding washed out. The
    phase is taken from the mid (L+R) signal and shared by both channels, so the
    stereo image doesn't smear. Frames are processed `chunk` at a time, and each
    stretch of the overlap-add is given out as soon as no later frame can reach it
    (_stretch), so memory beyond the output itself stays bounded on long sounds."""
    n = len(x)
    if n == 0 or abs(factor - 1.0) < 1e-3:
        return np.ascontiguousarray(x, dtype=F32)
    return np.concatenate(list(_stretch(_pieces(x), n, factor, n_fft, hop, chunk)))


def _resampled(pieces, dst: int):
    """engine.resample(x, SR, dst) of the pieces' audio, in pieces (the same samples:
    soxr's stream gives exactly what its one-call resample does)."""
    rs = soxr.ResampleStream(SR, dst, 2, dtype="float32", quality="VHQ")
    for p in pieces:
        y = rs.resample_chunk(np.ascontiguousarray(p), last=False)
        if len(y):
            yield y
    y = rs.resample_chunk(np.zeros((0, 2), F32), last=True)
    if len(y):
        yield y


def resampled_len(n: int, dst: int) -> int:
    """How many frames soxr makes of n at SR resampled to dst (its own rounding)."""
    return int(n * dst / SR + 0.5)


def _speed_pitch(pieces, n: int, speed: float, semitones: float, tape: bool):
    """(pieces, frames) of change_speed_pitch."""
    ratio = 2.0 ** (semitones / 12.0) * (speed if tape else 1.0)   # pitch ratio
    if abs(ratio - 1) >= 1e-4:
        dst = int(round(SR / ratio))
        if dst != SR and n:
            pieces, n = _resampled(pieces, dst), resampled_len(n, dst)
    # after the resample the sound is len/ratio long; it must end up len/speed long
    factor = ratio / speed
    if abs(factor - 1) >= 1e-3 and n:
        pieces, n = _stretch(pieces, n, factor), int(round(n * factor))
    return pieces, n


def change_speed_pitch(x: np.ndarray, speed: float, semitones: float,
                       tape: bool = False) -> np.ndarray:
    """Speed and pitch at SR. With `tape`, speed also shifts the pitch (and
    `semitones` adds to that)."""
    pieces, _n = _speed_pitch(_pieces(x), len(x), speed, semitones, tape)
    parts = list(pieces)
    return np.concatenate(parts) if parts else np.zeros((0, 2), F32)


# --------------------------------------------------------------------------- render

class _Broken(Exception):
    """A voice effect failed on one channel: render again without it there."""

    def __init__(self, kind: str, chan: int):
        super().__init__(kind, chan)
        self.kind, self.chan = kind, chan


def _effects(pieces, fx: dict, skip: set):
    """The active voice effects over the pieces, then TAIL_S more for their tails,
    trimmed back to where it falls silent. Raises _Broken when one fails (the caller
    starts over with it in `skip`): what was already given out can't be taken back."""
    types = _active_effects(fx)
    if not types:
        yield from pieces
        return
    chain = []
    for t in types:
        cls = voicefx.REGISTRY[t]
        inst = []
        for c in range(2):          # voice effects are mono: one instance per channel
            e = None
            if (t, c) not in skip:
                try:
                    e = cls(SR, fx["effects"][t])
                except Exception:  # noqa: BLE001 - a module effect that can't even start
                    log.exception("sound effect %r failed to start; skipped", t)
            inst.append(e)
        chain.append((t, inst))
    length = [0, None]               # frames of the sound so far, its length once known

    def counted():
        for p in pieces:
            length[0] += len(p)
            yield p
        length[1] = length[0]

    tail_n = int(TAIL_S * SR)
    at = 0
    tail = []
    for x in _rechunk(itertools.chain(counted(), [np.zeros((tail_n, 2), F32)]), CHUNK):
        for t, inst in chain:
            chans = []
            for c, e in enumerate(inst):
                col = np.ascontiguousarray(x[:, c])
                if e is None:
                    chans.append(col)
                    continue
                parts = []
                for i in range(0, len(col), BLOCK):
                    blk = col[i:i + BLOCK]
                    try:
                        yb = np.asarray(e.run(blk, SR), dtype=F32)
                        if yb.shape != blk.shape or not np.all(np.isfinite(yb)):
                            raise ValueError(f"returned {yb.shape} / non-finite audio")
                    except Exception:  # noqa: BLE001 - a broken module effect is skipped
                        log.exception("sound effect %r failed; skipped", t)
                        raise _Broken(t, c) from None
                    parts.append(yb)
                chans.append(np.concatenate(parts))
            x = np.stack(chans, 1)
        # the sound itself goes on; what's past its end is the tail, held to be trimmed
        end = length[1]
        main = len(x) if end is None else max(0, min(len(x), end - at))
        if main:
            yield x[:main]
        if main < len(x):
            tail.append(x[main:])
        at += len(x)
    x = np.concatenate(tail) if tail else np.zeros((0, 2), F32)
    # trim the tail back to where it falls silent: below 1e-3, or to the level the
    # effects settle at once the sound is over (the Radio's static never stops, and
    # would otherwise keep the whole TAIL_S pad). Decaying tails end well below
    # 1e-3 inside the pad, so for them the threshold stays at 1e-3.
    lvl = np.max(np.abs(x), axis=1)
    floor = float(lvl[-int(0.25 * SR):].max()) if len(lvl) else 0.0
    thr = max(1e-3, 2.0 * floor)
    loud = np.flatnonzero(lvl > thr)
    end = int(loud[-1]) + 1 if len(loud) else 0
    if thr > 1e-3 and end < len(x):   # cut into a noise bed: fade it out, no click
        k = min(int(0.02 * SR), len(x) - end)
        x[end:end + k] *= np.linspace(1, 0, k, dtype=F32)[:, None]
        end += k
    if end:
        yield x[:end]


def _render_pieces(data: np.ndarray, f: dict, skip: set):
    """The rendered sound in float32 pieces, clipped, not reversed (f: cleaned)."""
    x = trim(data, f)
    pieces, _n = _speed_pitch(_pieces(x), len(x), f["speed"], f["pitch"], f["tape"])
    sos = eq.design(f["eq"], SR)
    if sos is not None:
        e = dsp.SosRun(sos)
        pieces = (e.run(p) for p in pieces)
    pieces = _effects(pieces, f, skip)
    g = F32(10 ** (f["gain_db"] / 20)) if abs(f["gain_db"]) >= 1e-3 else None
    for p in pieces:
        yield np.clip(p * g if g is not None else p, -1.0, 1.0)


def render_into(data: np.ndarray, fx: dict | None, start, put) -> None:
    """Render a sound piece by piece: start() before the first piece (and again, to
    begin from scratch, if a voice effect fails partway and is left out), then
    put(piece) for each (m, 2) float32 piece, clipped to [-1, 1]. Reverse is left to
    the caller: it needs the end first."""
    f = clean(fx)
    skip: set = set()
    while True:
        start()
        try:
            for p in _render_pieces(data, f, skip):
                put(p)
            return
        except _Broken as b:
            skip.add((b.kind, b.chan))


def render(data: np.ndarray, fx: dict | None) -> np.ndarray:
    """The sound with its effects applied: (n, 2) int16 or float32 at SR in,
    (m, 2) float32 at SR out, clipped to [-1, 1]. Slow for long sounds (the
    stretch): call it off the UI thread. All of it is in memory: a long sound's
    render goes straight into its cache file instead (library.render_cached)."""
    f = clean(fx)
    if is_neutral(f):
        x = trim(data, f)
        return x.astype(F32) * F32(1 / 32767.0) if x.dtype == np.int16 else x.astype(F32)
    parts: list[np.ndarray] = []
    render_into(data, f, parts.clear, parts.append)
    x = np.concatenate(parts) if parts else np.zeros((0, 2), F32)
    if f["reverse"]:
        x = x[::-1]
    return np.ascontiguousarray(x, dtype=F32)


# --------------------------------------------------------------------------- presets

def _preset(**kw) -> dict:
    f = neutral()
    f.update(kw)
    return f


# name -> full settings (applied over everything in the Edit dialog)
PRESETS: dict[str, dict] = {
    "None (original)": neutral(),
    "Deep fried 🔊":     _preset(gain_db=24, eq=[12, 12, 8, 6, 10, 10, 6],
                                effects={"distortion": {"on": True, "drive": 30,
                                                        "tone": 9000, "level": 1}}),
    "Bass boosted":      _preset(gain_db=6, eq=[12, 10, 3, 0, 0, 0, 0]),
    "Slowed + reverb":   _preset(speed=0.8, tape=True,
                                effects={"reverb": {"on": True, "size": 0.85,
                                                    "tone": 5000, "mix": 0.35}}),
    "Nightcore":         _preset(speed=1.25, tape=True),
    "Chipmunk":          _preset(pitch=8),
    "Demon":             _preset(pitch=-8, effects={"reverb": {"on": True, "size": 0.6,
                                                               "tone": 3000, "mix": 0.25}}),
    "Fast (same pitch)": _preset(speed=1.5),
    "Slow-mo (same pitch)": _preset(speed=0.5),
    "Old radio":         _preset(effects={"radio": {"on": True, "low": 400, "high": 3000,
                                                    "drive": 8, "noise": 0.004}}),
    "Reversed":          _preset(reverse=True),
}
