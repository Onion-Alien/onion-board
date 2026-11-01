"""The setup guide's first-launch steps ("Make it yours"): the tabs to start with,
a language and a look, the privacy switches and the "Set up Discord" switch.
Mixed into SetupWizard."""
from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from soundboard.core import autostart
from soundboard.audio import engine as eng
from soundboard.ui.kit import theme
from soundboard.core import usage
from soundboard.ui.kit import icons, panel
from soundboard.ui.bun.bunnywidget import BunnyWidget
from soundboard.i18n import _
from soundboard.ui.setup.wizardkit import (BUN_H, BUN_PAD, HEADER_GAP, LOOK_CARD_GAP,
                                           LOOK_CARD_H, LOOK_CARD_W, SECTION_GAP,
                                           SWITCH_CARD_W, SWITCH_ROW_H, _card, _header,
                                           _label, _section, WizardStep)


# the first launch's "Make it yours" page: nine looks to start from (the rest: Settings).
# Row one the plain pair and a seasonal one (the limited edition on offer, Midnight when
# none is), then the best three dark and three light.
SEASONAL, SEASONAL_OFF = "seasonal", "Midnight"
LOOK_ROWS = (("Light", "Dark", SEASONAL),
             ("Ocean", "Toxic", "Synthwave"),
             ("Mint", "Paper", "Cherry Blossom"))


def look_themes() -> list[str]:
    seasonal = next((n for n in theme.LIMITED if theme.on_offer(n)), SEASONAL_OFF)
    return [seasonal if n == SEASONAL else n for row in LOOK_ROWS for n in row]


# the first launch's last step: the tabs to start with, besides Sounds and Setup (on
# for good). A new user starts with Voice on and these three off (BASIC_TABS_OFF).
OPTIONAL_TABS = ("voice", "radio", "apps", "triggers")


def tab_names() -> dict[str, str]:
    """The tiles' names (a function: the words follow the language picked at start-up)."""
    return {"voice": _("Voice"), "radio": _("Radio"), "apps": _("Apps"),
            "triggers": _("Triggers")}


def use_for(tabs: set[str]) -> str:
    """The extra tabs picked, as the use count's answer (usage.py: use-*): the old
    "What's it for?" answers, so the counts carry on from before the question went."""
    extra = tabs & {"radio", "apps", "triggers"}
    return {frozenset(): "normal", frozenset({"apps"}): "streamer",
            frozenset({"triggers"}): "games",
            frozenset({"radio", "apps", "triggers"}): "all"}.get(frozenset(extra), "custom")


class LookStep(WizardStep):
    """SetupWizard's first-launch pages and their choices."""

    def _discord_heading(self) -> str:
        return _("Last step: tell Discord or your game")

    def _page_look(self) -> QWidget:
        """First launch only: a look (nine to start from) and the language."""
        from soundboard import i18n
        from soundboard.ui.settings.langpick import LangButton
        from soundboard.ui.settings.appearance import ThemeCard
        p = QWidget()
        v = QVBoxLayout(p)
        v.addLayout(_header(_("All set! Now make it yours"),
                            # two lines, as every step's: the header ends level with Bun
                            _label(_("Pick a look and your language.<br>Change either "
                                     "later in <b>Settings</b>.")),
                            BunnyWidget("star", celebrate=True, height=BUN_H, pad=BUN_PAD)))
        v.addSpacing(HEADER_GAP)
        v.addWidget(_section(_("Look")))
        v.addSpacing(6)
        # the looks: three rows of three, filling the page's width (their edges on
        # Back's and Next's)
        g = QGridLayout()
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(LOOK_CARD_GAP)
        self.look_cards: list = []
        for i, name in enumerate(look_themes()):
            c = ThemeCard(name)
            c.setFixedSize(LOOK_CARD_W, LOOK_CARD_H)
            c.setChecked(name == theme.current_name)
            c.clicked.connect(lambda __=False, n=name: self._pick_look(n))
            self.look_cards.append(c)
            g.addWidget(c, i // 3, i % 3)
        g.setColumnStretch(3, 1)
        v.addLayout(g)
        v.addSpacing(6)
        # the board on a theme that isn't one of the nine: none would be ticked, so
        # this line says which one it is (_look_note)
        self.look_more = QLabel()
        self.look_more.setObjectName("hint")
        self.look_more.setWordWrap(True)
        v.addWidget(self.look_more)
        self._look_note()
        v.addSpacing(SECTION_GAP)
        # the language
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(_section(_("Language")))
        self.lang_button = LangButton()
        langs = dict(i18n.available())
        code = self.win.cfg.language if self.win.cfg.language in langs else i18n.current()
        self.lang_button.show_language(code, langs.get(code, code))
        row.addWidget(self.lang_button)
        row.addStretch(1)
        v.addLayout(row)
        self.lang_note = _label("", "font-size:10pt;")
        self.lang_note.setObjectName("hint")
        self.lang_note.hide()
        v.addWidget(self.lang_note)

        def open_picker():
            from soundboard.ui.settings.langpick import LanguageDialog
            dlg = LanguageDialog(self, code)
            dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            dlg.chosen.connect(self._pick_language)
            dlg.open_under(self.lang_button)
        self.lang_button.clicked.connect(open_picker)
        v.addStretch(1)
        return p

    def _switch_card(self, title: str, icon: str, hint: str) -> tuple[QFrame, QVBoxLayout]:
        """One of the last step's four cards: its icon and title, one line on what it's
        for, then its switches."""
        card, cl = _card(14, 0, roomy=False)   # (the rows' own height spaces them)
        card.setFixedWidth(SWITCH_CARD_W)
        row, _t, _marks = panel.heading_row(title, icon)
        cl.addLayout(row)
        cl.addSpacing(6)
        h = _label(hint, "font-size:10pt;")
        h.setObjectName("muted")
        cl.addWidget(h)
        cl.addSpacing(8)
        return card, cl

    @staticmethod
    def _switch_row(box: QCheckBox, info: QPushButton | None = None) -> QWidget:
        """A switch (and its ⓘ) on a row as tall as every other row of the cards, with
        or without an ⓘ."""
        w = QWidget()
        w.setFixedHeight(SWITCH_ROW_H)
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(box)
        if info is not None:
            row.addWidget(info)
        row.addStretch(1)
        return w

    def _page_switches(self) -> QWidget:
        """First launch only, the last step: four cards of switches people would only
        find in Settings: the tabs, Discord, the internet and this PC."""
        p = QWidget()
        v = QVBoxLayout(p)
        v.addLayout(_header(_("A few handy switches"),
                            _label(_("All optional: the way it is works fine.<br>Change any "
                                     "of it later in <b>Settings</b>.")),
                            BunnyWidget("star", celebrate=True, height=BUN_H, pad=BUN_PAD)))
        v.addSpacing(HEADER_GAP)
        g = QGridLayout()
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(LOOK_CARD_GAP)
        g.setColumnStretch(2, 1)
        v.addLayout(g)
        # the tabs: one tick box each (an opt-in reads as one), with its tab's icon and
        # an ⓘ that drops down what the tab is for (+ More tabs' words)
        card, cl = self._switch_card(_("Your tabs"), "list",
                                     _("Voice is on. Tick more to add them to the side."))
        self.tab_buttons: dict[str, QCheckBox] = {}
        self.tab_infos: dict[str, QPushButton] = {}
        names = tab_names()
        for key in OPTIONAL_TABS:
            chk = QCheckBox(names[key])
            icons.set_icon(chk, key)
            chk.setChecked(self.win.tabctl.tab_on(key))   # Voice on, the rest opt-in
            chk.setProperty("tab", key)
            info = panel.info_button(_("What's {name}?", name=names[key]))
            info.clicked.connect(lambda __=False, k=key: self._tab_info(k))
            cl.addWidget(self._switch_row(chk, info))
            self.tab_buttons[key] = chk
            self.tab_infos[key] = info
        cl.addStretch(1)
        g.addWidget(card, 0, 0)
        # Discord: an opt-in, done after Finish (Bun sets it: chatguide.set_up_discord)
        card, cl = self._switch_card(_("Discord"), "chat",
                                     _("Using Discord for voice chat?"))
        self.chk_discord = QCheckBox(_("Set up Discord for me"))
        self.discord_info = panel.info_button(_("What does Bun change in Discord?"))
        self.discord_info.clicked.connect(self._discord_more)
        cl.addWidget(self._switch_row(self.chk_discord, self.discord_info))
        self.discord_why = _label("", "font-size:10pt;")
        self.discord_why.setObjectName("hint")
        cl.addWidget(self.discord_why)
        cl.addStretch(1)
        g.addWidget(card, 0, 1)
        self._discord_touched = False   # ticked or unticked by them: keep it so
        self.chk_discord.clicked.connect(lambda: setattr(self, "_discord_touched", True))
        # the internet: Low data mode and Offline mode, as on Settings > Privacy and
        # Data (both applied at once)
        from soundboard.online import quality
        card, cl = self._switch_card(_("Internet"), "browser",
                                     _("On a hotspot, a capped plan or no internet?"))
        self.chk_low_data = QCheckBox(_("Use less data"))
        self.chk_low_data.setChecked(quality.current.low_data)
        self.chk_low_data.toggled.connect(self._set_low_data)
        self.low_data_info = panel.info_button(_("What does Use less data change?"))
        self.low_data_info.clicked.connect(lambda: self._drop_down(
            self.low_data_info, _("Use less data"),
            _("For a phone hotspot, capped plan or slow internet: smaller downloads, "
              "lower-bitrate radio, more patience with stations that cut out, and no "
              "pictures in web search results.")))
        cl.addWidget(self._switch_row(self.chk_low_data, self.low_data_info))
        self.chk_offline = QCheckBox(_("Offline mode"))
        self.chk_offline.setChecked(self.win.cfg.net_offline)
        self.chk_offline.toggled.connect(self._set_offline)
        self.offline_info = panel.info_button(_("What does Offline mode change?"))
        self.offline_info.clicked.connect(lambda: self._drop_down(
            self.offline_info, _("Offline mode"),
            _("Nothing goes online at all, and everything that needs the internet is "
              "hidden (the Radio tab, web search, downloads, updates…).")))
        cl.addWidget(self._switch_row(self.chk_offline, self.offline_info))
        cl.addStretch(1)
        g.addWidget(card, 1, 0)
        # this PC: starting with Windows, Lite mode (applied at once, as in Settings >
        # Appearance) and keeping the window on top
        from soundboard.ui.settings import lite
        card, cl = self._switch_card(_("This PC"), "settings",
                                     _("How Onion Board starts and runs."))
        self.chk_autostart = QCheckBox(_("Start with Windows"))
        self.chk_autostart.setToolTip(_("Start Onion Board when I sign in to Windows "
                                        "(quietly, in the tray)"))
        self.chk_autostart.setChecked(autostart.is_enabled())
        self.chk_autostart.setEnabled(autostart.available())
        cl.addWidget(self._switch_row(self.chk_autostart))
        self.chk_lite = QCheckBox(_("Lite mode (suggested for this PC)") if lite.slow_pc()
                                  else _("Lite mode"))
        self.chk_lite.setToolTip(_("Lite mode: no animations, for slower PCs"))
        self.chk_lite.setChecked(self.win.cfg.lite_mode)
        self.chk_lite.toggled.connect(self.win.themectl.set_lite_mode)
        cl.addWidget(self._switch_row(self.chk_lite))
        self.chk_on_top = QCheckBox(_("Keep window on top"))
        self.chk_on_top.setChecked(self.win.cfg.always_on_top)
        self.chk_on_top.toggled.connect(self.win.on_top_toggle)
        cl.addWidget(self._switch_row(self.chk_on_top))
        cl.addStretch(1)
        g.addWidget(card, 1, 1)
        self._offline_tabs()
        v.addStretch(1)
        return p

    def _set_low_data(self, on: bool):
        """Use less data: every Data & quality choice at its lightest, or back."""
        from soundboard.online import quality
        self.win.set_option("data", quality.change(**(quality.LOW if on else quality.NORMAL)))

    def _set_offline(self, on: bool):
        """Offline mode, at once (the window follows: net.on_change)."""
        from soundboard.online import net
        cfg = self.win.cfg
        self.win.set_option("net_offline", on)
        net.configure_features(cfg.net_off, cfg.net_offline)
        self._offline_tabs()

    def _offline_tabs(self):
        """In Offline mode the tabs that only work online can't be ticked (as in
        Settings), and Use less data has nothing to save."""
        from soundboard.online import net
        offline = net.offline()
        for key, chk in self.tab_buttons.items():
            needs = self.win.tabctl.needs_online(key)
            chk.setEnabled(not needs)
            chk.setToolTip(_("Needs the internet: Offline mode is on (Privacy & security)")
                           if needs else "")
        self.chk_low_data.setEnabled(not offline)

    def _discord_more(self):
        """Set up Discord's ⓘ: what Bun changes, how it goes back, and on the cable which
        mic Discord still needs picked."""
        text = _("Bun saves how Discord is set now, then turns off its noise suppression, "
                 "echo cancellation and automatic volume, which chop up your sounds. If "
                 "Discord is open, it closes for a few seconds. Undo it any time: Settings → "
                 "Audio → Mic effect → Put Discord back.")
        from soundboard.ui.setup.chatguide import clean_mic
        if clean_mic(self.win) is not None:   # chatguide.clean_mic_takes_over
            text += " " + _("Bun turns on Clean mic on the Voice tab in its place: it takes "
                            "background noise out of your voice and never touches your sounds.")
        if self._discord_needed():
            mic = eng.virtual_mic_for(self.win.routectl._main_name()) or "CABLE Output"
            text += " " + _("Then pick {mic} as your mic in Discord: Bun shows you where.",
                            mic=mic)
        self._drop_down(self.discord_info, _("Set up Discord for me"), text)

    def _tab_info(self, key: str):
        """A tab's ⓘ: what it's for, dropped down under the ⓘ (inside the window)."""
        from soundboard.ui.window.moretabs import PITCH
        # (Triggers is the owl's, as on its tab)
        self._drop_down(self.tab_infos[key], tab_names()[key], PITCH.get(key, ""),
                        owl=key == "triggers")

    def _drop_down(self, btn: QPushButton, title: str, text: str, owl: bool = False):
        """A help card dropped down under an ⓘ (inside the window)."""
        from PySide6.QtCore import QPoint
        from soundboard.ui.sounds.dialogs import TabHelpPopup
        box = TabHelpPopup(title, text, owl=owl, parent=self.win)
        lay = box.layout()
        if lay is not None:
            lay.activate()   # wrapped text: as tall as the words need
        box.resize(box.width(), box.heightForWidth(box.width()) if box.hasHeightForWidth()
                   else box.sizeHint().height())
        at = btn.mapToGlobal(QPoint(0, btn.height() + 6))
        area = self.win.geometry()
        box.move(max(area.left(), min(at.x() - 24, area.right() - box.width() + 1)),
                 max(area.top(), min(at.y(), area.bottom() - box.height() + 1)))
        box.exec()
        box.deleteLater()

    def _discord_needed(self) -> bool:
        """Discord has to be told something: on the cable or a virtual mic it must pick
        that mic (straight into the mic, it keeps the one it has)."""
        cfg = self.win.cfg
        return cfg.route == "cable" or (cfg.route == "device" and bool(
            eng.virtual_mic_for(self.win.routectl._main_name())))

    def _fill_discord_choice(self):
        """The "Set up Discord" switch's words (and, until they touch it, whether it's
        ticked) follow the send step: on by itself only when Discord must pick a mic."""
        need = self._discord_needed()
        if not self._discord_touched:
            self.chk_discord.setChecked(need)
        from soundboard.ui.setup.chatguide import clean_mic
        clean = clean_mic(self.win) is not None
        if need:
            why = (_("Bun swaps Discord's noise filter for Clean mic, then shows you which "
                     "mic to pick.") if clean else
                   _("Bun turns off Discord's noise filter, then shows you which mic to "
                     "pick."))
        else:
            why = (_("Bun swaps Discord's noise filter for Clean mic, so your sounds don't "
                     "get cut off.") if clean else
                   _("Bun turns off Discord's noise filter so your sounds don't get cut off."))
        self.discord_why.setText(why)

    def _pick_language(self, code: str):
        from soundboard import i18n
        self.win.langctl.switch_language(code, restart=False)
        self.lang_button.show_language(code, i18n.name_of(code))
        later = self._lang_pending = code != i18n.current()
        if later:
            self.lang_note.setText(i18n.in_language(code, lambda: _(
                "Onion Board restarts in {name} when you press Finish.",
                name=i18n.name_of(code))))
        self.lang_note.setVisible(later)

    def _pick_look(self, name: str):
        if name != theme.current_name:
            self.win.themectl.apply_theme(name)
            backdrop = self.win.findChild(QWidget, "setupbackdrop")
            if backdrop is not None:
                backdrop.update()
        for c in self.look_cards:
            c.setChecked(c.name == name)
        self._look_note()

    def _look_note(self):
        """Under the looks: how many more there are in Settings, and the theme the board
        uses now when it isn't one of the nine (so no look is ticked)."""
        more = len(theme.THEMES) - len(look_themes())
        if any(c.name == theme.current_name for c in self.look_cards):
            self.look_more.setText(_("{n} more themes in Settings.", n=more))
        else:
            self.look_more.setText(_("You're using <b>{theme}</b> now. {n} more themes in "
                                     "Settings.", theme=html.escape(theme.current_name),
                                     n=more))

    def _save_tabs(self):
        """The first launch's last step, left by Finish or closed there: the tabs as
        ticked, and the answer remembered (so the step is never the first launch's
        again). Its count is the old "What's it for?" answer (use_for)."""
        cfg = self.win.cfg
        if cfg.use_mode:
            return
        picked = {k for k, b in self.tab_buttons.items() if b.isChecked()}
        for key in OPTIONAL_TABS:
            self.win.tabctl.set_tab_on(key, key in picked)
        cfg.use_mode = use_for(picked)
        usage.used(f"use-{cfg.use_mode}")   # the answer's name only (usage.py)
        cfg.save()
