"""Edit sound's Advanced view (ui/sounds/editadvanced.py): the same draft as the Simple
tabs, the trim big on top, three columns or tabs, only the effects that are on (Add
effect brings in more), Undo / Redo, and the switch remembered."""
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QKeySequence, QShortcut, QWheelEvent
from PySide6.QtWidgets import QApplication, QPushButton, QScrollArea

from soundboard.ui.sounds import editadvanced
from soundboard.ui.sounds.dialogs import ADV_MIN_H, EditDialog
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)

FX = {"speed": 1.2, "gain_db": 3.0, "effects": {"echo": {"on": True}}}


def _dialog(w, sid="s0", **kw):
    m = w.meta(sid)
    m.fx = dict(FX)
    return EditDialog(m, w.hotkeys, lambda *a: None, w, **kw)


def _visible_pages(d):
    """The tab pages Qt would draw (only the current one may be)."""
    return [d.tabs.widget(i) for i in range(d.tabs.count()) if d.tabs.widget(i).isVisibleTo(d)]


def test_switching_keeps_the_draft_and_gives_everything_back(window):  # noqa: F811
    d = _dialog(window, tab="trim")
    d.show()
    before = d.effects.fx()
    d.switch.advanced.click()
    assert d.advanced() and d.tabs.isHidden() and not d.adv.isHidden()
    trim = d.effects.trim
    assert d.effects.trim_layout is d.adv.trim_box and trim.wave.big
    assert d.effects.fx() == before                     # nothing lost on the way
    d.adv.switch.simple.click()
    assert not d.advanced() and not d.tabs.isHidden()
    assert d.minimumWidth() == d._simple_min_w()       # Simple's own size limits again
    assert d.tabs.currentIndex() == 1                   # back on the tab it left
    assert [d.tabs.tabText(i) for i in range(d.tabs.count())] == [
        "Sound", "Trim && speed", "Effects", "Equalizer"]
    assert d.effects.trim_layout is d.effects._v and not trim.wave.big
    assert d.effects.trim_page.layout().indexOf(trim) >= 0
    d.tabs.setCurrentIndex(1)
    assert _visible_pages(d) == [d.tabs.widget(1)]     # not three pages over each other
    assert all(r.isVisibleTo(d.effects.fx_page) for r in d.effects.rows.values())
    assert d.effects.fx() == before
    d.close()


def test_wide_has_three_columns_narrow_three_tabs(window):  # noqa: F811
    d = _dialog(window, advanced=True)
    d.show()
    d.setFixedSize(2400, 820)   # (CI's text, without its fonts, is wide boxes)
    assert d.adv.wide and not d.adv.cols.isHidden() and d.adv.tabs.isHidden()
    assert all(isinstance(box.itemAt(box.count() - 1).widget(), QScrollArea)
               for box in d.adv.col_boxes)
    QApplication.processEvents()
    # each column as wide as its page: none scrolls sideways, cut off
    assert all(s.horizontalScrollBar().maximum() == 0 for s in d.adv._scrolls)
    assert not d.adv.fits(editadvanced.WIDE_PX - 1)
    need = d.minimumSizeHint().width()
    assert d.adv.fits(max(need, editadvanced.WIDE_PX)) and not d.adv.fits(need - 40)
    d.setFixedSize(760, 820)
    assert not d.adv.wide and d.adv.cols.isHidden() and d.adv.tabs.count() == 3
    d.show_tab("eq")
    assert d.adv.tabs.currentIndex() == 2
    d.close()


def test_a_short_screen_still_fits(window):  # noqa: F811
    """The big waveform gives up room on a short screen (1280 x 720): the window's
    least height holds everything, nothing squeezed over anything else."""
    d = _dialog(window, advanced=True)
    d.show()
    d.setFixedSize(2400, 624)
    QApplication.processEvents()
    assert d.minimumSizeHint().height() <= ADV_MIN_H
    assert all(s.viewport().height() >= 100 for s in d.adv._scrolls)
    d.close()


def test_the_choice_is_remembered(window):  # noqa: F811
    d = window.editctl.edit("s0")
    d.switch.advanced.click()
    assert window.cfg.edit_advanced is True
    d.reject()
    d2 = window.editctl.edit("s1")    # the closed one, reused, or a new one: Advanced
    assert d2.advanced()
    d2.adv.switch.simple.click()
    assert window.cfg.edit_advanced is False
    d2.reject()


def test_only_the_effects_on_and_add_effect(window):  # noqa: F811
    d = _dialog(window, advanced=True)
    d.show()
    eff = d.effects
    shown = [t for t, r in eff.rows.items() if r.isVisibleTo(eff.fx_page)]
    assert shown == ["echo"] and eff.add_effect.isVisibleTo(eff.fx_page)
    eff.add_effect.click()
    pk = d.adv.picker
    assert pk.isVisible() and pk.tiles["echo"].isChecked()
    pk.tiles["reverb"].click()                         # on, and in the list
    assert eff.rows["reverb"].chk.isChecked() and eff.rows["reverb"].isVisibleTo(eff.fx_page)
    assert "reverb" in d.effects.fx()["effects"]
    pk.close()
    eff.add_effect.click()
    pk.search.setText("echo")                          # the search narrows the tiles
    assert pk.tiles["echo"].isVisibleTo(pk) and not pk.tiles["robot"].isVisibleTo(pk)
    pk.search.setText("zzzz")
    assert pk.nothing.isVisibleTo(pk)
    pk.close()
    d.close()


def test_nothing_on_shows_the_knobs_and_add_effect(window):  # noqa: F811
    m = window.meta("s0")
    m.fx = {}
    d = EditDialog(m, window.hotkeys, lambda *a: None, window, advanced=True)
    d.show()
    eff = d.effects
    assert not any(r.isVisibleTo(eff.fx_page) for r in eff.rows.values())
    assert eff.add_effect.isVisibleTo(eff.fx_page)
    assert all(k.isVisibleTo(eff.fx_page) for k in eff.knobs.values())
    d.close()


def test_undo_and_redo(window):  # noqa: F811
    d = _dialog(window)
    first = d.effects.fx()
    d.effects.speed.set_value(1.5)
    d.effects.speed.changed.emit()
    d.fade_in.setValue(12)
    d.undo()                                           # the pending step is kept first
    assert d.effects.fx() == first and d.fade_in.value() == 0
    d.redo()
    assert d.effects.fx()["speed"] == 1.5 and d.fade_in.value() == 12
    d.undo()
    d.undo()                                           # nothing further back: no change
    assert d.effects.fx() == first
    # the system's keys: Ctrl+Z, and Ctrl+Shift+Z / Ctrl+Y
    keys = {s.key().toString() for s in d.findChildren(QShortcut)}
    assert "Ctrl+Z" in keys and ("Ctrl+Y" in keys or "Ctrl+Shift+Z" in keys)
    assert {QKeySequence(QKeySequence.StandardKey.Undo).toString(),
            QKeySequence(QKeySequence.StandardKey.Redo).toString()} <= keys
    d.close()


def test_a_drag_is_one_undo_step(window):  # noqa: F811
    d = _dialog(window)
    first = d.effects.fx()
    for v in (1.3, 1.4, 1.5, 1.6):                     # quick changes: one step
        d.effects.speed.set_value(v)
        d.effects.speed.changed.emit()
    d.undo()
    assert d.effects.fx() == first
    d.close()


def test_preset_and_voice_boxes_line_up(window):  # noqa: F811
    d = _dialog(window, tab="effects")
    d.show()
    QApplication.processEvents()
    eff = d.effects
    x = [w.mapTo(d, QPoint(0, 0)).x() for w in (eff.preset, eff.voice)]
    assert x[0] == x[1]
    d.close()


def test_the_big_waveform_zooms(window):  # noqa: F811
    d = _dialog(window, advanced=True)
    d.show()
    wave = d.effects.trim.wave
    assert wave.big and not wave.zoomed()
    d.adv.btn_in.click()
    assert wave.zoomed() and abs((wave.view[1] - wave.view[0]) - wave.length / 2) < 1e-6
    for _ in range(10):
        d.adv.btn_in.click()                           # no further than MAX_ZOOM
    assert wave.view[1] - wave.view[0] >= wave.length / 16 - 1e-6
    t = (wave.view[0] + wave.view[1]) / 2               # x and time agree when zoomed
    assert abs(wave._t(wave._x(t)) - t) < 1e-3
    d.adv.btn_fit.click()
    assert not wave.zoomed()
    ev = QWheelEvent(QPointF(wave.width() / 2, 50), QPointF(), QPoint(), QPoint(0, 120),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier,
                     Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(wave, ev)
    assert wave.zoomed()
    d.close()


def test_another_sound_in_advanced_keeps_the_big_trim(window):  # noqa: F811
    d = _dialog(window, advanced=True)
    d.show()
    d.load(window.meta("s1"))
    trim = d.effects.trim
    assert d.adv.trim_box.indexOf(trim) >= 0 and trim.wave.big
    d.adv.switch.simple.click()
    assert d.effects.trim_page.layout().indexOf(trim) >= 0 and not trim.wave.big
    d.close()


def test_zoomed_columns_stop_at_the_view(window):  # noqa: F811
    """The last column was the loudest of the whole rest of the sound when zoomed in."""
    import numpy as np
    from soundboard.ui.sounds.trim import Waveform
    fine = np.zeros(1000, np.float32)
    fine[900:] = 1.0                                   # loud only near the end
    w = Waveform([], 10.0)
    w.set_big(True)
    w.set_fine(fine)
    w.view = (0.0, 5.0)                                # the quiet first half
    assert w._columns(50).max() == 0.0
    w.view = (0.0, 10.0)
    assert w._columns(50)[-1] == 1.0


def test_live_controls_knobs_show_and_edit_the_sounds_live_stage(window):  # noqa: F811
    """Live controls' knobs in Advanced's Effects column: a pad saved from Live controls
    shows its knobs (stages merged), opening it changes nothing, and a knob moved makes
    them one stage, keeping the volume they were saved with."""
    m = window.meta("s0")
    m.fx = {"live": [{"bass": 6.0, "volume": 200.0}, {"bass": 3.0, "reverb": 0.4}]}
    d = EditDialog(m, window.hotkeys, lambda *a: None, window, advanced=True)
    d.show()
    eff = d.effects
    before = eff.fx()
    assert eff.knobs["bass"].value() == 9.0 and abs(eff.knobs["reverb"].value() - 0.4) < 1e-6
    assert not eff.live_row.isVisibleTo(eff.fx_page)   # the knobs stand in for it
    assert eff.fx() == before
    eff.knobs["echo"].set_value(0.5)
    eff.knobs["echo"].changed.emit()
    assert eff.fx()["live"] == [{"bass": 9.0, "reverb": 0.4, "echo": 0.5, "volume": 200.0}]
    d.adv.switch.simple.click()
    assert eff.live_row.isVisibleTo(eff.fx_page)        # Simple: the row, as before
    assert not eff.live_box.isVisibleTo(eff.fx_page)
    d.close()


def test_a_preset_saves_what_live_controls_saves(window):  # noqa: F811
    """Nightcore in Advanced is Nightcore in Live controls: what a pad saved from Live
    controls with it on plays (here as tape, a plain resample), and clicked again it's
    gone."""
    from soundboard.audio import livefx, soundfx
    m = window.meta("s0")
    m.fx = {}
    d = EditDialog(m, window.hotkeys, lambda *a: None, window, advanced=True)
    d.show()
    eff = d.effects
    b = eff.fx_presets["Nightcore"]
    b.click()
    assert b.isChecked() and not eff.keep.isChecked()
    p = livefx.PRESETS["Nightcore"]
    live, _capped = soundfx.with_live({}, *livefx.tuning(p), livefx.clean(p))
    got = eff.fx()
    assert got["live"] == live["live"] and got["speed"] == live["speed"]

    def ratio(f):   # how far up it ends (pitch and speed together): the same sound
        return 2 ** (f["pitch"] / 12) * (f["speed"] if f["tape"] else 1)
    assert abs(ratio(got) - ratio(live)) < 1e-3
    assert eff.pitch_note.isVisibleTo(eff.trim_page)    # +4.5 st from the speed
    b.click()
    assert not b.isChecked() and eff.fx() == {}
    d.close()


def test_speed_and_volume_quick_buttons(window):  # noqa: F811
    """Live controls' quick buttons: speeds under Speed, volumes under Volume (the
    Sound tab's, moved here from the top line). Simple keeps its own volume."""
    d = _dialog(window, advanced=True)
    d.show()
    eff = d.effects
    speeds = {b.text(): b for b in eff.speed_quick.findChildren(QPushButton)}
    speeds["0.75x"].click()
    assert eff.fx()["speed"] == 0.75
    vols = {b.text(): b for b in eff.volume_quick.findChildren(QPushButton)}
    vols["150%"].click()
    assert d.vol.value() == 150
    d.vol.setValue(80)
    assert eff.volume.value() == 80
    eff.keep.setChecked(False)
    assert eff.fx()["tape"] is True                     # keep pitch off = tape
    d.adv.switch.simple.click()
    assert not any(w.isVisibleTo(eff.trim_page)
                   for w in (eff.speed_quick, eff.volume, eff.volume_quick))
    d.close()


def test_the_preset_box_counts_the_knobs(window):  # noqa: F811
    """A knob up isn't "None (original)", and picking a preset (or its Reset) takes the
    knobs back off: back to plain in one click."""
    m = window.meta("s0")
    m.fx = {}
    d = EditDialog(m, window.hotkeys, lambda *a: None, window, advanced=True)
    d.show()
    eff = d.effects
    first = eff.preset.currentData()
    eff.knobs["reverb"].set_value(0.5)
    eff.knobs["reverb"].changed.emit()
    assert eff.preset.currentData() != first
    eff.preset.setCurrentIndex(0)
    assert eff.fx() == {} and eff.knobs["reverb"].value() == 0
    d.close()


def test_an_effect_on_doesnt_move_the_columns(window):  # noqa: F811
    """The "Effects: ..." line under the columns keeps its room while empty: switching
    an effect on showed it, the columns lost its height and their scroll bars flashed."""
    m = window.meta("s0")
    m.fx = {}
    d = EditDialog(m, window.hotkeys, lambda *a: None, window, advanced=True)
    d.show()
    d.setFixedSize(1500, 1000)
    QApplication.processEvents()
    def bars():
        return [(s.verticalScrollBar().isVisible(), s.horizontalScrollBar().isVisible())
                for s in d.adv._scrolls]
    before, high = bars(), [s.viewport().height() for s in d.adv._scrolls]
    d.effects.fx_presets["Nightcore"].click()
    QApplication.processEvents()
    assert bars() == before
    assert all(abs(s.viewport().height() - h) <= 1 for s, h in zip(d.adv._scrolls, high))
    d.close()
