"""A splice's own settings: clicked on Edit sound's big waveform, the Speed & loudness,
Effects and Equalizer columns change just that splice (soundfx "parts", heard when
the splices play joined); its right-click menu plays it, saves it as a pad of its own
or copies it; and the fade grips along the top drag its fades (or the sound's)."""
import numpy as np
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from soundboard.audio import soundfx
from soundboard.audio.engine import SR
from soundboard.ui.sounds.dialogs import EditDialog
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)

LEFT = Qt.MouseButton.LeftButton
RIGHT = Qt.MouseButton.RightButton
NO = Qt.KeyboardModifier.NoModifier


def _ramp(seconds: float) -> np.ndarray:
    t = (np.arange(int(seconds * SR)) / SR).astype(np.float32)
    return np.stack([t, t], axis=1)


# ------------------------------------------------------------------ the settings

def test_parts_are_cleaned_and_only_kept_with_their_splices():
    f = soundfx.clean({"splices": [[0, 1], [2, 3]],
                       "parts": [{"speed": 9, "volume": 5, "fade_in": -1, "junk": 1},
                                 {"speed": 1.0, "eq": [0] * 7}, {"speed": 2}]})
    assert f["parts"] == [{"speed": soundfx.SPEED_RANGE[1], "volume": 2.0}, {}]
    assert soundfx.clean({"parts": [{"speed": 2}]})["parts"] == []   # no splices
    assert soundfx.clean({"splices": [[0, 1]], "parts": [{}]})["parts"] == []
    # marked only, they change nothing that plays: the same cache as no splices
    assert soundfx.key({"splices": [[0, 1]], "parts": [{"speed": 2}]}) == ""


def test_a_joined_splice_plays_with_its_own_speed_volume_and_fades():
    x = np.ones((3 * SR, 2), np.float32) * 0.5
    fx = {"splices": [[0, 1], [2, 3]], "joined": True,
          "parts": [{"speed": 2.0, "fade_in": 0.2}, {"volume": 0.5}]}
    y = soundfx.trim(x, fx)
    assert abs(len(y) / SR - 1.5) < 0.01          # 1 s at 2x, then 1 s
    assert abs(y[10]).max() < 0.05               # its fade in starts silent
    assert abs(abs(y[int(0.35 * SR)]).max() - 0.5) < 0.02
    assert abs(abs(y[-SR // 2]).max() - 0.25) < 0.01   # splice 2 at half volume
    # the playhead knows splice 1 goes by twice as fast
    assert abs(soundfx.time_at(fx, 3.0, 0.5) - 2.25) < 0.01
    assert abs(soundfx.frac_at(fx, 3.0, 2.25) - 0.5) < 0.01


def test_a_part_with_nothing_of_its_own_plays_as_before():
    x = _ramp(4.0)
    plain = soundfx.join(x, [[0.5, 1.0], [2.0, 3.0]])
    same = soundfx.join(x, [[0.5, 1.0], [2.0, 3.0]], [{}, {}])
    assert np.array_equal(plain, same)


def test_splice_alone_is_one_joined_splice_with_its_own_settings():
    fx = {"splices": [[0, 1], [2, 3]], "parts": [{}, {"pitch": 3}], "speed": 1.5}
    one = soundfx.splice_alone(fx, 1)
    assert one["splices"] == [[2.0, 3.0]] and one["joined"]
    assert one["parts"] == [{"pitch": 3.0}] and one["speed"] == 1.5
    assert (one["start"], one["end"]) == (2.0, 3.0)   # what an older version plays


# ------------------------------------------------------------------ the editor

def _dialog(w, monkeypatch, preview=None):
    from soundboard.ui.sounds import dialogs
    monkeypatch.setattr(dialogs, "original_length", lambda meta: 10.0)
    m = w.meta("s0")
    m.fx = {}
    d = EditDialog(m, w.hotkeys, preview or (lambda *a: None), w, advanced=True)
    d.resize(1400, 900)
    d.show()
    QApplication.processEvents()
    return d


def _at(wave, t: float, y: int | None = None) -> QPoint:
    return QPoint(round(wave._x(t)), wave.height() // 2 if y is None else y)


def test_clicking_a_splice_edits_its_own_settings(window, monkeypatch):  # noqa: F811
    d = _dialog(window, monkeypatch)
    eff = d.effects
    wave = eff.trim.wave
    L = wave.length
    eff.trim.load(soundfx.clean({"splices": [[L * 0.2, L * 0.4], [L * 0.6, L * 0.8]]}))
    eff.speed.set_value(1.25)                       # the whole sound's speed
    eff._edited()
    QTest.mouseClick(wave, LEFT, NO, _at(wave, L * 0.7))
    assert wave.selected == 1 and eff.part == 1
    assert not d.adv.part_bar.isHidden() and "Splice 2" in d.adv.part_text.text()
    assert abs(eff.speed.value() - 1.0) < 1e-6      # splice 2's own: plain so far
    assert not eff.voice.isEnabled()                # a voice is the whole sound's
    eff.speed.set_value(2.0)
    eff.volume.set_value(50)
    eff._edited()
    fx = eff.fx()
    assert fx["speed"] == 1.25                      # the sound's speed is kept
    assert fx["parts"] == [{}, {"speed": 2.0, "volume": 0.5}]
    assert d.vol.value() == 100                     # the pad's volume isn't the splice's
    d.adv.part_whole.click()                        # back to the whole sound
    assert eff.part is None and d.adv.part_bar.isHidden()
    assert abs(eff.speed.value() - 1.25) < 1e-6 and abs(eff.volume.value() - 100) < 0.6
    QTest.mouseClick(wave, LEFT, NO, _at(wave, L * 0.7))   # its settings are still there
    assert abs(eff.speed.value() - 2.0) < 1e-6
    QTest.keyClick(wave, Qt.Key.Key_Escape)          # Esc: the whole sound, not the window
    assert eff.part is None and d.isVisible()
    QTest.mouseClick(wave, LEFT, NO, _at(wave, L * 0.3))
    eff.trim.remove_splice(0)                       # picked one removed: whole again
    assert eff.part is None and eff.fx()["parts"] == [{"speed": 2.0, "volume": 0.5}]
    d.close()


def test_undo_brings_a_splices_settings_back(window, monkeypatch):  # noqa: F811
    d = _dialog(window, monkeypatch)
    eff = d.effects
    wave = eff.trim.wave
    L = wave.length
    eff.trim.load(soundfx.clean({"splices": [[L * 0.2, L * 0.4]]}))
    d._flush()
    d._remember()
    QTest.mouseClick(wave, LEFT, NO, _at(wave, L * 0.3))
    eff.pitch.set_value(5.0)
    eff._edited()
    d._flush()
    assert eff.fx()["parts"] == [{"pitch": 5.0}]
    d.undo()
    assert eff.fx()["parts"] == [] and eff.part == 0 and abs(eff.pitch.value()) < 1e-6
    d.redo()
    assert abs(eff.pitch.value() - 5.0) < 1e-6
    d.close()


def test_the_right_click_menu(window, monkeypatch, tmp_path):  # noqa: F811
    played, saved = [], []

    def preview(sid, vol, fx, fades, done):
        played.append(fx)
        return "playing"
    d = _dialog(window, monkeypatch, preview)
    eff, bar = d.effects, d.adv.splices
    wave = eff.trim.wave
    L = wave.length
    eff.trim.load(soundfx.clean({"splices": [[L * 0.2, L * 0.4]],
                                 "parts": [{"pitch": -4}]}))
    QTest.mouseClick(wave, RIGHT, NO, _at(wave, L * 0.3))
    menu = bar._menu
    assert menu is not None
    names = [a.text() for a in menu.actions() if a.text()]
    assert names == ["Play now", "Edit its effects", "Save as new pad…", "Copy to clipboard",
                     "Remove splice 1"]
    menu.close()
    menu.actions()[0].trigger()                     # Play now: with its own pitch
    assert soundfx.clean(played[-1])["parts"] == [{"pitch": -4.0}]
    d.effects.trim.show_playing(0.5, {})            # the playhead in the splice
    assert L * 0.2 < wave.play < L * 0.4
    d.splice_saved.connect(lambda fx, name: saved.append((fx, name)))
    from soundboard.ui.sounds import splicepanel
    monkeypatch.setattr(splicepanel.QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("Just the drop", True)))
    bar.save_as_pad(0)
    assert saved and saved[0][1] == "Just the drop"
    assert saved[0][0]["splices"] == [[round(L * 0.2, 3), round(L * 0.4, 3)]]
    # Copy: a WAV of it on the clipboard, made on a worker
    monkeypatch.setattr(splicepanel, "load_original", lambda meta: _ramp(10.0))
    monkeypatch.setattr(splicepanel.tempfile, "gettempdir", lambda: str(tmp_path))
    bar.copy(0)
    for _i in range(200):
        QApplication.processEvents()
        md = QApplication.clipboard().mimeData()
        urls = md.urls() if md is not None else []
        if urls:
            break
        QTest.qWait(20)
    assert urls and urls[0].toLocalFile().endswith(".wav")
    import soundfile as sf
    got, sr = sf.read(urls[0].toLocalFile())
    assert sr == SR and abs(len(got) / SR - L * 0.2) < 0.05
    d.close()


def test_a_right_drag_still_moves_along_when_zoomed(window, monkeypatch):  # noqa: F811
    d = _dialog(window, monkeypatch)
    wave = d.effects.trim.wave
    L = wave.length
    d.effects.trim.load(soundfx.clean({"splices": [[L * 0.2, L * 0.9]]}))
    wave.zoom(4.0, L * 0.5)
    v0 = wave.view[0]
    seen = []
    wave.menu_asked.connect(lambda i, at: seen.append(i))
    p = _at(wave, L * 0.5)
    QTest.mousePress(wave, RIGHT, NO, p)
    QTest.mouseMove(wave, p + QPoint(60, 0))
    QTest.mouseRelease(wave, RIGHT, NO, p + QPoint(60, 0))
    assert wave.view[0] < v0 and not seen          # moved along, no menu
    d.close()


def _drag(wave, a: QPoint, b: QPoint):
    QTest.mousePress(wave, LEFT, NO, a)
    QTest.mouseMove(wave, b)
    QTest.mouseRelease(wave, LEFT, NO, b)


def _pt(wave, t, level):
    return QPoint(round(wave._x(t)), round(wave._level_y(level)))


def test_level_points_drag_a_splices_fades_volume_and_the_sounds(
        window, monkeypatch):  # noqa: F811
    d = _dialog(window, monkeypatch)
    eff = d.effects
    wave = eff.trim.wave
    L = wave.length
    eff.trim.load(soundfx.clean({"splices": [[L * 0.3, L * 0.6]]}))
    a, b = L * 0.3, L * 0.6
    # the fade-in corner (on the line at the splice's start) dragged sideways: a fade,
    # its volume kept
    _drag(wave, _pt(wave, a, 1.0), _pt(wave, a + L * 0.05, 1.0))
    part = eff.fx()["parts"][0]
    assert abs(part["fade_in"] - L * 0.05) < L * 0.01 and "volume" not in part
    # ...then down to half: that corner's own level, nothing else
    _drag(wave, _pt(wave, a + L * 0.05, 1.0), _pt(wave, a + L * 0.05, 0.5))
    part = eff.fx()["parts"][0]
    assert abs(part["fade_in_to"] - 0.5) < 0.03 and abs(part["fade_in"] - L * 0.05) < L * 0.01
    assert "volume" not in part and "fade_out_from" not in part
    # the fade's start point (shown now, at silence) up: it starts from a quarter
    _drag(wave, _pt(wave, a, 0.0), _pt(wave, a, 0.25))
    assert abs(eff.fx()["parts"][0]["fade_in_from"] - 0.25) < 0.05
    # the fade-out corner, sideways from the end (still at full: the in corner's
    # level didn't move it)
    _drag(wave, _pt(wave, b, 1.0), _pt(wave, b - L * 0.1, 1.0))
    assert abs(eff.fx()["parts"][0]["fade_out"] - L * 0.1) < L * 0.01
    # ...then down to a fifth: the fade-in corner stays at half
    _drag(wave, _pt(wave, b - L * 0.1, 1.0), _pt(wave, b - L * 0.1, 0.2))
    part = eff.fx()["parts"][0]
    assert abs(part["fade_out_from"] - 0.2) < 0.03 and abs(part["fade_in_to"] - 0.5) < 0.03
    # the sound's own line: its fade in, sideways only (the Fades sliders follow)
    _drag(wave, _pt(wave, 0.0, 1.0), _pt(wave, 1.5, 1.0))
    assert abs(d.fades()[0] - 1.5) < 0.11
    assert wave.splices == [[round(a, 3), round(b, 3)]]   # nothing else moved
    d.close()


def test_a_splices_fade_start_level_is_heard():
    x = np.ones((2 * SR, 2), np.float32)
    y = soundfx.trim(x, {"splices": [[0, 1], [1, 2]], "joined": True,
                         "parts": [{"fade_in": 0.5, "fade_in_from": 0.5}, {}]})
    assert abs(abs(y[0]).max() - 0.5) < 0.02 and abs(abs(y[int(0.6 * SR)]).max() - 1) < 0.02


def test_a_splices_corners_have_their_own_levels_and_fades_can_meet():
    x = np.ones((30 * SR, 2), np.float32)
    part = {"fade_in": 12.0, "fade_out": 18.0, "fade_in_to": 0.5, "fade_out_from": 0.5}
    assert soundfx.clean_part(part) == part        # longer than a sound.s 10 s, kept
    y = soundfx.trim(x, {"splices": [[0, 30]], "joined": True, "parts": [part]})
    assert abs(y[0]).max() < 0.02                  # from silence
    assert abs(abs(y[12 * SR]).max() - 0.5) < 0.02  # up to the in corner's half
    assert abs(abs(y[12 * SR + 1]).max() - 0.5) < 0.02   # (they meet: no flat middle)
    assert abs(abs(y[-1]).max()) < 0.02            # down to silence at the end
    # no fades but a sloped middle: from the in corner's level to the out corner's
    y = soundfx.trim(x, {"splices": [[0, 30]], "joined": True,
                         "parts": [{"fade_in_to": 0.2, "fade_out_from": 1.0}]})
    assert abs(abs(y[0]).max() - 0.2) < 0.02 and abs(abs(y[-1]).max() - 1.0) < 0.02


def test_scrolling_zooms_the_big_waveform(window, monkeypatch):  # noqa: F811
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QWheelEvent
    d = _dialog(window, monkeypatch)
    wave = d.effects.trim.wave
    span = wave.view[1] - wave.view[0]
    pos = QPointF(wave.width() / 2, wave.height() / 2)
    ev = QWheelEvent(pos, wave.mapToGlobal(pos), QPoint(0, 0), QPoint(0, 120),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                     Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(wave, ev)
    assert wave.view[1] - wave.view[0] < span
    d.close()


def test_add_splices_on_a_click_in_a_splice_picks_it_and_fade_buttons_fade_it(
        window, monkeypatch):  # noqa: F811
    d = _dialog(window, monkeypatch)
    eff, bar = d.effects, d.adv.splices
    wave = eff.trim.wave
    L = wave.length
    eff.trim.load(soundfx.clean({"splices": [[L * 0.2, L * 0.6]]}))
    bar.cut.setChecked(True)                         # Add splices stays on
    assert all(b.isHidden() for b in bar.fades.values())
    QTest.mouseClick(wave, LEFT, NO, _at(wave, L * 0.4))
    assert wave.selected == 0 and wave._first is None   # picked, not a new splice
    assert len(wave.splices) == 1 and wave._env_points()  # its dots show
    fade_in, fade_out = bar.fades["fade_in"], bar.fades["fade_out"]
    assert fade_in.isVisible() and not fade_in.isChecked()
    fade_in.click()
    assert wave.part_fades(0) == (1.0, 0.0)
    fade_out.click()
    assert eff.fx()["parts"] == [{"fade_in": 1.0, "fade_out": 1.0}]
    fade_in.click()                                  # off again
    assert wave.part_fades(0) == (0.0, 1.0)
    QTest.keyClick(wave, Qt.Key.Key_Escape)          # the whole sound: buttons go
    assert fade_in.isHidden()
    QTest.mouseClick(wave, LEFT, NO, _at(wave, L * 0.8))   # outside: a new one starts
    assert wave._first is not None
    d.close()
