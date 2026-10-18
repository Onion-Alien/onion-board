"""A soft glow in the theme's accent round the one button a step wants pressed (put my
sounds into my mic): among the setup card's colours it was easy to miss, and the cable's
button beside it got pressed instead. It breathes slowly while the button is on screen,
and stays still when Windows' animation effects are off."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractButton, QGraphicsDropShadowEffect

from soundboard.ui.kit import theme

PERIOD_S = 2.4     # one breath
TICK_MS = 66       # ~15 a second: enough for a slow glow, light on the UI thread
BLUR = (22, 44)    # px, out and in
ALPHA = (170, 255)


class Glow(QObject):
    """`Glow(button)`: on from the start; `set_on(False)` takes it off (the button isn't
    the main thing any more), `set_on(True)` puts it back."""

    def __init__(self, button: QAbstractButton):
        super().__init__(button)
        self.button = button
        self._on = True
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._effect: QGraphicsDropShadowEffect | None = None
        button.installEventFilter(self)
        self._apply()

    def set_on(self, on: bool):
        if on != self._on:
            self._on = on
            self._apply()

    def _apply(self):
        b = self.button
        # only while it's on screen: an effect left on a hidden button upset the layout
        # of the page round it (the guide's optional tiles stayed at half width)
        if not self._on or not b.isVisible():
            self._timer.stop()
            if self._effect is not None:
                # (Qt deletes the effect; None is what clears it, PySide's stub misses it)
                b.setGraphicsEffect(None)   # pyright: ignore[reportArgumentType]
                self._effect = None
            return
        if self._effect is None:
            self._effect = QGraphicsDropShadowEffect(b)
            self._effect.setOffset(0, 0)
            b.setGraphicsEffect(self._effect)
        self._paint(1.0)
        self._sync_timer()

    def _sync_timer(self):
        from soundboard.ui.kit.toast import animations_on
        if self._on and self.button.isVisible() and animations_on():
            self._timer.start()
        else:
            self._timer.stop()

    def _tick(self):
        k = 0.5 - 0.5 * math.cos(2 * math.pi * (time.monotonic() % PERIOD_S) / PERIOD_S)
        self._paint(k)

    def _paint(self, k: float):
        if self._effect is None:
            return
        c = QColor(theme.T.get("accent", "#8b5cf6"))
        c.setAlpha(round(ALPHA[0] + (ALPHA[1] - ALPHA[0]) * k))
        self._effect.setColor(c)
        self._effect.setBlurRadius(BLUR[0] + (BLUR[1] - BLUR[0]) * k)

    def eventFilter(self, obj, e):
        t = e.type()
        if t in (QEvent.Type.Show, QEvent.Type.Hide):
            # after the event, not in it: an effect swapped while the button was being
            # shown or hidden left the page's layout half done (the guide's tiles)
            QTimer.singleShot(0, self, self._apply)
        elif t in (QEvent.Type.StyleChange, QEvent.Type.PaletteChange):
            self._paint(1.0)   # a new theme: its accent
        return False
