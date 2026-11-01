"""Bun the note-taker: Send feedback's picture, at the top left beside its heading.

He wears round glasses and holds a little notebook open towards himself, so you see its
cover, a pencil in his other paw. Each pick ticked (`write(LINE)`) and each letter typed
(`write(LETTER)`) has him write a bit more in it: the pencil scribbles along over the
top of the book, his eyes following it. When the picks are sent (`finish()`) he shuts the
book, bows to you, and a heart floats up out of him. Then he sits holding the shut book,
smiling.

The timer only runs while something moves (writing, shutting, the bow, the heart, a
blink) and the widget is on screen. In lite mode (ui/settings/lite.py) there's no timer
at all: a still picture, the book shut with the heart over him once sent.

Everything is drawn on Bun's own 100 x 120 canvas (soundboard/ui/bun/bunny.py's
draw_bunny), scaled into a box exactly his size (fit); the heart floats up in front of him.
"""
from __future__ import annotations

import math
import time

import numpy as np

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from soundboard.style import bunnyfit
from soundboard.ui.bun.bunny import INK, ROOM_SIDE, W, draw_bunny, look_colour, sparkle
from soundboard.ui.bun.bunshapes import _ellipse
from soundboard.ui.kit import theme
from soundboard.ui.kit.pixels import snap_to_pixels
from soundboard.ui.settings import lite

SCALE = 0.72                     # Bun's canvas to pixels
FPS = 30

LINE, LETTER = 1.0, 0.07         # how much a tick and a typed letter have him write (lines)
SPEED = 1.8                      # lines a second
BEHIND = 3.0                     # at most this much still to write: he never runs on long
CLOSE_S, BOW_S, HEART_S = 0.4, 1.1, 1.6   # the ending: shut the book, bow, the heart
HEART_AT = CLOSE_S + 0.45        # the heart pops out as he's bowed lowest
BLINK_EVERY, BLINK_S = 3.4, 0.13

# Spectacles the theme's outfit might have: his round glasses go on instead.
EYEWEAR = {"shades", "round_glasses", "heart_glasses", "glasses_3d", "pixel_shades",
           "visor", "spirals", "readers", "laser"}

BOOK = (50.0, 106.0)             # the book's middle (its spine) on his canvas
HALF_W, BOOK_H = 17.0, 23.0      # one cover's width, the book's height at the spine
TILT = 3.0                       # how much shorter the open covers' outer edges look
PAPER = QColor("#fffdf6")
LEATHER = QColor("#b06a3b")      # the cover: a book's own brown, not the theme's colour
HEART = QColor("#ff6f91")
LINE_X0, LINE_X1 = -12.0, 10.0   # where the pencil writes along over the book's top
REST_X = 9.0                    # the pencil while he isn't writing


def _ease(k: float) -> float:
    k = max(0.0, min(1.0, k))
    return k * k * (3 - 2 * k)


def outfit() -> tuple[str, ...]:
    """The theme's outfit, his round glasses in place of any spectacles."""
    return tuple(pc for pc in bunnyfit.outfit() if pc not in EYEWEAR) + ("round_glasses",)


_FITS: dict[tuple, QRectF] = {}
SEEN = 40   # how far (R + G + B) a pixel is from the background for it to show


def fit() -> QRectF:
    """The part of his canvas you can see him take up in this theme, on its background,
    edge to edge: past it for an upright ear or a wide collar, inside it for a floppy ear
    or plain Bun's headphones, and not a cape as dark as the background. His box is
    exactly this, so the room round him is the layout's alone and looks the same on
    every side. Measured once per look on a picture of him (2 px a canvas unit); his bow
    and heart stay inside it."""
    bg = QColor(theme.T["bg"])   # a dialog's (themesheet: QDialog)
    key = (bunnyfit.outfit(), tuple(sorted(bunnyfit.look().items(), key=str)), bg.name())
    if key not in _FITS:
        k, pad = 2, 2 * ROOM_SIDE   # (wider and taller than any outfit reaches)
        img = QImage(round((W + 2 * pad) * k), round((120 + 2 * pad) * k),
                     QImage.Format.Format_RGB32)
        img.fill(bg)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(k, k)
        p.translate(pad, pad)
        draw_bunny(p, QRectF(0, 0, W, 120), None, outfit=outfit(),
                   hold=((BOOK[0] - HALF_W - 1, BOOK[1] + 3),
                         (BOOK[0] + REST_X + 2, BOOK[1] - BOOK_H / 2 + 2.5)))
        p.end()
        w, h = img.width(), img.height()
        px = np.frombuffer(bytes(img.constBits()), np.uint8)
        px = px.reshape(h, img.bytesPerLine())[:, :4 * w].reshape(h, w, 4)[..., :3]
        far = np.abs(px.astype(np.int16) - (bg.blue(), bg.green(), bg.red())).sum(2)
        ys, xs = np.nonzero(far > SEEN)   # (BGRA bytes)
        _FITS[key] = QRectF(xs.min() / k - pad, ys.min() / k - pad,
                            (xs.max() + 1 - xs.min()) / k, (ys.max() + 1 - ys.min()) / k)
    return _FITS[key]


def heart_shape(p: QPainter, x: float, y: float, r: float, col: QColor, pen: float = 1.4):
    path = QPainterPath(QPointF(x, y + r * 0.9))
    path.cubicTo(QPointF(x - r * 1.6, y - r * 0.2), QPointF(x - r * 0.6, y - r * 1.4),
                 QPointF(x, y - r * 0.45))
    path.cubicTo(QPointF(x + r * 0.6, y - r * 1.4), QPointF(x + r * 1.6, y - r * 0.2),
                 QPointF(x, y + r * 0.9))
    p.setPen(QPen(INK, pen))
    p.setBrush(col)
    p.drawPath(path)


class NoteBunny(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.box = fit()
        self.setFixedSize(round(self.box.width() * SCALE), round(self.box.height() * SCALE))
        self.target = 0.0            # lines he's been given to write
        self.written = 0.0           # lines written so far
        self.sent = False
        self._sent_at = 0.0
        self._blink_at = time.monotonic() + BLINK_EVERY
        self._last = time.monotonic()
        self._pen_x = REST_X         # the pencil along the book's top: glides to its spot
        self._timer = QTimer(self)
        self._timer.setInterval(1000 // FPS)
        self._timer.timeout.connect(self._tick)
        self._rest = QTimer(self)    # sitting still: wakes him for the next blink
        self._rest.setSingleShot(True)
        self._rest.timeout.connect(self._run)

    def sizeHint(self) -> QSize:
        return self.size()

    # ------------------------------------------------------------------ state
    def write(self, amount: float = LINE):
        """Something was ticked or typed: write `amount` lines more."""
        if self.sent:
            return
        self.target = min(self.target + amount, self.written + BEHIND)
        if lite.on():   # (no timer: nothing to watch)
            self.written = self.target
            return
        self._run()

    def finish(self):
        """Sent: shut the book, bow, the heart."""
        if self.sent:
            return
        self.sent = True
        self._sent_at = time.monotonic()
        self.target = self.written   # puts the pencil down mid-line
        self._run()

    def writing(self) -> bool:
        return not self.sent and self.written < self.target - 1e-3

    def _age(self) -> float:
        return time.monotonic() - self._sent_at

    def _pen_goal(self) -> float:
        if not self.writing():
            return REST_X
        return LINE_X0 + (LINE_X1 - LINE_X0) * (self.written % 1.0)

    def _busy(self) -> bool:
        """Something moves this frame."""
        return (self.writing() or abs(self._pen_x - self._pen_goal()) > 0.05
                or (self.sent and self._age() < HEART_AT + HEART_S)
                or time.monotonic() >= self._blink_at)

    def _run(self):
        if lite.on():   # a still picture: no timer
            self._timer.stop()
            self._rest.stop()
            self.written = self.target
            self.update()
            return
        if not self.isVisible():
            self._timer.stop()
            self._rest.stop()
            return
        if self._busy():
            self._rest.stop()
            if not self._timer.isActive():
                self._last = time.monotonic()
                self._timer.start()
        else:
            self._timer.stop()
            wait = min(60.0, max(0.05, self._blink_at - time.monotonic()))
            self._rest.start(round(wait * 1000))
        self.update()

    def showEvent(self, ev):
        super().showEvent(ev)
        self._run()

    def hideEvent(self, ev):
        self._timer.stop()
        self._rest.stop()
        super().hideEvent(ev)

    def _tick(self):
        now = time.monotonic()
        dt, self._last = min(0.1, now - self._last), now
        if self.writing():
            self.written = min(self.target, self.written + SPEED * dt)
        goal = self._pen_goal()
        # along the line at once; back to the start of the next one or to rest, gliding
        follow = 1.0 if self.writing() and goal > self._pen_x else min(1.0, dt * 12)
        self._pen_x += (goal - self._pen_x) * follow
        if now >= self._blink_at + BLINK_S:
            self._blink_at = now + BLINK_EVERY
        if not self._busy():
            self._run()   # sits still: the timer stops till the next blink
            return
        if not self.window().isMinimized():
            self.update()

    # --------------------------------------------------------------- painting
    def paintEvent(self, _e):
        still = lite.on()
        now = time.monotonic()
        t = 0.0 if still else now
        age = HEART_AT + HEART_S * 0.35 if still else self._age()
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setClipRect(self.rect())
        p.scale(SCALE, SCALE)
        p.translate(-self.box.left(), -self.box.top())
        # his pose
        blink = 1.0 if not still and now >= self._blink_at else 0.0
        dip = ears = look = bow = 0.0
        shut = 0.0   # 0 open .. 1 shut
        if self.sent:
            shut = 1.0 if still else _ease(age / CLOSE_S)
            b = 0.0 if still else (age - CLOSE_S) / BOW_S
            if 0 < b < 1:
                bow = math.sin(math.pi * b) ** 1.3
                blink = max(blink, 1.0 if bow > 0.25 else 0.0)   # happy shut eyes
            dip = 9 * bow   # (ears as they are: fanned out they'd reach past his box)
        writing = self.writing()
        if writing:   # looking down over the book at the pencil
            dip = 2.0
        look = max(-1.0, min(1.0, self._pen_x / 16)) if not self.sent else 0.0
        bx, by = BOOK[0], BOOK[1] + 2.5 * bow
        half = HALF_W - HALF_W * 0.3 * shut          # each half, narrowing as it shuts
        top = by - BOOK_H / 2
        pen = QPointF(bx + self._pen_x + (0.5 * math.sin(t * 31) if writing else 0.0),
                      top + (-1.0 + 0.8 * math.sin(t * 43) if writing else 1.5))
        left = QPointF(bx - half - 1, by + 3)
        right = (QPointF(bx + half + 1, by + 3) if self.sent
                 else QPointF(pen.x() + 2, pen.y() + 1))   # holding the pencil
        p.save()
        p.translate(50, 120)   # the bow: he leans in over his feet
        p.scale(1.0, 1.0 - 0.05 * bow)
        p.translate(-50, -120)
        draw_bunny(p, QRectF(0, 0, 100, 120), None, blink=blink, dip=dip, ears=ears,
                   look=look, outfit=outfit(),
                   hold=((left.x(), left.y()), (right.x(), right.y())))
        p.restore()
        if not self.sent:
            self._pencil(p, pen.x(), pen.y())
        self._book(p, bx, by, shut)
        fur = look_colour("fur")
        ink = QPen(INK, 2.4)
        _ellipse(p, left.x(), left.y(), 12, 10.5, fur, ink, -20)
        _ellipse(p, right.x(), right.y(), 12, 10.5, fur, ink, 20)
        if self.sent:
            self._heart(p, age)
        p.end()

    def _book(self, p: QPainter, cx: float, cy: float, shut: float):
        """The notebook, its cover to you: open towards him, the two covers seen from
        outside, their outer edges a little shorter (turned away); the pages' top edges
        show over them. Shutting, the covers come flat into one, its label and heart
        showing."""
        ink = QPen(INK, 1.8)
        ink.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        cover = LEATHER
        half = HALF_W - HALF_W * 0.3 * shut
        lean = TILT * (1 - shut)
        h = BOOK_H / 2
        p.save()
        p.translate(cx, cy)
        # the pages' top edges over the covers (hidden once it's shut)
        if shut < 1:
            p.setPen(QPen(INK, 1.2))
            p.setBrush(PAPER)
            for sd in (-1, 1):
                edge = QPainterPath(QPointF(0, -h - 3.5))
                edge.lineTo(sd * (half - 1.5), -h + lean - 3.0)
                edge.lineTo(sd * (half - 1.5), -h + lean + 2.0)
                edge.lineTo(0, -h + 2.0)
                edge.closeSubpath()
                p.drawPath(edge)
        p.setPen(ink)
        p.setBrush(cover)
        body = QPainterPath(QPointF(-half, -h + lean))
        body.lineTo(0, -h)
        body.lineTo(half, -h + lean)
        body.lineTo(half, h - lean)
        body.lineTo(0, h)
        body.lineTo(-half, h - lean)
        body.closeSubpath()
        p.drawPath(body)
        # the spine down the middle, fading as the covers come flat
        if shut < 1:
            p.setOpacity(1 - shut)
            p.setPen(QPen(cover.darker(135), 2.6))
            p.drawLine(QPointF(0, -h + 1.5), QPointF(0, h - 1.5))
            p.setOpacity(1)
        # the front: a little label and a heart, coming in as it shuts
        if shut > 0:
            p.setOpacity(_ease((shut - 0.4) / 0.6))
            p.setPen(QPen(cover.darker(140), 1.2))
            p.setBrush(PAPER)
            p.drawRoundedRect(QRectF(-half + 3, -h + 4, 2 * half - 6, 6), 1.5, 1.5)
            heart_shape(p, 0, 5, 3.2, HEART, 1.2)
            p.setOpacity(1)
        p.restore()

    def _pencil(self, p: QPainter, x: float, y: float):
        """A yellow pencil in his paw at (x, y), its point down in the book (behind
        the cover), leaning up and to the right."""
        p.save()
        p.translate(x, y)
        p.rotate(-58)
        ink = QPen(INK, 1.3)
        ink.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(ink)
        p.setBrush(QColor("#ffcf40"))
        p.drawRect(QRectF(-4, -1.6, 17, 3.2))
        p.setBrush(QColor("#ff8fae"))
        p.drawRoundedRect(QRectF(13, -1.6, 3.5, 3.2), 1.2, 1.2)
        p.restore()

    def _heart(self, p: QPainter, age: float):
        """The heart: pops out of him as he bows, floats up, then fades."""
        k = (age - HEART_AT) / HEART_S
        if not 0 <= k <= 1:
            return
        pop = min(1.0, k / 0.18)
        size = 9.5 * (pop * (1.25 - 0.25 * pop))          # overshoots, then settles
        if size < 2:   # (a speck of outline before it's a heart)
            return
        top = max(8.0, self.box.top() + size * 1.1)        # (inside his box, ears or not)
        y = 48 - (48 - top) * _ease(k)                     # out of him, up over his head
        fade = 1.0 - max(0.0, (k - 0.7) / 0.3)
        p.save()
        p.setOpacity(fade)
        heart_shape(p, 50, y, size, HEART)
        sparkle(p, 50 - 17, y + 4 - 6 * k, 4.0 * pop, QColor("#ffcf40"))
        sparkle(p, 50 + 18, y - 4 - 4 * k, 3.2 * pop, QColor("#ff8fae"))
        p.restore()
