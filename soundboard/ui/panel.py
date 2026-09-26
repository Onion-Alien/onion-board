"""Self-contained pieces of the right-hand audio panel: a volume box (slider +
typed %) and the equalizer. They own their widgets and emit plain values; the
main window maps those onto the config and the engine."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QSlider, QSpinBox, QVBoxLayout, QWidget)

from soundboard.eq import BAND_LABELS as EQ_LABELS
from soundboard.eq import MAX_DB as EQ_MAX_DB
from soundboard.eq import PRESETS as EQ_PRESETS
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


class VolumeBox(QFrame):
    """A titled volume control: slider to SLIDER_MAX %, typed box to TYPED_MAX %.
    `changed` carries the gain as a factor (1.0 = 100 %)."""
    changed = Signal(float)
    SLIDER_MAX = 300    # slider travel; the typed box goes further
    TYPED_MAX = 1000

    def __init__(self, title: str, desc: str, value: float):
        super().__init__()
        self.setObjectName("volbox")
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(2)
        top = QHBoxLayout()
        t = QLabel(title)
        t.setStyleSheet("font-weight:600;")
        top.addWidget(t, 1)
        self.spin = QSpinBox()
        self.spin.setRange(0, self.TYPED_MAX)
        self.spin.setSuffix(" %")
        self.spin.setFixedWidth(82)
        self.spin.setAlignment(Qt.AlignRight)
        self.spin.setToolTip("Type an exact volume (0–1000%)")
        top.addWidget(self.spin)
        v.addLayout(top)
        v.addWidget(hint_label(desc))
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, self.SLIDER_MAX)
        v.addWidget(self.slider)
        no_wheel(self.slider, self.spin)

        pct0 = int(round(value * 100))
        self.slider.setValue(min(pct0, self.SLIDER_MAX))
        self.spin.setValue(pct0)
        self._paint(pct0)
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)

    def value(self) -> float:
        return self.spin.value() / 100

    def _paint(self, pct):
        col = "" if pct <= 100 else "color:#ffb020;" if pct <= 300 else "color:#ff4d4f;"
        self.spin.setStyleSheet(f"{col} font-weight:600;")   # normal: the theme's text colour

    def _from_slider(self, pct):
        self.spin.blockSignals(True)
        self.spin.setValue(pct)
        self.spin.blockSignals(False)
        self._paint(pct)
        self.changed.emit(pct / 100)

    def _from_spin(self, pct):
        self.slider.blockSignals(True)
        self.slider.setValue(min(pct, self.SLIDER_MAX))
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
        row.addWidget(QLabel("for"))
        self.cb_target = QComboBox()
        for label, key in (("🎤 My voice", "voice"), ("🔊 My sounds", "sounds"),
                           ("Both", "all")):
            self.cb_target.addItem(label, key)
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

    def state(self) -> tuple[list[float], bool, str, str]:
        return (self.gains(), self.chk_on.isChecked(), self.cb_target.currentData(),
                self.cb_preset.currentText())

    # ---- internals
    def _set_sliders(self, gains):
        for s, g in zip(self.sliders, gains):
            s.blockSignals(True)
            s.setValue(int(round(g * 2)))
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
