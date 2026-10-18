"""Bun mode in the main window: the window goes and a floating Bun (ui/bun/bunmode.py) takes its
place, Back brings the window back as it was, Open the full board brings the whole board,
and Bun says the window's toasts while he's up. Starting as Bun when the app quit as Bun.

MainWindow makes one ``BunControl`` (``MainWindow.bunctl``); everything here runs on the UI
thread."""
from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import QRect, QSize, Qt, QTimer
from PySide6.QtWidgets import QApplication

from soundboard.core import usage
from soundboard.control import winkeys
from soundboard.i18n import _
from soundboard.ui.window.controller import Controller

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

BUN_TIP = _("Turn into Bun: a small Bun floating on top instead of this window. The "
            "button under him brings it back.")

FULL_FROM_BUN = QSize(1180, 720)   # Bun grown past his biggest opens the board this big


class BunControl(Controller):
    """Bun mode for one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self.bun_mode = None   # Bun mode's floating Bun (ui/bun/bunmode.py), once used

    def bun_up(self) -> bool:
        return self.bun_mode is not None and self.bun_mode.isVisible()

    def enter_bun_mode(self):
        """The window goes and a floating Bun takes its place (ui/bun/bunmode.py)."""
        mw = self.mw
        from soundboard.ui.bun.bunmode import BunMode
        if self.bun_mode is None:
            self.bun_mode = BunMode(mw)
            self.bun_mode.back.connect(lambda: self.leave_bun_mode(False))
            self.bun_mode.full.connect(lambda: self.leave_bun_mode(True))
        self.bun_mode.present(mw.frameGeometry() if mw.isVisible() else None)
        if mw.isVisible() and not mw.isMinimized():
            # the window as it is (the mini player or the board, maximized or not),
            # for Back: kept in the settings, so it's the same after a restart as Bun
            g = mw.normalGeometry() if mw.isMaximized() else mw.geometry()
            mw.cfg.bun["from"] = [g.x(), g.y(), g.width(), g.height(),
                                    bool(mw.isMaximized())]
        mw.cfg.bun["on"] = True
        mw._save_later()
        usage.used("bun-mode")
        if mw.focusWidget() is getattr(mw, "mini_bun", None):
            mw.mini_bun.clearFocus()   # back from Bun, the keys don't go to it
        mw.hide()
        mw.tickctl._wake()

    def tray_bun(self):
        """The tray menu's Bun item: Bun when he isn't up, the window back when he is."""
        if self.bun_up():
            self.leave_bun_mode(False)
        else:
            self.enter_bun_mode()

    def leave_bun_mode(self, full: bool = False):
        """Bun's Back button: the window back as it was. Open the full board (`full`,
        his right-click menu): the whole board, around where he stood."""
        mw = self.mw
        b = self.bun_mode
        if b is None or not b.isVisible():
            return
        spot = b.geometry().center()
        if full:
            room = (QApplication.screenAt(spot) or mw.screen()).availableGeometry()
            want = QSize(min(FULL_FROM_BUN.width(), room.width() - 40),
                         min(FULL_FROM_BUN.height(), room.height() - 40))
            if mw.isMaximized() or mw.isFullScreen():
                mw.showNormal()
            mw.resize(want)
            x = min(max(spot.x() - want.width() // 2, room.left()), room.right() - want.width())
            y = min(max(spot.y() - want.height() // 2, room.top()), room.bottom() - want.height())
            mw.move(x, y)
            # it was the mini player: shown at once, its first frames were a blank white
            # window while it laid the board out again; it fades in once that's done
            mw.setWindowOpacity(0.0)
            QTimer.singleShot(150, mw, lambda: mw.setWindowOpacity(1.0))   # (not once it's gone)
        else:
            self._back_as_it_was()
        mw.show_from_tray()
        if full:
            mw.fitctl._refit()   # out of the mini player now, not after the first paints
        if sys.platform == "win32":   # raise_/activateWindow alone left it behind the
            winkeys.to_front(int(mw.winId()))   # app in front (Bun never has focus)

    def _back_as_it_was(self):
        """The window's size and place from before Bun mode (cfg.bun["from"]), when
        it's on a screen still. Without it, the window started as Bun showed at its
        default size: Back looked just like Open the full board."""
        mw = self.mw
        was = mw.cfg.bun.get("from")
        if not (isinstance(was, list) and len(was) == 5):
            return
        x, y, w, h, maxed = was
        rect = QRect(int(x), int(y), int(w), int(h))
        if QApplication.screenAt(rect.center()) is None:   # that monitor's gone
            return
        if mw.isMaximized() or mw.isFullScreen():
            mw.showNormal()
        mw.setGeometry(rect)
        if maxed:
            mw.setWindowState(mw.windowState() | Qt.WindowState.WindowMaximized)

    def _bun_away(self):
        """Bun goes (the window's coming back, or the app's quitting)."""
        mw = self.mw
        b = self.bun_mode
        if b is not None and b.isVisible():
            b.hide()
            mw.cfg.bun["on"] = False
            mw._save_later()

    def start_as_bun(self) -> bool:
        """At start-up: quit as Bun last time, so Bun again (instead of the window)."""
        mw = self.mw
        if not (isinstance(mw.cfg.bun, dict) and mw.cfg.bun.get("on")
                and mw.cfg.setup_done):
            return False
        self.enter_bun_mode()
        return True

    def toast_seen(self, text: str, kind: str):
        """Every toast on the window (ui/kit/toast.py): Bun says it while he's up."""
        b = self.bun_mode
        if b is not None and b.isVisible():
            b.say(text, kind)
