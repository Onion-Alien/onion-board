"""The mouse's back side button presses the page's Back, as in a browser."""
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from soundboard.online import net
from soundboard.ui.window import mouseback
from conftest import process_events
from test_mainwindow import window as main_window  # noqa: F401 - the real window, offscreen

window = main_window


def _side_button(win, button=Qt.MouseButton.BackButton):
    """A side button clicked over the middle of the window, through its native window
    (offscreen: shown, so it has one, and its watch is on it)."""
    if win.windowHandle() is None:
        win.show()
    QTest.mouseClick(win.windowHandle(), button, Qt.KeyboardModifier.NoModifier,
                     QPoint(win.width() // 2, win.height() // 2))


def test_back_button_finds_the_shown_one(qapp):
    win = QWidget()
    lay = QVBoxLayout(win)
    page, other = QWidget(), QWidget()
    lay.addWidget(page)
    lay.addWidget(other)
    back = mouseback.mark(QPushButton("Back", page))
    hidden = mouseback.mark(QPushButton("Back", other))
    win.show()
    other.hide()
    assert mouseback.back_button(page, win) is back
    assert mouseback.back_button(None, win) is back
    back.setEnabled(False)
    assert mouseback.back_button(page, win) is None   # a hidden one never counts
    assert not hidden.isVisible()
    win.close()


def test_mouse_back_leaves_free_packs_and_settings(window, qapp, monkeypatch):
    monkeypatch.setattr(net, "allowed", lambda f: False)   # no list fetch
    window.impctl.show_packs()
    _side_button(window)
    assert process_events(qapp, lambda: not window.impctl.packs_open(), 5)
    window.setctl.open_settings("audio")
    window._mouse_back._last = -1e9   # (a new press, not the one before)
    _side_button(window)
    assert process_events(qapp, lambda: not window.setctl.settings_open(), 5)


def test_one_press_sent_twice_goes_back_once(window, qapp):
    """Mouse 4 as a click and as the Back key (some mouse software): one step back."""
    window.setctl.open_settings("audio")
    clicks = []
    window.setctl._settings_dlg.back_btn.clicked.connect(lambda: clicks.append(1))
    _side_button(window)
    key = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Back, Qt.KeyboardModifier.NoModifier)
    QCoreApplication.sendEvent(window.windowHandle(), key)
    assert process_events(qapp, lambda: clicks, 5)
    qapp.processEvents()
    assert clicks == [1]
    process_events(qapp, lambda: not window.setctl.settings_open(), 5)


def test_board_ignores_it(window, qapp):
    """No page with a Back: nothing happens, and the press goes on as before."""
    assert not window.setctl.settings_open() and not window.impctl.packs_open()
    assert mouseback.back_button(None, window) is None
    assert not window._mouse_back.press(window.childAt(QPoint(5, 5)))
    _side_button(window, Qt.MouseButton.ForwardButton)   # Mouse 5: nothing yet
    assert not window.setctl.settings_open()
