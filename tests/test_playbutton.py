import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from soundboard.ui.kit import icons
from soundboard.ui.kit.playbutton import PlayButton


def test_round_play_button_keeps_keyboard_mouse_and_disabled_behavior(qapp):
    button = PlayButton()
    button.resize(36, 36)
    icons.set_icon(button, 'play', 'on_accent', size=16)
    clicked = []
    button.clicked.connect(lambda: clicked.append(True))
    button.show()
    button.setFocus()
    QTest.keyClick(button, Qt.Key.Key_Space)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert len(clicked) == 2
    assert button.iconSize().width() == 16
    button.setEnabled(False)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert len(clicked) == 2
    assert not button.grab().isNull()
    button.deleteLater()


@pytest.mark.parametrize("scale, x", [(1.25, 10), (1.5, 11), (1.75, 10), (1.75, 11)])
def test_round_play_button_stays_round_at_fractional_scales(qapp, scale, x):
    """At 125 % the button starts half a pixel in (x 10 -> pixel 12.5); Qt keeps the
    pixels from 13, so the circle lost its left edge and looked flat there."""
    holder = QWidget()
    holder.resize(60, 46)
    holder.setStyleSheet("background:#000000")
    button = PlayButton(holder)
    button.setGeometry(x, 5, 36, 36)
    img = QImage(round(60 * scale), round(46 * scale), QImage.Format.Format_ARGB32)
    img.setDevicePixelRatio(scale)
    img.fill(QColor("#000000"))
    holder.render(img)
    left, right = [], []
    for y in range(img.height()):
        lit = [x for x in range(img.width()) if QColor(img.pixel(x, y)).lightness() > 40]
        if lit:
            left.append(lit[0])
            right.append(lit[-1])
    # as many rows reach the far left as the far right: round on both sides
    assert abs(left.count(min(left)) - right.count(max(right))) <= 1
    holder.deleteLater()
