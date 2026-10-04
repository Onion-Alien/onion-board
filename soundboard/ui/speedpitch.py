"""Live speed / pitch control: a small button on a transport bar ("1x") that opens a
popup with the sliders. It changes what's playing right now and isn't saved; to
keep a version of a sound, use its Edit → Effects tab instead.

The sane range (0.25–2x, ±12 st) is always there. The greyed-out **Redline**
section under it unlocks the silly range (up to 10x, ±36 st) and shows a rev
meter that goes into the red past 2x."""
from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from soundboard import theme, voicefx
from soundboard.ui import icons
from soundboard.ui.panel import hint_label
from soundboard.ui.voicepanel import ParamSlider

SPEED = voicefx.Param("speed", "Speed", 0.25, 2.0, 1.0, "x", 0.05)
PITCH = voicefx.Param("pitch", "Pitch", -12, 12, 0, " st", 1)
QUICK = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)
REDLINE_AT = 2.0                        # the meter's red zone starts here
REDLINE_SPEED = (0.1, 10.0)             # sounds
REDLINE_PITCH = voicefx.Param("pitch", "Pitch", -36, 36, 0, " st", 1)
REDLINE_QUICK = (3.0, 4.0, 6.0, 8.0, 10.0)
RED = "#ff4d4f"


def redline_speed(lo: float, hi: float) -> voicefx.Param:
    return voicefx.Param("speed", "Speed", lo, hi, 1.0, "x", 0.05)


class RevMeter(QWidget):
    """A tachometer for the speed: 0..top, the arc turns orange then red past
    REDLINE_AT, and the needle shows where you are."""
    SWEEP = 240.0                       # degrees, from lower-left round to lower-right

    def __init__(self, top: float):
        super().__init__()
        self.top = top
        self.speed = 1.0
        self.setFixedHeight(118)
        self.setMinimumWidth(200)

    def set_value(self, speed: float):
        if abs(speed - self.speed) > 1e-6:
            self.speed = speed
            self.update()

    def _angle(self, v: float) -> float:
        """Qt angle (degrees, counter-clockwise from 3 o'clock) of value v."""
        f = min(max(v / self.top, 0.0), 1.0)
        return 90 + self.SWEEP / 2 - self.SWEEP * f

    def paintEvent(self, _e):
        t = theme.T
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = min(self.width() / 2 - 12, self.height() * 0.62)
        c = QPointF(self.width() / 2, r + 10)
        box = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)

        def arc(v0, v1, color, width):
            a0, a1 = self._angle(v0), self._angle(v1)
            p.setPen(QPen(QColor(color), width, Qt.SolidLine, Qt.FlatCap))
            p.drawArc(box, int(a0 * 16), int((a1 - a0) * 16))

        def point(v, rad):
            a = math.radians(self._angle(v))
            return QPointF(c.x() + rad * math.cos(a), c.y() - rad * math.sin(a))

        warn_to = min(self.top, max(REDLINE_AT + 1, self.top * 0.4))
        arc(0, self.top, t["faint"], 3)                  # the whole dial, dim
        arc(0, REDLINE_AT, t["accent"], 7)
        arc(REDLINE_AT, warn_to, t["warn_text"], 7)
        if warn_to < self.top:
            arc(warn_to, self.top, RED, 7)

        f = QFont(self.font())
        f.setPointSizeF(7)
        p.setFont(f)
        for i in range(int(self.top) + 1):              # a tick + number per 1x
            hot = i > REDLINE_AT
            p.setPen(QPen(QColor(RED if hot else t["muted"]), 1.5))
            p.drawLine(point(i, r - 6), point(i, r - 13))
            q = point(i, r - 22)
            p.drawText(QRectF(q.x() - 10, q.y() - 7, 20, 14), Qt.AlignCenter, str(i))

        hot = self.speed > REDLINE_AT + 1e-6
        needle = QColor(RED if hot else t["text_hi"])
        p.setPen(QPen(needle, 2.5, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(c, point(self.speed, r - 4))
        p.setBrush(needle)
        p.setPen(Qt.NoPen)
        p.drawEllipse(c, 4.5, 4.5)

        f.setPointSizeF(11)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(RED if hot else t["text"]))
        p.drawText(QRectF(c.x() - 60, c.y() + 6, 120, 20), Qt.AlignCenter, f"{self.speed:g}x")
        if hot:
            f.setPointSizeF(7)
            p.setFont(f)
            p.drawText(QRectF(c.x() - 60, c.y() + 25, 120, 14), Qt.AlignCenter, "REDLINE")
        p.end()


class SpeedPitchButton(QPushButton):
    """`changed(speed, semitones, keep_pitch)` fires on every edit."""
    changed = Signal(float, float, bool)

    def __init__(self, what: str = "sounds", hint: str = "",
                 redline: tuple[float, float] = REDLINE_SPEED):
        """`redline`: the (slowest, fastest) speed once Redline is unlocked."""
        super().__init__()
        self.setObjectName("small")
        self.setToolTip(f"Speed and pitch of the {what} playing now")
        self.setCursor(Qt.PointingHandCursor)
        self._speed_hi = redline_speed(*redline)
        redline = redline[1]

        self.pop = QFrame(self, Qt.Popup)
        self.pop.setObjectName("transport")
        v = QVBoxLayout(self.pop)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)
        title = QLabel(f"Speed & pitch — {what}")
        title.setStyleSheet("font-weight:700;")
        v.addWidget(title)
        self.speed = ParamSlider(SPEED, 1.0)
        self.pitch = ParamSlider(PITCH, 0.0)
        v.addWidget(self.speed)
        v.addLayout(self._quick_row(QUICK))
        v.addWidget(self.pitch)
        self.keep = QCheckBox("Keep pitch when changing speed")
        self.keep.setChecked(True)
        self.keep.setToolTip("Off: slower is also deeper and faster is higher, like a tape")
        v.addWidget(self.keep)

        # --- Redline: greyed out until you ask for it
        self.redline = QPushButton(f"Redline — up to {redline:g}x")
        icons.set_icon(self.redline, "shield", size=14)
        self.redline.setObjectName("small")
        self.redline.setCheckable(True)
        self.redline.setToolTip(f"Unlock silly speeds (up to {redline:g}x) and pitch "
                                f"(±{REDLINE_PITCH.hi:g} st)")
        self.redline.setStyleSheet(f"QPushButton:!checked {{ color:{theme.T['faint']}; }}")
        self.redline.toggled.connect(self.set_redline)
        v.addWidget(self.redline)
        self.red_box = QWidget()
        rv = QVBoxLayout(self.red_box)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(4)
        self.meter = RevMeter(redline)
        rv.addWidget(self.meter)
        rv.addLayout(self._quick_row(tuple(s for s in REDLINE_QUICK if s <= redline)))
        self.red_box.hide()
        v.addWidget(self.red_box)

        row = QHBoxLayout()
        if hint:
            row.addWidget(hint_label(hint), 1)
        else:
            row.addStretch(1)
        reset = QPushButton("Reset")
        reset.setObjectName("small")
        reset.clicked.connect(self.reset)
        row.addWidget(reset)
        v.addLayout(row)
        self.pop.setMinimumWidth(360)

        self.speed.changed.connect(self._edited)
        self.pitch.changed.connect(self._edited)
        self.keep.toggled.connect(lambda _b: self._edited())
        self.clicked.connect(self._open)
        self._label()

    def _quick_row(self, speeds) -> QHBoxLayout:
        q = QHBoxLayout()
        q.setSpacing(4)
        for s in speeds:
            b = QPushButton(f"{s:g}x")
            b.setObjectName("small")
            b.clicked.connect(lambda _=False, s=s: self.speed.set_value(s) or self._edited())
            q.addWidget(b)
        return q

    def set_redline(self, on: bool):
        """Unlock (or lock again) the silly range. Locking pulls the values back in."""
        if self.redline.isChecked() != on:
            self.redline.setChecked(on)   # comes back here through toggled
            return
        icons.set_icon(self.redline, "wave" if on else "shield", size=14)
        self.speed.set_param(self._speed_hi if on else SPEED)
        self.pitch.set_param(REDLINE_PITCH if on else PITCH)
        self.red_box.setVisible(on)
        if self.pop.isVisible():
            self._open()                  # resize / re-place it for the new height
        self._edited()

    def values(self) -> tuple[float, float, bool]:
        return self.speed.value(), self.pitch.value(), self.keep.isChecked()

    def is_default(self) -> bool:
        s, p, _k = self.values()
        return abs(s - 1) < 1e-3 and abs(p) < 1e-3

    def set_values(self, speed: float, pitch: float, keep: bool):
        if not SPEED.lo <= speed <= SPEED.hi or not PITCH.lo <= pitch <= PITCH.hi:
            self.redline.setChecked(True)     # a value only the Redline range holds
        self.speed.set_value(speed)
        self.pitch.set_value(pitch)
        self.keep.blockSignals(True)
        self.keep.setChecked(keep)
        self.keep.blockSignals(False)
        self._edited()

    def reset(self):
        self.set_values(1.0, 0.0, self.keep.isChecked())

    def _open(self):
        self.pop.adjustSize()
        pos = self.mapToGlobal(QPoint(0, 0))
        # kept on the screen the button is on (a second monitor can sit left of or
        # above the primary one, at negative coordinates)
        area = self.screen().availableGeometry()
        y = pos.y() - self.pop.height() - 4     # above the bar, unless there's no room
        if y < area.top():
            y = pos.y() + self.height() + 4
        y = max(area.top(), min(y, area.bottom() - self.pop.height()))
        x = pos.x() + self.width() - self.pop.width()
        x = max(area.left(), min(x, area.right() - self.pop.width()))
        self.pop.move(x, y)
        self.pop.show()

    def _label(self):
        s, p, _k = self.values()
        txt = f"{s:g}x"
        if abs(p) >= 1e-3:
            txt += f" {p:+g}"
        self.setText(txt)
        hot = s > REDLINE_AT + 1e-6 or abs(p) > PITCH.hi
        self.setStyleSheet("" if self.is_default() else
                           f"font-weight:700; color:{RED if hot else theme.status('warn')};")

    def _edited(self):
        self._label()
        self.meter.set_value(self.speed.value())
        self.changed.emit(*self.values())
