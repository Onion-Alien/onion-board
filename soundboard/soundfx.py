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
import json
import logging
import math

import numpy as np

from soundboard import eq, voicefx
from soundboard.engine import SR, resample

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


# --------------------------------------------------------------------------- stretch

def stretch(x: np.ndarray, factor: float, n_fft: int = 2048, hop: int = 512,
            chunk: int = 64) -> np.ndarray:
    """Make (n, 2) float32 audio `factor` times longer without changing its pitch.

    Phase vocoder with identity phase locking (each bin keeps its phase relation
    to the nearest spectral peak), which keeps it from sounding washed out. The
    phase is taken from the mid (L+R) signal and shared by both channels, so the
    stereo image doesn't smear. Frames are processed `chunk` at a time, and each
    stretch of the overlap-add is written to the output as soon as no later frame
    can reach it, so memory beyond the output itself stays bounded on long sounds."""
    n = len(x)
    if n == 0 or abs(factor - 1.0) < 1e-3:
        return np.ascontiguousarray(x, dtype=F32)
    out_len = int(round(n * factor))
    ha = hop / factor                        # analysis hop (fractional)
    win = np.hanning(n_fft + 1)[:-1].astype(F32)
    pad = np.zeros((n_fft, 2), F32)
    xp = np.concatenate([pad, x.astype(F32, copy=False), pad])
    n_frames = int(np.ceil((n + n_fft) / ha)) + 1
    starts = np.minimum(np.round(np.arange(n_frames) * ha).astype(np.int64), len(xp) - n_fft)
    lead = int(round(n_fft * factor))         # the zero padding, stretched
    res = np.zeros((out_len, 2), F32)
    # overlap-add accumulators for one chunk of frames plus the overlap it leaves;
    # acc[0] is output-timeline position `base` (res[0] is `lead`)
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
        frames = xp[st[:, None] + idx]                     # (k, n_fft, 2)
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
        # everything before the next frame's start is final: normalise and flush it
        base = c0 * hop
        done = k * hop if c0 + k < n_frames else k * hop + n_fft
        w = wacc[:done]
        w[w < 1e-3] = 1.0
        a, b = max(base, lead), min(base + done, lead + out_len)
        if a < b:
            res[a - lead:b - lead] = acc[a - base:b - base] / w[a - base:b - base, None]
        keep = len(acc) - done
        acc[:keep] = acc[done:].copy()
        acc[keep:] = 0.0
        wacc[:keep] = wacc[done:].copy()
        wacc[keep:] = 0.0
    return res


def change_speed_pitch(x: np.ndarray, speed: float, semitones: float,
                       tape: bool = False) -> np.ndarray:
    """Speed and pitch at SR. With `tape`, speed also shifts the pitch (and
    `semitones` adds to that)."""
    ratio = 2.0 ** (semitones / 12.0) * (speed if tape else 1.0)   # pitch ratio
    y = x
    if abs(ratio - 1) >= 1e-4:
        y = resample(np.ascontiguousarray(x, dtype=F32), SR, int(round(SR / ratio)))
    # after the resample the sound is len/ratio long; it must end up len/speed long
    factor = ratio / speed
    if abs(factor - 1) >= 1e-3:
        y = stretch(y, factor)
    return y


# --------------------------------------------------------------------------- render

def _run_effects(x: np.ndarray, fx: dict) -> np.ndarray:
    types = _active_effects(fx)
    if not types:
        return x
    x = np.concatenate([x, np.zeros((int(TAIL_S * SR), 2), F32)])
    for t in types:
        cls = voicefx.REGISTRY[t]
        cfg = fx["effects"][t]
        chans = []
        for c in range(2):          # voice effects are mono: one instance per channel
            src = np.ascontiguousarray(x[:, c])
            parts = []
            try:
                e = cls(SR, cfg)
            except Exception:  # noqa: BLE001 - a module effect that can't even start
                log.exception("sound effect %r failed to start; skipped", t)
                chans.append(src)
                continue
            for i in range(0, len(src), BLOCK):
                blk = src[i:i + BLOCK]
                try:
                    yb = np.asarray(e.run(blk, SR), dtype=F32)
                    if yb.shape != blk.shape or not np.all(np.isfinite(yb)):
                        raise ValueError(f"returned {yb.shape} / non-finite audio")
                except Exception:  # noqa: BLE001 - a broken module effect is skipped
                    log.exception("sound effect %r failed; skipped", t)
                    parts = None
                    break
                parts.append(yb)
            chans.append(np.concatenate(parts) if parts is not None else src)
        x = np.stack(chans, 1)
    # trim the tail back to where it falls silent: below 1e-3, or to the level the
    # effects settle at once the sound is over (the Radio's static never stops, and
    # would otherwise keep the whole TAIL_S pad). Decaying tails end well below
    # 1e-3 inside the pad, so for them the threshold stays at 1e-3.
    lvl = np.max(np.abs(x), axis=1)
    floor = float(lvl[-int(0.25 * SR):].max()) if len(lvl) else 0.0
    thr = max(1e-3, 2.0 * floor)
    loud = np.flatnonzero(lvl > thr)
    end = max(int(loud[-1]) + 1 if len(loud) else 0, len(x) - int(TAIL_S * SR))
    if thr > 1e-3 and end < len(x):   # cut into a noise bed: fade it out, no click
        k = min(int(0.02 * SR), len(x) - end)
        x[end:end + k] *= np.linspace(1, 0, k, dtype=F32)[:, None]
        end += k
    return np.ascontiguousarray(x[:end])


def render(data: np.ndarray, fx: dict | None) -> np.ndarray:
    """The sound with its effects applied: (n, 2) int16 or float32 at SR in,
    (m, 2) float32 at SR out, clipped to [-1, 1]. Slow for long sounds (the
    stretch): call it off the UI thread."""
    f = clean(fx)
    x = trim(data, f)
    x = x.astype(F32) * F32(1 / 32767.0) if x.dtype == np.int16 else x.astype(F32)
    if is_neutral(f):
        return x
    x = change_speed_pitch(x, f["speed"], f["pitch"], f["tape"])
    if eq.design(f["eq"], SR) is not None:
        x = eq.EQ(SR).process(np.ascontiguousarray(x), f["eq"])
    x = _run_effects(x, f)
    if abs(f["gain_db"]) >= 1e-3:
        x = x * F32(10 ** (f["gain_db"] / 20))
    if f["reverse"]:
        x = x[::-1]
    return np.ascontiguousarray(np.clip(x, -1.0, 1.0, out=x), dtype=F32)   # x is ours


# --------------------------------------------------------------------------- presets

def _preset(**kw) -> dict:
    f = neutral()
    f.update(kw)
    return f


# name -> full settings (applied over everything in the Edit dialog)
PRESETS: dict[str, dict] = {
    "None (original)": neutral(),
    "Ear rape 🔊":       _preset(gain_db=24, eq=[12, 12, 8, 6, 10, 10, 6],
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
