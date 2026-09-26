"""Per-sound Edit dialog: the Sound tab (name, volume, hotkey…) and the Effects tab
(speed, pitch, EQ, boost, reverse and every voice effect, modules' included)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSlider,
                               QTabWidget, QVBoxLayout, QWidget)

from soundboard import soundfx, theme, voicefx
from soundboard.eq import PRESETS as EQ_PRESETS
from soundboard.library import MAX_FADE_S, PAD_COLORS, SoundMeta, clean_fade, original_peaks
from soundboard.settings import HotkeyDialog, pretty_key
from soundboard.ui import fit, icons
from soundboard.ui.panel import EqPanel, hint_label, section_label
from soundboard.ui.trim import TrimPanel
from soundboard.ui.voicepanel import EffectRow, ParamSlider
from soundboard.wheelguard import no_wheel
from soundboard.winkeys import Hotkeys

CUSTOM = "Custom"
SPEED = voicefx.Param("speed", "Speed", *soundfx.SPEED_RANGE, 1.0, "x", 0.05)
PITCH = voicefx.Param("pitch", "Pitch", *soundfx.PITCH_RANGE, 0.0, " st", 1)
BOOST = voicefx.Param("gain_db", "Boost", *soundfx.GAIN_RANGE, 0.0, " dB", 1)


class EffectsPanel(QWidget):
    """Every per-sound effect setting. `changed` fires on any edit; `fx()` is the
    settings dict for SoundMeta.fx ({} when nothing is changed)."""
    changed = Signal()

    def __init__(self, fx: dict | None, meta: SoundMeta | None = None):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 8, 0)
        v.setSpacing(8)

        prow = QHBoxLayout()
        prow.addWidget(QLabel("Preset"))
        self.preset = QComboBox()
        self.preset.addItems(list(soundfx.PRESETS) + [CUSTOM])
        no_wheel(self.preset)
        prow.addWidget(self.preset, 1)
        reset = QPushButton("Reset")
        reset.setObjectName("small")
        reset.setToolTip("Back to the original sound (the trim stays)")
        reset.clicked.connect(lambda: self.preset.setCurrentText(next(iter(soundfx.PRESETS))))
        prow.addWidget(reset)
        v.addLayout(prow)

        v.addWidget(section_label("TRIM"))
        peaks, length = original_peaks(meta) if meta is not None else ([], 0.0)
        self.trim = TrimPanel(peaks, length)
        self.trim.setVisible(length > 0)
        v.addWidget(self.trim)
        if length <= 0:
            v.addWidget(hint_label("Trimming works once the sound has loaded."))

        v.addWidget(section_label("SPEED & PITCH"))
        self.speed = ParamSlider(SPEED, 1.0)
        self.pitch = ParamSlider(PITCH, 0.0)
        self.tape = QCheckBox("Tape mode: speed changes the pitch too (nightcore / slowed)")
        self.tape.setToolTip("Off: speed and pitch are independent. On: like a record player, "
                             "faster is also higher; Pitch adds on top.")
        for w in (self.speed, self.pitch, self.tape):
            v.addWidget(w)

        v.addWidget(section_label("LOUDNESS"))
        self.boost = ParamSlider(BOOST, 0.0)
        v.addWidget(self.boost)
        self.boost_hint = hint_label("")
        v.addWidget(self.boost_hint)
        self.reverse = QCheckBox("Play backwards")
        v.addWidget(self.reverse)

        self.eq = EqPanel(False, "sounds", "Flat (off)", [0.0] * 7)
        self.eq.lbl_for.hide()
        self.eq.cb_target.hide()
        v.addWidget(self.eq)

        v.addWidget(section_label("EFFECTS"))
        self.rows: dict[str, EffectRow] = {}
        for etype, cls in voicefx.REGISTRY.items():
            if etype == "pitch":   # the Pitch slider above does this, better
                continue
            row = EffectRow(cls, {})
            row.changed.connect(self._edited)
            self.rows[etype] = row
            v.addWidget(row)
        v.addWidget(hint_label("Effects from add-on modules show up here too."))
        v.addStretch(1)

        self.load(fx or {})
        for s in (self.speed, self.pitch, self.boost):
            s.changed.connect(self._edited)
        self.tape.toggled.connect(self._edited)
        self.reverse.toggled.connect(self._edited)
        self.trim.changed.connect(self._edited)
        self.eq.changed.connect(lambda *_: self._edited())
        self.preset.currentTextChanged.connect(self._on_preset)
        self._matching_preset()

    def load(self, fx: dict):
        f = soundfx.clean(fx)
        widgets = (self.speed, self.pitch, self.boost, self.tape, self.reverse, self.eq,
                   self.trim, *self.rows.values())
        for w in widgets:
            w.blockSignals(True)
        self.trim.set_values(f["start"], f["end"])
        self.speed.set_value(f["speed"])
        self.pitch.set_value(f["pitch"])
        self.boost.set_value(f["gain_db"])
        self.tape.setChecked(f["tape"])
        self.reverse.setChecked(f["reverse"])
        self.eq.set_gains(f["eq"], next((n for n, g in EQ_PRESETS.items() if g == f["eq"]),
                                        CUSTOM))
        for etype, row in self.rows.items():
            cfg = f["effects"].get(etype)
            row.load(cfg if cfg and cfg.get("on") else {"on": False})
        for w in widgets:
            w.blockSignals(False)
        self._boost_hint()

    def fx(self) -> dict:
        gains, on, _t, _p = self.eq.state()
        start, end = self.trim.values()
        f = {"start": start, "end": end,
             "speed": round(self.speed.value(), 3), "pitch": round(self.pitch.value(), 2),
             "tape": self.tape.isChecked(), "gain_db": round(self.boost.value(), 2),
             "reverse": self.reverse.isChecked(),
             "eq": gains if on else [0.0] * len(gains),
             "effects": {t: r.state() for t, r in self.rows.items() if r.chk.isChecked()}}
        return {} if soundfx.is_neutral(f) else soundfx.clean(f)

    def _boost_hint(self):
        db = self.boost.value()
        self.boost_hint.setText("⚠ Very loud: this clips on purpose (ear-rape territory). "
                                "Preview it at low volume first." if db > 6 else
                                "Above 0 dB the sound gets louder until it clips.")

    def _edited(self):
        self._boost_hint()
        self._matching_preset()
        self.changed.emit()

    def _untrimmed(self) -> dict:
        f = soundfx.clean(self.fx())
        f["start"] = f["end"] = 0.0
        return f

    def _matching_preset(self):
        cur = soundfx.key(self._untrimmed())   # a preset never changes the trim
        name = next((n for n, p in soundfx.PRESETS.items() if soundfx.key(p) == cur), CUSTOM)
        self.preset.blockSignals(True)
        self.preset.setCurrentText(name)
        self.preset.blockSignals(False)

    def _on_preset(self, name: str):
        if name in soundfx.PRESETS:
            start, end = self.trim.values()
            self.load({**soundfx.PRESETS[name], "start": start, "end": end})
            self.changed.emit()


class EditDialog(QDialog):
    """Edit one sound. Nothing is written to the SoundMeta until `apply()`;
    `hotkeys_changed` fires after a capture so the owner can re-register the (paused)
    global hotkeys. After exec(), `as_copy` says whether "Save as new sound" was
    chosen (then apply() goes onto the copy, and the original stays as it was).

    preview_cb(sid, volume, fx, (fade_in, fade_out)) plays the sound, with these
    (unsaved) effects and fades, to your headphones only."""
    hotkeys_changed = Signal()

    def __init__(self, meta: SoundMeta, hotkeys: Hotkeys, preview_cb, parent=None,
                 tab: str = "sound"):
        super().__init__(parent)
        fit.watch(self)   # grows to fit its text (ui/fit.py)
        self.setWindowTitle("Edit sound")
        self.meta = meta
        self.hotkeys = hotkeys
        self.hotkey = meta.hotkey
        self.color = meta.color
        self.as_copy = False
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)

        basics = QWidget()
        form = QFormLayout(basics)
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

        self.fade_in = self._fade_row(form, "Fade in", meta.fade_in,
                                      "Starts silent and rises to full volume over this long")
        self.fade_out = self._fade_row(form, "Fade out", meta.fade_out,
                                       "Stopping it fades it out over this long instead of "
                                       "cutting it; a sound that isn't looping also fades "
                                       "over its last seconds. Stop everything still cuts "
                                       "straight away.")

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
        self.tabs.addTab(basics, "Sound")

        self.effects = EffectsPanel(meta.fx, meta)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.effects)
        scroll.setFrameShape(QScrollArea.NoFrame)
        self.tabs.addTab(scroll, "Effects")
        if tab == "effects":
            self.tabs.setCurrentIndex(1)

        prow = QHBoxLayout()
        prev = QPushButton("Preview (only you hear it)")
        icons.set_icon(prev, "headphones")
        prev.clicked.connect(lambda: preview_cb(self.meta.id, self.vol.value() / 100,
                                                self.effects.fx(), self.fades()))
        prow.addWidget(prev)
        self.fx_note = QLabel()
        self.fx_note.setObjectName("muted")
        prow.addWidget(self.fx_note, 1)
        lay.addLayout(prow)
        self.effects.changed.connect(self._fx_note)
        self._fx_note()

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        copy = bb.addButton("Save as new sound", QDialogButtonBox.AcceptRole)
        copy.setToolTip("Keep this sound as it is and add the edited version as a new pad")
        copy.clicked.connect(lambda: setattr(self, "as_copy", True))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.setMinimumWidth(500)
        self.resize(540, 640)

    @staticmethod
    def _fade_row(form: QFormLayout, label: str, value: float, tip: str) -> QSlider:
        """A 0..MAX_FADE_S slider in tenths of a second, with its value beside it."""
        row = QHBoxLayout()
        sl = QSlider(Qt.Horizontal)
        sl.setRange(0, int(MAX_FADE_S * 10))
        sl.setValue(int(round(clean_fade(value) * 10)))
        sl.setToolTip(tip)
        sl.setAccessibleName(label)
        no_wheel(sl)
        lbl = QLabel()
        lbl.setFixedWidth(42)

        def show(v):
            lbl.setText(f"{v / 10:.1f} s" if v else "off")
            sl.setAccessibleDescription(lbl.text())
        sl.valueChanged.connect(show)
        show(sl.value())
        row.addWidget(sl)
        row.addWidget(lbl)
        form.addRow(label, row)
        return sl

    def fades(self) -> tuple[float, float]:
        return self.fade_in.value() / 10, self.fade_out.value() / 10

    def _fx_note(self):
        s = soundfx.summary(self.effects.fx())
        self.fx_note.setText(f"Effects: {s}" if s else "")

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

    def apply(self, target: SoundMeta | None = None):
        m = target or self.meta
        m.name = self.name.text().strip() or m.name
        m.volume = self.vol.value() / 100
        m.mode = self.mode.currentData()
        m.loop = self.loop.isChecked()
        m.hotkey = self.hotkey
        m.color = self.color
        m.fade_in, m.fade_out = self.fades()
        m.fx = self.effects.fx()
