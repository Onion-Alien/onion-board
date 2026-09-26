"""The in-game overlay: its key layer, pages, open/close rules and settings. Runs on
Qt's offscreen platform with a fake host, so no window appears and no global
hotkey is registered."""
import pytest

from conftest import process_events
from soundboard import winkeys
from soundboard.library import Config, SoundMeta
from soundboard.ui import overlay as ovl
from soundboard.ui.overlay import Overlay, OverlaySettings


class Host:
    """Stands in for MainWindow: just the calls the overlay makes."""

    def __init__(self, n=12, hotkey="`"):
        sounds = [SoundMeta(id=f"s{i}", name=f"Sound {i}", file="x.wav") for i in range(n)]
        self.cfg = Config(sounds=sounds, overlay_hotkey=hotkey)
        self.audio = {m.id: object() for m in sounds}
        self.played, self.actions, self.cues = [], [], []
        self.registered = 0

    def play(self, sid):
        self.played.append(sid)

    def on_hotkey(self, action):
        self.actions.append(action)

    def register_hotkeys(self):
        self.registered += 1

    def cue(self, kind):
        self.cues.append(kind)


@pytest.fixture
def make(qapp, monkeypatch):
    monkeypatch.setattr(winkeys, "exclusive_fullscreen", lambda: False)
    made = []

    def build(settings=None, **host_kw):
        ov = Overlay(Host(**host_kw), settings)
        made.append(ov)
        return ov
    yield build
    for ov in made:
        ov.shutdown()


def test_settings_round_trip_and_reject_junk():
    s = OverlaySettings.from_dict({"mode": "hold", "keys": "numpad", "scale": 500,
                                   "opacity": "lots", "position": "moon", "autohide": True,
                                   "close_after_play": 1})
    assert (s.mode, s.keys, s.scale) == ("hold", "numpad", 160)
    assert s.opacity == 85 and s.position == "top" and s.autohide == 4
    assert s.close_after_play is True                    # 1 isn't a bool: default kept
    assert OverlaySettings.from_dict(s.to_dict()) == s
    assert OverlaySettings.from_dict(None) == OverlaySettings()


def test_config_keeps_overlay_settings():
    raw = Config(overlay={"mode": "hold"}, overlay_hotkey="f9").to_raw()
    cfg = Config.from_raw(raw)
    assert cfg.overlay == {"mode": "hold"} and cfg.overlay_hotkey == "f9"


def test_every_overlay_key_parses():
    for ks in ovl.KEYSETS.values():
        for key in ks["slots"] + [ks["prev"], ks["next"], ks["stop"], ks["pause"], "esc"]:
            assert winkeys.parse(key), key


def test_keys_are_claimed_only_while_open(make):
    ov = make()
    assert ov.layer() == {}
    ov.handle(Overlay.ACTION)
    assert ov.is_open and ov.host.registered == 1
    layer = ov.layer()
    assert layer["1"] == "__ov:slot:0" and layer["9"] == "__ov:slot:8"
    assert layer["q"] == "__ov:prev" and layer["esc"] == "__ov:close"
    ov.handle(Overlay.ACTION)                           # toggle: again = close
    assert not ov.is_open and ov.layer() == {} and ov.host.registered == 2


def test_numpad_tiles_follow_the_numpad_layout(make):
    ov = make({"keys": "numpad"})
    ov.open()
    layer = ov.layer()
    assert layer["num 7"] == "__ov:slot:0"             # top-left tile
    assert layer["num 3"] == "__ov:slot:8"             # bottom-right tile
    assert "1" not in layer


def test_pick_plays_from_the_current_page_and_closes(make, qapp):
    ov = make()
    ov.open()
    ov.handle("__ov:next")
    ov.handle("__ov:slot:1")
    assert ov.host.played == ["s10"]
    assert ov.is_open                                   # closes a moment later…
    process_events(qapp, lambda: not ov.is_open, timeout=2)
    assert not ov.is_open                               # …so the pick is seen


def test_empty_tile_does_nothing(make):
    ov = make(n=3)
    ov.open()
    ov.handle("__ov:slot:5")
    assert ov.host.played == [] and ov.is_open


def test_pages_wrap_both_ways(make):
    ov = make(n=20)                                      # 3 pages
    ov.open()
    ov.flip(-1)
    assert ov.page == 2 and [m.id for m in ov.page_sounds()] == ["s18", "s19"]
    ov.flip(1)
    assert ov.page == 0


def test_stop_and_pause_go_to_the_host(make):
    ov = make()
    ov.open()
    ov.handle("__ov:stop")
    ov.handle("__ov:pause")
    assert ov.host.actions == ["__stop__", "__pause__"]


def test_foreign_actions_are_left_alone(make):
    ov = make()
    assert ov.handle("s3") is False and ov.handle("__stop__") is False
    assert ov.handle("__ov:slot:0") is True and ov.host.played == []   # closed: dropped


def test_hold_mode_closes_on_release_and_claims_modified_keys(make, monkeypatch, qapp):
    held = {"down": True}
    monkeypatch.setattr(winkeys, "is_down", lambda vk: held["down"])
    ov = make({"mode": "hold", "close_after_play": True}, hotkey="ctrl+alt+o")
    ov.open()
    layer = ov.layer()
    assert layer["1"] == layer["ctrl+alt+1"] == "__ov:slot:0"
    ov.handle(Overlay.ACTION)                           # repeat press: stays open
    ov.handle("__ov:slot:0")
    process_events(qapp, lambda: False, timeout=0.4)
    assert ov.is_open                                   # hold mode ignores close-after-play
    held["down"] = False
    process_events(qapp, lambda: not ov.is_open, timeout=2)
    assert not ov.is_open


def test_autohide(make, qapp):
    ov = make({"autohide": 1})
    ov.open()
    process_events(qapp, lambda: not ov.is_open, timeout=3)
    assert not ov.is_open


def test_exclusive_fullscreen_opens_blind_with_beeps(make, monkeypatch):
    monkeypatch.setattr(winkeys, "exclusive_fullscreen", lambda: True)
    ov = make(n=20)
    ov.open()
    assert ov.blind and ov.layer() and ov._window is None   # keys yes, window no
    ov.flip(1)
    ov.close()
    assert ov.host.cues[0] == "start" and ov.host.cues[-1] == "stop"
    assert ov.host.cues[1] == (1175, 0, 1175, 0)         # two beeps: page 2


def test_window_shows_and_paints(make, qapp):
    ov = make()
    ov.open()
    w = ov.window
    assert w.isVisible()
    ov.tick({"s0": (0.5, False)})
    w.grab()                                             # runs paintEvent
    ov.apply({"scale": 140, "position": "bottom"})
    assert w.size() == w.sizeHint()
    ov.close()
    process_events(qapp, lambda: not w.isVisible(), timeout=2)
    assert not w.isVisible()


def test_clicks_play_tiles_and_pause_stop(make, qapp):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    ov = make({"close_after_play": False})
    ov.open()
    w = ov.window
    k = w._k()

    def at(r):
        return QPoint(round(r.center().x() * k), round(r.center().y() * k))
    QTest.mouseClick(w, Qt.LeftButton, pos=at(w._tile_rect(4)))
    btns = w._buttons()
    QTest.mouseClick(w, Qt.LeftButton, pos=at(btns["pause"]))
    QTest.mouseClick(w, Qt.LeftButton, pos=at(btns["stop"]))
    assert ov.host.played == ["s4"]
    assert ov.host.actions == ["__pause__", "__stop__"]
    ov.tick({"s4": (0.3, True)})
    assert w._all_paused()
    w.grab()                                             # paints the Resume state


def test_preview_claims_no_keys(make, qapp):
    ov = make()
    ov.preview(seconds=0.2)
    assert ov.window.isVisible() and ov.layer() == {} and ov.host.registered == 0
    process_events(qapp, lambda: not ov.window.isVisible(), timeout=2)
    assert not ov.window.isVisible()


# ---------------------------------------------------------------- wired into the app

from test_mainwindow import window  # noqa: E402,F401  (the real MainWindow fixture)


def test_main_window_hotkey_opens_overlay_and_claims_keys(window, monkeypatch):  # noqa: F811
    monkeypatch.setattr(winkeys, "exclusive_fullscreen", lambda: False)
    sent, played = [], []
    monkeypatch.setattr(window.hotkeys, "register", lambda m: sent.append(dict(m)))
    monkeypatch.setattr(window, "play", played.append)
    window.on_hotkey("__overlay__")
    assert window.overlay.is_open and sent[-1]["1"] == "__ov:slot:0"
    assert sent[-1]["`"] == "__overlay__"
    window.on_hotkey("__ov:slot:1")
    assert played == ["s1"]
    window.on_hotkey("__ov:close")
    assert not window.overlay.is_open and "1" not in sent[-1]


def test_settings_overlay_tab_saves_changes(window):  # noqa: F811
    from PySide6.QtWidgets import QComboBox

    from soundboard.settings import SettingsDialog
    d = SettingsDialog(window, "overlay")
    assert d.tabs.tabText(d.tabs.currentIndex()).endswith("Overlay")
    page = d.tabs.currentWidget()
    keys = next(cb for cb in page.findChildren(QComboBox) if cb.findData("numpad") >= 0)
    keys.setCurrentIndex(keys.findData("numpad"))
    assert window.overlay.s.keys == "numpad" and window.cfg.overlay["keys"] == "numpad"
    d.close()
