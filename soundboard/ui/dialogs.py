"""Per-sound Edit dialog: the Sound tab (name, volume, hotkey…) and the Effects tab
(speed, pitch, EQ, boost, reverse and every voice effect, modules' included)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QScrollArea, QSlider, QTabWidget,
                               QVBoxLayout, QWidget)

from soundboard import soundfx, theme, voicefx
from soundboard.eq import PRESETS as EQ_PRESETS
from soundboard.library import (MAX_COOLDOWN_S, MAX_DELAY_S, MAX_FADE_S, PAD_COLORS,
                                SoundMeta, original_peaks)
from soundboard.settings import HotkeyDialog, pretty_key
from soundboard.ui import busy, fit, icons
from soundboard.ui.panel import EqPanel, hint_label, section_label, steady_number
from soundboard.ui.trim import TrimPanel
from soundboard.ui.voicepanel import EffectRow, ParamSlider
from soundboard.wheelguard import no_wheel
from soundboard.winkeys import Hotkeys
from soundboard.i18n import _

CUSTOM = "Custom"   # the preset box's item data when no preset matches
# what the pad colour swatches are called (tooltip and screen reader)
COLOUR_NAMES = {"#7c5cff": _("Purple"), "#ff5c8a": _("Pink"), "#1fb6ff": _("Blue"),
                "#13ce66": _("Green"), "#ffb020": _("Yellow"), "#ff7849": _("Orange"),
                "#00c2b2": _("Teal"), "#e056fd": _("Magenta"), "#5c7cfa": _("Indigo"),
                "#94a3b8": _("Grey")}
SPEED = voicefx.Param("speed", _("Speed"), *soundfx.SPEED_RANGE, 1.0, "x", 0.05)
PITCH = voicefx.Param("pitch", _("Pitch"), *soundfx.PITCH_RANGE, 0.0, " st", 1)
BOOST = voicefx.Param("gain_db", _("Boost"), *soundfx.GAIN_RANGE, 0.0, " dB", 1)


class EffectsPanel(QWidget):
    """Every per-sound effect setting. `changed` fires on any edit; `fx()` is the
    settings dict for SoundMeta.fx ({} when nothing is changed)."""
    changed = Signal()

    def __init__(self, fx: dict | None, meta: SoundMeta | None = None):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 14, 8, 0)   # room under the dialog's tab bar
        v.setSpacing(8)

        prow = QHBoxLayout()
        prow.addWidget(QLabel(_("Preset")))
        self.preset = QComboBox()
        for name in soundfx.PRESETS:
            self.preset.addItem(name, name)
        self.preset.addItem(_("Custom"), CUSTOM)
        no_wheel(self.preset)
        prow.addWidget(self.preset)
        reset = QPushButton(_("Reset"))
        reset.setObjectName("small")
        reset.setToolTip(_("Back to the original sound (the trim stays)"))
        reset.clicked.connect(lambda: self.preset.setCurrentIndex(0))   # the first preset
        prow.addWidget(reset)
        prow.addStretch(1)
        v.addLayout(prow)

        v.addWidget(section_label(_("Trim")))
        peaks, length = original_peaks(meta) if meta is not None else ([], 0.0)
        self.trim = TrimPanel(peaks, length)
        v.addWidget(self.trim)              # in the layout first: shown with no parent,
        self.trim.setVisible(length > 0)    # it flashed up as a window of its own
        if length <= 0:
            v.addWidget(hint_label(_("Trimming works once the sound has loaded.")))

        v.addWidget(section_label(_("Speed & pitch")))
        self.speed = ParamSlider(SPEED, 1.0)
        self.pitch = ParamSlider(PITCH, 0.0)
        self.tape = QCheckBox(_("Tape mode: speed changes the pitch too (nightcore / slowed)"))
        self.tape.setToolTip(_("Off: speed and pitch are independent. On: like a record player, "
                               "faster is also higher; Pitch adds on top."))
        for w in (self.speed, self.pitch, self.tape):
            v.addWidget(w)

        v.addWidget(section_label(_("Loudness")))
        self.boost = ParamSlider(BOOST, 0.0)
        v.addWidget(self.boost)
        self.boost_hint = hint_label("")
        v.addWidget(self.boost_hint)
        self.reverse = QCheckBox(_("Play backwards"))
        v.addWidget(self.reverse)

        self.eq = EqPanel(False, "sounds", "Flat (off)", [0.0] * 7)
        self.eq.lbl_for.hide()
        self.eq.cb_target.hide()
        v.addWidget(self.eq)

        v.addWidget(section_label(_("Effects")))
        self.rows: dict[str, EffectRow] = {}
        for etype, cls in voicefx.REGISTRY.items():
            if etype == "pitch":   # the Pitch slider above does this, better
                continue
            if etype == "cleanup":   # a mic's room noise: nothing to clean in a sound
                continue
            row = EffectRow(cls, {})
            row.changed.connect(self._edited)
            self.rows[etype] = row
            v.addWidget(row)
        v.addWidget(hint_label(_("Effects from add-on modules show up here too.")))
        v.addStretch(1)

        self.load(fx or {})
        for s in (self.speed, self.pitch, self.boost):
            s.changed.connect(self._edited)
        self.tape.toggled.connect(self._edited)
        self.reverse.toggled.connect(self._edited)
        self.trim.changed.connect(self._edited)
        self.eq.changed.connect(lambda *__: self._edited())
        self.preset.currentIndexChanged.connect(
            lambda __: self._on_preset(self.preset.currentData()))
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
        self.boost_hint.setText(_("⚠ Very loud: this clips on purpose (deep-fried territory). "
                                  "Preview it at low volume first.") if db > 6 else
                                _("Above 0 dB the sound gets louder until it clips."))

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
        self.preset.setCurrentIndex(max(0, self.preset.findData(name)))
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

    preview_cb(sid, volume, fx, (fade_in, fade_out), done) plays the sound, with these
    (unsaved) effects and fades, to your headphones only."""
    hotkeys_changed = Signal()

    def __init__(self, meta: SoundMeta, hotkeys: Hotkeys, preview_cb, parent=None,
                 tab: str = "sound"):
        super().__init__(parent)
        fit.watch(self)   # grows to fit its text (ui/fit.py)
        self.setWindowTitle(_("Edit sound"))
        self.meta = meta
        self.hotkeys = hotkeys
        self.hotkey = meta.hotkey
        self.color = meta.color
        self.as_copy = False
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)

        # three cards: the sound itself, its hotkey, its timings. Labels share one
        # column width across the cards so the fields line up down the page.
        basics = QWidget()
        page = QVBoxLayout(basics)
        page.setContentsMargins(2, 14, 2, 2)   # room under the tabs
        page.setSpacing(10)
        labels = [_("Name"), _("Volume"), _("Colour"), _("Hotkey"), _("On press")]
        label_w = max(self.fontMetrics().horizontalAdvance(t) for t in labels) + 12

        def card():
            c = QFrame()
            c.setObjectName("setcard")   # (its buttons and boxes keep their fill)
            g = QGridLayout(c)
            g.setContentsMargins(14, 12, 14, 12)
            g.setHorizontalSpacing(12)
            g.setVerticalSpacing(10)
            g.setColumnMinimumWidth(0, label_w)
            g.setColumnStretch(1, 1)
            page.addWidget(c)
            return g

        def row(g, text, field):
            r = g.rowCount()
            lbl = QLabel(text)
            lbl.setObjectName("muted")
            g.addWidget(lbl, r, 0, Qt.AlignLeft | Qt.AlignVCenter)
            if isinstance(field, QWidget):
                g.addWidget(field, r, 1)
                lbl.setBuddy(field)
            else:
                g.addLayout(field, r, 1)

        g = card()
        self.name = QLineEdit(meta.name)
        f = self.name.font()
        f.setPointSizeF(f.pointSizeF() + 1.5)
        f.setWeight(QFont.DemiBold)
        self.name.setFont(f)
        row(g, _("Name"), self.name)

        vrow = QHBoxLayout()
        vrow.setSpacing(10)
        self.vol = QSlider(Qt.Horizontal)
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
        crow.addStretch()
        row(g, _("Colour"), crow)

        self.only_them = QCheckBox(_("Only others hear it, not played in my headphones"))
        self.only_them.setToolTip(_("It still goes out to others (Discord, the game, OBS…); you "
                                    "just don't hear it yourself (Preview still plays it to you)"))
        self.only_them.setChecked(meta.only_them)
        g.addWidget(self.only_them, g.rowCount(), 1)

        # the hotkey is what most people open this for: near the top, not under the timings
        g = card()
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
        self.mode.addItem(_("Restart: press again restarts it"), "restart")
        self.mode.addItem(_("Overlap: every press plays a new copy"), "overlap")
        self.mode.addItem(_("Toggle: press again stops it"), "toggle")
        self.mode.addItem(_("Solo: stops every other sound first"), "solo")
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

        # timings two by two, each its name and value over its slider
        c = QFrame()
        c.setObjectName("setcard")
        tg = QGridLayout(c)
        tg.setContentsMargins(14, 12, 14, 14)
        tg.setHorizontalSpacing(24)
        tg.setVerticalSpacing(12)
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

        self.effects = EffectsPanel(meta.fx, meta)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.effects)
        scroll.setFrameShape(QScrollArea.NoFrame)
        self.tabs.addTab(scroll, _("Effects"))
        if tab == "effects":
            self.tabs.setCurrentIndex(1)

        # what the effects add up to, on its own line (hidden when there are none)
        self.fx_note = QLabel()
        self.fx_note.setObjectName("muted")
        self.fx_note.setWordWrap(True)
        lay.addWidget(self.fx_note)
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
                self._say(_("▶  Playing") if ok else _("Couldn't render it"), ms)
            got = preview_cb(self.meta.id, self.vol.value() / 100, self.effects.fx(),
                             self.fades(), done)
            if got != "rendering":
                busy.set_busy(prev, False)
                self._say(_("Not loaded yet: try again in a moment") if got == "missing"
                          else _("▶  Playing"), 1500)
        prev.clicked.connect(play_preview)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setObjectName("primary")   # the one filled button
        bb.button(QDialogButtonBox.Cancel).setProperty("quiet", True)
        copy = bb.addButton(_("Save as new sound"), QDialogButtonBox.AcceptRole)
        copy.setToolTip(_("Keep this sound as it is and add the edited version as a new pad"))
        copy.clicked.connect(lambda: setattr(self, "as_copy", True))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        brow = QHBoxLayout()
        brow.addWidget(prev)
        brow.addStretch(1)
        brow.addWidget(bb)
        lay.addLayout(brow)
        self.setMinimumWidth(500)
        self.resize(540, 640)

    @staticmethod
    def _fade_cell(grid: QGridLayout, r: int, col: int, label: str, value: float, tip: str,
                   top: float = MAX_FADE_S) -> QSlider:
        """A 0..top slider in tenths of a second, its name and value above it."""
        v = QVBoxLayout()
        v.setSpacing(4)
        head = QHBoxLayout()
        name = QLabel(label)
        name.setToolTip(tip)
        lbl = QLabel()
        lbl.setObjectName("muted")
        steady_number(lbl, _("{s} s", s=f"{top:.1f}"))
        head.addWidget(name)
        head.addStretch(1)
        head.addWidget(lbl)
        sl = QSlider(Qt.Horizontal)
        sl.setRange(0, int(top * 10))
        sl.setValue(int(round(min(max(value, 0.0), top) * 10)))
        sl.setToolTip(tip)
        sl.setAccessibleName(label)
        no_wheel(sl)

        def show(v):
            lbl.setText(_("{s} s", s=f"{v / 10:.1f}") if v else _("off"))
            sl.setAccessibleDescription(lbl.text())
        sl.valueChanged.connect(show)
        show(sl.value())
        v.addLayout(head)
        v.addWidget(sl)
        grid.addLayout(v, r, col)
        return sl

    def fades(self) -> tuple[float, float]:
        return self.fade_in.value() / 10, self.fade_out.value() / 10

    def _fx_note(self):
        if getattr(self, "_saying", False):
            return   # a preview message is up: it puts the summary back when it's done
        s = soundfx.summary(self.effects.fx())
        self.fx_note.setText(_("Effects: {s}", s=s) if s else "")
        self.fx_note.setVisible(bool(s))

    def _say(self, text: str, ms: int):
        """A preview message where the effects summary goes; back to the summary after
        ``ms`` (0: stays until the next message)."""
        self._saying = True
        self.fx_note.setText(text)
        self.fx_note.show()
        self._said = getattr(self, "_said", 0) + 1
        if ms:
            n = self._said

            def back():
                if n == self._said:
                    self._saying = False
                    self._fx_note()
            QTimer.singleShot(ms, self, back)

    def _set_color(self, c):
        self.color = c
        t = theme.T
        for b, col in self.swatches:
            b.setChecked(col == c)
            # its own sheet outranks the theme's :focus rule, so focus is drawn here:
            # an accent ring, thick when it's also the chosen colour
            b.setStyleSheet(
                f"QPushButton {{ background:{col}; border:1px solid {t['border']};"
                f" border-radius:11px; }}"
                f"QPushButton:checked {{ border:3px solid {t['text']}; }}"
                f"QPushButton:focus {{ border:2px solid {t['accent']}; }}"
                f"QPushButton:checked:focus {{ border:3px solid {t['accent']}; }}")

    def _set_hk(self, combo):
        self.hotkey = combo
        self.hk_btn.setText(pretty_key(combo) or _("Click to set…"))

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
        m.hold = self.hold.isChecked()
        m.only_them = self.only_them.isChecked()
        m.delay = self.delay.value() / 10
        m.cooldown = self.cooldown.value() / 10
        m.hotkey = self.hotkey
        m.color = self.color
        m.fade_in, m.fade_out = self.fades()
        m.fx = self.effects.fx()
