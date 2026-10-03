"""A glowing, gently pulsing dot that marks a tab whose feature is live right now
(the Voice tab while the voice changer is changing your mic, Radio while a station
plays, Apps while a program's sound is sent, Triggers while the screen is watched),
so it can't be left on by accident without you noticing from another tab. The tab's
name is drawn in the live colour too."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPalette, QRadialGradient
from PySide6.QtWidgets import QProxyStyle, QStyleFactory, QTabBar, QTabWidget, QWidget

from soundboard import theme
from soundboard.ui import appstate, icons

GREEN = "#13ce66"     # the dot and the tab's icon: the same green as the voice changer's ON switch
BASE_STYLE = "Fusion"   # the app's widget style (app.py); the tab bar's own style sits on it


def live_color() -> str:
    """The colour a live tab's name is drawn in: the theme's "ok" green (the light
    themes darken it so it can be read)."""
    return theme.status("ok")


class LiveDot(QWidget):
    """A green dot with a soft halo that breathes (the halo, not the dot, so it
    stays readable). Animation runs only while the dot is shown and the app is in
    front, at 15 frames a second: a slow breath doesn't need more."""

    SIZE = 20

    def __init__(self, color: str = GREEN, parent: QWidget | None = None):
        super().__init__(parent)
        self._color = QColor(color)
        self._glow = 1.0
        self.setFixedSize(QSize(self.SIZE, self.SIZE))
        self.setAttribute(Qt.WA_TransparentForMouseEvents)   # clicks go to the tab
        self._timer = QTimer(self)
        self._timer.setInterval(66)
        self._timer.setTimerType(Qt.CoarseTimer)
        self._timer.timeout.connect(self._step)
        appstate.pause_in_background(self, self._timer.start, self._timer.stop)

    def _step(self):
        # 1 → 0.25 → 1 every 1.4 s
        phase = (time.monotonic() % 1.4) / 1.4
        self._glow = 0.625 + 0.375 * math.cos(2 * math.pi * phase)
        self.update()

    def showEvent(self, e):
        if appstate.active():
            self._timer.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        halo = QRadialGradient(c, self.SIZE / 2)
        inner = QColor(self._color)
        inner.setAlphaF(0.75 * self._glow)
        outer = QColor(self._color)
        outer.setAlphaF(0.0)
        halo.setColorAt(0.3, inner)
        halo.setColorAt(1.0, outer)
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(c, self.SIZE / 2, self.SIZE / 2)
        p.setBrush(self._color)
        p.drawEllipse(c, 4, 4)


class LiveTabStyle(QProxyStyle):
    """Draws the names of a tab bar's live tabs in the live colour. The theme's
    stylesheet gives every tab its text colour, which wins over
    QTabBar.setTabTextColor, but it leaves the actual drawing of the text to the
    style beneath it: this one, which swaps the colour for a live tab. It reads the
    theme when it paints, so a theme change needs nothing beyond the repaint it
    causes anyway. Owned by the tab bar (its child)."""

    def __init__(self, bar: QTabBar):
        super().__init__(QStyleFactory.create(BASE_STYLE))
        self.setParent(bar)

    def drawItemText(self, painter, rect, flags, pal, enabled, text, role=QPalette.NoRole):
        bar = self.parent()
        if text and isinstance(bar, QTabBar):
            for i in range(bar.count()):
                if _dot(bar, i) is not None and bar.tabRect(i).contains(rect.center()):
                    pal = QPalette(pal)
                    pal.setColor(role, QColor(live_color()))
                    break
        super().drawItemText(painter, rect, flags, pal, enabled, text, role)


def _dot(bar: QTabBar, index: int) -> LiveDot | None:
    dot = bar.tabButton(index, QTabBar.RightSide)
    return dot if isinstance(dot, LiveDot) else None


def set_tab_live(tabs: QTabWidget, index: int, on: bool, tip: str = "",
                 icon: str | None = None):
    """Show (or remove) a LiveDot on a tab, draw its name in the live colour, and put
    `tip` in front of its tooltip while it's live. `icon` names the tab's icon,
    turned green while live."""
    if icon:
        icons.set_tab_icon(tabs, index, icon, GREEN if on else None)
    bar = tabs.tabBar()
    if bar.findChild(LiveTabStyle) is None:
        bar.setStyle(LiveTabStyle(bar))
    dot = _dot(bar, index)
    base = tabs.property(f"_tip{index}")
    if base is None:
        base = tabs.tabToolTip(index)
        tabs.setProperty(f"_tip{index}", base)
    if on:
        if dot is None:
            dot = LiveDot()
            bar.setTabButton(index, QTabBar.RightSide, dot)
        dot.show()
        tabs.setTabToolTip(index, f"{tip}\n{base}" if tip else base)
    else:
        if dot is not None:
            bar.setTabButton(index, QTabBar.RightSide, None)
            dot.deleteLater()
        tabs.setTabToolTip(index, base)
    bar.update()   # the name's colour


def is_tab_live(tabs: QTabWidget, index: int) -> bool:
    return _dot(tabs.tabBar(), index) is not None
