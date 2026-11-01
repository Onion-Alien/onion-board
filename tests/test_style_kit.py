"""The style kit (soundboard/style): Onion Watch carries an exact copy of it, so it
imports nothing from the rest of the app, and it paints in the board's current theme."""
import ast
import sys
from pathlib import Path

from soundboard.ui.kit import theme
from soundboard.style import KIT_VERSION, bunnyfit, hooks, owl, palettes

KIT = Path(__file__).resolve().parent.parent / "soundboard" / "style"


def test_kit_imports_nothing_from_the_app():
    allowed = set(sys.stdlib_module_names) | {"PySide6", "__future__"}
    for path in KIT.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                names = [node.module]
            else:
                continue
            for name in names:
                assert name.split(".")[0] in allowed, f"{path.name} imports {name}"


def test_kit_paints_in_the_current_theme():
    was = theme.current_name
    try:
        theme.set_current("Royal")
        assert hooks.theme_name() == "Royal"
        assert hooks.palette()["accent"] == theme.T["accent"]
        assert bunnyfit.outfit() == bunnyfit.OUTFITS["Royal"]
        with theme.previewing("Vampire"):
            assert bunnyfit.outfit() == bunnyfit.OUTFITS["Vampire"]
        assert bunnyfit.outfit() == bunnyfit.OUTFITS["Royal"]
    finally:
        theme.set_current(was)


def test_hoot_says_his_lines_in_the_language_picked(qapp, monkeypatch):
    monkeypatch.setattr(hooks, "tr", lambda text, **kw: f"<{text}>")
    assert owl.wait_lines()[0] == "<pleeease?>"
    assert owl.OwlWidget(80).joy_lines[0].startswith("<")


def test_board_hands_the_add_on_its_look():
    from soundboard.ui.triggers.triggershost import BoardHost
    host = BoardHost.__new__(BoardHost)   # style() and kit() don't need the window
    was = theme.current_name
    try:
        theme.set_current("Lava")
        assert host.style()["theme"] == "Lava"
        assert host.kit().KIT_VERSION == KIT_VERSION
    finally:
        theme.set_current(was)


def test_textured_rules_follow_the_switch():
    from soundboard.style import textures
    was = (theme.current_name, theme.textures_on)
    try:
        theme.set_current("Carbon")
        assert "background-image" in textures.texture_style("QFrame#card")
        theme.textures_on = False
        assert theme.texture_style("QFrame#card") == ""
        theme.textures_on = True
        assert "background-image" in theme.texture_style("QFrame#card")
        assert theme.live_sheet() == palettes.live_sheet(theme.T)
    finally:
        theme.set_current(was[0])
        theme.textures_on = was[1]


def test_redrawn_texture_never_reuses_an_old_tile_file(qapp, monkeypatch, tmp_path):
    """The tile files in Temp outlive the app: one drawn by an older version must not
    stand in for a redrawn texture just because the theme's colours are the same."""
    from PySide6.QtGui import QColor, QImage

    from soundboard.style import textures
    monkeypatch.setattr(textures.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(textures, "_texture_urls", {})
    tk = dict(palettes.THEMES["Halloween"])
    old = textures.texture_url(tk)

    def redrawn(kind, tk=None, size=None):
        img = QImage(8, 8, QImage.Format.Format_ARGB32)
        img.fill(QColor(1, 2, 3, 40))
        return img
    monkeypatch.setattr(textures, "texture_image", redrawn)
    monkeypatch.setattr(textures, "_texture_urls", {})
    new = textures.texture_url(tk)
    assert new and new != old
    assert QImage(new).size().width() == 8


def test_cards_side_by_side_start_a_big_texture_in_different_places(qapp):
    """Every card started its texture at its own corner, so cards above or beside each
    other showed the same fireworks lined up: a big tile gets a rule per shift, and the
    cards made one after another pick different ones."""
    from PySide6.QtWidgets import QFrame

    from soundboard.style import textures
    fireworks = dict(theme.THEMES["Fireworks"])
    css = textures.texture_style("QFrame#card, QFrame#setcard", fireworks)
    assert css.count("background-image") == len(textures.SHIFTS)
    assert 'QFrame#setcard[texshift="3"]' in css
    scanlines = dict(theme.THEMES["Amber Terminal"])   # a 3 px tile can't line up
    assert textures.texture_style("QFrame#card", scanlines).count("background-image") == 1
    a, b = QFrame(), QFrame()
    theme.vary_texture(a)
    theme.vary_texture(b)
    assert a.property("texshift") != b.property("texshift")
    tile = textures.texture_image("fireworks", fireworks)
    moved = textures._shifted(tile, 0.5, 0.25)   # the same tile, started further in
    assert moved.pixel(0, 0) == tile.pixel(tile.width() // 2, tile.height() // 4)
