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


def _tray(w):
    """The tray's Voice changer menu, filled: (its own rows, the Favorites rows)."""
    w._tray_voices = QMenu()                  # (no tray icon under test)
    w._fill_tray_voices()
    rows = [a for a in w._tray_voices.actions() if not a.isSeparator()]
    favs = next(a for a in rows if a.text() == "Favorites").menu()
    return rows, favs.actions()


def test_tray_menu_is_clean_mic_favorites_and_off(window, monkeypatch):
    w = window
    fx, ai = w.voice.fx, w.voice.ai
    name = next(iter(sorted(fx.voice_names())))
    fx.set_favorite(name, True)
    monkeypatch.setattr(ai, "voices", [{"id": "nova", "name": "Nova"},
                                       {"id": "bear", "name": "Bear"}], raising=False)
    monkeypatch.setattr(type(ai), "favorites", property(lambda self: ["bear", "gone"]))
    picked = []
    monkeypatch.setattr(w.hkctl, "pick_ai_voice", picked.append)
    fx.btn_power.setChecked(False)
    rows, favs = _tray(w)
    assert [a.text() for a in rows] == ["Clean mic", "Favorites", "Turn on the voice changer"]
    texts = [a.text() for a in favs]
    assert fx.title_of(name) in texts and "Bear" in texts
    assert "Nova" not in texts and "gone" not in texts      # only the starred, still there
    next(a for a in favs if a.text() == "Bear").trigger()
    assert picked == ["bear"]
    next(a for a in favs if a.text() == fx.title_of(name)).trigger()
    assert fx.btn_power.isChecked() and fx.preset == name
    rows, favs = _tray(w)
    assert next(a for a in favs if a.text() == fx.title_of(name)).isChecked()
    stopped = []
    monkeypatch.setattr(ai, "stop", lambda: stopped.append(True))
    next(a for a in rows if a.text() == "Turn voices off").trigger()
    assert not fx.btn_power.isChecked() and stopped


def test_tray_menu_clean_mic_toggles(window):
    w = window
    clean = w.voice.clean
    if not clean.ok:
        return
    was = clean.is_on()
    rows, _favs = _tray(w)
    next(a for a in rows if a.text() == "Clean mic").trigger()
    assert clean.is_on() != was
    clean.set_on(was)


def test_tray_menu_without_favorites_says_how(window, monkeypatch):
    w = window
    fx, ai = w.voice.fx, w.voice.ai
    for n in list(fx.favorites):
        fx.set_favorite(n, False)
    monkeypatch.setattr(type(ai), "favorites", property(lambda self: []))
    _rows, favs = _tray(w)
    assert [a.text() for a in favs] == ["Star voices on the Voice tab to list them here"]
