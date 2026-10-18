"""Bun's first-run tour of the empty board (ui/firsttour.py), on the real MainWindow
offscreen: once only, one card, clicks outside do nothing until the search step's
Not now, a sound added finishes it, the Add button instead of the search box in
Offline mode, and never with tutorials switched off."""

import pytest
from conftest import process_events
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from soundboard import __version__
from soundboard.audio import engine
from soundboard.core import usage
from soundboard.online import net
from soundboard.control import winkeys
from soundboard.sounds.library import Config, SoundMeta
from soundboard.ui import coach, firsttour
from soundboard.ui import mainwindow as main
from soundboard.ui import setupwizard


@pytest.fixture
def counted(monkeypatch):
    seen = []
    monkeypatch.setattr(usage, "used", seen.append)
    return seen


@pytest.fixture
def window(qapp, app_dir, monkeypatch, counted):
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


def test_esc_doesnt_skip_until_not_now_shows(window, qapp, counted):
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
    assert window.cfg.sounds == []   # nothing gets added for them


def test_not_now_puts_it_off(window, counted):
    tour = to_search(window)
    tour._show_skip(tour.step)
    tour.card.btn_skip.click()
    assert firsttour._current is None and "tour-skipped" in counted
    assert window.cfg.sounds == [] and firsttour.start(window) is None


def test_typing_goes_into_the_search_box(window):
    tour = to_search(window)
    QTest.keyClicks(window.search, "meme")
    assert window.search.text() == "meme" and firsttour._current is tour


def test_a_sound_added_finishes_it(window, qapp, counted):
    tour = to_search(window)
    window.cfg.sounds = [SoundMeta(id="a", name="A", file="a.wav")]
    assert process_events(qapp, lambda: tour.step.extra["name"] == "nice", 2)
    assert "tour-added" in counted
    QTest.mouseClick(window.grid, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    assert firsttour._current is None
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


def test_turning_tutorials_off_ends_it(window):
    firsttour.start(window)
    window.tipctl.set_tutorials_on(False)
    assert firsttour._current is None and not window.cfg.tutorials_on


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


def test_a_search_that_fails_shows_the_red_card(window, qapp, counted):
    """A search that can't get through: the card goes red and says so; Try again goes
    back to the search box, Close lets them go."""
    to_search(window)
    tour = firsttour._current
    window.ytresults.failed = True
    assert process_events(qapp, lambda: tour.failing, 2)
    body = tour.card.body.text()
    assert tour.card.property("problem") and "search couldn't get through" in body
    tour._step_at = 0
    tour.card.btn_go.click()   # Try again
    assert not tour.failing and not window.ytresults.failed
    assert tour.step.extra.get("name") == "search"
    window.ytresults.failed = True
    assert process_events(qapp, lambda: tour.failing, 3)
    tour._step_at = 0
    tour.card.btn_skip.click()   # Close
    assert firsttour._current is None
    assert "tour-failed" in counted and window.cfg.sounds == []


def test_an_error_card_ends_it(window, counted):
    from soundboard.ui import busy
    firsttour.start(window)
    tour = firsttour._current
    busy.toast(window, "Couldn't do the thing", "error")
    assert tour.failing and firsttour._current is tour
    tour.end("failed")   # Close
    assert firsttour._current is None and "tour-failed" in counted
