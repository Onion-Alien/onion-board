"""The start-up splash: Bun in the middle of the screen with a spinner, from the
moment the QApplication exists until the main window is up.

A cold start (first launch after a reboot, files not yet cached) can spend several
seconds importing and building the window, all on the UI thread, so nothing would
animate on its own. `pump()` repaints the splash at most every frame; `show()`
also hooks the import system so every module loaded meanwhile pumps it, and
MainWindow calls `pump()` between its slower steps. Without a splash on screen
`pump()` does nothing, so it's safe to call anywhere.
"""
from __future__ import annotations

import math
import sys
import threading
import time

from PySide6.QtCore import QEventLoop, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from soundboard.bunny import draw_bunny

CARD_W, CARD_H = 260, 250
CARD = QColor("#1e1a2b")
CARD_EDGE = QColor("#3a3352")
TEXT = QColor("#d9d2e6")
ARC = (QColor("#7c5cff"), QColor("#ff4d8d"))   # the logo's colours
FRAME = 1 / 30   # seconds between repaints while pumping

_splash: Splash | None = None
_last = 0.0


class Splash(QWidget):
    def __init__(self):
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)   # don't take focus from a game
        self.setWindowTitle("Onion Board")
        self.setFixedSize(CARD_W, CARD_H)
        self._t0 = time.monotonic()

    def paintEvent(self, ev):
        t = time.monotonic() - self._t0
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(CARD_EDGE, 1.5))
        p.setBrush(CARD)
        p.drawRoundedRect(r, 22, 22)
        # Bun, bobbing gently
        bob = math.sin(t * 3.2) * 3
        draw_bunny(p, QRectF(r.center().x() - 50, 22 + bob, 100, 120))
        # the spinner: an arc chasing round, its length breathing in and out
        ring = QRectF(r.center().x() - 16, 160, 32, 32)
        p.setPen(QPen(CARD_EDGE, 4))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(ring)
        span = 70 + 160 * (0.5 + 0.5 * math.sin(t * 2.4))
        pen = QPen(ARC[0], 4)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(ring, int(-t * 360 * 16) % (360 * 16), int(span * 16))
        p.setPen(TEXT)
        f = QFont(self.font())
        f.setPointSizeF(10)
        p.setFont(f)
        p.drawText(QRectF(r.left(), 200, r.width(), 24), Qt.AlignCenter,
                   "Loading Onion Board" + "." * (int(t * 2.5) % 4))
        p.end()


class _PumpOnImport:
    """A meta-path finder that finds nothing: it only pumps the splash each time a
    module is imported, which is most of what a cold start spends its time on."""

    @staticmethod
    def find_spec(name, path=None, target=None):
        pump()
        return None


def show() -> Splash:
    """Put the splash up, centred on the screen the mouse is on."""
    global _splash
    _splash = Splash()
    screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
    if screen is not None:
        geo = screen.availableGeometry()
        _splash.move(geo.center().x() - CARD_W // 2, geo.center().y() - CARD_H // 2)
    _splash.show()
    _splash.repaint()
    QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
    sys.meta_path.insert(0, _PumpOnImport)
    return _splash


def pump():
    """Repaint the splash if a frame's time has passed (UI thread only)."""
    global _last
    if _splash is None or threading.current_thread() is not threading.main_thread():
        return
    now = time.monotonic()
    if now - _last < FRAME:
        return
    _last = now
    _splash.update()
    QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)


def close():
    """Take the splash down (the window is up, or start-up failed)."""
    global _splash
    try:
        sys.meta_path.remove(_PumpOnImport)
    except ValueError:
        pass
    if _splash is not None:
        _splash.close()
        _splash.deleteLater()
        _splash = None
