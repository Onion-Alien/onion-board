"""A soft glow in the theme's accent round the one button a step wants pressed (put my
sounds into my mic): among the setup card's colours it was easy to miss, and the cable's
button beside it got pressed instead. It breathes slowly while the button is on screen,
and stays still when Windows' animation effects are off."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QEvent, QObject, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QAbstractButton, QGraphicsDropShadowEffect, QHBoxLayout, QWidget

from soundboard.ui.kit import theme

PERIOD_S = 2.4     # one breath
TICK_MS = 66       # ~15 a second: enough for a slow glow, light on the UI thread
BLUR = (22, 44)    # px, out and in
ALPHA = (170, 255)


class Glow(QObject):
    """`Glow(button)`: on from the start; `set_on(False)` takes it off (the button isn't
    the main thing any more), `set_on(True)` puts it back. `tone="warn"` glows in the
    theme's warning colour (a step still to do, like the "1 step left" pill)."""

    def __init__(self, button: QAbstractButton, tone: str = ""):
        super().__init__(button)
        self.button = button
        self.tone = tone
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
        c = QColor(theme.status(self.tone) if self.tone else theme.T.get("accent", "#8b5cf6"))
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


class Halo(QWidget):
    """A bright glow painted round one button (Edit sound's Reset effects while any
    effect is on): soft rings in the theme's accent, strongest at the button's edge,
    breathing like Glow. A drop shadow (Glow) is too faint round a small button. It
    holds the button with `pad` px of room on every side for the rings; `set_on`."""

    def __init__(self, button: QAbstractButton, pad: int = 9, radius: float = 7.0):
        super().__init__()
        self.button, self.pad, self.radius = button, pad, radius
        lay = QHBoxLayout(self)
        lay.setContentsMargins(pad, pad, pad, pad)
        lay.addWidget(button)
        self._on = False
        self._k = 1.0
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)

    def is_on(self) -> bool:
        return self._on

    def set_on(self, on: bool):
        if on != self._on:
            self._on = on
            self._k = 1.0
            self._sync_timer()
            self.update()

    def _sync_timer(self):
        from soundboard.ui.kit.toast import animations_on
        if self._on and self.isVisible() and animations_on():
            self._timer.start()
        else:
            self._timer.stop()

    def showEvent(self, e):
        super().showEvent(e)
        self._sync_timer()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._timer.stop()

    def _tick(self):
        self._k = 0.5 - 0.5 * math.cos(2 * math.pi * (time.monotonic() % PERIOD_S) / PERIOD_S)
        self.update()

    def paintEvent(self, e):
        if not self._on or not self.button.isVisible():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        c = QColor(theme.T.get("accent", "#8b5cf6"))
        r = QRectF(self.button.geometry())
        peak = 70 + 50 * self._k          # each ring's alpha at the edge; they add up
        reach = self.pad * (0.7 + 0.3 * self._k)
        steps = max(1, round(reach))
        for i in range(steps, 0, -1):     # outside in: the inner rings stack brightest
            grow = reach * i / steps
            c.setAlpha(round(peak * (1 - i / (steps + 1)) ** 2))
            p.setBrush(c)
            p.drawRoundedRect(r.adjusted(-grow, -grow, grow, grow),
                              self.radius + grow, self.radius + grow)
        p.end()
