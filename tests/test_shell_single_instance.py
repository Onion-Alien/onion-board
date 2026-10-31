"""A second launch while the first is still starting up brings the first to the
front instead of saying "already open, look in the tray"."""
import ctypes
import os
import uuid

import pytest

from conftest import own_time
from soundboard.core import singleinstance as si

pytestmark = pytest.mark.windows   # Windows' named mutex


@pytest.fixture
def instance(monkeypatch):
    """A private instance name, so the real, running app is never found."""
    monkeypatch.setattr(si, "INSTANCE_NAME", f"onionboard-test-{os.getpid()}-{uuid.uuid4().hex}")
    boxes = []
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: boxes.append(a)))
    return boxes


def test_second_launch_waits_for_a_first_one_still_starting(qapp, instance, monkeypatch):
    assert si.claim_single_instance()   # the first copy: holds the lock, not listening yet
    servers = []

    def sleep(_s):   # the first copy gets as far as listening while the second waits
        if not servers:
            servers.append(si.listen_for_second_launch(qapp, lambda: None))
    own_time(monkeypatch, si, sleep=sleep)
    assert not si.claim_single_instance()   # the second copy
    assert instance == []                   # no "already open" message
    from conftest import process_events
    process_events(qapp, lambda: servers[0].show_requested, 3)
    assert servers[0].show_requested        # the first one will show its window
    servers[0].close()


def test_second_launch_gives_up_and_says_so(qapp, instance, monkeypatch):
    assert si.claim_single_instance()
    monkeypatch.setattr(si, "CONNECT_SECONDS", 0.3)
    assert not si.claim_single_instance()
    assert len(instance) == 1


def test_window_comes_to_front_on_a_normal_start_only():
    """The splash never takes the focus, so a normal start (the installer's "Open Onion
    Board now") must bring the window forward itself, or it lands behind the browser;
    a start with Windows (--tray) must not take the focus from a game."""
    from soundboard.core.autostart import TRAY_ARG
    assert si.comes_to_front(["main.py"], False)
    assert si.comes_to_front(["main.py", "--resume-setup"], False)
    assert not si.comes_to_front(["main.py", TRAY_ARG], False)
    assert si.comes_to_front(["main.py", TRAY_ARG], True)   # launched again meanwhile
    assert not si.comes_to_front(["main.py", "--restarted"], False)   # after a crash


def test_bring_to_front_raises_and_activates(qapp, monkeypatch):
    from PySide6.QtWidgets import QWidget
    w = QWidget()
    calls = []
    monkeypatch.setattr(w, "raise_", lambda: calls.append("raise"))
    monkeypatch.setattr(w, "activateWindow", lambda: calls.append("activate"))
    w.show()
    si.bring_to_front(w)   # the Windows part never throws, even for an offscreen window
    assert calls == ["raise", "activate"]
    w.close()


def release_lock():
    ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(si.take_lock.handle))


def test_uninstaller_asks_the_running_one_to_quit(qapp, instance, monkeypatch):
    """--quit-running: the open board quits like the tray's Quit (settings saved) and
    the lock is gone, so it can't go on running, and counting, after the uninstall."""
    assert si.claim_single_instance()
    quits = []

    class Window:
        def quit_app(self):   # what the real quit ends in: the lock freed
            quits.append(1)
            release_lock()
    window = Window()
    server = si.listen_for_second_launch(qapp, lambda: window)
    own_time(monkeypatch, si, sleep=lambda _s: qapp.processEvents())
    assert si.running()
    assert si.ask_running_to_quit(5)
    assert quits == [1] and not si.running()
    server.close()


def test_quit_gives_up_on_one_that_never_quits(qapp, instance, monkeypatch):
    assert si.claim_single_instance()
    server = si.listen_for_second_launch(qapp, lambda: None)   # still starting: no window
    own_time(monkeypatch, si, sleep=lambda _s: qapp.processEvents())
    assert not si.ask_running_to_quit(0.5)   # the uninstaller then ends it
    assert not server.show_requested         # a quit is never taken for "show yourself"
    release_lock()
    server.close()


def test_nothing_running_is_nothing_to_quit(instance):
    assert not si.running()
    assert si.ask_running_to_quit(0.1)


def test_uninstaller_closes_the_board_before_it_counts():
    from pathlib import Path
    iss = (Path(__file__).resolve().parents[1] / "installer" / "OnionBoard.iss").read_text(
        "utf-8")
    unins = iss[iss.index("procedure CurUninstallStepChanged("):]
    unins = unins[:unins.index("\nend;")]
    assert unins.index("'--quit-running'") < unins.index("BoardProcesses(True)") \
        < unins.index("'--uninstall-count'")
