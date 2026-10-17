"""The small games Bun picks besides Pong (bunpong.py has Pong, the shared `Game` and
the dialog): quick draw, rock paper scissors and tic-tac-toe. Each is a quick 1v1 on
the same court, Bun on the left, first to `win_at`, mouse or keys."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient

from soundboard import theme
from soundboard.bunny import INK
from soundboard.i18n import _
from soundboard.ui.bunpong import BUN_PINK, GO_KEYS, Game, _alpha, _mix

NUM_KEYS = {getattr(Qt.Key, f"Key_{i}"): i - 1 for i in range(1, 10)}
LEFT = (Qt.Key.Key_Left, Qt.Key.Key_A)
RIGHT = (Qt.Key.Key_Right, Qt.Key.Key_D)
UP = (Qt.Key.Key_Up, Qt.Key.Key_W)
DOWN = (Qt.Key.Key_Down, Qt.Key.Key_S)
ROUND_PAUSE = 1.3   # seconds a round's result shows before the next one
BUN_PAN, YOU_PAN = -0.6, 0.6   # where each side's sounds come from
BEAT = 0.25         # rock... paper... scissors...: seconds between the beats


def _ink_pen(width: float) -> QPen:
    pen = QPen(INK, width)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    return pen


class QuickDraw(Game):
    """Wait for GO, then click (or Space) before Bun does. Too early is his point."""

    @staticmethod
    def title() -> str:
        return _("Quick draw with Bun")

    def how(self) -> str:
        return _("First to {n} wins. When it says GO, click or press Space before Bun "
                 "does. Too early and the point is his.", n=self.win_at)

    def reset(self):
        super().reset()
        self.wait = 0.0        # seconds of "wait for it" this round
        self.bun_t = 0.0       # how long Bun takes to react this round
        self.shown: tuple[str, int] | None = None   # (who, ms): the round's winning time
        self.early = False
        self.beats = 0

    def start_round(self):
        self.wait = self.rng.uniform(1.0, 3.2)
        # mostly sharp, now and then dozy
        self.bun_t = (self.rng.uniform(0.27, 0.42) if self.rng.random() > 0.22
                      else self.rng.uniform(0.45, 0.7))
        self.shown, self.early = None, False
        self.beats = 0         # heartbeats so far this wait
        self._go("wait")
        self._play("serve")

    def fire(self):
        """Your click / Space."""
        cx, cy, _r = self._target(self.geo())
        if self.state == "ready":
            self.start_round()
        elif self.state == "wait":
            self.early = True
            self._say(_("too early!"))
            self._play("early")
            if not self._point("bun", quip=False):
                self._go("point")
        elif self.state == "go":
            self.shown = ("you", round(self.st * 1000))
            self._play("bang", pan=YOU_PAN)
            self._burst(cx, cy, QColor(theme.T["accent"]), 20, 1.4)
            if not self._point("you"):
                self._go("point")

    def step(self, dt: float):
        super().step(dt)
        if self.state == "wait" and self.st >= self.wait:
            self._go("go")
            self._play("go")
        elif self.state == "wait" and self.st >= self._beat_at(self.beats):
            self._play("heartbeat", level=self.beats)   # quicker the longer it drags
            self.beats += 1
        elif self.state == "go" and self.st >= self.bun_t:
            self.shown = ("bun", round(self.bun_t * 1000))
            self.swing = 0.45
            self._play("bang", pan=BUN_PAN)
            cx, cy, _r = self._target(self.geo())
            self._burst(cx, cy, BUN_PINK, 20, 1.4)
            if not self._point("bun"):
                self._go("point")
        elif self.state == "point" and self.st >= ROUND_PAUSE:
            self.start_round()

    @staticmethod
    def _beat_at(i: int) -> float:
        """When heartbeat i comes in the wait: from every 0.62 s down to 0.4 s."""
        return 0.15 + sum(max(0.4, 0.62 - 0.04 * j) for j in range(i))

    def key(self, k) -> bool:
        if k in GO_KEYS:
            self.fire()
            return True
        return False

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.fire()

    def bun_pose(self) -> dict:
        pose = super().bun_pose()
        if self.state == "go":   # eyes wide, bat ready
            pose["angry"] = 0.9
            pose["ears"] = -10
        return pose

    @staticmethod
    def _target(g: dict) -> tuple[float, float, float]:
        cx = (g["x0"] + g["x1"]) / 2
        r = min(g["h"] * 0.25, (g["x1"] - g["x0"]) * 0.3)
        return cx, g["h"] * 0.54, r

    def paint_game(self, p: QPainter, g: dict):
        cx, cy, r = self._target(g)
        h = g["h"]
        acc = QColor(theme.T["accent"])
        hi = QColor(theme.T["text_hi"])
        box = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        if self.state == "go":
            k = min(1.0, self.st / 0.12)
            rr = r * (0.85 + 0.15 * k + 0.06 * max(0.0, 1 - self.st / 0.25))
            glow = QRadialGradient(QPointF(cx, cy), rr * 1.6)
            glow.setColorAt(0, _alpha(acc, 0.55))
            glow.setColorAt(1, _alpha(acc, 0.0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QPointF(cx, cy), rr * 1.6, rr * 1.6)
            fill = QLinearGradient(0, cy - rr, 0, cy + rr)
            fill.setColorAt(0, _mix(acc, QColor("white"), 0.25))
            fill.setColorAt(1, acc)
            p.setBrush(fill)
            p.drawEllipse(QPointF(cx, cy), rr, rr)
            self._prompt(p, _("GO!"), box, r * 0.5, QColor(theme.T.get("on_accent", "#ffffff")))
            return
        # the target at rest: a ring, breathing while you wait
        breathe = 0.5 + 0.5 * math.sin(self.st * 5) if self.state == "wait" else 0.0
        ring = BUN_PINK if self.early else acc
        p.setBrush(_alpha(ring, 0.06 + 0.05 * breathe))
        p.setPen(QPen(_alpha(ring, 0.35 + 0.25 * breathe), 3))
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_alpha(hi, 0.10), 1.5))
        p.drawEllipse(QPointF(cx, cy), r * 0.62, r * 0.62)
        if self.state == "ready":
            self._prompt(p, _("Click to start"), box, h * 0.055)
        elif self.state == "wait":
            self._prompt(p, _("Wait for it…"), box, h * 0.05, QColor(theme.T["muted"]))
        elif self.state == "point" and self.shown is not None:
            who, ms = self.shown
            self._prompt(p, _("{ms} ms", ms=ms), box, r * 0.32,
                         acc if who == "you" else BUN_PINK)


CHOICES = ("rock", "paper", "scissors")
BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}


def _draw_hand(p: QPainter, kind: str, cx: float, cy: float, size: float, tint: QColor):
    """Rock, paper or scissors, drawn `size` px across round (cx, cy)."""
    s = size / 100
    p.save()
    p.translate(cx, cy)
    p.scale(s, s)
    ink = _ink_pen(3.2)
    if kind == "rock":
        path = QPainterPath()
        pts = [(-40, 8), (-30, -24), (0, -36), (30, -26), (42, 6), (26, 32), (-14, 36), (-38, 26)]
        path.moveTo(*pts[0])
        for i in range(len(pts)):   # rounded corners: through each edge's middle
            a, b = pts[i], pts[(i + 1) % len(pts)]
            path.quadTo(a[0], a[1], (a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        path.closeSubpath()
        fill = QLinearGradient(0, -36, 0, 36)
        fill.setColorAt(0, QColor("#b9bec6"))
        fill.setColorAt(1, QColor("#767c86"))
        p.setPen(ink)
        p.setBrush(fill)
        p.drawPath(path)
        p.setPen(_ink_pen(2.2))
        p.drawPolyline([QPointF(-12, -20), QPointF(-4, -8), QPointF(-10, 4)])
        p.drawLine(QPointF(14, 10), QPointF(24, 18))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 90))
        p.drawEllipse(QPointF(-18, -16), 7, 4)
    elif kind == "paper":
        p.rotate(-7)
        sheet = QPainterPath()
        sheet.moveTo(-30, -40)
        sheet.lineTo(16, -40)
        sheet.lineTo(32, -24)
        sheet.lineTo(32, 40)
        sheet.lineTo(-30, 40)
        sheet.closeSubpath()
        p.setPen(ink)
        p.setBrush(QColor("#fdfbf5"))
        p.drawPath(sheet)
        fold = QPainterPath()
        fold.moveTo(16, -40)
        fold.lineTo(16, -24)
        fold.lineTo(32, -24)
        p.setBrush(QColor("#e4ded0"))
        p.drawPath(fold)
        p.setPen(QPen(_alpha(tint, 0.85), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for y in (-12, 2, 16, 28):
            p.drawLine(QPointF(-20, y), QPointF(22 if y > -12 else 8, y))
    else:   # scissors
        blade = QColor("#dfe3ea")
        p.setPen(ink)
        for side in (-1, 1):
            b = QPainterPath()
            b.moveTo(0, 6)
            b.lineTo(side * 34, -40)
            b.lineTo(side * 24, -42)
            b.lineTo(-side * 6, 2)
            b.closeSubpath()
            p.setBrush(blade)
            p.drawPath(b)
        p.setBrush(tint)
        for side in (-1, 1):
            p.drawEllipse(QPointF(side * 17, 26), 13, 15)
            p.drawLine(QPointF(side * 6, 14), QPointF(side * 2, 6))
        p.setBrush(QColor("#fdfbf5"))
        for side in (-1, 1):
            p.drawEllipse(QPointF(side * 17, 26), 6, 7.5)
        p.setBrush(INK)
        p.drawEllipse(QPointF(0, 6), 3, 3)
    p.restore()


class RockPaperScissors(Game):
    """Pick one of three tiles; Bun picks too; rock beats scissors beats paper beats
    rock. He has a habit: now and then he plays what beats your last pick."""

    win_at = 3

    @staticmethod
    def title() -> str:
        return _("Rock paper scissors with Bun")

    def how(self) -> str:
        return _("First to {n} wins. Pick rock, paper or scissors with a click, or the "
                 "keys 1, 2 and 3.", n=self.win_at)

    def reset(self):
        super().reset()
        self.state = "pick"    # pick, shake (rock... paper... scissors), point, over
        self.mine: str | None = None
        self.his: str | None = None
        self.last: str | None = None   # your pick last round
        self.hover: int | None = None
        self.sel = 1           # the keys' tile
        self.won: str | None = None    # who took this round ("you", "bun", None: a draw)
        self.beats = 0         # drum beats so far this shake

    def pick(self, i: int):
        if self.state != "pick":
            return
        self.mine = CHOICES[i]
        self.sel = i
        if self.last is not None and self.rng.random() < 0.35:
            self.his = next(c for c in CHOICES if BEATS[c] == self.last)
        else:
            self.his = self.rng.choice(CHOICES)
        self.last = self.mine
        self.won = None
        self._go("shake")
        self._play("shake", level=0)
        self.beats = 1

    def step(self, dt: float):
        super().step(dt)
        if self.state == "shake" and self.beats < 3 and self.st >= self.beats * BEAT:
            self._play("shake", level=self.beats)
            self.beats += 1
        if self.state == "shake" and self.st >= 3 * BEAT and self.mine:
            self._play("reveal")
            if self.mine == self.his:
                self._say(_("Draw!"))
                self._play("tie")
                self._go("point")
                return
            who = "you" if BEATS[self.mine] == self.his else "bun"
            self.won = who
            g = self.geo()
            x, y, _s = self._reveal(g, who)
            if who == "bun":
                self.swing = 0.45
            self._burst(x, y, QColor(theme.T["accent"]) if who == "you" else BUN_PINK, 18)
            if not self._point(who):
                self._go("point")
        elif self.state == "point" and self.st >= ROUND_PAUSE:
            self.mine = self.his = self.won = None
            self._go("pick")

    # ------------------------------------------------------------------ input
    def key(self, k) -> bool:
        if k in NUM_KEYS and NUM_KEYS[k] < 3:
            self.pick(NUM_KEYS[k])
        elif k in LEFT or k in RIGHT:
            sel = max(0, min(2, self.sel + (1 if k in RIGHT else -1)))
            if sel != self.sel and self.state == "pick":
                self._play("hover", pan=(sel - 1) * 0.4)
            self.sel = sel
        elif k in GO_KEYS:
            self.pick(self.sel)
        else:
            return False
        return True

    def _tile_at(self, pos) -> int | None:
        for i, r in enumerate(self.tiles(self.geo())):
            if r.contains(pos):
                return i
        return None

    def mouseMoveEvent(self, ev):
        hover = self._tile_at(ev.position())
        if hover is not None and hover != self.hover and self.state == "pick":
            self._play("hover", pan=(hover - 1) * 0.4)
        self.hover = hover
        self.setCursor(Qt.CursorShape.PointingHandCursor if self.hover is not None
                       and self.state == "pick" else Qt.CursorShape.ArrowCursor)

    def leaveEvent(self, ev):
        self.hover = None
        super().leaveEvent(ev)

    def mousePressEvent(self, ev):
        i = self._tile_at(ev.position())
        if ev.button() == Qt.MouseButton.LeftButton and i is not None:
            self.pick(i)

    # ------------------------------------------------------------------ paint
    def tiles(self, g: dict) -> list[QRectF]:
        aw = g["x1"] - g["x0"]
        size = min(aw / 3 - 16, g["h"] * 0.27)
        gap = size * 0.18
        left = g["x0"] + (aw - 3 * size - 2 * gap) / 2
        top = g["h"] - size - g["h"] * 0.07
        return [QRectF(left + i * (size + gap), top, size, size) for i in range(3)]

    @staticmethod
    def _reveal(g: dict, who: str) -> tuple[float, float, float]:
        """Where Bun's / your hand shows: centre and size."""
        aw = g["x1"] - g["x0"]
        x = g["x0"] + aw * (0.22 if who == "bun" else 0.78)
        return x, g["h"] * 0.33, g["h"] * 0.24

    def paint_game(self, p: QPainter, g: dict):
        acc = QColor(theme.T["accent"])
        hi = QColor(theme.T["text_hi"])
        h = g["h"]
        # the two hands: fists shaking, then the picks
        for who, kind in (("bun", self.his), ("you", self.mine)):
            x, y, size = self._reveal(g, who)
            col = acc if who == "you" else BUN_PINK
            if self.state == "shake":
                bob = abs(math.sin(self.st * math.pi * 4)) * h * 0.05
                _draw_hand(p, "rock", x, y - bob, size, col)
            elif self.state == "point" and kind:
                if self.won == who:
                    glow = QRadialGradient(QPointF(x, y), size * 0.9)
                    glow.setColorAt(0, _alpha(col, 0.45))
                    glow.setColorAt(1, _alpha(col, 0.0))
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(glow)
                    p.drawEllipse(QPointF(x, y), size * 0.9, size * 0.9)
                _draw_hand(p, kind, x, y, size * (1.1 if self.won == who else 0.95), col)
            else:   # waiting for your pick: an empty spot
                pen = QPen(_alpha(col, 0.35), 2, Qt.PenStyle.CustomDashLine)
                pen.setDashPattern([3, 3])
                p.setPen(pen)
                p.setBrush(_alpha(col, 0.05))
                p.drawEllipse(QPointF(x, y), size * 0.42, size * 0.42)
                self._prompt(p, "?", QRectF(x - size / 2, y - size / 2, size, size), size * 0.3,
                             _alpha(col, 0.5))
        # the three tiles
        for i, r in enumerate(self.tiles(g)):
            chosen = self.mine == CHOICES[i]
            live = self.state == "pick"
            lit = live and (self.hover == i or (self.hover is None and self.sel == i))
            dim = not live and not chosen
            p.setPen(QPen(_alpha(acc, 0.9) if lit or chosen else _alpha(hi, 0.14),
                          2.2 if lit or chosen else 1.2))
            p.setBrush(_alpha(acc, 0.16) if chosen else _alpha(hi, 0.07 if lit else 0.035))
            p.drawRoundedRect(r, 14, 14)
            p.setOpacity(0.35 if dim else 1.0)
            lift = -3 if lit else 0
            _draw_hand(p, CHOICES[i], r.center().x(), r.center().y() + lift, r.width() * 0.7, acc)
            p.setOpacity(1.0)
            self._prompt(p, str(i + 1), QRectF(r.left() + 6, r.top() + 4, 18, 18), h * 0.035,
                         _alpha(hi, 0.45 if not dim else 0.2))


LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6))


class TicTacToe(Game):
    """Three in a row on a 3 x 3 board: you're the rings, Bun the crosses. Who goes
    first swaps every round; a full board with no line is a draw (no point)."""

    win_at = 3

    @staticmethod
    def title() -> str:
        return _("Tic-tac-toe with Bun")

    def how(self) -> str:
        return _("Three in a row wins a round, first to {n} rounds wins. Click a square, "
                 "or use the arrow keys and Space.", n=self.win_at)

    def reset(self):
        super().reset()
        self.state = "play"    # play, point (a round's end), over
        self.board: list[str | None] = [None] * 9
        self.first = self.turn = "you"
        self.cur = 4           # the keys' square
        self.hover: int | None = None
        self.line: tuple[int, int, int] | None = None   # the winning row
        self.think = 0.0       # how long Bun has thought about his move

    def place(self, i: int):
        """Your mark on square i, if it's your turn and the square is free."""
        if self.state != "play" or self.turn != "you" or self.board[i] is not None:
            return
        self.board[i] = "you"
        self.cur = i
        # your marks climb the ladder through a round, from where they're put
        self._play("you", rally=self.board.count("you") - 1, pan=(i % 3 - 1) * 0.5)
        self._moved("you")

    def _moved(self, who: str):
        line = next((ln for ln in LINES if all(self.board[i] == who for i in ln)), None)
        if line:
            self.line = line
            cx, cy, _r = self._cell_centre(self.geo(), line[1])
            if who == "bun":
                self.swing = 0.45
            self._play("line", rally=3 if who == "you" else 0,
                       pan=YOU_PAN if who == "you" else BUN_PAN)
            self._burst(cx, cy, QColor(theme.T["accent"]) if who == "you" else BUN_PINK, 22)
            if not self._point(who):
                self._go("point")
        elif all(self.board):
            self._say(_("Draw!"))
            self._play("tie")
            self._go("point")
        else:
            self.turn = "bun" if who == "you" else "you"
            self.think = 0.0

    def _bun_move(self) -> int:
        """Win if he can, block you if he must, else the middle, a corner, anything.
        Now and then he just plays anywhere, so he can be beaten."""
        empty = [i for i, c in enumerate(self.board) if c is None]
        if self.rng.random() < 0.22:
            return self.rng.choice(empty)
        for who in ("bun", "you"):
            for i in empty:
                if any(i in ln and all(self.board[j] == who for j in ln if j != i)
                       for ln in LINES):
                    return i
        if 4 in empty:
            return 4
        corners = [i for i in (0, 2, 6, 8) if i in empty]
        return self.rng.choice(corners or empty)

    def step(self, dt: float):
        super().step(dt)
        if self.state == "play" and self.turn == "bun":
            self.think += dt
            if self.think >= 0.55:
                i = self._bun_move()
                self.board[i] = "bun"
                self.swing = 0.3
                self._play("bun", pan=(i % 3 - 1) * 0.5)
                self._moved("bun")
        elif self.state == "point" and self.st >= ROUND_PAUSE:
            self.board = [None] * 9
            self.line = None
            self.first = "bun" if self.first == "you" else "you"
            self.turn, self.think = self.first, 0.0
            self._go("play")

    # ------------------------------------------------------------------ input
    def key(self, k) -> bool:
        r, c = divmod(self.cur, 3)
        was = self.cur
        if k in NUM_KEYS:
            self.place(NUM_KEYS[k])
        elif k in LEFT:
            self.cur = r * 3 + max(0, c - 1)
        elif k in RIGHT:
            self.cur = r * 3 + min(2, c + 1)
        elif k in UP:
            self.cur = max(0, r - 1) * 3 + c
        elif k in DOWN:
            self.cur = min(2, r + 1) * 3 + c
        elif k in GO_KEYS:
            self.place(self.cur)
        else:
            return False
        self.hover = None   # the keys' square shows again
        if self.cur != was and self.state == "play":
            self._play("hover", pan=(self.cur % 3 - 1) * 0.5)
        return True

    def _cell_at(self, pos) -> int | None:
        left, top, cell = self.board_box(self.geo())
        c, r = int((pos.x() - left) // cell), int((pos.y() - top) // cell)
        return r * 3 + c if 0 <= c < 3 and 0 <= r < 3 else None

    def mouseMoveEvent(self, ev):
        hover = self._cell_at(ev.position())
        if (hover is not None and hover != self.hover and self.state == "play"
                and self.board[hover] is None):
            self._play("hover", pan=(hover % 3 - 1) * 0.5)
        self.hover = hover
        free = self.hover is not None and self.board[self.hover] is None
        self.setCursor(Qt.CursorShape.PointingHandCursor if free and self.turn == "you"
                       and self.state == "play" else Qt.CursorShape.ArrowCursor)

    def leaveEvent(self, ev):
        self.hover = None
        super().leaveEvent(ev)

    def mousePressEvent(self, ev):
        i = self._cell_at(ev.position())
        if ev.button() == Qt.MouseButton.LeftButton and i is not None:
            self.place(i)

    # ------------------------------------------------------------------ paint
    @staticmethod
    def board_box(g: dict) -> tuple[float, float, float]:
        """The board's left, top and one square's size, px."""
        aw = g["x1"] - g["x0"]
        size = min(aw * 0.8, g["h"] * 0.84)
        return g["x0"] + (aw - size) / 2, (g["h"] - size) / 2, size / 3

    def _cell_centre(self, g: dict, i: int) -> tuple[float, float, float]:
        left, top, cell = self.board_box(g)
        r, c = divmod(i, 3)
        return left + (c + 0.5) * cell, top + (r + 0.5) * cell, cell

    def paint_game(self, p: QPainter, g: dict):
        acc = QColor(theme.T["accent"])
        hi = QColor(theme.T["text_hi"])
        left, top, cell = self.board_box(g)
        size = cell * 3
        # whose turn: the squares you could pick light up under the pointer / keys
        mine = self.state == "play" and self.turn == "you"
        spot = self.hover if self.hover is not None else self.cur
        if mine and spot is not None and self.board[spot] is None:
            cx, cy, _c = self._cell_centre(g, spot)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_alpha(acc, 0.14))
            p.drawRoundedRect(QRectF(cx - cell / 2 + 6, cy - cell / 2 + 6, cell - 12, cell - 12),
                              10, 10)
        p.setPen(QPen(_alpha(hi, 0.22), max(2.0, cell * 0.035), Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        for i in (1, 2):
            p.drawLine(QPointF(left + i * cell, top + 8), QPointF(left + i * cell, top + size - 8))
            p.drawLine(QPointF(left + 8, top + i * cell), QPointF(left + size - 8, top + i * cell))
        pen_w = max(3.0, cell * 0.1)
        for i, who in enumerate(self.board):
            if who is None:
                continue
            cx, cy, _c = self._cell_centre(g, i)
            rr = cell * 0.28
            faded = self.line is not None and i not in self.line
            p.setOpacity(0.4 if faded else 1.0)
            p.setBrush(Qt.BrushStyle.NoBrush)
            if who == "you":
                p.setPen(QPen(acc, pen_w))
                p.drawEllipse(QPointF(cx, cy), rr, rr)
            else:
                p.setPen(QPen(BUN_PINK, pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(cx - rr, cy - rr), QPointF(cx + rr, cy + rr))
                p.drawLine(QPointF(cx + rr, cy - rr), QPointF(cx - rr, cy + rr))
            p.setOpacity(1.0)
        if self.line is not None:   # the winning row, struck through
            a = self._cell_centre(g, self.line[0])
            b = self._cell_centre(g, self.line[2])
            who = self.board[self.line[0]]
            col = acc if who == "you" else BUN_PINK
            k = min(1.0, self.st / 0.25) if self.state == "point" else 1.0
            p.setPen(QPen(_alpha(col, 0.35), pen_w * 2.2, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            end = QPointF(a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k)
            p.drawLine(QPointF(a[0], a[1]), end)
            p.setPen(QPen(_mix(col, QColor("white"), 0.3), pen_w * 0.8, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(a[0], a[1]), end)


GAMES: dict[str, type[Game]] = {"draw": QuickDraw, "rps": RockPaperScissors,
                                "ttt": TicTacToe}
