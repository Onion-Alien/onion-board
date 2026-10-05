"""The Radio tab's flat world map: the default view, painted by Qt itself.

A plain map (land outlines, country names, a dot per station and, zoomed in, the
names of the cities and towns in view that have stations) costs nothing while
it sits there: it only repaints when you drag, zoom, hover over a different dot or the
stations change, and it needs no web engine. The whole world is drawn once per zoom
level and a drag only slides that picture; zoomed in too far for one picture, just
the part in view is drawn (there's little of it then). The 3D globe
(radio.globe_html) is the HD view, one click away on the map's HD button.

Stations arrive as radio.globe_points() dicts, like the globe's, so the tab can
feed either view the same way.
"""
from __future__ import annotations

import html

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen,
                           QPixmap, QTransform)
from PySide6.QtWidgets import QPushButton, QToolTip, QVBoxLayout, QWidget

from soundboard import theme

LAT_TOP, LAT_BOTTOM = 84.0, -58.0   # the inhabited world: no polar wastes
ZOOM_MAX = 250.0                    # about street level: a city's stations come apart
HIT_PX = 7.0                        # how near the pointer a dot counts as under it
LAND_PART = 400                     # outline points per drawn part (set_land)
FILL_PX = 1_000_000                 # device pixels per filled band (_fill)
WORLD_MAX_PX = 10_000_000           # biggest whole-world picture kept (device pixels)
SETTLE_MS = 160                     # zooming: the old picture, stretched, until this idle
TOWN_ZOOM = 2.0                     # city and town names show from this zoom in...
TOWNS_IN_VIEW = 40                  # ...at most this many at once, only those in view
SPREAD_ZOOM = 4.0                   # stations on the very same spot fan out from here...
SPREAD_PX = 2.4                     # ...this far apart (a spiral round the spot)


def _fill(p: QPainter, rect: QRectF, colour: QColor):
    """p.fillRect in bands of about FILL_PX device pixels: Qt keeps Python's lock while
    it fills, and the whole world picture in one go held up the audio for ~10 ms."""
    dpr = p.device().devicePixelRatioF()
    band = max(1.0, FILL_PX / max(1.0, rect.width() * dpr * dpr))
    y = rect.top()
    while y < rect.bottom():
        h = min(band, rect.bottom() - y)
        p.fillRect(QRectF(rect.left(), y, rect.width(), h), colour)
        y += h


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
        self._labels: list[tuple[str, float, float, float]] = []   # name, lon, lat, width°
        self._towns: list[dict] = []    # radio.town_labels(): the places with stations
        self._tlon = np.zeros(0)
        self._tlat = np.zeros(0)
        self._town_pm: dict[tuple, QPixmap] = {}   # each name drawn once, outlined
        self._points: list[dict] = []
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
        self._world: tuple | None = None  # (key, the whole world at this zoom)
        self._view: tuple | None = None   # (key, just the part in view): zoomed far in
        self._settle = QTimer(self)       # running while the wheel is still zooming
        self._settle.setSingleShot(True)
        self._settle.setInterval(SETTLE_MS)
        self._settle.timeout.connect(self.update)

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
        self._redraw()

    def set_points(self, points: list[dict]):
        # the least listened first, so the popular dots are drawn on top
        pts = sorted(points, key=lambda d: d.get("k", 0))
        self._points = pts
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
        if point and not any(d["id"] == point["id"] for d in self._points):
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
        """What's drawn changed (stations, land, theme): draw it again."""
        self._ver += 1
        self._world = self._view = None
        self._town_pm.clear()
        self.update()

    # ------------------------------------------------------------------ painting
    def _grow(self) -> float:
        return min(2.0, 1 + (self.zoom - 1) * 0.15)   # dots get a little bigger zoomed in

    def _paint_map(self, p: QPainter, tr: QTransform, s: float, rect: QRectF):
        """The sea, grid, land, names and dots, through `tr` ((lon, -lat) degrees to
        pixels); only what falls in `rect` (pixels) matters."""
        t = theme.T
        world = tr.mapRect(QRectF(-180, -LAT_TOP, 360, LAT_TOP - LAT_BOTTOM))
        _fill(p, world.intersected(rect), _mix(t["bg"], t["accent"], 0.06))
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
            p.save()
            p.setTransform(tr, True)
            p.setPen(QPen(_mix(t["bg"], t["text"], 0.3), 0.8 / s))
            p.setBrush(_mix(t["bg"], t["text"], 0.14))
            for part in self._land:
                p.drawPath(part)
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
            for i in np.flatnonzero(on):
                r = self._r[i] * grow
                p.drawEllipse(QPointF(xs[i], ys[i]), r, r)
        # country names last, outlined in the land's colour, so the dots don't hide them
        font, colour = self._label_style()
        fm = QFontMetricsF(font)
        halo = QPen(_mix(t["bg"], t["text"], 0.14), 3)
        halo.setJoinStyle(Qt.RoundJoin)
        for box, name in self._label_boxes(tr, s, rect, fm):
            path = QPainterPath()
            path.addText(box.left(), box.top() + fm.ascent(), font, name)
            p.strokePath(path, halo)
            p.fillPath(path, colour)
        p.restore()

    def _label_style(self) -> tuple[QFont, QColor]:
        font = QFont(self.font())
        font.setPointSizeF(max(7.0, font.pointSizeF() * 0.85))
        font.setWeight(QFont.DemiBold)
        return font, QColor(theme.T["text_hi"])

    def _label_boxes(self, tr: QTransform, s: float, rect: QRectF, fm: QFontMetricsF):
        """Where the country names go: (box, name), biggest first, each where it fits
        inside its country's width and doesn't run into a name already placed."""
        taken: list[QRectF] = []
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
            if any(pad.intersects(o) for o in taken):
                continue
            taken.append(pad)
            yield box, name

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
        """City and town names just above their stations, on top of the map picture.
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
        fm = QFontMetricsF(self._label_style()[0])
        taken = []
        for k in self._copies():
            tr = self._transform()
            tr.translate(k, 0)
            taken += [b.adjusted(-2, -1, 2, 1) for b, _n in self._label_boxes(tr, s, rect, fm)]
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

    def _world_key(self, dpr: float):
        s = self._scale()
        w, h = 360 * s, (LAT_TOP - LAT_BOTTOM) * s
        if w * h * dpr * dpr > WORLD_MAX_PX:
            return None
        return (round(s, 6), dpr, self._ver)

    def _world_pixmap(self, dpr: float) -> QPixmap | None:
        """The whole world at this zoom, drawn once: dragging only slides it. While the
        wheel is still zooming, the last one (it's stretched to fit)."""
        key = self._world_key(dpr)
        if key is None:
            return None
        if (self._settle.isActive() and self._world is not None
                and self._world[0][1:] == key[1:]):
            return self._world[1]
        if self._world is None or self._world[0] != key:
            s = self._scale()
            w, h = 360 * s, (LAT_TOP - LAT_BOTTOM) * s
            pm = QPixmap(max(1, round(w * dpr)), max(1, round(h * dpr)))
            pm.setDevicePixelRatio(dpr)
            p = QPainter(pm)
            p.setCompositionMode(QPainter.CompositionMode_Source)
            _fill(p, QRectF(0, 0, pm.width() / dpr, pm.height() / dpr), QColor(theme.T["bg"]))
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            p.setRenderHint(QPainter.Antialiasing)
            tr = QTransform()
            tr.translate(180 * s, LAT_TOP * s)
            tr.scale(s, s)
            self._paint_map(p, tr, s, QRectF(0, 0, w, h))
            p.end()
            self._world = (key, pm)
        return self._world[1]

    def paintEvent(self, _e):
        self._clamp()
        dpr = self.devicePixelRatioF()
        p = QPainter(self)
        t = theme.T
        p.fillRect(self.rect(), QColor(t["bg"]))
        world = self._world_pixmap(dpr)
        if world is not None:
            s = self._scale()
            # zooming: the last zoom's picture, stretched, until the wheel stops
            stretched = abs(world.deviceIndependentSize().width() - 360 * s) > 0.5
            if stretched:
                p.setRenderHint(QPainter.SmoothPixmapTransform)
            for k in self._copies():
                target = QRectF(self.width() / 2 - (self.cx - k + 180) * s,
                                self.height() / 2 - (LAT_TOP - self.cy) * s,
                                360 * s, (LAT_TOP - LAT_BOTTOM) * s)
                if stretched:
                    p.drawPixmap(target, world, QRectF(world.rect()))
                else:
                    p.drawPixmap(target.topLeft(), world)
        else:   # zoomed far in: draw the part in view (kept while nothing moves)
            key = (self.cx, self.cy, self.size(), dpr, round(self._scale(), 6), self._ver)
            if self._view is None or self._view[0] != key:
                pm = QPixmap(round(self.width() * dpr), round(self.height() * dpr))
                pm.setDevicePixelRatio(dpr)
                pm.fill(QColor(t["bg"]))
                q = QPainter(pm)
                q.setRenderHint(QPainter.Antialiasing)
                for k in self._copies():
                    tr = self._transform()
                    tr.translate(k, 0)
                    self._paint_map(q, tr, self._scale(), QRectF(self.rect()))
                q.end()
                self._view = (key, pm)
            p.drawPixmap(0, 0, self._view[1])
        self._paint_towns(p, dpr)
        p.setRenderHint(QPainter.Antialiasing)
        if len(self._points):
            xs, ys = self._screen()
            if 0 <= self._hover < len(self._points):
                r = self._r[self._hover] * self._grow() + 2
                p.setPen(QPen(QColor(t["text_hi"]), 1.5))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QPointF(xs[self._hover], ys[self._hover]), r, r)
            cur = next((i for i, d in enumerate(self._points) if d["id"] == self._current), -1)
            if cur >= 0:
                hot = QColor(t["accent2"])
                c = QPointF(xs[cur], ys[cur])
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

