"""The speed & pitch button and the volume control restyle only when their look
changes: each setStyleSheet re-polishes the widget (the button: its whole popup)."""
import pytest


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


@pytest.mark.parametrize("what", ["sounds", "radio", "apps"])
def test_effects_window_opens_over_owner_and_keeps_its_position(qapp, what):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget

    from soundboard.ui.speedpitch import SpeedPitchButton

    owner = QWidget()
    owner.setGeometry(30, 80, 760, 650)
    layout = QVBoxLayout(owner)
    button = SpeedPitchButton(what)
    layout.addWidget(button, 0, Qt.AlignTop | Qt.AlignLeft)
    owner.show()
    qapp.processEvents()
    try:
        button._open()
        qapp.processEvents()
        dialog = button.pop
        assert isinstance(dialog, QDialog)
        assert dialog.windowType() == Qt.Dialog
        assert not dialog.isModal()
        assert owner.frameGeometry().contains(dialog.frameGeometry())
        area = dialog.screen().availableGeometry()
        assert area.contains(dialog.frameGeometry())

        dialog.move(QPoint(area.left() + 10, area.top() + 10))
        placed = dialog.pos()
        dialog.close()
        button._open()
        assert dialog.pos() == placed
        button.set_redline(True)
        assert dialog.pos() == placed
        button.set_redline(False)
        assert dialog.pos() == placed

        # Closing the window does not discard the live settings.
        button.set_fx({"bass": 4})
        dialog.close()
        button._open()
        assert button.fx_values() == {"bass": 4}

        # A stale placement (e.g. a removed monitor) remains reachable on reopen.
        dialog.move(-10000, -10000)
        dialog.close()
        button._open()
        assert dialog.screen().availableGeometry().contains(dialog.frameGeometry())
    finally:
        button.pop.close()
        owner.close()


def test_redline_starts_at_eight_times(qapp):
    import math

    from PySide6.QtGui import QColor

    from soundboard.ui.speedpitch import RED, SpeedPitchButton

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
