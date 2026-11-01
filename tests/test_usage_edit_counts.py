"""The usage count hears of Edit sound's newer parts (Undo / Redo, its player, the
waveform's seek and zoom, splices), Live controls' Update / Reset of your own preset,
Star on GitHub, an On Air group folded and the mic helper switched off: by name only,
never what was edited, played or which preset (usage.FEATURES)."""
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from soundboard.audio import mypresets
from soundboard.core import usage
from soundboard.sounds.library import Config
from soundboard.ui.sounds.dialogs import EditDialog
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)

LEFT = Qt.MouseButton.LeftButton
NO = Qt.KeyboardModifier.NoModifier


@pytest.fixture
def used(monkeypatch):
    got: set[str] = set()
    monkeypatch.setattr(usage, "_used", got)
    yield got
    assert got <= set(usage.FEATURES)   # only names a count may send


def _dialog(w, monkeypatch):
    """Advanced, on a 10 s sound (long enough for two splices)."""
    from soundboard.ui.sounds import dialogs
    monkeypatch.setattr(dialogs, "original_length", lambda meta: 10.0)
    m = w.meta("s0")
    m.fx = {}
    d = EditDialog(m, w.hotkeys, lambda *a: "playing", w, advanced=True)
    d.show()
    QApplication.processEvents()
    return d


def _click(wave, t: float, y: int | None = None):
    pos = QPoint(round(wave._x(t)), wave.height() // 2 if y is None else y)
    QTest.mouseMove(wave, pos)
    QTest.mouseClick(wave, LEFT, NO, pos)


def test_undo_and_redo_count_only_when_they_do_something(window, monkeypatch, used):  # noqa: F811
    d = _dialog(window, monkeypatch)
    d.undo()
    d.redo()
    assert not {"edit-undo", "edit-redo"} & used   # nothing to undo yet
    d.fade_in.setValue(12)
    d.undo()
    assert "edit-undo" in used and "edit-redo" not in used
    d.redo()
    assert "edit-redo" in used
    d.close()


def test_the_waveform_counts_a_seek_and_a_zoom(window, monkeypatch, used):  # noqa: F811
    from soundboard.ui.sounds.trim import RULER_H
    d = _dialog(window, monkeypatch)
    wave = d.effects.trim.wave
    _click(wave, wave.length * 0.3)                  # a handle moved: neither
    assert not {"edit-wave-seek", "edit-wave-zoom"} & used
    d.adv.btn_in.click()
    assert "edit-wave-zoom" in used
    wave.set_play(1.0)
    _click(wave, (wave.view[0] + wave.view[1]) / 2, RULER_H // 2)   # the ruler
    assert "edit-wave-seek" in used
    d.close()


def test_splices_count_marked_played_and_combined(window, monkeypatch, used):  # noqa: F811
    d = _dialog(window, monkeypatch)
    bar, wave = d.adv.splices, d.effects.trim.wave
    L = wave.length
    bar.cut.click()
    _click(wave, L * 0.1)
    assert "edit-splice-marked" not in used          # half a splice
    _click(wave, L * 0.2)
    assert "edit-splice-marked" in used
    bar.play(0)
    assert "edit-splice-play" in used
    bar.ask_combine()
    bar.dlg.reject()                                 # Cancel: not a combine
    QApplication.processEvents()
    assert not {"edit-splices-new", "edit-splices-replace"} & used
    bar.ask_combine()
    bar.dlg._pick("replace")
    QApplication.processEvents()
    assert "edit-splices-replace" in used and "edit-splices-new" not in used


def test_edit_sounds_player_counts_its_own_buttons(window, used):  # noqa: F811
    d = window.editctl.edit("s0")
    p = d.player
    assert "edit-player" not in used
    p.btn_st.click()
    assert "edit-player" in used
    d.reject()


def test_your_presets_update_and_reset_count(qapp, monkeypatch, used):
    from soundboard.ui.sounds import speedpitch
    from soundboard.ui.sounds.speedpitch import SpeedPitchButton

    picked = []

    class Menu(speedpitch.QMenu):
        def exec(self, *_a):   # the ▾ menu's Reset, without a real pop-up
            for a in self.actions():
                if a.text().startswith(picked[-1]):
                    a.trigger()

    monkeypatch.setattr(speedpitch, "QMenu", Menu)
    mypresets.put("live", "Loud", {"bass": 6, "treble": 5})
    b = SpeedPitchButton("sounds")
    try:
        b._open()
        b.my_chips["Loud"].click()
        b.set_fx({"bass": 9, "treble": 5})
        picked.append("Reset")
        b._preset_menu()
        assert "live-mine-reset" in used and b.fx_values() == {"bass": 6, "treble": 5}
        assert "live-mine-updated" not in used
        b.set_fx({"bass": 9, "treble": 5})
        b.save_preset_btn.click()                    # Update "Loud"
        assert "live-mine-updated" in used
    finally:
        b.pop.close()


def test_star_on_github_counts(window, monkeypatch, used):  # noqa: F811
    from soundboard.ui.kit import busy
    monkeypatch.setattr(busy, "open_url", lambda *a, **k: None)   # no browser
    dlg = window.setctl.open_settings("about")
    dlg.star_btn.click()
    assert "github-star" in used
    window.setctl.close_settings()


def test_folding_an_on_air_group_counts(window, monkeypatch, used):  # noqa: F811
    card = window.rail.output
    monkeypatch.setattr(card, "folds", lambda g: False)
    card.toggle("voice")
    assert "on-air-fold" not in used                 # one line: no arrow, no fold
    monkeypatch.setattr(card, "folds", lambda g: True)
    card.toggle("voice")
    assert "on-air-fold" in used
    card.toggle("voice")


def test_the_mic_helper_switched_off_counts_every_day():
    assert "mic-helper-off" in usage.features_now(Config(mic_helper=False))
    assert "mic-helper-off" not in usage.features_now(Config())
    assert set(usage.features_now(Config(mic_helper=False))) <= set(usage.FEATURES)

