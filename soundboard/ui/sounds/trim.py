"""The Effects tab's trim control: the sound's waveform with a start and an end
handle to drag, and two boxes for exact times. Only the part between them plays;
the file itself is never cut (the trim is part of the sound's effects, see
soundfx.trim). Edit sound's Advanced view shows the same control big (`set_big`):
a time ruler, zoom, and the volume line (an automation clip's: see volumeline), and
splices: parts marked
with two clicks each while Cut is on, numbered, that can be joined to play back to
back (soundfx.join). On the big one the time ruler is a seek bar (a click or a drag
moves the playing sound there) and the playhead can be dragged along too; a click on
the wave itself only selects (a splice, or the whole sound), it never moves the playhead."""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QRegion, QValidator
from PySide6.QtWidgets import (QDoubleSpinBox, QHBoxLayout, QLabel, QMenu, QPushButton,
                               QToolTip, QVBoxLayout, QWidget)

from soundboard.audio import soundfx, volumeline
from soundboard.core import usage
from soundboard.ui.kit import theme
from soundboard.ui.kit.wheelguard import no_wheel
from soundboard.i18n import _
from soundboard.ui.kit.pixels import snap_to_pixels

HANDLE_PX = 8   # how close to a handle a press grabs it
PLAY_PX = 14    # ...and to the playhead: it moves while the pointer aims at it
PLAY_DRAG_PX = 4   # the big one's playhead: moved this far it's a drag, less is a click
BIG_H = 110     # the big waveform's least height (Advanced): on a short screen it gives
                # the columns under it room (they scroll); taller, it takes its share
RULER_H = 20    # its time ruler
MAX_ZOOM = 16   # the big one zooms in to a sixteenth of the sound
COL_PX = 2      # the big one draws a bar every 2 px
BADGE_H = 18    # a splice's number badge
LEVEL_TOP = 8   # full volume on the level line: this far under the ruler
POINT_R = 5     # a level point's radius
POINT_GRAB = 10  # how near a press must be to grab one
LINE_GRAB = 6   # ...and to the line: a press there puts a point there
BEND_PX = 120   # a bend circle dragged this far up or down: a full curve
BEND_R = 3.5    # a bend circle's radius
BEND_GRAB = 7   # ...and how near a press must be to grab it (nearer the line: a new point)
KNOB_H = 22     # a trim handle's grip, at the bottom (the volume line's ends are above)
MENU_PX = 4     # a right press that moves less than this is a click (the menu), not a drag
# ruler steps (seconds): the first that leaves room between its labels
STEPS = (0.01, 0.02, 0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600)


def ruler_text(t: float, step: float) -> str:
    """0:03 for whole-second steps, 0:03.5 / 0:03.25 for finer ones."""
    m, s = divmod(max(t, 0.0) + 1e-9, 60)
    if step >= 1:
        return f"{int(m)}:{int(s):02d}"
    places = 1 if round(step * 10, 6) == int(round(step * 10, 6)) else 2
    return f"{int(m)}:{s:0{3 + places}.{places}f}"


def line_tip() -> str:
    """How the volume line works (the waveform's tooltip, and the hint under it)."""
    return _("Click the line to add a point. Right-click a point to remove it.")


def splice_tip(i: int, a: float, b: float) -> str:
    return _("Splice {n}: {start} to {end}", n=i + 1, start=soundfx.fmt_s(a),
             end=soundfx.fmt_s(b))


class Waveform(QWidget):
    """Peaks with two handles. `moved(start, end)` in seconds (end = length for 'the
    end') while a handle is dragged. The big one also has splices: `spliced()` when
    one is made, moved or removed, or its fades dragged; and `scrubbed(t, done)` while
    its ruler or playhead is dragged to `t` seconds (`done` on letting go). A click on a
    splice picks it (`picked(i)`, None: none), a right-click asks for its menu
    (`menu_asked(i, global pos)`). Each splice has a level line over its waveform, its
    points dragged for its fades and volume (in `parts`, `level_moved(i)`); the sound
    has one too (`lined(line, fade_in, fade_out)`, SoundMeta.volume_line). Like an
    automation clip's: a press on the line puts a point there, points drag anywhere
    between their neighbours (the ends up and down), the circle halfway along a slope
    curves it, a right-click on a point takes it out."""
    moved = Signal(float, float)
    spliced = Signal()
    scrubbed = Signal(float, bool)
    picked = Signal(object)
    menu_asked = Signal(int, QPoint)
    lined = Signal(list, float, float)   # the sound's volume line, and the fades it makes
    level_moved = Signal(int)   # a splice's level line dragged (its volume may have changed)

    def __init__(self, peaks: np.ndarray | Sequence[float], length: float):
        super().__init__()
        self.peaks = peaks
        self.length = max(length, 0.001)
        self.start, self.end = 0.0, self.length
        self.play: float | None = None   # where it's playing now (seconds), None: it isn't
        # a handle, (splice, side) or "play": the ruler or the playhead
        self._drag: str | tuple[int, int] | None = None
        self._grab: tuple[float, float] | None = None   # (x, view start): dragging it along
        self.big = False
        self.fine: np.ndarray | None = None   # more peaks, for the big one (set_fine)
        self.view = (0.0, self.length)        # the part the big one shows (zoom)
        self._zoom_counted = False            # zoomed in or out yet (counted once)
        self.fades = (0.0, 0.0)               # fade in / out (s): the line, when it has none
        self.line: list[list[float]] = []     # the sound's volume line (SoundMeta.volume_line)
        self._bend0: tuple[float, float] | None = None   # a bend's press: (y, its curve)
        self._ghost: QPointF | None = None    # where a press would put a point
        self._menu: QMenu | None = None       # a point's right-click menu
        self._rpoint: tuple | None = None     # (line, point, where): right-pressed on it
        self.splices: list[list[float]] = []  # [[start, end], ...] in seconds, made in order
        self.parts: list[dict] = []           # each one's own settings (soundfx "parts")
        self.selected: int | None = None      # the splice picked: the panels edit it
        self._rpress: QPointF | None = None   # a right press, until it's a click or a drag
        self._press: QPointF | None = None    # where the left button went down
        self._play_press: QPointF | None = None   # ...on the big one's playhead (not yet a drag)
        self.joined = False                   # they play back to back (not the handles)
        self.cutting = False                  # Cut is on: two clicks make a splice
        self._first: float | None = None      # where the splice being made starts
        self._at: float | None = None         # the pointer, while making one
        self._hover: int | None = None        # the splice under the pointer
        self.setMinimumHeight(70)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.setMouseTracking(True)   # (the pointer over the handles and playhead)
        self.setToolTip(_("Drag the handles to cut off the start and end. Only the part "
                          "between them plays.") + " " + line_tip())

    def set_peaks(self, peaks: np.ndarray | Sequence[float]):
        self.peaks = peaks
        self.update()

    def set_range(self, start: float, end: float):
        self.start, self.end = start, end
        self.update()

    def set_play(self, t: float | None):
        if self._drag == "play":
            return   # it's being dragged: where the pointer is, not where it plays
        t = None if t is None else min(max(t, 0.0), self.length)
        if t != self.play:
            self.play = t
            self.update()

    def set_big(self, on: bool):
        """Advanced's big waveform (ruler, zoom, fades) or the tab's small one."""
        self.big = on
        if not on:
            self.set_cutting(False)
            self.pick(None)   # (Simple has no panels of a splice's own)
        self.view = (0.0, self.length)
        self.setMinimumHeight(BIG_H if on else 70)
        self.setToolTip(_("Drag the handles to cut off the start and end. Click or drag "
                          "the time ruler, or drag the playhead, to move where it plays. "
                          "Ctrl+scroll zooms. Drag with the right mouse button, or "
                          "Shift+scroll, to move along.") + " " +
                        _("Scroll to zoom. Click a splice for effects of its own, "
                          "right-click it for more.") + " " + line_tip()
                        if on else
                        _("Drag the handles to cut off the start and end. Only the part "
                          "between them plays.") + " " + line_tip())
        self.update()

    def set_fine(self, peaks: np.ndarray | None):
        """Peaks enough to zoom into (the big one draws these when it has them)."""
        self.fine = None if peaks is None or not len(peaks) else np.asarray(peaks, np.float32)
        self.update()

    def set_cutting(self, on: bool):
        """Cut on: a click marks where a splice starts, the next where it ends (a click
        inside a splice still picks it, and its level dots still drag)."""
        self.cutting = on
        self._first = None
        self.setCursor(Qt.CursorShape.IBeamCursor if on else Qt.CursorShape.SizeHorCursor)
        self.update()

    def set_splices(self, splices: list[list[float]], joined: bool,
                    parts: list[dict] | None = None):
        self.splices = [list(sp) for sp in splices]
        got = parts or []
        self.parts = [dict(got[i]) if i < len(got) else {} for i in range(len(self.splices))]
        self.joined = joined and bool(self.splices)
        self._hover = None
        self.update()
        self.spliced.emit()
        if self.selected is not None:   # (Undo: the same one if it's still there)
            self.pick(self.selected if self.selected < len(self.splices) else None, True)

    def remove_splice(self, i: int):
        if 0 <= i < len(self.splices):
            del self.splices[i]
            del self.parts[i]
            self.joined = self.joined and bool(self.splices)
            self._hover = None
            sel = self.selected   # (first: the panels mustn't save into the wrong one)
            if sel is not None and sel >= i:   # it, gone; or a later one, one place on
                self.pick(None if sel == i else sel - 1, True)
            self.update()
            self.spliced.emit()

    def pick(self, i: int | None, again: bool = False):
        """Splice `i` picked (None: the whole sound): `picked` tells the panels.
        `again`: tell them even when it's the same (its place or settings changed)."""
        if i != self.selected or again:
            self.selected = i
            self.update()
            self.picked.emit(i)

    FADE_KEYS = ("fade_in", "fade_out", "fade_in_from", "fade_out_to", "fade_in_to",
                 "fade_out_from", "volume", "line")

    def has_own(self, i: int) -> bool:
        """Splice `i` has settings of its own, beyond its volume line (fades, volume)."""
        p = self.parts[i] if 0 <= i < len(self.parts) else {}
        return any(k not in self.FADE_KEYS for k in p)

    def clear_own(self):
        """Every splice back to what it is plain (its volume line stays: that's the line's
        to change, on the waveform)."""
        self.parts = [{k: v for k, v in p.items() if k in self.FADE_KEYS} for p in self.parts]
        self.update()

    def part_fades(self, i: int) -> tuple[float, float]:
        if not 0 <= i < len(self.splices):
            return 0.0, 0.0
        a, b = self.splices[i]
        return volumeline.fades(soundfx.part_line(self.parts[i]), b - a)

    def set_part_fade(self, i: int, key: str, seconds: float):
        """Splice `i`'s "fade_in" or "fade_out" set to `seconds` (0: off): its volume
        line's fade (volumeline.with_fade)."""
        if not 0 <= i < len(self.splices):
            return
        a, b = self.splices[i]
        line = volumeline.with_fade(soundfx.part_line(self.parts[i]), key[5:], seconds, b - a)
        self._set_part_line(i, line)

    def _set_part_line(self, i: int, line: list):
        """Splice `i`'s volume line, and the fades it makes (what older versions read)."""
        a, b = self.splices[i]
        p = {k: v for k, v in self.parts[i].items() if k not in self.FADE_KEYS or k == "volume"}
        if line:
            p["line"] = line
            p["fade_in"], p["fade_out"] = volumeline.fades(line, b - a)
        self.parts[i] = soundfx.clean_part(p)
        self.update()
        self.level_moved.emit(i)
        self.spliced.emit()

    def set_line(self, line: list, fades: tuple[float, float]):
        """The sound's volume line (SoundMeta.volume_line; []: its plain `fades`)."""
        line = [list(pt) for pt in line]
        if (line, tuple(fades)) != (self.line, self.fades):
            self.line, self.fades = line, tuple(fades)
            self.update()

    def _top(self) -> float:
        return RULER_H if self.big else 0.0

    def _level_y(self, level: float) -> float:
        """Where a level (0 silence .. 1 full volume) is drawn: the middle line up to
        just under the ruler (the top), above the loudest peaks."""
        r = QRectF(self.rect()).adjusted(0.5, 0.5 + self._top(), -0.5, -0.5)
        mid, top = r.center().y(), r.top() + LEVEL_TOP
        return mid - min(max(level, 0.0), 1.0) * (mid - top)

    def _level_of(self, y: float) -> float:
        r = QRectF(self.rect()).adjusted(0.5, 0.5 + self._top(), -0.5, -0.5)
        mid, top = r.center().y(), r.top() + LEVEL_TOP
        return min(max((mid - y) / max(mid - top, 1.0), 0.0), 1.0)

    def _span(self, i: int) -> tuple[float, float]:
        """Where line `i` runs (seconds): splice `i`, or (-1) the sound's handles."""
        if i < 0:
            return self.start, self.end
        a, b = self.splices[i]
        return a, b

    def _vol(self, i: int) -> float:
        """How loud line `i` is drawn at full (a splice's own volume, up to full)."""
        if i < 0:
            return 1.0
        return min(float(self.parts[i].get("volume", 1.0)), 1.0)

    def _env(self, i: int) -> list[list[float]]:
        """Line `i`'s points [seconds into the sound, level, curve] (i = -1: the
        sound's, between its handles; its fades' when it has none of its own)."""
        a, b = self._span(i)
        if i < 0:
            line = self.line or volumeline.from_fades(*self.fades)
        else:
            line = soundfx.part_line(self.parts[i])
        return [[a + t, lv, c] for t, lv, c in volumeline.points(line, b - a)]

    def _set_env(self, i: int, pts: list[list[float]]):
        """Line `i` dragged to these points (as _env gives them)."""
        a, b = self._span(i)
        line = volumeline.store([[t - a, lv, c] for t, lv, c in pts], b - a)
        if i >= 0:
            self._set_part_line(i, line)
            return
        self.line = line
        self.fades = volumeline.fades(line, b - a) if line else (0.0, 0.0)
        self.update()
        self.lined.emit(line, *self.fades)

    def _env_lines(self) -> list[int]:
        """Which volume lines show: each splice's (on the big one), and the sound's
        while its handles play (joined, the sound plays its splices)."""
        own = list(range(len(self.splices))) if self.big else []
        return own + ([] if self.joined else [-1])

    def _loaded(self) -> bool:
        return self.fine is not None or bool(len(self.peaks))

    def _env_points(self) -> list[tuple[QPointF, tuple]]:
        """(where, what) of every point that can be dragged: ("env", line, k) for its
        points, ("bend", line, k) for the circle halfway along the part after point k
        (where that part slopes)."""
        out: list[tuple[QPointF, tuple]] = []
        if not self._loaded() or self._first is not None:
            return out
        for i in self._env_lines():
            env, vol = self._env(i), self._vol(i)
            for k, (t, lv, _c) in enumerate(env):
                out.append((QPointF(self._x(t), self._level_y(lv * vol)), ("env", i, k)))
            for k in range(len(env) - 1):
                (ta, la, _c), (tb, lb, _d) = env[k], env[k + 1]
                if abs(lb - la) < 0.02 or self._x(tb) - self._x(ta) < 4 * POINT_GRAB:
                    continue   # flat, or too short to bend by hand
                tm = (ta + tb) / 2
                lm = volumeline.level_at([[t - ta, lv, c] for t, lv, c in env[k:k + 2]],
                                         tm - ta)
                out.append((QPointF(self._x(tm), self._level_y(lm * vol)), ("bend", i, k)))
        return out

    def _env_at(self, x: float, y: float) -> tuple | None:
        """The point (or bend circle) under (x, y), the nearest; None: none."""
        if self._in_ruler(y):
            return None
        best, near = None, float(POINT_GRAB)
        for pt, what in self._env_points():
            d = ((pt.x() - x) ** 2 + (pt.y() - y) ** 2) ** 0.5
            if d < near and (what[0] == "env" or d < BEND_GRAB):
                best, near = what, d
        return best

    def _on_line(self, x: float, y: float) -> tuple[int, float] | None:
        """(line, seconds) where (x, y) is on a volume line, away from its points:
        a press there puts a point there."""
        if self._in_ruler(y) or not self._loaded() or self._first is not None:
            return None
        t = self._t(x)
        for i in reversed(self._env_lines()):
            a, b = self._span(i)
            if not a < t < b or (i < 0 and self.big and self._splice_at(t) is not None):
                continue
            env = self._env(i)
            lv = volumeline.level_at([[pt[0] - a, pt[1], pt[2]] for pt in env], t - a)
            if abs(self._level_y(lv * self._vol(i)) - y) <= LINE_GRAB:
                return i, t
        return None

    def _add_point(self, i: int, t: float) -> tuple:
        """A point put on line `i` at `t`, where the line is: ("env", i, k) to drag."""
        env = self._env(i)
        a = env[0][0]
        lv = volumeline.level_at([[pt[0] - a, pt[1], pt[2]] for pt in env], t - a)
        k = next(k for k in range(1, len(env)) if env[k][0] > t)
        env.insert(k, [t, lv, env[k - 1][2]])
        self._set_env(i, env)
        usage.used("edit-wave-point")
        # (stored and read back: the same place, in time order)
        got = self._env(i)
        return ("env", i, min(range(len(got)), key=lambda j: abs(got[j][0] - t)))

    def _drop_point(self, i: int, k: int):
        env = self._env(i)
        if 0 < k < len(env) - 1:
            del env[k]
            self._set_env(i, env)

    def _drag_env(self, what: tuple, x: float, y: float):
        """A point dragged to (x, y): anywhere between its neighbours (the line's ends
        only up and down). A bend circle dragged up or down curves its part."""
        kind, i, k = what
        env = self._env(i)
        if k >= len(env):
            return
        vol = self._vol(i) or 1.0
        if kind == "bend":
            if self._bend0 is None or k + 1 >= len(env):
                return
            y0, c0 = self._bend0
            falls = env[k + 1][1] < env[k][1]
            up = (y0 - y) / BEND_PX
            env[k][2] = round(min(max(c0 + (up if falls else -up), -1.0), 1.0), 3)
        else:
            env[k][1] = min(self._level_of(y) / vol, 1.0)
            if 0 < k < len(env) - 1:
                gap = volumeline.MIN_GAP_S * 2
                env[k][0] = min(max(self._t(x), env[k - 1][0] + gap), env[k + 1][0] - gap)
        self._set_env(i, env)

    def _heard_at(self, ts: np.ndarray) -> np.ndarray:
        """How loud each of the times `ts` plays by the volume lines (1: as it is): the
        joined splices' own lines, or the sound's between its handles times a splice's
        where there's one. The waveform is drawn that much smaller there."""
        out = np.ones(len(ts), np.float32)
        if not self._loaded() or self._first is not None:
            return out
        for i in (range(len(self.splices)) if self.joined else [-1]):
            env = self._env(i)
            a, b = env[0][0], env[-1][0]
            on = (ts >= a) & (ts <= b)
            if on.any():
                out[on] = volumeline.gain_of([[t - a, h, c] for t, h, c in env],
                                             ts[on] - a) * self._vol(i)
        if not self.joined:
            for i, part in enumerate(self.parts):
                env = self._env(i) if part else []
                if env:
                    a, b = env[0][0], env[-1][0]
                    on = (ts >= a) & (ts <= b)
                    if on.any():
                        out[on] *= volumeline.gain_of([[t - a, h, c] for t, h, c in env],
                                                      ts[on] - a) * self._vol(i)
        return out

    def _on_knob(self, x: float, y: float) -> bool:
        """(x, y) is on a trim handle's grip (at the bottom: it only trims)."""
        if self.joined:
            return False
        r = QRectF(self.rect()).adjusted(0.5, 0.5 + self._top(), -0.5, -0.5)
        near = min(abs(x - self._x(t)) for t in (self.start, self.end)) <= HANDLE_PX
        return near and y >= r.bottom() - KNOB_H - 4

    def _line_cursor(self, x: float, y: float) -> bool:
        """The pointer over the volume line: a point or bend circle (move), the line (a
        point to put there, shown faintly); True when it is (the cursor is set)."""
        ghost = None
        dragging = isinstance(self._drag, tuple) and self._drag[0] in ("env", "bend")
        what = None if self._drag or self._grab or self._on_knob(x, y) else self._env_at(x, y)
        on = None
        if not self._drag and not self._grab and what is None and not self._on_knob(x, y):
            on = self._on_line(x, y)
        if on is not None:
            i, t = on
            a = self._span(i)[0]
            env = self._env(i)
            lv = volumeline.level_at([[pt[0] - a, pt[1], pt[2]] for pt in env], t - a)
            ghost = QPointF(x, self._level_y(lv * self._vol(i)))
        if ghost != self._ghost:
            self._ghost = ghost
            self.update()
        drag = self._drag
        kind = drag[0] if isinstance(drag, tuple) and dragging else what[0] if what else None
        if kind == "bend":
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif kind == "env":
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        elif on is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            return False
        self._set_hover(None, None)
        return True

    def _point_menu(self, i: int, k: int, pos: QPoint):
        self._menu = menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.addAction(_("Delete point"), lambda: self._drop_point(i, k))
        menu.popup(pos)

    def _on_splices(self) -> bool:
        """Clicks work on the splices (Cut on, or they're what plays), not the handles."""
        return self.big and (self.cutting or self.joined)

    def _splice_edge(self, x: float) -> tuple[int, int] | None:
        """(splice, 0 start / 1 end) whose edge is under `x`, the nearest one."""
        best, near = None, HANDLE_PX + 0.5
        for i, sp in enumerate(self.splices):
            for side in (0, 1):
                d = abs(x - self._x(sp[side]))
                if d < near:
                    best, near = (i, side), d
        return best

    def _splice_at(self, t: float) -> int | None:
        """The splice `t` is in (the newest when they overlap)."""
        return next((i for i in range(len(self.splices) - 1, -1, -1)
                     if self.splices[i][0] <= t <= self.splices[i][1]), None)

    def _spans(self) -> list[tuple[float, float]]:
        """The parts that play: the joined splices, or what's between the handles."""
        if self.joined:
            return [(a, b) for a, b in self.splices]
        return [(self.start, self.end)]

    def _kept(self, ts: np.ndarray) -> np.ndarray:
        """Which of the times `ts` (seconds) play."""
        kept = np.zeros(len(ts), bool)
        for a, b in self._spans():
            kept |= (ts >= a) & (ts <= b)
        return kept

    def _gaps(self) -> list[tuple[float, float]]:
        """The parts that don't play, in order."""
        out, at = [], 0.0
        for a, b in sorted(self._spans()):
            if a > at:
                out.append((at, a))
            at = max(at, b)
        if at < self.length:
            out.append((at, self.length))
        return out

    def _gap_xs(self, lo: float, hi: float) -> list[tuple[float, float]]:
        """The parts that don't play in px, held to lo..hi (the sound's ends reach them)."""
        out = []
        for a, b in self._gaps():
            xa = lo if a <= 0 else max(self._x(a), lo)
            xb = hi if b >= self.length else min(self._x(b), hi)
            if xb - xa > 0.5:
                out.append((xa, xb))
        return out

    # the big one's zoom: `view` is the part of the sound shown, in seconds
    def zoom(self, factor: float, around: float | None = None):
        if not self._zoom_counted:   # once per sound edited: a scroll sends one per notch
            self._zoom_counted = True
            usage.used("edit-wave-zoom")
        v0, v1 = self.view
        span = min(max((v1 - v0) / factor, self.length / MAX_ZOOM), self.length)
        at = (v0 + v1) / 2 if around is None else around
        frac = (at - v0) / max(v1 - v0, 1e-9)
        self._set_view(at - frac * span, span)

    def pan(self, seconds: float):
        v0, v1 = self.view
        self._set_view(v0 + seconds, v1 - v0)

    def fit(self):
        self._set_view(0.0, self.length)

    def zoomed(self) -> bool:
        return self.view[1] - self.view[0] < self.length - 1e-6

    def _set_view(self, v0: float, span: float):
        v0 = min(max(v0, 0.0), self.length - span)
        self.view = (v0, v0 + span)
        self.update()

    def _area(self) -> tuple[float, float]:
        """(left, width) of where the sound is drawn, in px."""
        return (8.0, max(self.width() - 16.0, 1.0)) if self.big else \
            (4.0, max(self.width() - 8.0, 1.0))

    def _x(self, t: float) -> float:
        left, w = self._area()
        v0, v1 = self.view if self.big else (0.0, self.length)
        return left + w * (t - v0) / max(v1 - v0, 1e-9)

    def _t(self, x: float) -> float:
        left, w = self._area()
        v0, v1 = self.view if self.big else (0.0, self.length)
        return min(max(v0 + (x - left) / w * (v1 - v0), 0.0), self.length)

    def wheelEvent(self, e):
        """The big one: scrolling zooms around the pointer (Ctrl+scroll too), Shift+scroll
        or a touchpad's sideways swipe moves along. The small one scrolls the page."""
        if not self.big:
            e.ignore()
            return
        d = e.angleDelta().y() or e.angleDelta().x()
        mods = e.modifiers()
        side = e.angleDelta().x()
        if d and mods & Qt.KeyboardModifier.ControlModifier:
            self.zoom(1.25 if d > 0 else 0.8, self._t(e.position().x()))
        elif d and mods & Qt.KeyboardModifier.ShiftModifier:
            v0, v1 = self.view
            self.pan(-(v1 - v0) * 0.1 * (1 if d > 0 else -1))
        elif side and not e.angleDelta().y():   # a touchpad's sideways swipe
            v0, v1 = self.view
            self.pan(-(v1 - v0) * 0.1 * side / 120)
        elif d:
            self.zoom(1.25 if d > 0 else 0.8, self._t(e.position().x()))
        else:
            e.ignore()
            return
        e.accept()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            what = self._env_at(e.position().x(), e.position().y())
            if what is not None and what[0] == "env":
                env = self._env(what[1])
                if 0 < what[2] < len(env) - 1:   # (the line's ends stay)
                    # its menu on letting go, as Windows' are (on the press, the release
                    # landed on Delete point at once)
                    self._rpoint = (what[1], what[2], e.position())
                    e.accept()
                    return
        if self.big and e.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            # zoomed in, the rest of the sound is off to the sides: the right (or middle)
            # button drags it along, like a map; the left one keeps the handles
            if self.zoomed():
                self._grab = (e.position().x(), self.view[0])
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            # ...and a right click that doesn't drag: a splice's menu (mouseReleaseEvent)
            if e.button() == Qt.MouseButton.RightButton:
                self._rpress = e.position()
            e.accept()
            return
        x, y = e.position().x(), e.position().y()
        if self._in_ruler(y) or (not self.big and self._near_play(x)):
            self._drag = "play"
            self._scrub(x, False)
            return
        if self.big and self._near_play(x):
            # it sweeps through what you're aiming at while it plays: only a drag takes
            # it, a click is a click on the wave (mouseMoveEvent, mouseReleaseEvent)
            self._play_press = e.position()
            return
        self._press_wave(e.position())

    def _press_wave(self, pos: QPointF):
        """A left press on the wave, off the ruler and the playhead."""
        x, y = pos.x(), pos.y()
        self._press = pos
        point = None if self._on_knob(x, y) else self._env_at(x, y)
        if point is None and not self._on_knob(x, y):
            on = self._on_line(x, y)
            if on is not None:   # on the line: a point there, dragged from now
                point = self._add_point(*on)
        if point is not None:
            self._drag = point
            if point[0] == "bend":
                self._bend0 = (y, self._env(point[1])[point[2]][2])
            return
        if self._on_splices() or (not self.big and self.joined):
            self._press_splices(x)
            return
        ds, de = abs(x - self._x(self.start)), abs(x - self._x(self.end))
        if self.big and self.splices and min(ds, de) > HANDLE_PX:
            # on a splice: its edge drags, inside it picks it; elsewhere, the handles
            edge = self._splice_edge(x)
            if edge is not None:
                self._drag = edge
                return
            i = self._splice_at(self._t(x))
            self.pick(i)
            if i is not None:
                self.setFocus(Qt.FocusReason.MouseFocusReason)   # Esc: the whole sound
                return
        if min(ds, de) <= HANDLE_PX:   # only a handle itself drags it
            self._drag = "start" if ds <= de else "end"
        elif self.play is not None and not self.big:
            # elsewhere: plays from there (the big one's ruler does that: there it selects)
            self._drag = "play"
            self._scrub(x, False)

    def _in_ruler(self, y: float) -> bool:
        return self.big and y < RULER_H + 1

    def _near_play(self, x: float) -> bool:
        """The playhead is under `x`, nearer than any handle or splice edge (where they
        meet, the handle wins: it can't be reached any other way)."""
        if self.play is None or self._first is not None:
            return False
        d = abs(x - self._x(self.play))
        others = [abs(x - self._x(t)) for t in (self.start, self.end)] if not self.joined else []
        others += [abs(x - self._x(t)) for sp in self.splices for t in sp]
        return d <= PLAY_PX and all(d < o for o in others)

    def _grabs_play(self, x: float, y: float) -> bool:
        """A left press here moves where it plays: anywhere on the ruler, or on the
        playhead while it shows."""
        return self._in_ruler(y) or self._near_play(x)

    def _scrub(self, x: float, done: bool):
        t = self._t(x)
        self.play = t
        self.update()
        if done:
            usage.used("edit-wave-seek")
        self.scrubbed.emit(t, done)

    def _press_splices(self, x: float):
        if not self.big:   # the small one shows joined splices, the big one edits them
            return
        edge = self._splice_edge(x)
        if edge is not None and self._first is None:
            self._drag = edge
            return
        t = self._t(x)
        inside = self._splice_at(t)
        if not self.cutting or (self._first is None and inside is not None):
            # (joined, or Cut on and inside a splice) a click on one picks it
            self.pick(inside)
            if inside is not None:
                self.setFocus(Qt.FocusReason.MouseFocusReason)   # Esc: the whole sound
            return
        if self._first is None:
            self._first = t
            self.setFocus(Qt.FocusReason.MouseFocusReason)   # Esc lets go of it
        else:
            a, b = sorted((self._first, t))
            if b - a < soundfx.MIN_TRIM_S * 2:   # the same spot twice: start again there
                self._first = t
            elif len(self.splices) < soundfx.MAX_SPLICES:
                self._first = None
                self.splices.append([round(a, 3), round(b, 3)])
                self.parts.append({})
                usage.used("edit-splice-marked")
                self._hover = len(self.splices) - 1
                self.setMouseTracking(True)
                self.spliced.emit()
        self.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape and self._first is not None:
            self._first = None   # let go of the half-made splice, not the window
            self.update()
            e.accept()
            return
        if e.key() == Qt.Key.Key_Escape and self.selected is not None:
            self.pick(None)      # back to the whole sound, not closing the window
            e.accept()
            return
        super().keyPressEvent(e)

    def event(self, e):
        if e.type() == QEvent.Type.ToolTip and self._hover is not None:
            a, b = self.splices[self._hover]
            QToolTip.showText(e.globalPos(), splice_tip(self._hover, a, b), self)
            return True
        return super().event(e)

    def leaveEvent(self, e):
        self._at = None
        self._ghost = None
        self._set_hover(None, None)
        self.update()
        super().leaveEvent(e)

    def _set_hover(self, i: int | None, pos):
        if i == self._hover:
            return
        self._hover = i
        if i is None:
            QToolTip.hideText()
        elif pos is not None:
            a, b = self.splices[i]
            QToolTip.showText(pos, splice_tip(i, a, b), self)
        self.update()

    def mouseMoveEvent(self, e):
        if self._grab is not None:
            x0, at = self._grab
            v0, v1 = self.view
            self._set_view(at - (e.position().x() - x0) / self._area()[1] * (v1 - v0), v1 - v0)
        elif self._play_press is not None:
            if (e.position() - self._play_press).manhattanLength() >= PLAY_DRAG_PX:
                self._play_press = None
                self._drag = "play"
                self._scrub(e.position().x(), False)
            return
        elif self._drag == "play":
            self._scrub(e.position().x(), False)
            return
        elif isinstance(self._drag, tuple) and self._drag[0] in ("env", "bend"):
            self._drag_env(self._drag, e.position().x(), e.position().y())
        elif self._drag:
            self._move(e.position().x())
        x, y = e.position().x(), e.position().y()
        if self._line_cursor(x, y):
            return
        if not self.big and not self._drag:
            handle = min(abs(x - self._x(t)) for t in (self.start, self.end)) <= HANDLE_PX
            self.setCursor(Qt.CursorShape.SizeHorCursor if handle or self._near_play(x)
                           else Qt.CursorShape.PointingHandCursor if self.play is not None
                           else Qt.CursorShape.ArrowCursor)
        if self.big and self._grab is None:
            if not self._drag and self._grabs_play(x, e.position().y()):
                self.setCursor(Qt.CursorShape.PointingHandCursor
                               if self._in_ruler(e.position().y())
                               else Qt.CursorShape.SizeHorCursor)
                self._set_hover(None, None)
                return
            if not self._drag and not self._on_splices():
                handle = min(abs(x - self._x(t)) for t in (self.start, self.end)) <= HANDLE_PX
                self.setCursor(Qt.CursorShape.SizeHorCursor if handle
                               else Qt.CursorShape.PointingHandCursor if self.splices
                               else Qt.CursorShape.ArrowCursor)   # (nothing to select)
            if self.cutting:
                self._at = self._t(x)
                if self._first is not None:
                    self.update()
            i = self._splice_at(self._t(x)) if self._first is None else None
            if isinstance(self._drag, tuple):
                i = self._drag[0]
            self._set_hover(i, e.globalPosition().toPoint())
            if self._on_splices() and not self._drag:
                edge = self._first is None and self._splice_edge(x) is not None
                making = self.cutting and (self._first is not None or i is None)
                self.setCursor(Qt.CursorShape.SizeHorCursor if edge else
                               Qt.CursorShape.IBeamCursor if making
                               else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._play_press is not None:
            pos, self._play_press = self._play_press, None
            self._press_wave(pos)   # never dragged: a click there, nothing held after it
            self._drag, self._bend0 = None, None
            return
        rpoint, self._rpoint = self._rpoint, None
        if e.button() == Qt.MouseButton.RightButton and rpoint is not None:
            i, k, at = rpoint
            if (e.position() - at).manhattanLength() < POINT_GRAB:
                self._point_menu(i, k, e.globalPosition().toPoint())
            return
        rpress, self._rpress = self._rpress, None
        if e.button() == Qt.MouseButton.RightButton and rpress is not None:
            moved = (e.position() - rpress).manhattanLength()
            i = self._splice_at(self._t(e.position().x()))
            if moved < MENU_PX and i is not None and self._first is None:
                self._grab = None
                self.setCursor(Qt.CursorShape.IBeamCursor if self.cutting
                               else Qt.CursorShape.SizeHorCursor)
                self.menu_asked.emit(i, e.globalPosition().toPoint())
                return
        if self._grab is not None:
            self._grab = None
            self.setCursor(Qt.CursorShape.IBeamCursor if self.cutting
                           else Qt.CursorShape.SizeHorCursor)
            return
        if self._drag == "play":
            self._drag = None
            self._scrub(e.position().x(), True)
            return
        if isinstance(self._drag, tuple) and self._drag[0] in ("env", "bend"):
            usage.used("edit-wave-fade")
        self._drag, self._bend0 = None, None

    def _move(self, x: float):
        t = self._t(x)
        gap = soundfx.MIN_TRIM_S * 2
        if isinstance(self._drag, tuple) and self._drag[0] in ("env", "bend"):
            return   # (mouseMoveEvent passes the height too: _drag_env)
        if isinstance(self._drag, tuple):   # a splice's edge
            i, side = self._drag
            sp = self.splices[i]
            sp[side] = round(min(t, sp[1] - gap) if side == 0 else max(t, sp[0] + gap), 3)
            sp[0], sp[1] = max(sp[0], 0.0), min(sp[1], self.length)
            self.update()
            self.spliced.emit()
            return
        if self._drag == "start":
            self.start = min(t, self.end - gap)
        else:
            self.end = max(t, self.start + gap)
        self.start, self.end = max(self.start, 0.0), min(self.end, self.length)
        self.update()
        self.moved.emit(self.start, self.end)

    def paintEvent(self, e):
        if self.big:
            self._paint_big()
            return
        T = theme.T
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(T["border"]), 1))
        p.setBrush(QColor(T["bg"]))
        p.drawRoundedRect(r, 6, 6)
        mid, h = r.center().y(), r.height() / 2 - 6
        n = len(self.peaks)
        x0, x1 = self._x(self.start), self._x(self.end)
        if n:
            w = (self.width() - 8) / n
            on, off = QColor(T["accent"]), QColor(T["faint"])
            ts = (np.arange(n) + 0.5) / n * self.length
            kept, gains = self._kept(ts), self._heard_at(ts)
            p.setPen(Qt.PenStyle.NoPen)
            for i, v in enumerate(self.peaks):
                x = 4 + i * w
                bh = max(1.0, float(v) * h)
                p.setBrush(off)
                if kept[i] and gains[i] < 0.999:   # (all of it faint, what's heard over it)
                    p.drawRect(QRectF(x, mid - bh, max(w - 0.5, 0.6), bh * 2))
                    bh = max(1.0, bh * float(gains[i]))
                p.setBrush(on if kept[i] else off)
                p.drawRect(QRectF(x, mid - bh, max(w - 0.5, 0.6), bh * 2))
        else:
            p.setPen(QColor(T["muted"]))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter,
                       _("Waveform shows once the sound has loaded"))
        shade = QColor(0, 0, 0, 90)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(shade)
        for xa, xb in self._gap_xs(r.left(), r.right()):
            p.drawRect(QRectF(xa, r.top(), xb - xa, r.height()))
        for x in () if self.joined else (x0, x1):
            p.setPen(QPen(QColor(T["text_hi"]), 2))
            p.drawLine(int(x), int(r.top() + 2), int(x), int(r.bottom() - 2))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(T["text_hi"]))
            p.drawRoundedRect(QRectF(x - 4, r.bottom() - KNOB_H, 8, KNOB_H - 4), 3, 3)
        if n:
            self._paint_levels(p, r)
        if self.play is not None and n:   # the playhead: thin, no grip (not a handle)
            x = self._x(self.play)
            p.setPen(QPen(QColor(T["text_hi"]), 1.5))
            p.drawLine(QPointF(x, r.top() + 2), QPointF(x, r.bottom() - 2))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(T["text_hi"]))
            p.drawPolygon([QPointF(x - 4, r.top() + 1), QPointF(x + 4, r.top() + 1),
                           QPointF(x, r.top() + 6)])
        p.end()

    def _columns(self, n: int) -> np.ndarray:
        """The loudest peak in each of `n` equal slices of the part in view."""
        src = self.fine if self.fine is not None else np.asarray(self.peaks, np.float32)
        if not len(src) or n <= 0:
            return np.zeros(max(n, 0), np.float32)
        v0, v1 = self.view
        edges = np.linspace(v0, v1, n + 1) / self.length * len(src)
        starts = np.clip(edges[:-1].astype(int), 0, len(src) - 1)
        stop = min(len(src), max(int(np.ceil(edges[-1])), int(starts[-1]) + 1))
        # (reduceat's last slice runs to the end of what it's given: cut at the view's)
        return np.asarray(np.maximum.reduceat(src[:stop], starts), np.float32)

    def _paint_big(self):
        T = theme.T
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        full = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(T["border"]), 1))
        p.setBrush(QColor(T["bg"]))
        p.drawRoundedRect(full, 8, 8)
        r = full.adjusted(0, RULER_H, 0, 0)
        left, width = self._area()
        v0, v1 = self.view
        # the ruler: a labelled tick every `step`, small ones between
        p.setPen(QPen(QColor(T["border"]), 1))
        p.drawLine(QPointF(full.left() + 1, r.top()), QPointF(full.right() - 1, r.top()))
        f = p.font()
        f.setPointSizeF(f.pointSizeF() * 0.85)
        p.setFont(f)
        label_w = p.fontMetrics().horizontalAdvance("00:00.00") + 16
        per_s = width / max(v1 - v0, 1e-9)
        # room for two labels' width between labels: an easy-to-read ruler
        step = next((s for s in STEPS if s * per_s >= label_w * 2), STEPS[-1])
        minor = step / (4 if step in (0.2, 1, 2, 60, 120) else 5)
        k = int(np.floor(v0 / minor))
        while k * minor <= v1 + 1e-9:
            t = k * minor
            x = self._x(t)
            if x >= left - 0.5:
                whole = abs(t / step - round(t / step)) < 1e-6
                p.setPen(QPen(QColor(T["muted"] if whole else T["faint"]), 1))
                p.drawLine(QPointF(x, r.top() - (7 if whole else 3)), QPointF(x, r.top()))
                if whole and x + label_w - 12 <= full.right():
                    p.drawText(QRectF(x + 3, full.top() + 1, label_w, RULER_H - 6),
                               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                               ruler_text(t, step))
            k += 1
        # (the loudest peak stays just under the level line's full volume)
        mid = r.center().y()
        h = mid - (r.top() + LEVEL_TOP) - 3
        x0, x1 = self._x(self.start), self._x(self.end)
        n = int(width // COL_PX)
        cols = self._columns(n)
        if len(cols) and (self.fine is not None or len(self.peaks)):
            ts = v0 + (np.arange(n) + 0.5) / n * (v1 - v0)
            on, off = QColor(T["accent"]), QColor(T["faint"])
            kept_at = self._kept(ts)
            gains = self._heard_at(ts)
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(n):
                x = left + i * COL_PX
                kept = bool(kept_at[i])
                bh = max(1.0, float(cols[i]) * h)
                p.setBrush(off)
                if kept and gains[i] < 0.999:   # (all of it faint, what's heard over it)
                    p.drawRect(QRectF(x, mid - bh, COL_PX - 0.6, bh * 2))
                    bh = max(1.0, bh * float(gains[i]))
                p.setBrush(on if kept else off)
                p.drawRect(QRectF(x, mid - bh, COL_PX - 0.6, bh * 2))
        else:
            p.setPen(QColor(T["muted"]))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter,
                       _("Waveform shows once the sound has loaded"))
        p.setPen(QPen(QColor(T["border"]), 1))
        p.drawLine(QPointF(left, mid), QPointF(left + width, mid))
        # what doesn't play: shaded and hatched
        shade = QColor(0, 0, 0, 40 if theme.is_light() else 110)
        hatch = QColor(T["muted"])
        hatch.setAlpha(55)
        for a, b in self._gap_xs(r.left() + 1, r.right() - 1):
            band = QRectF(a, r.top() + 1, b - a, r.height() - 2)
            p.fillRect(band, shade)
            p.fillRect(band, QBrush(hatch, Qt.BrushStyle.BDiagPattern))
        # the level lines go on top of the splices (_paint_levels)
        # the handles (the joined splices have their own)
        p.setClipRect(r)
        for x in () if self.joined else (x0, x1):
            p.setPen(QPen(QColor(T["text_hi"]), 2))
            p.drawLine(QPointF(x, r.top() + 2), QPointF(x, r.bottom() - 2))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(T["text_hi"]))
            p.drawRoundedRect(QRectF(x - 5, r.bottom() - KNOB_H, 10, KNOB_H - 4), 3, 3)
        self._paint_splices(p, r, mid)
        self._paint_levels(p, r)
        p.setClipping(False)
        if self.play is not None and v0 <= self.play <= v1:
            x = self._x(self.play)
            p.setPen(QPen(QColor(T["accent2"]), 1.6))
            p.drawLine(QPointF(x, full.top() + 4), QPointF(x, r.bottom() - 2))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(T["accent2"]))
            p.drawPolygon([QPointF(x - 5, full.top() + 3), QPointF(x + 5, full.top() + 3),
                           QPointF(x, full.top() + 10)])
        p.end()

    def _paint_splices(self, p: QPainter, r: QRectF, mid: float):
        """Each splice: a lit band with an edge to drag at each end and its number on a
        badge at the top ("Splice 2" while the pointer is on it); the one being made:
        a dashed line where it starts, lit up to the pointer."""
        T = theme.T
        edge_c = QColor(T["text_hi"])
        fm = p.fontMetrics()
        for i, (a, b) in enumerate(self.splices):
            xa, xb = self._x(a), self._x(b)
            if xb < r.left() or xa > r.right():
                continue
            hover = i == self._hover
            picked = i == self.selected
            band = QColor(T["accent"] if picked else T["text_hi"])
            band.setAlpha(60 if picked else 46 if hover else 22)
            p.fillRect(QRectF(xa, r.top() + 1, xb - xa, r.height() - 2), band)
            if picked:   # the one the panels edit: framed in the accent colour
                p.setPen(QPen(QColor(T["accent"]), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(QRectF(xa + 1, r.top() + 2, xb - xa - 2, r.height() - 4))
            for x in (xa, xb):
                p.setPen(QPen(edge_c, 2))
                p.drawLine(QPointF(x, r.top() + 2), QPointF(x, r.bottom() - 2))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(edge_c)
                p.drawRoundedRect(QRectF(x - 3.5, r.bottom() - 16, 7, 12), 2, 2)
            text = _("Splice {n}", n=i + 1) if hover or picked else str(i + 1)
            if self.has_own(i):   # settings of its own (not just fades): marked
                text += " fx"
            w = max(BADGE_H, fm.horizontalAdvance(text) + 12)
            bx = min(max(xa + 8, r.left() + 2), max(xb - w - 8, r.left() + 2))
            badge = QRectF(bx, r.bottom() - BADGE_H - 4, w, BADGE_H)   # (the level line over it)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(T["accent"]))
            p.drawRoundedRect(badge, BADGE_H / 2, BADGE_H / 2)
            p.setPen(QColor(T["on_accent"]))
            p.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)
        if self._first is not None:
            xa = self._x(self._first)
            if self._at is not None:
                xb = self._x(self._at)
                band = QColor(T["accent"])
                band.setAlpha(50)
                p.fillRect(QRectF(min(xa, xb), r.top() + 1, abs(xb - xa), r.height() - 2),
                           band)
            p.setPen(QPen(edge_c, 2, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(xa, r.top() + 2), QPointF(xa, r.bottom() - 2))

    def _paint_levels(self, p: QPainter, r: QRectF):
        """Each splice's volume line over its waveform (and the sound's, while its
        handles play): full volume near the top, silence on the middle line. A dot on
        each point, a small circle halfway along each slope (it curves it), a faint dot
        where a click would put a point; on the big one, each fade's length beside it.
        Hidden while a splice is half made (its end click next)."""
        if self._first is not None or not self._loaded():
            return
        T = theme.T
        p.save()
        p.setClipRect(r)
        p.setBrush(Qt.BrushStyle.NoBrush)
        fm = p.fontMetrics()
        # the sound's line only where no splice is (theirs are drawn there)
        outside = QRegion(r.toAlignedRect())
        if self.big:
            for a, b in self.splices:
                xa, xb = self._x(a), self._x(b)
                outside -= QRegion(QRectF(xa, r.top(), xb - xa, r.height()).toAlignedRect())
        for i in self._env_lines():
            env, vol = self._env(i), self._vol(i)
            a, b = env[0][0], env[-1][0]
            xa, xb = self._x(a), self._x(b)
            if xb < r.left() or xa > r.right():
                continue
            # (curved parts in short steps, as many as there are pixels to fill)
            steps = int(min(max(xb - xa, 2.0), 4000.0) / 2) + 1
            ts = np.unique(np.concatenate([np.linspace(a, b, steps), [t for t, *_r in env]]))
            lv = volumeline.gain_of([[t - a, h, c] for t, h, c in env], ts - a)
            pts = [QPointF(self._x(t), self._level_y(float(v) * vol)) for t, v in zip(ts, lv)]
            if i < 0:
                p.setClipRegion(outside)
            p.setPen(QPen(QColor(T["text_hi"]), 1.6))
            p.drawPolyline(pts)
            p.setClipRect(r)
            if not self.big or len(env) < 3:
                continue
            fi, fo = volumeline.fades(volumeline.store([[t - a, h, c] for t, h, c in env],
                                                       b - a), b - a)
            boxes: list[QRectF] = []
            for text, fade, at, right in ((_("Fade in"), fi, env[1], True),
                                         (_("Fade out"), fo, env[-2], False)):
                if fade <= 0:
                    continue
                words = f"{text} {fade:.1f} s"
                tw = fm.horizontalAdvance(words) + 10
                ax, ay = self._x(at[0]), self._level_y(at[1] * vol)
                bx = ax + 8 if right else ax - 8 - tw
                lo, hi = xa + POINT_R + 4, xb - POINT_R - 4 - tw
                if hi >= lo:   # (inside its line's ends: a long fade's isn't on a dot)
                    bx = min(max(bx, lo), hi)
                box = QRectF(bx, ay + 6, tw, 16)
                for o in boxes:   # on the other one: beside it, while there's room
                    if box.intersects(o.adjusted(-2, -2, 2, 2)) and \
                            o.right() + 6 + tw <= xb - POINT_R - 4:
                        box.moveLeft(o.right() + 6)
                while any(box.intersects(o.adjusted(-2, -2, 2, 2)) for o in boxes):
                    box.translate(0, 20)   # (a short splice: one under the other)
                boxes.append(box)
                back = QColor(T["bg"])
                back.setAlpha(200)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(back)
                p.drawRoundedRect(box, 4, 4)
                p.setPen(QColor(T["text_hi"]))
                p.drawText(box, Qt.AlignmentFlag.AlignCenter, words)
        for pt, (kind, _i, _k) in self._env_points():
            if kind == "bend":   # a small ring: it curves the part it's on
                p.setPen(QPen(QColor(T["text_hi"]), 1.5))
                p.setBrush(QColor(T["bg"]))
                p.drawEllipse(pt, BEND_R, BEND_R)
            else:
                p.setPen(QPen(QColor(T["bg"]), 1.5))
                p.setBrush(QColor(T["accent"]))
                p.drawEllipse(pt, POINT_R, POINT_R)
        if self._ghost is not None:   # where a click puts a point
            c = QColor(T["accent"])
            c.setAlpha(120)
            p.setPen(QPen(QColor(T["text_hi"]), 1, Qt.PenStyle.DotLine))
            p.setBrush(c)
            p.drawEllipse(self._ghost, POINT_R, POINT_R)
        p.restore()


class TimeBox(QDoubleSpinBox):
    """Start / End in minutes and seconds (2:14.70), as the ruler and "plays" say it.
    Typed as 2:14.7 or as seconds (134.7)."""

    def textFromValue(self, v: float) -> str:
        m, sec = divmod(round(max(v, 0.0), 2), 60)
        return f"{int(m)}:{sec:05.2f}"

    def valueFromText(self, text: str) -> float:
        v = self._seconds(text)
        return self.minimum() if v is None else v

    def validate(self, text: str, pos: int):
        v = self._seconds(text)
        if v is not None and self.minimum() <= v <= self.maximum():
            return QValidator.State.Acceptable, text, pos
        typing = all(c.isdigit() or c in ":., " for c in text) and text.count(":") <= 1
        return (QValidator.State.Intermediate if typing else QValidator.State.Invalid,
                text, pos)

    @staticmethod
    def _seconds(text: str) -> float | None:
        """2:14.7 or 134,7 as seconds; None if it isn't a time (yet)."""
        parts = text.strip().replace(",", ".").split(":")
        try:
            nums = [float(x) for x in parts]
        except ValueError:
            return None
        if len(nums) > 2 or any(n < 0 for n in nums) or (len(nums) == 2 and nums[1] >= 60):
            return None
        return nums[0] * 60 + nums[1] if len(nums) == 2 else nums[0]


class TrimPanel(QWidget):
    """Waveform + Start / End boxes + Reset. `changed` on every edit; `values()` is
    (start, end) as soundfx wants them (end 0 = the end of the sound), `trim_fx()`
    those and the splices. `splices_changed` when a splice is made, moved or removed,
    or they're joined or split again."""
    changed = Signal()
    splices_changed = Signal()
    seek_to = Signal(float, bool)   # the ruler or playhead dragged: (seconds, let go)

    def __init__(self, peaks: np.ndarray | Sequence[float], length: float):
        super().__init__()
        self.length = max(length, 0.0)
        v = self._box = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        self.wave = Waveform(peaks, self.length)
        self.wave.moved.connect(self._from_wave)
        self.wave.spliced.connect(self._from_splices)
        self.wave.scrubbed.connect(self.seek_to)
        self._solo: dict | None = None   # one splice playing on its own: its effects
        v.addWidget(self.wave)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.info = QLabel()   # before the boxes: setting their values updates it
        self.info.setObjectName("muted")
        self.box_start, self.box_end = TimeBox(), TimeBox()
        self._box_parts: list[QWidget] = []   # the boxes and their labels
        self._boxes_hidden = False
        for lbl, box in ((_("Start"), self.box_start), (_("End"), self.box_end)):
            box.setDecimals(2)
            box.setSingleStep(0.1)
            box.setRange(0.0, max(self.length, 0.01))
            box.setKeyboardTracking(False)
            box.valueChanged.connect(self._from_boxes)
            no_wheel(box)
            name = QLabel(lbl)
            row.addWidget(name)
            row.addWidget(box)
            self._box_parts += [name, box]
        self.box_end.setValue(self.length)
        row.addWidget(self.info, 1)
        reset = QPushButton(_("Keep all"))
        reset.setObjectName("small")
        reset.setToolTip(_("Undo the trim: play the whole sound"))
        reset.clicked.connect(self._keep_all)
        row.addWidget(reset)
        v.addLayout(row)
        self._show_info()

    def set_big(self, on: bool):
        """Advanced's big waveform, or the Trim & speed tab's small one."""
        self.wave.set_big(on)
        self._box.setSpacing(8 if on else 6)

    def show_playing(self, frac: float | None, fx: dict | None = None):
        """The playhead at `frac` (0..1) of what plays, the sound with effects `fx`
        (its trim or joined splices and Play backwards say where that is in the file);
        None hides it."""
        if frac is None:
            self._solo = None
            self.wave.set_play(None)
            return
        self.wave.set_play(soundfx.time_at(self.as_played(fx), self.length, frac))

    def as_played(self, fx: dict | None) -> dict:
        """Effects `fx` as what plays has them: one splice's ▶ plays just that part."""
        return self._solo if self._solo is not None else soundfx.clean(fx or {})

    def frac_of(self, t: float, fx: dict | None) -> float:
        """How far through (0..1) the sound with effects `fx` is at `t` seconds into
        the file (a part that doesn't play: the next one that does)."""
        return soundfx.frac_at(self.as_played(fx), self.length, t)

    def play_solo(self, i: int, fx: dict) -> dict | None:
        """Splice `i` of a sound with effects `fx`, on its own with its own settings
        (soundfx.splice_alone): the effects to preview it with (the playhead shows it
        until it stops), None if there's no such splice."""
        if not 0 <= i < len(self.wave.splices):
            return None
        self._solo = soundfx.splice_alone({**fx, **self.trim_fx()}, i)
        return self._solo

    def clear_solo(self):
        self._solo = None

    def trim_fx(self) -> dict:
        """The trim's part of a sound's effects: start, end and the splices. Joined, start
        and end span them, so an older version (that has no splices) plays that much."""
        w = self.wave
        start, end = self.values()
        if w.joined:
            start = min(a for a, _b in w.splices)
            end = max(b for _a, b in w.splices)
            end = 0.0 if end >= self.length - 0.005 else end
        return {"start": start, "end": end, "splices": [list(sp) for sp in w.splices],
                "joined": w.joined, "parts": [dict(p) for p in w.parts]}

    def load(self, fx: dict):
        """Show the trim and splices of (cleaned) effects `fx`, without `changed`."""
        self.set_values(fx.get("start", 0.0), fx.get("end", 0.0))
        self.wave.set_splices(fx.get("splices") or [], bool(fx.get("joined")),
                              fx.get("parts") or [])

    def set_joined(self, on: bool):
        """Combine splices (on): the sound plays them back to back; off: the handles again."""
        on = on and bool(self.wave.splices)
        if on != self.wave.joined:
            self.wave.joined = on
            self.wave.update()
            self._from_splices()

    def remove_splice(self, i: int):
        self.wave.remove_splice(i)

    def _keep_all(self):
        self.wave.joined = False
        self.set_values(0.0, 0.0)
        self._from_splices()

    def _from_splices(self):
        self._sync_boxes()
        self.splices_changed.emit()
        self.changed.emit()

    def values(self) -> tuple[float, float]:
        s, e = round(self.wave.start, 3), round(self.wave.end, 3)
        return (0.0 if s < 0.005 else s), (0.0 if e >= self.length - 0.005 else e)

    def set_values(self, start: float, end: float, emit: bool = False):
        end = end if end and end <= self.length else self.length
        start = min(max(start, 0.0), end)
        self.wave.set_range(start, end)
        self._sync_boxes()
        if emit:
            self.changed.emit()

    def _sync_boxes(self):
        for box, v in ((self.box_start, self.wave.start), (self.box_end, self.wave.end)):
            box.blockSignals(True)
            box.setValue(v)
            box.blockSignals(False)
        self._show_info()

    def _show_info(self):
        joined = self.wave.joined
        if joined != self._boxes_hidden:   # joined, the splices say what plays, not the
            self._boxes_hidden = joined    # handles (only on a change: shown with no parent
            for w in self._box_parts:      # yet, each flashed up as a window of its own)
                w.setVisible(not joined)
        kept = sum(b - a for a, b in self.wave.splices) if joined else \
            self.wave.end - self.wave.start
        self.info.setText(_("plays {kept} of {length}",
                            kept=soundfx.fmt_s(kept), length=soundfx.fmt_s(self.length)))

    def _from_wave(self, _s, _e):
        self._sync_boxes()
        self.changed.emit()

    def _from_boxes(self, _v):
        s, e = self.box_start.value(), self.box_end.value()
        gap = soundfx.MIN_TRIM_S * 2
        if self.sender() is self.box_start:
            s = min(s, e - gap)
        else:
            e = max(e, s + gap)
        self.wave.set_range(max(s, 0.0), min(e, self.length))
        self._sync_boxes()
        self.changed.emit()
