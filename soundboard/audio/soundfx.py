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
     "splices": [[s, e]], parts of the original marked in Edit sound (seconds), in
                          the order they were made; [] = none
     "joined": False,     True: the sound is its splices back to back, and start /
                          end only span them (what older versions play instead)
     "effects": {type: {"on": bool, param: value, ...}},   any voicefx effect,
                                                            modules' included
     "voice": {"name": str,                     a voice laid over the sound, before
               "fx": str, "effects": {...},      its own effects (a copy: editing the
               "ai": {"id", "name", "pitch"}},  saved voice later doesn't change the
                                                 sound); {} = none. The AI voice part
                                                 needs the AI voices add-on
                                                 (speech.soundvoice); without it the
                                                 sound plays without that part
     "live": [{"bass": 8.0, ...}]}              Live controls' effects (livefx) after
                                                 the rest: a stage each time a pad was
                                                 saved from them (with_live)

The trim (or the joined splices) is applied first, to the original, so the file
itself is never cut and the trim can be moved or undone at any time.

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

from soundboard.audio import dsp, eq, livefx
from soundboard import voicefx
from soundboard.audio.engine import SR

log = logging.getLogger(__name__)

F32 = np.float32
SPEED_RANGE = (0.25, 4.0)
PITCH_RANGE = (-24.0, 24.0)
GAIN_RANGE = (-24.0, 36.0)
MAX_TRIM_S = 24 * 3600.0
MIN_TRIM_S = 0.05     # the shortest trimmed sound
MAX_SPLICES = 20      # parts marked on one sound
JOIN_S = 0.004        # each joined splice ramps in and out over this long (no click)
TAIL_S = 3.0          # room left for echo / reverb tails (trimmed back to the sound)
BLOCK = 2048          # effects run in blocks like they do on the mic


def neutral() -> dict:
    return {"speed": 1.0, "pitch": 0.0, "tape": False, "eq": [0.0] * len(eq.BANDS),
            "gain_db": 0.0, "reverse": False, "start": 0.0, "end": 0.0, "splices": [],
            "joined": False, "effects": {}, "voice": {}, "live": []}


MAX_LIVE = 4   # Live controls stages on one sound (a copy of a copy of a copy…)


MAX_VOICE_NAME = 60
AI_PITCH = (-12.0, 12.0)


def _line(text, limit: int = MAX_VOICE_NAME) -> str:
    return " ".join(str(text or "").split())[:limit]


def clean_voice(raw) -> dict:
    """{"name", "effects", "ai"} of a voice laid over a sound: only its effects that are
    on (and known), the AI voice if one is picked; {} if there's nothing left."""
    if not isinstance(raw, dict):
        return {}
    spec = voicefx.clean_spec({"effects": raw.get("effects")})["effects"]
    effects = {t: cfg for t, cfg in spec.items()
               if cfg.get("on") and t in voicefx.REGISTRY}
    got = raw.get("ai")
    ai: dict = got if isinstance(got, dict) else {}
    ai_id = _line(ai.get("id"), 80)
    out: dict = {}
    if ai_id:
        try:
            pitch = float(ai.get("pitch", 0.0))
        except (TypeError, ValueError):
            pitch = 0.0
        pitch = min(max(pitch, AI_PITCH[0]), AI_PITCH[1]) if math.isfinite(pitch) else 0.0
        out["ai"] = {"id": ai_id, "name": _line(ai.get("name")) or ai_id, "pitch": pitch}
    if effects:
        out["effects"] = effects
        if _line(raw.get("fx")):   # the voice changer voice they came from (its card)
            out["fx"] = _line(raw.get("fx"))
    if not out:
        return {}
    return {"name": _line(raw.get("name")), "effects": effects, **out}


def clean_splices(raw) -> list[list[float]]:
    """[[start, end], ...] in range, each at least MIN_TRIM_S long, at most MAX_SPLICES;
    anything else in the list is dropped."""
    out: list[list[float]] = []
    for part in raw if isinstance(raw, list) else []:
        try:
            a, b = (float(v) for v in part)
        except (TypeError, ValueError, OverflowError):
            continue
        if not (math.isfinite(a) and math.isfinite(b)):
            continue
        a, b = sorted((min(max(a, 0.0), MAX_TRIM_S), min(max(b, 0.0), MAX_TRIM_S)))
        if b - a >= MIN_TRIM_S:
            out.append([round(a, 3), round(b, 3)])
        if len(out) == MAX_SPLICES:
            break
    return out


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
    out["splices"] = clean_splices(fx.get("splices"))
    out["joined"] = bool(fx.get("joined", False)) and bool(out["splices"])
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
    out["voice"] = clean_voice(fx.get("voice"))
    live = fx.get("live")
    if isinstance(live, list):
        out["live"] = [st for st in map(livefx.clean, live[:MAX_LIVE]) if st]
    return out


def with_live(fx: dict | None, speed: float, pitch: float, keep: bool,
              live: dict) -> tuple[dict, bool]:
    """A sound's settings with Live controls' speed, pitch and effects on top, the way
    they sound together while it plays: (settings, True if a value had to be pulled
    into this sound's narrower range, Redline's 10x or ±36 st)."""
    f = clean(fx)
    ratio = 2.0 ** (f["pitch"] / 12.0) * (f["speed"] if f["tape"] else 1.0)
    ratio *= 2.0 ** (pitch / 12.0) * (1.0 if keep else speed)
    total = f["speed"] * speed
    if f["tape"] and not keep and abs(f["pitch"]) < 1e-3 and abs(pitch) < 1e-3:
        semis = 0.0   # tape on tape: still a pure resample
    else:
        f["tape"] = False
        semis = 12.0 * math.log2(max(ratio, 1e-6))
    f["speed"] = round(min(max(total, SPEED_RANGE[0]), SPEED_RANGE[1]), 3)
    f["pitch"] = round(min(max(semis, PITCH_RANGE[0]), PITCH_RANGE[1]), 2)
    capped = abs(f["speed"] - total) > 1e-3 or abs(f["pitch"] - semis) > 0.01
    stage = livefx.clean(live)
    if stage:
        f["live"] = (f["live"] + [stage])[-MAX_LIVE:]
    return clean(f), capped


def live_merged(stages: list) -> dict:
    """A sound's Live controls stages as one set of knobs: the dB ones added up, the
    others the strongest (each kept in its knob's range)."""
    out: dict[str, float] = {}
    for q in livefx.PARAMS:
        vals = [float(st[q.key]) for st in stages or [] if q.key in st]
        if vals:
            v = sum(vals) if q.unit.strip() == "dB" else max(vals)
            out[q.key] = min(max(v, q.lo), q.hi)
    return livefx.clean(out)


# Edit sound's effects that Live controls have a knob for: (effect, knob, its amount,
# that amount at the knob's top)
LIVE_LIKE = (("reverb", "reverb", "mix", 1.0), ("echo", "echo", "mix", 1.0),
             ("distortion", "crunch", "drive", 36.0))
NO_LIVE_VIEW: tuple = (1.0, 0.0, {})


def live_view(fx: dict | None) -> tuple[float, float, dict]:
    """What a sound's own effects put on Live controls' knobs: (speed, pitch, knobs),
    the knobs from its Live controls stages and its Reverb, Echo and Distortion."""
    f = clean(fx)
    amounts = live_merged(f["live"])
    for etype, knob, key, top in LIVE_LIKE:
        cfg = f["effects"].get(etype)
        if not cfg or not cfg.get("on") or etype not in voicefx.REGISTRY:
            continue
        default = next((q.default for q in voicefx.REGISTRY[etype].params if q.key == key), 0)
        amount = float(cfg.get(key, default)) / top
        amounts[knob] = min(1.0, amounts.get(knob, 0.0) + amount)
    return round(f["speed"], 3), round(f["pitch"], 2), livefx.clean(amounts)


def _active_effects(fx: dict) -> list[str]:
    return [t for t, cfg in fx["effects"].items() if cfg.get("on") and t in voicefx.REGISTRY]


def _chain(fx: dict) -> list[tuple[str, str, dict]]:
    """(id, effect type, settings) of every effect to run, in order: the voice's (in the
    voice changer's order, as on the mic), then the sound's own."""
    out = []
    voice = fx.get("voice") or {}
    for t in voicefx.REGISTRY:
        cfg = voice.get("effects", {}).get(t)
        if cfg and cfg.get("on"):
            out.append(("voice:" + t, t, cfg))
    return out + [(t, t, fx["effects"][t]) for t in _active_effects(fx)]


def _say(x: np.ndarray, voice: dict, cancel=None, progress=None) -> np.ndarray:
    """(n, 2) audio in the voice's AI voice (as float32, both channels the same: a
    voice is mono). Unchanged if the AI voice can't be used here (logged), or when
    `cancel()` stopped it (the caller sees cancel() too and gives up)."""
    ai = voice.get("ai")
    if not ai or not len(x):
        return x
    from soundboard.speech import soundvoice
    f = x.astype(F32) * F32(1 / 32767.0) if x.dtype == np.int16 else x.astype(F32)
    try:
        y = soundvoice.render(f.mean(axis=1), SR, ai["id"], ai.get("pitch", 0.0),
                              cancel=cancel or (lambda: False), progress=progress)
    except soundvoice.Unavailable as e:
        if cancel is None or not cancel():
            log.warning("AI voice %r left out of a sound: %s", ai.get("id"), e)
        return x
    return np.repeat(y[:, None], 2, axis=1)


def is_trimmed(fx: dict | None) -> bool:
    f = clean(fx)
    return f["start"] >= 1e-3 or f["end"] >= 1e-3 or f["joined"]


def is_neutral(fx: dict | None) -> bool:
    """True if these settings leave the sound exactly as it is."""
    f = clean(fx)
    return (not is_trimmed(f) and abs(f["speed"] - 1) < 1e-3 and abs(f["pitch"]) < 1e-3
            and abs(f["gain_db"]) < 1e-3 and not f["reverse"]
            and eq.design(f["eq"], SR) is None and not _chain(f) and not f["voice"]
            and not f["live"])


def key(fx: dict | None) -> str:
    """Short stable id of the settings ('' for none): the cache file suffix."""
    if is_neutral(fx):
        return ""
    f = clean(fx)
    if not f["joined"]:   # splices only marked change nothing that plays
        f["splices"] = []
    for k in ("start", "end", "splices", "joined", "voice", "live"):   # sounds without
        if not f[k]:                         # these keep the keys (and caches) they had
            del f[k]
    text = json.dumps(f, sort_keys=True)
    return hashlib.blake2b(text.encode(), digest_size=6).hexdigest()


def summary(fx: dict | None) -> str:
    """A few words for a tooltip: '0.8x, -3 st, EQ, +12 dB'."""
    if is_neutral(fx):
        return ""
    f = clean(fx)
    bits = []
    if f["joined"]:
        bits.append(f"{len(f['splices'])} splices joined")
    elif is_trimmed(f):
        bits.append(f"trimmed {fmt_s(f['start'])}–{fmt_s(f['end']) if f['end'] else 'end'}")
    if abs(f["speed"] - 1) >= 1e-3:
        bits.append(f"{round(f['speed'], 3):g}x" + (" tape" if f["tape"] else ""))
    if abs(f["pitch"]) >= 1e-3:
        bits.append(f"{f['pitch']:+g} st")
    if eq.design(f["eq"], SR) is not None:
        bits.append("EQ")
    if abs(f["gain_db"]) >= 1e-3:
        bits.append(f"{f['gain_db']:+g} dB")
    bits += [voicefx.REGISTRY[t].name for t in _active_effects(f)]
    if f["voice"]:
        bits.append(f"voice: {f['voice']['name'] or 'custom'}")
    if f["live"]:
        bits.append("live effects")
    if f["reverse"]:
        bits.append("reversed")
    return ", ".join(bits)


def fmt_s(s: float) -> str:
    """0:03.2 style: minutes, seconds and a tenth (trim points need the tenth)."""
    s = max(0.0, s)
    m, sec = divmod(s, 60)
    return f"{int(m)}:{sec:04.1f}"


def trim(x: np.ndarray, fx: dict | None) -> np.ndarray:
    """The part of (n, 2) audio at SR that the trim keeps (all of it if untrimmed), or
    its joined splices back to back."""
    f = clean(fx)
    if f["joined"]:
        return join(x, f["splices"])
    a = min(int(round(f["start"] * SR)), len(x))
    b = int(round(f["end"] * SR)) if f["end"] else len(x)
    b = min(max(b, a), len(x))
    if b - a < int(MIN_TRIM_S * SR):   # a trim past the end of this sound: ignore it
        return x
    return x[a:b]


def join(x: np.ndarray, splices: list[list[float]]) -> np.ndarray:
    """The parts of (n, 2) audio at SR, back to back in the order given, each ramped in
    and out over JOIN_S where it meets another (a cut mid-wave clicks). The ends of
    the whole stay as cut, like a trim's. All of it if no part falls in the sound."""
    parts = []
    for a, b in splices:
        a, b = min(int(round(a * SR)), len(x)), min(int(round(b * SR)), len(x))
        if b - a >= int(MIN_TRIM_S * SR):
            parts.append(x[a:b])
    if not parts:
        return x
    if len(parts) == 1:
        return parts[0]
    ramp = np.linspace(0.0, 1.0, int(JOIN_S * SR), endpoint=False, dtype=F32)[:, None]
    n = len(ramp)
    out = []
    for i, part in enumerate(parts):
        y = part.astype(F32) if part.dtype != F32 else part.copy()
        if i:
            y[:n] *= ramp[:len(y)]
        if i < len(parts) - 1:
            y[-n:] *= ramp[::-1][-len(y[-n:]):]
        out.append(y)
    y = np.concatenate(out)
    if x.dtype == np.int16:
        return np.round(y).astype(np.int16)
    return y


def played_length(fx: dict | None, length: float) -> float:
    """How long the part of a `length`-second sound that plays is, before speed."""
    f = clean(fx)
    if f["joined"]:
        return sum(min(b, length) - min(a, length) for a, b in f["splices"])
    end = f["end"] if 0 < f["end"] <= length else length
    return max(0.0, end - min(f["start"], end))


def preview_part(x: np.ndarray, fx: dict | None, seconds: float) -> tuple[np.ndarray, dict]:
    """(the part of `x` that plays first with these effects, about `seconds` of it as
    heard, the effects to render that part with): a long sound's preview renders just
    this, not the whole sound (a 2-hour song's pitch shift took minutes before the
    preview played). Reversed, the end plays first."""
    f = clean(fx)
    part = trim(x, f)
    n = max(1, int(seconds * f["speed"] * SR))
    part = part[-n:] if f["reverse"] else part[:n]
    return part, dict(f, start=0.0, end=0.0, splices=[], joined=False)


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
    spec = _chain(fx)
    if not spec and not fx["live"]:
        yield from pieces
        return
    stages = [(livefx.LiveFx(SR), st) for st in fx["live"]]
    chain = []
    for kind, t, cfg in spec:
        cls = voicefx.REGISTRY[t]
        inst = []
        for c in range(2):          # voice effects are mono: one instance per channel
            e = None
            if (kind, c) not in skip:
                try:
                    e = cls(SR, cfg)
                except Exception:  # noqa: BLE001 - a module effect that can't even start
                    log.exception("sound effect %r failed to start; skipped", kind)
            inst.append(e)
        chain.append((kind, inst))
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
        for lf, st in stages:   # Live controls' effects, in blocks as on the sounds bus
            x = np.concatenate([lf.process(np.ascontiguousarray(x[i:i + BLOCK]), st)
                                for i in range(0, len(x), BLOCK)]) if len(x) else x
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


# how long each part takes, per second of sound, to split one progress bar between
# them: the AI voice ~0.3 s (a song's took 68 s for 240 s), the rest ~0.025 s
AI_COST, FX_COST = 12.0, 1.0


def _render_pieces(data: np.ndarray, f: dict, skip: set, cancel=None, progress=None):
    """The rendered sound in float32 pieces, clipped, not reversed (f: cleaned).
    progress(frac) now and then, 0..1 over the whole render."""
    ai = AI_COST if (f["voice"] or {}).get("ai") else 0.0
    share = ai / (ai + FX_COST)
    said = None   # the AI voice's part of the bar
    if progress is not None and ai:
        said = lambda k, progress=progress: progress(share * k)  # noqa: E731
    x = _say(trim(data, f), f["voice"], cancel, said)
    pieces, n = _speed_pitch(_pieces(x), len(x), f["speed"], f["pitch"], f["tape"])
    sos = eq.design(f["eq"], SR)
    if sos is not None:
        e = dsp.SosRun(sos)
        pieces = (e.run(p) for p in pieces)
    pieces = _effects(pieces, f, skip)
    g = F32(10 ** (f["gain_db"] / 20)) if abs(f["gain_db"]) >= 1e-3 else None
    done = 0
    for p in pieces:
        if progress is not None:
            done += len(p)
            progress(share + (1 - share) * min(1.0, done / max(1, n)))
        yield np.clip(p * g if g is not None else p, -1.0, 1.0)


def render_into(data: np.ndarray, fx: dict | None, start, put, cancel=None,
                progress=None) -> None:
    """Render a sound piece by piece: start() before the first piece (and again, to
    begin from scratch, if a voice effect fails partway and is left out), then
    put(piece) for each (m, 2) float32 piece, clipped to [-1, 1]. Reverse is left to
    the caller: it needs the end first. cancel(): asked by the AI voice, which is one
    long step (put() is where the caller gives up); progress(frac): see _render_pieces."""
    f = clean(fx)
    skip: set = set()
    while True:
        start()
        try:
            for p in _render_pieces(data, f, skip, cancel, progress):
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
