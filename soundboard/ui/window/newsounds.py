"""New sounds, marked like unread mail. A sound that lands on the board (a download, a
pick from the queue, files or a zip dropped in, another soundboard or a sound pack
imported, a clip) glows on its card until the mouse goes over it, or until you leave
the Sounds tab having seen it. While you're on another tab the Sounds tab counts them
("3 new"), and a small arrow on it says more are still coming in.

Nothing is saved: a restart starts with none new. MainWindow makes one
(``MainWindow.newctl``); _rebuild_pads tells it what's on the board."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer

from soundboard.i18n import ngettext
from soundboard.ui.window.controller import Controller
from soundboard.ui.window.railtabs import set_tab_count

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

BUSY_MS = 500   # how often the arrow checks for downloads and imports while one runs


class NewSounds(Controller):
    """The new sounds of one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self._known: set[str] | None = None   # every sound seen this run (None: not yet)
        self.fresh: set[str] = set()           # glowing on the board
        self._away: set[str] = set()           # came in while Sounds wasn't showing
        self._was_on = False
        self._busy = False
        self._busy_timer = QTimer(self)
        self._busy_timer.setInterval(BUSY_MS)
        self._busy_timer.timeout.connect(self.follow)

    def on_board(self) -> bool:
        """The Sounds tab is what's showing (not another tab, not Settings)."""
        mw = self.mw
        tabs = getattr(mw, "tabs", None)
        page = getattr(mw, "sounds_page", None)
        if tabs is None or page is None or tabs.currentWidget() is not page:
            return False
        setctl = getattr(mw, "setctl", None)
        return setctl is None or not setctl.settings_open()

    def pads_rebuilt(self):
        """_rebuild_pads ran: the sounds not seen before are new (the first time, they're
        the library the app started with)."""
        mw = self.mw
        ids = set(mw.pads)
        if self._known is None:
            self._known = ids
            return
        added = ids - self._known
        self._known |= ids
        self.fresh &= ids
        self._away &= ids
        if added:
            self.fresh |= added
            if not self.on_board():
                self._away |= added
            self.follow()   # (an import is under way: the arrow, at once)
        for sid, p in mw.pads.items():
            p.set_fresh(sid in self.fresh)
        self._show()

    def seen(self, sid: str):
        """The mouse went over a new sound's card."""
        self.fresh.discard(sid)
        self._away.discard(sid)
        self._show()

    def follow(self, *_a):
        """Where you are and what's running: called on a tab switch, Settings opening
        or closing, and every BUSY_MS while a download or import runs."""
        on = self.on_board()
        if on:
            self._away.clear()   # the count goes: you're looking at them
        elif self._was_on and self.fresh:   # left Sounds having seen them: read
            for sid in self.fresh:
                p = self.mw.pads.get(sid)
                if p is not None:
                    p.set_fresh(False)
            self.fresh.clear()
        self._was_on = on
        self._busy = self._running()
        if self._busy and not self._busy_timer.isActive():
            self._busy_timer.start()
        elif not self._busy:
            self._busy_timer.stop()
        self._show()

    def _running(self) -> bool:
        mw = self.mw
        bars = [getattr(mw, n, None) for n in ("download_bar", "mini_download_bar")]
        if any(b is not None and (b.running() or b._queue) for b in bars):
            return True
        impctl = getattr(mw, "impctl", None)
        return impctl is not None and impctl._pending_imports > 0

    def count(self) -> int:
        return len(self._away)

    def _show(self):
        mw = self.mw
        tabs, page = getattr(mw, "tabs", None), getattr(mw, "sounds_page", None)
        if tabs is None or page is None:
            return
        n = self.count()
        words = ngettext("{n} new sound", "{n} new sounds", n) if n else ""
        set_tab_count(tabs, tabs.indexOf(page), n, self._busy, words)
