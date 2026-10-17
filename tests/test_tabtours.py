"""Each tab's first-visit how-to (ui/tabtours.py) on the real MainWindow offscreen: it
starts the first time a tab opens, stays until the thing's done or put off, never
comes back, and never with tutorials off or for someone updating from an older
version."""
import pytest
from conftest import process_events
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtTest import QTest

from soundboard import __version__, engine, net, usage, winkeys
from soundboard.library import Config, SoundMeta
from soundboard.ui import busy, coach, firsttour, tabtours
from soundboard.ui import mainwindow as main

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
    monkeypatch.setattr(busy, "toast", lambda *a, **k: None)
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
    tour._show_skip(tour.step)
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
