"""Optional pictures: the voice changer's voices.

They're PNGs in assets/art (bundled as art/ in the installed build), named by key:
`voice-chipmunk.png`, `voice-custom.png`... (assets/art/README.md lists them all).
A missing picture is fine: the tile shows a painted "?" and the tab its painted
icon, so the app never depends on them.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QIcon, QImage, QLinearGradient, QPainter, QPainterPath,
                           QPixmap)

from soundboard.ui import icons

ART_DIR = (Path(sys._MEIPASS) / "art" if hasattr(sys, "_MEIPASS")
           else Path(__file__).resolve().parents[2] / "assets" / "art")
ROUND = 0.24      # corner radius, as a fraction of the side

_images: dict[str, QImage | None] = {}
_icons: dict[str, QIcon] = {}


def slug(text: str) -> str:
    """"Stadium announcer" -> "stadium-announcer"."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def voice_key(preset: str) -> str:
    return "voice-" + slug(preset)


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
    if key not in _icons:   # drawn at the exact size shown (sharp on scaled screens)
        _icons[key] = icons.sharp_icon(lambda px, _mode, _state: pixmap(key, px))
    return _icons[key]


def _dice(size: int) -> QPixmap:
    """The "Random voice" tile's picture, painted: a white die on a purple-to-pink
    rounded square, so it sits with the voices' pictures without being a file."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 24
    bg = QLinearGradient(0, 0, size, size)
    bg.setColorAt(0, QColor("#7c4dff"))
    bg.setColorAt(1, QColor("#ff4f9a"))
    p.setPen(Qt.NoPen)
    p.setBrush(bg)
    p.drawRoundedRect(QRectF(0, 0, size, size), size * ROUND, size * ROUND)
    p.translate(size / 2, size / 2)
    p.rotate(-12)
    die = QRectF(-7.5 * s, -7.5 * s, 15 * s, 15 * s)
    p.setBrush(QColor(0, 0, 0, 60))   # a soft shadow under the die
    p.drawRoundedRect(die.translated(0.8 * s, 1.4 * s), 3.2 * s, 3.2 * s)
    face = QLinearGradient(die.topLeft(), die.bottomRight())
    face.setColorAt(0, QColor("#ffffff"))
    face.setColorAt(1, QColor("#e4dcff"))
    p.setBrush(face)
    p.drawRoundedRect(die, 3.2 * s, 3.2 * s)
    p.setBrush(QColor("#3b2a7a"))
    r = 1.45 * s
    for x, y in ((-3.6, -3.6), (3.6, -3.6), (0, 0), (-3.6, 3.6), (3.6, 3.6)):
        p.drawEllipse(QPointF(x * s, y * s), r, r)
    p.end()
    return pm


def random_icon() -> QIcon:
    """The "Random voice" tile's icon: assets/art/voice-random.png if there is one,
    else the painted die."""
    pic = icon("voice-random")
    if pic is not None:
        return pic
    if "dice" not in _icons:
        _icons["dice"] = icons.sharp_icon(lambda px, _mode, _state: _dice(px))
    return _icons["dice"]


def _mystery(size: int) -> QPixmap:
    """The picture of a voice that has none yet: a white question mark on a slate
    rounded square, painted like the Random voice die."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    bg = QLinearGradient(0, 0, size, size)
    bg.setColorAt(0, QColor("#5b6478"))
    bg.setColorAt(1, QColor("#343a4a"))
    p.setPen(Qt.NoPen)
    p.setBrush(bg)
    p.drawRoundedRect(QRectF(0, 0, size, size), size * ROUND, size * ROUND)
    f = QFont()
    f.setBold(True)
    f.setPixelSize(max(6, int(size * 0.62)))
    p.setFont(f)
    p.setPen(QColor("#ffffff"))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, "?")
    p.end()
    return pm


def mystery_icon() -> QIcon:
    """For a voice tile without a picture of its own (yet)."""
    if "mystery" not in _icons:
        _icons["mystery"] = icons.sharp_icon(lambda px, _mode, _state: _mystery(px))
    return _icons["mystery"]


def first(*keys: str) -> str:
    """The first of `keys` that has a picture ("" if none do)."""
    return next((k for k in keys if k and exists(k)), "")


def reload():
    """Forget what was loaded (pictures added or changed while running, tests)."""
    _images.clear()
    _icons.clear()
