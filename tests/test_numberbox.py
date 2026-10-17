"""A typed number counts without Enter, and Enter in a number box presses no button."""
import time

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from soundboard.ui import numberbox
from soundboard.ui.speedpitch import SpeedPitchButton


def _wait(qapp, ok, secs=3.0):
    end = time.monotonic() + secs
    while not ok() and time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.01)
    return ok()


@pytest.fixture
def typed(qapp):
    """The Live controls popup with "2" typed over the speed's 1.00x."""
    numberbox.install(qapp)
    b = SpeedPitchButton()
    b.pop.show()
    box = b.speed.val
    box.activateWindow()
    box.setFocus()
    assert _wait(qapp, box.hasFocus)
    box.lineEdit().selectAll()
    QTest.keyClicks(box, "2")
    assert b.speed.value() == 1.0   # not on the key itself
    yield b, box
    b.pop.close()
    b.deleteLater()
    qapp.processEvents()


def test_enter_sets_it_and_presses_no_button(typed):
    b, box = typed
    QTest.keyClick(box, Qt.Key.Key_Return)   # went on to the popup: Reset all, back to 1x
    assert b.speed.value() == 2.0
    assert box.text() == "2.00x"


def test_a_pause_sets_it_and_keeps_the_text(qapp, typed):
    b, box = typed
    assert _wait(qapp, lambda: b.speed.value() == 2.0, numberbox.PAUSE_MS / 1000 + 2)
    assert box.text() == "2x"   # not rewritten under the cursor


def test_a_click_away_sets_it(typed):
    b, box = typed
    # empty space in the popup: it takes no focus, so the box kept it and the "2"
    QTest.mouseClick(b.pop, Qt.MouseButton.LeftButton, pos=b.pop.rect().topLeft() + QPoint(4, 4))
    assert box.hasFocus()
    assert b.speed.value() == 2.0
