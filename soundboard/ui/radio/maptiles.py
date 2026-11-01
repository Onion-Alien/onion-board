"""The Radio map's tiles (`MapTiles`, a mixin of FlatMap): the world drawn in TILE-pixel
squares once per zoom, a slice at a time, and the last whole view standing in, stretched,
while new ones are drawn."""
from __future__ import annotations

import math
import time
from collections.abc import Iterator
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QPainter, QPixmap, QTransform
from PySide6.QtWidgets import QWidget

from soundboard.ui.kit import theme
from soundboard.ui.radio.mapparts import LAT_BOTTOM, LAT_TOP, _mix

# The world in tiles: a drag copies the ones in view (well under 1 ms) instead of
# drawing the map again, which took 10-20 ms a frame zoomed in and made it lag.
TILE = 512                          # device pixels a side
TILE_RING = 1                       # tiles drawn ahead (and kept) round the view
BASE_ZOOM = 1.0                     # the whole world's land, zoomed out: under everything
# New tiles (zoom, theme, a drag onto new ground) are drawn a slice at a time
# while stand-ins show: Qt keeps Python's lock through each draw call, and the audio
# threads wait out one call per numpy step, so 20-40 ms of drawing in one go made the
# cable 10-20 ms late (a skip) even with every call under 1 ms. A slice, then a break.
SLICE_S = 0.0015
SLICE_GAP_MS = 4

# what the mixin gets from FlatMap, for the type checker only: at run time
# it is a plain class (FlatMap itself is the widget)
_Base = QWidget if TYPE_CHECKING else object


class MapTiles(_Base):
    """FlatMap's tiles: which to draw, drawing them a slice at a time, and the stand-ins."""
    if TYPE_CHECKING:
        _build: tuple | None
        _land_ver: int
        _pics: dict[tuple, tuple]
        _queue: list[tuple]
        _settle: QTimer
        _slice: QTimer
        _stable: tuple | None
        _tiles: dict[tuple, QPixmap]
        cx: float
        cy: float
        zoom: float

        def _copies(self) -> list[int]: ...
        def _scale(self) -> float: ...
        def _map_steps(self, p: QPainter, tr: QTransform, s: float,
                       rect: QRectF) -> Iterator[object]: ...

    # ------------------------------------------------------------------ the tiles
    def _origin(self, k: int = 0, s: float | None = None) -> QPointF:
        """Where the world's top-left corner (copy `k`, see _copies) is on screen."""
        s = self._scale() if s is None else s
        return QPointF(self.width() / 2 - (self.cx - k + 180) * s,
                       self.height() / 2 - (LAT_TOP - self.cy) * s)

    def _level(self, zoom: float | None = None) -> tuple:
        """What tiles are drawn for: the scale (pixels per degree; at `zoom`, or the
        view's), the screen's pixel ratio, and the land on them (_land_ver). The
        stations and names aren't on the tiles: they're drawn over them every paint,
        so new stations never draw the tiles again."""
        s = self._scale() if zoom is None else self._scale() / self.zoom * zoom
        return (round(s, 6), self.devicePixelRatioF(), self._land_ver)

    def _base_level(self) -> tuple:
        """The whole world's land, small (BASE_ZOOM): the last stand-in, under all."""
        s = self._scale() / self.zoom * BASE_ZOOM
        return (round(s, 6), self.devicePixelRatioF(), self._land_ver, "land")

    @staticmethod
    def _grid(level: tuple) -> tuple[int, int, int, int]:
        """The whole world at `level` in device pixels, and in tiles: (w, h, nx, ny)."""
        s, dpr = level[0], level[1]
        w = max(1, round(360 * s * dpr))
        h = max(1, round((LAT_TOP - LAT_BOTTOM) * s * dpr))
        return w, h, -(-w // TILE), -(-h // TILE)

    def _slots(self, level: tuple, ring: int = 0) -> list[tuple[int, int, int]]:
        """The tiles of `level` over the view, and `ring` more round it: (copy, i, j)."""
        s = self._scale()
        side = TILE / level[1] * s / level[0]      # a tile's side on screen
        _w, _h, nx, ny = self._grid(level)
        out = []
        for k in self._copies():
            o = self._origin(k, s)
            i0 = max(0, math.floor(-o.x() / side) - ring)
            i1 = min(nx - 1, math.floor((self.width() - o.x()) / side) + ring)
            j0 = max(0, math.floor(-o.y() / side) - ring)
            j1 = min(ny - 1, math.floor((self.height() - o.y()) / side) + ring)
            out += [(k, i, j) for j in range(j0, j1 + 1) for i in range(i0, i1 + 1)]
        return out

    def _tile_rect(self, level: tuple, k: int, i: int, j: int) -> QRectF:
        """Where tile (i, j) of `level` goes on screen (copy `k`), its corner on a
        device pixel so the tiles meet without seams."""
        s, dpr = self._scale(), self.devicePixelRatioF()
        f = s / level[0] / level[1]                # its device pixels to screen pixels
        w, h, _nx, _ny = self._grid(level)
        o = self._origin(k, s)
        left = round((o.x() + i * TILE * f) * dpr) / dpr
        top = round((o.y() + j * TILE * f) * dpr) / dpr
        # The rounded cache width can differ from the next world's origin by a
        # device pixel. End the last tile at that origin, and snap both edges.
        end = min((i + 1) * TILE, w)
        right = self._origin(k + 360, s).x() if end == w else o.x() + end * f
        right = round(right * dpr) / dpr
        bottom = round((o.y() + min((j + 1) * TILE, h) * f) * dpr) / dpr
        return QRectF(left, top, right - left, bottom - top)

    def _tile_steps(self, level: tuple, i: int, j: int) -> tuple[QPixmap, Iterator[object]]:
        """A blank tile (i, j) of `level`, and the steps that draw it."""
        s, dpr = level[0], level[1]
        w, h, _nx, _ny = self._grid(level)
        w, h = min(TILE, w - i * TILE), min(TILE, h - j * TILE)
        pm = QPixmap(w, h)
        pm.setDevicePixelRatio(dpr)
        # The geographic world can end inside the last device pixel. Keep that
        # pixel sea-coloured too, instead of baking a dark edge into the cache.
        pm.fill(_mix(theme.T["bg"], theme.T["accent"], 0.06))

        def steps():
            p = QPainter(pm)
            try:
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                tr = QTransform()
                tr.translate(180 * s - i * TILE / dpr, LAT_TOP * s - j * TILE / dpr)
                tr.scale(s, s)
                yield from self._map_steps(p, tr, s, QRectF(0, 0, w / dpr, h / dpr))
            finally:
                p.end()
        return pm, steps()

    def _tile_now(self, key: tuple):
        pm, steps = self._tile_steps(*key)
        for _step in steps:
            pass
        self._tiles[key] = pm

    def _picture(self, level: tuple, slots: tuple) -> tuple | None:
        """The tiles of `level` at `slots` ((copy, i, j)) put together into one picture,
        once: (picture, x, y), x and y its corner in device pixels from the world's
        corner (copy 0). Gaps (a tile not drawn) stay see-through. Stretched as one
        picture it has no seams; tiles stretched one by one each blurred into the
        background at their edges and drew a grid over the map."""
        w = self._grid(level)[0]
        parts = [(round(k / 360 * w) + i * TILE, j * TILE, pm) for k, i, j in slots
                 if (pm := self._tiles.get((level, i, j))) is not None]
        if not parts:
            return None
        key = (level, slots, len(parts))   # put together again as more are drawn
        got = self._pics.get(key)
        if got is not None:
            return got
        x0 = min(x for x, _y, _pm in parts)
        y0 = min(y for _x, y, _pm in parts)
        x1 = max(x + pm.width() for x, _y, pm in parts)
        y1 = max(y + pm.height() for _x, y, pm in parts)
        pic = QPixmap(x1 - x0, y1 - y0)
        pic.fill(Qt.GlobalColor.transparent)
        q = QPainter(pic)
        for x, y, pm in parts:   # device pixel for device pixel
            q.drawPixmap(QRectF(x - x0, y - y0, pm.width(), pm.height()), pm,
                         QRectF(0, 0, pm.width(), pm.height()))
        q.end()
        for old in [old for old in self._pics if old[:2] == key[:2]]:
            del self._pics[old]
        got = self._pics[key] = (pic, x0, y0)
        return got

    def _draw_picture(self, p: QPainter, level: tuple, got: tuple, copies):
        """A _picture of `level`, stretched to the view's scale, for each copy shown."""
        pic, x0, y0 = got
        s = self._scale()
        f = s / level[0] / level[1]                # its device pixels to screen pixels
        view = QRectF(self.rect())
        for k in copies:
            o = self._origin(k, s)
            # Overlap adjacent world copies to cover subpixel rasterization gaps.
            target = QRectF(o.x() + x0 * f, o.y() + y0 * f, pic.width() * f + 0.5,
                            pic.height() * f)
            if target.intersects(view):
                p.drawPixmap(target, pic, QRectF(pic.rect()))

    def _stand_in(self, p: QPainter):
        """What shows while the view's tiles are drawn: the land of the whole world
        (small, so a little soft), and over it the last whole view, each one picture."""
        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        base = self._base_level()
        got = self._picture(base, tuple((0, i, j) for i, j in self._all_tiles(base)))
        if got is not None:
            self._draw_picture(p, base, got, self._copies())
        if self._stable is not None:
            level, slots = self._stable
            got = self._picture(level, slots)
            if got is not None:   # it's in copies already: shifted a world either way
                self._draw_picture(p, level, got, (-360, 0, 360))
        p.restore()

    def _plan(self, cur: tuple, slots: list, complete: bool):
        """After a paint: let go of the tiles no longer needed, and line up the ones
        to draw next (the view's, middle first; the whole world's land; the ring round
        the view, ready for a drag). With nothing at all to show yet, the land first:
        it's small, so there's a map to look at (and drag) in a moment."""
        if complete:
            self._stable = (cur, tuple(slots))
        base = self._base_level()
        ahead = self._slots(cur, TILE_RING)
        keep = {(cur, i, j) for _k, i, j in ahead}
        if self._stable is not None:
            keep |= {(self._stable[0], i, j) for _k, i, j in self._stable[1]}
        for key in list(self._tiles):
            if key not in keep and key[0] != base:
                del self._tiles[key]
        levels = {base, self._stable[0] if self._stable else None}
        for key in [key for key in self._pics if key[0] not in levels]:
            del self._pics[key]
        if self._settle.isActive() or not self.isVisible():
            self._queue = []   # still zooming: nothing's drawn till it stops
            return
        mid = QPointF(self.width() / 2, self.height() / 2)

        def far(slot):
            c = self._tile_rect(cur, *slot).center() - mid
            return abs(c.x()) + abs(c.y())

        view = [(cur, i, j) for _k, i, j in sorted(slots, key=far)]
        land = [(base, i, j) for i, j in self._all_tiles(base)]
        want = view + land if self._stable is not None else land + view
        want += [(cur, i, j) for _k, i, j in sorted(ahead, key=far)]
        self._queue = [key for key in dict.fromkeys(want) if key not in self._tiles]
        if self._queue and not self._slice.isActive():
            self._slice.start()

    def _all_tiles(self, level: tuple) -> list[tuple[int, int]]:
        _w, _h, nx, ny = self._grid(level)
        return [(i, j) for j in range(ny) for i in range(nx)]

    def _draw_slice(self):
        """Draw the next tiles for about SLICE_S, then let the others run."""
        if not self.isVisible():   # off screen: drawn afresh when it shows
            self._stop_build()
            return
        live = (self._level(), self._base_level())
        end = time.perf_counter() + SLICE_S
        drew = False
        while time.perf_counter() < end:
            if self._build is not None and self._build[0][0] not in live:
                self._drop_build()   # zoomed on since: not wanted now
            if self._build is None:
                while self._queue and (self._queue[0] in self._tiles
                                       or self._queue[0][0] not in live):
                    self._queue.pop(0)
                if not self._queue:
                    break
                key = self._queue.pop(0)
                self._build = (key, *self._tile_steps(*key))
            key, pm, steps = self._build
            if next(steps, steps) is steps:   # that was its last step
                self._build = None
                self._tiles[key] = pm
                drew = True
        if drew:
            self.update()
        if self._build is not None or self._queue:
            self._slice.start()

    def _drop_build(self):
        if self._build is not None:
            self._build[2].close()   # ends its painter
            self._build = None

    def _stop_build(self):
        self._drop_build()
        self._queue = []
        self._slice.stop()

    def busy(self) -> bool:
        """Tiles still to draw (tests, benches)."""
        return self._build is not None or bool(self._queue)
