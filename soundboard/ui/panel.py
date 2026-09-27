"""Shared UI building blocks: the bar / card / divider helpers every tab is built
from, the compact volume control (slider + typed %), and the equalizer. They own
their widgets and emit plain values; the main window maps those onto the config
and the engine."""
from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLayout, QSlider, QSpinBox, QVBoxLayout, QWidget)

from soundboard import theme
from soundboard.eq import BAND_LABELS as EQ_LABELS
from soundboard.eq import MAX_DB as EQ_MAX_DB
from soundboard.eq import PRESETS as EQ_PRESETS
from soundboard.ui import icons
from soundboard.ui.widgets import EqCurve
from soundboard.wheelguard import no_wheel


def section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("section")
    return lbl


def hint_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setObjectName("hint")
    return lbl


def vsep() -> QFrame:
    """A thin vertical divider between groups in a bar."""
    f = QFrame()
    f.setObjectName("vsep")
    f.setFixedWidth(1)
    return f


def bar(margins=(10, 8, 12, 8)) -> tuple[QFrame, QHBoxLayout]:
    """The rounded control bar every tab has along its bottom (and the mixer strip)."""
    f = QFrame()
    f.setObjectName("transport")
    h = QHBoxLayout(f)
    h.setContentsMargins(*margins)
    h.setSpacing(10)
    return f, h


class Flow(QLayout):
    """Lays its widgets out left to right, wrapping onto new lines (the Radio tab's
    genre chips, the Triggers tab's settings)."""

    def __init__(self, parent=None, gap: int = 6):
        super().__init__(parent)
        self._items, self._gap = [], gap
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._place(QRect(0, 0, w, 0), move=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, move=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        return size

    def _place(self, rect: QRect, move: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        for it in self._items:
            if it.isEmpty():
                continue
            hint = it.sizeHint()
            if line and x + hint.width() > rect.right() + 1:
                x, y, line = rect.x(), y + line + self._gap, 0
            if move:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._gap
            line = max(line, hint.height())
        return y + line - rect.y()


def card(title: str = "", hint: str = "") -> tuple[QFrame, QVBoxLayout]:
    """A titled card, the building block of the Voice and Setup pages."""
    f = QFrame()
    f.setObjectName("card")
    v = QVBoxLayout(f)
    v.setContentsMargins(14, 8, 14, 14)
    v.setSpacing(6)
    if title:
        v.addWidget(section_label(title))
    if hint:
        v.addWidget(hint_label(hint))
    return f, v


def icon_label(name: str, tip: str = "", color: str = "muted") -> QLabel:
    """A small painted icon used as a label in the bars."""
    lbl = QLabel()
    icons.set_label_icon(lbl, name, color)
    lbl.setToolTip(tip)
    lbl.setObjectName("iconlabel")
    return lbl


class VolumeControl(QWidget):
    """Slider to `slider_max` %, plus a box you can type an exact % into (up to
    `typed_max`). `changed` carries the gain as a factor (1.0 = 100 %)."""
    changed = Signal(float)

    def __init__(self, value: float, slider_max: int = 300, typed_max: int = 1000,
                 tip: str = ""):
        super().__init__()
        self.slider_max = slider_max
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, slider_max)
        self.slider.setMinimumWidth(70)
        self.slider.setMaximumWidth(150)
        self.spin = QSpinBox()
        self.spin.setRange(0, typed_max)
        self.spin.setSuffix(" %")
        self.spin.setFixedWidth(74)
        self.spin.setAlignment(Qt.AlignRight)
        self.spin.setToolTip(f"Type an exact volume (0–{typed_max}%)")
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
        self.spin.setStyleSheet(f"{col} font-weight:600;")   # normal: the theme's text colour

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
    `changed(gains, enabled, target, preset)` fires on any change."""
    changed = Signal(list, bool, str, str)

    def __init__(self, enabled: bool, target: str, preset: str, gains: list[float]):
        super().__init__()
        pv = QVBoxLayout(self)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(8)
        pv.addWidget(section_label("EQUALIZER"))
        row = QHBoxLayout()
        self.chk_on = QCheckBox("EQ on")
        self.chk_on.setChecked(enabled)
        row.addWidget(self.chk_on)
        self.lbl_for = QLabel("for")
        row.addWidget(self.lbl_for)
        self.cb_target = QComboBox()
        for ic, label, key in (("mic", "My voice", "voice"), ("volume", "My sounds", "sounds"),
                               ("wave", "Both", "all")):
            self.cb_target.addItem(icons.icon(ic), label, key)
        self.cb_target.setCurrentIndex(max(0, self.cb_target.findData(target)))
        row.addWidget(self.cb_target, 1)
        pv.addLayout(row)

        self.cb_preset = QComboBox()
        self.cb_preset.addItems(list(EQ_PRESETS))
        self.cb_preset.addItem("Custom")
        pv.addWidget(self.cb_preset)
        no_wheel(self.cb_target, self.cb_preset)

        self.curve = EqCurve()
        pv.addWidget(self.curve)

        grid = QGridLayout()
        grid.setHorizontalSpacing(2)
        grid.setVerticalSpacing(2)
        self.sliders, self.vals = [], []
        for i, lab in enumerate(EQ_LABELS):
            val = QLabel("0")
            val.setAlignment(Qt.AlignCenter)
            val.setObjectName("eqlabel")
            s = QSlider(Qt.Vertical)
            s.setRange(-EQ_MAX_DB * 2, EQ_MAX_DB * 2)   # half-dB steps
            s.setFixedHeight(96)
            s.setToolTip(f"{lab} Hz")
            f = QLabel(lab)
            f.setAlignment(Qt.AlignCenter)
            f.setObjectName("eqlabel")
            grid.addWidget(val, 0, i)
            grid.addWidget(s, 1, i, Qt.AlignHCenter)
            grid.addWidget(f, 2, i)
            s.valueChanged.connect(self._on_slider)
            self.sliders.append(s)
            self.vals.append(val)
        no_wheel(*self.sliders)
        pv.addLayout(grid)
        pv.addWidget(hint_label("Low = bass (left) · high = treble (right). Drag up to boost, "
                                "down to cut. Double-click the curve to reset."))

        self._set_sliders(gains)
        self.cb_preset.setCurrentText(preset if preset in EQ_PRESETS else "Custom")
        self.chk_on.toggled.connect(lambda _on: self._emit())
        self.cb_target.currentIndexChanged.connect(lambda _i: self._emit())
        self.cb_preset.currentTextChanged.connect(self._on_preset)
        self.curve.reset.connect(lambda: self.cb_preset.setCurrentText("Flat (off)"))
        self._refresh(emit=False)

    # ---- state
    def gains(self) -> list[float]:
        return [s.value() / 2 for s in self.sliders]

    def set_gains(self, gains: list[float], preset: str = "Custom"):
        """Load gains, turning the EQ on unless they're flat. Emits `changed`."""
        self._set_sliders(gains)
        self.cb_preset.blockSignals(True)
        self.cb_preset.setCurrentText(preset if preset in EQ_PRESETS else "Custom")
        self.cb_preset.blockSignals(False)
        self.chk_on.blockSignals(True)
        self.chk_on.setChecked(any(abs(g) >= 0.05 for g in self.gains()))
        self.chk_on.blockSignals(False)
        self._emit()

    def state(self) -> tuple[list[float], bool, str, str]:
        return (self.gains(), self.chk_on.isChecked(), self.cb_target.currentData(),
                self.cb_preset.currentText())

    # ---- internals
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
        self.cb_preset.setCurrentText("Custom")
        self.cb_preset.blockSignals(False)
        if not self.chk_on.isChecked():
            self.chk_on.setChecked(True)   # touching the EQ means you want it on (emits)
            return
        self._emit()

    def _on_preset(self, name):
        if name in EQ_PRESETS:
            self._set_sliders(EQ_PRESETS[name])
            if name != "Flat (off)" and not self.chk_on.isChecked():
                self.chk_on.setChecked(True)   # emits
                return
        self._emit()

    def _refresh(self, emit=True):
        gains, on, _target, _preset = self.state()
        self.curve.set_gains(gains, on)
        for w in self.sliders + [self.cb_target]:
            w.setProperty("dim", not on)
        if emit:
            self.changed.emit(*self.state())

    def _emit(self):
        self._refresh(emit=True)
