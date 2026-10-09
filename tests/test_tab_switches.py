"""Settings > Tabs: switching the Radio, Apps, Triggers and Voice tabs off and on
(Config.tabs_off, ui/taboff.py). A switched-off tab is hidden and never built."""
import pytest
from PySide6.QtCore import Qt

from conftest import process_events

from soundboard import remote
from soundboard.library import Config, clean_setting
from soundboard.settings import SettingsDialog
from soundboard.ui import mainwindow as main
from soundboard.ui import taboff
from soundboard.ui.appspanel import AppsTab
from soundboard.ui.radiopanel import RadioTab
from soundboard.ui.triggerstab import TriggersTab
from soundboard.ui.voicepanel import VoicePanel
from test_mainwindow import window as main_window  # noqa: F401  (the real MainWindow)

REAL = {"radio": RadioTab, "apps": AppsTab, "triggers": TriggersTab, "voice": VoicePanel}


@pytest.fixture
def window(main_window):  # noqa: F811
    return main_window


def test_off_hides_the_tab_and_on_builds_it_again(window):
    w = window
    for key, cls in REAL.items():
        i = main.TAB_INDEX[key]
        assert isinstance(getattr(w, key), cls) and w.tabs.isTabVisible(i)
        w.set_tab_on(key, False)
        assert not isinstance(getattr(w, key), cls)
        assert not w.tabs.isTabVisible(i)
        assert key in w.cfg.tabs_off
    assert w.engine.voice_chain is None        # the voice chain went with the tab
    assert w.tabs.count() == len(main.TABS)    # every tab keeps its place
    for key, cls in REAL.items():
        w.set_tab_on(key, True)
        i = main.TAB_INDEX[key]
        assert isinstance(getattr(w, key), cls) and w.tabs.isTabVisible(i)
        page = w.radio_page if key == "radio" else getattr(w, key)
        assert w.tabs.widget(i) is page
        # no description on hover: just the name, and only while the tab is icon-only
        assert w.tabs.tabToolTip(i) in ("", main.TABS[i][0])
    assert w.cfg.tabs_off == []
    assert w.engine.voice_chain is w.voice.chain


def test_switching_off_the_open_tab_goes_to_sounds(window):
    w = window
    w.tabs.setCurrentIndex(main.TAB_INDEX["voice"])
    w.set_tab_on("voice", False)
    assert w.tabs.currentIndex() == 0 and w.cfg.tab == 0


def test_switching_another_tab_keeps_the_open_one(window):
    w = window
    w.tabs.setCurrentIndex(main.TAB_INDEX["setup"])
    w.set_tab_on("apps", False)
    w.set_tab_on("apps", True)
    assert w.tabs.currentIndex() == main.TAB_INDEX["setup"]


def test_stand_ins_answer_the_window(window):
    """What the window does with every tab still works with them off."""
    w = window
    for key in taboff.KEYS:
        w.set_tab_on(key, False)
    w.stop_all()
    w.retheme() if hasattr(w, "retheme") else None
    w._set_voice(True)            # the voice hotkey: nothing to switch on
    assert not w.voice.fx.btn_power.isChecked()
    w.resize(500, 400)
    w._refit()
    assert remote.dispatch(w, "voice", {"on": "1"}) == (409, remote.VOICE_OFF)
    assert remote.dispatch(w, "radio", {}) == (409, remote.RADIO_OFF)


def test_a_switched_off_tab_is_never_built(qapp, app_dir, monkeypatch):
    """Off from the last run: the real tab's class isn't even called."""
    from PySide6.QtCore import QEvent

    from soundboard import engine, winkeys
    for name in ("set_main_device", "set_mon_device", "set_mic_device"):
        monkeypatch.setattr(engine.Engine, name, lambda self, n: None)
    monkeypatch.setattr(winkeys.Hotkeys, "register", lambda self, m: None)
    Config(tabs_off=list(taboff.KEYS), tab=main.TAB_INDEX["voice"], mic_first=True).save()
    for cls in REAL.values():
        monkeypatch.setattr(cls, "__init__", lambda *a, **k: pytest.fail("built"))
    w = main.MainWindow()
    try:
        w._load_thread.join(15)
        w.load_triggers()
        assert w.cfg.tabs_off == list(taboff.KEYS)
        assert w.tabs.isTabVisible(w.tabs.currentIndex())   # not the saved, hidden one
        assert [w.tabs.isTabVisible(i) for i in range(w.tabs.count())] == [
            True, False, False, False, False, True]
        assert w.engine.voice_chain is None
    finally:
        w.close()
        w._load_thread.join(15)
        w.deleteLater()
        qapp.sendPostedEvents(None, QEvent.DeferredDelete)


def test_settings_page_switches_them(window):
    d = SettingsDialog(window, "tabs")
    assert set(d.tab_boxes) == set(taboff.KEYS)
    d.tab_boxes["triggers"].setChecked(False)
    assert "triggers" in window.cfg.tabs_off
    assert not window.tabs.isTabVisible(main.TAB_INDEX["triggers"])
    d.tab_boxes["triggers"].setChecked(True)
    assert window.tab_on("triggers")
    d.close()
    d.deleteLater()


def test_settings_pages_build_with_every_tab_off(window):
    for key in taboff.KEYS:
        window.set_tab_on(key, False)
    d = SettingsDialog(window, "tabs")   # not lazy: every page, Add-ons and Audio too
    assert not any(b.isChecked() for b in d.tab_boxes.values())
    d.close()
    d.deleteLater()


def test_saved_list_keeps_a_newer_versions_tabs():
    assert clean_setting("tabs_off", ["voice", "", 3, "future", "voice"]) == ["voice", "future"]


# ---------------------------------------------------------------- what still talks to a
# switched-off (or swapped) tab

def _flush_deletes(qapp):
    from PySide6.QtCore import QEvent
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()


def test_an_open_settings_window_follows_the_triggers_tab(window, qapp):
    """Settings stays open while a tab is switched off from its Tabs page: the Add-ons
    page must not keep the old (deleted) Triggers tab and crash on a click."""
    d = SettingsDialog(window, "tabs")
    d.tab_boxes["triggers"].setChecked(False)
    _flush_deletes(qapp)
    for key in ("get", "check", "reinstall", "report", "remove"):
        d.watch_buttons[key].click()
    assert all(b.isHidden() for b in d.watch_buttons.values())
    assert "switched off" in d.addon_label.text()
    d.tab_boxes["triggers"].setChecked(True)
    _flush_deletes(qapp)
    assert not d.watch_buttons["get"].isHidden()   # back: Onion Watch can be got again
    d.close()
    d.deleteLater()


def test_an_open_settings_window_follows_the_voice_tab(window, qapp, monkeypatch):
    """The Audio page's Custom voices card belongs to the Voice tab: it goes with it,
    comes back with it, and its buttons reach the tab that's there now."""
    d = SettingsDialog(window, "tabs")
    card = d.voices_card
    assert not card.isHidden()
    d.tab_boxes["voice"].setChecked(False)
    _flush_deletes(qapp)
    assert card.isHidden()
    d.tab_boxes["voice"].setChecked(True)
    _flush_deletes(qapp)
    assert not card.isHidden()
    shown = []
    monkeypatch.setattr(type(window.voice.speech), "show_custom_voices",
                        lambda self: shown.append(self))
    d.voices_show.click()
    assert shown == [window.voice.speech]          # the new tab's, not the deleted one's
    assert window.tabs.currentWidget() is window.voice
    d.close()
    d.deleteLater()


def test_settings_built_with_voice_off_has_the_card_once_it_is_on(window, qapp):
    window.set_tab_on("voice", False)
    d = SettingsDialog(window, "tabs")
    assert d.voices_card.isHidden()
    d.tab_boxes["voice"].setChecked(True)
    assert not d.voices_card.isHidden()
    d.close()
    d.deleteLater()


def test_a_long_voice_job_finishing_after_the_tab_is_off(window, qapp, monkeypatch):
    """A module install, AI voices download or translation download runs for minutes
    on a worker thread; switching the Voice tab off meanwhile must not end in a crash
    report when it finishes."""
    import threading

    from soundboard import aiaddon, modules
    from soundboard.speech import translation
    go = threading.Event()
    started = []

    def slow(*_a, **_k):
        started.append(threading.current_thread())
        go.wait(10)
        return True
    monkeypatch.setattr(modules, "install", slow)
    monkeypatch.setattr(aiaddon, "latest", lambda *a, **k: slow() and None)
    monkeypatch.setattr(translation, "download", lambda m, progress, cancelled: slow())
    sp, ai = window.voice.speech, window.voice.ai
    jobs = 1
    ai._get()
    if sp.module is not None:
        sp._install()
        jobs += 1
    lang = next((m for m in window.voice.modules if m.kind == "translation"), None)
    if lang is not None:
        monkeypatch.setattr(type(sp), "_lang", lambda self: lang)
        sp._download()
        jobs += 1
    assert process_events(qapp, lambda: len(started) >= jobs, timeout=5)
    window.set_tab_on("voice", False)
    _flush_deletes(qapp)
    go.set()
    for t in started:
        t.join(10)
    qapp.processEvents()


def test_onion_watch_download_finishing_after_the_tab_is_off(window, qapp, monkeypatch):
    import threading

    from soundboard import watchaddon
    go, started = threading.Event(), []

    def slow(cancelled=None):
        started.append(threading.current_thread())
        go.wait(10)
        return None   # "no release": the download ends with an error
    monkeypatch.setattr(watchaddon, "latest", slow)
    window.triggers.get()
    assert process_events(qapp, lambda: bool(started), timeout=5)
    window.set_tab_on("triggers", False)
    _flush_deletes(qapp)
    go.set()
    started[0].join(10)
    qapp.processEvents()


def test_importing_settings_switches_the_tabs_live(window, qapp):
    """A settings backup carries tabs_off: the window follows it at once, never a
    saved list that says one thing while the window shows another."""
    window._apply_backup_settings({"tabs_off": ["voice", "radio"]})
    assert isinstance(window.voice, taboff.VoiceOff)
    assert not isinstance(window.radio, RadioTab)
    assert not window.tabs.isTabVisible(main.TAB_INDEX["voice"])
    assert window.engine.voice_chain is None
    window._apply_backup_settings({"tabs_off": []})
    assert isinstance(window.voice, VoicePanel) and isinstance(window.radio, RadioTab)
    assert window.tabs.isTabVisible(main.TAB_INDEX["voice"])
    assert window.engine.voice_chain is window.voice.chain
    d = SettingsDialog(window, "tabs")   # every page builds with what's there now
    d.close()
    d.deleteLater()


def test_the_voice_hotkey_beeps_fail_with_the_tab_off(window, monkeypatch):
    cues = []
    monkeypatch.setattr(window, "cue", lambda kind: cues.append(kind))
    window.set_tab_on("voice", False)
    window.on_hotkey("__voice__")
    window.on_hotkey("__voicehold__")
    window.on_hotkey_released("__voicehold__")
    assert cues == ["fail"]
    assert not window.voice.fx.btn_power.isChecked()


def test_apps_switched_off_right_after_it_is_built(window, qapp):
    """With remembered programs the Apps tab starts itself 1.5 s after it's made."""
    import time
    window.cfg.apps_paths = {"c:\\games\\x.exe": {"exe": "x.exe"}}
    window.set_tab_on("apps", False)
    window.set_tab_on("apps", True)
    window.set_tab_on("apps", False)
    _flush_deletes(qapp)
    end = time.monotonic() + 2.0
    while time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.02)


def test_keyboard_never_lands_on_a_hidden_tab(window, qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    for key in taboff.KEYS:
        window.set_tab_on(key, False)
    window.tabs.setCurrentIndex(0)
    for _ in range(4):
        QTest.keyClick(window.tabs, Qt.Key_Tab, Qt.ControlModifier)
        assert window.tabs.isTabVisible(window.tabs.currentIndex())
    window.tabs.setCurrentIndex(main.TAB_INDEX["setup"])
    QTest.keyClick(window.tabs.tabBar(), Qt.Key_Left)
    assert window.tabs.isTabVisible(window.tabs.currentIndex())


@pytest.fixture
def fake_watch(app_dir, request):
    """A made-up Onion Watch installed where the window looks for it."""
    from soundboard import modules
    from test_triggers_module import make_module
    from test_triggerstab import PANEL
    name = f"fakewatch_tabs_{abs(hash(request.node.name)) % 10**8}"
    make_module(app_dir / "modules" / "onion-watch", package=name, board=PANEL)
    yield name
    modules._forget(name)


def test_off_on_cycles_leave_nothing_behind(window, qapp, fake_watch):
    """off -> on -> off -> on, again and again: one of each tab, no extra signal
    connections, no Onion Watch or voice chain left running."""
    import gc

    from PySide6.QtWidgets import QApplication

    from soundboard import net
    from soundboard.ui.aivoicepanel import AiVoicePanel
    from soundboard.ui.radiopanel import RadioOff
    from soundboard.ui.triggershost import BoardHost
    from soundboard.ui.voicepanel import SpeechPanel
    from soundboard.voicefx import VoiceChain
    w = window
    counted = (*REAL.values(), BoardHost, VoiceChain, SpeechPanel, AiVoicePanel,
               taboff.TabOff, RadioOff)
    # Only what this test makes is counted. An earlier test's window can still be
    # around, held by something outside Python's view (a pending timer's lambda keeps
    # one until it fires), and let go in the middle of this test: its tabs and
    # listeners going then changed the numbers. So whatever is already here is held
    # until the end, and left out.
    gc.collect()
    already = [o for o in gc.get_objects() if isinstance(o, counted)]
    already_ids = {id(o) for o in already}
    old_listeners = list(net._listeners)
    old_listener_ids = {id(ref) for ref in old_listeners}
    for key in taboff.KEYS:   # once round, so every count below is a settled one
        w.set_tab_on(key, False)
        w.set_tab_on(key, True)
    w.load_triggers()         # (not watching, it would wait to be shown)

    def counts():
        # a tab that's just gone can take a few collections to really let go
        # (how many depends on the machine), so look again until the numbers stop
        last = None
        for _ in range(10):
            _flush_deletes(qapp)
            gc.collect()
            _flush_deletes(qapp)
            now = snapshot()
            if now == last:
                break
            last = now
        return now

    def snapshot():
        alive = sum(ref() is not None for ref in net._listeners
                    if id(ref) not in old_listener_ids)
        objs = [o for o in gc.get_objects() if id(o) not in already_ids]
        return {"net listeners": alive, "fit steps": len(w._fit.steps),
                "stack": len(w._stack_cols), "tabs": w.tabs.count(),
                "radio pages": w.radio_page.count(),
                "watch panels": sum(type(x).__name__ == "Panel"
                                    for x in QApplication.allWidgets()),
                # nothing still holds an old tab (a hook, a closure, the host)
                **{cls.__name__: sum(isinstance(o, cls) for o in objs) for cls in counted}}
    before = counts()
    assert before["watch panels"] == 1
    calls = []   # each Onion Watch panel's log (not the panel: that would keep it)
    for _ in range(4):
        for key in taboff.KEYS:
            if key == "triggers":
                calls.append(w.triggers.panel.calls)
            w.set_tab_on(key, False)
            assert w.engine.voice_chain is (None if key == "voice" else w.voice.chain)
            w.set_tab_on(key, True)
            assert isinstance(getattr(w, key), REAL[key])
            if key == "triggers":   # not watching: it waits to be shown, or asked for
                assert w.triggers.pending and w.triggers.panel is None
                w.load_triggers()
        assert w.engine.voice_chain is w.voice.chain
        assert w.triggers.panel is not None
        assert counts() == before
    assert len(calls) == 4 and all("shutdown" in c for c in calls)


def test_the_onion_watch_nudge_is_hooked_once(window, monkeypatch):
    """Watching was on before Onion Watch became an add-on: the tab is tinted until
    it's opened. Switching it off and on again mustn't stack up a hook each time."""
    window.cfg.screen = {"on": True, "triggers": [{"id": "a", "name": "Died"}]}
    window.tabs.setCurrentIndex(0)
    for _ in range(3):
        window.set_tab_on("triggers", False)
        window.set_tab_on("triggers", True)
        assert window.triggers.needs_nudge()
    nudged = []
    monkeypatch.setattr(window.triggers, "nudged", lambda: nudged.append(1))
    window.tabs.setCurrentIndex(main.TAB_INDEX["triggers"])
    window.tabs.setCurrentIndex(0)
    window.tabs.setCurrentIndex(main.TAB_INDEX["triggers"])
    assert nudged == [1]


def test_off_from_the_start_then_on_and_off_again(qapp, app_dir, monkeypatch, fake_watch):
    from PySide6.QtCore import QEvent

    from soundboard import engine, winkeys
    for name in ("set_main_device", "set_mon_device", "set_mic_device"):
        monkeypatch.setattr(engine.Engine, name, lambda self, n: None)
    monkeypatch.setattr(winkeys.Hotkeys, "register", lambda self, m: None)
    Config(tabs_off=list(taboff.KEYS), mic_first=True).save()
    w = main.MainWindow()
    try:
        w._load_thread.join(15)
        w.load_triggers()
        steps = len(w._fit.steps)
        for _ in range(2):
            for key, cls in REAL.items():
                w.set_tab_on(key, True)
                assert isinstance(getattr(w, key), cls)
                assert w.tabs.isTabVisible(main.TAB_INDEX[key])
            assert w.engine.voice_chain is w.voice.chain
            assert w.triggers.pending   # not watching: Onion Watch waits to be shown
            w.load_triggers()
            assert w.triggers.panel is not None   # ...and loads on the way back
            for key in REAL:
                w.set_tab_on(key, False)
            assert w.engine.voice_chain is None
            assert len(w._fit.steps) == steps
        w.resize(500, 400)
        w._refit()
    finally:
        w.close()
        w._load_thread.join(15)
        w.deleteLater()
        qapp.sendPostedEvents(None, QEvent.DeferredDelete)


def test_a_new_user_starts_with_the_basic_tabs():
    cfg = Config.first_start()
    assert cfg.tabs_off == ["radio", "apps", "triggers"]   # Sounds, Voice and Setup
    assert Config().tabs_off == []   # settings saved before keep every tab they had


def test_more_tabs_lists_the_switched_off_ones_and_adds_one(window, monkeypatch):
    w = window
    assert w.btn_more_tabs.isHidden()                      # every tab on: nothing to add
    w.set_tab_on("radio", False)
    w.set_tab_on("triggers", False)
    assert not w.btn_more_tabs.isHidden()
    menu = w.btn_more_tabs.menu()
    menu.aboutToShow.emit()
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert texts[0].startswith("Radio: ") and texts[1].startswith("Triggers: ")
    assert texts[-1] == "Choose tabs in Settings…" and len(texts) == 3
    opened = []
    monkeypatch.setattr(w, "open_settings", lambda page="privacy": opened.append(page))
    menu.actions()[-1].trigger()
    assert opened == ["tabs"]
    menu.actions()[1].trigger()                            # Triggers
    assert w.tab_on("triggers") and w.tabs.currentIndex() == main.TAB_INDEX["triggers"]
    w.set_tab_on("radio", True)
    assert w.btn_more_tabs.isHidden()


def test_right_click_hides_a_tab_and_more_tabs_brings_it_back(window, monkeypatch):
    w = window
    shown = []
    monkeypatch.setattr(w, "toast", lambda text, kind="": shown.append(text))
    w.tabs.setCurrentIndex(main.TAB_INDEX["radio"])
    w.hide_tab("radio")
    assert not w.tab_on("radio") and w.tabs.currentIndex() == 0
    assert "More tabs" in shown[0]
    assert w.tabs.cornerWidget(Qt.TopRightCorner).isAncestorOf(w.btn_more_tabs)
    assert not w.btn_more_tabs.isHidden()
    menu = w.btn_more_tabs.menu()
    menu.aboutToShow.emit()
    menu.actions()[0].trigger()
    assert w.tab_on("radio")
