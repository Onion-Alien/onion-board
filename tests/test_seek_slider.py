"""The seek bar shows no fill at 0:00 (a sliver of it made a new sound look a few
seconds in)."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QSignalSpy
from test_mainwindow import window  # noqa: F401

from soundboard import theme
from soundboard.ui.widgets import SeekSlider


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
        window._update_transport({"s0": (frac, False)})
        for slider in (window.seek, window.mini_seek):
            assert slider.value() == int(frac * 1000)
            assert slider.property("atstart") is (frac == 0)
