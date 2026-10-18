"""Games run as admin (soundboard.control.adminfront): Windows keeps their keys from the board,
so a full-screen admin window in front gets a notice with Restart as admin."""
import os

from conftest import process_events, said
from PySide6.QtWidgets import QApplication
from test_mainwindow import window  # noqa: F401  (the real MainWindow)

from soundboard.control import adminfront
from soundboard.core import autostart
from soundboard.ui.kit import toast


def run_loop(monkeypatch, fronts, admins, fullscreen=lambda pid: True):
    """Drive Watcher._loop over `fronts` (the pid in front at each look); the
    programs in `admins` run as admin. What it reported, in order."""
    from soundboard.core import tips
    w = adminfront.Watcher()
    seen, asked, left = [], [], list(fronts)
    w.found.connect(seen.append)

    def front():
        if not left:
            w.stop()
            return 0
        front.pid = left.pop(0)
        return front.pid
    front.pid = 0
    monkeypatch.setattr(adminfront, "EVERY_S", 0)
    monkeypatch.setattr(adminfront, "front_pid", front)
    monkeypatch.setattr(tips, "fullscreen_in_front", lambda: fullscreen(front.pid))
    monkeypatch.setattr(adminfront, "elevated",
                        lambda pid=None: asked.append(pid) or pid in admins)
    monkeypatch.setattr(adminfront, "exe_name", lambda pid: f"game{pid}.exe")
    w._loop()
    return seen, asked


def test_full_screen_admin_game_reported_once(monkeypatch):
    seen, asked = run_loop(monkeypatch, [5, 5, 7, 5, 9, 9], admins={5, 9})
    assert seen == ["game5.exe", "game9.exe"]
    assert asked == [5, 7, 9]   # each program asked once


def test_not_full_screen_or_not_admin_or_the_board(monkeypatch):
    me = os.getpid()
    seen, asked = run_loop(monkeypatch, [me, 3, 4, 4], admins={me, 3, 4},
                           fullscreen=lambda pid: pid != 4)   # Task Manager, windowed
    assert seen == ["game3.exe"] and me not in asked and 4 not in asked
    seen, _ = run_loop(monkeypatch, [6, 6], admins=set())
    assert seen == []


def test_restart_args_drop_one_off_ones(window, monkeypatch):  # noqa: F811
    import sys
    monkeypatch.setattr(sys, "argv", ["main.py", autostart.TRAY_ARG, "--restart-after",
                                      "123", "--resume-setup"])
    assert window.restart_args() == ["main.py", "--restart-after", str(os.getpid())]


def notice(w):
    return [t for t in toast.shown(w) if t.key == "admin-game"]


def test_notice_restarts_as_admin(window, monkeypatch):  # noqa: F811
    calls = []
    monkeypatch.setattr(adminfront, "start_elevated", lambda args: calls.append(args) or True)
    monkeypatch.setattr(window, "quit_app", lambda: calls.append("quit"))
    window.hkctl._admin_in_front("game.exe")
    [t] = notice(window)
    assert "can't reach this game" in said(window) and t.kind == "warn"
    assert t.card.action.text() == "Restart as admin"
    t.card.action.click()
    process_events(QApplication.instance(), lambda: "quit" in calls)
    assert calls == [window.restart_args(), "quit"]


def test_notice_answered_no_keeps_running(window, monkeypatch):  # noqa: F811
    calls = []
    monkeypatch.setattr(adminfront, "start_elevated", lambda args: False)
    monkeypatch.setattr(window, "quit_app", lambda: calls.append("quit"))
    window.hkctl._admin_in_front("game.exe")
    notice(window)[0].card.action.click()
    process_events(QApplication.instance(), lambda: "without admin" in said(window))
    assert "without admin" in said(window) and calls == []


def test_no_notice_while_hotkeys_are_off(window):  # noqa: F811
    window.hkctl._hotkeys_off = True
    window.hkctl._admin_in_front("game.exe")
    assert notice(window) == []


def test_elevated_reads_this_process():
    assert adminfront.elevated() in (True, False)
    assert adminfront.exe_name(os.getpid()).lower().startswith("python")
