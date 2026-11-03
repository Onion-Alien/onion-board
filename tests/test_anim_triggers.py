"""The logo duel starts in the real window, the way a user starts it, on a PC with
Windows' Animation effects off (it follows Lite mode only). Bun's theme-card wave:
test_every_theme.py."""
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from soundboard.ui.bun.logowidget import LogoWidget
from soundboard.ui.kit import toast
from test_mainwindow import window  # noqa: F401


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
