"""The window's edge being dragged (Windows' size/move loop): what it shows meanwhile,
and work that can wait until the edge rests or is let go.

Windows sends WM_ENTERSIZEMOVE when the user starts dragging an edge (or the title
bar) and WM_EXITSIZEMOVE when they let go. In between, each mouse move is a resize
step, and Qt paints the whole window again for every one (~12 ms with a board of
pads): a fast mouse kept a CPU core busy for as long as the edge was held, and the
pads jumped between columns under it. So while the edge moves, the window shows a
still picture of itself (LiveResize), takes a new size at most every STEP_MS, and is
laid out once, for the size it has, when the edge rests (REST_MS) or is let go."""
from __future__ import annotations

import sys
import time
from ctypes import byref, c_uint, wintypes

from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRect, Qt, QTimer
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from soundboard.ui.kit import theme

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

WM_SIZING = 0x0214
WM_ENTERSIZEMOVE = 0x0231
WM_EXITSIZEMOVE = 0x0232
STEP_MS = 16   # while an edge is dragged: a new size at most this often
REST_MS = 150  # the edge held still this long: the window is laid out for its size
_MSG_ID = wintypes.MSG.message.offset if sys.platform == "win32" else 0


def drag_edge(message) -> int:
    """From a window's nativeEvent: 1 as a size/move drag starts, -1 as it ends, else 0.
    Every Windows message passes here: one read of the message's id."""
    if sys.platform != "win32":
        return 0
    kind = c_uint.from_address(int(message) + _MSG_ID).value
    if kind == WM_ENTERSIZEMOVE:
        return 1
    if kind == WM_EXITSIZEMOVE:
        return -1
    return 0


class _Still(QWidget):
    """The window as it was when the edge started moving, over the whole page; the room
    it grew by is the page's background. Painting it is one copy, not every widget."""

    def __init__(self, parent: QWidget, picture: QPixmap):
        super().__init__(parent)
        self.picture = picture
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, e):
        p = QPainter(self)
        page = self.parentWidget() or self
        w, h = self.picture.deviceIndependentSize().toSize().toTuple()
        # the room it grew by (right of it, below it): the page's own background, glow
        # and all
        for strip in (QRect(w, 0, page.width() - w, page.height()),
                      QRect(0, h, w, page.height() - h)):
            strip = strip.intersected(e.rect())
            if not strip.isEmpty():
                theme.paint_window_bg(p, strip, QPointF(0, 0), page.width(), page.height())
        p.drawPixmap(0, 0, self.picture)
        p.end()


class LiveResize:
    """A main window's edge being dragged: the still picture, the rest and the size steps.
    MainWindow.nativeEvent passes it every message (sizing, drag_edge) and resizeEvent
    asks it first (resized)."""

    def __init__(self, mw: MainWindow):
        self.mw = mw
        self.dragging = False
        self._still: _Still | None = None
        self._rest = QTimer(mw)
        self._rest.setSingleShot(True)
        self._rest.setInterval(REST_MS)
        self._rest.timeout.connect(self._thaw)
        self._last = 0.0
        self._held: tuple[int, int, int, int, int] | None = None   # hwnd, left, top, w, h
        self._step = QTimer(mw)
        self._step.setSingleShot(True)
        self._step.timeout.connect(self.flush)

    def drag(self, on: bool) -> None:
        """The edge (or the title bar) held, or let go."""
        if on == self.dragging:
            return
        self.dragging = on
        if not on:
            self.flush()   # the size held back last, before it's laid out
            self._thaw()
        self._hold_pads(on)
        self.mw.fitctl.live(on)

    def _hold_pads(self, on: bool) -> None:
        # (from the start: the pads are resized before the window's resizeEvent)
        grid = getattr(self.mw, "grid", None)
        if grid is not None:
            grid.hold(on)

    def resized(self) -> bool:
        """From resizeEvent: True while the edge is dragged (the window shows its still
        picture; the layout waits for the edge to rest)."""
        if not self.dragging:
            return False
        if self._still is None:
            self._freeze()
        self._rest.start()
        return True

    def _freeze(self) -> None:
        page = self.mw.centralWidget()
        if page is None:
            return
        self._hold_pads(True)
        self._still = _Still(page, page.grab())
        self._still.setGeometry(0, 0, 1 << 14, 1 << 14)   # whatever size it grows to
        self._still.show()
        self._still.raise_()

    def _thaw(self) -> None:
        """Laid out once for the size the window has, and shown as it really is."""
        self._rest.stop()
        if self._still is None:
            return
        still, self._still = self._still, None
        if self.dragging:   # (let go: fitctl.live(False) fits it all, measuring fresh)
            self.mw.fitctl._refit()
            self._hold_pads(False)   # (held again as the edge moves on: _freeze)
        still.hide()
        still.deleteLater()

    def sizing(self, message) -> bool:
        """From nativeEvent: True when it held a size back (the message is handled; answer
        TRUE): while the edge is dragged, a new size at most every STEP_MS. A size asked
        for too soon is given a moment later, so the window still ends up exactly where
        the edge stopped. Every Windows message passes here: one read of its id."""
        if sys.platform != "win32":
            return False
        if c_uint.from_address(int(message) + _MSG_ID).value != WM_SIZING:
            return False
        msg = wintypes.MSG.from_address(int(message))
        wait = self._last + STEP_MS / 1000 - time.monotonic()
        if wait <= 0:
            self._last = time.monotonic()
            self._held = None
            self._step.stop()
            return False
        rect = wintypes.RECT.from_address(msg.lParam)
        self._held = (int(msg.hWnd or 0), rect.left, rect.top,
                      rect.right - rect.left, rect.bottom - rect.top)
        now = wintypes.RECT()
        if _user32().GetWindowRect(msg.hWnd, byref(now)):
            rect.left, rect.top, rect.right, rect.bottom = (now.left, now.top,
                                                            now.right, now.bottom)
        if not self._step.isActive():
            self._step.start(max(1, round(wait * 1000)))
        return True

    def flush(self) -> None:
        """Give the window the size held back (its moment came, or the edge was let go)."""
        self._step.stop()
        if self._held is None:
            return
        hwnd, x, y, w, h = self._held
        self._held = None
        self._last = time.monotonic()
        _user32().SetWindowPos(hwnd, None, x, y, w, h, _SWP_NOZORDER | _SWP_NOACTIVATE)


_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010


def _user32():
    import ctypes
    return ctypes.windll.user32
