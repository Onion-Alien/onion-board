"""The Effects tab's trim control: the sound's waveform with a start and an end
handle to drag, and two boxes for exact times. Only the part between them plays;
the file itself is never cut (the trim is part of the sound's effects, see
soundfx.trim). Edit sound's Advanced view shows the same control big (`set_big`):
a time ruler, zoom, and the fades drawn where they happen, and splices: parts marked
with two clicks each while Cut is on, numbered, that can be joined to play back to
back (soundfx.join). On the big one the time ruler is a seek bar (a click or a drag
moves the playing sound there) and the playhead can be dragged along too."""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QRegion, QValidator
from PySide6.QtWidgets import (QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QToolTip,
                               QVBoxLayout, QWidget)

from soundboard.audio import soundfx
from soundboard.core import usage
from soundboard.ui.kit import theme
from soundboard.ui.kit.wheelguard import no_wheel
from soundboard.i18n import _
from soundboard.ui.kit.pixels import snap_to_pixels

HANDLE_PX = 8   # how close to a handle a press grabs it
PLAY_PX = 14    # ...and to the playhead: it moves while the pointer aims at it
BIG_H = 110     # the big waveform's least height (Advanced): on a short screen it gives
                # the columns under it room (they scroll); taller, it takes its share
RULER_H = 20    # its time ruler
MAX_ZOOM = 16   # the big one zooms in to a sixteenth of the sound
COL_PX = 2      # the big one draws a bar every 2 px
BADGE_H = 18    # a splice's number badge
LEVEL_TOP = 8   # full volume on the level line: this far under the ruler
POINT_R = 5     # a level point's radius
POINT_GRAB = 10  # how near a press must be to grab one
LEVEL_SLACK = 6  # a fade's corner dragged sideways keeps its level until it moves this far
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
    has one too, for its fades (`faded(fade_in, fade_out)`)."""
    moved = Signal(float, float)
    spliced = Signal()
    scrubbed = Signal(float, bool)
    picked = Signal(object)
    menu_asked = Signal(int, QPoint)
    faded = Signal(float, float)
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
        self.fades = (0.0, 0.0)               # fade in / out (s), drawn on the big one
        self.splices: list[list[float]] = []  # [[start, end], ...] in seconds, made in order
        self.parts: list[dict] = []           # each one's own settings (soundfx "parts")
        self.selected: int | None = None      # the splice picked: the panels edit it
        self._rpress: QPointF | None = None   # a right press, until it's a click or a drag
        self._press: QPointF | None = None    # where the left button went down
        self.joined = False                   # they play back to back (not the handles)
        self.cutting = False                  # Cut is on: two clicks make a splice
        self._first: float | None = None      # where the splice being made starts
        self._at: float | None = None         # the pointer, while making one
        self._hover: int | None = None        # the splice under the pointer
        self.setMinimumHeight(70)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.setToolTip(_("Drag the handles to cut off the start and end. Only the part between "
                          "them plays."))

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
        self.setMouseTracking(on or bool(self.splices))   # (the ruler's and playhead's pointer)
        self.view = (0.0, self.length)
        self.setMinimumHeight(BIG_H if on else 70)
        self.setToolTip(_("Drag the handles to cut off the start and end. Click or drag "
                          "the time ruler, or drag the playhead, to move where it plays. "
                          "Ctrl+scroll zooms. Drag with the right mouse button, or "
                          "Shift+scroll, to move along.") + " " +
                        _("Scroll to zoom. On a splice's level line, drag the dots: the "
                          "corners sideways for a fade and up or down for its volume, the "
                          "ends up or down for where a fade starts. Click a splice for "
                          "effects of its own, right-click it for more.")
                        if on else
                        _("Drag the handles to cut off the start and end. Only the part "
                          "between them plays."))
        self.update()

    def set_fine(self, peaks: np.ndarray | None):
        """Peaks enough to zoom into (the big one draws these when it has them)."""
        self.fine = None if peaks is None or not len(peaks) else np.asarray(peaks, np.float32)
        self.update()

    def set_fades(self, fade_in: float, fade_out: float):
        if (fade_in, fade_out) != self.fades:
            self.fades = (fade_in, fade_out)
            self.update()

    def set_cutting(self, on: bool):
        """Cut on: a click marks where a splice starts, the next where it ends (a click
        inside a splice still picks it, and its level dots still drag)."""
        self.cutting = on
        self._first = None
        self.setMouseTracking(on or self.big or bool(self.splices))
        self.setCursor(Qt.CursorShape.IBeamCursor if on else Qt.CursorShape.SizeHorCursor)
        self.update()

    def set_splices(self, splices: list[list[float]], joined: bool,
                    parts: list[dict] | None = None):
        self.splices = [list(sp) for sp in splices]
        got = parts or []
        self.parts = [dict(got[i]) if i < len(got) else {} for i in range(len(self.splices))]
        self.joined = joined and bool(self.splices)
        self._hover = None
        self.setMouseTracking(self.cutting or self.big or bool(self.splices))
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

    FADE_KEYS = ("fade_in", "fade_out", "fade_in_from", "fade_out_to", "volume")

    def has_own(self, i: int) -> bool:
        """Splice `i` has settings of its own, beyond its level line (fades, volume)."""
        p = self.parts[i] if 0 <= i < len(self.parts) else {}
        return any(k not in self.FADE_KEYS for k in p)

    def part_fades(self, i: int) -> tuple[float, float]:
        p = self.parts[i] if 0 <= i < len(self.parts) else {}
        return float(p.get("fade_in", 0.0)), float(p.get("fade_out", 0.0))

    def set_part_fade(self, i: int, key: str, seconds: float):
        """Splice `i`'s "fade_in" or "fade_out" set to `seconds` (0: off), kept inside
        the splice beside its other fade."""
        if not 0 <= i < len(self.splices):
            return
        (a, b), p = self.splices[i], dict(self.parts[i])
        other = float(p.get("fade_out" if key == "fade_in" else "fade_in", 0.0))
        p[key] = round(min(max(seconds, 0.0), b - a - other, soundfx.MAX_FADE_S), 2)
        self.parts[i] = soundfx.clean_part(p)
        self.update()
        self.level_moved.emit(i)
        self.spliced.emit()

    def _level_y(self, level: float) -> float:
        """Where a level (0 silence .. 1 full volume) is drawn: the middle line up to
        just under the ruler, above the loudest peaks."""
        r = QRectF(self.rect()).adjusted(0.5, 0.5 + RULER_H, -0.5, -0.5)
        mid, top = r.center().y(), r.top() + LEVEL_TOP
        return mid - min(max(level, 0.0), 1.0) * (mid - top)

    def _level_of(self, y: float) -> float:
        r = QRectF(self.rect()).adjusted(0.5, 0.5 + RULER_H, -0.5, -0.5)
        mid, top = r.center().y(), r.top() + LEVEL_TOP
        return min(max((mid - y) / max(mid - top, 1.0), 0.0), 1.0)

    def _env(self, i: int) -> list[tuple[float, float]]:
        """Splice `i`'s level line (i = -1: the sound's, between its handles) as its four
        points (seconds, level): where the fade in starts, where it's full, where the
        fade out starts, where it ends."""
        if i < 0:
            a, b = self.start, self.end
            fi, fo = self.fades
            return [(a, 0.0 if fi > 0 else 1.0), (a + fi, 1.0), (b - fo, 1.0),
                    (b, 0.0 if fo > 0 else 1.0)]
        (a, b), p = self.splices[i], self.parts[i] if i < len(self.parts) else {}
        fi, fo = self.part_fades(i)
        vol = min(float(p.get("volume", 1.0)), 1.0)
        lo_in = float(p.get("fade_in_from", 0.0)) if fi > 0 else 1.0
        lo_out = float(p.get("fade_out_to", 0.0)) if fo > 0 else 1.0
        return [(a, lo_in * vol), (a + fi, vol), (b - fo, vol), (b, lo_out * vol)]

    def _env_lines(self) -> list[int]:
        """Which level lines show: each splice's, and the sound's while its handles
        play (joined, the sound's fades are the Fades sliders': its points would sit on
        splice 1's and the last one's)."""
        return list(range(len(self.splices))) + ([] if self.joined else [-1])

    def _env_points(self) -> list[tuple[QPointF, tuple]]:
        """(where, what) of every point that can be dragged: ("env", line, point 0..3).
        The start and end points only while that fade is on, and the sound's only
        sideways (its fades always start and end silent)."""
        out = []
        if self.fine is None and not len(self.peaks):   # not loaded: no line to drag yet
            return out
        for i in self._env_lines():
            env = self._env(i)
            fi, fo = self.part_fades(i) if i >= 0 else self.fades
            for k, (t, lv) in enumerate(env):
                if (k == 0 and (fi <= 0 or i < 0)) or (k == 3 and (fo <= 0 or i < 0)):
                    continue
                out.append((QPointF(self._x(t), self._level_y(lv)), ("env", i, k)))
        return out

    def _env_at(self, x: float, y: float) -> tuple | None:
        """The level point under (x, y), the nearest; None: none."""
        if not self.big or self._first is not None or self._in_ruler(y):
            return None
        best, near = None, POINT_GRAB
        for pt, what in self._env_points():
            d = ((pt.x() - x) ** 2 + (pt.y() - y) ** 2) ** 0.5
            if d < near:
                best, near = what, d
        return best

    def _drag_env(self, what: tuple, x: float, y: float):
        """A level point dragged to (x, y): the fade's corners sideways set its length
        and up and down the splice's volume; its start / end point up and down set the
        level that fade starts from / ends at."""
        _e, i, k = what
        t = self._t(x)
        if i < 0:
            a, b = self.start, self.end
            fi, fo = self.fades
        else:
            (a, b), (fi, fo) = self.splices[i], self.part_fades(i)
        room = b - a
        if k == 1:
            fi = min(max(t - a, 0.0), room - fo)
        elif k == 2:
            fo = min(max(b - t, 0.0), room - fi)
        fi, fo = (round(v, 2) if v >= 0.02 else 0.0 for v in (fi, fo))   # near 0: off
        if i < 0:
            self.fades = (min(fi, soundfx.MAX_FADE_S), min(fo, soundfx.MAX_FADE_S))
            self.update()
            self.faded.emit(*self.fades)
            return
        p = self.parts[i]
        level = round(self._level_of(y), 2)
        if k in (1, 2):   # (sideways only, until it's dragged clearly up or down)
            if self._press is not None and abs(y - self._press.y()) >= LEVEL_SLACK:
                p["volume"] = level
        else:
            vol = min(float(p.get("volume", 1.0)), 1.0) or 1.0
            p["fade_in_from" if k == 0 else "fade_out_to"] = round(min(level / vol, 1.0), 2)
        for key, v in (("fade_in", fi), ("fade_out", fo)):
            p[key] = min(v, soundfx.MAX_FADE_S)
        self.parts[i] = soundfx.clean_part(p)
        self.update()
        self.level_moved.emit(i)
        self.spliced.emit()

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
        x = e.position().x()
        if self._grabs_play(x, e.position().y()):   # the ruler, or the playhead itself
            self._drag = "play"
            self._scrub(x, False)
            return
        self._press = e.position()
        point = self._env_at(x, e.position().y())
        if point is not None:
            self._drag = point
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
        if min(ds, de) <= HANDLE_PX:
            self._drag = "start" if ds <= de else "end"
        else:   # a click elsewhere moves the nearer handle there
            self._drag = "start" if ds < de else "end"
            self._move(x)

    def _in_ruler(self, y: float) -> bool:
        return self.big and y < RULER_H + 1

    def _near_play(self, x: float) -> bool:
        """The playhead is under `x`, nearer than any handle or splice edge (where they
        meet, the handle wins: it can't be reached any other way)."""
        if not self.big or self.play is None or self._first is not None:
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
        elif self._drag == "play":
            self._scrub(e.position().x(), False)
            return
        elif isinstance(self._drag, tuple) and self._drag[0] == "env":
            self._drag_env(self._drag, e.position().x(), e.position().y())
        elif self._drag:
            self._move(e.position().x())
        if self.big and self._grab is None:
            x = e.position().x()
            fading = isinstance(self._drag, tuple) and self._drag[0] == "env"
            if fading or (not self._drag and self._env_at(x, e.position().y())):
                self.setCursor(Qt.CursorShape.SizeAllCursor)
                self._set_hover(None, None)
                return
            if not self._drag and self._grabs_play(x, e.position().y()):
                self.setCursor(Qt.CursorShape.PointingHandCursor
                               if self._in_ruler(e.position().y())
                               else Qt.CursorShape.SizeHorCursor)
                self._set_hover(None, None)
                return
            if not self._drag and not self._on_splices():
                self.setCursor(Qt.CursorShape.SizeHorCursor)
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
        if isinstance(self._drag, tuple) and self._drag[0] == "env":
            usage.used("edit-wave-fade")
        self._drag = None

    def _move(self, x: float):
        t = self._t(x)
        gap = soundfx.MIN_TRIM_S * 2
        if isinstance(self._drag, tuple) and self._drag[0] == "env":
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
            kept = self._kept((np.arange(n) + 0.5) / n * self.length)
            p.setPen(Qt.PenStyle.NoPen)
            for i, v in enumerate(self.peaks):
                x = 4 + i * w
                p.setBrush(on if kept[i] else off)
                bh = max(1.0, float(v) * h)
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
            p.drawRoundedRect(QRectF(x - 4, mid - 9, 8, 18), 3, 3)
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
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(n):
                x = left + i * COL_PX
                kept = bool(kept_at[i])
                p.setBrush(on if kept else off)
                bh = max(1.0, float(cols[i]) * h)
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
            p.drawRoundedRect(QRectF(x - 5, mid - 12, 10, 24), 3, 3)
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
        """Each splice's level line over its waveform (and the sound's, while its
        handles play): full volume near the top, sloping to the level each fade starts
        from or ends at; a dot on each point that can be dragged, the fade's length
        beside its corner. Hidden while a splice is half made (its end click next)."""
        if self._first is not None or (self.fine is None and not len(self.peaks)):
            return   # (or not loaded)
        T = theme.T
        p.save()
        p.setClipRect(r)
        p.setBrush(Qt.BrushStyle.NoBrush)
        fm = p.fontMetrics()
        # the sound's line only where no splice is (theirs are drawn there)
        outside = QRegion(r.toAlignedRect())
        for a, b in self.splices:
            xa, xb = self._x(a), self._x(b)
            outside -= QRegion(QRectF(xa, r.top(), xb - xa, r.height()).toAlignedRect())
        for i in self._env_lines():
            env = self._env(i)
            pts = [QPointF(self._x(t), self._level_y(lv)) for t, lv in env]
            if pts[-1].x() < r.left() or pts[0].x() > r.right():
                continue
            if i < 0:
                p.setClipRegion(outside)
            p.setPen(QPen(QColor(T["text_hi"]), 1.6))
            p.drawPolyline(pts)
            p.setClipRect(r)
            fi, fo = self.part_fades(i) if i >= 0 else self.fades
            boxes: list[QRectF] = []
            for text, fade, at, right in ((_("Fade in"), fi, pts[1], True),
                                         (_("Fade out"), fo, pts[2], False)):
                if fade <= 0:
                    continue
                words = f"{text} {fade:.1f} s"
                tw = fm.horizontalAdvance(words) + 10
                box = QRectF(at.x() + 8 if right else at.x() - 8 - tw, at.y() + 6, tw, 16)
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
        for pt, (_e, _i, k) in self._env_points():
            corner = k in (1, 2)
            p.setPen(QPen(QColor(T["bg"]), 1.5))
            p.setBrush(QColor(T["accent"] if corner else T["text_hi"]))
            p.drawEllipse(pt, POINT_R, POINT_R)
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
