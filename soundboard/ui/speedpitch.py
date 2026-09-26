"""Live speed / pitch control: a small button on a transport bar ("1x") that opens a
popup with the sliders. It changes what's playing right now and isn't saved; to
keep a version of a sound, use its Edit → Effects tab instead."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout)

from soundboard import voicefx
from soundboard.ui.panel import hint_label
from soundboard.ui.voicepanel import ParamSlider

SPEED = voicefx.Param("speed", "Speed", 0.25, 2.0, 1.0, "x", 0.05)
PITCH = voicefx.Param("pitch", "Pitch", -12, 12, 0, " st", 1)
QUICK = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)


class SpeedPitchButton(QPushButton):
    """`changed(speed, semitones, keep_pitch)` fires on every edit."""
    changed = Signal(float, float, bool)

    def __init__(self, what: str = "sounds", hint: str = ""):
        super().__init__()
        self.setObjectName("small")
        self.setToolTip(f"Speed and pitch of the {what} playing now")
        self.setCursor(Qt.PointingHandCursor)

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
        q = QHBoxLayout()
        q.setSpacing(4)
        for s in QUICK:
            b = QPushButton(f"{s:g}x")
            b.setObjectName("small")
            b.clicked.connect(lambda _=False, s=s: self.speed.set_value(s) or self._edited())
            q.addWidget(b)
        v.addLayout(q)
        v.addWidget(self.pitch)
        self.keep = QCheckBox("Keep pitch when changing speed")
        self.keep.setChecked(True)
        self.keep.setToolTip("Off: slower is also deeper and faster is higher, like a tape")
        v.addWidget(self.keep)
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

    def values(self) -> tuple[float, float, bool]:
        return self.speed.value(), self.pitch.value(), self.keep.isChecked()

    def is_default(self) -> bool:
        s, p, _k = self.values()
        return abs(s - 1) < 1e-3 and abs(p) < 1e-3

    def set_values(self, speed: float, pitch: float, keep: bool):
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
        y = pos.y() - self.pop.height() - 4     # above the bar, unless there's no room
        if y < 0:
            y = pos.y() + self.height() + 4
        self.pop.move(max(0, pos.x() + self.width() - self.pop.width()), y)
        self.pop.show()

    def _label(self):
        s, p, _k = self.values()
        txt = f"{s:g}x"
        if abs(p) >= 1e-3:
            txt += f" {p:+g}"
        self.setText(txt)
        self.setStyleSheet("" if self.is_default() else "font-weight:700; color:#ffb020;")

    def _edited(self):
        self._label()
        self.changed.emit(*self.values())
