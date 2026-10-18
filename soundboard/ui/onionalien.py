"""The Onion Alien: the author's own mascot, a purple onion with big alien eyes, drawn
with QPainter in the same style as Bun and Hoot (bold shapes, a dark outline, soft
shading, no detail lines). He says the note on Settings > About.

    AlienNote(text)          # him saying `text` in a speech bubble, typed out
    alien_pixmap(104, dpr)   # QPixmap, transparent background
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
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


def draw_alien(p: QPainter, rect: QRectF, mouth_open: float = 1.0):
    """Draw him fitted (aspect kept, centred) into `rect`. `mouth_open` 0..1: his
    smile, from shut to wide (talking flaps it)."""
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
    if o < 0.15:
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

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.text = text
        self.shown = len(text)    # letters typed so far
        self._wait = 0
        self._timer = QTimer(self)
        self._timer.setInterval(self.TICK_MS)
        self._timer.timeout.connect(self._tick)
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
        draw_alien(p, QRectF(0, ay, aw, self.ALIEN_H), talk)

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
