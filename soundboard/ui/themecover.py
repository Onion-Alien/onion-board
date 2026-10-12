"""A still of the window over it while the theme changes, faded out afterwards.

Restyling every widget takes a moment on a full board (seconds on a busy PC), and a
frame painted part way through showed the app half styled: Qt's plain look, or the
old theme's colours on some parts and the new one's on others. Like other polished
desktop apps (a Qt chat client fades its old frame out the same way), the window
shows a picture of itself, dimmed, with Bun in the middle until the new theme is in,
then fades to it. The cover is a child of the window: no window of its own appears.
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

from soundboard import theme
from soundboard.ui.pixels import snap_to_pixels

FADE_MS = 180
BUNNY_H = 96


class ThemeCover(QWidget):
    def __init__(self, window: QWidget):
        super().__init__(window)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setGeometry(window.rect())
        dpr = window.devicePixelRatioF() or 1.0
        self.still: QPixmap = window.grab()
        # the old theme's colours: what's under the cover until it fades
        self.scrim = QColor(theme.T["bg"])
        self.scrim.setAlpha(150)
        from soundboard.bunny import bunny_pixmap
        self.bunny = bunny_pixmap(BUNNY_H, dpr=dpr)
        self._fade: QPropertyAnimation | None = None

    def paintEvent(self, _e):
        p = QPainter(self)
        # opaque: the full cover goes down before snap_to_pixels, or its nudge leaves
        # an edge row of whatever was on screen before
        p.drawPixmap(self.rect(), self.still)
        p.fillRect(self.rect(), self.scrim)
        snap_to_pixels(p)
        size = self.bunny.deviceIndependentSize()
        at = QRectF((self.width() - size.width()) / 2, (self.height() - size.height()) / 2,
                    size.width(), size.height())
        p.drawPixmap(at, self.bunny, QRectF(self.bunny.rect()))
        p.end()

    def cover(self):
        """Up on screen now, before the UI thread gets busy restyling."""
        self.raise_()
        self.show()
        self.repaint()

    def uncover(self):
        """Fade to the restyled window, then go."""
        self.raise_()
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        fade = self._fade = QPropertyAnimation(effect, b"opacity", self)
        fade.setDuration(FADE_MS)
        fade.setStartValue(1.0)
        fade.setEndValue(0.0)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade.finished.connect(self.deleteLater)
        fade.start()


def covered(window: QWidget):
    """The cover over `window` for a `with` block (None when it isn't on screen)."""
    return _Covered(window)


class _Covered:
    def __init__(self, window: QWidget):
        # a quick second click: the last cover may still be fading, and a still taken
        # through it would show the theme before that one
        direct = Qt.FindChildOption.FindDirectChildrenOnly
        for old in window.findChildren(ThemeCover, options=direct):
            old.hide()
            old.deleteLater()
        self.cover = (ThemeCover(window) if window.isVisible() and not window.isMinimized()
                      else None)

    def __enter__(self):
        if self.cover is not None:
            self.cover.cover()
        return self.cover

    def __exit__(self, *_exc):
        if self.cover is not None:
            self.cover.uncover()
        return False
