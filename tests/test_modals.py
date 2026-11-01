"""Dialogs don't flash white when they open, and a click outside a modal one closes it
(unless closing it would lose work)."""
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QInputDialog, QWidget

from soundboard.ui.kit import modals
from soundboard.ui.sounds.dialogs import EditDialog


def wait_for(qapp, cond, timeout=2.0):
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.01)
    return cond()


def test_a_dialog_stays_see_through_until_it_has_painted(qapp):
    dlg = QDialog()
    modals._polished(dlg)   # as the app style does to every widget
    try:
        dlg.show()
        assert dlg.windowOpacity() == 0.0   # on screen, nothing drawn yet
        assert wait_for(qapp, lambda: dlg.windowOpacity() == 1.0)
        dlg.hide()
        dlg.show()   # opened again: hidden again until painted
        assert dlg.windowOpacity() == 0.0
        assert wait_for(qapp, lambda: dlg.windowOpacity() == 1.0)
    finally:
        dlg.close()


def test_a_click_on_a_blocked_window_is_spotted():
    msg = modals._MSG()
    msg.message = modals.WM_SETCURSOR
    msg.lParam = (modals.WM_LBUTTONDOWN << 16) | modals.HTERROR
    assert modals._outside_click(msg)
    msg.lParam = (0x0200 << 16) | modals.HTERROR   # the mouse only moved over it
    assert not modals._outside_click(msg)
    msg.lParam = (modals.WM_LBUTTONDOWN << 16) | 1   # a click inside a window: normal
    assert not modals._outside_click(msg)


def test_a_click_outside_closes_a_small_dialog(qapp):
    parent = QWidget()
    closed = []
    QTimer.singleShot(50, lambda: closed.append(modals.close_front_dialog()))
    text, ok = QInputDialog.getText(parent, "Rename category", "New name:", text="Resanance")
    assert closed == [True] and not ok   # the same as Cancel


def test_dialogs_that_would_lose_work_stay_open():
    assert not modals.closes_on_click_outside(EditDialog.__new__(EditDialog))
    form = QDialog()
    assert modals.closes_on_click_outside(form)
    assert not modals.closes_on_click_outside(modals.keep_open(form))
    assert modals.close_front_dialog() is False   # nothing open: nothing to do
