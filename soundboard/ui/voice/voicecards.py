"""The Voice tab's cards and tabs: each card's head and badge, switching tabs, the status
bar's chips and the cards' on / off states. Mixed into VoicePanel (voicepanel.py)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton,
                               QWidget)

from soundboard.core import langnames, usage
from soundboard.ui.kit import theme
from soundboard import voicefx
from soundboard.speech import spoken
from soundboard.ui.kit import icons
from soundboard.ui.voice import art
from soundboard.ui.kit.panel import card, icon_button, section_label
from soundboard.ui.voice.voicefxpanel import CUSTOM, PICKED_ART
from soundboard.ui.voice.voicetiles import place_bar_controls
from soundboard.i18n import _
from soundboard.ui.kit.pixels import snap_to_pixels

if TYPE_CHECKING:
    class _Panel(QWidget):
        # what VoicePanel itself provides, for the type checker only
        def __getattr__(self, name: str) -> Any: ...
else:
    _Panel = object


# the voices with a bar of their own over the status bar (VoicePanel._barred)
BARRED = ("fx", "ai")


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


# Clean mic first: your mic is cleaned before any voice changes it
CARD_ICONS = {"clean": "mic", "fx": "voice", "ai": "wave", "speak": "browser", "addons": "puzzle"}
TAB_KEYS = tuple(CARD_ICONS)   # the Voice tab's own tabs, in order
ORDER = ("fx", "ai", "lang")   # the status bar's chips, as the sound goes through
TAB_NAMES = {"clean": lambda: _("Clean mic"), "fx": lambda: _("Voice changer"),
             "ai": lambda: _("AI voices"), "speak": lambda: _("Languages"),
             "addons": lambda: _("Add-ons")}


class _VoiceTab(QPushButton):
    """A Voice tab: with property "live" (its voice or Clean mic is on) a small green
    dot after its name, picked or not. (Blue words for it looked like a glitch.)"""

    DOT = 8

    def sizeHint(self):
        sh = super().sizeHint()
        if self.property("live"):   # room for the dot only while it shows: kept on every
            sh.setWidth(sh.width() + self.DOT + 6)   # tab, the row wrapped a tab sooner
        return sh

    def paintEvent(self, e):
        super().paintEvent(e)
        if not self.property("live"):
            return
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # picked: in its words' colour on the accent, as its icon (green was lost there)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.T["on_accent" if self.isChecked() else "ok_text"]))
        x = 8 if self.isRightToLeft() else self.width() - 8 - self.DOT
        p.drawEllipse(QRectF(x, (self.height() - self.DOT) / 2, self.DOT, self.DOT))
        p.end()


class VoiceCards(_Panel):
    """VoicePanel's cards, tabs and status chips."""

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
        b = _VoiceTab(TAB_NAMES[key]())
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
        for _k, panel in self._barred():
            # every voice that's on keeps its bar, whichever tab shows (the voice
            # changer's and an AI voice's, one over the other); in its card when not
            # pinned, so shown with it
            if panel.picked.property("pinned"):
                panel.show_picked_row(True)
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

    def _make_bar_controls(self):
        """Each voice's bar gets, at its right end, a pause button (that voice off for a
        while, its bar kept, dimmed, to bring it back with one click) and a ✕ (off, and
        Voices ON won't bring it back): what the bar's chips used to do."""
        self._bar_ctl: dict[str, tuple[QPushButton, QPushButton]] = {}
        for key, panel in self._barred():
            ctl = QWidget()
            h = QHBoxLayout(ctl)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(6)
            pause = icon_button("pause", _("Pause this voice (click again to bring it back)"))
            pause.clicked.connect(lambda __=False, k=key: (usage.used("voice-bar-pause"),
                                                          self.toggle_one(k)))
            close = icon_button("close", _("Turn this voice off (Voices ON won't bring it "
                                           "back)"))
            close.clicked.connect(lambda __=False, k=key: (usage.used("voice-chip-off"),
                                                          self.forget_one(k)))
            h.addWidget(pause)
            h.addWidget(close)
            # the picture, name and kind on a line of their own, which takes the pause
            # and ✕ too when the bar folds (place_bar_controls)
            box = panel.picked_box
            item = box.itemAt(0)
            name_line = item.layout() if item is not None else None
            assert isinstance(name_line, QHBoxLayout)
            box.removeItem(name_line)
            name_line.setParent(None)
            top = QHBoxLayout()
            top.setSpacing(10)
            top.addLayout(name_line)
            top.addStretch(1)
            box.insertLayout(0, top)
            box.addWidget(ctl, 0, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            panel.bar_top = top
            panel.bar_controls = ctl
            place_bar_controls(panel)
            # dimmed while paused: the picture and the name
            dim = []
            for w in (panel.picked_pic, panel.picked_name):
                fx = QGraphicsOpacityEffect(w)
                fx.setOpacity(1.0)
                w.setGraphicsEffect(fx)
                dim.append(fx)
            self._bar_ctl[key] = (pause, close)
            self._bar_dim = {**getattr(self, "_bar_dim", {}), key: dim}

    def _show_bar_controls(self, on: list[str], paused: list[str]):
        """The bars' pause buttons say pause or play; a paused voice's bar stays, dimmed."""
        for key, panel in self._barred():
            if key not in getattr(self, "_bar_ctl", {}):
                continue
            pause, _close = self._bar_ctl[key]
            is_paused = ((self._clean_paused and not self.clean.is_on()) if key == "clean"
                         else key in paused and key not in on)
            icons.set_icon(pause, "play" if is_paused else "pause", size=18)
            tip = (_("Paused: click to turn this voice back on") if is_paused
                   else _("Pause this voice (click again to bring it back)"))
            pause.setToolTip(tip)
            pause.setAccessibleName(tip)
            for fx in self._bar_dim[key]:
                fx.setOpacity(0.45 if is_paused else 1.0)
            panel.set_paused(is_paused)

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
        if "fx" in on:   # on again (a voice picked): ON may turn it on again
            self._fx_forgot = False
        click_off = _("Click to turn it off. Right-click to open it.")
        # Clean mic has its own bar over this one too (it isn't a voice, so the Voices
        # switch leaves it alone)
        clean = getattr(self, "clean", None)
        # the voice changer and an AI voice have their own bars over this one (with
        # pause and ✕), so no chip; an AI voice still starting, or failed, says so here
        if self.ai.is_on() and self.ai.status() in ("starting", "failed"):
            title = self.ai.voice_title()
            items.append(("ai", _("AI voice off"), "warn", "warn", None,
                          self.ai.failure_text() + " " + click_off)
                         if self.ai.status() == "failed" else
                         ("ai", title + "…", "on", "wave", None,
                          _("AI voice: {voice}, starting.", voice=title) + " " + click_off))
        m = self.speech.translating() if "lang" in on else None
        # its own voice speaking it has a bar of its own (as the AI voice): no chip
        barred = BARRED + (("lang",) if getattr(self, "_reader", "") == "read" else ())
        if m is not None and "lang" not in barred:
            lang = langnames.of(m)
            items.append(("lang", lang, "on", "browser", None,
                          _("What you say is said in {language}.", language=lang)
                          + " " + click_off))
        # grey: what Voices ON brings back (a click brings just that one back)
        # (with Clean mic's chip there and nothing to bring back, "Mic unchanged" beside
        # it read as if Clean mic did nothing)
        paused = self.back_keys() if not on else self._back
        chipped = [k for k in paused if k not in barred]   # the rest show on their bars
        if not on and not (clean is not None and clean.is_on() and not chipped):
            items.append(("none", _("Mic unchanged. ON brings back:") if chipped and self._back
                          else _("Mic unchanged. ON turns on:") if chipped else
                          _("Mic unchanged"), "off", "mic", None,
                          _("Nothing is changing your mic voice. Switch Voices ON, or "
                            "click a grey voice, to turn it on.")))
        click_on = _("Off. Click to turn it back on. Right-click to open it.")
        for k in chipped:
            if k == "lang" and self._back_lang and spoken.heard():
                lang = langnames.name(self._back_lang, self._back_lang)
                items.append(("lang", lang, "off", "browser", None,
                              _("What you say is said in {language}.", language=lang)
                              + " " + click_on))
        self.bar.set_items(items)
        self._show_bar_controls(on, paused)
        chip_names = {it[0]: it[1] for it in items if it[2] == "off" and it[0] != "none"}
        names = ", ".join(  # what ON brings back: the paused bars' voices and grey chips
            self._fx_shown()[0] if k == "fx" else self.ai.voice_title() if k == "ai"
            else self._lang_bar_name() if k == "lang" and k in barred
            else chip_names[k]
            for k in paused if k in barred or k in chip_names)
        self.bar.set_master(bool(on), (
            _("Turns off every voice changing your mic. Switching it on brings them back.")
            if on else _("Turns on: {voices}", voices=names) if names else
            _("Pick a voice to turn one on")))

    def _fx_shown(self) -> tuple:
        """The voice changer's voice for a chip: its short name and its picture."""
        name = self.fx.preset
        shown = _("My own mix") if name == CUSTOM else voicefx.shown(name)
        return shown, art.icon(art.voice_key(name)) if name != CUSTOM else None

    def _show_clean_bar(self):
        """Clean mic's bar: its preset by name, as a voice's (Loud room (Clean mic))."""
        from soundboard.ui.voice.cleanmicsettings import preset_names
        from soundboard.voicefx import cleanmic
        bar = self.clean_bar
        preset = cleanmic.preset_of(self.clean.s)
        name = preset_names().get(preset) or _("Custom")
        if bar.picked_pic.pixmap().isNull():   # (it follows the theme from here)
            icons.set_label_icon(bar.picked_pic, "mic", "text", 24)
            bar.picked_kind.setText(_("(Clean mic)"))
        if bar.picked_name.text() != name:
            bar.picked_name.setText(name)
            bar._fit_picked()

    def _edit_clean(self):
        """Clean mic's Edit: its Mic settings, open on its tab."""
        self.show_tab("clean", asked=True)
        self.clean.b_cog.setChecked(True)
        QTimer.singleShot(0, self._scroll, lambda: self._scroll.ensureWidgetVisible(
            self.clean.settings))

    def _lang_code(self) -> str:
        """The language spoken (or paused from its bar)."""
        return self.speech.cb_lang.currentData() or getattr(self, "_back_lang", "") or ""

    def _lang_bar_name(self) -> str:
        """The voice actually reading the language: its own, or a Windows one."""
        m = self.speech._module(self._lang_code())
        return self.speech.voice_name(m) if m is not None else ""

    def _show_lang_bar(self):
        """The language's own voice's bar: its name ("Huayan"), "(Chinese voice)" and
        the language's card picture."""
        bar = getattr(self, "lang_bar", None)
        code = self._lang_code()
        if bar is None or not code:
            return
        from soundboard.ui.voice.speechtiles import lang_icon
        m = self.speech._module(code)
        lang = langnames.of(m) if m is not None else langnames.name(code, code)
        name = self._lang_bar_name() or lang
        kind = _("({language} voice)", language=lang)
        if bar.picked_name.text() != name or bar.picked_kind.text() != kind:
            bar.show_voice(name, kind, lang_icon(code, True, PICKED_ART).pixmap(
                PICKED_ART, PICKED_ART))

    def _edit_lang_voice(self):
        """The language voice's Edit voice: how fast it reads, under the Languages
        card's More options."""
        usage.used("voice-tweak")
        self.show_tab("speak", asked=True)
        self.speech.btn_opts.setChecked(True)
        QTimer.singleShot(0, self._scroll, lambda: self._scroll.ensureWidgetVisible(
            self.speech.opts))

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
        self._show_lang_bar()
        if "speak" not in self._states:   # still being made
            return
        m = self.speech.translating()
        lang = langnames.of(m) if m is not None else ""
        late = _("in {language}, a few seconds late", language=lang) if lang else ""
        fx, ai = self.fx.btn_power.isChecked(), self.ai.is_on()
        # the switches already say On: their heads only add the language
        self._set_state("fx", fx, late if fx and not ai else "")
        self._set_state("ai", ai, late if ai else "")
        # another language spoken (by its own voice, the AI voice or the voice changer)
        # lights its tab up too
        speaking = m is not None and spoken.heard()
        # its switch and its lit card already say which: no words beside the switch
        self._set_state("speak", speaking, "")
        self._set_state("clean", self.clean.is_on(), "")

    def _set_state(self, key: str, on: bool, note: str):
        st = self._states[key]
        st.setText(note)
        st.setVisible(bool(note))
        tab = self._tabs[key]
        if tab.property("live") != on:   # a tab that's on shows it, picked or not
            tab.setProperty("live", on)
            tab.setToolTip(_("On") if on else "")
            tab.updateGeometry()   # (its dot's room)
            tab.update()
            self.live_tabs_changed.emit()   # the On Air card's lines (netcontrol)

    def live_tabs(self) -> list[tuple[str, str, str]]:
        """The tabs that are on (their dot), in order: (key, icon, name)."""
        return [(k, CARD_ICONS[k], TAB_NAMES[k]()) for k, b in self._tabs.items()
                if b.property("live")]

    def tab_icon(self) -> str:
        """A consistent line icon; the live dot indicates whether voice is active."""
        return "voice"
