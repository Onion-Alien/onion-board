"""The main window's tabs: which are on and shown (some need the internet), switching them
on and off from Settings > Tabs or their right-click menu, the More tabs menu for the
ones that are off, moving a tab's place, the keys that
step through tabs, and counting which tab was opened.

MainWindow makes one ``TabControl`` (``MainWindow.tabctl``); everything here runs on the
UI thread."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtWidgets import QMenu

from soundboard.online import net
from soundboard.core import usage
from soundboard.i18n import _
from soundboard.ui.kit import icons
from soundboard.ui import taboff
from soundboard.ui.appspanel import AppsTab
from soundboard.ui.buncontrol import BUN_TIP
from soundboard.ui.controller import Controller
from soundboard.ui.livedot import set_tab_live
from soundboard.ui.storetab import StoreTab
from soundboard.ui.voice.voicepanel import VoicePanel

if TYPE_CHECKING:
    from soundboard.ui.mainwindow import MainWindow

log = logging.getLogger(__name__)

# The tabs, in order: each one is a thing you can play (or, last, the setup). The
# tooltip says what it's for in a few words.
# the tabs' keys (never translated: settings, Tabs on/off, the usage count) and labels
TAB_KEYS = ("sounds", "radio", "apps", "triggers", "voice", "setup", "store")
TABS = ((_("Sounds"), _("Your sound buttons: click one to play it")),
        (_("Radio"), _("Internet radio stations from around the world")),
        (_("Apps"), _("Send another program's sound (music player, game…)")),
        (_("Triggers"), _("Play a sound when something shows up on your screen (“YOU DIED”…)")),
        (_("Voice"), _("Change your voice, speak another language, or use text-to-speech")),
        (_("Setup"), _("Pick where your sounds go (Discord, games, OBS…), test it")),
        (_("Community"), _("Sounds and voices players share, voted on by everyone: add "
                                 "them or share your own")))
TAB_INDEX = {key: i for i, key in enumerate(TAB_KEYS)}
BEFORE_SETUP = ("store",)   # last in TAB_KEYS, but on the rail before Setup


def rail_order(saved: list[str]) -> list[str]:
    """The tabs' keys in the rail's order: as dragged (Config.sidebar_order), any tab
    that order doesn't have in its usual place. Store comes last in TAB_KEYS
    (older configs keep their saved tab numbers) but sits before Setup on the rail. A key
    no tab has any more (the old "chat") is left out."""
    keys = [k for k in dict.fromkeys(saved) if k in TAB_INDEX]
    for k in TAB_KEYS:
        if k in keys:
            continue
        if k in BEFORE_SETUP and "setup" in keys:
            keys.insert(keys.index("setup"), k)
        else:
            keys.append(k)
    return keys


class TabControl(Controller):
    """The tabs of one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)

    def _radio_live(self, on: bool):
        mw = self.mw
        set_tab_live(mw.tabs, mw.tabs.indexOf(mw.radio_page), on,
                     mw.radio.live_tip(), "radio")

    def _focus_open_tab(self):
        """The window's first focus: the open tab's page (Ctrl+V on Sounds works at
        once). Left to Qt, a window shown with nothing focused focuses its first
        focusable widget as if Tab were pressed: the Sounds rail button, with its
        keyboard ring, whatever tab was open, so it looked like a second picked tab."""
        mw = self.mw
        if (fw := mw.focusWidget()) is not None and not mw.rail.isAncestorOf(fw):
            return   # something else has it already
        if (page := mw.tabs.currentWidget()) is not None:
            page.setFocus(Qt.FocusReason.OtherFocusReason)

    def tab_on(self, key: str) -> bool:
        """Whether a tab (taboff.KEYS) is switched on in Settings > Tabs."""
        mw = self.mw
        return key not in mw.cfg.tabs_off

    def needs_online(self, key: str) -> bool:
        """In Offline mode, whether a tab is of no use at all: Radio, and Triggers
        until Onion Watch is installed (its page is only the Get button). Those are
        hidden, and + More tabs doesn't offer them."""
        mw = self.mw
        if not net.offline():
            return False
        if key == "radio":
            return True
        if key == "triggers":
            has = getattr(mw.triggers, "has_addon", None)   # (switched off: a stand-in)
            if has is not None:
                return not has()
            from soundboard.addons import watchaddon
            return watchaddon.installed() is None and watchaddon.local_zip() is None
        return False

    def tab_shown(self, key: str) -> bool:
        """Whether a tab is in the tab bar: switched on, and of use (needs_online)."""
        return self.tab_on(key) and not self.needs_online(key)

    def _more_tab_keys(self) -> list[str]:
        """The tabs + More tabs offers: switched off, and of use (not Radio offline)."""
        return [k for k in taboff.KEYS if not self.tab_on(k) and not self.needs_online(k)]

    def _update_more_tabs(self):
        mw = self.mw
        mw.btn_more_tabs.setVisible(bool(self._more_tab_keys()))

    def _fill_more_tabs(self, menu: QMenu):
        """+ More tabs: a card for each tab that's switched off, with what it's good
        for (click: it's added and opened), then Settings > Tabs to pick them all."""
        mw = self.mw
        from soundboard.ui import moretabs
        off = [(k, *TABS[TAB_INDEX[k]]) for k in self._more_tab_keys()]
        self._more_added = False
        usage.used("more-tabs-opened")
        moretabs.fill(menu, off, self._add_from_more, lambda: mw.setctl.open_settings("tabs"))

    def _more_tabs_hidden(self):
        """+ More tabs closed: counted when nothing was added (a pick's triggered
        signal comes after the menu hides, so this looks once that's through)."""
        def check():
            if not getattr(self, "_more_added", True):
                usage.used("more-tabs-closed")
            self._more_added = True
        QTimer.singleShot(0, check)

    def _add_from_more(self, key: str):
        self._more_added = True
        usage.used(f"more-tabs-added-{key}")
        self._add_tab(key)

    def _add_tab(self, key: str):
        mw = self.mw
        self.set_tab_on(key, True)
        mw.tabs.setCurrentIndex(TAB_INDEX[key])

    def tab_menu(self, i: int) -> QMenu:
        mw = self.mw
        key = TAB_KEYS[i]
        menu = QMenu(mw)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        if mw.tipctl._tab_info_at(i) is not None:
            menu.addAction(icons.icon("info"), _("About this tab"),
                           lambda: mw.tipctl._show_tab_info(i))
            menu.addSeparator()
        if key in taboff.KEYS:
            act = menu.addAction(icons.icon("offline"), _("Hide this tab"))
            act.triggered.connect(lambda: self.hide_tab(key))
        else:
            act = menu.addAction(icons.icon("check"), _("This tab is always shown"))
            act.setEnabled(False)
        menu.addSeparator()
        menu.addAction(icons.icon("settings"), _("Choose tabs in Settings"),
                       lambda: mw.setctl.open_settings("tabs"))
        # Bun mode from the full window too (the mini player has its own Bun button)
        menu.addSeparator()
        act = menu.addAction(mw.builder._bun_icon(), _("Turn into Bun"), mw.bunctl.enter_bun_mode)
        act.setToolTip(BUN_TIP)
        menu.setToolTipsVisible(True)
        return menu

    def hide_tab(self, key: str):
        """Hide a tab from its right-click menu, saying where to get it back."""
        mw = self.mw
        self.set_tab_on(key, False)
        usage.used(f"tab-hidden-{key}")
        mw.toast(_("{tab} hidden. Bring it back with + More tabs or Settings > Tabs.",
                     tab=TABS[TAB_INDEX[key]][0]))

    def _tab_live(self, key: str, on: bool):
        """The live badge on the Voice, Triggers or Apps tab (Store has none)."""
        mw = self.mw
        if key == "store":
            return
        page = getattr(mw, key)
        if key == "voice":   # the active voice's picture, when there is one
            set_tab_live(mw.tabs, TAB_INDEX[key], on,
                         _("● ON: others hear your changed / computer voice"), page.tab_icon())
        elif key == "triggers":
            set_tab_live(mw.tabs, TAB_INDEX[key], on, _("● ON: watching your screen"),
                         "triggers")
        else:
            set_tab_live(mw.tabs, TAB_INDEX[key], on, page.live_tip(), "apps")

    def set_tab_on(self, key: str, on: bool):
        """Settings > Tabs: switch a tab off (what it was doing stops, it's shut down
        and hidden, and it isn't made again, even at the next start) or back on (made
        afresh and shown)."""
        mw = self.mw
        if key not in taboff.KEYS or self.tab_on(key) == on:
            return
        off = [k for k in mw.cfg.tabs_off if k != key]
        mw.set_option("tabs_off", off if on else [*off, key])
        i = TAB_INDEX[key]
        if not on and mw.tabs.currentIndex() == i:
            mw.tabs.move_to(0)   # (Settings, where this is done, stays up)
        if key == "radio":
            mw.netctl._radio_follow_switch()
        else:
            self._swap_tab(key)
        mw.tabs.setTabVisible(i, self.tab_shown(key))
        self._update_more_tabs()
        log.info("tab %s switched %s", key, "on" if on else "off")
        if on:   # once per install, sent now (usage.py: a daily count could be a day off)
            usage.step(mw.cfg, f"added-{key}-tab")
        mw.tab_switched.emit(key, on)

    def _swap_tab(self, key: str):
        """Put a freshly made `key` tab (or its stand-in) in place of the one there."""
        mw = self.mw
        i, old = TAB_INDEX[key], getattr(mw, key)
        if key == "triggers":
            old.cancel_pending()   # sounds still waiting out a trigger's wait
        old.shutdown()   # first: a new Voice tab sets the engine's voice chain
        steps = mw.fitctl._tab_steps.pop(key, []) if hasattr(mw.fitctl, "_fit") else []
        if steps:
            mw.fitctl._fit.remove(steps)
        new = mw._make_tab(key)
        setattr(mw, key, new)
        bar = mw.tabs.tabBar()
        text, tip, name = mw.tabs.tabText(i), mw.tabs.tabToolTip(i), bar.accessibleTabName(i)
        cur = mw.tabs.currentIndex()
        with QSignalBlocker(mw.tabs):   # no tab change saved, no status rewritten
            mw.tabs.removeTab(i)
            mw.tabs.insertTab(i, new, text)
            mw.tabs.setTabToolTip(i, tip)
            bar.setAccessibleTabName(i, name)
            mw.tabs.setCurrentIndex(cur)
        mw.rail.sync()
        icons.set_tab_icon(mw.tabs, i, key)
        old.deleteLater()
        self._tab_live(key, False)
        if key == "triggers":
            mw.load_triggers()
        if hasattr(mw.fitctl, "_fit"):
            if key in ("voice", "triggers"):
                assert not isinstance(new, (AppsTab, StoreTab))
                mw.fitctl._tab_steps[key] = new.fit_steps()
                mw.fitctl._fit.extend(mw.fitctl._tab_steps[key])
            if key == "voice":
                assert isinstance(new, (VoicePanel, taboff.TabOff))
                mw.fitctl._stack_cols = (*mw.fitctl._stack_cols[:1], *new.stack_steps())
            mw.fitctl._refit()

    def _count_tab(self, i: int):
        mw = self.mw
        if 0 <= i < len(TABS):
            usage.tab_opened(mw.cfg, TAB_KEYS[i])

    def _go_tab(self, n: int, absolute: bool = False):
        """The n-th tab on the rail (`absolute`), or the one n steps from this one."""
        mw = self.mw
        shown = [b for b in mw.rail.buttons if b.isVisible()]
        if not shown:
            return
        usage.used("tab-keys")
        if absolute:
            if n < len(shown):
                shown[n].click()
            return
        cur = next((k for k, b in enumerate(shown) if b.index == mw.tabs.currentIndex()), 0)
        shown[(cur + n) % len(shown)].click()
