"""Bun's first-run tour of the empty board (ui/firsttour.py), on the real MainWindow
offscreen: once only, one card, clicks outside do nothing until the search step's
Not now, a sound added finishes it, the Add button instead of the search box in
Offline mode, and never with tutorials switched off."""
from pathlib import Path

import pytest
from conftest import process_events
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from soundboard import __version__, engine, net, starter, usage, winkeys
from soundboard.library import Config, SoundMeta
from soundboard.ui import coach, firsttour
from soundboard.ui import mainwindow as main
from soundboard.ui import setupwizard


@pytest.fixture
def counted(monkeypatch):
    seen = []
    monkeypatch.setattr(usage, "used", seen.append)
    return seen


REAL_ADD_TO = starter.add_to   # (the fixture below stubs it)


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
        firsttour._current.end("left")
    w.close()
    w.soundctl._load_thread.join(15)
    w.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)


def spin(qapp, s):
    process_events(qapp, lambda: False, s)


def press_go(tour):
    """Its button, once it takes clicks (coach.ARM_MS)."""
    tour._step_at -= coach.ARM_MS / 1000
    tour.card.btn_go.click()


def to_search(window):
    tour = firsttour.start(window)
    press_go(tour)
    assert tour.step.extra["name"] == "search"
    return tour


def esc():
    return QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)


def test_it_shows_once_on_an_empty_board(window, counted):
    tour = firsttour.start(window)
    assert tour is not None and tour.step.extra["name"] == "welcome"
    assert firsttour.KEY in window.cfg.tips_seen and "tour-shown" in counted
    tour.end("left")
    assert firsttour._current is None
    assert firsttour.start(window) is None   # once only


def test_not_with_sounds_already_there(window):
    window.cfg.sounds = [SoundMeta(id="a", name="A", file="a.wav")]
    assert not firsttour.will_run(window) and firsttour.start(window) is None


def test_not_with_tutorials_off(window):
    window.cfg.tutorials_on = False
    assert not firsttour.will_run(window) and firsttour.start(window) is None


def test_bun_stays_calm_meanwhile(window):
    """The board's Bun goes quiet for the card, but doesn't hop the whole time."""
    tour = firsttour.start(window)
    press_go(tour)
    assert not window.grid.bun._hopeful and window.grid.bun.say == ""


def test_one_card_for_every_step(window):
    """Every step speaks through the same card: one box, never a second bubble."""
    tour = firsttour.start(window)
    card = tour.card
    press_go(tour)
    assert tour.card is card and card.isVisible()
    assert window.findChildren(coach.Card) == [card]


def test_clicks_outside_do_nothing(window, qapp):
    """Spam-clicking the dimmed window doesn't get rid of it or move it on."""
    tour = firsttour.start(window)
    assert tour.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    for _ in range(10):
        QTest.mouseClick(window.grid, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
        QTest.mouseClick(window.rail, Qt.MouseButton.LeftButton, pos=QPoint(20, 120))
    spin(qapp, 0.2)
    assert firsttour._current is tour and tour.step.extra["name"] == "welcome"
    assert window.tabs.currentWidget() is window.sounds_page   # the rail took no click


def test_spam_clicking_its_button_doesnt_race_through(window):
    tour = firsttour.start(window)
    for _ in range(5):
        tour.card.btn_go.click()   # straight away: not armed yet
    assert tour.step.extra["name"] == "welcome"
    press_go(tour)
    assert tour.step.extra["name"] == "search"


def test_esc_doesnt_skip_until_not_now_shows(window, qapp, counted, added):
    tour = firsttour.start(window)
    QApplication.sendEvent(window.grid, esc())
    assert firsttour._current is tour
    press_go(tour)
    assert not tour.card.btn_skip.isVisible()   # not straight away either
    QApplication.sendEvent(window.search, esc())
    assert firsttour._current is tour
    assert process_events(qapp, lambda: tour.card.btn_skip.isVisible(),
                          coach.SKIP_MS / 1000 + 2)
    QApplication.sendEvent(window.search, esc())
    assert firsttour._current is None and "tour-skipped" in counted
    assert added == [window]   # and the board isn't left bare


def test_not_now_puts_it_off(window, counted, added):
    tour = to_search(window)
    tour._show_skip(tour.step)
    tour.card.btn_skip.click()
    assert firsttour._current is None and "tour-skipped" in counted
    assert added == [window] and firsttour.start(window) is None


def test_typing_goes_into_the_search_box(window):
    tour = to_search(window)
    QTest.keyClicks(window.search, "meme")
    assert window.search.text() == "meme" and firsttour._current is tour


def test_a_sound_added_finishes_it(window, qapp, counted, added):
    tour = to_search(window)
    window.cfg.sounds = [SoundMeta(id="a", name="A", file="a.wav")]
    assert process_events(qapp, lambda: tour.step.extra["name"] == "nice", 2)
    assert "tour-added" in counted
    QTest.mouseClick(window.grid, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    assert firsttour._current is None and added == []
    assert "tour-skipped" not in counted


def test_results_closing_goes_back_to_the_search_box(window, qapp, monkeypatch):
    tour = to_search(window)
    up = {"on": True}
    monkeypatch.setattr(firsttour.Tour, "_results_up", lambda self: up["on"])
    assert process_events(qapp, lambda: tour.step.extra["name"] == "results", 2)
    up["on"] = False
    assert process_events(qapp, lambda: tour.step.extra["name"] == "search", 2)


def test_offline_it_points_at_add(window, qapp, monkeypatch):
    monkeypatch.setattr(net, "offline", lambda: True)
    tour = firsttour.start(window)   # offline: shown all the same
    assert tour is not None and not tour.online
    press_go(tour)
    assert tour.step.extra["name"] == "add"
    window.grab()   # (draws the Add step without an error)
    assert tour._in_ring(window.btn_add.mapTo(window, window.btn_add.rect().center()))
    assert firsttour._current is tour


def test_turning_tutorials_off_ends_it(window, added):
    firsttour.start(window)
    window.tipctl.set_tutorials_on(False)
    assert firsttour._current is None and not window.cfg.tutorials_on
    assert added == [window]


def test_the_guide_hands_over_to_the_tour(window, qapp):
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
    tour.end("skipped")
    assert added == [window]


def test_the_window_going_adds_them_too(window, added):
    tour = firsttour.start(window)
    tour.end("left")
    assert added == [window]


def test_a_board_with_sounds_gets_none(window, added):
    tour = firsttour.start(window)
    window.cfg.sounds = [SoundMeta(id="a", name="A", file="a.wav")]
    tour.end("skipped")
    assert added == []


def test_the_starter_sounds_ship_small_and_come_once(window, monkeypatch, added):
    # the real starter.add_to, not the stub (undo() would drop the window's stubs too)
    monkeypatch.setattr(starter, "add_to", REAL_ADD_TO)
    found = starter.files()
    assert len(found) == 25
    assert sum(Path(f).stat().st_size for f in found) < 1_000_000   # about 0.8 MB
    got = []
    monkeypatch.setattr(window.impctl, "import_files",
                        lambda files, extras=None: got.append((files, extras)))
    assert starter.add_to(window) and got[0][0] == found
    assert {e.tags[0] for e in got[0][1].values()} == {"Starter"}   # a tab of their own
    assert starter.KEY in window.cfg.tips_seen
    assert not starter.add_to(window) and len(got) == 1   # once only
