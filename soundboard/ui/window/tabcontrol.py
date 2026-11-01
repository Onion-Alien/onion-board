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
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMenu

from soundboard.control import winkeys
from soundboard.online import net
from soundboard.core import achievements, usage
from soundboard.i18n import _
from soundboard.ui.kit import icons
from soundboard.ui.kit.crashdialog import free_dialog
from soundboard.ui.kit.hotkeypick import HotkeyDialog, pretty_key
from soundboard.ui.window import taboff
from soundboard.ui.apps.appspanel import AppsTab
from soundboard.ui.window.controller import Controller
from soundboard.ui.window.livedot import set_tab_live
from soundboard.ui.window.railtabs import set_tab_new
from soundboard.ui.store.storetab import StoreTab
from soundboard.ui.voice.voicepanel import VoicePanel

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

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
                                 "them to your board or share your own")))
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


# a saved key (winkeys' names, by Windows key code) -> Qt's, for a tab's own key;
# letters, digits, F-keys and the numpad go by their ranges (qt_keys)
_QT_KEY = {0x20: Qt.Key.Key_Space, 0x0D: Qt.Key.Key_Return, 0x09: Qt.Key.Key_Tab,
           0x1B: Qt.Key.Key_Escape, 0x08: Qt.Key.Key_Backspace, 0x2D: Qt.Key.Key_Insert,
           0x2E: Qt.Key.Key_Delete, 0x24: Qt.Key.Key_Home, 0x23: Qt.Key.Key_End,
           0x21: Qt.Key.Key_PageUp, 0x22: Qt.Key.Key_PageDown, 0x26: Qt.Key.Key_Up,
           0x28: Qt.Key.Key_Down, 0x25: Qt.Key.Key_Left, 0x27: Qt.Key.Key_Right,
           0x13: Qt.Key.Key_Pause, 0x2C: Qt.Key.Key_Print, 0x91: Qt.Key.Key_ScrollLock,
           0x14: Qt.Key.Key_CapsLock, 0x90: Qt.Key.Key_NumLock, 0x5D: Qt.Key.Key_Menu,
           0xBA: Qt.Key.Key_Semicolon, 0xBB: Qt.Key.Key_Equal, 0xBC: Qt.Key.Key_Comma,
           0xBD: Qt.Key.Key_Minus, 0xBE: Qt.Key.Key_Period, 0xBF: Qt.Key.Key_Slash,
           0xC0: Qt.Key.Key_QuoteLeft, 0xDB: Qt.Key.Key_BracketLeft,
           0xDC: Qt.Key.Key_Backslash, 0xDD: Qt.Key.Key_BracketRight,
           0xDE: Qt.Key.Key_Apostrophe, 0xB3: Qt.Key.Key_MediaTogglePlayPause,
           0xB0: Qt.Key.Key_MediaNext, 0xB1: Qt.Key.Key_MediaPrevious,
           0xAF: Qt.Key.Key_VolumeUp, 0xAE: Qt.Key.Key_VolumeDown, 0xAD: Qt.Key.Key_VolumeMute}
_QT_PAD = {0x6A: Qt.Key.Key_Asterisk, 0x6B: Qt.Key.Key_Plus, 0x6D: Qt.Key.Key_Minus,
           0x6E: Qt.Key.Key_Period, 0x6F: Qt.Key.Key_Slash}


def qt_keys(combo: str) -> QKeySequence | None:
    """'ctrl+shift+f5' as Qt's key sequence, or None for a key Qt can't take (a MIDI
    pad, a mouse button): a tab's key works only while the window is in front."""
    got = winkeys.parse(combo) if combo else None
    if got is None:
        return None
    mods, vk = got
    mod = Qt.KeyboardModifier.NoModifier
    for flag, m in ((winkeys.MOD_CONTROL, Qt.KeyboardModifier.ControlModifier),
                    (winkeys.MOD_ALT, Qt.KeyboardModifier.AltModifier),
                    (winkeys.MOD_SHIFT, Qt.KeyboardModifier.ShiftModifier),
                    (winkeys.MOD_WIN, Qt.KeyboardModifier.MetaModifier)):
        if mods & flag:
            mod |= m
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:   # digits, letters: the same codes
        key = Qt.Key(vk)
    elif 0x70 <= vk <= 0x87:
        key = Qt.Key(Qt.Key.Key_F1.value + vk - 0x70)
    elif 0x60 <= vk <= 0x69 or vk in _QT_PAD:
        mod |= Qt.KeyboardModifier.KeypadModifier
        key = Qt.Key(Qt.Key.Key_0.value + vk - 0x60) if vk <= 0x69 else _QT_PAD[vk]
    elif vk in _QT_KEY:
        key = _QT_KEY[vk]
    else:
        return None
    return QKeySequence(key | mod)


class TabControl(Controller):
    """The tabs of one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self._key_shortcuts: list[QShortcut] = []

    def _radio_live(self, on: bool):
        mw = self.mw
        achievements.live("radio", on)
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
        from soundboard.ui.window import moretabs
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
        # the key that jumps here: Ctrl+1... clash with pads' keys, so it can be changed
        menu.addSeparator()
        combo = self.tab_key(key)
        if combo:
            hk = menu.addMenu(icons.icon("keyboard"), _("Hotkey: {hotkey}",
                                                        hotkey=pretty_key(combo)))
            hk.addAction(icons.icon("keyboard"), _("Change"), lambda: self.set_tab_key(key))
            hk.addAction(icons.icon("trash"), _("Remove hotkey"),
                         lambda: self.set_tab_key(key, ""))
        else:
            menu.addAction(icons.icon("keyboard"), _("Set hotkey"),
                           lambda: self.set_tab_key(key))
        return menu

    def _shown_buttons(self) -> list:
        mw = self.mw
        return [b for b in mw.rail.buttons
                if b.index < mw.tabs.count() and mw.tabs.isTabVisible(b.index)]

    def tab_key(self, key: str, n: int | None = None) -> str:
        """The combo that jumps to tab `key` ("" = none): its own (Config.tab_keys), or
        Ctrl+its place among the shown tabs on the rail (`n`, from 1) up to 9, unless
        another tab took that one."""
        mw = self.mw
        if key in mw.cfg.tab_keys:
            return mw.cfg.tab_keys[key]
        if n is None:
            n = next((n for n, b in enumerate(self._shown_buttons(), 1)
                      if b.index == TAB_INDEX[key]), None)
        combo = f"ctrl+{n}" if n and n <= 9 else ""
        return "" if combo in mw.cfg.tab_keys.values() else combo

    def bind_tab_keys(self):
        """Ctrl+1... jump to the tabs by their places on the rail and the tabs' own keys
        to theirs, while the window is in front; made again when a key changes."""
        mw = self.mw
        for sc in self._key_shortcuts:
            sc.setEnabled(False)
            sc.deleteLater()
        self._key_shortcuts = []
        own = {k: c for k, c in mw.cfg.tab_keys.items() if c and k in TAB_INDEX}
        for k, combo in own.items():
            seq = qt_keys(combo)
            if seq is not None:
                self._key_shortcuts.append(QShortcut(
                    seq, mw, activated=lambda k=k: self._open_tab(k)))  # pyright: ignore[reportCallIssue]  # signal keyword
        for n in range(1, 10):
            if f"ctrl+{n}" not in own.values():
                self._key_shortcuts.append(QShortcut(
                    QKeySequence(f"Ctrl+{n}"), mw,  # pyright: ignore[reportCallIssue]  # signal keyword
                    activated=lambda n=n: self._ctrl_number(n)))
        mw.rail.key_for = lambda i, n: pretty_key(self.tab_key(TAB_KEYS[i], n))
        mw.rail.sync()

    def _ctrl_number(self, n: int):
        """Ctrl+n: the n-th shown tab, unless it has a key of its own instead."""
        shown = self._shown_buttons()
        if n <= len(shown) and TAB_KEYS[shown[n - 1].index] in self.mw.cfg.tab_keys:
            return
        self._go_tab(n - 1, absolute=True)

    def _open_tab(self, key: str):
        b = next((b for b in self._shown_buttons() if b.index == TAB_INDEX[key]), None)
        if b is not None:
            usage.used("tab-keys")
            b.click()

    def set_tab_key(self, key: str, combo: str | None = None):
        """Tab `key`'s own key (asks for it unless given; "" = none, not even Ctrl+n).
        One key opens one tab: another tab that had it loses it."""
        mw = self.mw
        if combo is None:
            d = HotkeyDialog(mw.hotkeys, mw, pads=False, in_app=_(
                "Opens this tab while Onion Board is in front.\nEsc = cancel."))
            combo = d.result_combo if d.exec() and d.result_combo else None
            free_dialog(d)
            mw.hkctl.register_hotkeys()   # the capture paused them
            if combo is None:
                return
        keys = {k: c for k, c in mw.cfg.tab_keys.items() if not combo or c != combo}
        keys[key] = combo
        mw.set_option("tab_keys", keys)
        usage.used("tab-key-set")
        self.bind_tab_keys()

    def hide_tab(self, key: str):
        """Hide a tab from its right-click menu, saying where to get it back."""
        mw = self.mw
        self.set_tab_on(key, False)
        usage.used(f"tab-hidden-{key}")
        mw.toast(_("{tab} hidden. Bring it back with + More tabs or Settings > Tabs.",
                     tab=TABS[TAB_INDEX[key]][0]))

    def mark_store_new(self):
        """A "New" pill on the Store tab until it's first opened (Config.store_seen):
        people who never looked in it find it; once opened, never again."""
        mw = self.mw
        i = TAB_INDEX["store"]

        def seen(cur: int):
            if cur != i:
                return
            mw.tabs.currentChanged.disconnect(seen)
            mw.set_option("store_seen", True)
            set_tab_new(mw.tabs, i, False)
        if mw.cfg.store_seen:
            return
        set_tab_new(mw.tabs, i, True)
        mw.tabs.currentChanged.connect(seen)
        seen(mw.tabs.currentIndex())

    def _tab_live(self, key: str, on: bool):
        """The live badge on the Voice, Triggers or Apps tab (Store has none)."""
        mw = self.mw
        achievements.live(key, on)   # (voice and apps count time: Settings > Achievements)
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
