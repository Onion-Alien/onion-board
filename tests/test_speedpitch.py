"""The speed & pitch button and the volume control restyle only when their look
changes: each setStyleSheet re-polishes the widget (the button: its whole popup)."""


def _count_sheets(w):
    calls = []
    real = w.setStyleSheet
    w.setStyleSheet = lambda sheet: (calls.append(sheet), real(sheet))[1]
    return calls


def test_speed_pitch_button_restyles_only_when_its_look_changes(qapp):
    from soundboard.ui.speedpitch import SpeedPitchButton
    b = SpeedPitchButton()
    calls = _count_sheets(b)
    s = b.speed.slider
    for v in range(s.value() + 1, s.value() + 11):   # faster: the warning look, once
        s.setValue(v)
    assert len(calls) == 1 and calls[0]
    assert b.text() != "1x"
    b.speed.slider.setValue(b.speed.slider.minimum())   # still not the default
    b.speed.set_value(1.0)
    b._edited()                                         # back to normal: plain again
    assert calls[-1] == "" and len(calls) <= 3


def test_volume_control_restyles_only_when_its_colour_changes(qapp):
    from soundboard.ui.panel import VolumeControl
    vc = VolumeControl(1.0)
    calls = _count_sheets(vc.spin)
    for v in range(20, 90, 5):                 # all under 100 %: the same look
        vc.slider.setValue(v)
    assert calls == []
    vc.slider.setValue(150)                    # over 100 %: warning colour
    vc.slider.setValue(160)
    assert len(calls) == 1


def test_live_stream_button_has_no_speed(qapp):
    """The Radio and Apps tabs' button: pitch and effects only, a live stream can't
    be sped up."""
    from soundboard.ui.speedpitch import SpeedPitchButton
    b = SpeedPitchButton("radio")
    got = []
    b.changed.connect(lambda s, p, k: got.append((s, p)))
    assert not b.has_speed and b.speed.isHidden() and b.keep.isHidden()
    assert b.text() == "Effects"
    b.pitch.set_value(3)
    b._edited()
    assert got[-1] == (1.0, 3) and b.text() == "+3 st"
    b.set_fx({"reverb": 0.5})
    assert b.text() == "+3 st · FX"
    b.set_redline(True)
    assert b.red_box.isHidden()            # the rev meter is for speed
    b.reset()
    assert b.text() == "Effects"
