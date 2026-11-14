"""Bun in his diving gear, as on Onion Pocket's phone page (its opening dive), in a small
underwater scene: he swims, reaches out, plugs the phone's cable into the PC's, the plug
lights up and he gives a happy thumbs-up; then the cables drift apart and he does it again.
Painted here with QPainter (the same shapes as the add-on's drawing, no SVG renderer).

He moves for REST_S after he's shown, then stops on his thumbs-up until he's clicked (as
Hoot does on the Triggers tab), never behind another app (appstate) and never in Lite
mode (hooks.still): a still picture then."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPolygonF, QRadialGradient)
from PySide6.QtWidgets import QWidget

from soundboard.style import appstate, hooks

# the drawing's own coordinates (the add-on's 640 x 400 stage), cropped to the scene
VIEW = QRectF(178, 62, 284, 270)
INK, FUR, BELLY, PINK = "#2b2340", "#fbf7f2", "#ece3da", "#ffb3c7"
GEAR, GLASS, GLASS_EDGE, GLINT = "#a68afa", "#83e5e4", "#386175", "#d7ffff"
WATER = ("#4cc3d4", "#1f87a6", "#123c63")       # top, middle, floor
SAND, SAND_TOP, WEED, WEED_DARK = "#d6b27a", "#ecd3a2", "#3fb07f", "#2a8a62"
LIT = "#79f5ce"
FRAME_MS = 33
REST_S = 30.0
LOOP_S = 6.0     # one plug-in, thumbs-up and let-go
HOLD_U = 3.6     # the moment in the loop he rests on (thumb up, plugged in)
BOB_S = 3.0
KICK_S = 0.96    # one kick and back (the add-on's .48 s each way)
# bubbles from his mask: phase, x drift, radius, rise time
BUBBLES = ((0.0, 0, 6.0, 2.6), (0.22, 6, 3.5, 2.2), (0.47, -4, 5.0, 2.9),
           (0.68, 3, 3.0, 2.0), (0.85, -2, 4.0, 2.4))
# specks floating in the water: x, y, size, speed
SPECKS = ((196, 120, 1.6, 5), (230, 250, 1.2, 7), (262, 90, 1.0, 4), (300, 300, 1.4, 6),
          (402, 110, 1.3, 5), (432, 210, 1.7, 8), (452, 280, 1.1, 4), (380, 70, 1.0, 6),
          (214, 180, 1.0, 3), (446, 150, 1.2, 5))


def _ease(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def _seg(u: float, a: float, b: float) -> float:
    return _ease((u - a) / (b - a))


def _quad(*pts: float) -> QPainterPath:
    """M x0 y0 Q cx cy x y [Q cx cy x y ...]"""
    p = QPainterPath(QPointF(pts[0], pts[1]))
    for i in range(2, len(pts), 4):
        p.quadTo(pts[i], pts[i + 1], pts[i + 2], pts[i + 3])
    return p


def _rgba(color: str, alpha: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


class DiveBun(QWidget):
    clicked = Signal()

    def __init__(self, height: int = 196, parent: QWidget | None = None):
        super().__init__(parent)
        self.bun_h = height
        self.t = HOLD_U
        self._last = 0.0
        self._rest_at = REST_S
        self._resting_due = False
        self.resting = False
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(self.sizeHint())
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)
        appstate.pause_in_background(self, self._resume, self._pause)

    def sizeHint(self) -> QSize:
        return QSize(round(self.bun_h * VIEW.width() / VIEW.height()), self.bun_h)

    # ------------------------------------------------------------------ moving
    def showEvent(self, ev):
        self.resting = hooks.still()
        if not self.resting:
            self._rest_at = self.t + REST_S
        if appstate.active():
            self._resume()
        super().showEvent(ev)

    def hideEvent(self, ev):
        self._pause()
        super().hideEvent(ev)

    def _resume(self):
        if self.resting or not self.isVisible():
            return
        self._last = time.monotonic()
        self._timer.start()

    def _pause(self):
        self._timer.stop()

    def _tick(self):
        now = time.monotonic()
        before = self.t % LOOP_S
        self.t += min(0.1, now - self._last)
        self._last = now
        after = self.t % LOOP_S
        # time's up: stop the next time he's on his thumbs-up, so he never freezes mid-move
        if hooks.still() or (self.t >= self._rest_at and before <= HOLD_U <= after):
            self.t += HOLD_U - after
            self.resting = True
            self._pause()
        self.update()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            if not hooks.still():   # another while of moving
                self.resting = False
                self._rest_at = self.t + REST_S
                self._resume()
        super().mousePressEvent(ev)

    # ------------------------------------------------------------------ the pose
    def _pose(self) -> dict:
        t = self.t
        u = t % LOOP_S
        reach = _seg(u, 0.8, 1.6) * (1 - _seg(u, 2.2, 2.8))
        up = _seg(u, 2.2, 2.8) * (1 - _seg(u, 4.6, 5.3))
        join = _seg(u, 1.0, 1.9) * (1 - _seg(u, 4.9, 5.8))
        lit = _seg(u, 1.85, 1.95) * (1 - _seg(u, 4.8, 4.95))
        flash = max(0.0, 1 - (u - 1.9) / 0.6) if u >= 1.9 else 0.0
        hop = -9 * math.sin(math.pi * min(1.0, max(0.0, (u - 2.2) / 0.6)))
        calm = 1 - _seg(u, 0.6, 1.0) + _seg(u, 2.8, 3.4)    # still while he works
        bob = math.sin(t * 2 * math.pi / BOB_S) * calm
        if self.resting:
            bob = 0.0
        blink = (u % 3.0) - 0.3
        return {
            "dy": bob * 7 + hop, "tilt": -bob * 3,
            "left": -38 * reach, "right": 38 * reach - 78 * up, "wrist": -38 * reach + 78 * up,
            "thumb": _seg(u, 2.5, 2.85) * (1 - _seg(u, 4.5, 4.8)), "happy": up > 0.5,
            "gap": 30 * (1 - join), "lit": lit, "flash": flash,
            "kick": 0.5 - 0.5 * math.cos(t * 2 * math.pi / KICK_S),
            "ears": math.sin(t * 2 * math.pi / BOB_S - 0.9) * 5 * (0.4 + 0.6 * calm),
            "blink": 0.0 <= blink < 0.12 and up < 0.5,
        }

    # ------------------------------------------------------------------ drawing
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        frame = QPainterPath()
        frame.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)
        p.setClipPath(frame)
        s = self.height() / VIEW.height()
        p.scale(s, s)
        p.translate(-VIEW.left(), -VIEW.top())
        pose = self._pose()
        self._water(p)
        self._floor(p)
        self._bubbles(p)
        p.save()
        self._bun_space(p, pose)
        self._body(p, pose)
        p.restore()
        self._cables(p, pose)
        p.save()
        self._bun_space(p, pose)
        self._hands(p, pose)
        p.restore()
        p.resetTransform()
        p.setClipping(False)
        p.setPen(QPen(_rgba("#ffffff", 0.14), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(frame)
        p.end()

    @staticmethod
    def _bun_space(p: QPainter, pose: dict):
        """The add-on draws Bun at 1.25x round (320, 190); he bobs and tilts round it."""
        p.translate(0, pose["dy"])
        p.translate(320, 190)
        p.rotate(pose["tilt"])
        p.scale(1.25, 1.25)
        p.translate(-320, -190)

    @staticmethod
    def _pen(color: str = INK, w: float = 3.0) -> QPen:
        pen = QPen(QColor(color), w)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        return pen

    def _ellipse(self, p: QPainter, cx, cy, rx, ry, fill: str, rot: float = 0.0,
                 stroke: bool = True):
        p.save()
        p.translate(cx, cy)
        p.rotate(rot)
        p.setPen(self._pen() if stroke else Qt.PenStyle.NoPen)
        p.setBrush(QColor(fill))
        p.drawEllipse(QRectF(-rx, -ry, 2 * rx, 2 * ry))
        p.restore()

    # the scene
    def _water(self, p: QPainter):
        v = VIEW
        g = QLinearGradient(0, v.top(), 0, v.bottom())
        g.setColorAt(0.0, QColor(WATER[0]))
        g.setColorAt(0.55, QColor(WATER[1]))
        g.setColorAt(1.0, QColor(WATER[2]))
        p.fillRect(v, g)
        # sunlight from the surface, slowly swaying
        p.setPen(Qt.PenStyle.NoPen)
        for i, (x, w) in enumerate(((236, 26), (318, 40), (410, 22))):
            sway = math.sin(self.t * 0.7 + i * 1.9) * 10
            a = 0.10 + 0.05 * math.sin(self.t * 1.1 + i * 2.3)
            ray = QLinearGradient(0, v.top(), 0, v.bottom() - 30)
            ray.setColorAt(0, _rgba("#ffffff", a))
            ray.setColorAt(1, _rgba("#ffffff", 0.0))
            p.setBrush(ray)
            p.drawPolygon(QPolygonF([QPointF(x, v.top()), QPointF(x + w, v.top()),
                                     QPointF(x + w * 2 - 30 + sway, v.bottom()),
                                     QPointF(x - 34 + sway, v.bottom())]))
        # the surface shimmer
        p.setPen(QPen(_rgba("#ffffff", 0.35), 2, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        wave = QPainterPath(QPointF(v.left(), v.top() + 6))
        for k in range(0, 12):
            x = v.left() + k * 26
            off = math.sin(self.t * 1.6 + k) * 2
            wave.quadTo(x + 13, v.top() + 2 + off, x + 26, v.top() + 6)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(wave)
        # specks drifting up
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_rgba("#e9fbff", 0.45))
        span = v.height()
        for x, y, r, speed in SPECKS:
            yy = v.top() + ((y - v.top() - self.t * speed) % span)
            p.drawEllipse(QPointF(x + math.sin(self.t + y) * 3, yy), r, r)

    def _weed(self, p: QPainter, x: float, height: float, phase: float, color: str):
        base = VIEW.bottom()
        path = QPainterPath(QPointF(x, base))
        segs = 4
        for k in range(1, segs + 1):
            y = base - height * k / segs
            sway = math.sin(self.t * 1.3 + phase + k * 0.7) * 3 * k
            cx = x + (8 if k % 2 else -8) + sway * 0.6
            path.quadTo(cx, y + height / segs / 2, x + sway, y)
        pen = self._pen(color, 7)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

    def _floor(self, p: QPainter):
        v = VIEW
        self._weed(p, 194, 128, 0.0, WEED_DARK)
        self._weed(p, 206, 92, 1.4, WEED)
        self._weed(p, 444, 112, 2.1, WEED)
        self._weed(p, 455, 76, 0.7, WEED_DARK)
        sand = QPainterPath(QPointF(v.left(), 318))
        sand.quadTo(240, 309, 300, 315)
        sand.quadTo(380, 323, v.right(), 312)
        sand.lineTo(v.right(), v.bottom())
        sand.lineTo(v.left(), v.bottom())
        sand.closeSubpath()
        g = QLinearGradient(0, 310, 0, v.bottom())
        g.setColorAt(0, QColor(SAND_TOP))
        g.setColorAt(1, QColor(SAND))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawPath(sand)
        p.setBrush(_rgba("#b8925c", 0.7))
        for x, y, rx in ((214, 322, 5), (252, 326, 3), (398, 324, 4), (430, 320, 6)):
            p.drawEllipse(QPointF(x, y), rx, rx * 0.6)

    def _bubbles(self, p: QPainter):
        if self.resting:
            return
        for phase, drift, r, rise in BUBBLES:
            k = ((self.t / rise) + phase) % 1.0
            x = 372 + drift + math.sin(k * 9 + phase * 6) * 4
            y = 168 - 120 * k
            a = min(1.0, k / 0.12) * (1 - _ease((k - 0.7) / 0.3))
            rr = r * (0.7 + 0.3 * k)
            p.setPen(QPen(_rgba("#ffffff", 0.75 * a), 1.6))
            p.setBrush(_rgba("#ffffff", 0.16 * a))
            p.drawEllipse(QPointF(x, y), rr, rr)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_rgba("#ffffff", 0.85 * a))
            p.drawEllipse(QPointF(x - rr * 0.35, y - rr * 0.35), rr * 0.28, rr * 0.28)

    # the cables he plugs together (not in Bun's space: they lie on the sand)
    def _cables(self, p: QPainter, pose: dict):
        gap = pose["gap"]
        for side in (-1, 1):
            p.save()
            p.translate(side * gap, 0)
            path = QPainterPath(QPointF(320 + side * 250, 310))
            path.cubicTo(320 + side * 200, 310, 320 + side * 175, 328, 320 + side * 110, 310)
            path.cubicTo(320 + side * 45, 292, 320 + side * 53, 290, 320 + side * 23, 290)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(self._pen("#485269", 12))
            p.drawPath(path)
            p.setPen(self._pen("#93a5bd", 3))
            p.drawPath(path.translated(0, -3))
            p.setPen(self._pen())
            if side < 0:
                p.setBrush(QColor("#9e7ce5"))
                p.drawRoundedRect(QRectF(290, 277, 30, 26), 5, 5)
                p.setPen(self._pen("#c6b0fb", 3))
                p.drawLine(QPointF(311, 283), QPointF(311, 297))
                p.drawLine(QPointF(301, 283), QPointF(301, 297))
            else:
                p.setBrush(QColor(BELLY))
                p.drawRoundedRect(QRectF(320, 279, 31, 22), 4, 4)
                p.setPen(self._pen("#9aa0b4", 3))
                p.drawLine(QPointF(337, 283), QPointF(337, 297))
                p.drawLine(QPointF(344, 283), QPointF(344, 297))
            p.restore()
        lit, flash = pose["lit"], pose["flash"]
        if lit <= 0:
            return
        glow = QRadialGradient(QPointF(322, 290), 40 + 40 * flash)
        glow.setColorAt(0, _rgba(LIT, 0.55 * lit + 0.3 * flash))
        glow.setColorAt(1, _rgba(LIT, 0.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(322, 290), 40 + 40 * flash, 40 + 40 * flash)
        p.setBrush(_rgba(LIT, lit))
        p.drawEllipse(QPointF(326, 290), 4, 4)
        grow = 1 + 0.6 * flash
        p.setPen(self._pen(LIT, 2.5))
        # sparks out to the sides of the plug (above it is Bun's belly)
        for (x1, y1), (x2, y2) in (((284, 284), (274, 278)), ((284, 296), (274, 302)),
                                   ((358, 284), (368, 278)), ((358, 296), (368, 302)),
                                   ((321, 308), (321, 316))):
            p.drawLine(QPointF(x1, y1), QPointF(x1 + (x2 - x1) * grow, y1 + (y2 - y1) * grow))

    # Bun
    def _body(self, p: QPainter, pose: dict):
        e = self._ellipse
        e(p, 364, 228, 13, 12, FUR)            # tail
        e(p, 320, 224, 34, 36, FUR)            # body
        e(p, 320, 233, 22, 24, BELLY, stroke=False)
        p.setPen(self._pen())
        p.setBrush(QColor(GEAR))
        kick = pose["kick"] * 22
        for path, ox, oy, sign in ((_quad(293, 249, 276, 260, 276, 280, 297, 283, 306, 255),
                                    291, 249, 1),
                                   (_quad(336, 250, 350, 264, 354, 281, 332, 283, 324, 256),
                                    339, 250, -1)):
            path.closeSubpath()
            p.save()
            p.translate(ox, oy)
            p.rotate(kick * sign)
            p.translate(-ox, -oy)
            p.drawPath(path)
            p.restore()
        for cx, cy, rx, ry, rot, sign in ((298, 135, 13, 37, -12, -1), (341, 137, 13, 35, 17, 1)):
            p.save()           # the ears sway from their roots
            p.translate(cx, cy + ry - 6)
            p.rotate(pose["ears"] * sign)
            p.translate(-cx, -(cy + ry - 6))
            e(p, cx, cy, rx, ry, FUR, rot)
            e(p, cx, cy + 1, 6, ry - 12, PINK, rot, stroke=False)
            p.restore()
        e(p, 320, 183, 43, 37, FUR)            # head
        p.setBrush(_rgba(PINK, 0.8))           # cheeks
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(294, 203), 6, 3.5)
        p.drawEllipse(QPointF(346, 203), 6, 3.5)
        p.setBrush(Qt.BrushStyle.NoBrush)       # the mask's strap
        p.setPen(self._pen(GEAR, 9))
        p.drawPath(_quad(279, 180, 273, 135, 320, 141, 366, 141, 362, 182))
        p.setPen(self._pen())
        p.setBrush(QColor(GEAR))
        p.drawRoundedRect(QRectF(271, 170, 13, 27), 6, 6)
        p.drawRoundedRect(QRectF(356, 170, 13, 27), 6, 6)
        p.setBrush(_rgba(GLASS, 0.65))
        p.setPen(self._pen(GLASS_EDGE))
        p.drawRoundedRect(QRectF(287, 169, 66, 27), 12, 12)
        if pose["happy"]:                       # ^ ^ while the thumb's up
            p.setPen(self._pen(INK, 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(_quad(301, 186, 306, 177, 311, 186))
            p.drawPath(_quad(330, 186, 335, 177, 340, 186))
        elif pose["blink"]:
            p.setPen(self._pen(INK, 3))
            p.drawLine(QPointF(302, 183), QPointF(310, 183))
            p.drawLine(QPointF(331, 183), QPointF(339, 183))
        else:
            e(p, 306, 183, 3, 5, INK, stroke=False)
            e(p, 335, 183, 3, 5, INK, stroke=False)
        p.setPen(self._pen(GLINT))
        p.drawLine(QPointF(293, 175), QPointF(307, 173))
        p.drawLine(QPointF(331, 175), QPointF(343, 173))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(self._pen())
        p.drawPath(_quad(316, 198, 320, 204, 325, 198))
        if pose["happy"]:                       # a wide open smile
            smile = _quad(310, 206, 320, 220, 331, 205)
            smile.closeSubpath()
            p.setBrush(QColor("#e86a8a"))
            p.drawPath(smile)
        else:
            p.drawPath(_quad(311, 207, 320, 214, 330, 206))

    def _arm(self, p: QPainter, path: QPainterPath):
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(self._pen(INK, 18))
        p.drawPath(path)
        p.setPen(self._pen(FUR, 12))
        p.drawPath(path)

    def _paw(self, p: QPainter, x: float, y: float, line_x: float):
        p.setPen(self._pen())
        p.setBrush(QColor(FUR))
        p.drawEllipse(QPointF(x, y), 9, 9)
        p.setPen(self._pen("#c6bdb7", 1.5))
        p.drawLine(QPointF(line_x, y + 1.5), QPointF(line_x + 6, y + 1.5))

    @staticmethod
    def _turn(p: QPainter, x: float, y: float, deg: float):
        p.translate(x, y)
        p.rotate(deg)
        p.translate(-x, -y)

    def _hands(self, p: QPainter, pose: dict):
        p.save()
        self._turn(p, 300, 219, pose["left"])
        self._arm(p, _quad(300, 219, 289, 230, 285, 251))
        self._paw(p, 285, 251, 281)
        p.restore()
        # the right arm swings up (the add-on's -78 deg at the shoulder, +78 at the
        # wrist: the paw stays upright) and the thumb stands up from the paw
        p.save()
        self._turn(p, 340, 219, pose["right"])
        self._arm(p, _quad(340, 219, 350, 230, 351, 251))
        self._turn(p, 351, 251, pose["wrist"])
        thumb = pose["thumb"]
        if thumb > 0.05:
            p.save()
            p.translate(350.5, 248)
            p.scale(1, max(0.1, thumb))
            p.translate(-350.5, -248)
            t = QPainterPath(QPointF(346, 248))
            t.lineTo(346, 234)
            t.quadTo(346, 228, 350, 228)
            t.quadTo(355, 228, 355, 234)
            t.lineTo(355, 248)
            t.closeSubpath()
            p.setPen(self._pen())
            p.setBrush(QColor(FUR))
            p.drawPath(t)
            p.restore()
        self._paw(p, 351, 251, 348)
        p.restore()
