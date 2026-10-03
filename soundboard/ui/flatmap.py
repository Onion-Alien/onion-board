"""The Radio tab's flat world map: the default view, painted by Qt itself.

A plain map (land outlines and a dot per station) costs nothing while it sits there:
it only repaints when you drag, zoom, hover over a different dot or the stations
change, and it needs no web engine. The 3D globe (radio.globe_html) is the HD view,
one click away on the map's HD button.

Stations arrive as radio.globe_points() dicts, like the globe's, so the tab can
feed either view the same way.
"""
from __future__ import annotations

import html

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QPushButton, QToolTip, QVBoxLayout, QWidget

from soundboard import theme

LAT_TOP, LAT_BOTTOM = 84.0, -58.0   # the inhabited world: no polar wastes
ZOOM_MAX = 14.0
HIT_PX = 7.0                        # how near the pointer a dot counts as under it


def _mix(a: str, b: str, t: float) -> QColor:
    ca, cb = QColor(a), QColor(b)
    return QColor.fromRgbF(ca.redF() + (cb.redF() - ca.redF()) * t,
                           ca.greenF() + (cb.greenF() - ca.greenF()) * t,
                           ca.blueF() + (cb.blueF() - ca.blueF()) * t)


class FlatMap(QWidget):
    clicked = Signal(str)       # a station's uuid
    hd_requested = Signal()     # the HD (3D globe) button

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(120, 80)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self._land = QPainterPath()     # in (lon, -lat) degrees
        self._points: list[dict] = []
        self._lon = np.zeros(0)
        self._lat = np.zeros(0)
        self._r = np.zeros(0)           # dot radius before zoom
        self._current: str | None = None
        self._hover = -1
        self._msg = "Finding stations…"
        self.zoom = 1.0
        self.cx, self.cy = 10.0, (LAT_TOP + LAT_BOTTOM) / 2   # the view's centre (lon, lat)
        self._drag: QPointF | None = None
        self._dragged = False
        self._bg: QPixmap | None = None   # land at the current view, redrawn when it moves

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
    def set_land(self, rings: list):
        path = QPainterPath()
        path.setFillRule(Qt.WindingFill)
        for ring in rings:
            path.moveTo(ring[0][0], -ring[0][1])
            for x, y in ring[1:]:
                path.lineTo(x, -y)
            path.closeSubpath()
        self._land = path
        self._redraw()

    def set_points(self, points: list[dict]):
        # the least listened first, so the popular dots are drawn on top
        pts = sorted(points, key=lambda d: d.get("k", 0))
        self._points = pts
        self._lon = np.array([d["lo"] for d in pts], float)
        self._lat = np.array([d["la"] for d in pts], float)
        k = np.array([d.get("k", 0) for d in pts], float)
        top = max(1.0, float(k.max())) if len(k) else 1.0
        self._r = 1.6 + 2.4 * np.sqrt(k / top)
        self._hover = -1
        if pts:
            self._msg = ""
        self._redraw()

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
        self._redraw()

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
        """Pixels per degree."""
        w, h = max(1, self.width()), max(1, self.height())
        return min(w / 360.0, h / (LAT_TOP - LAT_BOTTOM)) * self.zoom

    def _clamp(self):
        self.zoom = min(ZOOM_MAX, max(1.0, self.zoom))
        s = self._scale()
        half_w, half_h = self.width() / s / 2, self.height() / s / 2
        lo, hi = -180 + half_w, 180 - half_w
        self.cx = min(hi, max(lo, self.cx)) if lo <= hi else 0.0
        lo, hi = LAT_BOTTOM + half_h, LAT_TOP - half_h
        self.cy = min(hi, max(lo, self.cy)) if lo <= hi else (LAT_TOP + LAT_BOTTOM) / 2

    def _transform(self) -> QTransform:
        s = self._scale()
        t = QTransform()
        t.translate(self.width() / 2 - self.cx * s, self.height() / 2 + self.cy * s)
        t.scale(s, s)
        return t

    def _screen(self) -> tuple[np.ndarray, np.ndarray]:
        s = self._scale()
        return (self.width() / 2 + (self._lon - self.cx) * s,
                self.height() / 2 - (self._lat - self.cy) * s)

    def _redraw(self):
        self._bg = None
        self.update()

    # ------------------------------------------------------------------ painting
    def _grow(self) -> float:
        return min(2.0, 1 + (self.zoom - 1) * 0.15)   # dots get a little bigger zoomed in

    def _background(self) -> QPixmap:
        """The sea, the land and the dots at this view, kept until the view, the stations
        or the theme change: hovering only draws its ring on top."""
        t = theme.T
        dpr = self.devicePixelRatioF()
        pm = QPixmap(round(self.width() * dpr), round(self.height() * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(QColor(t["bg"]))
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        tr = self._transform()
        s = self._scale()
        # the map's own rectangle (the world can be narrower or shorter than the widget)
        world = tr.mapRect(QRectF(-180, -LAT_TOP, 360, LAT_TOP - LAT_BOTTOM))
        p.fillRect(world, _mix(t["bg"], t["accent"], 0.06))
        p.setClipRect(world)
        p.setPen(QPen(_mix(t["bg"], t["text"], 0.07), 1))
        for lon in range(-150, 180, 30):
            x = tr.map(QPointF(lon, 0)).x()
            p.drawLine(QPointF(x, world.top()), QPointF(x, world.bottom()))
        for lat in (-30, 0, 30, 60):
            y = tr.map(QPointF(0, -lat)).y()
            p.drawLine(QPointF(world.left(), y), QPointF(world.right(), y))
        if not self._land.isEmpty():
            p.save()
            p.setTransform(tr)
            p.setPen(QPen(_mix(t["bg"], t["text"], 0.3), 0.8 / s))
            p.setBrush(_mix(t["bg"], t["text"], 0.14))
            p.drawPath(self._land)
            p.restore()
        if len(self._points):
            xs, ys = self._screen()
            on = (xs > -8) & (xs < self.width() + 8) & (ys > -8) & (ys < self.height() + 8)
            accent = QColor(t["accent"])
            accent.setAlphaF(0.85)
            p.setPen(Qt.NoPen)
            p.setBrush(accent)
            grow = self._grow()
            for i in np.flatnonzero(on):
                r = self._r[i] * grow
                p.drawEllipse(QPointF(xs[i], ys[i]), r, r)
        p.end()
        return pm

    def paintEvent(self, _e):
        self._clamp()
        if self._bg is None or self._bg.deviceIndependentSize().toSize() != self.size():
            self._bg = self._background()
        p = QPainter(self)
        p.drawPixmap(0, 0, self._bg)
        t = theme.T
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
        if self._msg:
            p.setPen(QColor(t["muted"]))
            p.drawText(self.rect().adjusted(24, 24, -24, -24), Qt.AlignCenter | Qt.TextWordWrap,
                       self._msg)
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
        self._redraw()

    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120.0
        if steps:
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
                self._redraw()
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
            self._redraw()

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

