"""Playback's round button, with one antialiased circular edge."""
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QPushButton, QStyle, QStyleOptionButton

from soundboard import theme
from soundboard.ui.pixels import snap_to_pixels


class PlayButton(QPushButton):
    """Keep QPushButton input and icons; paint the circle without CSS border joins."""

    def paintEvent(self, event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        hover = enabled and bool(option.state & QStyle.StateFlag.State_MouseOver)
        down = enabled and bool(option.state & QStyle.StateFlag.State_Sunken)
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
        tokens = theme.T
        side = min(self.width(), self.height())
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2,
                      side, side).adjusted(0.5, 0.5, -0.5, -0.5)
        painter = QPainter(self)
        snap_to_pixels(painter)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not enabled:
            fill = QColor(tokens['btn'])
            edge = QColor(tokens['border'])
        elif theme.polished():
            shades = theme._accent_shades(tokens)
            if down:
                fill = QColor(shades['accent_press'])
            else:
                fill = QLinearGradient(rect.topLeft(), rect.bottomRight())
                fill.setColorAt(0, QColor(shades['accent_top_hi' if hover else 'accent_top']))
                fill.setColorAt(0.3, QColor(tokens['accent_hover' if hover else 'accent']))
                fill.setColorAt(1, QColor(shades['accent_end_hi' if hover else 'accent_end']))
            edge = QColor(theme.mix(tokens['accent'], tokens['text_hi'], 0.16))
        else:
            fill = QColor(tokens['accent_hover' if hover else 'accent'])
            edge = QColor(tokens['accent'])
        painter.setBrush(fill)
        painter.setPen(QPen(QColor(tokens['text_hi']) if focused else edge, 1.0))
        painter.drawEllipse(rect)
        self.style().drawControl(QStyle.ControlElement.CE_PushButtonLabel, option, painter, self)
        painter.end()
