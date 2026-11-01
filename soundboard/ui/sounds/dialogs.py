"""Per-sound Edit dialog: the Sound tab (name, volume, hotkey…), the Trim & speed tab
(trim, speed, pitch, boost, reverse), the Effects tab (preset, voice and every voice
effect, modules' included) and the EQ tab."""
from __future__ import annotations

import json
import logging
import math
import threading
from typing import Any

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox,
                               QDialog, QDialogButtonBox, QFrame, QGridLayout,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QMessageBox, QProgressBar,
                               QPushButton, QScrollArea, QSlider, QTabWidget, QVBoxLayout,
                               QWidget)

from soundboard.core import achievements, usage
from soundboard.audio import livefx, mypresets, soundfx
from soundboard.ui.kit import theme
from soundboard import voicefx
from soundboard.sounds import thumbs
from soundboard.audio.eq import PRESETS as EQ_PRESETS
from soundboard.sounds.library import (MAX_COOLDOWN_S, MAX_DELAY_S, PAD_COLORS,
                                       SoundMeta, original_length, original_peaks)
from soundboard.ui.kit import busy, fit, icons
from soundboard.ui.kit.panel import (EqPanel, hint_label, icon_button, reset_button,
                                     section_label, steady_number)
from soundboard.ui.sounds.editadvanced import AdvancedView, ModeSwitch
from soundboard.ui.sounds.speedpitch import (FX_NAME_W, GAP, NAME_W, QUICK, QUICK_SLACK,
                                             VOLUME_QUICK, name_of, popup_slider,
                                             preset_name, quick_row)
from soundboard.ui.sounds.trim import TrimPanel
from soundboard.ui.voice.voicefxpanel import ADDON_GROUP, GROUPS, EffectRow, ParamSlider
from soundboard.ui.kit.plaintext import plain_tip
from soundboard.ui.kit.wheelguard import no_wheel
from soundboard.control.winkeys import Hotkeys
from soundboard.i18n import _, ngettext
from soundboard.ui.sounds.tabhelp import TabHelpPopup  # noqa: F401
from soundboard.ui.sounds.editdialogparts import PIC_H, PIC_W  # noqa: F401
from soundboard.ui.sounds.editdialogparts import EditDialogParts

log = logging.getLogger(__name__)
HISTORY_MS = 400      # changes this close together are one Undo step (a drag)
HISTORY_STEPS = 200   # Undo goes this far back
ADV_W, ADV_H = 1320, 880       # the Advanced window, when the screen has room
ADV_MIN_W, ADV_MIN_H = 720, 600

CUSTOM = "Custom"   # the preset box's item data when no preset matches
MINE = "mine:"      # before your own presets' names in the preset box's item data
# what the pad colour swatches are called (tooltip and screen reader)
COLOUR_NAMES = {"#7c5cff": _("Purple"), "#ff5c8a": _("Pink"), "#1fb6ff": _("Blue"),
                "#13ce66": _("Green"), "#ffb020": _("Yellow"), "#ff7849": _("Orange"),
                "#00c2b2": _("Teal"), "#e056fd": _("Magenta"), "#5c7cfa": _("Indigo"),
                "#94a3b8": _("Grey")}
SPEED = voicefx.Param("speed", _("Speed"), *soundfx.SPEED_RANGE, 1.0, "x", 0.05)
PITCH = voicefx.Param("pitch", _("Pitch"), *soundfx.PITCH_RANGE, 0.0, " st", 1)
BOOST = voicefx.Param("gain_db", _("Boost"), *soundfx.GAIN_RANGE, 0.0, " dB", 1)
VOLUME = voicefx.Param("volume", _("Volume"), 0, 200, 100, "%", 1)   # the pad's (meta.volume)


def _page() -> tuple[QWidget, QVBoxLayout]:
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 14, 8, 0)   # room under the dialog's tab bar
    v.setSpacing(8)
    return w, v


class EffectsPanel(QObject):
    """Every per-sound effect setting, on three pages for the dialog's tabs: `trim_page`
    (trim, speed & pitch, loudness), `fx_page` (preset, voice, effects) and `eq_page`
    (one long page was too much to scroll). `changed` fires on any edit; `fx()` is the settings
    dict for SoundMeta.fx ({} when nothing is changed).

    `pick_voice(voice)` opens the voice picker (ui.voicepicker) on the sound's voice
    and gives back the new one, or None if it was cancelled. The sound keeps a copy."""
    changed = Signal()
    peaks_read = Signal(int, object)   # (trim generation, peaks) from the waveform worker
    trim_replaced = Signal()           # set_sound made a new `trim` (Advanced re-hooks it)

    def __init__(self, fx: dict | None, meta: SoundMeta | None = None, pick_voice=None):
        super().__init__()
        self._pick_voice = pick_voice
        self._trim_gen = 0
        self.peaks_read.connect(self._on_peaks)
        self._voice: dict = {}
        self._live: list = []
        self.compact = False   # Advanced: only the effects that are on (set_compact)
        self._folded_here: set = set()   # the cards set_compact folded
        self.trim_page, tv = _page()
        self.fx_page, v = _page()
        self.eq_page, ev = _page()

        # Preset, Voice and Live controls: their names in one column, so the boxes
        # after them start level whatever the language
        top = QGridLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setHorizontalSpacing(8)
        top.setVerticalSpacing(8)
        top.setColumnStretch(1, 1)
        v.addLayout(top)
        prow = QHBoxLayout()
        top.addWidget(QLabel(_("Preset")), 0, 0)
        top.addLayout(prow, 0, 1)
        self.preset = QComboBox()
        self.mine: dict[str, dict] = {}   # your own presets (audio/mypresets.py)
        self._fill_presets()
        no_wheel(self.preset)
        prow.addWidget(self.preset)
        reset = reset_button(_("Back to the original sound (the trim stays)"))
        reset.clicked.connect(lambda: self.preset.setCurrentIndex(0))   # the first preset
        prow.addWidget(reset)
        # Reset's slim look beside it: what's on now, kept as a preset of your own
        self.save_preset = QPushButton(_("Save as preset"))
        self.save_preset.setObjectName("reset")
        self.save_preset.setCursor(Qt.CursorShape.PointingHandCursor)
        icons.set_icon(self.save_preset, "plus", "muted", size=12)
        self.save_preset.setToolTip(_("Keep these effects as a preset of your own, in "
                                      "this list for every sound"))
        self.save_preset.clicked.connect(self._save_preset)
        prow.addWidget(self.save_preset)
        self.delete_preset = icon_button("trash", _("Delete this preset"))
        self.delete_preset.clicked.connect(self._delete_preset)
        self.delete_preset.hide()
        prow.addWidget(self.delete_preset)
        prow.addStretch(1)
        # a deleted preset can come back until the dialog closes
        self.undo_row = QWidget()
        urow = QHBoxLayout(self.undo_row)
        urow.setContentsMargins(0, 0, 0, 0)
        self.undo_text = QLabel()
        self.undo_text.setObjectName("hint")
        undo = QPushButton(_("Undo"))
        undo.setObjectName("small")
        undo.setCursor(Qt.CursorShape.PointingHandCursor)
        undo.clicked.connect(self._undo_delete)
        urow.addWidget(self.undo_text)
        urow.addWidget(undo)
        urow.addStretch(1)
        self.undo_row.hide()
        self._deleted: tuple[str, int, dict] | None = None
        top.addWidget(self.undo_row, 1, 1)

        vrow = QHBoxLayout()
        top.addWidget(QLabel(_("Voice")), 2, 0)
        top.addLayout(vrow, 2, 1)
        self.voice = QPushButton()
        self.voice.setToolTip(_("Says this sound in a voice from the Voice tab, the way your "
                                "mic sounds with it: a voice changer voice, an AI voice or "
                                "your own voice combo"))
        self.voice.setAccessibleName(_("Voice"))
        icons.set_icon(self.voice, "voice", "muted")
        self.voice.clicked.connect(self._open_voices)
        self.voice.setEnabled(pick_voice is not None)
        vrow.addWidget(self.voice)
        self.voice_off = icon_button("close", _("Take the voice off"))
        self.voice_off.clicked.connect(lambda: self.set_voice({}))
        vrow.addWidget(self.voice_off)
        vrow.addStretch(1)

        # Live controls' effects on a pad saved from them (soundfx.with_live): shown
        # here so they can be taken off; their knobs stay in Live controls
        self.live_row = QWidget()
        lrow = QHBoxLayout(self.live_row)
        lrow.setContentsMargins(0, 0, 0, 0)
        self.live_name = QLabel(_("Live controls"))
        top.addWidget(self.live_name, 3, 0)
        top.addWidget(self.live_row, 3, 1)
        self.live_text = QLabel()
        self.live_text.setObjectName("muted")
        self.live_text.setWordWrap(True)
        lrow.addWidget(self.live_text, 1)
        live_off = icon_button("close", _("Take the Live controls effects off"))
        live_off.clicked.connect(self._live_off)
        lrow.addWidget(live_off)
        self.live_row.hide()
        self.live_name.hide()

        # Advanced: Live controls' effect knobs and presets themselves (in place of the
        # row above), kept on the sound as its Live controls stage, so they sound the
        # same as in Live controls (soundfx.with_live, livefx.LiveFx)
        self.live_box = QWidget()
        lv = QVBoxLayout(self.live_box)
        lv.setContentsMargins(0, 4, 0, 4)
        lv.setSpacing(8)
        self.knobs: dict[str, ParamSlider] = {}
        for q in livefx.PARAMS:
            k = self.knobs[q.key] = popup_slider(q, q.default)
            k.changed.connect(self._knobs_edited)
            lv.addWidget(k)
        knob_w = max(FX_NAME_W, *(name_of(k).sizeHint().width() for k in self.knobs.values()))
        for k in self.knobs.values():
            name_of(k).setFixedWidth(knob_w)
        grid = QGridLayout()
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)
        self.fx_presets: dict[str, QPushButton] = {}
        for i, pname in enumerate(livefx.PRESETS):
            b = QPushButton(preset_name(pname))
            b.setObjectName("small")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda on, n=pname: self._fx_preset_clicked(n, on))
            self.fx_presets[pname] = b
            grid.addWidget(b, i // 3, i % 3)
        grid.setColumnStretch(3, 1)   # as wide as their words, on the left
        lv.addLayout(grid)
        self._before_preset: tuple[str, dict, tuple[float, float, bool]] | None = None
        lv.addWidget(hint_label(_("A voice chat's noise suppression can wipe these out, "
                                  "deep bass too. Discord: Input Profile → Studio.")))
        self.live_box.hide()
        v.addWidget(self.live_box)

        self.trim_head = section_label(_("Trim"))
        tv.addWidget(self.trim_head)
        self._v = tv
        self.trim_layout = tv   # where the trim is: here, or Advanced's editor (it moves it)
        self.trim_hint = hint_label(_("Trimming works once the sound has loaded."))
        # it only picks the part that plays: someone hunted for the cut file
        self.trim_kept = hint_label(_("Your file stays whole: only the part between the "
                                      "handles plays."))
        tv.addWidget(self.trim_hint)
        tv.addWidget(self.trim_kept)
        self.trim = self._new_trim(meta, tv.indexOf(self.trim_hint))   # above them

        # Live controls' own sliders (ui/sounds/speedpitch.py), with their typed values,
        # words and quick buttons, so the same settings read and sound the same here.
        # The quick buttons and Volume are Advanced's (set_compact)
        tv.addWidget(section_label(_("Speed & pitch")))
        self.speed = popup_slider(SPEED, 1.0)
        self.pitch = popup_slider(PITCH, 0.0)
        self.boost = popup_slider(BOOST, 0.0)
        self.volume = popup_slider(VOLUME, VOLUME.default)   # the Sound tab's, mirrored
        name_w = max(NAME_W, *(name_of(s).sizeHint().width()
                               for s in (self.speed, self.pitch, self.boost, self.volume)))
        for s in (self.speed, self.pitch, self.boost, self.volume):
            name_of(s).setFixedWidth(name_w)
        indent = min(name_w, NAME_W + QUICK_SLACK) + GAP
        tv.addWidget(self.speed)
        self.speed_quick = QWidget()
        self.speed_quick.setLayout(quick_row(
            [(f"{x:g}x", x) for x in QUICK], indent,
            lambda x: self.speed.set_value(x) or self._edited(), narrow=True))
        tv.addWidget(self.speed_quick)
        tv.addWidget(self.pitch)
        # with keep pitch off the speed moves the pitch too: said under the slider
        self.pitch_note = QLabel()
        self.pitch_note.setObjectName("hint")
        self.pitch_note.setContentsMargins(name_w + GAP, 0, 0, 0)
        keep_line = self.pitch_note.sizePolicy()   # (kept while hidden: no jump in a drag)
        keep_line.setRetainSizeWhenHidden(True)
        self.pitch_note.setSizePolicy(keep_line)
        self.pitch_note.hide()
        tv.addWidget(self.pitch_note)
        self.keep = QCheckBox(_("Keep pitch when changing speed"))   # off = "tape"
        self.keep.setChecked(True)
        self.keep.setToolTip(_("Off: slower is also deeper and faster is higher, like a tape"))
        tv.addWidget(self.keep)

        tv.addWidget(section_label(_("Loudness")))
        tv.addWidget(self.volume)
        self.volume_quick = QWidget()
        self.volume_quick.setLayout(quick_row(
            [(f"{lv:g}%", lv) for lv in VOLUME_QUICK if lv <= VOLUME.hi], indent,
            lambda lv: self.volume.set_value(lv) or self.volume.changed.emit(), narrow=True))
        tv.addWidget(self.volume_quick)
        tv.addWidget(self.boost)
        for w in (self.speed_quick, self.volume, self.volume_quick):
            w.hide()   # Advanced's (Simple has the volume on the Sound tab)
        self.boost_hint = hint_label("")
        tv.addWidget(self.boost_hint)
        self.reverse = QCheckBox(_("Play backwards"))
        tv.addWidget(self.reverse)
        tv.addStretch(1)

        self.eq = EqPanel(False, "sounds", "Flat (off)", [0.0] * 7)
        self.eq.lbl_for.hide()
        self.eq.cb_target.hide()
        ev.addWidget(self.eq)
        ev.addStretch(1)

        self.rows: dict[str, EffectRow] = {}
        for etype, cls in voicefx.REGISTRY.items():
            if etype == "pitch":   # the Pitch slider on Trim & speed does this, better
                continue
            if etype == "backdrop":   # sounds behind your voice: the mic's, not a sound's
                continue
            row = EffectRow(cls, {})
            row.changed.connect(self._edited)
            self.rows[etype] = row
        # in Edit voice's groups, so the long list reads in parts; add-ons' last
        grouped = {t for _t, types in GROUPS for t in types}
        self.groups: list[tuple[QLabel, list[EffectRow]]] = []   # (heading, its rows)
        for title, types in (*GROUPS,
                             (ADDON_GROUP, [t for t in self.rows if t not in grouped])):
            rows = [self.rows[t] for t in types if t in self.rows]
            if rows:
                head = section_label(title)
                v.addWidget(head)
                self.groups.append((head, rows))
            for row in rows:
                v.addWidget(row)
        self.addon_hint = hint_label(_("Effects from add-on modules show up here too."))
        v.addWidget(self.addon_hint)
        # Advanced: right after the effects that are on, a button to add one more
        self.add_effect = QPushButton(_("Add effect"))
        icons.set_icon(self.add_effect, "plus", size=14)
        self.add_effect.setToolTip(_("Pick an effect to turn on"))
        self.add_effect.hide()
        arow = QHBoxLayout()
        arow.addWidget(self.add_effect)
        arow.addStretch(1)
        v.addLayout(arow)
        v.addStretch(1)

        self.load(fx or {})
        for s in (self.speed, self.pitch, self.boost):
            s.changed.connect(self._edited)
        self.keep.toggled.connect(self._edited)
        self.reverse.toggled.connect(self._edited)
        self.eq.changed.connect(lambda *__: self._edited())
        self.preset.currentIndexChanged.connect(
            lambda __: self._on_preset(self.preset.currentData()))
        self._matching_preset()

    def _new_trim(self, meta: SoundMeta | None, at: int = -1) -> TrimPanel:
        """The trim for `meta`'s sound (its waveform is that sound's). Its peaks come
        from a worker: reading them off a paged-out cache froze Edit for seconds."""
        length = original_length(meta) if meta is not None else 0.0
        trim = TrimPanel([], length)
        self._trim_gen += 1
        if meta is not None and length > 0:
            gen = self._trim_gen

            def work():
                busy.emit(self.peaks_read, gen, original_peaks(meta)[0])
            threading.Thread(target=work, daemon=True, name="edit-waveform").start()
        if at < 0:
            self.trim_layout.addWidget(trim)   # in the layout first: shown with no parent,
        else:
            self.trim_layout.insertWidget(at, trim)
        trim.setVisible(length > 0)     # it flashed up as a window of its own
        self.trim_hint.setVisible(length <= 0)
        self.trim_kept.setVisible(length > 0)
        trim.changed.connect(self._edited)
        return trim

    def _on_peaks(self, gen: int, peaks):
        if gen == self._trim_gen:   # still the same sound's trim
            self.trim.wave.set_peaks(peaks)

    def set_sound(self, meta: SoundMeta):
        """Show another sound (Edit sound reused, EditControl.edit): its trim and fx."""
        old = self.trim
        self.trim = self._new_trim(meta, self.trim_layout.indexOf(old))
        self.trim_layout.removeWidget(old)
        old.hide()
        old.deleteLater()
        # the window reused: the last sound's deleted preset is gone for good, and the
        # list has the presets saved since (in another Edit window too)
        self._deleted = None
        self.undo_row.hide()
        self._fill_presets()
        self.load(meta.fx or {})
        self._matching_preset()
        if self.compact:
            self.set_compact(True)
        self.trim_replaced.emit()

    def set_compact(self, on: bool):
        """Advanced's Effects column: only the effects that are on now (Add effect brings
        in more), no group headings. One switched off there stays until the next time
        the list is drawn, so a slip of the mouse doesn't make it vanish."""
        self.compact = on
        shown = 0
        for head, rows in self.groups:
            for row in rows:
                row.setVisible(not on or row.chk.isChecked())
                shown += row.chk.isChecked()
            head.setVisible(not on)
        # two or more on: folded to their names, so they and Add effect fit (as they
        # were, back in Simple)
        for row in self.rows.values():
            if on and shown > 1 and row.chk.isChecked() and not row._folded:
                row.set_folded(True)
                self._folded_here.add(row)
            elif not on and row in self._folded_here:
                row.set_folded(False)
        if not on:
            self._folded_here.clear()
        self.addon_hint.setVisible(not on)
        self.add_effect.setVisible(on)
        for w in (self.speed_quick, self.volume, self.volume_quick, self.live_box):
            w.setVisible(on)
        self._show_live()

    def turn_on(self, etype: str, on: bool = True):
        """Add effect's tile: switch `etype` on (open, in view) or off."""
        row = self.rows.get(etype)
        if row is None:
            return
        row.chk.setChecked(on)   # (its changed signal edits the fx)
        if on:
            row.setVisible(True)
            row.set_folded(False)
        elif self.compact:
            row.setVisible(False)

    def on_count(self) -> int:
        return sum(r.chk.isChecked() for r in self.rows.values())

    def load(self, fx: dict):
        f = soundfx.clean(fx)
        widgets = (self.speed, self.pitch, self.boost, self.keep, self.reverse, self.eq,
                   self.trim, *self.rows.values())
        for w in widgets:
            w.blockSignals(True)
        self.trim.set_values(f["start"], f["end"])
        self.speed.set_value(f["speed"])
        self.pitch.set_value(f["pitch"])
        self.boost.set_value(f["gain_db"])
        self.keep.setChecked(not f["tape"])
        self.reverse.setChecked(f["reverse"])
        self.eq.set_gains(f["eq"], next((n for n, g in EQ_PRESETS.items() if g == f["eq"]),
                                        CUSTOM))
        for etype, row in self.rows.items():
            cfg = f["effects"].get(etype)
            row.load(cfg if cfg and cfg.get("on") else {"on": False})
        for w in widgets:
            w.blockSignals(False)
        self._voice = f["voice"]
        self._show_voice()
        self._live = f["live"]
        self._show_live()
        self._boost_hint()
        self._pitch_note()

    def _show_live(self):
        self.live_text.setText("; ".join(", ".join(
            f"{voicefx.shown(q.label)} " + (f"{st[q.key]:+g}{q.unit}" if q.unit
                                             else f"{round(st[q.key] * 100)}%")
            for q in livefx.PARAMS if q.key in st)
            for st in self._live))
        self.live_row.setVisible(bool(self._live) and not self.compact)
        self.live_name.setVisible(bool(self._live) and not self.compact)
        merged = soundfx.live_merged(self._live)
        for key, k in self.knobs.items():
            k.set_value(merged.get(key, 0.0))
        self._light_presets()

    def knob_values(self) -> dict[str, float]:
        """Advanced's Live controls knobs that are off 0."""
        return livefx.clean({key: k.value() for key, k in self.knobs.items()})

    def _knobs_edited(self):
        """A knob moved: the sound's Live controls stages become one, these knobs (and
        the volume they were saved with, which has no slider here)."""
        vol = 1.0
        for st in self._live:
            vol *= st.get(livefx.VOLUME.key, livefx.VOLUME.default) / 100
        stage = livefx.clean({**self.knob_values(), livefx.VOLUME.key: vol * 100})
        self._live = [stage] if stage else []
        self._edited()

    def _fx_preset_on(self, name: str) -> bool:
        """The knobs (and the speed and pitch, if it sets them) are the preset's, as
        Live controls lights it."""
        p = livefx.PRESETS[name]
        want = livefx.clean(p)
        want.pop(livefx.VOLUME.key, None)
        if self.knob_values() != want:
            return False
        t = livefx.tuning(p)
        return t is None or (abs(self.speed.value() - t[0]) < 1e-3
                             and abs(self.pitch.value() - t[1]) < 1e-3
                             and self.keep.isChecked() == t[2])

    def _light_presets(self):
        for name, b in self.fx_presets.items():
            b.setChecked(self._fx_preset_on(name))

    def _set_tuning(self, speed: float, pitch: float, keep: bool):
        self.speed.set_value(speed)
        self.pitch.set_value(pitch)
        self.keep.blockSignals(True)
        self.keep.setChecked(keep)
        self.keep.blockSignals(False)

    def _fx_preset_clicked(self, name: str, on: bool):
        """Live controls' preset: sets its knobs, and its speed and pitch when it has
        them; clicked again (lit), back to how they were before it."""
        p = livefx.PRESETS[name]
        t = livefx.tuning(p)
        if on:
            self._before_preset = (name, self.knob_values(),
                                   (self.speed.value(), self.pitch.value(),
                                    self.keep.isChecked()))
            knobs = p
            if t is not None:
                self._set_tuning(*t)
        else:
            was = self._before_preset
            knobs, (speed, pitch, keep) = ((was[1], was[2]) if was and was[0] == name
                                           else ({}, (1.0, 0.0, self.keep.isChecked())))
            if t is not None:
                self._set_tuning(speed, pitch, bool(keep))
        for key, k in self.knobs.items():
            k.set_value(knobs.get(key, 0.0))
        self._knobs_edited()

    def _live_off(self):
        self._live = []
        self._show_live()
        self._edited()

    def _show_voice(self):
        from soundboard.ui.sounds.voicepicker import describe
        self.voice.setText(describe(self._voice) if self._voice else _("Pick a voice"))
        self.voice_off.setVisible(bool(self._voice))

    def set_voice(self, voice: dict):
        """Put a voice on the sound ({} takes it off)."""
        self._voice = soundfx.clean_voice(voice)
        self._show_voice()
        self._edited()

    def _open_voices(self):
        if self._pick_voice is None:
            return
        got = self._pick_voice(self._voice)
        if got is not None:
            self.set_voice(got)

    def fx(self) -> dict:
        gains, on, _t, _p = self.eq.state()
        start, end = self.trim.values()
        f = {"start": start, "end": end,
             "speed": round(self.speed.value(), 3), "pitch": round(self.pitch.value(), 2),
             "tape": not self.keep.isChecked(), "gain_db": round(self.boost.value(), 2),
             "reverse": self.reverse.isChecked(),
             "eq": gains if on else [0.0] * len(gains),
             "effects": {t: r.state() for t, r in self.rows.items() if r.chk.isChecked()},
             "voice": self._voice, "live": self._live}
        return {} if soundfx.is_neutral(f) else soundfx.clean(f)

    def _boost_hint(self):
        db = self.boost.value()
        self.boost_hint.setText(_("⚠ Very loud: this clips on purpose (deep-fried territory). "
                                  "Preview it at low volume first.") if db > 6 else
                                _("Above 0 dB the sound gets louder until it clips."))

    def _edited(self):
        self._boost_hint()
        self._pitch_note()
        self._light_presets()
        self._matching_preset()
        self.changed.emit()

    def _pitch_note(self):
        """How far the speed moves the pitch while keep pitch is off, and the total with
        the slider's shift (Live controls' note)."""
        st = 0.0 if self.keep.isChecked() else round(12 * math.log2(self.speed.value()), 1)
        shift = self.pitch.value()
        if abs(st) < 0.05:
            self.pitch_note.hide()
            return
        if abs(shift) < 1e-3:
            text = _("{st} st from the speed", st=f"{st:+g}")
        else:
            text = _("{st} st from the speed, {total} st in all", st=f"{st:+g}",
                     total=f"{round(st + shift, 1):+g}")
        self.pitch_note.setText(text)
        self.pitch_note.show()

    def _untrimmed(self) -> dict:
        f = soundfx.clean(self.fx())
        f["start"] = f["end"] = 0.0
        f["voice"] = {}   # the voice is a layer of its own: presets don't set it
        return f          # (Live controls' knobs are effects: Advanced's Effects column)

    def _matching_preset(self):
        cur = soundfx.key(self._untrimmed())   # a preset never changes the trim
        name = next((n for n, p in soundfx.PRESETS.items() if soundfx.key(p) == cur),
                    next((MINE + n for n, p in self.mine.items() if soundfx.key(p) == cur),
                         CUSTOM))
        self.preset.blockSignals(True)
        self.preset.setCurrentIndex(max(0, self.preset.findData(name)))
        self.preset.blockSignals(False)
        self.delete_preset.setVisible(name.startswith(MINE))

    def _fill_presets(self):
        """The built-in presets, then yours, then Custom."""
        self.mine = mypresets.load("sound")
        self.preset.blockSignals(True)
        self.preset.clear()
        for name in soundfx.PRESETS:
            self.preset.addItem(name, name)
        if self.mine:
            self.preset.insertSeparator(self.preset.count())
            for name in self.mine:
                self.preset.addItem(name, MINE + name)
        self.preset.addItem(_("Custom"), CUSTOM)
        self.preset.blockSignals(False)

    def _ask_preset_name(self, text: str) -> str:
        """A name for one of your presets, or "" if cancelled. A built-in preset's name
        is taken; so is another of yours, unless you agree to replace it."""
        title, parent = _("Save as preset"), self.fx_page.window()
        builtin = {n.casefold() for n in soundfx.PRESETS}
        while True:
            name, ok = QInputDialog.getText(parent, title, _("Name:"),
                                            QLineEdit.EchoMode.Normal, text)
            name = mypresets.clean_name(name) if ok else ""
            if not name:
                return ""
            if name.casefold() in builtin:
                QMessageBox.information(parent, title, plain_tip(_(
                    "“{name}” is a built-in preset's name. Pick another one.", name=name)))
                text = name
                continue
            other = mypresets.find("sound", name)
            if other is None:
                return name
            if QMessageBox.question(parent, title, plain_tip(_(
                    "You already have a preset called “{name}”. Replace it?", name=other))
                    ) == QMessageBox.StandardButton.Yes:
                return other
            text = name

    def _save_preset(self):
        """"Save as preset": these effects (not the trim or the voice) under a name, in
        the Preset list of every sound from now on."""
        parent = self.fx_page.window()
        if mypresets.full("sound"):
            QMessageBox.information(parent, _("Save as preset"), ngettext(
                "You have {n} preset, the most there can be. Delete one first.",
                "You have {n} presets, the most there can be. Delete one first.",
                mypresets.MAX_PRESETS))
            return
        n, base = 1, _("My preset")
        while mypresets.find("sound", f"{base} {n}"):
            n += 1
        name = self._ask_preset_name(f"{base} {n}")
        if name and mypresets.put("sound", name, self._untrimmed()):
            self._fill_presets()
            self._matching_preset()
            busy.flash(self.save_preset, _("✓ Saved"))

    def _delete_preset(self):
        """Take the picked preset of yours out; Undo puts it back until the dialog
        closes."""
        name = str(self.preset.currentData() or "")
        if not name.startswith(MINE):
            return
        name = name[len(MINE):]
        got = mypresets.remove("sound", name)
        if got is None:
            return
        self._deleted = (name, *got)
        self.undo_text.setText(_("Deleted “{name}”", name=name))
        self.undo_row.show()
        self._fill_presets()
        self._matching_preset()

    def _undo_delete(self):
        if self._deleted is not None:
            name, at, p = self._deleted
            mypresets.put("sound", name, p, at)
        self._deleted = None
        self.undo_row.hide()
        self._fill_presets()
        self._matching_preset()

    def reset_all(self):
        """Every effect off, the voice too (the trim stays)."""
        start, end = self.trim.values()
        self.load({"start": start, "end": end})
        self._matching_preset()
        self.changed.emit()

    def _on_preset(self, name: str):
        p = soundfx.PRESETS.get(name) or (self.mine.get(name[len(MINE):])
                                          if name.startswith(MINE) else None)
        if p:
            start, end = self.trim.values()
            self.load({**p, "start": start, "end": end, "voice": self._voice})
            self.changed.emit()
        self.delete_preset.setVisible(name.startswith(MINE))


class EditDialog(EditDialogParts, QDialog):
    """Edit one sound. Nothing is written to the SoundMeta until `apply()`;
    `hotkeys_changed` fires after a capture so the owner can re-register the (paused)
    global hotkeys. After exec(), `as_copy` says whether "Save a copy" was
    chosen (then apply() goes onto the copy, and the original stays as it was).

    preview_cb(sid, volume, fx, (fade_in, fade_out), done) plays the sound, with these
    (unsaved) effects and fades, to your headphones only."""
    hotkeys_changed = Signal()
    picture_fetched = Signal(int, object, str)   # (which try, QImage or None, why not)
    source_forgotten = Signal()   # Details → Delete info: saved at once, Save or Cancel
    effects_reset = Signal()      # Reset effects: a playing sound goes plain at once
    advanced_changed = Signal(bool)   # the Simple | Advanced switch was clicked

    def __init__(self, meta: SoundMeta, hotkeys: Hotkeys, preview_cb, parent=None,
                 tab: str = "sound", others=None, pick_voice=None, save_hook=None,
                 stop_render=None, advanced: bool = False):
        """save_hook(dialog) -> True when Save was handled and the window stays open (a
        slow render, shown here: show_render); stop_render(sid): its ✕. `advanced`:
        open in the Advanced view (ui/sounds/editadvanced.py)."""
        super().__init__(parent)
        self.save_hook, self.stop_cb = save_hook, stop_render
        fit.watch(self)   # grows to fit its text (ui/kit/fit.py)
        self.setWindowTitle(_("Edit sound"))
        self.meta = meta
        self.others = others   # () -> every sound on the board, for the same-name warning
        self.hotkeys = hotkeys
        self.hotkey = meta.hotkey
        self.color = meta.color
        self.as_copy = False
        lay = self._lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        self.switch = ModeSwitch(False, slim=True)   # Simple | Advanced, by the tabs
        self.switch.picked.connect(self._switch_picked)
        self.tabs.setCornerWidget(self.switch, Qt.Corner.TopRightCorner)
        self.adv: AdvancedView | None = None   # made the first time Advanced is picked
        self._simple_size: QSize | None = None
        self._simple_page = 0   # the tab Simple showed when Advanced was picked

        # three cards: how the pad looks, how it plays, its timings. Labels share one
        # column width across the cards so the fields line up down the page.
        basics = QWidget()
        page = QVBoxLayout(basics)
        page.setContentsMargins(2, 14, 2, 2)   # room under the tabs
        page.setSpacing(10)
        labels = [_("Name"), _("Colour"), _("Picture"), _("Volume"), _("Hotkey"),
                  _("On press")]
        label_w = max(self.fontMetrics().horizontalAdvance(t) for t in labels) + 12

        def card(title: str):
            c = QFrame()
            c.setObjectName("setcard")   # (its buttons and boxes keep their fill)
            g = QGridLayout(c)
            g.setContentsMargins(14, 10, 14, 12)
            g.setHorizontalSpacing(12)
            g.setVerticalSpacing(10)
            g.setColumnMinimumWidth(0, label_w)
            g.setColumnStretch(1, 1)
            g.addWidget(section_label(title), 0, 0, 1, 2)
            page.addWidget(c)
            return g

        def row(g, text, field):
            r = g.rowCount()
            lbl = QLabel(text)
            lbl.setObjectName("muted")
            g.addWidget(lbl, r, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            if isinstance(field, QWidget):
                g.addWidget(field, r, 1)
                lbl.setBuddy(field)
            else:
                g.addLayout(field, r, 1)

        g = card(_("Look"))
        self.name = QLineEdit(meta.name)
        f = self.name.font()
        f.setPointSizeF(f.pointSizeF() + 1.5)
        f.setWeight(QFont.Weight.DemiBold)
        self.name.setFont(f)
        row(g, _("Name"), self.name)
        # same name as another pad: allowed, but two "Airhorn"s are hard to tell apart
        self.name_hint = hint_label(_("⚠ Another sound already has this name."))
        self.name_hint.hide()
        g.addWidget(self.name_hint, g.rowCount(), 1)
        self.name.textChanged.connect(self._check_name)

        crow = QHBoxLayout()
        crow.setSpacing(8)
        self.swatches = []
        self.swatch_group = QButtonGroup(self)   # exclusive: one colour is checked
        for c in PAD_COLORS:
            b = QPushButton()
            b.setFixedSize(22, 22)
            b.setCheckable(True)
            name = COLOUR_NAMES.get(c, c)
            b.setToolTip(name)
            b.setAccessibleName(_("{name} colour", name=name))
            b.clicked.connect(lambda __=False, c=c: self._set_color(c))
            self.swatch_group.addButton(b)
            self.swatches.append((b, c))
            crow.addWidget(b)
        # any other colour: a colour wheel; the button wears the custom colour once picked
        self.custom_swatch = QPushButton()
        self.custom_swatch.setFixedSize(22, 22)
        self.custom_swatch.setCheckable(True)
        self.custom_swatch.setToolTip(_("Custom colour…"))
        self.custom_swatch.setAccessibleName(_("Custom colour"))
        self.custom_swatch.clicked.connect(self._pick_custom)
        self.swatch_group.addButton(self.custom_swatch)
        crow.addWidget(self.custom_swatch)
        crow.addStretch()
        row(g, _("Colour"), crow)

        # the pad's picture: changed here, kept only on Save (self.picture)
        self.picture: QImage | str | None = None   # None: as it is, "": removed
        self._pic_gen = 0
        prow = QHBoxLayout()
        prow.setSpacing(8)
        self.pic_view = QLabel()
        self.pic_view.setFixedSize(PIC_W, PIC_H)
        self.pic_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pic_view.setStyleSheet(f"background: {theme.T['inset']}; border-radius: 6px;")
        prow.addWidget(self.pic_view)

        def pic_button(icon, tip, slot):
            b = QPushButton()
            b.setObjectName("iconbutton")
            icons.set_icon(b, icon)
            b.setToolTip(tip)
            b.setAccessibleName(tip)
            b.clicked.connect(slot)
            prow.addWidget(b)
            return b
        self.btn_pic_file = pic_button(
            "folder", _("From a file (you can also drop a picture on the pad)"),
            lambda: (usage.used("pad-picture-file"), self._picture_from_file()))
        self.btn_pic_link = pic_button(
            "browser", _("From a link: a picture's address, a YouTube video or a web page"),
            lambda: (usage.used("pad-picture-link"), self._picture_from_link()))
        self.btn_pic_clear = pic_button("trash", _("Remove picture"),
                                        lambda: self._set_picture(""))
        self.pic_note = QLabel()
        self.pic_note.setObjectName("muted")
        prow.addWidget(self.pic_note)
        prow.addStretch(1)
        row(g, _("Picture"), prow)
        self.picture_fetched.connect(self._on_picture_fetched)
        self._show_picture()

        # where a downloaded sound came from (soundboard.sounds.sourceinfo)
        self._look, self._source_at = g, g.rowCount()
        self.btn_source = self.source_row = None
        self._fill_source()

        # how it plays: the hotkey is what most people open this for
        g = card(_("Playback"))
        vrow = QHBoxLayout()
        vrow.setSpacing(10)
        self.vol = QSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 200)
        self.vol.setValue(round(meta.volume * 100))   # int() made 0.29 read as 28 %
        self.vol.setAccessibleName(_("Volume"))
        no_wheel(self.vol)
        self.vol_lbl = QLabel()
        self.vol_lbl.setObjectName("muted")
        self.vol.valueChanged.connect(lambda v: self.vol_lbl.setText(f"{v}%"))
        self.vol_lbl.setText(f"{self.vol.value()}%")
        steady_number(self.vol_lbl, "200%")
        vrow.addWidget(self.vol, 1)
        vrow.addWidget(self.vol_lbl)
        row(g, _("Volume"), vrow)

        hrow = QHBoxLayout()
        hrow.setSpacing(8)
        self.hk_btn = QPushButton()
        self.hk_btn.clicked.connect(self._capture)
        self.hk_btn.setAccessibleName(_("Hotkey"))
        icons.set_icon(self.hk_btn, "keyboard")
        clr = QPushButton(_("Clear"))
        clr.clicked.connect(lambda: self._set_hk(""))
        self.hk_btn.setMinimumWidth(140)   # room for "Ctrl+Shift+F12", not the whole row
        hrow.addWidget(self.hk_btn)
        hrow.addWidget(clr)
        hrow.addStretch(1)
        row(g, _("Hotkey"), hrow)
        self._set_hk(self.hotkey)

        self.mode = QComboBox()
        # the default stops the other sounds (an old "solo" sound shows as it too)
        self.mode.addItem(_("Solo: stops every other sound first"), "restart")
        self.mode.addItem(_("Overlap: every press plays a new copy"), "overlap")
        self.mode.addItem(_("Toggle: press again stops it"), "toggle")
        self.mode.addItem(_("Queue: waits for the sounds playing to finish"), "queue")
        self.mode.setCurrentIndex(max(0, self.mode.findData(meta.mode)))
        no_wheel(self.mode)
        row(g, _("On press"), self.mode)

        self.loop = QCheckBox(_("Loop until stopped"))
        self.loop.setChecked(meta.loop)
        g.addWidget(self.loop, g.rowCount(), 1)

        self.hold = QCheckBox(_("Hold to play: stops when you let go of its hotkey"))
        self.hold.setToolTip(_("Plays only while its hotkey or MIDI pad is held down, like an "
                               "air horn. Clicking the pad still plays it through."))
        self.hold.setChecked(meta.hold)
        g.addWidget(self.hold, g.rowCount(), 1)

        self.only_them = QCheckBox(_("Only others hear it, not played in my headphones"))
        self.only_them.setToolTip(_("It still goes out to others (Discord, the game, OBS…); you "
                                    "just don't hear it yourself (Preview still plays it to you)"))
        self.only_them.setChecked(meta.only_them)
        g.addWidget(self.only_them, g.rowCount(), 1)

        # timings two by two, each its name and value over its slider
        c = QFrame()
        c.setObjectName("setcard")
        tv = QVBoxLayout(c)
        tv.setContentsMargins(14, 10, 14, 14)
        tv.setSpacing(10)
        tv.addWidget(section_label(_("Timing")))
        tg = QGridLayout()
        tg.setHorizontalSpacing(24)
        tg.setVerticalSpacing(12)
        tv.addLayout(tg)
        page.addWidget(c)
        self.fade_in = self._fade_cell(tg, 0, 0, _("Fade in"), meta.fade_in,
                                       _("Starts silent and rises to full volume over this long"))
        self.fade_out = self._fade_cell(tg, 0, 1, _("Fade out"), meta.fade_out,
                                        _("Stopping it fades it out over this long instead of "
                                          "cutting it; a sound that isn't looping also fades "
                                          "over its last seconds. Stop everything still cuts "
                                          "straight away."))
        self.delay = self._fade_cell(tg, 1, 0, _("Wait first"), meta.delay,
                                     _("Waits this long after the press before it plays, say "
                                       "for a punchline. Stop everything cancels it."),
                                     MAX_DELAY_S)
        self.cooldown = self._fade_cell(tg, 1, 1, _("Cooldown"), meta.cooldown,
                                        _("After it starts, presses are ignored for this long, "
                                          "so nobody can spam it"), MAX_COOLDOWN_S)
        page.addStretch(1)
        self._set_color(self.color)
        self.tabs.addTab(basics, _("Sound"))

        self.effects = EffectsPanel(
            meta.fx, meta, (lambda v: pick_voice(v, self)) if pick_voice else None)
        self.effects.setParent(self)
        self._fx_scrolls = []
        for pg, title in ((self.effects.trim_page, _("Trim & speed").replace("&", "&&")),
                          (self.effects.fx_page, _("Effects")),
                          (self.effects.eq_page, _("Equalizer"))):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(pg)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            self._fx_scrolls.append(scroll)
            self.tabs.addTab(scroll, title)
        self.tabs.currentChanged.connect(
            lambda i: i >= 1 and usage.used("pad-effects"))   # the name only (usage.py)
        self.tabs.setCurrentIndex(self._tab_index(tab))
        self.effects.trim_replaced.connect(lambda: self.adv and self.adv.retrim())

        # Undo / Redo (the system's keys: Ctrl+Z, Ctrl+Shift+Z or Ctrl+Y) for the trim,
        # the effects and the fades; a drag is one step. A text box keeps its own.
        self._history: list[tuple[str, int, int]] = []
        self._hpos = 0
        self._restoring = False
        self._htimer = QTimer(self)
        self._htimer.setSingleShot(True)
        self._htimer.setInterval(HISTORY_MS)
        self._htimer.timeout.connect(self._record)

        # what the effects add up to, on its own line (hidden when there are none)
        self.fx_note = QLabel()
        self.fx_note.setObjectName("muted")
        self.fx_note.setWordWrap(True)
        # its line kept while it's empty: an effect switched on showed it, the pages
        # above lost its height and their scroll bars flashed on and off
        keep_line = self.fx_note.sizePolicy()
        keep_line.setRetainSizeWhenHidden(True)
        self.fx_note.setSizePolicy(keep_line)
        lay.addWidget(self.fx_note)
        # while the playing sound is made again with the changed effects (show_live)
        self.live_bar = QProgressBar()
        self.live_bar.setObjectName("downloadprogress")   # the theme's thin bar
        self.live_bar.setRange(0, 1000)
        self.live_bar.setTextVisible(False)
        self.live_bar.setFixedHeight(4)
        self.live_bar.setAccessibleName(_("Applying to the playing sound"))
        self.live_bar.hide()
        lay.addWidget(self.live_bar)
        self.effects.changed.connect(self._fx_note)
        self._fx_note()

        # one row at the bottom: a headphones icon to preview on the left, the
        # dialog's own buttons on the right
        prev = self.btn_preview = QPushButton()
        prev.setObjectName("iconbutton")
        prev.setProperty("quiet", True)
        icons.set_icon(prev, "headphones")
        prev.setToolTip(_("Preview (only you hear it)"))
        prev.setAccessibleName(_("Preview (only you hear it)"))

        def play_preview():
            busy.set_busy(prev, True)
            self._say(_("Rendering the effects…"), 0)

            def done(ok, ms=1500):
                busy.set_busy(prev, False)
                if ok:
                    self._say(_("▶  Playing"), ms)
                else:   # the window's corner card says why: the summary comes back
                    self._saying = False
                    self._fx_note()
            got = preview_cb(self.meta.id, self.vol.value() / 100, self.effects.fx(),
                             self.fades(), done)
            if got != "rendering":
                busy.set_busy(prev, False)
                self._say(_("Not loaded yet: try again in a moment") if got == "missing"
                          else _("▶  Playing"), 1500)
        prev.clicked.connect(play_preview)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                              | QDialogButtonBox.StandardButton.Cancel)
        # the one filled button
        bb.button(QDialogButtonBox.StandardButton.Save).setObjectName("primary")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setProperty("quiet", True)
        copy = bb.addButton(_("Save a copy"), QDialogButtonBox.ButtonRole.AcceptRole)
        copy.setToolTip(_("Keep this sound as it is and add the edited version as a new pad"))
        # (the box's clicked comes before its accepted; the button's own clicked came
        # after, so Save a copy saved onto the original)
        bb.clicked.connect(lambda b: setattr(self, "as_copy", b is copy))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        # beside Save: every effect off, so a playing sound goes plain again at once
        # (and a slow voice still being applied to it stops)
        self.btn_reset = QPushButton(_("Reset effects"))
        self.btn_reset.setObjectName("resetfx")
        icons.set_icon(self.btn_reset, "reload", size=14)
        self.btn_reset.setToolTip(_("Turn every effect off (the trim stays). "
                                    "A playing sound goes back to plain at once."))

        def reset_all():
            usage.used("pad-effects-reset")
            self.effects.reset_all()
            self.effects_reset.emit()
        self.btn_reset.clicked.connect(reset_all)
        from soundboard.ui.kit.glow import Halo
        self._reset_glow = Halo(self.btn_reset)   # lit while there's anything to reset
        self.effects.changed.connect(self._light_reset)
        self._light_reset()
        brow = QHBoxLayout()
        brow.addWidget(prev)
        brow.addStretch(1)
        brow.addWidget(self._reset_glow)
        brow.addWidget(bb)
        self._bb = bb
        self._brow = brow
        self.player: Any = None   # the board's player, an EditPlayer (set_player)
        lay.addLayout(brow)

        # after Save, while a slow render runs: how far it is, ✕ to stop it, and Close
        # (it keeps going: the pad shows it). The edits wait, greyed, until it's done.
        rend = self.render_box = QWidget()
        rl = QVBoxLayout(rend)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
        self.render_words = QLabel()
        rl.addWidget(self.render_words)
        bar_row = QHBoxLayout()
        bar_row.setSpacing(8)
        self.render_bar = QProgressBar()
        self.render_bar.setObjectName("downloadprogress")   # the theme's thin bar
        self.render_bar.setRange(0, 1000)
        self.render_bar.setTextVisible(False)
        self.render_bar.setFixedHeight(6)
        self.render_bar.setAccessibleName(_("Applying the effects"))
        bar_row.addWidget(self.render_bar, 1)
        self.render_stop = icon_button("close", _("Stop, keep the old effects"))
        self.render_stop.clicked.connect(lambda: self.stop_cb and self.stop_cb(self.meta.id))
        bar_row.addWidget(self.render_stop)
        rl.addLayout(bar_row)
        rhint = QLabel(_("You can close this window: it keeps going, and the pad shows "
                         "how far it is."))
        rhint.setObjectName("muted")
        rhint.setWordWrap(True)
        rl.addWidget(rhint)
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        self.render_close = QPushButton(_("Close"))
        self.render_close.clicked.connect(self.reject)   # saved already: nothing to undo
        close_row.addWidget(self.render_close)
        rl.addLayout(close_row)
        rend.hide()
        lay.addWidget(rend)
        self.setMinimumWidth(self._simple_min_w())
        self.resize(max(540, self.minimumWidth()), 640)
        self.effects.changed.connect(self._note_change)
        self.fade_in.valueChanged.connect(self._note_change)
        self.fade_out.valueChanged.connect(self._note_change)
        QShortcut(QKeySequence.StandardKey.Undo, self, self.undo)
        QShortcut(QKeySequence.StandardKey.Redo, self, self.redo)
        self._remember()
        if advanced:
            self.set_advanced(True)


    def load(self, meta: SoundMeta, tab: str = "sound"):
        """Show another sound, as a new window would: EditControl.edit reuses a closed
        one (building one took ~200 ms each time)."""
        for child in self.findChildren(QDialog):   # its Details / hotkey boxes
            child.close()
        self.meta = meta
        self.hotkey = meta.hotkey
        self.as_copy = False
        self.setResult(0)
        self.name.setText(meta.name)
        self.name.setCursorPosition(0)
        self._check_name()   # same text as the last sound: textChanged doesn't fire
        self.picture = None
        self._set_picture(None)
        self.pic_view.setStyleSheet(f"background: {theme.T['inset']}; border-radius: 6px;")
        self._fill_source()
        self.vol.setValue(round(meta.volume * 100))
        self._set_hk(self.hotkey)
        self.mode.setCurrentIndex(max(0, self.mode.findData(meta.mode)))
        self.loop.setChecked(meta.loop)
        self.hold.setChecked(meta.hold)
        self.only_them.setChecked(meta.only_them)
        for sl, value in ((self.fade_in, meta.fade_in), (self.fade_out, meta.fade_out),
                          (self.delay, meta.delay), (self.cooldown, meta.cooldown)):
            sl.setValue(int(round(min(max(value, 0.0), sl.maximum() / 10) * 10)))
        self._set_color(meta.color)
        self.effects.set_sound(meta)
        self.show_render(None)   # (EditControl.edit shows this sound's, if it has one)
        self.live_bar.hide()
        self._light_reset()   # (set_sound loads without the changed signal)
        for scroll in self._fx_scrolls:
            scroll.verticalScrollBar().setValue(0)
        busy.set_busy(self.btn_preview, False)
        self._saying = False
        self._said = getattr(self, "_said", 0) + 1   # a "Playing" still timing out
        self._fx_note()
        self.show_tab(tab)
        self._remember()

    TABS = ("sound", "trim", "effects", "eq")

    @classmethod
    def _tab_index(cls, tab: str) -> int:
        return cls.TABS.index(tab) if tab in cls.TABS else 0

    def show_tab(self, tab: str):
        """Bring `tab` ("sound", "trim", "effects", "eq") into view, in either view."""
        i = self._tab_index(tab)
        if self.adv is not None and self.advanced():
            if i:
                self.adv.show_page(i - 1)
        else:
            self.tabs.setCurrentIndex(i)

    # ------------------------------------------------------------------ Advanced
    def advanced(self) -> bool:
        return self.adv is not None and not self.adv.isHidden()

    def _switch_picked(self, on: bool):
        if on != self.advanced():
            self.set_advanced(on)
            self.advanced_changed.emit(on)

    def set_advanced(self, on: bool):
        """The Advanced view (a bigger window, everything at once) or the Simple one
        (the tabs). The same widgets move between them, so nothing is lost."""
        if on == self.advanced():
            return
        screen = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        if on:
            if self.adv is None:
                self.adv = AdvancedView(self)
                self.adv.switch.picked.connect(self._switch_picked)
                self._lay.insertWidget(self._lay.indexOf(self.tabs) + 1, self.adv, 1)
            self._simple_size = self.size()
            page = self._simple_page = self.tabs.currentIndex()
            for scroll in self._fx_scrolls:
                self.tabs.removeTab(self.tabs.indexOf(scroll))
            w = min(ADV_W, screen.width() - 48)
            h = min(ADV_H, screen.height() - 48)
            self.tabs.hide()
            self.adv.attach(self._fx_scrolls, w)
            self.adv.show()
            self.setMinimumSize(ADV_MIN_W, ADV_MIN_H)
            self.resize(w, h)
            if page:
                self.adv.show_page(page - 1)
        else:
            assert self.adv is not None
            # back on the page in view (narrow), else the one you left
            page = (self.adv.tabs.currentIndex() + 1 if not self.adv.wide
                    else getattr(self, "_simple_page", 0))
            self.adv.detach()
            self.adv.hide()
            for scroll, title in zip(self._fx_scrolls, self.page_titles()):
                self.tabs.addTab(scroll, title)   # (the tabs show one at a time)
            self.tabs.setCurrentIndex(page)
            self.tabs.show()
            self.setMinimumSize(self._simple_min_w(), 0)
            self.resize(self._simple_size or QSize(max(540, self.minimumWidth()), 640))
        self.switch.set_advanced(on)
        if self.adv is not None:
            self.adv.switch.set_advanced(on)
        if self.isVisible():   # all of it on the screen
            g = self.frameGeometry()
            x = min(max(g.x(), screen.left()), screen.right() - g.width())
            y = min(max(g.y(), screen.top()), screen.bottom() - g.height())
            self.move(max(x, screen.left()), max(y, screen.top()))

    def set_player(self, player: QWidget):
        """The board's player (ui/sounds/editplayer.py), over the Save row: a big
        window covers the board's own, and the song had to be paused from somewhere."""
        self._lay.insertWidget(self._lay.indexOf(self._brow), player)
        self.player = player

    def _simple_min_w(self) -> int:
        """Simple's least width: its four tabs and the switch beside them, whole (long
        languages too: the tabs got scroll arrows), and never under 500."""
        m = self._lay.contentsMargins()
        need = (self.tabs.tabBar().sizeHint().width() + self.switch.sizeHint().width()
                + 16 + m.left() + m.right())
        return max(500, need)

    @staticmethod
    def page_titles() -> tuple[str, str, str]:
        """The tabs after Sound, as the Simple view names them."""
        return (_("Trim & speed").replace("&", "&&"), _("Effects"), _("Equalizer"))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        try:   # (nothing in a Qt override may raise: AGENT-RULES *Async results*)
            if self.adv is not None and self.advanced():
                self.adv.set_wide(self.adv.fits(self.width()))
        except Exception:  # noqa: BLE001
            log.debug("Advanced re-layout failed", exc_info=True)

    # ------------------------------------------------------------------ undo / redo
    def _snap(self) -> tuple[str, int, int]:
        return (json.dumps(self.effects.fx(), sort_keys=True),
                self.fade_in.value(), self.fade_out.value())

    def _remember(self):
        """Start the history afresh (a sound opened): how it is now is the first step."""
        self._htimer.stop()
        self._history, self._hpos = [self._snap()], 0

    def _note_change(self, *_a):
        if not self._restoring:
            self._htimer.start()   # a drag's many changes: one step when it settles

    def _record(self):
        snap = self._snap()
        if snap == self._history[self._hpos]:
            return
        del self._history[self._hpos + 1:]
        self._history.append(snap)
        del self._history[:-HISTORY_STEPS]
        self._hpos = len(self._history) - 1

    def _flush(self):
        if self._htimer.isActive():
            self._htimer.stop()
            self._record()

    def undo(self):
        self._flush()
        if self._hpos > 0:
            self._hpos -= 1
            self._restore(self._history[self._hpos])

    def redo(self):
        self._flush()
        if self._hpos < len(self._history) - 1:
            self._hpos += 1
            self._restore(self._history[self._hpos])

    def _restore(self, snap: tuple[str, int, int]):
        fx, fade_in, fade_out = snap
        self._restoring = True
        try:
            self.effects.load(json.loads(fx))
            self.effects._matching_preset()
            if self.effects.compact:
                self.effects.set_compact(True)
            self.fade_in.setValue(fade_in)
            self.fade_out.setValue(fade_out)
            self.effects.changed.emit()   # the summary, Reset's glow, a playing sound
        finally:
            self._restoring = False


    def fades(self) -> tuple[float, float]:
        return self.fade_in.value() / 10, self.fade_out.value() / 10

    def accept(self):
        """Save. A slow effects render keeps the window open to show it (save_hook)."""
        if not self.as_copy and self.save_hook is not None and self.save_hook(self):
            return
        super().accept()


    def apply(self, target: SoundMeta | None = None):
        m = target or self.meta
        if not self.as_copy:   # (Name Tag, Painter)
            if self.name.text().strip() not in ("", m.name):
                achievements.bump("renamed")
            if self.color != m.color:
                achievements.bump("recoloured")
        m.name = self.name.text().strip() or m.name
        m.volume = self.vol.value() / 100
        m.mode = self.mode.currentData()
        m.loop = self.loop.isChecked()
        m.hold = self.hold.isChecked()
        m.only_them = self.only_them.isChecked()
        m.delay = self.delay.value() / 10
        m.cooldown = self.cooldown.value() / 10
        m.hotkey = self.hotkey
        m.color = self.color
        m.fade_in, m.fade_out = self.fades()
        m.fx = self.effects.fx()
        if self.picture == "":
            thumbs.clear(m)
        elif self.picture is not None:
            thumbs.set_image(m, self.picture)
