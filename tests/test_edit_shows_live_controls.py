"""Edit sound shows Live controls' speed, pitch and knobs on top of the sound's own, as
Live controls show the playing sound's own on top of theirs; an edit there still goes
to the sound's own, and Live controls stay as they are."""
import pytest
from test_mainwindow import window  # noqa: F401

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


def test_an_edit_goes_to_the_sounds_own(window):  # noqa: F811
    window.meta("s0").fx = {}
    window.speed_btn.fx_presets["Nightcore"].click()
    d = window.editctl.edit("s0", "effects")
    eff = d.effects
    eff.speed.set_value(1.3 * 1.5)
    eff.knobs["bass"].set_value(9)
    eff._knobs_edited()
    f = eff.fx()
    assert f["speed"] == pytest.approx(1.5) and f["live"] == [{"bass": 6}]
    e = window.engine
    assert e.sound_speed == pytest.approx(1.3) and e.sound_fx == {"bass": 3}   # untouched
    d.done(0)


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
