"""The Radio map's country names (`MapLabels`, a mixin of FlatMap): where they go at each
zoom, and drawn over the stations, each name a picture drawn once and copied."""
from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QPixmap,
                           QTransform)
from PySide6.QtWidgets import QWidget

from soundboard.ui.kit import theme
from soundboard.ui.radio.mapparts import LAT_BOTTOM, LAT_TOP, _mix

LABEL_GROW_MAX = 2.2                # country names grow up to this much zoomed in
LABEL_SLICE_S = 0.002               # new names drawn a paint; the rest the next one

# what the mixin gets from FlatMap, for the type checker only: at run time
# it is a plain class (FlatMap itself is the widget)
_Base = QWidget if TYPE_CHECKING else object


class MapLabels(_Base):
    """FlatMap's country names."""
    if TYPE_CHECKING:
        _labels: list[tuple[str, float, float, float]]
        _placed: dict[float, list]
        _label_pm: dict[tuple, QPixmap]
        _towns_later: QTimer
        cx: float
        cy: float
        zoom: float

        def _copies(self) -> list[int]: ...
        def _scale(self) -> float: ...
        def _origin(self, k: int = 0, s: float | None = None) -> QPointF: ...

    def _label_style(self, s: float) -> tuple[QFont, QColor]:
        """The country names' font at scale `s`: they grow as the map zooms in, so a
        country's name stays well above its cities' (the same size, it read as one)."""
        font = QFont(self.font())
        zoom = s / max(1e-9, self._scale() / self.zoom)
        grow = min(LABEL_GROW_MAX, max(1.0, 1 + 0.4 * math.log2(max(zoom, 1.0) / 1.5)))
        # in whole points: a name is drawn once a size, not once a wheel step
        font.setPointSizeF(round(max(7.0, font.pointSizeF() * 0.85) * grow))
        font.setWeight(QFont.Weight.DemiBold)
        return font, QColor(theme.T["text_hi"])

    def _label_boxes(self, tr: QTransform, s: float, rect: QRectF, fm: QFontMetricsF):
        """Where the country names go: (box, name), biggest first, each where it fits
        inside its country's width and doesn't run into a name already placed (looked
        up by grid cell: checking every placed name was ~10 ms a wheel step zoomed in)."""
        taken: dict[tuple[int, int], list[QRectF]] = {}
        cell = 128.0
        h = fm.height()
        for name, lon, lat, width in self._labels:
            if width * s < 30:   # sorted widest first: none of the rest fit either
                break
            w = fm.horizontalAdvance(name)
            c = tr.map(QPointF(lon, -lat))
            box = QRectF(c.x() - w / 2, c.y() - h / 2, w, h)
            if not box.intersects(rect) or width * s < w * 0.8:
                continue
            pad = box.adjusted(-4, -2, 4, 2)
            cells = [(x, y) for x in range(math.floor(pad.left() / cell),
                                           math.floor(pad.right() / cell) + 1)
                     for y in range(math.floor(pad.top() / cell),
                                    math.floor(pad.bottom() / cell) + 1)]
            if any(pad.intersects(o) for c in cells for o in taken.get(c, ())):
                continue
            for c in cells:
                taken.setdefault(c, []).append(pad)
            yield box, name

    def _place_labels(self, s: float) -> list[tuple[QRectF, str]]:
        """The country names' boxes at scale `s`, in pixels from the world's top-left
        corner: placed once for the whole world, so the town names know where
        they are."""
        key = round(s, 6)
        got = self._placed.get(key)
        if got is None:
            if len(self._placed) > 8:
                self._placed.clear()
            tr = QTransform()
            tr.translate(180 * s, LAT_TOP * s)
            tr.scale(s, s)
            whole = QRectF(0, 0, 360 * s, (LAT_TOP - LAT_BOTTOM) * s)
            fm = QFontMetricsF(self._label_style(s)[0])
            got = self._placed[key] = list(self._label_boxes(tr, s, whole, fm))
        return got

    def _label_pixmap(self, name: str, font: QFont, dpr: float) -> QPixmap:
        """A country's name drawn once at this size, outlined in the land's colour so
        it reads over the dots; after that it's only copied onto the map."""
        key = (name, font.pointSizeF(), dpr)
        pm = self._label_pm.get(key)
        if pm is None:
            if len(self._label_pm) > 600:
                self._label_pm.clear()
            t = theme.T
            fm = QFontMetricsF(font)
            w, h = fm.horizontalAdvance(name) + 6, fm.height() + 6
            pm = QPixmap(max(1, math.ceil(w * dpr)), max(1, math.ceil(h * dpr)))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.GlobalColor.transparent)
            q = QPainter(pm)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            path = QPainterPath()
            path.addText(3, 3 + fm.ascent(), font, name)
            halo = QPen(_mix(t["bg"], t["text"], 0.14), 3)
            halo.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            q.strokePath(path, halo)
            q.fillPath(path, QColor(t["text_hi"]))
            q.end()
            self._label_pm[key] = pm
        return pm

    def _paint_labels(self, p: QPainter, dpr: float):
        """The country names in view, over the dots. A name at a size not drawn before
        (zooming in to a bigger one) gets about LABEL_SLICE_S a paint; the rest show
        a paint later."""
        if not self._labels:
            return
        s = self._scale()
        font = self._label_style(s)[0]
        size = font.pointSizeF()
        rect = QRectF(self.rect())
        placed = self._place_labels(s)
        end = time.perf_counter() + LABEL_SLICE_S
        for k in self._copies():
            o = self._origin(k, s)
            for box, name in placed:
                box = box.translated(o)
                if not box.adjusted(-3, -3, 3, 3).intersects(rect):
                    continue
                if (name, size, dpr) not in self._label_pm and time.perf_counter() > end:
                    self._towns_later.start()   # (a repaint in a moment)
                    continue
                p.drawPixmap(box.topLeft() - QPointF(3, 3), self._label_pixmap(name, font, dpr))
