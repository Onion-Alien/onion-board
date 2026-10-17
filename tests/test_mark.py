"""The onion logo family (style/mark.py): both apps' marks in both finishes, simpler
when tiny, and the theme picking the finish."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from soundboard import theme
from soundboard.style import mark


def _mark(size: int, **kw) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    mark.paint_mark(p, QRectF(0, 0, size, size), "#7c5cff", "#ff4d8d", **kw)
    p.end()
    return img


def test_every_kind_and_finish_draws_its_own_picture(qapp):
    seen = []
    for kind in ("board", "watch"):
        for finish in mark.FINISHES:
            for size in (16, 20, 32, 256):
                img = _mark(size, kind=kind, finish=finish)
                assert img.pixelColor(size // 2, size // 2).alpha() > 0, (kind, finish, size)
            seen.append(_mark(64, kind=kind, finish=finish))
    assert len({bytes(img.constBits()) for img in seen}) == len(seen)


def test_the_night_tile_is_dark_and_the_signal_tile_is_the_colours(qapp):
    corner = (40, 40)   # (inside the round corner, clear of the onion)
    night = _mark(256, finish="night").pixelColor(*corner)
    signal = _mark(256, finish="signal").pixelColor(*corner)
    assert night.lightness() < 60
    assert signal.lightness() > 100 and signal.saturation() > 100


def test_watchs_eye_shuts(qapp):
    assert _mark(64, kind="watch", awake=False) != _mark(64, kind="watch")


def test_tiny_marks_drop_the_details(qapp):
    big, small = mark.shapes("board", 64), mark.shapes("board", 16)
    assert len(small["cuts"]) < len(big["cuts"]) and not small["roots"]


def test_the_theme_picks_the_finish(qapp, monkeypatch):
    dark = next(n for n in theme.THEMES if not theme.is_light(n))
    light = next(n for n in theme.THEMES if theme.is_light(n))
    assert theme.logo_finish(dark) == "night"
    assert theme.logo_finish(light) == "signal"
    # the .exe and installer art keep the colour tile, whatever the theme
    monkeypatch.setattr(theme, "current_name", dark)
    brand = theme.logo_image(64)
    tile = brand.pixelColor(12, 12)
    assert tile.lightness() > 100 and QColor(tile).saturation() > 100
