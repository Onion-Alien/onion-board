"""Settings > Tabs: switching the Radio, Apps, Triggers and Voice tabs off and on
(Config.tabs_off, ui/taboff.py). A switched-off tab is hidden and never built."""
import pytest

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
        assert w.tabs.tabToolTip(i).endswith(main.TABS[i][1])
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
