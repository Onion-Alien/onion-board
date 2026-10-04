"""The start-up splash: Bun hopping about in the middle of the screen, from the
moment the QApplication exists until the main window is up. Just Bun on the
desktop (no card, spinner or caption), his headphones in the saved theme's accent
(read straight from config.json; the rest of the settings load later).

A cold start (first launch after a reboot, files not yet cached) can spend several
seconds importing and building the window, all on the UI thread, so nothing would
animate on its own. `pump()` repaints the splash at most every frame; `show()`
also hooks the import system so every module loaded meanwhile pumps it, and
MainWindow calls `pump()` between its slower steps. Without a splash on screen
`pump()` does nothing, so it's safe to call anywhere.
"""
from __future__ import annotations

import json
import math
import os
import sys
import threading
import time

from pathlib import Path

from PySide6.QtCore import QEventLoop, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from soundboard import theme
from soundboard.bunny import draw_bunny

CARD_W, CARD_H = 240, 190
BUN_W, BUN_H = 90, 108
HOP = 0.62       # seconds per hop
HOP_PX = 26      # how high he gets
ROAM_PX = 55     # how far he wanders either side of the middle
FRAME = 1 / 30   # seconds between repaints while pumping
# library.CONFIG_PATH, without importing library (numpy, soundfile...) this early
CONFIG = Path(os.environ.get("APPDATA", Path.home())) / "OnionBoard" / "config.json"

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
        u = (t % HOP) / HOP                     # 0..1 through this hop
        air = 4 * u * (1 - u)                   # 0 on the ground, 1 at the top
        land = max(0.0, 1 - u / 0.18)           # just landed: squash, ears flop
        wander = math.sin(t * 0.9)
        facing = 1 if math.cos(t * 0.9) >= 0 else -1   # the way he's heading
        stretch = 1 + 0.08 * air - 0.14 * land   # taller in the air, squat on landing
        foot_x = self.width() / 2 + wander * ROAM_PX
        foot_y = self.height() - 12
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # a soft shadow on the ground, smaller while he's up
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, round(70 - 40 * air)))
        sw = 56 * (1 - 0.35 * air)
        p.drawEllipse(QRectF(foot_x - sw / 2, foot_y - 4, sw, 8))
        # Bun, squashed about his feet and mirrored to face where he's going
        p.translate(foot_x, foot_y - HOP_PX * air)
        p.scale(facing / stretch ** 0.5, stretch)
        blink = 1.0 if (t % 2.7) > 2.55 else 0.0
        draw_bunny(p, QRectF(-BUN_W / 2, -BUN_H, BUN_W, BUN_H),
                   blink=blink, ears=14 * land - 6 * air)
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
    try:
        theme.set_current(json.loads(CONFIG.read_text(encoding="utf-8-sig")).get("theme", ""))
    except Exception:  # noqa: BLE001 - first launch, or unreadable: the default theme
        pass
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
