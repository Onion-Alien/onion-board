"""Each tab's first-visit how-to (ui/setup/tabtours.py) on the real MainWindow offscreen: it
starts the first time a tab opens, stays until the thing's done or put off, never
comes back, and never with tutorials off or for someone updating from an older
version."""
import pytest
from conftest import process_events
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtTest import QTest

from soundboard import __version__
from soundboard.audio import engine
from soundboard.core import usage
from soundboard.online import net
from soundboard.control import winkeys
from soundboard.sounds.library import Config, SoundMeta
from soundboard.ui.setup import coach, firsttour, tabtours
from soundboard.ui.window import mainwindow as main

TAB_TOURS = True   # (conftest switches them off everywhere else)


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
    Config(stats_version=__version__, setup_done=True, tabs_off=[],
           tips_seen=[firsttour.KEY],
           sounds=[SoundMeta(id="a", name="A", file="a.wav")]).save()
    w = main.MainWindow()
    w.soundctl._load_thread.join(15)
    w.resize(1100, 700)
    w.show()
    yield w
    if tabtours._current is not None:
        tabtours._current.end("left")
    w.close()
    w.soundctl._load_thread.join(15)
    w.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)


def open_tab(window, qapp, tab):
    window.tabs.setCurrentWidget(window.radio_page if tab == "radio" else getattr(window, tab))
    return process_events(qapp, lambda: tabtours._current is not None,
                          tabtours.START_MS / 1000 + 1.5)


@pytest.mark.parametrize("tab", tabtours.TABS)
def test_each_tab_gets_one_the_first_time(window, qapp, counted, tab):
    assert open_tab(window, qapp, tab)
    tour = tabtours._current
    assert tour.tab == tab and f"tour-{tab}-shown" in counted
    window.grab()   # (draws without an error)
    tour.card.btn_skip.click()
    assert tabtours._current is None and tabtours.key(tab) in window.cfg.tips_seen
    assert f"tour-{tab}-skipped" in counted
    window.tabs.setCurrentWidget(window.sounds_page)
    assert not open_tab(window, qapp, tab)   # once only


def test_doing_it_finishes_it(window, qapp, counted, monkeypatch):
    on = {"v": False}
    monkeypatch.setattr(type(window.radio), "is_active", lambda self: on["v"])
    assert open_tab(window, qapp, "radio")
    on["v"] = True
    assert process_events(qapp, lambda: tabtours._current is None, 2)
    assert "tour-radio-done" in counted and tabtours.key("radio") in window.cfg.tips_seen


def test_the_rail_takes_no_click_meanwhile(window, qapp):
    assert open_tab(window, qapp, "store")
    for _ in range(6):
        QTest.mouseClick(window.rail, Qt.MouseButton.LeftButton, pos=QPoint(20, 80))
    assert tabtours._current is not None and window.tabs.currentWidget() is window.store


def test_leaving_the_tab_brings_it_back_next_time(window, qapp):
    assert open_tab(window, qapp, "voice")
    window.tabs.setCurrentWidget(window.sounds_page)   # (a key, or the app itself)
    assert process_events(qapp, lambda: tabtours._current is None, 2)
    assert tabtours.key("voice") not in window.cfg.tips_seen
    assert open_tab(window, qapp, "voice")


def test_a_tab_already_clicked_in_waits_for_next_time(window, qapp):
    """Clean mic picked and its switch clicked before the Voice tab's tour started: the
    tour switched the page back to Voice changer and that click was lost. Busy on the
    tab already, its tour waits for the next visit, and the page stays where they are."""
    window.tabs.setCurrentWidget(window.voice)
    process_events(qapp, lambda: False, 0.05)
    tab = window.voice._tabs["clean"]
    QTest.mouseClick(tab, Qt.MouseButton.LeftButton, pos=tab.rect().center())
    assert window.voice.current_tab() == "clean"
    assert not process_events(qapp, lambda: tabtours._current is not None,
                              tabtours.START_MS / 1000 + 0.6)
    assert window.voice.current_tab() == "clean"
    assert tabtours.key("voice") not in window.cfg.tips_seen
    assert not window._tour_clicks._on   # (watches the input only while a tour waits)
    window.tabs.setCurrentWidget(window.sounds_page)
    assert open_tab(window, qapp, "voice")   # left alone this time: it comes


def test_none_with_tutorials_off(window, qapp):
    window.tipctl.set_tutorials_on(False)
    assert not open_tab(window, qapp, "apps")


def test_turning_tutorials_off_ends_one(window, qapp):
    assert open_tab(window, qapp, "apps")
    window.tipctl.set_tutorials_on(False)
    assert tabtours._current is None
    assert not any(c.isVisible() for c in window.findChildren(coach.Card))


def test_settings_has_the_switch(window, qapp):
    window.setctl.open_settings("general")
    box = window.setctl._settings_dlg.box_tutorials
    assert box.isChecked()
    box.click()
    assert not window.cfg.tutorials_on


def test_updating_from_an_older_version_marks_them_seen():
    old = Config.from_raw({"setup_done": True, "main_device": "x"})
    assert all(tabtours.key(t) in old.tips_seen for t in tabtours.TABS)
    new = Config.from_raw({"setup_done": True, "tutorials_on": True})
    assert not any(tabtours.key(t) in new.tips_seen for t in tabtours.TABS)
    fresh = Config.from_raw({})   # never set up: a new user
    assert not any(tabtours.key(t) in fresh.tips_seen for t in tabtours.TABS)


# ---- something going wrong ends it at once: nobody is held on a thing that doesn't work

def red_card(tour) -> bool:
    """The tour stopped on its red card: sad Bun, what to do, the window let go."""
    c = tour.card
    return bool(tour.failing and not tour.ended and c.property("problem")
                and c.bun.sad == 1.0 and c.btn_go.text() == "Try again"
                and c.btn_skip.isVisibleTo(c) and c.btn_report.isVisibleTo(c)
                and "close Onion Board and open it again" in c.body.text())


def test_a_station_that_wont_play_shows_the_red_card(window, qapp, counted):
    """The radio's own error card (a station off the air): the tour's card goes red and
    says so; Close lets them go and it doesn't come back."""
    assert open_tab(window, qapp, "radio")
    tour = tabtours._current
    window.radio._on_error("Station off the air")
    assert red_card(tour) and tabtours._current is tour
    tour._step_at = 0   # (armed)
    tour.card.btn_skip.click()   # Close
    assert tabtours._current is None and tabtours.key("radio") in window.cfg.tips_seen
    assert "tour-radio-failed" in counted


def test_the_red_card_lets_the_window_go(window, qapp):
    """While it's red the window is theirs: clicks aren't held back or nudged."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    assert open_tab(window, qapp, "radio")
    tour = tabtours._current
    tour.fail()
    ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(2, 2), QPointF(2, 2),
                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier)
    assert tour._input(window.tabs, ev) is False   # goes through
    assert tour._shake_at < 0                      # no nudge


def test_try_again_on_the_red_card_runs_the_step_again(window, qapp):
    assert open_tab(window, qapp, "radio")
    tour = tabtours._current
    reloads = []
    tour.step.retry = lambda: reloads.append(1)
    window.radio._globe_error = "Can't reach the station list."
    assert process_events(qapp, lambda: tour.failing, 2)
    assert "Can't reach the station list." in tour.card.body.text()
    assert tour.card.title.text() == "The radio couldn't connect"
    window.radio._globe_error = ""
    tour._step_at = 0
    tour.card.btn_go.click()   # Try again
    assert reloads == [1] and not tour.failing and not tour.card.property("problem")
    assert tour.card.title.text() == "Pick a station on the globe"


def test_report_on_the_red_card_opens_the_bug_form(window, qapp, monkeypatch):
    from soundboard.ui.kit import busy
    opened = []
    monkeypatch.setattr(busy, "open_url", lambda url, *a, **k: opened.append(url))
    assert open_tab(window, qapp, "store")
    tour = tabtours._current
    tour.fail()
    tour.card.btn_report.click()
    assert opened and "issues/new" in opened[0] and tabtours._current is None


def test_esc_closes_the_red_card(window, qapp):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    assert open_tab(window, qapp, "store")
    tour = tabtours._current
    tour.fail()
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    assert tour._input(window.store, ev) is True and tour.ended


def test_an_error_logged_anywhere_shows_the_red_card(window, qapp):
    import logging
    assert open_tab(window, qapp, "store")
    tour = tabtours._current
    logging.getLogger("soundboard.somewhere").error("it broke")
    assert process_events(qapp, lambda: red_card(tour), 2)
    assert "Something went wrong." in tour.card.body.text()


def test_a_warning_logged_doesnt(window, qapp):
    import logging
    assert open_tab(window, qapp, "store")
    logging.getLogger("soundboard.somewhere").warning("just so you know")
    process_events(qapp, lambda: False, 0.4)
    assert tabtours._current is not None


def test_a_broken_step_lets_go(window, qapp):
    """A step whose own test raises: the tour ends, it doesn't keep the window."""
    assert open_tab(window, qapp, "apps")

    def boom():
        raise ValueError("bad step")
    tabtours._current.step.done = boom
    assert process_events(qapp, lambda: tabtours._current is None, 2)


def test_the_radio_one_rings_the_globe(window, qapp):
    assert open_tab(window, qapp, "radio")
    tour = tabtours._current
    flat = window.radio.flat
    assert flat is not None and flat.isVisible()
    rings = tour._targets()
    assert rings and rings[0] == coach.rect_of(window, flat)[0]


def test_no_station_list_shows_the_red_card(window, qapp):
    """The globe couldn't get its stations (sad Bun on the map): nothing to pick."""
    assert open_tab(window, qapp, "radio")
    tour = tabtours._current
    window.radio._globe_error = "Can't reach the station list."
    assert process_events(qapp, lambda: red_card(tour), 2)


def test_a_store_that_wont_list_shows_the_red_card(window, qapp):
    assert open_tab(window, qapp, "store")
    tour = tabtours._current
    window.store.failed = True
    assert process_events(qapp, lambda: red_card(tour), 2)
    assert tour.card.title.text() == "The store couldn't load"


def test_apps_with_nothing_to_share_say_so_calmly(window, qapp, monkeypatch):
    """No program making sound for a while: Bun's sad but it isn't an error (no red,
    no Report), and Try again waits again."""
    monkeypatch.setattr(tabtours, "EMPTY_S", 0.2)
    assert open_tab(window, qapp, "apps")
    tour = tabtours._current
    for r in window.apps.rows.values():
        r.hide()
    assert process_events(qapp, lambda: tour.failing, 3)
    c = tour.card
    assert not c.property("problem") and not c.btn_report.isVisibleTo(c) and c.bun.sad == 1.0
    assert c.title.text() == "Nothing to share yet"
    tour._step_at = 0
    c.btn_go.click()
    assert not tour.failing


def test_a_voice_that_cant_switch_on_shows_the_red_card(window, qapp, monkeypatch):
    assert open_tab(window, qapp, "voice")
    tour = tabtours._current
    monkeypatch.setattr(window.voice, "problem",
                        lambda: "Your mic couldn&#x27;t be opened: busy")
    assert process_events(qapp, lambda: red_card(tour), 2)
    assert tour.card.title.text() == "Your voice couldn't be switched on"
    assert "Your mic couldn't be opened: busy" in tour.card.body.text()


def skip_open_tour(window, qapp, tab):
    assert open_tab(window, qapp, tab)
    tour = tabtours._current
    tour.card.btn_skip.click()
    window.tabs.setCurrentWidget(window.sounds_page)


def test_two_quick_not_nows_switch_the_rest_off(window, qapp, counted, monkeypatch):
    toasts = []
    monkeypatch.setattr(tabtours.busy, "toast", lambda w, text, *a, **k: toasts.append(text))
    skip_open_tour(window, qapp, "store")
    assert window.cfg.tutorials_on and not toasts
    skip_open_tour(window, qapp, "apps")
    assert not window.cfg.tutorials_on and "tours-quit" in counted
    assert toasts == ["Tutorials are off now. Settings → General turns them back on."]
    assert not open_tab(window, qapp, "radio")   # the rest stay off
    window.tipctl.set_tutorials_on(True)        # Settings brings back the ones not seen
    window.tabs.setCurrentWidget(window.sounds_page)
    assert open_tab(window, qapp, "radio")


def test_not_nows_far_apart_keep_them_on(window, qapp):
    skip_open_tour(window, qapp, "store")
    window._tour_skipped_at -= tabtours.QUIT_S + 1   # (a minute and more ago)
    skip_open_tour(window, qapp, "apps")
    assert window.cfg.tutorials_on


def test_the_page_red_card_speaks_and_its_try_again_carries_on(window, qapp, monkeypatch):
    """The store's own red card is up: the tour's card steps aside (one message), and
    the page's Try again carries the tour on."""
    from soundboard.online import store
    assert open_tab(window, qapp, "store")
    tour = tabtours._current
    tab = window.store
    tab._problem("Couldn't open the store", "No connection.")
    assert process_events(qapp, lambda: tour.failing and not tour.card.isVisible(), 2)
    monkeypatch.setattr(store, "browse", lambda *a, **k: ([], False))
    tab.oops.btn_retry.click()   # the page's own Try again
    assert process_events(qapp, lambda: not tour.failing and tour.card.isVisible(), 3)
    assert not tour.ended and tour.card.title.text() == "Hear one, then add it"


def test_store_tour_waits_for_an_add_from_the_store(window, qapp, counted):
    """A sound landing on the board from elsewhere (a download, an import) doesn't end
    it: only Play or Add on the Community tab does. Its "OK" is there from the start."""
    assert open_tab(window, qapp, "store")
    tour = tabtours._current
    assert tour.card.btn_skip.isVisible()
    window.cfg.sounds.append(SoundMeta(id="b", name="B", file="b.wav"))
    process_events(qapp, lambda: False, 0.5)
    assert tabtours._current is tour and "tour-store-done" not in counted
    window.store.used += 1
    assert process_events(qapp, lambda: tabtours._current is None, 2)
    assert "tour-store-done" in counted


def test_open_clean_mic_skips_the_voice_tour_this_visit(window, qapp):
    from soundboard.ui.setup import chatguide
    chatguide.open_clean_mic(window)   # (the button in the box after Discord's set up)
    assert window.tabs.currentWidget() is window.voice
    assert not open_tab(window, qapp, "voice")
    window.tabs.setCurrentWidget(window.sounds_page)
    process_events(qapp, lambda: False, tabtours.START_MS / 1000 + 0.3)
    assert open_tab(window, qapp, "voice")   # the next visit has it
