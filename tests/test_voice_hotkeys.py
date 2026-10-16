"""A voice's own hotkey, and the tray's Voice changer menu."""
import pytest
from PySide6.QtWidgets import QMenu

from test_mainwindow import window as main_window  # noqa: F401  (the real MainWindow)


@pytest.fixture
def window(main_window):  # noqa: F811
    return main_window


def test_voice_hotkey_picks_the_voice_and_is_unique(window, monkeypatch):
    w = window
    registered = []
    monkeypatch.setattr(w.hotkeys, "register", lambda m: registered.append(dict(m)))
    fx = w.voice.fx
    name = next(iter(sorted(fx.voice_names())))
    w.meta("s0").hotkey = "ctrl+7"
    w.hkctl.set_voice_hotkey(name, "ctrl+7")
    assert w.meta("s0").hotkey == "" and w.cfg.voice_hotkeys == {name: "ctrl+7"}
    assert registered[-1]["ctrl+7"] == "__pickvoice__:" + name
    fx.btn_power.setChecked(False)
    w.hkctl.on_hotkey("__pickvoice__:" + name)
    assert fx.btn_power.isChecked() and fx.preset == name
    w.hkctl.set_global_hotkey("stop_hotkey", "ctrl+7")      # the key goes to something else
    assert w.cfg.voice_hotkeys == {}
    w.hkctl.set_voice_hotkey(name, "ctrl+8")
    w.hkctl.set_voice_hotkey(name, "")
    assert w.cfg.voice_hotkeys == {}


def test_voice_hotkey_ignores_a_voice_that_is_gone(window, monkeypatch):
    w = window
    monkeypatch.setattr(w.hotkeys, "register", lambda m: None)
    w.cfg.voice_hotkeys = {"Not a voice": "ctrl+9"}
    registered = []
    monkeypatch.setattr(w.hotkeys, "register", lambda m: registered.append(dict(m)))
    w.hkctl.register_hotkeys()
    assert "ctrl+9" not in registered[-1]
    w.hkctl.on_hotkey("__pickvoice__:Not a voice")          # nothing happens, no crash


def test_tray_menu_lists_favorites_and_picks(window):
    w = window
    fx = w.voice.fx
    name = next(iter(sorted(fx.voice_names())))
    fx.set_favorite(name, True)
    w._tray_voices = QMenu()                  # (no tray icon under test)
    w._fill_tray_voices()
    acts = [a for a in w._tray_voices.actions() if a.text() == fx.title_of(name)]
    assert len(acts) == 1
    acts[0].trigger()
    assert fx.btn_power.isChecked() and fx.preset == name
