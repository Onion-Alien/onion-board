"""The Voice tab's voice changer card: `VoiceFxPanel`. Its pieces have their own
modules: effect rows (effectrow.py), sliders and switches (fxcontrols.py) and voice
cards (voicetiles.py).

It follows panel.py's pattern: it owns its widgets and emits plain dicts
(`changed`) that the main window stores in the config.
"""
from __future__ import annotations

import html
import random
import threading
from collections.abc import Callable

import numpy as np

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QBoxLayout, QButtonGroup, QDialog, QFrame, QGridLayout, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton,
                               QScrollArea, QTabWidget, QVBoxLayout, QWidget)
from shiboken6 import isValid as qt_valid

from soundboard.core import errors, usage
from soundboard.mic import savedvoices
from soundboard import voicefx
from soundboard.speech import aipreview
from soundboard.ui.voice import art
from soundboard.ui.kit import busy, icons
from soundboard.ui.voice.aivoicebrowser import HEAR, MAKING, hear_button
from soundboard.ui.voice.groupbar import GroupBar, no_match
from soundboard.ui.kit.widgets import take_out
from soundboard.ui.kit.panel import (Flow, UndoBar, ViewToggle, hint_label, section_label,
                                     steady_number)
from soundboard.i18n import _, ngettext
from soundboard.ui.voice.fxcontrols import _enable
# (callers import these from here too)
from soundboard.ui.voice.fxcontrols import ParamSlider, Switch, param_text  # noqa: F401
from soundboard.ui.voice.voicetiles import (ALL, CUSTOM, FAVS, GROUP_ICONS, LIST_MIN_W, MAX_COLS,
                                            MINE, PICKED_ART, TILE_ART, TILE_GAP, TILE_MIN_W,
                                            VOICE_GROUPS, VOICE_ICONS, BigSwitch, VoiceTile,
                                            voice_group)
from soundboard.ui.voice.effectrow import (ADDON_GROUP, GROUPS, HERO, KEEP, MAIN_TAB, EffectRow,
                                           on_top)


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


POWER_TEXT = {False: _("Voice changer is OFF"), True: _("Voice changer is ON")}


class VoiceFxPanel(QWidget):
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
        self.btn_sample.hide()
        pb.addWidget(self.btn_sample)
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
        self.btn_save = QPushButton(_("Save as a voice"))
        icons.set_icon(self.btn_save, "plus")
        self.btn_save.setToolTip(_("Keep these settings as a voice with a name: it gets its "
                                   "own button under “Pick a voice”."))
        self.btn_save.clicked.connect(self.save_voice)
        srow.addWidget(self.btn_save)
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
        srow.addWidget(self.delay)
        bv.addWidget(self.tweak)

        # ---- the effects, a tab a group (one long page was too much to scroll):
        # Main has Pitch & voice and Clean up my mic, then Change the voice, Character,
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
        done = QHBoxLayout()
        done.setContentsMargins(16, 0, 16, 0)
        done.addStretch(1)
        btn_done = QPushButton(_("Done"))
        btn_done.setObjectName("primary")
        btn_done.clicked.connect(self.dlg.close)
        done.addWidget(btn_done)
        dv.addLayout(done)

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
        self._fill_saved()
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
        # (Clean up my mic is yours, not the voice's: it stays as it is)
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
        self._refresh()
        self._emit()

    def is_blank(self) -> bool:
        """No voice at all to turn on: your own mix with nothing in it (`clear_mix`)."""
        return (self._preset == CUSTOM and not self._extras and not any(
            r.chk.isChecked() for t, r in self.rows.items() if t != "cleanup"))

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
        what's on top of the voice). Clean up my mic is yours, not the voice's: it stays."""
        for t, r in self.rows.items():
            if t != "cleanup":
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
        self._refresh()
        self._emit()

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

    # ------------------------------------------------------------------ the window
    DLG_SIZE = QSize(660, 720)

    def _backdrop_row(self):
        """The Background's card (None before it's made, or an add-on took its place)."""
        from soundboard.ui.voice.backdroprow import BackdropRow
        row = self.rows.get("backdrop")
        return row if isinstance(row, BackdropRow) else None

    def open_effects(self):
        """The Effects pop-up, over the voice bar's button."""
        if self.effects_pop is None:
            from soundboard.ui.voice.effectspopup import EffectsPopup
            self.effects_pop = EffectsPopup(self)
        self.effects_pop.open_for(self.btn_effects)

    def on_top_state(self) -> dict:
        """What the Effects pop-up shows: {"layers": {layer: level}, "sounds": [(id,
        name, level)], "extras": {type: its slider's value}} (only what's on)."""
        from soundboard.ui.voice.effectspopup import EXTRAS
        from soundboard.voicefx import backdrop
        out: dict = {"layers": {}, "sounds": [], "extras": {}}
        row = self._backdrop_row()
        if row is not None and row.chk.isChecked():
            st = row.state()
            out["layers"] = {k: st.get(k, 0) for k in backdrop.LAYERS if st.get(k, 0) > 0}
            names = {sid: name for sid, name, _c in row._list()}
            out["sounds"] = [(d["id"], names.get(d["id"]) or _("Sound not found"),
                              d.get("level", 0.5)) for d in row.picked]
        for t, key in EXTRAS:
            cfg = self._extras.get(t)
            if cfg is not None and t in voicefx.REGISTRY:
                out["extras"][t] = cfg.get(key, voicefx.defaults(t).get(key, 0))
        return out

    def set_on_top(self, key: str, value: float | None):
        """Turn one thing on top of the voice on (at `value`), change it, or take it off
        (None): a Background layer ("rain"), a board sound ("sound:<id>") or an extra
        ("extra_echo")."""
        from soundboard.voicefx import backdrop
        row = self._backdrop_row()
        if key in backdrop.LAYERS or key.startswith("sound:"):
            if row is None:
                return
            if key.startswith("sound:"):
                sid = key[len("sound:"):]
                if value is None:
                    row._remove(sid)
                else:
                    row._level(sid, value)
            else:
                st = row.state()
                st[key] = 0.0 if value is None else value
                row.load(st)
            self._backdrop_on()
            return
        cls = voicefx.REGISTRY.get(key)
        if cls is None or not cls.extra:
            return
        if value is None:
            self._extras.pop(key, None)
        else:
            from soundboard.ui.voice.effectspopup import EXTRAS
            cfg = self._extras.get(key) or {"on": True, **voicefx.defaults(key)}
            cfg[dict(EXTRAS)[key]] = value
            self._extras[key] = cfg
        self._refresh()
        self._emit()

    def _backdrop_on(self):
        """The Background is on while it has a sound to play, off once it has none."""
        from soundboard.voicefx import backdrop
        row = self._backdrop_row()
        if row is None:
            return
        st = row.state()
        st["on"] = any(st.get(k, 0) > 0 for k in backdrop.LAYERS) or bool(row.picked)
        row.load(st)
        self._edited("backdrop")

    def board_sound_menu(self):
        """The board's sounds, to add one behind your voice (None: no Background)."""
        row = self._backdrop_row()
        if row is None:
            return None
        m = row.add_menu()
        m.triggered.connect(lambda _a: self._backdrop_on())   # picked: it goes on with it
        return m

    def effects_count(self) -> int:
        st = self.on_top_state()
        return len(st["layers"]) + len(st["sounds"]) + len(st["extras"])

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
                      - 2 * self.picked_box.spacing())
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

    # ------------------------------------------------------------------ saved voices
    def _roll_pool(self, on: str | None = None) -> list[str]:
        """The voices Random voice picks from: the cards shown, without your own mix
        and without the voice that's on now (`on`; None: the one that's on)."""
        if on is None:
            on = self._preset if self.btn_power.isChecked() else ""
        return [n for n in self._shown if n != CUSTOM and n != on]

    def roll(self, rng: random.Random | None = None) -> str:
        """Random voice: turn on one of the voices shown, never the one that's on.
        Returns its name ("" when there's nothing to pick)."""
        pool = self._roll_pool()
        if not pool:
            return ""
        name = (rng or random.Random()).choice(pool)
        self.pick(name)
        return name

    def effects_of(self, name: str) -> dict:
        """A voice's effects as the chain takes them ({type: {"on", setting...}}), without
        Clean up my mic (it's yours, not the voice's). Your own mix: as it is now."""
        if name in voicefx.PRESETS:
            return {t: {"on": True, **cfg} for t, cfg in voicefx.PRESETS[name].items()}
        if name in self.store.voices:
            fx = self.store.voices[name]
        elif name == self._preset or name == CUSTOM:
            fx = {t: r.state() for t, r in self.rows.items()}
        else:
            fx = self._custom
        return {t: dict(cfg) for t, cfg in fx.items()
                if not on_top(t) and isinstance(cfg, dict) and cfg.get("on")}

    def hear(self, name: str):
        """Hear it: a short line in the voice `name`, in your headphones only. Made off
        the UI thread (the first one asks Windows' speech voice for the line)."""
        if self.play_sample is None or self._hearing:
            return
        usage.used("voice-hear")
        effects = self.effects_of(name)
        self._hearing = True
        self.btn_sample.setText(MAKING)

        def work():
            try:
                busy.emit(self._sampled, aipreview.fx_sample(effects), "")
            except aipreview.PreviewError as e:
                busy.emit(self._sampled, None, str(e))
            except Exception as e:  # noqa: BLE001 - the button must come back
                busy.emit(self._sampled, None, errors.plain(e))
        threading.Thread(target=work, name="voice-sample", daemon=True).start()

    def _sample_done(self, data, err: str):
        self._hearing = False
        self.btn_sample.setText(HEAR)
        if data is not None and self.play_sample is not None:
            self.play_sample(data)
        elif err:
            busy.toast(self._parent(), html.escape(
                _("⚠ Couldn't play a sample: {error}", error=err)), "warn")

    def _tile_clicked(self, name: str):
        """A voice card: that voice, on. The one that's on already: the voice changer
        off (a second click undoes the first, no hunting for the switch)."""
        if self.btn_power.isChecked() and name == self._preset:
            self.btn_power.setChecked(False)   # its toggled handler applies it
            return
        self.pick(name)

    def _make_tile(self, name: str, title: str, pic, line_icon: str) -> VoiceTile:
        """A checkable voice card: its picture (ui/voice/art.py), else a line icon, with the
        name under it."""
        b = VoiceTile(title)
        if self._listed:
            b.set_listed(True)
        if pic is not None:
            b.setIcon(pic)
            b.setProperty("art", True)
        else:
            b.setIcon(icons.icon(line_icon, "muted"))
        b.setIconSize(QSize(TILE_ART, TILE_ART))   # a line icon: as tall as a picture
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(lambda __=False, n=name: self._tile_clicked(n))
        if name != CUSTOM:
            b.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            b.customContextMenuRequested.connect(
                lambda pos, n=name, w=b: self._tile_menu(n, w.mapToGlobal(pos)))
        b.star.setChecked(name in self._favs)
        b.star.toggled.connect(lambda on, n=name: self.set_favorite(n, on))
        self.tiles.addButton(b)
        self._tile[name] = b
        return b

    def _fill_saved(self):
        """(Re)make the saved voices' tiles, after "My own mix"."""
        for b in self._saved_tiles:
            self.tiles.removeButton(b)
            self._tile_grid.removeWidget(b)
            self._tile = {n: t for n, t in self._tile.items() if t is not b}
            b.hide()   # until it's gone it would paint over the regrown grid
            b.deleteLater()
        self._saved_tiles = []
        for name in self.store.voices:
            b = self._make_tile(name, name, art.icon(art.voice_key(CUSTOM)), "sliders")
            b.setToolTip(_("Your saved voice “{name}”. Click to turn the voice changer on "
                           "with it; right-click to rename or delete it.", name=name))
            self._saved_tiles.append(b)
        self._place_tiles()
        self.btn_bin.setVisible(bool(self.store.deleted))
        self._refresh()

    def _place_tiles(self):
        """The cards the picked chip shows: All under a heading per group, else one
        group (or your favorites, in the order you starred them) without headings."""
        g, cols = self._tile_grid, self._tile_cols
        names = list(voicefx.PRESETS) + [CUSTOM] + [n for n in self.store.voices
                                                    if n in self._tile]
        for w in (*self._tile.values(), *self._heads.values(), self.random_tile):
            g.removeWidget(w)
        rows: list[tuple[str, list[str]]]
        if self._group == ALL:
            rows = [(k, [n for n in names if voice_group(n) == k])
                    for k in (*(k for k, _t, _n in VOICE_GROUPS), MINE)]
        elif self._group == FAVS:
            rows = [("", [n for n in self._favs if n in self._tile])]
        else:
            rows = [("", [n for n in names if voice_group(n) == self._group])]
        found = self.bar.text()
        if found:
            rows = [(k, [n for n in ns if self.bar.matches(self._tile[n].title, n)])
                    for k, ns in rows]
        shown: set[str] = set()
        self._shown = []
        r = last = last_n = 0
        for head, group in rows:
            if not group:
                continue
            if head:
                g.addWidget(self._heads[head], r, 0, 1, cols)
                r += 1
            for i, n in enumerate(group):
                g.addWidget(self._tile[n], r + i // cols, i % cols)
            last, last_n = r, len(group)
            r += (len(group) + cols - 1) // cols
            shown.update(group)
            self._shown += group
        # the die, right after the last card, while there are two voices to pick from
        rolls = not found and len(self._roll_pool(on="")) >= 2
        if rolls:
            g.addWidget(self.random_tile, last + last_n // cols, last_n % cols)
        self.random_tile.setVisible(rolls)
        for k, lbl in self._heads.items():
            lbl.setVisible(self._group == ALL and any(voice_group(n) == k for n in shown))
        for n, b in self._tile.items():
            b.setVisible(n in shown)
        self.no_favs.setVisible(self._group == FAVS and not shown and not found)
        no_match(self.no_match, found, shown)
        for c in range(MAX_COLS):
            g.setColumnStretch(c, 1 if c < cols else 0)

    def set_view(self, view: str):
        """Picture cards, or a list: small pictures beside the names, more a screen."""
        self._listed = view == "list"
        self.view_toggle.set_view(view)
        for b in self._tile.values():
            b.set_listed(self._listed)
        self._tile_cols = 0   # refit for the new width a voice needs
        self._fit_width(self.width())

    def show_group(self, key: str):
        """Show one chip's voices (ALL, FAVS, MINE or a VOICE_GROUPS key)."""
        self._group = key
        self.bar.set_group(key)
        self._place_tiles()

    def _group_count(self, key: str) -> int:
        """How many voices a group holds (the dropdown's numbers)."""
        names = [*voicefx.PRESETS, CUSTOM, *(n for n in self.store.voices if n in self._tile)]
        if key == ALL:
            return len(names)
        if key == FAVS:
            return sum(n in self._tile for n in self._favs)
        return sum(voice_group(n) == key for n in names)

    @property
    def favorites(self) -> list[str]:
        return list(self._favs)

    def set_favorite(self, name: str, on: bool):
        """Star or unstar a voice: Favorites lists them in the order you starred them."""
        if on == (name in self._favs):
            return
        if on:
            usage.used("voice-favorite")   # the name only (usage.py)
            self._favs.append(name)
        else:
            self._favs.remove(name)
        b = self._tile.get(name)
        if b is not None and b.star.isChecked() != on:
            b.star.setChecked(on)   # (toggled comes back here and finds nothing to do)
        if self._group == FAVS:
            self._place_tiles()
        self._emit()

    def _ask_name(self, title: str, text: str, keep: str = "") -> str:
        """A name for a saved voice, or "" if cancelled. Built-in voices' names are
        taken; so is another saved voice's, unless you agree to replace it (`keep` is
        the voice being renamed, whose own name is fine)."""
        builtin = self._builtin_names()
        while True:
            name, ok = QInputDialog.getText(self._parent(), title, _("Name:"),
                                            QLineEdit.EchoMode.Normal,
                                            text)
            name = savedvoices.clean_name(name) if ok else ""
            if not name:
                return ""
            if name.casefold() in builtin:
                QMessageBox.information(self._parent(), title,
                                        _("“{name}” is a built-in voice's name. "
                                          "Pick another one.", name=name))
                text = name
                continue
            other = self.store.find(name)
            if other is None or other == keep:
                return name
            if QMessageBox.question(self._parent(), title,
                                    _("You already have a voice called “{name}”. Replace it?",
                                      name=other)) == QMessageBox.StandardButton.Yes:
                return other
            text = name

    def save_voice(self):
        """Fine-tune's "Save as a voice": what's in Fine-tune now, under a name, as a
        tile of its own (picked straight away)."""
        suggestion = self._based_on or self.store.free_name(_("My voice"))
        if self.store.full() and self.store.find(suggestion) is None:
            busy.toast(self._parent(), html.escape(self._full_text()), "warn", 8000)
            return
        name = self._ask_name(_("Save as a voice"), suggestion)
        if not name:
            return
        effects = {t: r.state() for t, r in self.rows.items()}
        if self._mine():
            self._custom = effects   # "My own mix" stays what it was too
        name = self.store.put(name, effects)
        usage.used("voice-saved")   # the name only (usage.py), never the voice's
        self._preset, self._own, self._based_on = name, False, name
        self._fill_saved()
        self._emit()
        busy.flash(self.btn_save, _("✓ Saved"))
        # the flash is gone in a second: the card says it stuck, and under what name
        busy.toast(self._parent(), html.escape(_("Saved “{name}”.", name=name)), "ok")

    def voice_names(self) -> set[str]:
        """The voices a hotkey can pick: the ready ones and your saved ones."""
        return {n for n in self._tile if n != CUSTOM}

    def saved_names(self) -> list[str]:
        return list(self.store.voices)

    def title_of(self, name: str) -> str:
        """What a voice's card calls it."""
        return voicefx.shown(name) if name in voicefx.PRESETS else name

    def _tile_menu(self, name: str, at):
        """A voice card's right-click menu: its hotkey, and for a saved voice rename,
        share and delete."""
        from soundboard.ui.kit.hotkeypick import pretty_key
        m = QMenu(self)
        if self.play_sample is not None:
            m.addAction(icons.icon("headphones"), HEAR, lambda: self.hear(name))
            m.addSeparator()
        key = self.keys.get(name, "")
        m.addAction(icons.icon("keyboard"),
                    _("Hotkey: {key}…", key=pretty_key(key)) if key else _("Set a hotkey…"),
                    lambda: self.hotkey_asked.emit(name))
        if key:
            m.addAction(icons.icon("close"), _("Clear hotkey"),
                        lambda: self.hotkey_cleared.emit(name))
        if name in self.store.voices:
            m.addSeparator()
            m.addAction(icons.icon("edit"), _("Rename"), lambda: self.rename_voice(name))
            m.addAction(icons.icon("copy"), _("Copy share code"), lambda: self.copy_code(name))
            m.addAction(icons.icon("upload"), _("Share to the store…"),
                        lambda: self.share_asked.emit(name))
            m.addAction(icons.icon("trash", "danger_text"), _("Delete"),
                        lambda: self.delete_voice(name))
        m.exec(at)

    @staticmethod
    def _full_text() -> str:
        return ngettext("You have {n} saved voice, the most there can be. Delete one "
                        "(right-click it) first.",
                        "You have {n} saved voices, the most there can be. Delete one "
                        "(right-click it) first.", savedvoices.MAX_VOICES)

    def _parent(self) -> QWidget:
        """Where a question goes: over Edit voice while it's open."""
        return self.dlg if self.dlg.isVisible() else self

    def copy_code(self, name: str) -> str:
        """A saved voice as a share code, onto the clipboard. Returns the code."""
        effects = self.store.voices.get(name)
        if effects is None:
            return ""
        code = savedvoices.share_code(name, effects)
        QGuiApplication.clipboard().setText(code)
        usage.used("voice-code-shared")
        if self.dlg.isVisible() and name == self._preset:
            busy.flash(self.btn_share, _("✓ Copied"))
        else:
            self.undo_bar.finish()
            self._note(_("Copied “{name}” as a share code", name=name))
        return code

    def _note(self, text: str):
        """A short result, as a corner card."""
        busy.toast(self._parent(), html.escape(text), "ok")

    def import_code(self, text: str | None = None) -> str:
        """Add a voice from a share code (asked for if not given) as a new saved voice,
        renamed if the name's taken, and turn it on; a code holding an AI voice or a
        setup goes to `take_code`. Returns the name it got ("" if none)."""
        title = _("Import a voice code")
        if text is None:
            text, ok = QInputDialog.getText(self._parent(), title,
                                            _("Paste the code someone sent you:"),
                                            QLineEdit.EchoMode.Normal, "")
            if not ok:   # OK on an empty box gets read_code's "There's no code there."
                return ""
        from soundboard.online import storevoices
        try:
            v, notes = storevoices.read_code(text)
        except savedvoices.CodeError as e:
            busy.toast(self._parent(), html.escape(str(e)), "warn")
            return ""
        if v.kind != "fx":
            return self.take_code(v, notes) if self.take_code is not None else ""
        name, effects = v.name, v.effects
        if self.store.full():
            busy.toast(self._parent(), html.escape(self._full_text()), "warn", 8000)
            return ""
        if name.casefold() in self._builtin_names():
            name = f"{name[:savedvoices.MAX_NAME - 9]} (shared)"
        name = self.store.free_name(name)
        on = [voicefx.shown(voicefx.REGISTRY[t].name) for t in effects]
        ask = (_("Add the voice “{name}”?<br><br>Effects: {effects}", name=html.escape(name),
                 effects=(html.escape(", ".join(on)) if on
                          else _("none (your normal voice)")))
               + "".join(f"<br><br>{html.escape(n)}" for n in notes))
        if QMessageBox.question(self._parent(), title, ask) != QMessageBox.StandardButton.Yes:
            return ""
        name = self.store.put(name, effects)
        usage.used("voice-code-imported")
        self._fill_saved()
        self.pick(name)
        if self.dlg.isVisible():
            busy.flash(self.btn_import, _("✓ Added"))
        else:   # nothing else would say it worked
            busy.toast(self._parent(), _("Added the voice “{name}”", name=html.escape(name)),
                       "ok")
        return name

    @staticmethod
    def _builtin_names() -> set[str]:
        return savedvoices.builtin_names()

    def rename_voice(self, old: str):
        new = self._ask_name(_("Rename voice"), old, keep=old)
        if not new or new == old:
            return
        if self.store.find(new) not in (None, old):
            self.store.remove(new)   # agreed to replace it (it goes to the bin)
            if self._preset == new:
                self._preset = CUSTOM
        new = self.store.rename(old, new)
        if not new:
            return
        if self._preset == old:
            self._preset = new
        if self._based_on == old:
            self._based_on = new
        self._favs = [new if n == old else n for n in self._favs]
        self._fill_saved()
        self.renamed.emit(old, new)
        self._emit()

    def delete_voice(self, name: str):
        """Into the bin (Undo for a few seconds, "Recently deleted" for a month).
        If it was on, the voice you hear doesn't change: it shows as "My own mix"."""
        item = self.store.remove(name)
        if item is None:
            return
        was_on = self._preset == name
        if was_on:
            self._preset = CUSTOM
        if self._based_on == name:
            self._based_on = ""
        self._fill_saved()
        self._emit()
        self.undo_bar.show_for(_("Deleted the voice “{name}”", name=name),
                               lambda: self._undelete(item.id, was_on))

    def _undelete(self, item_id: str, was_on: bool = False) -> str:
        item = self.store.take(item_id)
        if item is None:
            return ""
        name = self.store.restore(item, item.index)
        # still sounding just like it (nothing touched since): it's the one that's on
        if was_on and self._preset == CUSTOM and \
                {t: r.state() for t, r in self.rows.items()} == self.store.voices[name]:
            self._preset = name
        self._fill_saved()
        self._emit()
        return name

    def show_deleted(self):
        from soundboard.ui.sounds.deleted import DeletedDialog
        self.undo_bar.finish()

        def back(item) -> bool:   # DeletedDialog has taken it out of the bin already
            self.store.restore(item, item.index)   # in its old place, as Undo does
            self._fill_saved()
            self._emit()
            return True
        DeletedDialog(savedvoices.VOICE, "voices", back, self, source=self.store).exec()
        self._fill_saved()

    def merge_saved(self, raw) -> int:
        """Add a backup's saved voices (the ones not here by name). Returns how many."""
        added = self.store.merge(raw)
        if added:
            self._fill_saved()
        return added

    def set_device_delay(self, ms: float | None):
        """Your sound devices' own delay (mic in + send device out), from the engine."""
        if ms != self._device_ms:
            self._device_ms = ms
            self._show_delay()

    def effects_delay(self) -> float:
        """Milliseconds the effects that are on add (worked out from their settings, so
        it's known before the mic has sent anything)."""
        if not self.btn_power.isChecked():
            return 0.0
        total = 0.0
        for t, r in self.rows.items():
            if not r.chk.isChecked():
                continue
            if r.cls.latency is voicefx.Effect.latency:
                continue   # never delays the voice: no throwaway effect to ask (Robot's ~1 ms)
            st = r.state()
            key = (t, tuple(sorted(st.items())))
            if key not in self._delay_cache:
                if len(self._delay_cache) > 256:
                    self._delay_cache.clear()
                try:
                    self._delay_cache[key] = max(0.0, float(r.cls(48000, st).latency()))
                except Exception:  # noqa: BLE001 - an add-on's effect: not counted
                    self._delay_cache[key] = 0.0
            total += self._delay_cache[key]
        return total * 1000

    def _show_delay(self):
        on = self.btn_power.isChecked()
        self.delay.setVisible(on)
        if not on:
            return
        fx = self.effects_delay()
        dev = self._device_ms
        total = fx + (dev or 0.0)
        self.delay.setText(_("{ms} ms delay", ms=f"{total:.0f}"))
        if dev is None:
            tip = _("How far behind your real voice the changed one is: {effects} ms from the "
                    "effects. Under about 100 ms feels normal to talk over; pitch effects "
                    "cost the most, the rest almost nothing.", effects=f"{fx:.0f}")
        else:
            tip = _("How far behind your real voice the changed one is: {effects} ms from the "
                    "effects + {devices} ms from your sound devices. Under about 100 ms feels "
                    "normal to talk over; pitch effects cost the most, the rest almost "
                    "nothing.", effects=f"{fx:.0f}", devices=f"{dev:.0f}")
        self.delay.setToolTip(tip)
        slow = total > 120
        if bool(self.delay.property("slow")) != slow:
            self.delay.setProperty("slow", slow)
            self.delay.style().unpolish(self.delay)
            self.delay.style().polish(self.delay)

    def add_new_effects(self):
        """Add cards for effect types registered since (modules loaded later)."""
        added = False
        for etype, cls in voicefx.REGISTRY.items():
            if etype in self.rows or cls.extra:   # (the extras live in the Effects pop-up)
                continue
            cfg = self._spec_effects.get(etype)
            if cfg is None:
                # mic clean-up starts on: it only makes changed voices sound better
                cfg = {"on": True} if etype == "cleanup" else {}
            if etype == "backdrop":
                from soundboard.ui.voice.backdroprow import BackdropRow
                r = BackdropRow(cls, cfg, lambda: self.sound_list())
            else:
                r = EffectRow(cls, cfg, hero=etype in HERO)
            r.changed.connect(lambda t=etype: self._edited(t))
            r.set_folded(etype in self._folded_fx)
            r.folded_changed.connect(lambda f, t=etype: self._card_folded(t, f))
            r.reshaped.connect(self._reshape)
            if etype in HERO:
                self.hero_box.insertWidget(min(HERO.index(etype), self.hero_box.count()), r)
            self.rows[etype] = r
            added = True
        if added:
            self._place_cards()

    def set_folded(self, types):
        """Fold these effects' cards (the rest open): what `folds_changed` said last time."""
        self._folded_fx = {t for t in types if isinstance(t, str)}
        for t, r in self.rows.items():
            r.set_folded(t in self._folded_fx)

    def _card_folded(self, etype: str, folded: bool):
        (self._folded_fx.add if folded else self._folded_fx.discard)(etype)
        self.folds_changed.emit(sorted(self._folded_fx))

    def _ordered_cards(self) -> list[tuple[str, list[EffectRow]]]:
        """(group title, its cards) in reading order; add-on effects last."""
        grouped: set[str] = set(HERO)
        for _title, types in GROUPS:
            grouped.update(types)
        out = []
        for title in self._pages:
            types = dict(GROUPS).get(title) or [t for t in self.rows if t not in grouped]
            out.append((title, [self.rows[t] for t in types if t in self.rows]))
        return out

    @staticmethod
    def _card_height(c: QWidget, width: int) -> int:
        return c.heightForWidth(width) if c.hasHeightForWidth() else c.sizeHint().height()

    def _place_cards(self):
        """Each tab's cards into its columns: one column, or two with each card under
        whichever column is shorter so far (in reading order), so a short card never
        leaves a hole beside a tall one. A tab with no cards (Add-ons) is hidden."""
        plans = {}
        for title, cards in self._ordered_cards():
            if self._fx_cols == 1:
                plan = [list(cards), []]
            else:
                room = self.more.width() - 4
                width = max(200, (room - self._pages[title][1].spacing()) // 2)
                plan, heights = [[], []], [0, 0]
                for c in cards:
                    i = 0 if heights[0] <= heights[1] else 1
                    plan[i].append(c)
                    heights[i] += self._card_height(c, width) + 10
            plans[title] = plan
        if plans != self._placed:
            self._placed = plans
            for title, plan in plans.items():
                scroll, row, cols = self._pages[title]
                for col in cols:
                    while col.count() > 1:           # all but the stretch
                        take_out(col)
                for col, widgets in zip(cols, plan):
                    for w in widgets:
                        col.insertWidget(col.count() - 1, w)   # above the column's stretch
                row.setStretch(1, 1 if self._fx_cols == 2 else 0)
                self.more.setTabVisible(self.more.indexOf(scroll), any(plan))
        self._count_tabs()

    def _count_tabs(self):
        """Each group's tab says how many of its effects are on, so none is missed
        behind another tab (Main is the first one seen: no count)."""
        for title, cards in self._ordered_cards():
            scroll = self._pages[title][0]
            n = sum(c.chk.isChecked() for c in cards)
            text = (ngettext("{group}  ·  {n} on", "{group}  ·  {n} on", n, group=title)
                    if n else title)
            i = self.more.indexOf(scroll)
            if self.more.tabText(i) != text:
                self.more.setTabText(i, text)

    def _reshape(self):
        """A card got taller or shorter (on/off, folded): balance the columns again."""
        if self._fx_cols == 2:
            self._replace.start()

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
        self.btn_sample.setVisible(self.play_sample is not None)

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
        self.changed.emit(self.spec())
