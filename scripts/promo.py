"""Render the Triggers demo: a short clip of a made-up game where "YOU DIED" comes
up, the Triggers tab spots it and a sad trombone plays.

    .venv\\Scripts\\python scripts/promo.py --out <folder>
        [--gif <file>.gif]

Writes `onionboard-triggers-vertical.mp4` (1080 x 1920, for TikTok / Shorts /
Reels) and `onionboard-triggers-wide.mp4` (1280 x 720) into --out, and with --gif a
small looping GIF of the wide version. Everything is drawn here with
QPainter (the game scene, the app's trigger card) and the trombone is synthesized
with numpy, so nothing from anyone's game or sound library is used. Needs ffmpeg
on PATH. Runs on Qt's offscreen platform: no window appears.
"""
import argparse
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_QPA_FONTDIR", str(Path(os.environ.get("WINDIR", r"C:\Windows"))
                                            / "Fonts"))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QGuiApplication, QImage,  # noqa: E402
                           QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FPS = 30
SR = 48000
LENGTH = 13.0
DIED_AT = 4.0          # "YOU DIED" starts fading in
SEEN_AT = 4.8          # the trigger matches
PLAY_AT = 5.3          # ...and plays after its 0.5 s wait
OUTRO_AT = 9.0

BG = QColor("#0f1016")
CARD = QColor("#1c1d27")
EDGE = QColor("#2c2d3a")
TEXT = QColor("#e8e8f0")
MUTED = QColor("#9a9bb0")
ACCENT = QColor("#7c5cff")
GREEN = QColor("#13ce66")


def ease(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def fade(t: float, start: float, dur: float) -> float:
    return ease((t - start) / dur)


# --------------------------------------------------------------------------- drawing

SERIF = ["Palatino Linotype", "Book Antiqua", "Constantia", "Georgia", "Times New Roman"]
SOUL_RED = QColor("#b01a22")
SOUL_GOLD = QColor("#e2b650")


def _blur(img: QImage, radius: float) -> QImage:
    """A cheap soft blur: shrink, then scale back up smoothly (twice, for a rounder falloff)."""
    w, h = img.width(), img.height()
    for k in (max(2.0, radius), max(2.0, radius * 0.5)):
        small = img.scaled(max(1, int(w / k)), max(1, int(h / k)), Qt.IgnoreAspectRatio,
                           Qt.SmoothTransformation)
        img = small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return img


def _fit_font(families: list[str], text: str, width: float, height: float,
              spacing: float = 100, bold: bool = False, italic: bool = False) -> QFont:
    """The biggest font (pixel size) whose `text` fits `width`, and at most `height` px."""
    f = QFont()
    f.setFamilies(families)
    f.setBold(bold)
    f.setItalic(italic)
    f.setLetterSpacing(QFont.PercentageSpacing, spacing)
    f.setPixelSize(100)
    adv = QFontMetricsF(f).horizontalAdvance(text) or 1
    f.setPixelSize(max(6, int(min(width / adv * 100, height))))
    return f


def _text_path(f: QFont, text: str, c: QPointF) -> QPainterPath:
    """`text` as a path, centred on c (vertically by its capitals' height)."""
    fm = QFontMetricsF(f)
    path = QPainterPath()
    path.setFillRule(Qt.WindingFill)
    path.addText(QPointF(c.x() - fm.horizontalAdvance(text) / 2, c.y() + fm.capHeight() / 2),
                 f, text)
    return path


def _glow(p: QPainter, path: QPainterPath, box: QRectF, colour: QColor, radius: float):
    """A soft halo of `colour` around `path`, painted into the box it sits in."""
    img = QImage(max(1, int(box.width())), max(1, int(box.height())),
                 QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    q = QPainter(img)
    q.setRenderHint(QPainter.Antialiasing)
    q.translate(-box.left(), -box.top())
    q.setPen(QPen(colour, radius * 0.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    q.setBrush(colour)
    q.drawPath(path)
    q.end()
    p.drawImage(box, _blur(img, radius))


def draw_banner(p: QPainter, r: QRectF, text: str, colour: QColor = SOUL_RED,
                alpha: float = 1.0, grow: float = 1.0, size: float = 0.13, fill: float = 0.62):
    """A souls-like title card across r: a soft black band the full width, and `text`
    in big spaced serif capitals with a faint glow. `size` caps the letters' height as
    a fraction of r's height, `fill` their width as a fraction of r's width."""
    if alpha <= 0:
        return
    f = _fit_font(SERIF, text, r.width() * fill, r.height() * size, spacing=112)
    px = f.pixelSize()
    c = r.center()
    band = QRectF(r.left(), c.y() - px * 1.3, r.width(), px * 2.6)
    g = QLinearGradient(band.topLeft(), band.bottomLeft())
    g.setColorAt(0.0, QColor(0, 0, 0, 0))
    g.setColorAt(0.3, QColor(0, 0, 0, int(200 * alpha)))
    g.setColorAt(0.7, QColor(0, 0, 0, int(200 * alpha)))
    g.setColorAt(1.0, QColor(0, 0, 0, 0))
    p.save()
    p.setPen(Qt.NoPen)
    p.fillRect(band, g)
    path = _text_path(f, text, QPointF(0, 0))
    p.translate(c)
    p.scale(grow, grow)
    p.setOpacity(p.opacity() * alpha)
    halo = QColor(colour)
    halo.setAlpha(130)
    _glow(p, path, QRectF(-r.width() / 2, -px * 1.4, r.width(), px * 2.8), halo, px * 0.3)
    fill_g = QLinearGradient(QPointF(0, -px * 0.45), QPointF(0, px * 0.45))
    fill_g.setColorAt(0, colour.lighter(125))
    fill_g.setColorAt(1, colour.darker(130))
    p.setBrush(fill_g)
    p.drawPath(path)
    p.restore()


def draw_callout(p: QPainter, r: QRectF, text: str, accent: QColor = QColor("#ff4a3d"),
                 fill: float = 0.5):
    """A shooter-style kill callout: a crosshair and bold italic capitals on a slanted
    dark plate with an accent edge; the word takes `fill` of r's width."""
    f = _fit_font(["Bahnschrift", "Impact", "Segoe UI"], text, r.width() * fill,
                  r.height() * fill * 0.4, spacing=104, bold=True, italic=True)
    px = f.pixelSize()
    fm = QFontMetricsF(f)
    tw = fm.horizontalAdvance(text)
    ch = px * 1.05                                          # the crosshair's size
    total = ch + px * 0.45 + tw
    left = r.center().x() - total / 2
    cy = r.center().y()
    plate_h, slant = px * 1.55, px * 0.35                  # slanted like the letters
    x0, x1 = left - px * 0.7, left + total + px * 0.9

    def slanted(a: float, b: float) -> QPainterPath:
        path = QPainterPath()
        path.moveTo(a + slant, cy - plate_h / 2)
        path.lineTo(b + slant, cy - plate_h / 2)
        path.lineTo(b - slant, cy + plate_h / 2)
        path.lineTo(a - slant, cy + plate_h / 2)
        path.closeSubpath()
        return path
    g = QLinearGradient(QPointF(x0, 0), QPointF(x1, 0))
    g.setColorAt(0, QColor(10, 10, 14, 235))
    g.setColorAt(0.75, QColor(10, 10, 14, 205))
    g.setColorAt(1, QColor(10, 10, 14, 0))
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawPath(slanted(x0, x1))
    p.setBrush(accent)
    p.drawPath(slanted(x0, x0 + px * 0.16))                # the accent edge
    cc = QPointF(left + ch / 2, cy)                        # the crosshair
    p.setPen(QPen(accent, px * 0.11, Qt.SolidLine, Qt.FlatCap))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(cc, ch * 0.34, ch * 0.34)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        p.drawLine(QPointF(cc.x() + dx * ch * 0.18, cc.y() + dy * ch * 0.18),
                   QPointF(cc.x() + dx * ch * 0.5, cc.y() + dy * ch * 0.5))
    p.setPen(Qt.NoPen)
    p.setBrush(accent)
    p.drawEllipse(cc, px * 0.07, px * 0.07)
    path = QPainterPath()                                  # the word, with a hot glow
    path.setFillRule(Qt.WindingFill)       # variable fonts' overlapping strokes stay solid
    path.addText(QPointF(left + ch + px * 0.45, cy + fm.capHeight() / 2), f, text)
    halo = QColor(accent)
    halo.setAlpha(150)
    _glow(p, path, QRectF(r), halo, px * 0.25)
    p.setBrush(QColor("#fbfbfd"))
    p.drawPath(path)
    p.restore()


def draw_scene(p: QPainter, r: QRectF, t: float):
    """A made-up dark-fantasy scene at dusk: a ruined keep on the horizon, broken
    pillars, drifting fog and a bonfire with a sword in it, flickering."""
    w, h = r.width(), r.height()
    u = h / 100
    cx = r.center().x()
    horizon = r.top() + h * 0.64
    p.save()
    p.setClipRect(r)
    p.setPen(Qt.NoPen)
    sky = QLinearGradient(r.topLeft(), QPointF(r.left(), horizon))
    sky.setColorAt(0, QColor("#15171f"))
    sky.setColorAt(0.65, QColor("#2b2a33"))
    sky.setColorAt(1, QColor("#453a3a"))
    p.fillRect(QRectF(r.left(), r.top(), w, horizon - r.top()), sky)
    far = QPainterPath()                  # the distant keep, pale with distance
    far.moveTo(r.left(), horizon)
    for x, top in ((0.00, 8), (0.06, 8), (0.06, 14), (0.10, 14), (0.10, 9), (0.18, 9),
                   (0.18, 22), (0.195, 25), (0.21, 22), (0.21, 11), (0.30, 11), (0.33, 7),
                   (0.62, 7), (0.62, 17), (0.635, 30), (0.65, 17), (0.65, 12), (0.70, 12),
                   (0.70, 19), (0.74, 19), (0.74, 10), (0.86, 10), (0.88, 6), (1.0, 6)):
        far.lineTo(r.left() + w * x, horizon - u * top)
    far.lineTo(r.right(), horizon)
    far.closeSubpath()
    p.setBrush(QColor("#24232b"))
    p.drawPath(far)
    ground = QLinearGradient(QPointF(r.left(), horizon), r.bottomLeft())
    ground.setColorAt(0, QColor("#16161b"))
    ground.setColorAt(1, QColor("#060608"))
    p.fillRect(QRectF(r.left(), horizon, w, r.bottom() - horizon), ground)
    p.setBrush(QColor("#0c0c10"))          # near ruins: a broken pillar each side
    for side in (-1, 1):
        bx = cx + side * w * 0.36
        pw = u * 9
        top = horizon - u * (52 if side < 0 else 40)
        pillar = QPainterPath()
        pillar.moveTo(bx - pw / 2, r.bottom())
        pillar.lineTo(bx - pw / 2, top + u * 3)
        pillar.lineTo(bx - pw * 0.1, top)
        pillar.lineTo(bx + pw * 0.2, top + u * 4)
        pillar.lineTo(bx + pw / 2, top + u * 1.5)
        pillar.lineTo(bx + pw / 2, r.bottom())
        pillar.closeSubpath()
        p.drawPath(pillar)
        p.drawRect(QRectF(bx - pw * 0.7, horizon + u * 6, pw * 1.4, u * 4))
    for i in range(4):                     # fog, drifting
        y = horizon - u * (4 + 7 * i)
        x = r.left() + ((t * w * 0.02 * (i + 1) + i * w * 0.37) % (w * 1.6)) - w * 0.3
        fog = QRadialGradient(QPointF(0, 0), w * 0.35)
        fog.setColorAt(0, QColor(160, 165, 185, 30))
        fog.setColorAt(1, QColor(160, 165, 185, 0))
        p.save()
        p.translate(x, y)
        p.scale(1, u * 9 / (w * 0.35))    # squashed flat: an elliptical gradient
        p.setBrush(fog)
        p.drawEllipse(QPointF(0, 0), w * 0.35, w * 0.35)
        p.restore()
    # the bonfire: its glow on the ground, stones, a sword, flames and embers
    fu = u * 1.45
    fire = QPointF(cx, horizon + u * 22)
    flick = 0.9 + 0.1 * math.sin(t * 11) * math.sin(t * 6.3 + 1)
    glow = QRadialGradient(fire, fu * 32 * flick)
    glow.setColorAt(0, QColor(255, 150, 60, 120))
    glow.setColorAt(0.5, QColor(255, 110, 40, 40))
    glow.setColorAt(1, QColor(255, 100, 30, 0))
    p.setBrush(glow)
    p.drawEllipse(fire, fu * 32 * flick, fu * 32 * flick)
    p.setBrush(QColor("#1b1715"))
    for dx, s in ((-5.5, 3.0), (-2.2, 3.4), (1.5, 3.2), (4.8, 2.8), (-0.4, 2.6)):
        p.drawEllipse(QPointF(fire.x() + fu * dx, fire.y() + fu * 0.8), fu * s, fu * s * 0.55)
    sword = QPainterPath()
    sword.addRect(QRectF(-fu * 0.45, -fu * 16, fu * 0.9, fu * 16))     # blade
    sword.addRect(QRectF(-fu * 2.6, -fu * 16.8, fu * 5.2, fu * 0.9))   # crossguard
    sword.addRect(QRectF(-fu * 0.35, -fu * 20.5, fu * 0.7, fu * 3.8))  # grip
    sword.addEllipse(QPointF(0, -fu * 21), fu * 0.8, fu * 0.8)        # pommel
    p.save()
    p.translate(fire.x(), fire.y() - fu * 0.5)
    p.rotate(-8)
    p.setBrush(QColor("#2a2624"))
    p.drawPath(sword)
    p.restore()
    for i, (dx, hgt, wid, sp) in enumerate(((-2.6, 7, 2.2, 9), (2.4, 8, 2.3, 7.7),
                                            (0, 11, 3.2, 8.3), (-0.8, 6, 1.6, 12))):
        fh = fu * hgt * (0.82 + 0.18 * math.sin(t * sp + i * 1.7))
        fw = fu * wid
        bx = fire.x() + fu * dx
        tip = QPointF(bx + fu * 0.8 * math.sin(t * sp * 0.7 + i), fire.y() - fh)
        flame = QPainterPath()
        flame.moveTo(bx - fw, fire.y())
        flame.cubicTo(QPointF(bx - fw, fire.y() - fh * 0.5),
                      QPointF(tip.x() - fw * 0.2, tip.y() + fh * 0.3), tip)
        flame.cubicTo(QPointF(tip.x() + fw * 0.2, tip.y() + fh * 0.3),
                      QPointF(bx + fw, fire.y() - fh * 0.5), QPointF(bx + fw, fire.y()))
        flame.closeSubpath()
        fg = QLinearGradient(QPointF(0, fire.y()), QPointF(0, tip.y()))
        fg.setColorAt(0, QColor(255, 236, 170, 240))
        fg.setColorAt(0.45, QColor(255, 150, 50, 220))
        fg.setColorAt(1, QColor(220, 60, 20, 0))
        p.setBrush(fg)
        p.drawPath(flame)
    for i in range(14):                    # embers rising
        life = (t * 0.45 + i * 0.137) % 1.0
        ex = fire.x() + fu * (math.sin(i * 12.9) * 4 + math.sin(t * 2 + i) * 2 * life)
        ey = fire.y() - fu * (4 + life * 30)
        p.setBrush(QColor(255, 170 + i % 3 * 25, 80, int(230 * (1 - life))))
        p.drawEllipse(QPointF(ex, ey), fu * 0.3, fu * 0.3)
    vig = QRadialGradient(r.center(), max(w, h) * 0.75)
    vig.setColorAt(0.55, QColor(0, 0, 0, 0))
    vig.setColorAt(1, QColor(0, 0, 0, 190))
    p.setBrush(vig)
    p.drawRect(r)
    p.restore()


def draw_game(p: QPainter, r: QRectF, t: float):
    """The made-up game: the scene, and YOU DIED fading in over it at DIED_AT."""
    draw_scene(p, r, t)
    a = fade(t, DIED_AT, 1.2)
    if a > 0:
        p.fillRect(r, QColor(0, 0, 0, int(70 * a)))      # the screen dims as it comes up
        draw_banner(p, r, "YOU DIED", SOUL_RED, a, 1 + 0.05 * min(1.0, (t - DIED_AT) / 4))


def draw_card(p: QPainter, r: QRectF, t: float):
    """The Triggers tab's card for this trigger, as the app draws it."""
    s = r.width() / 520
    p.setPen(QPen(EDGE, 2 * s))
    p.setBrush(CARD)
    p.drawRoundedRect(r, 16 * s, 16 * s)
    pad = 18 * s
    # thumbnail: the picture it looks for
    th = QRectF(r.left() + pad, r.top() + pad, 120 * s, 64 * s)
    p.setPen(QPen(EDGE, 1.5 * s))
    p.setBrush(QColor("#08080b"))
    p.drawRoundedRect(th, 8 * s, 8 * s)
    p.save()
    clip = QPainterPath()
    clip.addRoundedRect(th, 8 * s, 8 * s)
    p.setClipPath(clip)
    draw_scene(p, th, 6.0)
    draw_banner(p, th, "YOU DIED", SOUL_RED, size=0.2, fill=0.78)
    p.restore()
    # name + state line
    x = th.right() + 16 * s
    f = QFont("Segoe UI")
    f.setPixelSize(int(24 * s))
    f.setBold(True)
    p.setFont(f)
    p.setPen(TEXT)
    p.drawText(QPointF(x, th.top() + 26 * s), "Died")
    f.setBold(False)
    f.setPixelSize(int(17 * s))
    p.setFont(f)
    if t >= PLAY_AT:
        state, col = "Played! 🔊  Sad Trombone", GREEN
    elif t >= SEEN_AT:
        state, col = "Seen! Playing in 0.5 s…", GREEN
    else:
        state, col = "Plays 0.5 s after it shows up", MUTED
    p.setPen(col)
    p.drawText(QPointF(x, th.top() + 56 * s), state)
    # match meter
    my = th.bottom() + 26 * s
    score = 0.12 + 0.03 * math.sin(t * 5)
    if t > DIED_AT:
        score = 0.12 + 0.84 * fade(t, DIED_AT, 0.8)
    p.setPen(MUTED)
    p.drawText(QPointF(r.left() + pad, my + 6 * s), "Match")
    bar = QRectF(r.left() + pad + 70 * s, my - 8 * s, r.width() - 2 * pad - 190 * s, 14 * s)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#2a2b37"))
    p.drawRoundedRect(bar, 7 * s, 7 * s)
    hit = score >= 0.8
    p.setBrush(GREEN if hit else ACCENT)
    p.drawRoundedRect(QRectF(bar.left(), bar.top(), bar.width() * score, bar.height()),
                      7 * s, 7 * s)
    p.setPen(QPen(TEXT, 2 * s))                               # the 80% needed mark
    p.drawLine(QPointF(bar.left() + bar.width() * 0.8, bar.top() - 4 * s),
               QPointF(bar.left() + bar.width() * 0.8, bar.bottom() + 4 * s))
    f.setBold(hit)
    p.setFont(f)
    p.setPen(GREEN if hit else TEXT)
    p.drawText(QPointF(bar.right() + 14 * s, my + 6 * s), f"now {round(score * 100)}%")


def caption(p: QPainter, r: QRectF, text: str, size: float, alpha: float = 1.0,
            color: QColor = TEXT, bold: bool = True):
    f = QFont("Segoe UI")
    f.setPixelSize(int(size))
    f.setBold(bold)
    p.setFont(f)
    path = QPainterPath()
    fm_lines = text.split("\n")
    line_h = size * 1.2
    y0 = r.center().y() - line_h * (len(fm_lines) - 1) / 2 + size * 0.35
    for i, line in enumerate(fm_lines):
        width = p.fontMetrics().horizontalAdvance(line)
        path.addText(QPointF(r.center().x() - width / 2, y0 + i * line_h), f, line)
    p.setPen(QPen(QColor(0, 0, 0, int(230 * alpha)), size * 0.16, Qt.SolidLine, Qt.RoundCap,
                  Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    c = QColor(color)
    c.setAlpha(int(255 * alpha))
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    p.drawPath(path)


def draw_logo(p: QPainter, c: QPointF, size: float):
    from soundboard import theme
    pm = theme.app_icon("#7c5cff", "#ff5c8a").pixmap(int(size), int(size))
    p.drawPixmap(QPointF(c.x() - size / 2, c.y() - size / 2), pm)


def frame(w: int, h: int, t: float, shot: QImage) -> QImage:
    img = QImage(w, h, QImage.Format_RGB888)
    img.fill(BG)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    vertical = h > w
    shake = 0.0
    if PLAY_AT <= t < PLAY_AT + 0.4:
        shake = math.sin((t - PLAY_AT) * 70) * (1 - (t - PLAY_AT) / 0.4) * w * 0.006
    if t < OUTRO_AT:
        game = QRectF(0, h * 0.18, w, w * 9 / 16 * 1.25) if vertical else QRectF(0, 0, w, h)
        p.save()
        p.translate(shake, 0)
        p.setClipRect(game)
        draw_game(p, game, t)
        p.restore()
        cw = w * (0.86 if vertical else 0.38)
        card = QRectF((w - cw) / 2 if vertical else w - cw - w * 0.03,
                      game.bottom() + h * 0.04 if vertical else h - cw * 0.31 - h * 0.05,
                      cw, cw * 0.31)
        a = fade(t, 1.2, 0.6)
        if a > 0:
            p.setOpacity(a)
            draw_card(p, card, t)
            p.setOpacity(1)
        if vertical:
            top = QRectF(0, h * 0.03, w, h * 0.13)
            caption(p, top, "my soundboard plays a sound\nwhen I die", w * 0.065,
                    fade(t, 0.2, 0.5))
            below = QRectF(0, card.bottom() + h * 0.03, w, h * 0.12)
            if t >= PLAY_AT:
                caption(p, below, "🎺 wah wah waaah", w * 0.07, fade(t, PLAY_AT, 0.3), GREEN)
            elif t >= 1.8:
                caption(p, below, "it watches the screen for\na picture you pick",
                        w * 0.05, fade(t, 1.8, 0.4), MUTED, bold=False)
        else:
            if t >= 0.2 and t < DIED_AT:
                caption(p, QRectF(0, h * 0.06, w, h * 0.12),
                        "Plays a sound when something shows up on screen", w * 0.032,
                        fade(t, 0.2, 0.5))
    else:
        # outro: the real Triggers tab and where to get it
        a = fade(t, OUTRO_AT, 0.5)
        p.setOpacity(a)
        if vertical:
            sw = w * 0.94
            sh = sw * shot.height() / shot.width()
            target = QRectF((w - sw) / 2, h * 0.30, sw, sh)
        else:
            sh = h * 0.60
            sw = sh * shot.width() / shot.height()
            target = QRectF((w - sw) / 2, h * 0.32, sw, sh)
        p.setPen(QPen(EDGE, 3))
        p.drawImage(target, shot)
        p.drawRect(target)
        draw_logo(p, QPointF(w / 2, h * (0.10 if vertical else 0.09)),
                  w * (0.14 if vertical else 0.06))
        caption(p, QRectF(0, h * (0.17 if vertical else 0.16), w, h * 0.06), "Onion Board",
                w * (0.085 if vertical else 0.045))
        caption(p, QRectF(0, h * (0.22 if vertical else 0.235), w, h * 0.05),
                "free soundboard for Windows", w * (0.05 if vertical else 0.026), 1, MUTED,
                bold=False)
        if vertical:
            caption(p, QRectF(0, target.bottom() + h * 0.03, w, h * 0.08),
                    "voice changer · text-to-speech\nscreen triggers · in-game overlay",
                    w * 0.045, 1, TEXT, bold=False)
            caption(p, QRectF(0, h * 0.86, w, h * 0.06), "link in bio 🧅", w * 0.07, 1, GREEN)
        p.setOpacity(1)
    p.end()
    return img


# --------------------------------------------------------------------------- sound

def trombone() -> np.ndarray:
    """The sad trombone: four falling notes, the last one wobbling."""
    notes = [(466.2, 0.42), (440.0, 0.42), (415.3, 0.42), (392.0, 1.5)]
    out = []
    for i, (f, d) in enumerate(notes):
        n = int(d * SR)
        t = np.arange(n) / SR
        vib = 1 + (0.012 * np.sin(2 * np.pi * 6 * t) * np.minimum(1, t / 0.3) if i == 3 else 0)
        slide = 1 - (0.06 * np.maximum(0, t - 0.9) if i == 3 else 0)
        phase = 2 * np.pi * np.cumsum(f * vib * slide) / SR
        tone = sum(np.sin(k * phase) / k ** 1.3 for k in range(1, 9))   # brassy
        env = np.minimum(1, t / 0.04) * np.minimum(1, (d - t) / 0.08)
        out.append(tone * env)
    y = np.concatenate(out)
    return (y / np.abs(y).max() * 0.6).astype(np.float32)


def soundtrack() -> np.ndarray:
    n = int(LENGTH * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(3)
    drone = 0.05 * (np.sin(2 * np.pi * 55 * t) + 0.5 * np.sin(2 * np.pi * 82.4 * t))
    wind = np.convolve(rng.standard_normal(n), np.ones(400) / 400, "same") * 0.35
    y = (drone + wind) * np.clip(1 - (t - OUTRO_AT) / 1.0, 0.25, 1)
    boom_at = int(DIED_AT * SR)                              # a low hit under YOU DIED
    bt = np.arange(int(1.5 * SR)) / SR
    y[boom_at:boom_at + len(bt)] += 0.5 * np.sin(2 * np.pi * 48 * bt) * np.exp(-bt * 3)
    tb = trombone()
    s = int(PLAY_AT * SR)
    y[s:s + len(tb)] += tb[:n - s]
    y = y / max(1.0, np.abs(y).max() / 0.9)
    return np.stack([y, y], 1).astype(np.float32)


# --------------------------------------------------------------------------- output

def render(path: Path, w: int, h: int, shot: QImage, wav: Path):
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{w}x{h}", "-r", str(FPS), "-i", "-", "-i", str(wav),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "medium",
           "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(path)]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(int(LENGTH * FPS)):
        img = frame(w, h, i / FPS, shot)
        bpl = img.bytesPerLine()
        buf = np.frombuffer(img.constBits(), np.uint8, count=bpl * h).reshape(h, bpl)
        ff.stdin.write(buf[:, :w * 3].tobytes())
    ff.stdin.close()
    if ff.wait():
        raise SystemExit(f"ffmpeg failed for {path}")
    print("wrote", path)


def gif(src: Path, dest: Path):
    """The wide clip's middle (the death and the trigger) as a small looping GIF."""
    filt = ("fps=10,scale=560:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=64"
            ":stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5"
            ":diff_mode=rectangle")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1.0", "-t",
                    str(OUTRO_AT - 1.0 + 2.5), "-i", str(src), "-vf", filt, "-loop", "0",
                    str(dest)], check=True)
    print("wrote", dest, f"({dest.stat().st_size // 1024} KB)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--gif", type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    QGuiApplication([])
    shot = QImage(str(ROOT / "docs" / "screenshots" / "triggers.png"))
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "track.wav"
        sf.write(wav, soundtrack(), SR)
        render(args.out / "onionboard-triggers-vertical.mp4", 1080, 1920, shot, wav)
        wide = args.out / "onionboard-triggers-wide.mp4"
        render(wide, 1280, 720, shot, wav)
    if args.gif:
        gif(wide, args.gif)


if __name__ == "__main__":
    main()
