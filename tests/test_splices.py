"""Splices: parts of a sound marked with two clicks each on Edit sound's big waveform,
listed in the Splices pop-up, and joined to play back to back (soundfx.join). The
plain trim works as before for anyone who never makes one, and the settings load in
older versions (start / end span the joined splices)."""
import numpy as np
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from soundboard.audio import soundfx
from soundboard.audio.engine import SR
from soundboard.ui.sounds.dialogs import EditDialog
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)

LEFT = Qt.MouseButton.LeftButton
NO = Qt.KeyboardModifier.NoModifier


def _ramp(seconds: float) -> np.ndarray:
    """(n, 2) float32 whose value is its own time in seconds: easy to check cuts."""
    t = (np.arange(int(seconds * SR)) / SR).astype(np.float32)
    return np.stack([t, t], axis=1)


# ------------------------------------------------------------------ the settings

def test_clean_keeps_good_splices_and_drops_the_rest():
    f = soundfx.clean({"splices": [[1, 2], [3.5, 3], "x", [1, 1.01], [float("nan"), 2],
                                   [-1, 0.5]], "joined": True})
    assert f["splices"] == [[1.0, 2.0], [3.0, 3.5], [0.0, 0.5]]
    assert f["joined"]
    assert soundfx.clean({"splices": [[0, 1]] * 50})["splices"] == [[0.0, 1.0]] * 20
    assert not soundfx.clean({"joined": True})["joined"]    # nothing to join
    assert soundfx.clean({})["splices"] == [] and not soundfx.clean({})["joined"]


def test_marked_splices_change_nothing_that_plays():
    """Only joined splices play: marks alone keep the sound (and its cache) as it was."""
    plain = {"speed": 1.5}
    marked = {**plain, "splices": [[1, 2], [3, 4]]}
    assert soundfx.key(marked) == soundfx.key(plain)
    assert soundfx.is_neutral({"splices": [[1, 2]]})
    joined = {**marked, "joined": True}
    assert soundfx.key(joined) != soundfx.key(plain)
    assert not soundfx.is_neutral({"splices": [[1, 2]], "joined": True})
    assert "2 splices joined" in soundfx.summary(joined)


def test_joined_splices_play_back_to_back_in_their_order():
    x = _ramp(6.0)
    fx = {"splices": [[4, 5], [1, 2]], "joined": True}
    y = soundfx.trim(x, fx)
    assert len(y) == 2 * SR
    assert abs(y[SR // 2, 0] - 4.5) < 1e-3 and abs(y[SR + SR // 2, 0] - 1.5) < 1e-3
    # the joins ramp in and out (no click); the ends stay as cut
    assert abs(y[SR - 1, 0]) < 0.01 and abs(y[SR, 0]) < 0.01
    assert abs(y[0, 0] - 4.0) < 1e-3 and abs(y[-1, 0] - 2.0) < 1e-3
    out = soundfx.render(x, {**fx, "gain_db": 0.0})
    assert len(out) == 2 * SR
    # int16 in, int16 out (the cache's samples)
    assert soundfx.trim((x * 1000).astype(np.int16), fx).dtype == np.int16


def test_a_preview_part_starts_from_the_joined_splices():
    x = _ramp(6.0)
    part, fx = soundfx.preview_part(x, {"splices": [[4, 5], [1, 2]], "joined": True}, 1.5)
    assert abs(part[0, 0] - 4.0) < 1e-3 and not fx["joined"] and not fx["splices"]


def test_an_older_version_plays_the_span():
    """An older version drops the keys it doesn't know: start / end are what's left."""
    saved = {"start": 1.0, "end": 5.0, "splices": [[4, 5], [1, 2]], "joined": True}
    old = {k: v for k, v in saved.items() if k not in ("splices", "joined")}
    assert len(soundfx.trim(_ramp(6.0), old)) == 4 * SR


# ------------------------------------------------------------------ the window

def _dialog(w, monkeypatch, preview=None):
    """Advanced, on a 10 s sound (the test board's are a tenth of a second: too short
    for two splices)."""
    from soundboard.ui.sounds import dialogs
    monkeypatch.setattr(dialogs, "original_length", lambda meta: 10.0)
    m = w.meta("s0")
    m.fx = {}
    d = EditDialog(m, w.hotkeys, preview or (lambda *a: None), w, advanced=True)
    d.show()
    QApplication.processEvents()
    return d


def _click(wave, t: float):
    x = round(wave._x(t))
    y = wave.height() // 2
    QTest.mouseMove(wave, QPoint(x, y))
    QTest.mouseClick(wave, LEFT, NO, QPoint(x, y))


def test_clicks_work_the_handles_until_add_splices_is_on(window, monkeypatch):  # noqa: F811
    d = _dialog(window, monkeypatch)
    trim = d.effects.trim
    wave = trim.wave
    L = wave.length
    _click(wave, L * 0.3)                       # as before: the nearer handle moves there
    assert abs(wave.start - L * 0.3) < L * 0.01 and not wave.splices
    d.adv.splices.cut.click()
    assert wave.cutting
    _click(wave, L * 0.5)
    _click(wave, L * 0.6)
    assert len(wave.splices) == 1 and abs(wave.start - L * 0.3) < L * 0.01   # handles kept
    a, b = wave.splices[0]
    assert abs(a - L * 0.5) < L * 0.01 and abs(b - L * 0.6) < L * 0.01
    _click(wave, L * 0.9)                       # the next two clicks: splice 2, either way
    _click(wave, L * 0.7)
    assert len(wave.splices) == 2 and wave.splices[1][0] < wave.splices[1][1]
    assert d.adv.splices.list.text() == "Splices (2)"
    # Esc lets go of a half-made splice, not the window
    _click(wave, L * 0.1)
    QTest.keyClick(wave, Qt.Key.Key_Escape)
    assert wave._first is None and d.isVisible() and len(wave.splices) == 2
    # marks are saved with the sound but don't change what plays
    fx = d.effects.fx()
    assert len(fx["splices"]) == 2 and not fx["joined"]
    assert soundfx.key(fx) == soundfx.key({"start": fx["start"], "end": fx["end"]})
    d.close()


def test_hover_names_the_splice_and_its_edges_drag(window, monkeypatch):  # noqa: F811
    d = _dialog(window, monkeypatch)
    wave = d.effects.trim.wave
    L = wave.length
    d.adv.splices.cut.click()
    _click(wave, L * 0.2)
    _click(wave, L * 0.4)
    QTest.mouseMove(wave, QPoint(round(wave._x(L * 0.3)), wave.height() // 2))
    assert wave._hover == 0
    QTest.mouseMove(wave, QPoint(round(wave._x(L * 0.6)), wave.height() // 2))
    assert wave._hover is None
    y = wave.height() // 2
    QTest.mousePress(wave, LEFT, NO, QPoint(round(wave._x(L * 0.4)), y))   # its end edge
    QTest.mouseMove(wave, QPoint(round(wave._x(L * 0.5)), y))
    QTest.mouseRelease(wave, LEFT, NO, QPoint(round(wave._x(L * 0.5)), y))
    assert len(wave.splices) == 1 and abs(wave.splices[0][1] - L * 0.5) < L * 0.01
    d.close()


def test_the_pop_up_plays_removes_and_combines(window, monkeypatch):  # noqa: F811
    played = []

    def preview(sid, vol, fx, fades, done):
        played.append(fx)
        return "playing"
    d = _dialog(window, monkeypatch, preview)
    trim, bar = d.effects.trim, d.adv.splices
    wave = trim.wave
    L = wave.length
    bar.cut.click()
    for a, b in ((0.1, 0.2), (0.5, 0.6), (0.3, 0.4)):
        _click(wave, L * a)
        _click(wave, L * b)
    bar.list.click()
    pop = bar.popup
    assert pop.isVisible() and len(pop._row_widgets) == 3
    assert pop.empty.isHidden() and not pop.combine.isHidden() and pop.split.isHidden()
    play = pop._row_widgets[1].findChildren(type(pop.combine))[0]
    play.click()                                     # splice 2, on its own
    got = soundfx.clean(played[-1])
    assert abs(got["start"] - L * 0.5) < L * 0.01 and abs(got["end"] - L * 0.6) < L * 0.01
    assert got["joined"] and len(got["splices"]) == 1   # (with its own settings)
    trim.show_playing(0.5, {})                       # its playhead: inside splice 2
    assert L * 0.5 < wave.play < L * 0.6
    pop.combine.click()                              # asks: a new pad, or this one
    dlg = bar.dlg
    assert dlg is not None and dlg.isVisible() and not pop.isVisible()
    dlg.reject()                                     # Cancel: nothing changes
    QApplication.processEvents()
    assert not d.effects.fx()["joined"] and d.isVisible()
    trim.set_joined(True)                            # (what both choices do first)
    bar.list.click()
    fx = d.effects.fx()
    assert fx["joined"] and len(fx["splices"]) == 3
    assert abs(fx["start"] - L * 0.1) < L * 0.01 and abs(fx["end"] - L * 0.6) < L * 0.01
    assert not pop.split.isHidden() and pop.combine.isHidden()
    assert trim.box_start.isHidden()                 # the splices say what plays now
    trim.show_playing(0.5, fx)                       # half way: the middle of splice 2
    assert abs(wave.play - L * 0.55) < L * 0.02
    d._flush()                                       # (each step its own undo)
    drop = pop._row_widgets[0].findChildren(type(pop.combine))[1]
    drop.click()                                     # remove splice 1
    assert len(wave.splices) == 2 and len(pop._row_widgets) == 2
    d.undo()                                         # and it's back
    assert len(d.effects.trim.wave.splices) == 3
    pop.split.click()
    assert not d.effects.fx()["joined"] and not trim.box_start.isHidden()
    pop.close()
    d.close()


def test_joined_splices_are_saved_and_load_again(window, monkeypatch):  # noqa: F811
    d = _dialog(window, monkeypatch)
    trim = d.effects.trim
    L = trim.wave.length
    trim.load(soundfx.clean({"splices": [[L * 0.1, L * 0.2], [L * 0.5, L * 0.6]],
                             "joined": True}))
    assert d.adv.splices.list.text() == "Splices (2)"
    fx = d.effects.fx()
    d.close()
    m = window.meta("s0")
    m.fx = fx
    d2 = EditDialog(m, window.hotkeys, lambda *a: None, window)   # Simple: shown, joined
    assert d2.effects.trim.wave.joined and len(d2.effects.trim.wave.splices) == 2
    assert d2.effects.fx() == fx
    d2.close()


def test_combine_saves_as_a_new_pad_or_over_this_one(window, monkeypatch):  # noqa: F811
    for choice in ("new", "replace"):
        d = _dialog(window, monkeypatch)
        trim, bar = d.effects.trim, d.adv.splices
        L = trim.wave.length
        trim.load(soundfx.clean({"splices": [[L * 0.1, L * 0.2], [L * 0.5, L * 0.6]]}))
        bar.ask_combine()
        dlg = bar.dlg
        assert dlg.windowTitle() == "Combine 2 splices"
        assert dlg.name.text().endswith("(splices)")
        if choice == "new":
            dlg.name.setText("Just the drop")
        name = d.name.text()
        dlg._pick(choice)
        QApplication.processEvents()
        assert d.result() == d.DialogCode.Accepted and not d.isVisible()
        assert d.effects.fx()["joined"]
        assert d.as_copy == (choice == "new")
        assert d.name.text() == ("Just the drop" if choice == "new" else name)
