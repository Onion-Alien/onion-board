"""A preset clicked off takes its own speed and knobs with it, whatever was touched since."""
import pytest
from test_live_effects import live  # noqa: F401
from test_mainwindow import window  # noqa: F401

from soundboard.audio import livefx, soundfx

NC = "Nightcore"
PLAIN = (1.0, 0.0, True)


def _edit(window, fx=None):  # noqa: F811
    window.meta("s0").fx = soundfx.clean(fx) if fx else {}
    d = window.editctl.edit("s0", "effects")
    return d, d.effects


def _plain(eff):
    assert eff.panel.values() == pytest.approx(PLAIN) and eff.knob_values() == {}
    assert soundfx.is_neutral(eff.fx()) and eff.preset.currentData() == "None (original)"


@pytest.mark.parametrize("live", (False, True))
def test_off_after_keep_pitch_was_ticked(window, live):  # noqa: F811
    """1.30x, Keep pitch on, Bass +3, Custom: clicking Nightcore on and off kept 1.30x."""
    if live:
        window.speed_btn.fx_presets[NC].click()
    d, eff = _edit(window)
    if not live:
        eff.fx_presets[NC].click()
    eff.keep.click()
    assert not eff.fx_presets[NC].isChecked()
    eff.fx_presets[NC].click()
    eff.fx_presets[NC].click()
    _plain(eff)
    d.done(0)


@pytest.mark.parametrize("tape", (True, False))
def test_off_in_a_saved_sound(window, tape):  # noqa: F811
    d, eff = _edit(window, {**soundfx.PRESETS[NC], "tape": tape})
    for _ in range(1 if tape else 2):
        eff.fx_presets[NC].click()
    _plain(eff)
    d.done(0)


@pytest.mark.parametrize("saved", (False, True))
def test_another_preset_takes_its_place(window, saved):  # noqa: F811
    d, eff = _edit(window, soundfx.PRESETS[NC] if saved else None)
    if not saved:
        eff.fx_presets[NC].click()
    eff.fx_presets["Bass boosted"].click()
    assert eff.panel.values() == pytest.approx(PLAIN) and eff.knob_values() == {"bass": 12}
    eff.fx_presets["Slowed + reverb"].click()
    eff.fx_presets["Slowed + reverb"].click()
    _plain(eff)
    d.done(0)


def test_saved_and_live_nightcore_together_can_be_clicked_off(window):  # noqa: F811
    """1.69x, Bass +6: the button never lit, so it could never be clicked off."""
    window.speed_btn.fx_presets[NC].click()
    d, eff = _edit(window, soundfx.PRESETS[NC])
    eff.fx_presets[NC].click()
    assert eff.fx_presets[NC].isChecked() and window.engine.sound_speed == pytest.approx(1)
    assert eff.speed.value() == pytest.approx(1.3)
    eff.fx_presets[NC].click()
    _plain(eff)
    assert window.engine.sound_fx == {}
    d.done(0)


def test_what_you_set_yourself_stays(window):  # noqa: F811
    d, eff = _edit(window, {"speed": 0.9, "pitch": 2, "live": [{"reverb": 0.3}]})
    eff.fx_presets[NC].click()
    eff.keep.click()
    eff.fx_presets[NC].click()
    eff.fx_presets[NC].click()
    assert eff.panel.values() == pytest.approx((0.9, 2.0, True))
    assert eff.knob_values() == {"reverb": pytest.approx(0.3)}
    d.done(0)


def test_live_controls_the_same(window):  # noqa: F811
    b = window.speed_btn
    b.fx_presets[NC].click()
    b.keep.click()
    b.fx_presets[NC].click()
    b.fx_presets[NC].click()
    assert b.values() == pytest.approx(PLAIN) and window.engine.sound_fx == {}


def test_before_preset_keeps_a_keep_pitch_choice():
    p = livefx.PRESETS[NC]
    assert livefx.before_preset(p, {}, (1.0, 0.0, False)) == ({}, (1.0, 0.0, False))
    assert livefx.before_preset(p, {"bass": 5}, (1.3, 0.0, True)) == ({"bass": 5}, PLAIN)


def test_off_is_heard_on_a_playing_sound(live, qapp):  # noqa: F811
    win, d, _saved, _made, _swaps, _stops = live
    eff = d.effects
    eff.fx_presets[NC].click()
    eff.keep.click()
    eff.fx_presets[NC].click()
    qapp.processEvents()
    assert win.engine.sound_live["s0"][0] == pytest.approx(1.3)
    eff.fx_presets[NC].click()
    qapp.processEvents()
    _plain(eff)
    assert win.engine.sound_live.get("s0") is None and win.engine.sound_speed == 1
