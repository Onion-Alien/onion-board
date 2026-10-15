"""The Voice tab's AI voices card: pick a character, press Start, talk.

The add-on (modules/ai-voices) does the converting in its own process; this card
installs it, starts and stops it (soundboard.speech.aivoice) and shows how it's
doing. The voices are picture cards under chips, like the voice changer's: All (a
heading per kind), Favorites, Men, Women, In between & fun, Mine. Under them the
picked voice, with Hear it and Make your own voice (ui/aivoicebrowser.py). Settings
are a plain dict (`changed`) the Voice tab keeps in the speech settings under "ai".
"""
from __future__ import annotations

import html
import json
import logging
import re
import threading

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QMenu, QPushButton,
                               QSlider, QVBoxLayout, QWidget)

from soundboard import aiaddon, applog, errors, net, updates
from soundboard import modules as mods
from soundboard.i18n import _, ngettext
from soundboard.speech import aivoice
from soundboard.speech import aivoicelist as avl
from soundboard.ui import busy, icons
from soundboard.ui.aivoicebrowser import AiVoiceEditor, Previewer, hear_button
from soundboard.ui.bunnywidget import BunnyWidget
from soundboard.ui.panel import Flow, UndoBar, fold_button, hint_label, section_label
from soundboard.ui.voicefxpanel import (MAX_COLS, PICKED_ART, TILE_ART, TILE_GAP,
                                        TILE_MIN_W, VoiceTile)
from soundboard.ui.widgets import LoadingBar
from soundboard.wheelguard import no_wheel

log = logging.getLogger(__name__)

IDLE = _("Ready")
BACKUP_LABELS = [(_("A built-in voice (still hides yours)"), "voice"),
                 (_("My real voice"), "mic"), (_("Silence"), "mute")]
# what others hear once the AI voice has stopped, by backup key ("Others now hear …")
BACKUP_HEARD = {"voice": _("a built-in voice (still hides yours)"),
                "mic": _("your real voice"), "mute": _("silence")}

# the chips over the voice cards: All shows a heading per kind (avl.who), your own last
ALL, FAVS, MINE = "", "favs", "mine"
KINDS = (("men", _("Men")), ("women", _("Women")), ("other", _("In between & fun")),
         (MINE, _("Mine")))


def voice_kind(voice: dict) -> str:
    """The heading a voice card goes under: yours under Mine, else who it sounds like."""
    return MINE if avl.is_mine(voice) else avl.who(voice)


def emoji_icon(emoji: str, size: int = TILE_ART) -> QIcon:
    """A voice's emoji as a card picture (the AI voices have emoji, not drawings)."""
    pm = QPixmap(size * 2, size * 2)   # drawn at 2x: sharp on a high-DPI screen too
    pm.setDevicePixelRatio(2.0)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    f = QFont("Segoe UI Emoji")
    f.setPixelSize(int(size * 0.8))
    p.setFont(f)
    p.drawText(0, 0, size, size, Qt.AlignmentFlag.AlignCenter, emoji or "🎙️")
    p.end()
    return QIcon(pm)


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


BOX_MAX_W = 560   # px: the pitch box at its widest


class AiVoicePanel(QWidget):
    changed = Signal(dict)
    live_changed = Signal(bool)
    modules_changed = Signal()      # got or removed the add-on: the Voice tab rescans
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
        self.intro = hint_label(_("Your words and tone, a different voice. Live on this PC."))
        self.intro.setToolTip(_("Talk, and others hear a different person: your words and "
                                 "tone, another voice, live. It runs on this PC (about one "
                                 "CPU core while you talk, nothing while you're quiet); what "
                                 "you say never leaves it."))

        self.ready_box = QWidget()
        rv = QVBoxLayout(self.ready_box)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(12)
        action = QHBoxLayout()
        action.setSpacing(14)
        self.b_start = QPushButton(_("Start AI voice"))
        icons.set_icon(self.b_start, "mic", "on_accent", "on_accent")
        self.b_start.setCheckable(True)
        self.b_start.setMinimumHeight(40)
        self.b_start.setObjectName("primary")
        self.b_start.toggled.connect(self._toggle)
        action.addWidget(self.b_start, 0, Qt.AlignmentFlag.AlignTop)
        self.lbl_state = QLabel(IDLE)
        self.lbl_state.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_state.setObjectName("muted")
        self.lbl_state.setWordWrap(True)
        self.lbl_state.setMinimumWidth(0)
        action.addWidget(self.lbl_state, 1)
        rv.addLayout(action)
        rv.addWidget(self.intro)

        # ---- which voices show: All (a heading per kind), your favorites, one kind
        favs = self.s.pop("favorites", None)   # kept here, added back by _emit
        self._favs: list[str] = list(favs) if isinstance(favs, list) else []
        self._group = ALL
        self.cats = QWidget()
        cflow = Flow(self.cats, gap=6)
        self._cat_group = QButtonGroup(self)
        self._cat_btns: dict[str, QPushButton] = {}
        for key, text in ((ALL, _("All")), (FAVS, _("Favorites")), *KINDS):
            b = QPushButton(text.replace("&", "&&"))
            b.setObjectName("voicecat")
            b.setAccessibleName(text)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if key == FAVS:
                icons.set_icon(b, "star_filled", "accent")
            b.clicked.connect(lambda __=False, k=key: self.show_group(k))
            self._cat_group.addButton(b)
            self._cat_btns[key] = b
            cflow.addWidget(b)
        self._cat_btns[ALL].setChecked(True)
        rv.addWidget(self.cats)
        self._heads: dict[str, QLabel] = {}
        for key, text in KINDS:
            lbl = QLabel(text)
            lbl.setObjectName("fxgroup")
            lbl.hide()
            self._heads[key] = lbl
        self.no_favs = hint_label(_("No favorites yet. Click the star in a voice's corner "
                                    "to keep it here."))
        self.no_favs.hide()
        self.no_mine = hint_label(_("No voices of your own yet: press Make your own voice "
                                    "below."))
        self.no_mine.hide()

        # ---- pick a voice: a card each, as many a row as the width holds
        self._tile_grid = QGridLayout()
        self._tile_grid.setSpacing(TILE_GAP)
        self._tile_cols = 3
        self.tiles = QButtonGroup(self)
        self.tiles.setExclusive(True)
        self._tile: dict[str, VoiceTile] = {}
        rv.addLayout(self._tile_grid)
        rv.addWidget(self.no_favs)
        rv.addWidget(self.no_mine)
        self.undo_bar = UndoBar(_("Bring the voice back"))
        rv.addWidget(self.undo_bar)

        # ---- the voice you picked: what it is; under that Hear it, Make your own voice
        # (and change or delete it, one of yours), on a line of their own
        self.picked = QFrame()
        self.picked.setObjectName("picked")
        pv = QVBoxLayout(self.picked)
        pv.setContentsMargins(12, 8, 12, 10)
        pv.setSpacing(8)
        ph = QHBoxLayout()
        ph.setSpacing(10)
        pv.addLayout(ph)
        self.picked_pic = QLabel()
        self.picked_pic.setFixedSize(PICKED_ART, PICKED_ART)
        ph.addWidget(self.picked_pic, 0, Qt.AlignmentFlag.AlignTop)
        words = QVBoxLayout()
        words.setSpacing(2)
        self.picked_name = QLabel()
        self.picked_name.setObjectName("pickedname")
        self.picked_name.setTextFormat(Qt.TextFormat.PlainText)
        self.picked_name.setMinimumWidth(40)   # a long name gives way in a narrow window
        words.addWidget(self.picked_name)
        self.lbl_about = hint_label("")
        self.lbl_about.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_about.setMinimumWidth(40)
        words.addWidget(self.lbl_about)
        ph.addLayout(words, 1)
        btns = QWidget()
        bflow = Flow(btns, gap=6)
        self.b_hear = hear_button()
        self.b_hear.clicked.connect(lambda: self.previewer.hear(
            self.b_hear, self._voice(), self._sampled, self._say))
        bflow.addWidget(self.b_hear)
        self.b_make = QPushButton(_("Make your own voice"))
        icons.set_icon(self.b_make, "plus")
        self.b_make.clicked.connect(lambda: self.edit(None))
        bflow.addWidget(self.b_make)
        self.b_edit = QPushButton()
        icons.set_icon(self.b_edit, "edit")
        self.b_edit.setToolTip(_("Change this voice"))
        self.b_edit.setAccessibleName(_("Change this voice"))
        self.b_edit.clicked.connect(lambda: self.edit(self.s["voice"]))
        bflow.addWidget(self.b_edit)
        self.b_delete = QPushButton()
        icons.set_icon(self.b_delete, "trash", "danger_text")
        self.b_delete.setToolTip(_("Delete this voice (you can bring it back)"))
        self.b_delete.setAccessibleName(_("Delete this voice (you can bring it back)"))
        self.b_delete.clicked.connect(lambda: self.delete(self.s["voice"]))
        bflow.addWidget(self.b_delete)
        self.b_bin = QPushButton("")
        self.b_bin.setObjectName("fold")
        icons.set_icon(self.b_bin, "trash", "muted", "text", size=12)
        self.b_bin.clicked.connect(self.show_deleted)
        bflow.addWidget(self.b_bin)
        brow = QHBoxLayout()
        brow.addSpacing(PICKED_ART + 10)   # under the name, not the picture
        brow.addWidget(btns, 1)
        pv.addLayout(brow)
        rv.addWidget(self.picked)
        self.lbl_sample = QLabel("")
        self.lbl_sample.setObjectName("muted")
        self.lbl_sample.setWordWrap(True)
        self.lbl_sample.hide()
        rv.addWidget(self.lbl_sample)

        # ---- how high: in its own inner area under the picked voice
        grid = QGridLayout()
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
        box = self.voicebox = QFrame()
        box.setObjectName("voicebox")
        box.setMaximumWidth(BOX_MAX_W)   # a slider, not a bar across the card
        grid.setContentsMargins(14, 4, 14, 14)
        box.setLayout(grid)
        rv.addWidget(box)
        v.addWidget(self.ready_box)

        self.missing = QWidget()
        mv = QVBoxLayout(self.missing)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(12)
        mv.addWidget(hint_label(_("Your words and tone, a different voice. Live on this PC.")))

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
        self.b_install = QPushButton(_("Install AI voices"))
        icons.set_icon(self.b_install, "plus")
        self.b_install.setToolTip(_("One-time download, about 90 MB."))
        self.b_install.clicked.connect(self._install)
        mrow.addWidget(self.b_install)
        self.b_get = QPushButton(_("Get AI voices"))
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
        self.b_remove.setVisible(m is not None and aiaddon.removable(m))
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
        elif m.broken:   # the Python they were set up with is gone (soundboard.pyget)
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
        self.b_make.setEnabled(can_make)
        self.b_make.setToolTip(
            _("Blend two voices and set how deep and how high it is") if can_make else
            _("Only for AI voices installed with the Get AI voices button"))

    # ------------------------------------------------------------ settings
    def _emit(self):
        self.changed.emit({**self.s, **({"favorites": list(self._favs)} if self._favs
                                        else {})})

    def current_voice(self) -> str:
        """The picked voice's id: the saved one if the add-on has it, else its first."""
        ids = [vo["id"] for vo in self.voices]
        return self.s["voice"] if self.s["voice"] in ids else (ids[0] if ids else "")

    def _voice(self) -> dict:
        vid = self.current_voice()
        return next((vo for vo in self.voices if vo["id"] == vid), {})

    def _show_about(self):
        """The bar under the cards: the picked voice, who it sounds like and about it."""
        vo = self._voice()
        tags = avl.tag_line(vo) if vo else ""
        text = str(vo.get("about") or vo.get("description") or "")
        self.picked_name.setText(str(vo.get("name", "")))
        self.picked_pic.setPixmap(emoji_icon(str(vo.get("emoji") or ""), PICKED_ART)
                                  .pixmap(PICKED_ART, PICKED_ART))
        self.lbl_about.setText(f"{tags}. {text}" if tags and text else tags or text)
        mine = avl.is_mine(vo)
        self.b_edit.setVisible(mine and self.can_make())
        self.b_delete.setVisible(mine)
        self.b_hear.setVisible(self.previewer.available())
        n = len(self.store.deleted)
        self.b_bin.setText(_("Recently deleted ({n})", n=n))
        self.b_bin.setVisible(n > 0)
        self.tiles.setExclusive(False)
        for vid, b in self._tile.items():
            b.setChecked(vid == vo.get("id"))
        self.tiles.setExclusive(True)

    def _say(self, text: str):
        self.lbl_sample.setText(text)
        self.lbl_sample.setVisible(bool(text))

    # ------------------------------------------------------------ the voice cards
    def _fill_tiles(self):
        """(Re)make a card for each voice the add-on has."""
        for b in self._tile.values():
            self.tiles.removeButton(b)
            self._tile_grid.removeWidget(b)
            b.hide()   # until it's gone it would paint over the regrown grid
            b.deleteLater()
        self._tile = {}
        for vo in self.voices:
            vid = vo["id"]
            b = VoiceTile(vo["name"])
            b.setIcon(emoji_icon(str(vo.get("emoji") or "")))
            b.setIconSize(QSize(TILE_ART, TILE_ART))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            tags = avl.tag_line(vo)
            about = str(vo.get("about") or vo.get("description") or "")
            b.setToolTip(f"{tags}. {about}" if tags and about else tags or about)
            b.clicked.connect(lambda __=False, i=vid: self.use(i))
            b.star.setChecked(vid in self._favs)
            b.star.toggled.connect(lambda on, i=vid: self.set_favorite(i, on))
            if avl.is_mine(vo):
                b.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                b.customContextMenuRequested.connect(
                    lambda pos, i=vid, w=b: self._mine_menu(i, w.mapToGlobal(pos)))
            self.tiles.addButton(b)
            self._tile[vid] = b
        self._place_tiles()
        self._show_about()

    def _place_tiles(self):
        """The cards the picked chip shows: All under a heading per kind (lowest voice
        first), else one kind (or your favorites, in the order you starred them)."""
        g, cols = self._tile_grid, self._tile_cols
        for w in (*self._tile.values(), *self._heads.values()):
            g.removeWidget(w)
        by_id = {vo["id"]: vo for vo in self.voices if vo["id"] in self._tile}
        low_first = sorted(by_id.values(), key=lambda vo: vo.get("pitch_hz", 0))
        rows: list[tuple[str, list[str]]]
        if self._group == ALL:
            rows = [(k, [vo["id"] for vo in low_first if voice_kind(vo) == k])
                    for k, _t in KINDS]
        elif self._group == FAVS:
            rows = [("", [i for i in self._favs if i in by_id])]
        else:
            rows = [("", [vo["id"] for vo in low_first if voice_kind(vo) == self._group])]
        shown: set[str] = set()
        r = 0
        for head, group in rows:
            if not group:
                continue
            if head:
                g.addWidget(self._heads[head], r, 0, 1, cols)
                r += 1
            for i, vid in enumerate(group):
                g.addWidget(self._tile[vid], r + i // cols, i % cols)
            r += (len(group) + cols - 1) // cols
            shown.update(group)
        for k, lbl in self._heads.items():
            lbl.setVisible(self._group == ALL and any(voice_kind(by_id[i]) == k
                                                      for i in shown))
        for vid, b in self._tile.items():
            b.setVisible(vid in shown)
        self.no_favs.setVisible(self._group == FAVS and not shown)
        self.no_mine.setVisible(self._group == MINE and not shown)
        for c in range(MAX_COLS):
            g.setColumnStretch(c, 1 if c < cols else 0)

    def show_group(self, key: str):
        """Show one chip's voices (ALL, FAVS, MINE or an avl.WHO key)."""
        self._group = key
        self._cat_btns[key].setChecked(True)
        self._place_tiles()

    @property
    def favorites(self) -> list[str]:
        return list(self._favs)

    def set_favorite(self, vid: str, on: bool):
        """Star or unstar a voice: Favorites lists them in the order you starred them."""
        if on == (vid in self._favs):
            return
        if on:
            self._favs.append(vid)
        else:
            self._favs.remove(vid)
        b = self._tile.get(vid)
        if b is not None and b.star.isChecked() != on:
            b.star.setChecked(on)   # (toggled comes back here and finds nothing to do)
        if self._group == FAVS:
            self._place_tiles()
        self._emit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # only a new width: fewer cards a row makes it taller, and refitting on that
        # can flip it back and forth
        if e.size().width() != e.oldSize().width():
            self._fit_width(self.width())

    def _fit_width(self, width: int):
        """As many voice cards a row as the width holds, at least one."""
        cols = max(1, min(MAX_COLS, (width + TILE_GAP) // (TILE_MIN_W + TILE_GAP)))
        if cols != self._tile_cols:
            self._tile_cols = cols
            self._place_tiles()

    def use(self, vid: str):
        """A card was clicked: that voice, on now (like the voice changer's cards)."""
        self.pick(vid)
        if vid in self._tile and not self.is_on():
            self.b_start.setChecked(True)      # _toggle starts it with this voice

    def pick(self, vid: str):
        """Make this the voice: the next Start, or now if it's on."""
        if vid not in self._tile:
            return
        self.s["voice"] = vid
        self._show_about()
        if self.ctl.running:
            self.ctl.set_voice(vid, self.s["pitch"])
            self._voice_name = self._voice().get("name", "")
            self.lbl_state.setText(_("● switching to {voice}…", voice=self._voice_name))
        self._emit()

    # ------------------------------------------------------------ your own voices
    def can_make(self) -> bool:
        """Your own voices are written into the add-on: only the one you downloaded."""
        return self.module is not None and aiaddon.removable(self.module)

    def _resync(self):
        """Your own voices changed: write them into the add-on and list them again."""
        old = self.s["voice"]
        self.voices = read_voices(self.module, self.store.voices)
        self._favs = [i for i in self._favs if any(vo["id"] == i for vo in self.voices)]
        self._fill_tiles()
        if self.current_voice() != old:     # it was deleted: the first one instead
            self.pick(self.current_voice())
        self._emit()

    def _play_sample(self, data):
        assert self.engine is not None   # only offered with one
        self.engine.play("__ai_voice_sample", data, 1.0, preview=True)

    def _mine_menu(self, vid: str, pos: QPoint):
        m = QMenu(self)
        if self.can_make():
            m.addAction(_("Change this voice"), lambda: self.edit(vid))
        m.addAction(_("Delete"), lambda: self.delete(vid))
        m.exec(pos)

    def edit(self, vid: str | None):
        """Make one of your own voices (None) or change one."""
        if not self.can_make():
            return
        if vid is None and self.store.full():
            busy.toast(self, html.escape(ngettext(
                "⚠ You have {n} voice of your own already: delete it to make another.",
                "⚠ You have {n} voices of your own already: delete one to make another.",
                avl.MAX_VOICES).removeprefix("⚠ ")), "warn")
            return
        built = [vo for vo in self.voices if not avl.is_mine(vo)]
        d = AiVoiceEditor(built, self.store.get(vid) if vid else None, self.previewer, self)
        if d.exec() == QDialog.DialogCode.Accepted and self.store.put(d.result_voice()) is not None:
            self._resync()
            if vid is None:
                self.pick(d.result_voice()["id"])

    def delete(self, vid: str):
        item = self.store.remove(vid)
        if item is None:
            return
        self._resync()
        self.undo_bar.show_for(_("Deleted “{name}”", name=item.name),
                               lambda: self._undo(item.id))

    def _undo(self, item_id: str):
        it = self.store.take(item_id)
        if it is not None and self.store.restore(it) is not None:
            self._resync()

    def show_deleted(self):
        from soundboard.ui.deleted import DeletedDialog
        self.undo_bar.finish()

        def back(item) -> bool:
            return self.store.restore(item) is not None
        DeletedDialog(avl.KIND, "voices", back, self, source=self.store).exec()
        self._resync()

    def _auto_toggled(self, on: bool):
        self.s["auto_pitch"] = on
        self.ctl.set_auto_pitch(on)
        self._emit()

    def _show_pitch(self):
        st = self.sl_pitch.value() / 2
        self.lbl_pitch.setText("0" if st == 0 else f"{st:+g}")

    def _pitch_moved(self, _v):
        self._show_pitch()
        if not self.sl_pitch.isSliderDown():
            self._pitch_released()

    def _pitch_released(self):
        st = self.sl_pitch.value() / 2
        if st != self.s["pitch"]:
            self.s["pitch"] = st
            if self.ctl.running:
                self.ctl.set_voice(self.s["voice"], st)
            self._emit()

    def _backup_picked(self, *_):
        self.s["backup"] = self.cb_backup.currentData() or "voice"
        self.ctl.set_backup(self.s["backup"])
        if self.status() == "failed":
            self.lbl_state.setText(self.failure_text(getattr(self, "_failure_error", "")))
        elif self.status() == "starting":
            self.lbl_state.setText(self._starting_text())
        self._emit()

    # ------------------------------------------------------------ start / stop
    def is_on(self) -> bool:
        return self.b_start.isChecked()

    def stop(self):
        if self.b_start.isChecked():
            self.b_start.setChecked(False)

    def _toggle(self, on: bool):
        if on and not self.ctl.running:
            if self.module is None:
                self._set_ui(False, IDLE)
                return
            self._retried = False
            if not self._start_helper():
                return
            self._voice_name = self._voice().get("name", "")
            self._set_ui(True, self._starting_text())
        elif not on and self.ctl.running:
            self.ctl.stop()
            self._set_ui(False, IDLE)

    def _start_helper(self) -> bool:
        self._connected = False      # the helper said hello (it can still fail to load)
        module = self.module
        assert module is not None   # both callers checked
        try:
            self.ctl.start(module, self.current_voice(),
                           self.s["auto_pitch"], self.s["pitch"])
        except RuntimeError as e:
            self._set_ui(False, f"⚠ {errors.plain(e)}")
            return False
        return True

    def status(self) -> str:
        """"off", "starting", "on" (others hear the AI voice) or "failed" (the backup
        covers you): for the Voice tab's status bar."""
        return self._status if self.is_on() else "off"

    def voice_title(self) -> str:
        """The running voice's name (the status bar's chip)."""
        return self._voice_name or self._voice().get("name", "")

    def backup_heard(self) -> str:
        return BACKUP_HEARD.get(self.cb_backup.currentData() or "voice", BACKUP_HEARD["voice"])

    def _starting_text(self, retry: bool = False) -> str:
        return (_("starting again…") if retry else _("starting…")) + " " + _(
            "Others now hear {backup}.", backup=self.backup_heard())

    def failure_text(self, error: str = "") -> str:
        error = error.strip().rstrip(".。")   # the sentence adds its own full stop
        return (_("⚠ The AI voice stopped: {error}. Others now hear {backup}. Press Stop, "
                  "then Start to try again.", error=error, backup=self.backup_heard()) if error else
                _("⚠ The AI voice stopped. Others now hear {backup}. Press Stop, then Start "
                  "to try again.", backup=self.backup_heard()))

    def _set_ui(self, on: bool, state: str):
        self._status = "starting" if on else "off"
        self.b_start.blockSignals(True)
        self.b_start.setChecked(on)
        self.b_start.blockSignals(False)
        self.b_start.setText(_("Stop AI voice") if on else _("Start AI voice"))
        self.b_update.setEnabled(not on)
        self.lbl_state.setText(state)
        self.live_changed.emit(on)

    def _on_event(self, ev: dict):
        t = ev.get("type")
        text = str(ev.get("text", ""))
        if t == "hello":
            self._connected = True
        elif t == "status":
            self.lbl_state.setText(text)
        elif t == "ready":
            self._status = "on"
            msg = (_("● you sound like {voice}", voice=self._voice_name) if self._voice_name
                   else _("● you sound like the voice"))
            if ev.get("slow"):
                msg += " " + _("⚠ This PC is slow for AI voices: games may stutter. A voice "
                               "changer preset (left) is much lighter.")
            self.lbl_state.setText(msg)
        elif t == "stats":
            cpu, ms = f"{float(ev.get('cpu', 0)):.0f}", f"{aivoice.LATENCY_S * 1000:.0f}"
            self.lbl_state.setText(
                _("● you sound like {voice} · CPU {cpu}% · about {ms} ms behind you",
                  voice=self._voice_name, cpu=cpu, ms=ms) if self._voice_name else
                _("● you sound like the voice · CPU {cpu}% · about {ms} ms behind you",
                  cpu=cpu, ms=ms))
        elif t == "error":
            self._status = "failed"
            self._failure_error = text
            self.lbl_state.setText(self.failure_text(text))
        elif (t == "stopped" and self.ctl.running and not self._connected
              and not self._retried and self.module is not None):
            # the helper never called back (once it sat silent for 30 s, then started
            # fine the next time): one more go by itself before asking you to
            self._retried = True
            log.warning("AI voice helper didn't connect (%s); trying once more", text)
            if self._start_helper():
                self._status = "starting"
                self.lbl_state.setText(self._starting_text(retry=True))
        elif t == "stopped" and self.ctl.running:
            self._status = "failed"
            self._failure_error = text
            self.lbl_state.setText(self.failure_text(text))

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
        for b in (self.b_install, self.b_update, self.b_start):
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
        for b in (self.b_install, self.b_update, self.b_start, self.b_get):
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
            busy.toast(self, _("AI voices are installed. Pick a voice and press Start."), "ok")
        else:
            self._refresh()                 # the buttons come back to try again
            last = self.lbl_install.text()
            self.lbl_install.hide()
            busy.toast(self, html.escape(_(
                "⚠ Install failed: {error}. Press it again to retry; if it keeps failing, "
                "run install.bat in the add-on's folder to see why.",
                error=err or self._last_line[-160:] or last).removeprefix("⚠ ")), "error")

    def shutdown(self):
        self.ctl.shutdown()
