"""The games Bun picks besides Pong (bunpong.py has Pong, the shared `Game` and the
dialog): dodgeball, home run and whack-a-Bun. Each is a quick 1v1 on the same court,
Bun on the left, mouse or keys.

They're meant to be hard: Bun plays well and gets quicker as the points go in, so
winning takes real play, never luck or clicking everywhere. Each has a way in for a
good player (Dodgeball: hit him while he winds up, or box him in at an edge; Home
run: let the ones outside the box go by; Whack-a-Bun: never swing at nothing)."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QCursor, QLinearGradient, QPainter, QPainterPath, QPen,
                           QRadialGradient)

from soundboard.ui.kit import theme
from soundboard.ui.bun.bunny import INK, W, draw_bunny, sparkle
from soundboard.i18n import _
from soundboard.ui.bun.bunpong import BALL, BUN_PINK, GO_KEYS, SERVE_PAUSE, Game, _alpha, _mix

LEFT = (Qt.Key.Key_Left, Qt.Key.Key_A)
RIGHT = (Qt.Key.Key_Right, Qt.Key.Key_D)
UP = (Qt.Key.Key_Up, Qt.Key.Key_W)
DOWN = (Qt.Key.Key_Down, Qt.Key.Key_S)
MOVE_KEYS = {**{k: (-1, 0) for k in LEFT}, **{k: (1, 0) for k in RIGHT},
             **{k: (0, -1) for k in UP}, **{k: (0, 1) for k in DOWN}}
BUN_PAN, YOU_PAN = -0.6, 0.6   # where each side's sounds come from
CARROT = QColor("#ff9a3c")
LEAF = QColor("#4cc26a")


def _ink_pen(width: float) -> QPen:
    pen = QPen(INK, width)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    return pen


def _player(p: QPainter, x: float, y: float, rr: float):
    """You: a round player in the theme's colour, looking left at Bun."""
    acc = QColor(theme.T["accent"])
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_alpha(acc, 0.16))
    p.drawEllipse(QPointF(x, y), rr * 1.45, rr * 1.45)
    grad = QRadialGradient(QPointF(x - rr * 0.3, y - rr * 0.4), rr * 1.5)
    grad.setColorAt(0, _mix(acc, QColor("white"), 0.45))
    grad.setColorAt(1, acc)
    p.setPen(_ink_pen(max(1.5, rr * 0.12)))
    p.setBrush(grad)
    p.drawEllipse(QPointF(x, y), rr, rr)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(INK)
    for ex in (-0.42, 0.05):
        p.drawEllipse(QPointF(x + ex * rr, y - 0.12 * rr), rr * 0.12, rr * 0.16)


def _ball(p: QPainter, x: float, y: float, r: float, col: QColor):
    """A ball lit from the top left, with an ink edge."""
    grad = QRadialGradient(QPointF(x - r * 0.35, y - r * 0.4), r * 1.4)
    grad.setColorAt(0, _mix(col, QColor("white"), 0.55))
    grad.setColorAt(1, col)
    p.setPen(_ink_pen(max(1.2, r * 0.16)))
    p.setBrush(grad)
    p.drawEllipse(QPointF(x, y), r, r)


class _Aimed(Game):
    """A game steered like Pong: the mouse (read from the screen, so leaving the court
    never sticks it) or held arrow / WASD keys move where you want to be."""

    def reset(self):
        super().reset()
        self.held: set = set()
        self._cursor = QCursor.pos()

    def _mouse(self) -> QPointF | None:
        """The mouse in the court, px, if it moved since last asked."""
        pos = QCursor.pos()
        if pos == self._cursor or not self.isVisible():
            return None
        self._cursor = pos
        return QPointF(self.mapFromGlobal(pos))

    def _keys(self) -> tuple[int, int]:
        dx = sum(MOVE_KEYS[k][0] for k in self.held)
        dy = sum(MOVE_KEYS[k][1] for k in self.held)
        return max(-1, min(1, dx)), max(-1, min(1, dy))

    def key_up(self, k) -> bool:
        if k in self.held:
            self.held.discard(k)
            return True
        return False

    def focusOutEvent(self, ev):
        self.held.clear()   # a key let go somewhere else must not keep it moving
        super().focusOutEvent(ev)

    def _go(self, state: str):
        super()._go(state)
        # the pointer hides while you play (you're drawn where it is)
        self.setCursor(Qt.CursorShape.BlankCursor if self.playing
                       else Qt.CursorShape.ArrowCursor)


# ====================================================================== dodgeball
class Dodgeball(_Aimed):
    """Both throw, both dodge. You run about your half of the court (the mouse or the
    arrow keys, only so fast) and throw straight across at Bun (click / Space); he bats
    balls at you, aiming where you're heading. Hit him to score; get hit and the point
    is his. He dodges what he sees coming, but not while he winds up a throw (the pink
    ring at his bat), and the top and bottom of the court box him in. From the third
    point he can send two at once, from the sixth three."""

    ach = "dodge"
    YOU_SPEED = 1.2     # how fast you run, court heights a second
    YOU_R = 0.045       # your size (radius), of the court height
    BALL_R = 0.024      # a ball's, too
    THROW = 1.5         # your throws, court widths a second
    RELOAD = 0.45       # seconds between your throws
    HALF = 0.6          # your half starts this far across, of the width
    BUN_DODGE = 1.15    # how fast he gets out of the way, court heights a second
    BUN_DRIFT = 0.6     # ... and how fast he moves about otherwise
    KEEP = 0.2          # he keeps at least this far off your line, of the height
    REACT = 0.17        # seconds before he sees a throw coming
    MISREAD = (0.1, 0.42)   # now and then (chance) he's this slow to see it
    WINDUP = (0.38, 0.3)    # his wind-up, seconds: at first, at the end; he's still for it
    GAP = (1.05, 0.55)      # seconds between his throws: at first, at the end
    SPEED = (0.85, 1.25)    # his throws, court widths a second: at first, at the end

    @staticmethod
    def title() -> str:
        return _("Dodgeball with Bun")

    def how(self) -> str:
        return _("First to {n} hits wins. Move with the mouse or the arrow keys, throw "
                 "with a click or Space. He can't dodge while he winds up.", n=self.win_at)

    def reset(self):
        super().reset()
        self.you = [0.8, 0.5]           # where you are, 0..1 of the court
        self.aim = [0.8, 0.5]           # where the mouse / keys want you
        self.you_vy = 0.0               # how fast you're moving up / down, heights a second
        self.bun_y = 0.5                # where his bat is, 0..1 of the height
        self.spot = 0.3                 # where he's heading when nothing's coming
        self.balls: list[dict] = []     # x, y (0..1), vx, vy (px a second), who, age, seen
        self.reload = 0.0               # seconds till you can throw again
        self.act, self.act_t = "idle", 0.0   # Bun: "idle" or "windup", and for how long
        self.next_throw = 1.2           # seconds till his next wind-up
        self.windup = self.WINDUP[0]
        self.hit_at: tuple[float, float, float] | None = None   # x, y (px), age: a hit

    def _d(self) -> float:
        """How far into the game, 0 to 1: he speeds up as the points go in."""
        return min(1.0, (self.score["you"] + self.score["bun"]) / (2 * self.win_at - 2))

    def _lerp(self, pair: tuple[float, float]) -> float:
        return pair[0] + (pair[1] - pair[0]) * self._d()

    # ------------------------------------------------------------------ geometry
    def geo(self) -> dict:
        g = super().geo()
        s, h = g["s"], g["h"]
        g.update({"bun_min": (72 * s + 6) / h, "bun_max": 1 - (g["bh"] - 72 * s + 6) / h,
                  "r": max(4.0, h * self.BALL_R), "you_r": max(9.0, h * self.YOU_R)})
        return g

    def bun_rect(self, g: dict) -> QRectF:
        if self.state == "over":
            return super().bun_rect(g)
        s = g["s"]
        return QRectF(g["bun_x"] - 86 * s, self.bun_y * g["h"] - 72 * s, W * s, g["bh"])

    def score_boxes(self, w: float, h: float) -> tuple[QRectF, QRectF]:
        nw = w * 0.11   # either side of your half's line, out of Bun's way
        bun = QRectF(self.HALF * w - nw - w * 0.025, h * 0.06, nw, h * 0.22)
        return bun, bun.translated(nw + w * 0.05, 0)

    def bun_box(self, g: dict) -> QRectF:
        """Where a ball hits him, px: his body and head, not the tips of his ears."""
        r = self.bun_rect(g)
        s = g["s"]
        return QRectF(r.left() + 20 * s, r.top() + 30 * s, 62 * s, 86 * s)

    def _area(self, g: dict) -> tuple[float, float, float, float]:
        """Your half: the most left, right, up and down you can be, 0..1."""
        rx, ry = g["you_r"] * 1.4 / g["w"], g["you_r"] * 1.4 / g["h"]   # the ring too
        return self.HALF + rx, 1 - rx - 12 / g["w"], ry + 12 / g["h"], 1 - ry - 12 / g["h"]

    # ------------------------------------------------------------------ play
    def start(self):
        self.balls.clear()
        self.reload = 0.0
        self.act, self.act_t = "idle", 0.0
        self.next_throw = self.rng.uniform(0.7, 1.1)
        self._go("play")
        self._play("serve")

    def throw(self):
        """Your click / Space: a ball straight across at Bun."""
        if self.state == "ready":
            self.start()
            return
        if self.state != "play" or self.reload > 0:
            return
        self.reload = self.RELOAD
        g = self.geo()
        slow = self.rng.random() < self.MISREAD[0]
        self.balls.append({"x": self.you[0] - g["you_r"] / g["w"], "y": self.you[1],
                           "vx": -self.THROW * g["w"], "vy": 0.0, "who": "you", "age": 0.0,
                           "seen": self.MISREAD[1] if slow else self.REACT})
        self._play("you", pan=YOU_PAN)

    def _bun_throw(self, g: dict):
        """He bats one (or two or three) at where he thinks you'll be."""
        w, h = g["w"], g["h"]
        x0, y0 = (g["bun_x"] + 8) / w, self.bun_y
        speed = self._lerp(self.SPEED) * w
        dx = self.you[0] * w - x0 * w
        t = dx / speed
        lead = self.rng.uniform(0.4, 1.0)   # how much he trusts where you're heading
        lo, hi = self._area(g)[2:]
        ty = min(hi, max(lo, self.you[1] + self.you_vy * t * lead + self.rng.gauss(0, 0.035)))
        pts = self.score["you"] + self.score["bun"]
        n = 1
        if pts >= 6 and self.rng.random() < 0.3:
            n = 3
        elif pts >= 3 and self.rng.random() < 0.35:
            n = 2
        spread = {1: (0.0,), 2: (-0.085, 0.085), 3: (-0.15, 0.0, 0.15)}[n]
        for off in spread:
            dy = (ty + off) * h - y0 * h
            k = speed / math.hypot(dx, dy)
            self.balls.append({"x": x0, "y": y0, "vx": dx * k, "vy": dy * k, "who": "bun",
                               "age": 0.0, "seen": 0.0})
        self.swing = 0.45
        self._play("bun", pan=BUN_PAN, heat=self._d())

    def step(self, dt: float):
        super().step(dt)
        g = self.geo()
        self._steer(dt, g)
        if self.hit_at is not None:
            x, y, age = self.hit_at
            self.hit_at = (x, y, age + dt) if age < 0.5 else None
        if self.state == "point" and self.st >= SERVE_PAUSE:
            self.start()
        if self.state != "play":
            self._bun_move(dt, g, None)
            return
        self.reload = max(0.0, self.reload - dt)
        # Bun: wind up, then throw; otherwise keep an eye out for yours
        self.act_t += dt
        if self.act == "idle":
            self.next_throw -= dt
            if self.next_throw <= 0:
                self.act, self.act_t = "windup", 0.0
                self.windup = self._lerp(self.WINDUP)
        elif self.act == "windup" and self.act_t >= self.windup:
            self._bun_throw(g)
            self.act, self.act_t = "idle", 0.0
            self.next_throw = self._lerp(self.GAP) * self.rng.uniform(0.75, 1.25)
            self.spot = self._new_spot(g["bun_min"], g["bun_max"])
        self._bun_move(dt, g, self._threat(g))
        # the balls, in a few sub-steps so a fast one can't skip through anyone
        n = max(1, math.ceil(dt / 0.008))
        for _i in range(n):
            if self._move(dt / n, g):
                return
        self.balls = [b for b in self.balls if -0.05 < b["x"] < 1.05 and -0.1 < b["y"] < 1.1]

    def _steer(self, dt: float, g: dict):
        m = self._mouse()
        if m is not None:
            self.aim = [m.x() / g["w"], m.y() / g["h"]]
        dx, dy = self._keys()
        if dx or dy:
            self.aim = [self.you[0] + dx * 0.2 * g["h"] / g["w"], self.you[1] + dy * 0.2]
        left, right, top, bottom = self._area(g)
        self.aim = [min(right, max(left, self.aim[0])), min(bottom, max(top, self.aim[1]))]
        # you run there, only so fast (px, so it's the same speed both ways)
        ex = (self.aim[0] - self.you[0]) * g["w"]
        ey = (self.aim[1] - self.you[1]) * g["h"]
        dist = math.hypot(ex, ey)
        move = self.YOU_SPEED * g["h"] * dt
        k = 1.0 if dist <= move else move / dist
        old = self.you[1]
        self.you = [self.you[0] + ex * k / g["w"], self.you[1] + ey * k / g["h"]]
        if dt > 0:
            self.you_vy = 0.8 * self.you_vy + 0.2 * (self.you[1] - old) / dt

    def _threat(self, g: dict) -> dict | None:
        """The nearest of your throws he has seen that would hit him where he is."""
        box = self.bun_box(g)
        r = g["r"]
        best = None
        for b in self.balls:
            if b["who"] != "you" or b["age"] < b["seen"]:
                continue
            y = b["y"] * g["h"]
            if box.top() - r - 6 <= y <= box.bottom() + r + 6:
                if best is None or b["x"] < best["x"]:
                    best = b
        return best

    def _bun_move(self, dt: float, g: dict, threat: dict | None):
        h = g["h"]
        lo, hi = g["bun_min"], g["bun_max"]
        if self.state == "play" and self.act == "windup":
            return   # planted for his throw: the moment to get him
        if threat is not None:
            # out of the way to whichever side is nearer and has room
            box = self.bun_box(g)
            y = threat["y"] * h
            pad = g["r"] + 10
            up = self.bun_y - (box.bottom() + pad - y) / h
            down = self.bun_y + (y - box.top() + pad) / h
            can_up, can_down = up >= lo, down <= hi
            if can_up and (not can_down or self.bun_y - up <= down - self.bun_y):
                target, speed = up, self.BUN_DODGE
            elif can_down:
                target, speed = down, self.BUN_DODGE
            else:   # boxed in at an edge: away from it, as far as he can
                target, speed = (lo if down > hi else hi), self.BUN_DODGE
        else:
            if self.state != "play":
                self.spot = 0.5
            elif abs(self.spot - self.you[1]) < self.KEEP:   # you've lined up on him
                self.spot = self._new_spot(lo, hi)
            target, speed = self.spot, self.BUN_DRIFT
        target = min(hi, max(lo, target))
        move = speed * dt
        self.bun_y += max(-move, min(move, target - self.bun_y))

    def _new_spot(self, lo: float, hi: float) -> float:
        """Somewhere off your line to stand (he'd rather not be straight across from
        you), if there's room."""
        far = [y for y in (lo + (hi - lo) * i / 8 for i in range(9))
               if abs(y - self.you[1]) >= self.KEEP * 1.5]
        return self.rng.choice(far) if far else (lo if self.you[1] > 0.5 else hi)

    def _move(self, dt: float, g: dict) -> bool:
        """Move the balls on; True if a point was scored."""
        w, h, r = g["w"], g["h"], g["r"]
        box = self.bun_box(g).adjusted(-r, -r, r, r)
        yx, yy = self.you[0] * w, self.you[1] * h
        for b in self.balls:
            b["age"] += dt
            b["x"] += b["vx"] * dt / w
            b["y"] += b["vy"] * dt / h
            x, y = b["x"] * w, b["y"] * h
            if b["who"] == "you" and box.contains(QPointF(x, y)):
                return self._hit("you", x, y)
            if b["who"] == "bun" and math.hypot(x - yx, y - yy) <= r + g["you_r"]:
                return self._hit("bun", x, y)
        return False

    def _hit(self, who: str, x: float, y: float) -> bool:
        self.hit_at = (x, y, 0.0)
        self._burst(x, y, QColor(theme.T["accent"]) if who == "you" else BUN_PINK, 22, 1.3)
        self._play("bang", pan=YOU_PAN if who == "bun" else BUN_PAN)
        self.balls.clear()
        self.act = "idle"
        if not self._point(who):
            self._go("point")
        return True

    # ------------------------------------------------------------------ input
    def key(self, k) -> bool:
        if k in MOVE_KEYS:
            self.held.add(k)
            if self.state == "ready":
                self.start()
        elif k in GO_KEYS:
            self.throw()
        else:
            return False
        return True

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.throw()

    # ------------------------------------------------------------------ paint
    def bun_pose(self) -> dict:
        pose = super().bun_pose()
        if self.state == "play" and self.act == "windup":   # bat drawn right back
            pose["swing"] = -0.25 * min(1.0, self.act_t / 0.12)
            pose["angry"] = 0.9
        return pose

    def paint_back(self, p: QPainter, g: dict):
        w, h = g["w"], g["h"]
        dash = QPen(_alpha(theme.T["text_hi"], 0.22), 2, Qt.PenStyle.CustomDashLine,
                    Qt.PenCapStyle.RoundCap)
        dash.setDashPattern([2.5, 4])
        p.setPen(dash)
        p.drawLine(QPointF(self.HALF * w, 12), QPointF(self.HALF * w, h - 12))

    def paint_game(self, p: QPainter, g: dict):
        w, h, r = g["w"], g["h"], g["r"]
        acc = QColor(theme.T["accent"])
        if self.state == "play" and self.act == "windup":   # his tell: a ring closing in
            k = min(1.0, self.act_t / max(0.01, self.windup))
            cx, cy = g["bun_x"] + 8, self.bun_y * h
            rr = r * (4.2 - 3.0 * k)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_alpha(BUN_PINK, 0.35 + 0.5 * k), 2.5))
            p.drawEllipse(QPointF(cx, cy), rr, rr)
        for b in self.balls:
            col = acc if b["who"] == "you" else BUN_PINK
            x, y = b["x"] * w, b["y"] * h
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(1, 5):   # a short trail behind it
                t = i * 0.012
                p.setBrush(_alpha(col, 0.22 - i * 0.045))
                p.drawEllipse(QPointF(x - b["vx"] * t, y - b["vy"] * t), r * (1 - i * 0.12),
                              r * (1 - i * 0.12))
            _ball(p, x, y, r, col)
        if self.hit_at is not None:
            x, y, age = self.hit_at
            k = age / 0.5
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_alpha(BALL, 0.8 * (1 - k)), 3))
            p.drawEllipse(QPointF(x, y), r * (1.5 + 4 * k), r * (1.5 + 4 * k))
        self._paint_you(p, g)
        if self.state == "ready":
            self._prompt(p, _("Click or press Space to start"),
                         QRectF(self.HALF * w, h * 0.7, w * (1 - self.HALF), h * 0.1),
                         h * 0.045)

    def _paint_you(self, p: QPainter, g: dict):
        """You, the ring round you filling up as your next throw gets ready."""
        x, y, rr = self.you[0] * g["w"], self.you[1] * g["h"], g["you_r"]
        _player(p, x, y, rr)
        acc = QColor(theme.T["accent"])
        ready = 1 - self.reload / self.RELOAD
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_alpha(theme.T["text_hi"], 0.15), 3))
        ring = QRectF(x - rr * 1.3, y - rr * 1.3, rr * 2.6, rr * 2.6)
        p.drawEllipse(ring)
        pen = QPen(_alpha(acc if ready >= 1 else theme.T["text_hi"], 0.85), 3,
                   Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(ring, 90 * 16, -round(360 * 16 * ready))


# ====================================================================== home run
class HomeRun(_Aimed):
    """Bun pitches, you bat. Put your bat at the ball's height (the mouse or the arrow
    keys) and swing (click / Space) just as it reaches the box: on time and on height
    is a home run, your point. A miss, a strike you let go by, or a swing at one outside
    the box is a strike, his point. Close but not quite is a foul: nobody's point. He
    mixes fast ones, slow ones and curves that break late, and throws harder as the
    game goes on."""

    ach = "homerun"
    HR_TIME = (0.03, 0.02)     # a home run: this close to on time, seconds (at first, end)
    FOUL_TIME = 0.085          # a foul: this close
    HR_HEIGHT = 0.035          # a home run: bat this close to the ball, of the court height
    FOUL_HEIGHT = 0.1          # a foul: this close
    FLIGHT = (0.78, 0.52)      # a fast one's flight, seconds (at first, at the end)
    SLOW = 1.5                 # a slow one takes this many times as long
    CURVE = 1.15               # a curve this many, and bends this much at most:
    BEND = (0.1, 0.2)          # of the court height
    IN_BOX = 0.68              # how many of his pitches are in the box
    BAT_SPEED = 1.3            # your bat on the keys, court heights a second
    SWING = 0.2                # the swing, seconds

    @staticmethod
    def title() -> str:
        return _("Home run with Bun")

    def how(self) -> str:
        return _("First to {n} wins. Hold your bat at the ball's height with the mouse or "
                 "the arrow keys, and swing with a click or Space as it reaches the box. "
                 "Let the ones outside the box go by.", n=self.win_at)

    def reset(self):
        super().reset()
        self.bat_y = 0.56              # your bat's height, 0..1
        self.pitch: dict = {}          # the pitch in the air ({}: none yet)
        self.swung: float | None = None   # seconds since you swung (None: not yet)
        self.result = ""               # "hr", "foul", "strike", "ball": what this pitch was
        self.fly: list[float] | None = None   # x, y, vx, vy (px): the ball after a hit
        self.windup = 0.0
        self._stepped = time.monotonic()   # when the last step ran

    def _d(self) -> float:
        return min(1.0, (self.score["you"] + self.score["bun"]) / (2 * self.win_at - 2))

    def _lerp(self, pair: tuple[float, float]) -> float:
        return pair[0] + (pair[1] - pair[0]) * self._d()

    # ------------------------------------------------------------------ geometry
    def geo(self) -> dict:
        g = super().geo()
        h = g["h"]
        span = g["x1"] - g["x0"]
        g.update({"plate": g["x1"] - span * 0.3, "zone_y": h * 0.56, "zone_h": h * 0.17,
                  "zone_w": max(12.0, span * 0.035), "r": max(6.0, h * 0.03),
                  "bat_len": h * 0.2, "you_r": max(10.0, h * 0.05)})
        br = super().bun_rect(g)
        g["hand"] = (br.left() + 84 * g["s"], br.top() + 52 * g["s"])   # where he lets go
        return g

    def _ball_at(self, g: dict, t: float) -> tuple[float, float]:
        """Where the pitch is `t` seconds after he let go, px (past the plate it carries
        on the same way)."""
        pt = self.pitch
        hx, hy = g["hand"]
        u = t / pt["T"]
        x = hx + (g["plate"] - hx) * u
        y = hy + (pt["ty"] * g["h"] - hy) * min(u, 1.0)
        if u > 1:
            y += (pt["ty"] * g["h"] - hy) * (u - 1) * 0.5
        uu = min(u, 1.0)   # a curve: off to one side, and back in late
        y += pt["bend"] * g["h"] * 6.75 * uu * uu * (1 - uu)
        return x, y

    def in_box(self, g: dict, y_frac: float) -> bool:
        return abs(y_frac * g["h"] - g["zone_y"]) <= g["zone_h"]

    # ------------------------------------------------------------------ play
    def start(self):
        self.fly = None
        self.pitch, self.swung, self.result = {}, None, ""
        self.windup = self.rng.uniform(0.6, 1.25)
        self._go("windup")

    def _release(self, g: dict):
        d = self._d()
        kind = self.rng.choices(("fast", "slow", "curve"),
                                (0.55 - 0.15 * d, 0.22 + 0.08 * d, 0.23 + 0.07 * d))[0]
        T = self._lerp(self.FLIGHT) * {"fast": 1.0, "slow": self.SLOW, "curve": self.CURVE}[kind]
        zy, zh = g["zone_y"] / g["h"], g["zone_h"] / g["h"]
        if self.rng.random() < self.IN_BOX:
            ty = zy + self.rng.uniform(-0.85, 0.85) * zh
        else:
            ty = zy + self.rng.choice((-1, 1)) * self.rng.uniform(1.3, 1.9) * zh
        bend = 0.0
        if kind == "curve":
            bend = self.rng.choice((-1, 1)) * self.rng.uniform(*self.BEND)
        self.pitch = {"kind": kind, "T": T, "ty": ty, "bend": bend, "t": 0.0}
        self._go("pitch")
        self._play("serve")

    def swing_bat(self):
        """Your click / Space."""
        if self.state == "ready":
            self.start()
            return
        if self.state != "pitch" or self.swung is not None:
            return
        self.swung = 0.0
        g = self.geo()
        pt = self.pitch
        # a click lands between two frames: count the time since the last one too, so
        # the timing is as fine as the click, not the frame rate
        early = pt["t"] + min(0.03, time.monotonic() - self._stepped) - pt["T"]
        bx, by = self._ball_at(g, pt["T"])   # where it crosses the plate
        off = abs(by - self.bat_y * g["h"]) / g["h"]
        if not self.in_box(g, by / g["h"]):
            self._call("strike", _("chased it!"))
        elif abs(early) <= self._lerp(self.HR_TIME) and off <= self.HR_HEIGHT:
            self._call("hr")
        elif abs(early) <= self.FOUL_TIME and off <= self.FOUL_HEIGHT:
            self._call("foul")
        else:
            self._call("strike", _("swing and a miss!"))

    def _call(self, result: str, say: str = ""):
        """How this pitch went: a home run (yours), a strike (his), a foul or a ball."""
        self.result = result
        g = self.geo()
        x, y = self._ball_at(g, self.pitch["t"])
        if result == "hr":
            self.fly = [x, y, -1.5 * g["w"], -1.25 * g["h"]]
            self._burst(x, y, QColor(theme.T["accent"]), 26, 1.5)
            self._play("bang", pan=YOU_PAN)
            self._play("you", rally=4, pan=YOU_PAN, heat=1.0)
            if not self._point("you", quip=False):
                self._say(self.fx.choice((_("no way!"), _("that's gone!"), _("my ball!"))))
                self._go("after")
        elif result == "foul":
            self.fly = [x, y, 0.4 * g["w"], -1.4 * g["h"]]
            self._play("wall", pan=YOU_PAN)
            self._say(_("foul!"), 0.9)
            self._go("after")
        elif result == "strike":
            if not self._point("bun", quip=False):
                self._say(say or _("strike!"))
                self._go("after")
        else:
            self._say(_("ball."), 0.8)
            self._go("after")

    def step(self, dt: float):
        super().step(dt)
        self._stepped = time.monotonic()
        g = self.geo()
        self._steer(dt, g)
        if self.swung is not None:
            self.swung += dt
        if self.fly is not None:
            self.fly[0] += self.fly[2] * dt
            self.fly[1] += self.fly[3] * dt
            self.fly[3] += 2.2 * g["h"] * dt
        if self.state == "windup" and self.st >= self.windup:
            self._release(g)
        elif self.state == "pitch":
            self.pitch["t"] += dt
            t, T = self.pitch["t"], self.pitch["T"]
            if self.swung is None and t >= T + 0.12:   # it went by
                _x, y = self._ball_at(g, T)
                if self.in_box(g, y / g["h"]):
                    self._call("strike", _("strike! looking."))
                else:
                    self._call("ball")
        elif self.state == "after":
            if self.pitch and self.fly is None:
                self.pitch["t"] += dt
            if self.st >= 1.1:
                self.start()

    def _steer(self, dt: float, g: dict):
        m = self._mouse()
        if m is not None:
            self.bat_y = m.y() / g["h"]
        dy = self._keys()[1]
        if dy:
            self.bat_y += dy * self.BAT_SPEED * dt
        lo = (g["zone_y"] - g["zone_h"] * 2.2) / g["h"]
        hi = min(g["zone_y"] + g["zone_h"] * 2.2,   # you stay on the court too
                 g["h"] - g["you_r"] * 1.9 - 14) / g["h"]
        self.bat_y = min(hi, max(lo, self.bat_y))

    # ------------------------------------------------------------------ input
    def key(self, k) -> bool:
        if k in UP or k in DOWN:
            self.held.add(k)
            self.bat_y += (-1 if k in UP else 1) * 0.02
        elif k in GO_KEYS:
            self.swing_bat()
        else:
            return False
        return True

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.swing_bat()

    # ------------------------------------------------------------------ paint
    def bun_pose(self) -> dict:
        pose = super().bun_pose()
        if self.state == "over":
            return pose
        pose["prop"] = None
        if self.state == "windup":   # the arm going round
            pose["wave"] = math.sin(self.st * 9)
        elif self.state == "after" and self.result == "hr":
            pose["sad"], pose["angry"] = 0.6, 0.0
        elif self.state == "after" and self.result == "strike":
            pose["smug"] = True
        return pose

    def paint_back(self, p: QPainter, g: dict):
        """The box: where his strikes go."""
        hi = QColor(theme.T["text_hi"])
        x, zy, zh, zw = g["plate"], g["zone_y"], g["zone_h"], g["zone_w"]
        box = QRectF(x - zw, zy - zh, 2 * zw, 2 * zh)
        p.setPen(QPen(_alpha(hi, 0.3), 2))
        p.setBrush(_alpha(hi, 0.05))
        p.drawRoundedRect(box, 4, 4)
        dash = QPen(_alpha(hi, 0.12), 1.5, Qt.PenStyle.CustomDashLine)
        dash.setDashPattern([3, 4])
        p.setPen(dash)
        for k in (1 / 3, 2 / 3):
            yy = box.top() + box.height() * k
            p.drawLine(QPointF(box.left(), yy), QPointF(box.right(), yy))

    def paint_game(self, p: QPainter, g: dict):
        w, h, r = g["w"], g["h"], g["r"]
        if self.pitch and self.fly is None and self.state in ("pitch", "after"):
            x, y = self._ball_at(g, self.pitch["t"])
            if x < w + r * 2:
                hx = g["hand"][0]
                k = max(0.0, min(1.0, (x - hx) / max(1.0, g["plate"] - hx)))
                rr = r * (0.75 + 0.45 * k)   # bigger as it comes at you
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(_alpha("black", 0.12))
                p.drawEllipse(QPointF(x, h * 0.93), rr * 1.3, rr * 0.35)
                _ball(p, x, y, rr, QColor("#f4f1e8"))
                p.setPen(QPen(QColor("#e0485a"), max(1.0, rr * 0.14)))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawArc(QRectF(x - rr * 1.4, y - rr * 0.8, rr * 1.4, rr * 1.6), -50 * 16,
                          100 * 16)
        if self.fly is not None:
            _ball(p, self.fly[0], self.fly[1], r, QColor("#f4f1e8"))
        self._paint_bat(p, g)
        if self.state == "ready":
            self._prompt(p, _("Click or press Space to start"),
                         QRectF(g["x0"], h * 0.84, g["x1"] - g["x0"], h * 0.1), h * 0.045)
        elif self.state == "after" and self.result == "hr":
            k = min(1.0, self.st / 0.15)
            self._prompt(p, _("Home run!"), QRectF(g["x0"], h * 0.08, g["x1"] - g["x0"],
                                                   h * 0.16),
                         h * (0.06 + 0.03 * k), QColor(theme.T["accent"]))

    REST, FOLLOW = 100.0, -70.0   # the bat's angle held ready and after the swing:
    # 0 points it flat at Bun (over the plate), 90 straight up

    def bat_angle(self) -> float:
        if self.swung is None or self.swung > self.SWING + 0.35:
            return self.REST
        k = min(1.0, self.swung / self.SWING)
        return self.REST + (self.FOLLOW - self.REST) * (1 - (1 - k) ** 3)

    def _paint_bat(self, p: QPainter, g: dict):
        """You, the batter, behind the plate at your bat's height; a swing sweeps the bat
        down across the box, flat out over the plate half-way through."""
        acc = QColor(theme.T["accent"])
        length = g["bat_len"]
        y = self.bat_y * g["h"]
        hands = QPointF(g["plate"] + length * 0.95, y)
        ang = self.bat_angle()
        rr = g["you_r"]
        # the height guide: a faint line out to the plate at the bat's height
        p.setPen(QPen(_alpha(acc, 0.35), 1.5, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(g["plate"] - g["zone_w"] - 6, y), QPointF(hands.x() - 4, y))
        _player(p, hands.x() + rr * 0.9, y + rr * 0.25, rr)
        if self.swung is not None and self.swung < self.SWING + 0.1:   # the swing's blur
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_alpha(acc, 0.13))
            box = QRectF(hands.x() - length, hands.y() - length, 2 * length, 2 * length)
            p.drawPie(box, round((180 - self.REST) * 16), round((self.REST - ang) * 16))
        a = math.radians(ang)
        tip = QPointF(hands.x() - math.cos(a) * length, hands.y() - math.sin(a) * length)
        path = QPainterPath()
        ux, uy = (tip.x() - hands.x()) / length, (tip.y() - hands.y()) / length
        nx, ny = -uy, ux
        th0, th1 = length * 0.035, length * 0.085   # thin at the handle, fat at the end
        path.moveTo(hands.x() + nx * th0, hands.y() + ny * th0)
        path.lineTo(tip.x() + nx * th1, tip.y() + ny * th1)
        path.quadTo(tip.x() + ux * th1 * 1.6, tip.y() + uy * th1 * 1.6,
                    tip.x() - nx * th1, tip.y() - ny * th1)
        path.lineTo(hands.x() - nx * th0, hands.y() - ny * th0)
        path.closeSubpath()
        wood = QLinearGradient(hands, tip)
        wood.setColorAt(0, QColor("#a8743f"))
        wood.setColorAt(1, QColor("#e3b47a"))
        p.setPen(_ink_pen(max(1.4, length * 0.014)))
        p.setBrush(wood)
        p.drawPath(path)
        p.setBrush(QColor("#2b2340"))   # the grip tape and your paws on it
        p.drawEllipse(hands, length * 0.055, length * 0.055)


# ====================================================================== whack-a-Bun
HOLE_KEYS = {getattr(Qt.Key, f"Key_{n}"): i
             for i, n in enumerate((7, 8, 9, 4, 5, 6, 1, 2, 3))}   # as on the number pad


class WhackABun(Game):
    """Little Buns pop up out of nine burrows; whack each one (click it, or its key, laid
    out as on the number pad) before it ducks back down. One that gets away is Bun's
    point, and so is whacking a carrot. Swinging at an empty burrow sticks your mallet
    for a moment, so clicking everywhere loses. You need 15, he needs 5. They come
    quicker, two at a time and with more carrots as you go."""

    ach = "whack"
    YOU_GOAL, BUN_GOAL = 20, 5
    UP_FOR = (1.1, 0.66)      # how long one stays up, seconds: at first, at the end
    GAP = (0.85, 0.42)        # seconds between them
    TWO = (0.06, 0.3)         # the chance two come at once
    DECOY = (0.12, 0.28)      # the chance it's a carrot
    CARROT_UP = 1.25          # a carrot stays up this long
    STUCK = 0.42              # a swing at nothing sticks the mallet this long
    RISE, SINK = 0.09, 0.12   # popping up and ducking down, seconds

    @staticmethod
    def title() -> str:
        return _("Whack-a-Bun")

    def how(self) -> str:
        return _("Whack {n} Buns before {m} get away. Click them, or press their number "
                 "on the number pad. Never the carrots, and don't swing at nothing.",
                 n=self.YOU_GOAL, m=self.BUN_GOAL)

    def goal(self, who: str) -> int:
        return self.YOU_GOAL if who == "you" else self.BUN_GOAL

    def score_text(self, side: str) -> str:
        return f"{self.score[side]}/{self.goal(side)}"

    def score_boxes(self, w: float, h: float) -> tuple[QRectF, QRectF]:
        bun = QRectF(16, h * 0.05, h * 0.19, h * 0.085)   # smaller, to fit "12/20" twice
        return bun, bun.translated(h * 0.21, 0)

    def reset(self):
        super().reset()
        self.holes: list[dict | None] = [None] * 9   # what's up in each: kind, t, up, hit
        self.next_pop = 0.9
        self.stuck = 0.0             # seconds your mallet's stuck for
        self.mallet = QPointF(-100, -100)   # where it is, px
        self.whack_t = 9.0           # seconds since you swung it

    def _d(self) -> float:
        return min(1.0, self.score["you"] / (self.YOU_GOAL - 1))

    def _lerp(self, pair: tuple[float, float]) -> float:
        return pair[0] + (pair[1] - pair[0]) * self._d()

    # ------------------------------------------------------------------ geometry
    def geo(self) -> dict:
        g = super().geo()
        h = g["h"]
        span = g["x1"] - g["x0"] - 10
        cw = min(span / 3, h * 0.82 / 3 * 1.25)   # one burrow's cell
        ch = cw / 1.25
        left = g["x0"] + (span - 3 * cw) / 2 + 5
        top = h * 0.1 + (h * 0.82 - 3 * ch) / 2
        g.update({"cell_w": cw, "cell_h": ch, "grid_x": left, "grid_y": top})
        return g

    def hole(self, g: dict, i: int) -> tuple[float, float, float]:
        """Burrow i's middle (its opening) and its opening's width, px."""
        cw, ch = g["cell_w"], g["cell_h"]
        cx = g["grid_x"] + (i % 3 + 0.5) * cw
        cy = g["grid_y"] + (i // 3) * ch + ch * 0.62
        return cx, cy, cw * 0.62

    def _hole_at(self, pos: QPointF) -> int | None:
        g = self.geo()
        for i in range(9):
            cx, cy, hw = self.hole(g, i)
            top, bottom = cy - g["cell_h"] * 0.72, cy + hw * 0.22
            if abs(pos.x() - cx) <= g["cell_w"] / 2 and top <= pos.y() <= bottom:
                return i
        return None

    # ------------------------------------------------------------------ play
    def start(self):
        self.holes = [None] * 9
        self.next_pop = 0.6
        self._go("play")
        self._play("serve")

    def _pop(self):
        free = [i for i, hl in enumerate(self.holes) if hl is None]
        n = 2 if self.rng.random() < self._lerp(self.TWO) else 1
        for i in self.rng.sample(free, min(n, len(free))):
            carrot = self.rng.random() < self._lerp(self.DECOY)
            up = self.CARROT_UP if carrot else self._lerp(self.UP_FOR) * self.rng.uniform(0.85, 1.1)
            self.holes[i] = {"kind": "carrot" if carrot else "bun", "t": 0.0, "up": up,
                             "hit": False}
        self._play("hover")

    def whack(self, i: int | None):
        """Your swing at burrow i (None: not at a burrow)."""
        if self.state == "ready":
            self.start()
            return
        if self.state != "play" or self.stuck > 0:
            return
        self.whack_t = 0.0
        hl = self.holes[i] if i is not None else None
        g = self.geo()
        if i is not None:
            cx, cy, _hw = self.hole(g, i)
            self.mallet = QPointF(cx, cy - g["cell_h"] * 0.35)
        if i is None or hl is None or hl["hit"] or not self._showing(hl):
            self.stuck = self.STUCK   # nothing there
            self._play("wall")
            return
        hl["hit"] = True
        hl["t"] = max(hl["t"], hl["up"])   # down it goes
        cx, cy, hw = self.hole(g, i)
        if hl["kind"] == "carrot":
            self._play("early")
            self._burst(cx, cy - hw * 0.3, CARROT, 14)
            self._point("bun", quip=False)
            if self.state != "over":
                self._say(self.fx.choice((_("my carrot!"), _("hey, that's mine!"))))
        else:
            self._play("you", rally=min(8, self.score["you"] // 2), pan=(i % 3 - 1) * 0.5)
            self._burst(cx, cy - hw * 0.4, QColor(theme.T["accent"]), 16, 1.1)
            self._point("you", quip=False)
            if self.state != "over" and self.fx.random() < 0.3:
                self._say(self.fx.choice((_("ow!"), _("hey!"), _("lucky!"))), 0.9)

    def _showing(self, hl: dict) -> bool:
        """Up far enough to whack: from a little way out until it's nearly down."""
        return 0.04 <= hl["t"] <= hl["up"] + self.SINK * 0.4

    def step(self, dt: float):
        super().step(dt)
        self.whack_t += dt
        self.stuck = max(0.0, self.stuck - dt)
        if self.state != "play":
            return
        for i, hl in enumerate(self.holes):
            if hl is None:
                continue
            hl["t"] += dt
            if hl["t"] >= hl["up"] + self.SINK:
                self.holes[i] = None
                if hl["kind"] == "bun" and not hl["hit"]:   # got away
                    if self._point("bun", quip=False):
                        return
                    self._say(self.fx.choice((_("too slow!"), _("ha!"), _("missed one!"))))
        self.next_pop -= dt
        if self.next_pop <= 0:
            self._pop()
            self.next_pop = self._lerp(self.GAP) * self.rng.uniform(0.7, 1.3)

    # ------------------------------------------------------------------ input
    def key(self, k) -> bool:
        if k in HOLE_KEYS:
            self.whack(HOLE_KEYS[k])
        elif k in GO_KEYS and self.state == "ready":
            self.start()
        else:
            return False
        return True

    def mouseMoveEvent(self, ev):
        self.mallet = ev.position()

    def leaveEvent(self, ev):
        self.mallet = QPointF(-100, -100)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.mallet = ev.position()
            self.whack(self._hole_at(ev.position()))

    def _go(self, state: str):
        super()._go(state)
        self.setCursor(Qt.CursorShape.BlankCursor if state == "play"
                       else Qt.CursorShape.ArrowCursor)

    # ------------------------------------------------------------------ paint
    def bun_pose(self) -> dict:
        pose = super().bun_pose()
        if self.state == "play" and self.pop["bun"] < 0.8:   # one got away: he loves it
            pose["smug"] = True
            pose["angry"] = 0.0
        return pose

    def paint_game(self, p: QPainter, g: dict):
        for i in range(9):
            self._paint_hole(p, g, i)
        self._paint_mallet(p, g)
        if self.state == "ready":
            self._prompt(p, _("Click or press Space to start"),
                         QRectF(g["x0"], g["h"] * 0.02, g["x1"] - g["x0"], g["h"] * 0.09),
                         g["h"] * 0.042)

    def _paint_hole(self, p: QPainter, g: dict, i: int):
        cx, cy, hw = self.hole(g, i)
        hh = hw * 0.3
        hi = QColor(theme.T["text_hi"])
        light = theme.is_light()
        # the mound round the opening
        mound = QRectF(cx - hw * 0.68, cy - hh * 0.9, hw * 1.36, hh * 2.3)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_alpha(hi, 0.07 if not light else 0.06))
        p.drawEllipse(mound)
        # the opening, dark inside
        opening = QRectF(cx - hw / 2, cy - hh / 2, hw, hh)
        dark = QRadialGradient(QPointF(cx, cy + hh * 0.2), hw * 0.55)
        dark.setColorAt(0, QColor(0, 0, 0, 200))
        dark.setColorAt(1, QColor(0, 0, 0, 120))
        p.setBrush(dark)
        p.drawEllipse(opening)
        hl = self.holes[i]
        if hl is not None:
            self._paint_popper(p, g, i, hl, opening)
        # its front lip, drawn over whatever's coming out
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_alpha(hi, 0.28), max(1.5, hw * 0.035)))
        p.drawArc(opening, 200 * 16, 140 * 16)
        if hl is None and not self.playing:   # the key it answers to
            n = (7, 8, 9, 4, 5, 6, 1, 2, 3)[i]
            self._prompt(p, str(n), QRectF(cx - 20, cy + hh * 0.5, 40, hh * 1.6), hh * 0.9,
                         _alpha(hi, 0.35))

    def _paint_popper(self, p: QPainter, g: dict, i: int, hl: dict, opening: QRectF):
        """A little Bun (or a carrot) out of burrow i, cut off at the opening."""
        cx, cy = opening.center().x(), opening.center().y()
        hw = opening.width()
        t, up = hl["t"], hl["up"]
        if t < self.RISE:
            out = t / self.RISE
        elif t < up:
            out = 1.0
        else:
            out = max(0.0, 1 - (t - up) / self.SINK)
        out = 1 - (1 - out) ** 2
        clip = QPainterPath()   # all above the opening's middle, and the opening itself
        clip.setFillRule(Qt.FillRule.WindingFill)
        clip.addRect(QRectF(cx - hw, cy - g["cell_h"] * 1.2, hw * 2, g["cell_h"] * 1.2))
        clip.addEllipse(opening)
        p.save()
        p.setClipPath(clip)
        if hl["kind"] == "carrot":
            size = hw * 0.55   # its leaves first, then most of it out of the ground
            self._paint_carrot(p, cx, cy + size * 0.2 - size * 1.05 * out, size)
        else:
            bw = hw * 0.78
            bh = bw * 1.2
            rect = QRectF(cx - bw / 2, cy - bh * 0.78 * out + bh * 0.12, bw, bh)
            dizzy = hl["hit"]
            draw_bunny(p, rect, None, blink=1.0 if dizzy else 0.0, sad=0.7 if dizzy else 0.0,
                       angry=0.0 if dizzy else 0.5, smug=not dizzy and t > up * 0.6,
                       ears=30 if dizzy else 0)
            if dizzy:
                for k in range(3):
                    a = self.st * 7 + k * math.tau / 3
                    sparkle(p, cx + math.cos(a) * bw * 0.4, rect.top() + bh * 0.2
                            + math.sin(a) * bw * 0.1, 3.5, QColor("#ffcf40"))
        p.restore()

    @staticmethod
    def _paint_carrot(p: QPainter, cx: float, top: float, size: float):
        body = QPainterPath()
        body.moveTo(cx - size * 0.28, top + size * 0.25)
        body.quadTo(cx, top + size * 0.15, cx + size * 0.28, top + size * 0.25)
        body.lineTo(cx + size * 0.04, top + size * 1.3)
        body.quadTo(cx, top + size * 1.36, cx - size * 0.04, top + size * 1.3)
        body.closeSubpath()
        p.setPen(_ink_pen(max(1.2, size * 0.05)))
        for a in (-28, 0, 28):   # the leaves
            p.save()
            p.translate(cx, top + size * 0.22)
            p.rotate(a)
            p.setBrush(LEAF)
            p.drawEllipse(QRectF(-size * 0.07, -size * 0.38, size * 0.14, size * 0.38))
            p.restore()
        grad = QLinearGradient(cx - size * 0.3, 0, cx + size * 0.3, 0)
        grad.setColorAt(0, _mix(CARROT, QColor("white"), 0.3))
        grad.setColorAt(1, CARROT)
        p.setBrush(grad)
        p.drawPath(body)
        p.setPen(_ink_pen(max(1.0, size * 0.035)))
        for k in (0.5, 0.8):   # its rings
            y = top + size * (0.2 + k)
            half = size * 0.28 * (1.3 - k) * 0.85
            p.drawLine(QPointF(cx - half, y), QPointF(cx - half * 0.2, y + size * 0.02))

    def _paint_mallet(self, p: QPainter, g: dict):
        """Your mallet, where the mouse is: tipped forward on a swing, wobbling while
        it's stuck."""
        if not self.playing or self.mallet.x() < 0:
            return
        acc = QColor(theme.T["accent"])
        size = g["cell_h"] * 0.42
        k = min(1.0, self.whack_t / 0.12)
        tilt = -55 * math.sin(math.pi * k) if self.whack_t < 0.12 else 0
        if self.stuck > 0:
            tilt += 10 * math.sin(self.stuck * 40)
        p.save()
        p.translate(self.mallet.x() + size * 0.5, self.mallet.y() + size * 0.6)
        p.rotate(-20 + tilt)
        p.setPen(_ink_pen(max(1.4, size * 0.06)))
        p.setBrush(QColor("#c9935a"))   # the handle
        p.drawRoundedRect(QRectF(-size * 0.07, -size * 0.2, size * 0.14, size * 1.0),
                          size * 0.05, size * 0.05)
        head = QRectF(-size * 0.55, -size * 0.55, size * 1.1, size * 0.42)
        grad = QLinearGradient(0, head.top(), 0, head.bottom())
        grad.setColorAt(0, _mix(acc, QColor("white"), 0.35))
        grad.setColorAt(1, acc if self.stuck <= 0 else _mix(acc, QColor("grey"), 0.6))
        p.setBrush(grad)
        p.drawRoundedRect(head, size * 0.12, size * 0.12)
        p.restore()


GAMES: dict[str, type[Game]] = {"dodge": Dodgeball, "homerun": HomeRun, "whack": WhackABun}
