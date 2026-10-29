"""Clean mic's ⚙ settings (the card's Mic settings button), laid out like a voice chat
app's voice settings so they're where people coming from one look: presets, Input
volume, Input sensitivity (with the live bar), Noise suppression and Automatic gain
control. This only shows and edits the settings (voicefx.cleanmic.clean_settings); the
card (cleanmicpanel) keeps them, hands them to the chain and does Strong's download.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QStyle, QStyleOptionSlider, QVBoxLayout, QWidget)

from soundboard.i18n import _
from soundboard.ui.kit import theme
from soundboard.ui.kit.panel import Flow, VolumeControl, hint_label, section_label
from soundboard.ui.kit.wheelguard import no_wheel
from soundboard.ui.kit.widgets import CrispSlider
from soundboard.ui.voice.fxcontrols import Switch
from soundboard.voicefx import cleanmic

QUIET, TALK = "#ffb020", "#13ce66"   # the sensitivity bar: under the line, over it
FALL_DB_S = 30.0                     # the bar falls back this fast (dB a second)


def strength_words(key: str) -> str:
    if key == "off":
        return _("Off: no noise is taken out. Input volume, sensitivity and gain control "
                 "still work.")
    if key == "light":
        return _("Light: noise is turned well down, and your voice stays most natural.")
    if key == "strong":
        return _("Strong: nearly everything but your voice goes, even loud noise. Uses "
                 "about twice Normal's CPU.")
    return _("Normal: fans, keyboards and a TV go. Uses about 5% of one CPU core.")


def preset_names() -> dict[str, str]:
    return {"normal": _("Normal"), "loud": _("Loud room"), "voice": _("Just my voice"),
            "quiet": _("Quiet room")}


def preset_words(key: str) -> str:
    if key == "loud":
        return _("Loud room: Strong cleaning and a stricter sensitivity, for loud fans, a TV or "
                 "people talking nearby.")
    if key == "voice":
        return _("Just my voice: Strong cleaning, a strict sensitivity and your voice kept at one "
                 "loudness. Quiet words can be cut: speak up.")
    if key == "quiet":
        return _("Quiet room: Light cleaning, and your voice stays most natural.")
    if key == "normal":
        return _("Normal: noise cleaned, and the sensitivity set by itself.")
    return _("Custom: your own settings. Pick a preset to start from one again.")


class SenseSlider(CrispSlider):
    """Input sensitivity: a slider (dB) whose track is your mic's live level, yellow
    under the line and green over it. Automatic: no handle, and the line is where the
    gate learned to open (set_level's `open_db`)."""

    BAND = 8   # px: the level's track

    def __init__(self):
        super().__init__(Qt.Orientation.Horizontal)
        self.setRange(cleanmic.SENSE_LO, 0)
        self.setMinimumWidth(160)
        self.setFixedHeight(24)
        self.level_db = -120.0
        self.line_db: float | None = None   # where the line sits while it's automatic
        self.auto = True
        self._span = (0.0, 1.0)   # the handle centre's travel (paintEvent)

    def set_level(self, db: float, open_db: float | None, dt: float):
        db = max(db, self.level_db - FALL_DB_S * dt)
        changed = (round(db) != round(self.level_db) or
                   (open_db is None) != (self.line_db is None) or
                   (open_db is not None and self.line_db is not None and
                    round(open_db) != round(self.line_db)))
        self.level_db, self.line_db = db, open_db
        if changed:
            self.update()

    def _x(self, groove: QRectF, db: float) -> float:
        lo, hi = self.minimum(), self.maximum()
        f = min(max((db - lo) / (hi - lo), 0.0), 1.0)
        left, width = self._span
        return left + width * f

    def paintEvent(self, e):
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        style = self.style()
        handle = style.subControlRect(QStyle.ComplexControl.CC_Slider, opt,
                                      QStyle.SubControl.SC_SliderHandle, self)
        # the track as long as the other sliders' (Input volume's above it); the line
        # moves as the handle's centre does
        groove = style.subControlRect(QStyle.ComplexControl.CC_Slider, opt,
                                      QStyle.SubControl.SC_SliderGroove, self)
        g = QRectF(groove.left(), (self.height() - self.BAND) / 2, groove.width(), self.BAND)
        half = handle.width() / 2
        self._span = (groove.left() + half, groove.width() - 2 * half)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        r = self.BAND / 2
        p.setBrush(QColor(theme.T["groove"]))
        p.drawRoundedRect(g, r, r)
        line = self.line_db if self.auto else float(self.value())
        lx = self._x(g, line) if line is not None else None
        x = self._x(g, self.level_db)
        if x > g.left() + 1:
            p.save()
            p.setClipRect(QRectF(g.left(), g.top(), x - g.left(), g.height()))
            if lx is None or lx >= x:
                p.setBrush(QColor(QUIET if lx is not None else TALK))
                p.drawRoundedRect(g, r, r)
            else:
                p.setBrush(QColor(QUIET))
                p.drawRoundedRect(QRectF(g.left(), g.top(), lx - g.left() + r, g.height()), r, r)
                p.setBrush(QColor(TALK))
                p.drawRect(QRectF(lx, g.top(), x - lx, g.height()))
            p.restore()
        if lx is None:
            p.end()
            return
        if self.auto or not self.isEnabled():   # the line only: nothing to drag
            p.setPen(QPen(QColor(theme.T["text_hi"]), 2))
            p.drawLine(round(lx), round(g.top() - 4), round(lx), round(g.bottom() + 4))
            p.end()
            return
        d = min(handle.width(), handle.height())
        circle = QRectF(lx - d / 2, self.height() / 2 - d / 2, d, d)
        p.setBrush(QColor(theme.T["text_hi"]))
        p.drawEllipse(circle)
        hovered = opt.activeSubControls == QStyle.SubControl.SC_SliderHandle
        if self.hasFocus() or hovered or self.isSliderDown():
            ring = self.hasFocus() or self.isSliderDown()
            width = 2 if ring else 1
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(theme.T["accent" if ring else "border_hi"]), width))
            p.drawEllipse(circle.adjusted(width / 2, width / 2, -width / 2, -width / 2))
        p.end()


class MicSettings(QFrame):
    """`edited(changes)`: settings the user changed ({"volume": 120}, ...);
    `strength_picked(key)`: a Noise suppression button (the card checks Strong's
    download); `preset_picked(key)`."""
    edited = Signal(dict)
    strength_picked = Signal(str)
    preset_picked = Signal(str)

    def __init__(self, s: dict):
        super().__init__()
        self.setObjectName("cleansettings")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 16)
        v.setSpacing(10)

        # ---- presets
        v.addWidget(section_label(_("Preset")))
        row = Flow(gap=4)
        self.b_preset: dict[str, QPushButton] = {}
        for key, name in preset_names().items():
            b = QPushButton(name)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(preset_words(key))
            b.setAccessibleName(_("{label} preset", label=name))
            b.clicked.connect(lambda _c=False, k=key: self.preset_picked.emit(k))
            self.b_preset[key] = b
            row.addWidget(b)
        v.addLayout(row)
        self.lbl_preset = hint_label("")
        v.addWidget(self.lbl_preset)

        # ---- input volume
        v.addWidget(section_label(_("Input volume")))
        self.volume = VolumeControl(s["volume"] / 100, slider_max=cleanmic.VOLUME_MAX,
                                    typed_max=cleanmic.VOLUME_MAX,
                                    tip=_("Your mic turned up or down before it's cleaned"))
        self.volume.slider.setMaximumWidth(16777215)
        self.volume.slider.setAccessibleName(_("Input volume"))
        self.volume.setMaximumWidth(420)
        self.volume.changed.connect(lambda f: self.edited.emit({"volume": round(f * 100)}))
        v.addWidget(self.volume)

        # ---- input sensitivity
        v.addWidget(section_label(_("Input sensitivity")))
        ar = QHBoxLayout()
        ar.setSpacing(10)
        self.auto = Switch(_("Set input sensitivity automatically"), hover=False)
        self.auto.toggled.connect(lambda on: self.edited.emit({"auto_sense": on}))
        ar.addWidget(self.auto)
        lbl = QLabel(_("Set it automatically"))
        lbl.setBuddy(self.auto)
        ar.addWidget(lbl)
        ar.addStretch(1)
        v.addLayout(ar)
        sense_row = QWidget()
        sense_row.setMaximumWidth(420)   # as Input volume's: one column
        sr = QHBoxLayout(sense_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.setSpacing(4)
        self.sense = SenseSlider()
        self.sense.setAccessibleName(_("Input sensitivity"))
        self.sense.setToolTip(_("Your voice goes through above the line"))
        self.sense.valueChanged.connect(self._sense_moved)
        no_wheel(self.sense)
        sr.addWidget(self.sense, 1)
        self.lbl_db = QLabel("")
        self.lbl_db.setStyleSheet("font-weight:600;")   # as Input volume's %
        self.lbl_db.setFixedWidth(max(self.volume.spin.width(), self.lbl_db.fontMetrics()
                                      .horizontalAdvance("-100 dB") + 8))
        pol = self.lbl_db.sizePolicy()
        pol.setRetainSizeWhenHidden(True)   # the bar as long, automatic or not
        self.lbl_db.setSizePolicy(pol)
        sr.addWidget(self.lbl_db)
        v.addWidget(sense_row)
        self.lbl_sense = hint_label("")
        v.addWidget(self.lbl_sense)

        # ---- noise suppression
        v.addWidget(section_label(_("Noise suppression")))
        row = Flow(gap=4)
        self.strength = QButtonGroup(self)
        self.strength.setExclusive(True)
        self.b_strength: dict[str, QPushButton] = {}
        for key, name in (("off", _("Off")), ("light", _("Light")), ("normal", _("Normal")),
                          ("strong", _("Strong"))):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(strength_words(key))
            b.setAccessibleName(_("{label} cleaning", label=name))
            b.clicked.connect(lambda _c=False, k=key: self.strength_picked.emit(k))
            self.strength.addButton(b)
            self.b_strength[key] = b
            row.addWidget(b)
        v.addLayout(row)
        self.lbl_strength = hint_label("")
        v.addWidget(self.lbl_strength)
        self.under_strength = QVBoxLayout()   # the card's Strong download and warnings
        self.under_strength.setContentsMargins(0, 0, 0, 0)
        self.under_strength.setSpacing(6)
        v.addLayout(self.under_strength)

        # ---- automatic gain control
        v.addWidget(section_label(_("Automatic gain control")))
        gr = QHBoxLayout()
        gr.setSpacing(10)
        self.agc = Switch(_("Automatic gain control"), hover=False)
        self.agc.toggled.connect(lambda on: self.edited.emit({"agc": on}))
        gr.addWidget(self.agc)
        lbl = QLabel(_("Keep my voice at one loudness"))
        lbl.setBuddy(self.agc)
        gr.addWidget(lbl)
        gr.addStretch(1)
        v.addLayout(gr)
        v.addWidget(hint_label(_("Quiet and loud words come out alike. Only your voice: "
                                 "your sounds are added after it.")))
        self.show_settings(s)

    def _sense_moved(self, db: int):
        self.lbl_db.setText(_("{db} dB", db=db))
        if not self.sense.auto:
            self.edited.emit({"sense_db": db})

    def show_settings(self, s: dict):
        """The controls as `s` has them (no edited signals)."""
        for w in (self.volume, self.auto, self.sense, self.agc):
            w.blockSignals(True)
        try:
            pct = s["volume"]
            self.volume.slider.setValue(pct)
            self.volume.spin.setValue(pct)
            self.volume._paint(pct)
            self.auto.setChecked(s["auto_sense"])
            self.sense.auto = s["auto_sense"]
            self.sense.setValue(s["sense_db"])
            self.agc.setChecked(s["agc"])
        finally:
            for w in (self.volume, self.auto, self.sense, self.agc):
                w.blockSignals(False)
        self.sense.setEnabled(not s["auto_sense"])
        self.sense.setCursor(Qt.CursorShape.ArrowCursor if s["auto_sense"]
                             else Qt.CursorShape.PointingHandCursor)
        self.lbl_db.setVisible(not s["auto_sense"])
        self.lbl_db.setText(_("{db} dB", db=s["sense_db"]))
        self.sense.update()
        if not s["auto_sense"]:
            sense = _("Your voice goes through while the bar is green, past the handle. "
                      "Under it, yellow, your mic is turned down.")
        elif s["strength"] == "light":
            sense = _("Automatic. Light keeps the room: nothing is turned down between "
                      "your words.")
        else:
            sense = _("Automatic: it learns your room's level and lets your voice through "
                      "above it (the line).")
        self.lbl_sense.setText(sense)
        self.b_strength[s["strength"]].setChecked(True)
        self.lbl_strength.setText(strength_words(s["strength"]))
        preset = cleanmic.preset_of(s)
        for key, b in self.b_preset.items():
            b.setChecked(key == preset)
        self.lbl_preset.setText(preset_words(preset))

    def set_level(self, db: float, open_db: float | None, dt: float):
        self.sense.set_level(db if math.isfinite(db) else -120.0, open_db, dt)
