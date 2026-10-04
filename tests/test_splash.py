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


def test_splash_follows_the_saved_theme(qapp, tmp_path, monkeypatch):
    from soundboard import theme
    cfg = tmp_path / "config.json"
    cfg.write_text('{"theme": "Toxic"}', encoding="utf-8")
    monkeypatch.setattr(splash, "CONFIG", cfg)
    try:
        s = splash.show()
        assert theme.current_name == "Toxic"
        img = s.grab().toImage()
        assert img.pixelColor(0, 0).alpha() == 0   # no card behind Bun any more
    finally:
        splash.close()
        theme.set_current(theme.DEFAULT)


def test_frames_draw_at_any_scale(qapp):
    """The native splash paints paint_frame() at the monitor's own scale."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    for k in (1.0, 1.25, 2.0):
        img = QImage(round(splash.CARD_W * k), round(splash.CARD_H * k),
                     QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.scale(k, k)
        splash.paint_frame(p, 0.3, splash.CARD_W, splash.CARD_H)
        p.end()
        assert img.pixelColor(0, 0).alpha() == 0
        assert any(img.pixelColor(x, img.height() // 2).alpha() == 255
                   for x in range(img.width()))   # Bun is in there, solid
