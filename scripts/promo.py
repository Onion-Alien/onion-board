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
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QImage, QLinearGradient,  # noqa: E402
                           QPainter, QPainterPath, QPen, QRadialGradient)

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
RED = QColor("#a3161f")


def ease(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def fade(t: float, start: float, dur: float) -> float:
    return ease((t - start) / dur)


# --------------------------------------------------------------------------- drawing

def draw_game(p: QPainter, r: QRectF, t: float):
    """A made-up dark-fantasy scene: fog, a ruined arch, a bonfire glow."""
    g = QLinearGradient(r.topLeft(), r.bottomLeft())
    g.setColorAt(0, QColor("#1b1d24"))
    g.setColorAt(0.6, QColor("#101116"))
    g.setColorAt(1, QColor("#08080b"))
    p.fillRect(r, g)
    cx, base = r.center().x(), r.top() + r.height() * 0.72
    w = r.width()
    # the arch
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#1f2129"))
    arch = QPainterPath()
    arch.addRect(QRectF(cx - w * 0.30, base - w * 0.55, w * 0.08, w * 0.55))
    arch.addRect(QRectF(cx + w * 0.22, base - w * 0.48, w * 0.08, w * 0.48))
    arch.addEllipse(QRectF(cx - w * 0.30, base - w * 0.75, w * 0.60, w * 0.45))
    inner = QPainterPath()
    inner.addEllipse(QRectF(cx - w * 0.22, base - w * 0.67, w * 0.44, w * 0.40))
    inner.addRect(QRectF(cx - w * 0.22, base - w * 0.47, w * 0.44, w * 0.47))
    p.drawPath(arch.subtracted(inner))
    # the ground
    p.setBrush(QColor("#0b0c10"))
    p.drawRect(QRectF(r.left(), base, w, r.bottom() - base))
    # a bonfire's glow, flickering
    flick = 0.85 + 0.15 * math.sin(t * 13) * math.sin(t * 7.3)
    glow = QRadialGradient(QPointF(cx, base), w * 0.25 * flick)
    glow.setColorAt(0, QColor(255, 140, 50, 150))
    glow.setColorAt(1, QColor(255, 120, 40, 0))
    p.setBrush(glow)
    p.drawEllipse(QPointF(cx, base), w * 0.25 * flick, w * 0.25 * flick)
    p.setBrush(QColor(255, 190, 90))
    p.drawEllipse(QPointF(cx, base - w * 0.01), w * 0.012, w * 0.02 * flick)
    # drifting fog
    for i in range(5):
        y = base - w * (0.1 + 0.08 * i)
        x = (cx - w + ((t * 30 * (i + 1)) % (w * 2)))
        fog = QRadialGradient(QPointF(x, y), w * 0.4)
        fog.setColorAt(0, QColor(150, 160, 180, 22))
        fog.setColorAt(1, QColor(150, 160, 180, 0))
        p.setBrush(fog)
        p.drawEllipse(QPointF(x, y), w * 0.4, w * 0.12)
    # YOU DIED
    a = fade(t, DIED_AT, 1.2)
    if a > 0:
        band = QRectF(r.left(), r.center().y() - w * 0.09, w, w * 0.18)
        bg = QLinearGradient(band.topLeft(), band.bottomLeft())
        bg.setColorAt(0, QColor(0, 0, 0, 0))
        bg.setColorAt(0.5, QColor(0, 0, 0, int(200 * a)))
        bg.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(band, bg)
        f = QFont("Georgia")
        f.setPixelSize(int(w * 0.105))
        f.setLetterSpacing(QFont.PercentageSpacing, 108)
        p.setFont(f)
        c = QColor(RED)
        c.setAlpha(int(255 * a))
        p.setPen(c)
        grow = 1 + 0.04 * (t - DIED_AT) / 4
        p.save()
        p.translate(band.center())
        p.scale(grow, grow)
        p.drawText(QRectF(-w / 2, -band.height() / 2, w, band.height()), Qt.AlignCenter,
                   "YOU DIED")
        p.restore()


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
    f = QFont("Georgia")
    f.setPixelSize(int(17 * s))
    p.setFont(f)
    p.setPen(RED)
    p.drawText(th, Qt.AlignCenter, "YOU DIED")
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
