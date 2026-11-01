"""*Last time Onion Board closed while installing AI voices. Install it again?*: a slim
bar over the tabs, at the start after an add-on install the app was closed (or
crashed) in the middle of (soundboard.addons.addonmarks). Install again takes you to
where that add-on is installed and starts it there, the way its own button does; Not
now lets it be: the add-on's own page still offers it. One add-on at a time.

MainWindow makes one ``AddonNotice`` (``MainWindow.addonctl``); the marks are read on a
worker, everything else runs on the UI thread."""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer, Signal
from shiboken6 import isValid as qt_valid

from soundboard.addons import addonmarks
from soundboard.core import langnames
from soundboard.i18n import _
from soundboard.ui.kit import busy
from soundboard.ui.kit.topbar import TopBar
from soundboard.ui.window.controller import Controller

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

VOICE_KEYS = (addonmarks.AI_VOICES, addonmarks.LIVE_VOICE)   # on the Voice tab


class AddonNotice(Controller):
    """The cut-off add-on install bar of one MainWindow (``mw``)."""
    _found = Signal(list)   # the marks a closed app left, read on a worker

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self.left: list[str] = []   # still to ask about, oldest first
        self.key = ""               # the one the bar asks about now
        self._found.connect(self._on_found)

    def build_bar(self) -> TopBar:
        self.bar = TopBar("download", "warn")
        self.no_btn = self.bar.add_button(_("Not now"))
        self.no_btn.clicked.connect(self.not_now)
        self.yes_btn = self.bar.add_button(_("Install again"), primary=True)
        self.yes_btn.clicked.connect(self.again)
        self.bar.close_btn.hide()   # Not now says it, and the buttons need the room
        self.bar.hide()
        return self.bar

    def start(self):
        """Look for cut-off installs (a folder listing, on a worker)."""
        threading.Thread(target=lambda: busy.emit(self._found, addonmarks.cut_off()),
                         daemon=True, name="addon-marks").start()

    def _on_found(self, keys: list):
        self.left = list(keys)
        self._next()

    def _words(self, key: str) -> str:
        """The bar's question for `key`, or "" when it can't be offered here (its tab is
        switched off, or the language isn't one the app knows any more)."""
        mw = self.mw
        if key in VOICE_KEYS or key.startswith(addonmarks.TRANSLATION):
            if not mw.tabctl.tab_on("voice"):
                return ""
        if key == addonmarks.AI_VOICES:
            return _("Last time Onion Board closed while installing AI voices. Install "
                     "them again?")
        if key == addonmarks.LIVE_VOICE:
            return _("Last time Onion Board closed while installing speech recognition. "
                     "Install it again?")
        if key == addonmarks.WATCH:
            if not mw.tabctl.tab_on("triggers"):
                return ""
            return _("Last time Onion Board closed while installing Onion Watch. Install "
                     "it again?")
        if key == addonmarks.POCKET:
            return _("Last time Onion Board closed while installing Onion Pocket. Install "
                     "it again?")
        m = self._language(key)
        if m is not None:
            return _("Last time Onion Board closed while downloading {language}. "
                     "Download it again?", language=langnames.of(m))
        return ""

    def _language(self, key: str):
        if not key.startswith(addonmarks.TRANSLATION):
            return None
        mid = key[len(addonmarks.TRANSLATION):]
        return next((m for m in getattr(self.mw.voice, "modules", ())
                     if m.id == mid and m.kind == "translation"), None)

    def _next(self):
        """Ask about the next one, or hide the bar when none is left."""
        while self.left:
            key = self.left.pop(0)
            words = self._words(key)
            if words:
                self.key = key
                self.bar.set_message(words)
                lang = key.startswith(addonmarks.TRANSLATION)
                self.yes_btn.setText(_("Download again") if lang else _("Install again"))
                for btn in (self.yes_btn, self.no_btn):   # the words wrap, never the buttons
                    btn.setMinimumWidth(btn.sizeHint().width())
                self.bar.show()
                return
        self.key = ""
        self.bar.hide()

    def not_now(self):
        """It's left as it is: its own page still offers Install, and it isn't asked
        again."""
        if self.key:
            threading.Thread(target=addonmarks.forget, args=(self.key,), daemon=True,
                             name="addon-mark-forget").start()
        self._next()

    def again(self):
        """Go where the add-on is installed and start it there (that install marks it
        again while it runs)."""
        key = self.key
        if not key:
            return
        addonmarks.forget(key)   # (one tiny file; the install writes it again)
        self._go(key)
        self._next()

    def _go(self, key: str):
        mw = self.mw
        if key == addonmarks.WATCH:
            mw.tabs.setCurrentWidget(mw.triggers)
            if not getattr(mw.triggers, "_busy", True):
                mw.triggers.get()
            return
        if key == addonmarks.POCKET:
            mw.setctl.open_settings("remote")

            def press():   # once the page is made
                dlg = mw.setctl._settings_dlg
                b = getattr(dlg, "get_pocket", None) if dlg is not None else None
                if b is not None and qt_valid(b) and b.isVisibleTo(dlg):
                    b.click()
            QTimer.singleShot(0, self, press)
            return
        v = mw.voice
        mw.tabs.setCurrentWidget(v)
        if key == addonmarks.AI_VOICES:
            v._open_card("ai")
            ai = v.ai
            if ai.module is None:
                ai._get()
            elif not ai.module.installed:
                ai._install()
            return
        v._open_card("speak")
        inst = v.speech.installs
        if key == addonmarks.LIVE_VOICE:
            if v.speech.module is not None and not v.speech.module.installed:
                inst._install()
            return
        m = self._language(key)
        if m is not None and not m.installed:
            inst._download(m)
