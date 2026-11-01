"""Recently deleted's Bun reaching out of his bin with a long stretchy arm, over the
window (ui/sounds/deleted.py):

- `throw`: Bring back. The paw grabs the row, rips it out of the list, pulls it up and
  throws it away into the distance: it spins, shrinks and fades as if it flew off.
- `peel`: Delete for good. The paw takes the row's right end and peels it back like a
  sticker; the folded sticker goes into his bin.

The row is a picture of it taken before it goes (`QListWidget` row); the list itself is
filled again (`ripped`) once the picture has left its place. Drawn by a see-through layer
over the whole window that takes no clicks, on a timer only while it plays. In lite
mode nothing plays: the callbacks run at once.
"""
from __future__ import annotations

import math
import time
from collections.abc import Callable

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from soundboard.ui.bun.bunny import INK, look_colour
from soundboard.ui.bun.bunskitkit import ease, seg
from soundboard.ui.kit import theme
from soundboard.ui.settings import lite

FRAME_MS = 16
THROW_S = 2.7      # Bring back, start to end
PEEL_S = 2.3       # Delete for good
REACH = 0.5        # the arm out to the row
GRAB = 0.62        # the paw has it
ARM_W = 12.0       # the stretchy arm's thickness, px
PAW = (21.0, 17.0)
PAD = (8.0, 7.0)   # the card round a row's picture once it's ripped out
PAPER = QColor("#efe9f7")   # the sticker's back


def _lerp(a: QPointF, b: QPointF, k: float) -> QPointF:
    return QPointF(a.x() + (b.x() - a.x()) * k, a.y() + (b.y() - a.y()) * k)


class BinHand(QWidget):
    """The layer over the window `host`; `start()` gives where his arm comes out (the
    bin's rim, in the host's coordinates)."""

    def __init__(self, host: QWidget, start: Callable[[], QPointF]):
        super().__init__(host)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self._start = start
        self._kind = ""
        self._pic: QPixmap | None = None
        self._rect = QRectF()
        self._at = 0.0
        self._grabbed: Callable[[], None] | None = None
        self._ripped: Callable[[], None] | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)
        self.hide()

    @property
    def playing(self) -> bool:
        return bool(self._kind)

    def throw(self, pic: QPixmap, rect: QRect, grabbed: Callable[[], None],
              ripped: Callable[[], None]):
        """Bring back: `rect` is the row in the host's coordinates. `grabbed` runs when
        the paw takes it (blank the row: the picture stands in for it), `ripped` once
        it's out of the list (fill the list again)."""
        self._play("throw", pic, rect, grabbed, ripped)

    def peel(self, pic: QPixmap, rect: QRect, grabbed: Callable[[], None],
             ripped: Callable[[], None]):
        """Delete for good: as `throw`; `ripped` once the sticker is off the list."""
        self._play("peel", pic, rect, grabbed, ripped)

    def finish(self):
        """Stop at once, as if it had played to the end."""
        grabbed, ripped = self._grabbed, self._ripped
        self._kind, self._grabbed, self._ripped = "", None, None
        self._timer.stop()
        self.hide()
        for fn in (grabbed, ripped):
            if fn is not None:
                fn()

    def _play(self, kind, pic, rect, grabbed, ripped):
        self.finish()
        if lite.on():
            grabbed()
            ripped()
            return
        self._kind, self._pic, self._rect = kind, pic, QRectF(rect)
        self._grabbed, self._ripped = grabbed, ripped
        self._at = time.monotonic()
        host = self.parentWidget()
        if host is not None:
            self.setGeometry(host.rect())
        self.raise_()
        self.show()
        self._timer.start()

    def _tick(self):
        t = time.monotonic() - self._at
        rip_at = GRAB + 0.15 if self._kind == "throw" else 1.5
        if self._grabbed is not None and t >= GRAB:
            grabbed, self._grabbed = self._grabbed, None
            grabbed()
        if self._ripped is not None and t >= rip_at:
            ripped, self._ripped = self._ripped, None
            ripped()
        if t >= (THROW_S if self._kind == "throw" else PEEL_S):
            self.finish()
            return
        self.update()

    # ------------------------------------------------------------------ drawing
    def paintEvent(self, ev):
        if not self._kind or self._pic is None:
            return
        t = time.monotonic() - self._at
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        try:
            (self._paint_throw if self._kind == "throw" else self._paint_peel)(p, t)
        except Exception:  # noqa: BLE001 - nothing in a paint may raise
            self._kind = ""
        p.end()

    def _arm(self, p: QPainter, paw: QPointF, out: float, angle: float = 0.0):
        """His arm from the bin's rim to `paw`, `out` 0..1 of the way (a stretchy noodle
        with a bend in it), and the paw."""
        if out <= 0.01:
            return
        s = self._start()
        end = _lerp(s, paw, out)
        mid = _lerp(s, end, 0.5)
        bend = QPointF(mid.x() + 0.18 * abs(end.y() - s.y()), mid.y() - 0.25 * abs(end.x() - s.x()))
        path = QPainterPath(s)
        path.quadTo(bend, end)
        fur = look_colour("fur")
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(INK, ARM_W + 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(path)
        p.setPen(QPen(fur, ARM_W, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(path)
        p.save()
        p.translate(end)
        p.rotate(angle)
        p.setPen(QPen(INK, 1.6))
        p.setBrush(fur)
        p.drawEllipse(QRectF(-PAW[0] / 2, -PAW[1] / 2, *PAW))
        p.restore()

    def _card(self, p: QPainter, centre: QPointF, scale: float, turn: float, alpha: float,
              pic: QPixmap | None = None, shadow: bool = True):
        pic = pic or self._pic
        if pic is None or alpha <= 0 or scale <= 0.01:
            return
        w, h = self._rect.width(), self._rect.height()
        p.save()
        p.setOpacity(alpha)
        p.translate(centre)
        p.rotate(turn)
        p.scale(scale, scale)
        card = QRectF(-w / 2 - PAD[0], -h / 2 - PAD[1], w + 2 * PAD[0], h + 2 * PAD[1])
        if shadow:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 90))
            p.drawRoundedRect(card.translated(4, 7), 8, 8)
        p.setPen(QPen(QColor(theme.T["accent"]), 2))   # a card: the row on a plate
        p.setBrush(QColor(theme.T["panel"]))
        p.drawRoundedRect(card, 8, 8)
        p.drawPixmap(QRectF(-w / 2, -h / 2, w, h), pic, QRectF(pic.rect()))
        p.restore()

    def _paint_throw(self, p: QPainter, t: float):
        r = self._rect
        grab = QPointF(r.left() + r.width() * 0.3, r.center().y())
        home = r.center()
        s = self._start()
        held_at = QPointF(s.x() + 70, s.y() - 30)        # pulled up beside him
        away = QPointF(self.width() * 0.62, self.height() * 0.18)   # into the distance
        if t < GRAB:   # reaching out (the row's still in the list)
            self._arm(p, grab, ease(seg(t, 0, REACH)))
            return
        lift = ease(seg(t, GRAB, GRAB + 0.3))            # ripped out, tilting up
        pull = ease(seg(t, GRAB + 0.3, 1.25))             # pulled up to him
        fly = seg(t, 1.3, THROW_S)                        # thrown
        if fly <= 0:
            c = _lerp(QPointF(home.x(), home.y() - 14 * lift), held_at, pull)
            turn = -8 * lift + 14 * pull
            self._card(p, c, 1.0 + 0.2 * lift - 0.25 * pull, turn, 1.0)   # (up at you)
            off = QPointF(grab.x() - home.x(), grab.y() - home.y())
            self._arm(p, QPointF(c.x() + off.x() * (1 - 0.3 * pull),
                                 c.y() + off.y() * (1 - 0.3 * pull)), 1.0)
            return
        k = 1 - (1 - fly) ** 1.6                          # fast off, slowing into the distance
        c = _lerp(held_at, away, k)
        c.setY(c.y() - 40 * math.sin(math.pi * min(1.0, fly * 1.4)))   # up in an arc
        self._card(p, c, 0.95 * (1 - k) ** 1.2 + 0.04, 14 + 300 * k, 1 - seg(fly, 0.7, 1.0),
                   shadow=fly < 0.4)
        self._arm(p, held_at, 1 - ease(seg(t, 1.3, 1.75)))   # the arm snapping back

    def _paint_peel(self, p: QPainter, t: float):
        r = self._rect.adjusted(-PAD[0], -PAD[1], PAD[0], PAD[1])   # the row as a sticker
        w = r.width()
        corner = QPointF(r.right() - 5, r.center().y())
        sticker = self._sticker()
        if t < GRAB:   # reaching for its right end (it's a sticker from the start)
            p.drawPixmap(r.topLeft(), sticker)
            self._arm(p, corner, ease(seg(t, 0, REACH)), 30)
            return
        k = ease(seg(t, GRAB, 1.45))      # peeled back to its middle
        fold = w * (1 - 0.5 * k)
        flap = 2 * fold - w                # the peeled end, folded back over
        lift = ease(seg(t, 1.5, 2.15))     # the folded sticker, off into the bin
        folded = self._folded(sticker, fold, flap)
        if lift <= 0:
            p.drawPixmap(r.topLeft(), folded)
            self._arm(p, QPointF(r.left() + flap + 3, r.center().y() - 5 * k), 1.0, 30 - 40 * k)
            return
        s = self._start()
        home = QPointF(r.left() + fold / 2, r.center().y())
        target = QPointF(s.x() - 18, s.y() + 6)   # into the bin
        c = _lerp(home, target, lift)
        c.setY(c.y() - 50 * math.sin(math.pi * lift))
        scale = 1 - 0.8 * lift
        p.save()
        p.setOpacity(1 - seg(lift, 0.8, 1.0))
        p.translate(c)
        p.rotate(-25 * lift)
        p.scale(scale, scale)
        p.drawPixmap(QPointF(-fold / 2, -r.height() / 2), folded, QRectF(0, 0, fold, r.height()))
        p.restore()
        self._arm(p, QPointF(c.x() - fold / 2 * scale, c.y()), 1 - seg(lift, 0.75, 1.0), -10)

    def _sticker(self) -> QPixmap:
        """The row's picture on its card: what he peels off."""
        r = self._rect
        out = QPixmap(round(r.width() + 2 * PAD[0]), round(r.height() + 2 * PAD[1]))
        out.fill(Qt.GlobalColor.transparent)
        q = QPainter(out)
        q.setRenderHint(QPainter.RenderHint.Antialiasing)
        q.setPen(QPen(QColor(theme.T["accent"]), 2))
        q.setBrush(QColor(theme.T["panel"]))
        q.drawRoundedRect(QRectF(1, 1, out.width() - 2, out.height() - 2), 8, 8)
        if self._pic is not None:
            q.drawPixmap(QRectF(PAD[0], PAD[1], r.width(), r.height()), self._pic,
                         QRectF(self._pic.rect()))
        q.end()
        return out

    def _folded(self, sticker: QPixmap, fold: float, flap: float) -> QPixmap:
        """The sticker peeled back: the part left of `fold` still on, and the peeled end
        folded back over it (its paper back, from `flap` to `fold`)."""
        out = QPixmap(sticker.size())
        out.fill(Qt.GlobalColor.transparent)
        q = QPainter(out)
        q.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = out.height()
        q.drawPixmap(QRectF(0, 0, fold, h), sticker, QRectF(0, 0, fold, h))
        if fold - flap > 0.5:
            q.setPen(Qt.PenStyle.NoPen)
            q.setBrush(QColor(0, 0, 0, 90))   # its shadow on the part still stuck down
            q.drawRoundedRect(QRectF(flap - 4, 4, fold - flap, h - 3), 8, 8)
            g = QLinearGradient(flap, 0, fold, 0)
            g.setColorAt(0.0, PAPER)
            g.setColorAt(0.7, PAPER.darker(108))
            g.setColorAt(1.0, PAPER.darker(135))   # rounding over at the fold
            q.setBrush(g)
            q.setPen(QPen(QColor(INK.red(), INK.green(), INK.blue(), 140), 1.2))
            q.drawRoundedRect(QRectF(flap, 1, fold - flap, h - 2), 8, 8)
        q.end()
        return out
