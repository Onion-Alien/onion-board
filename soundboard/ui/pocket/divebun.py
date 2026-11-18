"""Bun diving, the Pocket tab's picture: the app's own Bun (soundboard/ui/bun/bunny.py's
draw_bunny, in the current theme's look) in a dive mask, snorkel and flippers, in a
small underwater scene. He floats, kicking his flippers, holding the phone's cable in
one paw and the PC's in the other; he clicks them together, the plug lights up, and he
waves, beaming; then he pulls them apart and does it again.

He moves for REST_S after he's shown, then stops on his wave until he's clicked (as
Hoot does on the Triggers tab), never behind another app (appstate) and never in Lite
mode (hooks.still): a still picture then. Everything is drawn as shapes every frame, so
he's sharp at any screen scale."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPolygonF, QRadialGradient, QTransform)
from PySide6.QtWidgets import QWidget

from soundboard.style import appstate, bunnyfit, hooks
from soundboard.ui.bun.bunny import INK, LEG_HIPS, draw_bunny, standing_feet

# the scene's own coordinates, and where Bun's 100 x 120 canvas sits in them
VIEW = QRectF(178, 62, 284, 270)
BUN_AT, BUN_S = QPointF(253, 80), 1.34   # (standing, fins and all, clear of the sand)
WATER = ("#4cc3d4", "#1f87a6", "#123c63")       # top, middle, floor
SAND, SAND_TOP, WEED, WEED_DARK = "#d6b27a", "#ecd3a2", "#3fb07f", "#2a8a62"
GLASS, GLINT = QColor(150, 235, 245, 70), QColor(255, 255, 255, 190)
CABLE, CABLE_HI = "#4a5368", "#8e9cb4"
PHONE_PLUG, PC_PLUG, METAL = "#3a3452", "#e8e2f0", "#c9ccd8"
LIT = "#79f5ce"
FRAME_MS = 33
REST_S = 30.0
LOOP_S = 6.0     # one plug-in, wave and let-go
HOLD_U = 3.3     # the moment in the loop he rests on (plugged in, waving)
BOB_S = 3.0
KICK_S = 0.9     # one flutter of his flippers
# his paws (canvas), holding the phone's plug (left) and the PC's socket (right):
# apart, and clicked together
APART = ((18.0, 98.0), (82.0, 98.0))
JOINED = ((35.5, 103.0), (64.5, 103.0))
WAVE_AT = (87.5, 84.5)   # where draw_bunny's waving paw starts (bunny._wave_paw(0))
SNORKEL_TOP = QPointF(5.5, 16)
# bubbles from his snorkel: phase, x drift, radius, rise time
BUBBLES = ((0.0, 0, 5.0, 2.6), (0.22, 5, 3.0, 2.2), (0.47, -4, 4.2, 2.9),
           (0.68, 3, 2.6, 2.0), (0.85, -2, 3.4, 2.4))
# specks floating in the water: x, y, size, speed
SPECKS = ((196, 120, 1.6, 5), (230, 250, 1.2, 7), (262, 90, 1.0, 4), (300, 300, 1.4, 6),
          (402, 110, 1.3, 5), (432, 210, 1.7, 8), (452, 280, 1.1, 4), (380, 70, 1.0, 6),
          (214, 180, 1.0, 3), (446, 150, 1.2, 5))


def _ease(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def _seg(u: float, a: float, b: float) -> float:
    return _ease((u - a) / (b - a))


def _mix(a, b, k: float) -> tuple[float, float]:
    return a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k


def _rgba(color, alpha: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def _pen(color, w: float) -> QPen:
    pen = QPen(QColor(color), w)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    return pen


def _gear() -> QColor:
    """His dive gear's colour: the theme's second colour, as his hats are (the
    headphones are the first), or the next one that stands out from his fur."""
    pal = hooks.palette()
    fur = QColor(bunnyfit.look()["fur"])
    for c in (pal.get("accent2"), pal.get("accent"), "#ff8a3d"):
        if c and not _near(QColor(c), fur):
            return QColor(c)
    return QColor("#3fc6e0")


def _near(a: QColor, b: QColor) -> bool:
    """Too alike to tell apart at a glance: close in colour, or the same hue on
    coloured fur."""
    if abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue()) < 150:
        return True
    if b.hsvSaturationF() < 0.2 or a.hsvHue() < 0 or b.hsvHue() < 0:
        return False
    d = abs(a.hsvHue() - b.hsvHue()) % 360
    return min(d, 360 - d) < 40


def _outfit() -> tuple[str, ...]:
    """The theme's outfit, less anything on his eyes (the mask is there) and anything
    cut for his sitting body (a sweater: he's standing)."""
    return tuple(n for n in bunnyfit.outfit()
                 if n not in bunnyfit.EYEWEAR and n not in bunnyfit.HIDE_EYES
                 and n not in ("laser", "spirals", "sweater", "collar"))


class DiveBun(QWidget):
    clicked = Signal()

    def __init__(self, height: int = 196, parent: QWidget | None = None):
        super().__init__(parent)
        self.bun_h = height
        self.t = HOLD_U
        self._last = 0.0
        self._rest_at = REST_S
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
        # time's up: stop the next time he's waving, so he never freezes mid-move
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
        join = _seg(u, 0.9, 1.8) * (1 - _seg(u, 4.9, 5.7))
        lit = _seg(u, 1.8, 1.9) * (1 - _seg(u, 4.8, 4.9))
        flash = max(0.0, 1 - (u - 1.85) / 0.6) if u >= 1.85 else 0.0
        # his right paw lets go of the plugged-in pair and goes up to wave, and back
        up = _seg(u, 2.2, 2.45) * (1 - _seg(u, 4.35, 4.6))
        waving = 2.45 <= u < 4.35
        happy = _seg(u, 2.0, 2.3) * (1 - _seg(u, 4.2, 4.5))
        calm = 1 - _seg(u, 0.6, 1.0) + _seg(u, 2.0, 2.6)   # steady while he works
        bob = 0.0 if self.resting else math.sin(t * 2 * math.pi / BOB_S) * calm
        left = _mix(APART[0], JOINED[0], join)
        right = _mix(_mix(APART[1], JOINED[1], join), WAVE_AT, up)
        blink = (u % 3.0) - 0.3
        return {
            "dy": bob * 6 - 3 * _ease(join) * (1 - happy), "tilt": -bob * 2.5,
            "nod": 6 * _ease(join) * (1 - happy) - 3 * happy,
            "left": left, "right": None if waving else right,
            "wave": (math.sin((u - 2.45) * 2 * math.pi / 0.9) * 0.9) if waving else None,
            "blink": 1.0 if happy > 0.5 else (1.0 if 0.0 <= blink < 0.12 else 0.0),
            "mouth": 0.45 * happy,
            "ears": math.sin(t * 2 * math.pi / BOB_S - 0.9) * 6 * (0.4 + 0.6 * calm),
            "kick": math.sin(t * 2 * math.pi / KICK_S) * (0.5 + 0.5 * calm),
            "lit": lit, "flash": flash, "join": join, "up": up,
        }

    def _bun_xf(self, pose: dict) -> QTransform:
        """Bun's canvas into the scene: bobbing and leaning round his middle."""
        mid = QPointF(BUN_AT.x() + 50 * BUN_S, BUN_AT.y() + 70 * BUN_S)
        xf = QTransform()
        xf.translate(0, pose["dy"])
        xf.translate(mid.x(), mid.y())
        xf.rotate(pose["tilt"])
        xf.translate(-mid.x(), -mid.y())
        xf.translate(BUN_AT.x(), BUN_AT.y())
        xf.scale(BUN_S, BUN_S)
        return xf

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
        scene = p.transform()
        pose = self._pose()
        bun = self._bun_xf(pose)
        self._water(p)
        self._floor(p)
        p.setTransform(bun * scene)
        draw_bunny(p, QRectF(0, 0, 100, 120), None, blink=pose["blink"],
                   mouth=pose["mouth"], ears=pose["ears"], nod=pose["nod"],
                   outfit=_outfit(), wave=pose["wave"], stand=True, kick=pose["kick"],
                   hold=(self._grip(pose["left"]), self._grip(pose["right"])))
        self._fins(p, pose)
        self._mask(p, pose)
        self._cables(p, pose, bun)
        self._held(p, pose)
        p.setTransform(scene)
        self._bubbles(p, bun.map(self._snorkel_top(pose)))
        p.resetTransform()
        p.setClipping(False)
        p.setPen(QPen(_rgba("#ffffff", 0.14), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(frame)
        p.end()

    @staticmethod
    def _grip(at):
        """A paw's spot for draw_bunny's `hold`, on a half-unit grid (its arm shapes are
        kept per spot)."""
        return None if at is None else (round(at[0] * 2) / 2, round(at[1] * 2) / 2)

    @staticmethod
    def _head(p: QPainter, pose: dict):
        """Into his head's frame, as draw_bunny tilts it on his neck."""
        p.translate(50, 92)
        p.rotate(pose["nod"])
        p.translate(-50, -92)

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
        p.setPen(_pen(color, 7))
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

    def _bubbles(self, p: QPainter, top: QPointF):
        if self.resting:
            return
        for phase, drift, r, rise in BUBBLES:
            k = ((self.t / rise) + phase) % 1.0
            x = top.x() + drift + math.sin(k * 9 + phase * 6) * 4
            y = top.y() - 4 - (top.y() - VIEW.top()) * k
            a = min(1.0, k / 0.12) * (1 - _ease((k - 0.7) / 0.3))
            rr = r * (0.7 + 0.3 * k)
            p.setPen(QPen(_rgba("#ffffff", 0.75 * a), 1.4))
            p.setBrush(_rgba("#ffffff", 0.16 * a))
            p.drawEllipse(QPointF(x, y), rr, rr)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_rgba("#ffffff", 0.85 * a))
            p.drawEllipse(QPointF(x - rr * 0.35, y - rr * 0.35), rr * 0.28, rr * 0.28)

    # his dive gear (Bun's canvas)
    def _fins(self, p: QPainter, pose: dict):
        """A fin on each foot, at the end of his standing legs: a foot pocket round his
        foot, then a slim blade that widens a little to a notched end. Each lines up
        with its leg, splayed out a touch, and flaps at the ankle against the kick (the
        blade trails behind the foot's swing, as real fins do)."""
        gear = _gear()
        for i, (hip, ankle) in enumerate(zip(LEG_HIPS, standing_feet(pose["kick"]))):
            out = -1 if i == 0 else 1
            lift = -pose["kick"] if i == 0 else pose["kick"]   # >0: this leg's going up
            along = math.degrees(math.atan2(ankle[0] - hip[0], ankle[1] - hip[1]))
            p.save()
            p.translate(*ankle)
            p.rotate(-along - out * 7 + out * 16 * lift)
            # the blade (under the pocket): out from the foot to a notched tip
            blade = QPainterPath(QPointF(-5.5, 6))
            blade.cubicTo(QPointF(-6.5, 14), QPointF(-9, 22), QPointF(-9.5, 31))
            blade.quadTo(QPointF(-4.5, 29), QPointF(0, 26.5))                 # the notch
            blade.quadTo(QPointF(4.5, 29), QPointF(9.5, 31))
            blade.cubicTo(QPointF(9, 22), QPointF(6.5, 14), QPointF(5.5, 6))
            blade.closeSubpath()
            p.setPen(_pen(INK, 2.4))
            p.setBrush(gear)
            p.drawPath(blade)
            p.setPen(_pen(gear.darker(125), 1.4))   # its ribs
            p.drawLine(QPointF(-3.2, 13), QPointF(-6.0, 27))
            p.drawLine(QPointF(3.2, 13), QPointF(6.0, 27))
            # the foot pocket, a darker cap over his foot
            pocket = QPainterPath()
            pocket.addRoundedRect(QRectF(-7.2, -3.5, 14.4, 15.5), 6.5, 6.5)
            p.setPen(_pen(INK, 2.4))
            p.setBrush(gear.darker(118))
            p.drawPath(pocket)
            p.setPen(_pen(gear.lighter(140), 1.3))   # a shine on it
            p.drawLine(QPointF(-4.2, 0.5), QPointF(-4.2, 6.5))
            p.restore()

    def _mask(self, p: QPainter, pose: dict):
        """A dive mask over his eyes (you see them through the glass), its strap to his
        headphones, and a snorkel up by his left ear cup."""
        gear = _gear()
        p.save()
        self._head(p, pose)
        # the snorkel: a tube up the side of his head, clipped to the strap
        tube = QPainterPath(QPointF(16, 82))
        tube.quadTo(QPointF(3, 80), QPointF(4, 64))
        tube.lineTo(QPointF(SNORKEL_TOP.x(), SNORKEL_TOP.y() + 6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(_pen(INK, 7.4))
        p.drawPath(tube)
        p.setPen(_pen(gear, 4.4))
        p.drawPath(tube)
        p.setPen(_pen(gear.lighter(140), 1.4))
        p.drawPath(tube.translated(-1.0, 0))
        p.setPen(_pen(INK, 2.2))
        p.setBrush(QColor("#ff8a3d"))   # the orange top, to be seen from the boat
        p.drawRoundedRect(QRectF(SNORKEL_TOP.x() - 4.5, SNORKEL_TOP.y(), 9, 8), 3, 3)
        # the strap, from the mask's sides back to the ear cups
        y = bunnyfit.EYE_Y
        for x0, x1 in ((24, 19), (76, 81)):
            p.setPen(_pen(INK, 5.4))
            p.drawLine(QPointF(x0, y - 1), QPointF(x1, y - 1))
            p.setPen(_pen(gear.darker(115), 3.0))
            p.drawLine(QPointF(x0, y - 1), QPointF(x1, y - 1))
        # the glass: one wide lens, lightly tinted, with a glint
        lens = QPainterPath()   # (above his nose: his smile stays in sight)
        lens.addRoundedRect(QRectF(23.5, y - 12.5, 53, 19.5), 9.5, 9.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(GLASS)
        p.drawPath(lens)
        p.save()
        p.setClipPath(lens)
        p.setPen(_pen(GLINT, 2.0))
        p.drawLine(QPointF(28, y + 3), QPointF(33.5, y - 7))
        p.setPen(_pen(_rgba("#ffffff", 0.55), 1.4))
        p.drawLine(QPointF(32, y + 4), QPointF(36, y - 3))
        p.drawLine(QPointF(58, y + 3), QPointF(62, y - 5))
        p.restore()
        # its frame: ink round a band of gear colour, like his headphones' band
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(_pen(INK, 6.2))
        p.drawPath(lens)
        p.setPen(_pen(gear, 3.4))
        p.drawPath(lens)
        p.setPen(_pen(gear.lighter(145), 1.2))
        top = QPainterPath(QPointF(31, y - 13.5))
        top.lineTo(QPointF(47, y - 13.5))
        p.drawPath(top)
        p.restore()

    @staticmethod
    def _snorkel_top(pose: dict) -> QPointF:
        head = QTransform().translate(50, 92).rotate(pose["nod"]).translate(-50, -92)
        return head.map(QPointF(SNORKEL_TOP.x(), SNORKEL_TOP.y()))

    # the cables and what's in his paws (Bun's canvas)
    def _cables(self, p: QPainter, pose: dict, bun: QTransform):
        """Each cable from the sand at the scene's edge up to the plug in his paw."""
        inv, _ok = bun.inverted()
        (lx, ly), (rx, ry) = pose["left"], self._socket_at(pose)
        # (out to the side first, so they clear his feet)
        for (sx, sy), (ex, ey), side in (((VIEW.left() - 10, 314), (lx, ly), -1),
                                         ((VIEW.right() + 10, 312), (rx, ry), 1)):
            start = inv.map(QPointF(sx, sy))
            path = QPainterPath(QPointF(ex, ey))
            path.cubicTo(QPointF(ex + side * 22, ey + 2), QPointF(start.x() - side * 40,
                                                               start.y() - 6), start)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(_pen(INK, 6.4))
            p.drawPath(path)
            p.setPen(_pen(CABLE, 4.0))
            p.drawPath(path)
            p.setPen(_pen(CABLE_HI, 1.2))
            p.drawPath(path.translated(0, -1.0))

    @staticmethod
    def _socket_at(pose: dict):
        """The PC's socket: in his right paw, or plugged onto the phone's plug from the
        moment that paw lets go to wave until it's back (never carried up and dropped)."""
        if pose["right"] is not None and not pose.get("up"):
            return pose["right"]
        lx, ly = pose["left"]
        return lx + JOINED[1][0] - JOINED[0][0], ly + JOINED[1][1] - JOINED[0][1]

    def _held(self, p: QPainter, pose: dict):
        ink = _pen(INK, 2.4)
        fur = QColor(bunnyfit.look()["fur"])
        (lx, ly), (rx, ry) = pose["left"], self._socket_at(pose)
        # the phone's plug, pins out to the right; the PC's socket, open to the left
        p.setPen(ink)
        p.setBrush(QColor(METAL))
        p.drawRoundedRect(QRectF(lx + 12, ly - 2.6, 5, 5.2), 1.2, 1.2)
        p.setBrush(QColor(PHONE_PLUG))
        p.drawRoundedRect(QRectF(lx + 1, ly - 4.8, 12, 9.6), 3, 3)
        p.setPen(_pen("#6b6390", 1.2))
        p.drawLine(QPointF(lx + 5, ly - 2.5), QPointF(lx + 10, ly - 2.5))
        p.setPen(ink)
        p.setBrush(QColor(PC_PLUG))
        p.drawRoundedRect(QRectF(rx - 15, ry - 5.6, 14, 11.2), 3, 3)
        p.setPen(_pen("#9aa0b4", 1.4))
        p.drawLine(QPointF(rx - 12, ry - 2.2), QPointF(rx - 12, ry + 2.2))
        # the glow once they click
        lit, flash = pose["lit"], pose["flash"]
        if lit > 0:
            cx, cy = (lx + 17 + rx - 15) / 2, (ly + ry) / 2
            r = 11 + 13 * flash
            glow = QRadialGradient(QPointF(cx, cy), r)
            glow.setColorAt(0, _rgba(LIT, 0.55 * lit + 0.3 * flash))
            glow.setColorAt(1, _rgba(LIT, 0.0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QPointF(cx, cy), r, r)
            p.setBrush(_rgba(LIT, lit))
            p.drawEllipse(QPointF(rx - 5, ry), 1.6, 1.6)
            grow = 1 + 0.6 * flash
            p.setPen(_pen(_rgba(LIT, lit), 1.6))
            for dx, dy in ((-0.6, -1), (0.6, -1), (-0.7, 0.9), (0.7, 0.9), (0, 1.2)):
                x1, y1 = cx + dx * 9, cy + dy * 7
                p.drawLine(QPointF(x1, y1), QPointF(x1 + dx * 5 * grow, y1 + dy * 4 * grow))
        # his paws over them (draw_bunny's arms reach here: `hold`)
        p.setPen(ink)
        p.setBrush(fur)
        for at in (pose["left"], pose["right"]):
            if at is not None:
                p.drawEllipse(QPointF(*at), 5.5, 5.0)
