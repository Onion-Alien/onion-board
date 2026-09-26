"""Per-sound Edit dialog."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider, QVBoxLayout)

from soundboard import theme
from soundboard.library import PAD_COLORS, SoundMeta
from soundboard.settings import HotkeyDialog, pretty_key
from soundboard.ui import icons
from soundboard.wheelguard import no_wheel
from soundboard.winkeys import Hotkeys


class EditDialog(QDialog):
    """Name, volume, press mode, loop, hotkey and colour of one sound. Nothing is
    written to the SoundMeta until `apply()`; `hotkeys_changed` fires after a
    capture so the owner can re-register the (paused) global hotkeys."""
    hotkeys_changed = Signal()

    def __init__(self, meta: SoundMeta, hotkeys: Hotkeys, preview_cb, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit sound")
        self.meta = meta
        self.hotkeys = hotkeys
        self.hotkey = meta.hotkey
        self.color = meta.color
        lay = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self.name = QLineEdit(meta.name)
        form.addRow("Name", self.name)

        vrow = QHBoxLayout()
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 200)
        self.vol.setValue(int(meta.volume * 100))
        no_wheel(self.vol)
        self.vol_lbl = QLabel()
        self.vol.valueChanged.connect(lambda v: self.vol_lbl.setText(f"{v}%"))
        self.vol_lbl.setText(f"{self.vol.value()}%")
        self.vol_lbl.setFixedWidth(42)
        vrow.addWidget(self.vol)
        vrow.addWidget(self.vol_lbl)
        form.addRow("Volume", vrow)

        self.mode = QComboBox()
        self.mode.addItem("Restart — press again restarts it", "restart")
        self.mode.addItem("Overlap — every press plays a new copy", "overlap")
        self.mode.addItem("Toggle — press again stops it", "toggle")
        self.mode.setCurrentIndex(max(0, self.mode.findData(meta.mode)))
        no_wheel(self.mode)
        form.addRow("On press", self.mode)

        self.loop = QCheckBox("Loop until stopped")
        self.loop.setChecked(meta.loop)
        form.addRow("", self.loop)

        hrow = QHBoxLayout()
        self.hk_btn = QPushButton()
        self.hk_btn.clicked.connect(self._capture)
        clr = QPushButton("Clear")
        clr.clicked.connect(lambda: self._set_hk(""))
        hrow.addWidget(self.hk_btn, 1)
        hrow.addWidget(clr)
        form.addRow("Hotkey", hrow)
        self._set_hk(self.hotkey)

        crow = QHBoxLayout()
        crow.setSpacing(6)
        self.swatches = []
        for c in PAD_COLORS:
            b = QPushButton()
            b.setFixedSize(24, 24)
            b.clicked.connect(lambda _=False, c=c: self._set_color(c))
            self.swatches.append((b, c))
            crow.addWidget(b)
        crow.addStretch()
        form.addRow("Colour", crow)
        self._set_color(self.color)
        lay.addLayout(form)

        prev = QPushButton("Preview (only you hear it)")
        icons.set_icon(prev, "headphones")
        prev.clicked.connect(lambda: preview_cb(self.meta.id, self.vol.value() / 100))
        lay.addWidget(prev)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.setMinimumWidth(460)

    def _set_color(self, c):
        self.color = c
        for b, col in self.swatches:
            border = (f"3px solid {theme.T['text']}" if col == c
                      else f"1px solid {theme.T['border']}")
            b.setStyleSheet(f"background:{col}; border:{border}; border-radius:12px;")

    def _set_hk(self, combo):
        self.hotkey = combo
        self.hk_btn.setText(pretty_key(combo) or "Click to set…")

    def _capture(self):
        d = HotkeyDialog(self.hotkeys, self)
        if d.exec() and d.result_combo:
            self._set_hk(d.result_combo)
        self.hotkeys_changed.emit()   # the capture paused them; the owner re-registers

    def apply(self):
        m = self.meta
        m.name = self.name.text().strip() or m.name
        m.volume = self.vol.value() / 100
        m.mode = self.mode.currentData()
        m.loop = self.loop.isChecked()
        m.hotkey = self.hotkey
        m.color = self.color
