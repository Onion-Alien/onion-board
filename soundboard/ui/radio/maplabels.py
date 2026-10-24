"""The Radio map's country names (`MapLabels`, a mixin of FlatMap): where they go at each
zoom, and drawn once over the stations popping in."""
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
from soundboard.ui.radio.maptiles import SLICE_S

LABEL_GROW_MAX = 2.2                # country names grow up to this much zoomed in

# what the mixin gets from FlatMap, for the type checker only: at run time
# it is a plain class (FlatMap itself is the widget)
_Base = QWidget if TYPE_CHECKING else object


class MapLabels(_Base):
    """FlatMap's country names."""
    if TYPE_CHECKING:
        _labels: list[tuple[str, float, float, float]]
        _names_build: tuple | None
        _names_pic: tuple | None
        _placed: dict[float, list]
        _towns_later: QTimer
        _ver: int
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
        font.setPointSizeF(max(7.0, font.pointSizeF() * 0.85) * grow)
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
        corner: placed once for the whole world, so the tiles (and the town names)
        agree on which names show."""
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

    def _names_steps(self, pic: QPixmap, s: float):
        """The steps that draw the country names in view onto `pic`, a name a step."""
        q = QPainter(pic)
        try:
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            t = theme.T
            font, colour = self._label_style(s)
            fm = QFontMetricsF(font)
            halo = QPen(_mix(t["bg"], t["text"], 0.14), 3)
            halo.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            rect = QRectF(self.rect())
            placed = self._place_labels(s)
            yield
            for k in self._copies():
                corner = self._origin(k, s)
                for box, name in placed:
                    box = box.translated(corner)
                    if not box.adjusted(-3, -3, 3, 3).intersects(rect):
                        continue
                    path = QPainterPath()
                    path.addText(box.left(), box.top() + fm.ascent(), font, name)
                    q.strokePath(path, halo)
                    q.fillPath(path, colour)
                    yield
        finally:
            q.end()

    def _drop_names(self):
        if self._names_build is not None:
            self._names_build[2].close()   # ends its painter
            self._names_build = None

    def _paint_names(self, p: QPainter):
        """The country names over the pop-in (the stand-in under it is just land), so
        they're there before the dots: drawn once for the view, then copied. Drawn a
        slice a paint (all at once was ~25 ms, a skip in the sound playing), shown
        when they're all there."""
        if not self._labels:
            return
        dpr = self.devicePixelRatioF()
        s = self._scale()
        view = (round(s, 6), self.cx, self.cy, self.width(), self.height(), dpr,
                self._ver)
        if self._names_pic is None or self._names_pic[0] != view:
            if self._names_build is None or self._names_build[0] != view:
                self._drop_names()
                pic = QPixmap(max(1, round(self.width() * dpr)),
                              max(1, round(self.height() * dpr)))
                pic.setDevicePixelRatio(dpr)
                pic.fill(Qt.GlobalColor.transparent)
                self._names_build = (view, pic, self._names_steps(pic, s))
            _view, pic, steps = self._names_build
            end = time.perf_counter() + SLICE_S
            while time.perf_counter() < end:
                if next(steps, steps) is steps:   # that was its last step
                    self._names_build = None
                    self._names_pic = (view, pic)
                    break
            else:
                self._towns_later.start()   # the rest in a moment
                return
        p.drawPixmap(0, 0, self._names_pic[1])
