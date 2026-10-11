"""Bounded edge dragging supplements the rail's keyboard-accessible toggle."""
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QLabel, QWidget
from soundboard.ui.sidebar import OPEN_W, SHUT_W, SideRail, SideTabs
from soundboard.ui.sidebar import _Arrow


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


@pytest.mark.parametrize("rtl", [False, True])
def test_dot_stays_next_to_arrow_at_every_width(qapp, rtl):
    arrow = _Arrow()
    arrow.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
    for width in (34, 70, 116, 159, 190):
        arrow.resize(width, 38)
        dot = arrow.dot_rect()
        assert dot.center().x() - width / 2 == (-8 if rtl else 8)
        assert dot.center().y() == (38 - 20) / 2
    arrow.close()


def test_halfway_drag_shows_names_and_wrapped_brand_without_saving(qapp):
    tabs = SideTabs()
    tabs.addTab(QWidget(), "Sounds")
    saved = []
    rail = SideRail(tabs, QWidget(), QLabel("Onion Board"), QLabel("v1.0"), [], False,
                    on_open=saved.append)
    rail.resize(SHUT_W, 600)
    rail.show()
    rail.drag_width(116)
    qapp.processEvents()
    assert rail.is_open() and rail.buttons[0].text().strip() == "Sounds"
    assert rail.brand.isVisible() and rail.brand.wordWrap()
    assert rail.rect().contains(rail.brand.geometry())
    assert saved == []
    rail.drag_width(117)
    rail.finish_resize()
    assert saved == [True] and rail.width() == OPEN_W
    rail.close()
