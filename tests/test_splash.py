"""The start-up splash (ui/splash.py): up while starting, pumped by imports, gone after."""
import sys

from soundboard.ui import splash


def test_pump_without_splash_does_nothing(qapp):
    assert splash._splash is None
    splash.pump()   # must not raise or show anything


def test_show_pump_close(qapp):
    s = splash.show()
    try:
        assert s.isVisible()
        assert splash._PumpOnImport in sys.meta_path
        splash._last = 0.0
        splash.pump()
        assert splash._PumpOnImport.find_spec("no_such_module_xyz") is None
        img = s.grab().toImage()
        assert not img.isNull() and img.width() == splash.CARD_W
    finally:
        splash.close()
    assert splash._splash is None
    assert splash._PumpOnImport not in sys.meta_path
    splash.close()   # twice is fine (start-up failure path, then the normal one)
