"""Bun's outfits: every theme's pieces exist, every piece draws, and he's plain when
asked (installer art) or as Robo-Bun."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter

from soundboard import bunny, bunnyfit, theme


def _draw(k: int = 1, **kw) -> QImage:
    img = QImage(100 * k, 120 * k, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    bunny.draw_bunny(p, QRectF(0, 0, 100 * k, 120 * k), **kw)
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


def test_every_theme_but_the_plain_ones_dresses_him(qapp):
    plain = {"Dark", "High Contrast"}      # the default (installer art) and accessibility
    for name in theme.THEMES:
        assert bool(bunnyfit.outfit(name)) == (name not in plain), name


def test_theme_picks_the_outfit_and_robot_wears_none(qapp, monkeypatch):
    monkeypatch.setattr(theme, "current_name", "Royal")
    assert bunnyfit.outfit() == ("crown",)
    assert _draw() == _draw(outfit=("crown",))
    assert _draw(robot=True) == _draw(robot=True, outfit=())


def test_nightcap_replaces_his_hat_and_glasses(qapp):
    capped = _draw(nightcap=True, blink=1.0, outfit=())
    assert _draw(nightcap=True, blink=1.0, outfit=("crown",)) == capped
    for glasses in bunnyfit.EYEWEAR:        # taken off to sleep
        assert _draw(nightcap=True, blink=1.0, outfit=(glasses,)) == capped, glasses
    assert _draw(nightcap=True, blink=1.0, outfit=("scarf",)) != capped   # neck stays


def test_dark_glasses_hide_his_tears_and_lift_his_brows(qapp):
    def ink(img, x, y):
        c = img.pixelColor(x, y)
        return c.alpha() > 200 and c.lightness() < 90

    def tear_blue(img, x, y):
        c = img.pixelColor(x, y)
        return c.blue() > 150 and c.blue() > c.red() + 20

    assert tear_blue(_draw(4, sad=1.0, outfit=()), 156, 276)
    for shades in bunnyfit.HIDE_EYES:       # no tear peeking out under the lens
        assert not tear_blue(_draw(4, sad=1.0, outfit=(shades,)), 156, 276), shades
    # the smug flat brow sits above the lens, not along its top edge
    assert not ink(_draw(4, smug=True, outfit=()), 156, 207)
    assert ink(_draw(4, smug=True, outfit=("shades",)), 156, 207)


def test_hoot_wears_the_theme_outfit_but_not_in_artwork(qapp, monkeypatch):
    from soundboard.ui import owl

    def hoot(**kw):
        img = QImage(100, 120, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        owl.draw_owl(p, QRectF(0, 0, 100, 120), **kw)
        p.end()
        return img

    monkeypatch.setattr(theme, "current_name", "Royal")
    assert hoot() == hoot(outfit=("crown",)) != hoot(outfit=())
    for piece in set(bunnyfit.PIECES) - owl.NOT_ON_OWL:   # every piece lands on him
        assert hoot(outfit=(piece,)) != hoot(outfit=()), piece
    plain = owl.owl_image(120)             # the artwork: his own teal, no outfit
    monkeypatch.setattr(theme, "current_name", "Dark")
    assert owl.owl_image(120) == plain


def test_laser_eyes_stop_when_his_eyes_shut(qapp):
    assert _draw(blink=1.0, outfit=("laser",)) == _draw(blink=1.0, outfit=())
    assert _draw(outfit=("laser",)) != _draw(outfit=())
