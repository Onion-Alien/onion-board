"""The seek bar shows no fill at 0:00 (a sliver of it made a new sound look a few
seconds in)."""
import math

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QStyle, QStyleOptionSlider
from test_mainwindow import window  # noqa: F401

from soundboard import theme
from soundboard.ui.widgets import SeekSlider
from soundboard.ui.panel import VolumeControl


def test_seek_bar_marks_the_start(qapp):
    s = SeekSlider(Qt.Horizontal)
    s.setRange(0, 1000)
    assert s.property("atstart") is True
    s.setValue(10)
    assert s.property("atstart") is False
    s.setValue(0)
    assert s.property("atstart") is True


def test_playback_updates_fill_with_signals_blocked(qapp):
    """Timer updates must paint progress without emitting a user seek signal."""
    s = SeekSlider(Qt.Horizontal)
    s.setObjectName("seek")
    s.setRange(0, 1000)
    s.resize(400, 24)
    changed = QSignalSpy(s.valueChanged)
    for name in ("Dark", "Light"):
        theme.apply(qapp, name)
        s.blockSignals(True)
        for value in (0, 500, 750, 0):
            s.setValue(value)
            assert s.property("atstart") is (value == 0)
            rendered = s.grab().toImage()
            expected = theme.T["accent" if value else "groove"]
            assert rendered.pixelColor(50, 12) == QColor(expected)
        s.blockSignals(False)
    assert changed.count() == 0


def test_transport_playback_updates_both_players(window):  # noqa: F811
    window.current = "s0"
    for frac in (0, 0.4, 0.7, 0):
        window.transctl._update_transport({"s0": (frac, False)})
        for slider in (window.seek, window.mini_seek):
            assert slider.value() == int(frac * 1000)
            assert slider.property("atstart") is (frac == 0)


@pytest.mark.parametrize("scale", [1, 1.25, 1.5, 2])
@pytest.mark.parametrize("name, enabled", [("Hacker", True), ("Light", True), ("Dark", False)])
@pytest.mark.parametrize("kind", ["seek", "volume"])
def test_knob_has_no_transparent_border(qapp, scale, name, enabled, kind):
    """The top and right of the circle reach its bounds without a faded border."""
    theme.apply(qapp, name)
    if kind == "seek":
        s = SeekSlider(Qt.Horizontal)
        s.setObjectName("seek")
    else:
        volume = VolumeControl(1)
        s = volume.slider
        s.setParent(None)
        s.setMaximumWidth(400)
    s.resize(400, 24)
    s.setRange(0, 1000)
    s.setValue(500)
    s.setEnabled(enabled)
    s.ensurePolished()
    opt = QStyleOptionSlider()
    s.initStyleOption(opt)
    rect = s.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, s)
    image = QImage(int(400 * scale), int(24 * scale), QImage.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(scale)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    s.render(painter, QPoint())
    painter.end()
    diameter = math.floor(min(rect.width(), rect.height()) * scale + 0.5)
    left = math.floor((rect.x() + rect.width() / 2) * scale - diameter / 2 + 0.5)
    top = math.floor((rect.y() + rect.height() / 2) * scale - diameter / 2 + 0.5)
    expected = QColor(theme.T["text_hi" if enabled else ("off" if kind == "seek" else "inset")])
    for x, y in ((left + diameter // 2, top),
                 (left + diameter - 1, top + diameter // 2)):
        actual = image.pixelColor(x, y)
        assert max(abs(a - b) for a, b in zip(actual.getRgb(), expected.getRgb())) <= 20
