"""A voice's own hotkey, and the tray's Voice changer menu."""
import pytest
from PySide6.QtWidgets import QMenu, QWidgetAction

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


def test_tray_menu_lists_clean_mic_and_starred_ai_voices(window, monkeypatch):
    w = window
    ai, clean = w.voice.ai, w.voice.clean
    monkeypatch.setattr(ai, "voices", [{"id": "nova", "name": "Nova"},
                                       {"id": "bear", "name": "Bear"}], raising=False)
    monkeypatch.setattr(type(ai), "favorites", property(lambda self: ["bear", "gone"]))
    picked = []
    monkeypatch.setattr(w.hkctl, "pick_ai_voice", picked.append)
    w._tray_voices = QMenu()                  # (no tray icon under test)
    w._fill_tray_voices()
    texts = [a.text() for a in w._tray_voices.actions()]
    assert "Clean mic" in texts and "Bear" in texts
    assert "Nova" not in texts and "gone" not in texts      # only the starred, still there
    next(a for a in w._tray_voices.actions() if a.text() == "Bear").trigger()
    assert picked == ["bear"]
    if clean.ok:
        was = clean.is_on()
        next(a for a in w._tray_voices.actions() if a.text() == "Clean mic").trigger()
        assert clean.is_on() != was
        clean.set_on(was)


def test_tray_menu_groups_under_headings_and_turns_voices_off(window, monkeypatch):
    w = window
    fx, ai = w.voice.fx, w.voice.ai
    fav = next(iter(sorted(fx.voice_names())))
    fx.set_favorite(fav, True)
    monkeypatch.setattr(fx, "saved_names", lambda: ["fdsfs", "fdsfs (2)"])
    monkeypatch.setattr(fx, "voice_names", lambda: {fav, "fdsfs", "fdsfs (2)"})
    monkeypatch.setattr(ai, "voices", [{"id": "bear", "name": "Bear"}], raising=False)
    monkeypatch.setattr(type(ai), "favorites", property(lambda self: ["bear"]))
    w._tray_voices = QMenu()                  # (no tray icon under test)
    w._fill_tray_voices()
    texts = [a.text() for a in w._tray_voices.actions() if not a.isSeparator()]
    heads = [a.text() for a in w._tray_voices.actions() if isinstance(a, QWidgetAction)]
    assert heads == ["Voice changer", "Saved voices", "AI voices"]
    assert texts.index("Voice changer") < texts.index(fx.title_of(fav)) < texts.index(
        "Saved voices") < texts.index("fdsfs") < texts.index("AI voices") < texts.index("Bear")
    assert "Turn voices off" in texts or "Turn on the voice changer" in texts
    # on, then off from the menu: the voice changer and the AI voice both go off
    fx.btn_power.setChecked(True)
    stopped = []
    monkeypatch.setattr(ai, "stop", lambda: stopped.append(True))
    w._fill_tray_voices()
    off = next(a for a in w._tray_voices.actions() if a.text() == "Turn voices off")
    off.trigger()
    assert not fx.btn_power.isChecked() and stopped
    w._fill_tray_voices()
    assert "Turn on the voice changer" in [a.text() for a in w._tray_voices.actions()]


def test_tray_menu_hides_empty_groups(window, monkeypatch):
    w = window
    fx, ai = w.voice.fx, w.voice.ai
    for n in list(fx.favorites):
        fx.set_favorite(n, False)
    monkeypatch.setattr(fx, "saved_names", lambda: [])
    monkeypatch.setattr(type(ai), "favorites", property(lambda self: []))
    w._tray_voices = QMenu()                  # (no tray icon under test)
    w._fill_tray_voices()
    assert not [a for a in w._tray_voices.actions() if isinstance(a, QWidgetAction)]
    assert "Star voices on the Voice tab to list them here" in [
        a.text() for a in w._tray_voices.actions()]
