"""Bun's outfits: every theme's pieces exist, every piece draws, and he's plain when
asked (installer art) or as Robo-Bun."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from soundboard.ui.bun import bunny
from soundboard.ui.kit import theme
from soundboard.style import bunnyfit


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

    # (on his left eye, x4: the tear just under it, the flat smug brow above it)
    tx, ty = round(bunnyfit.EYES[0] * 4), round((bunnyfit.EYE_Y + 6.5) * 4)
    assert tear_blue(_draw(4, sad=1.0, outfit=()), tx, ty)
    for shades in bunnyfit.HIDE_EYES:       # no tear peeking out under the lens
        assert not tear_blue(_draw(4, sad=1.0, outfit=(shades,)), tx, ty), shades
    # the smug flat brow sits above the lens, not along its top edge
    bx, by = round(bunnyfit.EYES[0] * 4), round((bunnyfit.EYE_Y - 13.3) * 4)
    assert not ink(_draw(4, smug=True, outfit=()), bx, by)
    assert ink(_draw(4, smug=True, outfit=("shades",)), bx, by)


def test_hoot_wears_the_theme_outfit_but_not_in_artwork(qapp, monkeypatch):
    from soundboard.style import owl

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


def test_every_look_names_a_theme_and_known_extras(qapp):
    for name, kit in bunnyfit.LOOKS.items():
        assert name in theme.THEMES, name
        assert set(kit) <= set(bunnyfit.VANILLA), name
        assert kit.get("ears", "up") in ("up", "left", "right", "both"), name
        assert set(kit.get("extras", ())) <= {"chomp", "earring", "shiner", "bandaid",
                                               "freckles"}, name
        assert kit.get("tail", "round") in bunnyfit.TAILS, name
        assert set(kit.get("pattern", ())) <= set(bunnyfit.PATTERNS), name
        for key in ("fur", "iris", "inner", "nose", "marks", "belly", "pads"):
            if kit.get(key) is not None:
                assert QColor(kit[key]).isValid(), (name, key)


def test_plain_bun_keeps_his_old_colours(qapp):
    assert bunny.IRIS.name() == bunnyfit.VANILLA["iris"]
    assert bunny.PINK.name() == bunnyfit.VANILLA["inner"]
    assert bunny.NOSE.name() == bunnyfit.VANILLA["nose"]
    assert bunnyfit.VANILLA["pattern"] == () and bunnyfit.VANILLA["pads"] is None


def test_the_default_theme_is_plain_bun(qapp):
    assert "Dark" not in bunnyfit.LOOKS
    assert bunnyfit.look("Dark") == bunnyfit.VANILLA


def test_every_look_change_shows(qapp):
    plain = _draw(outfit=(), kit=bunnyfit.VANILLA)
    changes = [{"fur": "#6f4630"}, {"ears": "right"}, {"ears": "both"}, {"ears": "left"}]
    changes += [{"extras": (x,)} for x in ("chomp", "earring", "shiner", "bandaid", "freckles")]
    changes += [{"tail": t} for t in bunnyfit.TAILS if t != "round"]
    changes += [{"pattern": (x,)} for x in bunnyfit.PATTERNS]
    changes += [{"iris": "#ff3b2f"}, {"inner": "#9ea6e2"}, {"nose": "#3a2218"},
                {"belly": "#c9f2f7"}, {"pads": "#ff9fbf"}]
    for kit in changes:
        assert _draw(outfit=(), kit=kit) != plain, kit
    # every theme's new keys show too (each draws something of its own)
    for name, kit in bunnyfit.LOOKS.items():
        for key in ("tail", "iris", "inner", "nose", "pattern", "belly", "pads"):
            if key in kit:
                assert _draw(outfit=(), kit={key: kit[key]}) != plain, (name, key)


def test_markings_stay_on_him_and_dark_ones_get_light_eye_rims(qapp):
    """Spots and patches are clipped to his head and body; an eye on dark markings
    gets the light rim dark fur gets, so it doesn't sink into them."""
    marks = "#00ff00"   # (a colour nothing else on him uses)
    for pattern in bunnyfit.PATTERNS:
        img = _draw(4, outfit=(), kit={"pattern": (pattern,), "marks": marks})
        green = [(x, y) for y in range(0, img.height(), 2) for x in range(0, img.width(), 2)
                 if img.pixelColor(x, y).green() > 200 and img.pixelColor(x, y).red() < 60]
        assert green, pattern
        head, body = bunnyfit.head_path(), bunnyfit.body_path()
        for x, y in green:
            q = QPointF(x / 4, y / 4)
            assert head.contains(q) or body.contains(q), (pattern, x, y)
    # the rim: just outside the eye's edge, light on dark markings, the marks without
    ex, ey = bunnyfit.EYES[1], bunnyfit.EYE_Y
    px, py = round((ex + 7.0) * 4), round(ey * 4)
    dark = _draw(4, outfit=(), kit={"pattern": ("patch",), "marks": "#3a2d47"})
    light = _draw(4, outfit=(), kit={"pattern": ("patch",), "marks": "#f3e3cc"})
    assert dark.pixelColor(px, py).lightness() > 200
    assert math.isclose(light.pixelColor(px, py).lightness(),
                        QColor("#f3e3cc").lightness(), abs_tol=25)


def test_pads_are_shapes_under_his_feet(qapp):
    pads = "#00ff00"
    img = _draw(4, outfit=(), kit={"pads": pads})
    for fx in (36.5, 63.5):   # the big pad's middle, on each foot
        c = img.pixelColor(round(fx * 4), round((114.6 + 1.3) * 4))
        assert c.green() > 200 and c.red() < 60, fx
    assert _draw(robot=True, kit={"pads": pads}) == _draw(robot=True, kit=bunnyfit.VANILLA)


def test_his_look_follows_the_theme_but_robot_keeps_his_own(qapp, monkeypatch):
    monkeypatch.setattr(theme, "current_name", "Mocha")
    assert _draw(outfit=()) == _draw(outfit=(), kit=bunnyfit.look("Mocha"))
    assert _draw(outfit=()) != _draw(outfit=(), kit=bunnyfit.VANILLA)
    assert _draw(robot=True) == _draw(robot=True, kit=bunnyfit.VANILLA)
