"""Popup mouse grabs must not leave their openers visually hovered."""
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QMenu, QPushButton, QVBoxLayout

from conftest import real_pc_mouse
from soundboard.ui.panel import HoverCard
from test_mainwindow import window  # noqa: F401


pytestmark = real_pc_mouse


@pytest.mark.parametrize("popup_type", [QMenu, QDialog])
def test_popup_clears_hover_and_allows_reentry(qapp, popup_type):
    card = HoverCard()
    button = QPushButton("Open")
    QVBoxLayout(card).addWidget(button)
    card.resize(300, 150)
    card.show()
    popup = popup_type(card)
    if isinstance(popup, QMenu):
        popup.addAction("Item")
    else:
        popup.setWindowFlags(Qt.Popup)
    try:
        # into the card first, as at the end: a window an earlier test showed may still
        # be Qt's last one under the mouse
        QTest.qWaitForWindowExposed(card)
        QTest.mouseMove(card, QPoint(1, 1))
        QTest.mouseMove(button, button.rect().center())
        qapp.processEvents()
        assert button.underMouse() and card.property("hovered")
        popup.move(card.mapToGlobal(QPoint(card.width() + 10, 0)))
        popup.show()
        qapp.processEvents()
        assert not button.underMouse()
        assert not card.property("hovered")
        QTest.mouseMove(popup, popup.rect().center())
        popup.close()
        qapp.processEvents()
        assert not button.underMouse()
        assert not card.property("hovered")
        QTest.mouseMove(card, QPoint(1, 1))
        QTest.mouseMove(button, button.rect().center())
        qapp.processEvents()
        assert button.underMouse() and card.property("hovered")
    finally:
        popup.close()
        card.close()
        card.deleteLater()


def test_onion_menu_dismissed_away_clears_rail_fill(qapp, window):  # noqa: F811
    window.show()
    button = window.btn_about
    try:
        QTest.mouseMove(window, QPoint(window.width() - 10, 10))
        button.clearFocus()
        qapp.processEvents()
        resting = button.grab().toImage()
        QTest.mouseMove(button, button.rect().center())
        qapp.processEvents()
        assert button.underMouse()
        assert button.grab().toImage() != resting
        window.aboutctl._show_about_menu()
        QTest.mouseMove(window.about_menu, window.about_menu.rect().center())
        window.about_menu.close()
        button.clearFocus()
        qapp.processEvents()
        assert not button.underMouse()
        assert button.grab().toImage() == resting
    finally:
        window.about_menu.close()

