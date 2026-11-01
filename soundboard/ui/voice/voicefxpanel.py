"""The Voice tab's voice changer card: `VoiceFxPanel`. Its pieces have their own
modules: effect rows (effectrow.py), sliders and switches (fxcontrols.py) and voice
cards (voicetiles.py).

It follows panel.py's pattern: it owns its widgets and emits plain dicts
(`changed`) that the main window stores in the config.
"""
from __future__ import annotations

import html
import json
import random
from collections.abc import Callable

import numpy as np

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QBoxLayout, QButtonGroup, QDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QMenu, QPushButton, QSizePolicy,
                               QScrollArea, QTabWidget, QVBoxLayout, QWidget)
from shiboken6 import isValid as qt_valid

from soundboard.core import usage
from soundboard.mic import savedvoices
from soundboard import voicefx
from soundboard.ui.voice import art
from soundboard.ui.kit import busy, icons
from soundboard.ui.kit.glow import Halo
from soundboard.ui.voice.aivoicebrowser import hear_button
from soundboard.ui.voice.groupbar import GroupBar
from soundboard.ui.kit.panel import (Flow, UndoBar, ViewToggle, hint_label, section_label,
                                     steady_number)
from soundboard.i18n import _, ngettext
from soundboard.ui.voice.fxcontrols import _enable
# (callers import these from here too)
from soundboard.ui.voice.fxcontrols import ParamSlider, Switch, param_text  # noqa: F401
from soundboard.ui.voice.voicetiles import (ALL, CUSTOM, FAVS, GROUP_ICONS, LIST_MIN_W, MAX_COLS,
                                            MINE, PICKED_ART, TILE_ART, TILE_GAP, TILE_MIN_W,
                                            VOICE_GROUPS, VOICE_ICONS, BigSwitch, VoiceTile)
from soundboard.ui.voice.voicetiles import voice_group  # noqa: F401  (the tests import it from here)
from soundboard.ui.voice.effectrow import (ADDON_GROUP, GROUPS, HERO, KEEP, MAIN_TAB, EffectRow,
                                           on_top)
from soundboard.ui.voice.voicefxtiles import VoiceFxTiles
from soundboard.ui.voice.voicefxsaved import VoiceFxSaved
from soundboard.ui.voice.voicefxcards import VoiceFxCards


def default_fx_spec() -> dict:
    return {"enabled": False, "preset": CUSTOM, "effects": {}}


def at_start(spec):
    """The saved voice changer as the app starts with it: left off, it forgets the voice
    picked last time, so ON doesn't bring back one from an old run. Your own mix stays;
    left on, it comes back as it was."""
    if not isinstance(spec, dict) or spec.get("enabled") or spec.get("preset", CUSTOM) == CUSTOM:
        return spec
    custom = spec.get("custom")
    return {**spec, "preset": CUSTOM, "effects": custom if isinstance(custom, dict) else {}}


class Footer(QWidget):
    """Edit voice's footer: `left` and `right` button groups on one line, or the right
    one under the left when the window is too narrow for both (so the window can still
    be made narrow)."""

    def __init__(self):
        super().__init__()
        self.box = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(6)
        self.left, self.right = QHBoxLayout(), QHBoxLayout()
        for lay in (self.left, self.right):
            lay.setSpacing(6)
        self.left.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.right.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.box.addLayout(self.left, 1)
        self.box.addLayout(self.right, 1)

    def _both(self) -> int:
        m = self.contentsMargins()
        return (self.left.sizeHint().width() + self.right.sizeHint().width()
                + self.box.spacing() + m.left() + m.right())

    def minimumSizeHint(self) -> QSize:
        m = self.contentsMargins()
        w = max(self.left.minimumSize().width(), self.right.minimumSize().width())
        return QSize(w + m.left() + m.right(), super().minimumSizeHint().height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        want = (QBoxLayout.Direction.LeftToRight if self._both() <= e.size().width()
                else QBoxLayout.Direction.TopToBottom)
        if self.box.direction() != want:
            self.box.setDirection(want)
            self.updateGeometry()


DLG_ART = 32   # the voice's picture at the top of Edit voice
POWER_TEXT = {False: _("Voice changer is OFF"), True: _("Voice changer is ON")}


class VoiceFxPanel(VoiceFxTiles, VoiceFxSaved, VoiceFxCards, QWidget):
    """The voice changer: one big on/off switch, a grid of voices to pick from, a
    way to hear yourself, and (folded away) the individual effects for fine-tuning.

    `changed(spec)` with spec = {"enabled", "preset", "effects": {type: {...}}}."""
    changed = Signal(dict)
    folds_changed = Signal(list)   # the effect types whose cards are folded away
    hotkey_asked = Signal(str)     # right-click a voice -> Set hotkey: its name ("" key: clear)
    hotkey_cleared = Signal(str)
    renamed = Signal(str, str)     # a saved voice's old and new name
    share_asked = Signal(str)      # right-click a saved voice -> Share to the store: its name
    # an imported code holding an AI voice or a setup (storevoices.Voice, notes) -> the
    # name it was added as, "" if not (the Voice tab adds those; None: not taken here)
    take_code: Callable[[object, list], str] | None = None
    _sampled = Signal(object, str)  # Hear it's worker: (the sample or None, why not)

    COLS = 3

    def __init__(self, spec: dict, store: savedvoices.Store | None = None,
                 play_sample: Callable[[np.ndarray], object] | None = None):
        super().__init__()
        # your saved voices (Fine-tune -> "Save as a voice"): their own file, see
        # soundboard.mic.savedvoices
        self.store = store if store is not None else savedvoices.Store()
        # the board's sounds for the Background card's "Add a sound from my board":
        # [(id, name, categories)], set by the main window
        self.sound_list: Callable[[], list[tuple[str, str, list[str]]]] = list
        self._based_on = ""   # the saved voice Fine-tune started from (Save offers it)
        # cleaned: a damaged setting (hand-edited, an old backup) mustn't stop the app
        spec = {**default_fx_spec(), **voicefx.clean_spec(spec)}
        preset = spec.get("preset")
        self._preset: str = (preset if isinstance(preset, str)
                             and (preset in voicefx.PRESETS or preset in self.store.voices)
                             else CUSTOM)
        # "My own mix" while a preset is on, so picking a preset never loses it
        effects, custom = dict(spec.get("effects", {})), dict(spec.get("custom", {}))
        self._custom: dict = custom or (effects if self._preset == CUSTOM else {})
        # Fine-tune holds your own mix, not a preset you nudged (that shows as Custom
        # too, but mustn't replace the mix you made)
        self._own = self._preset == CUSTOM and self._custom == effects
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        self.title = section_label(_("Voice changer"))
        v.addWidget(self.title)

        # ---- the big ON/OFF: the Voice tab puts `head` right after its card's name
        self.btn_power = BigSwitch()
        self.btn_power.setChecked(spec["enabled"])
        self.btn_power.toggled.connect(self._on_power)
        self.head = QWidget()
        hh = QHBoxLayout(self.head)
        hh.setContentsMargins(0, 0, 0, 0)
        hh.addWidget(self.btn_power)
        # your mic level is in the tab's status bar (ui/voice/voicestatus.py), over every card
        # (to hear it: the mixer's "Hear what they hear", the one switch on every tab)
        v.addWidget(hint_label(_("Change your mic live for whoever you send sounds to (Discord, "
                                 "a game, OBS). Pick a voice to turn it on, then use Hear what "
                                 "they hear at the bottom to try it.")))

        # ---- which voices show: All (under group headings), your favorites, one group
        favs = spec.get("favorites")
        self._favs: list[str] = list(favs) if isinstance(favs, list) else []
        self._group = ALL
        self._listed = False
        self.view_toggle = ViewToggle("grid", _("Voices"))
        self.view_toggle.changed.connect(self.set_view)
        self.bar = GroupBar(
            [(ALL, _("All"), "sounds"), (FAVS, _("Favorites"), "star_filled"),
             *((k, t, GROUP_ICONS[k]) for k, t, _n in VOICE_GROUPS),
             (MINE, _("Mine"), "mic")],
            self.view_toggle, self._group_count,
            (_("Search voices"), _("Search")), _("Which voices show"))
        self.bar.picked.connect(lambda k: (usage.used("voice-group"), self.show_group(k)))
        self.bar.searched.connect(lambda _t: self._place_tiles())
        v.addWidget(self.bar)
        self._heads: dict[str, QLabel] = {}
        for key, text in (*((k, t) for k, t, _n in VOICE_GROUPS), (MINE, _("Mine"))):
            lbl = QLabel(text)
            lbl.setObjectName("fxgroup")
            lbl.hide()
            self._heads[key] = lbl
        self.no_favs = hint_label(_("No favorites yet. Click the star in a voice's corner "
                                    "to keep it here."))
        self.no_favs.hide()
        self.no_match = hint_label("")
        self.no_match.hide()

        # ---- pick a voice: picture cards, as many a row as the width holds
        grid = self._tile_grid = QGridLayout()
        grid.setSpacing(TILE_GAP)
        self._tile_cols = self.COLS
        self.tiles = QButtonGroup(self)
        self.tiles.setExclusive(True)
        self._tile: dict[str, VoiceTile] = {}
        self.keys: dict[str, str] = {}   # voice name -> its hotkey (the window fills it in)
        self._saved_tiles: list[VoiceTile] = []
        for name in list(voicefx.PRESETS) + [CUSTOM]:
            title = _("My own mix") if name == CUSTOM else voicefx.shown(name)
            pic = art.icon(art.voice_key(name)) or (art.mystery_icon() if name != CUSTOM
                                                    else None)
            b = self._make_tile(name, title, pic, VOICE_ICONS.get(name, "wave"))
            if name == CUSTOM:
                b.setToolTip(_("Your own settings: Edit voice opens them"))
        # the die: turns on one of the voices shown, at random. It isn't a voice itself,
        # so it never lights up and has no star; it goes after the last card
        self._shown: list[str] = []   # the voices the cards show now, in order
        rt = self.random_tile = VoiceTile(_("Random voice"))
        rt.setCheckable(False)
        rt.star.hide()
        rt.setIcon(art.random_icon())
        rt.setProperty("art", True)
        rt.setIconSize(QSize(TILE_ART, TILE_ART))
        rt.setCursor(Qt.CursorShape.PointingHandCursor)
        rt.setToolTip(_("Turns on one of the voices shown here, picked at random. Click "
                        "again for another."))
        rt.clicked.connect(lambda: (usage.used("voice-roll"), self.roll()))
        for c in range(self.COLS):
            grid.setColumnStretch(c, 1)
        v.addLayout(grid)
        v.addWidget(self.no_favs)
        v.addWidget(self.no_match)
        self.undo_bar = UndoBar(_("Bring the voice back, as it was"))
        v.addWidget(self.undo_bar)

        # ---- the voice you picked, and Edit voice (hearing it: the mixer's Hear what
        # they hear, the one switch, just below). The Voice tab pins it under
        # its scrolling cards (never scrolled out of sight); alone, it ends this panel
        self.picked = QFrame()
        self.picked.setObjectName("picked")
        # the voice's picture and name, then its buttons: side by side, or, when the
        # bar is too narrow for both (_fit_picked), the buttons on a line of their own
        self.picked_box = QBoxLayout(QBoxLayout.Direction.LeftToRight, self.picked)
        self.picked_box.setContentsMargins(12, 8, 12, 8)
        self.picked_box.setSpacing(10)
        ph = QHBoxLayout()
        ph.setSpacing(10)
        self.picked_box.addLayout(ph)
        pb = QHBoxLayout()
        pb.setSpacing(10)
        self.picked_box.addLayout(pb, 1)   # right after the name; the room left is past them
        self._picked_pb = pb
        self.picked_pic = QLabel()
        self.picked_pic.setFixedSize(PICKED_ART, PICKED_ART)
        ph.addWidget(self.picked_pic)
        self.picked_name = QLabel()
        self.picked_name.setObjectName("pickedname")
        self.picked_name.setWordWrap(True)
        self.picked_name.setMinimumWidth(40)   # a long name gives way in a narrow window
        ph.addWidget(self.picked_name)
        # which kind of voice it is, after its name (Robot alone didn't say)
        self.picked_kind = QLabel(_("(Voice changer)"))
        self.picked_kind.setObjectName("pickedkind")
        ph.addWidget(self.picked_kind)
        for lbl in (self.picked_name, self.picked_kind):   # no wider than their words:
            # the kind stays by the name, on a line of its own too (narrow)
            lbl.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        # everything for making your own voice opens in a window of its own (on the
        # card it made the tab scroll forever)
        self.btn_tweak = QPushButton(_("Edit voice"))
        icons.set_icon(self.btn_tweak, "sliders")
        self.btn_tweak.setToolTip(_("Pitch, Randomize, every effect, and your saved voices: "
                                    "build your own voice in a window beside the app"))
        self.btn_tweak.clicked.connect(lambda: (usage.used("voice-tweak"), self.open_tweak()))
        pb.addWidget(self.btn_tweak)
        # what's on top of the voice (rain, a crowd, an echo, your own sounds): a small
        # pop-up, before Edit voice (the full editor). It's the simple way in
        self.btn_effects = QPushButton(_("Effects"))
        icons.set_icon(self.btn_effects, "sounds")
        self.btn_effects.setToolTip(_("Rain, a crowd, an echo or sounds from your board, on "
                                      "top of any voice"))
        self.btn_effects.clicked.connect(lambda: (usage.used("voice-effects"),
                                                  self.open_effects()))
        pb.insertWidget(0, self.btn_effects)
        # a short line said in this voice, in your headphones (play_sample, from the
        # Voice tab: without it there's nowhere to play it, and no button)
        self.play_sample = play_sample
        self._hearing = False
        self._sampled.connect(self._sample_done)
        self.btn_sample = hear_button()
        self.btn_sample.clicked.connect(lambda: self.hear(self._preset))
        self.btn_sample.setParent(self.picked)   # not on the bar (as an AI voice's has
        self.btn_sample.hide()                   # none): a card's right-click Hear it
        pb.addStretch(1)
        v.addWidget(self.picked)
        self.picked.installEventFilter(self)   # (after its buttons: _fit_picked reads them)

        # ---- the "Edit voice" window: not modal, so the voices stay clickable
        self.dlg = QDialog(self)
        self.dlg.setWindowTitle(_("Edit voice"))
        self.dlg.setModal(False)
        self.dlg.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.dlg.finished.connect(self._tweak_closed)
        self.dlg.installEventFilter(self)
        self.destroyed.connect(self.dlg.deleteLater)   # (it may belong to the window)
        size = spec.get("panel_size")
        self._dlg_size = QSize(*size) if size else None
        dv = QVBoxLayout(self.dlg)
        dv.setContentsMargins(0, 0, 0, 10)
        dv.setSpacing(8)
        body = QFrame()
        body.setObjectName("card")   # painted like the tab's cards (sliders see-through)
        bv = QVBoxLayout(body)
        bv.setContentsMargins(16, 14, 16, 12)
        bv.setSpacing(6)
        dv.addWidget(body, 1)

        self.tweak = QFrame()
        self.tweak.setObjectName("tweak")
        tv = QVBoxLayout(self.tweak)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(10)
        # which voice you're changing (and whether you have), its delay on the right
        top = QHBoxLayout()
        top.setSpacing(10)
        self.dlg_pic = QLabel()
        self.dlg_pic.setFixedSize(DLG_ART, DLG_ART)
        top.addWidget(self.dlg_pic)
        self.dlg_name = QLabel()
        self.dlg_name.setObjectName("pickedname")
        self.dlg_name.setWordWrap(True)
        self.dlg_name.setMinimumWidth(40)
        top.addWidget(self.dlg_name, 1)
        tv.addLayout(top)
        # the window's buttons, all along the top (they wrap when it's narrow); the
        # title bar already says "Edit voice"
        tools = QWidget()
        srow = Flow(tools, gap=6)
        tv.addWidget(tools)
        self.btn_random = QPushButton(_("Randomize"))
        self.btn_random.setIcon(art.random_icon())
        self.btn_random.setIconSize(QSize(16, 16))
        self.btn_random.setToolTip(_("A random silly mix of effects, as “My own mix”: what "
                                     "it changed lights up below. Click again for another."))
        self.btn_random.clicked.connect(lambda: (usage.used("voice-random"), self.randomize()))
        srow.addWidget(self.btn_random)
        # two voices at once (Robot + Demon): the other one's effects on top of yours
        self.btn_mix = QPushButton(_("Mix in a voice"))
        icons.set_icon(self.btn_mix, "shuffle")
        self.btn_mix.setToolTip(_("Add another voice's effects to this one (Robot + Demon): "
                                  "the effects it has that yours doesn't get switched on"))
        self.btn_mix.clicked.connect(self._mix_menu)
        srow.addWidget(self.btn_mix)
        self.btn_save = QPushButton(_("Save as a voice"))
        icons.set_icon(self.btn_save, "plus")
        self.btn_save.setToolTip(_("Keep these settings as a voice with a name: it gets its "
                                   "own button under “Pick a voice”."))
        self.btn_save.clicked.connect(self.save_voice)
        # saved voices: share one as a line of text, add one a friend sent
        self.btn_share = QPushButton(_("Copy share code"))
        icons.set_icon(self.btn_share, "copy")
        self.btn_share.setToolTip(_("Copy the saved voice that's on as a short code to paste "
                                    "to a friend: just its name and settings"))
        self.btn_share.clicked.connect(lambda: self.copy_code(self._preset))
        srow.addWidget(self.btn_share)
        self.btn_import = QPushButton(_("Import a code"))
        icons.set_icon(self.btn_import, "plus")
        self.btn_import.setToolTip(_("Add a voice someone sent you as a code (it starts "
                                     "with “OB”)"))
        self.btn_import.clicked.connect(lambda: self.import_code())
        srow.addWidget(self.btn_import)
        self.btn_bin = QPushButton(_("Recently deleted"))
        icons.set_icon(self.btn_bin, "trash")
        self.btn_bin.setToolTip(ngettext(
            "Saved voices you deleted, kept for {n} day so you can bring them back",
            "Saved voices you deleted, kept for {n} days so you can bring them back",
            savedvoices.KEEP_DAYS))
        self.btn_bin.clicked.connect(self.show_deleted)
        srow.addWidget(self.btn_bin)
        self.delay = QLabel()
        self.delay.setObjectName("pill")
        steady_number(self.delay, _("{ms} ms delay", ms="000"))
        self.delay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(self.delay, 0, Qt.AlignmentFlag.AlignVCenter)
        bv.addWidget(self.tweak)

        # ---- the effects, a tab a group (one long page was too much to scroll):
        # Main has Pitch & voice, then Change the voice, Character,
        # Room and Add-ons, each tab's cards in two columns
        self.more = QTabWidget()
        self.more.setDocumentMode(True)
        bv.addWidget(self.more, 1)

        def tab(title: str) -> tuple[QScrollArea, QVBoxLayout]:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            page = QWidget()
            pv = QVBoxLayout(page)
            pv.setContentsMargins(0, 10, 4, 0)   # room under the tab bar, the scroll bar
            pv.setSpacing(10)
            scroll.setWidget(page)
            self.more.addTab(scroll, title)
            return scroll, pv

        self._main_scroll, mv = tab(MAIN_TAB)
        self.hero_box = QVBoxLayout()
        self.hero_box.setSpacing(10)
        mv.addLayout(self.hero_box)
        mv.addWidget(hint_label(_("Switch effects on and drag their sliders to build "
                                  "your own voice. Changing anything switches to “My "
                                  "own mix”; like it? Save it as a voice and it gets a "
                                  "button of its own.")))
        mv.addStretch(1)
        # two columns a tab that stack their cards tightly, each card going under the
        # shorter one: a grid left holes beside the shorter cards
        self._pages: dict[str, tuple[QScrollArea, QHBoxLayout, list[QVBoxLayout]]] = {}
        for title, _types in (*GROUPS, (ADDON_GROUP, ())):
            scroll, pv = tab(title)
            row = QHBoxLayout()
            row.setSpacing(10)
            cols = []
            for __ in range(2):
                col = QVBoxLayout()
                col.setSpacing(10)
                col.addStretch(1)
                row.addLayout(col, 1)
                cols.append(col)
            pv.addLayout(row)
            pv.addStretch(1)
            self._pages[title] = (scroll, row, cols)
        self._fx_cols = 2
        self._placed: dict | None = None   # what each tab's columns hold now
        self._replace = QTimer(self)       # a voice pick changes many cards: once after
        self._replace.setSingleShot(True)
        self._replace.setInterval(0)
        self._replace.timeout.connect(self._place_cards)
        self._folded_fx: set[str] = set()
        # the footer: Undo, Redo and Reset (back to the voice you started from) on the
        # left; Save as a voice and Done on the right, as in Edit sound
        footer = Footer()
        footer.setContentsMargins(16, 0, 16, 0)
        done = footer.left
        self.btn_undo = QPushButton(_("Undo"))
        self.btn_undo.setToolTip(_("Take back the last change (Ctrl+Z)"))
        self.btn_undo.clicked.connect(self.undo)
        self.btn_redo = QPushButton(_("Redo"))
        self.btn_redo.setToolTip(_("Do the change again (Ctrl+Y)"))
        self.btn_redo.clicked.connect(self.redo)
        self.btn_reset = QPushButton(_("Reset"))
        self.btn_reset.setObjectName("resetfx")
        icons.set_icon(self.btn_reset, "reload", size=14)
        self.btn_reset.clicked.connect(lambda: (usage.used("voice-edit-reset"),
                                                self.reset_edits()))
        self._reset_glow = Halo(self.btn_reset)   # lit while there's anything to reset
        done.addWidget(self.btn_undo)
        done.addWidget(self.btn_redo)
        done.addWidget(self._reset_glow)
        footer.right.addWidget(self.btn_save)
        btn_done = QPushButton(_("Done"))
        btn_done.setObjectName("primary")
        btn_done.clicked.connect(self.dlg.close)
        footer.right.addWidget(btn_done)
        dv.addWidget(footer)

        self.rows: dict[str, EffectRow] = {}
        self._spec_effects = dict(spec.get("effects", {}))
        # the Effects pop-up's extras that are on: {type: settings}
        self._extras: dict[str, dict] = {
            t: dict(c) for t, c in self._spec_effects.items()
            if isinstance(c, dict) and c.get("on") and t in voicefx.REGISTRY
            and voicefx.REGISTRY[t].extra}
        self.effects_pop = None
        self._delay_cache: dict = {}
        self._device_ms: float | None = None
        self.add_new_effects()
        self._fresh_timer = QTimer(self)
        self._fresh_timer.setSingleShot(True)
        self._fresh_timer.timeout.connect(self._clear_fresh)
        # Undo / Redo: each settled change a step (a slider drag is one), and the voice
        # you started from for Reset (set again when you pick a voice)
        self._restoring = False
        self._htimer = QTimer(self)
        self._htimer.setSingleShot(True)
        self._htimer.setInterval(400)
        self._htimer.timeout.connect(self._record)
        QShortcut(QKeySequence.StandardKey.Undo, self.dlg, self.undo)
        QShortcut(QKeySequence.StandardKey.Redo, self.dlg, self.redo)
        self._fill_saved()
        self._mark_start()
        self._refresh()

    # ------------------------------------------------------------------ public
    @property
    def preset(self) -> str:
        return self._preset

    def pick(self, name: str):
        """Choose a voice (a preset name or CUSTOM) and turn the changer on. Your own
        mix is kept aside while a preset is on, and comes back with "My own mix"."""
        mine = self._mine()
        if mine and name != CUSTOM:
            self._custom = {t: r.state() for t, r in self.rows.items()}
        self._preset = name
        self._clear_fresh()
        fx = voicefx.PRESETS.get(name)
        saved = self.store.voices.get(name)
        self._based_on = name if saved is not None else ""
        rows = {t: r for t, r in self.rows.items() if t not in KEEP}
        if fx is not None:
            self._own = False
            for t, r in rows.items():
                r.load({"on": True, **fx[t]} if t in fx else None)
        elif saved is not None:   # stored whole, "on" and all, like Fine-tune's rows
            self._own = False
            for t, r in rows.items():
                r.load(saved.get(t))
        elif name == CUSTOM:
            if not mine and self._custom:
                for t, r in rows.items():
                    r.load(self._custom.get(t))
            self._own = True
            self.open_tweak()   # your own mix lives in Edit voice
        self.btn_power.blockSignals(True)
        self.btn_power.setChecked(True)
        self.btn_power.blockSignals(False)
        self._mark_start()
        self._refresh()
        self._emit()

    def use_mix(self, effects: dict):
        """Turn the changer on with these effects as your own mix (a setup made from a
        voice that's gone since), without opening Edit voice."""
        rows = {t: r for t, r in self.rows.items() if t not in KEEP}
        for t, r in rows.items():
            r.load(effects.get(t))
        self._custom = {t: r.state() for t, r in self.rows.items()}
        self._preset = CUSTOM
        self._own = True
        self._based_on = ""
        self._clear_fresh()
        self.btn_power.blockSignals(True)
        self.btn_power.setChecked(True)
        self.btn_power.blockSignals(False)
        self._mark_start()
        self._refresh()
        self._emit()

    def is_blank(self) -> bool:
        """No voice at all to turn on: your own mix with nothing in it (`clear_mix`)."""
        return (self._preset == CUSTOM and not self._extras and not any(
            r.chk.isChecked() for r in self.rows.values()))

    def snapshot(self) -> dict:
        """Everything `clear_mix` throws away, for `restore` (its Undo)."""
        return {"rows": {t: r.state() for t, r in self.rows.items()},
                "extras": {t: dict(c) for t, c in self._extras.items()},
                "custom": dict(self._custom), "preset": self._preset, "own": self._own,
                "based_on": self._based_on, "on": self.btn_power.isChecked()}

    def restore(self, snap: dict):
        for t, r in self.rows.items():
            r.load(snap["rows"].get(t))
        self._extras = {t: dict(c) for t, c in snap["extras"].items()}
        self._custom, self._preset = dict(snap["custom"]), snap["preset"]
        self._own, self._based_on = snap["own"], snap["based_on"]
        self.btn_power.blockSignals(True)
        self.btn_power.setChecked(snap["on"])
        self.btn_power.blockSignals(False)
        self._refresh()
        self._emit()

    def clear_mix(self):
        """A fresh start: off, with no effects at all (your own mix emptied too, and
        what's on top of the voice)."""
        for r in self.rows.values():
            r.load(None)
        self._extras = {}
        self._custom = {}
        self._preset = CUSTOM
        self._own = True
        self._based_on = ""
        self._clear_fresh()
        self.btn_power.blockSignals(True)
        self.btn_power.setChecked(False)
        self.btn_power.blockSignals(False)
        self._mark_start()
        self._refresh()
        self._emit()

    # ------------------------------------------------------------------ undo / reset
    HISTORY_STEPS = 100

    def _voice_snap(self) -> dict:
        """The voice itself, for Undo and Reset: its effects (not what's on top of it,
        which the Effects pop-up owns) and which voice it is."""
        return {"rows": {t: r.state() for t, r in self.rows.items() if not on_top(t)},
                "preset": self._preset, "own": self._own, "based_on": self._based_on,
                "custom": dict(self._custom)}

    @staticmethod
    def _same(a: dict, b: dict) -> bool:
        def key(snap: dict) -> str:
            return json.dumps([snap["rows"], snap["preset"]], sort_keys=True, default=str)
        return key(a) == key(b)

    def _mark_start(self):
        """A new voice (picked, saved, cleared): Reset goes back to this, and the
        history starts again from it."""
        self._start = self._voice_snap()
        self._htimer.stop()
        self._history, self._hpos = [self._start], 0

    def edited_since_start(self) -> bool:
        return not self._same(self._voice_snap(), self._start)

    def _load_snap(self, snap: dict):
        self._restoring = True
        try:
            for t, r in self.rows.items():
                if not on_top(t):
                    r.load(snap["rows"].get(t))
            self._preset, self._own = snap["preset"], snap["own"]
            self._based_on, self._custom = snap["based_on"], dict(snap["custom"])
            self._clear_fresh()
            self._refresh()
            self._emit()
        finally:
            self._restoring = False

    def reset_edits(self):
        """Reset: back to the voice as it was when you picked it. It's one more Undo
        step, so Ctrl+Z brings your changes back."""
        self._flush()
        if not self.edited_since_start():
            return
        self._load_snap(self._start)
        self._record()

    def _record(self):
        snap = self._voice_snap()
        if not self._same(snap, self._history[self._hpos]):
            del self._history[self._hpos + 1:]
            self._history.append(snap)
            del self._history[:-self.HISTORY_STEPS]
            self._hpos = len(self._history) - 1
        self._show_edit_state()

    def _flush(self):
        if self._htimer.isActive():
            self._htimer.stop()
            self._record()

    def undo(self):
        self._flush()
        if self._hpos > 0:
            self._hpos -= 1
            self._load_snap(self._history[self._hpos])

    def redo(self):
        self._flush()
        if self._hpos < len(self._history) - 1:
            self._hpos += 1
            self._load_snap(self._history[self._hpos])

    def _mix_menu(self):
        """Mix in a voice's list: the voices under their groups, then your saved ones."""
        m = QMenu(self.dlg)

        def add(menu: QMenu, name: str):
            pic = art.icon(art.voice_key(name)) if name in voicefx.PRESETS else None
            # (an "&" in a name shows as itself: Qt reads one as a shortcut marker)
            a = menu.addAction(self.title_of(name).replace("&", "&&"),
                               lambda: self.mix_in(name))
            if pic is not None:
                a.setIcon(pic)
        for key, title, names in VOICE_GROUPS:
            sub = m.addMenu(icons.icon(GROUP_ICONS[key]), title.replace("&", "&&"))
            for name in names:
                if name in voicefx.PRESETS:
                    add(sub, name)
        if self.store.voices:
            sub = m.addMenu(icons.icon("mic"), _("Mine"))
            for name in self.store.voices:
                add(sub, name)
        m.exec(self.btn_mix.mapToGlobal(self.btn_mix.rect().bottomLeft()))

    def mix_in(self, name: str) -> list[str]:
        """Mix in a voice: its effects that yours doesn't have yet, switched on with its
        settings (the ones you have stay yours). They light up like Randomize's.
        Returns the effects it added."""
        usage.used("voice-mix-in")
        added = []
        for t, cfg in self.effects_of(name).items():
            r = self.rows.get(t)
            if r is None or r.chk.isChecked():
                continue
            r.load(cfg)
            added.append(t)
        if not added:
            busy.toast(self._parent(), html.escape(
                _("Your voice already has everything “{voice}” has", voice=self.title_of(name))))
            return added
        self._preset = CUSTOM
        self.btn_power.blockSignals(True)
        self.btn_power.setChecked(True)
        self.btn_power.blockSignals(False)
        self._refresh()
        self._emit()
        self._clear_fresh()
        for t in added:
            self.rows[t].set_fresh(True)
        self._fresh_timer.start(self.FRESH_MS)
        QTimer.singleShot(60, self._scroll_to_fresh)
        return added

    def edit_voice(self, name: str):
        """A voice card's right-click Edit voice: that voice on, and its editor open."""
        usage.used("voice-edit-menu")
        if not (self.btn_power.isChecked() and self._preset == name):
            self.pick(name)
        self.open_tweak()

    def _show_edit_state(self):
        """Edit voice's top line and footer: the voice you're changing (", changed" once
        you have), Reset lit while there's anything to put back, Undo and Redo while
        there's a step to take."""
        if not hasattr(self, "_start"):
            return   # (still being made)
        base = self._start["preset"]
        shown = _("My own mix") if base == CUSTOM else self.title_of(base)
        edited = self.edited_since_start()
        self.dlg_name.setText(_("{voice}, changed", voice=shown) if edited else shown)
        pm = art.pixmap(art.voice_key(base), DLG_ART) if base != CUSTOM else None
        if pm is None:
            pm = icons.icon(VOICE_ICONS.get(base, "wave"), "muted").pixmap(DLG_ART, DLG_ART)
        self.dlg_pic.setPixmap(pm)
        tip = (_("Back to “{voice}” as it was when you picked it", voice=shown)
               if base != CUSTOM else _("Back to your own mix as it was"))
        self.btn_reset.setToolTip(tip)
        self.btn_reset.setAccessibleName(tip)
        self.btn_reset.setEnabled(edited)
        self._reset_glow.set_on(edited)
        if bool(self.btn_reset.property("nudge")) != edited:
            self.btn_reset.setProperty("nudge", edited)
            self.btn_reset.style().unpolish(self.btn_reset)
            self.btn_reset.style().polish(self.btn_reset)
        self.btn_undo.setEnabled(self._hpos > 0 or self._htimer.isActive())
        self.btn_redo.setEnabled(self._hpos < len(self._history) - 1)

    # never ear-splitting: louder settings are capped below their slider's top
    RANDOM_CAPS = {("compressor", "boost"): 9, ("distortion", "drive"): 20,
                   ("echo", "feedback"): 0.6, ("radio", "drive"): 14,
                   ("wobble", "vibrato"): 10}

    def randomize(self, rng: random.Random | None = None):
        """A random mix for the lols: the pitch moved well away from normal plus one
        or two other effects at random settings, as "My own mix"."""
        rng = rng or random.Random()
        others = [t for t in self.rows if t != "pitch" and t not in KEEP]
        chosen = set(rng.sample(others, min(len(others), rng.randint(1, 2))))
        if "pitch" in self.rows:
            chosen.add("pitch")
        for t, r in self.rows.items():
            if t in KEEP:
                continue
            if t not in chosen:
                r.load(None)
                continue
            cfg: dict[str, bool | float] = {"on": True}
            for q in r.cls.params:
                hi = min(q.hi, self.RANDOM_CAPS.get((t, q.key), q.hi))
                cfg[q.key] = rng.uniform(q.lo, hi)
            if t == "pitch":
                cfg["semitones"] = rng.choice((-1, 1)) * rng.uniform(4, 12)
                cfg["mix"] = 1.0
                cfg["tune"] = rng.choice((0.0, 0.0, 1.0))   # sometimes autotuned
            r.load(cfg)
        self._own = True
        self._custom = {t: r.state() for t, r in self.rows.items()}
        self._preset = CUSTOM
        self._based_on = ""
        self.btn_power.blockSignals(True)
        self.btn_power.setChecked(True)
        self.btn_power.blockSignals(False)
        self._refresh()
        self._emit()
        # show what it did: Edit voice opens with the effects it set lit up for a while
        self.open_tweak()
        for t, r in self.rows.items():
            r.set_fresh(t in chosen)
        self._fresh_timer.start(self.FRESH_MS)
        QTimer.singleShot(60, self._scroll_to_fresh)

    FRESH_MS = 8000

    def _clear_fresh(self):
        self._fresh_timer.stop()
        for r in self.rows.values():
            r.set_fresh(False)

    def _scroll_to_fresh(self):
        """Inside Edit voice, bring the lit-up effects into view: the tab of the first
        one past Main (the pitch is nearly always one of them), scrolled to it."""
        fresh = [r for r in self.rows.values() if r.is_fresh()]
        for scroll in (*(pg[0] for pg in self._pages.values()), self._main_scroll):
            page = scroll.widget()
            mine = [r for r in fresh if page is not None and page.isAncestorOf(r)]
            if mine:
                self.more.setCurrentWidget(scroll)
                scroll.ensureWidgetVisible(mine[-1], 0, 24)
                scroll.ensureWidgetVisible(mine[0], 0, 24)
                return


    def open_tweak(self):
        """Show the Edit voice window (at the size you left it), or bring it up."""
        if not self.dlg.isVisible():
            # owned by the app's window, not this panel: inside a card the theme makes
            # every widget see-through (QFrame#card QWidget), the window included
            if self.dlg.parentWidget() is not self.window():
                self.dlg.setParent(self.window(), self.dlg.windowFlags())
            size = self._dlg_size or self.DLG_SIZE
            screen = (self.screen() or QGuiApplication.primaryScreen()).availableGeometry()
            self.dlg.resize(min(size.width(), screen.width()),
                            min(size.height(), screen.height()))
            self.dlg.show()
        self.dlg.raise_()
        self.dlg.activateWindow()

    def _tweak_closed(self, _result=0):
        self._clear_fresh()
        self._emit()   # its size goes into the settings, for next time

    def hideEvent(self, e):
        super().hideEvent(e)
        # the app went to the tray (not just another tab): Edit voice goes with it
        if self.dlg.isVisible():
            QTimer.singleShot(0, self.dlg, self._close_if_app_hidden)   # (dropped if it's gone)

    def _close_if_app_hidden(self):
        if qt_valid(self) and not self.window().isVisible():
            self.dlg.close()

    def _fit_picked(self):
        """The voice bar, by its width: the first of these that fits. Buttons beside
        the voice's name; under it (squeezed, "Edit voice  ·  4 on" lost its words);
        then Effects as its icon alone (its tooltip and screen-reader name still
        say it); then Edit voice without its count."""
        if getattr(self, "_fitting", False):
            return   # a text change below lays the bar out again
        self._fitting = True
        try:
            tw, tb, pb = self.btn_tweak, self.btn_effects, self._picked_pb

            def width(b, text: str) -> int:   # b's width showing `text` (icon alone: "")
                fm = b.fontMetrics()
                now = b.text()
                base = b.minimumSizeHint().width() - (fm.horizontalAdvance(now) + 6
                                                      if now else 0)
                return base + (fm.horizontalAdvance(text) + 6 if text else 0)

            full = getattr(self, "_tweak_text", "") or _("Edit voice")
            bd = getattr(self, "_effects_text", "") or _("Effects")
            hear = (self.btn_sample.minimumSizeHint().width() + pb.spacing()
                    if not self.btn_sample.isHidden() else 0)
            m = self.picked_box.contentsMargins()
            line = self.picked.width() - m.left() - m.right()
            beside = (line - PICKED_ART - min(self.picked_name.sizeHint().width(), 140)
                      - self.picked_kind.sizeHint().width() - 3 * self.picked_box.spacing())
            row, col = QBoxLayout.Direction.LeftToRight, QBoxLayout.Direction.TopToBottom
            tries = ((row, full, bd, beside), (col, full, bd, line), (col, full, "", line),
                     (col, _("Edit voice"), "", line))
            want, t_text, b_text, _room = next(
                (t for t in tries
                 if width(tw, t[1]) + pb.spacing() + width(tb, t[2]) + hear <= t[3]),
                tries[-1])
            if self.picked_box.direction() != want:
                self.picked_box.setDirection(want)
            for b, text in ((tw, t_text), (tb, b_text)):
                if b.text() != text:
                    b.setText(text)
                    icons.text_gap(b)
        finally:
            self._fitting = False

    def eventFilter(self, obj, e):
        if obj is self.picked and e.type() == QEvent.Type.Resize:
            self._fit_picked()
        if obj is self.dlg and e.type() == QEvent.Type.Resize:
            if self.dlg.isVisible():
                self._dlg_size = QSize(e.size())
            cols = 2 if e.size().width() >= 600 else 1
            if cols != self._fx_cols:
                self._fx_cols = cols
                self._place_cards()
            else:
                self._reshape()   # wider or narrower: the cards' text wraps differently
        return super().eventFilter(obj, e)


    def _mine(self) -> bool:
        """Is Fine-tune showing your own mix? A nudged preset counts only while you
        haven't made one."""
        made = any(isinstance(e, dict) and e.get("on")
                   for t, e in self._custom.items() if t not in KEEP)
        return self._preset == CUSTOM and (self._own or not made)

    def spec(self) -> dict:
        effects = {t: r.state() for t, r in self.rows.items()}
        effects.update({t: dict(c) for t, c in self._extras.items()})
        return {"enabled": self.btn_power.isChecked(), "preset": self._preset,
                "effects": effects,
                "custom": effects if self._mine() else self._custom,
                **({"favorites": list(self._favs)} if self._favs else {}),
                **({"panel_size": [self._dlg_size.width(), self._dlg_size.height()]}
                   if self._dlg_size else {})}

    def show_errors(self, errors: dict[str, str]):
        for t, r in self.rows.items():
            r.set_error(errors.get(t, ""))

    # ------------------------------------------------------------------ internals
    def _on_power(self, on: bool):
        self._refresh()
        self._emit()

    def _count_on(self) -> int:
        # the voice's own effects: what's on top of it is Effects' count
        return sum(r.chk.isChecked() for t, r in self.rows.items()
                   if t not in HERO and not on_top(t))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # only a new width: fewer voices a row makes it taller, and refitting on that
        # can flip it back and forth (the Apps tab's cards jumped up and down that way)
        if e.size().width() != e.oldSize().width():
            self._fit_width(self.width())

    def _fit_width(self, width: int):
        """As many voice cards a row as the width holds, at least one."""
        lay = self.layout()
        assert lay is not None   # made in __init__
        m = lay.contentsMargins()
        room = width - m.left() - m.right()
        least = LIST_MIN_W if self._listed else TILE_MIN_W
        cols = max(1, min(MAX_COLS, (room + TILE_GAP) // (least + TILE_GAP)))
        if cols != self._tile_cols:
            self._tile_cols = cols
            self._place_tiles()
            lay.activate()

    def _refresh(self):
        on = self.btn_power.isChecked()
        self.btn_power.setText(_("On") if on else _("Off"))
        self.btn_power.setAccessibleName(POWER_TEXT[on])
        self._show_picked()
        # only a voice that's actually in use is highlighted
        self.tiles.setExclusive(False)
        for name, b in self._tile.items():
            b.setChecked(on and name == self._preset)
        self.tiles.setExclusive(True)
        n = self._count_on()
        self._tweak_text = (ngettext("Edit voice  ·  {n} on", "Edit voice  ·  {n} on", n)
                            if n else _("Edit voice"))
        self.btn_tweak.setText(self._tweak_text)   # (_fit_picked may shorten it)
        self.btn_tweak.setAccessibleName(self._tweak_text)
        self._count_tabs()
        ne = self.effects_count()
        text = ngettext("Effects  ·  {n}", "Effects  ·  {n}", ne) if ne else _("Effects")
        self.btn_effects.setAccessibleName(text)
        self._effects_text = text
        self.btn_effects.setText(text)
        self._fit_picked()   # a longer count may not fit beside the name any more
        mine = self._preset in self.store.voices
        _enable(self.btn_share, mine, _("Turn on one of your saved voices to share it "
                                        "(or right-click its button)"))
        self._show_delay()

    def show_picked_row(self, room: bool | None = None):
        """The bar under the cards shows only while the voice changer is on: after
        Stop it went on naming the voice, as if it were still changing your mic.
        `room`: whether the Voice tab has a place for it now (its own tab showing)."""
        if room is not None:
            self._picked_room = room
        self.picked.setVisible(getattr(self, "_picked_room", True)
                               and self.btn_power.isChecked())

    def _show_picked(self):
        """The bar under the cards: the voice that's on, by name."""
        self.show_picked_row()
        name = self._preset
        shown = _("My own mix") if name == CUSTOM else voicefx.shown(name)
        pm = art.pixmap(art.voice_key(name), PICKED_ART) if name != CUSTOM else None
        if pm is None:
            pm = icons.icon(VOICE_ICONS.get(name, "wave"), "muted").pixmap(PICKED_ART,
                                                                            PICKED_ART)
        self.picked_pic.setPixmap(pm)
        self.picked_name.setText(shown)

    def _edited(self, etype: str = ""):
        if etype in KEEP:     # your mic clean-up, the Background: the voice stays picked
            self._refresh()
            self._emit()
            return
        self._preset = CUSTOM
        if not self.btn_power.isChecked() and any(r.chk.isChecked() for r in self.rows.values()):
            self.btn_power.blockSignals(True)
            self.btn_power.setChecked(True)   # touching an effect means you want it on
            self.btn_power.blockSignals(False)
        self._refresh()
        self._emit()

    def _emit(self):
        if hasattr(self, "_history") and not self._restoring:
            self._htimer.start()   # a drag's many changes: one step when it settles
        self._show_edit_state()
        self.changed.emit(self.spec())
