"""The Effects tab's trim control: the sound's waveform with a start and an end
handle to drag, and two boxes for exact times. Only the part between them plays;
the file itself is never cut (the trim is part of the sound's effects, see
soundfx.trim)."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from soundboard import soundfx, theme
from soundboard.wheelguard import no_wheel
from soundboard.i18n import _

HANDLE_PX = 8   # how close to a handle a press grabs it


class Waveform(QWidget):
    """Peaks with two handles. `moved(start, end)` in seconds (end = length for 'the
    end') while a handle is dragged."""
    moved = Signal(float, float)

    def __init__(self, peaks: np.ndarray, length: float):
        super().__init__()
        self.peaks = peaks
        self.length = max(length, 0.001)
        self.start, self.end = 0.0, self.length
        self._drag: str | None = None
        self.setMinimumHeight(70)
        self.setCursor(Qt.SizeHorCursor)
        self.setToolTip(_("Drag the handles to cut off the start and end. Only the part between "
                          "them plays."))

    def set_range(self, start: float, end: float):
        self.start, self.end = start, end
        self.update()

    def _x(self, t: float) -> float:
        return 4 + (self.width() - 8) * t / self.length

    def _t(self, x: float) -> float:
        return min(max((x - 4) / max(self.width() - 8, 1) * self.length, 0.0), self.length)

    def mousePressEvent(self, e):
        x = e.position().x()
        ds, de = abs(x - self._x(self.start)), abs(x - self._x(self.end))
        if min(ds, de) <= HANDLE_PX:
            self._drag = "start" if ds <= de else "end"
        else:   # a click elsewhere moves the nearer handle there
            self._drag = "start" if ds < de else "end"
            self._move(x)

    def mouseMoveEvent(self, e):
        if self._drag:
            self._move(e.position().x())

    def mouseReleaseEvent(self, e):
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
        T = theme.T
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
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
            p.setPen(Qt.NoPen)
            for i, v in enumerate(self.peaks):
                x = 4 + i * w
                p.setBrush(on if x0 <= x + w / 2 <= x1 else off)
                bh = max(1.0, float(v) * h)
                p.drawRect(QRectF(x, mid - bh, max(w - 0.5, 0.6), bh * 2))
        else:
            p.setPen(QColor(T["muted"]))
            p.drawText(r, Qt.AlignCenter, _("Waveform shows once the sound has loaded"))
        shade = QColor(0, 0, 0, 90)
        p.setPen(Qt.NoPen)
        p.setBrush(shade)
        p.drawRect(QRectF(r.left(), r.top(), x0 - r.left(), r.height()))
        p.drawRect(QRectF(x1, r.top(), r.right() - x1, r.height()))
        for x in (x0, x1):
            p.setPen(QPen(QColor(T["text_hi"]), 2))
            p.drawLine(int(x), int(r.top() + 2), int(x), int(r.bottom() - 2))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(T["text_hi"]))
            p.drawRoundedRect(QRectF(x - 4, mid - 9, 8, 18), 3, 3)
        p.end()


class TrimPanel(QWidget):
    """Waveform + Start / End boxes + Reset. `changed` on every edit; `values()` is
    (start, end) as soundfx wants them (end 0 = the end of the sound)."""
    changed = Signal()

    def __init__(self, peaks: np.ndarray, length: float):
        super().__init__()
        self.length = max(length, 0.0)
        v = QVBoxLayout(self)
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
