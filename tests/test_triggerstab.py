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
from soundboard.ui.triggershost import BoardHost
from soundboard.ui.triggerstab import TriggersTab
from test_triggers_module import make_module, zip_of

PANEL = '''
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget
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


def test_get_installs_it_and_loads_it_into_the_tab(qapp, tmp_path, addon_zip, monkeypatch):
    monkeypatch.setenv(watchaddon.LOCAL_ENV, str(addon_zip()))
    monkeypatch.setattr(updates, "_get", lambda url: pytest.fail("asked GitHub"))
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
    def not_found(url):
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


def test_with_no_headphones_a_ring_plays_where_the_board_plays():
    win = FakeWindow(headphones=False)
    host = BoardHost(win)
    assert host.play("s1", loop=True, tag="t1")
    assert win.engine.voices == {"s1:ring:t1": False}


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
    host.save()
    assert win.saves == 1


def test_the_zip_names_its_own_folder(addon_zip):
    with zipfile.ZipFile(addon_zip()) as z:
        assert all(n.startswith("onion-watch/") for n in z.namelist())
