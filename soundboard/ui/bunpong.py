"""The Easter egg: poke Bun enough times (bunnywidget.py, `pong=True`) and he comes back
with a baseball bat and challenges you to Pong, in a card over the page he lives on.

He holds his bat up as his paddle on the left; yours is on the right and follows the
mouse (or the arrow keys). First to WIN_AT. Every hit speeds the ball up a little, and
Bun only moves so fast, so a long rally is how you beat him.

Nothing is kept: Esc, the close button or leaving the page (a tab switch hides it)
ends the game and Bun calms down again.
"""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QPainterPath, QPen, QShortcut
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from soundboard import theme
from soundboard.bunny import INK, H, W, draw_bunny, sparkle
from soundboard.i18n import _
from soundboard.ui import appstate

WIN_AT = 5
FPS = 60
SERVE_PAUSE = 0.9     # seconds between a point and the next serve
SPEED0 = 0.55         # serve speed, court widths a second
SPEEDUP, SPEED_MAX = 1.07, 1.35
BUN_SPEED = 0.95      # how fast Bun can move, court heights a second
MAX_ANGLE = 55        # degrees off straight, hitting the very end of a paddle
BALL = QColor("#d8f25e")
BUBBLE = QColor("#fffaf0")


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
        self.setMouseTracking(True)
        self.setMinimumSize(320, 220)
        self.setCursor(Qt.BlankCursor)
        self.on_over = None   # called when someone reaches WIN_AT
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
                "you_x": w - 22, "you_half": 0.1, "pad_w": 9}

    def bun_rect(self, g: dict) -> QRectF:
        s = g["s"]
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
        top, bottom = g["bun_half"], 1 - g["bun_half"]
        target = min(bottom, max(top, target))
        move = BUN_SPEED * dt
        self.bun_y += max(-move, min(move, target - self.bun_y))
        self.swing = max(0.0, self.swing - dt * 2.5)
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
            if abs(off) <= 1 + ry / g["bun_half"]:
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

    def _point(self, who: str):
        self.score[who] += 1
        self.server = "bun" if who == "you" else "you"   # served toward who lost it
        self.trail.clear()
        if self.score[who] >= WIN_AT:
            self._go("over")
            self._say(_("aww…") if who == "you" else _("who's the champ!"), 1e9)
            if self.on_over:
                self.on_over()
            return
        if who == "you":
            self._say(self.rng.choice((_("no way!"), _("lucky!"), _("hey!"))))
        else:
            self._say(self.rng.choice((_("ha!"), _("too slow!"), _("bonk!"))))
        self._go("point")

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
        court = QRectF(0.5, 0.5, w - 1, h - 1)
        p.setPen(QPen(QColor(theme.T["border"]), 1))
        p.setBrush(QColor(theme.T.get("inset", theme.T["bg"])))
        p.drawRoundedRect(court, 10, 10)
        line = QColor(theme.T["border"])
        dash = QPen(line, 2, Qt.CustomDashLine, Qt.RoundCap)
        dash.setDashPattern([2.5, 4])
        p.setPen(dash)
        if self.state != "over":
            p.drawLine(QPointF(w / 2, 10), QPointF(w / 2, h - 10))

        # the score: big and faint behind the play
        f = QFont(self.font())
        f.setPixelSize(round(h * 0.24))
        f.setBold(True)
        p.setFont(f)
        faint = QColor(theme.T["text_hi"])
        faint.setAlphaF(0.12)
        p.setPen(faint)
        if self.state != "over":
            nw = w * 0.16   # each side's number, just off the net
            top = QRectF(w / 2 - nw - w * 0.03, h * 0.06, nw, h * 0.28)
            p.drawText(top, Qt.AlignCenter, str(self.score["bun"]))
            p.drawText(top.translated(nw + w * 0.06, 0), Qt.AlignCenter,
                       str(self.score["you"]))
            f.setPixelSize(max(10, round(h * 0.045)))
            f.setBold(False)
            p.setFont(f)
            p.setPen(QColor(theme.T["muted"]))
            under = QRectF(top.left(), top.bottom() - 4, nw, h * 0.07)
            p.drawText(under, Qt.AlignCenter, _("Bun"))
            p.drawText(under.translated(nw + w * 0.06, 0), Qt.AlignCenter, _("You"))

        # Bun with his bat up as a paddle (or not, at the end)
        over = self.state == "over"
        lost = over and self.winner == "you"
        won = over and self.winner == "bun"
        br = self.bun_rect(g)
        if won:
            br.translate(0, -6 * abs(math.sin(t * 3.4)))
            for i, col in enumerate(("#ffcf40", "#ff8fae", "#1fb6ff", "#a48bff")):
                a = t * 0.9 + i * math.pi / 2
                sparkle(p, br.center().x() + math.cos(a) * br.width() * 0.7,
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
        glow = QColor(acc)
        glow.setAlphaF(0.22 if not over else 0.0)
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawRoundedRect(QRectF(px - 4, py - 4, g["pad_w"] + 8, ph + 8), 8, 8)
        p.setBrush(acc)
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
        if self.state in ("play", "ready"):
            p.setPen(Qt.NoPen)
            for i, (tx, ty) in enumerate(self.trail[:-1]):
                c = QColor(BALL)
                c.setAlphaF(0.05 + 0.25 * i / len(self.trail))
                p.setBrush(c)
                rr = r * (0.5 + 0.5 * i / len(self.trail))
                p.drawEllipse(QPointF(tx * w, ty * h), rr, rr)
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


class _EndCard(QWidget):
    """The end-of-game panel over the court: a raised card with a soft shadow."""

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(6, 4, -6, -8)
        p.setPen(Qt.NoPen)
        for i in range(4):
            p.setBrush(QColor(0, 0, 0, 22))
            p.drawRoundedRect(r.adjusted(-i, -i + 3, i, i + 3), 12 + i, 12 + i)
        p.setPen(QPen(QColor(theme.T["border"]), 1))
        p.setBrush(QColor(theme.T["card"]))
        p.drawRoundedRect(r, 12, 12)
        p.end()


def _host_page(w: QWidget) -> QWidget:
    """The page `w` sits on: the child of the nearest stacked widget (a tab's page),
    else its window."""
    while w.parentWidget() is not None:
        if isinstance(w.parentWidget(), QStackedWidget):
            return w
        w = w.parentWidget()
    return w


def open_for(bun) -> BunPong:
    """Open the game over the page Bun is on (one at a time per page)."""
    page = _host_page(bun)
    for old in page.findChildren(BunPong):
        old.finish()
    game = BunPong(page, bun)
    game.show()
    game.raise_()
    game.setFocus(Qt.OtherFocusReason)
    return game


class BunPong(QWidget):
    """The page dimmed, and on it a card with the game: a heading, the court, and (at
    the end) who won with a Play again button. Real widgets for everything but the
    court, so it looks like the rest of the app."""

    def __init__(self, page: QWidget, bun=None, rng: random.Random | None = None):
        super().__init__(page)
        self.page, self.bun = page, bun
        self.setFocusPolicy(Qt.StrongFocus)
        self.setGeometry(page.rect())
        page.installEventFilter(self)
        QShortcut(QKeySequence(Qt.Key_Escape), self, self.finish,
                  context=Qt.WidgetWithChildrenShortcut)
        self._done = False
        self._fade = 0.0

        self.card = QFrame(self)
        self.card.setObjectName("card")
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(18, 14, 14, 16)
        lay.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(8)
        words = QVBoxLayout()
        words.setSpacing(2)
        title = QLabel(_("Pong with Bun"))
        title.setObjectName("section")
        title.setProperty("head", True)
        hint = QLabel(_("First to {n}. Move with the mouse or the arrow keys.", n=WIN_AT))
        hint.setObjectName("hint")
        words.addWidget(title)
        words.addWidget(hint)
        head.addLayout(words, 1)
        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("iconbutton")
        self.close_btn.setToolTip(_("Close (Esc)"))
        self.close_btn.setFocusPolicy(Qt.NoFocus)
        self.close_btn.clicked.connect(self.finish)
        head.addWidget(self.close_btn, 0, Qt.AlignTop)
        lay.addLayout(head)
        self.court = Court(rng, self.card)
        self.court.on_over = self._show_end
        lay.addWidget(self.court, 1)

        # the end: who won, and Play again (over the right of the court)
        self.end = _EndCard(self.court)
        el = QVBoxLayout(self.end)
        el.setContentsMargins(28, 22, 28, 20)
        el.setSpacing(4)
        self.end_title = QLabel()
        self.end_title.setStyleSheet("font-size:17pt; font-weight:700;")
        self.end_title.setAlignment(Qt.AlignCenter)
        self.end_score = QLabel()
        self.end_score.setObjectName("hint")
        self.end_score.setAlignment(Qt.AlignCenter)
        self.again = QPushButton(_("Play again"))
        self.again.setObjectName("primary")
        self.again.setCursor(Qt.PointingHandCursor)
        self.again.clicked.connect(self.play_again)
        leave = QLabel(_("Esc to leave"))
        leave.setObjectName("hint")
        leave.setAlignment(Qt.AlignCenter)
        el.addWidget(self.end_title)
        el.addWidget(self.end_score)
        el.addSpacing(12)
        el.addWidget(self.again, 0, Qt.AlignHCenter)
        el.addSpacing(2)
        el.addWidget(leave)
        self.end.setCursor(Qt.ArrowCursor)
        self.end.hide()

        self._t0 = self._last = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(1000 // FPS)
        self._timer.timeout.connect(self._tick)
        appstate.pause_in_background(self, self._resume, self._timer.stop)
        self._place()

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

    def play_again(self):
        self.end.hide()
        self.court.reset()
        self.setFocus()

    def finish(self):
        """End the game: nothing is kept, and Bun calms down."""
        if self._done:
            return
        self._done = True
        self._timer.stop()
        self.page.removeEventFilter(self)
        if self.bun is not None:
            try:
                self.bun.calm_down()
            except RuntimeError:   # Bun's widget is already gone
                pass
        self.hide()
        self.deleteLater()

    def step(self, dt: float):
        """Move everything on by `dt` seconds (the timer's tick; tests call it too)."""
        self._fade = min(1.0, self._fade + dt / 0.18)
        self.court.step(dt)

    # ------------------------------------------------------------------ timing
    def _tick(self):
        now = time.monotonic()
        dt = min(0.05, now - self._last)
        self._last = now
        self.step(dt)
        self.update()
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

    # ------------------------------------------------------------------ layout
    def _place(self):
        w, h = self.width(), self.height()
        cw, ch = min(600, w - 32), min(420, h - 32)
        self.card.setGeometry(round((w - cw) / 2), round((h - ch) / 2), cw, ch)
        self._place_end()

    def _place_end(self):
        c = self.court
        sz = self.end.sizeHint()
        sz.setWidth(max(sz.width(), 220))
        self.end.setGeometry(round(c.width() * 0.66 - sz.width() / 2),
                             round((c.height() - sz.height()) / 2), sz.width(), sz.height())

    def resizeEvent(self, ev):
        self._place()
        super().resizeEvent(ev)

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:
        if obj is self.page:
            if ev.type() == QEvent.Resize:
                self.setGeometry(self.page.rect())
            elif ev.type() == QEvent.Hide:   # left the tab: the game's over
                self.finish()
        return False

    def keyPressEvent(self, ev):
        k = ev.key()
        if k == Qt.Key_Escape:
            self.finish()
        elif k in (Qt.Key_Up, Qt.Key_W):
            self.court.nudge(-0.08)
        elif k in (Qt.Key_Down, Qt.Key_S):
            self.court.nudge(0.08)
        elif k in (Qt.Key_Space, Qt.Key_Return) and self.court.state == "ready":
            self.court.serve("bun")
        else:
            super().keyPressEvent(ev)

    def mousePressEvent(self, ev):
        self.setFocus()   # (a click on the dimmed page outside the card: nothing else)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(8, 6, 16, round(150 * self._fade)))
        # a soft shadow under the card
        r = QRectF(self.card.geometry())
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        for i in range(6):
            p.setBrush(QColor(0, 0, 0, round(14 * self._fade)))
            p.drawRoundedRect(r.adjusted(-i * 2, -i * 2 + 4, i * 2, i * 2 + 4), 12 + i * 2,
                              12 + i * 2)
        p.end()
