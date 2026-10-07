"""The Triggers tab as Onion Board's side of the Onion Watch add-on
(ui/triggerstab.py, ui/triggershost.py): Hoot and the download button until it's
installed (saying the triggers are kept), getting it loads it straight into the tab,
a broken or unreachable one says why, an update is offered and needs a restart, and
the board host plays, rings and adds sounds through the board. A made-up add-on and
a stand-in board; no network, nothing heard."""
import zipfile

import numpy as np
import pytest

from conftest import process_events
from soundboard import updates, watchaddon
from soundboard.library import SoundMeta
from soundboard.ui import triggershost
from soundboard.ui.livedot import is_tab_live
from soundboard.ui.triggershost import BoardHost
from soundboard.ui.triggerstab import TriggersTab
from test_triggers_module import make_module, zip_of

PANEL = '''
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QMenu, QPushButton, QVBoxLayout, QWidget
from . import __version__


class Panel(QWidget):
    active_changed = Signal(bool)

    def __init__(self, host):
        super().__init__()
        self.host, self.calls, self.active = host, [], False
        v = QVBoxLayout(self)
        self.hint = QLabel("hint")
        self.watch = QPushButton("Start watching")
        v.addWidget(self.hint)
        v.addWidget(self.watch)
        if not host.screen.get("no_more"):
            self.btn_more = QPushButton("More")
            menu = QMenu(self.btn_more)
            menu.addAction("What went off…")
            self.btn_more.setMenu(menu)
            v.addWidget(self.btn_more)

    def is_active(self):
        return self.active

    def set_active(self, on):
        self.active = on
        self.active_changed.emit(on)

    def sounds_changed(self):
        self.calls.append("sounds")

    def retheme(self):
        self.calls.append("theme")

    def cancel_pending(self):
        self.calls.append("cancel")

    def shutdown(self):
        self.calls.append("shutdown")

    def fit_parts(self):
        return {"hint": self.hint, "watch": self.watch}


def create(host):
    if host.screen.get("explode"):
        raise RuntimeError("the add-on fell over")
    return Panel(host)
'''


class FakeHost:
    """What the tab needs of BoardHost."""
    def __init__(self, screen=None):
        self.screen = screen if screen is not None else {}
        self.saves = 0
        self.calls = []

    def save(self):
        self.saves += 1

    def sounds_changed(self):
        self.calls.append("sounds_changed")

    def import_done(self):
        self.calls.append("import_done")


@pytest.fixture
def pkg(request):
    from soundboard import modules
    name = f"fakewatch_tab_{abs(hash(request.node.name)) % 10**8}"
    yield name
    modules._forget(name)


@pytest.fixture
def addon_zip(tmp_path, pkg, monkeypatch):
    """A made-up Onion Watch zip, offered through ONIONBOARD_ONION_WATCH_ZIP."""
    def build(version="0.2.0", name="src"):
        src = make_module(tmp_path / name / "onion-watch", package=pkg, version=version,
                          board=PANEL)
        return zip_of(src, tmp_path / f"{name}-{version}.zip")
    return build


def two_triggers(on=True):
    return {"on": on, "triggers": [{"id": "a", "name": "Died"}, {"id": "b", "name": "Win"}]}


def test_without_the_add_on_it_shows_hoot_and_keeps_the_triggers(qapp, tmp_path):
    host = FakeHost(two_triggers())
    tab = TriggersTab(host, [tmp_path / "modules"])
    assert tab.stack.currentWidget() is tab.get_page and tab.panel is None
    assert tab.btn_get.text() == "Get Onion Watch"
    assert tab.kept.text().startswith("Your 2 triggers and their pictures are kept")
    assert not tab.is_active()
    # watching was on: the board points at the tab once
    assert tab.needs_nudge()
    tab.nudged()
    assert not tab.needs_nudge() and host.screen["board_nudged"] is True and host.saves
    assert not TriggersTab(FakeHost(two_triggers(on=False)), [tmp_path / "m"]).needs_nudge()
    assert TriggersTab(FakeHost(), [tmp_path / "m"]).kept.isHidden()


def test_a_deferred_tab_loads_the_add_on_only_when_asked(qapp, tmp_path, pkg, monkeypatch):
    """The window builds the tab with defer=True and loads Onion Watch once it's up:
    loading it took up to a second before the window could show."""
    make_module(tmp_path / "modules" / "onion-watch", package=pkg, board=PANEL)
    host = FakeHost(two_triggers())
    loads = []
    real = watchaddon.installed
    monkeypatch.setattr(watchaddon, "installed", lambda d: loads.append(1) or real(d))
    tab = TriggersTab(host, [tmp_path / "modules"], defer=True)
    assert not loads and tab.pending and tab.panel is None
    assert tab.stack.currentWidget() is tab.wait_page   # blank, not "Get Onion Watch"
    assert not tab.needs_nudge()                         # not known yet
    tab.load()
    assert loads == [1] and not tab.pending
    assert tab.stack.currentWidget() is tab.board_page and tab.panel is not None
    tab.shutdown()


def test_the_window_loads_onion_watch_after_it_is_built(qapp, app_dir, monkeypatch):
    from PySide6.QtCore import QEvent
    from soundboard import engine, winkeys
    from soundboard.library import Config
    from soundboard.ui import mainwindow as main
    for name in ("set_main_device", "set_mon_device", "set_mic_device"):
        monkeypatch.setattr(engine.Engine, name, lambda self, n: None)
    monkeypatch.setattr(winkeys.Hotkeys, "register", lambda self, m: None)
    loads = []
    monkeypatch.setattr(TriggersTab, "load", lambda self, *a: loads.append(self) or
                        setattr(self, "pending", False))
    Config().save()
    w = main.MainWindow()
    try:
        assert not loads and w.triggers.pending          # not while the window is built
        assert process_events(qapp, lambda: bool(loads), timeout=5)
        w.load_triggers()
        assert loads == [w.triggers]                     # once
    finally:
        w._load_thread.join(15)
        w.close()
        w.deleteLater()
        qapp.sendPostedEvents(None, QEvent.DeferredDelete)


def watch_window(qapp, app_dir, monkeypatch, pkg, screen):
    """The real MainWindow with a made-up Onion Watch installed and `screen` saved."""
    from soundboard import engine, winkeys
    from soundboard.library import Config
    from soundboard.ui import mainwindow as main
    for name in ("set_main_device", "set_mon_device", "set_mic_device"):
        monkeypatch.setattr(engine.Engine, name, lambda self, n: None)
    monkeypatch.setattr(winkeys.Hotkeys, "register", lambda self, m: None)
    make_module(app_dir / "modules" / "onion-watch", package=pkg, board=PANEL)
    Config(screen=screen, mic_first=True).save()
    w = main.MainWindow()
    w._load_thread.join(15)
    return w


def close_window(qapp, w):
    from PySide6.QtCore import QEvent
    w.close()
    w._load_thread.join(15)
    w.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)


def test_not_watching_the_window_leaves_onion_watch_until_the_tab_is_shown(
        qapp, app_dir, monkeypatch, pkg):
    """Watching off: loading the add-on (~0.5 s, 40+ MB, a dozen threads) waits for
    the Triggers tab; showing it switches at once, then loads it."""
    from soundboard.ui import mainwindow as main
    w = watch_window(qapp, app_dir, monkeypatch, pkg, two_triggers(on=False))
    try:
        w.show()
        process_events(qapp, lambda: False, timeout=0.5)   # well past its start timer
        assert w.triggers.pending and w.triggers.panel is None
        assert w.triggers.info is not None                 # Settings > Add-ons knows it
        assert w.triggers.stack.currentWidget() is w.triggers.wait_page
        assert not is_tab_live(w.tabs, main.TAB_INDEX["triggers"])
        w.tabs.setCurrentWidget(w.triggers)
        assert w.tabs.currentWidget() is w.triggers and w.triggers.panel is None
        assert process_events(qapp, lambda: w.triggers.panel is not None, timeout=5)
        assert w.triggers.stack.currentWidget() is w.triggers.board_page
        assert w.triggers.panel.host.screen is w.cfg.screen
    finally:
        close_window(qapp, w)


def test_watching_on_loads_onion_watch_at_the_start(qapp, app_dir, monkeypatch, pkg):
    w = watch_window(qapp, app_dir, monkeypatch, pkg, two_triggers(on=True))
    try:
        assert w.triggers.pending                          # not while it's built...
        assert process_events(qapp, lambda: w.triggers.panel is not None, timeout=5)
        assert w.tabs.currentWidget() is not w.triggers    # ...without the tab shown
    finally:
        close_window(qapp, w)


def test_watching_on_with_no_triggers_still_waits(qapp, app_dir, monkeypatch, pkg):
    """Onion Watch only starts watching again when there's a trigger to watch."""
    w = watch_window(qapp, app_dir, monkeypatch, pkg, {"on": True, "triggers": []})
    try:
        process_events(qapp, lambda: False, timeout=0.3)
        assert w.triggers.pending and w.triggers.panel is None
        w.load_triggers()                                  # asked for: loads now
        assert w.triggers.panel is not None and not w.triggers.pending
    finally:
        close_window(qapp, w)


def test_a_waiting_tab_loads_when_first_shown(qapp, tmp_path, pkg):
    make_module(tmp_path / "modules" / "onion-watch", package=pkg, board=PANEL)
    tab = TriggersTab(FakeHost(two_triggers(on=False)), [tmp_path / "modules"], defer=True)
    assert not tab.needed_now() and tab.info is not None and tab.pending
    tab.resize(600, 400)
    tab.show()
    assert tab.panel is None                               # its first paint comes first
    assert process_events(qapp, lambda: tab.panel is not None, timeout=5)
    assert not tab.pending
    tab.hide()
    tab.show()                                             # once: never loaded twice
    process_events(qapp, lambda: False, timeout=0.2)
    tab.shutdown()


def test_a_waiting_tab_hidden_again_before_it_loads_waits_on(qapp, tmp_path, pkg):
    make_module(tmp_path / "modules" / "onion-watch", package=pkg, board=PANEL)
    tab = TriggersTab(FakeHost(), [tmp_path / "modules"], defer=True)
    tab.needed_now()
    tab.show()
    tab.hide()                                             # clicked straight past it
    process_events(qapp, lambda: False, timeout=0.3)
    assert tab.pending and tab.panel is None
    tab.show()
    assert process_events(qapp, lambda: tab.panel is not None, timeout=5)
    tab.shutdown()


def test_with_none_installed_the_start_loads_hoot_at_once(qapp, tmp_path):
    tab = TriggersTab(FakeHost(two_triggers(on=False)), [tmp_path / "modules"], defer=True)
    assert tab.needed_now()                                # nothing to wait for
    tab.load()
    assert tab.stack.currentWidget() is tab.get_page


def test_an_update_found_before_it_loads_is_on_the_tab_once_it_does(qapp, tmp_path, pkg):
    make_module(tmp_path / "modules" / "onion-watch", package=pkg, board=PANEL)
    tab = TriggersTab(FakeHost(), [tmp_path / "modules"], defer=True)
    tab.needed_now()
    tab.offer_update(watchaddon.Offer("9.0.0", notes="Faster."))
    assert tab.offer is not None and tab.panel is None    # kept, not dropped
    tab.load()
    assert tab.update_text.text() == "Onion Watch 9.0.0 is out. Faster."
    assert not tab.update_bar.isHidden()
    tab.shutdown()


def test_getting_it_while_it_waits_loads_it_first_and_updates_for_the_next_start(
        qapp, tmp_path, addon_zip, monkeypatch):
    """Settings > Add-ons' Update / Reinstall, or the urgent banner, before the tab
    was ever shown: it works as it always did on a loaded tab."""
    watchaddon.install(addon_zip("0.2.0", "old"), tmp_path / "modules")
    tab = TriggersTab(FakeHost(), [tmp_path / "modules"], defer=True)
    tab.needed_now()
    tab.offer = watchaddon.Offer("0.3.0", local=addon_zip("0.3.0", "new"))
    tab.get()
    assert tab.panel is not None                           # the installed one, loaded
    assert process_events(qapp, lambda: "Restart Onion Board" in tab.update_text.text())
    assert watchaddon.installed([tmp_path / "modules"]).version == "0.3.0"
    tab.shutdown()


def test_removing_it_while_it_waits(qapp, tmp_path, addon_zip, monkeypatch):
    watchaddon.install(addon_zip(), tmp_path / "modules")
    tab = TriggersTab(FakeHost(two_triggers(on=False)), [tmp_path / "modules"], defer=True)
    tab.needed_now()
    monkeypatch.setattr(tab, "confirm_remove", lambda: True)
    tab.remove()
    assert watchaddon.installed([tmp_path / "modules"]) is None
    assert not tab.pending and tab.panel is None
    assert tab.stack.currentWidget() is tab.get_page
    tab.show()                                             # nothing left to load
    process_events(qapp, lambda: False, timeout=0.2)
    assert tab.panel is None and tab.stack.currentWidget() is tab.get_page
    tab.hide()


def test_triggers_past_the_50th_are_counted_too(qapp, tmp_path):
    # Onion Watch 0.6+ keeps those under "more_triggers"
    screen = two_triggers()
    screen["triggers"] = [{"id": str(i)} for i in range(50)]
    screen["more_triggers"] = [{"id": f"m{i}"} for i in range(70)]
    tab = TriggersTab(FakeHost(screen), [tmp_path / "modules"])
    assert tab.kept.text().startswith("Your 120 triggers and their pictures are kept")


def test_get_installs_it_and_loads_it_into_the_tab(qapp, tmp_path, addon_zip, monkeypatch):
    monkeypatch.setenv(watchaddon.LOCAL_ENV, str(addon_zip()))
    monkeypatch.setattr(updates, "_get", lambda url, *_f: pytest.fail("asked GitHub"))
    host = FakeHost(two_triggers())
    tab = TriggersTab(host, [tmp_path / "modules"])
    step = dict((p, f) for p, _axis, f in tab.fit_steps() if p in (20, 28))
    step[28](True)                        # the window is small before it's even loaded
    live = []
    tab.active_changed.connect(live.append)
    tab.btn_get.click()
    assert process_events(qapp, lambda: tab.panel is not None)
    assert tab.stack.currentWidget() is tab.board_page and not tab.needs_nudge()
    assert (tmp_path / "modules" / "onion-watch" / "module.json").is_file()
    assert tab.panel.host is host
    assert tab.panel.watch.text() == ""   # ...so its Watch button came in icon only
    tab.panel.set_active(True)
    assert live == [True] and tab.is_active()
    tab.sounds_changed()
    tab.retheme()
    tab.cancel_pending()
    tab.shutdown()
    assert tab.panel.calls == ["sounds", "theme", "cancel", "shutdown"]
    assert host.calls == ["sounds_changed"]


def test_getting_it_shows_each_step_and_the_real_download_progress(qapp, tmp_path):
    """Not a bar that sits full: a gliding pill while there's no number (asking
    GitHub, installing, starting), and the download's real share in between."""
    tab = TriggersTab(FakeHost(), [tmp_path / "modules"])
    tab._busy = True
    tab._on_step("Finding the newest…")
    assert tab.working.running() and tab.bar.isHidden()
    assert tab.btn_get.text() == "Finding the newest…"
    tab._on_progress(0, 0)                  # size unknown: still gliding
    assert tab.working.running() and tab.bar.isHidden()
    tab._on_progress(30, 100)
    assert not tab.working.running() and not tab.bar.isHidden()
    assert tab.bar.value() == 300 and tab.btn_get.text() == "Downloading… 30%"
    tab._on_progress(20, 100)               # never goes backwards
    assert tab.bar.value() == 300
    tab._on_step("Installing…")
    assert tab.working.running() and tab.bar.isHidden()
    assert tab.btn_get.text() == "Installing…"
    tab._finish(None, "Cancelled", False)
    assert not tab.working.running() and tab.working.isHidden() and tab.bar.isHidden()


def test_an_installed_add_on_loads_on_start(qapp, tmp_path, addon_zip):
    watchaddon.install(addon_zip(), tmp_path / "modules")
    tab = TriggersTab(FakeHost(), [tmp_path / "modules"])
    assert tab.panel is not None and tab.stack.currentWidget() is tab.board_page


def test_one_that_breaks_shows_hoot_with_why(qapp, tmp_path, addon_zip):
    watchaddon.install(addon_zip(), tmp_path / "modules")
    tab = TriggersTab(FakeHost({"explode": True}), [tmp_path / "modules"])
    assert tab.panel is None and tab.stack.currentWidget() is tab.get_page
    assert tab.title.text() == "Onion Watch couldn't start"
    assert "fell over" in tab.error.text() and tab.btn_get.text() == "Get Onion Watch again"


def test_one_that_cannot_be_downloaded_says_why(qapp, tmp_path, monkeypatch):
    def not_found(url, *_feature):
        raise OSError("HTTP Error 404: Not Found")
    monkeypatch.setattr(updates, "_get", not_found)
    tab = TriggersTab(FakeHost(), [tmp_path / "modules"])
    tab.btn_get.click()
    assert process_events(qapp, lambda: not tab.error.isHidden())
    assert "isn't available to download yet" in tab.error.text()
    assert tab.btn_get.isEnabled() and tab.bar.isHidden() and tab.panel is None


def test_an_update_is_offered_and_installed_for_the_next_start(qapp, tmp_path, addon_zip,
                                                                monkeypatch):
    watchaddon.install(addon_zip("0.2.0", "old"), tmp_path / "modules")
    tab = TriggersTab(FakeHost(), [tmp_path / "modules"])
    new = addon_zip("0.3.0", "new")
    tab.offer_update(watchaddon.Offer("0.3.0", notes="Faster.", local=new))
    assert not tab.update_bar.isHidden()
    assert tab.update_text.text() == "Onion Watch 0.3.0 is out. Faster."
    tab.btn_update.click()
    assert process_events(qapp, lambda: "Restart Onion Board" in tab.update_text.text())
    assert watchaddon.installed([tmp_path / "modules"]).version == "0.3.0"
    assert tab.btn_update.isHidden()


def test_remove_asks_first_then_uninstalls_it_and_keeps_the_triggers(qapp, tmp_path, addon_zip,
                                                                     monkeypatch):
    monkeypatch.setenv(watchaddon.LOCAL_ENV, str(addon_zip()))
    host = FakeHost(two_triggers())
    tab = TriggersTab(host, [tmp_path / "modules"])
    tab.btn_get.click()
    assert process_events(qapp, lambda: tab.panel is not None)
    menu = tab.panel.btn_more.menu()
    assert menu.actions()[-1] is tab.act_remove and tab.btn_remove.isHidden()
    assert tab.act_remove.text() == "Remove Onion Watch…"
    lay = tab.board_page.layout()
    assert lay.itemAt(lay.count() - 1).widget() is tab.panel     # no row of its own
    panel = tab.panel
    panel.set_active(True)
    live = []
    tab.active_changed.connect(live.append)
    monkeypatch.setattr(tab, "confirm_remove", lambda: False)
    tab.act_remove.trigger()               # "No": nothing happens
    assert tab.panel is panel and (tmp_path / "modules" / "onion-watch").is_dir()
    monkeypatch.setattr(tab, "confirm_remove", lambda: True)
    tab.act_remove.trigger()
    assert tab.panel is None and tab.act_remove is None
    assert tab.stack.currentWidget() is tab.get_page
    assert panel.calls == ["shutdown"] and live == [False]
    assert not (tmp_path / "modules" / "onion-watch").exists()
    assert watchaddon.installed([tmp_path / "modules"]) is None
    assert tab.btn_get.text() == "Get Onion Watch" and tab.btn_remove_broken.isHidden()
    assert host.screen["triggers"] and tab.kept.text().startswith("Your 2 triggers")
    # ...and getting it again in the same run loads it afresh
    tab.btn_get.click()
    assert process_events(qapp, lambda: tab.panel is not None)
    assert tab.panel is not panel
    assert tab.panel.btn_more.menu().actions()[-1] is tab.act_remove


def test_an_add_on_without_a_more_menu_gets_a_remove_button_under_it(qapp, tmp_path,
                                                                     addon_zip, monkeypatch):
    watchaddon.install(addon_zip(), tmp_path / "modules")
    tab = TriggersTab(FakeHost({"no_more": True}), [tmp_path / "modules"])
    assert tab.act_remove is None and not tab.btn_remove.isHidden()
    lay = tab.board_page.layout()
    assert lay.itemAt(lay.count() - 1).layout() is tab.foot
    monkeypatch.setattr(tab, "confirm_remove", lambda: True)
    tab.btn_remove.click()
    assert tab.panel is None and watchaddon.installed([tmp_path / "modules"]) is None


def test_a_broken_one_can_be_removed_from_hoots_page(qapp, tmp_path, addon_zip, monkeypatch):
    watchaddon.install(addon_zip(), tmp_path / "modules")
    tab = TriggersTab(FakeHost({"explode": True}), [tmp_path / "modules"])
    assert tab.panel is None and not tab.btn_remove_broken.isHidden()
    monkeypatch.setattr(tab, "confirm_remove", lambda: True)
    tab.btn_remove_broken.click()
    assert watchaddon.installed([tmp_path / "modules"]) is None
    assert tab.title.text() == "Get Onion Watch for the Triggers tab"
    assert tab.error.isHidden() and tab.btn_remove_broken.isHidden()


def test_one_shipped_with_the_app_cannot_be_removed(qapp, tmp_path, addon_zip):
    watchaddon.install(addon_zip(), tmp_path / "shipped")
    tab = TriggersTab(FakeHost(), [tmp_path / "modules", tmp_path / "shipped"])
    assert tab.panel is not None and tab.btn_remove.isHidden() and tab.act_remove is None
    assert [a.text() for a in tab.panel.btn_more.menu().actions()] == ["What went off…"]


# ---------------------------------------------------------------- the board as host

class FakeEngine:
    def __init__(self, headphones=True):
        self.headphones = headphones
        self.voices = {}                  # voice id -> preview

    def play(self, sid, data, gain, loop=False, preview=False, **_):
        if preview and not self.headphones:
            return None
        self.voices[sid] = preview
        return object()

    def stop(self, sid):
        self.voices.pop(sid, None)

    def playing(self):
        return {sid: (0.0, False) for sid in self.voices}


class FakeTray:
    def __init__(self):
        self.shown = []

    def isVisible(self):
        return True

    def showMessage(self, *a):
        self.shown.append(a[:2])


class FakeWindow:
    def __init__(self, headphones=True):
        from soundboard.library import Config
        self.cfg = Config()
        self.cfg.sounds = [SoundMeta(id="s1", name="Airhorn", file="a.wav", fingerprint="fp1")]
        self.audio = {"s1": np.zeros((10, 2), np.float32)}
        self.engine = FakeEngine(headphones)
        self.played, self.imports, self.saves = [], [], 0
        self.tray = FakeTray()
        self.active = False

    def meta(self, sid):
        return next((m for m in self.cfg.sounds if m.id == sid), None)

    def gain_for(self, m):
        return 1.0

    def play(self, sid):
        self.played.append(sid)

    def drop_pending(self, sid):
        pass

    def import_files(self, files):
        self.imports.extend(files)

    def _save_later(self):
        self.saves += 1

    def isActiveWindow(self):
        return self.active


def test_the_board_plays_a_trigger_like_its_pad_and_rings_in_the_headphones():
    win = FakeWindow()
    host = BoardHost(win)
    assert host.sounds() == [("s1", "Airhorn")] and host.play("s1")
    assert win.played == ["s1"]
    assert host.play("s1", loop=True, tag="t1")
    assert win.engine.voices == {"s1:ring:t1": True}          # headphones only
    assert host.ringing() == ["t1"]
    host.stop_tag("t1")
    assert host.ringing() == [] and not host.play("gone")


def test_the_host_says_which_trigger_sounds_still_play():
    win = FakeWindow()
    host = BoardHost(win)
    assert host.play("s1", tag="t1/s1")                 # a one-shot: its pad
    win.engine.voices["s1"] = False                     # ...still playing
    assert host.play("s1", loop=True, tag="t2")
    assert sorted(host.playing()) == ["t1/s1", "t2"]
    del win.engine.voices["s1"]                         # the pad's sound ended
    assert host.playing() == ["t2"]


def test_with_no_headphones_a_ring_plays_where_the_board_plays():
    win = FakeWindow(headphones=False)
    host = BoardHost(win)
    assert host.play("s1", loop=True, tag="t1")
    assert win.engine.voices == {"s1:ring:t1": False}


def test_a_sound_checked_on_a_card_plays_to_you_alone_and_stops_by_its_tag():
    win = FakeWindow()
    host = BoardHost(win)
    assert host.play("s1", tag="hear:t1/s1")
    assert win.played == [] and win.engine.voices == {"s1:hear:hear:t1/s1": True}
    assert host.ringing() == []                     # a preview isn't a ring
    host.stop_tag("hear:t1/s1")
    assert win.engine.voices == {}


def test_with_no_headphones_a_card_preview_goes_nowhere():
    """Like a pad's preview: never into the call or the stream."""
    win = FakeWindow(headphones=False)
    host = BoardHost(win)
    assert not host.play("s1", tag="hear:t1/s1")
    assert win.engine.voices == {} and win.played == []


def test_a_tagged_one_shot_stops_by_its_tag():
    """A trigger's sound plays like its pad; stopping its tag stops that pad (a
    sound taken off the trigger, or the trigger deleted, while it plays)."""
    win = FakeWindow()
    host = BoardHost(win)
    assert host.play("s1", tag="t1/s1")
    assert win.played == ["s1"]
    win.engine.voices["s1"] = False                 # the pad playing, as win.play does
    host.stop_tag("t2/s1")                          # another trigger's: left alone
    assert "s1" in win.engine.voices
    host.stop_tag("t1/s1")
    assert win.engine.voices == {}
    host.stop_tag("t1/s1")                          # twice is fine


def test_a_sound_file_is_added_through_the_boards_import(tmp_path, monkeypatch):
    win = FakeWindow()
    host = BoardHost(win)
    got = []
    monkeypatch.setattr(triggershost.library, "fingerprint",
                        lambda path: {"old.wav": "fp1", "new.wav": "fp2"}.get(path, ""))
    host.add_sound("old.wav", got.append)             # already a pad: straight away
    assert got == ["s1"] and win.imports == []
    host.add_sound("new.wav", got.append)
    assert win.imports == ["new.wav"] and got == ["s1"]
    win.cfg.sounds.append(SoundMeta(id="s2", name="New", file="n.wav", fingerprint="fp2"))
    host.sounds_changed()
    assert got == ["s1", "s2"]
    host.add_sound("broken.wav", got.append)          # one the import gives up on
    host.import_done()
    assert got == ["s1", "s2", None]


def test_notifications_only_while_the_board_is_not_in_front():
    win = FakeWindow()
    host = BoardHost(win)
    host.notify("Died", "It just showed up.")
    win.active = True
    host.notify("Won", "It just showed up.")
    assert win.tray.shown == [("Died", "It just showed up.")]
    assert host.palette()["accent"] and host.data_dir.name
    assert host.language() == "en"   # the board's language, for the add-on
    host.save()
    assert win.saves == 1


def test_the_zip_names_its_own_folder(addon_zip):
    with zipfile.ZipFile(addon_zip()) as z:
        assert all(n.startswith("onion-watch/") for n in z.namelist())
