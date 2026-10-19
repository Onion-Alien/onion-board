"""Bun's theme-card wave and the logo duel start in the real window, the way a user
starts them, on a PC with Windows' Animation effects off (they follow Lite mode only)."""
from types import SimpleNamespace

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from soundboard.ui.bun.logowidget import LogoWidget
from soundboard.ui.kit import toast
from soundboard.ui.settings import lite
from soundboard.ui.settings.appearance import ThemeCard
from test_mainwindow import window  # noqa: F401


def test_mouse_onto_a_theme_card_makes_bun_wave(window, monkeypatch):  # noqa: F811
    monkeypatch.setattr(toast, "ANIMATE", False)   # Windows' Animation effects: off
    window.resize(1275, 820)
    window.show()
    window.setctl.open_settings("appearance")
    QApplication.processEvents()
    first, card = [c for c in window.findChildren(ThemeCard) if c.isVisible()][:2]
    QTest.mouseMove(first, QPoint(5, 5))
    QTest.mouseMove(card, QPoint(card.width() // 2, card.height() // 2))
    assert card._hello is not None and card._tick.isActive()
    card._tick.stop()
    card._hello = None
    monkeypatch.setattr(lite, "on", lambda: True)   # lite mode: he holds still
    QTest.mouseMove(first, QPoint(5, 5))
    QTest.mouseMove(card, QPoint(10, 10))
    assert card._hello is None and not card._tick.isActive()


def test_clicking_the_board_logo_fires_the_duel(window, monkeypatch):  # noqa: F811
    monkeypatch.setattr(toast, "ANIMATE", False)
    window.resize(1275, 820)
    window.show()
    tab = window.triggers
    owl = LogoWidget()   # stands in for the add-on's logo
    owl.setParent(tab.board_page)
    tab.panel = SimpleNamespace(pages=SimpleNamespace(logo=owl), shutdown=lambda: None)
    try:
        window.tabs.setCurrentWidget(tab)   # shown: binds to both logos
        QApplication.processEvents()
        tab.stack.setCurrentWidget(tab.board_page)   # (as when the add-on loads)
        owl.show()
        assert tab.logo_duel.logos == (window.logo, owl)
        QTest.mouseClick(window.logo, Qt.MouseButton.LeftButton)
        overlay = tab.logo_duel.overlay
        assert overlay is not None and overlay.isVisible() and overlay.timer.isActive()
        assert overlay.first == 0
        overlay.stop()
        QTest.mouseClick(owl, Qt.MouseButton.LeftButton)
        assert overlay.isVisible() and overlay.first == 1
    finally:
        tab.logo_duel.stop()
        tab.panel = None
        tab.logo_duel.bind()
