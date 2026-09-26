"""Settings → General → "Who's listening": pick the destination mode that shapes
the sounds bus for the voice chat on the other end (soundboard.destination),
and an editor for custom modes (describe any other codec by the same knobs)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QSlider,
                               QVBoxLayout, QWidget)

from soundboard import destination
from soundboard.destination import CEILINGS, Dest
from soundboard.ui import fit
from soundboard.ui.panel import hint_label
from soundboard.wheelguard import no_wheel


def describe(d: Dest) -> str:
    """One line of what a mode does, for the label under the picker."""
    if not d.active:
        return d.note
    parts = []
    if d.mono:
        parts.append("mono")
    if d.bass > 0:
        parts.append(f"sub-bass harmonics {round(d.bass * 100)}%")
    if d.comp > 0:
        parts.append(f"compressor {round(d.comp * 100)}%")
    if d.ceiling:
        parts.append(f"cut above {d.ceiling // 1000} kHz")
    what = " · ".join(parts)
    return f"{d.note}  ({what})" if d.note else what


def ceiling_label(hz: int) -> str:
    return "No cut (full band)" if not hz else f"Cut above {hz // 1000} kHz"


class DestPanel(QWidget):
    """Mode picker + description + the custom-modes button. Applies to the engine
    and saves through the main window straight away."""

    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        row = QHBoxLayout()
        self.combo = QComboBox()
        no_wheel(self.combo)
        row.addWidget(self.combo, 1)
        custom = QPushButton("Custom modes…")
        custom.setToolTip("Describe another codec or service by what it does to the sound")
        custom.clicked.connect(self.edit_custom)
        row.addWidget(custom)
        v.addLayout(row)
        self.desc = hint_label("")
        v.addWidget(self.desc)
        self.refresh()
        self.combo.currentIndexChanged.connect(self._picked)

    def _cfg(self) -> dict:
        d = self.mw.cfg.dest
        if not isinstance(d, dict):
            d = self.mw.cfg.dest = {}
        return d

    def refresh(self):
        cfg = self._cfg()
        current = destination.resolve(cfg).key
        self.combo.blockSignals(True)
        self.combo.clear()
        for d in destination.all_modes(cfg.get("custom")):
            self.combo.addItem(d.label + ("  (custom)" if d.custom else ""), d.key)
        self.combo.setCurrentIndex(max(0, self.combo.findData(current)))
        self.combo.blockSignals(False)
        self._show()

    def _show(self):
        d = destination.resolve(self._cfg())
        self.desc.setText(describe(d))

    def _picked(self, i: int):
        key = self.combo.itemData(i)
        if key is None:
            return
        self._cfg()["mode"] = key
        destination.apply(self.mw.cfg, self.mw.engine)
        self.mw._save_later()
        self._show()

    def edit_custom(self):
        dlg = CustomDestDialog(self.mw, self)
        dlg.exec()
        self.refresh()


class CustomDestDialog(QDialog):
    """Add / edit / remove custom destination modes. Edits land in the config (and
    on the engine, if the edited mode is the one in use) as they're made."""
    changed = Signal()

    def __init__(self, mw, parent=None):
        super().__init__(parent or mw)
        fit.watch(self)
        self.mw = mw
        self.setWindowTitle("Custom destination modes")
        self.setMinimumSize(640, 420)
        cfg = mw.cfg.dest if isinstance(mw.cfg.dest, dict) else {}
        mw.cfg.dest = cfg
        self.items: list[dict] = [d for d in cfg.get("custom", []) if isinstance(d, dict)]
        cfg["custom"] = self.items
        self._loading = False

        lay = QVBoxLayout(self)
        lay.addWidget(hint_label(
            "A mode describes what the listener's voice codec does to your sounds, so the "
            "app can pre-shape them: which frequencies it cuts, how much sub-bass to turn "
            "into harmonics that survive, how much to even out the level, and whether it's "
            "mono. The built-in modes were measured; to measure another service, run "
            "scripts/codec_bench.py from the source tree."))
        body = QHBoxLayout()
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._select)
        left.addWidget(self.list, 1)
        btns = QHBoxLayout()
        self.b_add = QPushButton("Add")
        self.b_add.clicked.connect(self.add)
        self.b_copy = QPushButton("Copy built-in…")
        self.b_copy.setToolTip("Start from one of the measured modes")
        self.b_copy.clicked.connect(self.copy_builtin)
        self.b_del = QPushButton("Remove")
        self.b_del.clicked.connect(self.remove)
        for b in (self.b_add, self.b_copy, self.b_del):
            b.setObjectName("small")
            btns.addWidget(b)
        left.addLayout(btns)
        body.addLayout(left, 1)

        self.form_box = QWidget()
        form = QFormLayout(self.form_box)
        form.setLabelAlignment(Qt.AlignRight)
        self.name = QLineEdit()
        self.name.setMaxLength(40)
        self.name.textEdited.connect(self._edited)
        form.addRow("Name", self.name)
        self.ceiling = QComboBox()
        for hz in CEILINGS:
            self.ceiling.addItem(ceiling_label(hz), hz)
        self.ceiling.currentIndexChanged.connect(self._edited)
        form.addRow("Frequencies", self.ceiling)
        self.bass, bass_row = self._slider("sub-bass turned into harmonics the codec keeps")
        form.addRow("Sub-bass", bass_row)
        self.comp, comp_row = self._slider("evens the level out for the service's gate / auto gain")
        form.addRow("Compressor", comp_row)
        self.mono = QCheckBox("Mono (the service captures a mono mic)")
        self.mono.toggled.connect(self._edited)
        form.addRow("", self.mono)
        self.note = QLineEdit()
        self.note.setMaxLength(200)
        self.note.setPlaceholderText("e.g. Mumble at 72 kbps, TeamSpeak…")
        self.note.textEdited.connect(self._edited)
        form.addRow("Notes", self.note)
        no_wheel(self.ceiling, self.bass, self.comp)
        body.addWidget(self.form_box, 2)
        lay.addLayout(body, 1)

        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.accept)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)
        self._fill()

    # ------------------------------------------------------------------ widgets
    def _slider(self, tip: str) -> tuple[QSlider, QWidget]:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        s = QSlider(Qt.Horizontal)
        s.setRange(0, 100)
        s.setToolTip(tip)
        lbl = QLabel("0%")
        lbl.setFixedWidth(40)
        lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        s.valueChanged.connect(lambda v: lbl.setText(f"{v}%"))
        s.valueChanged.connect(self._edited)
        h.addWidget(s, 1)
        h.addWidget(lbl)
        return s, w

    # ------------------------------------------------------------------ list
    def _fill(self, select: int | None = None):
        self.list.blockSignals(True)
        self.list.clear()
        for raw in self.items:
            self.list.addItem(Dest.from_dict(raw).label)
        self.list.blockSignals(False)
        if self.items:
            self.list.setCurrentRow(min(select if select is not None else 0, len(self.items) - 1))
        self._select(self.list.currentRow())

    def _select(self, row: int):
        ok = 0 <= row < len(self.items)
        self.form_box.setEnabled(ok)
        self.b_del.setEnabled(ok)
        if not ok:
            return
        d = Dest.from_dict(self.items[row])
        self._loading = True
        self.name.setText(d.label)
        self.ceiling.setCurrentIndex(max(0, self.ceiling.findData(d.ceiling)))
        if self.ceiling.findData(d.ceiling) < 0:      # a hand-edited value: keep it
            self.ceiling.insertItem(1, ceiling_label(d.ceiling), d.ceiling)
            self.ceiling.setCurrentIndex(1)
        self.bass.setValue(round(d.bass * 100))
        self.comp.setValue(round(d.comp * 100))
        self.mono.setChecked(d.mono)
        self.note.setText(d.note)
        self._loading = False

    def _new_key(self) -> str:
        used = {d.get("key") for d in self.items} | set(destination.BUILTIN_BY_KEY)
        n = 1
        while f"custom{n}" in used:
            n += 1
        return f"custom{n}"

    def add(self):
        self.items.append(Dest(self._new_key(), f"My mode {len(self.items) + 1}", 0, 0.5, 0.4,
                               True).to_dict())
        self._fill(len(self.items) - 1)
        self._commit()
        self.name.setFocus()
        self.name.selectAll()

    def copy_builtin(self):
        from PySide6.QtWidgets import QInputDialog
        names = [d.label for d in destination.BUILTIN if d.active]
        pick, ok = QInputDialog.getItem(self, "Copy a built-in mode", "Start from", names, 0, False)
        if not ok:
            return
        src = next(d for d in destination.BUILTIN if d.label == pick)
        raw = src.to_dict()
        raw.update(key=self._new_key(), label=f"{src.label} (copy)")
        self.items.append(raw)
        self._fill(len(self.items) - 1)
        self._commit()

    def remove(self):
        row = self.list.currentRow()
        if not (0 <= row < len(self.items)):
            return
        gone = self.items.pop(row)
        cfg = self.mw.cfg.dest
        if cfg.get("mode") == gone.get("key"):
            cfg["mode"] = "off"
        self._fill(row)
        self._commit()

    # ------------------------------------------------------------------ edits
    def _edited(self, *_):
        if self._loading:
            return
        row = self.list.currentRow()
        if not (0 <= row < len(self.items)):
            return
        raw = self.items[row]
        raw.update(label=self.name.text().strip() or raw.get("key", "custom"),
                   ceiling=int(self.ceiling.currentData() or 0),
                   bass=self.bass.value() / 100, comp=self.comp.value() / 100,
                   mono=self.mono.isChecked(), note=self.note.text().strip())
        item = self.list.item(row)
        if item is not None and item.text() != raw["label"]:
            item.setText(raw["label"])
        self._commit()

    def _commit(self):
        destination.apply(self.mw.cfg, self.mw.engine)   # picks up edits to the mode in use
        self.mw._save_later()
        self.changed.emit()
