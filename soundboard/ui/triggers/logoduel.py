"""A brief, silent laser duel between the two logos on the Triggers page."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from soundboard.ui.kit import theme
from soundboard.ui.kit import appstate
from soundboard.ui.bun.splash import _animations_enabled

FRAME_MS = 33
SHOT_S = 0.48
ROUNDS = 4


class LogoDuel(QObject):
    def __init__(self, tab):
        super().__init__(tab)
        self.tab = tab
        self.logos: tuple[QWidget, ...] = ()
        self.overlay: _Lasers | None = None
        tab.installEventFilter(self)

    def bind(self):
        """Optional add-on UI: older versions without a logo keep their own clicks."""
        self.stop()
        for logo in self.logos:
            logo.removeEventFilter(self)
        self.logos = ()
        board = getattr(self.tab.window(), "logo", None)
        pages = getattr(self.tab.panel, "pages", None)
        watch = getattr(pages, "logo", None)
        if isinstance(board, QWidget) and isinstance(watch, QWidget):
            self.logos = (board, watch)
            for logo in self.logos:
                logo.installEventFilter(self)

    def stop(self):
        if self.overlay is not None:
            self.overlay.stop()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Hide:
            self.stop()
        elif (obj in self.logos and event.type() == QEvent.Type.MouseButtonPress
              and event.button() == Qt.MouseButton.LeftButton
              and self.tab.isVisible() and all(w.isVisible() for w in self.logos)
              and _animations_enabled()):
            if self.overlay is None:
                self.overlay = _Lasers(self, self.tab.window())
            self.overlay.start(self.logos.index(obj))
            event.accept()
            return True
        return False


class _Lasers(QWidget):
    def __init__(self, duel: LogoDuel, host: QWidget):
        super().__init__(host)
        self.duel = duel
        self.host = host
        self.elapsed = 0.0
        self.first = 0
        self._last = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.timer = QTimer(self)
        self.timer.setInterval(FRAME_MS)
        self.timer.timeout.connect(self._tick)
        appstate.pause_in_background(self, self.stop, self.stop)
        self.hide()

    def start(self, first: int):
        # Repeat clicks restart the same bounded exchange; no queued timers or layers.
        self.first, self.elapsed = first, 0.0
        self._last = time.monotonic()
        self.setGeometry(self.host.rect())
        self.show()
        self.raise_()
        self.timer.start()
        self.update()

    def stop(self):
        self.timer.stop()
        self.hide()

    def _tick(self):
        now = time.monotonic()
        self.advance(min(0.1, now - self._last))
        self._last = now

    def advance(self, dt: float):
        self.elapsed += dt
        if (self.elapsed >= SHOT_S * ROUNDS or not self.duel.tab.isVisible()
                or not all(w.isVisible() for w in self.duel.logos)):
            self.stop()
        else:
            self.setGeometry(self.host.rect())
            self.update()

    def _eye(self, widget: QWidget) -> QPointF:
        origin = widget.mapTo(self, QPoint(0, 0))
        eye = getattr(widget, "eye_center", None)
        if callable(eye):
            center = eye()
            if isinstance(center, QPointF):
                return QPointF(origin) + center
        return QPointF(origin) + QPointF(widget.width() * 0.5, widget.height() * 0.60)

    def paintEvent(self, _event):
        if len(self.duel.logos) != 2:
            return
        shot = int(self.elapsed / SHOT_S)
        phase = (self.elapsed % SHOT_S) / SHOT_S
        source = (self.first + shot) % 2
        a = self._eye(self.duel.logos[source])
        b = self._eye(self.duel.logos[1 - source])
        tip = a + (b - a) * min(1.0, phase / 0.42)
        tail = a + (b - a) * max(0.0, (phase - 0.32) / 0.68)
        color = QColor(theme.T["accent" if source == 0 else "accent2"])
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for width, alpha in ((11, 35), (6, 95), (2, 255)):
            color.setAlpha(alpha)
            p.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(tail, tip)
        if 0.42 <= phase < 0.92:
            burst = (phase - 0.42) / 0.5
            color.setAlpha(round(255 * (1 - burst)))
            p.setPen(QPen(color, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            for i in range(8):
                angle = i * math.tau / 8 + shot
                ray = QPointF(math.cos(angle), math.sin(angle))
                p.drawLine(b + ray * (4 + burst * 5), b + ray * (8 + burst * 12))
        p.end()
