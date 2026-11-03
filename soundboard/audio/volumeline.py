"""A volume line: a sound's (SoundMeta.volume_line) or a splice's (its part's "line"),
drawn over its waveform in Edit sound and dragged like an automation clip.

Stored as points [seconds, level, curve], in time order:
- the first and the last are the line's ends: always at its start and its end (the
  trim handles, a splice's edges), whatever their seconds say; only their level counts;
- the ones in between are kept from the end they're nearer to: seconds after the start
  (>= 0) or before the end (< 0), so moving a trim handle takes a fade with it;
- level 0..1 (0 silence, 1 as loud as the sound);
- curve -1..1 bends the part from that point to the next (0: a straight line).

[] is "no line of its own": the plain fades (fade_in / fade_out) play instead."""
from __future__ import annotations

import math

import numpy as np

BEND = 2.5          # a curve of 1 raises the part's 0..1 to the power 2 ** BEND
MIN_GAP_S = 0.01    # points closer than this in time would make a step


def _num(v, lo: float, hi: float, none: float) -> float:
    try:
        v = float(v)
    except (TypeError, ValueError, OverflowError):
        return none
    return round(min(max(v, lo), hi), 3) if math.isfinite(v) else none


def clean(raw) -> list[list[float]]:
    """A stored line, in range ([] when it's unreadable or plain: flat at full)."""
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return []
    out = []
    for p in raw:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            return []
        c = p[2] if len(p) > 2 else 0.0
        out.append([_num(p[0], -86400.0, 86400.0, 0.0), _num(p[1], 0.0, 1.0, 1.0),
                    _num(c, -1.0, 1.0, 0.0)])
    out[0][0] = out[-1][0] = 0.0
    if len(out) == 2 and all(lv >= 0.999 for _t, lv, _c in out):
        return []   # flat at full: plain
    return out


def from_fades(fade_in: float, fade_out: float,
               levels=(0.0, 1.0, 1.0, 0.0)) -> list[list[float]]:
    """The line the plain fades make (or an older version's four levels: where the fade
    in starts, its top, the fade out's top, where it ends)."""
    lo_in, top_in, top_out, lo_out = (float(x) for x in levels)
    out = [[0.0, lo_in if fade_in > 0 else top_in, 0.0]]
    if fade_in > 0:
        out.append([round(float(fade_in), 3), top_in, 0.0])
    if fade_out > 0:
        out.append([-round(float(fade_out), 3), top_out, 0.0])
    out.append([0.0, lo_out if fade_out > 0 else top_out, 0.0])
    return out


def points(line, length: float) -> list[list[float]]:
    """The stored line as [seconds from its start, level, curve] over `length` seconds:
    its ends at 0 and `length`, the points between in time order (one past either
    end, or on it, left out)."""
    if not line:
        return [[0.0, 1.0, 0.0], [max(length, 0.0), 1.0, 0.0]]
    length = max(length, 0.0)
    mid = []
    for t, lv, c in line[1:-1]:
        at = t if t >= 0 else length + t
        if MIN_GAP_S <= at <= length - MIN_GAP_S:
            mid.append([at, lv, c])
    mid.sort(key=lambda p: p[0])
    return [[0.0, line[0][1], line[0][2]], *mid, [length, line[-1][1], 0.0]]


def store(pts, length: float) -> list[list[float]]:
    """Points from `points` (dragged) back to a stored line: each one between the ends
    kept from the end it's nearer to. [] when it's flat at full."""
    out = []
    last = len(pts) - 1
    for k, (t, lv, c) in enumerate(pts):
        if k in (0, last):
            at = 0.0
        else:
            at = t if t <= length / 2 else -(length - t)
        out.append([round(at, 3), round(min(max(lv, 0.0), 1.0), 3),
                    round(min(max(c, -1.0), 1.0), 3)])
    return clean(out)


def shape(u, curve: float):
    """0..1 along a part to 0..1 of the way from its level to the next one's."""
    return u ** (2.0 ** (curve * BEND)) if curve else u


def gain(line, at: np.ndarray, length: float) -> np.ndarray:
    """The line's level (float32) at each of `at` (seconds from its start) over a sound
    `length` seconds long."""
    return gain_of(points(line, length), at)


def gain_of(pts, at: np.ndarray) -> np.ndarray:
    """gain() of points already placed (`points`)."""
    ts = np.array([p[0] for p in pts], np.float64)
    lv = np.array([p[1] for p in pts], np.float64)
    at = np.clip(np.asarray(at, np.float64), 0.0, ts[-1])
    i = np.clip(np.searchsorted(ts, at, side="right") - 1, 0, len(ts) - 2)
    span = ts[i + 1] - ts[i]
    u = np.clip((at - ts[i]) / np.where(span > 0, span, 1.0), 0.0, 1.0)
    for k, (_t, _lv, c) in enumerate(pts[:-1]):
        if c:
            on = i == k
            u[on] = shape(u[on], c)
    return (lv[i] + (lv[i + 1] - lv[i]) * u).astype(np.float32)


def level_at(pts, t: float) -> float:
    """One level, of points already placed (`points`)."""
    return float(gain_of(pts, np.array([t]))[0])


def fades(line, length: float) -> tuple[float, float]:
    """The fade in and fade out a line makes (seconds; 0: none): from its start up to
    its first point when the line rises there, and from its last point down to its
    end when it falls there. A loop and a stop use these."""
    pts = points(line, length)
    fi = pts[1][0] if len(pts) > 2 and pts[0][1] < pts[1][1] - 1e-3 else 0.0
    fo = (length - pts[-2][0]) if len(pts) > 2 and pts[-1][1] < pts[-2][1] - 1e-3 else 0.0
    return round(fi, 2), round(max(fo, 0.0), 2)


def with_fade(line, which: str, seconds: float, length: float,
              plain: tuple[float, float] = (0.0, 0.0)) -> list[list[float]]:
    """The line with its fade in (`which` "in") or fade out ("out") set to `seconds`
    (0: none), as the Fade sliders set it: the point at the fade's top moves there, or
    one is put there (the end then drops to silence); none, and the end comes up to
    that point's level. `plain`: the fades a line of [] has."""
    pts = points(line or from_fades(*plain), length)
    seconds = min(max(float(seconds), 0.0), length)
    end, top = (0, 1) if which == "in" else (len(pts) - 1, len(pts) - 2)
    has = len(pts) > 2 and pts[end][1] < pts[top][1] - 1e-3
    if seconds <= 0:
        if has:
            pts[end][1] = pts[top][1]
            if which == "in":
                pts[0][2] = pts[1][2]
            del pts[top]
        return store(pts, length)
    at = seconds if which == "in" else length - seconds
    if has:   # its top point moves, not past the next one
        if which == "in":
            nxt = pts[2][0] if len(pts) > 3 else length
            pts[1][0] = min(at, nxt - MIN_GAP_S)
        else:
            prev = pts[-3][0] if len(pts) > 3 else 0.0
            pts[-2][0] = max(at, prev + MIN_GAP_S)
        return store(pts, length)
    if len(pts) > 2:   # (past the nearest point: just this side of it)
        at = (min(at, pts[1][0] - MIN_GAP_S) if which == "in"
              else max(at, pts[-2][0] + MIN_GAP_S))
    lv = max(level_at(pts, at), pts[end][1]) or 1.0
    if which == "in":
        pts.insert(1, [at, lv, pts[0][2]])
        pts[0][1], pts[0][2] = 0.0, 0.0
    else:
        pts.insert(len(pts) - 1, [at, lv, 0.0])
        pts[-1][1] = 0.0
    return store(pts, length)
