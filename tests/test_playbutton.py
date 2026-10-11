from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from soundboard.ui import icons
from soundboard.ui.playbutton import PlayButton


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
