"""Bounded edge dragging supplements the rail's keyboard-accessible toggle."""
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QLabel, QPushButton, QWidget
from soundboard.ui.sidebar import FULL_W, OPEN_W, SHUT_W, SideRail, SideTabs, _Arrow


def _event(qapp, handle, kind, x):
    event = QMouseEvent(kind, QPointF(3, 20), QPointF(x, 100),
                        Qt.LeftButton if kind != QEvent.MouseMove else Qt.NoButton,
                        Qt.LeftButton if kind != QEvent.MouseButtonRelease else Qt.NoButton,
                        Qt.NoModifier)
    qapp.sendEvent(handle, event)
    qapp.processEvents()


@pytest.mark.parametrize("rtl", [False, True])
def test_drag_edge_clamps_width_and_saves_only_the_released_state(qapp, rtl):
    tabs = SideTabs()
    tabs.addTab(QWidget(), "Sounds")
    saved = []
    rail = SideRail(tabs, QWidget(), QLabel(), QLabel(), [], False, on_open=saved.append)
    rail.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
    rail.resize(SHUT_W, 600)
    rail.show()
    qapp.processEvents()
    handle = rail.resize_handle
    direction = -1 if rtl else 1
    try:
        _event(qapp, handle, QEvent.MouseButtonPress, 300)
        _event(qapp, handle, QEvent.MouseMove, 300 + 70 * direction)
        assert rail.width() == SHUT_W + 70 and saved == []
        _event(qapp, handle, QEvent.MouseMove, 300 + 600 * direction)
        assert rail.width() == OPEN_W
        _event(qapp, handle, QEvent.MouseButtonRelease, 300 + 600 * direction)
        assert rail.is_open() and saved == [True]
        _event(qapp, handle, QEvent.MouseButtonPress, 300)
        _event(qapp, handle, QEvent.MouseMove, 300 - 600 * direction)
        assert rail.width() == SHUT_W
        _event(qapp, handle, QEvent.MouseButtonRelease, 300 - 600 * direction)
        assert not rail.is_open() and saved == [True, False]
        rail.toggle.click()
        assert rail.is_open() and rail.width() == OPEN_W
    finally:
        rail.close()


def test_short_drag_snaps_back_without_changing_saved_preference(qapp):
    tabs = SideTabs()
    tabs.addTab(QWidget(), "Sounds")
    saved = []
    rail = SideRail(tabs, QWidget(), QLabel(), QLabel(), [], False, on_open=saved.append)
    rail.drag_width(SHUT_W + 20)
    rail.finish_resize()
    assert rail.width() == SHUT_W and not rail.is_open() and saved == []
    rail.squeeze(True)
    rail.resize_handle._start = None
    _event(qapp, rail.resize_handle, QEvent.MouseButtonPress, 300)
    assert rail.resize_handle._start is None
    rail.close()


def test_shut_then_mid_then_full_while_dragging(qapp):
    tabs = SideTabs()
    tabs.addTab(QWidget(), "Sounds")
    settings = QPushButton()
    settings.setProperty("railtext", "Settings")
    rail = SideRail(tabs, QWidget(), QLabel("Onion Board"), QLabel("v1.0"), [], False,
                    foot=[settings])
    rail.resize(SHUT_W, 600)
    rail.show()
    try:
        full = rail._full_fit()
        assert FULL_W < full <= OPEN_W
        for width in range(SHUT_W, OPEN_W + 1, 3):
            rail.drag_width(width)
            qapp.processEvents()
            named = bool(rail.buttons[0].text().strip())
            assert named == (width >= FULL_W) == rail.brand.isVisible()
            # the mid layout: no version, Settings just its icon
            assert rail.byline.isVisible() == (width >= full)
            assert bool(settings.text().strip()) == (width >= full)
            assert not named or rail.rect().contains(rail.brand.geometry())
            # mid: Settings and the arrow side by side, centred as a pair
            if FULL_W <= width < full:
                qapp.processEvents()
                left = settings.mapTo(rail, settings.rect().topLeft()).x()
                right = rail.toggle.mapTo(rail, rail.toggle.rect().topRight()).x()
                assert abs((left + right) / 2 - (rail.width() - 1) / 2) <= 2
        rail.finish_resize()
    finally:
        rail.close()


@pytest.mark.parametrize("rtl", [False, True])
def test_dot_stays_beside_the_arrow_at_every_width(qapp, rtl):
    arrow = _Arrow()
    arrow.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
    for width in (34, 70, 116, 159, 190):
        arrow.resize(width, 38)
        assert arrow.dot_rect().center().x() - width / 2 == (-8 if rtl else 8)
    arrow.close()
