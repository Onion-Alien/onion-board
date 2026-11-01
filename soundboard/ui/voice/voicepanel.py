"""The Voice tab: lays out its cards (Clean mic, voice changer, AI voices, Languages,
add-ons) and the tab's bottom bar.

The cards live in their own files: `CleanMicPanel` (cleanmicpanel.py), `VoiceFxPanel`
(voicefxpanel.py), `SpeechPanel` (speechpanel.py) and `AiVoicePanel` (aivoicepanel.py).
`VoicePanel` owns the chain wiring between them. Its methods live in four mixins beside
it: `voicecombos` (My voice combos), `voiceswitch` (voices on and off), `voicecards` (the
cards, tabs and status chips) and `voiceaddons` (the add-ons list and finding add-ons).
"""
from __future__ import annotations

import html
import threading
from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from soundboard.addons import modules as mods
from soundboard.core import usage
from soundboard.mic import voicesetups
from soundboard import voicefx
from soundboard.online import net
from soundboard.speech.aivoice import AiVoiceController
from soundboard.speech.live import SpeechController
from soundboard.ui.kit import a11y, appstate
from soundboard.ui.kit.panel import Flow, UndoBar
from soundboard.ui.window.responsive import FitWidth
from soundboard.ui.voice.speechpanel import SpeechPanel
from soundboard.ui.voice.voicefxpanel import EffectRow, VoiceFxPanel
from soundboard.ui.voice.voicestatus import VoiceStatusBar
from soundboard.i18n import _
# the tab's parts (callers import their names from here too)
from soundboard.ui.voice.voicecombos import VoiceCombos
from soundboard.ui.voice.voiceswitch import VoiceSwitch
from soundboard.ui.voice.voicecards import (CARD_ICONS, ORDER, TAB_KEYS, TAB_NAMES,  # noqa: F401
                                            CardBadge, VoiceCards)
from soundboard.ui.voice.voiceaddons import ModulesList, VoiceAddons  # noqa: F401

__all__ = ["VoicePanel", "VoiceFxPanel", "SpeechPanel", "EffectRow"]


class VoicePanel(VoiceCombos, VoiceSwitch, VoiceCards, VoiceAddons, QWidget):
    """The Voice tab, shaped like the others: cards (live voice first, then the
    voice changer and add-ons) and the tab's bottom bar. Owns the chain wiring for
    the engine.

    `fx_changed(spec)` and `speech_changed(settings)` are for the main window to
    save in the config."""
    fx_changed = Signal(dict)
    speech_changed = Signal(dict)
    active_changed = Signal(bool)   # the voice changer or the computer voice is on / off
    clip_ready = Signal(object, str)   # a typed line saved as a sound (SpeechPanel)
    share_asked = Signal(str)   # Share to the store: the voice, as the Share window lists it
    light_changed = Signal(bool)   # Use less CPU switched by hand
    live_tabs_changed = Signal()   # a tab's "on" dot came or went (live_tabs)
    _scanned = Signal(object, object)   # the Refresh button's worker: (modules, AI voices)

    def set_light(self, on: bool):
        """Show Use less CPU as on or off (the main window decides; no signal)."""
        self.chk_light.blockSignals(True)
        self.chk_light.setChecked(bool(on))
        self.chk_light.blockSignals(False)

    def __init__(self, engine, fx_spec: dict | None = None, speech: dict | None = None):
        super().__init__()
        self.engine = engine
        self._active = None              # last is_active() sent out (active_changed)
        self.chain = voicefx.VoiceChain()
        engine.voice_chain = self.chain
        # the Background's loops (changed built-in sounds, board sounds), made on a
        # worker and handed straight to the chain
        from soundboard.voicefx import backdrop
        self.backdrop = backdrop.Maker(self.chain.set_beds)
        # the board's sounds (library.SoundMeta), for the Background: set by the main window
        self.board_sounds: Callable[[], list] = list
        self.modules = mods.discover()
        mods.load_effects(self.modules)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(8)
        # what's on and your mic level, whatever's folded or scrolled away: at the
        # bottom, just above the mixer (added below, after the cards; the Say bar on top)
        self.bar = VoiceStatusBar()
        # what Voices ON (or a grey chip's click) brings back, in the bar's order, and
        # the language that was being spoken in ("lang")
        self._back: list[str] = []
        self._back_lang = ""
        # the voice changer's ✕: ON won't turn its picked voice on until it's on again
        self._fx_forgot = False
        self._switching = False          # set_voices / toggle_one at work (_update_bar)
        self.bar.open_card.connect(self._open_card)
        self.bar.master_toggled.connect(self._master_flipped)
        self.bar.toggle.connect(self.toggle_one)
        self.bar.turn_off.connect(lambda k: (usage.used("voice-chip-off"), self.forget_one(k)))
        self.bar.reset_asked.connect(self.reset_voices)
        self.reset_undo = UndoBar(_("Put the voices back, exactly as they were"))
        outer.addWidget(self.reset_undo)   # in the window, so its card shows there
        scroll = self._scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        a11y.scroll_stop(scroll, _("Voice"))
        page = FitWidth()   # the voice changer fits itself to the width (_fit_width)
        body = QWidget()
        # the full width, in line with the Say bar above (the cards fill it: the voice
        # changer with more voices a row, the rest with their own rows)
        pl = QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(body)
        self._body = body
        pv = QVBoxLayout(body)
        pv.setContentsMargins(0, 4, 8, 12)   # left edge in line with the download bar
        pv.setSpacing(12)
        # a row of tabs, one card under it: the voice changer, AI voices, another
        # language, custom voices, add-ons (they wrap onto two lines when narrow).
        # They and My voice combos scroll away with the card: pinned above it, on a short
        # window they left the voices a sliver (the Say bar and the bottom bar stay)
        tab_row = QWidget()
        self._tab_flow = Flow(tab_row, gap=8)
        self._tab_group = QButtonGroup(self)
        self._tab_group.setExclusive(True)
        self._tabs: dict[str, QPushButton] = {}
        self._cards: dict[str, QFrame] = {}
        self._states: dict[str, QLabel] = {}
        head = self._head = QVBoxLayout()   # the tabs, then My voice combos (placed below)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        pv.addLayout(head)
        self._card_box = QVBoxLayout()
        self._card_box.setContentsMargins(0, 0, 0, 0)
        pv.addLayout(self._card_box, 1)   # all spare height here, none to the head
        # spare height goes under the card: each card is held at the top of its box
        # (_section), at its height for the width. Not pv.addStretch(): with a stretch
        # under it the card got its one-line height instead, so a card with wrapped text
        # was squeezed (controls shorter than they can be, text cut off) when narrow
        # "folded": Edit voice's folded effect cards ("fx.<type>"); "tab": the tab open
        saved_folds = speech.get("folded") if isinstance(speech, dict) else None
        self._folded = ({k for k in saved_folds if isinstance(k, str)}
                        if isinstance(saved_folds, list) else set())
        tab = speech.get("tab") if isinstance(speech, dict) else None
        if tab == "custom":
            tab = "addons"                # Custom voices joined Add-ons
        self._tab = tab if tab in TAB_KEYS else "fx"
        scroll.setWidget(page)
        # the tabs are the tab's heading: a line under them keeps them apart from My
        # setups (they looked like one row of the same buttons)
        tab_head = QWidget()
        th = QVBoxLayout(tab_head)
        th.setContentsMargins(0, 0, 0, 0)
        th.setSpacing(8)
        # Use less CPU, beside the tabs: it's for every voice, not one card. On by
        # itself in lite mode (the main window says which)
        self.chk_light = QCheckBox(_("Use less CPU"))
        self.chk_light.setToolTip(_(
            "For slower PCs: the voices use less CPU. The voice changer skips hiss "
            "removal and its robot voices and echoes are a little simpler. Speech "
            "recognition uses the smaller model if it's downloaded (other languages are "
            "heard a little less well) and translations are simpler. AI voices stay as they "
            "are: they can't get lighter without sounding worse. On by itself in lite mode."))
        self.chk_light.toggled.connect(self.light_changed)
        tabs_line = QHBoxLayout()
        tabs_line.setContentsMargins(0, 0, 0, 0)
        tabs_line.setSpacing(12)
        tabs_line.addWidget(tab_row, 1)
        tabs_line.addWidget(self.chk_light, 0, Qt.AlignmentFlag.AlignTop)
        th.addLayout(tabs_line)
        rule = QFrame()
        rule.setObjectName("voicetabrule")
        rule.setFixedHeight(1)
        th.addWidget(rule)
        head.addWidget(tab_head)
        # My voice combos: under the tabs, so it's there whichever part is showing
        self.setups = voicesetups.Store()   # (its bar is placed once the panels are made)
        outer.addWidget(scroll, 1)

        # Clean mic, the first tab: noise out of your mic before any voice. Unlike the
        # voices it stays on from last time: it doesn't change who you sound like
        from soundboard.ui.voice.cleanmicpanel import CleanMicPanel
        self.clean = CleanMicPanel(self.chain, engine,
                                   speech.get("clean") if isinstance(speech, dict) else None)
        self.clean.changed.connect(self._clean_changed)
        self.clean.live_changed.connect(self._clean_live)
        self._section("clean", self.clean, self.clean.title, self.clean.head)
        # its bar, as a voice's: its preset by name, and Edit for its Mic settings (no
        # Effects: it isn't a voice). Its pause turns it off with the bar kept, dimmed
        from soundboard.ui.voice.voicebar import VoiceBar
        self.clean_bar = VoiceBar(self.clean, self.clean.is_on, effects=False)
        self.clean_bar.btn_tweak.setText(_("Edit"))   # (not a voice: "Edit voice" was wrong)
        self.clean_bar.btn_tweak.setToolTip(_("Input volume, sensitivity, noise suppression "
                                              "and gain control"))
        self.clean_bar.edit_wanted.connect(self._edit_clean)
        self._clean_paused = False
        self._show_clean_bar()

        # the voice changer. It always starts off (the voice you picked is kept):
        # left on from last time, it changed your mic the moment the app opened.
        # (Hear it on a voice: a sample in your headphones only)
        self.fx = VoiceFxPanel({**voicefx.clean_spec(fx_spec), "enabled": False},
                               play_sample=lambda data: engine.play(
                                   "__fx_voice_sample", data, 1.0, preview=True))
        self.fx.changed.connect(self._fx_changed)
        # Edit voice's folded effect cards: "fx.<type>" in the same list
        self.fx.set_folded(k[3:] for k in self._folded if k.startswith("fx."))
        self.fx.folds_changed.connect(self._fx_folds)
        self._section("fx", self.fx, self.fx.title, self.fx.head)

        # Bottom: Speak another language (and the computer voice); right: AI voices, add-ons.
        self.controller = SpeechController(engine, self.chain, lambda ev: None)
        self.speech = SpeechPanel(self.controller, speech or {}, self.modules)
        self.speech.changed.connect(self.speech_changed)
        self.speech.changed.connect(lambda _s: self._emit_active())   # the tab's picture
        self.speech.downloaded.connect(lambda: self.addons.show_modules(self.modules))
        self.speech.clip_ready.connect(self.clip_ready)
        self.speech.live_changed.connect(lambda _on: self._emit_active())
        # AI voices: the live voice changer
        from soundboard.ui.voice.aivoicepanel import AiVoicePanel
        self.ai_controller = AiVoiceController(self.chain, lambda ev: None)
        saved = speech.get("ai") if isinstance(speech, dict) else None   # may be damaged
        self.ai = AiVoicePanel(self.ai_controller, saved, self.modules, engine)
        self.ai.changed.connect(self._ai_changed)
        self.ai.changed.connect(lambda _s: self._update_bar())   # the chip names the voice
        self.ai.live_changed.connect(self._ai_live)
        self.ai.effects_wanted.connect(lambda: (usage.used("voice-effects"),
                                                self.fx.open_effects(self.ai.btn_effects)))
        self.ai.modules_changed.connect(self.rescan_modules)
        self.ai._event.connect(lambda _ev: self._update_bar())   # starting -> on / failed
        self._ai_card = self._section("ai", self.ai, self.ai.title, self.ai.head)
        net.on_change(self._ai_net_changed)
        self.speech.live_changed.connect(self._speech_live)
        self.speech.lang_changed.connect(self._emit_active)
        self._section("speak", self.speech, self.speech.title, self.speech.head)
        # the computer voice's bar (a voice server's voice too): it has no voice cards
        from soundboard.ui.voice.voicebar import VoiceBar
        self.speak_bar = VoiceBar(self.speech, self.speech.livevoice.b_live.isChecked)
        self.speak_bar.effects_wanted.connect(lambda: (
            usage.used("voice-effects"), self.fx.open_effects(self.speak_bar.btn_effects)))
        self.speak_bar.edit_wanted.connect(self._edit_speak_voice)
        self._follow_offline()
        self.speech.custom_wanted.connect(lambda: self.show_tab("addons"))
        self.addons = ModulesList(self.speech.custom_title, self.speech.custom_box)
        self.addons.refresh.connect(self._rescan_in_background)
        self.addons.refresh.connect(self.speech.servers.check)   # the voice servers, again
        self._scanned.connect(self._apply_scan)
        self._scanning = False
        self.addons.show_modules(self.modules)
        self._section("addons", self.addons, self.addons.title)
        self.show_tab(self._tab if self._tabs[self._tab].isVisibleTo(self) else "fx")
        # as tall as a tab: Use less CPU sits level with the first row of them
        self.chk_light.setFixedHeight(self._tabs["fx"].sizeHint().height())

        from soundboard.ui.voice.voicesetupsbar import SetupsBar
        self.setups_bar = SetupsBar(self.setups, self.current_setup, self.use_setup,
                                    self.setup_icon, self.setup_words,
                                    copy_code=self.copy_setup_code,
                                    import_code=self.fx.import_code)
        head.addWidget(self.setups_bar)
        self.fx.take_code = self.take_code   # a code with an AI voice or a setup in it
        from soundboard.ui.store.storevoices import kind_name
        self.setups_bar.share = lambda n: self.share_asked.emit(f"{kind_name('setup')}: {n}")
        self.fx.share_asked.connect(lambda n: self.share_asked.emit(f"{kind_name('fx')}: {n}"))
        outer.insertWidget(0, self.speech.say_bar)   # on top: the bottom has the mixer
        # the voice is on but can't work (the mic won't open, an effect broke): sad Bun
        # says so across the top, with Try again (poll)
        from soundboard.ui.kit import oops
        self.oops = oops.OopsPanel(compact=True)
        self.oops.show_problem("", "", self.try_again)
        self.oops.hide()
        outer.insertWidget(1, self.oops)
        self._oops_for = ""
        # each voice that's on has its bar pinned under the cards, on every tab (the voice
        # changer's and an AI voice's both, when both are on): its Edit voice and Hear
        # it never scroll out of sight
        for _key, panel in self._barred():
            lay = panel.layout()
            assert lay is not None   # made in the panel's __init__
            lay.removeWidget(panel.picked)
            outer.addWidget(panel.picked)
            panel.picked.setProperty("pinned", True)
            panel.show_picked_row(True)
        self._make_bar_controls()
        outer.addWidget(self.bar)
        # cards or a list: one setting for both (the window keeps the voice changer's)
        self.fx.view_toggle.changed.connect(self.ai.set_view)
        self.fx.view_toggle.changed.connect(self.speech.set_view)
        self.ai.view_toggle.changed.connect(self.fx.view_toggle.changed)
        self.speech.view_toggle.changed.connect(self.fx.view_toggle.changed)
        self.fx.sound_list = lambda: [(m.id, m.name, list(m.tags)) for m in self.board_sounds()]
        self.chain.configure(self.fx.spec())
        self._update_backdrop(self.fx.spec())
        self._ai_effects_text()
        self._emit_active()

        # the voice changer's mic meter (only while the tab is showing)
        self._meter_timer = QTimer(self)
        self._meter_timer.timeout.connect(self._meter)
        appstate.slow_in_background(self, self._meter_timer, 50)   # behind a game

    def showEvent(self, e):
        super().showEvent(e)
        self._meter_timer.start(appstate.interval(50))

    def hideEvent(self, e):
        super().hideEvent(e)
        self._meter_timer.stop()   # no wake-ups while another tab is showing

    def _meter(self):
        if self.isVisible():
            e = self.engine
            self.bar.set_level(e.level_mic if e.mic_stream is not None else None)
            self._ticks = getattr(self, "_ticks", 0) + 1
            if self._ticks % 20 == 1:       # the devices' delay: once a second is plenty
                delay = getattr(e, "device_delay", None)
                s = delay() if callable(delay) else None
                self.fx.set_device_delay(s * 1000 if isinstance(s, (int, float)) else None)

    def fit_steps(self):
        """What the main window may hide here when it gets small (ui/window/responsive.py)."""
        from soundboard.ui.window import responsive as r
        return [(50, "w", r.hide(self.speech.say_stop)),
                # a short window: the picked voice's bar scrolls with the voices (still
                # there, under them) rather than the window turning into the mini player
                (45, "h", self._pin_picked_off)]

    def _barred(self):
        """The cards with a picked voice's bar: (tab key, panel). Clean mic's first, as
        the sound goes through it."""
        bars = (("clean", self.clean_bar), ("fx", self.fx), ("ai", self.ai))
        speak = getattr(self, "speak_bar", None)   # (made after the other cards)
        return bars + (("speak", speak),) if speak is not None else bars

    def set_view(self, view: str):
        """The voices as picture cards or a list, in both cards."""
        self.fx.set_view(view)
        self.ai.set_view(view)
        self.speech.set_view(view)

    def _pin_picked_off(self, compact: bool):
        """Pinned under the scrolling card, or (`compact`) at the end of its card (the
        voice changer's, AI voices' before More options), scrolling with it."""
        outer = self.layout()
        assert isinstance(outer, QVBoxLayout)
        for _key, panel in self._barred():
            picked = panel.picked
            if bool(picked.property("pinned")) != compact:
                continue
            own = panel.layout()
            assert isinstance(own, QVBoxLayout)
            outer.removeWidget(picked)
            own.removeWidget(picked)
            if compact:
                at = own.indexOf(self.ai.btn_opts) if panel is self.ai else own.count()
                own.insertWidget(at, picked)
            else:
                outer.insertWidget(outer.indexOf(self.bar), picked)
            picked.setProperty("pinned", not compact)
            picked.style().unpolish(picked)
            picked.style().polish(picked)
            panel.show_picked_row(True)   # (in its card: shown with it)

    def stack_steps(self):
        return []   # one card at a time: nothing to stack when narrow

    def poll(self):
        """Call from the UI's status timer: surfaces effects the chain had to bypass,
        and the red strip while the voice is on but can't work."""
        errors = dict(self.chain.errors)   # the mic thread writes it
        if errors:
            self.fx.show_errors(errors)
        why = self.problem()
        # no mic for two polls in a row: a mic being reopened (a device switch) is
        # closed for a moment, and the strip shouldn't flash for that
        gone = why == self._no_mic_text()
        self._no_mic_polls = getattr(self, "_no_mic_polls", 0) + 1 if gone else 0
        if gone and self._no_mic_polls >= 2:
            usage.used("voice-no-mic")
        self._show_problem("" if gone and self._no_mic_polls < 2 else why)

    def problem(self) -> str:
        """Why the voice that's on isn't working (rich text), or "": the mic won't open,
        or an effect had to be turned off after an error."""
        if not self.is_active():
            return ""
        mic = getattr(self.engine, "errors", {}).get("mic", "")
        errors = dict(self.chain.errors)
        why = (_("Your mic couldn't be opened: {error}", error=mic) if mic
               else _("A voice effect stopped after an error: {error}",
                      error=next(iter(errors.values()))) if errors else "")
        if not why and getattr(self.engine, "mic_stream", True) is None:
            return VoicePanel._no_mic_text()   # unplugged or none: the voice has nothing to change
        return html.escape(why, quote=False)

    @staticmethod
    def _no_mic_text() -> str:
        return html.escape(_("No mic is open, so there's no voice to change. Plug one in, "
                             "or pick it in Settings → Audio."), quote=False)

    def _show_problem(self, why: str):
        if why == self._oops_for:
            return
        self._oops_for = why
        if why:
            self.oops.show_problem(_("Your voice couldn't be switched on"), why,
                                   self.try_again)
        self.oops.setVisible(bool(why))

    def try_again(self):
        """Try again on the red strip: the effects once more, and the mic opened again
        (on a worker: opening a device never runs on the UI thread)."""
        self.chain.errors.clear()
        self.chain.configure(self.fx.spec())
        self.fx.show_errors({})
        eng = self.engine
        name = getattr(eng, "names", {}).get("mic")
        if ((getattr(eng, "errors", {}).get("mic") or getattr(eng, "mic_stream", True) is None)
                and hasattr(eng, "set_mic_device")):
            threading.Thread(target=lambda: eng.set_mic_device(name), daemon=True,
                             name="voice-retry-mic").start()
        self._oops_for = ""
        self.oops.hide()   # back if it still can't (the next poll)

    def add_recordings(self, shelf):
        """The Recordings list (ui.clipshelf.ClipShelf, voice=True): what the bar's
        Record keeps, just above the bar. It hides itself while it's empty."""
        self.recordings = shelf
        outer = self.layout()
        assert isinstance(outer, QVBoxLayout)
        outer.insertWidget(outer.indexOf(self.bar), shelf)

    def shutdown(self):
        """Closing the app, or the tab switched off in Settings > Tabs. A download or
        install still running finishes quietly (busy.emit) or, a translation, stops."""
        self._meter_timer.stop()
        self.clean.shutdown()
        if getattr(self, "recordings", None) is not None:
            self.recordings.shutdown()
        self.speech.installs._dl_cancel = True
        self.ai.shutdown()
        self.controller.shutdown()
        self.backdrop.close()
        self.engine.voice_chain = None
