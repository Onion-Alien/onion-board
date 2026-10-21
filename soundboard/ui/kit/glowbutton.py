"""GlowButton: a primary button with a soft accent glow round it, for the one thing to
press before a card works (the AI voices and speech recognition installs)."""
from __future__ import annotations

from PySide6.QtCore import QEvent
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QPushButton

from soundboard.ui.kit import theme


class GlowButton(QPushButton):
    """A primary button with a soft accent glow round it: the one thing to press before
    a switch works (greyed till then, which alone didn't say why)."""

    def __init__(self, text: str):
        super().__init__(text)
        self.setObjectName("primary")
        self._glow = QGraphicsDropShadowEffect(self)
        self._glow.setOffset(0, 0)
        self._glow.setBlurRadius(40)
        self.setGraphicsEffect(self._glow)
        self._recolour()

    def _recolour(self):
        self._glow.setColor(QColor(theme.T.get("accent", "#7c5cff")))

    def changeEvent(self, e):
        if e.type() == QEvent.Type.StyleChange:   # a theme change: the new accent
            self._recolour()
        super().changeEvent(e)
