"""The Apps tab's eye button: a small live picture of a program's window. Only cards
whose program has a window show the eye; the picture runs while it's open and on
screen, and says why when there's nothing to show. The Windows calls are faked."""
import time

import pytest

from soundboard.win import winshot
from soundboard.audio.appaudio import App
from soundboard.ui.apps import windowview
from soundboard.ui.apps.appspanel import AppRow
from soundboard.ui.kit.widgets import Meter


@pytest.fixture
def fake_win(monkeypatch):
    state = {"status": winshot.OK, "grabs": 0, "pids": None}

    def find(pids):
        state["pids"] = tuple(pids)
        return 77

    def grab(hwnd, w, h):
        state["grabs"] += 1
        if state["status"] != winshot.OK:
            return winshot.Shot(state["status"])
        tw, th = winshot.fit(400, 200, w, h)
        return winshot.Shot(winshot.OK, tw, th, b"\x40\x80\xc0\xff" * (tw * th))

    monkeypatch.setattr(winshot, "find_window", find)
    monkeypatch.setattr(winshot, "grab", grab)
    monkeypatch.setattr(windowview, "FRAME_S", 0.02)
    return state


def wait_for(qapp, cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def shown_row(qapp, app):
    row = AppRow("music.exe", Meter)
    row.resize(360, 400)
    row.set_app(app)
    row.show()
    qapp.processEvents()
    return row


def test_eye_only_on_programs_with_a_window(qapp):
    row = shown_row(qapp, App(5, "music.exe", title="Music Thing"))
    assert row.btn_view.isVisible()
    assert "Music" in row.btn_view.accessibleName()
    row.set_app(App(5, "music.exe", title=""))     # a background service: no window
    assert not row.btn_view.isVisible()
    row.set_app(None)                              # not running
    assert not row.btn_view.isVisible()
    row.close()


def test_open_shows_the_window_and_close_stops_it(qapp, fake_win):
    row = shown_row(qapp, App(5, "music.exe", title="Music Thing", session_pids={9}))
    assert not row.view.isVisible()
    row.btn_view.click()
    assert row.view.isVisible()
    assert wait_for(qapp, lambda: row.view.picture.isVisible())
    assert fake_win["pids"] == (5, 9)
    pm = row.view.picture.pixmap()
    assert not pm.isNull() and pm.width() <= row.view.width() * pm.devicePixelRatio() + 1
    assert row.view.picture.height() <= windowview.VIEW_H
    row.btn_view.click()                           # closed: nothing grabs any more
    assert not row.view.isVisible() and row.view._grabber is None
    qapp.processEvents()
    n = fake_win["grabs"]
    time.sleep(0.1)
    qapp.processEvents()
    assert fake_win["grabs"] <= n + 1
    row.close()


@pytest.mark.parametrize("status", [winshot.MINIMISED, winshot.GONE, winshot.BLACK])
def test_no_picture_says_why(qapp, fake_win, status):
    fake_win["status"] = status
    row = shown_row(qapp, App(5, "music.exe", title="Music Thing"))
    row.btn_view.click()
    assert wait_for(qapp, lambda: row.view.status == status)
    assert not row.view.picture.isVisible()
    assert row.view.message.text() == windowview.MESSAGES[status]
    row.close_view()
    row.close()


def test_hidden_view_pauses_and_a_closed_program_closes_it(qapp, fake_win):
    row = shown_row(qapp, App(5, "music.exe", title="Music Thing"))
    row.btn_view.click()
    assert wait_for(qapp, lambda: fake_win["grabs"] > 0)
    row.hide()                                     # the tab switched away
    assert row.view._grabber is not None and not row.view._grabber._run
    row.show()
    assert row.view._grabber._run
    row.set_app(None)                              # the program closed
    assert not row.btn_view.isChecked() and row.view._grabber is None
    row.close()


def test_fit_keeps_the_shape_and_never_grows():
    assert winshot.fit(1920, 1080, 320, 180) == (320, 180)
    assert winshot.fit(1000, 2000, 320, 180) == (90, 180)
    assert winshot.fit(100, 50, 320, 180) == (100, 50)


def test_black_check():
    assert winshot.is_black(b"\x00\x00\x00\xff" * 1000)
    assert not winshot.is_black(b"\x00\x00\x00\xff" * 500 + b"\xff\xff\xff\xff" * 500)


def test_minimised_keeps_last_picture_until_restored(qapp, fake_win, monkeypatch):
    restored = []

    def restore(pids):
        restored.append(tuple(pids))
        fake_win["status"] = winshot.OK

    monkeypatch.setattr(winshot, "restore_window", restore)
    row = shown_row(qapp, App(5, "music.exe", title="Music Thing"))
    row.btn_view.click()
    assert wait_for(qapp, lambda: row.view.status == winshot.OK)
    before = row.view.picture.pixmap().toImage()
    fake_win["status"] = winshot.MINIMISED
    assert wait_for(qapp, lambda: row.view.status == winshot.MINIMISED)
    assert row.view.picture.isVisible()
    assert row.view.picture.pixmap().toImage() == before
    assert row.view.message.text() == "Minimised: last picture"
    assert row.view.restore.isVisible()
    row.view.restore.click()
    assert wait_for(qapp, lambda: row.view.status == winshot.OK)
    assert restored == [(5,)]
    assert not row.view.restore.isVisible()
    row.close_view()
    row.close()


def test_lost_window_discards_cached_picture(qapp, fake_win):
    row = shown_row(qapp, App(5, "music.exe", title="Music Thing"))
    row.btn_view.click()
    assert wait_for(qapp, lambda: row.view.status == winshot.OK)
    fake_win["status"] = winshot.GONE
    assert wait_for(qapp, lambda: row.view.status == winshot.GONE)
    assert row.view.picture.pixmap().isNull()
    fake_win["status"] = winshot.MINIMISED
    assert wait_for(qapp, lambda: row.view.status == winshot.MINIMISED)
    assert not row.view.picture.isVisible()
    assert row.view.restore.isVisible()
    row.close_view()
    row.close()


def test_restore_only_minimised_source_without_activation(monkeypatch):
    from types import SimpleNamespace

    calls = []
    u = SimpleNamespace(IsIconic=lambda hwnd: True,
                        ShowWindowAsync=lambda *args: calls.append(args) or True)
    monkeypatch.setattr(winshot, "find_window", lambda pids: 77 if pids else 0)
    monkeypatch.setattr(winshot, "_win", lambda: (u, None, None))
    assert winshot.restore_window((5,))
    assert calls == [(77, 4)]
    u.IsIconic = lambda hwnd: False
    assert not winshot.restore_window((5,))
    assert not winshot.restore_window(())
    assert len(calls) == 1


def test_view_runs_without_focus_but_pauses_when_board_minimised(qapp, fake_win, monkeypatch):
    from soundboard.ui.kit import appstate

    monkeypatch.setattr(appstate, "active", lambda: False)
    row = shown_row(qapp, App(5, "music.exe", title="Music Thing"))
    row.btn_view.click()
    assert wait_for(qapp, lambda: fake_win["grabs"] >= 3)
    row.showMinimized()
    qapp.processEvents()
    assert not row.view._grabber._run
    row.showNormal()
    qapp.processEvents()
    assert row.view._grabber._run
    row.close_view()
    row.close()


def test_changed_program_and_late_results_cannot_reuse_old_picture(qapp, fake_win):
    view = windowview.WindowView()
    view.set_pids((5,))
    view._open = True
    view._show(winshot.Shot(winshot.OK, 2, 2, b"\x40\x80\xc0\xff" * 4))
    view.set_pids((9,))
    assert view.picture.pixmap().isNull()
    view._received(((5,), winshot.Shot(winshot.OK, 2, 2, b"\xff" * 16)))
    assert view.picture.pixmap().isNull()
    view._show(winshot.Shot(winshot.MINIMISED))
    assert view.message.text() == windowview.MESSAGES[winshot.MINIMISED]
    view.close()
