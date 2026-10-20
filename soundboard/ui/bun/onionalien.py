"""The Onion Alien: the author's own mascot, a purple onion with big alien eyes, drawn
with QPainter in the same style as Bun and Hoot (bold shapes, a dark outline, soft
shading, no detail lines). He says the note on Settings > About.

    AlienNote(text)          # him saying `text` in a speech bubble, typed out
    alien_pixmap(104, dpr)   # QPixmap, transparent background
"""
from __future__ import annotations

import math

from PySide6.QtCore import (QElapsedTimer, QEvent, QPointF, QRect, QRectF, QSize, Qt, QTimer,
                            Signal)
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen,
                           QPixmap, QRadialGradient, QTextLayout, QTextOption)
from PySide6.QtWidgets import QSizePolicy, QWidget

# drawn on a 100 x 120 canvas, like Bun and Hoot, scaled to the requested height
W, H = 100.0, 120.0
INK = QColor("#2b2340")
SKIN = QColor("#ae45d7")        # the Onion theme's purple
SKIN_DARK = QColor("#7d2fa0")
LAYER = QColor(201, 117, 234, 110)
LEAF = QColor("#8fd14f")
LEAF_DARK = QColor("#5fa32c")
ROOT = QColor("#e8d6b0")
EYE = QColor("#251c33")
IRIS = QColor("#8fd14f")
MOUTH = QColor("#c2413b")
TONGUE = QColor("#ff8fae")
CHEEK = QColor(255, 128, 160, 120)
TEAR = QColor("#8fd3ff")
THROAT = QColor("#3a1028")
EYES = (36.0, 64.0)
EYE_Y = 70.0


def _e(p: QPainter, cx, cy, w, h, fill, pen=None):
    p.setPen(pen or Qt.PenStyle.NoPen)
    p.setBrush(fill)
    p.drawEllipse(QRectF(cx - w / 2, cy - h / 2, w, h))


def _shade(p: QPainter, shape: QPainterPath, x, y, r, col: QColor, alpha: int):
    """A soft round shade inside `shape`, darkest at x, y and gone `r` away."""
    c, edge = QColor(col), QColor(col)
    c.setAlpha(alpha)
    edge.setAlpha(0)
    g = QRadialGradient(QPointF(x, y), r)
    g.setColorAt(0.0, c)
    g.setColorAt(1.0, edge)
    p.save()
    p.setClipPath(shape)
    p.fillRect(QRectF(x - r, y - r, 2 * r, 2 * r), g)
    p.restore()


def body_path() -> QPainterPath:
    """The onion bulb: a soft point on top, round and fat low down."""
    top, wide, mid, bottom = 26.0, 36.0, 76.0, 112.0
    path = QPainterPath(QPointF(50, top))
    path.cubicTo(QPointF(56, top + 14), QPointF(50 + wide, mid - 30), QPointF(50 + wide, mid))
    path.cubicTo(QPointF(50 + wide, mid + 26), QPointF(70, bottom), QPointF(50, bottom))
    path.cubicTo(QPointF(30, bottom), QPointF(50 - wide, mid + 26), QPointF(50 - wide, mid))
    path.cubicTo(QPointF(50 - wide, mid - 30), QPointF(44, top + 14), QPointF(50, top))
    path.closeSubpath()
    return path


def _leaf(sx: int, length: float) -> QPainterPath:
    """One green shoot out of his tip, leaning out to side `sx`."""
    tip = QPointF(50 + sx * 10, 28 - length)
    leaf = QPainterPath(QPointF(50 - sx * 2, 29))
    leaf.cubicTo(QPointF(50 - sx * 3, 18), QPointF(50 + sx * 2, 28 - length * 0.7), tip)
    leaf.cubicTo(QPointF(50 + sx * 7, 28 - length * 0.45), QPointF(50 + sx * 5, 22),
                 QPointF(50 + sx * 3, 29))
    leaf.closeSubpath()
    return leaf


def _tear(p: QPainter, x: float, t: float):
    """A tear out of the eye at `x`, `t` 0..1 through its life: it wells up under the
    eye, then runs down his cheek and fades."""
    grow = min(1.0, t / 0.25)
    run = max(0.0, (t - 0.25) / 0.75)
    cy = EYE_Y + 12 + run * run * 28
    r = 2.6 + 3.0 * grow
    drop = QPainterPath(QPointF(x, cy - r * 2.4))
    drop.cubicTo(QPointF(x + r * 0.4, cy - r * 1.2), QPointF(x + r, cy - r * 0.4),
                 QPointF(x + r, cy))
    drop.cubicTo(QPointF(x + r, cy + r * 1.3), QPointF(x - r, cy + r * 1.3),
                 QPointF(x - r, cy))
    drop.cubicTo(QPointF(x - r, cy - r * 0.4), QPointF(x - r * 0.4, cy - r * 1.2),
                 QPointF(x, cy - r * 2.4))
    alpha = 1.0 if run < 0.7 else max(0.0, 1 - (run - 0.7) / 0.3)
    fill, ink = QColor(TEAR), QColor(INK)
    fill.setAlphaF(alpha)
    ink.setAlphaF(alpha)
    p.setPen(QPen(ink, 1.4))
    p.setBrush(fill)
    p.drawPath(drop)
    shine = QColor("white")
    shine.setAlphaF(alpha * 0.9)
    _e(p, x - r * 0.35, cy - r * 0.2, r * 0.55, r * 0.7, shine)


def draw_alien(p: QPainter, rect: QRectF, mouth_open: float = 1.0,
               tears: tuple = (), gape: float = 0.0):
    """Draw him fitted (aspect kept, centred) into `rect`. `mouth_open` 0..1: his
    smile, from shut to wide (talking flaps it). `tears`: (eye 0/1, 0..1 through
    it) for each tear running down; any makes him frown. `gape` 0..1: his mouth
    opened into a big round hole (the eating easter egg)."""
    s = min(rect.width() / W, rect.height() / H)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(rect.center().x() - W * s / 2, rect.center().y() - H * s / 2)
    p.scale(s, s)
    ink = QPen(INK, 2.4)
    ink.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    ink.setCapStyle(Qt.PenCapStyle.RoundCap)

    # the shoots on top, behind the bulb
    for sx, length in ((-1, 16.0), (1, 21.0)):
        leaf = _leaf(sx, length)
        p.setPen(ink)
        p.setBrush(LEAF)
        p.drawPath(leaf)
        _shade(p, leaf, 50 + sx * 2, 30, 12, LEAF_DARK, 170)
    # stubby arms from his sides, mostly behind him
    for sx in (-1, 1):
        p.setPen(ink)
        p.setBrush(SKIN)
        p.drawEllipse(QRectF(50 + sx * 38 - 6, 83.5, 12, 9))
    # the bulb, lit from up on his right, deeper underneath
    body = body_path()
    p.setPen(ink)
    p.setBrush(SKIN)
    p.drawPath(body)
    _shade(p, body, 50, 122, 46, SKIN_DARK, 190)
    _shade(p, body, 40, 40, 24, SKIN.lighter(130), 150)
    # the onion's layers: soft lighter bands, no lines
    p.save()
    p.setClipPath(body)
    for dx in (-17, 17):
        band = QPainterPath(QPointF(50 + dx * 0.15, 30))
        band.quadTo(QPointF(50 + dx * 1.9, 69), QPointF(50 + dx * 0.6, 110))
        band.quadTo(QPointF(50 + dx * 1.35, 69), QPointF(50 + dx * 0.15, 30))
        p.fillPath(band, LAYER)
    p.restore()
    # little roots for feet
    p.setPen(QPen(ROOT, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    for dx, lean in ((-6, -1), (0, 0), (6, 1)):
        root = QPainterPath(QPointF(50 + dx, 111))
        root.quadTo(QPointF(50 + dx + lean * 2, 116), QPointF(50 + dx + lean * 4, 118))
        p.drawPath(root)
    # blushing cheeks
    p.save()
    p.setClipPath(body)
    for x in (25.0, 75.0):
        g = QRadialGradient(QPointF(x, 82), 6.5)
        g.setColorAt(0, CHEEK)
        g.setColorAt(0.55, CHEEK)
        g.setColorAt(1, QColor(255, 128, 160, 0))
        p.fillRect(QRectF(x - 7, 75, 14, 14), g)
    p.restore()
    # the big glossy eyes, green low down
    ew, eh = 19.0, 21.0
    for x in EYES:
        eye = QPainterPath()
        eye.addEllipse(QRectF(x - ew / 2, EYE_Y - eh / 2, ew, eh))
        p.fillPath(eye, EYE)
        p.save()
        p.setClipPath(eye)
        g = QRadialGradient(QPointF(x, EYE_Y + eh * 0.42), ew * 0.45)
        g.setColorAt(0, IRIS)
        g.setColorAt(1, QColor(IRIS.red(), IRIS.green(), IRIS.blue(), 0))
        p.fillRect(QRectF(x - ew, EYE_Y, 2 * ew, eh), g)
        _e(p, x + 3.2, EYE_Y - 3.8, 6.1, 6.7, QColor("white"))
        _e(p, x - 3.2, EYE_Y + 4.2, 2.5, 2.5, QColor("white"))
        p.restore()
    # a little open smile (a plain curve when shut)
    o = max(0.0, min(1.0, mouth_open))
    pen = QPen(INK, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
               Qt.PenJoinStyle.RoundJoin)
    mouth = QPainterPath(QPointF(45.5, 85))
    g = max(0.0, min(1.0, gape))
    if g > 0.05:
        # wide open: a round dark hole, his tongue at the bottom
        mw, mh = 9 + 15 * g, 4 + 13 * g
        hole = QPainterPath()
        hole.addEllipse(QRectF(50 - mw / 2, 90 - mh / 2, mw, mh))
        p.setPen(pen)
        p.setBrush(THROAT)
        p.drawPath(hole)
        p.save()
        p.setClipPath(hole)
        _e(p, 50, 90 + mh * 0.42, mw * 0.6, mh * 0.45, TONGUE)
        p.restore()
    elif tears:
        mouth = QPainterPath(QPointF(45.5, 88))
        mouth.quadTo(QPointF(50, 84), QPointF(54.5, 88))
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(mouth)
    elif o < 0.15:
        mouth.quadTo(QPointF(50, 89), QPointF(54.5, 85))
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(mouth)
    else:
        mouth.quadTo(QPointF(50, 85 + 8.5 * o), QPointF(54.5, 85))
        mouth.closeSubpath()
        p.setPen(pen)
        p.setBrush(MOUTH)
        p.drawPath(mouth)
        p.save()
        p.setClipPath(mouth)
        _e(p, 50, 85 + 6.5 * o, 5.4, 3.6, TONGUE)
        p.restore()
    for eye, t in tears:
        if 0.0 <= t <= 1.0:
            _tear(p, EYES[eye] + (2.5 if eye else -2.5), t)
    p.restore()


class AlienNote(QWidget):
    """The Onion Alien saying `text` in a speech bubble, typed out a letter at a time
    like an RPG's dialogue box each time it's shown (no sound). A click shows it all.
    The bubble takes the theme's colours, read as it paints, so a theme switch shows
    at once; its height is the whole text's from the start, so nothing below jumps."""

    ALIEN_H = 96
    GAP = 4          # alien to the tail's point
    PIX = 2          # one pixel of the bubble, px
    TAIL_S = 8       # how far the tail pokes out (small units, see _pix_font)
    EDGE_S = 2       # the border's thickness
    PAD_S = 6        # inside the border
    FONT_S = 11      # the letters' pixel size
    MAX_W = 520      # the longest line, px (a translation wraps)
    TICK_MS = 28     # one letter
    PAUSE = {".": 9, "?": 9, "!": 9, ",": 4, "\n": 6}   # extra ticks after these

    # the easter egg: clicks on him. One tear at TEAR_1, two at TEAR_2, and at GULP he
    # eats the whole window and spits it back out a minute later (OnionGulp)
    TEAR_1, TEAR_2, GULP = 10, 50, 100
    TEAR_MS = 1800       # one tear's life
    TEAR_GAP_MS = 250    # the second of two tears starts this much later

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.text = text
        self.shown = len(text)    # letters typed so far
        self._wait = 0
        self._timer = QTimer(self)
        self._timer.setInterval(self.TICK_MS)
        self._timer.timeout.connect(self._tick)
        self.clicks = 0
        self.tear_ms = -1.0       # how far the tears have got, -1 = none
        self.tear_count = 0
        self.hidden_alien = False  # he's out of his spot, eating the window
        self.gulp: OnionGulp | None = None
        self._tear_clock = QElapsedTimer()
        self._tear_timer = QTimer(self)
        self._tear_timer.setInterval(16)
        self._tear_timer.timeout.connect(self._tear_tick)
        self.setAccessibleName(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        pol = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        pol.setHeightForWidth(True)
        self.setSizePolicy(pol)

    # -- typing
    @property
    def typing(self) -> bool:
        return self.shown < len(self.text)

    def restart(self):
        self.shown, self._wait = 0, 0
        self._timer.start()
        self.update()

    def finish(self):
        self._timer.stop()
        self.shown = len(self.text)
        self.update()

    def _tick(self):
        if self._wait > 0:
            self._wait -= 1
            return
        self.shown += 1
        if not self.typing:
            self._timer.stop()
        else:
            self._wait = self.PAUSE.get(self.text[self.shown - 1], 0)
        self.update()

    def showEvent(self, ev):
        super().showEvent(ev)
        self.restart()

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self._timer.stop()

    def mousePressEvent(self, ev):
        self.finish()
        if ev.position().x() <= self._alien_w():
            self.poke()

    # -- the easter egg
    def poke(self):
        """One click on him (none count while he's out eating the window)."""
        if self.gulp is not None:
            return
        self.clicks += 1
        if self.clicks == self.TEAR_1:
            self.cry(1)
        elif self.clicks == self.TEAR_2:
            self.cry(2)
        elif self.clicks >= self.GULP:
            self.clicks = 0
            self.eat_window()

    def cry(self, count: int):
        self.tear_count = count
        self.tear_ms = 0.0
        self._tear_clock.start()
        self._tear_timer.start()
        self.update()

    def tears(self) -> tuple:
        """(eye, 0..1) for each tear running now."""
        if self.tear_ms < 0:
            return ()
        if self.tear_count == 1:
            return ((1, self.tear_ms / self.TEAR_MS),)
        return ((0, self.tear_ms / self.TEAR_MS),
                (1, (self.tear_ms - self.TEAR_GAP_MS) / self.TEAR_MS))

    def set_tear_ms(self, ms: float):
        total = self.TEAR_MS + (self.TEAR_GAP_MS if self.tear_count > 1 else 0)
        self.tear_ms = ms if ms < total else -1.0
        if self.tear_ms < 0:
            self._tear_timer.stop()
        self.update()

    def _tear_tick(self):
        self.set_tear_ms(float(self._tear_clock.elapsed()))

    def alien_rect(self) -> QRectF:
        return QRectF(0, (self.height() - self.ALIEN_H) / 2, self._alien_w(), self.ALIEN_H)

    def eat_window(self) -> OnionGulp | None:
        win = self.window()
        if win is self or not self.isVisible():
            return None
        self.gulp = OnionGulp(self, win)
        self.gulp.done.connect(self._gulp_done)
        self.gulp.start()
        return self.gulp

    def _gulp_done(self):
        self.gulp = None
        self.hidden_alien = False
        self.update()

    # -- layout. The bubble is drawn PIX times smaller with no smoothing, then blown up,
    # so its border, tail and letters come out in chunky pixels, like an old game's
    # text box (in every language: it's the normal font, just pixelated). Sizes in
    # the small units carry an _s.
    def _alien_w(self) -> float:
        return self.ALIEN_H * W / H

    def _pix_font(self) -> QFont:
        f = QFont(self.font())
        f.setFamilies(["Consolas", "DejaVu Sans Mono", "Menlo", f.family()])  # a blocky mono
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setPixelSize(self.FONT_S)
        f.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        f.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
        return f

    def _text_w(self, width: int) -> int:
        """The text's width (small units): as wide as the words, up to MAX_W or the
        room."""
        room = (width - self._alien_w() - self.GAP) // self.PIX - self.TAIL_S \
            - 2 * (self.PAD_S + self.EDGE_S) - 1
        fm = QFontMetricsF(self._pix_font())
        words = max(fm.horizontalAdvance(para) for para in self.text.split("\n")) + 1
        return int(max(30, min(words, self.MAX_W // self.PIX, room)))

    def _lines(self, width: float) -> list[tuple[QTextLayout, int]]:
        """Each paragraph laid out at `width`, with where it starts in the text."""
        out, start = [], 0
        font = self._pix_font()
        for para in self.text.split("\n"):
            lay = QTextLayout(para, font)
            opt = QTextOption()
            opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
            lay.setTextOption(opt)
            lay.beginLayout()
            y = 0.0
            while True:
                line = lay.createLine()
                if not line.isValid():
                    break
                line.setLineWidth(width)
                line.setPosition(QPointF(0, y))
                y += line.height()
            lay.endLayout()
            out.append((lay, start))
            start += len(para) + 1
        return out

    @staticmethod
    def _para_h(lay: QTextLayout, fm: QFontMetricsF) -> float:
        return lay.boundingRect().height() if lay.lineCount() else fm.height()

    def _box_h(self, tw: int) -> int:
        """The bubble's height, small units."""
        fm = QFontMetricsF(self._pix_font())
        text_h = sum(self._para_h(lay, fm) for lay, __ in self._lines(tw))
        return math.ceil(text_h) + 2 * (self.PAD_S + self.EDGE_S)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return max(self.ALIEN_H, self._box_h(self._text_w(width)) * self.PIX) + 2

    def sizeHint(self) -> QSize:
        return QSize(420, self.heightForWidth(420))

    def minimumSizeHint(self) -> QSize:
        return QSize(round(self._alien_w() + 140), self.ALIEN_H)

    # -- painting
    def paintEvent(self, ev):
        from soundboard.ui.kit import theme
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        aw = self._alien_w()
        ay = (self.height() - self.ALIEN_H) / 2
        # his mouth flaps open and shut as each letter comes out
        talk = 1.0 if not self.typing else (0.0 if self.shown % 4 < 2 else 0.85)
        if not self.hidden_alien:
            draw_alien(p, QRectF(0, ay, aw, self.ALIEN_H), talk, self.tears())

        tw = self._text_w(self.width())
        bw, bh = tw + 2 * (self.PAD_S + self.EDGE_S), self._box_h(tw)
        img = QImage(self.TAIL_S + bw, bh, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        q = QPainter(img)
        edge, fill = QColor(t["accent"]), QColor(t["field"])
        e, x0 = self.EDGE_S, self.TAIL_S
        # the box: a thick border with the corners stepped in, the fill inside it
        q.fillRect(x0 + e, 0, bw - 2 * e, bh, edge)
        q.fillRect(x0, e, bw, bh - 2 * e, edge)
        q.fillRect(x0 + e // 2, e // 2, bw - e, bh - e, edge)
        q.fillRect(x0 + e + 1, e, bw - 2 * e - 2, bh - 2 * e, fill)
        q.fillRect(x0 + e, e + 1, bw - 2 * e, bh - 2 * e - 2, fill)
        # the tail: a solid stepped point out of the left side, at his mouth's
        # height, opening into the box (its border cut away where they meet)
        mouth = (ay + self.ALIEN_H * 87 / H - (self.height() - bh * self.PIX) / 2) / self.PIX
        my = int(max(e + 6, min(bh - e - 7, mouth)))
        for i in range(self.TAIL_S):
            x = x0 - 1 - i
            half = (self.TAIL_S - i) // 2   # narrower towards the point
            q.fillRect(x, my - half - e, 1, 2 * half + 2 * e, edge)
            q.fillRect(x, my - half, 1, 2 * half, fill)
        q.fillRect(x0, my - self.TAIL_S // 2, e + 1, 2 * (self.TAIL_S // 2), fill)
        # the letters typed so far, in the theme's highlight colour; the line being
        # typed is cut off where it's got to
        q.setPen(QColor(t["accent_link"]))
        fm = QFontMetricsF(self._pix_font())
        x, y = x0 + e + self.PAD_S, e + self.PAD_S
        for lay, start in self._lines(tw):
            if start > self.shown:
                break
            for i in range(lay.lineCount()):
                line = lay.lineAt(i)
                if start + line.textStart() >= self.shown:
                    break
                origin = QPointF(x, y)
                cut = self.shown - start
                if cut < line.textStart() + line.textLength():
                    right = x + line.cursorToX(cut)[0]  # pyright: ignore[reportIndexIssue]  (PySide returns (x, cursor))
                    q.save()
                    q.setClipRect(QRectF(x - 1, y + line.y(), right - x + 1, line.height()))
                    line.draw(q, origin)
                    q.restore()
                else:
                    line.draw(q, origin)
            y += self._para_h(lay, fm)
        q.end()
        # blown up with no smoothing: every small pixel a PIX x PIX block
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        left = aw + self.GAP
        top = (self.height() - bh * self.PIX) / 2
        p.drawImage(QRectF(left, round(top), img.width() * self.PIX, bh * self.PIX), img)
        p.end()

def _ease(u: float) -> float:
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


class OnionGulp(QWidget):
    """The 100-click easter egg, laid over the whole window: he hops out of his note
    into the middle, sucks the whole window in piece by piece (nearest first), sits on
    the empty window for BLANK_MS, then spits every piece back to where it was and hops
    home. It only paints over a picture of the window: nothing
    underneath is touched, and the window's clicks wait until he's done.

    `t` is how far it's got (ms); set_t() steps it by hand (tests, pictures)."""

    done = Signal()
    TILE = 44           # one piece of the window, px
    HOP_MS = 700        # out of the note to the middle, mouth opening
    EAT_MS = 3400       # the pieces going in, one after another
    FLY_MS = 650        # one piece's trip
    SHUT_MS = 500       # mouth shut, a gulp
    BLANK_MS = 60_000   # the empty window (cut short by typing MAGIC)
    OPEN_MS = 450       # mouth open again
    HOME_MS = 600       # back into the note
    MAGIC = "onionalienplease"   # typed while he's out (spaces and case don't matter)
    FRAME_MS = 16       # while the pieces fly
    SIT_FRAME_MS = 33   # while he sits on the empty window (just a slow bob)

    def __init__(self, note: AlienNote, win: QWidget):
        super().__init__(win)
        self.note = note
        self.t = 0.0
        note.hidden_alien = True
        note.repaint()
        self.shot = win.grab()           # the window without him in it
        self.setGeometry(win.rect())
        dpr = self.shot.devicePixelRatio()
        home = note.alien_rect()
        self.home = QRectF(note.mapTo(win, home.topLeft().toPoint()), home.size())
        side = max(120.0, min(self.height() * 0.42, self.width() * 0.3, 300.0))
        self.big = QRectF(0, 0, side * W / H, side)
        self.big.moveCenter(QPointF(self.width() / 2, self.height() / 2))
        mouth = self._mouth(self.big)
        pieces = []
        for y in range(0, self.height(), self.TILE):
            for x in range(0, self.width(), self.TILE):
                r = QRectF(x, y, min(self.TILE, self.width() - x),
                           min(self.TILE, self.height() - y))
                c = r.center()
                near = math.hypot(c.x() - mouth.x(), c.y() - mouth.y())
                pix = self.shot.copy(round(x * dpr), round(y * dpr),
                                     math.ceil(r.width() * dpr), math.ceil(r.height() * dpr))
                pix.setDevicePixelRatio(dpr)
                pieces.append((near, r, pix))
        pieces.sort(key=lambda piece: piece[0])
        self.pieces = [(r, pix) for __, r, pix in pieces]
        spread = self.EAT_MS - self.FLY_MS
        n = max(1, len(self.pieces) - 1)
        self.starts = [spread * i / n for i in range(len(self.pieces))]
        self.ate = self.HOP_MS + self.EAT_MS
        self.blank_at = self.ate + self.SHUT_MS
        self.spit_at = self.blank_at + self.BLANK_MS + self.OPEN_MS
        self.home_at = self.spit_at + self.EAT_MS
        self.end = self.home_at + self.HOME_MS
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(self.FRAME_MS)
        self._sat = False           # the last frame was the empty window
        self.skipped = 0.0          # ms jumped ahead by "onionalien please"
        self.typed = ""
        self._timer.timeout.connect(
            lambda: self.set_t(self._clock.elapsed() + self.skipped))
        self.win = win
        win.installEventFilter(self)

    @staticmethod
    def _mouth(rect: QRectF) -> QPointF:
        s = min(rect.width() / W, rect.height() / H)
        return QPointF(rect.center().x(), rect.center().y() + (90 - H / 2) * s)

    def start(self):
        self.show()
        self.raise_()
        self._clock.start()
        self._timer.start()
        self.grabKeyboard()     # the keys are his until he's done

    def stop(self):
        """Everything back at once (the window was resized or closed under him)."""
        if self._timer.isActive() or self.isVisible():
            self._timer.stop()
            self.releaseKeyboard()
            self.win.removeEventFilter(self)
            self.hide()
            self.deleteLater()
            self.done.emit()

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Type.Resize, QEvent.Type.Close):
            self.stop()
        return False

    def keyPressEvent(self, ev):
        letters = "".join(c for c in ev.text().lower() if c.isalpha())
        if letters:
            self.typed = (self.typed + letters)[-len(self.MAGIC):]
            if self.typed == self.MAGIC:
                self.please()

    def please(self):
        """He gives it all back now: straight on to spitting it out."""
        spit = self.spit_at - self.OPEN_MS
        if self.t < spit:
            self.skipped += spit - self.t
            self.set_t(spit)

    def set_t(self, t: float):
        self.t = t
        if t >= self.end:
            self.stop()
            return
        sitting = self.blank_at <= t < self.spit_at - self.OPEN_MS
        self._timer.setInterval(self.SIT_FRAME_MS if sitting else self.FRAME_MS)
        if sitting and self._sat:
            # the empty window: only his slow bob moves, so only his spot is redrawn
            # (the whole window 60 times a second kept a CPU core busy for the minute)
            self.update(self._sit_box())
        else:
            self.update()
        self._sat = sitting

    def _sit_box(self) -> QRect:
        """Everything he can cover while he sits full and bobbing (see paintEvent)."""
        b = self.big
        w, h = b.width() * 1.3, b.height() * 1.15
        return QRectF(b.center().x() - w / 2, b.bottom() - h, w, h).adjusted(
            -6, -6, 6, 6).toAlignedRect()

    # where he is and how he looks at `t`
    def _pose(self) -> tuple[QRectF, float, float]:
        """(his rect, gape 0..1, belly 0..1)."""
        t = self.t
        if t < self.HOP_MS:
            u = _ease(t / self.HOP_MS)
            return self._between(self.home, self.big, u), u, 0.0
        if t < self.ate:
            eaten = sum(1 for s in self.starts if t >= self.HOP_MS + s + self.FLY_MS / 2)
            return self.big, 1.0, eaten / max(1, len(self.starts))
        if t < self.blank_at:
            u = (t - self.ate) / self.SHUT_MS
            return self.big, 1 - _ease(u * 2), 1.0
        if t < self.spit_at - self.OPEN_MS:
            return self.big, 0.0, 1.0
        if t < self.spit_at:
            return self.big, _ease((t - self.spit_at + self.OPEN_MS) / self.OPEN_MS), 1.0
        if t < self.home_at:
            out = sum(1 for s in self.starts if t >= self.spit_at + s + self.FLY_MS / 2)
            return self.big, 1.0, 1 - out / max(1, len(self.starts))
        u = _ease((t - self.home_at) / self.HOME_MS)
        return self._between(self.big, self.home, u), 1 - u, 0.0

    @staticmethod
    def _between(a: QRectF, b: QRectF, u: float) -> QRectF:
        return QRectF(a.x() + (b.x() - a.x()) * u, a.y() + (b.y() - a.y()) * u,
                      a.width() + (b.width() - a.width()) * u,
                      a.height() + (b.height() - a.height()) * u)

    def _piece_at(self, i: int) -> float | None:
        """Piece `i`'s trip: 0 = in its place, 1 = in his mouth (None: not drawn)."""
        t = self.t
        if t < self.HOP_MS + self.starts[i]:
            return 0.0
        if t < self.blank_at:
            u = (t - self.HOP_MS - self.starts[i]) / self.FLY_MS
            return None if u >= 1 else u * u
        if t < self.spit_at:
            return None
        # spat out last-in first-out
        j = len(self.starts) - 1 - i
        u = (t - self.spit_at - self.starts[j]) / self.FLY_MS
        if u <= 0:
            return None
        return 0.0 if u >= 1 else 1 - (1 - (1 - u) ** 2)

    def paintEvent(self, ev):
        from soundboard.ui.kit import theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(theme.tokens()["bg"]))
        rect, gape, belly = self._pose()
        mouth = self._mouth(rect)
        moving = []
        eaten = self.blank_at <= self.t < self.spit_at   # every piece is inside him
        for i, (r, pix) in enumerate(() if eaten else self.pieces):
            k = self._piece_at(i)
            if k is None:
                continue
            if k == 0.0:
                p.drawPixmap(r.topLeft(), pix)
            else:
                moving.append((k, r, pix))
        for k, r, pix in sorted(moving, key=lambda m: m[0]):
            # swirl in: round the mouth, shrinking and spinning as it goes
            c = r.center()
            vx, vy = c.x() - mouth.x(), c.y() - mouth.y()
            a = k * 1.4
            shrink = 1 - k
            x = mouth.x() + (vx * math.cos(a) - vy * math.sin(a)) * shrink
            y = mouth.y() + (vx * math.sin(a) + vy * math.cos(a)) * shrink
            p.save()
            p.translate(x, y)
            p.rotate(k * 220)
            p.scale(max(0.05, shrink), max(0.05, shrink))
            p.drawPixmap(QRectF(-r.width() / 2, -r.height() / 2, r.width(), r.height()),
                         pix, QRectF(pix.rect()))
            p.restore()
        # fatter the more he's eaten, bobbing while he sits full
        bob = math.sin(self.t / 260) * 0.03 * belly
        sx, sy = 1 + 0.22 * belly + bob, 1 + 0.06 * belly - bob
        c = QPointF(rect.center().x(), rect.bottom())
        p.translate(c)
        p.scale(sx, sy)
        p.translate(-c)
        draw_alien(p, rect, 1.0, (), gape)
        p.end()

    def mousePressEvent(self, ev):
        ev.accept()     # the window waits until he's done


def alien_image(height: int) -> QImage:
    h = max(1, height)
    w = max(1, round(h * W / H))
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    draw_alien(p, QRectF(0, 0, w, h))
    p.end()
    return img


def alien_pixmap(height: int, dpr: float = 1.0) -> QPixmap:
    pix = QPixmap.fromImage(alien_image(round(height * dpr)))
    pix.setDevicePixelRatio(dpr)
    return pix
