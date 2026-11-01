"""The Voice tab's AI voices card: pick a character and talk.

The add-on (modules/ai-voices) does the converting in its own process; this card
installs it, starts and stops it (soundboard.speech.aivoice) and shows how it's
doing. It looks and works as the voice changer's card: the same big ON/OFF switch
next to its name, the same picture cards (or list) under chips: All (a heading per kind),
Favorites, Men, Women, In between & fun, Mine. Picking one turns it on, and the voice
that's on gets the same bar under the cards: Edit voice (its pitch), Make your own
voice (ui/voice/aivoicebrowser.py), Hear it. Settings
are a plain dict (`changed`) the Voice tab keeps in the speech settings under "ai".
Its methods live in three mixins beside it: `aivoicecards` (the voice cards and the
voice bar), `aivoicemine` (your own voices, pitch, the backup voice) and `aivoicerun`
(settings, start / stop, the helper's events).
"""
from __future__ import annotations

import html
import json
import logging
import re
import threading

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (QBoxLayout, QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSlider, QVBoxLayout,
                               QWidget)

from soundboard.addons import aiaddon
from soundboard.core import applog, errors, updates, usage
from soundboard.online import net
from soundboard.addons import modules as mods
from soundboard.i18n import _
from soundboard.speech import aivoice
from soundboard.speech import aivoicelist as avl
from soundboard.ui.kit import busy, icons
from soundboard.ui.voice.aivoicebrowser import Previewer, hear_button
from soundboard.ui.bun.bunnywidget import BunnyWidget
from soundboard.ui.kit.glowbutton import GlowButton
from soundboard.ui.kit.panel import (Flow, UndoBar, ViewToggle, fold_button, hint_label,
                                     section_label)
from soundboard.ui.voice.groupbar import GroupBar
from soundboard.ui.voice.voicefxpanel import PICKED_ART, TILE_ART, TILE_GAP, BigSwitch, VoiceTile
from soundboard.ui.kit.widgets import LoadingBar
from soundboard.ui.kit.wheelguard import no_wheel
# the card's parts (callers import their names from here too)
from soundboard.ui.voice.aivoicecards import (ALL, FAVS, KINDS, KIND_ICONS, MAKE,  # noqa: F401
                                              MINE, AiVoiceCards, EditPopup,
                                              art_key, emoji_icon, voice_icon,
                                              voice_kind)
from soundboard.ui.voice.aivoicemine import AiVoiceMine
from soundboard.ui.voice.aivoicerun import BACKUP_HEARD, LOAD_TIMEOUT_MS, AiVoiceRun  # noqa: F401

log = logging.getLogger(__name__)

BACKUP_LABELS = [(_("A built-in voice (still hides yours)"), "voice"),
                 (_("My real voice"), "mic"), (_("Silence"), "mute")]


def read_voices(module: mods.ModuleInfo | None,
                mine: list[dict] | None = None) -> list[dict]:
    """The add-on's voices.json "voices" (id, name, description, emoji…), first brought
    up to date with the app's built-in voices and your own (`mine`, else read from
    your file) when it's the installed copy (aivoicelist.sync); [] if unreadable."""
    if module is None:
        return []
    try:
        voices = avl.sync(module.path, avl.Store().voices if mine is None else mine,
                          aiaddon.removable(module))
        if voices:
            return voices
        data = json.loads((module.path / "voices.json").read_text(encoding="utf-8"))
        return [v for v in data.get("voices", [])
                if isinstance(v, dict) and isinstance(v.get("id"), str) and v.get("name")]
    except (OSError, ValueError, AttributeError):
        return []


def model_downloaded(module: mods.ModuleInfo | None) -> bool:
    return module is not None and all(
        (module.path / "model" / f).is_file()
        for f in ("stream.onnx", "speaker.onnx", "voices.npz"))


def install_step(line: str) -> str | None:
    """What the card says for one line of the add-on's install output: each install
    step's command ("> -m pip install …") becomes a short stage, the voice download's
    percentage updates it, and pip's own chatter is None (the stage stays up)."""
    s = line.strip()
    if s.startswith("> "):
        if " venv " in s + " ":
            return _("Getting Python ready…")
        if " pip " in s:
            return _("Installing the voice engine (a few minutes)…")
        if "--download" in s:
            return _("Downloading the voices…")
        return _("Setting up…")
    m = re.search(r"voice model: (\d+) ?%", s)
    if m:
        return _("Downloading the voices: {percent}%", percent=int(m.group(1)))
    return None


class AiVoicePanel(AiVoiceCards, AiVoiceMine, AiVoiceRun, QWidget):
    changed = Signal(dict)
    live_changed = Signal(bool)
    modules_changed = Signal()      # got or removed the add-on: the Voice tab rescans
    effects_wanted = Signal()       # the bar's Effects: the Voice tab opens the pop-up
    hotkey_asked = Signal(str)      # right-click a card -> Set a hotkey: the voice's id
    hotkey_cleared = Signal(str)
    voices_changed = Signal()       # the voices were read again: their hotkeys may be live now
    _event = Signal(dict)
    _install_line = Signal(str)     # a raw line of the install's output
    _install_note = Signal(str)     # our own words for the card, shown as they are
    _install_done = Signal(bool, str)
    _sampled = Signal(object, object, str)   # a Hear it sample is made (Previewer)

    def __init__(self, controller: aivoice.AiVoiceController, settings: dict | None,
                 module_list: list[mods.ModuleInfo], engine=None):
        super().__init__()
        self.ctl = controller
        self.engine = engine           # for Hear it (None: no samples)
        self.store = avl.Store()       # your own voices
        self.s = aivoice.clean_settings(settings)
        controller.on_event = self._event.emit
        controller.set_backup(self.s["backup"])
        self._event.connect(self._on_event)
        self._install_line.connect(self._on_install_line)
        self._install_note.connect(lambda t: self.lbl_install.setText(t))
        self._last_line = ""            # the install's last output: the error if it fails
        self._install_done.connect(self._on_install_done)
        self._installing = False
        self._voice_name = ""
        self._connected = self._retried = False   # this start's helper (_start_helper)
        self._load_timer = QTimer(self, singleShot=True, interval=LOAD_TIMEOUT_MS)
        self._load_timer.timeout.connect(lambda: self._event.emit({"type": "timeout"}))
        self._status = "off"
        self.module: mods.ModuleInfo | None = None
        self.voices: list[dict] = []
        self.previewer = Previewer(
            self, lambda: self.module if self.module is not None and self.module.installed
            else None, self._play_sample if engine is not None else None)
        self._sampled.connect(lambda b, d, e: self.previewer.done(b, d, e, self._say))

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        self.title = section_label(_("AI voices"))
        v.addWidget(self.title)

        # ---- the big ON/OFF, as the voice changer's: the Voice tab puts `head` right
        # after its card's name. Picking a voice turns it on too
        self.b_start = BigSwitch(_("AI voices"))
        self.b_start.setText(_("Off"))
        self.b_start.toggled.connect(self._toggle)
        self.head = QWidget()
        hh = QHBoxLayout(self.head)
        hh.setContentsMargins(0, 0, 0, 0)
        hh.addWidget(self.b_start)
        self.intro = hint_label(_("Your words and tone, a different voice. Live on this PC."))
        self.intro.setToolTip(_("Talk, and others hear a different person: your words and "
                                 "tone, another voice, live. It runs on this PC (about one "
                                 "CPU core while you talk, nothing while you're quiet); what "
                                 "you say never leaves it."))
        v.addWidget(self.intro)
        # how it's doing while it's on (starting, who you sound like, a failure); empty
        # and hidden while it's off
        self.lbl_state = hint_label("")
        self.lbl_state.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_state.setMinimumWidth(0)
        self.lbl_state.hide()
        v.addWidget(self.lbl_state)

        self.ready_box = QWidget()
        rv = QVBoxLayout(self.ready_box)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(12)

        # ---- which voices show: All (a heading per kind), your favorites, one kind;
        # cards or a list at the right (the voice changer's switch, the same setting)
        favs = self.s.pop("favorites", None)   # kept here, added back by _emit
        self._favs: list[str] = list(favs) if isinstance(favs, list) else []
        self._group = ALL
        self._listed = False
        self.view_toggle = ViewToggle("grid", _("Voices"))
        self.view_toggle.changed.connect(self.set_view)
        self.bar = GroupBar(
            [(ALL, _("All"), "sounds"), (FAVS, _("Favorites"), "star_filled"),
             *((k, t, KIND_ICONS[k]) for k, t in KINDS)],
            self.view_toggle, self._group_count,
            (_("Search AI voices"), _("Search")), _("Which voices show"))
        self.bar.picked.connect(lambda k: (usage.used("ai-voice-group"), self.show_group(k)))
        self.bar.searched.connect(lambda _t: self._place_tiles())
        rv.addWidget(self.bar)
        self._heads: dict[str, QLabel] = {}
        for key, text in KINDS:
            lbl = QLabel(text)
            lbl.setObjectName("fxgroup")
            lbl.hide()
            self._heads[key] = lbl
        self.no_favs = hint_label(_("No favorites yet. Click the star in a voice's corner "
                                    "to keep it here."))
        self.no_favs.hide()
        self.no_match = hint_label("")
        self.no_match.hide()

        # ---- pick a voice: a card each, as many a row as the width holds; under Mine,
        # after your own, a card that makes one (as the voice changer's My own mix)
        self._tile_grid = QGridLayout()
        self._tile_grid.setSpacing(TILE_GAP)
        self._tile_cols = 3
        self.tiles = QButtonGroup(self)
        self.tiles.setExclusive(True)
        self._tile: dict[str, VoiceTile] = {}
        mt = self.make_tile = VoiceTile(_("Make your own voice"))
        mt.setCheckable(False)
        mt.star.hide()
        mt.setIcon(icons.icon("plus", "muted"))
        mt.setIconSize(QSize(TILE_ART, TILE_ART))
        mt.setCursor(Qt.CursorShape.PointingHandCursor)
        mt.clicked.connect(lambda: self.edit(None))
        rv.addLayout(self._tile_grid)
        rv.addWidget(self.no_favs)
        rv.addWidget(self.no_match)
        self.undo_bar = UndoBar(_("Bring the voice back"))
        rv.addWidget(self.undo_bar)
        self.lbl_sample = QLabel("")
        self.lbl_sample.setObjectName("muted")
        self.lbl_sample.setWordWrap(True)
        self.lbl_sample.hide()
        rv.addWidget(self.lbl_sample)
        v.addWidget(self.ready_box)

        # ---- the voice that's on: a bar like the voice changer's (the Voice tab pins it
        # under its scrolling cards). Its picture and name, then Edit voice (the pitch),
        # the same as the voice changer's bar. Make your own voice is the + card under
        # Mine; Hear it, change and delete are on a card's right-click (kept here,
        # hidden, for what they do)
        self.picked = QFrame()
        self.picked.setObjectName("picked")
        self.picked_box = QBoxLayout(QBoxLayout.Direction.LeftToRight, self.picked)
        self.picked_box.setContentsMargins(12, 8, 12, 8)
        self.picked_box.setSpacing(10)
        ph = QHBoxLayout()
        ph.setSpacing(10)
        self.picked_box.addLayout(ph)
        self.picked_pic = QLabel()
        self.picked_pic.setFixedSize(PICKED_ART, PICKED_ART)
        ph.addWidget(self.picked_pic)
        self.picked_name = QLabel()
        self.picked_name.setObjectName("pickedname")
        self.picked_name.setTextFormat(Qt.TextFormat.PlainText)
        self.picked_name.setWordWrap(True)
        self.picked_name.setMinimumWidth(40)   # a long name gives way in a narrow window
        ph.addWidget(self.picked_name)
        # which kind of voice it is, after its name (Robot alone didn't say)
        self.picked_kind = QLabel(_("(AI voice)"))
        self.picked_kind.setObjectName("pickedkind")
        ph.addWidget(self.picked_kind)
        for lbl in (self.picked_name, self.picked_kind):   # no wider than their words:
            # the kind stays by the name, on a line of its own too (narrow)
            lbl.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self._picked_btns = QWidget()
        bflow = Flow(self._picked_btns, gap=10)
        self.picked_box.addWidget(self._picked_btns, 1)   # right after the name
        # what's on top of the voice: the voice changer's Effects pop-up, the same
        # things (one list for both bars; they play on the AI voice too)
        self.btn_effects = QPushButton(_("Effects"))
        icons.set_icon(self.btn_effects, "sounds")
        self.btn_effects.setToolTip(_("Rain, a crowd, an echo or sounds from your board, on "
                                      "top of any voice"))
        self.btn_effects.clicked.connect(lambda: self.effects_wanted.emit())
        bflow.addWidget(self.btn_effects)   # first, as on the voice changer's bar
        self.btn_tweak = QPushButton(_("Edit voice"))
        icons.set_icon(self.btn_tweak, "sliders")
        self.btn_tweak.clicked.connect(lambda: self.open_tweak())
        bflow.addWidget(self.btn_tweak)
        self.b_make = QPushButton(_("Make your own voice"))
        icons.set_icon(self.b_make, "plus")
        self.b_make.clicked.connect(lambda: self.edit(None))
        self.b_hear = hear_button()
        self.b_hear.clicked.connect(lambda: (usage.used("ai-voice-hear"), self.previewer.hear(
            self.b_hear, self._voice(), self._sampled, self._say)))
        self.b_edit = QPushButton()
        icons.set_icon(self.b_edit, "edit")
        self.b_edit.setToolTip(_("Change this voice"))
        self.b_edit.setAccessibleName(_("Change this voice"))
        self.b_edit.clicked.connect(lambda: self.edit(self.s["voice"]))
        self.b_delete = QPushButton()
        icons.set_icon(self.b_delete, "trash", "danger_text")
        self.b_delete.setToolTip(_("Delete this voice (you can bring it back)"))
        self.b_delete.setAccessibleName(_("Delete this voice (you can bring it back)"))
        self.b_delete.clicked.connect(lambda: self.delete(self.s["voice"]))
        for b in (self.b_make, self.b_hear, self.b_edit, self.b_delete):
            b.setParent(self.picked)   # (a parent: never a window of its own)
            b.hide()
        self.b_bin = QPushButton("")
        self.b_bin.setObjectName("fold")
        icons.set_icon(self.b_bin, "trash", "muted", "text", size=12)
        self.b_bin.clicked.connect(self.show_deleted)
        bflow.addWidget(self.b_bin)
        v.addWidget(self.picked)
        self.picked.installEventFilter(self)   # (after its buttons: _fit_picked reads them)
        self.picked.hide()                     # (only while it's on: show_picked_row)

        # ---- Edit voice's pop-up: how high (made with the panel, placed in the pop-up
        # the first time it opens)
        self.pitch_box = QWidget(self)
        grid = QGridLayout(self.pitch_box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.addWidget(section_label(_("Pitch")), 0, 0)
        prow = QHBoxLayout()
        self.chk_auto = QCheckBox(_("Match the voice"))
        self.chk_auto.setToolTip(_("Moves your pitch to where this voice naturally sits, "
                                 "whoever is talking. Off: your own pitch."))
        self.chk_auto.setChecked(self.s["auto_pitch"])
        grid.addWidget(self.chk_auto, 0, 1, Qt.AlignmentFlag.AlignRight)
        self.sl_pitch = QSlider(Qt.Orientation.Horizontal)
        self.sl_pitch.setRange(-24, 24)            # half semitones
        self.sl_pitch.setValue(int(round(self.s["pitch"] * 2)))
        self.sl_pitch.setMinimumHeight(28)
        self.sl_pitch.setToolTip(_("Higher or lower than that, in semitones"))
        prow.addWidget(self.sl_pitch, 1)
        self.lbl_pitch = QLabel("")
        self.lbl_pitch.setMinimumWidth(38)
        self.lbl_pitch.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        prow.addWidget(self.lbl_pitch)
        grid.addLayout(prow, 1, 0, 1, 2)
        grid.setColumnStretch(1, 1)
        self.pitch_box.hide()
        self.tweak_pop: EditPopup | None = None
        self.keys: dict[str, str] = {}   # voice id -> its hotkey (the window fills it in)

        self.missing = QWidget()
        mv = QVBoxLayout(self.missing)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(12)

        setup_row = QHBoxLayout()
        setup_row.setSpacing(16)
        self.bun_robot = BunnyWidget(height=88, pad=14, robot=True)
        setup_row.addWidget(self.bun_robot, 0, Qt.AlignmentFlag.AlignVCenter)

        info = QVBoxLayout()
        info.setSpacing(10)
        # the words, the button and the progress stay together, centred beside Robo-Bun
        # (spread over his height they left a gap between the words and the button)
        info.addStretch(1)
        self.lbl_missing = hint_label("")
        info.addWidget(self.lbl_missing)

        mrow = QHBoxLayout()
        mrow.setSpacing(8)
        self.b_install = GlowButton(_("Install AI voices"))
        icons.set_icon(self.b_install, "plus")
        self.b_install.setToolTip(_("One-time download, about 90 MB."))
        self.b_install.clicked.connect(self._install)
        mrow.addWidget(self.b_install)
        self.b_get = GlowButton(_("Get AI voices"))
        icons.set_icon(self.b_get, "plus")
        self.b_get.setToolTip(_("An optional add-on: about 55 MB, from this project's GitHub "
                                "page."))
        self.b_get.clicked.connect(self._get)
        mrow.addWidget(self.b_get)
        mrow.addStretch(1)
        info.addLayout(mrow)

        self.lbl_install = hint_label("")
        self.lbl_install.hide()
        info.addWidget(self.lbl_install)

        self.loading_bar = LoadingBar()
        self.loading_bar.hide()
        info.addWidget(self.loading_bar)
        info.addStretch(1)

        setup_row.addLayout(info, 1)
        # Robo-Bun and the install, in their own inner area
        setup = QFrame()
        setup.setObjectName("voicebox")
        setup_row.setContentsMargins(8, 8, 16, 8)
        setup.setLayout(setup_row)
        mv.addWidget(setup)
        v.addWidget(self.missing)

        # ---- the add-on itself: what covers you if it stops, update, remove (there
        # whether it's on or off: it's removed only while off)
        self.btn_opts = fold_button(_("More options"))
        v.addWidget(self.btn_opts, 0, Qt.AlignmentFlag.AlignLeft)
        self.opts = QWidget()
        ov = QVBoxLayout(self.opts)
        ov.setContentsMargins(0, 0, 0, 0)
        ov.setSpacing(10)
        brow = QHBoxLayout()
        brow.setSpacing(12)
        brow.addWidget(QLabel(_("If the AI voice stops")))
        self.cb_backup = QComboBox()
        for label, key in BACKUP_LABELS:
            self.cb_backup.addItem(label, key)
        self.cb_backup.setCurrentIndex(max(0, self.cb_backup.findData(self.s["backup"])))
        self.cb_backup.setToolTip(_("What others hear if the AI voice crashes or can't keep "
                                    "up: by default a built-in voice changer preset, so your "
                                    "real voice still isn't heard."))
        self.cb_backup.setMaximumWidth(360)
        brow.addWidget(self.cb_backup, 1)
        brow.addStretch(1)
        ov.addLayout(brow)
        self.b_update = QPushButton(_("Update AI voices"))
        self.b_update.setToolTip(_("Runs its install again (and fetches the voice model if "
                                   "it's missing)."))
        self.b_update.clicked.connect(self._install)
        urow = QHBoxLayout()
        urow.setSpacing(8)
        urow.addWidget(self.b_update)
        self.b_remove = QPushButton(_("Remove AI voices"))
        self.b_remove.setToolTip(_("Deletes the add-on, its voice model and its Python "
                                   "environment from this PC. Get it again any time."))
        self.b_remove.clicked.connect(self._remove)
        urow.addWidget(self.b_remove)
        urow.addStretch(1)
        ov.addLayout(urow)
        self.lbl_credits = hint_label("")
        ov.addWidget(self.lbl_credits)
        v.addWidget(self.opts)
        self.opts.hide()
        self.btn_opts.toggled.connect(self.opts.setVisible)
        no_wheel(self.sl_pitch, self.cb_backup)

        self.chk_auto.toggled.connect(self._auto_toggled)
        self.sl_pitch.valueChanged.connect(self._pitch_moved)
        self.sl_pitch.sliderReleased.connect(self._pitch_released)
        self.cb_backup.currentIndexChanged.connect(self._backup_picked)
        self._show_pitch()
        self.set_modules(module_list)

    # ------------------------------------------------------------ modules
    def set_modules(self, module_list: list[mods.ModuleInfo], voices: list[dict] | None = None):
        """`voices`: the add-on's read_voices(), when a worker already read them."""
        self.module = next((m for m in module_list
                            if m.id == aivoice.MODULE_ID and not m.error), None)
        self.voices = read_voices(self.module) if voices is None else voices
        self._fill_tiles()
        self.voices_changed.emit()
        self.lbl_credits.setText(self.module.credits if self.module else "")
        self._refresh()

    def ready(self) -> bool:
        """Installed, its model downloaded and its voices there: it works offline."""
        m = self.module
        return m is not None and m.installed and model_downloaded(m) and bool(self.voices)

    def _refresh(self):
        m = self.module
        ok = m is not None and m.installed and model_downloaded(m) and bool(self.voices)
        if self._installing:
            self.ready_box.setVisible(False)
            self.missing.setVisible(True)
        else:
            self.ready_box.setVisible(ok)
            self.missing.setVisible(not ok)
        self.b_install.setVisible(m is not None and not ok)
        self.b_get.setVisible(m is None)
        self.b_update.setVisible(m is not None)
        # a copy that came with the app too, once there's something of it to delete
        self.b_remove.setVisible(m is not None and (aiaddon.removable(m) or m.installed
                                                    or model_downloaded(m)))
        self.btn_opts.setVisible(m is not None and not self._installing)
        if net.offline():   # Offline mode: nothing here can be fetched (the card goes
            for b in (self.b_get, self.b_install, self.b_update):   # when not ready)
                b.hide()
        if m is None:
            self.opts.hide()
            self.btn_opts.setChecked(False)
            self.lbl_missing.setText(_(
                "AI voices are an optional add-on (about 55 MB, the voice model and its "
                "runtime). Nothing is downloaded until you press Get AI voices."))
        elif m.broken:   # the Python they were set up with is gone (soundboard.online.pyget)
            self.lbl_missing.setText(_("AI voices stopped working: the Python they were set "
                                       "up with is gone from this PC. Press Repair to set "
                                       "them up again."))
        elif not ok:
            self.lbl_missing.setText(_("AI voices need a one-time install first: about 90 MB "
                                       "(the voice model and its runtime)."))
        if not self._installing:
            fix = m is not None and m.broken
            self.b_install.setText(_("Repair") if fix else _("Install AI voices"))
            icons.set_icon(self.b_install, "reload" if fix else "plus")
        can_make = self.can_make()
        tip = (_("Blend two voices and set how deep and how high it is") if can_make else
               _("Only for AI voices installed with the Get AI voices button"))
        for b in (self.b_make, self.make_tile):
            b.setEnabled(can_make)
            b.setToolTip(tip)
        # the switch works once the voices are here; till then the card says what's
        # missing (and it's off: nothing to start)
        usable = (ok and not self._installing) or self.is_on()
        self.b_start.setEnabled(usable)
        self.b_start.setToolTip("" if usable else self.lbl_missing.text())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # only a new width: fewer cards a row makes it taller, and refitting on that
        # can flip it back and forth
        if e.size().width() != e.oldSize().width():
            self._fit_width(self.width())

    def eventFilter(self, obj, e):
        if obj is self.picked and e.type() == QEvent.Type.Resize:
            self._fit_picked()
        return super().eventFilter(obj, e)

    def _resync(self):
        """Your own voices changed: write them into the add-on and list them again."""
        old = self.s["voice"]
        self.voices = read_voices(self.module, self.store.voices)
        self._favs = [i for i in self._favs if any(vo["id"] == i for vo in self.voices)]
        self._fill_tiles()
        self.voices_changed.emit()
        if self.current_voice() != old:     # it was deleted: the first one instead
            self.pick(self.current_voice())
        self._emit()

    # ------------------------------------------------------------ get / remove
    def _get(self):
        if self._installing:
            return
        self._installing = True
        busy.set_busy(self.b_get, True)
        self.b_get.setText(_("Getting AI voices…"))
        self._last_line = ""
        self._refresh()
        self.bun_robot.build()
        self.lbl_install.show()
        self.lbl_install.setText(_("asking GitHub for the add-on…"))
        self.loading_bar.show()
        self.loading_bar.start()

        def progress(done: int, total: int):
            if total:
                busy.emit(self._install_note, _("downloading: {percent}% of {size} MB",
                                                percent=done * 100 // total,
                                                size=f"{total / 1e6:.0f}"))

        def work():
            try:
                offer = aiaddon.latest()
                if offer is None:
                    raise mods.ModuleError(_("there's no AI voices add-on to download yet"))
                info = aiaddon.install(aiaddon.fetch(offer, progress))
                busy.emit(self._install_note,
                          _("setting up its Python environment (a few minutes)…"))
                ok = mods.install(info, lambda line: busy.emit(self._install_line, line),
                                  on_note=lambda t: busy.emit(self._install_note, t))
                busy.emit(self._install_done, ok, "")
            except Exception as e:  # noqa: BLE001 - the button must come back
                # a bug: report it. A download that failed (offline, the connection
                # dropped: UpdateError) is said on the tab, not reported as a crash
                if not isinstance(e, (mods.ModuleError, OSError, updates.UpdateError)):
                    applog.report(where="AI voices download")
                busy.emit(self._install_done, False, aiaddon.friendly(e))

        threading.Thread(target=work, name="ai-voices-get", daemon=True).start()

    def _remove(self):
        m = self.module
        if m is None or self.ctl.running or self._installing:
            return

        def go():
            aiaddon.remove(m)

        def done(_r=None):
            self.modules_changed.emit()
            busy.toast(self, _("AI voices are removed."), "ok")

        busy.run_busy(self.b_remove, _("Removing…"), go, done)

    # ------------------------------------------------------------ install
    def _install(self):
        m = self.module
        if m is None or self._installing:
            return
        self._installing = True
        self._refresh()
        for b in (self.b_install, self.b_update):
            busy.set_busy(b, True)
        self.b_install.setText(_("Installing… (a few minutes)"))
        self._last_line = ""
        self.bun_robot.build()
        self.lbl_install.show()
        self.lbl_install.setText(_("starting…"))
        self.loading_bar.show()
        self.loading_bar.start()

        def work():
            try:
                ok = mods.install(m, lambda line: busy.emit(self._install_line, line),
                                  on_note=lambda t: busy.emit(self._install_note, t))
                busy.emit(self._install_done, ok, "")
            except Exception as e:  # noqa: BLE001 - the buttons must come back
                if not isinstance(e, (mods.ModuleError, OSError)):   # a bug: report it
                    applog.report(where="module install")
                busy.emit(self._install_done, False, errors.plain(e))

        threading.Thread(target=work, name="ai-voices-install", daemon=True).start()

    def _on_install_line(self, t: str):
        """Robo-Bun does the work on screen: the card shows the stage, not pip's output,
        and keeps the last line in case it's the error."""
        self._last_line = t
        step = install_step(t)
        if step:
            self.lbl_install.setText(step)

    def _on_install_done(self, ok: bool, err: str = ""):
        self._installing = False
        for b in (self.b_install, self.b_update, self.b_get):
            busy.set_busy(b, False)
        self.b_update.setEnabled(not self.ctl.running)
        self.b_install.setText(_("Install AI voices"))
        self.b_get.setText(_("Get AI voices"))
        self.loading_bar.stop()
        self.loading_bar.hide()
        self.bun_robot.stop_building(ok)
        if ok:
            self.lbl_install.hide()
            self.modules_changed.emit()     # a fresh download is a new module folder
            self._refresh()
            busy.toast(self, _("AI voices are installed. Pick a voice to turn it on."), "ok")
        else:
            self._refresh()                 # the buttons come back to try again
            last = self.lbl_install.text()
            self.lbl_install.hide()
            busy.toast(self, html.escape(_(
                "⚠ Install failed: {error}. Press it again to retry; if it keeps failing, "
                "run install.bat in the add-on's folder to see why.",
                error=err or self._last_line[-160:] or last).removeprefix("⚠ ")), "error")

    def shutdown(self):
        self._load_timer.stop()
        self.ctl.shutdown()
