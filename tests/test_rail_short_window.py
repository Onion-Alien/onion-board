"""A short window never takes the rail's open / shut arrow or its drag edge: shut, the
rail is the taller one, and the narrow window's squeeze used to fire for the height."""
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from test_mainwindow import window as main_window  # noqa: F401 - the real window, offscreen


def _settle():
    for _ in range(5):
        QApplication.processEvents()


def _drag(handle, start, end):
    for kind, x in ((QEvent.MouseButtonPress, start), (QEvent.MouseMove, end),
                    (QEvent.MouseButtonRelease, end)):
        QApplication.sendEvent(handle, QMouseEvent(
            kind, QPointF(3, 20), QPointF(x, 100),
            Qt.LeftButton if kind != QEvent.MouseMove else Qt.NoButton,
            Qt.LeftButton if kind != QEvent.MouseButtonRelease else Qt.NoButton,
            Qt.NoModifier))
        _settle()


@pytest.mark.parametrize("height", [560, 540, 480])
def test_short_window_keeps_the_arrow_and_the_drag(main_window, height):  # noqa: F811
    w = main_window
    w.show()
    w.rail.set_open(True)
    w.resize(1470, height)
    _settle()
    rail = w.rail
    _drag(rail.resize_handle, 300, 100)   # dragged shut
    assert not rail.is_open() and not rail._squeezed and not w.fitctl.is_mini()
    assert rail.toggle.isVisible()
    assert rail.toggle.geometry().bottom() < rail.height()   # inside the window
    _drag(rail.resize_handle, 100, 400)   # dragged open again
    assert rail.is_open()
    rail.toggle.click()
    _settle()
    assert not rail.is_open()
    rail.toggle.click()
    _settle()
    assert rail.is_open()


def test_opening_in_a_tiny_window_leaves_the_arrow_and_the_drag(main_window):  # noqa: F811
    w = main_window
    w.show()
    w.rail.set_open(False)
    w.resize(560, 500)
    _settle()
    rail = w.rail
    rail.toggle.click()   # no room to open: it stays shut, nothing goes away
    _settle()
    assert rail._squeezed and not rail.is_open() and not w.fitctl.is_mini()
    assert not rail.toggle.isHidden()
    _drag(rail.resize_handle, 20, 200)
    _settle()
    assert not rail.toggle.isHidden() and rail._drag_width is None
    w.resize(1400, 800)   # with the room, it opens
    _settle()
    assert rail.is_open() and not rail._squeezed


def test_a_shut_rail_nothing_holds_shut_opens_again(main_window):  # noqa: F811
    w = main_window
    w.show()
    w.rail.set_open(True)
    w.resize(1400, 800)
    _settle()
    w.rail.squeeze(True)   # no step says so: nothing would ever have undone it
    w.fitctl._refit()
    _settle()
    assert not w.rail._squeezed and w.rail.is_open()


def test_a_step_kept_for_too_big_a_size_goes_on_a_click(main_window):  # noqa: F811
    w = main_window
    w.show()
    w.rail.set_open(True)
    w.resize(1400, 800)
    _settle()
    fit = w.fitctl._fit
    at = next(i for i, s in enumerate(fit.steps) if s[2] == w.fitctl._squeeze_step)
    fit.steps[at][2](True)   # stuck shut in a big window, however it came to be
    fit._at[at] = (99999, 99999, False)
    w.fitctl._refit()
    _settle()
    assert w.rail._squeezed and not w.rail.toggle.isHidden()
    w.rail.toggle.click()
    w.rail.toggle.click()
    _settle()
    assert not w.rail._squeezed and w.rail.is_open()


def test_a_small_window_hides_more_tabs_but_keeps_help(main_window):  # noqa: F811
    w = main_window
    w.show()
    w.resize(1400, 800)
    _settle()
    plus = bool(w.tabctl._more_tab_keys())
    assert not w.btn_about.isHidden() and w.btn_more_tabs.isHidden() != plus
    w.resize(1000, 600)   # short
    _settle()
    assert not w.btn_about.isHidden() and w.btn_more_tabs.isHidden()
    assert not w.rail.toggle.isHidden() and not w.gear.isHidden()
    w.resize(700, 800)   # narrow
    _settle()
    assert not w.btn_about.isHidden() and w.btn_more_tabs.isHidden()
    w.resize(1400, 800)
    _settle()
    assert not w.btn_about.isHidden() and w.btn_more_tabs.isHidden() != plus


def test_a_wide_mini_player_is_as_slim_as_the_full_bar(main_window):  # noqa: F811
    w = main_window
    w.show()
    w.resize(1227, 300)
    _settle()
    assert w.fitctl.is_mini()
    card, tall = w._mini_card, w.mini_mic.height() * 3
    assert card.height() < tall and card.height() <= w.mixer.minimumHeight() + 2
    row = {b.geometry().center().y() for b in (w.mini_mic, w.mini_air, w.mini_stop)}
    assert max(row) - min(row) <= 2
    w.resize(600, 300)   # no room: stacked again, with the stop buttons on top
    _settle()
    assert w.fitctl.is_mini() and w.mini_air.y() < w.mini_mic.y()
    assert card.height() >= tall
