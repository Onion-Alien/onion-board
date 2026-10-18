"""Give the website's live demo the themes' Textured look, from the app's own drawing.

    .venv\\Scripts\\python scripts/pictures/demo_textures.py

For each theme in site/board-demo-data.js that has a texture, this draws the app's tile
(soundboard/style/textures.py) in that theme's colours into site/demo-textures/<slug>.png
and stores it on the theme as "tex" (a CSS url(), cache-busted) for board-demo.css to
tile on the bars and cards, the way the app does with Textured on. Rerun it after
changing a texture or a theme's colours.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QGuiApplication  # noqa: E402

from soundboard.ui.kit import theme  # noqa: E402
from soundboard.style import textures  # noqa: E402

DATA = ROOT / "site" / "board-demo-data.js"
OUT = ROOT / "site" / "demo-textures"
START = "window.ONION_BOARD_DATA = "


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def main():
    QGuiApplication.instance() or QGuiApplication(["demo_textures", "-platform", "offscreen"])
    text = DATA.read_text(encoding="utf-8")
    at = text.index(START) + len(START)
    data, end = json.JSONDecoder().raw_decode(text, at)
    OUT.mkdir(exist_ok=True)
    wanted = set()
    for name, tk in data["themes"].items():
        tk.pop("tex", None)
        kind = theme.THEMES.get(name, {}).get("texture")
        if kind not in textures.TEXTURES:
            continue
        dest = OUT / f"{slug(name)}.png"
        if not textures.texture_image(kind, dict(theme.THEMES[name])).save(str(dest)):
            raise SystemExit(f"couldn't write {dest}")
        wanted.add(dest.name)
        v = hashlib.sha1(dest.read_bytes()).hexdigest()[:8]
        tk["tex"] = f"url(demo-textures/{dest.name}?v={v})"
    for old in OUT.glob("*.png"):
        if old.name not in wanted:
            old.unlink()
    DATA.write_text(text[:at] + json.dumps(data, separators=(",", ":"), ensure_ascii=False)
                    + text[end:], encoding="utf-8")
    print(f"{len(wanted)} textures in {OUT.relative_to(ROOT)}, stamped into {DATA.name}")


if __name__ == "__main__":
    main()
