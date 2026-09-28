"""Optional pictures: the voice changer's voices, the computer voice, its languages.

They're PNGs in assets/art (bundled as art/ in the installed build), named by key:
`voice-chipmunk.png`, `voice-custom.png`, `voice-computer.png`, `lang-zh.png`...
(assets/art/README.md lists them all). A missing picture is fine: the tile keeps
its emoji and the tab its painted icon, so the app never depends on them.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPainterPath, QPixmap

ART_DIR = (Path(sys._MEIPASS) / "art" if hasattr(sys, "_MEIPASS")
           else Path(__file__).resolve().parents[2] / "assets" / "art")
COMPUTER_VOICE = "voice-computer"
SIZES = (16, 20, 24, 28, 32, 40, 48, 64)
ROUND = 0.24      # corner radius, as a fraction of the side

_images: dict[str, QImage | None] = {}
_icons: dict[str, QIcon] = {}


def slug(text: str) -> str:
    """"Stadium announcer" -> "stadium-announcer"."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def voice_key(preset: str) -> str:
    return "voice-" + slug(preset)


def language_key(code: str) -> str:
    return "lang-" + slug(code)


def _image(key: str) -> QImage | None:
    if key not in _images:
        img = QImage(str(ART_DIR / f"{key}.png")) if key else QImage()
        _images[key] = None if img.isNull() else img
    return _images[key]


def exists(key: str) -> bool:
    return _image(key) is not None


def pixmap(key: str, size: int) -> QPixmap | None:
    """The picture as a `size` px rounded square (centre-cropped), or None."""
    img = _image(key)
    if img is None:
        return None
    side = min(img.width(), img.height())
    sq = img.copy((img.width() - side) // 2, (img.height() - side) // 2, side, side)
    sq = sq.scaled(size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, size, size), size * ROUND, size * ROUND)
    p.setClipPath(clip)
    p.drawImage(0, 0, sq)
    p.end()
    return pm


def icon(key: str) -> QIcon | None:
    """The picture as an icon (every state looks the same), or None."""
    if not exists(key):
        return None
    if key not in _icons:
        ic = QIcon()
        for s in SIZES:
            pm = pixmap(key, s)
            for mode in (QIcon.Normal, QIcon.Active, QIcon.Selected):
                ic.addPixmap(pm, mode, QIcon.Off)
                ic.addPixmap(pm, mode, QIcon.On)
        _icons[key] = ic
    return _icons[key]


def first(*keys: str) -> str:
    """The first of `keys` that has a picture ("" if none do)."""
    return next((k for k in keys if k and exists(k)), "")


def reload():
    """Forget what was loaded (pictures added or changed while running, tests)."""
    _images.clear()
    _icons.clear()
