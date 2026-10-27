"""What Bun's games (ui/bun/bunpong.py) share: the court's colours and timings, the paper grain,
sparks and speech bubbles, and `Game`, the base every game builds on (state, score, Bun's end,
keys, painting the arena and the scores). `bunpong` re-exports it all."""
from __future__ import annotations

import math
import random
import time
from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from soundboard.core import achievements, usage
from soundboard.i18n import _
from soundboard.ui.bun.bunny import H, INK, W, draw_bunny, sparkle
from soundboard.ui.kit import theme
from soundboard.ui.kit.pixels import snap_to_pixels


TITLE_CSS = "font-size:17pt; font-weight:800;"   # as the guides' titles (wizardkit.py)
BODY_CSS = "font-size:11pt;"

WIN_AT = 5
FPS = 60
SERVE_PAUSE = 0.9     # seconds between a point and the next serve
SPEED0 = 0.55         # serve speed, court widths a second
SPEEDUP, SPEED_MAX = 1.07, 1.35
BUN_SPEED = 0.95      # how fast Bun can move, court heights a second
MAX_ANGLE = 55        # degrees off straight, hitting the very end of a paddle
KEY_SPEED = (1.1, 2.0)   # your paddle on held keys, court heights a second: at first, then
KEY_RAMP = 0.22          # after holding this many seconds
KEY_TAP = 0.035          # a single tap's nudge, of the court height
KEY_DIRS = {Qt.Key.Key_Up: -1, Qt.Key.Key_W: -1, Qt.Key.Key_Down: 1, Qt.Key.Key_S: 1}
GO_KEYS = (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter)
BALL = QColor("#d8f25e")
BUN_PINK = QColor("#ff8fae")   # his end of the court
CONFETTI = ("#ffcf40", "#ff8fae", "#1fb6ff", "#13ce66", "#a48bff")
RALLY_SHOWN = 3   # from this many hits in a row the rally counter shows
MILESTONE = 5     # every this many hits in a row a chime plays
EDGE = 0.8        # a hit this far out on your paddle (0 middle, 1 tip) is a close call
BUBBLE = QColor("#fffaf0")
SOUND_SID = "__pong__"   # the game's sounds in the engine (engine.FIXED_SIDS)


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
        img = QImage(96, 96, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
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
    p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)


class Game(QWidget):
    """What every game with Bun shares: the court bed, Bun on the left with his quips,
    the score, sparks and confetti, the sounds, and first to `win_at` ending it.

    A game sets `state` ("ready" before it starts, "over" at the end, anything else
    while playing), moves itself on in `step`, takes keys in `key` / `key_up`, and
    paints its own part in `paint_game`."""

    win_at = WIN_AT
    net = False   # the court's middle line and circle (Pong's)
    ach = ""      # its name for the achievements that count it ("rps", "ttt")

    def __init__(self, rng: random.Random | None = None, parent=None):
        super().__init__(parent)
        self.rng = rng or random.Random()
        self.fx = random.Random()   # sparks and shakes: never moves the game's own dice
        self.setMouseTracking(True)
        self.setMinimumSize(320, 220)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.on_over: Callable[[], None] | None = None   # called when someone reaches win_at
        # plays one of pongsounds.NAMES: sound(name, **pongsounds.render's options)
        self.sound: Callable[..., None] | None = None
        self.end_bun_left = 0.0   # where Bun stands at the end (the dialog centres him)
        self.reset()

    @staticmethod
    def title() -> str:
        raise NotImplementedError

    def how(self) -> str:
        """The line under the title: how to play."""
        raise NotImplementedError

    # ------------------------------------------------------------------ state
    def reset(self):
        self.score = {"you": 0, "bun": 0}
        self.state = "ready"
        self.st = 0.0              # seconds in this state
        self.say, self.say_until = "", 0.0
        self.swing = 0.0           # Bun's bat, 0 at rest, up to ~0.4 on a hit
        self.sparks: list[_Spark] = []     # hit sparks and confetti, px
        self.goal_flash: list | None = None   # [side "bun" / "you", age]: a point lost
        self.pop = {"you": 9.0, "bun": 9.0}   # seconds since each side scored
        self.shake = 0.0                   # seconds of court shake left

    @property
    def playing(self) -> bool:
        return self.state not in ("ready", "over")

    def _go(self, state: str):
        self.state, self.st = state, 0.0

    def _play(self, name: str, **kw):
        if self.sound is not None:
            self.sound(name, **kw)

    def _say(self, text: str, secs: float = 1.2):
        self.say, self.say_until = text, time.monotonic() + secs

    def _point(self, who: str, quip: bool = True) -> bool:
        """`who` ("you" / "bun") scores. True if that ends the game."""
        self.score[who] += 1
        achievements.game_point(self.ach, who)
        self.pop[who] = 0.0
        self.goal_flash = ["bun" if who == "you" else "you", 0.0]
        self.shake = 0.28
        if self.score[who] >= self.win_at:
            usage.used("egg-pong-won" if who == "you" else "egg-pong-lost")
            if who == "you":
                achievements.game_won(self.ach)
                self._confetti()
            self._play("win" if who == "you" else "lose")
            self._go("over")
            self._say(_("aww…") if who == "you" else _("who's the champ!"), 1e9)
            if self.on_over:
                self.on_over()
            return True
        self._play("score_you" if who == "you" else "score_bun")
        QTimer.singleShot(180, self, lambda: self._play("score_pop"))
        if not quip:
            pass
        elif who == "you":
            self._say(self.fx.choice((_("no way!"), _("lucky!"), _("hey!"))))
        else:
            self._say(self.fx.choice((_("ha!"), _("too slow!"), _("bonk!"))))
        return False

    def _confetti(self):
        w = max(1, self.width())
        for _i in range(70):
            self.sparks.append(_Spark(self.fx.uniform(0, w), self.fx.uniform(-60, -4),
                                      self.fx.uniform(-40, 40), self.fx.uniform(20, 120),
                                      self.fx.uniform(1.6, 2.6),
                                      self.fx.choice(CONFETTI), self.fx.uniform(3, 5),
                                      spin=self.fx.uniform(4, 10)))

    def _burst(self, x: float, y: float, col: QColor, n: int = 14, power: float = 1.0):
        """Sparks flying out all round (x, y), px."""
        for _i in range(n):
            a = self.fx.uniform(0, math.tau)
            v = self.fx.uniform(70, 200) * power
            self.sparks.append(_Spark(x, y, math.cos(a) * v, math.sin(a) * v,
                                      self.fx.uniform(0.25, 0.5),
                                      col if self.fx.random() < 0.6 else BALL,
                                      self.fx.uniform(1.4, 2.6)))

    @property
    def winner(self) -> str | None:
        if self.state != "over":
            return None
        return "you" if self.score["you"] >= self.win_at else "bun"

    # ------------------------------------------------------------------ geometry
    def geo(self) -> dict:
        """Pixel sizes for the current widget size."""
        w, h = max(1, self.width()), max(1, self.height())
        bh = h * 0.42                       # Bun's height
        s = bh / H
        return {"w": w, "h": h, "bh": bh, "s": s, "bun_x": 86 * s + 6,
                # the games' own space, right of Bun
                "x0": W * s + 26, "x1": w - 16}

    def bun_rect(self, g: dict) -> QRectF:
        s = g["s"]
        if self.state == "over":   # beside the result, both centred on the court
            return QRectF(self.end_bun_left, (g["h"] - g["bh"]) / 2, W * s, g["bh"])
        return QRectF(14, (g["h"] - g["bh"]) / 2 + g["h"] * 0.08, W * s, g["bh"])

    # ------------------------------------------------------------------ simulation
    def step(self, dt: float):
        self.st += dt
        self.swing = max(0.0, self.swing - dt * 2.5)
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

    # ------------------------------------------------------------------ input
    def key(self, k) -> bool:
        """A key went down. True if the game used it."""
        return False

    def key_up(self, k) -> bool:
        """A key came up. True if the game used it."""
        return False

    def press(self, ev, down: bool) -> bool:
        """A key event (from the court or the dialog round it). True if used."""
        k = ev.key()
        if ev.isAutoRepeat():   # held keys are tracked from press to release
            return k in KEY_DIRS or k in GO_KEYS
        return self.key(k) if down else self.key_up(k)

    def keyPressEvent(self, ev):
        if not self.press(ev, True):
            super().keyPressEvent(ev)

    def keyReleaseEvent(self, ev):
        if not self.press(ev, False):
            super().keyReleaseEvent(ev)

    # ------------------------------------------------------------------ paint
    def paintEvent(self, ev):
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = self.geo()
        w, h = g["w"], g["h"]
        t = time.monotonic()
        over = self.state == "over"
        if self.shake > 0:   # a little jolt when a point goes in
            k = self.shake / 0.28
            p.translate(self.fx.uniform(-3, 3) * k, self.fx.uniform(-2, 2) * k)
        self._paint_arena(p, w, h, over)
        if not over:
            self._paint_scores(p, w, h)
            self.paint_back(p, g)
        br = self._paint_bun(p, g, t)
        self._paint_sparks(p)
        if not over:
            self.paint_game(p, g)
        if self.say and time.monotonic() < self.say_until:
            _bubble(p, self.say, br.center().x() + br.width() * 0.15,
                    br.top() + br.height() * 0.1, max(10, round(g["bh"] * 0.12)))
        p.end()

    def paint_back(self, p: QPainter, g: dict):
        """The game's part under Bun."""

    def paint_game(self, p: QPainter, g: dict):
        """The game's part over Bun (not at the end)."""

    def bun_pose(self) -> dict:
        """How Bun stands now: draw_bunny's keywords."""
        lost = self.winner == "you"
        won = self.winner == "bun"
        return {"prop": "star" if won else None if lost else "bat", "swing": self.swing,
                "sad": 0.9 if lost else 0.0, "angry": 0.0 if self.state == "over" else 0.6,
                "ears": 30 if lost else -4}

    def _paint_bun(self, p: QPainter, g: dict, t: float) -> QRectF:
        br = self.bun_rect(g)
        if self.winner == "bun":
            br.translate(0, -6 * abs(math.sin(t * 3.4)))
            for i, col in enumerate(("#ffcf40", "#ff8fae", "#1fb6ff", "#a48bff")):
                a = t * 0.9 + i * math.pi / 2
                sparkle(p, br.center().x() + math.cos(a) * br.width() * 0.52,
                        br.center().y() + math.sin(a) * br.height() * 0.45,
                        3 + 3 * abs(math.sin(t * 4 + i)), QColor(col))
        blink = 1.0 if (t % 3.7) < 0.12 else 0.0
        pose = self.bun_pose()
        draw_bunny(p, br, pose.pop("prop"), blink=blink, **pose)
        return br

    def score_boxes(self, w: float, h: float) -> tuple[QRectF, QRectF]:
        """Where Bun's and your numbers go: over Bun, top left (Pong puts them by the
        net)."""
        nw = h * 0.16
        bun = QRectF(18, h * 0.04, nw, h * 0.18)
        return bun, bun.translated(nw + h * 0.04, 0)

    def _paint_scores(self, p: QPainter, w: float, h: float):
        """The score: big and faint behind the play, popping when it goes up."""
        f = QFont(self.font())
        boxes = self.score_boxes(w, h)
        for side, box in zip(("bun", "you"), boxes):
            k = self.pop[side]
            bump = 1 + 0.35 * max(0.0, 1 - k / 0.35) ** 2
            col = QColor(theme.T["text_hi"])
            col.setAlphaF(0.12 + 0.5 * max(0.0, 1 - k / 0.6))
            f.setPixelSize(round(box.height() * 0.86 * bump))
            f.setBold(True)
            p.setFont(f)
            p.setPen(col)
            p.drawText(box.adjusted(-30, -30, 30, 30), Qt.AlignmentFlag.AlignCenter,
                       str(self.score[side]))
        f.setPixelSize(max(10, round(h * 0.045)))
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor(theme.T["muted"]))
        for name, box in zip((_("Bun"), _("You")), boxes):
            under = QRectF(box.left() - 20, box.bottom() - 4, box.width() + 40, h * 0.07)
            p.drawText(under, Qt.AlignmentFlag.AlignCenter, name)

    def _paint_sparks(self, p: QPainter):
        for sp in self.sparks:
            k = sp.age / sp.life
            p.setPen(Qt.PenStyle.NoPen)
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

    def _prompt(self, p: QPainter, text: str, rect: QRectF, px: float, col: QColor | None = None):
        f = QFont(self.font())
        f.setPixelSize(max(11, round(px)))
        f.setBold(True)
        p.setFont(f)
        p.setPen(col or QColor(theme.T["text_hi"]))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_arena(self, p: QPainter, w: float, h: float, over: bool):
        """The court bed: sunk into the card, lit from the middle with the theme colour,
        each end tinted for its player, with lines (and Pong's glowing net). All from
        the theme's own colours, so it fits every theme."""
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
        if self.goal_flash is not None:   # a point just went in against this side
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
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(line, 1.5))
            p.drawRoundedRect(court.adjusted(12, 12, -12, -12), 6, 6)
            if self.net:
                rr = h * 0.17
                p.drawEllipse(QPointF(w / 2, h / 2), rr, rr)
                p.setPen(QPen(_alpha(acc, 0.10), 7, Qt.PenStyle.SolidLine,
                              Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(w / 2, 12), QPointF(w / 2, h - 12))   # the net's glow
                dash = QPen(_alpha(hi, 0.35), 2, Qt.PenStyle.CustomDashLine,
                            Qt.PenCapStyle.RoundCap)
                dash.setDashPattern([2.5, 4])
                p.setPen(dash)
                p.drawLine(QPointF(w / 2, 12), QPointF(w / 2, h - 12))
        p.restore()
        # the lip: shade along the top edge, a catch of light along the bottom
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_alpha(hi, 0.08 if not light else 0.0), 1))
        p.drawRoundedRect(court.adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
