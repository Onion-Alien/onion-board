"""The style kit (soundboard/style): Onion Watch carries an exact copy of it, so it
imports nothing from the rest of the app, and it paints in the board's current theme."""
import ast
import sys
from pathlib import Path

from soundboard import theme
from soundboard.style import KIT_VERSION, bunnyfit, hooks, owl

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
    from soundboard.ui.triggershost import BoardHost
    host = BoardHost.__new__(BoardHost)   # style() and kit() don't need the window
    was = theme.current_name
    try:
        theme.set_current("Lava")
        assert host.style()["theme"] == "Lava"
        assert host.kit().KIT_VERSION == KIT_VERSION
    finally:
        theme.set_current(was)
