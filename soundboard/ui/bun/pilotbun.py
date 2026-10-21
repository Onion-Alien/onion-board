"""Pilot Bun: the Languages card's install picture, Bun flying a little plane round the
world (Robo-Bun's counterpart on the AI voice card).

The Earth turns in the middle (the real coasts, much simplified, seen a little from
above), and Bun flies round it in a small red propeller plane, his scarf streaming out
behind: round the back of the world (smaller, hidden behind it), then across the
front, always pointing the way he's going, the propeller spinning and the wind
streaming past. He flies for REST_S after he's shown (or clicked, or the mouse comes
onto him), then holds still where he is, so a card left open costs nothing; while the
install runs (`set_flying(True)`) he keeps going. The timer only runs while he's on
screen and the app is in front. In lite mode (ui/settings/lite.py) there's no timer at
all: one still picture.

Everything is drawn in this widget's own pixels (SLOT_W x SLOT_H), Bun himself scaled
down with soundboard/ui/bun/bunny.py's draw_bunny (kept as a picture per pose in
`_layer`, like ui/bun/scribebun.py).
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QSizePolicy, QWidget

from soundboard.ui.kit import appstate, theme
from soundboard.ui.bun.bunny import H, INK, W, draw_bunny
from soundboard.ui.kit.pixels import snap_to_pixels
from soundboard.ui.settings import lite

SLOT_W, SLOT_H = 132, 104        # about Robo-Bun's size beside the AI voices install
BUN_SCALE = 0.36                 # Bun's canvas (100 x 120) to the plane's units
FPS = 30
REST_S = 20.0                    # how long he flies after a stir, then holds still

GLOBE_C, GLOBE_R = QPointF(66, 54), 31.0
VIEW_LAT = 18.0                  # the Earth seen this many degrees above the equator
SPIN = 14.0                      # degrees a second it turns
ORBIT_RX, ORBIT_RY = 46.0, 22.0  # his flight path round it, an ellipse seen at a slant
ORBIT_TILT = -12.0               # degrees
ORBIT_SPEED = 0.75               # radians a second
BANK = 15.0                      # the most he tips the plane up or down, degrees
PLANE_SCALE = 0.45               # the plane's units to pixels, at the front of the path
OCEAN, OCEAN_DEEP = QColor("#3d8fd6"), QColor("#174a8f")
LAND, DESERT, ICE = QColor("#5e9f45"), QColor("#c7a35c"), QColor("#eef4f7")
AIR = QColor(150, 205, 255)
BODY, BODY_DARK = QColor("#e8574a"), QColor("#b53a32")
WING, WING_DARK = QColor("#f6ecd6"), QColor("#d8c7a2")
GLASS = QColor(200, 236, 255, 170)

# the world's coasts, much simplified: "longitude latitude" points round each land, in
# the order they're drawn (a desert over the land it's in)
_LANDS = (
    (LAND, "-168 66 -162 70 -156 71 -140 70 -128 70 -115 68 -95 72 -85 70 -80 63 -90 57 "
           "-82 52 -78 58 -70 60 -64 58 -56 52 -60 47 -66 44 -70 42 -74 40 -76 35 -81 31 "
           "-80 26 -82 27 -84 30 -90 29 -97 27 -97 22 -94 18 -88 21 -87 16 -83 15 -80 9 "
           "-78 8 -84 10 -86 12 -92 14 -96 16 -105 20 -110 24 -112 29 -115 31 -117 32 "
           "-121 35 -124 40 -124 46 -125 50 -131 54 -137 58 -145 60 -152 59 -158 57 "
           "-165 54 -160 58 -165 61 -166 64"),                          # North America
    (ICE, "-73 78 -60 82 -35 83 -20 81 -18 76 -22 70 -32 68 -42 60 -48 61 -52 65 -55 70 "
          "-60 75 -70 77"),                                             # Greenland
    (LAND, "-80 9 -75 11 -72 12 -62 11 -60 8 -52 5 -50 0 -44 -2 -35 -5 -35 -9 -39 -14 "
           "-40 -20 -44 -23 -48 -26 -53 -34 -58 -38 -62 -39 -65 -45 -68 -50 -69 -55 "
           "-74 -52 -75 -46 -73 -38 -71 -30 -70 -18 -76 -14 -81 -6 -80 -1 -78 2 "
           "-78 7"),                                                    # South America
    (LAND, "-10 36 -9 43 -2 44 -5 48 2 51 8 54 9 57 12 56 18 60 22 65 18 70 26 71 33 70 "
           "42 67 44 68 54 69 60 70 70 73 80 73 87 75 100 77 112 74 130 72 140 72 160 70 "
           "170 70 180 68 178 64 170 60 163 58 160 54 156 51 156 58 150 59 140 54 136 54 "
           "140 48 135 43 130 42 129 36 126 37 126 40 122 40 119 35 122 30 120 24 110 21 "
           "108 16 109 12 105 9 100 13 99 8 103 2 100 4 98 10 98 16 94 17 92 22 88 22 "
           "80 16 77 8 73 17 72 22 67 25 62 25 57 26 56 24 59 22 52 17 44 13 43 17 39 22 "
           "35 28 34 31 36 35 30 36 27 37 26 40 29 41 28 43 23 40 22 37 20 40 19 42 13 45 "
           "12 44 16 40 16 38 15 40 10 44 3 43 -1 37 -6 36"),          # Europe and Asia
    (DESERT, "35 28 39 22 43 17 44 13 52 17 59 22 56 24 51 25 48 30 44 30 "
             "38 32"),                                                  # Arabia
    (LAND, "-17 21 -13 27 -10 30 -6 35 10 37 11 33 20 31 32 31 34 28 38 22 43 12 51 12 "
           "44 2 40 -3 40 -10 40 -16 35 -24 32 -29 27 -34 20 -35 18 -32 14 -23 12 -17 "
           "13 -10 9 -1 9 4 4 6 -4 5 -8 4 -13 8 -17 13 -17 15"),        # Africa
    (DESERT, "-16 20 -13 27 -10 30 -6 35 10 37 11 33 20 31 32 31 34 28 37 22 33 17 22 15 "
             "10 16 0 16 -10 17"),                                      # the Sahara
    (LAND, "44 -25 47 -25 50 -15 49 -12 44 -17"),                       # Madagascar
    (DESERT, "114 -22 114 -26 115 -34 118 -35 124 -34 131 -31 135 -35 138 -35 140 -38 "
             "146 -39 150 -37 153 -31 153 -25 146 -19 145 -15 142 -11 141 -17 136 -12 "
             "130 -12 126 -14 122 -18"),                                # Australia
    (LAND, "109 1 117 7 119 1 116 -4 110 -3"),                          # Borneo
    (LAND, "95 5 98 4 106 -6 102 -4"),                                  # Sumatra
    (LAND, "131 -1 141 -3 150 -10 141 -9 137 -5"),                      # New Guinea
    (LAND, "130 31 135 34 140 36 142 40 141 45 140 41 136 36 131 34"),  # Japan
    (LAND, "-5 50 1 51 0 53 -2 56 -5 58 -6 56 -4 54 -3 53 -5 52"),      # Britain
    (ICE, " ".join(f"{lon} -70" for lon in range(-180, 181, 20))
     + " 180 -90 -180 -90"),                                            # Antarctica
)


def _points(text: str) -> list[tuple[float, float]]:
    n = [math.radians(float(v)) for v in text.split()]
    return list(zip(n[::2], n[1::2]))


LANDS = tuple((colour, _points(text)) for colour, text in _LANDS)


class PilotBunny(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(SLOT_W, SLOT_H)
        self.flying = False          # the install is running: no rest
        self._t0 = time.monotonic()  # the clock his flight runs on
        self._rest_at = 0.0          # when he holds still
        self._held = 0.0             # the moment he holds once resting
        self._layers: dict[tuple, QPixmap] = {}
        self._scale = 1.0
        self._timer = QTimer(self)
        self._timer.setInterval(1000 // FPS)
        self._timer.timeout.connect(self._tick)

    def sizeHint(self) -> QSize:
        return QSize(SLOT_W, SLOT_H)

    # ------------------------------------------------------------------ state
    def set_flying(self, on: bool):
        """The install started (he keeps flying) or ended (he rests after REST_S)."""
        self.flying = bool(on)
        self.stir()

    def stir(self):
        """Fly again for REST_S."""
        self._rest_at = time.monotonic() + REST_S
        self._run()

    def resting(self) -> bool:
        return lite.on() or (not self.flying and time.monotonic() >= self._rest_at)

    def _run(self):
        if self.isVisible() and not self.resting():
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def showEvent(self, ev):
        super().showEvent(ev)
        self.stir()

    def hideEvent(self, ev):
        self._timer.stop()
        super().hideEvent(ev)

    def enterEvent(self, ev):
        self.stir()
        super().enterEvent(ev)

    def mousePressEvent(self, ev):
        self.stir()
        super().mousePressEvent(ev)

    def _tick(self):
        if self.resting():
            self._timer.stop()
        if appstate.active() and not self.window().isMinimized():
            self.update()

    def _now(self) -> float:
        """His clock: running while he flies, held where he stopped once he rests."""
        if lite.on():
            return 0.0
        if not self.resting():
            self._held = time.monotonic() - self._t0
        return self._held

    def _layer(self, key: tuple, draw, size: tuple[float, float]) -> QPixmap:
        """A transparent picture `size` big drawn by `draw(painter)`, kept by `key`."""
        key = key + (theme.T["accent"], theme.current_name, self._scale)   # name: his outfit
        pm = self._layers.get(key)
        if pm is None:
            if len(self._layers) > 32:
                self._layers.clear()
            dpr = self._scale
            pm = QPixmap(round(size[0] * dpr), round(size[1] * dpr))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.GlobalColor.transparent)
            q = QPainter(pm)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            draw(q)
            q.end()
            self._layers[key] = pm
        return pm

    # --------------------------------------------------------------- painting
    def paintEvent(self, _e):
        t = self._now()
        p = QPainter(self)
        snap_to_pixels(p)
        self._scale = round(max(p.device().devicePixelRatioF(), p.deviceTransform().m11()), 2)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setClipRect(self.rect())
        # his place on the path: round the back of the world (behind it), then across
        # the front (in front of it)
        a = 2.2 - t * ORBIT_SPEED
        tilt = math.radians(ORBIT_TILT)
        ox, oy = ORBIT_RX * math.cos(a), ORBIT_RY * math.sin(a)
        dx, dy = ORBIT_RX * math.sin(a), -ORBIT_RY * math.cos(a)   # the way he's going
        pos = QPointF(GLOBE_C.x() + ox * math.cos(tilt) - oy * math.sin(tilt),
                      GLOBE_C.y() + ox * math.sin(tilt) + oy * math.cos(tilt))
        vx = dx * math.cos(tilt) - dy * math.sin(tilt)
        vy = dx * math.sin(tilt) + dy * math.cos(tilt)
        near = math.sin(a)   # 1 at the front of the path, -1 behind the world
        if near < 0:
            self._plane_at(p, t, pos, vx, vy, near)
        self._globe(p, t)
        if near >= 0:
            self._plane_at(p, t, pos, vx, vy, near)
        p.end()

    def _plane_at(self, p: QPainter, t: float, pos: QPointF, vx: float, vy: float,
                  near: float):
        """The plane at `pos`, pointing along (vx, vy), a little smaller far away."""
        p.save()
        p.translate(pos.x(), pos.y() + 0.8 * math.sin(t * 2.3))
        # nose up or down with the path, never steeper than BANK; round the ends he
        # turns: the plane narrows side-on, then comes back facing the other way
        bank = max(-BANK, min(BANK, math.degrees(math.atan2(vy, abs(vx)))))
        p.rotate(bank if vx >= 0 else -bank)
        turn = vx / (math.hypot(vx, vy) or 1.0)
        k = PLANE_SCALE * (0.85 + 0.15 * near)
        p.scale(k * math.copysign(max(0.3, abs(turn)) ** 0.5, turn), k)
        self._plane(p, t)
        p.restore()

    def _globe(self, p: QPainter, t: float):
        c, r = GLOBE_C, GLOBE_R
        halo = QRadialGradient(c, r * 1.18)   # the air round the world
        halo.setColorAt(0.84, QColor(AIR.red(), AIR.green(), AIR.blue(), 120))
        halo.setColorAt(1.0, QColor(AIR.red(), AIR.green(), AIR.blue(), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(c, r * 1.18, r * 1.18)
        ball = QPainterPath()
        ball.addEllipse(c, r, r)
        sea = QRadialGradient(c.x() - r * 0.35, c.y() - r * 0.4, r * 1.5)
        sea.setColorAt(0, OCEAN)
        sea.setColorAt(1, OCEAN_DEEP)
        p.setBrush(sea)
        p.drawPath(ball)
        p.save()
        p.setClipPath(ball, Qt.ClipOperation.IntersectClip)
        lon0 = math.radians(t * SPIN - 20)   # (still: Africa and Europe face him)
        sin0, cos0 = math.sin(math.radians(VIEW_LAT)), math.cos(math.radians(VIEW_LAT))
        for colour, pts in LANDS:
            shown, path = False, QPainterPath()
            for i, (lon, lat) in enumerate(pts):
                dl = lon - lon0
                x = math.cos(lat) * math.sin(dl)
                y = cos0 * math.sin(lat) - sin0 * math.cos(lat) * math.cos(dl)
                if sin0 * math.sin(lat) + cos0 * math.cos(lat) * math.cos(dl) < 0:
                    n = math.hypot(x, y) or 1.0   # round the back: along the rim instead
                    x, y = x / n, y / n
                else:
                    shown = True
                pt = QPointF(c.x() + r * x, c.y() - r * y)
                if i:
                    path.lineTo(pt)
                else:
                    path.moveTo(pt)
            if shown:
                path.closeSubpath()
                p.setBrush(colour)
                p.drawPath(path)
        shade = QRadialGradient(c.x() - r * 0.4, c.y() - r * 0.45, r * 1.9)
        shade.setColorAt(0.0, QColor(255, 255, 255, 80))   # the sun on it, top left
        shade.setColorAt(0.3, QColor(255, 255, 255, 0))
        shade.setColorAt(0.6, QColor(10, 20, 50, 0))
        shade.setColorAt(1.0, QColor(10, 20, 50, 150))     # night round the far side
        p.setBrush(shade)
        p.drawPath(ball)
        p.restore()
        p.setPen(QPen(INK, 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(ball)

    def _whoosh(self, p: QPainter, t: float):
        """Three short lines streaming back from the plane: he's going places."""
        col = QColor(theme.T.get("muted", "#8a8398"))
        for i, (y, length) in enumerate(((-3, 9), (3, 13), (9, 8))):
            k = (t * 1.6 + i * 0.37) % 1.0   # each runs back from the tail and fades
            col.setAlpha(round(170 * math.sin(math.pi * k)))
            p.setPen(QPen(col, 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            x = -44 - 10 * k
            p.drawLine(QPointF(x, y), QPointF(x - length, y))

    def _plane(self, p: QPainter, t: float):
        """The plane, its cockpit at (0, 0), facing right, Bun in it."""
        if not self.resting():
            self._whoosh(p, t)
        # ink lines a pixel wide once the plane is shrunk to PLANE_SCALE
        ink = QPen(INK, 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                   Qt.PenJoinStyle.RoundJoin)
        # the scarf, streaming back from his neck
        wave = math.sin(t * 9)
        scarf = QPainterPath(QPointF(-4, -10))
        scarf.cubicTo(-12, -11 + 2 * wave, -20, -8 - 2 * wave, -30, -11 + 3 * wave)
        scarf.lineTo(-29, -6 + 3 * wave)
        scarf.cubicTo(-19, -4 - 2 * wave, -12, -6 + 2 * wave, -4, -6)
        scarf.closeSubpath()
        p.setPen(ink)
        p.setBrush(QColor(theme.T.get("accent", "#ff7a2f")))
        p.drawPath(scarf)
        # the far wing, behind him
        p.setBrush(WING_DARK)
        p.drawRoundedRect(QRectF(-6, -2, 18, 4), 2, 2)
        # Bun, his chest at the cockpit's rim
        blink = 1.0 if (t % 3.4) < 0.13 else 0.0
        ears = round(10 + 4 * math.sin(t * 7))   # the wind in them
        bw, bh = W * BUN_SCALE, H * BUN_SCALE
        room = 10.0   # an upright ear (or a tall hat) reaches above his canvas
        rect = QRectF(-bw / 2 - 1, -bh * 0.84, bw, bh)
        pm = self._layer(("bun", blink, ears), lambda q: draw_bunny(
            q, QRectF(room, room, bw, bh), None, blink=blink, ears=ears),
            (bw + 2 * room, bh + 2 * room))
        p.drawPixmap(QPointF(rect.x() - room, rect.y() - room), pm)
        # the fuselage over his lower half: tail on the left, nose on the right
        body = QPainterPath(QPointF(-38, -9))
        body.lineTo(-20, -2)
        body.lineTo(22, -3)
        body.cubicTo(30, -3, 33, 2, 33, 4)
        body.cubicTo(33, 8, 28, 11, 22, 11)
        body.lineTo(-12, 11)
        body.cubicTo(-24, 10, -34, 4, -38, -9)
        body.closeSubpath()
        p.setBrush(BODY)
        p.drawPath(body)
        p.save()   # a cream stripe along it
        p.setClipPath(body)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(WING)
        p.drawRect(QRectF(-40, 3, 80, 2.6))
        p.setBrush(BODY_DARK)
        p.drawRect(QRectF(-40, 8.5, 80, 4))
        p.restore()
        p.setPen(ink)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(body)
        # the cockpit's rim, in front of his tummy
        p.setBrush(BODY_DARK)
        p.drawRoundedRect(QRectF(-11, -4, 20, 3.2), 1.6, 1.6)
        # the windscreen
        glass = QPainterPath(QPointF(10, -3))
        glass.lineTo(13, -10)
        glass.lineTo(17, -10)
        glass.lineTo(18, -3)
        glass.closeSubpath()
        p.setBrush(GLASS)
        p.drawPath(glass)
        # the tail fin and tailplane
        fin = QPainterPath(QPointF(-37, -8))
        fin.lineTo(-41, -21)
        fin.cubicTo(-38, -22, -34, -21, -33, -18)
        fin.lineTo(-27, -4)
        fin.closeSubpath()
        p.setBrush(BODY)
        p.drawPath(fin)
        p.setBrush(WING)
        p.drawEllipse(QPointF(-31, 1), 8, 2.4)
        # wheels
        p.drawLine(QPointF(8, 11), QPointF(7, 16))
        p.drawLine(QPointF(16, 11), QPointF(17, 16))
        p.setBrush(INK)
        p.drawEllipse(QPointF(7, 16.5), 2.0, 2.0)
        p.drawEllipse(QPointF(17, 16.5), 2.0, 2.0)
        # the near wing, over all that, swept back a little
        wing = QPainterPath(QPointF(-6, 5))
        wing.lineTo(14, 5)
        wing.cubicTo(17, 5, 17, 8, 14, 9)
        wing.lineTo(-12, 13)
        wing.cubicTo(-15, 13, -15, 10, -12, 9)
        wing.closeSubpath()
        p.setBrush(WING)
        p.drawPath(wing)
        # the nose and the propeller
        p.setBrush(WING_DARK)
        p.drawEllipse(QPointF(33.5, 4), 2.6, 3.4)
        spin = t * 40
        if not self.resting():   # a blur where the blades turn
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 55))
            p.drawEllipse(QPointF(35.5, 4), 2.4, 13)
            p.setPen(ink)
        p.setBrush(QColor("#6b4a2e"))
        for blade in (0.0, math.pi):
            k = math.cos(spin + blade)
            if abs(k) > 0.08:
                p.drawEllipse(QRectF(34.2, 4 if k > 0 else 4 + 12 * k, 2.6, 12 * abs(k)))
