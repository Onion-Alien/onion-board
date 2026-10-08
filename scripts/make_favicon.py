"""Render the website's tab icons (Bun the mascot, from soundboard/bunny.py) into docs/.

    .venv\\Scripts\\python scripts\\make_favicon.py
"""
import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # no window needed

from PySide6.QtCore import QBuffer, QIODevice, QRect, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))   # run from scripts\: make `soundboard` importable
OUT = ROOT / "docs"

ICO_SIZES = (16, 32, 48)
HEAD = 0.80   # top share of Bun that's ears + head + headphones: tiny icons skip the body


def png_bytes(img) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def head(size: int, bg: QColor | None = None) -> QImage:
    """Bun's head centred in a size x size square, on `bg` (else transparent)."""
    from soundboard.bunny import bunny_image
    big = bunny_image(1024)
    crop = big.copy(QRect(0, 0, big.width(), round(big.height() * HEAD)))
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(bg if bg is not None else Qt.transparent)
    pad = round(size * (0.12 if bg is not None else 0.0))
    fit = crop.scaled(size - 2 * pad, size - 2 * pad, Qt.KeepAspectRatio,
                      Qt.SmoothTransformation)
    p = QPainter(img)
    p.drawImage((size - fit.width()) // 2, (size - fit.height()) // 2, fit)
    p.end()
    return img


def main():
    _app = QGuiApplication(sys.argv)   # QPainter needs a live application object
    pngs = [png_bytes(head(s)) for s in ICO_SIZES]
    # ICO = header + one directory entry per size + PNG payloads (Vista+ format)
    out = struct.pack("<HHH", 0, 1, len(ICO_SIZES))
    offset = 6 + 16 * len(ICO_SIZES)
    for s, data in zip(ICO_SIZES, pngs):
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    out += b"".join(pngs)
    (OUT / "favicon.ico").write_bytes(out)
    head(192).save(str(OUT / "favicon.png"))
    # phones put the home-screen icon on a tile, so give it the site's background
    head(180, QColor("#0f1016")).save(str(OUT / "apple-touch-icon.png"))
    print("wrote docs/favicon.ico, favicon.png, apple-touch-icon.png")


if __name__ == "__main__":
    main()
