"""Regenerate soundboard.ico (used by the desktop / Start menu shortcuts) from the
logo in theme.py, so the shortcut icon always matches the in-app one.

    .venv\\Scripts\\python make_icon.py
"""
import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # no window needed

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QGuiApplication

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def png_bytes(img) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def main():
    _app = QGuiApplication(sys.argv)   # QPainter needs a live application object
    import theme
    pngs = [png_bytes(theme.logo_image(s)) for s in SIZES]
    # ICO = header + one directory entry per size + PNG payloads (Vista+ format)
    out = struct.pack("<HHH", 0, 1, len(SIZES))
    offset = 6 + 16 * len(SIZES)
    for s, data in zip(SIZES, pngs):
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    out += b"".join(pngs)
    dest = Path(__file__).resolve().parent / "soundboard.ico"
    dest.write_bytes(out)
    print(f"wrote {dest.name} ({len(out) // 1024} KB, sizes {', '.join(map(str, SIZES))})")


if __name__ == "__main__":
    main()
