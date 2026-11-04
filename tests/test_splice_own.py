"""A splice's own settings: clicked on Edit sound's big waveform, the Speed & loudness,
Effects and Equalizer columns change just that splice (soundfx "parts", heard when
the splices play joined); its right-click menu plays it, saves it as a pad of its own
or copies it; and the fade grips along the top drag its fades (or the sound's)."""
import numpy as np
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from soundboard.audio import soundfx, volumeline
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
    assert soundfx.key({"splices": [[0, 1]]}) == ""
    assert soundfx.key({"splices": [[0, 1]], "parts": [{"speed": 2}]}) != ""


def test_a_splices_settings_play_where_it_is_and_nowhere_else():
    x = np.ones((6 * SR, 2), np.float32) * 0.5
    fx = {"splices": [[2, 4]], "parts": [{"speed": 2.0, "volume": 0.5}]}
    y = soundfx.trim(x, fx)
    assert abs(len(y) / SR - 5.0) < 0.01                  # 2 s + 1 s (2 s at 2x) + 2 s
    assert abs(abs(y[SR]).max() - 0.5) < 1e-3             # before it: as it was
    assert abs(abs(y[int(2.5 * SR)]).max() - 0.25) < 1e-3  # in it: its own
    assert abs(abs(y[int(4 * SR)]).max() - 0.5) < 1e-3    # after it: as it was
    # the playhead follows: the splice goes by at twice the speed
    assert abs(soundfx.time_at(fx, 6.0, 2.0 / 5) - 2.0) < 0.01
    assert abs(soundfx.time_at(fx, 6.0, 2.5 / 5) - 3.0) < 0.01
    assert abs(soundfx.frac_at(fx, 6.0, 5.0) - 4.0 / 5) < 0.01


def test_a_splice_in_place_stays_in_the_trim_and_the_order():
    f = soundfx.clean({"start": 1.0, "end": 9.0, "splices": [[6, 8], [0, 3], [2, 4]],
                       "parts": [{"pitch": 1}, {"pitch": 2}, {"pitch": 3}]})
    spans, parts = soundfx.in_place(f, 10.0)
    assert spans == [[1.0, 3.0], [3.0, 4.0], [4.0, 6.0], [6.0, 8.0], [8.0, 9.0]]
    assert [p.get("pitch") for p in parts] == [2.0, 3.0, None, 1.0, None]
    # a splice past the trim: nothing of it plays
    f = soundfx.clean({"end": 2.0, "splices": [[5, 6]], "parts": [{"pitch": 1}]})
    assert soundfx.in_place(f, 10.0) == ([[0.0, 2.0]], [{}])
    # one splice covering the whole sound
    f = soundfx.clean({"splices": [[0, 10]], "parts": [{"pitch": 1}]})
    assert soundfx.in_place(f, 10.0)[0] == [[0.0, 10.0]]


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


def _live_nightcore(w, eff):
    w.speed_btn.apply_preset("Nightcore")
    QApplication.processEvents()
    assert w.engine.sound_speed == 1.3 and abs(eff.speed.value() - 1.3) < 1e-6


def _plain_again(w, eff):
    QApplication.processEvents()
    assert w.engine.sound_speed == 1.0 and not w.engine.sound_fx
    assert abs(eff.speed.value() - 1.0) < 1e-6 and not eff.knob_values()
    assert not eff.panel.presets["Nightcore"].isChecked()
    assert w.speed_btn.text() == "1x"


def _edit(w, monkeypatch):
    from soundboard.ui.sounds import dialogs
    monkeypatch.setattr(dialogs, "original_length", lambda meta: 10.0)
    w.cfg.edit_advanced = True
    d = w.editctl.edit("s0")
    d.resize(1400, 900)
    d.show()
    QApplication.processEvents()
    return d


def test_none_takes_live_controls_off_the_sound_too(window, monkeypatch):  # noqa: F811
    """Nightcore in Live controls read as 1.30x under Preset: None, and None (already
    showing) did nothing: the song played on in Nightcore."""
    d = _edit(window, monkeypatch)
    eff = d.effects
    _live_nightcore(window, eff)
    assert eff.preset.currentData() == "Nightcore"
    eff.preset.setCurrentIndex(eff.preset.findData("None (original)"))
    eff.preset.activated.emit(eff.preset.currentIndex())
    _plain_again(window, eff)
    d.close()


def test_reset_takes_live_controls_off_the_sound_too(window, monkeypatch):  # noqa: F811
    d = _edit(window, monkeypatch)
    eff = d.effects
    _live_nightcore(window, eff)
    d.btn_reset.click()
    _plain_again(window, eff)
    d.close()


def test_a_preset_lit_by_live_controls_goes_off_there(window, monkeypatch):  # noqa: F811
    """Clicked off, it took Live controls' off the sound's own: 0.77x, Bass -3."""
    d = _edit(window, monkeypatch)
    eff = d.effects
    _live_nightcore(window, eff)
    QTest.mouseClick(eff.panel.presets["Nightcore"], LEFT)
    _plain_again(window, eff)
    assert eff.fx() == {} or soundfx.is_neutral(eff.fx())
    d.close()


def _splice_under_nightcore(w, monkeypatch):
    d = _edit(w, monkeypatch)
    eff = d.effects
    _live_nightcore(w, eff)
    wave = eff.trim.wave
    L = wave.length
    eff.trim.load(soundfx.clean({"splices": [[L * 0.2, L * 0.4]]}))
    QTest.mouseClick(wave, LEFT, NO, _at(wave, L * 0.3))
    assert eff.part == 0
    return d, eff, wave


def _main_track(eff):
    eff.trim.wave.pick(None)
    assert eff.part is None


def test_none_on_a_splice_leaves_the_rest_of_the_song_alone(window, monkeypatch):  # noqa: F811
    d, eff, wave = _splice_under_nightcore(window, monkeypatch)
    eff.preset.setCurrentIndex(eff.preset.findData("None (original)"))
    eff.preset.activated.emit(eff.preset.currentIndex())
    assert window.engine.sound_speed == 1.3 and window.engine.sound_fx == {"bass": 3}
    assert abs(eff.speed.value() - 1.0) < 1e-6 and not eff.knob_values()  # it reads plain...
    p = wave.parts[0]
    assert abs(p["speed"] * 1.3 - 1) < 1e-2 and p["tape"]                 # ...and sounds it
    assert p["live"] == [{"bass": -3}]
    _main_track(eff)                                 # Live off: nothing left of it on the splice
    eff.preset.setCurrentIndex(eff.preset.findData("None (original)"))
    eff.preset.activated.emit(eff.preset.currentIndex())
    _plain_again(window, eff)
    assert wave.parts[0] == {}
    d.close()


def test_a_splice_keeps_what_it_has_when_the_main_track_goes_plain(window, monkeypatch):  # noqa: F811
    d, eff, wave = _splice_under_nightcore(window, monkeypatch)
    eff.speed.set_value(1.5)                         # 1.5x and Bass +6, as it reads
    eff.panel.tuning_edited.emit()
    eff.knobs["bass"].set_value(6)
    eff.panel.knobs_edited.emit()
    assert window.engine.sound_speed == 1.3          # the splice's: Live controls don't move
    _main_track(eff)
    assert abs(eff.speed.value() - 1.3) < 1e-6       # the main track's Nightcore
    eff.preset.setCurrentIndex(eff.preset.findData("None (original)"))
    eff.preset.activated.emit(eff.preset.currentIndex())
    _plain_again(window, eff)
    p = wave.parts[0]
    assert abs(p["speed"] - 1.5) < 1e-2 and p["live"] == [{"bass": 6}]
    QTest.mouseClick(wave, LEFT, NO, _at(wave, wave.length * 0.3))
    assert abs(eff.speed.value() - 1.5) < 1e-2 and eff.knob_values() == {"bass": 6}
    d.close()


def test_a_preset_on_a_splice_isnt_stacked_on_live_controls(window, monkeypatch):  # noqa: F811
    """Nightcore from the list read 1.69x and Bass +6."""
    d, eff, wave = _splice_under_nightcore(window, monkeypatch)
    eff.preset.setCurrentIndex(eff.preset.findData("Slowed + reverb"))
    eff.preset.activated.emit(eff.preset.currentIndex())
    assert abs(eff.speed.value() - 0.8) < 1e-3 and eff.knob_values()["bass"] == 3
    d.close()


def test_a_preset_clicked_off_goes_back_to_this_splices_own(window, monkeypatch):  # noqa: F811
    d = _dialog(window, monkeypatch)
    eff = d.effects
    wave = eff.trim.wave
    L = wave.length
    eff.trim.load(soundfx.clean({"splices": [[L * 0.2, L * 0.4], [L * 0.6, L * 0.8]]}))
    QTest.mouseClick(wave, LEFT, NO, _at(wave, L * 0.3))
    eff.speed.set_value(0.5)                        # splice 1: slow, then the preset on
    eff._edited()
    QTest.mouseClick(eff.panel.presets["Nightcore"], LEFT)
    QTest.mouseClick(wave, LEFT, NO, _at(wave, L * 0.7))
    QTest.mouseClick(eff.panel.presets["Nightcore"], LEFT)   # splice 2: plain, on
    QTest.mouseClick(wave, LEFT, NO, _at(wave, L * 0.3))
    QTest.mouseClick(eff.panel.presets["Nightcore"], LEFT)   # splice 1: off
    assert abs(eff.speed.value() - 1.0) < 1e-6
    assert wave.parts[1].get("speed") == 1.3
    d.close()


def test_the_banner_follows_the_picked_splices_edge(window, monkeypatch):  # noqa: F811
    d = _dialog(window, monkeypatch)
    eff = d.effects
    wave = eff.trim.wave
    L = wave.length
    eff.trim.load(soundfx.clean({"splices": [[L * 0.2, L * 0.4]]}))
    QTest.mouseClick(wave, LEFT, NO, _at(wave, L * 0.3))
    was = d.adv.part_text.text()
    y = wave.height() // 2
    x = round(wave._x(L * 0.4))
    QTest.mousePress(wave, LEFT, NO, QPoint(x, y))
    QTest.mouseMove(wave, QPoint(x + 40, y))
    QTest.mouseRelease(wave, LEFT, NO, QPoint(x + 40, y))
    assert soundfx.fmt_s(wave.splices[0][1]) in d.adv.part_text.text()
    assert d.adv.part_text.text() != was
    d.close()


def test_reset_and_simples_chip_take_the_splices_effects_off(window, monkeypatch):  # noqa: F811
    from soundboard.ui.sounds import editsummary
    d = _dialog(window, monkeypatch)
    eff = d.effects
    keep = {"splices": [[2, 4]], "parts": [{"speed": 2.0}]}
    eff.load(keep)
    assert soundfx.key(eff.fx()) != ""                # it plays differently: not neutral
    (_text, off), = editsummary.items(eff)            # Simple shows it, with its ×
    off()
    assert eff.fx()["parts"] == [] and eff.fx()["splices"] == [[2.0, 4.0]]
    eff.load(keep)
    d.btn_reset.click()                               # nothing picked: every effect off
    assert eff.fx()["parts"] == [] and eff.fx()["splices"] == [[2.0, 4.0]]
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


def _dot(wave, what):
    """Where a point (or bend circle) is drawn: ("env" / "bend", line, k)."""
    pt = next(pt for pt, w in wave._env_points() if w == what)
    return QPoint(round(pt.x()), round(pt.y()))


def _line(wave, i):
    """Line i's points as (seconds into the sound, level), rounded."""
    return [(round(t, 2), round(lv, 2)) for t, lv, _c in wave._env(i)]


def test_a_splices_volume_line_works_like_an_automation_clip(
        window, monkeypatch):  # noqa: F811
    d = _dialog(window, monkeypatch)
    eff = d.effects
    wave = eff.trim.wave
    L = wave.length
    a, b = L * 0.3, L * 0.6
    eff.trim.load(soundfx.clean({"splices": [[a, b]]}))
    assert _line(wave, 0) == [(round(a, 2), 1.0), (round(b, 2), 1.0)]   # flat, full
    # a press on the line puts a point there, dragged at once: down to half
    t = a + L * 0.1
    _drag(wave, _pt(wave, t, 1.0), _pt(wave, t, 0.5))
    got = _line(wave, 0)
    assert len(got) == 3 and abs(got[1][0] - t) < 0.05 and abs(got[1][1] - 0.5) < 0.03
    # a point drags anywhere between its neighbours: left and up
    _drag(wave, _dot(wave, ("env", 0, 1)), _pt(wave, a + L * 0.05, 0.8))
    got = _line(wave, 0)
    assert abs(got[1][0] - (a + L * 0.05)) < 0.05 and abs(got[1][1] - 0.8) < 0.03
    # the line's end: only up and down (the splice's edge stays where it is)
    _drag(wave, _dot(wave, ("env", 0, 2)), _pt(wave, b - L * 0.1, 0.0))
    got = _line(wave, 0)
    assert got[-1] == (round(b, 2), 0.0)
    part = eff.fx()["parts"][0]   # (older versions read its fades)
    assert abs(part["fade_out"] - (b - a - L * 0.05)) < 0.06 and part["line"]
    # the circle half way down that slope, dragged up: a curve that holds up longer
    mid = (got[1][0] + got[2][0]) / 2
    straight = wave._env(0)
    _drag(wave, _dot(wave, ("bend", 0, 1)), _dot(wave, ("bend", 0, 1)) - QPoint(0, 40))
    bent = wave._env(0)
    assert bent[1][2] > 0 and [p[:2] for p in bent] == [p[:2] for p in straight]
    assert soundfx.trim(np.ones((int(L * SR), 2), np.float32),
                        dict(eff.fx(), joined=True))[int((mid - a) * SR)].max() > 0.45
    # a click on the line just beside that circle: a point, not the curve
    near = wave._t(_dot(wave, ("bend", 0, 1)).x() + 8)
    env = wave._env(0)
    lv = volumeline.level_at([[t - a, h, c] for t, h, c in env], near - a)
    n = len(env)
    QTest.mouseClick(wave, LEFT, NO, _pt(wave, near, lv))
    assert len(wave._env(0)) == n + 1 and wave._env(0)[1][2] == bent[1][2]
    _drag_back = wave._env(0)
    del _drag_back[2]
    wave._set_env(0, _drag_back)   # (that point off again: the rest as it was)
    # the start: a point up from it, then the start itself down to silence
    _drag(wave, _dot(wave, ("env", 0, 0)), _pt(wave, a + 1.0, 0.0))
    assert _line(wave, 0)[0] == (round(a, 2), 0.0)
    # right-click a point: Delete point
    n = len(wave._env(0))
    QTest.mouseClick(wave, RIGHT, NO, _dot(wave, ("env", 0, 1)))
    menu = wave._menu
    assert menu is not None and [x.text() for x in menu.actions()] == ["Delete point"]
    menu.actions()[0].trigger()
    menu.close()
    assert len(wave._env(0)) == n - 1
    d.close()


def test_the_sounds_volume_line_sliders_knobs_undo_and_save(window, monkeypatch):  # noqa: F811
    seen = []
    d = _dialog(window, monkeypatch, lambda *a: seen.append(a[3]))
    wave = d.effects.trim.wave
    L = wave.length
    assert d.volume_line == [] and len(wave._env(-1)) == 2
    # the trim handles' grips sit at the bottom, under the line's ends
    knob = QPoint(round(wave._x(L)), wave.height() - 12)
    assert wave._on_knob(knob.x(), knob.y())
    assert not wave._on_knob(*(lambda q: (q.x(), q.y()))(_dot(wave, ("env", -1, 1))))
    # a point at 6 s, then the end down to silence: a 4 s fade out (the slider follows)
    _drag(wave, _pt(wave, 6.0, 1.0), _pt(wave, 6.0, 1.0))
    _drag(wave, _dot(wave, ("env", -1, 2)), _pt(wave, L, 0.0))
    assert len(d.volume_line) == 3 and abs(d.fades()[1] - 4.0) < 0.15
    # the Fade out slider moves that point
    d.fade_out.setValue(20)
    assert abs(wave._env(-1)[1][0] - (L - 2.0)) < 0.02 and d.fades()[1] == 2.0
    # ...and Fade in puts a fade in on the same line
    d.fade_in.setValue(10)
    got = _line(wave, -1)
    assert got[0] == (0.0, 0.0) and got[1][0] == 1.0 and got[-1] == (round(L, 2), 0.0)
    # the end handle's grip trims, the fade out goes with it
    _drag(wave, knob, QPoint(round(wave._x(L - 1.0)), knob.y()))
    assert abs(wave.end - (L - 1.0)) < 0.1
    got = _line(wave, -1)
    assert abs(got[-2][0] - (wave.end - 2.0)) < 0.05 and got[-1][1] == 0.0
    # previews play it, Undo takes it back, Save keeps it
    d.btn_preview.click()
    assert seen and seen[-1][2] == d.volume_line
    want = [list(pt) for pt in d.volume_line]
    d._flush()
    d.undo()
    assert d.volume_line != want
    d.redo()
    assert d.volume_line == want
    m = d.meta
    d.apply()
    assert m.volume_line == want and m.fade_out == 2.0
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
    got = eff.fx()["parts"][0]
    assert (got["fade_in"], got["fade_out"]) == (1.0, 1.0) and got["line"]
    fade_in.click()                                  # off again
    assert wave.part_fades(0) == (0.0, 1.0)
    QTest.keyClick(wave, Qt.Key.Key_Escape)          # the whole sound: buttons go
    assert fade_in.isHidden()
    QTest.mouseClick(wave, LEFT, NO, _at(wave, L * 0.8))   # outside: a new one starts
    assert wave._first is not None
    d.close()
