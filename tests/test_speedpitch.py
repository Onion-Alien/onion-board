"""The speed & pitch button and the volume control restyle only when their look
changes: each setStyleSheet re-polishes the widget (the button: its whole popup)."""
import pytest


@pytest.mark.parametrize("what", ["sounds", "radio", "apps"])
def test_live_reset_has_a_large_target_and_clears_controls(qapp, what):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton

    from soundboard.ui.sounds.speedpitch import SpeedPitchButton

    button = SpeedPitchButton(what)
    try:
        button.pop.show()
        qapp.processEvents()
        reset = button.pop.findChild(QPushButton, "liveReset")
        assert reset.width() >= 96 and reset.height() >= 36
        assert reset.width() >= reset.minimumSizeHint().width()
        assert reset.iconSize().width() >= 18
        assert reset.toolTip() and reset.text()
        button.set_values(1.5 if button.has_speed else 1, 4, False)
        button.set_fx({"bass": 6, "reverb": 0.3})
        # The enlarged edge is clickable, not just padding around the old target.
        QTest.mouseClick(reset, Qt.MouseButton.LeftButton,
                         pos=QPoint(reset.width() - 3, reset.height() // 2))
        assert button.speed.value() == 1
        assert button.pitch.value() == 0
        assert not button.keep.isChecked()
        assert button.fx_values() == {}
        assert button.pop.isVisible()
    finally:
        button.pop.close()
        button.deleteLater()


def _count_sheets(w):
    calls = []
    real = w.setStyleSheet
    w.setStyleSheet = lambda sheet: (calls.append(sheet), real(sheet))[1]
    return calls


def test_speed_pitch_button_restyles_only_when_its_look_changes(qapp):
    from soundboard.ui.sounds.speedpitch import SpeedPitchButton
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


@pytest.mark.parametrize("what", ["sounds", "radio"])
def test_the_live_controls_button_has_a_name(qapp, what):
    """Its text is the speed ("1x"): a screen reader said only that."""
    from soundboard.ui.sounds.speedpitch import SpeedPitchButton
    b = SpeedPitchButton(what)
    assert b.accessibleName() == "Live controls" and b.accessibleDescription() == b.toolTip()


def test_volume_control_restyles_only_when_its_colour_changes(qapp):
    from soundboard.ui.kit.panel import VolumeControl
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
    from soundboard.ui.sounds.speedpitch import SpeedPitchButton
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
    assert not b.red_box.isHidden()        # Redline's meter shows the pitch here
    assert b.meter.pitch and b.meter.speed == 3
    b.pitch.set_value(30)
    b._edited()
    assert b.meter.speed == 30 and b.meter._hot(30) and not b.meter._hot(12)
    b.reset()
    assert b.text() == "Effects"


@pytest.mark.parametrize("what", ["sounds", "radio", "apps"])
def test_live_controls_pop_up_beside_the_button_and_click_away(qapp, what):
    """A pop-up, not a window: it opens by its button, on the button's screen, a
    click outside (or Escape) closes it, and the settings stay for next time."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from soundboard.ui.sounds.speedpitch import SpeedPitchButton

    owner = QWidget()
    owner.setGeometry(30, 80, 760, 650)
    layout = QVBoxLayout(owner)
    button = SpeedPitchButton(what)
    layout.addWidget(button, 0, Qt.AlignBottom | Qt.AlignRight)
    owner.show()
    qapp.processEvents()
    pop = button.pop
    try:
        button.click()
        qapp.processEvents()
        assert pop.isVisible() and pop.windowType() == Qt.Popup
        area = button.screen().availableGeometry()
        assert area.contains(pop.frameGeometry())
        b = button.rect().translated(button.mapToGlobal(button.rect().topLeft()))
        assert pop.geometry().bottom() < b.top()          # just above its button
        assert abs(pop.geometry().right() - b.right()) <= 1

        button.set_redline(True)                          # taller: re-placed above it
        assert pop.isVisible() and area.contains(pop.frameGeometry())
        button.set_redline(False)

        button.set_fx({"bass": 4})
        pop.close()                                       # a click outside / Escape
        assert not pop.isVisible()
        button.click()            # the press that closed it was on the button: stays shut
        assert not pop.isVisible()
        button._hidden_at = 0.0   # (a later click)
        button.click()
        assert pop.isVisible() and button.fx_values() == {"bass": 4}
    finally:
        pop.close()
        owner.close()


def test_redline_starts_at_eight_times(qapp):
    import math

    from PySide6.QtGui import QColor

    from soundboard.ui.sounds.speedpitch import RED, SpeedPitchButton

    button = SpeedPitchButton()
    button.set_redline(True)
    button.set_values(7.95, 0, True)
    assert RED not in button.styleSheet()
    button.set_values(8, 0, True)
    assert RED in button.styleSheet()
    button.set_values(10, 0, True)
    assert button.speed.value() == 10

    # Check the drawn arc too: 8.5x is already red, rather than an orange
    # warning band that delays the red zone until 9x.
    meter = button.meter
    meter.resize(340, 132)
    meter.set_value(1)
    picture = meter.grab().toImage()
    radius = min(meter.width() / 2 - 12, meter.height() * 0.62)
    angle = math.radians(meter._angle(8.5))
    pixel = picture.pixelColor(round(meter.width() / 2 + radius * math.cos(angle)),
                               round(radius + 10 - radius * math.sin(angle)))
    red = QColor(RED)
    assert abs(pixel.red() - red.red()) < 10
    assert abs(pixel.green() - red.green()) < 10
    assert abs(pixel.blue() - red.blue()) < 10


def test_no_change_sits_mid_slider_on_lopsided_ranges(qapp):
    """1x speed and +0 dB bass sit in the middle like 0 st pitch does, though
    their ranges are lopsided (0.25x to 2x, -12 to +18 dB)."""
    from soundboard.audio import livefx
    from soundboard.ui.sounds.speedpitch import SpeedPitchButton
    b = SpeedPitchButton()
    for s in (b.speed, b.pitch, b.fx["bass"], b.fx["treble"]):
        sl = s.slider
        assert sl.value() * 2 == sl.maximum(), s.q.key
        sl.setValue(sl.minimum())
        assert s.value() == s.q.lo
        sl.setValue(sl.maximum())
        assert s.value() == s.q.hi
        for v in (s.q.lo, s.q.default, s.q.hi):   # every value comes back as set
            s.set_value(v)
            assert s.value() == v
    b.speed.set_value(1.5)
    assert b.speed.value() == 1.5 and b.speed.slider.value() > b.speed.slider.maximum() / 2
    b.set_redline(True)                            # 0.1x to 10x: 1x still mid
    b.speed.set_value(1.0)
    assert b.speed.slider.value() * 2 == b.speed.slider.maximum()
    assert b.fx["muffle"].slider.value() == 0      # 0 to 100 %: starts at the left
    assert livefx.MUFFLE.default == livefx.MUFFLE.lo


def test_the_values_can_be_typed(qapp):
    """The sliders had positions only: each value is a box you can type in too."""
    from soundboard.ui.sounds.speedpitch import SpeedPitchButton, ValueBox
    b = SpeedPitchButton()
    got = []
    b.fx_changed.connect(got.append)
    box = b.fx["bass"].val
    assert isinstance(box, ValueBox) and box.suffix() == " dB"
    box.setValue(7)                                   # typed, then Enter
    assert b.fx["bass"].value() == 7 and got[-1]["bass"] == 7
    b.fx["bass"].slider.setValue(b.fx["bass"].slider.maximum())
    assert box.value() == 18                          # and it follows the slider
    reverb = b.fx["reverb"].val
    assert reverb.suffix() == "%" and reverb.maximum() == 100
    reverb.setValue(40)
    assert b.fx["reverb"].value() == 0.4
    b.speed.val.setValue(1.5)
    assert b.speed.value() == 1.5


def test_a_lit_preset_clicked_again_puts_the_knobs_back(qapp):
    """Clicked again, a lit preset turned every knob off, a tweak made before it too."""
    from soundboard.audio import livefx
    from soundboard.ui.sounds.speedpitch import SpeedPitchButton
    b = SpeedPitchButton()
    b.set_fx({"reverb": 0.3})
    name = next(n for n, a in livefx.PRESETS.items() if "reverb" not in a)
    b.fx_presets[name].click()
    assert b.fx_values() == livefx.clean(livefx.PRESETS[name])
    assert b.fx_presets[name].isChecked()
    b.fx_presets[name].click()
    assert b.fx_values() == {"reverb": 0.3}


def test_my_setups_label_lines_up_with_its_chips(qapp):
    """"My setups" sat a few pixels below "No voice": the section label's top padding."""
    from soundboard.ui.sounds.speedpitch import SpeedPitchButton
    b = SpeedPitchButton()
    b.set_setups([], "")
    chip = b._setup_chips[""]
    assert b._setups_lab.property("head") is True
    assert b._setups_lab.height() == chip.sizeHint().height()
