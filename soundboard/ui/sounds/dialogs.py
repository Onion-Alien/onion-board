"""Per-sound Edit dialog: the Sound tab (name, volume, hotkey…), the Trim & speed tab
(trim, speed, pitch, boost, reverse), the Effects tab (preset, voice and every voice
effect, modules' included) and the EQ tab."""
from __future__ import annotations

import json
import logging
import threading
from typing import Any

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt, QTimer, Signal
from shiboken6 import isValid as qt_valid
from PySide6.QtGui import QFont, QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox,
                               QDialog, QDialogButtonBox, QFrame, QGridLayout,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QMessageBox, QProgressBar,
                               QPushButton, QScrollArea, QSlider, QVBoxLayout,
                               QWidget)

from soundboard.core import achievements, usage
from soundboard.audio import livefx, mypresets, soundfx
from soundboard.ui.kit import theme
from soundboard import voicefx
from soundboard.sounds import thumbs
from soundboard.audio.eq import PRESETS as EQ_PRESETS
from soundboard.sounds.library import (MAX_COOLDOWN_S, MAX_DELAY_S, PAD_COLORS,
                                       SoundMeta, original_length, original_peaks)
from soundboard.ui.bun import bunacts
from soundboard.ui.kit import busy, fit, icons
from soundboard.ui.kit.panel import (EqPanel, hint_label, icon_button, reset_button,
                                     section_label)
from soundboard.ui.kit.layouts import take_out
from soundboard.ui.sounds.editadvanced import AdvancedView, ModeSwitch
from soundboard.ui.sounds.editsummary import Summary
from soundboard.ui.sounds.soundpanel import SoundPanel, name_of, popup_slider, preset_name
from soundboard.ui.sounds.trim import TrimPanel
from soundboard.ui.voice.voicefxpanel import ADDON_GROUP, GROUPS, EffectRow
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
BUN_GAP = 12   # px above and below Bun in Advanced's editor card (_fit_bun)
BUN_ROOM = 10  # px more across: his corner's a little wider, him in its middle
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
VOLUME_QUICK = (50, 100, 150, 200)


def _page() -> tuple[QWidget, QVBoxLayout]:
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 14, 8, 0)   # room under the dialog's tab bar
    v.setSpacing(8)
    return w, v


class EffectsPanel(QObject):
    """Every per-sound effect setting. Advanced shows three pages: `trim_page` (speed &
    pitch, loudness), `fx_page` (preset, voice, the knobs, the effect cards) and `eq_page`;
    the trim (`trim_box`) goes big above them. Simple shows the trim small, and moves the
    `speed_slot`, `volume_slot` and `knob_slot` into its own cards (EditDialog._place).
    The speed, pitch, volume and knobs are Live controls' own widgets (soundpanel), so
    the same settings read and sound the same in both. `changed` fires on any edit;
    `fx()` is the settings dict for SoundMeta.fx ({} when nothing is changed).

    `pick_voice(voice)` opens the voice picker (ui.voicepicker) on the sound's voice
    and gives back the new one, or None if it was cancelled. The sound keeps a copy.

    A splice clicked on the big waveform (`part`, its number from 0; None: the whole
    sound) turns the speed, pitch, volume, knobs, effects and equalizer into that
    splice's own (soundfx "parts"); the whole sound's wait in `_whole` meanwhile."""
    changed = Signal()
    peaks_read = Signal(int, object)   # (trim generation, peaks) from the waveform worker
    trim_replaced = Signal()           # set_sound made a new `trim` (Advanced re-hooks it)
    volume_edited = Signal()           # the Volume slider (the pad's, EditDialog keeps it)
    part_picked = Signal(object)       # the panels show splice `part` now (None: the sound)

    def __init__(self, fx: dict | None, meta: SoundMeta | None = None, pick_voice=None):
        super().__init__()
        self._pick_voice = pick_voice
        self._trim_gen = 0
        self.peaks_read.connect(self._on_peaks)
        self._voice: dict = {}
        self._live: list = []
        self.part: int | None = None
        self._whole: dict = {}          # the sound's own settings while a splice's show
        self._pad_volume = 100.0        # ...and the pad's volume
        self._loading = False
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
        self._deleted: tuple[str, str, int, dict] | None = None   # (kind, name, at, it)
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

        # the trim: small in Simple's Trim card, big in Advanced's editor (it moves it)
        self.trim_box = QWidget()
        tb = QVBoxLayout(self.trim_box)
        tb.setContentsMargins(0, 0, 0, 0)
        tb.setSpacing(8)
        self.trim_layout = tb   # where the trim is: here, or Advanced's editor
        self.trim_hint = hint_label(_("Trimming works once the sound has loaded."))
        # it only picks the part that plays: someone hunted for the cut file
        self.trim_kept = hint_label(_("Your file stays whole: only the part between the "
                                      "handles plays."))
        tb.addWidget(self.trim_hint)
        tb.addWidget(self.trim_kept)
        self.trim = self._new_trim(meta, tb.indexOf(self.trim_hint))   # above them

        # Live controls' own sliders, knobs and presets (soundpanel)
        p = self.panel = SoundPanel(SPEED, PITCH, VOLUME, VOLUME_QUICK, narrow=True)
        self.speed, self.pitch, self.keep, self.volume = p.speed, p.pitch, p.keep, p.volume
        self.pitch_note, self.knobs, self.fx_presets = p.pitch_note, p.knobs, p.presets
        self.boost = popup_slider(BOOST, 0.0)
        name_w = max(p.name_w, name_of(self.boost).sizeHint().width())
        p.set_name_width(name_w)
        name_of(self.boost).setFixedWidth(name_w)
        self.speed_slot = self._slot(self.speed, p.speed_quick)
        self.volume_slot = self._slot(self.volume, p.volume_quick)
        self.knob_slot = self._slot(*self.knobs.values())
        self._before_preset: tuple[str, dict, tuple[float, float, bool]] | None = None

        # (Advanced's column, titled Speed & loudness: no headings inside, so it fits
        # whole on a 1280 x 800 screen)
        tv.setContentsMargins(0, 14, 8, 0)   # (its first row level with the others')
        tv.addWidget(self.speed_slot)
        tv.addWidget(self.pitch)
        # "+4.5 st from the speed" beside Keep pitch, not on a line of its own under
        # Pitch (kept empty while hidden, it left a hole in the column)
        keep_row = QHBoxLayout()
        keep_row.setSpacing(12)
        keep_row.addWidget(self.keep)
        keep_row.addWidget(self.pitch_note, 1)
        self.pitch_note.setContentsMargins(0, 0, 0, 0)
        self.pitch_note.setWordWrap(True)
        tv.addLayout(keep_row)
        tv.addSpacing(8)
        tv.addWidget(self.volume_slot)
        tv.addWidget(self.boost)
        self.boost_hint = hint_label("")
        tv.addWidget(self.boost_hint)
        self.reverse = QCheckBox(_("Play backwards"))
        tv.addWidget(self.reverse)
        tv.addStretch(1)

        v.addWidget(self.knob_slot)
        v.addWidget(p.preset_box)
        v.addWidget(p.fx_note)

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
        p.tuning_edited.connect(self._edited)
        p.knobs_edited.connect(self._knobs_edited)
        p.volume_edited.connect(self._volume_moved)
        p.preset_clicked.connect(self._fx_preset_clicked)
        self.boost.changed.connect(self._edited)
        self.reverse.toggled.connect(self._edited)
        self.eq.changed.connect(lambda *__: self._edited())
        self.preset.currentIndexChanged.connect(
            lambda __: self._on_preset(self.preset.currentData()))
        self._matching_preset()

    @staticmethod
    def _slot(*widgets: QWidget) -> QWidget:
        """Widgets that move together between Simple's cards and Advanced's pages."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        for x in widgets:
            lay.addWidget(x)
        return w

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
        trim.wave.picked.connect(self._pick_part)
        trim.wave.level_moved.connect(self._level_moved)
        return trim

    def _on_peaks(self, gen: int, peaks):
        if gen == self._trim_gen:   # still the same sound's trim
            self.trim.wave.set_peaks(peaks)

    def set_sound(self, meta: SoundMeta):
        """Show another sound (Edit sound reused, EditControl.edit): its trim and fx."""
        if self.part is not None:   # (the last sound's splice: back to a whole sound)
            self.part = None
            self.volume.set_value(self._pad_volume)
            self._show_part_mode()
            self.part_picked.emit(None)
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

    def eq_off(self):
        """The equalizer flat and off (the summary's ×)."""
        self.eq.set_gains([0.0] * len(self.eq.gains()), "Flat (off)")
        self._edited()

    def on_count(self) -> int:
        return sum(r.chk.isChecked() for r in self.rows.values())

    def load(self, fx: dict):
        """Show settings `fx` (the trim too); a splice picked keeps showing its own."""
        f = soundfx.clean(fx)
        self._whole = {k: f[k] for k in soundfx.PART_FX}
        self._loading = True
        try:
            self.trim.blockSignals(True)
            self.trim.load(f)   # (a splice still picked shows its own: _pick_part)
            self.trim.blockSignals(False)
        finally:
            self._loading = False
        self._voice = f["voice"]
        self._show_voice()
        if self.part is None:
            self._show_knobs(f)
        else:
            self._show_part(self.part)

    def _show_knobs(self, f: dict):
        """The speed, pitch, boost, Play backwards, equalizer, effects and knobs as in
        (cleaned) settings `f`, without `changed`."""
        widgets = (self.speed, self.pitch, self.boost, self.keep, self.reverse, self.eq,
                   *self.rows.values())
        for w in widgets:
            w.blockSignals(True)
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
        self._live = f["live"]
        self._show_live()
        self._boost_hint()
        self._pitch_note()

    def _knobs(self) -> dict:
        """What the speed, pitch, boost, equalizer, effects and knobs say now (soundfx's
        PART_FX: what a splice can have of its own)."""
        gains, on, _t, _p = self.eq.state()
        return {"speed": round(self.speed.value(), 3), "pitch": round(self.pitch.value(), 2),
                "tape": not self.keep.isChecked(), "gain_db": round(self.boost.value(), 2),
                "reverse": self.reverse.isChecked(),
                "eq": gains if on else [0.0] * len(gains),
                "effects": {t: r.state() for t, r in self.rows.items() if r.chk.isChecked()},
                "live": self._live}

    # ------------------------------------------------------------------ a splice's own
    def _pick_part(self, i):
        """The waveform picked splice `i` (None: the whole sound): the panels show its
        own settings, and edits go to it."""
        wave = self.trim.wave
        i = i if i is not None and 0 <= i < len(wave.splices) else None
        if i is not None and i != self.part:
            usage.used("edit-splice-own")
        if self.part is None and i is not None:   # the whole sound's, kept till it's back
            self._whole = self._knobs()
            self._pad_volume = self.volume.value()
        self.part = i
        if i is None:
            if not self._loading:   # (load shows the sound's own next)
                self._show_knobs(soundfx.clean(self._whole))
            self.volume.set_value(self._pad_volume)
        else:
            self._show_part(i)
        self._show_part_mode()
        self._light_presets()
        self._matching_preset()
        self.part_picked.emit(i)

    def _show_part(self, i: int):
        p = self.trim.wave.parts[i] if i < len(self.trim.wave.parts) else {}
        self._show_knobs(soundfx.clean({k: p[k] for k in soundfx.PART_FX if k in p}))
        self.volume.set_value(float(p.get("volume", 1.0)) * 100)

    def _show_part_mode(self):
        """A splice's own settings have no voice: that's the whole sound's."""
        on = self.part is None
        self.voice.setEnabled(on and self._pick_voice is not None)
        self.voice_off.setEnabled(on)
        self.voice.setToolTip(_("Says this sound in a voice from the Voice tab, the way your "
                                "mic sounds with it: a voice changer voice, an AI voice or "
                                "your own voice combo") if on else
                              _("A voice is for the whole sound: click outside the splices "
                                "to get back to it"))

    def _level_moved(self, i: int):
        """A splice's level line dragged on the waveform: its Volume slider shows it."""
        if i == self.part:
            p = self.trim.wave.parts[i] if i < len(self.trim.wave.parts) else {}
            self.volume.blockSignals(True)
            self.volume.set_value(float(p.get("volume", 1.0)) * 100)
            self.volume.blockSignals(False)

    def _volume_moved(self):
        if self.part is None:
            self.volume_edited.emit()   # the pad's
        else:
            self._edited()              # the splice's own

    def _save_part(self):
        """The panels' settings into the picked splice's (its fades kept)."""
        wave, i = self.trim.wave, self.part
        if i is None or i >= len(wave.parts):
            return
        old = wave.parts[i]
        wave.parts[i] = soundfx.clean_part({
            **self._knobs(), "volume": self.volume.value() / 100,
            **{k: old[k] for k in ("fade_in", "fade_out", "fade_in_from", "fade_out_to")
               if k in old}})

    def _show_live(self):
        """The sound's Live controls stages on the knobs (merged into one set)."""
        self.panel.set_knobs(soundfx.live_merged(self._live))
        self._light_presets()

    def knob_values(self) -> dict[str, float]:
        """The Live controls knobs that are off 0."""
        return self.panel.knob_values()

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
        self.panel.light(self._fx_preset_on)

    def _set_tuning(self, speed: float, pitch: float, keep: bool):
        self.panel.set_tuning(speed, pitch, keep)

    def _fx_preset_clicked(self, name: str, on: bool):
        """Live controls' preset: sets its knobs, and its speed and pitch when it has
        them; clicked again (lit), back to how they were before it."""
        usage.used("edit-preset")
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
        self.panel.set_knobs(knobs)
        self._knobs_edited()

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
        knobs = self._knobs() if self.part is None else self._whole
        f = {**self.trim.trim_fx(), **knobs, "voice": self._voice}
        # (splices only marked change nothing, but stay with the sound)
        return {} if soundfx.is_neutral(f) and not f["splices"] else soundfx.clean(f)

    def _boost_hint(self):
        db = self.boost.value()
        self.boost_hint.setText(_("⚠ Very loud: this clips on purpose (deep-fried territory). "
                                  "Preview it at low volume first.") if db > 6 else
                                _("Above 0 dB the sound gets louder until it clips."))

    def _edited(self):
        if self.part is not None and not self._loading:
            self._save_part()
        self._boost_hint()
        self._pitch_note()
        self._light_presets()
        self._matching_preset()
        self.changed.emit()

    def _pitch_note(self):
        self.panel.show_pitch_note()

    def _untrimmed(self) -> dict:
        """What the panels show (the sound's, or a picked splice's): no trim, no voice
        (a layer of its own: presets don't set it). Live controls' knobs are effects:
        Advanced's Effects column."""
        return soundfx.clean(self._knobs())

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
        """The built-in presets (Live controls' first, by their shown names), then yours
        (Live controls' too: the same list), then Custom."""
        self.mine = mypresets.load("sound")
        self._mine_live = set()   # yours that are Live controls' (saved as "live")
        for name, p in mypresets.load("live").items():
            if mypresets.find("sound", name) is None:
                self.mine[name] = soundfx.from_live(p)
                self._mine_live.add(name)
        self.preset.blockSignals(True)
        self.preset.clear()
        for name in soundfx.PRESETS:
            self.preset.addItem(preset_name(name), name)
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
        builtin = {n.casefold() for n in (*soundfx.PRESETS, *map(preset_name, soundfx.PRESETS))}
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
            other = mypresets.find("sound", name) or mypresets.find("live", name)
            if other is None:
                return name
            if QMessageBox.question(parent, title, plain_tip(_(
                    "You already have a preset called “{name}”. Replace it?", name=other))
                    ) == QMessageBox.StandardButton.Yes:
                return other
            text = name

    def _save_preset(self):
        """"Save as preset": these effects (not the trim or the voice) under a name, in
        the Preset list of every sound from now on, and in Live controls' My presets
        too when it can play them (speed, pitch and the knobs only)."""
        parent = self.fx_page.window()
        live = soundfx.to_live(self._untrimmed())
        if mypresets.full("live" if live is not None else "sound"):
            QMessageBox.information(parent, _("Save as preset"), ngettext(
                "You have {n} preset, the most there can be. Delete one first.",
                "You have {n} presets, the most there can be. Delete one first.",
                mypresets.MAX_PRESETS))
            return
        n, base = 1, _("My preset")
        while mypresets.find("sound", f"{base} {n}"):
            n += 1
        name = self._ask_preset_name(f"{base} {n}")
        if name:   # (one name, one kind: an old one of the other kind goes)
            for kind in mypresets.KINDS:
                if mypresets.find(kind, name) is not None:
                    mypresets.remove(kind, mypresets.find(kind, name) or name)
        if name and (mypresets.put("live", name, live) if live is not None
                     else mypresets.put("sound", name, self._untrimmed())):
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
        kind = "live" if name in self._mine_live else "sound"
        got = mypresets.remove(kind, name)
        if got is None:
            return
        self._deleted = (kind, name, *got)
        self.undo_text.setText(_("Deleted “{name}”", name=name))
        self.undo_row.show()
        self._fill_presets()
        self._matching_preset()

    def _undo_delete(self):
        if self._deleted is not None:
            kind, name, at, p = self._deleted
            mypresets.put(kind, name, p, at)
        self._deleted = None
        self.undo_row.hide()
        self._fill_presets()
        self._matching_preset()

    def reset_all(self):
        """Every effect off, the voice too (the trim stays). A splice picked: its own."""
        if self.part is not None:
            self._show_knobs(soundfx.neutral())
            self.volume.set_value(100)
            self._edited()
            return
        self.load(self.trim.trim_fx())
        self._matching_preset()
        self.changed.emit()

    def _on_preset(self, name: str):
        usage.used("edit-preset")
        p = soundfx.PRESETS.get(name) or (self.mine.get(name[len(MINE):])
                                          if name.startswith(MINE) else None)
        if p and self.part is not None:   # on the picked splice only
            self._show_knobs(soundfx.clean(p))
            self._edited()
        elif p:
            self.load({**p, **self.trim.trim_fx(), "voice": self._voice})
            self.changed.emit()
        self.delete_preset.setVisible(name.startswith(MINE))


class EditDialog(EditDialogParts, QDialog):
    """Edit one sound. Nothing is written to the SoundMeta until `apply()`;
    `hotkeys_changed` fires after a capture so the owner can re-register the (paused)
    global hotkeys. After exec(), `as_copy` says whether "Save a copy" was
    chosen (then apply() goes onto the copy, and the original stays as it was).

    preview_cb(sid, volume, fx, (fade_in, fade_out), done) plays the sound, with these
    (unsaved) effects and fades, to your headphones only."""
    KEEP_OPEN = True   # a click outside doesn't close it: it would lose work
    hotkeys_changed = Signal()
    picture_fetched = Signal(int, object, str)   # (which try, QImage or None, why not)
    source_forgotten = Signal()   # Details → Delete info: saved at once, Save or Cancel
    effects_reset = Signal()      # Reset effects: a playing sound goes plain at once
    advanced_changed = Signal(bool)   # the Simple | Advanced switch was clicked
    splice_saved = Signal(object, str)   # a splice's menu: (its effects, name) as a new pad

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
        # Simple: one page that scrolls, no tabs (the few controls people use; the
        # rest is in Advanced, and the summary at its top shows whatever is on)
        self.simple = QScrollArea()
        self.simple.setWidgetResizable(True)
        self.simple.setFrameShape(QScrollArea.Shape.NoFrame)
        lay.addWidget(self.simple, 1)
        self.switch = ModeSwitch(False)   # Simple | Advanced, at the page's top
        self.switch.picked.connect(self._switch_picked)
        self.adv: AdvancedView | None = None   # made the first time Advanced is picked
        self._simple_size: QSize | None = None

        # cards: how the pad looks, how it plays, its trim, speed and effects, and its
        # timings (folded). Labels share one column width across the cards so the
        # fields line up down the page.
        basics = QWidget()
        page = self._page = QVBoxLayout(basics)
        page.setContentsMargins(2, 2, 8, 2)   # (room for the scroll bar)
        page.setSpacing(10)
        self._head = QHBoxLayout()   # the summary (once there are effects), the switch
        self._head.setSpacing(8)
        page.addLayout(self._head)
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
        # the pad's volume: shown as Live controls' slider in the Speed & loudness card
        # (effects.volume, with its typed value and quick buttons); kept here
        self.vol = QSlider(Qt.Orientation.Horizontal, self)
        self.vol.setRange(0, 200)
        self.vol.setValue(round(meta.volume * 100))   # int() made 0.29 read as 28 %
        self.vol.hide()

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
        self.timing = c   # behind More options (page's end)
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
        self._set_color(self.color)

        self.effects = EffectsPanel(
            meta.fx, meta, (lambda v: pick_voice(v, self)) if pick_voice else None)
        self.effects.setParent(self)
        eff = self.effects
        # Advanced's three pages (its columns or tabs); Simple doesn't show them. Kept
        # hidden under the window, never parentless: freeing the window frees them (a
        # parentless page outlived every spare Edit sound a theme switch dropped)
        self._fx_scrolls = []
        for pg in (eff.trim_page, eff.fx_page, eff.eq_page):
            scroll = QScrollArea(self)
            scroll.hide()
            scroll.setWidgetResizable(True)
            scroll.setWidget(pg)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            self._fx_scrolls.append(scroll)
        self.effects.trim_replaced.connect(lambda: self.adv and self.adv.retrim())
        # the Volume slider is the pad's
        eff.volume.set_value(self.vol.value())
        eff.volume_edited.connect(lambda: self.vol.setValue(round(eff.volume.value())))
        self.vol.valueChanged.connect(   # (a splice picked: the slider is its own then)
            lambda val: eff.part is None and abs(eff.volume.value() - val) > 0.5
            and eff.volume.set_value(val))

        # Simple's top: what's on (a chip each, × takes it off), then the switch
        self.summary = Summary(eff)
        self.summary.set_sound(meta)
        self.bun = bunacts.EditBunny()   # Bun at his DJ desk, at the page's top
        self._head.addWidget(self.bun, 0, Qt.AlignmentFlag.AlignTop)
        self._head.addWidget(self.summary, 1)
        self._head.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignTop)

        def simple_card(title: str) -> QVBoxLayout:
            c = QFrame()
            c.setObjectName("setcard")
            v = QVBoxLayout(c)
            v.setContentsMargins(14, 10, 14, 12)
            v.setSpacing(8)
            v.addWidget(section_label(title))
            page.addWidget(c)
            return v
        self.simple_trim = simple_card(_("Trim"))
        self.simple_trim.addWidget(eff.trim_box)
        self.simple_speed = simple_card(_("Speed & loudness"))
        self.simple_fx = simple_card(_("Effects"))
        # the rare ones, folded: fades, wait first, cooldown
        self.more = QPushButton(_("More options"))
        self.more.setProperty("quiet", True)
        self.more.setCursor(Qt.CursorShape.PointingHandCursor)
        icons.set_icon(self.more, "fold", "muted", size=14)
        self.more.clicked.connect(lambda: self._show_more(self.timing.isHidden()))
        mrow = QHBoxLayout()
        mrow.addWidget(self.more)
        mrow.addStretch(1)
        page.addLayout(mrow)
        page.addWidget(self.timing)
        self.timing.hide()
        page.addStretch(1)
        self.simple.setWidget(basics)
        self._place(False)

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
        self.effects.changed.connect(self._tune_bun)
        self._tune_bun()
        self._fx_note()

        # one row at the bottom: a headphones icon to preview on the left, the
        # dialog's own buttons on the right
        prev = self.btn_preview = QPushButton()
        prev.setObjectName("iconbutton")
        prev.setProperty("quiet", True)
        icons.set_icon(prev, "headphones")
        prev.setToolTip(_("Preview (only you hear it)"))
        prev.setAccessibleName(_("Preview (only you hear it)"))

        def play_preview(_checked=False, fx: dict | None = None):
            """With `fx`: the sound with those effects (one splice), not the draft's."""
            busy.set_busy(prev, True)
            self._say(_("Rendering the effects…"), 0)

            def done(ok, ms=1500):
                busy.set_busy(prev, False)
                if ok:
                    self._say(_("▶  Playing"), ms)
                else:   # the window's corner card says why: the summary comes back
                    self._saying = False
                    self._fx_note()
            got = preview_cb(self.meta.id, self.vol.value() / 100,
                             self.effects.fx() if fx is None else fx, self.fades(), done)
            if got != "rendering":
                busy.set_busy(prev, False)
                self._say(_("Not loaded yet: try again in a moment") if got == "missing"
                          else _("▶  Playing"), 1500)
        prev.clicked.connect(play_preview)
        self.play_preview = play_preview

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
        self.btn_save, self.btn_copy = bb.button(QDialogButtonBox.StandardButton.Save), copy
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
        usage.used("edit-opened")
        if advanced:
            self.set_advanced(True)


    def _tune_bun(self):
        """Bun at the top mixes at the sound's speed, stretched up or squashed by its
        pitch; a change sends him off to snip (the trim) or twist a knob (the rest)."""
        f = self.effects.fx()
        self.bun.tune(float(f.get("speed", 1.0)), float(f.get("pitch", 0.0)))
        trim = self.effects.trim.trim_fx()
        rest = soundfx.clean({k: v for k, v in f.items() if k not in trim})
        was, self._bun_was = getattr(self, "_bun_was", None), (trim, rest)
        if was is None:
            return
        if was[0] != trim:
            self.bun.busy(bunacts.SNIP)
        elif was[1] != rest:
            self.bun.busy(bunacts.KNOB)

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
        self.summary.set_sound(meta)
        self.show_render(None)   # (EditControl.edit shows this sound's, if it has one)
        self.live_bar.hide()
        self._light_reset()   # (set_sound loads without the changed signal)
        for scroll in (self.simple, *self._fx_scrolls):
            scroll.verticalScrollBar().setValue(0)
        self._show_more(False)
        busy.set_busy(self.btn_preview, False)
        self._saying = False
        self._said = getattr(self, "_said", 0) + 1   # a "Playing" still timing out
        self._fx_note()
        self.show_tab(tab)
        self._remember()
        usage.used("edit-opened")

    TABS = ("sound", "trim", "effects", "eq")

    def show_tab(self, tab: str):
        """Bring `tab` ("sound", "trim", "effects", "eq") into view, in either view:
        Simple scrolls to its card (it has no equalizer: that's Advanced's)."""
        i = self.TABS.index(tab) if tab in self.TABS else 0
        if self.advanced():
            assert self.adv is not None
            if i:
                self.adv.show_page(i - 1)
            return
        if tab == "eq":
            self.set_advanced(True)
            assert self.adv is not None
            self.adv.show_page(2)
            return
        lay = (None, self.simple_trim, self.simple_fx, None)[i]
        card = lay.parentWidget() if lay is not None else None
        if card is None:
            self.simple.verticalScrollBar().setValue(0)
        else:
            self._page.activate()
            self.simple.ensureWidgetVisible(card, 0, 12)

    def _show_more(self, on: bool):
        """More options: the Timing card, folded or open."""
        self.timing.setVisible(on)
        icons.set_icon(self.more, "fold_open" if on else "fold", "muted", size=14)
        if on:   # once it's laid out (shown just now, it has no height yet)
            QTimer.singleShot(0, lambda: qt_valid(self) and self.simple.ensureWidgetVisible(
                self.timing, 0, 12))

    def _place(self, advanced: bool):
        """Put the sliders that both views show where this one has them: the speed,
        volume and knobs in Simple's cards, or back on Advanced's pages."""
        eff = self.effects
        moves = ((eff.speed_slot, self.simple_speed, eff.trim_page.layout(), eff.pitch),
                 (eff.volume_slot, self.simple_speed, eff.trim_page.layout(), eff.boost),
                 (eff.knob_slot, self.simple_fx, eff.fx_page.layout(), eff.panel.preset_box))
        for slot, simple, page, before in moves:
            parent = slot.parentWidget()
            old = parent.layout() if parent is not None else None
            for lay in (old, *(old.findChildren(QVBoxLayout) if old is not None else ())):
                i = lay.indexOf(slot) if lay is not None else -1
                if i >= 0:
                    take_out(lay, i)
                    break
            if advanced:
                page.insertWidget(page.indexOf(before), slot)
            else:
                simple.addWidget(slot)
            slot.show()

    # ------------------------------------------------------------------ Advanced
    def advanced(self) -> bool:
        return self.adv is not None and not self.adv.isHidden()

    def _switch_picked(self, on: bool):
        if on != self.advanced():
            self.set_advanced(on)
            self.advanced_changed.emit(on)

    def set_advanced(self, on: bool):
        """The Advanced view (a bigger window, everything at once) or the Simple one
        (one page). The same widgets move between them, so nothing is lost."""
        if on == self.advanced():
            return
        screen = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        if on:
            if self.adv is None:
                self.adv = AdvancedView(self)
                self.adv.switch.picked.connect(self._switch_picked)
                self._lay.insertWidget(self._lay.indexOf(self.simple) + 1, self.adv, 1)
            self._simple_size = self.size()
            usage.used("pad-effects")   # (the name only: usage.py) the effects editor
            w = min(ADV_W, screen.width() - 48)
            h = min(ADV_H, screen.height() - 48)
            self.simple.hide()
            self._place(True)
            self.adv.attach(self._fx_scrolls, w)
            self.adv.show()
            self.setMinimumSize(ADV_MIN_W, ADV_MIN_H)
            self.resize(w, h)
        else:
            assert self.adv is not None
            self.adv.detach()
            self.adv.hide()
            self._place(False)
            self.simple.show()
            self.setMinimumSize(self._simple_min_w(), 0)
            self.resize(self._simple_size or QSize(max(540, self.minimumWidth()), 640))
        self._move_bun(on)
        self.switch.set_advanced(on)
        if self.adv is not None:
            self.adv.switch.set_advanced(on)
        self._fx_note()   # (Advanced's effects line; Simple has its summary)
        if self.isVisible():   # all of it on the screen
            g = self.frameGeometry()
            x = min(max(g.x(), screen.left()), screen.right() - g.width())
            y = min(max(g.y(), screen.top()), screen.bottom() - g.height())
            self.move(max(x, screen.left()), max(y, screen.top()))

    def _move_bun(self, advanced: bool):
        """Bun goes with the view: the start of Simple's top line, or in Advanced the
        editor card's top-left corner, the button row beside him made as tall as he needs
        (_fit_bun)."""
        i = self._head.indexOf(self.bun)
        if i >= 0:
            take_out(self._head, i)
        adv = self.adv
        if advanced and adv is not None:
            self.bun.set_height(bunacts.ADV_H)
            self.bun.setParent(adv.editor)
            self._fit_bun()
            self.bun.raise_()
        else:
            if adv is not None:
                adv.bar.setContentsMargins(0, 0, 0, 0)
            self.bun.set_height(bunacts.ACT_H)
            self._head.insertWidget(0, self.bun, 0, Qt.AlignmentFlag.AlignTop)
        self.bun.show()

    def _fit_bun(self):
        """Bun in Advanced, centred in his corner of the editor card: left to right between
        the card's edge and the Preview button, top to bottom between the card's top and
        the waveform's ruler. The button row is made that tall, its buttons centred on
        him."""
        adv = self.adv
        assert adv is not None
        card = adv.editor.layout()
        assert card is not None   # (the card's own layout: always made with it)
        seen = self.bun.seen()
        side = BUN_GAP + BUN_ROOM / 2   # the same each side of him (Preview a bit off)
        self.bun.move(round(side - seen.left()), round(BUN_GAP - seen.top()))
        m = card.contentsMargins()
        left = round(2 * side + seen.width()) - m.left()
        adv.bar.setContentsMargins(left, 0, 0, 0)
        card.activate()
        # then measured, not worked out: the ruler a gap under him, the buttons' middle
        # level with his
        play, trim = adv.btn_play, self.effects.trim
        mid = play.mapTo(adv.editor, QPoint(0, 0)).y() + play.height() / 2
        ruler = trim.mapTo(adv.editor, QPoint(0, 0)).y()
        top = max(0, round(BUN_GAP + seen.height() / 2 - mid))
        bottom = max(0, round(2 * BUN_GAP + seen.height() - ruler) - top)
        adv.bar.setContentsMargins(left, top, 0, bottom)

    def set_player(self, player: QWidget):
        """The board's player (ui/sounds/editplayer.py), over the Save row: a big
        window covers the board's own, and the song had to be paused from somewhere."""
        self._lay.insertWidget(self._lay.indexOf(self._brow), player)
        self.player = player

    def _simple_min_w(self) -> int:
        """Simple's least width: its page whole beside its scroll bar (long languages
        too), and never under 500."""
        m = self._lay.contentsMargins()
        page = self.simple.widget()
        whole = ((page.minimumSizeHint().width() if page is not None else 0)
                 + self.simple.verticalScrollBar().sizeHint().width())
        # (on the scroll area too, so the window's size hint counts the page: a wide
        # player under it then can't make Simple wider than it was)
        self.simple.setMinimumWidth(whole)
        return max(500, whole + m.left() + m.right())

    def showEvent(self, e):
        super().showEvent(e)
        try:   # (nothing in a Qt override may raise: AGENT-RULES *Async results*)
            # the page grows once its cards are shown, and the scroll area makes it that
            # tall only one pass later: till then every row was squeezed into the old
            # height (the name box half shut, Start over the waveform) for the first
            # ~0.3 s on screen. Settled here, before the first paint.
            for _i in range(4):
                QApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
        except Exception:  # noqa: BLE001
            log.debug("Edit sound's first layout failed", exc_info=True)

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
            usage.used("edit-undo")
            self._hpos -= 1
            self._restore(self._history[self._hpos])

    def redo(self):
        self._flush()
        if self._hpos < len(self._history) - 1:
            usage.used("edit-redo")
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


    def _count_saved(self):
        """Which settings this save changed, by name only (usage.py), so Simple can show
        the ones people use."""
        m = self.meta
        was, now = soundfx.clean(m.fx), soundfx.clean(self.effects.fx())
        knobs = ("speed", "pitch", "tape", "live", "gain_db", "reverse", "eq", "effects",
                 "voice")
        changed: dict[str, bool] = dict(zip(
            ("speed", "pitch", "keep-pitch", "knobs", "boost", "reverse", "eq", "effects",
             "voice"), (was[k] != now[k] for k in knobs)))
        changed.update({
            "name": self.name.text().strip() not in ("", m.name),
            "colour": self.color != m.color, "picture": self.picture is not None,
            "hotkey": self.hotkey != m.hotkey, "press": self.mode.currentData() != m.mode,
            "loop": self.loop.isChecked() != m.loop, "hold": self.hold.isChecked() != m.hold,
            "only-them": self.only_them.isChecked() != m.only_them,
            "volume": self.vol.value() != round(m.volume * 100),
            "trim": (was["start"], was["end"]) != (now["start"], now["end"]),
            "fades": self.fades() != (m.fade_in, m.fade_out),
            "wait": self.delay.value() != round(m.delay * 10),
            "cooldown": self.cooldown.value() != round(m.cooldown * 10)})
        for k, on in changed.items():
            if on:
                usage.used(f"edit-{k}")
        usage.used("edit-copy" if self.as_copy else
                   "edit-advanced-saved" if self.advanced() else "edit-saved")

    def apply(self, target: SoundMeta | None = None):
        self._count_saved()
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
