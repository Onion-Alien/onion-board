"""A button's focus ring is for the keyboard: a dialog that opens hands its first button
the focus by itself, and the theme's :focus rule used to ring it at once, so it looked
picked while the mouse was elsewhere (and hovering it barely showed)."""
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QPushButton, QVBoxLayout

from soundboard.ui.kit import theme, widgets


def _pixels(w):
    img = w.grab().toImage()
    return np.frombuffer(img.constBits(), np.uint8, count=img.sizeInBytes()).copy()


def test_rings_need_the_keyboard_in_the_style_sheet():
    css = theme.key_focus_only(
        "/* a, b :focus */ QPushButton:focus { border-color:red; }\n"
        "QFrame#card QPushButton#primary:focus, QPushButton:checked:focus { border:1px; }\n"
        "QCheckBox::indicator:focus { border-color:red; }\n"
        "QLineEdit:focus { border-color:red; }")
    assert 'QPushButton[keyfocus="true"]:focus {' in css
    assert 'QFrame#card QPushButton#primary[keyfocus="true"]:focus, ' \
           'QPushButton[keyfocus="true"]:checked:focus' in css
    assert 'QCheckBox[keyfocus="true"]::indicator:focus' in css
    assert "QLineEdit:focus" in css           # a box you type in keeps its ring
    assert "/*" not in css                    # comments can't split a rule open


def test_a_dialog_opening_rings_no_button_but_tab_does(qapp):
    # (only the ring part of install_click_focus: its polish hook would change every
    # later test's focus policies in this process)
    qapp.focusChanged.connect(widgets.key_focus_rings)
    theme.apply(qapp, "Dark")
    d = QDialog()
    lay = QVBoxLayout(d)
    first, second = QPushButton("First"), QPushButton("Second")
    lay.addWidget(first)
    lay.addWidget(second)
    try:
        d.show()
        d.activateWindow()
        for _ in range(5):
            qapp.processEvents()
        assert d.focusWidget() is first               # Qt gave it the focus by itself...
        assert not first.property(widgets.KEY_FOCUS)  # ...but not from the keyboard
        at_rest = _pixels(first)
        first.clearFocus()
        qapp.processEvents()
        assert np.array_equal(at_rest, _pixels(first))   # no ring: as without the focus
        second.setFocus(Qt.FocusReason.OtherFocusReason)
        QTest.keyClick(second, Qt.Key.Key_Backtab)       # the keyboard: ringed
        qapp.processEvents()
        assert d.focusWidget() is first and first.property(widgets.KEY_FOCUS)
        assert not np.array_equal(at_rest, _pixels(first))
    finally:
        qapp.focusChanged.disconnect(widgets.key_focus_rings)
        d.close()
        d.deleteLater()
