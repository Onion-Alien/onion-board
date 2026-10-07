"""Live speed / pitch / effects: a small button on a transport bar ("1x") that opens
a popup with the sliders. It changes what's playing right now and isn't saved; to
keep a version of a sound, use its Edit → Effects tab instead.

Two columns: speed & pitch on the left, the live effects (soundboard.livefx: bass,
treble, muffle, reverb, echo, distortion, and presets that set several) on the right.

The sane range (0.25–2x, ±12 st) is always there. The greyed-out **Redline**
section under it unlocks the silly range (up to 10x, ±36 st) and shows a rev
meter that goes into the red past 2x."""
from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from soundboard import livefx, theme, voicefx
from soundboard.ui import icons
from soundboard.ui.panel import hint_label, section_label
from soundboard.ui.voicepanel import ParamSlider
from soundboard.i18n import _

SPEED = voicefx.Param("speed", _("Speed"), 0.25, 2.0, 1.0, "x", 0.05)
PITCH = voicefx.Param("pitch", _("Pitch"), -12, 12, 0, " st", 1)
QUICK = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)
REDLINE_AT = 2.0                        # the meter's red zone starts here
REDLINE_SPEED = (0.1, 10.0)             # sounds
REDLINE_PITCH = voicefx.Param("pitch", _("Pitch"), -36, 36, 0, " st", 1)
REDLINE_QUICK = (3.0, 4.0, 6.0, 8.0, 10.0)
RED = "#ff4d4f"
NAME_W, VAL_W, GAP = 48, 52, 10         # popup slider columns: name | track | value
FX_NAME_W = 70                          # the effects column: longer names
COL_W = 340                             # each column


def redline_speed(lo: float, hi: float) -> voicefx.Param:
    return voicefx.Param("speed", _("Speed"), lo, hi, 1.0, "x", 0.05)


class RevMeter(QWidget):
    """A tachometer for the speed: 0..top, the arc turns orange then red past
    REDLINE_AT, and the needle shows where you are."""
    SWEEP = 240.0                       # degrees, from lower-left round to lower-right

    def __init__(self, top: float):
        super().__init__()
        self.top = top
        self.speed = 1.0
        self.setFixedHeight(132)
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
            p.drawText(QRectF(c.x() - 60, c.y() + 25, 120, 14), Qt.AlignCenter, _("REDLINE"))
        p.end()


class SpeedPitchButton(QPushButton):
    """`changed(speed, semitones, keep_pitch)` fires on every speed / pitch edit,
    `fx_changed(amounts)` on every effects edit (livefx.clean: only knobs off 0)."""
    changed = Signal(float, float, bool)
    fx_changed = Signal(dict)

    def __init__(self, what: str = "sounds", hint: str = "",
                 redline: tuple[float, float] = REDLINE_SPEED):
        """`what`: "sounds", or a live stream, "radio" / "apps" (the Radio and Apps
        tabs): those have no speed, only the pitch and the effects.
        `redline`: the (slowest, fastest) speed once Redline is unlocked."""
        super().__init__()
        self.has_speed = what == "sounds"
        self.setObjectName("small")
        self.setProperty("speedpitch", True)
        self.setToolTip({"radio": _("Pitch and effects of the radio"),
                         "apps": _("Pitch and effects of the programs you send")}.get(
            what, _("Speed, pitch and effects of the sounds playing now")))
        self.setCursor(Qt.PointingHandCursor)
        if not self.has_speed:   # "Effects" on its own reads as a label: show it's a control
            icons.set_icon(self, "wave", size=14)
        self._speed_hi = redline_speed(*redline)
        redline = redline[1]

        self.pop = QFrame(self, Qt.Popup)
        self.pop.setObjectName("transport")
        v = QVBoxLayout(self.pop)
        v.setContentsMargins(16, 12, 16, 14)
        v.setSpacing(8)

        # header: title on the left, Reset where it's easy to find
        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel(_("Live controls"))
        title.setStyleSheet("font-weight:700; font-size:10.5pt;")
        sub = QLabel({"radio": _("The radio"), "apps": _("All programs")}.get(
            what, _("All sounds")))
        sub.setObjectName("muted")
        reset = QPushButton(_("Reset all"))
        reset.setObjectName("small")
        reset.setToolTip(_("Back to 1x, no pitch change and no effects") if self.has_speed
                         else _("Back to no pitch change and no effects"))
        reset.setCursor(Qt.PointingHandCursor)
        reset.clicked.connect(self.reset)
        head.addWidget(title)
        head.addWidget(sub)
        head.addStretch(1)
        head.addWidget(reset)
        v.addLayout(head)
        v.addWidget(self._rule())

        cols = QHBoxLayout()
        cols.setSpacing(16)
        left_w, right_w = QWidget(), QWidget()
        for w in (left_w, right_w):
            w.setObjectName("spcol")    # sits on the popup, no box of its own
            w.setStyleSheet("QWidget#spcol { background:transparent; }")
            w.setFixedWidth(COL_W)
        cols.addWidget(left_w, 0, Qt.AlignTop)
        divider = QFrame()
        divider.setObjectName("vsep")
        divider.setFixedWidth(1)
        cols.addWidget(divider)
        cols.addWidget(right_w, 0, Qt.AlignTop)
        v.addLayout(cols)
        self._effects(right_w)

        outer, v = v, QVBoxLayout(left_w)     # the speed & pitch column
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        v.addWidget(section_label(_("SPEED & PITCH") if self.has_speed else _("PITCH")))
        self.speed = self._slider(SPEED, 1.0)
        self.pitch = self._slider(PITCH, 0.0)
        v.addWidget(self.speed)
        quick = QWidget()
        quick.setObjectName("spcol")
        quick.setLayout(self._quick_row(QUICK))
        v.addWidget(quick)
        v.addSpacing(2)
        v.addWidget(self.pitch)
        self.keep = QCheckBox(_("Keep pitch when changing speed"))
        self.keep.setChecked(True)
        self.keep.setToolTip(_("Off: slower is also deeper and faster is higher, like a tape"))
        v.addWidget(self.keep)
        if not self.has_speed:    # a live stream can't be sped up or slowed down
            for w in (self.speed, quick, self.keep):
                w.hide()

        # --- Redline: its own section, locked until you ask for it
        v.addSpacing(2)
        v.addWidget(self._rule())
        red_row = QHBoxLayout()
        red_row.setSpacing(8)
        red_text = QVBoxLayout()
        red_text.setSpacing(0)
        red_name = QLabel(_("Redline"))
        red_name.setStyleSheet("font-weight:700;")
        red_sub = QLabel(_("Up to {redline:g}x speed and ±{hi:g} st pitch",
                           redline=redline, hi=REDLINE_PITCH.hi) if self.has_speed
                         else _("Up to ±{hi:g} st pitch", hi=REDLINE_PITCH.hi))
        red_sub.setObjectName("hint")
        red_text.addWidget(red_name)
        red_text.addWidget(red_sub)
        red_row.addLayout(red_text, 1)
        self.redline = QPushButton(_("Unlock"))
        icons.set_icon(self.redline, "shield", size=14)
        self.redline.setObjectName("small")
        self.redline.setCheckable(True)
        self.redline.setCursor(Qt.PointingHandCursor)
        self.redline.setMinimumWidth(84)
        self.redline.setToolTip(_("Unlock silly speeds (up to {redline:g}x) and pitch (±{hi:g} "
                                  "st)", redline=redline, hi=REDLINE_PITCH.hi) if self.has_speed
                                else _("Unlock silly pitch (±{hi:g} st)", hi=REDLINE_PITCH.hi))
        self.redline.toggled.connect(self.set_redline)
        red_row.addWidget(self.redline, 0, Qt.AlignVCenter)
        v.addLayout(red_row)
        self.red_box = QWidget()
        self.red_box.setObjectName("redbox")    # sits on the popup, no box of its own
        self.red_box.setStyleSheet("QWidget#redbox { background:transparent; }")
        rv = QVBoxLayout(self.red_box)
        rv.setContentsMargins(0, 4, 0, 0)
        rv.setSpacing(6)
        self.meter = RevMeter(redline)
        rv.addWidget(self.meter)
        rv.addLayout(self._quick_row(tuple(s for s in REDLINE_QUICK if s <= redline)))
        self.red_box.hide()
        v.addWidget(self.red_box)

        v = outer
        if hint:
            v.addSpacing(2)
            v.addWidget(self._rule())
            v.addWidget(hint_label(hint))

        self.speed.changed.connect(self._edited)
        self.pitch.changed.connect(self._edited)
        self.keep.toggled.connect(lambda _b: self._edited())
        self.clicked.connect(self._open)
        self._label()

    def _effects(self, box: QWidget):
        """The right column: one slider per live effect, then presets that set them."""
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        v.addWidget(section_label(_("EFFECTS")))
        self.fx = {}
        for q in livefx.PARAMS:
            s = self._slider(q, q.default, FX_NAME_W)
            s.changed.connect(self._fx_edited)
            self.fx[q.key] = s
            v.addWidget(s)
        grid = QGridLayout()
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)
        self.fx_presets = {}
        for i, (name, amounts) in enumerate(livefx.PRESETS.items()):
            b = QPushButton(name)
            b.setObjectName("small")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(_("Click again to turn it off"))
            b.clicked.connect(lambda on, a=amounts: self.set_fx(a if on else {}))
            self.fx_presets[name] = b
            grid.addWidget(b, i // 3, i % 3)
        v.addLayout(grid)

    @staticmethod
    def _slider(q: voicefx.Param, value: float, name_w: int = NAME_W) -> ParamSlider:
        """A ParamSlider laid out for the popup: no effect-row indent, a fixed name
        column so both sliders (and the quick buttons) line up, a readable value."""
        s = ParamSlider(q, value)
        h = s.layout()
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(GAP)
        h.itemAt(0).widget().setFixedWidth(name_w)
        s.val.setObjectName("")
        s.val.setFixedWidth(VAL_W)
        return s

    @staticmethod
    def _rule() -> QFrame:
        line = QFrame()
        line.setObjectName("vsep")       # the bar divider's colour, laid flat
        line.setFixedHeight(1)
        return line

    def _quick_row(self, speeds) -> QHBoxLayout:
        """Preset speeds, under the slider track so they read as part of it."""
        q = QHBoxLayout()
        q.setContentsMargins(NAME_W + GAP, 0, 0, 0)
        q.setSpacing(4)
        for s in speeds:
            b = QPushButton(f"{s:g}x")
            b.setObjectName("small")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda __=False, s=s: self.speed.set_value(s) or self._edited())
            q.addWidget(b)
        return q

    def set_redline(self, on: bool):
        """Unlock (or lock again) the silly range. Locking pulls the values back in."""
        if self.redline.isChecked() != on:
            self.redline.setChecked(on)   # comes back here through toggled
            return
        icons.set_icon(self.redline, "wave" if on else "shield", size=14)
        self.redline.setText(_("On") if on else _("Unlock"))
        self.speed.set_param(self._speed_hi if on else SPEED)
        self.pitch.set_param(REDLINE_PITCH if on else PITCH)
        self.red_box.setVisible(on and self.has_speed)   # the rev meter: speed only
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
        self.set_fx({})

    def fx_values(self) -> dict[str, float]:
        return livefx.clean({k: s.value() for k, s in self.fx.items()})

    def set_fx(self, amounts: dict):
        """Set every effect knob (missing ones go to 0)."""
        for k, s in self.fx.items():
            s.set_value(amounts.get(k, 0.0))
        self._fx_edited()

    def _fx_edited(self):
        now = self.fx_values()
        for name, b in self.fx_presets.items():   # lit while the knobs match it
            b.setChecked(now == livefx.clean(livefx.PRESETS[name]))
        self._label()
        self.fx_changed.emit(now)

    def _open(self):
        # settle the layouts first: right after Redline hides its box, the column's
        # and the popup's size hint (and the popup's minimum) still hold the old,
        # taller height, so adjustSize alone would never shrink it back
        self.red_box.parentWidget().layout().activate()
        self.pop.layout().activate()
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
        fx = bool(self.fx_values())
        if self.has_speed:
            txt = f"{s:g}x"
            if abs(p) >= 1e-3:
                txt += f" {p:+g}"
            if fx:
                txt += " · FX"
        else:   # no speed to show: "Effects" until something's on
            parts = [f"{p:+g} st"] if abs(p) >= 1e-3 else []
            if fx:
                parts.append("FX")
            txt = " · ".join(parts) or _("Effects")
        self.setText(txt)
        hot = s > REDLINE_AT + 1e-6 or abs(p) > PITCH.hi
        # scoped to this button: unscoped, it would cascade into the popup (a child).
        # Only when the look changes: each set re-polishes the popup's ~90 widgets too
        # (6-9 ms a slider step)
        sheet = ("" if self.is_default() and not fx else
                 f"QPushButton[speedpitch=\"true\"] {{ font-weight:700; "
                 f"color:{RED if hot else theme.status('warn')}; }}")
        if sheet != self.styleSheet():
            self.setStyleSheet(sheet)

    def _edited(self):
        self._label()
        self.meter.set_value(self.speed.value())
        self.changed.emit(*self.values())
