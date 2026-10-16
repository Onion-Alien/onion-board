"""Bun's first-run tour of the empty board (ui/firsttour.py), on the real MainWindow
offscreen: once only, never in the way (every click goes on to what was under it),
gone when they go elsewhere or leave it alone, and the Add button instead of the
search box in Offline mode."""
import time
from pathlib import Path

import pytest
from conftest import process_events
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from soundboard import __version__, engine, net, starter, usage, winkeys
from soundboard.library import Config
from soundboard.ui import firsttour
from soundboard.ui import mainwindow as main
from soundboard.ui import setupwizard


@pytest.fixture
def counted(monkeypatch):
    seen = []
    monkeypatch.setattr(usage, "used", seen.append)
    return seen


@pytest.fixture
def added(monkeypatch):
    """The windows the starter sounds were handed to (not really imported)."""
    seen = []
    monkeypatch.setattr(starter, "add_to", lambda win: seen.append(win) or True)
    return seen


@pytest.fixture
def window(qapp, app_dir, monkeypatch, counted, added):
    for name in ("set_main_device", "set_mon_device", "set_mic_device"):
        monkeypatch.setattr(engine.Engine, name, lambda self, n, _k=name: None)
    monkeypatch.setattr(winkeys.Hotkeys, "register", lambda self, m: None)
    monkeypatch.setattr(net, "offline", lambda: False)
    monkeypatch.setattr(firsttour.SearchResults, "available", staticmethod(lambda: True))
    # a new install's first start: nothing on the board, "What's it for?" not answered
    Config(use_mode="", stats_version=__version__).save()
    w = main.MainWindow()
    w.soundctl._load_thread.join(15)
    w.resize(1100, 700)
    w.show()
    w.tabs.setCurrentWidget(w.sounds_page)
    yield w
    if firsttour._current is not None:
        firsttour._current.end()
    w.close()
    w.soundctl._load_thread.join(15)
    w.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)


def spin(qapp, s):
    process_events(qapp, lambda: False, s)


def test_it_shows_once_on_an_empty_board(window, counted):
    tour = firsttour.start(window)
    assert tour is not None and tour.step == "bun"
    assert firsttour.KEY in window.cfg.tips_seen and "tour-shown" in counted
    tour.end()
    assert firsttour._current is None
    assert firsttour.start(window) is None   # once only


def test_not_with_sounds_already_there(window):
    from soundboard.library import SoundMeta
    window.cfg.sounds = [SoundMeta(id="a", name="A", file="a.wav")]
    assert not firsttour.will_run(window) and firsttour.start(window) is None


def test_it_never_takes_a_click(window, qapp):
    """A click goes on to what was under it: here the empty board, and the tour moves
    on to the search box."""
    tour = firsttour.start(window)
    assert tour.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    target = window.grid
    QTest.mouseClick(target, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    assert process_events(qapp, lambda: tour.step == "search", 2)
    assert window.search.hasFocus() or not window.isActiveWindow()


def test_leaving_the_sounds_tab_ends_it_for_good(window, qapp):
    tour = firsttour.start(window)
    window.tabs.setCurrentWidget(window.setup_page)
    assert process_events(qapp, lambda: firsttour._current is None, 2)
    window.tabs.setCurrentWidget(window.sounds_page)
    spin(qapp, 0.3)
    assert firsttour._current is None and firsttour.start(window) is None
    assert tour is not None


def test_a_menu_ends_it(window, qapp):
    tour = firsttour.start(window)
    menu = window._add_menu
    menu.popup(window.mapToGlobal(QPoint(50, 50)))
    try:
        assert process_events(qapp, lambda: firsttour._current is None, 2)
    finally:
        menu.close()
    assert tour is not None


def test_esc_skips_it(window, qapp, counted):
    firsttour.start(window)
    QApplication.sendEvent(window.grid, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                                  Qt.KeyboardModifier.NoModifier))
    assert firsttour._current is None and "tour-skipped" in counted


def test_typing_goes_into_the_search_box(window, counted):
    tour = firsttour.start(window)
    QApplication.sendEvent(window.grid, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_M,
                                                  Qt.KeyboardModifier.NoModifier, "m"))
    assert tour.step == "search" and window.search.text() == "m"


def test_left_alone_it_goes_away(window, qapp, counted, monkeypatch):
    tour = firsttour.start(window)
    tour._last_input = time.monotonic() - firsttour.IDLE_S - 1
    assert process_events(qapp, lambda: firsttour._current is None, 2)
    assert "tour-ignored" in counted and "tour-skipped" not in counted


def test_offline_it_points_at_add(window, qapp, counted, monkeypatch):
    monkeypatch.setattr(net, "offline", lambda: True)
    tour = firsttour.start(window)   # offline: shown all the same
    assert tour is not None and not tour.online
    QApplication.sendEvent(window.grid, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_M,
                                                  Qt.KeyboardModifier.NoModifier, "m"))
    assert tour.step == "add" and window.search.text() == ""   # no search box offline
    window.grab()   # (draws the Add step's bubble without an error)
    ev_obj = window.btn_add
    tour._input(ev_obj, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A,
                                  Qt.KeyboardModifier.NoModifier))   # a key: stays
    assert firsttour._current is tour
    QTest.mousePress(window.btn_add, Qt.MouseButton.LeftButton)
    assert firsttour._current is None and "tour-files" in counted
    QTest.mouseRelease(window.btn_add, Qt.MouseButton.LeftButton)
    window._add_menu.close()


def test_the_guide_hands_over_to_the_tour(window, qapp, monkeypatch, counted):
    """A first start opens on the Setup tab (nothing set up yet); closing the guide
    goes to the board and the tour starts there."""
    window.tabs.setCurrentWidget(window.setup_page)
    wiz = setupwizard.SetupWizard(window)
    assert wiz._ask_use
    wiz.done(QDialog.DialogCode.Rejected)
    assert window.tabs.currentWidget() is window.sounds_page
    assert process_events(qapp, lambda: firsttour._current is not None, 3)
    wiz.deleteLater()


# ---- the starter sounds: added by themselves when the tour ends on a bare board -------

def test_skipping_the_tour_adds_the_starter_sounds(window, added):
    tour = firsttour.start(window)
    tour.end(skipped=True)
    assert added == [window]


def test_leaving_it_alone_or_for_another_tab_adds_them_too(window, qapp, added):
    firsttour.start(window)
    window.tabs.setCurrentWidget(window.setup_page)
    assert process_events(qapp, lambda: firsttour._current is None, 2)
    assert added == [window]


def test_searching_then_picking_a_song_adds_none(window, added):
    tour = firsttour.start(window)
    tour._go("results")   # they searched: what they pick is their own first sound
    tour.end()
    assert added == []


def test_a_board_with_sounds_gets_none(window, added):
    from soundboard.library import SoundMeta
    tour = firsttour.start(window)
    window.cfg.sounds = [SoundMeta(id="a", name="A", file="a.wav")]
    tour.end()
    assert added == []


def test_the_starter_sounds_ship_small_and_come_once(window, monkeypatch, added):
    monkeypatch.undo()   # the real starter.add_to, not the stub
    found = starter.files()
    assert len(found) == 25
    assert sum(Path(f).stat().st_size for f in found) < 1_000_000   # about 0.8 MB
    got = []
    monkeypatch.setattr(window.impctl, "import_files", got.append)
    assert starter.add_to(window) and got == [found]
    assert starter.KEY in window.cfg.tips_seen
    assert not starter.add_to(window) and len(got) == 1   # once only
