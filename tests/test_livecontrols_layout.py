"""Live controls keep the Sounds layout when opened from other tabs."""
from PySide6.QtTest import QTest

from test_mainwindow import window as window


def test_live_controls_first_open_styles_preset_headings(window, qapp):
    window.show()
    QTest.qWait(400)
    for button in (window.speed_btn, window.apps.fx_btn, window.radio.fx_btn):
        button._open()
        qapp.processEvents()
        assert button._mine_lab.font().weight() >= 600
        assert button._setups_lab.font().weight() >= 600
        button.pop.hide()
