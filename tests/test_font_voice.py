"""Voice labels and the picked-voice icon fit the theme font."""
import pytest
from PySide6.QtWidgets import QApplication, QLabel
from test_mainwindow import window  # noqa: F401
from test_font_footer import ink_middle, pixel_fonts  # noqa: F401
from soundboard.ui.mainwindow import TAB_INDEX


@pytest.mark.parametrize("name", ["Dark", "Amber Terminal", "Comic Sans"])
def test_voice_font_ink_and_narrow_labels(window, name):  # noqa: F811
    w = window
    w.apply_theme(name)
    w.show()
    w.tabs.setCurrentIndex(TAB_INDEX["voice"])
    w.resize(1700, 900)
    for _ in range(8):
        QApplication.processEvents()
        w._refit()
    fx = w.voice.fx
    assert abs(ink_middle(fx.picked_pic, fx.picked)
               - ink_middle(fx.picked_name, fx.picked, capital=True)) <= 1
    w.voice.show_tab("speak")
    w.resize(440, 900)
    for _ in range(8):
        QApplication.processEvents()
        w._refit()
    label = next(item for item in w.voice.findChildren(QLabel) if item.text() == "Computer voice")
    assert label.isVisible()
    assert label.width() >= label.fontMetrics().horizontalAdvance(label.text())
