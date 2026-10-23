"""The pictures the style sheet draws controls with (the tick, the radio circle, the
dropdown and stepper chevrons): painted in a theme's colours and saved to the temp folder,
as a style sheet's `image:` needs a file."""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import (QColor, QImage, QPainter, QPainterPath, QPen, QTransform)


def _check_image(colour: str, size: int) -> QImage:
    """A rounded tick, drawn in code so it follows the theme's on-accent colour."""
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(colour), size * 0.16)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    path = QPainterPath(QPointF(size * 0.22, size * 0.52))
    path.lineTo(QPointF(size * 0.42, size * 0.72))
    path.lineTo(QPointF(size * 0.78, size * 0.30))
    p.drawPath(path)
    p.end()
    return img


def _check_url(colour: str) -> str:
    """Stylesheets need a file for `image:`, so write the tick (plus an @2x copy Qt picks
    on high-DPI screens) to the temp folder once per colour."""
    folder = Path(tempfile.gettempdir()) / "onionboard-ui"
    base = folder / f"check-{colour.lstrip('#')}.png"
    try:
        folder.mkdir(exist_ok=True)
        for path, size in ((base, 14), (base.with_name(base.stem + "@2x.png"), 28)):
            if not path.exists():
                _check_image(colour, size).save(str(path))
    except OSError:
        return ""
    return base.as_posix()


def _radio_image(ring: str, fill: str, dot: str, size: int) -> QImage:
    """A whole radio circle: a 1px ring (scaled with `size`) around `fill`, plus a centre
    dot when `dot` is set. Kept half a pixel inside the edge so no side gets clipped."""
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen_w = size / 16
    p.setPen(QPen(QColor(ring), pen_w))
    p.setBrush(QColor(fill))
    r = size / 2 - pen_w / 2 - size / 64
    p.drawEllipse(QPointF(size / 2, size / 2), r, r)
    if dot:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(dot))
        p.drawEllipse(QPointF(size / 2, size / 2), size * 0.22, size * 0.22)
    p.end()
    return img


def _radio_url(ring: str, fill: str, dot: str = "") -> str:
    """The radio circle as a file for `image:`, plus a sharp high-DPI copy."""
    folder = Path(tempfile.gettempdir()) / "onionboard-ui"
    name = "-".join(c.lstrip("#") for c in (ring, fill, dot) if c)
    base = folder / f"radio2-{name}.png"
    try:
        folder.mkdir(exist_ok=True)
        for path, size in ((base, 16), (base.with_name(base.stem + "@2x.png"), 32)):
            if not path.exists():
                _radio_image(ring, fill, dot, size).save(str(path))
    except OSError:
        return ""
    return base.as_posix()


def _chevron_image(colour: str, size: int, up: bool) -> QImage:
    """A rounded chevron (dropdown / stepper arrow), drawn in code like the tick."""
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(colour), size * 0.17)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    tip, ends = (0.34, 0.64) if up else (0.66, 0.36)
    path = QPainterPath(QPointF(size * 0.18, size * ends))
    path.lineTo(QPointF(size * 0.5, size * tip))
    path.lineTo(QPointF(size * 0.82, size * ends))
    p.drawPath(path)
    p.end()
    return img


def _chevron_url(colour: str, size: int, up: bool, side: str = "") -> str:
    """`side` "left" / "right" turns the down chevron on its side (tab-bar scroll arrows)."""
    folder = Path(tempfile.gettempdir()) / "onionboard-ui"
    name = side or ("up" if up else "down")
    base = folder / f"chevron-{name}{size}-{colour.lstrip('#')}.png"
    try:
        folder.mkdir(exist_ok=True)
        for path, px in ((base, size), (base.with_name(base.stem + "@2x.png"), size * 2)):
            if not path.exists():
                img = _chevron_image(colour, px, up)
                if side:
                    img = img.transformed(QTransform().rotate(90 if side == "left" else -90))
                img.save(str(path))
    except OSError:
        return ""
    return base.as_posix()
