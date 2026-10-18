"""Mouse clicks toggle tick boxes without capturing the keyboard focus."""
import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QCheckBox, QPushButton, QVBoxLayout, QWidget

from soundboard.ui.kit import theme


@pytest.mark.parametrize("name", theme.THEMES)
def test_mouse_toggle_keeps_focus_and_tab_space_still_work(qapp, name):
    previous = theme.current_name
    host = QWidget()
    layout = QVBoxLayout(host)
    start = QPushButton("Start", host)
    check = QCheckBox("Option", host)
    end = QPushButton("End", host)
    for widget in (start, check, end):
        layout.addWidget(widget)
    QWidget.setTabOrder(start, check)
    QWidget.setTabOrder(check, end)
    try:
        theme.apply(qapp, name)
        host.show()
        host.activateWindow()
        qapp.processEvents()
        start.setFocus()
        assert start.hasFocus()
        for expected in (True, False, True):
            QTest.mouseClick(check, Qt.MouseButton.LeftButton)
            assert check.isChecked() == expected
            assert start.hasFocus() and not check.hasFocus()
        QTest.keyClick(start, Qt.Key.Key_Tab)
        assert check.hasFocus()
        QTest.keyClick(check, Qt.Key.Key_Space)
        assert not check.isChecked() and check.hasFocus()
        QTest.keyClick(check, Qt.Key.Key_Tab)
        assert end.hasFocus()
        QTest.keyClick(end, Qt.Key.Key_Backtab)
        assert check.hasFocus()
    finally:
        host.close()
        host.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        theme.apply(qapp, previous)


def test_explicit_no_focus_checkbox_is_preserved(qapp):
    check = QCheckBox("Display only")
    check.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    check.ensurePolished()
    try:
        assert check.focusPolicy() == Qt.FocusPolicy.NoFocus
    finally:
        check.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
