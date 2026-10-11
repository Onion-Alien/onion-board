"""Bun's outfits: every theme's pieces exist, every piece draws, and he's plain when
asked (installer art) or as Robo-Bun."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter

from soundboard import bunny, bunnyfit, theme


def _draw(**kw) -> QImage:
    img = QImage(100, 120, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    bunny.draw_bunny(p, QRectF(0, 0, 100, 120), **kw)
    p.end()
    return img


def test_every_outfit_piece_is_known_and_themes_exist(qapp):
    for name, pieces in bunnyfit.OUTFITS.items():
        assert name in theme.THEMES, name
        for piece in pieces:
            assert piece in bunnyfit.PIECES, (name, piece)


def test_every_piece_changes_the_picture(qapp):
    plain = _draw(outfit=())
    for piece in bunnyfit.PIECES:
        assert _draw(outfit=(piece,)) != plain, piece


def test_theme_picks_the_outfit_and_robot_wears_none(qapp, monkeypatch):
    monkeypatch.setattr(theme, "current_name", "Royal")
    assert bunnyfit.outfit() == ("crown",)
    assert _draw() == _draw(outfit=("crown",))
    assert _draw(robot=True) == _draw(robot=True, outfit=())


def test_nightcap_replaces_his_hat(qapp):
    capped = _draw(nightcap=True, outfit=())
    assert _draw(nightcap=True, outfit=("crown",)) == capped
    assert _draw(nightcap=True, outfit=("shades",)) != capped   # glasses stay on


def test_laser_eyes_stop_when_his_eyes_shut(qapp):
    assert _draw(blink=1.0, outfit=("laser",)) == _draw(blink=1.0, outfit=())
    assert _draw(outfit=("laser",)) != _draw(outfit=())
