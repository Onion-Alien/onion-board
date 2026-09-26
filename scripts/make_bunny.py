"""Render the installer's artwork (Bun the mascot, from soundboard/bunny.py) into
installer/. build.ps1 runs this before compiling the installer.

    .venv\\Scripts\\python scripts\\make_bunny.py            # installer images
    .venv\\Scripts\\python scripts\\make_bunny.py --preview  # also a sheet of every pose
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # no window needed
# the offscreen platform ships no fonts of its own
os.environ.setdefault("QT_QPA_FONTDIR",
                      os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))   # run from scripts\: make `soundboard` importable
OUT = ROOT / "installer"


def side_panel(w: int, h: int) -> QImage:
    """The tall picture on the installer's Welcome and Finish pages."""
    from soundboard.bunny import draw_bunny
    img = QImage(w, h, QImage.Format_RGB32)
    p = QPainter(img)
    g = QLinearGradient(0, 0, 0, h)
    g.setColorAt(0, QColor("#7c5cff"))
    g.setColorAt(1, QColor("#ff5c8a"))
    p.fillRect(img.rect(), g)
    p.setPen(QColor(255, 255, 255, 60))
    p.setBrush(QColor(255, 255, 255, 45))
    p.drawEllipse(QRectF(w * 0.08, h * 0.30, w * 0.84, w * 0.84))
    draw_bunny(p, QRectF(w * 0.1, h * 0.26, w * 0.8, h * 0.44), "headphones")
    f = p.font()
    f.setPixelSize(max(12, w // 7))
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("white"))
    p.drawText(QRectF(0, h * 0.74, w, h * 0.1), Qt.AlignCenter, "Onion Board")
    f.setPixelSize(max(9, w // 14))
    f.setBold(False)
    p.setFont(f)
    p.drawText(QRectF(0, h * 0.83, w, h * 0.08), Qt.AlignCenter, "Hi! I'm Bun.")
    p.end()
    return img


def small_corner(s: int) -> QImage:
    """The little picture in the top-right corner of the other installer pages."""
    from soundboard.bunny import draw_bunny
    img = QImage(s, s, QImage.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    draw_bunny(p, QRectF(0, 0, s, s), None)
    p.end()
    return img


def main():
    _app = QGuiApplication(sys.argv)   # QPainter needs a live application object
    OUT.mkdir(exist_ok=True)
    # 100% and 200% DPI versions; Inno Setup picks the best one for the screen
    for k in (1, 2):
        side_panel(164 * k, 314 * k).save(str(OUT / f"wizard-{k}x.bmp"))
        small_corner(55 * k).save(str(OUT / f"wizard-small-{k}x.bmp"))
    print(f"wrote installer artwork to {OUT}")
    if "--preview" in sys.argv:
        from soundboard.bunny import PROPS, draw_bunny
        sheet = QImage(200 * len(PROPS), 240, QImage.Format_RGB32)
        sheet.fill(QColor("#1e1b2e"))
        p = QPainter(sheet)
        for i, prop in enumerate(PROPS):
            draw_bunny(p, QRectF(200 * i + 10, 10, 180, 220), prop)
        p.end()
        sheet.save(str(OUT / "bunny-preview.png"))
        side_panel(328, 628).save(str(OUT / "side-preview.png"))
        print("wrote bunny-preview.png and side-preview.png")


if __name__ == "__main__":
    main()
