"""Pong itself (`Court`), the first of Bun's games (ui/bun/bunpong.py): serving, Bun's
paddle guessing where the ball goes, your paddle on the mouse or keys, hits, rallies and the
ball. `bunpong` re-exports it."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QLinearGradient, QPainter, QPen, QRadialGradient

from soundboard.i18n import _
from soundboard.ui.bun.bunny import W
from soundboard.ui.bun.bunpongbase import (
    BALL,
    BUN_PINK,
    BUN_SPEED,
    EDGE,
    GO_KEYS,
    Game,
    KEY_DIRS,
    KEY_RAMP,
    KEY_SPEED,
    KEY_TAP,
    MAX_ANGLE,
    MILESTONE,
    RALLY_SHOWN,
    SERVE_PAUSE,
    SPEED0,
    SPEEDUP,
    SPEED_MAX,
    _Spark,
    _alpha,
    _mix,
)
from soundboard.ui.kit import theme


class Court(Game):
    """Pong: the court, both paddles, the ball."""

    net = True

    @staticmethod
    def title() -> str:
        return _("Pong with Bun")

    def how(self) -> str:
        return _("First to {n} wins. Move your paddle with the mouse or the arrow keys.",
                 n=self.win_at)

    # ------------------------------------------------------------------ state
    def reset(self):
        super().reset()
        self.state = "ready"       # ready (click to serve), play, point, over
        self.you_y = self.bun_y = 0.5   # paddle centres, 0..1 of the court height
        self.aim_y = 0.5           # where the mouse / keys want your paddle
        self.bx, self.by = 0.5, 0.5     # the ball, 0..1 of the court
        self.vx = self.vy = 0.0         # court widths / heights a second
        self.trail: list[tuple[float, float]] = []
        self.flash: list[list] = []     # [x, y, age]: a ring where the ball was hit
        self.err = 0.0             # how far off Bun's guess is this rally
        self.server = "you"
        self.rally = 0                     # hits in a row this point
        self.held: set = set()     # arrow / W S keys held down
        self.held_t = 0.0          # how long they've been held
        self._cursor = QCursor.pos()   # the mouse, last seen (anywhere on screen)

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
        self._play("serve")

    def _go(self, state: str):
        super()._go(state)
        # the pointer hides while you play (your paddle is the pointer)
        self.setCursor(Qt.CursorShape.BlankCursor if state in ("play", "point")
                       else Qt.CursorShape.ArrowCursor)

    def _pan(self) -> float:
        """Where the ball is, as a stereo position: a little left of Bun to a little
        right of you, never all the way to one ear."""
        return (self.bx - 0.5) * 1.4

    def _heat(self) -> float:
        return max(0.0, min(1.0, (self._speed() - SPEED0) / (SPEED_MAX - SPEED0)))

    def _guess_error(self) -> float:
        """How far from the ball Bun aims, in paddle half-lengths: mostly close, and
        now and then quite wrong."""
        if self.rng.random() < 0.18:
            return self.rng.choice((-1, 1)) * self.rng.uniform(1.0, 1.6)
        return self.rng.uniform(-0.6, 0.6)

    # ------------------------------------------------------------------ geometry
    def geo(self) -> dict:
        g = super().geo()
        s, h = g["s"], g["h"]
        half = 26 * s / h                   # his bat's half length, 0..1 of the height
        g.update({"r": max(5.0, h * 0.028), "bun_half": half,
                  # how far up and down he can go and still be all on the court
                  "bun_min": (72 * s + 6) / h, "bun_max": 1 - (g["bh"] - 72 * s + 6) / h,
                  "you_x": g["w"] - 22, "you_half": 0.1, "pad_w": 9})
        return g

    def bun_rect(self, g: dict) -> QRectF:
        if self.state == "over":
            return super().bun_rect(g)
        s = g["s"]
        return QRectF(g["bun_x"] - 86 * s, self.bun_y * g["h"] - 72 * s, W * s, g["bh"])

    def score_boxes(self, w: float, h: float) -> tuple[QRectF, QRectF]:
        nw = w * 0.16   # each side's number, just off the net
        top = QRectF(w / 2 - nw - w * 0.03, h * 0.06, nw, h * 0.28)
        return top, top.translated(nw + w * 0.06, 0)

    # ------------------------------------------------------------------ simulation
    def step(self, dt: float):
        super().step(dt)
        g = self.geo()
        self._steer(dt, g)
        # your paddle: straight to where the mouse / keys want it, kept on the court
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
        for f in self.flash:
            f[2] += dt
        self.flash = [f for f in self.flash if f[2] < 0.35]
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

    def _steer(self, dt: float, g: dict):
        """Where you want your paddle: the mouse's height whenever it has moved (read
        from the screen, so it keeps working off the court and never sticks at the
        edge), and held keys glide it, a little faster the longer they're held."""
        pos = QCursor.pos()
        if pos != self._cursor:
            self._cursor = pos
            if self.isVisible():
                self.aim_y = self.mapFromGlobal(pos).y() / g["h"]
        d = sum(KEY_DIRS[k] for k in self.held)
        if d:
            self.held_t += dt
            ramp = min(1.0, self.held_t / KEY_RAMP)
            self.aim_y += d * (KEY_SPEED[0] + (KEY_SPEED[1] - KEY_SPEED[0]) * ramp) * dt
        else:
            self.held_t = 0.0
        # never further than the paddle can go: turning back starts at once
        self.aim_y = min(1 - g["you_half"], max(g["you_half"], self.aim_y))

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
            self._play("wall", pan=self._pan())
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
        heat = self._heat()
        if sign < 0:   # yours: one step up the ladder each hit of the rally
            self._play("you", rally=self.rally - 1, pan=self._pan(), heat=heat,
                       edge=abs(off) >= EDGE)
        else:
            self._play("bun", pan=self._pan(), heat=heat)
        if self.rally % MILESTONE == 0:
            self._play("milestone", level=self.rally // MILESTONE)
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

    def _point(self, who: str, quip: bool = True) -> bool:
        self.server = "bun" if who == "you" else "you"   # served toward who lost it
        self.trail.clear()
        self.rally = 0
        if super()._point(who, quip):
            return True
        self._go("point")
        return False

    # ------------------------------------------------------------------ input
    def mouseMoveEvent(self, ev):
        self.aim_y = ev.position().y() / max(1, self.height())

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton and self.state == "ready":
            self.serve("bun")

    def key(self, k) -> bool:
        """Arrows / W S move your paddle (a tap nudges it, holding glides it), Space or
        Enter serves."""
        if k in KEY_DIRS:
            self.held.add(k)
            self.nudge(KEY_DIRS[k] * KEY_TAP)
        elif k in GO_KEYS and self.state == "ready":
            self.serve("bun")
        else:
            return False
        return True

    def key_up(self, k) -> bool:
        if k in self.held:
            self.held.discard(k)
            return True
        return False

    def focusOutEvent(self, ev):
        self.held.clear()   # a key let go somewhere else must not keep it moving
        super().focusOutEvent(ev)

    def nudge(self, d: float):
        """Move your paddle by `d` of the court height."""
        self.aim_y = min(1.0, max(0.0, self.you_y + d))
        if self.state == "ready":
            self.serve("bun")

    # ------------------------------------------------------------------ paint
    def paint_back(self, p: QPainter, g: dict):
        if self.rally >= RALLY_SHOWN and self.state == "play":
            self._paint_rally(p, g["w"], g["h"])

    def paint_game(self, p: QPainter, g: dict):
        w, h, r = g["w"], g["h"], g["r"]
        # your paddle: a soft glow under a solid pill
        acc = QColor(theme.T["accent"])
        px = g["you_x"] - g["pad_w"] / 2
        ph = g["you_half"] * 2 * h
        py = self.you_y * h - ph / 2
        p.setPen(Qt.PenStyle.NoPen)
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
            p.setBrush(Qt.BrushStyle.NoBrush)
            rr = r * (1.2 + 2.2 * k)
            p.drawEllipse(QPointF(fx * w, fy * h), rr, rr)
        if self.state in ("play", "ready"):
            heat = self._heat()
            hot = _mix(BALL, QColor(theme.T["accent"]), heat)
            p.setPen(Qt.PenStyle.NoPen)
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
            self._prompt(p, _("Click to serve"), QRectF(0, h * 0.62, w, h * 0.1), h * 0.055)

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
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_alpha(acc, 0.25))
        p.drawRoundedRect(box.adjusted(-3, -3, 3, 3), bh / 2 + 3, bh / 2 + 3)
        p.setBrush(g)
        p.drawRoundedRect(box, bh / 2, bh / 2)
        p.setPen(QColor(theme.T.get("on_accent", "#ffffff")))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    @staticmethod
    def _paint_ball(p: QPainter, x: float, y: float, r: float):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 70))
        p.drawEllipse(QPointF(x + 1.5, y + 2), r, r)
        p.setPen(QPen(QColor("#9fb83a"), 1))
        p.setBrush(BALL)
        p.drawEllipse(QPointF(x, y), r, r)
        seam = QPen(QColor(255, 255, 255, 220), max(1.0, r * 0.18), Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap)
        p.setPen(seam)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(x - r * 1.6, y - r * 0.8, r * 1.4, r * 1.6), -60 * 16, 120 * 16)
        p.drawArc(QRectF(x + r * 0.2, y - r * 0.8, r * 1.4, r * 1.6), 120 * 16, 120 * 16)
