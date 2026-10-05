"""The Radio tab's flat world map: the default view, painted by Qt itself.

A plain map (land outlines, country names, a dot per station and, zoomed in, the
names of the cities and towns in view that have stations) costs nothing while
it sits there: it only repaints when you drag, zoom, hover over a different dot or the
stations change, and it needs no web engine. The world is drawn in tiles (TILE device
pixels square), each once per zoom: a drag or a repaint only copies the tiles in view,
at any zoom. Tiles not drawn yet (a new zoom, a drag onto new ground) are drawn a
slice at a time while the last zoom's tiles, stretched, stand in for them. The 3D globe
(radio.globe_html) is the HD view, one click away on the map's HD button.

Stations arrive as radio.globe_points() dicts, like the globe's, so the tab can
feed either view the same way.
"""
from __future__ import annotations

import html
import math
import time

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen,
                           QPixmap, QRegion, QTransform)
from PySide6.QtWidgets import QPushButton, QToolTip, QVBoxLayout, QWidget

from soundboard import theme

LAT_TOP, LAT_BOTTOM = 84.0, -58.0   # the inhabited world: no polar wastes
ZOOM_MAX = 250.0                    # about street level: a city's stations come apart
HIT_PX = 7.0                        # how near the pointer a dot counts as under it
LAND_PART = 400                     # outline points per drawn part (set_land)
FILL_PX = 1_000_000                 # device pixels per filled band (_fill)
# The world in tiles: a drag copies the ones in view (well under 1 ms) instead of
# drawing the map again, which took 10-20 ms a frame zoomed in and made it lag.
TILE = 512                          # device pixels a side
TILE_RING = 1                       # tiles drawn ahead (and kept) round the view
BASE_ZOOM = 0.5                     # the whole world, small: what shows till a tile's drawn
# New tiles (zoom, new dots, theme, a drag onto new ground) are drawn a slice at a time
# while stand-ins show: Qt keeps Python's lock through each draw call, and the audio
# threads wait out one call per numpy step, so 20-40 ms of drawing in one go made the
# cable 10-20 ms late (a skip) even with every call under 1 ms. A slice, then a break.
SLICE_S = 0.0015
SLICE_GAP_MS = 4
FORGET_MS = 60_000   # hidden this long: let the drawn tiles go (back sooner: no redraw)
SETTLE_MS = 120                     # zooming: the old tiles, stretched, until this idle
TOWN_ZOOM = 2.0                     # city and town names show from this zoom in...
TOWNS_IN_VIEW = 40                  # ...at most this many at once, only those in view
SPREAD_ZOOM = 4.0                   # stations on the very same spot fan out from here...
SPREAD_PX = 2.4                     # ...this far apart (a spiral round the spot)


def _fill(p: QPainter, rect: QRectF, colour: QColor):
    """p.fillRect in bands of about FILL_PX device pixels: Qt keeps Python's lock while
    it fills, and the whole world picture in one go held up the audio for ~10 ms.
    A step per band (FlatMap._world_steps)."""
    dpr = p.device().devicePixelRatioF()
    band = max(1.0, FILL_PX / max(1.0, rect.width() * dpr * dpr))
    y = rect.top()
    while y < rect.bottom():
        h = min(band, rect.bottom() - y)
        p.fillRect(QRectF(rect.left(), y, rect.width(), h), colour)
        y += h
        yield


def _mix(a: str, b: str, t: float) -> QColor:
    ca, cb = QColor(a), QColor(b)
    return QColor.fromRgbF(ca.redF() + (cb.redF() - ca.redF()) * t,
                           ca.greenF() + (cb.greenF() - ca.greenF()) * t,
                           ca.blueF() + (cb.blueF() - ca.blueF()) * t)


def _fan_out(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """For dots on the same spot (to ~100 m), an offset each in a sunflower spiral
    round it, in steps of one: the last of them (the most listened, drawn on top)
    keeps the middle. Dots alone on their spot get (0, 0)."""
    fan = np.zeros((len(lon), 2))
    groups: dict[tuple, list[int]] = {}
    for i, key in enumerate(zip(np.round(lon, 3), np.round(lat, 3))):
        groups.setdefault(key, []).append(i)
    golden = np.pi * (3 - np.sqrt(5))
    for idx in groups.values():
        for n, i in enumerate(reversed(idx)):
            r = np.sqrt(n)
            fan[i] = (r * np.cos(n * golden), r * np.sin(n * golden))
    return fan


class FlatMap(QWidget):
    clicked = Signal(str)       # a station's uuid
    hd_requested = Signal()     # the HD (3D globe) button

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(120, 80)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self._land: list[QPainterPath] = []   # in (lon, -lat) degrees, in parts (set_land)
        self._land_box: list[QRectF] = []     # each part's bounds: a tile skips the rest
        self._labels: list[tuple[str, float, float, float]] = []   # name, lon, lat, width°
        self._towns: list[dict] = []    # radio.town_labels(): the places with stations
        self._tlon = np.zeros(0)
        self._tlat = np.zeros(0)
        self._town_pm: dict[tuple, QPixmap] = {}   # each name drawn once, outlined
        self._points: list[dict] = []
        self._index: dict[str, int] = {}   # a station's place in _points, by uuid
        self._lon = np.zeros(0)
        self._lat = np.zeros(0)
        self._r = np.zeros(0)           # dot radius before zoom
        self._fan = np.zeros((0, 2))    # where a stacked dot goes round its spot (SPREAD_PX)
        self._current: str | None = None
        self._hover = -1
        self._msg = "Finding stations…"
        self.zoom = 1.0
        self.cx, self.cy = 10.0, (LAT_TOP + LAT_BOTTOM) / 2   # the view's centre (lon, lat)
        self._drag: QPointF | None = None
        self._dragged = False
        self._ver = 0                     # bumped when what's drawn changes
        self._tiles: dict[tuple, QPixmap] = {}   # (level, i, j): see _level
        self._stable: tuple | None = None # the last level drawn all over the view
        self._placed: dict[float, list] = {}     # country names' places, per scale
        self._settle = QTimer(self)       # running while the wheel is still zooming
        self._settle.setSingleShot(True)
        self._settle.setInterval(SETTLE_MS)
        self._settle.timeout.connect(self.update)
        self._queue: list[tuple] = []     # tiles to draw next, the most wanted first
        self._build: tuple | None = None  # (tile, picture, its steps): being drawn
        self._slice = QTimer(self)        # draws the next slice of it
        self._slice.setSingleShot(True)
        self._slice.setTimerType(Qt.PreciseTimer)
        self._slice.setInterval(SLICE_GAP_MS)
        self._slice.timeout.connect(self._draw_slice)
        self._forget = QTimer(self)       # hidden a while: let the drawn tiles go
        self._forget.setSingleShot(True)
        self._forget.setInterval(FORGET_MS)
        self._forget.timeout.connect(self._forget_tiles)

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 10, 10)
        box.addStretch(1)
        self._buttons = []
        for text, tip, slot in (("+", "Zoom in", lambda: self._zoom_by(1.5)),
                                ("−", "Zoom out", lambda: self._zoom_by(1 / 1.5)),
                                ("HD", "Show the 3D globe (uses more memory and graphics "
                                       "power than this map)", self.hd_requested.emit)):
            b = QPushButton(text)
            b.setObjectName("mapbtn")
            b.setToolTip(tip)
            b.setFixedSize(30, 30)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(slot)
            box.addWidget(b, 0, Qt.AlignRight)
            self._buttons.append(b)
        self.set_theme()

    # ------------------------------------------------------------------ what's shown
    def set_land(self, rings: list, labels: list | None = None):
        """The countries' outlines, and their names: (name, lon, lat, width in degrees),
        each shown once there's room for it at the zoom."""
        self._labels = sorted(labels or [], key=lambda x: -x[3])   # big countries first
        # in parts of a few hundred points: Qt holds Python's lock while it draws a
        # path, and the whole world in one took 10-30 ms, long enough to hold up the
        # audio threads (a sound skipped each time the map was redrawn at a new zoom).
        # A part takes about 1 ms, and all of them less than the one did.
        self._land = []
        path, n = None, 0
        for ring in rings:
            if path is None or n + len(ring) > LAND_PART:
                path, n = QPainterPath(), 0
                path.setFillRule(Qt.WindingFill)
                self._land.append(path)
            path.moveTo(ring[0][0], -ring[0][1])
            for x, y in ring[1:]:
                path.lineTo(x, -y)
            path.closeSubpath()
            n += len(ring)
        self._land_box = [part.boundingRect() for part in self._land]
        self._redraw()

    def set_points(self, points: list[dict]):
        # the least listened first, so the popular dots are drawn on top
        pts = sorted(points, key=lambda d: d.get("k", 0))
        self._points = pts
        self._index = {d["id"]: i for i, d in enumerate(pts)}
        self._lon = np.array([d["lo"] for d in pts], float)
        self._lat = np.array([d["la"] for d in pts], float)
        k = np.array([d.get("k", 0) for d in pts], float)
        top = max(1.0, float(k.max())) if len(k) else 1.0
        self._r = 1.1 + 1.7 * np.sqrt(k / top)
        self._fan = _fan_out(self._lon, self._lat)
        self._hover = -1
        if pts:
            self._msg = ""
        self._redraw()

    def set_towns(self, towns: list[dict]):
        """City and town names (radio.town_labels(), most stations first), shown once
        zoomed in: the ones with the most stations get first claim on the space."""
        self._towns = list(towns)
        self._tlon = np.array([t["lo"] for t in self._towns], float)
        self._tlat = np.array([t["la"] for t in self._towns], float)
        if len(self._town_pm) > 4 * len(self._towns) + 200:
            self._town_pm.clear()   # names the filters no longer show
        self.update()

    def select(self, point: dict | None, go: bool = False):
        """Mark the playing station (one found by search is added); `go` brings it into view."""
        self._current = point["id"] if point else None
        if point and point["id"] not in self._index:
            self.set_points(self._points + [point])
        if point and go:
            self.fly(point["la"], point["lo"])
        else:
            self.update()

    def fly(self, lat: float, lon: float, *_):
        """Centre on a place, zooming in a little if the whole world is showing."""
        self.zoom = max(self.zoom, 2.5)
        self.cx, self.cy = lon, lat
        self.update()

    def show_message(self, text: str):
        self._msg = text
        self.update()

    def set_theme(self, *_):
        t = theme.T
        self.setStyleSheet(
            f"QPushButton#mapbtn {{ border-radius:8px; border:1px solid {t['border']};"
            f" background:{t['card']}; color:{t['text']}; font-weight:600; padding:0; }}"
            f" QPushButton#mapbtn:hover {{ border-color:{t['accent']}; }}")
        self._redraw()

    # ------------------------------------------------------------------ the projection
    def _scale(self) -> float:
        """Pixels per degree. Zoomed all the way out the map still fills the whole
        area, top to bottom and side to side (no empty bands): it wraps around
        sideways, so whatever is cut off at one edge is a drag away."""
        w, h = max(1, self.width()), max(1, self.height())
        return max(w / 360.0, h / (LAT_TOP - LAT_BOTTOM)) * self.zoom

    def _clamp(self):
        self.zoom = min(ZOOM_MAX, max(1.0, self.zoom))
        s = self._scale()
        half_h = self.height() / s / 2
        self.cx = (self.cx + 180) % 360 - 180   # round the world, east or west
        lo, hi = LAT_BOTTOM + half_h, LAT_TOP - half_h
        self.cy = min(hi, max(lo, self.cy)) if lo <= hi else (LAT_TOP + LAT_BOTTOM) / 2

    def _copies(self) -> list[int]:
        """The world's copies (as degrees east) that show: it repeats sideways."""
        s = self._scale()
        half = self.width() / s / 2
        return [k for k in (-360, 0, 360)
                if self.cx - half < 180 + k and self.cx + half > -180 + k]

    def _transform(self) -> QTransform:
        s = self._scale()
        t = QTransform()
        t.translate(self.width() / 2 - self.cx * s, self.height() / 2 + self.cy * s)
        t.scale(s, s)
        return t

    def _screen(self) -> tuple[np.ndarray, np.ndarray]:
        """Each dot's spot on screen: its copy of the world nearest the middle."""
        s = self._scale()
        dx, dy = self._spread()
        return (self.width() / 2 + ((self._lon - self.cx + 180) % 360 - 180) * s + dx,
                self.height() / 2 - (self._lat - self.cy) * s + dy)

    def _spread(self) -> tuple[np.ndarray | float, np.ndarray | float]:
        """Pixels to move each dot by: zoomed in, stations listed at the very same spot
        (often a whole city's, at its centre) fan out so each can be seen and clicked."""
        if self.zoom < SPREAD_ZOOM or not len(self._fan):
            return 0.0, 0.0
        k = SPREAD_PX * self._grow()
        return self._fan[:, 0] * k, self._fan[:, 1] * k

    def _redraw(self):
        """What's drawn changed (stations, land, theme): draw it again (a tile at a
        time, the old tiles showing till then)."""
        self._ver += 1
        self._placed.clear()
        self._town_pm.clear()
        self.update()

    def hideEvent(self, e):
        """Off screen (another tab, the Radio tab's globe instead): after FORGET_MS let
        the tiles go (tens of MB zoomed in). Not at once: flicking between tabs would
        draw them all again on every return, a freeze each time."""
        self._stop_build()
        self._forget.start()
        super().hideEvent(e)

    def showEvent(self, e):
        self._forget.stop()
        super().showEvent(e)

    def _forget_tiles(self):
        if self.isVisible():
            return
        self._stop_build()
        self._tiles.clear()
        self._stable = None
        self._town_pm.clear()

    # ------------------------------------------------------------------ painting
    def _grow(self) -> float:
        return min(2.0, 1 + (self.zoom - 1) * 0.15)   # dots get a little bigger zoomed in

    def _map_steps(self, p: QPainter, tr: QTransform, s: float, rect: QRectF):
        """The sea, grid, land, names and dots, through `tr` ((lon, -lat) degrees to
        pixels), a draw call or so per step; only what falls in `rect` (pixels) is drawn."""
        t = theme.T
        world = tr.mapRect(QRectF(-180, -LAT_TOP, 360, LAT_TOP - LAT_BOTTOM))
        yield from _fill(p, world.intersected(rect), _mix(t["bg"], t["accent"], 0.06))
        p.save()
        p.setClipRect(world.intersected(rect))
        p.setPen(QPen(_mix(t["bg"], t["text"], 0.07), 1))
        for lon in range(-150, 180, 30):
            x = tr.map(QPointF(lon, 0)).x()
            p.drawLine(QPointF(x, world.top()), QPointF(x, world.bottom()))
        for lat in (-30, 0, 30, 60):
            y = tr.map(QPointF(0, -lat)).y()
            p.drawLine(QPointF(world.left(), y), QPointF(world.right(), y))
        if self._land:
            seen = tr.inverted()[0].mapRect(rect.adjusted(-2, -2, 2, 2))   # in degrees
            p.save()
            p.setTransform(tr, True)
            p.setPen(QPen(_mix(t["bg"], t["text"], 0.3), 0.8 / s))
            p.setBrush(_mix(t["bg"], t["text"], 0.14))
            for part, box in zip(self._land, self._land_box):
                if box.intersects(seen):   # a tile: just the land on it
                    p.drawPath(part)
                    yield
            p.restore()
        if len(self._points):
            o = tr.map(QPointF(0, 0))
            dx, dy = self._spread()
            xs, ys = o.x() + self._lon * s + dx, o.y() - self._lat * s + dy
            on = ((xs > rect.left() - 8) & (xs < rect.right() + 8)
                  & (ys > rect.top() - 8) & (ys < rect.bottom() + 8))
            accent = QColor(t["accent"])
            accent.setAlphaF(0.85)
            p.setPen(Qt.NoPen)
            p.setBrush(accent)
            grow = self._grow()
            for k, i in enumerate(np.flatnonzero(on), 1):
                r = self._r[i] * grow
                p.drawEllipse(QPointF(xs[i], ys[i]), r, r)
                if k % 200 == 0:
                    yield
        # country names last, outlined in the land's colour, so the dots don't hide them
        font, colour = self._label_style()
        fm = QFontMetricsF(font)
        halo = QPen(_mix(t["bg"], t["text"], 0.14), 3)
        halo.setJoinStyle(Qt.RoundJoin)
        corner = tr.map(QPointF(-180, -LAT_TOP))
        for box, name in self._place_labels(s):
            box = box.translated(corner)
            if not box.adjusted(-3, -3, 3, 3).intersects(rect):
                continue
            path = QPainterPath()
            path.addText(box.left(), box.top() + fm.ascent(), font, name)
            p.strokePath(path, halo)
            p.fillPath(path, colour)
            yield
        p.restore()

    def _label_style(self) -> tuple[QFont, QColor]:
        font = QFont(self.font())
        font.setPointSizeF(max(7.0, font.pointSizeF() * 0.85))
        font.setWeight(QFont.DemiBold)
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
            fm = QFontMetricsF(self._label_style()[0])
            got = self._placed[key] = list(self._label_boxes(tr, s, whole, fm))
        return got

    def _town_pixmap(self, name: str, dpr: float) -> QPixmap:
        """A city name drawn once, outlined in the land's colour so it reads over the
        dots; after that it's only copied onto the screen."""
        key = (name, dpr)
        pm = self._town_pm.get(key)
        if pm is None:
            t = theme.T
            font = QFont(self.font())
            font.setPointSizeF(max(7.0, font.pointSizeF() * 0.8))
            font.setWeight(QFont.Normal)
            fm = QFontMetricsF(font)
            w, h = fm.horizontalAdvance(name) + 6, fm.height() + 2
            pm = QPixmap(max(1, round(w * dpr)), max(1, round(h * dpr)))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.transparent)
            q = QPainter(pm)
            q.setRenderHint(QPainter.Antialiasing)
            path = QPainterPath()
            path.addText(3, 1 + fm.ascent(), font, name)
            halo = QPen(_mix(t["bg"], t["text"], 0.14), 3)
            halo.setJoinStyle(Qt.RoundJoin)
            q.strokePath(path, halo)
            q.fillPath(path, _mix(t["bg"], t["text"], 0.68))
            q.end()
            self._town_pm[key] = pm
        return pm

    def _paint_towns(self, p: QPainter, dpr: float) -> int:
        """City and town names just above their stations, on top of the map tiles.
        Nothing at all until zoomed in; then only the places in view are looked at, the
        ones with the most stations first, each where it doesn't cover a country's name
        or another town's, and at most TOWNS_IN_VIEW of them: a drag costs a few
        copied pictures. Answers how many it drew."""
        if not len(self._towns) or self.zoom < TOWN_ZOOM:
            return 0
        s = self._scale()
        xs = self.width() / 2 + ((self._tlon - self.cx + 180) % 360 - 180) * s
        ys = self.height() / 2 - (self._tlat - self.cy) * s
        on = np.flatnonzero((xs > -60) & (xs < self.width() + 60)
                            & (ys > 0) & (ys < self.height() + 20))
        if not len(on):
            return 0
        rect = QRectF(self.rect())
        placed = self._place_labels(s)
        taken = []
        for k in self._copies():
            o = self._origin(k, s)
            taken += [b for b in (box.translated(o).adjusted(-2, -1, 2, 1)
                                  for box, _n in placed) if b.intersects(rect)]
        drawn = 0
        for i in on:   # most stations first, like the list
            pm = self._town_pixmap(self._towns[i]["n"], dpr)
            size = pm.deviceIndependentSize()
            box = QRectF(xs[i] - size.width() / 2, ys[i] - 3 - size.height(),
                         size.width(), size.height())
            if any(box.intersects(o) for o in taken):
                continue
            taken.append(box)
            p.drawPixmap(box.topLeft(), pm)
            drawn += 1
            if drawn >= TOWNS_IN_VIEW:
                break
        return drawn

    # ------------------------------------------------------------------ the tiles
    def _origin(self, k: int = 0, s: float | None = None) -> QPointF:
        """Where the world's top-left corner (copy `k`, see _copies) is on screen."""
        s = self._scale() if s is None else s
        return QPointF(self.width() / 2 - (self.cx - k + 180) * s,
                       self.height() / 2 - (LAT_TOP - self.cy) * s)

    def _level(self, zoom: float | None = None) -> tuple:
        """What tiles are drawn for: the scale (pixels per degree; at `zoom`, or the
        view's), the screen's pixel ratio, and what's on the map (_ver)."""
        s = self._scale() if zoom is None else self._scale() / self.zoom * zoom
        return (round(s, 6), self.devicePixelRatioF(), self._ver)

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
        return QRectF(round((o.x() + i * TILE * f) * dpr) / dpr,
                      round((o.y() + j * TILE * f) * dpr) / dpr,
                      min(TILE, w - i * TILE) * f, min(TILE, h - j * TILE) * f)

    def _tile_steps(self, level: tuple, i: int, j: int) -> tuple[QPixmap, object]:
        """A blank tile (i, j) of `level`, and the steps that draw it."""
        s, dpr = level[0], level[1]
        w, h, _nx, _ny = self._grid(level)
        w, h = min(TILE, w - i * TILE), min(TILE, h - j * TILE)
        pm = QPixmap(w, h)
        pm.setDevicePixelRatio(dpr)
        pm.fill(QColor(theme.T["bg"]))

        def steps():
            p = QPainter(pm)
            try:
                p.setRenderHint(QPainter.Antialiasing)
                tr = QTransform()
                tr.translate(180 * s - i * TILE / dpr, LAT_TOP * s - j * TILE / dpr)
                tr.scale(s, s)
                yield from self._map_steps(p, tr, s, QRectF(0, 0, w / dpr, h / dpr))
            finally:
                p.end()
        return pm, steps()

    def _tile_now(self, key: tuple):
        pm, steps = self._tile_steps(*key)
        for _ in steps:
            pass
        self._tiles[key] = pm

    def _stand_in(self, p: QPainter, missing: QRegion, cur: tuple):
        """Over the tiles not drawn yet: the other levels' tiles, stretched, the
        coarsest first (the whole world zoomed out, BASE_ZOOM) and the sharpest on top."""
        p.save()
        p.setClipRegion(missing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        view = QRectF(self.rect())
        for level in sorted({key[0] for key in self._tiles} - {cur},
                            key=lambda lv: (lv[1] == cur[1], lv[0], lv[2])):
            for k, i, j in self._slots(level):
                pm = self._tiles.get((level, i, j))
                if pm is None:
                    continue
                target = self._tile_rect(level, k, i, j)
                shown = target.intersected(view)
                if shown.isEmpty():
                    continue
                fx, fy = pm.width() / target.width(), pm.height() / target.height()
                p.drawPixmap(shown, pm, QRectF((shown.left() - target.left()) * fx,
                                               (shown.top() - target.top()) * fy,
                                               shown.width() * fx, shown.height() * fy))
        p.restore()

    def _plan(self, cur: tuple, complete: bool):
        """After a paint: let go of the tiles no longer needed, and line up the ones
        to draw next (the view's, middle first; the whole world zoomed out, the
        stand-in for the rest; the ring round the view, ready for a drag)."""
        if complete:
            self._stable = cur
        base = self._level(BASE_ZOOM)
        base_done = all((base, i, j) in self._tiles for i, j in self._all_tiles(base))
        ahead = self._slots(cur, TILE_RING)
        keep = {(cur, i, j) for _k, i, j in ahead}
        for key in list(self._tiles):
            level = key[0]
            if (key in keep or level == base or level == self._stable
                    or (not base_done and level[0] == base[0])):   # the old stand-in
                continue
            del self._tiles[key]
        if self._settle.isActive() or not self.isVisible():
            self._queue = []   # still zooming: nothing's drawn till it stops
            return
        mid = QPointF(self.width() / 2, self.height() / 2)

        def far(slot):
            c = self._tile_rect(cur, *slot).center() - mid
            return abs(c.x()) + abs(c.y())

        want = [(cur, i, j) for _k, i, j in sorted(self._slots(cur), key=far)]
        want += [(base, i, j) for i, j in self._all_tiles(base)]
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
        live = (self._level(), self._level(BASE_ZOOM))
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

    def paintEvent(self, _e):
        self._clamp()
        dpr = self.devicePixelRatioF()
        p = QPainter(self)
        t = theme.T
        p.fillRect(self.rect(), QColor(t["bg"]))
        cur = self._level()
        slots = self._slots(cur)
        # nothing to stand in (the first time): just the sea and the dots, the land
        # comes in a slice at a time a moment later; nothing waits for all of it
        shown, missing = [], QRegion()
        for k, i, j in slots:
            pm = self._tiles.get((cur, i, j))
            r = self._tile_rect(cur, k, i, j)
            if pm is None:
                missing += r.toAlignedRect()
            else:
                shown.append((r.topLeft(), pm))
        if not missing.isEmpty():
            self._stand_in(p, missing, cur)
        for at, pm in shown:
            p.drawPixmap(at, pm)
        self._plan(cur, missing.isEmpty())
        self._paint_towns(p, dpr)
        p.setRenderHint(QPainter.Antialiasing)
        hover, cur_i = self._hover, self._index.get(self._current, -1)
        if (0 <= hover < len(self._points)) or cur_i >= 0:
            xs, ys = self._screen()
            if 0 <= hover < len(self._points):
                r = self._r[hover] * self._grow() + 2
                p.setPen(QPen(QColor(t["text_hi"]), 1.5))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QPointF(xs[hover], ys[hover]), r, r)
            if cur_i >= 0:
                hot = QColor(t["accent2"])
                c = QPointF(xs[cur_i], ys[cur_i])
                p.setPen(QPen(hot, 2))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(c, 9, 9)
                p.setPen(QPen(QColor(t["bg"]), 1.5))
                p.setBrush(hot)
                p.drawEllipse(c, 5, 5)
        if self._msg:   # on a card of its own, not over the country names
            area = QRectF(self.rect().adjusted(24, 24, -24, -24))
            flags = Qt.AlignCenter | Qt.TextWordWrap
            box = p.boundingRect(area, flags, self._msg).adjusted(-14, -8, 14, 8)
            p.setPen(QPen(QColor(t["border"]), 1))
            p.setBrush(QColor(t["card"]))
            p.drawRoundedRect(box, 8, 8)
            p.setPen(QColor(t["text"]))
            p.drawText(area, flags, self._msg)
        p.end()

    # ------------------------------------------------------------------ input
    def _hit(self, pos: QPointF) -> int:
        if not len(self._points):
            return -1
        xs, ys = self._screen()
        d = np.hypot(xs - pos.x(), ys - pos.y())
        i = int(np.argmin(d))
        return i if d[i] <= HIT_PX + self._r[i] else -1

    def _zoom_by(self, f: float, at: QPointF | None = None):
        s0 = self._scale()
        at = at or QPointF(self.width() / 2, self.height() / 2)
        # keep the place under the pointer where it is
        lon = self.cx + (at.x() - self.width() / 2) / s0
        lat = self.cy - (at.y() - self.height() / 2) / s0
        self.zoom = min(ZOOM_MAX, max(1.0, self.zoom * f))
        s1 = self._scale()
        self.cx = lon - (at.x() - self.width() / 2) / s1
        self.cy = lat + (at.y() - self.height() / 2) / s1
        self.update()

    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120.0
        if steps:
            self._settle.start()
            self._zoom_by(1.25 ** steps, e.position())
        e.accept()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.position()
            self._dragged = False

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            d = pos - self._drag
            if self._dragged or abs(d.x()) + abs(d.y()) > 3:
                self._dragged = True
                s = self._scale()
                self.cx -= d.x() / s
                self.cy += d.y() / s
                self._drag = pos
                self.setCursor(Qt.ClosedHandCursor)
                QToolTip.hideText()
                self.update()
            return
        i = self._hit(pos)
        if i != self._hover:
            self._hover = i
            self.setCursor(Qt.PointingHandCursor if i >= 0 else Qt.ArrowCursor)
            if i >= 0:
                QToolTip.showText(e.globalPosition().toPoint(), self._tip(self._points[i]), self)
            else:
                QToolTip.hideText()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        dragged, self._drag = self._dragged, None
        self.unsetCursor()
        if not dragged:
            i = self._hit(e.position())
            if i >= 0:
                self.clicked.emit(self._points[i]["id"])

    def mouseDoubleClickEvent(self, e):
        if self._hit(e.position()) < 0:   # the empty map: back to the whole world
            self.zoom = 1.0
            self.update()

    def leaveEvent(self, e):
        super().leaveEvent(e)
        if self._hover >= 0:
            self._hover = -1
            self.update()

    def _tip(self, d: dict) -> str:
        # everything from the directory is escaped: it's community-edited
        where = ", ".join(html.escape(x) for x in (d.get("s"), d.get("c")) if x)
        lines = [f"<b>{html.escape(d.get('n', ''))}</b>"]
        if where:
            lines.append(where)
        tags = ", ".join(html.escape(t) for t in (d.get("t") or [])[:4])
        if tags:
            lines.append(tags)
        audio = " · ".join(x for x in (f"{d['b']} kbps" if d.get("b") else "",
                                       html.escape(d.get("co") or "")) if x)
        if audio:
            lines.append(audio)
        if d.get("k"):
            lines.append(f"{int(d['k']):,} plays today")
        lines.append("▶ Playing now" if d.get("id") == self._current else "Click to play")
        return "<br>".join(lines)

