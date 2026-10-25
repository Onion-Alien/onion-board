"""The page kit's bigger controls (ui/kit/panel.py): `VolumeControl` (a slider, a typed percent
up to the most and a level dot), `EqPanel` (the equaliser's sliders and presets) and `UndoBar`
(the undo toast after a delete). `panel` re-exports them."""
from __future__ import annotations

import html
import math
import re

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from soundboard.audio.eq import BAND_LABELS as EQ_LABELS, MAX_DB as EQ_MAX_DB, PRESETS as EQ_PRESETS
from soundboard.i18n import _
from soundboard.ui.kit import icons, theme
from soundboard.ui.kit.panellabels import hint_label, section_label
from soundboard.ui.kit.pixels import snap_to_pixels
from soundboard.ui.kit.wheelguard import no_wheel
from soundboard.ui.kit.widgets import CrispSlider, EqCurve, Meter


class _LevelDot(Meter):
    """Audio activity beside a volume control, without a second slider-like track."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(6, 6)
        self.setAccessibleName(_("Audio activity"))
        self.setToolTip(_("Audio activity: green is signal, amber is loud, red is near clipping"))

    def paintEvent(self, e):
        frac, color = self._bar()
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color if frac > 0 else theme.T["groove"]))
        p.drawEllipse(self.rect())
        p.end()


class _Pct(QSpinBox):
    """The typeable %: as wide as its longest value in the font the theme gives it
    (known only once styled: "1000 %" in Retro 98's Tahoma didn't fit a fixed 58 px).
    Typing sets the volume once, on a pause, Enter or a click away (ui/numberbox):
    as each digit came in, "150" went 1 %, 15 %, 150 % (a dip on a live mic) and saved three times.
    A number past either end is capped there on Enter: Qt's own check dropped the key
    that took it out of range, so "5000" set 500 %, "9999" 999 % and "-50" +50 %."""

    def __init__(self):
        super().__init__()
        self.setKeyboardTracking(False)

    def _typed(self, text: str) -> str:
        return text.removesuffix(self.suffix()).strip()

    def validate(self, text, pos):
        state, text, pos = super().validate(text, pos)
        if state == QValidator.State.Invalid and re.fullmatch(r"-?\d{0,6}", self._typed(text)):
            state = QValidator.State.Intermediate   # fixup() caps it on Enter
        return state, text, pos

    def fixup(self, text):
        num = self._typed(text)
        if re.fullmatch(r"-?\d{1,6}", num):
            return self.textFromValue(min(max(int(num), self.minimum()), self.maximum()))
        return super().fixup(text)

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            text = f"{self.maximum()}{self.suffix()}"
            self.setFixedWidth(max(58, self.fontMetrics().horizontalAdvance(text) + 14))


class VolumeControl(QWidget):
    """Slider to `slider_max` %, plus a % you can click and type an exact value into
    (up to `typed_max`). `changed` carries the gain as a factor (1.0 = 100 %).
    With `meter`, a small audio-activity dot (`.meter`) sits beside the slider."""
    changed = Signal(float)

    def __init__(self, value: float, slider_max: int = 300, typed_max: int = 1000,
                 tip: str = "", meter: bool = False):
        super().__init__()
        self.slider_max = slider_max
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        self.slider = CrispSlider(Qt.Orientation.Horizontal)
        self.meter = _LevelDot() if meter else None
        if self.meter is not None:
            h.addWidget(self.meter)
        self.slider.setRange(0, slider_max)
        self.slider.setMinimumWidth(70)
        self.slider.setMaximumWidth(150)
        self.spin = _Pct()
        self.spin.setObjectName("pct")   # reads as plain text until hovered / typed in
        self.spin.setRange(0, typed_max)
        self.spin.setSuffix("%")
        self.spin.setFixedWidth(58)   # until it's styled (_Pct)
        # beside its slider, on the row's centre line: right-aligned in a box as wide as
        # "1000%", "70%" sat 30-40 px away from its slider
        self.spin.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        # its text box rounds the centring down: the digits sat 1-1.5 px under the
        # slider and the labels beside it (measured ink); 2 px less at the bottom
        # moves the centre up by one
        self.spin.lineEdit().setTextMargins(0, 0, 0, 2)
        self.spin.setToolTip(_("Type an exact volume (0–{typed_max}%)", typed_max=typed_max))
        if tip:
            self.slider.setToolTip(tip)
        h.addWidget(self.slider, 1)
        h.addWidget(self.spin)
        no_wheel(self.slider, self.spin)

        pct0 = int(round(value * 100))
        self.slider.setValue(min(pct0, slider_max))
        self.spin.setValue(pct0)
        self._paint(pct0)
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)

    def value(self) -> float:
        return self.spin.value() / 100

    def _paint(self, pct):
        col = ("" if pct <= 100 else f"color:{theme.status('warn' if pct <= 300 else 'error')};")
        sheet = f"{col} font-weight:600;"   # normal: the theme's text colour
        if sheet != self.spin.styleSheet():   # each set re-polishes it: only on a change
            self.spin.setStyleSheet(sheet)

    def _from_slider(self, pct):
        self.spin.blockSignals(True)
        self.spin.setValue(pct)
        self.spin.blockSignals(False)
        self._paint(pct)
        self.changed.emit(pct / 100)

    def _from_spin(self, pct):
        self.slider.blockSignals(True)
        self.slider.setValue(min(pct, self.slider_max))
        self.slider.blockSignals(False)
        self._paint(pct)
        self.changed.emit(pct / 100)


class EqPanel(QWidget):
    """On/off, target, preset, curve and the seven band sliders.
    `changed(gains, enabled, target, preset)` fires on any change. `fold`: while the EQ
    is off, only its heading and on/off row show (the Setup tab: seven flat sliders and
    an empty curve took a third of it)."""
    changed = Signal(list, bool, str, str)

    def __init__(self, enabled: bool, target: str, preset: str, gains: list[float],
                 fold: bool = False):
        super().__init__()
        self.fold = fold
        pv = QVBoxLayout(self)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(8)
        if not fold:   # (Setup's: the card it's in has the title)
            pv.addWidget(section_label(_("Equalizer")))
        row = QHBoxLayout()
        self.chk_on = QCheckBox(_("EQ on"))
        self.chk_on.setChecked(enabled)
        row.addWidget(self.chk_on)
        self.lbl_for = QLabel(_("for"))
        row.addWidget(self.lbl_for)
        self.cb_target = QComboBox()
        self.cb_target.setAccessibleName(_("Equalizer"))   # (the "for" before it is no name)
        for label, key in ((_("My voice"), "voice"), (_("My sounds"), "sounds"),
                           (_("Both"), "all")):
            self.cb_target.addItem(label, key)
        icons.set_item_icons(self.cb_target, ["mic", "volume", "wave"])
        self.cb_target.setCurrentIndex(max(0, self.cb_target.findData(target)))
        row.addWidget(self.cb_target)
        row.addStretch(1)
        pv.addLayout(row)
        self.body = QWidget()   # everything under the on/off row (folds away: `fold`)
        bv = QVBoxLayout(self.body)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(8)
        pv.addWidget(self.body)

        self.cb_preset = QComboBox()
        self.cb_preset.setAccessibleName(_("Preset"))   # (folded away until EQ is on)
        # the item data is the preset's key, "Custom" for none; the keys are saved in
        # config, so they keep their old dash and only the shown name drops it
        for name in EQ_PRESETS:
            self.cb_preset.addItem(name.replace(" — ", ": "), name)
        self.cb_preset.addItem(_("Custom"), "Custom")
        bv.addWidget(self.cb_preset)
        no_wheel(self.cb_target, self.cb_preset)

        self.curve = EqCurve()
        bv.addWidget(self.curve)

        grid = QGridLayout()
        grid.setHorizontalSpacing(2)
        grid.setVerticalSpacing(2)
        self.sliders, self.vals = [], []
        for i, lab in enumerate(EQ_LABELS):
            val = QLabel("0")
            val.setAlignment(Qt.AlignmentFlag.AlignCenter)
            val.setObjectName("eqlabel")
            s = QSlider(Qt.Orientation.Vertical)
            s.setRange(-EQ_MAX_DB * 2, EQ_MAX_DB * 2)   # half-dB steps
            s.setFixedHeight(96)
            s.setAccessibleName(_("{lab} Hz", lab=lab))   # its label is under it
            f = QLabel(lab)
            f.setAlignment(Qt.AlignmentFlag.AlignCenter)
            f.setObjectName("eqlabel")
            grid.addWidget(val, 0, i)
            grid.addWidget(s, 1, i, Qt.AlignmentFlag.AlignHCenter)
            grid.addWidget(f, 2, i)
            s.valueChanged.connect(self._on_slider)
            self.sliders.append(s)
            self.vals.append(val)
        no_wheel(*self.sliders)
        bv.addLayout(grid)
        bv.addWidget(hint_label(_("Low = bass (left) · high = treble (right). Drag up to boost, "
                                  "down to cut. Double-click the curve to reset.")))

        self._set_sliders(gains)
        self._show_preset(preset)
        self.chk_on.toggled.connect(lambda _on: self._emit())
        self.cb_target.currentIndexChanged.connect(lambda _i: self._emit())
        self.cb_preset.currentIndexChanged.connect(
            lambda _i: self._on_preset(self.cb_preset.currentData()))
        self.curve.reset.connect(self._reset)
        self._refresh(emit=False)

    # ---- state
    def gains(self) -> list[float]:
        return [s.value() / 2 for s in self.sliders]

    def set_gains(self, gains: list[float], preset: str = "Custom"):
        """Load gains, turning the EQ on unless they're flat. Emits `changed`."""
        self._set_sliders(gains)
        self.cb_preset.blockSignals(True)
        self._show_preset(preset)
        self.cb_preset.blockSignals(False)
        self.chk_on.blockSignals(True)
        self.chk_on.setChecked(any(abs(g) >= 0.05 for g in self.gains()))
        self.chk_on.blockSignals(False)
        self._emit()

    def state(self) -> tuple[list[float], bool, str, str]:
        return (self.gains(), self.chk_on.isChecked(), self.cb_target.currentData(),
                self.cb_preset.currentData())

    # ---- internals
    def _show_preset(self, preset: str):
        """Select `preset` (a key of EQ_PRESETS) in the box, or Custom."""
        key = preset if preset in EQ_PRESETS else "Custom"
        self.cb_preset.setCurrentIndex(max(0, self.cb_preset.findData(key)))

    def _set_sliders(self, gains):
        # a damaged config can hand us anything: a band that isn't a finite number, or
        # a list of the wrong length, is flat (0 dB) instead of an error
        if not isinstance(gains, (list, tuple)) or len(gains) != len(self.sliders):
            gains = [0.0] * len(self.sliders)
        for s, g in zip(self.sliders, gains):
            ok = isinstance(g, (int, float)) and not isinstance(g, bool) and math.isfinite(g)
            s.blockSignals(True)
            s.setValue(int(round(min(max(g, -EQ_MAX_DB), EQ_MAX_DB) * 2)) if ok else 0)
            s.blockSignals(False)
        self._refresh_labels()

    def _refresh_labels(self):
        for s, lab in zip(self.sliders, self.vals):
            g = s.value() / 2
            lab.setText(f"{g:+g}" if g else "0")

    def _on_slider(self, _v):
        self._refresh_labels()
        self.cb_preset.blockSignals(True)
        self._show_preset("Custom")
        self.cb_preset.blockSignals(False)
        if not self.chk_on.isChecked():
            self.chk_on.setChecked(True)   # touching the EQ means you want it on (emits)
            return
        self._emit()

    def _reset(self):
        """Double-click on the curve: flat and off, even if it already says Flat."""
        self.cb_preset.blockSignals(True)
        self._show_preset("Flat (off)")
        self.cb_preset.blockSignals(False)
        self._on_preset("Flat (off)")

    def _on_preset(self, name):
        if name in EQ_PRESETS:
            self._set_sliders(EQ_PRESETS[name])
            # "Flat (off)" means off, like set_gains with flat gains; any other turns it on
            on = name != "Flat (off)"
            if self.chk_on.isChecked() != on:
                self.chk_on.setChecked(on)   # emits
                return
        self._emit()

    def _refresh(self, emit=True):
        gains, on, _target, _preset = self.state()
        self.curve.set_gains(gains, on)
        self.body.setVisible(on or not self.fold)
        for w in self.sliders + [self.cb_target]:
            if bool(w.property("dim")) != (not on):
                w.setProperty("dim", not on)
                w.style().unpolish(w)   # a property change alone doesn't restyle it
                w.style().polish(w)
                w.update()
        if emit:
            self.changed.emit(*self.state())

    def _emit(self):
        self._refresh(emit=True)


class UndoBar(QWidget):
    """"Deleted X · Undo" for a few seconds after something is thrown away, as a corner
    card (ui/kit/toast.py) with an Undo button; this widget itself is never seen.
    show_for(text, undo, done): Undo calls `undo`; the card timing out, being closed,
    or showing something else calls `done` (if given) instead."""
    SECONDS = 10

    def __init__(self, tip: str = ""):
        super().__init__()
        self.tip = tip or _("Put it back, exactly as it was")
        self.text = ""
        self._undo = self._done = None
        self._key = f"undo-{id(self)}"
        self.hide()

    def active(self) -> bool:
        """Is its card up (Undo still possible)?"""
        return self._undo is not None or self._done is not None

    def show_for(self, text: str, undo, done=None):
        from soundboard.ui.kit import busy
        self.finish()
        self.text = text
        self._undo, self._done = undo, done
        t = busy.toast(self, html.escape(text), "", self.SECONDS * 1000, key=self._key,
                       action=(_("Undo"), self.undo), on_close=self.finish)
        if t is not None:
            t.card.action.setToolTip(self.tip)

    def _take_down(self):
        from soundboard.ui.kit import toast
        toast.close(self, self._key)

    def undo(self):
        cb, self._undo, self._done = self._undo, None, None
        self._take_down()
        if cb is not None:
            cb()

    def finish(self):
        cb, self._undo, self._done = self._done, None, None
        self._take_down()
        if cb is not None:
            cb()
