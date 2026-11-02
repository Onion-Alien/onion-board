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
