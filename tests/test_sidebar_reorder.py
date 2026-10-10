"""Dragging the rail changes visual order without changing page identities."""
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from soundboard.library import Config
from soundboard.ui.sidebar import SideRail, SideTabs


@pytest.fixture
def sidebar(qapp):
    host = QWidget()
    tabs = SideTabs()
    for name in ("Sounds", "Radio", "Apps", "Voice"):
        tabs.addTab(QWidget(), name)
    extra = QPushButton("About")
    rail = SideRail(tabs, QWidget(), QLabel(), QLabel(), [extra], True)
    QVBoxLayout(host).addWidget(rail)
    host.resize(200, 500)
    host.show()
    qapp.processEvents()
    yield rail, tabs, extra
    host.close()


def drag(qapp, button, destination):
    QTest.mousePress(button, Qt.LeftButton)
    local = button.mapFromGlobal(destination)
    event = QMouseEvent(QMouseEvent.MouseMove, local, destination,
                        Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    qapp.sendEvent(button, event)
    QTest.mouseRelease(button, Qt.LeftButton, pos=local)
    qapp.processEvents()


@pytest.mark.parametrize("opened,compact,rtl", [(True, False, False),
                                                (False, False, False),
                                                (True, True, True)])
def test_drag_both_directions_keeps_current_page_and_click_targets(sidebar, qapp,
                                                                 opened, compact, rtl):
    rail, tabs, extra = sidebar
    rail.set_open(opened)
    rail.compact(compact)
    rail.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
    qapp.processEvents()
    sounds, radio, apps, voice = rail.buttons
    tabs.setCurrentIndex(2)
    page = tabs.currentWidget()
    changes = []
    rail.orderChanged.connect(changes.append)
    drag(qapp, sounds, voice.mapToGlobal(QPoint(10, voice.height() - 1)))
    assert [b.index for b in rail.buttons] == [1, 2, 3, 0]
    assert tabs.currentWidget() is page
    assert changes == [[1, 2, 3, 0]]
    assert rail._drop_y is None and not sounds.isDown()
    assert radio.nextInFocusChain() is apps
    assert sounds.nextInFocusChain() is extra
    QTest.mouseClick(sounds, Qt.LeftButton)
    assert tabs.currentIndex() == 0
    drag(qapp, sounds, radio.mapToGlobal(QPoint(10, 0)))
    assert [b.index for b in rail.buttons] == [0, 1, 2, 3]
    QTest.keyClick(sounds, Qt.Key_Down)
    assert tabs.currentIndex() == 1


def test_click_right_button_and_drop_outside_do_not_reorder(sidebar, qapp):
    rail, tabs, _extra = sidebar
    sounds, radio, apps, voice = rail.buttons
    QTest.mouseClick(apps, Qt.LeftButton)
    assert tabs.currentIndex() == 2
    QTest.mouseClick(radio, Qt.RightButton)
    assert tabs.currentIndex() == 2
    drag(qapp, sounds, rail.mapToGlobal(QPoint(-30, 200)))
    assert [b.index for b in rail.buttons] == [0, 1, 2, 3]
    assert tabs.currentIndex() == 2 and rail._drop_y is None


def test_hidden_tabs_retain_slots_and_saved_order_is_normalized(sidebar, qapp):
    rail, tabs, _extra = sidebar
    sounds, radio, apps, voice = rail.buttons
    tabs.setTabVisible(1, False)
    qapp.processEvents()
    drag(qapp, voice, sounds.mapToGlobal(QPoint(10, 0)))
    assert [b.index for b in rail.buttons] == [3, 1, 0, 2]
    tabs.setTabVisible(1, True)
    qapp.processEvents()
    assert radio.isVisible()
    rail.set_order([2, 2, 99])
    assert [b.index for b in rail.buttons] == [2, 3, 1, 0]


def test_saved_sidebar_order_survives_restart(app_dir):
    cfg = Config.from_raw({"sidebar_order": ["voice", "sounds", "voice", 42, "future"]})
    assert cfg.sidebar_order == ["voice", "sounds", "future"]
    assert cfg.save()
    assert Config.load().sidebar_order == ["voice", "sounds", "future"]
