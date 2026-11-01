"""The Effects tab's trim control: the sound's waveform with a start and an end
handle to drag, and two boxes for exact times. Only the part between them plays;
the file itself is never cut (the trim is part of the sound's effects, see
soundfx.trim). Edit sound's Advanced view shows the same control big (`set_big`):
a time ruler, zoom, and the fades drawn where they happen."""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from soundboard.audio import soundfx
from soundboard.ui.kit import theme
from soundboard.ui.kit.wheelguard import no_wheel
from soundboard.i18n import _
from soundboard.ui.kit.pixels import snap_to_pixels

HANDLE_PX = 8   # how close to a handle a press grabs it
BIG_H = 110     # the big waveform's least height (Advanced): on a short screen it gives
                # the columns under it room (they scroll); taller, it takes its share
RULER_H = 20    # its time ruler
MAX_ZOOM = 16   # the big one zooms in to a sixteenth of the sound
COL_PX = 2      # the big one draws a bar every 2 px
# ruler steps (seconds): the first that leaves room between its labels
STEPS = (0.01, 0.02, 0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600)


def ruler_text(t: float, step: float) -> str:
    """0:03 for whole-second steps, 0:03.5 / 0:03.25 for finer ones."""
    m, s = divmod(max(t, 0.0) + 1e-9, 60)
    if step >= 1:
        return f"{int(m)}:{int(s):02d}"
    places = 1 if round(step * 10, 6) == int(round(step * 10, 6)) else 2
    return f"{int(m)}:{s:0{3 + places}.{places}f}"


class Waveform(QWidget):
    """Peaks with two handles. `moved(start, end)` in seconds (end = length for 'the
    end') while a handle is dragged."""
    moved = Signal(float, float)

    def __init__(self, peaks: np.ndarray | Sequence[float], length: float):
        super().__init__()
        self.peaks = peaks
        self.length = max(length, 0.001)
        self.start, self.end = 0.0, self.length
        self.play: float | None = None   # where it's playing now (seconds), None: it isn't
        self._drag: str | None = None
        self._grab: tuple[float, float] | None = None   # (x, view start): dragging it along
        self.big = False
        self.fine: np.ndarray | None = None   # more peaks, for the big one (set_fine)
        self.view = (0.0, self.length)        # the part the big one shows (zoom)
        self.fades = (0.0, 0.0)               # fade in / out (s), drawn on the big one
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
        t = None if t is None else min(max(t, 0.0), self.length)
        if t != self.play:
            self.play = t
            self.update()

    def set_big(self, on: bool):
        """Advanced's big waveform (ruler, zoom, fades) or the tab's small one."""
        self.big = on
        self.view = (0.0, self.length)
        self.setMinimumHeight(BIG_H if on else 70)
        self.setToolTip(_("Drag the handles to cut off the start and end. Ctrl+scroll "
                          "zooms. Drag with the right mouse button, or Shift+scroll, to "
                          "move along.") if on else
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

    # the big one's zoom: `view` is the part of the sound shown, in seconds
    def zoom(self, factor: float, around: float | None = None):
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
        """The big one: Ctrl+scroll zooms around the pointer, Shift+scroll moves along.
        Anything else (and the small one) scrolls the page as usual."""
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
        elif side and not e.angleDelta().y() and self.zoomed():   # a touchpad's sideways swipe
            v0, v1 = self.view
            self.pan(-(v1 - v0) * 0.1 * side / 120)
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
            e.accept()
            return
        x = e.position().x()
        ds, de = abs(x - self._x(self.start)), abs(x - self._x(self.end))
        if min(ds, de) <= HANDLE_PX:
            self._drag = "start" if ds <= de else "end"
        else:   # a click elsewhere moves the nearer handle there
            self._drag = "start" if ds < de else "end"
            self._move(x)

    def mouseMoveEvent(self, e):
        if self._grab is not None:
            x0, at = self._grab
            v0, v1 = self.view
            self._set_view(at - (e.position().x() - x0) / self._area()[1] * (v1 - v0), v1 - v0)
        elif self._drag:
            self._move(e.position().x())

    def mouseReleaseEvent(self, e):
        if self._grab is not None:
            self._grab = None
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            return
        self._drag = None

    def _move(self, x: float):
        t = self._t(x)
        gap = soundfx.MIN_TRIM_S * 2
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
            p.setPen(Qt.PenStyle.NoPen)
            for i, v in enumerate(self.peaks):
                x = 4 + i * w
                p.setBrush(on if x0 <= x + w / 2 <= x1 else off)
                bh = max(1.0, float(v) * h)
                p.drawRect(QRectF(x, mid - bh, max(w - 0.5, 0.6), bh * 2))
        else:
            p.setPen(QColor(T["muted"]))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter,
                       _("Waveform shows once the sound has loaded"))
        shade = QColor(0, 0, 0, 90)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(shade)
        p.drawRect(QRectF(r.left(), r.top(), x0 - r.left(), r.height()))
        p.drawRect(QRectF(x1, r.top(), r.right() - x1, r.height()))
        for x in (x0, x1):
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
        mid, h = r.center().y(), r.height() / 2 - 8
        x0, x1 = self._x(self.start), self._x(self.end)
        n = int(width // COL_PX)
        cols = self._columns(n)
        if len(cols) and (self.fine is not None or len(self.peaks)):
            ts = v0 + (np.arange(n) + 0.5) / n * (v1 - v0)
            gain = np.ones(n, np.float32)
            fi, fo = self.fades
            if fi > 0:   # what the fades leave of it
                gain = np.where((ts >= self.start) & (ts < self.start + fi),
                                (ts - self.start) / fi, gain)
            if fo > 0:
                gain = np.where((ts > self.end - fo) & (ts <= self.end),
                                np.minimum(gain, (self.end - ts) / fo), gain)
            on, off = QColor(T["accent"]), QColor(T["faint"])
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(n):
                x = left + i * COL_PX
                kept = self.start <= ts[i] <= self.end
                p.setBrush(on if kept else off)
                bh = max(1.0, float(cols[i]) * (float(gain[i]) if kept else 1.0) * h)
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
        for a, b in ((r.left() + 1, x0), (x1, r.right() - 1)):
            a, b = max(a, r.left() + 1), min(b, r.right() - 1)
            if b - a > 0.5:
                band = QRectF(a, r.top() + 1, b - a, r.height() - 2)
                p.fillRect(band, shade)
                p.fillRect(band, QBrush(hatch, Qt.BrushStyle.BDiagPattern))
        # the fades: a dashed line from full height down to nothing
        fi, fo = self.fades
        pen = QPen(QColor(T["text"]), 1.4, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        top, bottom = r.top() + 8, r.bottom() - 8
        for a, b, rising in ((self.start, self.start + fi, True),
                             (self.end - fo, self.end, False)):
            if b - a <= 0 or b < v0 or a > v1:
                continue
            xa, xb = self._x(a), self._x(b)
            path = QPainterPath()
            if rising:
                path.moveTo(xa, mid)
                path.lineTo(xb, top)
                path.moveTo(xa, mid)
                path.lineTo(xb, bottom)
            else:
                path.moveTo(xa, top)
                path.lineTo(xb, mid)
                path.moveTo(xa, bottom)
                path.lineTo(xb, mid)
            p.drawPath(path)
        # the handles
        p.setClipRect(r)
        for x in (x0, x1):
            p.setPen(QPen(QColor(T["text_hi"]), 2))
            p.drawLine(QPointF(x, r.top() + 2), QPointF(x, r.bottom() - 2))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(T["text_hi"]))
            p.drawRoundedRect(QRectF(x - 5, mid - 12, 10, 24), 3, 3)
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


class TrimPanel(QWidget):
    """Waveform + Start / End boxes + Reset. `changed` on every edit; `values()` is
    (start, end) as soundfx wants them (end 0 = the end of the sound)."""
    changed = Signal()

    def __init__(self, peaks: np.ndarray | Sequence[float], length: float):
        super().__init__()
        self.length = max(length, 0.0)
        v = self._box = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        self.wave = Waveform(peaks, self.length)
        self.wave.moved.connect(self._from_wave)
        v.addWidget(self.wave)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.info = QLabel()   # before the boxes: setting their values updates it
        self.info.setObjectName("muted")
        self.box_start, self.box_end = QDoubleSpinBox(), QDoubleSpinBox()
        for lbl, box in ((_("Start"), self.box_start), (_("End"), self.box_end)):
            box.setDecimals(2)
            box.setSingleStep(0.1)
            box.setSuffix(" s")
            box.setRange(0.0, max(self.length, 0.01))
            box.setKeyboardTracking(False)
            box.valueChanged.connect(self._from_boxes)
            no_wheel(box)
            row.addWidget(QLabel(lbl))
            row.addWidget(box)
        self.box_end.setValue(self.length)
        row.addWidget(self.info, 1)
        reset = QPushButton(_("Keep all"))
        reset.setObjectName("small")
        reset.setToolTip(_("Undo the trim: play the whole sound"))
        reset.clicked.connect(lambda: self.set_values(0.0, 0.0, emit=True))
        row.addWidget(reset)
        v.addLayout(row)
        self._show_info()

    def set_big(self, on: bool):
        """Advanced's big waveform, or the Trim & speed tab's small one."""
        self.wave.set_big(on)
        self._box.setSpacing(8 if on else 6)

    def show_playing(self, frac: float | None, fx: dict | None = None):
        """The playhead at `frac` (0..1) of what plays, the sound with effects `fx`
        (its trim and Play backwards say where that is in the file); None hides it."""
        if frac is None:
            self.wave.set_play(None)
            return
        f = soundfx.clean(fx or {})
        start = min(max(f["start"], 0.0), self.length)
        end = f["end"] if 0 < f["end"] <= self.length else self.length
        self.wave.set_play(end - frac * (end - start) if f["reverse"]
                           else start + frac * (end - start))

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
        kept = self.wave.end - self.wave.start
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
