"""Dragging the rail changes visual order without changing page identities."""
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget

from soundboard.sounds.library import Config
from soundboard.ui.window.railtabs import HOLD_TO_MOVE_S
from soundboard.ui.window.sidebar import SideRail, SideTabs


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


def move_to(qapp, button, destination):
    local = button.mapFromGlobal(destination)
    event = QMouseEvent(QMouseEvent.MouseMove, local, destination,
                        Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    qapp.sendEvent(button, event)
    return local


def drag(qapp, button, destination):
    """Press, held long enough (the clock is wound back, not waited for), move, let go."""
    QTest.mousePress(button, Qt.LeftButton)
    button._press_at -= HOLD_TO_MOVE_S
    local = move_to(qapp, button, destination)
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


def test_quick_click_opens_the_tab_and_moves_nothing(sidebar):
    rail, tabs, _extra = sidebar
    QTest.mouseClick(rail.buttons[2], Qt.LeftButton)
    assert tabs.currentIndex() == 2
    assert [b.index for b in rail.buttons] == [0, 1, 2, 3]
    assert rail._drop_y is None


def test_double_click_is_a_click_and_its_second_press_restarts_the_hold(sidebar, qapp):
    """A mouse that double-clicks by itself: however long ago the first click was, moving
    straight after the second press doesn't move the tab."""
    rail, tabs, _extra = sidebar
    sounds, _radio, apps, _voice = rail.buttons
    clicks = []
    apps.clicked.connect(lambda: clicks.append(1))
    QTest.mouseClick(apps, Qt.LeftButton)   # as Qt sends one: click, double-click, release
    apps._press_at -= HOLD_TO_MOVE_S        # the first click was long ago
    QTest.mouseDClick(apps, Qt.LeftButton)
    local = move_to(qapp, apps, sounds.mapToGlobal(QPoint(10, 0)))
    assert rail._drop_y is None and not apps._dragging
    QTest.mouseRelease(apps, Qt.LeftButton, pos=local)
    assert [b.index for b in rail.buttons] == [0, 1, 2, 3]
    QTest.mouseClick(apps, Qt.LeftButton)
    QTest.mouseDClick(apps, Qt.LeftButton)
    QTest.mouseRelease(apps, Qt.LeftButton)
    assert tabs.currentIndex() == 2 and len(clicks) == 3
    assert [b.index for b in rail.buttons] == [0, 1, 2, 3]


def test_moving_before_the_hold_is_up_never_moves_the_tab(sidebar, qapp):
    rail, _tabs, _extra = sidebar
    sounds, _radio, _apps, voice = rail.buttons
    changes = []
    rail.orderChanged.connect(changes.append)
    target = voice.mapToGlobal(QPoint(10, voice.height() - 1))
    QTest.mousePress(sounds, Qt.LeftButton)
    sounds._press_at -= HOLD_TO_MOVE_S - 0.5   # half a second short
    move_to(qapp, sounds, target)
    assert rail._drop_y is None
    # waiting on with the button down doesn't bring the move back: it needs a new press
    sounds._press_at -= HOLD_TO_MOVE_S
    local = move_to(qapp, sounds, target)
    assert rail._drop_y is None
    QTest.mouseRelease(sounds, Qt.LeftButton, pos=local)
    assert changes == [] and [b.index for b in rail.buttons] == [0, 1, 2, 3]


def test_sloppy_click_that_slides_a_little_still_clicks(sidebar, qapp):
    rail, tabs, _extra = sidebar
    apps = rail.buttons[2]
    QTest.mousePress(apps, Qt.LeftButton)
    slide = QPoint(QApplication.startDragDistance() + 1, 0)
    local = move_to(qapp, apps, apps.mapToGlobal(apps.rect().center() + slide))
    assert rail._drop_y is None
    QTest.mouseRelease(apps, Qt.LeftButton, pos=local)
    assert tabs.currentIndex() == 2
    assert [b.index for b in rail.buttons] == [0, 1, 2, 3]


def test_a_real_hold_survives_a_wobble_and_then_drags(sidebar, qapp):
    """On the real clock: a wobble under the drag distance doesn't end the hold."""
    rail, _tabs, _extra = sidebar
    sounds, _radio, _apps, voice = rail.buttons
    QTest.mousePress(sounds, Qt.LeftButton)
    move_to(qapp, sounds, sounds.mapToGlobal(sounds.rect().center() + QPoint(1, 0)))
    QTest.qWait(round(HOLD_TO_MOVE_S * 1000) + 50)
    local = move_to(qapp, sounds, voice.mapToGlobal(QPoint(10, voice.height() - 1)))
    assert rail._drop_y is not None and sounds._dragging
    QTest.mouseRelease(sounds, Qt.LeftButton, pos=local)
    assert [b.index for b in rail.buttons] == [1, 2, 3, 0]
    assert rail._drop_y is None


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
