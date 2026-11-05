"""Edit voice's Reset, Undo / Redo and Mix in a voice; Edit voice and hotkeys from a voice
card's right-click menu, on the voice changer's cards and the AI voices' cards."""
from PySide6.QtCore import QPoint, QSize, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu

from soundboard.ui.kit import toast
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


def test_a_cards_reset_puts_it_back_as_the_voice_has_it(window):  # noqa: F811
    """A card's own Reset on a voice: that card as the voice has it (Pitch off for a
    voice without it), and once nothing's changed it's that voice again, not "My own
    mix"."""
    fx = window.voice.fx
    fx.pick("Singing monk")
    pitch = fx.rows["pitch"].sliders[0].slider
    pitch.setValue(pitch.maximum())
    robot = fx.rows["robot"]
    robot.chk.setChecked(True)
    settle()
    assert fx.preset != "Singing monk" and fx.picked_name.text() == "My own mix"
    fx.rows["pitch"].reset()
    assert not fx.rows["pitch"].chk.isChecked() and fx.preset != "Singing monk"
    robot.reset()
    assert not robot.chk.isChecked()
    assert fx.preset == "Singing monk" and fx.picked_name.text() == "Singing monk"
    assert not fx.btn_reset.isEnabled() and fx.dlg_name.text() == "Singing monk"
    fx.pick("Robot")
    before = robot.state()
    robot.sliders[0].slider.setValue(robot.sliders[0].slider.minimum())
    assert fx.preset != "Robot"
    robot.reset()
    assert robot.state() == before and fx.preset == "Robot"


def test_a_cards_reset_on_your_own_mix_goes_to_the_effects_start(window):  # noqa: F811
    fx = window.voice.fx
    fx.clear_mix()
    pitch = fx.rows["pitch"].sliders[0].slider
    pitch.setValue(pitch.maximum())
    fx.rows["pitch"].reset()
    assert fx.rows["pitch"].state()["semitones"] == 0 and fx.preset != "Robot"


def test_right_click_edit_voice_after_changing_it_edits_the_mics_voice(window):  # noqa: F811
    """Changed a voice, closed Edit voice, then its card's right-click Edit voice: the
    same changes come back, and Reset puts the voice back on the mic too (it opened a
    fresh copy of the voice instead, so Reset left "My own mix" on)."""
    fx = window.voice.fx
    fx.pick("Hothead")
    fx.open_tweak()
    pitch = fx.rows["pitch"].sliders[0].slider
    pitch.setValue(pitch.maximum())
    settle()
    fx.dlg.close()
    fx.edit_voice("Hothead")
    assert fx.dlg_name.text() == "Hothead, changed"
    assert fx.rows["pitch"].state()["semitones"] > 0
    fx.reset_edits()
    assert fx.preset == "Hothead" and fx.picked_name.text() == "Hothead"
    fx.dlg.close()


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
    fx.pick("Robot")
    fx.edit_voice("Robot")   # the voice that's on: edited live, as the bar's button does
    assert fx.preset == "Robot" and fx.dlg.isVisible() and fx._preview is None
    fx.dlg.close()


def test_edit_voice_on_a_card_never_turns_that_voice_on(window):  # noqa: F811
    fx = window.voice.fx
    fx.btn_power.setChecked(False)
    sent = []
    fx.changed.connect(sent.append)
    fx.edit_voice("Hothead")
    assert fx.dlg.isVisible() and fx.dlg_name.text() == fx.title_of("Hothead")
    assert fx.rows["pitch"].chk.isChecked() or fx._count_on() > 0   # Hothead's own
    assert not fx.btn_power.isChecked() and not fx._tile["Hothead"].isChecked()
    assert not fx.picked.isVisibleTo(fx)
    fx.rows["pitch"].chk.setChecked(not fx.rows["pitch"].chk.isChecked())   # an edit
    assert not fx.btn_power.isChecked()
    assert sent and all(not s["enabled"] for s in sent)   # the mic never got it
    fx.dlg.close()
    assert not fx.btn_power.isChecked() and fx.spec()["enabled"] is False

    # another voice on: it stays on, and comes back to the editor when it closes
    fx.pick("Robot")
    robot = fx.spec()["effects"]
    sent.clear()
    fx.edit_voice("Hothead")
    assert fx.btn_power.isChecked() and fx.preset == "Robot"
    assert fx._tile["Robot"].isChecked() and not fx._tile["Hothead"].isChecked()
    assert fx.picked_name.text() == fx.title_of("Robot")
    assert all(s["preset"] == "Robot" and s["effects"] == robot for s in sent)
    fx.dlg.close()
    assert fx._preview is None and fx._preset == "Robot" and fx.spec()["effects"] == robot

    # a card clicked while Edit voice shows another: that voice, on, as always
    fx.edit_voice("Hothead")
    fx._tile_clicked("Chipmunk")
    assert fx._preview is None and fx.preset == "Chipmunk" and fx.btn_power.isChecked()
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


def test_animals_are_voices_not_effects_on_another_voice(window):  # noqa: F811
    """Nobody puts a cow on a robot: an animal's card shows only while that animal is
    the voice (its Pitch and the rest), and Randomize never adds one."""
    import random
    from soundboard.ui.voice.effectrow import CALLERS
    fx = window.voice.fx

    def shown():
        QTest.qWait(50)
        return {t for t in CALLERS
                if any(fx.rows[t] in cards for _title, cards in fx._ordered_cards())}
    fx.pick("Robot")
    assert shown() == set()
    fx.pick("Cow")
    assert shown() == {"cow"} and not fx.rows["dog"].isVisibleTo(fx.dlg)
    fx.pick("Robot")
    assert shown() == set() and not fx.rows["cow"].isVisibleTo(fx.dlg)
    for seed in range(30):
        fx.randomize(random.Random(seed))
        assert not any(fx.rows[t].chk.isChecked() for t in CALLERS)


def test_opening_edit_voice_leaves_the_toasts_clickable(window):  # noqa: F811
    """Edit voice belongs to the main window, and asking for its window handle made every
    other child of the main window a native window too. The page then lay over the toasts:
    they still showed, but Windows gave their mouse to the page, so none could be clicked
    for the rest of the run."""
    fx = window.voice.fx
    fx.open_tweak()
    settle(100)
    fx.dlg.close()
    page = window.centralWidget()
    card = toast.show(window, "A notice", "ok", ms=0)
    assert card is not None
    assert not page.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)
    assert not page.internalWinId()
    assert not card.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)
    card.dismiss()


def test_edit_voice_and_its_buttons_stay_on_the_screen(window):  # noqa: F811
    """A size left from a bigger screen (or just a small screen): the whole window, title
    bar included, fits in the room above the task bar, so Done can be clicked. Its inside
    alone was limited to that room, which left the bottom row under the task bar."""
    def check(fx):
        settle(100)
        room = fx.dlg.screen().availableGeometry()
        assert room.contains(fx.dlg.frameGeometry())
        assert fx.btn_save.isVisible()
        assert room.contains(fx.btn_save.mapToGlobal(fx.btn_save.rect().bottomRight()))
        assert fx.more.currentWidget().height() > 0   # the middle is what gets shorter
        fx.dlg.close()

    fx = window.voice.fx
    fx._dlg_size = QSize(660, 5000)
    fx.open_tweak()
    check(fx)
    fx.dlg.move(0, 5000)   # left low on a screen it's no longer on
    fx.open_tweak()
    check(fx)
    window.voice._edit_ai_voice()   # an AI voice's is the same window
    ai = window.voice.ai_edit
    ai._dlg_size = QSize(660, 5000)
    ai.dlg.close()
    ai.open_tweak()
    check(ai)
