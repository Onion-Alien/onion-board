from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage, QPainter, QRegion
from PySide6.QtWidgets import QWidget

from soundboard.ui.widgets import PadGrid


class _Plain(QWidget):
    def paintEvent(self, e):
        QPainter(self).fillRect(e.rect(), QColor(0, 0, 0))


def _rows(widget, oy) -> list[int]:
    pink = QColor(255, 0, 255)
    img = QImage(400, 300, QImage.Format.Format_ARGB32)
    img.setDevicePixelRatio(1.25)
    img.fill(pink)
    widget.render(img, QPoint(0, oy), QRegion(0, 10, 300, 21),
                  QWidget.RenderFlag.DrawChildren)
    return [y for y in range(300) if img.pixelColor(150, y) != pink]


def test_board_repaint_leaves_no_old_pixels_at_125(qapp):
    # the board is opaque (nothing clears under it), so a part of it repainted at a
    # fractional scale must cover every screen pixel of that part: a missed row kept
    # the old picture, thin lines behind the cards after a scroll
    grid, plain = PadGrid(), _Plain()
    for w in (grid, plain):
        w.resize(300, 200)
    for oy in range(4):
        assert _rows(grid, oy) == _rows(plain, oy), oy
