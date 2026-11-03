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
    """The tray's Voice changer menu, filled: {text: row} for it and for Favorites and
    each of its menus."""
    w._tray_voices = QMenu()                  # (no tray icon under test)
    w._fill_tray_voices()
    rows = [a for a in w._tray_voices.actions() if not a.isSeparator()]
    favs = next(a for a in rows if a.text() == "Favorites").menu()
    inner = {a.text(): {b.text(): b for b in a.menu().actions()}
             for a in favs.actions() if a.menu() is not None}
    return {a.text(): a for a in rows}, {a.text(): a for a in favs.actions()}, inner


def test_tray_favorites_has_a_menu_per_kind_and_shows_whats_on(window, monkeypatch):
    w = window
    fx, ai = w.voice.fx, w.voice.ai
    a, b = sorted(fx.voice_names())[:2]
    for n in (a, b):
        fx.set_favorite(n, True)
    monkeypatch.setattr(ai, "voices", [{"id": "nova", "name": "Nova"},
                                       {"id": "bear", "name": "Bear"}], raising=False)
    monkeypatch.setattr(type(ai), "favorites", property(lambda self: ["bear", "gone"]))
    now = {"ai": None}
    monkeypatch.setattr(ai, "is_on", lambda: now["ai"] is not None)
    monkeypatch.setattr(ai, "current_voice", lambda: now["ai"])
    monkeypatch.setattr(w.hkctl, "pick_ai_voice", lambda v: now.update(ai=v))
    monkeypatch.setattr(ai, "stop", lambda: now.update(ai=None))
    fx.btn_power.setChecked(False)
    rows, favs, inner = _tray(w)
    assert list(rows) == ["Clean mic", "Favorites", "Turn on the voice changer"]
    assert list(favs) == ["Voice changer", "AI voices"]
    assert set(inner["Voice changer"]) == {fx.title_of(a), fx.title_of(b)}
    assert list(inner["AI voices"]) == ["Bear"]           # only the starred, still there
    # one of each on: both show as plain rows under Favorites
    inner["Voice changer"][fx.title_of(a)].trigger()
    inner["AI voices"]["Bear"].trigger()
    rows, favs, inner = _tray(w)
    shown = f"Voice changer: {fx.title_of(a)}"
    assert list(rows) == ["Clean mic", "Favorites", shown, "AI voice: Bear", "Turn voices off"]
    assert not rows[shown].isEnabled() and not rows["AI voice: Bear"].isEnabled()
    assert inner["Voice changer"][fx.title_of(a)].isChecked()
    assert inner["AI voices"]["Bear"].isChecked()
    # another voice swaps it; the ticked one again turns it off
    inner["Voice changer"][fx.title_of(b)].trigger()
    assert fx.btn_power.isChecked() and fx.preset == b
    rows, favs, inner = _tray(w)
    assert not inner["Voice changer"][fx.title_of(a)].isChecked()
    inner["Voice changer"][fx.title_of(b)].trigger()
    inner["AI voices"]["Bear"].trigger()
    assert not fx.btn_power.isChecked() and now["ai"] is None
    # Turn voices off turns both off
    fx.pick(a)
    now["ai"] = "bear"
    rows, favs, inner = _tray(w)
    rows["Turn voices off"].trigger()
    assert not fx.btn_power.isChecked() and now["ai"] is None


def test_tray_menu_clean_mic_toggles(window):
    w = window
    clean = w.voice.clean
    if not clean.ok:
        return
    was = clean.is_on()
    rows, _favs, _inner = _tray(w)
    rows["Clean mic"].trigger()
    assert clean.is_on() != was
    clean.set_on(was)


def test_tray_menu_without_favorites_says_how(window, monkeypatch):
    w = window
    fx, ai = w.voice.fx, w.voice.ai
    for n in list(fx.favorites):
        fx.set_favorite(n, False)
    monkeypatch.setattr(type(ai), "favorites", property(lambda self: []))
    _rows, favs, inner = _tray(w)
    assert list(favs) == ["Star voices on the Voice tab to list them here"] and not inner
