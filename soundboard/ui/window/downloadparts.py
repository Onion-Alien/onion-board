"""The download card's parts (ui/window/downloadbar.py): its smooth progress bar, the
title label, the kind tag, the tick / cross flash when a pick ends, a pick's title
and source in words, the pictures' rounded corners and stand-in, and how strong the
accent glow is on this theme."""
from __future__ import annotations

import math
import re
import time
import urllib.parse

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QWidget

from soundboard.ui.kit import theme
from soundboard.i18n import _
from soundboard.ui.kit import icons
from soundboard.ui.kit.pixels import snap_to_pixels
from soundboard.ui.settings import lite


class SmoothProgressBar(QWidget):
    """A sleek 6px progress bar that only fills forward (soundboard/core/jobprogress.py). While
    a step has nothing to measure (the link looked up, the audio converted) a faint glint
    runs along the empty part, so it's plainly busy, never a block that looks full."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(6)
        self._busy = True
        self._progress = 0.0          # 0.0 .. 1.0
        self._t0 = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(1000 // 24)
        self._timer.timeout.connect(self.update)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_busy(self, on: bool):
        """The glint over the empty part: on while a step can't say how far it is."""
        if on and not self._busy:
            self._t0 = time.monotonic()
        self._busy = on
        if on and self.isVisible():
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def set_progress(self, frac: float, busy: bool = False):
        self._progress = max(0.0, min(1.0, float(frac)))
        self.set_busy(busy)

    def showEvent(self, ev):
        super().showEvent(ev)
        if self._busy:
            self._timer.start()

    def hideEvent(self, ev):
        self._timer.stop()
        super().hideEvent(ev)

    def sizeHint(self) -> QSize:
        return QSize(180, 6)

    def paintEvent(self, _e):
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        rad = r.height() / 2
        p.setPen(Qt.PenStyle.NoPen)
        groove = QColor(theme.T.get("groove", theme.mix(theme.T["card"], theme.T["text"], 0.12)))
        p.setBrush(groove)
        p.drawRoundedRect(r, rad, rad)

        accent = QColor(theme.T.get("accent", "#7c5cff"))
        w = r.width() * self._progress
        if w > 0:
            p.setBrush(accent)
            p.drawRoundedRect(QRectF(r.left(), r.top(), max(r.height(), w), r.height()),
                              rad, rad)
        if self._busy:
            # a soft glint sweeping the empty part, faded at both ends: busy, not further
            empty = QRectF(r.left() + w, r.top(), r.width() - w, r.height())
            if empty.width() > r.height():
                k = ((time.monotonic() - self._t0) / 1.6) % 1.0
                gw = max(r.height() * 4, empty.width() * 0.3)
                gx = empty.left() - gw + (empty.width() + gw) * k
                g = QLinearGradient(gx, 0, gx + gw, 0)
                clear, lit = QColor(accent), QColor(accent)
                clear.setAlpha(0)
                lit.setAlpha(110)
                g.setColorAt(0.0, clear)
                g.setColorAt(0.5, lit)
                g.setColorAt(1.0, clear)
                p.save()
                clip = QPainterPath()
                clip.addRoundedRect(r, rad, rad)
                p.setClipPath(clip)
                p.setClipRect(empty, Qt.ClipOperation.IntersectClip)
                p.setBrush(g)
                p.drawRect(QRectF(gx, r.top(), gw, r.height()))
                p.restore()
        p.end()


class ElideLabel(QLabel):
    """A one-line label that shrinks with its box and ends in … when the text doesn't fit."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def sizeHint(self) -> QSize:
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 2,
                     super().sizeHint().height())

    def paintEvent(self, _e):
        p = QPainter(self)
        snap_to_pixels(p)
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, self.width())
        self.style().drawItemText(p, self.rect(),
                                  int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                                  self.palette(), self.isEnabled(), text,
                                  QPalette.ColorRole.WindowText)
        p.end()


class KindTag(QWidget):
    """What a pick will do, as a status (an icon and a few words in the accent colour,
    no box): a filled "Add as sound" pill looked like a button to press."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("kindtag")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.icon = QLabel()
        self.icon.setFixedSize(12, 12)
        self.text = QLabel()
        self.text.setObjectName("kindtag")
        lay.addWidget(self.icon)
        lay.addWidget(self.text)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.kind, self.queued = "", False

    def set_kind(self, kind: str, queued: bool = False):
        self.kind, self.queued = kind, queued
        if queued:   # only Add as sound waits in the queue (Play once never does)
            text = _("Waiting to add")
            tip = _("Becomes a new sound on your board after the ones before it. "
                    "Nothing to press.")
        elif kind == "play":
            text = _("Playing once")
            tip = _("Plays once when it's ready. It isn't added to your sounds.")
        else:
            text = _("Adding to sounds")
            tip = _("Becomes a new sound on your board when it's ready. Nothing to press.")
        self.text.setText(text)
        self.setToolTip(tip)
        self.retheme()

    def retheme(self):
        icons.set_label_icon(self.icon, "play" if self.kind == "play" and not self.queued
                             else "plus", "live_text", size=12)


class Outcome(QWidget):
    """How a download ended, flashed for a moment: a small green tick in front of the
    picture (or Bun) when it worked, a red ✗ there when it didn't (the bar's background
    turns red then too: DownloadBar.paintEvent, under the words). No badge behind the
    mark; it pops in and fades straight away. Clicks go through it."""

    SHOW_MS = 1000
    MARK = 20.0          # the tick's or ✗'s size, px

    def __init__(self, bar: QFrame):
        super().__init__(bar)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.ok = True
        self.spot = QRectF()   # the picture's box, in the bar's pixels (empty: no badge)
        self._k = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(self.SHOW_MS)
        self._anim.valueChanged.connect(self._step)
        self._anim.finished.connect(self.hide)
        self.hide()

    def play(self, ok: bool, spot: QRectF):
        self.ok, self.spot = ok, spot
        bar = self.parentWidget()
        assert bar is not None   # made on the bar
        self.setGeometry(bar.rect())
        self.raise_()
        self.show()
        self._anim.stop()
        self._anim.start()

    def stop(self):
        self._anim.stop()
        self.hide()

    def running(self) -> bool:
        return self._anim.state() == QVariantAnimation.State.Running

    def k(self) -> float:
        return self._k

    def _step(self, k):
        if lite.on():   # (lite mode: there whole and still, then gone at once)
            k = 0.5 if k < 0.95 else 1.0
            if k == self._k:
                return
        self._k = float(k)
        self.update()
        bar = self.parentWidget()
        if not self.ok and bar is not None:
            bar.update()   # its red background fades with it

    def paintEvent(self, _e):
        k = self._k
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        red = QColor(theme.status("error"))
        if self.spot.isEmpty():
            p.end()
            return
        pop = min(1.0, k / 0.15)                               # pops in, then fades out
        fade = min(1.0, (1.0 - k) / 0.4)
        u = self.MARK / 2 * (0.6 + 0.4 * pop)
        c = self.spot.center()
        path = QPainterPath()
        if self.ok:
            path.moveTo(c.x() - 0.8 * u, c.y() + 0.05 * u)
            path.lineTo(c.x() - 0.25 * u, c.y() + 0.6 * u)
            path.lineTo(c.x() + 0.85 * u, c.y() - 0.6 * u)
        else:
            a = 0.62 * u
            path.moveTo(c.x() - a, c.y() - a)
            path.lineTo(c.x() + a, c.y() + a)
            path.moveTo(c.x() - a, c.y() + a)
            path.lineTo(c.x() + a, c.y() - a)
        p.setBrush(Qt.BrushStyle.NoBrush)
        edge = QColor(theme.T["bg"]).darker(140)   # a thin dark edge: shows on any picture
        edge.setAlphaF(0.7 * fade)
        p.setPen(QPen(edge, 5.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                      Qt.PenJoinStyle.RoundJoin))
        p.drawPath(path)
        mark = QColor(theme.status("ok") if self.ok else red)
        mark.setAlphaF(fade)
        p.setPen(QPen(mark, 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                      Qt.PenJoinStyle.RoundJoin))
        p.drawPath(path)
        p.end()


AUDIO_EXTS = (".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus", ".webm", ".mp4")


def pretty_title(title: str) -> str:
    """A title as a person would write it: a file name loses its extension, and a name
    made of underscores or dashes ("my_cool-song") becomes words ("My Cool Song").
    A real title with spaces keeps its dashes ("Artist - Song")."""
    t = (title or "").strip()
    if t.lower().endswith(AUDIO_EXTS):
        t = t.rsplit(".", 1)[0]
    if " " not in t:   # a slug or file name
        t = t.replace("_", " ").replace("-", " ")
    else:
        t = t.replace("_", " ")
    t = re.sub(r"\s+", " ", t).strip()
    if t and t == t.lower():
        t = t.title()
    return t


def source_of(url: str) -> tuple[str, str]:
    """(icon name, site name) for the page a sound comes from."""
    host = (urllib.parse.urlsplit(url).hostname or "").lower().removeprefix("www.")

    def under(*domains):
        return any(host == d or host.endswith("." + d) for d in domains)
    if host == "music.youtube.com":
        return "ytmusic", "YouTube Music"
    if under("youtube.com", "youtu.be", "youtube-nocookie.com"):
        return "youtube", "YouTube"
    if under("soundcloud.com", "snd.sc"):
        return "soundcloud", "SoundCloud"
    if under("tiktok.com"):
        return "tiktok", "TikTok"
    if under("myinstants.com"):
        return "myinstants", "Myinstants"
    return "browser", host


def _rounded(pm: QPixmap, w: int, h: int, radius: int, dpr: float) -> QPixmap:
    """`pm` filled into a w x h box (cropped, not squashed) with rounded corners."""
    out = QPixmap(round(w * dpr), round(h * dpr))
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
    p.setClipPath(path)
    src = pm.scaled(round(w * dpr), round(h * dpr), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation)
    p.drawPixmap(QRectF(0, 0, w, h), src, QRectF(
        (src.width() - w * dpr) / 2, (src.height() - h * dpr) / 2, w * dpr, h * dpr))
    p.end()
    return out


def _placeholder(w: int, h: int, radius: int, dpr: float) -> QPixmap:
    """The picture for a sound with none of its own (an MP3 link, a search card whose
    art hasn't come yet): the theme's accent in a soft gradient with a sound wave on it."""
    T = theme.T
    out = QPixmap(round(w * dpr), round(h * dpr))
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(0, 0, w, h)
    grad.setColorAt(0, QColor(theme.mix(T["card"], T["accent"], 0.75)))
    grad.setColorAt(1, QColor(theme.mix(T["card"], T["accent"], 0.25)))
    p.setBrush(grad)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(0, 0, w, h), radius, radius)
    side = round(h * 0.6)
    glyph = icons.pixmap("wave", round(side * dpr), T["live_text"])
    glyph.setDevicePixelRatio(dpr)
    p.drawPixmap(round((w - side) / 2), round((h - side) / 2), glyph)
    p.end()
    return out


SOFT = 0.5   # the glow's strength when the theme's cards aren't its accent's colour


def theme_matches_accent() -> bool:
    """The theme's own cards are a shade of its accent: Lava's dark orange cards and
    orange accent, Ocean's navy and cyan. Then the banner's accent glow is the theme's
    look and shows in full; on Dark (near-black cards, a purple accent), Light or Royal
    (gold on violet) the same glow was all anyone saw, so it shows at half."""
    card, accent = QColor(theme.T["card"]), QColor(theme.T["accent"])
    hc, ha = card.hsvHueF(), accent.hsvHueF()
    if hc < 0 or ha < 0:   # a grey: no colour to match
        return False
    colour = card.hsvSaturationF() * card.valueF()   # how far from grey the cards are
    presence = max(0.0, min(1.0, (colour - 0.04) / 0.1))
    same_hue = max(0.0, math.cos(abs(hc - ha) * 2 * math.pi))   # 1 = the same colour
    return presence * same_hue >= 0.6


def glow() -> float:
    """The accent glow's strength: 1 on a theme it matches, else SOFT."""
    return 1.0 if theme_matches_accent() else SOFT
