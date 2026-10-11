"""The seek bar shows no fill at 0:00 (a sliver of it made a new sound look a few
seconds in)."""
from PySide6.QtCore import Qt

from soundboard.ui.widgets import SeekSlider


def test_seek_bar_marks_the_start(qapp):
    s = SeekSlider(Qt.Horizontal)
    s.setRange(0, 1000)
    assert s.property("atstart") is True
    s.setValue(10)
    assert s.property("atstart") is False
    s.setValue(0)
    assert s.property("atstart") is True
