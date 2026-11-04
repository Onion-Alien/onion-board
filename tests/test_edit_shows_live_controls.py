"""Edit sound shows Live controls' speed, pitch and knobs on top of the sound's own, as
Live controls show the playing sound's own on top of theirs. On the main track what they
have on is theirs: moved there, Live controls move, and the sound's own stays as it was."""
import pytest
from test_mainwindow import window  # noqa: F401

from soundboard.audio import soundfx
from soundboard.ui.sounds import editsummary
from soundboard.ui.sounds.dialogs import EffectsPanel


def test_nightcore_in_live_controls_shows_in_edit_sound(window):  # noqa: F811
    window.meta("s0").fx = {}
    window.speed_btn.fx_presets["Nightcore"].click()       # 1.3x, Bass +3
    d = window.editctl.edit("s0", "effects")
    eff = d.effects
    assert eff.speed.value() == pytest.approx(1.3) and not eff.keep.isChecked()
    assert eff.knob_values() == {"bass": 3}
    assert eff.fx_presets["Nightcore"].isChecked()
    assert eff.fx() == {} and editsummary.items(eff) == []    # nothing of the sound's own

    window.speed_btn.reset()                                 # Live controls off: plain again
    assert eff.speed.value() == pytest.approx(1.0) and eff.keep.isChecked()
    assert not eff.fx_presets["Nightcore"].isChecked()
    d.done(0)


def _nightcore_edit(window):  # noqa: F811
    window.meta("s0").fx = {}
    window.speed_btn.fx_presets["Nightcore"].click()
    d = window.editctl.edit("s0", "effects")
    return d, d.effects, window.engine


def test_bringing_nightcore_back_by_hand_leaves_the_sound_plain(window):  # noqa: F811
    """1.00x and Bass 0 saved 0.769x and Bass -3 on the sound: normal speed, pitched up."""
    d, eff, e = _nightcore_edit(window)
    eff.speed.set_value(1.0)
    eff.panel.tuning_edited.emit()
    assert e.sound_speed == pytest.approx(1.0) and e.sound_fx == {"bass": 3}
    assert window.speed_btn.speed.value() == pytest.approx(1.0)
    eff.knobs["bass"].set_value(0)
    eff.panel.knobs_edited.emit()
    assert e.sound_fx == {} and abs(eff.speed.value() - 1.0) < 1e-6
    assert window.speed_btn.text() == "1x"
    assert soundfx.is_neutral(eff.fx())
    d.done(0)


def test_every_other_way_to_plain_leaves_it_plain_too(window):  # noqa: F811
    for go in (lambda d, eff: eff.panel.presets["Nightcore"].click(),
               lambda d, eff: d.btn_reset.click(),
               lambda d, eff: (eff.preset.setCurrentIndex(eff.preset.findData("None (original)")),
                               eff.preset.activated.emit(eff.preset.currentIndex()))):
        d, eff, e = _nightcore_edit(window)
        assert eff.preset.currentData() == "Nightcore"       # reads what it sounds like
        go(d, eff)
        assert e.sound_speed == pytest.approx(1.0) and e.sound_fx == {}
        assert abs(eff.speed.value() - 1.0) < 1e-6 and not eff.knob_values()
        assert soundfx.is_neutral(eff.fx()) and eff.preset.currentData() == "None (original)"
        d.done(0)


def test_what_live_controls_dont_have_on_goes_to_the_sounds_own(window):  # noqa: F811
    d, eff, e = _nightcore_edit(window)
    eff.knobs["reverb"].set_value(0.3)
    eff.panel.knobs_edited.emit()
    assert eff.fx()["live"] == [{"reverb": pytest.approx(0.3)}]
    assert e.sound_speed == pytest.approx(1.3) and e.sound_fx == {"bass": 3}
    d.done(0)


def test_the_sounds_own_stays_when_live_controls_move(window):  # noqa: F811
    window.meta("s0").fx = {"speed": 1.2, "pitch": 2.0, "live": [{"bass": 2}]}
    window.speed_btn.fx_presets["Nightcore"].click()
    d = window.editctl.edit("s0", "effects")
    eff, e = d.effects, window.engine
    assert abs(eff.speed.value() - 1.56) < 0.03 and eff.knob_values()["bass"] == 5
    eff.speed.set_value(1.2)
    eff.panel.tuning_edited.emit()
    eff.knobs["bass"].set_value(2)
    eff.panel.knobs_edited.emit()
    assert e.sound_speed == pytest.approx(1.0) and e.sound_fx == {}
    f = eff.fx()
    assert f["speed"] == pytest.approx(1.2) and f["pitch"] == 2 and f["live"] == [{"bass": 2}]
    d.done(0)


def test_a_preset_from_the_list_isnt_stacked_on_live_controls(window):  # noqa: F811
    d, eff, e = _nightcore_edit(window)
    eff.preset.setCurrentIndex(eff.preset.findData("Slowed + reverb"))
    eff.preset.activated.emit(eff.preset.currentIndex())
    assert e.sound_speed == pytest.approx(1.0) and e.sound_fx == {}
    assert eff.speed.value() == pytest.approx(0.8)
    d.done(0)


def test_undo_brings_live_controls_back(window):  # noqa: F811
    d, eff, e = _nightcore_edit(window)
    d.btn_reset.click()
    d._flush()
    assert e.sound_speed == pytest.approx(1.0)
    d.undo()
    assert e.sound_speed == pytest.approx(1.3) and e.sound_fx == {"bass": 3}
    assert eff.speed.value() == pytest.approx(1.3)
    d.redo()
    assert e.sound_speed == pytest.approx(1.0) and e.sound_fx == {}
    d.done(0)


def test_cancel_leaves_live_controls_as_they_were_left(window):  # noqa: F811
    d, eff, e = _nightcore_edit(window)
    d.done(0)                                                # nothing done: Nightcore stays
    assert e.sound_speed == pytest.approx(1.3) and e.sound_fx == {"bass": 3}
    d, eff, e = _nightcore_edit(window)
    d.btn_reset.click()
    d.done(0)                                                # got rid of it: it stays gone
    assert e.sound_speed == pytest.approx(1.0) and e.sound_fx == {}


def test_the_sounds_own_and_live_controls_add_up():
    p = EffectsPanel({"speed": 1.2, "pitch": 2, "live": [{"bass": 6, "reverb": 0.2}]})
    p.set_live_layer(1.5, 1.0, True, {"bass": 3, "reverb": 0.5, "volume": 150})
    assert p.speed.value() == pytest.approx(1.8) and p.pitch.value() == pytest.approx(3)
    assert p.knob_values() == {"bass": 9, "reverb": pytest.approx(0.7)}
    assert p.own_knobs() == {"bass": 6, "reverb": pytest.approx(0.2)}
    f = p.fx()                                               # Save keeps only its own
    assert (f["speed"], f["pitch"]) == (1.2, 2) and f["live"] == [{"bass": 6, "reverb": 0.2}]
    p.set_live_layer(1.0, 0.0, True, {})
    assert p.speed.value() == pytest.approx(1.2) and p.knob_values()["bass"] == 6
