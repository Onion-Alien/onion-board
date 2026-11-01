"""The Radio tab's world map, painted by Qt itself.

A plain map (land outlines, country names, a dot per station and, zoomed in, the
names of the cities and towns in view that have stations) costs nothing while
it sits there: it only repaints when you drag, zoom, hover over a different dot or the
stations change, and it needs no web engine. The land and the country names are drawn
in tiles (TILE device pixels square), each once per zoom: a drag or a repaint only
copies the tiles in view, at any zoom. Tiles not drawn yet (a new zoom, a drag onto new
ground) are drawn a slice at a time while the last whole view, put together into one
picture and stretched, stands in for them (tiles stretched one by one showed their
seams, a grid over the map); a new zoom shows only once all of it is drawn. Under
that, the land of the whole world, small.

The stations are not on the tiles. They're drawn over them on every paint, each dot a
picture drawn once and copied (_sprite): all 3000 in view are ~1.5 ms, zoomed in only
the few in view. So they're sharp and in place at every zoom, mid-zoom too, and the
same size at every zoom: zooming in only ever moves them further apart. Stations at
the same spot are fanned out once, when they come (set_points, _spread_out). The
country names show first, then (NAMES_FIRST_S on) the stations fade in (REVEAL_S);
Bun waits on the map till they come.

Stations arrive as radio.globe_points() dicts (the name is from the 3D globe this map
replaced).

The tiles (maptiles.py) and the country names (maplabels.py) are FlatMap's mixins; the
loading card, dot sizes and colour helpers are in mapparts.py.
"""
from __future__ import annotations

import html
import math
import time
from collections import deque

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen,
                           QPixmap, QTransform)
from PySide6.QtWidgets import QPushButton, QToolTip, QVBoxLayout, QWidget

from soundboard.ui.kit import theme
from soundboard.i18n import _, ngettext
from soundboard.ui.kit import oops
from soundboard.ui.kit.pixels import snap_to_pixels
from soundboard.ui.radio.mapparts import (LAT_BOTTOM, LAT_TOP, SPREAD_S, _fill, _glow_image,
                                          _Loading, _mix, _sizes, _spread_out)
from soundboard.ui.radio.maptiles import SLICE_GAP_MS, MapTiles
from soundboard.ui.radio.maplabels import MapLabels
# (callers import these from here too)
from soundboard.ui.radio.mapparts import (FILL_PX, HOT_MIN, HOT_R, HOT_SHARE,  # noqa: F401
                                          LOADING_TEXT, QUIET_R)
from soundboard.ui.radio.maptiles import BASE_ZOOM, SLICE_S, TILE, TILE_RING  # noqa: F401
from soundboard.ui.radio.maplabels import LABEL_GROW_MAX  # noqa: F401

ZOOM_MAX = 250.0                    # about street level: a city's stations come apart
HIT_PX = 7.0                        # how near the pointer a dot counts as under it
LAND_PART = 400                     # outline points per drawn part (set_land)
# The parts are made one a step with this long a rest between (set_land). All ~30 in
# one go were 10-40 ms of back-to-back Qt calls on opening the Radio tab, and the audio
# threads wait on them: a sound playing came up to 33 ms late, a skip.
STEP_GAP_MS = 4
FORGET_MS = 60_000   # hidden this long: let the drawn tiles go (back sooner: no redraw)
SETTLE_MS = 120                     # zooming: the old tiles, stretched, until this idle
TOWN_ZOOM = 2.0                     # city and town names show from this zoom in...
TOWNS_IN_VIEW = 40                  # ...at most this many at once, only those in view
TOWN_SLICE_S = 0.0015               # new names drawn a paint, then the rest a moment later
GLOW = 2.2                          # the glow round a popular dot, times its size
NAMES_FIRST_S = 0.35                # the country names alone, before the dots...
REVEAL_S = 0.5                      # ...then the first stations fade in over this long
CORNER_PX = 12                      # the map's rounded corners (like QFrame#stations)


class FlatMap(MapTiles, MapLabels, QWidget):
    clicked = Signal(str)       # a station's uuid
    retry = Signal()            # Try again on the red card (the station list once more)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(120, 80)   # not opaque: the rounded corners show what's behind
        self._land: list[QPainterPath] = []   # in (lon, -lat) degrees, in parts (set_land)
        self._land_box: list[QRectF] = []     # each part's bounds: a tile skips the rest
        self._labels: list[tuple[str, float, float, float]] = []   # name, lon, lat, width°
        self._towns: list[dict] = []    # radio.town_labels(): the places with stations
        self._tlon = np.zeros(0)
        self._tlat = np.zeros(0)
        self._town_pm: dict[tuple, QPixmap] = {}   # each name drawn once, outlined
        self._town_box: dict[tuple, QSizeF] = {}   # ...and its size, known before that
        self._points: list[dict] = []
        self._index: dict[str, int] = {}   # a station's place in _points, by uuid
        self._lon = np.zeros(0)
        self._lat = np.zeros(0)
        self._r = np.zeros(0)           # dot radius, pixels (_sizes)
        self._hot = np.zeros(0, bool)   # ...and which glow: the most listened
        self._off = np.zeros((0, 2))    # pixels each dot is moved by at SPREAD_S (_screen)
        self._buf: QImage | None = None  # the map drawn before its corners are rounded
        self._look: tuple | None = None  # (colours, quiet, hot, glow picture): _dot_look
        self._sprites: dict[tuple, QPixmap] = {}   # each dot size drawn once (_sprite)
        self._current: str | None = None
        self._hover = -1
        self._msg = ""
        self.zoom = 1.0
        self.cx, self.cy = 10.0, (LAT_TOP + LAT_BOTTOM) / 2   # the view's centre (lon, lat)
        self._drag: QPointF | None = None
        self._dragged = False
        self._land_ver = 0                # bumped when the land (or its colours) changes
        self._tiles: dict[tuple, QPixmap] = {}   # (level, i, j): see _level
        # the last view drawn all over: (level, its slots), put together on demand into
        # one picture (_pics) that stands in, stretched, while a new one is drawn
        self._stable: tuple | None = None
        self._pics: dict[tuple, tuple] = {}      # (level, slots): (picture, x, y)
        self._placed: dict[float, list] = {}     # country names' places, per scale
        self._label_pm: dict[tuple, QPixmap] = {}  # ...and each drawn once (_label_pixmap)
        self._reveal_t0: float | None = None     # when the first stations fade in (REVEAL_S)
        self._reveal_wait = False                # ...stations came before the land did
        self._land_set = False
        self._rings: deque[list] = deque()          # outlines still to make parts of
        self._land_new: list[QPainterPath] = []     # ...and the parts made so far
        self._land_steps = QTimer(self)             # makes the next part (_land_step)
        self._land_steps.setSingleShot(True)
        self._land_steps.setTimerType(Qt.TimerType.PreciseTimer)
        self._land_steps.timeout.connect(self._land_step)
        self._reveal = QTimer(self)
        self._reveal.setInterval(1000 // 30)   # a short fade: 30 fps is plenty
        self._reveal.timeout.connect(self._reveal_step)
        self._settle = QTimer(self)       # running while the wheel is still zooming
        self._settle.setSingleShot(True)
        self._settle.setInterval(SETTLE_MS)
        self._settle.timeout.connect(self.update)
        self._queue: list[tuple] = []     # tiles to draw next, the most wanted first
        self._build: tuple | None = None  # (tile, picture, its steps): being drawn
        self._slice = QTimer(self)        # draws the next slice of it
        self._slice.setSingleShot(True)
        self._slice.setTimerType(Qt.TimerType.PreciseTimer)
        self._slice.setInterval(SLICE_GAP_MS)
        self._slice.timeout.connect(self._draw_slice)
        self._towns_later = QTimer(self)  # town names left for the next paint
        self._towns_later.setSingleShot(True)
        self._towns_later.setTimerType(Qt.TimerType.PreciseTimer)
        self._towns_later.setInterval(SLICE_GAP_MS)
        self._towns_later.timeout.connect(self.update)
        self._forget = QTimer(self)       # hidden a while: let the drawn tiles go
        self._forget.setSingleShot(True)
        self._forget.setInterval(FORGET_MS)
        self._forget.timeout.connect(self._forget_tiles)

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 10, 10)
        box.addStretch(1)
        self._buttons = []
        for text, tip, slot in (("+", _("Zoom in"), lambda: self._zoom_by(1.5)),
                                ("−", _("Zoom out"), lambda: self._zoom_by(1 / 1.5))):
            b = QPushButton(text)
            b.setObjectName("mapbtn")
            b.setAccessibleName(tip)
            b.setFixedSize(30, 30)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(slot)
            box.addWidget(b, 0, Qt.AlignmentFlag.AlignRight)
            self._buttons.append(b)
        self._loading = _Loading(self)   # until the stations come (set_points)
        self.oops = oops.OopsPanel(self)   # ... or why they can't (show_message)
        self.oops.hide()
        self.set_theme()

    # ------------------------------------------------------------------ what's shown
    def set_land(self, rings: list, labels: list | None = None):
        """The countries' outlines, and their names: (name, lon, lat, width in degrees),
        each shown once there's room for it at the zoom."""
        self._labels = sorted(labels or [], key=lambda x: -x[3])   # big countries first
        # in parts of a few hundred points: Qt holds Python's lock while it draws a
        # path, and the whole world in one took 10-30 ms, long enough to hold up the
        # audio threads (a sound skipped each time the map was redrawn at a new zoom).
        # A part takes about 1 ms, and all of them less than the one did. They're made
        # one a step too (STEP_GAP_MS), and shown once they're all made.
        self._rings = deque(rings)
        self._land_new = []
        self._land_steps.stop()
        self._land_step()   # the first at once: a small map (or none) is done here

    def _land_step(self):
        """The next part of the land (set_land); the last one puts them all on the map."""
        path, n = QPainterPath(), 0
        path.setFillRule(Qt.FillRule.WindingFill)
        while self._rings and (n == 0 or n + len(self._rings[0]) <= LAND_PART):
            ring = self._rings.popleft()
            path.moveTo(ring[0][0], -ring[0][1])
            for x, y in ring[1:]:
                path.lineTo(x, -y)
            path.closeSubpath()
            n += len(ring)
        if n:
            self._land_new.append(path)
        if self._rings:
            self._land_steps.start(STEP_GAP_MS)
            return
        self._land = self._land_new
        self._land_box = [part.boundingRect() for part in self._land]
        self._land_ver += 1
        self._land_set = True
        if self._reveal_wait:   # the stations came first: their fade-in waited for this
            self._start_reveal()
        self._redraw()

    def set_points(self, points: list[dict]):
        # the least listened first, so the popular dots are drawn on top
        pts = sorted(points, key=lambda d: d.get("k", 0))
        first = bool(pts) and not self._points
        self._points = pts
        self._index = {d["id"]: i for i, d in enumerate(pts)}
        self._lon = np.array([d["lo"] for d in pts], float)
        self._lat = np.array([d["la"] for d in pts], float)
        k = np.array([d.get("k", 0) for d in pts], float)
        self._r, self._hot = _sizes(k)
        self._off = _spread_out(self._lon * SPREAD_S, -self._lat * SPREAD_S, self._r)
        self._hover = -1
        if pts:
            self._msg = ""
            self.oops.hide()
            self._loading.hide()
        if first:
            if self._land_set:
                self._start_reveal()
            else:   # the land and its names first, then the dots
                self._reveal_wait = True
        self.update()

    def _start_reveal(self):
        """The country names show on their own for NAMES_FIRST_S, then the dots fade in."""
        self._reveal_wait = False
        self._reveal_t0 = time.monotonic() + NAMES_FIRST_S
        self._reveal.start()

    def revealing(self) -> bool:
        """The first stations still to fade in, or fading in (REVEAL_S)."""
        return self._reveal_t0 is not None or self._reveal_wait

    def _reveal_step(self):
        if self._reveal_t0 is None or time.monotonic() - self._reveal_t0 >= REVEAL_S:
            self._reveal_t0 = None
            self._reveal.stop()
        self.update()

    def set_towns(self, towns: list[dict]):
        """City and town names (radio.town_labels(), most stations first), shown once
        zoomed in: the ones with the most stations get first claim on the space."""
        self._towns = list(towns)
        self._tlon = np.array([t["lo"] for t in self._towns], float)
        self._tlat = np.array([t["la"] for t in self._towns], float)
        if len(self._town_pm) > 4 * len(self._towns) + 200:
            self._town_pm.clear()   # names the filters no longer show
            self._town_box.clear()
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
        """Why there are no stations (the list can't be fetched): the red card with sad
        Bun says it, with Try again (`retry`); "" takes it away."""
        self._msg = text
        if text:
            self.oops.show_problem(_("The radio couldn't connect"),
                                   html.escape(text, quote=False), self.retry.emit)
            self._loading.hide()
        self.oops.setVisible(bool(text))
        self._place_loading()
        self.update()

    def set_loading(self, on: bool):
        """Bun waiting on the map for the stations (on from the start; the first
        stations take him away). Not under the red card (show_message)."""
        self._loading.setVisible(not self._msg and on and not self._points)
        self._place_loading()

    def set_theme(self, *_):
        t = theme.T
        self.setStyleSheet(
            f"QPushButton#mapbtn {{ border-radius:8px; border:1px solid {t['border']};"
            f" background:{t['map_btn']}; color:{t['text']}; font-weight:600; padding:0; }}"
            f" QPushButton#mapbtn:hover {{ border-color:{t['accent']}; }}"
            f" QFrame#maploader {{ border-radius:14px; border:1px solid {t['border']};"
            f" background:{t['card']}; }}"
            f" QLabel#maploadertext {{ color:{t['text']}; font-weight:600;"
            f" background:transparent; }}")
        self._land_ver += 1
        self._redraw()

    def _place_loading(self):
        w = self._loading
        size = w.sizeHint()
        width = min(size.width(), max(120, self.width() - 32))
        w.setGeometry((self.width() - width) // 2, (self.height() - size.height()) // 2,
                      width, size.height())
        if self.oops.isVisibleTo(self):
            o = self.oops
            ow = min(oops.MAX_W, max(200, self.width() - 32))
            o.setFixedWidth(ow)
            o.fit_height(self.height() - 24)
            oh = min(o.height_for(ow), max(60, self.height() - 16))
            o.setGeometry((self.width() - ow) // 2, max(8, (self.height() - oh) // 2), ow, oh)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_loading()

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

    def _screen(self) -> tuple[np.ndarray, np.ndarray]:
        """Each dot's spot on screen: its copy of the world nearest the middle, moved
        off any dot it would cover (_off). Zoomed out from SPREAD_S the move shrinks
        with the map, so a city's dots close up into one spot on the whole world;
        zoomed in from it, it grows (slower than the map), so they keep coming apart."""
        s = self._scale()
        f = s / SPREAD_S if s < SPREAD_S else (s / SPREAD_S) ** 0.3
        return (self.width() / 2 + ((self._lon - self.cx + 180) % 360 - 180) * s
                + self._off[:, 0] * f,
                self.height() / 2 - (self._lat - self.cy) * s + self._off[:, 1] * f)

    def _redraw(self):
        """The land, its names or the theme changed: draw it again (a tile at a time,
        the old tiles showing till then)."""
        self._placed.clear()
        self._label_pm.clear()
        self._town_pm.clear()
        self._town_box.clear()
        self.update()

    def hideEvent(self, e):
        """Off screen (another tab): after FORGET_MS let the tiles go (tens of MB
        zoomed in). Not at once: flicking between tabs would draw them all again on
        every return, a freeze each time."""
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
        base = self._base_level()   # a few MB: kept, so there's a map the moment it's back
        self._tiles = {key: pm for key, pm in self._tiles.items() if key[0] == base}
        self._pics = {key: pic for key, pic in self._pics.items() if key[0] == base}
        self._stable = None
        self._label_pm.clear()
        self._town_pm.clear()
        self._town_box.clear()

    # ------------------------------------------------------------------ painting
    def _dot_look(self) -> tuple[QColor, QColor, QImage]:
        """The dots' colours for the theme: a quiet station's, a popular one's (the
        accent, lit up towards the brightest text: whiter on a dark theme, deeper on
        a light one) and the glow round it."""
        accent, hi = theme.T["accent"], theme.T["text_hi"]
        if self._look is None or self._look[0] != (accent, hi):
            quiet = QColor(accent)
            quiet.setAlphaF(0.8)
            self._look = ((accent, hi), quiet, _mix(accent, hi, 0.3),
                          _glow_image(QColor(accent)))
            self._sprites.clear()
        return self._look[1:]

    def _sprite(self, hot: bool, r: float, dpr: float) -> QPixmap:
        """A dot `r` pixels big (a popular one with its glow round it), drawn once
        for the theme; the map only copies it."""
        quiet, lit, glow = self._dot_look()
        key = (hot, r, dpr)
        pm = self._sprites.get(key)
        if pm is None:
            g = r * GLOW if hot else r
            side = max(1, math.ceil((2 * g + 2) * dpr))
            pm = QPixmap(side, side)
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.GlobalColor.transparent)
            q = QPainter(pm)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            q.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            c = side / dpr / 2
            if hot:
                q.drawImage(QRectF(c - g, c - g, 2 * g, 2 * g), glow, QRectF(glow.rect()))
            q.setPen(Qt.PenStyle.NoPen)
            q.setBrush(lit if hot else quiet)
            q.drawEllipse(QPointF(c, c), r, r)
            q.end()
            self._sprites[key] = pm
        return pm

    def _paint_dots(self, p: QPainter, dpr: float):
        """The stations in view, over the tiles: the quiet ones, then the popular ones
        (biggest last) on top. A copied picture a dot, on a device pixel."""
        if not len(self._points) or self._reveal_wait:
            return
        fade = 1.0
        if self._reveal_t0 is not None:   # the first stations fading in
            fade = min(1.0, (time.monotonic() - self._reveal_t0) / REVEAL_S)
            if fade <= 0:
                return
        xs, ys = self._screen()
        pad = self._r * np.where(self._hot, GLOW, 1.0) + 2
        on = ((xs > -pad) & (xs < self.width() + pad)
              & (ys > -pad) & (ys < self.height() + pad))
        size = np.round(self._r * 4) / 4   # a picture for every quarter pixel of size
        p.save()
        try:
            p.setOpacity(fade)
            for hot in (False, True):
                part = on & (self._hot == hot)
                for r in np.unique(size[part]).tolist():
                    which = part & (size == r)
                    pm = self._sprite(hot, r, dpr)
                    half = pm.width() / dpr / 2
                    for x, y in zip((np.round((xs[which] - half) * dpr) / dpr).tolist(),
                                    (np.round((ys[which] - half) * dpr) / dpr).tolist()):
                        p.drawPixmap(QPointF(x, y), pm)
        finally:
            p.restore()

    def _map_steps(self, p: QPainter, tr: QTransform, s: float, rect: QRectF):
        """The sea and land,
        through `tr` ((lon, -lat) degrees to pixels), a draw call or so per step; only
        what falls in `rect` (pixels) is drawn."""
        t = theme.T
        world = tr.mapRect(QRectF(-180, -LAT_TOP, 360, LAT_TOP - LAT_BOTTOM))
        # no lines of latitude and longitude: stretched while zooming they read as a
        # grid laid over the map
        yield from _fill(p, world.intersected(rect), _mix(t["bg"], t["accent"], 0.06))
        p.save()
        # try/finally: a tile dropped half-drawn (_drop_build closes this generator at a
        # yield) must leave its painter balanced, or ending it warns about saved states
        try:
            p.setClipRect(world.intersected(rect))
            if self._land:
                seen = tr.inverted()[0].mapRect(rect.adjusted(-2, -2, 2, 2))   # in degrees
                p.save()
                try:
                    p.setTransform(tr, True)
                    p.setPen(QPen(_mix(t["bg"], t["text"], 0.3), 0.8 / s))
                    p.setBrush(_mix(t["bg"], t["text"], 0.14))
                    for part, box in zip(self._land, self._land_box):
                        if box.intersects(seen):   # a tile: just the land on it
                            p.drawPath(part)
                            yield
                finally:
                    p.restore()
        finally:
            p.restore()

    def _town_font(self) -> QFont:
        font = QFont(self.font())
        font.setPointSizeF(max(7.0, font.pointSizeF() * 0.8))
        font.setWeight(QFont.Weight.Normal)
        return font

    def _town_size(self, name: str, dpr: float) -> QSizeF:
        """How big _town_pixmap's picture of `name` is, without drawing it (a city
        name that won't fit isn't drawn at all)."""
        key = (name, dpr)
        size = self._town_box.get(key)
        if size is None:
            fm = QFontMetricsF(self._town_font())
            w, h = fm.horizontalAdvance(name) + 6, fm.height() + 2
            size = self._town_box[key] = QSizeF(max(1, round(w * dpr)) / dpr,
                                                max(1, round(h * dpr)) / dpr)
        return size

    def _town_pixmap(self, name: str, dpr: float) -> QPixmap:
        """A city name drawn once, outlined in the land's colour so it reads over the
        dots; after that it's only copied onto the screen."""
        key = (name, dpr)
        pm = self._town_pm.get(key)
        if pm is None:
            t = theme.T
            font = self._town_font()
            fm = QFontMetricsF(font)
            size = self._town_size(name, dpr)
            pm = QPixmap(round(size.width() * dpr), round(size.height() * dpr))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.GlobalColor.transparent)
            q = QPainter(pm)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            path = QPainterPath()
            path.addText(3, 1 + fm.ascent(), font, name)
            halo = QPen(_mix(t["bg"], t["text"], 0.14), 3)
            halo.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
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
        copied pictures. Answers how many it drew.

        Only the names that fit are drawn (each measured first): drawing every town
        in view, Europe's hundreds, took 80 ms in one paint as the zoom passed
        TOWN_ZOOM, and the sound playing skipped (Qt holds Python's lock through each
        call, and the audio threads wait on it). New names get about TOWN_SLICE_S a
        paint; the rest keep their place and come a moment later."""
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
        drawn, placed, later = 0, 0, False
        end = time.perf_counter() + TOWN_SLICE_S
        for i in on:   # most stations first, like the list
            name = self._towns[i]["n"]
            size = self._town_size(name, dpr)
            box = QRectF(xs[i] - size.width() / 2, ys[i] - 3 - size.height(),
                         size.width(), size.height())
            if any(box.intersects(o) for o in taken):
                continue
            taken.append(box)   # its place is kept even when it's drawn next time
            placed += 1
            pm = self._town_pm.get((name, dpr))
            if pm is None and time.perf_counter() > end:
                later = True
            else:
                p.drawPixmap(box.topLeft(), pm or self._town_pixmap(name, dpr))
                drawn += 1
            if placed >= TOWNS_IN_VIEW:
                break
        if later:
            self._towns_later.start()
        return drawn

    def paintEvent(self, _e):
        # Rounded like the stations card beside it. A clip path or a widget mask is
        # all-or-nothing per pixel, so its corners come out as stairs: draw the map
        # into a picture, cut the corners out of that with a smooth (antialiased)
        # rounded shape, then put the picture on screen.
        self._clamp()
        dpr = self.devicePixelRatioF()
        size = self.size() * dpr
        buf = self._buf
        if buf is None or buf.size() != size or buf.devicePixelRatio() != dpr:
            buf = self._buf = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
            buf.setDevicePixelRatio(dpr)
        buf.fill(Qt.GlobalColor.transparent)
        q = QPainter(buf)
        self._paint(q, dpr)
        corners = QPainterPath()   # odd-even fill: the box minus the rounded card
        corners.addRect(QRectF(self.rect()))
        corners.addRoundedRect(QRectF(self.rect()), CORNER_PX, CORNER_PX)
        q.setRenderHint(QPainter.RenderHint.Antialiasing)
        q.setClipping(False)
        q.resetTransform()
        q.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
        q.fillPath(corners, QColor(0, 0, 0))
        q.end()
        p = QPainter(self)
        snap_to_pixels(p)
        p.drawImage(0, 0, buf)
        p.end()

    def _paint(self, p: QPainter, dpr: float):
        t = theme.T
        p.fillRect(self.rect(), QColor(t["bg"]))
        cur = self._level()
        slots = self._slots(cur)
        shown = [(self._tile_rect(cur, k, i, j), self._tiles.get((cur, i, j)))
                 for k, i, j in slots]
        complete = all(pm is not None for _at, pm in shown)
        if complete:
            for at, pm in shown:
                if pm is not None:   # (all of them: complete)
                    p.drawPixmap(at, pm, QRectF(pm.rect()))
        else:
            # a new zoom shows all at once when it's all drawn, never a patchwork of
            # sharp and stretched squares; till then the last view
            self._stand_in(p)
            if self._stable is not None and self._stable[0] == cur:
                for at, pm in shown:   # the same zoom, dragged: the tiles there are
                    if pm is not None:
                        p.drawPixmap(at, pm, QRectF(pm.rect()))
        self._plan(cur, slots, complete)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._paint_dots(p, dpr)
        self._paint_labels(p, dpr)
        self._paint_towns(p, dpr)
        cur = self._current
        hover, cur_i = self._hover, self._index.get(cur, -1) if cur is not None else -1
        if (0 <= hover < len(self._points)) or cur_i >= 0:
            xs, ys = self._screen()
            if 0 <= hover < len(self._points):
                r = self._r[hover] + 2
                p.setPen(QPen(QColor(t["text_hi"]), 1.5))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(xs[hover], ys[hover]), r, r)
            if cur_i >= 0:
                hot = QColor(t["accent2"])
                c = QPointF(float(xs[cur_i]), float(ys[cur_i]))
                p.setPen(QPen(hot, 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, 9, 9)
                p.setPen(QPen(QColor(t["bg"]), 1.5))
                p.setBrush(hot)
                p.drawEllipse(c, 5, 5)

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
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.position()
            self._dragged = False

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
            d = pos - self._drag
            if self._dragged or abs(d.x()) + abs(d.y()) > 3:
                self._dragged = True
                s = self._scale()
                self.cx -= d.x() / s
                self.cy += d.y() / s
                self._drag = pos
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                QToolTip.hideText()
                self.update()
            return
        i = self._hit(pos)
        if i != self._hover:
            self._hover = i
            self.setCursor(Qt.CursorShape.PointingHandCursor if i >= 0
                           else Qt.CursorShape.ArrowCursor)
            if i >= 0:
                QToolTip.showText(e.globalPosition().toPoint(), self._tip(self._points[i]), self)
            else:
                QToolTip.hideText()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
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
            lines.append(ngettext("{n} play today", "{n} plays today", int(d["k"]),
                                  n=f"{int(d['k']):,}"))
        lines.append("▶ " + _("Playing now") if d.get("id") == self._current
                     else _("Click to play"))
        return "<br>".join(lines)

