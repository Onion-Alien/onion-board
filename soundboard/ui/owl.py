"""Hoot, Onion Watch's mascot: a cartoon owl (owls keep watch), drawn with QPainter
in the same style as Bun, so it's crisp at any size and needs no image files. The
Triggers tab shows Hoot until the Onion Watch add-on is installed (a copy of
onionwatch/owl.py from the Onion Watch project: the tab needs it before there's
any Onion Watch to take it from; keep the two the same).

    owl_image(160)             # QImage, transparent background
    OwlWidget(96, lines=...)   # Hoot alive: waiting, begging, sulking
"""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from soundboard.ui import appstate

# drawn on a 100 x 120 canvas, scaled to the requested height
W, H = 100.0, 120.0
INK = QColor("#2b2340")
FEATHER = QColor("#4fc3b0")
FEATHER_DARK = QColor("#2f9c8c")
BELLY = QColor("#f4efe6")
BELLY_MARK = QColor("#d9cfbf")
BEAK = QColor("#ffb347")
EYE_RING = QColor("#fff6d8")
CHEEK = QColor(255, 128, 160, 110)
TEAR = QColor("#8fd3ff")
BUBBLE = QColor("#fffaf0")
SPARKLE_COLORS = ("#ffcf40", "#ff8fae", "#1fb6ff", "#a48bff")
EYES = (36, 64)
FPS = 30


def _e(p, cx, cy, w, h, fill, pen=None, angle=0.0):
    p.save()
    p.translate(cx, cy)
    p.rotate(angle)
    p.setPen(pen or Qt.NoPen)
    p.setBrush(fill)
    p.drawEllipse(QRectF(-w / 2, -h / 2, w, h))
    p.restore()


def _mix(a: float, b: float, k: float) -> float:
    return a + (b - a) * k


def draw_owl(p: QPainter, rect: QRectF, look: float = 0.0, feather=FEATHER, dark=FEATHER_DARK,
             *, look_y: float = 0.0, blink: float = 0.0, sad: float = 0.0,
             tufts: float = 0.0, clasp: float = 0.0, flap: float = 0.0,
             plead: float = 0.0, tear: float = 0.0):
    """Draw Hoot fitted (aspect kept, centred) into `rect`. `look` / `look_y` -1..1
    turn the pupils left / right and up / down: watching. The keywords pose him for
    OwlWidget: `blink` 0..1 closes the eyes, `sad` 0..1 worries the brows and wets
    the eyes, `tufts` droops the ear tufts by that many degrees (negative perks them
    up), `clasp` 0..1 brings the wings together in front (begging), `flap` 0..1 lifts
    them (joy), `plead` 0..1 makes the pupils big and shiny, and `tear` 0..1 rolls a
    tear down his cheek (0 = none)."""
    s = min(rect.width() / W, rect.height() / H)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.translate(rect.center().x() - W * s / 2, rect.center().y() - H * s / 2)
    p.scale(s, s)
    ink = QPen(INK, 2.4)
    ink.setJoinStyle(Qt.RoundJoin)
    ink.setCapStyle(Qt.RoundCap)

    # ear tufts, turned about their base
    for sx in (-1, 1):
        p.save()
        p.translate(50 + sx * 25, 38)
        p.rotate(sx * tufts)
        p.translate(-(50 + sx * 25), -38)
        tuft = QPainterPath(QPointF(50 + sx * 16, 34))
        tuft.quadTo(QPointF(50 + sx * 30, 22), QPointF(50 + sx * 34, 10))
        tuft.quadTo(QPointF(50 + sx * 36, 30), QPointF(50 + sx * 34, 44))
        tuft.closeSubpath()
        p.setPen(ink)
        p.setBrush(dark)
        p.drawPath(tuft)
        p.restore()
    # body (one round egg: owls are all head)
    body = QPainterPath()
    body.addRoundedRect(QRectF(16, 24, 68, 88), 34, 36)
    p.setPen(ink)
    p.setBrush(feather)
    p.drawPath(body)
    # belly with little feather marks
    _e(p, 50, 88, 42, 40, BELLY)
    p.setPen(QPen(BELLY_MARK, 1.8, Qt.SolidLine, Qt.RoundCap))
    p.setBrush(Qt.NoBrush)
    for x, y in ((42, 80), (50, 84), (58, 80), (46, 92), (54, 92), (50, 100)):
        m = QPainterPath(QPointF(x - 3, y))
        m.quadTo(x, y + 3, x + 3, y)
        p.drawPath(m)
    # feet
    for x in (40, 60):
        p.setPen(ink)
        p.setBrush(BEAK)
        for dx in (-3.5, 0, 3.5):
            _e(p, x + dx, 113, 4.2, 6, BEAK, QPen(INK, 1.6))
    # wings: at his sides, clasped in front of the belly, or flung up
    for sx in (-1, 1):
        x = 50 + sx * (_mix(33, 15, clasp) + 5 * flap)
        y = 80 + 5 * clasp - 10 * flap
        ang = -sx * (_mix(12, 30, clasp) - 70 * flap)
        _e(p, x, y, 16, 38, dark, ink, ang)
    # face disc
    face = QPainterPath(QPointF(50, 40))
    face.cubicTo(QPointF(40, 30), QPointF(18, 34), QPointF(20, 54))
    face.cubicTo(QPointF(22, 70), QPointF(42, 72), QPointF(50, 64))
    face.cubicTo(QPointF(58, 72), QPointF(78, 70), QPointF(80, 54))
    face.cubicTo(QPointF(82, 34), QPointF(60, 30), QPointF(50, 40))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 70))
    p.drawPath(face)
    # the big eyes
    pw, ph = _mix(13, 16.5, plead), _mix(14, 17.5, plead)
    for x in EYES:
        _e(p, x, 53, 24, 24, EYE_RING, ink)
        ring = QPainterPath()
        ring.addEllipse(QRectF(x - 11, 42, 22, 22))
        p.save()
        p.setClipPath(ring)
        px, py = x + 3.5 * look, 54 + 3.0 * look_y
        _e(p, px, py, pw, ph, INK)
        _e(p, px + 2.2, py - 3.5, _mix(4.6, 6.2, plead), _mix(4.8, 6.4, plead), QColor("white"))
        _e(p, px - 2.4, py + 3.5, 2, 2, QColor("white"))
        if plead > 0.05:   # the extra glint that makes puppy eyes
            c = QColor("white")
            c.setAlphaF(plead)
            _e(p, px + 3.4, py + 2.2, 2.6, 2.6, c)
        if sad > 0.05:     # welling up: water along the bottom of each eye
            c = QColor(TEAR)
            c.setAlphaF(0.55 * sad)
            _e(p, x, 64, 22, 7 * sad, c)
        if blink > 0.01:   # the lid comes down from the top
            lid = 24 * blink
            p.setPen(Qt.NoPen)
            p.setBrush(feather)
            p.drawRect(QRectF(x - 13, 41, 26, lid))
            p.setPen(ink)
            p.drawLine(QPointF(x - 12, 41 + lid), QPointF(x + 12, 41 + lid))
        p.restore()
        p.setPen(ink)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(x - 12, 41, 24, 24))
    # worried brows: inner ends lifted
    if sad > 0.05:
        c = QColor(INK)
        c.setAlphaF(min(1.0, sad * 1.4))
        p.setPen(QPen(c, 2.6, Qt.SolidLine, Qt.RoundCap))
        for x, sx in ((36, -1), (64, 1)):
            p.drawLine(QPointF(x + sx * 9, 38.5 + 1.5 * sad), QPointF(x - sx * 5, 38 - 5 * sad))
    _e(p, 25, 68, 10, 6, CHEEK)
    _e(p, 75, 68, 10, 6, CHEEK)
    # beak
    beak = QPainterPath(QPointF(45.5, 62))
    beak.lineTo(54.5, 62)
    beak.quadTo(52, 70, 50, 72)
    beak.quadTo(48, 70, 45.5, 62)
    p.setPen(QPen(INK, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(BEAK)
    p.drawPath(beak)
    # a tear rolling down from the outer corner of his left eye
    if 0 < tear < 1:
        c = QColor(TEAR)
        c.setAlphaF(min(1.0, tear * 5, (1 - tear) * 3))
        ty = 63 + 24 * tear * tear
        drop = QPainterPath(QPointF(26, ty - 7))
        drop.cubicTo(QPointF(30.5, ty - 1), QPointF(31, ty + 4.5), QPointF(26, ty + 4.5))
        drop.cubicTo(QPointF(21, ty + 4.5), QPointF(21.5, ty - 1), QPointF(26, ty - 7))
        p.setPen(QPen(QColor(INK.red(), INK.green(), INK.blue(), round(160 * c.alphaF())), 1))
        p.setBrush(c)
        p.drawPath(drop)
    p.restore()


def owl_image(height: int, look: float = 0.5) -> QImage:
    h = max(1, height)
    w = max(1, round(h * W / H))
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    draw_owl(p, QRectF(0, 0, w, h), look)
    p.end()
    return img


def sparkle(p: QPainter, x: float, y: float, r: float, col: QColor):
    """A four-pointed twinkle."""
    path = QPainterPath(QPointF(x, y - r))
    path.quadTo(QPointF(x, y), QPointF(x + r, y))
    path.quadTo(QPointF(x, y), QPointF(x, y + r))
    path.quadTo(QPointF(x, y), QPointF(x - r, y))
    path.quadTo(QPointF(x, y), QPointF(x, y - r))
    p.setPen(Qt.NoPen)
    p.setBrush(col)
    p.drawPath(path)


# ---------------------------------------------------------------------- alive
WAIT_LINES = ("pleeease?", "just one picture?", "I'll watch anything…", "hoo? hoo…?",
              "so… bored…", "my turn yet?")
JOY_LINES = ("yay!! ↓ down there!", "hoo-ray!", "let's watch something!")
# the little acts he does while he waits, and how long each lasts (seconds)
ACTS = {"sigh": 1.8, "plead": 3.0, "tear": 2.6, "peek": 2.2, "doze": 5.0}


def _bell(k: float) -> float:
    """0 → 1 → 0 over k = 0..1, with soft ends."""
    return math.sin(math.pi * max(0.0, min(1.0, k)))


def _ease(k: float) -> float:
    k = max(0.0, min(1.0, k))
    return k * k * (3 - 2 * k)


class OwlWidget(QWidget):
    """Hoot, alive and waiting: he sways, blinks and glances down at the buttons
    below, sighs, begs with his wings clasped and big shiny eyes, sheds a tear,
    peeks, dozes off and jolts awake. Bring the mouse near and he perks up and
    follows it with his eyes; click him and he hops for joy.

    `lines` are what he says when he begs, `joy` what he shouts when clicked.
    `left` / `right` are the room beside him, px (default: plenty both sides, for
    the speech bubble up to his right and the zzz). The timer only runs while he's
    on screen."""

    clicked = Signal()

    def __init__(self, height: int = 96, lines=WAIT_LINES, joy=JOY_LINES, parent=None, *,
                 left: int | None = None, right: int | None = None):
        super().__init__(parent)
        self.owl_h = height
        self.lines = tuple(lines)
        self.joy_lines = tuple(joy)
        side = round(height * 1.45)
        self.left = side if left is None else left
        self.right = side if right is None else right
        self.top = round(height * 0.34)    # room above for "?" and z's
        # the room beside him gives way first when space is short (the bubble then
        # overlaps him a little)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Hoot is waiting for something to watch")
        self._rng = random.Random()
        self._t0 = self._last = time.monotonic()
        self.t = 0.0
        self.act: str | None = None
        self._act_t = 0.0
        self._next_act = self._rng.uniform(2.0, 3.5)
        self._next_blink = self._rng.uniform(1.0, 3.0)
        self._blink_t = -1.0
        self._near = 0.0           # 0..1, how close the mouse is (smoothed)
        self._joy_t = -1.0         # seconds since he was clicked, or -1
        self.say = ""              # the speech bubble's text
        self._look = [0.0, 0.7]    # pupils, smoothed
        self._glance = (0.0, 0.7)  # where he looks when left alone
        self._next_glance = 1.5
        self._timer = QTimer(self)
        self._timer.setInterval(1000 // FPS)
        self._timer.timeout.connect(self._tick)
        appstate.pause_in_background(self, self._resume, self._timer.stop)

    def sizeHint(self) -> QSize:
        return QSize(round(self.owl_h * W / H) + self.left + self.right,
                     self.owl_h + self.top + 8)

    def minimumSizeHint(self) -> QSize:
        return QSize(round(self.owl_h * W / H) + 8, self.owl_h + self.top + 8)

    def showEvent(self, ev):
        if appstate.active():   # behind a game it waits until the app is back in front
            self._resume()
        super().showEvent(ev)

    def _resume(self):
        self._last = time.monotonic()
        self._timer.start()

    def hideEvent(self, ev):
        self._timer.stop()
        super().hideEvent(ev)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.cheer()
            self.clicked.emit()
        super().mousePressEvent(ev)

    def cheer(self):
        """A happy hop with sparkles (what a click does)."""
        self._joy_t = 0.0
        self.act = None
        self.say = self._rng.choice(self.joy_lines) if self.joy_lines else ""

    # ------------------------------------------------------------------ time
    def _owl_rect(self) -> QRectF:
        w = self.owl_h * W / H
        spare, room = self.width() - w, self.left + self.right   # shared as asked
        x = spare * self.left / room if room else spare / 2
        return QRectF(x, self.height() - self.owl_h - 4, w, self.owl_h)

    def _tick(self):
        now = time.monotonic()
        self.step(min(0.1, now - self._last))
        self._last = now
        self.update()

    def _mouse(self) -> tuple[float, float] | None:
        """The cursor relative to his face, in owl heights, if it's in this window."""
        win = self.window()
        g = QCursor.pos()
        if win is None or not win.frameGeometry().contains(g):
            return None
        pos = self.mapFromGlobal(g)
        r = self._owl_rect()
        return ((pos.x() - r.center().x()) / self.owl_h,
                (pos.y() - (r.top() + r.height() * 0.45)) / self.owl_h)

    def step(self, dt: float, mouse=...):
        """Advance the animation by `dt` seconds (`mouse` overrides the cursor, tests)."""
        self.t += dt
        m = self._mouse() if mouse is ... else mouse
        dist = math.hypot(*m) if m else 99.0
        near = 1.0 if dist < 2.2 else 0.0
        self._near += (near - self._near) * min(1.0, dt * (5 if near else 1.5))
        if self._joy_t >= 0:
            self._joy_t += dt
            if self._joy_t > 1.6:
                self._joy_t = -1.0
                self.say = ""
        if self.act:
            self._act_t += dt
            if self._act_t >= ACTS[self.act] or self._near > 0.6:
                self.act = None
                self.say = ""
                self._next_act = self.t + self._rng.uniform(3.5, 7.0)
        elif self._joy_t < 0 and self._near < 0.3 and self.t >= self._next_act:
            self.start(self._rng.choice(list(ACTS)))
        if self.t >= self._next_blink:
            self._blink_t = self.t
            self._next_blink = self.t + self._rng.uniform(2.0, 5.0)
        if self.t >= self._next_glance:   # mostly down at the buttons, now and then at you
            self._glance = self._rng.choice(((0.0, 0.8), (0.0, 0.8), (-0.3, 0.6), (0.3, 0.7),
                                             (0.0, -0.2), (-0.7, 0.2), (0.6, 0.1)))
            self._next_glance = self.t + self._rng.uniform(1.2, 3.0)
        if m and self._near > 0.2:
            tx, ty = max(-1.0, min(1.0, m[0] * 1.6)), max(-1.0, min(1.0, m[1] * 1.6))
        else:
            tx, ty = self._glance
        if self.act == "peek":
            tx, ty = 0.5, 1.0
        k = min(1.0, dt * 8)
        self._look[0] += (tx - self._look[0]) * k
        self._look[1] += (ty - self._look[1]) * k

    def start(self, act: str):
        """Begin one of ACTS now."""
        self.act, self._act_t = act, 0.0
        self.say = self._rng.choice(self.lines) if act == "plead" and self.lines else ""

    def pose(self) -> dict:
        """Everything draw_owl and the extras need for this moment."""
        t, near = self.t, self._near
        sad = 0.85 * (1 - near)
        tufts = 24 * sad - 10 * near + 3 * math.sin(t * 1.1)
        dy = -1.2 * math.sin(t * 2.0) - 4 * near * abs(math.sin(t * 5)) * 0.5
        rot = 2.5 * math.sin(t * 0.8)
        blink = 0.0
        if self._blink_t >= 0 and (b := t - self._blink_t) < 0.18:
            blink = 1 - abs(b - 0.09) / 0.09
        clasp = flap = plead = tear = 0.0
        extra = {}
        a, k = self.act, (self._act_t / ACTS[self.act] if self.act else 0.0)
        if a == "sigh":        # sinks, eyes half shut, a puff of breath
            b = _bell(k)
            dy += 5 * b
            tufts += 14 * b
            blink = max(blink, 0.45 * b)
            extra["puff"] = k
        elif a == "plead":     # wings clasped, puppy eyes, hopeful little hops
            e = _ease(k / 0.15) * _ease((1 - k) / 0.15)
            clasp, plead = e, e
            sad = max(sad, 0.9 * e)
            tufts -= 10 * e
            dy -= 4 * e * abs(math.sin(k * math.pi * 6))
        elif a == "tear":
            tear = k
            sad = 1.0
            blink = max(blink, 0.25 * _bell(k))
        elif a == "peek":      # leans over to look down at the buttons
            b = _bell(k)
            rot += 9 * b
            extra["ask"] = b
        elif a == "doze":      # nods off... and jolts awake
            if k < 0.78:
                d = _ease(k / 0.3)
                blink = max(blink, 0.9 * d)
                dy += 3 * d
                rot += -4 * d + 1.5 * math.sin(t * 1.5) * d
                extra["zzz"] = k
            else:
                j = (k - 0.78) / 0.22
                dy -= 9 * _bell(j * 1.5)
                tufts -= 25 * _bell(j)
                extra["startle"] = j
        if self._joy_t >= 0:
            j = self._joy_t / 1.6
            e = _bell(j)
            sad, tufts = sad * (1 - e), tufts - 30 * e
            flap = abs(math.sin(self._joy_t * 14)) * e
            dy -= 16 * abs(math.sin(j * math.pi * 2)) * (1 - j)
            blink = 0.0
            plead = 0.6 * e
            extra["joy"] = j
        return {"look": self._look[0], "look_y": self._look[1], "blink": blink, "sad": sad,
                "tufts": tufts, "clasp": clasp, "flap": flap, "plead": plead, "tear": tear,
                "dy": dy, "rot": rot, **extra}

    # ------------------------------------------------------------------ paint
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pose = self.pose()
        r = self._owl_rect()
        u = self.owl_h / H     # one canvas unit, px
        # a soft shadow on the floor, shrinking as he rises
        lift = max(0.0, -pose["dy"])
        sw = r.width() * (0.6 - lift * 0.01)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, max(18, 60 - int(lift * 4))))
        p.drawEllipse(QRectF(r.center().x() - sw / 2, r.bottom() - 3, sw, 7))
        # sway about his feet
        p.save()
        foot = QPointF(r.center().x(), r.bottom())
        p.translate(foot)
        p.rotate(pose["rot"])
        p.translate(-foot)
        body = r.translated(0, pose["dy"])
        draw_owl(p, body, pose["look"], look_y=pose["look_y"], blink=pose["blink"],
                 sad=pose["sad"], tufts=pose["tufts"], clasp=pose["clasp"],
                 flap=pose["flap"], plead=pose["plead"], tear=pose["tear"])
        p.restore()
        head = QPointF(body.center().x(), body.top() + 18 * u)
        if "puff" in pose:
            k = pose["puff"]
            if 0.25 < k < 0.95:
                q = (k - 0.25) / 0.7
                p.setOpacity(0.7 * (1 - q))
                p.setBrush(QColor("#d9d2e6"))
                for i in range(3):
                    rr = (3 + 5 * q + i) * u
                    x = body.center().x() + (8 + 30 * q + i * 6) * u
                    y = body.top() + (70 - 8 * q - i * 3) * u
                    p.drawEllipse(QPointF(x, y), rr, rr * 0.8)
                p.setOpacity(1.0)
        if pose.get("ask", 0) > 0.05:
            self._text(p, "?", head.x() + 30 * u, body.top() - 2 * u, 22 * u * pose["ask"],
                       QColor(SPARKLE_COLORS[0]))
        if "zzz" in pose:
            for i in range(3):
                q = (pose["zzz"] * 2.2 - i * 0.35) % 1.3
                if q < 1:
                    p.setOpacity(_bell(q))
                    self._text(p, "z", head.x() + (26 + 16 * q + i * 4) * u,
                               head.y() - (8 + 34 * q) * u, (10 + 6 * q) * u,
                               QColor(SPARKLE_COLORS[3]))
            p.setOpacity(1.0)
        if "startle" in pose:
            self._text(p, "!", head.x() + 28 * u, body.top() + 4 * u,
                       22 * u * _bell(pose["startle"]), QColor(SPARKLE_COLORS[1]))
        if "joy" in pose:
            j = pose["joy"]
            for i, col in enumerate(SPARKLE_COLORS * 2):
                a = i * math.pi / 4 + j * 2
                d = (40 + 30 * j) * u
                p.setOpacity(1 - j)
                sparkle(p, head.x() + math.cos(a) * d, head.y() + 10 * u + math.sin(a) * d * 0.8,
                        (4 + 3 * math.sin(j * 9 + i)) * u, QColor(col))
            p.setOpacity(1.0)
        if self.say:
            self._bubble(p, self.say, body)
        p.end()

    def _text(self, p: QPainter, text: str, x: float, y: float, px: float, col: QColor):
        if px < 1:
            return
        f = QFont(self.font())
        f.setBold(True)
        f.setPixelSize(max(1, round(px)))
        p.setFont(f)
        p.setPen(col)
        p.drawText(QPointF(x, y), text)

    def _bubble(self, p: QPainter, text: str, body: QRectF):
        """A comic speech bubble up and to the right of his head, tail to his beak."""
        f = QFont(self.font())
        f.setPixelSize(max(9, round(self.owl_h * 0.12)))
        f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        tw = min(fm.horizontalAdvance(text), self.width() - 20)
        pad = 7
        bw, bh = tw + 2 * pad, fm.height() + 2 * pad - 4
        x = max(2.0, min(body.right() + 2, self.width() - bw - 2))
        y = max(2.0, body.top() - bh * 0.35)
        box = QRectF(x, y, bw, bh)
        tail = QPainterPath(QPointF(box.left() + 10, box.bottom() - 2))
        tail.lineTo(body.center().x() + body.width() * 0.34, body.top() + body.height() * 0.27)
        tail.lineTo(box.left() + 22, box.bottom() - 2)
        shape = QPainterPath()
        shape.addRoundedRect(box, bh / 2, bh / 2)
        shape = shape.united(tail)
        p.setPen(QPen(INK, 1.6))
        p.setBrush(BUBBLE)
        p.drawPath(shape)
        p.setPen(INK)
        p.drawText(box.adjusted(pad, 0, -pad, 0), Qt.AlignCenter,
                   fm.elidedText(text, Qt.ElideRight, round(tw)))
