"""The Easter egg: poke Bun enough times (bunnywidget.py, `pong=True`) and he comes back
with a baseball bat and challenges you to Pong, in a dialog like the app's guides.

He holds his bat up as his paddle on the left; yours is on the right and follows the
mouse (or the arrow keys). First to WIN_AT. Every hit speeds the ball up a little, and
Bun only moves so fast, so a long rally is how you beat him.

Nothing is kept: Esc or Close ends the game and Bun calms down again.
"""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QRadialGradient)
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from soundboard import theme, usage
from soundboard.bunny import INK, H, W, draw_bunny, sparkle
from soundboard.i18n import _
from soundboard.ui import appstate, fit
from soundboard.ui.panel import hint_label

TITLE_CSS = "font-size:17pt; font-weight:800;"   # as the guides' titles (setupwizard.py)
BODY_CSS = "font-size:11pt;"

WIN_AT = 5
FPS = 60
SERVE_PAUSE = 0.9     # seconds between a point and the next serve
SPEED0 = 0.55         # serve speed, court widths a second
SPEEDUP, SPEED_MAX = 1.07, 1.35
BUN_SPEED = 0.95      # how fast Bun can move, court heights a second
MAX_ANGLE = 55        # degrees off straight, hitting the very end of a paddle
BALL = QColor("#d8f25e")
BUN_PINK = QColor("#ff8fae")   # his end of the court
CONFETTI = ("#ffcf40", "#ff8fae", "#1fb6ff", "#13ce66", "#a48bff")
RALLY_SHOWN = 3   # from this many hits in a row the rally counter shows
BUBBLE = QColor("#fffaf0")


def _mix(a: QColor, b: QColor, t: float, alpha: float = 1.0) -> QColor:
    """`a` moved fraction `t` of the way to `b`, at `alpha`."""
    c = QColor(round(a.red() + (b.red() - a.red()) * t),
               round(a.green() + (b.green() - a.green()) * t),
               round(a.blue() + (b.blue() - a.blue()) * t))
    c.setAlphaF(alpha)
    return c


def _alpha(c: QColor | str, a: float) -> QColor:
    c = QColor(c)
    c.setAlphaF(max(0.0, min(1.0, a)))
    return c


_grain: dict[bool, QPixmap] = {}


def _grain_tile(light: bool) -> QPixmap:
    """A tile of fine grain laid over the court: it breaks up the banding soft colour
    fades get on 8-bit screens (the same idea as the themes' window grain)."""
    if light not in _grain:
        rnd = random.Random(7)
        img = QImage(96, 96, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        base = (0, 0, 0) if light else (255, 255, 255)
        for y in range(96):
            for x in range(96):
                a = rnd.randint(0, 9 if light else 11)
                if a:
                    img.setPixelColor(x, y, QColor(*base, a))
        _grain[light] = QPixmap.fromImage(img)
    return _grain[light]


class _Spark:
    """A bit of something flying: a spark off a hit, or confetti."""
    __slots__ = ("x", "y", "vx", "vy", "age", "life", "col", "size", "spin")

    def __init__(self, x, y, vx, vy, life, col, size, spin=0.0):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.age, self.life, self.col, self.size, self.spin = 0.0, life, QColor(col), size, spin


def _bubble(p: QPainter, text: str, x: float, y: float, px: int):
    """A small speech bubble whose tail points down at (x, y)."""
    f = QFont(p.font())
    f.setPixelSize(px)
    f.setBold(True)
    p.setFont(f)
    fm = p.fontMetrics()
    bw, bh = fm.horizontalAdvance(text) + 16, fm.height() + 8
    box = QRectF(x - 12, y - bh - 10, bw, bh)
    shape = QPainterPath()
    shape.addRoundedRect(box, bh / 2, bh / 2)
    tail = QPainterPath(QPointF(box.left() + 8, box.bottom() - 2))
    tail.lineTo(x, y)
    tail.lineTo(box.left() + 20, box.bottom() - 2)
    shape = shape.united(tail)
    p.setPen(QPen(INK, 1.6))
    p.setBrush(BUBBLE)
    p.drawPath(shape)
    p.setPen(INK)
    p.drawText(box, Qt.AlignCenter, text)


class Court(QWidget):
    """The game itself: the court, both paddles, the ball, the score."""

    def __init__(self, rng: random.Random | None = None, parent=None):
        super().__init__(parent)
        self.rng = rng or random.Random()
        self.fx = random.Random()   # sparks and shakes: never moves the game's own dice
        self.setMouseTracking(True)
        self.setMinimumSize(320, 220)
        self.setFocusPolicy(Qt.StrongFocus)
        self.on_over = None   # called when someone reaches WIN_AT
        self.end_bun_left = 0.0   # where Bun stands at the end (the dialog centres him)
        self.reset()

    # ------------------------------------------------------------------ state
    def reset(self):
        self.score = {"you": 0, "bun": 0}
        self.state = "ready"       # ready (click to serve), play, point, over
        self.st = 0.0              # seconds in this state
        self.you_y = self.bun_y = 0.5   # paddle centres, 0..1 of the court height
        self.aim_y = 0.5           # where the mouse / keys want your paddle
        self.bx, self.by = 0.5, 0.5     # the ball, 0..1 of the court
        self.vx = self.vy = 0.0         # court widths / heights a second
        self.trail: list[tuple[float, float]] = []
        self.flash: list[list] = []     # [x, y, age]: a ring where the ball was hit
        self.swing = 0.0           # Bun's bat, 0 at rest, up to ~0.4 on a hit
        self.err = 0.0             # how far off Bun's guess is this rally
        self.say, self.say_until = "", 0.0
        self.server = "you"
        self.sparks: list[_Spark] = []     # hit sparks and confetti, px
        self.rally = 0                     # hits in a row this point
        self.goal_flash: list | None = None   # [side "bun" / "you", age]: a goal let in
        self.pop = {"you": 9.0, "bun": 9.0}   # seconds since each side scored
        self.shake = 0.0                   # seconds of court shake left

    def _speed(self) -> float:
        return math.hypot(self.vx * self.width(), self.vy * self.height()) / max(1, self.width())

    def serve(self, toward: str):
        a = math.radians(self.rng.uniform(-25, 25))
        sign = -1 if toward == "bun" else 1
        self.bx, self.by = 0.5, self.rng.uniform(0.35, 0.65)
        aspect = self.width() / max(1, self.height())
        self.vx = sign * SPEED0 * math.cos(a)
        self.vy = SPEED0 * math.sin(a) * aspect
        self.err = self._guess_error()
        self.trail.clear()
        self._go("play")

    def _go(self, state: str):
        self.state, self.st = state, 0.0
        # the pointer hides while you play (your paddle is the pointer)
        self.setCursor(Qt.BlankCursor if state in ("play", "point") else Qt.ArrowCursor)

    def _say(self, text: str, secs: float = 1.2):
        self.say, self.say_until = text, time.monotonic() + secs

    def _guess_error(self) -> float:
        """How far from the ball Bun aims, in paddle half-lengths: mostly close, and
        now and then quite wrong."""
        if self.rng.random() < 0.18:
            return self.rng.choice((-1, 1)) * self.rng.uniform(1.0, 1.6)
        return self.rng.uniform(-0.6, 0.6)

    # ------------------------------------------------------------------ geometry
    def geo(self) -> dict:
        """Pixel sizes for the current widget size."""
        w, h = max(1, self.width()), max(1, self.height())
        bh = h * 0.42                       # Bun's height
        s = bh / H
        half = 26 * s / h                   # his bat's half length, 0..1 of the height
        return {"w": w, "h": h, "bh": bh, "s": s, "r": max(5.0, h * 0.028),
                "bun_x": 86 * s + 6,        # his bat, px from the left
                "bun_half": half,
                # how far up and down he can go and still be all on the court
                "bun_min": (72 * s + 6) / h, "bun_max": 1 - (bh - 72 * s + 6) / h,
                "you_x": w - 22, "you_half": 0.1, "pad_w": 9}

    def bun_rect(self, g: dict) -> QRectF:
        s = g["s"]
        if self.state == "over":   # beside the result, both centred on the court
            return QRectF(self.end_bun_left, (g["h"] - g["bh"]) / 2, W * s, g["bh"])
        return QRectF(g["bun_x"] - 86 * s, self.bun_y * g["h"] - 72 * s, W * s, g["bh"])

    # ------------------------------------------------------------------ simulation
    def step(self, dt: float):
        self.st += dt
        g = self.geo()
        # your paddle: straight to the mouse, kept on the court
        self.you_y = min(1 - g["you_half"], max(g["you_half"], self.aim_y))
        # Bun: chases where the ball will cross his line (plus his guess error) while
        # it's coming, drifts back to the middle while it's going away
        if self.state == "play" and self.vx < 0:
            target = self._predict(g["bun_x"] / g["w"]) + self.err * g["bun_half"]
        else:
            target = 0.5
        target = min(g["bun_max"], max(g["bun_min"], target))
        move = BUN_SPEED * dt
        self.bun_y += max(-move, min(move, target - self.bun_y))
        self.swing = max(0.0, self.swing - dt * 2.5)
        for f in self.flash:
            f[2] += dt
        self.flash = [f for f in self.flash if f[2] < 0.35]
        for sp in self.sparks:
            sp.age += dt
            sp.x += sp.vx * dt
            sp.y += sp.vy * dt
            sp.vy += 260 * dt if sp.spin else 0.0   # confetti falls, sparks just fly
            sp.vx *= 1 - dt * 2.5
            if not sp.spin:
                sp.vy *= 1 - dt * 2.5
        self.sparks = [sp for sp in self.sparks if sp.age < sp.life]
        if self.goal_flash is not None:
            self.goal_flash[1] += dt
            if self.goal_flash[1] > 0.7:
                self.goal_flash = None
        for k in self.pop:
            self.pop[k] += dt
        self.shake = max(0.0, self.shake - dt)
        if self.state == "point" and self.st >= SERVE_PAUSE:
            self.serve(self.server)
        if self.state != "play":
            return
        # the ball, in a few sub-steps so a fast one can't skip through a paddle
        n = max(1, math.ceil(dt / 0.008))
        for _i in range(n):
            if self._move(dt / n, g):
                break
        self.trail.append((self.bx, self.by))
        del self.trail[:-8]

    def _predict(self, x: float) -> float:
        """Where the ball crosses x (0..1), bouncing off the top and bottom."""
        if self.vx >= 0:
            return self.by
        t = (self.bx - x) / -self.vx
        y = self.by + self.vy * t
        y = y % 2.0
        return 2 - y if y > 1 else y

    def _move(self, dt: float, g: dict) -> bool:
        """Move the ball on; True if a point was scored."""
        w, h, r = g["w"], g["h"], g["r"]
        self.bx += self.vx * dt
        self.by += self.vy * dt
        ry = r / h
        if self.by < ry and self.vy < 0 or self.by > 1 - ry and self.vy > 0:
            self.vy = -self.vy
            self.by = min(1 - ry, max(ry, self.by))
        x = self.bx * w
        # Bun's bat
        bx = g["bun_x"] + 3
        if self.vx < 0 and bx - 6 <= x - r <= bx:
            off = (self.by - self.bun_y) / g["bun_half"]
            # as high or low as he can go, he reaches the rest of the way with the bat
            top = 0.0 if self.bun_y <= g["bun_min"] + 1e-3 else self.bun_y - g["bun_half"]
            bottom = 1.0 if self.bun_y >= g["bun_max"] - 1e-3 else self.bun_y + g["bun_half"]
            if top - ry <= self.by <= bottom + ry:
                self._hit(off, 1, (bx + r) / w)
                self.swing = 0.45
                return False
        # your paddle
        px = g["you_x"] - g["pad_w"] / 2
        if self.vx > 0 and px <= x + r <= px + 8:
            off = (self.by - self.you_y) / g["you_half"]
            if abs(off) <= 1 + ry / g["you_half"]:
                self._hit(off, -1, (px - r) / w)
                self.err = self._guess_error()
                return False
        if x < -r * 2:
            self._point("you")
            return True
        if x > w + r * 2:
            self._point("bun")
            return True
        return False

    def _hit(self, off: float, sign: int, x: float):
        off = max(-1.0, min(1.0, off))
        speed = min(SPEED_MAX, max(SPEED0, self._speed()) * SPEEDUP)
        a = math.radians(off * MAX_ANGLE)
        aspect = self.width() / max(1, self.height())
        self.vx = sign * speed * math.cos(a)
        self.vy = speed * math.sin(a) * aspect
        self.bx = x
        self.flash.append([self.bx, self.by, 0.0])
        self.rally += 1
        # sparks off the hit, in the hitter's colour, flying back into the court
        col = BUN_PINK if sign > 0 else QColor(theme.T["accent"])
        px, py = self.bx * self.width(), self.by * self.height()
        for _i in range(9 + min(9, self.rally)):
            a = math.radians(self.fx.uniform(-70, 70))
            v = self.fx.uniform(80, 220) * (1 + speed - SPEED0)
            self.sparks.append(_Spark(px, py, sign * math.cos(a) * v, math.sin(a) * v,
                                      self.fx.uniform(0.25, 0.5),
                                      col if self.fx.random() < 0.6 else BALL,
                                      self.fx.uniform(1.4, 2.6)))

    def _point(self, who: str):
        self.score[who] += 1
        self.server = "bun" if who == "you" else "you"   # served toward who lost it
        self.trail.clear()
        self.rally = 0
        self.pop[who] = 0.0
        self.goal_flash = ["bun" if who == "you" else "you", 0.0]
        self.shake = 0.28
        if self.score[who] >= WIN_AT:
            usage.used("egg-pong-won" if who == "you" else "egg-pong-lost")
            if who == "you":
                self._confetti()
            self._go("over")
            self._say(_("aww…") if who == "you" else _("who's the champ!"), 1e9)
            if self.on_over:
                self.on_over()
            return
        if who == "you":
            self._say(self.fx.choice((_("no way!"), _("lucky!"), _("hey!"))))
        else:
            self._say(self.fx.choice((_("ha!"), _("too slow!"), _("bonk!"))))
        self._go("point")

    def _confetti(self):
        w = max(1, self.width())
        for _i in range(70):
            self.sparks.append(_Spark(self.fx.uniform(0, w), self.fx.uniform(-60, -4),
                                      self.fx.uniform(-40, 40), self.fx.uniform(20, 120),
                                      self.fx.uniform(1.6, 2.6),
                                      self.fx.choice(CONFETTI), self.fx.uniform(3, 5),
                                      spin=self.fx.uniform(4, 10)))

    @property
    def winner(self) -> str | None:
        if self.state != "over":
            return None
        return "you" if self.score["you"] >= WIN_AT else "bun"

    # ------------------------------------------------------------------ input
    def mouseMoveEvent(self, ev):
        self.aim_y = ev.position().y() / max(1, self.height())

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.state == "ready":
            self.serve("bun")

    def key(self, k) -> bool:
        """The keys: arrows / W S move your paddle, Space or Enter serves. True if used."""
        if k in (Qt.Key_Up, Qt.Key_W):
            self.nudge(-0.08)
        elif k in (Qt.Key_Down, Qt.Key_S):
            self.nudge(0.08)
        elif k in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter) and self.state == "ready":
            self.serve("bun")
        else:
            return False
        return True

    def keyPressEvent(self, ev):
        if not self.key(ev.key()):
            super().keyPressEvent(ev)

    def nudge(self, d: float):
        """The arrow keys: move your paddle by `d` of the court height."""
        self.aim_y = min(1.0, max(0.0, self.you_y + d))
        if self.state == "ready":
            self.serve("bun")

    # ------------------------------------------------------------------ paint
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        g = self.geo()
        w, h, r = g["w"], g["h"], g["r"]
        t = time.monotonic()
        over = self.state == "over"
        if self.shake > 0:   # a little jolt when a point goes in
            k = self.shake / 0.28
            p.translate(self.fx.uniform(-3, 3) * k, self.fx.uniform(-2, 2) * k)
        self._paint_arena(p, w, h, over)

        # the score: big and faint behind the play, popping when it goes up
        f = QFont(self.font())
        if not over:
            nw = w * 0.16   # each side's number, just off the net
            top = QRectF(w / 2 - nw - w * 0.03, h * 0.06, nw, h * 0.28)
            for side, box in (("bun", top), ("you", top.translated(nw + w * 0.06, 0))):
                k = self.pop[side]
                bump = 1 + 0.35 * max(0.0, 1 - k / 0.35) ** 2
                col = QColor(theme.T["text_hi"])
                col.setAlphaF(0.12 + 0.5 * max(0.0, 1 - k / 0.6))
                f.setPixelSize(round(h * 0.24 * bump))
                f.setBold(True)
                p.setFont(f)
                p.setPen(col)
                p.drawText(box.adjusted(-30, -30, 30, 30), Qt.AlignCenter, str(self.score[side]))
            f.setPixelSize(max(10, round(h * 0.045)))
            f.setBold(False)
            p.setFont(f)
            p.setPen(QColor(theme.T["muted"]))
            under = QRectF(top.left(), top.bottom() - 4, nw, h * 0.07)
            p.drawText(under, Qt.AlignCenter, _("Bun"))
            p.drawText(under.translated(nw + w * 0.06, 0), Qt.AlignCenter, _("You"))
            if self.rally >= RALLY_SHOWN and self.state == "play":
                self._paint_rally(p, w, h)

        # Bun with his bat up as a paddle (or not, at the end)
        lost = over and self.winner == "you"
        won = over and self.winner == "bun"
        br = self.bun_rect(g)
        if won:
            br.translate(0, -6 * abs(math.sin(t * 3.4)))
            for i, col in enumerate(("#ffcf40", "#ff8fae", "#1fb6ff", "#a48bff")):
                a = t * 0.9 + i * math.pi / 2
                sparkle(p, br.center().x() + math.cos(a) * br.width() * 0.52,
                        br.center().y() + math.sin(a) * br.height() * 0.45,
                        3 + 3 * abs(math.sin(t * 4 + i)), QColor(col))
        blink = 1.0 if (t % 3.7) < 0.12 else 0.0
        draw_bunny(p, br, "star" if won else None if lost else "bat", blink=blink,
                   swing=self.swing, sad=0.9 if lost else 0.0,
                   angry=0.0 if over else 0.6, ears=30 if lost else -4)

        # your paddle: a soft glow under a solid pill
        acc = QColor(theme.T["accent"])
        if over:
            acc.setAlphaF(0.0)
        px = g["you_x"] - g["pad_w"] / 2
        ph = g["you_half"] * 2 * h
        py = self.you_y * h - ph / 2
        if not over:
            p.setPen(Qt.NoPen)
            for i, a in ((10, 0.06), (6, 0.12), (3, 0.2)):   # a soft glow round it
                p.setBrush(_alpha(acc, a))
                p.drawRoundedRect(QRectF(px - i, py - i, g["pad_w"] + 2 * i, ph + 2 * i),
                                  g["pad_w"] / 2 + i, g["pad_w"] / 2 + i)
            body = QLinearGradient(px, 0, px + g["pad_w"], 0)
            body.setColorAt(0, _mix(acc, QColor("white"), 0.35))
            body.setColorAt(1, acc)
            p.setBrush(body)
            p.drawRoundedRect(QRectF(px, py, g["pad_w"], ph), g["pad_w"] / 2, g["pad_w"] / 2)

        # hit rings, the ball's trail, the ball
        for fx, fy, age in self.flash:
            k = age / 0.35
            c = QColor(BALL)
            c.setAlphaF(0.7 * (1 - k))
            p.setPen(QPen(c, 2))
            p.setBrush(Qt.NoBrush)
            rr = r * (1.2 + 2.2 * k)
            p.drawEllipse(QPointF(fx * w, fy * h), rr, rr)
        for sp in self.sparks:
            k = sp.age / sp.life
            p.setPen(Qt.NoPen)
            p.setBrush(_alpha(sp.col, 1 - k * k))
            if sp.spin:   # confetti: little turning paper strips
                p.save()
                p.translate(sp.x, sp.y)
                p.rotate(sp.age * sp.spin * 60)
                p.scale(1, abs(math.cos(sp.age * sp.spin)) + 0.15)
                p.drawRect(QRectF(-sp.size / 2, -sp.size, sp.size, sp.size * 2))
                p.restore()
            else:
                p.drawEllipse(QPointF(sp.x, sp.y), sp.size * (1 - 0.5 * k), sp.size * (1 - 0.5 * k))
        if self.state in ("play", "ready"):
            heat = max(0.0, min(1.0, (self._speed() - SPEED0) / (SPEED_MAX - SPEED0)))
            hot = _mix(BALL, QColor(theme.T["accent"]), heat)
            p.setPen(Qt.NoPen)
            for i, (tx, ty) in enumerate(self.trail[:-1]):
                k = i / len(self.trail)
                p.setBrush(_alpha(hot, 0.06 + (0.25 + 0.2 * heat) * k))
                rr = r * (0.45 + 0.55 * k)
                p.drawEllipse(QPointF(tx * w, ty * h), rr, rr)
            glow = QRadialGradient(QPointF(self.bx * w, self.by * h), r * (2.6 + 1.6 * heat))
            glow.setColorAt(0, _alpha(hot, 0.35 + 0.25 * heat))
            glow.setColorAt(1, _alpha(hot, 0.0))
            p.setBrush(glow)
            p.drawEllipse(QPointF(self.bx * w, self.by * h), r * (2.6 + 1.6 * heat),
                          r * (2.6 + 1.6 * heat))
            self._paint_ball(p, self.bx * w, self.by * h, r)

        if self.state == "ready":
            f.setPixelSize(max(11, round(h * 0.055)))
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(theme.T["text_hi"]))
            p.drawText(QRectF(0, h * 0.62, w, h * 0.1), Qt.AlignCenter,
                       _("Click to serve"))
        if self.say and time.monotonic() < self.say_until:
            _bubble(p, self.say, br.center().x() + br.width() * 0.15,
                    br.top() + br.height() * 0.1, max(10, round(g["bh"] * 0.12)))
        p.end()

    def _paint_arena(self, p: QPainter, w: float, h: float, over: bool):
        """The court bed: sunk into the card, lit from the middle with the theme colour,
        each end tinted for its player, with lines and a glowing net. All from the
        theme's own colours, so it fits every theme."""
        light = theme.is_light()
        acc = QColor(theme.T["accent"])
        hi = QColor(theme.T["text_hi"])
        bed = QColor(theme.T.get("inset", theme.T["bg"]))
        dark = QColor("white" if light else "black")
        court = QRectF(0, 0, w, h)
        path = QPainterPath()
        path.addRoundedRect(court, 12, 12)
        p.save()
        p.setClipPath(path)
        g = QLinearGradient(0, 0, 0, h)   # a sunken bed: shaded under the top lip
        g.setColorAt(0, _mix(bed, dark, 0.25 if not light else 0.0))
        g.setColorAt(0.12, bed)
        g.setColorAt(1, _mix(bed, hi, 0.03))
        p.fillRect(court, g)
        glow = QRadialGradient(QPointF(w / 2, h / 2), max(w, h) * 0.55)
        glow.setColorAt(0, _alpha(acc, 0.14 if not light else 0.08))
        glow.setColorAt(1, _alpha(acc, 0.0))
        p.fillRect(court, glow)
        for x0, x1, col in ((0, w * 0.22, BUN_PINK), (w, w * 0.78, acc)):   # the ends
            end = QLinearGradient(x0, 0, x1, 0)
            end.setColorAt(0, _alpha(col, 0.13))
            end.setColorAt(1, _alpha(col, 0.0))
            p.fillRect(court, end)
        if self.goal_flash is not None:   # a goal just went in at this end
            side, age = self.goal_flash
            k = max(0.0, 1 - age / 0.7)
            col = BUN_PINK if side == "you" else acc   # the scorer's colour
            x0, x1 = (w, w * 0.6) if side == "you" else (0, w * 0.4)
            fl = QLinearGradient(x0, 0, x1, 0)
            fl.setColorAt(0, _alpha(col, 0.45 * k))
            fl.setColorAt(1, _alpha(col, 0.0))
            p.fillRect(court, fl)
        p.fillRect(court, QBrush(_grain_tile(light)))
        if not over:
            line = _alpha(hi, 0.10)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(line, 1.5))
            p.drawRoundedRect(court.adjusted(12, 12, -12, -12), 6, 6)
            rr = h * 0.17
            p.drawEllipse(QPointF(w / 2, h / 2), rr, rr)
            p.setPen(QPen(_alpha(acc, 0.10), 7, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(w / 2, 12), QPointF(w / 2, h - 12))   # the net's glow
            dash = QPen(_alpha(hi, 0.35), 2, Qt.CustomDashLine, Qt.RoundCap)
            dash.setDashPattern([2.5, 4])
            p.setPen(dash)
            p.drawLine(QPointF(w / 2, 12), QPointF(w / 2, h - 12))
        p.restore()
        # the lip: shade along the top edge, a catch of light along the bottom
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(_alpha(hi, 0.08 if not light else 0.0), 1))
        p.drawRoundedRect(court.adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)

    def _paint_rally(self, p: QPainter, w: float, h: float):
        """A pill at the bottom of the court counting the rally, like a combo meter."""
        f = QFont(self.font())
        f.setPixelSize(max(10, round(h * 0.042)))
        f.setBold(True)
        p.setFont(f)
        text = _("Rally {n}", n=self.rally)
        fm = p.fontMetrics()
        bw, bh = fm.horizontalAdvance(text) + 22, fm.height() + 8
        box = QRectF((w - bw) / 2, h - bh - 18, bw, bh)
        acc = QColor(theme.T["accent"])
        g = QLinearGradient(0, box.top(), 0, box.bottom())
        g.setColorAt(0, _mix(acc, QColor("white"), 0.16))
        g.setColorAt(1, acc)
        p.setPen(Qt.NoPen)
        p.setBrush(_alpha(acc, 0.25))
        p.drawRoundedRect(box.adjusted(-3, -3, 3, 3), bh / 2 + 3, bh / 2 + 3)
        p.setBrush(g)
        p.drawRoundedRect(box, bh / 2, bh / 2)
        p.setPen(QColor(theme.T.get("on_accent", "#ffffff")))
        p.drawText(box, Qt.AlignCenter, text)

    @staticmethod
    def _paint_ball(p: QPainter, x: float, y: float, r: float):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 70))
        p.drawEllipse(QPointF(x + 1.5, y + 2), r, r)
        p.setPen(QPen(QColor("#9fb83a"), 1))
        p.setBrush(BALL)
        p.drawEllipse(QPointF(x, y), r, r)
        seam = QPen(QColor(255, 255, 255, 220), max(1.0, r * 0.18), Qt.SolidLine, Qt.RoundCap)
        p.setPen(seam)
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(x - r * 1.6, y - r * 0.8, r * 1.4, r * 1.6), -60 * 16, 120 * 16)
        p.drawArc(QRectF(x + r * 0.2, y - r * 0.8, r * 1.4, r * 1.6), 120 * 16, 120 * 16)


def open_for(bun) -> BunPong:
    """Open the game for Bun, over his window (one game at a time)."""
    win = bun.window()
    for old in win.findChildren(BunPong):
        old.finish()
    dlg = BunPong(win, bun)
    usage.used("egg-pong-opened")   # the names only (usage.py)
    dlg.open()
    dlg.court.setFocus(Qt.OtherFocusReason)
    return dlg


class BunPong(QDialog):
    """The game in a dialog built like the app's guides: a big title and a line on how
    to play, the court on the theme's card, and Close at the bottom. At the end Bun and
    who won sit side by side, centred together on the court, with Play again."""

    def __init__(self, parent: QWidget, bun=None, rng: random.Random | None = None):
        super().__init__(parent)
        fit.watch(self)
        self.bun = bun
        self._done = False
        self.setWindowTitle(_("Pong with Bun"))
        self.setMinimumWidth(640)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 18)
        v.setSpacing(12)
        title = QLabel(_("Pong with Bun"))
        title.setStyleSheet(TITLE_CSS)
        body = QLabel(_("First to {n} wins. Move your paddle with the mouse or the arrow "
                        "keys.", n=WIN_AT))
        body.setWordWrap(True)
        body.setStyleSheet(BODY_CSS)
        v.addWidget(title)
        v.addWidget(body)

        self.card = QFrame()
        self.card.setObjectName("card")
        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(0, 0, 0, 0)
        self.court = Court(rng)
        self.court.setMinimumHeight(320)
        self.court.on_over = self._show_end
        cl.addWidget(self.court)
        v.addWidget(self.card, 1)

        # the end: who won and Play again, beside Bun (placed in _place_end)
        self.end = QWidget(self.court)
        el = QVBoxLayout(self.end)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(6)
        self.end_title = QLabel()
        self.end_title.setStyleSheet(TITLE_CSS)
        self.end_score = QLabel()
        self.end_score.setStyleSheet(BODY_CSS)
        self.again = QPushButton(_("Play again"))
        self.again.setObjectName("primary")
        self.again.setAutoDefault(False)
        self.again.clicked.connect(self.play_again)
        el.addWidget(self.end_title)
        el.addWidget(self.end_score)
        el.addSpacing(8)
        el.addWidget(self.again, 0, Qt.AlignLeft)
        self.end.setCursor(Qt.ArrowCursor)
        self.end.hide()

        row = QHBoxLayout()
        row.addWidget(hint_label(_("Closing it ends the game. Nothing is kept.")), 1)
        close = QPushButton(_("Close"))
        close.setAutoDefault(False)
        close.clicked.connect(self.reject)
        row.addWidget(close)
        v.addLayout(row)
        self.finished.connect(lambda _r: self.finish())

        self._last = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(1000 // FPS)
        self._timer.timeout.connect(self._tick)
        appstate.pause_in_background(self, self._resume, self._timer.stop)

    # ------------------------------------------------------------------ flow
    def _show_end(self):
        c = self.court
        you, bun = c.score["you"], c.score["bun"]
        if c.winner == "you":
            self.end_title.setText(_("You win!"))
            self.end_score.setText(_("{you} to {bun}. Bun's not happy.", you=you, bun=bun))
        else:
            self.end_title.setText(_("Bun wins!"))
            self.end_score.setText(_("{bun} to {you}. Try again?", you=you, bun=bun))
        self.end.adjustSize()
        self._place_end()
        self.end.show()
        self.again.setFocus()

    def _place_end(self):
        """Bun and the result side by side, the pair centred on the court."""
        c = self.court
        g = c.geo()
        sz = self.end.sizeHint()
        gap = 28
        bun_w = g["bh"] * W / H
        left = (c.width() - (bun_w + gap + sz.width())) / 2
        c.end_bun_left = left
        self.end.setGeometry(round(left + bun_w + gap), round((c.height() - sz.height()) / 2),
                             sz.width(), sz.height())

    def play_again(self):
        self.end.hide()
        self.court.reset()
        self.court.setFocus()

    def finish(self):
        """End the game: nothing is kept, and Bun calms down."""
        if self._done:
            return
        self._done = True
        self._timer.stop()
        if self.court.state in ("play", "point"):   # left mid-game
            usage.used("egg-pong-quit")
        if self.bun is not None:
            try:
                self.bun.calm_down()
            except RuntimeError:   # Bun's widget is already gone
                pass
        if self.isVisible():
            self.reject()
        self.deleteLater()

    def step(self, dt: float):
        """Move the game on by `dt` seconds (the timer's tick; tests call it too)."""
        self.court.step(dt)

    # ------------------------------------------------------------------ timing
    def _tick(self):
        now = time.monotonic()
        dt = min(0.05, now - self._last)
        self._last = now
        self.step(dt)
        self.court.update()

    def showEvent(self, ev):
        if appstate.active():
            self._resume()
        super().showEvent(ev)

    def _resume(self):
        if not self._done:
            self._last = time.monotonic()
            self._timer.start()

    def hideEvent(self, ev):
        self._timer.stop()
        super().hideEvent(ev)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self.end.isVisible():
            self._place_end()

    def keyPressEvent(self, ev):
        if not self.court.key(ev.key()):
            super().keyPressEvent(ev)   # Esc closes, as in every dialog
