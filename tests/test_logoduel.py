from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from soundboard.ui.kit import theme
from soundboard.ui.triggers import logoduel
from soundboard.ui.bun.logowidget import LogoWidget


@pytest.fixture
def arena(qapp, monkeypatch):
    monkeypatch.setattr(logoduel, "_animations_enabled", lambda: True)
    host = QWidget()
    row = QHBoxLayout(host)
    host.logo = LogoWidget()
    row.addWidget(host.logo)
    tab = QWidget()
    row.addWidget(tab)
    layout = QVBoxLayout(tab)
    other = LogoWidget()
    layout.addWidget(other)
    tab.panel = SimpleNamespace(pages=SimpleNamespace(logo=other))
    duel = logoduel.LogoDuel(tab)
    host.resize(320, 140)
    host.show()
    duel.bind()
    yield host, tab, other, duel
    host.close()
    host.deleteLater()


@pytest.mark.parametrize("source", [0, 1])
def test_either_logo_starts_bounded_exchange_and_other_tabs_wobble(arena, source):
    host, tab, other, duel = arena
    clicked = (host.logo, other)[source]
    QTest.mouseClick(clicked, Qt.MouseButton.RightButton)
    assert duel.overlay is None
    QTest.mouseClick(clicked, Qt.MouseButton.LeftButton)
    overlay = duel.overlay
    assert overlay is not None and overlay.isVisible()
    assert overlay.first == source
    assert clicked.squish == 0
    for _ in range(50):
        QTest.mouseClick(clicked, Qt.MouseButton.LeftButton)
    assert duel.overlay is overlay
    overlay.advance(logoduel.SHOT_S * logoduel.ROUNDS)
    assert not overlay.isVisible() and not overlay.timer.isActive()
    tab.hide()
    QTest.mouseClick(host.logo, Qt.MouseButton.LeftButton)
    assert host.logo.squish == 1
    assert not overlay.timer.isActive()


def test_tab_hide_and_addon_removal_stop_the_duel(arena):
    host, tab, other, duel = arena
    QTest.mouseClick(other, Qt.MouseButton.LeftButton)
    tab.hide()
    assert not duel.overlay.timer.isActive()
    tab.show()
    QTest.mouseClick(host.logo, Qt.MouseButton.LeftButton)
    tab.panel = None
    duel.bind()
    assert not duel.logos
    assert not duel.overlay.isVisible()
    other.setParent(None)
    other.deleteLater()
    duel.bind()


def test_reduced_motion_keeps_normal_click(arena, monkeypatch):
    host, tab, other, duel = arena
    monkeypatch.setattr(logoduel, "_animations_enabled", lambda: False)
    QTest.mouseClick(host.logo, Qt.MouseButton.LeftButton)
    assert duel.overlay is None
    assert host.logo.squish == 1


def test_lasers_render_in_every_theme_and_follow_resizing(arena):
    host, tab, other, duel = arena
    original = theme.T
    try:
        QTest.mouseClick(host.logo, Qt.MouseButton.LeftButton)
        for palette in theme.THEMES.values():
            theme.T = palette
            for phase in (0.1, 0.3, 0.6, 0.85):
                duel.overlay.elapsed = phase * logoduel.SHOT_S
                assert not host.grab().isNull()
        host.resize(440, 200)
        duel.overlay.advance(0.01)
        assert duel.overlay.geometry() == host.rect()
    finally:
        theme.T = original
