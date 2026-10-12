"""Dropdowns settle closed during rapid clicks, then reopen after a short pause."""
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QComboBox, QMenu, QPushButton, QWidget

from soundboard import wheelguard
from soundboard.ui.langpick import LanguageDialog


@pytest.mark.parametrize("kind", ["language", "menu", "combo"])
def test_mouse_burst_stays_closed_then_reopens(qapp, monkeypatch, kind):
    clock = [100.0]
    monkeypatch.setattr(wheelguard, "time", type("Clock", (), {
        "monotonic": staticmethod(lambda: clock[0])}))
    button = QComboBox() if kind == "combo" else QPushButton("Open")
    button.resize(160, 40)
    if kind == "combo":
        button.addItems(["First", "Second"])
        popup = button.view().window()
        open_popup = button.showPopup
    elif kind == "menu":
        popup = QMenu(button)
        popup.addAction("First")
        open_popup = lambda: popup.popup(button.mapToGlobal(QPoint(0, 45)))
        button.clicked.connect(open_popup)
    else:
        popup = LanguageDialog(current="en")
        open_popup = lambda: popup.open_under(button)
        button.clicked.connect(open_popup)
    button.show()
    try:
        QTest.mouseClick(button, Qt.LeftButton)
        assert popup.isVisible()
        popup.hide()
        for _ in range(20):
            clock[0] += 0.1  # ten clicks per second, longer than one cooldown
            QTest.mouseClick(button, Qt.LeftButton)
            assert not popup.isVisible()
            assert button.isEnabled()
        clock[0] += 0.3
        QTest.mouseClick(button, Qt.LeftButton)
        assert popup.isVisible()
        QTest.keyClick(popup, Qt.Key_Escape)
        assert not popup.isVisible()
        # Keyboard reopening is immediate, even during the mouse cooldown.
        if kind == "combo":
            QTest.keyClick(button, Qt.Key_Down, Qt.AltModifier)
        else:
            QTest.keyClick(button, Qt.Key_Space)
        assert popup.isVisible()
    finally:
        popup.close()
        button.close()
        popup.deleteLater()
        button.deleteLater()


def test_regular_button_double_click_is_unchanged(qapp):
    button = QPushButton("Action")
    clicks = []
    button.clicked.connect(lambda: clicks.append(1))
    button.show()
    try:
        for _ in range(10):
            QTest.mouseClick(button, Qt.LeftButton)
        assert len(clicks) == 10
    finally:
        button.close()
        button.deleteLater()


def test_submenu_dismissal_does_not_throttle_root_opener(qapp):
    button = QPushButton("Open")
    root = QMenu(button)
    sub = root.addMenu("More")
    sub.addAction("Item")
    button.show()
    try:
        root.popup(QPoint(200, 100))
        sub.popup(QPoint(400, 100))
        sub.hide()
        assert button.property("popupClosedAt") is None
    finally:
        root.close()
        button.close()
        button.deleteLater()


def test_menu_owned_by_panel_still_throttles_its_button(qapp):
    panel = QWidget()
    button = QPushButton("Edit", panel)
    menu = QMenu(panel)
    menu.addAction("Item")
    button.setMenu(menu)
    panel.show()
    try:
        menu.popup(QPoint(200, 100))
        menu.hide()
        assert button.property("popupClosedAt") is not None
        QTest.mouseDClick(button, Qt.LeftButton)
        QTest.mouseRelease(button, Qt.LeftButton)
        assert not menu.isVisible()
    finally:
        panel.close()
        panel.deleteLater()
