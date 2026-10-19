"""Regenerate the Stream Deck plugin's pictures (streamdeck/*.sdPlugin/imgs/): the plugin
and category icons from the logo in theme.py (PNG, as Elgato's store wants), and the
action list icons and key pictures (SVG, drawn here).

    .venv\\Scripts\\python scripts\\pictures\\make_streamdeck_icons.py
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # no window needed

from PySide6.QtGui import QGuiApplication

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))   # run from scripts\: make `soundboard` importable
IMGS = ROOT / "streamdeck" / "com.onionalien.onionboard.sdPlugin" / "imgs"

# name → size (the @2x file is twice that)
LOGOS = {"plugin": 256, "category": 28}

LIST = "#efefef"     # action list icons: light on clear (Elgato's style)
ACCENT = "#7c5cff"   # PAD_COLORS[0]

# the shapes, on a 20x20 grid for the list icons and inside a 144x144 key
WAVE = ('<rect x="3" y="8" width="2.4" height="4" rx="1.2"/><rect x="7" y="4" width="2.4" '
        'height="12" rx="1.2"/><rect x="11" y="6" width="2.4" height="8" rx="1.2"/>'
        '<rect x="15" y="8.5" width="2.4" height="3" rx="1.2"/>')
STOP = '<rect x="5" y="5" width="10" height="10" rx="2"/>'
DICE = ('<rect x="3" y="3" width="14" height="14" rx="3" fill="none" stroke-width="1.8" '
        'stroke="{c}"/><circle cx="7" cy="7" r="1.4"/><circle cx="10" cy="10" r="1.4"/>'
        '<circle cx="13" cy="13" r="1.4"/>')
SWITCH = ('<rect x="2" y="6" width="16" height="8" rx="4" fill="none" stroke-width="1.8" '
          'stroke="{c}"/><circle cx="{x}" cy="10" r="2.6"/>')


def list_icon(shape: str, colour: str = LIST, x: int = 13) -> str:
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" '
            'viewBox="0 0 20 20">'
            f'<g fill="{colour}">{shape.format(c=colour, x=x)}</g></svg>\n')


def key(shape: str, bg: str, fg: str = "#ffffff", x: int = 13, top: bool = False) -> str:
    """A 144x144 key: rounded background, the shape big in the middle (or near the top,
    leaving room for a title under it)."""
    scale, dy = (3.2, 10) if top else (4.4, 28)
    dx = (144 - 20 * scale) / 2
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="144" height="144" '
            'viewBox="0 0 144 144">'
            f'<rect width="144" height="144" rx="26" fill="{bg}"/>'
            f'<g transform="translate({dx:g} {dy:g}) scale({scale:g})" fill="{fg}">'
            f'{shape.format(c=fg, x=x)}</g></svg>\n')


SVGS = {
    "play": list_icon(WAVE),
    "stop": list_icon(STOP),
    "random": list_icon(DICE),
    "toggle": list_icon(SWITCH),
    "play-key": key(WAVE, "#3d2f80", top=True),
    "stop-key": key(STOP, "#80303d"),
    "random-key": key(DICE, "#3d2f80"),
    "toggle-on": key(SWITCH, ACCENT, top=True),
    "toggle-off": key(SWITCH, "#3a3a44", fg="#9a9aa6", x=7, top=True),
}


def main():
    _app = QGuiApplication(sys.argv)   # QPainter needs a live application object
    from soundboard.ui.kit import theme
    IMGS.mkdir(parents=True, exist_ok=True)
    for name, size in LOGOS.items():
        theme.logo_image(size).save(str(IMGS / f"{name}.png"))
        theme.logo_image(size * 2).save(str(IMGS / f"{name}@2x.png"))
    for name, svg in SVGS.items():
        (IMGS / f"{name}.svg").write_text(svg, encoding="utf-8", newline="\n")
    print(f"wrote {len(LOGOS) * 2} PNGs and {len(SVGS)} SVGs to {IMGS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
