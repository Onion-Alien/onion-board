"""The first ✕ asks: keep running in the tray, or close fully."""
from PySide6.QtGui import QCloseEvent
import pytest
from test_mainwindow import window as main_window  # noqa: F401 - the real window, offscreen



@pytest.fixture
def window(main_window):  # noqa: F811
    return main_window


class Tray:
    def isVisible(self):
        return True

    def hide(self):
        pass

    def showMessage(self, *a):
        pass


def press_x(window):
    ev = QCloseEvent()
    window.closeEvent(ev)
    return ev


def setup(window, mp):
    mp.setattr(window, "tray", Tray())
    mp.setattr(window, "shutdown", lambda: None)
    mp.setattr(window, "close", lambda: press_x(window))
    window.cfg.tray, window.cfg.close_asked = True, False
    window.show()


def finish(window):
    if window._close_ask is not None:
        window._close_ask.reject()
    window.cfg.close_asked = True


def test_first_x_asks_and_the_window_stays(window, monkeypatch, qapp):
    with monkeypatch.context() as mp:
        setup(window, mp)
        assert not press_x(window).isAccepted()
        dlg = window._close_ask
        assert dlg is not None and dlg.isVisible() and window.isVisible()
        assert not press_x(window).isAccepted() and window._close_ask is dlg   # only one
        finish(window)


def test_keep_running_hides_and_never_asks_again(window, monkeypatch, qapp):
    with monkeypatch.context() as mp:
        setup(window, mp)
        press_x(window)
        window._close_ask.keep_btn.click()
        assert window.cfg.close_asked and window.cfg.tray and window._close_ask is None
        assert not window.isVisible()
        window.show()
        assert not press_x(window).isAccepted()
        assert window._close_ask is None and not window.isVisible()


def test_close_fully_quits_and_turns_the_tray_setting_off(window, monkeypatch, qapp):
    closed = []
    with monkeypatch.context() as mp:
        setup(window, mp)
        mp.setattr(window, "close", lambda: closed.append(press_x(window).isAccepted()))
        press_x(window)
        window._close_ask.quit_btn.click()
        assert window.cfg.close_asked and not window.cfg.tray
        assert closed == [True]
    window.cfg.tray = True


def test_esc_keeps_the_window_and_asks_next_time(window, monkeypatch, qapp):
    with monkeypatch.context() as mp:
        setup(window, mp)
        press_x(window)
        window._close_ask.reject()
        assert window._close_ask is None and window.isVisible()
        assert not window.cfg.close_asked and window.cfg.tray
        press_x(window)
        assert window._close_ask is not None
        finish(window)


def test_a_real_quit_never_asks(window, monkeypatch, qapp):
    with monkeypatch.context() as mp:
        setup(window, mp)
        window._on_session_end()   # Windows signing out, an installer closing the app
        assert press_x(window).isAccepted() and window._close_ask is None
        window._quitting = False
        window.cfg.close_asked = True


def test_no_question_while_the_window_is_hidden(window, monkeypatch, qapp):
    with monkeypatch.context() as mp:
        setup(window, mp)
        window.hide()
        assert not press_x(window).isAccepted() and window._close_ask is None
        window.cfg.close_asked = True
