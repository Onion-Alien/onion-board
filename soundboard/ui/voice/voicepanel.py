"""The Voice tab: lays out its cards (voice changer, AI voices, Languages, add-ons)
and the tab's bottom bar.

The cards live in their own files: `VoiceFxPanel` (voicefxpanel.py), `SpeechPanel`
(speechpanel.py) and `AiVoicePanel` (aivoicepanel.py). `VoicePanel` owns the chain
wiring between them; this file also has the add-ons list.
"""
from __future__ import annotations

import html
import threading
from collections.abc import Callable

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from soundboard.addons import modules as mods
from soundboard.core import langnames, usage
from soundboard.mic import savedvoices, voicesetups
from soundboard.ui.kit import theme
from soundboard import voicefx
from soundboard.online import net
from soundboard.speech import spoken, translation
from soundboard.speech.aivoice import AiVoiceController
from soundboard.speech.live import SpeechController
from soundboard.ui.kit import a11y, appstate, busy, icons
from soundboard.ui.voice import art
from soundboard.ui.kit.panel import Flow, card, hint_label, icon_button, section_label
from soundboard.ui.responsive import FitWidth
from soundboard.ui.voice.speechpanel import LIVE_MODULE, SpeechPanel
from soundboard.ui.voice.voicefxpanel import CUSTOM, EffectRow, VoiceFxPanel, on_top
from soundboard.ui.voice.voicestatus import VoiceStatusBar
from soundboard.i18n import _
from soundboard.ui.kit.pixels import snap_to_pixels

__all__ = ["VoicePanel", "VoiceFxPanel", "SpeechPanel", "EffectRow"]


class ModulesList(QWidget):
    """`refresh` asks for a rescan (the Voice tab does it off the UI thread); the
    button stays on "Checking…" until the next show_modules()."""
    refresh = Signal()
    shown = Signal()

    def __init__(self, voices_title: QLabel | None = None, voices: QWidget | None = None):
        """`voices_title` and `voices`: the custom voices part, under the list."""
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        self.title = section_label(_("Add-ons"))
        v.addWidget(self.title)
        self.list = QVBoxLayout()
        self.list.setSpacing(10)
        v.addLayout(self.list)
        row = QHBoxLayout()
        b = self.b_refresh = QPushButton(_("Refresh"))
        b.clicked.connect(self._refresh)
        o = icon_button("folder", _("Open folder"), hover=False)
        o.clicked.connect(lambda: SpeechPanel._open_folder(btn=o))
        row.addWidget(b)
        row.addWidget(o)
        row.addStretch(1)
        v.addLayout(row)
        if voices is not None:
            if voices_title is not None:
                v.addWidget(voices_title)
            v.addWidget(voices)

    def _refresh(self):
        if busy.is_busy(self.b_refresh):
            return   # already checking: a double click mustn't start it twice
        busy.hold_until(self.b_refresh, _("Checking…"), self.shown, lambda: _("✓ Up to date"))
        self.refresh.emit()

    def show_modules(self, infos: list[mods.ModuleInfo]):
        while self.list.count():
            item = self.list.takeAt(0)
            w = item.widget() if item else None
            if w:
                w.deleteLater()
        e = html.escape   # error text is often "<class ...>"-shaped

        def row(text: str, tip: str):
            lbl = hint_label(text)
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setToolTip(tip)
            self.list.addWidget(lbl)
        # the Voice tab's own add-ons only: Onion Watch lives on the Triggers tab (and
        # Settings → Add-ons), and the languages share one line
        voice = [m for m in infos if m.kind not in ("triggers", "remote")]
        langs = [m for m in voice if m.kind == "translation" and not m.error]
        for m in voice:
            if m in langs:
                continue
            if m.error:
                state = f"⚠ {m.error}"
            elif m.kind == "service" and m.broken:
                state = _("stopped working: needs a repair")
            elif m.kind == "service" and not m.installed:
                state = (_("not set up yet: press Install speech recognition above")
                         if m.id == LIVE_MODULE and not net.offline() else _("not set up yet"))
            elif m.kind == "effects":
                state = _("on") if m.loaded else _("not loaded")
            else:
                state = _("ready")
            row(f"<b>{e(m.name)}</b> {e(m.version)} · {e(state)}",
                f"{m.description}" + chr(10) + str(m.path))
        if langs:
            have = [langnames.of(m) for m in langs if m.installed]
            more = [langnames.of(m) for m in langs if not m.installed]
            parts = [_("{languages} downloaded", languages=", ".join(have))] if have else []
            if more and not net.offline():   # Offline mode: nothing can be downloaded
                parts.append(_("{languages} can be downloaded under Speak in",
                               languages=", ".join(more)))
            row(_("<b>Languages</b> · {state}", state=e("; ".join(parts))),
                chr(10).join(_("{language}: {size} MB", language=langnames.of(m),
                               size=translation.size_mb(m))
                             for m in langs))
        if not voice:
            self.list.addWidget(hint_label(_("No voice add-ons installed.")))
        self.shown.emit()


class CardBadge(QWidget):
    """A small, theme-coloured emblem for a Voice card's header."""

    def __init__(self, name: str):
        super().__init__()
        self.name = name
        self.setFixedSize(36, 36)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, _event):
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = QColor(theme.T["accent"])
        wash = QColor(accent)
        wash.setAlpha(32)
        soft = QColor(accent)
        soft.setAlpha(12)
        edge = QColor(accent)
        edge.setAlpha(55)
        bg = QLinearGradient(0, 0, 36, 36)
        bg.setColorAt(0, wash)
        bg.setColorAt(1, soft)
        p.setBrush(bg)
        p.setPen(edge)
        p.drawRoundedRect(QRectF(0.5, 0.5, 35, 35), 10, 10)
        icons.icon(self.name, "accent").paint(p, 7, 7, 22, 22)
        p.end()


CARD_ICONS = {"fx": "voice", "ai": "wave", "speak": "browser", "addons": "puzzle"}
TAB_KEYS = tuple(CARD_ICONS)   # the Voice tab's own tabs, in order
ORDER = ("fx", "ai", "speak", "lang")   # the status bar's chips, as the sound goes through
TAB_NAMES = {"fx": lambda: _("Voice changer"), "ai": lambda: _("AI voices"),
             "speak": lambda: _("Languages"), "addons": lambda: _("Add-ons")}


class VoicePanel(QWidget):
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
    _scanned = Signal(object, object)   # the Refresh button's worker: (modules, AI voices)

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
        self._switching = False          # set_voices / toggle_one at work (_update_bar)
        self.bar.open_card.connect(self._open_card)
        self.bar.master_toggled.connect(self._master_flipped)
        self.bar.toggle.connect(self.toggle_one)
        self.bar.turn_off.connect(lambda k: (usage.used("voice-chip-off"), self.forget_one(k)))
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
        # They and My setups scroll away with the card: pinned above it, on a short
        # window they left the voices a sliver (the Say bar and the bottom bar stay)
        tab_row = QWidget()
        self._tab_flow = Flow(tab_row, gap=8)
        self._tab_group = QButtonGroup(self)
        self._tab_group.setExclusive(True)
        self._tabs: dict[str, QPushButton] = {}
        self._cards: dict[str, QFrame] = {}
        self._states: dict[str, QLabel] = {}
        head = self._head = QVBoxLayout()   # the tabs, then My setups (placed below)
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
        th.addWidget(tab_row)
        rule = QFrame()
        rule.setObjectName("voicetabrule")
        rule.setFixedHeight(1)
        th.addWidget(rule)
        head.addWidget(tab_head)
        # My setups: under the tabs, so it's there whichever part is showing
        self.setups = voicesetups.Store()   # (its bar is placed once the panels are made)
        outer.addWidget(scroll, 1)

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
        self.ai.live_changed.connect(self._ai_live)
        self.ai.modules_changed.connect(self.rescan_modules)
        self.ai._event.connect(lambda _ev: self._update_bar())   # starting -> on / failed
        self._ai_card = self._section("ai", self.ai, self.ai.title, self.ai.head)
        net.on_change(self._ai_net_changed)
        self._ai_follow_offline()
        self.speech.live_changed.connect(self._speech_live)
        self.speech.lang_changed.connect(self._emit_active)
        self._section("speak", self.speech, self.speech.title)
        # speech recognition has to hear the app's language for any of it to work
        self._tabs["speak"].setVisible(spoken.heard())
        self.speech.custom_wanted.connect(lambda: self.show_tab("addons"))
        self.addons = ModulesList(self.speech.custom_title, self.speech.custom_box)
        self.addons.refresh.connect(self._rescan_in_background)
        self._scanned.connect(self._apply_scan)
        self._scanning = False
        self.addons.show_modules(self.modules)
        self._section("addons", self.addons, self.addons.title)
        self.show_tab(self._tab if self._tabs[self._tab].isVisibleTo(self) else "fx")

        from soundboard.ui.voice.voicesetupsbar import SetupsBar
        self.setups_bar = SetupsBar(self.setups, self.current_setup, self.use_setup,
                                    self.setup_icon, self.setup_words,
                                    copy_code=self.copy_setup_code,
                                    import_code=self.fx.import_code)
        head.addWidget(self.setups_bar)
        self.fx.take_code = self.take_code   # a code with an AI voice or a setup in it
        from soundboard.ui.storevoices import kind_name
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
        # the picked voice's bar, pinned under the cards while the voice changer (or AI
        # voices) shows: its Edit voice and Hear it never scroll out of sight
        for key, panel in self._barred():
            lay = panel.layout()
            assert lay is not None   # made in the panel's __init__
            lay.removeWidget(panel.picked)
            outer.addWidget(panel.picked)
            panel.picked.setProperty("pinned", True)
            panel.show_picked_row(self._tab == key)
        outer.addWidget(self.bar)
        # cards or a list: one setting for both (the window keeps the voice changer's)
        self.fx.view_toggle.changed.connect(self.ai.set_view)
        self.ai.view_toggle.changed.connect(self.fx.view_toggle.changed)
        self.fx.sound_list = lambda: [(m.id, m.name, list(m.tags)) for m in self.board_sounds()]
        self.chain.configure(self.fx.spec())
        self._update_backdrop(self.fx.spec())
        self._emit_active()

        # the voice changer's mic meter (only while the tab is showing)
        self._meter_timer = QTimer(self)
        self._meter_timer.timeout.connect(self._meter)
        appstate.slow_in_background(self, self._meter_timer, 50)   # behind a game

    def showEvent(self, e):
        super().showEvent(e)
        self._meter_timer.start(appstate.interval(50))

    # ---- My setups (voicesetups)
    def current_setup(self) -> dict:
        """What's on now as a setup: the voice changer's voice, the AI voice, the
        language spoken; {} when none of them is on. Its "name" is a suggestion."""
        out: dict = {}
        names = []
        if self.fx.btn_power.isChecked():
            effects = {t: c for t, c in self.fx.spec()["effects"].items()
                       if c.get("on") and not on_top(t)}
            if effects:
                name = self.fx.preset
                out["fx"] = "" if name == CUSTOM else name
                out["effects"] = effects
                names.append(_("My own mix") if name == CUSTOM else voicefx.shown(name))
        if self.ai.is_on():
            vid = self.ai.s.get("voice", "")
            vo = next((v for v in self.ai.voices if v.get("id") == vid), None)
            if vo is not None:
                out["ai"] = {"id": vid, "name": vo.get("name", vid),
                             "pitch": float(self.ai.s.get("pitch", 0.0) or 0.0)}
                names.append(out["ai"]["name"])
        lang = self.speech.cb_lang.currentData() or ""
        if lang:
            out["language"] = lang
            m = next((m for m in self.speech.langs if m.language == lang), None)
            names.append(langnames.of(m) if m is not None else lang)
        if out:
            out["name"] = " + ".join(names)[:voicesetups.MAX_NAME]
        return out

    def use_setup(self, setup: dict):
        """Turn a setup's whole mix on for your mic (what it hasn't got goes off)."""
        effects = setup.get("effects") or {}
        name = setup.get("fx") or ""
        saved = self.fx.store.voices.get(name)
        if not effects:
            self.fx.btn_power.setChecked(False)
        elif name in voicefx.PRESETS or (saved is not None and savedvoices.shared_effects(
                saved) == savedvoices.shared_effects(effects)):
            self.fx.pick(name)
        else:   # its own mix, or a voice of that name here that isn't the same one

            self.fx.use_mix(effects)
        ai = setup.get("ai")
        if ai and self.ai.module is not None and any(
                v.get("id") == ai["id"] for v in self.ai.voices):
            self.ai.use(ai["id"])
        else:
            self.ai.stop()
        i = self.speech.cb_lang.findData(setup.get("language") or "")
        self.speech.cb_lang.setCurrentIndex(max(0, i))
        self._update_heads()

    def copy_setup_code(self, name: str) -> bool:
        """A setup as a share code, onto the clipboard (its own AI voice's blend goes
        too, as nobody else has it). False if there's nothing in it to share."""
        from PySide6.QtGui import QGuiApplication

        from soundboard.online import storevoices
        setup = self.setups.setups.get(name)
        if setup is None:
            return False
        ai = setup.get("ai") or {}
        payload = storevoices.pack_setup(name, setup,
                                         self.ai.store.get(ai["id"]) if ai.get("id") else None)
        if not storevoices.can_share(payload):
            return False
        QGuiApplication.clipboard().setText(storevoices.share_code(payload))
        usage.used("setup-code-shared")
        return True

    def take_code(self, v, notes: list[str]) -> str:
        """An AI voice or setup from a share code (storevoices.Voice): asked about, then
        added to yours as a Store voice is. The name it got, "" if none."""
        from PySide6.QtWidgets import QMessageBox

        from soundboard.ui.storevoices import VoiceHooks, meta_line
        title = _("Import a voice code")
        ask = (_("Add “{name}”?", name=html.escape(v.name))
               + f"<br><br>{html.escape(meta_line(v))}"
               + "".join(f"<br><br>{html.escape(n)}" for n in notes))
        if QMessageBox.question(self, title, ask) != QMessageBox.StandardButton.Yes:
            return ""
        hooks = VoiceHooks(lambda: self)
        said = hooks.take(v)
        if hooks.last:
            usage.used("voice-code-imported")
        busy.toast(self, html.escape(said), "ok" if hooks.last else "warn")
        return hooks.last

    def setup_icon(self, setup: dict):
        """A setup's picture: its AI voice's emoji, else its voice changer voice's."""
        ai = setup.get("ai")
        vo = next((v for v in self.ai.voices if ai and v.get("id") == ai["id"]), None)
        if vo is not None:
            from soundboard.ui.voice.aivoicepanel import voice_icon
            return voice_icon(vo)
        pic = art.icon(art.voice_key(setup["fx"])) if setup.get("fx") else None
        return pic or icons.icon("sliders" if setup.get("effects") else "browser", "muted")

    def setup_words(self, setup: dict) -> str:
        """What's in a setup, in words."""
        parts = []
        if setup.get("effects"):
            fx = setup.get("fx") or ""
            parts.append(_("Voice changer: {voice}", voice=voicefx.shown(fx) if fx
                           else _("My own mix")))
        if setup.get("ai"):
            parts.append(_("AI voice: {voice}", voice=setup["ai"].get("name", "")))
        lang = setup.get("language")
        if lang:
            m = next((m for m in self.speech.langs if m.language == lang), None)
            parts.append(_("Speaks {language}", language=langnames.of(m) if m else lang))
        return " · ".join(parts)

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
        """What the main window may hide here when it gets small (ui/responsive.py)."""
        from soundboard.ui import responsive as r
        return [(50, "w", r.hide(self.speech.say_stop)),
                # a short window: the picked voice's bar scrolls with the voices (still
                # there, under them) rather than the window turning into the mini player
                (45, "h", self._pin_picked_off)]

    def _barred(self):
        """The cards with a picked voice's bar: (tab key, panel)."""
        return (("fx", self.fx), ("ai", self.ai))

    def set_view(self, view: str):
        """The voices as picture cards or a list, in both cards."""
        self.fx.set_view(view)
        self.ai.set_view(view)

    def _pin_picked_off(self, compact: bool):
        """Pinned under the scrolling card, or (`compact`) at the end of its card (the
        voice changer's, AI voices' before More options), scrolling with it."""
        outer = self.layout()
        assert isinstance(outer, QVBoxLayout)
        for key, panel in self._barred():
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
            panel.show_picked_row(compact or self._tab == key)

    def stack_steps(self):
        return []   # one card at a time: nothing to stack when narrow

    def _fx_changed(self, spec: dict):
        if self.chain.errors:              # give a bypassed effect another go after an edit
            self.chain.errors.clear()      # (configure rebuilds; clear_errors() would twice)
        self.chain.configure(spec)
        self._update_backdrop(spec)
        self.fx.show_errors({})
        self.fx_changed.emit(spec)
        self._emit_active()

    def _update_backdrop(self, spec: dict):
        """Have the Background's loops made for these settings (a worker reads the board
        sounds from disk and renders them; nothing when it's off)."""
        cfg = (spec.get("effects") or {}).get("backdrop") if spec.get("enabled") else None
        if cfg and cfg.get("on") and cfg.get("sounds"):
            metas = {m.id: m for m in self.board_sounds()}   # read here, on the UI thread
        else:
            metas = {}

        def load(sid: str):
            from soundboard.sounds import library
            m = metas.get(sid)
            return library.load_sound(m) if m is not None else None
        self.backdrop.update(cfg, load)

    def board_changed(self):
        """Sounds were added, renamed or deleted: the Background's names and loops again."""
        refresh = getattr(self.fx.rows.get("backdrop"), "refresh_names", None)
        if refresh is not None:
            refresh()
        self._update_backdrop(self.fx.spec())

    def _ai_changed(self, s: dict):
        self.speech.s["ai"] = s            # kept with the speech settings
        self.speech_changed.emit(dict(self.speech.s))

    def _ai_live(self, on: bool):
        if on:                             # one replacement for your voice at a time
            self.speech.livevoice.b_live.setChecked(False)
        self._emit_active()

    def _speech_live(self, on: bool):
        if on:
            self.ai.stop()

    def stop_all(self):
        """The window's Stop all: the typed line stops and every voice goes off (the
        voice changer, the AI voice, the computer voice and translating). What was on
        is remembered: Voices ON brings it back."""
        self.controller.stop_speaking()
        self.set_voices(False)
        self.speech.stop_translating()   # a language picked but not ready yet goes too

    def on_keys(self) -> list[str]:
        """What's changing your mic now, in the bar's order: "fx", "ai", "speak",
        "lang"."""
        keys = []
        if self.fx.btn_power.isChecked():
            keys.append("fx")
        if self.ai.is_on():
            keys.append("ai")
        if self.speech.livevoice.b_live.isChecked():
            keys.append("speak")
        if spoken.heard() and self.speech.translating() is not None:   # else no Languages tab
            keys.append("lang")
        return keys

    def voices_on(self) -> bool:
        """The Voices switch's state: something here is changing your mic."""
        return bool(self.on_keys())

    def back_keys(self) -> list[str]:
        """What Voices ON would turn on: what it turned off, else the voice changer
        with the voice picked on it."""
        return list(self._back) or ["fx"]

    def set_voices(self, on: bool):
        """The Voices switch. Off: every voice goes off, remembered with the grey ones
        already waiting. On: exactly those come back (nothing remembered: the voice
        changer with its picked voice)."""
        self._switching = True
        try:
            if not on:
                keys = self.on_keys()
                if keys:                 # already all off: keep what's remembered
                    # the grey ones stay too (they were shown as coming back), except
                    # a replacement for your voice the one that's on would push off
                    other = {"ai": "speak", "speak": "ai"}
                    self._back = [k for k in ORDER if k in keys or (
                        k in self._back and other.get(k) not in keys)]
                    if "lang" in keys:
                        self._back_lang = self.speech.cb_lang.currentData() or ""
                for k in keys:
                    self.stop_one(k)
            elif not self.voices_on():
                keys = self.back_keys()
                self._back = []
                for k in keys:
                    self._turn_on(k)
        finally:
            self._switching = False
        self._update_heads()

    def toggle_voices(self) -> bool:
        """The Voices hotkey: flips the switch. True when voices are on now."""
        self.set_voices(not self.voices_on())
        return self.voices_on()

    def _master_flipped(self, on: bool):
        usage.used("voices-master")
        self.set_voices(on)

    def _turn_on(self, key: str):
        if key == "fx":
            self.fx.btn_power.setChecked(True)   # its toggled handler applies it
        elif key == "ai":
            self.ai.b_start.setChecked(True)
        elif key == "speak":
            self.speech.livevoice.b_live.setChecked(True)
        elif key == "lang" and self._back_lang:
            i = self.speech.cb_lang.findData(self._back_lang)
            if i > 0:                    # (its language may have been removed since)
                self.speech.cb_lang.setCurrentIndex(i)

    def toggle_one(self, key: str):
        """A status bar chip clicked: that one goes off (remembered, its chip stays
        grey), or a grey one comes back on."""
        usage.used("voice-chip-toggle")
        before = self.on_keys()
        self._switching = True
        try:
            if key in before:
                if key == "lang":
                    self._back_lang = self.speech.cb_lang.currentData() or ""
                self._back = [k for k in ORDER if k == key or k in self._back]
                self.stop_one(key)
            else:
                self._back = [k for k in self._back if k != key]
                self._turn_on(key)
                # one replacement for your voice at a time: the one it pushed off goes grey
                pushed = [k for k in before if k not in self.on_keys()]
                self._back = [k for k in ORDER if k in self._back or k in pushed]
        finally:
            self._switching = False
        self._update_heads()

    def forget_one(self, key: str):
        """A chip's ✕: that one goes off, and Voices ON won't bring it back."""
        self._back = [k for k in self._back if k != key]
        if key in self.on_keys():
            self.stop_one(key)
        self._update_heads()

    def stop_one(self, key: str):
        """Just that one goes off, the others stay on."""
        if key == "fx":
            self.fx.btn_power.setChecked(False)   # its toggled handler applies it
        elif key == "ai":
            self.ai.stop()
        elif key == "speak":
            self.controller.stop_speaking()
            self.speech.livevoice.b_live.setChecked(False)
        elif key == "lang":
            self.speech.stop_translating()

    def is_active(self) -> bool:
        """Something here is changing what others hear from your mic."""
        return (self.fx.btn_power.isChecked() or self.speech.livevoice.b_live.isChecked()
                or self.ai.is_on())

    def _emit_active(self):
        self._sync_translate()
        self._update_heads()
        # only when it flips: every slider step lands here, and each send redraws the tab
        on = self.is_active()
        if on != self._active:
            self._active = on
            self.active_changed.emit(on)

    # ---- Speak in: the voice that's on says the translated lines
    def _sync_translate(self):
        sp = self.speech
        lv = sp.livevoice
        m = sp.translating()
        fg = lv.b_live.isChecked()   # text-to-speech's own Start translates by itself
        who = ""
        if m is not None and not fg:
            if self.ai.is_on():
                who = "ai"
            elif self.fx.btn_power.isChecked():
                who = "fx"
        self.ai_controller.set_dub(who == "ai")
        sp.ctl.dub = self.ai_controller if who == "ai" else None   # (typed in live.py)
        sp.ctl.fx_always = who == "fx"
        if who and not lv.bg_for:
            lv._bg_note("")               # "turn on a voice": one is on now
        lv.translate_for(who)
        if not lv.bg_for and not lv._bg_warning:
            lv._bg_note("")               # Said by says who speaks (or that Start does)
        fx = self.fx.preset
        if self.ai.is_on():
            on = ("ai", self.ai.voice_title())
        elif self.fx.btn_power.isChecked():
            on = ("fx", _("My own mix") if fx == CUSTOM else voicefx.shown(fx))
        else:
            on = ("", "")
        sp.said_by(*on)

    # ---- cards that fold away
    def _section(self, key: str, panel: QWidget, title: QLabel,
                 beside: QWidget | None = None) -> QFrame:
        """A tab and its card: the card's head is the panel's own title (`title`, shown
        there instead) with its emblem; `beside` (an on/off switch) goes right after it."""
        f, v = card(roomy=True)
        v.setContentsMargins(18, 14, 18, 18)   # no section label's top padding here
        v.setSpacing(12)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(12)
        head.addWidget(CardBadge(CARD_ICONS[key]), 0, Qt.AlignmentFlag.AlignVCenter)
        lbl = section_label(title.text())
        lbl.setProperty("head", True)   # no top padding: centred on the emblem
        head.addWidget(lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        # the on/off switch right after the card's name: at the far end of the head it
        # sat a whole window away from the name it switches (on a wide window)
        if beside is not None:
            head.addSpacing(4)
            head.addWidget(beside, 0, Qt.AlignmentFlag.AlignVCenter)
        state = QLabel("")
        state.setObjectName("pill")
        state.setProperty("on", True)
        state.hide()
        head.addWidget(state, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addStretch(1)
        title.hide()                      # the head shows it
        v.addLayout(head)
        # any height the card gets beyond what it needs (wrapped text measured at
        # another width) goes to the panel, never around the title: at 440 px the
        # title row sat in an 80 px gap
        v.addWidget(panel, 1)
        panel.show()
        b = QPushButton(TAB_NAMES[key]())
        b.setObjectName("voicetab")
        b.setCheckable(True)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        icons.set_icon(b, CARD_ICONS[key], checked_color="on_accent", size=16)
        b.clicked.connect(lambda __=False, k=key: self.show_tab(k, asked=True))
        self._tab_group.addButton(b)
        self._tab_flow.addWidget(b)
        self._tabs[key] = b
        self._cards[key] = f
        self._states[key] = state
        self._card_box.addWidget(f, 0, Qt.AlignmentFlag.AlignTop)
        f.hide()
        return f

    def show_tab(self, key: str, asked: bool = False):
        """Show one card, its tab pressed. `asked`: a click, so it's remembered."""
        if key not in self._cards:
            return
        self._tab = key
        for k, f in self._cards.items():
            f.setVisible(k == key)
        for k, panel in self._barred():
            if panel.picked.property("pinned"):   # (in its card when not: shown with it)
                panel.show_picked_row(key == k)
        self._tabs[key].setChecked(True)
        self._update_heads()
        if asked and key in usage.VOICE_TABS:
            usage.used(f"voice-tab-{key}")
        if asked and self.speech.s.get("tab") != key:
            self.speech.s["tab"] = key   # kept with the speech settings
            self.speech_changed.emit(dict(self.speech.s))

    def current_tab(self) -> str:
        return self._tab

    def _fx_folds(self, types: list):
        self._folded = {k for k in self._folded if not k.startswith("fx.")} | {
            f"fx.{t}" for t in types}
        self.speech.s["folded"] = sorted(self._folded)   # kept with the speech settings
        self.speech_changed.emit(dict(self.speech.s))

    def _update_bar(self):
        """The status bar's chips: each thing changing what others hear, in the order
        the sound goes through them."""
        if not hasattr(self, "bar"):
            return
        # short: a picture and a name; the full words are the chip's tip
        items = []
        on = self.on_keys()
        # turned on again some other way (its card): it's no longer waiting to come back
        # (not while the switch or a chip turns them on and off one by one)
        if not self._switching:
            self._back = [k for k in self._back if k not in on]
        click_off = _("Click to turn it off. Right-click to open it.")
        if "fx" in on:
            shown, pic = self._fx_shown()
            items.append(("fx", shown, "on", "voice" if pic is None else "", pic,
                          _("Voice changer: {voice}.", voice=shown) + " " + click_off))
        if self.ai.is_on():
            st, title = self.ai.status(), self.ai.voice_title()
            if st == "failed":
                items.append(("ai", _("AI voice off"), "warn", "warn", None,
                              self.ai.failure_text() + " " + click_off))
            else:
                items.append(("ai", title + ("…" if st == "starting" else ""), "on", "wave",
                              None, (_("AI voice: {voice}, starting.", voice=title)
                                     if st == "starting" else
                                     _("AI voice: {voice}.", voice=title)) + " "
                              + click_off))
        if "speak" in on:
            who = self._speak_shown()
            items.append(("speak", who, "on", "speech", None,
                          _("The computer voice ({voice}) speaks for you.", voice=who)
                          + " " + click_off))
        m = self.speech.translating() if "lang" in on else None
        if m is not None:
            lang = langnames.of(m)
            items.append(("lang", lang, "on", "browser", None,
                          _("What you say is said in {language}.", language=lang)
                          + " " + click_off))
        # grey: what Voices ON brings back (a click brings just that one back)
        if not on:
            items.append(("none", _("Mic unchanged. ON brings back:") if self._back else
                          _("Mic unchanged. ON turns on:"), "off", "mic", None,
                          _("Nothing is changing your mic voice. Switch Voices ON, or "
                            "click a grey voice, to turn it on.")))
        click_on = _("Off. Click to turn it back on. Right-click to open it.")
        for k in (self.back_keys() if not on else self._back):
            if k == "fx":
                shown, pic = self._fx_shown()
                items.append(("fx", shown, "off", "voice" if pic is None else "", pic,
                              _("Voice changer: {voice}.", voice=shown) + " " + click_on,
                              bool(self._back)))   # the voice it'd turn on anyway: no ✕
            elif k == "ai":
                title = self.ai.voice_title()
                items.append(("ai", title, "off", "wave", None,
                              _("AI voice: {voice}.", voice=title) + " " + click_on))
            elif k == "speak":
                who = self._speak_shown()
                items.append(("speak", who, "off", "speech", None,
                              _("The computer voice ({voice}) speaks for you.", voice=who)
                              + " " + click_on))
            elif k == "lang" and self._back_lang and spoken.heard():
                lang = langnames.name(self._back_lang, self._back_lang)
                items.append(("lang", lang, "off", "browser", None,
                              _("What you say is said in {language}.", language=lang)
                              + " " + click_on))
        self.bar.set_items(items)
        names = ", ".join(it[1] for it in items if it[2] == "off" and it[0] != "none")
        self.bar.set_master(bool(on), (
            _("Turns off every voice changing your mic. Switching it on brings them back.")
            if on else _("Turns on: {voices}", voices=names)))

    def _fx_shown(self) -> tuple:
        """The voice changer's voice for a chip: its short name and its picture."""
        name = self.fx.preset
        shown = _("My own mix") if name == CUSTOM else voicefx.shown(name)
        return shown, art.icon(art.voice_key(name)) if name != CUSTOM else None

    def _speak_shown(self) -> str:
        # which voice: a custom one may be a voice server on this PC (a web address)
        cb = self.speech.cb_voice
        return cb.currentText() if cb.currentData() else _("Computer voice")

    def _open_card(self, key: str):
        """A status bar chip: show its tab, from the top."""
        key = {"lang": "speak"}.get(key, key)
        if key not in self._cards or not self._tabs[key].isVisibleTo(self):
            return
        self.show_tab(key, asked=True)
        # tied to this tab: closed meanwhile, it never runs
        QTimer.singleShot(0, self._scroll, lambda: self._scroll.verticalScrollBar().setValue(0))

    def _update_heads(self):
        """Each card's head, and its tab, say when it's on (and when it speaks another
        language)."""
        self._update_bar()
        if "speak" not in self._states:   # still being made
            return
        m = self.speech.translating()
        lang = langnames.of(m) if m is not None else ""
        late = _("in {language}, a few seconds late", language=lang) if lang else ""
        fx, ai, tts = (self.fx.btn_power.isChecked(), self.ai.is_on(),
                       self.speech.livevoice.b_live.isChecked())
        # the switches already say On: their heads only add the language
        self._set_state("fx", fx, late if fx and not ai and not tts else "", say_on=False)
        self._set_state("ai", ai, late if ai and not tts else "", say_on=False)
        self._set_state("speak", tts, lang if tts else "")

    def _set_state(self, key: str, on: bool, note: str, say_on: bool = True):
        text = " · ".join(t for t in (_("On") if on and say_on else "", note) if t)
        st = self._states[key]
        st.setText(text)
        st.setVisible(bool(text))
        tab = self._tabs[key]
        if tab.property("live") != on:   # a tab that's on shows it, picked or not
            tab.setProperty("live", on)
            tab.style().unpolish(tab)
            tab.style().polish(tab)

    def tab_icon(self) -> str:
        """A consistent line icon; the live dot indicates whether voice is active."""
        return "voice"

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

    def rescan_modules(self, found: list | None = None, ai_voices: list | None = None):
        """`found` / `ai_voices`: already read from disk by _rescan_in_background."""
        self.modules = mods.discover() if found is None else found
        mods.load_effects(self.modules)
        self.fx.add_new_effects()
        self.chain.configure(self.fx.spec())
        self.speech.set_modules(self.modules)
        self.ai.set_modules(self.modules, ai_voices)
        self._ai_follow_offline()
        self.addons.show_modules(self.modules)

    def _rescan_in_background(self):
        """The add-ons' Refresh button: the folder scan and voices.json read on a
        worker (17 ms of disk on a slow drive), the rest back on the UI thread."""
        if self._scanning:
            return
        self._scanning = True

        def work():
            from soundboard.speech import aivoice
            from soundboard.ui.voice.aivoicepanel import read_voices
            found = voices = None
            try:
                found = mods.discover()
                voices = read_voices(next((m for m in found if m.id == aivoice.MODULE_ID
                                           and not m.error), None))
            except Exception:  # noqa: BLE001 - scanned again on the UI thread instead
                found = voices = None
            busy.emit(self._scanned, found, voices)
        threading.Thread(target=work, daemon=True, name="addon-scan").start()

    def _ai_follow_offline(self):
        """Offline mode: the AI voices tab only while they're ready to use (getting
        or installing them goes online)."""
        shown = not net.offline() or self.ai.ready()
        self._tabs["ai"].setVisible(shown)
        if not shown and self._tab == "ai":
            self.show_tab("fx")
        self._ai_card.setVisible(shown and self._tab == "ai")

    def _ai_net_changed(self):
        if not self.ai._installing:   # (its buttons come back when that's done)
            self.ai._refresh()
        self._ai_follow_offline()
        self.addons.show_modules(self.modules)   # its lines name downloads

    def _apply_scan(self, found, voices):
        self._scanning = False
        try:
            self.rescan_modules(found, voices)
        except Exception:
            self.addons.shown.emit()   # never leave Refresh stuck on "Checking…"
            raise

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
        if getattr(self, "recordings", None) is not None:
            self.recordings.shutdown()
        self.speech.installs._dl_cancel = True
        self.ai.shutdown()
        self.controller.shutdown()
        self.backdrop.close()
        self.engine.voice_chain = None
