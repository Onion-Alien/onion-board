"""The Radio tab's world map, painted by Qt itself.

A plain map (land outlines, country names, a dot per station and, zoomed in, the
names of the cities and towns in view that have stations) costs nothing while
it sits there: it only repaints when you drag, zoom, hover over a different dot or the
stations change, and it needs no web engine. The world is drawn in tiles (TILE device
pixels square), each once per zoom: a drag or a repaint only copies the tiles in view,
at any zoom. Tiles not drawn yet (a new zoom, a drag onto new ground) are drawn a
slice at a time while the last whole view, put together into one picture and
stretched, stands in for them (tiles stretched one by one showed their seams, a grid
over the map); a new zoom shows only once all of it is drawn. Under that, the land of
the whole world, small. The country names show first, then (NAMES_FIRST_S on) the
first stations pop in a few at a time (REVEAL_S); Bun waits on the map till they come.

Stations arrive as radio.globe_points() dicts (the name is from the 3D globe this map
replaced).
"""
from __future__ import annotations

import html
import math
import time
from collections import deque
from collections.abc import Iterator

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath,
                           QPen, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QToolTip,
                               QVBoxLayout, QWidget)

from soundboard.ui.kit import theme
from soundboard.i18n import _, ngettext
from soundboard.ui.kit import oops
from soundboard.ui.kit.pixels import snap_to_pixels

LAT_TOP, LAT_BOTTOM = 84.0, -58.0   # the inhabited world: no polar wastes
ZOOM_MAX = 250.0                    # about street level: a city's stations come apart
HIT_PX = 7.0                        # how near the pointer a dot counts as under it
LAND_PART = 400                     # outline points per drawn part (set_land)
# The parts are made one a step with this long a rest between (set_land). All ~30 in
# one go were 10-40 ms of back-to-back Qt calls on opening the Radio tab, and the audio
# threads wait on them: a sound playing came up to 33 ms late, a skip.
STEP_GAP_MS = 4
FILL_PX = 1_000_000                 # device pixels per filled band (_fill)
# The world in tiles: a drag copies the ones in view (well under 1 ms) instead of
# drawing the map again, which took 10-20 ms a frame zoomed in and made it lag.
TILE = 512                          # device pixels a side
TILE_RING = 1                       # tiles drawn ahead (and kept) round the view
BASE_ZOOM = 1.0                     # the whole world's land, zoomed out: under everything
# New tiles (zoom, new dots, theme, a drag onto new ground) are drawn a slice at a time
# while stand-ins show: Qt keeps Python's lock through each draw call, and the audio
# threads wait out one call per numpy step, so 20-40 ms of drawing in one go made the
# cable 10-20 ms late (a skip) even with every call under 1 ms. A slice, then a break.
SLICE_S = 0.0015
SLICE_GAP_MS = 4
FORGET_MS = 60_000   # hidden this long: let the drawn tiles go (back sooner: no redraw)
SETTLE_MS = 120                     # zooming: the old tiles, stretched, until this idle
LABEL_GROW_MAX = 2.2                # country names grow up to this much zoomed in
TOWN_ZOOM = 2.0                     # city and town names show from this zoom in...
TOWNS_IN_VIEW = 40                  # ...at most this many at once, only those in view
TOWN_SLICE_S = 0.0015               # new names drawn a paint, then the rest a moment later
# The most listened stations (HOT_SHARE of them, at least HOT_MIN plays today) are big
# glowing dots, bigger the more they're played; the rest are small plain ones.
HOT_SHARE = 0.1
HOT_MIN = 10
QUIET_R = 1.0                       # a quiet station's dot (pixels, before zoom)...
HOT_R = (2.0, 5.0)                  # ...a popular one's, least to most played
GLOW = 2.8                          # the glow round a popular dot, times its size
# Dots that would cover each other move apart (where they are needn't be exact): each
# takes the nearest free place round its spot, up to ROOM_PX away (more zoomed in, as
# the dots grow), ROOM_GAP_PX apart. Past ROOM_ZOOM both grow with the zoom (the gaps
# as its square root, the reach in step with it): a city's stations all listed at its
# centre keep coming apart as you zoom in, instead of staying one fixed clump. Worked
# out once per half zoom step (ROOM_STEPS a doubling) and kept, a slice at a time
# (ROOM_BATCH dots a step, ROOM_SLICE_S a slice) between frames, the dots where they
# were till it's done.
ROOM_PX = 14.0
ROOM_GAP_PX = 0.8
ROOM_ZOOM = 4.0
ROOM_STEPS = 2
ROOM_BATCH = 32
ROOM_SLICE_S = 0.004
NAMES_FIRST_S = 0.35                # the country names alone, before the dots...
REVEAL_S = 1.4                      # ...then the first stations pop in over this long...
POP_S = 0.3                         # ...each growing in over this (a little overshoot)
CORNER_PX = 12                      # the map's rounded corners (like QFrame#stations)
LOADING_TEXT = _("Tuning in to radio stations around the world…")


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


def _pop(x: np.ndarray) -> np.ndarray:
    """0..1 -> a dot's size while it pops in: grows a little past full, then settles."""
    x = np.clip(x, 0.0, 1.0) - 1
    return 1 + 2.7 * x ** 3 + 1.7 * x ** 2


class _Loading(QFrame):
    """Bun with his headphones on, tuning in, music notes floating up: on the map
    (which can be dragged and zoomed meanwhile) until the stations come."""

    def __init__(self, parent: QWidget):
        from soundboard.ui.bun.bunnywidget import BunnyWidget
        super().__init__(parent)
        self.setObjectName("maploader")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        box = QHBoxLayout(self)
        box.setContentsMargins(6, 4, 18, 4)
        box.setSpacing(4)
        self.bun = BunnyWidget("headphones", height=64, pad=14)
        box.addWidget(self.bun)
        text = LOADING_TEXT
        self.label = QLabel(text)
        self.label.setObjectName("maploadertext")
        # two lines in any language: wrap at about half the text's width
        self.label.setWordWrap(True)
        self.label.setFixedWidth(max(150, self.label.fontMetrics().horizontalAdvance(text)
                                     * 55 // 100))
        box.addWidget(self.label)
        self._notes = QTimer(self)
        self._notes.setInterval(700)
        self._notes.timeout.connect(lambda: self.bun.burst(2))

    def showEvent(self, e):
        super().showEvent(e)
        self.bun.burst(3)
        self._notes.start()

    def hideEvent(self, e):
        self._notes.stop()
        super().hideEvent(e)


def _sizes(k: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Plays today -> each dot's radius (before zoom) and whether it glows: the most
    listened HOT_SHARE (HOT_MIN plays or more) big, on a log scale up to the most
    played; the rest all QUIET_R."""
    if not len(k):
        return np.zeros(0), np.zeros(0, bool)
    floor = max(float(HOT_MIN), float(np.quantile(k, 1 - HOT_SHARE)))
    hot = k >= floor
    lo, hi = math.log1p(floor), math.log1p(max(floor, float(k.max())))
    q = np.clip((np.log1p(k) - lo) / max(1e-9, hi - lo), 0.0, 1.0)
    r = np.where(hot, HOT_R[0] + (HOT_R[1] - HOT_R[0]) * np.sqrt(q), QUIET_R)
    return r, hot


def _make_room(x: np.ndarray, y: np.ndarray, r: np.ndarray, step: float,
               room: float) -> Iterator[None]:
    """The steps that work out how many pixels to move each dot by so none covers
    another (the generator's return value, (n, 2)): from the last (the most listened,
    which keeps its spot) to the first, each takes the first free place on a
    sunflower spiral round its own spot (`step` apart), no further than `room`; with
    none free it stays put. `x`, `y`: where the dots are, in pixels. All ~3000 in one
    go took ~100 ms zoomed out, a stall: a step every ROOM_BATCH dots."""
    n = len(x)
    out = np.zeros((n, 2))
    if not n:
        return out
    gap = ROOM_GAP_PX
    j = np.arange(int((room / step) ** 2) + 1)
    d = step * np.sqrt(j)
    a = j * math.pi * (3 - math.sqrt(5))
    tx, ty = (d * np.cos(a))[:, None], (d * np.sin(a))[:, None]   # (0, 0) first
    chunk = 256   # places tried at a time: zoomed in there can be thousands
    reach = 2 * (room + float(r.max())) + gap   # two moved dots touching, at most
    # the dots placed so far, by square (reach a side, by where each started): a dot
    # looks only at the nine round its own, not at every dot placed
    gx = np.floor(x / reach).astype(int).tolist()
    gy = np.floor(y / reach).astype(int).tolist()
    cells: dict[tuple[int, int], list[int]] = {}
    px, py = x.copy(), y.copy()
    for i in range(n - 1, -1, -1):
        a, b = gx[i], gy[i]
        near = [q for ca in (a - 1, a, a + 1) for cb in (b - 1, b, b + 1)
                for q in cells.get((ca, cb), ())]
        if near:
            q = np.array(near)
            lim = (r[i] + r[q] + gap) ** 2
            for c in range(0, len(tx), chunk):
                cx, cy = tx[c:c + chunk], ty[c:c + chunk]
                free = (((x[i] + cx - px[q]) ** 2 + (y[i] + cy - py[q]) ** 2)
                        >= lim).all(axis=1)
                t = int(np.argmax(free))
                if free[t]:
                    t += c
                    break
            else:   # not free anywhere near enough: it stays on its spot
                t = 0
            if t:
                out[i] = (tx[t, 0], ty[t, 0])
                px[i], py[i] = x[i] + tx[t, 0], y[i] + ty[t, 0]
        cells.setdefault((a, b), []).append(i)
        if i % ROOM_BATCH == 0:
            yield
    return out


def _glow_image(colour: QColor) -> QImage:
    """A soft round glow in `colour`, fading to nothing at its edge: drawn stretched
    under each popular dot."""
    side = 64
    img = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    g = QRadialGradient(side / 2, side / 2, side / 2)
    for at, alpha in ((0.0, 0.95), (0.3, 0.6), (0.6, 0.2), (1.0, 0.0)):
        c = QColor(colour)
        c.setAlphaF(alpha)
        g.setColorAt(at, c)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawEllipse(QRectF(0, 0, side, side))
    p.end()
    return img


class FlatMap(QWidget):
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
        self._r = np.zeros(0)           # dot radius before zoom (_sizes)
        self._hot = np.zeros(0, bool)   # ...and which glow: the most listened
        self._buf: QImage | None = None  # the map drawn before its corners are rounded
        self._room: dict[tuple, np.ndarray] = {}   # dots moved apart, per zoom (_spread)
        self._room_job: tuple | None = None        # (zoom, its steps): being worked out
        self._room_shown: np.ndarray | None = None  # ...and what shows meanwhile
        self._room_timer = QTimer(self)            # works on it a slice more (_room_step)
        self._room_timer.setSingleShot(True)
        self._room_timer.setInterval(SLICE_GAP_MS)
        self._room_timer.timeout.connect(self._room_step)
        self._look: tuple | None = None  # (accent, quiet, hot, glow picture): _dot_look
        self._current: str | None = None
        self._hover = -1
        self._msg = ""
        self.zoom = 1.0
        self.cx, self.cy = 10.0, (LAT_TOP + LAT_BOTTOM) / 2   # the view's centre (lon, lat)
        self._drag: QPointF | None = None
        self._dragged = False
        self._ver = 0                     # bumped when what's drawn changes
        self._land_ver = 0                # ...and when the land (or its colours) does
        self._tiles: dict[tuple, QPixmap] = {}   # (level, i, j): see _level
        # the last view drawn all over: (level, its slots), put together on demand into
        # one picture (_pics) that stands in, stretched, while a new one is drawn
        self._stable: tuple | None = None
        self._pics: dict[tuple, tuple] = {}      # (level, slots): (picture, x, y)
        self._placed: dict[float, list] = {}     # country names' places, per scale
        self._reveal_t0: float | None = None     # when the first stations pop in (REVEAL_S)
        self._reveal_wait = False                # ...stations came before the land did
        self._land_set = False
        self._rings: deque[list] = deque()          # outlines still to make parts of
        self._land_new: list[QPainterPath] = []     # ...and the parts made so far
        self._land_steps = QTimer(self)             # makes the next part (_land_step)
        self._land_steps.setSingleShot(True)
        self._land_steps.setTimerType(Qt.TimerType.PreciseTimer)
        self._land_steps.timeout.connect(self._land_step)
        self._names_pic: tuple | None = None     # (view, picture): the names over the pop-in
        self._names_build: tuple | None = None   # (view, picture, its steps): being drawn
        self._dots_pic: tuple | None = None      # (view, picture, which are on it): the
                                                 # dots done popping in, drawn once
        self._delay = np.zeros(0)                # ...and each one's turn to pop in
        self._reveal = QTimer(self)
        self._reveal.setInterval(1000 // 24)   # a short pop-in: 24 fps is plenty
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
        if self._reveal_wait:   # the stations came first: their pop-in waited for this
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
        self._room = {}
        self._room_job = None
        self._hover = -1
        if pts:
            self._msg = ""
            self.oops.hide()
            self._loading.hide()
        if first:
            # the map fills up: the most listened first, the rest in a shuffled wave
            n = len(pts)
            rank = (n - 1 - np.arange(n)) / max(1, n)
            # a fixed scatter, not np.random: its first use loads numpy's random DLLs,
            # and a DLL load here waited out the decoder's (radio.preload_decoder)
            jitter = (np.arange(n) * 0.6180339887 % 1.0) * 0.25
            self._delay = (REVEAL_S - POP_S) * np.clip(rank * 0.8 + jitter, 0, 1)
            if self._land_set:
                self._start_reveal()
            else:   # the land and its names first, then the dots
                self._reveal_wait = True
        elif self.revealing():
            self._delay = np.zeros(len(pts))   # changed mid-way: the rest at once
        self._redraw()

    def _start_reveal(self):
        """The country names show on their own for NAMES_FIRST_S, then the dots pop in."""
        self._reveal_wait = False
        self._reveal_t0 = time.monotonic() + NAMES_FIRST_S
        self._reveal.start()

    def revealing(self) -> bool:
        """The first stations still to pop in, or popping in (REVEAL_S)."""
        return self._reveal_t0 is not None or self._reveal_wait

    def _reveal_step(self):
        if self._reveal_t0 is None or time.monotonic() - self._reveal_t0 >= REVEAL_S:
            self._reveal_t0 = None
            self._names_pic = None
            self._drop_names()
            self._dots_pic = None
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

    def _transform(self) -> QTransform:
        s = self._scale()
        t = QTransform()
        t.translate(self.width() / 2 - self.cx * s, self.height() / 2 + self.cy * s)
        t.scale(s, s)
        return t

    def _screen(self) -> tuple[np.ndarray, np.ndarray]:
        """Each dot's spot on screen: its copy of the world nearest the middle."""
        s = self._scale()
        dx, dy = self._spread(s)
        return (self.width() / 2 + ((self._lon - self.cx + 180) % 360 - 180) * s + dx,
                self.height() / 2 - (self._lat - self.cy) * s + dy)

    def _spread(self, s: float, wait: bool = False
                ) -> tuple[np.ndarray | float, np.ndarray | float]:
        """Pixels to move each dot by at scale `s` so none covers another: stations
        close together, or listed at the very same spot (often a whole city's, at its
        centre), move apart so each can be seen and clicked (_make_room). Worked out
        for the half zoom step at or below `s` and kept: zooming further in only
        spreads them more. Not worked out yet: it starts (_room_step), and till it's
        done the dots are where the nearest zoom worked out had them (`wait`: now)."""
        if not len(self._lon):
            return 0.0, 0.0
        base = round(self._scale() / self.zoom, 6)
        b = math.floor(math.log2(max(1.0, s / base)) * ROOM_STEPS + 1e-9)
        room = self._room.get((b, base))
        if room is None:
            if self._room_job is None or self._room_job[0] != (b, base):
                zoom = 2 ** (b / ROOM_STEPS)
                grow = self._grow(zoom)
                self._room_job = ((b, base), _make_room(
                    self._lon * base * zoom, -self._lat * base * zoom, self._r * grow,
                    *self._room_size(zoom)))
                self._room_timer.start()
            if wait:
                self._room_step(math.inf)
                return self._spread(s)
            # meanwhile: the nearest zoom out worked out, else the nearest in, else none
            done = sorted((k[0] for k in self._room if k[1] == base),
                          key=lambda k: (k > b, abs(k - b)))
            if not done:
                self._room_shown = None
                return 0.0, 0.0
            room = self._room_shown = self._room[(done[0], base)]
        return room[:, 0], room[:, 1]

    def _room_size(self, zoom: float | None = None) -> tuple[float, float]:
        """How far apart moved dots sit and how far from their spot they may go, in
        pixels, at `zoom` (_make_room)."""
        zoom = self.zoom if zoom is None else zoom
        grow = self._grow(zoom)
        more = max(1.0, zoom / ROOM_ZOOM)
        return ((2 * QUIET_R * grow + ROOM_GAP_PX) * 1.05 * math.sqrt(more),
                ROOM_PX * grow * grow * more)

    def _room_step(self, budget: float = ROOM_SLICE_S):
        """Works on the dots' places (_spread) for `budget` seconds; once they're done,
        the map is drawn again with them."""
        if self._room_job is None:
            return
        key, steps = self._room_job
        end = time.perf_counter() + budget
        try:
            while time.perf_counter() < end:
                next(steps)
        except StopIteration as done:
            self._room[key] = room = done.value
            self._room_job = None
            shown = self._room_shown
            # drawn again only if they moved: nothing to move (a dot alone) redrew the
            # whole map for nothing
            if not (np.array_equal(room, shown) if shown is not None else not room.any()):
                self._redraw()
            return
        self._room_timer.start()

    def _redraw(self):
        """What's drawn changed (stations, land, theme): draw it again (a tile at a
        time, the old tiles showing till then)."""
        self._ver += 1
        self._placed.clear()
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
        self._town_pm.clear()
        self._town_box.clear()

    # ------------------------------------------------------------------ painting
    def _grow(self, zoom: float | None = None) -> float:
        zoom = self.zoom if zoom is None else zoom
        return min(2.0, 1 + (zoom - 1) * 0.15)   # dots get a little bigger zoomed in

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
        return self._look[1:]

    def _dots_steps(self, p: QPainter, xs, ys, which: np.ndarray, r: np.ndarray):
        """Draws dots `which` (in order, most listened last) at `xs`, `ys`, `r` big:
        the popular ones' glows first, so a glow never hides a dot, then the quiet
        dots, then the popular ones on top. A step every 200 draws."""
        quiet, hot, glow = self._dot_look()
        which = np.asarray(which, int)
        lit = which[self._hot[which]].tolist()
        # plain floats for Qt
        fx, fy, fr = (np.asarray(v, float).tolist() for v in (xs, ys, r))
        p.save()
        try:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.setPen(Qt.PenStyle.NoPen)
            n = 0
            src = QRectF(glow.rect())
            for i in lit:
                g = fr[i] * GLOW
                p.drawImage(QRectF(fx[i] - g, fy[i] - g, 2 * g, 2 * g), glow, src)
                n += 1
                if n % 200 == 0:
                    yield
            for brush, part in ((quiet, which[~self._hot[which]].tolist()), (hot, lit)):
                p.setBrush(brush)
                for i in part:
                    p.drawEllipse(QPointF(fx[i], fy[i]), fr[i], fr[i])
                    n += 1
                    if n % 200 == 0:
                        yield
        finally:
            p.restore()

    def _map_steps(self, p: QPainter, tr: QTransform, s: float, rect: QRectF,
                   land_only: bool = False):
        """The sea, grid, land, names and dots (just the sea and land if `land_only`),
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
            if land_only:
                return
            if len(self._points):
                o = tr.map(QPointF(0, 0))
                dx, dy = self._spread(s)
                xs, ys = o.x() + self._lon * s + dx, o.y() - self._lat * s + dy
                r = self._r * self._grow()
                pad = r * np.where(self._hot, GLOW, 1.0) + 2
                on = ((xs > rect.left() - pad) & (xs < rect.right() + pad)
                      & (ys > rect.top() - pad) & (ys < rect.bottom() + pad))
                yield from self._dots_steps(p, xs, ys, np.flatnonzero(on), r)
            # country names last, outlined in the land's colour, so the dots don't hide them
            font, colour = self._label_style(s)
            fm = QFontMetricsF(font)
            halo = QPen(_mix(t["bg"], t["text"], 0.14), 3)
            halo.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
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
        finally:
            p.restore()

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
                yield from self._map_steps(p, tr, s, QRectF(0, 0, w / dpr, h / dpr),
                                           land_only=len(level) > 3)
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
        """Tiles still to draw, or the dots' places still to work out (tests, benches)."""
        return self._build is not None or bool(self._queue) or self._room_job is not None

    def _paint_reveal(self, p: QPainter):
        """The first stations popping in, drawn live over the map (the tiles with
        them on wait till all are in): just the ones in view, each its turn. A dot
        done growing is drawn once, into a picture kept for the view, so a frame
        draws only the ones still growing: drawing all ~3000 every frame was 4-7 ms
        of back-to-back draw calls each 16 ms, the most right as the last ones came
        in, and the sound playing skipped (the audio threads wait on each call)."""
        if self._reveal_t0 is None:   # waiting on the land: no dots yet
            return
        t = time.monotonic() - self._reveal_t0
        n = len(self._r)
        if len(self._delay) == n:
            x = (t - self._delay) / POP_S
            size, done = _pop(x), x >= 1.0
        else:
            size, done = np.ones(n), np.ones(n, bool)
        xs, ys = self._screen()
        r = self._r * self._grow()
        pad = r * np.where(self._hot, GLOW, 1.0) + 2
        seen = ((xs > -pad) & (xs < self.width() + pad)
                & (ys > -pad) & (ys < self.height() + pad))
        dpr = self.devicePixelRatioF()
        view = (round(self._scale(), 6), self.cx, self.cy, self.width(), self.height(),
                dpr, self._ver, n)
        if self._dots_pic is None or self._dots_pic[0] != view:
            pic = QImage(max(1, round(self.width() * dpr)), max(1, round(self.height() * dpr)),
                         QImage.Format.Format_ARGB32_Premultiplied)
            pic.setDevicePixelRatio(dpr)
            pic.fill(Qt.GlobalColor.transparent)
            self._dots_pic = (view, pic, np.zeros(n, bool))
        _view, pic, drawn = self._dots_pic
        new = np.flatnonzero(done & seen & ~drawn)
        if len(new):
            q = QPainter(pic)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            for _step in self._dots_steps(q, xs, ys, new, r):
                pass
            q.end()
            drawn[new] = True
        p.drawImage(0, 0, pic)
        growing = np.flatnonzero((size > 0.05) & ~done & seen)
        for _step in self._dots_steps(p, xs, ys, growing, r * size):
            pass

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
        revealing = self.revealing()
        if complete and not revealing:
            for at, pm in shown:
                if pm is not None:   # (all of them: complete)
                    p.drawPixmap(at, pm, QRectF(pm.rect()))
        else:
            # a new zoom (or new dots) shows all at once when it's all drawn, never a
            # patchwork of sharp and stretched squares; till then the last view
            self._stand_in(p)
            if not revealing and self._stable is not None and self._stable[0] == cur:
                for at, pm in shown:   # the same zoom, dragged: the tiles there are
                    if pm is not None:
                        p.drawPixmap(at, pm, QRectF(pm.rect()))
        self._plan(cur, slots, complete and not revealing)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if revealing:
            self._paint_reveal(p)
            self._paint_names(p)   # on top, as the tiles have them
        self._paint_towns(p, dpr)
        cur = self._current
        hover, cur_i = self._hover, self._index.get(cur, -1) if cur is not None else -1
        if (0 <= hover < len(self._points)) or cur_i >= 0:
            xs, ys = self._screen()
            if 0 <= hover < len(self._points):
                r = self._r[hover] * self._grow() + 2
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

