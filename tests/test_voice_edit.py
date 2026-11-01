"""Edit voice's Reset, Undo / Redo and Mix in a voice; Edit voice and hotkeys from a voice
card's right-click menu, on the voice changer's cards and the AI voices' cards."""
from PySide6.QtCore import QPoint, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu

from test_mainwindow import window  # noqa: F401


def settle(ms: int = 500):
    QTest.qWait(ms)   # a change becomes an Undo step once it settles


def menu_texts(open_menu) -> list[str]:
    got: list[str] = []

    def read():
        m = QApplication.activePopupWidget()
        if isinstance(m, QMenu):
            got.extend(a.text() for a in m.actions() if a.text())
            m.close()
    QTimer.singleShot(200, read)
    open_menu()
    return got


def test_reset_puts_the_picked_voice_back_and_undo_brings_the_change_back(window):  # noqa: F811
    fx = window.voice.fx
    fx.pick("Robot")
    assert not fx.btn_reset.isEnabled()
    assert fx.dlg_name.text() == "Robot"
    fx.rows["harmony"].chk.setChecked(True)
    settle()
    assert fx.preset != "Robot" and fx.btn_reset.isEnabled()
    assert "changed" in fx.dlg_name.text()
    fx.reset_edits()
    assert fx.preset == "Robot" and not fx.rows["harmony"].chk.isChecked()
    assert not fx.btn_reset.isEnabled()
    fx.undo()
    assert fx.rows["harmony"].chk.isChecked()
    fx.redo()
    assert fx.preset == "Robot" and not fx.rows["harmony"].chk.isChecked()


def test_undo_steps_back_one_change_at_a_time(window):  # noqa: F811
    fx = window.voice.fx
    fx.pick("Robot")
    fx.rows["harmony"].chk.setChecked(True)
    settle()
    fx.rows["growl"].chk.setChecked(True)
    settle()
    fx.undo()
    assert fx.rows["harmony"].chk.isChecked() and not fx.rows["growl"].chk.isChecked()
    fx.undo()
    assert not fx.rows["harmony"].chk.isChecked() and fx.preset == "Robot"
    assert not fx.btn_undo.isEnabled() and fx.btn_redo.isEnabled()


def test_saving_makes_the_saved_voice_what_reset_goes_back_to(window, monkeypatch):  # noqa: F811
    fx = window.voice.fx
    fx.pick("Robot")
    fx.rows["harmony"].chk.setChecked(True)
    settle()
    monkeypatch.setattr(fx, "_ask_name", lambda *a, **k: "Choir bot")
    fx.save_voice()
    assert fx.preset == "Choir bot" and not fx.btn_reset.isEnabled()
    fx.rows["harmony"].chk.setChecked(False)
    settle()
    fx.reset_edits()
    assert fx.preset == "Choir bot" and fx.rows["harmony"].chk.isChecked()


def test_mix_in_adds_the_other_voices_effects_and_keeps_yours(window):  # noqa: F811
    fx = window.voice.fx
    fx.pick("Robot")
    robot = fx.rows["robot"].state()
    added = fx.mix_in("Demon")
    assert added and "robot" not in added
    assert all(fx.rows[t].chk.isChecked() and fx.rows[t].is_fresh() for t in added)
    assert fx.rows["robot"].state() == robot   # yours stays as it was
    assert fx.btn_reset.isEnabled()
    settle()
    fx.reset_edits()
    assert fx.preset == "Robot" and not any(fx.rows[t].chk.isChecked() for t in added)
    assert fx.mix_in("Robot") == []   # nothing new to add


def test_voice_card_menu_edits_that_voice(window):  # noqa: F811
    fx = window.voice.fx
    tile = fx._tile["Hothead"]
    texts = menu_texts(lambda: fx._tile_menu("Hothead", tile.mapToGlobal(QPoint(5, 5))))
    assert "Edit voice…" in texts
    fx.edit_voice("Hothead")
    assert fx.preset == "Hothead" and fx.btn_power.isChecked() and fx.dlg.isVisible()
    assert fx.dlg_name.text() == fx.title_of("Hothead")
    fx.dlg.close()


def test_ai_voice_cards_have_the_same_menu_and_a_hotkey(window, monkeypatch):  # noqa: F811
    ai = window.voice.ai
    ai.set_modules([], voices=[{"id": "duke", "name": "Duke"}, {"id": "ivy", "name": "Ivy"}])
    tile = ai._tile["duke"]
    texts = menu_texts(lambda: ai._card_menu("duke", tile.mapToGlobal(QPoint(5, 5))))
    assert "Edit voice…" in texts and "Set a hotkey…" in texts
    monkeypatch.setattr(ai, "open_tweak", lambda under=None: None)
    ai.edit_voice("ivy")
    assert ai.current_voice() == "ivy"

    hk = window.hkctl
    hk.set_ai_voice_hotkey("duke", "ctrl+alt+f9")
    assert window.cfg.voice_hotkeys["ai:duke"] == "ctrl+alt+f9"
    assert ai.keys == {"duke": "ctrl+alt+f9"}
    used = []
    monkeypatch.setattr(ai, "use", used.append)
    hk.on_hotkey("__pickai__:duke")
    assert used == ["duke"]
    # a voice changer voice taking the key takes it off the AI voice
    window.hkctl.set_voice_hotkey("Robot", "ctrl+alt+f9")
    assert "ai:duke" not in window.cfg.voice_hotkeys
    hk.set_ai_voice_hotkey("ivy", "ctrl+alt+f8")
    hk.set_ai_voice_hotkey("ivy", "")
    assert "ai:ivy" not in window.cfg.voice_hotkeys and ai.keys == {}
