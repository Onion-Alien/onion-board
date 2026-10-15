"""Shoot the website's pictures in the themes its look switcher offers.

    .venv\\Scripts\\python scripts/pictures/site_themes.py [--watch-repo DIR] [--menu-only]

The site's own pictures (site/screenshots/*.png) are the Dark theme, and stay the ones
search engines and link previews see. For each other theme in SITE_THEMES this writes
the same pictures as WebP into site/screenshots/themes/<slug>/ (Onion Watch's into
<slug>/watch/), then rewrites the switcher's menu between the <!-- themes --> markers in
site/index.html with each theme's colours, straight from soundboard/theme.py.

--watch-repo is an Onion Watch checkout: its scripts/screenshots.py shoots the Watch tab's
pictures. Set ONIONBOARD_ONION_WATCH_ZIP (see screenshots.py) for the Triggers picture.
--menu-only skips the pictures and only rewrites the menu.
"""
import argparse
import hashlib
import html
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from soundboard import theme  # noqa: E402

DEFAULT = "Dark"   # the site's own pictures: no copies, no colour overrides
SITE_THEMES = ["Blood Moon", "Synthwave", "Hacker", "Ocean", "Light"]
BOARD_PICS = ["sounds", "voice", "triggers", "apps", "setup"]
WATCH_PICS = ["main", "window-picker", "cut-picture", "health-bar", "categories"]
OUT = ROOT / "site" / "screenshots" / "themes"
PAGE = ROOT / "site" / "index.html"
PAGE_BG = "#0b0b12"   # the site's own background, kept under light themes


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _rgb(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _mix(a: str, b: str, t: float) -> str:
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(_rgb(a), _rgb(b)))


def _light(c: str) -> bool:
    r, g, b = _rgb(c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b > 128


def colours(name: str) -> dict[str, str]:
    """The page colours for theme `name`. The page is dark whatever the theme (its
    glass, lines and text are drawn for dark), so a light theme lends only its accent."""
    t = theme.THEMES[name]
    if _light(t["bg"]):
        bg = _mix(PAGE_BG, t["accent"], 0.06)
        return {"bg": bg, "bg2": _mix(bg, "#ffffff", 0.03), "a1": t["accent"],
                "a2": t["accent2"], "link": _mix(t["accent"], "#ffffff", 0.35)}
    return {"bg": t["bg"], "bg2": t["panel"], "a1": t["accent"], "a2": t["accent2"],
            "link": t["accent_link"]}


def webp(src: Path, dest: Path):
    from PySide6.QtGui import QImage
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not QImage(str(src)).save(str(dest), "WEBP", 88):
        raise SystemExit(f"couldn't write {dest}")


def texture(name: str) -> dict[str, str]:
    """Write theme `name`'s texture tile (the app's own, see soundboard/style/textures.py)
    for the page's background, and return the colours that point at it ({} if none)."""
    from PySide6.QtGui import QGuiApplication

    from soundboard.style import textures
    kind = theme.THEMES[name].get("texture")
    if not kind:
        return {}
    QGuiApplication.instance() or QGuiApplication(["site_themes", "-platform", "offscreen"])
    dest = OUT / slug(name) / "texture.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tile = textures.texture_image(kind, dict(theme.THEMES[name]))
    if not tile.save(str(dest)):
        raise SystemExit(f"couldn't write {dest}")
    h = hashlib.sha1(dest.read_bytes()).hexdigest()[:8]
    return {"tex": f"url(screenshots/themes/{slug(name)}/texture.png?v={h})",
            "tex-size": f"{tile.width()}px"}


def shoot(name: str, watch_repo: Path | None):
    out = OUT / slug(name)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # judged by the pictures it wrote: it sometimes crashes on its way out (see docs.py)
        subprocess.run([sys.executable, "-u", str(ROOT / "scripts" / "pictures" / "screenshots.py"),
                        "--theme", name, "--out", str(tmp / "board")], cwd=ROOT, timeout=300)
        for pic in BOARD_PICS:
            if (tmp / "board" / f"{pic}.png").exists():
                webp(tmp / "board" / f"{pic}.png", out / f"{pic}.webp")
            else:
                print(f"{name}: no {pic}.png (set ONIONBOARD_ONION_WATCH_ZIP for triggers)")
        if watch_repo:
            py = watch_repo / ".venv" / "Scripts" / "python.exe"
            subprocess.run([str(py if py.exists() else sys.executable), "-u",
                            str(watch_repo / "scripts" / "screenshots.py"), str(tmp / "watch"),
                            "--theme", name], cwd=watch_repo, timeout=300)
            for pic in WATCH_PICS:
                webp(tmp / "watch" / f"{pic}.png", out / "watch" / f"{pic}.webp")
    print("shot", name)


def version(name: str) -> str:
    """A hash of the theme's pictures, so a changed set isn't served from a stale cache."""
    h = hashlib.sha1()
    for p in sorted((OUT / slug(name)).rglob("*.webp")):
        h.update(p.read_bytes())
    return h.hexdigest()[:8]


def menu() -> str:
    rows = []
    for name in [DEFAULT, *SITE_THEMES]:
        t = theme.THEMES[name]
        swatch = f"--s1:{t['accent']};--s2:{t['accent2']};--s0:{t['bg']}"
        if name == DEFAULT:
            attrs = f'data-theme="{slug(name)}"'
        else:
            c = colours(name) | texture(name)
            vars_ = ";".join(f"--{k}:{v}" for k, v in c.items())
            attrs = (f'data-theme="{slug(name)}" data-v="{version(name)}" '
                     f'data-vars="{vars_}"')
        rows.append(f'        <button type="button" aria-pressed="false" '
                    f'{attrs}><i style="{swatch}"></i>{html.escape(name)}</button>')
    return "\n".join(rows)


def stamp_menu():
    text = PAGE.read_text(encoding="utf-8")
    new, n = re.subn(r"(<!-- themes -->\n).*?([ \t]*<!-- /themes -->)",
                     lambda m: m.group(1) + menu() + "\n" + m.group(2), text, flags=re.S)
    if n != 1:
        raise SystemExit(f"{PAGE.name}: expected one <!-- themes --> block, found {n}")
    PAGE.write_text(new, encoding="utf-8")
    print("stamped the theme menu in", PAGE.relative_to(ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch-repo", type=Path, help="an Onion Watch checkout")
    ap.add_argument("--menu-only", action="store_true", help="only rewrite the menu")
    args = ap.parse_args()
    if not args.menu_only:
        if not os.environ.get("ONIONBOARD_ONION_WATCH_ZIP"):
            print("note: ONIONBOARD_ONION_WATCH_ZIP isn't set, so the themed triggers "
                  "pictures stay as they are")
        for name in SITE_THEMES:
            shoot(name, args.watch_repo)
        for old in OUT.iterdir() if OUT.exists() else ():
            if old.name not in {slug(n) for n in SITE_THEMES}:
                print("left over (not in SITE_THEMES, delete it):", old)
    stamp_menu()


if __name__ == "__main__":
    main()
