"""Who's listening (on the Setup tab, and in Settings -> Audio): the simple modes
(Game, Voice chat, Clean, Advanced: soundboard.profiles) that pick the destination
mode shaping the sounds bus for the voice chat on the other end
(soundboard.destination), Advanced's full picker, and an editor for custom modes
(describe any other codec by the same knobs)."""
from __future__ import annotations

import html

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QPushButton, QSlider, QVBoxLayout, QWidget)

from soundboard import destination, profiles, voicesdk
from soundboard.destination import CEILINGS, LOWCUTS, Dest
from soundboard.ui import fit
from soundboard.ui.panel import Flow, UndoBar, hint_label
from soundboard.wheelguard import no_wheel
from soundboard.i18n import _


def describe(d: Dest) -> str:
    """One line of what a mode does, for the label under the picker."""
    if not d.active:
        return d.about
    parts = []
    if d.mono:
        parts.append(_("mono"))
    if d.bass > 0:
        parts.append(_("sub-bass harmonics {percent}%", percent=round(d.bass * 100)))
    if d.lowcut:
        parts.append(_("sub-bass under {hz} Hz swapped for level", hz=d.lowcut))
    if d.comp > 0:
        parts.append(_("compressor {percent}%", percent=round(d.comp * 100)))
    if d.ceiling:
        parts.append(_("cut above {khz} kHz", khz=d.ceiling // 1000))
    what = " · ".join(parts)
    return f"{d.about}  ({what})" if d.about else what


DUCK_LABELS = ((_("Off"), 0.0), (_("A little (-6 dB)"), -6.0), (_("Half (-12 dB)"), -12.0),
               (_("A lot (-20 dB)"), -20.0))


def apply_send(cfg, engine):
    """Push the config's send options (mono, ducking, the mic gate) onto the engine."""
    engine.send_mono = bool(cfg.send_mono)
    engine.duck_db = min(0.0, float(cfg.duck_db))
    engine.mic_gate = bool(cfg.mic_gate)


def ceiling_label(hz: int) -> str:
    return _("No cut (full band)") if not hz else _("Cut above {khz} kHz", khz=hz // 1000)


def lowcut_label(hz: int) -> str:
    return (_("Keep it (no cut)") if not hz
            else _("Cut under {hz} Hz, give the level back", hz=hz))


def _dest_cfg(mw) -> dict:
    d = mw.cfg.dest
    if not isinstance(d, dict):
        d = mw.cfg.dest = {}
    return d


def mode_tip(p: profiles.Profile) -> str:
    """A simple mode's tooltip: who it's for, then what it does."""
    return f"<b>{p.name}</b>: {html.escape(p.blurb)}<br><br>{html.escape(p.about)}"


def set_simple(mw, key: str) -> profiles.Profile:
    """Switch to simple mode `key`: picks its shaping from what's seen, applies, saves."""
    d = _dest_cfg(mw)
    mw.mode_why = profiles.pick(d, key, getattr(mw, "voice_hints", ()))
    destination.apply(mw.cfg, mw.engine)
    mw._save_later()
    _refresh_views(mw)
    return profiles.BY_KEY[key]


def set_exact(mw, mode_key: str):
    """One destination mode by name (the remote's ?set=, Advanced's picker): Off is
    Clean, anything else is Advanced with that mode, so nothing switches it."""
    d = _dest_cfg(mw)
    d["mode"] = mode_key
    d["simple"] = profiles.CLEAN.key if mode_key == "off" else profiles.ADVANCED.key
    mw.mode_why = ""
    destination.apply(mw.cfg, mw.engine)
    mw._save_later()
    _refresh_views(mw)


def _refresh_views(mw):
    for name in ("mode_combo", "dest_panel"):
        w = getattr(mw, name, None)
        if w is not None and hasattr(w, "refresh"):
            w.refresh()


class ModesHelp(QDialog):
    """What do these do?: every simple mode in plain words, and what it's doing now."""

    def __init__(self, mw, parent=None):
        super().__init__(parent or mw)
        fit.watch(self)
        self.setWindowTitle(_("Sound modes: what each one does"))
        self.setMinimumWidth(520)
        v = QVBoxLayout(self)
        v.setSpacing(10)
        now = QLabel(_("<b>Right now:</b> {explain}", explain=html.escape(
            profiles.explain(_dest_cfg(mw), getattr(mw, "mode_why", "")))))
        now.setWordWrap(True)
        v.addWidget(now)
        for p in profiles.PROFILES:
            lbl = QLabel(f"<b>{p.name}</b> &nbsp;<i>{html.escape(p.blurb)}</i><br>"
                         f"{html.escape(p.about)}")
            lbl.setWordWrap(True)
            lbl.setTextFormat(Qt.RichText)
            v.addWidget(lbl)
        v.addWidget(hint_label(profiles.shared()))
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.accept)
        v.addWidget(bb)


class ModeCombo(QComboBox):
    """Who's listening as one small dropdown (the Sounds tab's top bar): the simple
    modes, the same setting as DestPanel's buttons. Each one's tooltip says what it
    does."""

    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        self.setAccessibleName(_("Who's listening"))
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(10)
        no_wheel(self)
        self.currentIndexChanged.connect(self._picked)
        sig = getattr(mw, "voice_engine", None)
        if sig is not None:
            sig.connect(self._on_voice_engine)   # a simple mode picked new shaping
        self.refresh()

    def refresh(self):
        d = _dest_cfg(self.mw)
        p = profiles.current(d)
        self.blockSignals(True)
        self.clear()
        for q in profiles.PROFILES:
            label = q.name
            if q is profiles.ADVANCED:
                label = (_("Advanced: {label}", label=destination.resolve(d).name)
                         if p is q else _("Advanced…"))
            self.addItem(label, q.key)
            self.setItemData(self.count() - 1, mode_tip(q), Qt.ToolTipRole)
        self.setCurrentIndex(max(0, self.findData(p.key)))
        self.view().setMinimumWidth(self.view().sizeHintForColumn(0) + 32)   # long names whole
        self.blockSignals(False)
        self.setToolTip(
            _("Who's listening: {explain}<br><br>Hover a mode in the list to see what it does. "
              "More in Settings → Audio → Who's listening.",
              explain=html.escape(profiles.explain(d, getattr(self.mw, 'mode_why', '')))))

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()   # changed on the Setup tab or in Settings meanwhile

    def _on_voice_engine(self, _key):
        self.refresh()

    def _picked(self, i: int):
        key = self.itemData(i)
        if key not in profiles.BY_KEY:
            return
        set_simple(self.mw, key)
        if key == profiles.ADVANCED.key:   # its knobs live in Settings
            QTimer.singleShot(0, lambda: self.mw.open_settings("audio"))


class DestPanel(QWidget):
    """The simple modes as buttons, what the picked one is doing, a "What do these
    do?" box, Advanced's full picker (shown in Advanced only) and the send options.
    Applies to the engine and saves through the main window straight away."""

    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        row = Flow(gap=4)   # wraps in a narrow window instead of widening it
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        for p in profiles.PROFILES:
            b = QPushButton(p.name)
            b.setCheckable(True)
            b.setToolTip(mode_tip(p))
            b.setAccessibleName(_("{label} mode", label=p.name))
            b.setAccessibleDescription(p.blurb)
            self.group.addButton(b)
            self.buttons[p.key] = b
            row.addWidget(b)
        v.addLayout(row)
        self.now = hint_label("")
        v.addWidget(self.now)
        help_btn = QPushButton(_("What do these do?"))
        help_btn.setObjectName("small")
        help_btn.setToolTip(_("Every mode in plain words, and what it's doing right now"))
        help_btn.clicked.connect(self.show_help)
        v.addWidget(help_btn, 0, Qt.AlignLeft)
        # a hint that something else is in use: Discord listening while in Game, say,
        # or (Advanced) the game in front ships a voice engine we know
        self.suggest = QWidget()
        sr = QVBoxLayout(self.suggest)   # stacked: side by side it widened the Setup tab
        sr.setContentsMargins(0, 0, 0, 0)
        sr.setSpacing(4)
        self.suggest_text = hint_label("")
        sr.addWidget(self.suggest_text)
        self.suggest_btn = QPushButton(_("Use it"))
        self.suggest_btn.setToolTip(_("Switch to the mode that suits what's listening"))
        self.suggest_btn.setObjectName("small")
        self.suggest_btn.clicked.connect(self._use_suggestion)
        sr.addWidget(self.suggest_btn, 0, Qt.AlignLeft)
        self.suggest.hide()
        v.addWidget(self.suggest)

        # Advanced: every mode by name, custom modes, switching between all of them
        self.advanced = QWidget()
        av = QVBoxLayout(self.advanced)
        av.setContentsMargins(0, 0, 0, 0)
        av.setSpacing(6)
        arow = QHBoxLayout()
        self.combo = QComboBox()
        no_wheel(self.combo)
        arow.addWidget(self.combo, 1)
        custom = QPushButton(_("Custom modes…"))
        custom.setToolTip(_("Describe another codec or service by what it does to the sound"))
        custom.clicked.connect(self.edit_custom)
        arow.addWidget(custom)
        av.addLayout(arow)
        self.desc = hint_label("")
        av.addWidget(self.desc)
        self.chk_auto = QCheckBox(_("Pick the mode by itself"))
        self.chk_auto.setToolTip(
            _("When Discord, TeamSpeak, Mumble or a game with a known voice chat is listening to "
              "your mic (or the cable), use its mode without asking. With nothing listening, the "
              "mode stays as it is."))
        av.addWidget(self.chk_auto)
        v.addWidget(self.advanced)
        sig = getattr(mw, "voice_engine", None)
        if sig is not None:
            sig.connect(self._on_voice_engine)   # a bound slot: gone with the panel
        # the send stage (soundboard.sendfx), whatever the mode
        self.chk_mono = QCheckBox(_("Send in mono (recommended)"))
        self.chk_mono.setToolTip(
            _("Every voice chat sends one channel. Onion Board makes it, smarter than Discord or "
              "a game would: wide stereo sounds and phasey bass don't cancel out"))
        v.addWidget(self.chk_mono)
        duck = QHBoxLayout()
        duck.addWidget(QLabel(_("While I talk, lower my sounds:")))
        self.cb_duck = QComboBox()
        no_wheel(self.cb_duck)
        for label, db in DUCK_LABELS:
            self.cb_duck.addItem(label, db)
        self.cb_duck.setToolTip(_("Turns your sounds down while the mic hears you, so your voice "
                                  "isn't buried under a song"))
        duck.addWidget(self.cb_duck, 1)
        v.addLayout(duck)
        self.chk_gate = QCheckBox(_("Mute my mic while a sound plays"))
        self.chk_gate.setToolTip(_("Others hear only the sound, clean, and your mic comes back "
                                   "the moment it ends. Handy with a noisy room or keyboard."))
        v.addWidget(self.chk_gate)
        self.refresh()
        self.group.buttonClicked.connect(self._simple_clicked)
        self.combo.currentIndexChanged.connect(self._picked)
        self.chk_auto.toggled.connect(self._auto_changed)
        self.chk_mono.toggled.connect(self._send_changed)
        self.cb_duck.currentIndexChanged.connect(self._send_changed)
        self.chk_gate.toggled.connect(self._send_changed)

    def _cfg(self) -> dict:
        return _dest_cfg(self.mw)

    def refresh(self):
        cfg = self._cfg()
        p = profiles.current(cfg)
        self.buttons[p.key].setChecked(True)
        current = destination.resolve(cfg).key
        self.combo.blockSignals(True)
        self.combo.clear()
        for d in destination.all_modes(cfg.get("custom")):
            self.combo.addItem(_("{mode}  (custom)", mode=d.name) if d.custom else d.name, d.key)
        self.combo.setCurrentIndex(max(0, self.combo.findData(current)))
        self.combo.blockSignals(False)
        c = self.mw.cfg
        for w in (self.chk_mono, self.cb_duck, self.chk_gate, self.chk_auto):
            w.blockSignals(True)
        self.chk_auto.setChecked(bool(cfg.get("auto")))
        self.chk_gate.setChecked(bool(c.mic_gate))
        self.chk_mono.setChecked(bool(c.send_mono))
        i = min(range(len(DUCK_LABELS)), key=lambda k: abs(DUCK_LABELS[k][1] - c.duck_db))
        self.cb_duck.setCurrentIndex(i)
        for w in (self.chk_mono, self.cb_duck, self.chk_gate, self.chk_auto):
            w.blockSignals(False)
        self._show()

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()   # the other copy (Setup tab / Settings) may have changed it

    def _show(self):
        cfg = self._cfg()
        p = profiles.current(cfg)
        self.now.setText(html.escape(profiles.explain(cfg, getattr(self.mw, "mode_why", ""))))
        self.advanced.setVisible(p is profiles.ADVANCED)
        self.desc.setText(describe(destination.resolve(cfg)))
        self._show_suggestion()
        combo = getattr(self.mw, "mode_combo", None)   # the Sounds tab's dropdown
        if combo is not None:
            combo.refresh()

    def show_help(self):
        dlg = ModesHelp(self.mw, self)
        dlg.exec()

    def _simple_clicked(self, b):
        key = next(k for k, w in self.buttons.items() if w is b)
        if key == profiles.current(self._cfg()).key:
            return
        set_simple(self.mw, key)
        self.refresh()

    def _better(self):
        """(simple mode key, hint) when something seen suits another simple mode."""
        p = profiles.current(self._cfg())
        h = profiles.better(p, getattr(self.mw, "voice_hints", ()))
        return (h.simple, h) if h else (None, None)

    def _suggested(self) -> str | None:
        """Advanced: the mode the game in front calls for, if it isn't the one picked."""
        if profiles.current(self._cfg()) is not profiles.ADVANCED:
            return None
        key = getattr(self.mw, "voice_suggestion", None)
        if key not in destination.BUILTIN_BY_KEY:
            return None
        return None if destination.resolve(self._cfg()).key == key else key

    def _on_voice_engine(self, _key):
        self.refresh()   # a simple mode or *Pick the mode by itself* may have switched

    def _auto_changed(self, on: bool):
        self._cfg()["auto"] = bool(on)
        self._cfg()["simple"] = profiles.ADVANCED.key   # it's Advanced's switch
        self.mw._save_later()
        if on:
            self.mw._auto_dest()
            self.refresh()

    def _show_suggestion(self):
        key = self._suggested()
        simple, hint = self._better()
        if key:
            why = html.escape(getattr(self.mw, "voice_why", "") or (
                _("The game you have open uses {voice} for voice chat",
                  voice=voicesdk.NAMES.get(key, key))))
            self.suggest_text.setText(
                _("{why}: <b>{label}</b> suits it.",
                  why=why, label=destination.BUILTIN_BY_KEY[key].name))
        elif simple:
            self.suggest_text.setText(
                _("{why}: <b>{label}</b> mode suits it.",
                  why=html.escape(hint.why), label=profiles.BY_KEY[simple].name))
        self.suggest.setVisible(bool(key or simple))

    def _use_suggestion(self):
        key = self._suggested()
        if key:
            self.combo.setCurrentIndex(max(0, self.combo.findData(key)))
            return
        simple, _hint = self._better()
        if simple:
            set_simple(self.mw, simple)
            self.refresh()

    def _picked(self, i: int):
        key = self.combo.itemData(i)
        if key is None:
            return
        d = self._cfg()
        d["mode"] = key
        d["simple"] = profiles.ADVANCED.key   # picked by name: stays exactly that
        destination.apply(self.mw.cfg, self.mw.engine)
        self.mw._save_later()
        self._show()

    def _send_changed(self, *__):
        c = self.mw.cfg
        c.send_mono = self.chk_mono.isChecked()
        c.duck_db = float(self.cb_duck.currentData())
        c.mic_gate = self.chk_gate.isChecked()
        apply_send(c, self.mw.engine)
        self.mw._save_later()

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
        self.setWindowTitle(_("Custom destination modes"))
        self.setMinimumSize(640, 420)
        cfg = mw.cfg.dest if isinstance(mw.cfg.dest, dict) else {}
        mw.cfg.dest = cfg
        raw = cfg.get("custom")
        self.items: list[dict] = ([d for d in raw if isinstance(d, dict)]
                                  if isinstance(raw, list) else [])
        cfg["custom"] = self.items
        self._loading = False

        lay = QVBoxLayout(self)
        lay.addWidget(hint_label(
            _("A mode describes what the listener's voice codec does to your sounds, so the app "
              "can pre-shape them: which frequencies it cuts, how much sub-bass to turn into "
              "harmonics that survive, how much to even out the level, and whether it's mono. "
              "The built-in modes were measured; to measure another service, run "
              "scripts/codec_bench.py from the source tree.")))
        body = QHBoxLayout()
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._select)
        left.addWidget(self.list, 1)
        self.empty = hint_label(_("No custom modes yet. Fill in the form to make one, or click "
                                  "Add / Copy built-in…."))
        left.addWidget(self.empty)
        btns = QHBoxLayout()
        self.b_add = QPushButton(_("Add"))
        self.b_add.clicked.connect(self.add)
        self.b_copy = QPushButton(_("Copy built-in…"))
        self.b_copy.setToolTip(_("Start from one of the measured modes"))
        self.b_copy.clicked.connect(self.copy_builtin)
        self.b_del = QPushButton(_("Remove"))
        self.b_del.clicked.connect(self.remove)
        for b in (self.b_add, self.b_copy, self.b_del):
            b.setObjectName("small")
            btns.addWidget(b)
        left.addLayout(btns)
        self.undo_bar = UndoBar(_("Put the mode back, as it was"))
        left.addWidget(self.undo_bar)
        body.addLayout(left, 1)

        self.form_box = QWidget()
        form = QFormLayout(self.form_box)
        form.setLabelAlignment(Qt.AlignRight)
        self.name = QLineEdit()
        self.name.setMaxLength(40)
        self.name.textEdited.connect(self._edited)
        form.addRow(_("Name"), self.name)
        self.ceiling = QComboBox()
        for hz in CEILINGS:
            self.ceiling.addItem(ceiling_label(hz), hz)
        self.ceiling.currentIndexChanged.connect(self._edited)
        form.addRow(_("Frequencies"), self.ceiling)
        self.bass, bass_row = self._slider(_("sub-bass turned into harmonics the codec keeps"))
        form.addRow(_("Sub-bass"), bass_row)
        self.lowcut = QComboBox()
        for hz in LOWCUTS:
            self.lowcut.addItem(lowcut_label(hz), hz)
        self.lowcut.setToolTip(_("The chat throws the deepest bass away anyway. Cutting it here "
                                 "stops it pulling the whole sound down in the limiter, and each "
                                 "sound is turned back up by what the cut took from it"))
        self.lowcut.currentIndexChanged.connect(self._edited)
        form.addRow(_("Deep bass"), self.lowcut)
        self.comp, comp_row = self._slider(
            _("evens the level out for the service's gate / auto gain"))
        form.addRow(_("Compressor"), comp_row)
        self.mono = QCheckBox(_("Mono (the service captures a mono mic)"))
        self.mono.toggled.connect(self._edited)
        form.addRow("", self.mono)
        self.note = QLineEdit()
        self.note.setMaxLength(200)
        self.note.setPlaceholderText(_("e.g. Mumble at 72 kbps, TeamSpeak…"))
        self.note.textEdited.connect(self._edited)
        form.addRow(_("Notes"), self.note)
        no_wheel(self.ceiling, self.lowcut, self.bass, self.comp)
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
        # The form is always usable: with no mode picked, the first edit makes one
        # (a disabled form looked the same and just ignored clicks and typing).
        ok = 0 <= row < len(self.items)
        self.b_del.setEnabled(ok)
        self.empty.setVisible(not self.items)
        d = Dest.from_dict(self.items[row]) if ok else Dest("", "", 0, 0.5, 0.4, True)
        self._loading = True
        self.name.setText(d.label)
        self.ceiling.setCurrentIndex(max(0, self.ceiling.findData(d.ceiling)))
        if self.ceiling.findData(d.ceiling) < 0:      # a hand-edited value: keep it
            self.ceiling.insertItem(1, ceiling_label(d.ceiling), d.ceiling)
            self.ceiling.setCurrentIndex(1)
        self.bass.setValue(round(d.bass * 100))
        self.lowcut.setCurrentIndex(max(0, self.lowcut.findData(d.lowcut)))
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
        self.items.append(Dest(self._new_key(), _("My mode {n}", n=len(self.items) + 1), 0,
                               0.5, 0.4, True).to_dict())
        self._fill(len(self.items) - 1)
        self._commit()
        self.name.setFocus()
        self.name.selectAll()

    def copy_builtin(self):
        from PySide6.QtWidgets import QInputDialog
        modes = [d for d in destination.BUILTIN if d.active]
        names = [d.label for d in modes]
        pick, ok = QInputDialog.getItem(self, _("Copy a built-in mode"), _("Start from"), names,
                                        0, False)
        if not ok or pick not in names:
            return
        src = modes[names.index(pick)]   # by place: the shown label may be translated
        raw = src.to_dict()
        raw.update(key=self._new_key(), label=_("{label} (copy)", label=src.label))
        self.items.append(raw)
        self._fill(len(self.items) - 1)
        self._commit()

    def remove(self):
        row = self.list.currentRow()
        if not (0 <= row < len(self.items)):
            return
        gone = self.items.pop(row)
        cfg = self.mw.cfg.dest
        was_on = cfg.get("mode") == gone.get("key")
        if was_on:
            cfg["mode"] = "off"
        self._fill(row)
        self._commit()
        name = gone.get("label") or _("mode")
        self.undo_bar.show_for(
            _("Removed “{name}”: Who's listening is Off now", name=name) if was_on
            else _("Removed “{name}”", name=name),
            lambda: self._put_back(row, gone, was_on))

    def _put_back(self, row: int, raw: dict, was_on: bool):
        if raw.get("key") in {d.get("key") for d in self.items}:
            return
        row = min(row, len(self.items))
        self.items.insert(row, raw)
        if was_on and self.mw.cfg.dest.get("mode") == "off":
            self.mw.cfg.dest["mode"] = raw.get("key")
        self._fill(row)
        self._commit()

    # ------------------------------------------------------------------ edits
    def _edited(self, *__):
        if self._loading:
            return
        row = self.list.currentRow()
        if not (0 <= row < len(self.items)):       # nothing picked: this edit makes a mode
            self.items.append(Dest(self._new_key(), "", 0, 0.5, 0.4, True).to_dict())
            row = len(self.items) - 1
            self.list.blockSignals(True)
            self.list.addItem("")
            self.list.setCurrentRow(row)
            self.list.blockSignals(False)
            self.b_del.setEnabled(True)
            self.empty.setVisible(False)
        raw = self.items[row]
        raw.update(label=self.name.text().strip() or _("My mode {n}", n=row + 1),
                   ceiling=int(self.ceiling.currentData() or 0),
                   bass=self.bass.value() / 100, comp=self.comp.value() / 100,
                   lowcut=int(self.lowcut.currentData() or 0),
                   mono=self.mono.isChecked(), note=self.note.text().strip())
        item = self.list.item(row)
        if item is not None and item.text() != raw["label"]:
            item.setText(raw["label"])
        self._commit()

    def _commit(self):
        destination.apply(self.mw.cfg, self.mw.engine)   # picks up edits to the mode in use
        self.mw._save_later()
        self.changed.emit()
