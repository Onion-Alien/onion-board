"""The Sounds tab's web search: press Enter in "Search sounds" (or the Search
button next to it) and this list takes the pad grid's place. It's a plain list of
hits (thumbnail, title, channel, length) from the site searches in ytdl.SOURCES
(YouTube, YouTube Music, SoundCloud, TikTok sounds, Myinstants), with no web page
and no video. While one runs the list makes way for a loading view: Bun or Hoot
(picked at random each time) over a sliding bar and "Searching YouTube for ...".
Play plays one once and Add adds it as a
pad; both hand the page to the link bar (ui/linkbar.py), which downloads just its
audio. Sites without a search (Instagram, X…) work by pasting a link into the
search box instead.
"""
from __future__ import annotations

import html
import logging
import math
import random
import threading

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, QSize, QUrl, Qt, Signal
from PySide6.QtGui import (QColor, QIcon, QPainter, QPainterPath, QPixmap,
                           QTextLayout)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (QBoxLayout, QButtonGroup, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from soundboard import net, netlog, quality, theme, ytdl
from soundboard.bunny import H as BUN_H
from soundboard.bunny import W as BUN_W
from soundboard.ui import busy, icons
from soundboard.ui.bunnywidget import BunnyWidget
from soundboard.ui.owl import H as OWL_H
from soundboard.ui.owl import W as OWL_W
from soundboard.ui.owl import OwlWidget
from soundboard.ui.panel import CardGrid, HoverCard, RoundedFrame
from soundboard.ui.responsive import FitWidth
from soundboard.ui.widgets import LoadingBar, fmt_time, paint_now_playing
from soundboard import errors
from soundboard.i18n import _, ngettext

log = logging.getLogger(__name__)

THUMB_W, THUMB_H = 128, 72   # the pictures' shape (16:9); they fill the card's width
CARD_MIN_W = 210             # results are cards, as many across as fit at this width
LINK_CARD_MAX_W = 820        # a pasted link's card: picture beside the words, this wide at most
TIPS = {"youtube": _("Search YouTube"),
        "ytmusic": _("Search YouTube Music: songs, the official versions"),
        "soundcloud": _("Search SoundCloud"),
        "tiktok": _("Find TikTok sounds (TikTok's own search needs an account, so this "
                    "looks for them on YouTube, where they get reposted)"),
        "myinstants": _("Search Myinstants: short meme sound buttons")}


def fmt_count(n: int) -> str:
    """1234 -> "1.2K", 4553746 -> "4.6M" (YouTube's way of rounding)."""
    for size, unit in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if n >= size:
            v = n / size
            return (f"{v:.1f}".rstrip("0").rstrip(".") if v < 10 else f"{v:.0f}") + unit
    return str(n)


def _count(kind: str, n: int, shown: str) -> str:
    """"1.2K views": `n` picks the word's form, `shown` is the number as written."""
    if kind == "views":
        return ngettext("{count} view", "{count} views", n, count=shown)
    if kind == "likes":
        return ngettext("{count} like", "{count} likes", n, count=shown)
    return ngettext("{count} comment", "{count} comments", n, count=shown)


def stats_text(r: ytdl.Result) -> tuple[str, str]:
    """(the card's line, its tooltip) for a hit's views, likes and comments, as its
    search entry gave them: nothing for what it didn't say. No video page is fetched
    for more (a look-up per hit is scraping, and the kind that gets you bot-checked)."""
    parts, tip = [], []
    for n, kind in ((r.views, "views"), (r.likes, "likes"), (r.comments, "comments")):
        if n is not None:
            parts.append(_count(kind, n, fmt_count(n)))
            tip.append(_count(kind, n, f"{n:,}"))
    return " · ".join(parts), ", ".join(tip)


class _BusyOwl(OwlWidget):
    """Hoot on the job: bright-eyed and tufts up instead of moping, scanning left and
    right for your sound, no dozing or begging."""

    def __init__(self, height: int, parent=None):
        super().__init__(height, lines=(), joy=(), parent=parent, left=0, right=0)
        self._next_act = math.inf
        self.setToolTip("")

    def busy(self) -> bool:
        return True   # always scanning: never the slow idle frames

    def pose(self) -> dict:
        d = super().pose()
        d["sad"] = 0.0
        d["tufts"] = -8 + 3 * math.sin(self.t * 1.1)
        d["look"] = 0.8 * math.sin(self.t * 1.6)     # scanning the results
        d["look_y"] = 0.25
        return d


class SearchingView(QWidget):
    """What the results area shows while a search runs: a mascot (Bun with his
    headphones on, or Hoot keeping watch; a coin toss each time) over a loading bar
    and the "Searching ... for ..." line, all centred. Laid out by hand so it never
    asks the window for room: the mascot shrinks with the space and goes when
    there's too little, then the bar, leaving just the line."""

    MASCOTS = ("bunny", "owl")
    BIG, SMALL = 104, 44       # mascot heights, px
    GAP = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self.kind = ""
        self.mascot: QWidget | None = None
        self._rng = random.Random()
        self.bar = LoadingBar(self)
        self.label = QLabel(self)
        self.label.setTextFormat(Qt.RichText)
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignCenter)
        self.hide()

    def sizeHint(self) -> QSize:
        return QSize(320, 220)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, self.label.sizeHint().height())

    def start(self, text: str):
        """Show `text` (rich text) under a freshly picked mascot and start the bar."""
        self.label.setText(text)
        kind = self._rng.choice(self.MASCOTS)
        if kind != self.kind or self.mascot is None:
            if self.mascot is not None:
                self.mascot.hide()
                self.mascot.deleteLater()
            self.mascot = self._make(kind)
            self.kind = kind
        self.bar.start()
        self.show()
        self._place()

    def stop(self):
        self.bar.stop()
        self.hide()            # the mascot's own timer stops with it

    def running(self) -> bool:
        return self.bar.running()

    def _make(self, kind: str) -> QWidget:
        if kind == "owl":
            m = _BusyOwl(self.BIG, parent=self)
        else:
            m = BunnyWidget("headphones", height=self.BIG, pad=22, parent=self)
        return m

    def _fit_mascot(self, h: int) -> QSize:
        """Draw the mascot `h` px tall; returns the box it then needs."""
        m = self.mascot
        if isinstance(m, OwlWidget):
            m.owl_h, m.top = h, round(h * 0.34)
            return QSize(round(h * OWL_W / OWL_H) + 8, h + m.top + 8)
        m.bun_h, m.pad = h, round(h * 0.22)
        return QSize(round(h * BUN_W / BUN_H) + 2 * m.pad + 20, h + 2 * m.pad)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._place()

    def _place(self):
        w, h, gap = self.width(), self.height(), self.GAP
        tw = max(40, min(w - 24, 460))
        th = self.label.heightForWidth(tw)
        th = th if th > 0 else self.label.sizeHint().height()
        bw = max(0, min(260, w - 48))
        show_bar = bw >= 60 and h >= th + gap + 6
        need = th + (gap + 6 if show_bar else 0)
        room = h - need - gap               # what's left above for the mascot
        box = QSize()
        if self.mascot is not None:
            # biggest that fits (its box is about 1.5x its height), or none at all
            mh = min(self.BIG, int(room / 1.5))
            if mh >= self.SMALL:
                box = self._fit_mascot(mh)
                if box.width() > w - 8 or box.height() > room:
                    box = QSize()
            self.mascot.setVisible(not box.isEmpty())
        total = need + (box.height() + gap if not box.isEmpty() else 0)
        y = max(0, (h - total) // 2)
        if not box.isEmpty():
            self.mascot.setGeometry((w - box.width()) // 2, y, box.width(), box.height())
            y += box.height() + gap
        self.bar.setVisible(show_bar)
        if show_bar:
            self.bar.setGeometry((w - bw) // 2, y, bw, 6)
            y += 6 + gap
        self.label.setGeometry((w - tw) // 2, y, tw, th)


class Thumb(QWidget):
    """A result's picture: fills the card's width at 16:9 with rounded corners, a
    wave icon until the picture arrives."""

    def __init__(self):
        super().__init__()
        self._pm: QPixmap | None = None
        self._scaled: QPixmap | None = None   # _pm at this size: not scaled per paint
        self.now = ""   # "playing" / "paused" while it's the one in the player
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        return round(w * THUMB_H / THUMB_W)

    def sizeHint(self) -> QSize:
        return QSize(THUMB_W, THUMB_H)

    def minimumSizeHint(self) -> QSize:
        return QSize(THUMB_W, THUMB_H)

    def set_pixmap(self, pm: QPixmap):
        self._pm, self._scaled = pm, None
        self.update()

    def has_picture(self) -> bool:
        return self._pm is not None

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), 8, 8)
        p.setClipPath(path)
        if self._pm is None:
            p.fillPath(path, QColor(128, 128, 128, 40))   # reads on light and dark
            # the theme's colour now (it was fixed when the card was made), centred by
            # its size on screen, not its pixel count (off-centre on a scaled screen)
            icons.icon("wave", "muted").paint(p, QRect((w - 32) // 2, (h - 32) // 2, 32, 32))
        else:
            # scaled to the screen's real pixels, so it isn't stretched (soft) at 125 %
            dpr = self.devicePixelRatioF()
            pw, ph = round(w * dpr), round(h * dpr)
            pm = self._scaled
            if pm is None or pm.devicePixelRatio() != dpr or not (
                    pm.width() >= pw and pm.height() >= ph and
                    (pm.width() == pw or pm.height() == ph)):
                pm = self._scaled = self._pm.scaled(pw, ph, Qt.KeepAspectRatioByExpanding,
                                                    Qt.SmoothTransformation)
                pm.setDevicePixelRatio(dpr)
            size = pm.deviceIndependentSize()
            p.drawPixmap(QPointF((w - size.width()) / 2, (h - size.height()) / 2), pm)
        if self.now:
            self._paint_now(p, w, h)
        p.end()

    def _paint_now(self, p: QPainter, w: int, h: int):
        """The one in the player: the picture dims and a big equalizer (bouncing, or
        still while paused) with "Playing" / "Paused" sits on it."""
        p.fillRect(QRectF(0, 0, w, h), QColor(0, 0, 0, 120))
        paused = self.now == "paused"
        eq = min(44.0, h * 0.42)
        box = QRectF((w - eq) / 2, h / 2 - eq * 0.75, eq, eq)
        if paused:   # a pause sign: still bars read as dots
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#ffffff"))
            bw = eq * 0.24
            for x in (box.center().x() - bw * 1.4, box.center().x() + bw * 0.4):
                p.drawRoundedRect(QRectF(x, box.top() + eq * 0.1, bw, eq * 0.8), 3, 3)
        else:
            paint_now_playing(p, box, QColor("#ffffff"))
        f = p.font()
        f.setBold(True)
        f.setPointSizeF(9)
        p.setFont(f)
        word = _("Paused") if paused else _("Playing")
        pill_w = p.fontMetrics().horizontalAdvance(word) + 18
        pill = QRectF((w - pill_w) / 2, h / 2 + eq * 0.35, pill_w, 20)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.T["accent"]))
        p.drawRoundedRect(pill, 10, 10)
        p.setPen(QColor(theme.T["on_accent"]))
        p.drawText(pill, Qt.AlignCenter, word)

    def set_now(self, now: str):
        changed, self.now = now != self.now, now
        if changed or now == "playing":
            self.update()   # bouncing bars: every tick while it plays


class ClampLabel(QLabel):
    """Text (bold by default) wrapped onto at most `lines` lines, the last ending in "…" when it
    doesn't fit (the full text in the tooltip). Always that tall, so cards in a row
    line up."""

    def __init__(self, text: str, lines: int = 2, bold: bool = True):
        super().__init__()
        self.full, self.lines = text, lines
        self._wrap: tuple = (None, [])   # (key, lines) from _wrapped()
        f = self.font()
        f.setBold(bold)
        self.setFont(f)
        self.setToolTip(text)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._fit()

    def set_full(self, text: str, tip: str = ""):
        self.full = text
        self.setToolTip(tip or text)
        self.update()

    def _fit(self):
        self.setFixedHeight(self.fontMetrics().lineSpacing() * self.lines + 2)

    def changeEvent(self, e):
        # the theme's font comes with its style sheet, after __init__ (and changes with
        # the theme): sized by the font it had then, the last line lost its descenders
        super().changeEvent(e)
        if e.type() in (QEvent.FontChange, QEvent.StyleChange):
            self._fit()

    def _wrapped(self) -> list[tuple[str, float]]:
        """The lines to draw and their tops. Kept by (text, width, font): a page of
        cards repaints on every hover and scroll, and wrapping is the slow part."""
        key = (self.full, self.width(), self.font().key(), self.lines)
        if self._wrap[0] == key:
            return self._wrap[1]
        fm = self.fontMetrics()
        layout = QTextLayout(self.full, self.font())
        layout.beginLayout()
        y, shown = 0.0, []
        while len(shown) < self.lines:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(self.width())
            shown.append((line.textStart(), line.textLength(), y))
            y += fm.lineSpacing()
        layout.endLayout()
        out = []
        for i, (start, length, ly) in enumerate(shown):
            text = self.full[start:start + length].rstrip()
            if i == len(shown) - 1 and start + length < len(self.full):
                text = fm.elidedText(self.full[start:], Qt.ElideRight, self.width())
            out.append((text, ly))
        self._wrap = (key, out)
        return out

    def paintEvent(self, e):
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        p.setFont(self.font())
        ascent = self.fontMetrics().ascent()
        for text, ly in self._wrapped():
            p.drawText(QPointF(0, ly + ascent), text)
        p.end()


class StatsLabel(ClampLabel):
    """Compact metadata with the same painted symbols as the app's controls."""

    def __init__(self):
        super().__init__("", lines=1, bold=False)
        self.fields = []

    def set_stats(self, result):
        self.fields = [(icon, fmt_count(n))
                       for n, icon in ((result.views, "triggers"), (result.likes, "like"),
                                       (result.comments, "speech"))
                       if n is not None]
        text, tip = stats_text(result)
        self.set_full(text, tip)
        self.setAccessibleName(text)
        self.setVisible(bool(text))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setFont(self.font())
        p.setPen(QColor(theme.T["muted"]))
        fm = self.fontMetrics()
        side = max(12, min(16, fm.height()))
        x = 0
        for icon, text in self.fields:
            room = self.width() - x - side - 5
            if room < fm.horizontalAdvance("…"):
                break
            icons.icon(icon, "muted").paint(p, x, (self.height() - side) // 2, side, side)
            x += side + 5
            shown = fm.elidedText(text, Qt.ElideRight, room)
            p.drawText(QPointF(x, (self.height() - fm.height()) / 2 + fm.ascent()), shown)
            x += fm.horizontalAdvance(shown) + 14
        p.end()


class ResultRow(HoverCard):
    """One hit as a card: picture, title, channel and length, Play and Add. `wide`: a
    pasted link's one card, picture beside the words (stacked when there's no room)."""
    play = Signal(object)
    add = Signal(object)
    WIDE_MIN_W = 560      # narrower than this, a wide card stacks like the others
    WIDE_THUMB_W = 340
    WIDE_STACKED_THUMB_H = 190

    def __init__(self, r: ytdl.Result, wide: bool = False):
        super().__init__()
        self.result = r
        self.wide = wide
        self._side: bool | None = None   # a wide card: picture beside the words (resizeEvent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setProperty("own_space", True)   # Space plays / pauses this one (spacekey.py)
        self.setAccessibleName(r.title)
        self.thumb = Thumb()
        self.title = ClampLabel(r.title)
        if wide:   # the style sheet sets the font: a setFont() would be undone
            self.title.setStyleSheet("font-size:12.5pt; font-weight:700;")
        # channel names come from YouTube: painted as plain text
        self.sub = ClampLabel(" · ".join(x for x in (r.channel, fmt_time(r.seconds)
                                                       if r.seconds else "") if x),
                              lines=1, bold=False)
        self.sub.setObjectName("muted")
        self.stats = StatsLabel()
        self.stats.setObjectName("muted")
        self.stats.set_stats(r)
        self.btn_play = QPushButton(_("Play"))
        self.btn_play.setObjectName("cardplay")
        self.btn_play.setToolTip(_("Download its audio and play it once (it isn't kept)"))
        icons.set_icon(self.btn_play, "play", "live_text", size=14)
        self.btn_play.clicked.connect(lambda: self.play.emit(self.result))
        self.btn_add = QPushButton(_("Add"))
        self.btn_add.setObjectName("cardadd")
        self.btn_add.setToolTip(_("Download its audio and add it to your sounds"))
        icons.set_icon(self.btn_add, "plus", "on_accent", size=14)
        self.btn_add.clicked.connect(lambda: self.add.emit(self.result))
        for b in (self.btn_play, self.btn_add):
            b.setCursor(Qt.PointingHandCursor)
            if wide:   # as wide as their words (and the download's), not the whole card
                b.setMinimumWidth(140)
                b.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            else:
                b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.fill = -1.0        # the download's 0..1 (or -1: none), shown in its button
        self._tip = ""          # its words: the buttons' tooltip while it downloads

        self.text_box = QVBoxLayout()
        self.text_box.setSpacing(6)
        for w in (self.title, self.sub, self.stats):
            self.text_box.addWidget(w)
        self.text_box.addStretch(1)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self.btn_play)
        buttons.addWidget(self.btn_add)
        if wide:
            buttons.addStretch(1)
        self.text_box.addLayout(buttons)
        box = QBoxLayout(QBoxLayout.TopToBottom, self)
        box.setContentsMargins(10, 10, 10, 10) if wide else box.setContentsMargins(8, 8, 8, 8)
        box.setSpacing(14 if wide else 8)
        box.addWidget(self.thumb)
        box.addLayout(self.text_box, 1)
        self._style()
        self._release = {}      # "play" / "add" -> busy.hold's release while it's fetched
        self._added = False
        self._locked = False
        self.now = ""           # "playing" / "paused": it's the one in the player
        self.setProperty("playing", False)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(_("Double-click to play"))

    def _style(self):
        """The card's two buttons: Play a soft accent tint, Add the filled accent; the
        one downloading fills with the accent as it goes; Added goes quiet."""
        T = theme.T
        base = "border-radius:9px; padding:8px 12px; font-weight:600;"
        tint, edge = theme.mix(T["card"], T["accent"], 0.2), theme.mix(T["card"], T["accent"], 0.5)
        tint_hi = theme.mix(T["card"], T["accent"], 0.32)
        styles = {
            "play": (f"QPushButton {{ {base} background:{tint}; border:1px solid {edge};"
                     f" color:{T['live_text']}; }}"
                     f"QPushButton:hover {{ background:{tint_hi}; }}"),
            "add": (f"QPushButton {{ {base} background:{T['accent']};"
                    f" border:1px solid {T['accent']};"
                    f" color:{T['on_accent']}; }}"
                    f"QPushButton:hover {{ background:{T['accent_hover']}; }}"),
        }
        # waiting for another card's download: greyed, like any busy button
        waiting = (f"QPushButton[busy=\"true\"] {{ background:{T['btn']}; border:1px solid"
                   f" {T['border']}; color:{T['muted']}; }}")
        styles = {k: v + waiting for k, v in styles.items()}
        added = (f"QPushButton {{ {base} background:transparent; border:1px solid "
                 f"{T['live_border']}; color:{T['live_text']}; }}")
        for kind, b in (("play", self.btn_play), ("add", self.btn_add)):
            css = added if kind == "add" and self._added_shown() else styles[kind]
            if kind in getattr(self, "_release", {}) and self.fill >= 0:
                # the download fills it from the left: accent over the card colour
                f = min(max(self.fill, 0.0), 1.0)
                on, off = T["accent"], theme.mix(T["card"], T["accent"], 0.12)
                grad = (f"qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {on}, stop:{f:.3f} {on},"
                        f" stop:{min(f + 0.001, 1):.3f} {off}, stop:1 {off})")
                css = (f"QPushButton {{ {base} background:{grad}; border:1px solid {edge};"
                       f" color:{T['text_hi']}; }}")
            if b.styleSheet() != css:
                b.setStyleSheet(css)

    def _added_shown(self) -> bool:
        return getattr(self, "_added", False)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.wide:   # beside each other when there's room, stacked when not
            side = self.width() >= self.WIDE_MIN_W
            if side != self._side:
                self._side = side
                self.layout().setDirection(QBoxLayout.LeftToRight if side
                                           else QBoxLayout.TopToBottom)
                if side:
                    self.thumb.setFixedWidth(self.WIDE_THUMB_W)
                    self.thumb.setMaximumHeight(16777215)
                else:   # a narrow window: the buttons stay in sight (the picture is cropped)
                    self.thumb.setMinimumWidth(0)
                    self.thumb.setMaximumWidth(16777215)
                    self.thumb.setMaximumHeight(self.WIDE_STACKED_THUMB_H)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        return self.layout().heightForWidth(w)

    def mouseDoubleClickEvent(self, e):
        if not busy.is_busy(self.btn_play):
            self.play.emit(self.result)
        super().mouseDoubleClickEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            if not busy.is_busy(self.btn_play):
                self.play.emit(self.result)
            e.accept()
            return
        super().keyPressEvent(e)

    def _btn(self, kind: str) -> QPushButton:
        return self.btn_add if kind == "add" else self.btn_play

    def set_now(self, now: str):
        """"playing" / "paused" while it's the one in the player, "" when it isn't:
        the picture shows it, the card is outlined and Play becomes Pause / Resume."""
        self.thumb.set_now(now)
        if now == self.now:
            return
        self.now = now
        self.setProperty("playing", bool(now))
        self.style().unpolish(self)
        self.style().polish(self)
        if "play" not in self._release:   # not while its button shows the download
            self.btn_play.setText({"playing": _("Pause"), "paused": _("Resume")}.get(
                now, _("Play")))
            icons.set_icon(self.btn_play, "pause" if now == "playing" else "play",
                           "live_text", size=14)
        self.btn_play.setToolTip(_("Pause it") if now == "playing" else
                                 _("Carry on playing it") if now == "paused" else
                                 _("Download its audio and play it once (it isn't kept)"))

    def set_busy(self, kind: str):
        """Its audio is being fetched: that button shows how far, filling up as it
        downloads, and takes no clicks until set_done."""
        if kind in self._release or (kind == "add" and self._added):
            return
        btn = self._btn(kind)
        if self._locked:
            busy.set_busy(btn, False)
        if not self._release:
            self.fill = 0.0
            self._tip = _("Preparing audio download · 0%")
        text = (_("Processing…") if self._tip == _("Processing audio…") else
                (_("Adding… {pct:.0f}%", pct=self.fill * 100) if kind == "add" else
                 _("Loading… {pct:.0f}%", pct=self.fill * 100))
                if self.fill > 0 else _("Preparing… 0%"))
        self._release[kind] = busy.hold(btn, text)
        btn.setToolTip(self._tip)
        self._style()

    def set_progress(self, frac: float):
        """0..1 of its audio downloaded, or below 0 while it's being converted."""
        if not self._release:
            return
        if frac < 0:
            self._tip = _("Processing audio…")
            self.fill = 1.0
        else:
            self.fill = max(self.fill, min(1.0, frac))
            self._tip = _("Downloading audio · {value:.0f}%", value=self.fill * 100)
        for kind in self._release:
            word = _("Adding…") if kind == "add" else _("Loading…")
            btn = self._btn(kind)
            btn.setText(_("Processing…") if frac < 0 else f"{word} {self.fill * 100:.0f}%")
            btn.setToolTip(self._tip)
        self._style()

    def set_done(self, kind: str, ok: bool):
        release = self._release.pop(kind, None)
        if not self._release:
            self.fill = -1.0
        if release is None:
            self._style()
            return
        if kind == "add" and ok:
            release()
            self._added = True
            self.btn_add.setIcon(QIcon())          # not "+ ✓ Added"
            self.btn_add.setText(_("✓ Added"))     # added once is enough
            self.btn_add.setToolTip(_("It's in your sounds now"))
            busy.set_busy(self.btn_add, True)
        else:
            release(None if ok else (_("Didn't add") if kind == "add" else _("Didn't play")))
            if self._locked:
                busy.set_busy(self._btn(kind), True)
            if kind == "play" and self.now:   # it started before the button let go
                now, self.now = self.now, ""
                self.set_now(now)
        if kind == "add" and not ok:
            self.btn_add.setToolTip(_("Download its audio and add it to your sounds"))
        elif kind == "play":
            now, self.now = self.now, None   # its tooltip again, for what it's doing now
            self.set_now(now)
        self._style()

    def set_locked(self, on: bool):
        """Another card's download is running: this one's buttons wait for it (one at a
        time, so a click never cancels the one before it)."""
        if on == self._locked:
            return
        self._locked = on
        for kind in ("play", "add"):
            if kind in self._release or (kind == "add" and self._added):
                continue
            busy.set_busy(self._btn(kind), on)
        self.setToolTip(_("Wait for the other download to finish") if on
                        else _("Double-click to play"))

    def set_thumb(self, pm: QPixmap):
        self.thumb.set_pixmap(pm)


class SearchResults(RoundedFrame):
    """`play(Result)` / `add(Result)` when a row's button is pressed; `closed()`
    when its "My sounds" back button is (the owner shows its pads again). The site
    buttons in the header pick where the search goes and re-run it there."""
    play = Signal(object)
    add = Signal(object)
    closed = Signal()
    _done = Signal(int, object, str)   # worker -> UI: (search number, results, error)

    def __init__(self):
        super().__init__()
        self.query = ""
        self.link = ""          # a pasted link shown as its own card (show_link), not a search
        self.source = "youtube"
        self._gen = 0
        self._rows: list[ResultRow] = []
        self._fetching: dict[str, set[str]] = {}   # url -> {"play", "add"} downloading
        self.net = QNetworkAccessManager(self)
        net.apply_qt(self.net, "sounds_web")   # thumbnails: Settings > Privacy & security
        self._done.connect(self._on_done)

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(6)
        head = QHBoxLayout()
        back = self.btn_back = QPushButton(_("Back to my sounds"))
        back.setObjectName("backhome")   # stands out: the way out of the results
        back.setCursor(Qt.PointingHandCursor)
        icons.set_icon(back, "back", "danger_text", size=18)
        back.clicked.connect(self.close_results)
        head.addWidget(back)
        head.addSpacing(8)
        self.site_btns: dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for key, (name, _prefix) in ytdl.SOURCES.items():
            b = QPushButton(name)
            b.setObjectName("small")
            b.setCheckable(True)
            b.setChecked(key == self.source)
            b.setToolTip(TIPS.get(key, f"Search {name}"))
            b.clicked.connect(lambda _c=False, k=key: self.set_source(k))
            group.addButton(b)
            head.addWidget(b)
            self.site_btns[key] = b
        head.addStretch(1)
        v.addLayout(head)
        self.title = QLabel()
        self.title.setTextFormat(Qt.RichText)
        self.title.setWordWrap(True)
        errors.linkify(self.title)   # an error's "Report it" link
        v.addWidget(self.title)
        # Tor mode, after the site turned Tor away even over new routes: only this click
        # runs the search without Tor (ytdl.TorBlocked)
        self.direct_btn = QPushButton(_("Search this without Tor"))
        self.direct_btn.setToolTip(_("Run just this search straight from the site, not through "
                                     "Tor: the site will see your own address"))
        self.direct_btn.clicked.connect(self._without_tor)
        self.direct_btn.hide()
        row = QHBoxLayout()
        row.addWidget(self.direct_btn)
        row.addStretch(1)
        v.addLayout(row)
        self.loading = SearchingView()      # takes the list's place while searching
        self.spinner = self.loading         # start / stop / running()
        v.addWidget(self.loading, 1)
        self.list = FitWidth()   # the cards re-flow to the width they get
        lv = QVBoxLayout(self.list)
        lv.setContentsMargins(0, 0, 6, 0)
        self.link_row = QHBoxLayout()   # a pasted link's one wide card
        self.link_row.addStretch(1)
        lv.addLayout(self.link_row)
        self.rows = CardGrid(min_w=CARD_MIN_W, gap=10)
        lv.addLayout(self.rows)
        lv.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(self.list)
        scroll.setFrameShape(QFrame.NoFrame)
        v.addWidget(scroll, 1)
        self.scroll = scroll
        self.hide()
        self.follow_switches()
        net.on_change(self.follow_switches)

    def follow_switches(self):
        """Settings > Privacy & security: a site switched off has its button greyed
        (saying why), and searching moves to one that's on. With finding sounds online
        switched off altogether, open results close."""
        for key, b in self.site_btns.items():
            ok = ytdl.site_allowed(key)
            b.setEnabled(ok)
            b.setToolTip(TIPS.get(key, f"Search {ytdl.SOURCES[key][0]}") if ok
                         else net.off_message(ytdl.site_feature(key)))
        if not ytdl.site_allowed(self.source):
            on = [k for k in self.site_btns if ytdl.site_allowed(k)]
            if on:
                self.set_source(on[0])
            elif not self.isHidden():
                self.close_results()

    @staticmethod
    def available() -> bool:
        """Can anything be searched online at all (else the bar searches only the
        board)?"""
        return any(ytdl.site_allowed(k) for k in ytdl.SOURCES)

    @property
    def site(self) -> str:
        return ytdl.SOURCES[self.source][0]

    def set_source(self, key: str):
        """Search `key` (a ytdl.SOURCES key) from now on, re-running the current search."""
        if key not in ytdl.SOURCES:
            return
        self.site_btns[key].setChecked(True)
        if key != self.source:
            self.source = key
            if self.query and not self.isHidden():
                self.search(self.query)

    def search(self, query: str, direct: bool = False) -> bool:
        query = " ".join(query.split())
        if not query or not ytdl.site_allowed(self.source):
            return False
        self.query = query
        self.link = ""
        self._show_sites(True)
        self._gen += 1
        self._clear()
        where = _("TikTok sounds") if self.source == "tiktok" else self.site
        netlog.cause(ytdl.FEATURE, f"You searched {where} for {netlog.quoted(query)}"
                     + (" (without Tor)" if direct else ""))
        text = (_("Searching TikTok sounds for <b>{query}</b>…", query=html.escape(query))
                if self.source == "tiktok" else
                _("Searching {where} for <b>{query}</b>…", where=where, query=html.escape(query)))
        self.title.setText(text)
        self._loading(True, text)
        self.show()
        self.direct_btn.hide()
        threading.Thread(target=self._work, args=(self._gen, query, self.source, direct),
                         daemon=True, name="web-search").start()
        return True

    def show_link(self, url: str, direct: bool = False) -> bool:
        """A pasted link: look it up (nothing downloaded) and show it as one card, to
        play or add like a search hit. False when its site is switched off."""
        if not ytdl.site_allowed(url):
            return False
        if url == self.link and not direct and not self.isHidden() and (
                self._rows or self.loading.running()):
            return True   # already showing (Enter after the paste looked it up)
        self.query = self.link = url
        self._show_sites(False)   # the site buttons pick where a search goes: not a link
        self._gen += 1
        self._clear()
        netlog.cause(ytdl.FEATURE, "You pasted a link: looking up its name, picture and "
                                   "length" + (" (without Tor)" if direct else ""))
        host = html.escape(url.split("/")[2].removeprefix("www.") if "//" in url else url)
        text = _("Looking up <b>{host}</b>…", host=host)
        self.title.setText(text)
        self._loading(True, text)
        self.show()
        self.direct_btn.hide()
        threading.Thread(target=self._work_link, args=(self._gen, url, direct),
                         daemon=True, name="link-lookup").start()
        return True

    def _show_sites(self, on: bool):
        for b in self.site_btns.values():
            b.setVisible(on)

    def _without_tor(self):
        if self.link:
            self.show_link(self.link, direct=True)
        else:
            self.search(self.query, direct=True)

    def close_results(self):
        self._gen += 1       # a search still running is ignored when it lands
        self._loading(False)
        self._clear()
        self.link = ""
        self.hide()
        self.closed.emit()

    def _loading(self, on: bool, text: str = ""):
        """The loading view in place of the title and list (on), or those back."""
        for w in (self.title, self.scroll):
            w.setVisible(not on)
        if on:
            self.loading.start(text)
        else:
            self.loading.stop()

    def mark(self, url: str, kind: str, ok: bool | None = None):
        """A row's Play / Add: busy (ok None) while its audio is fetched, then done.
        Meanwhile the other rows' buttons wait: the link bar does one link at a time,
        and a second pick used to replace the first, which then never played."""
        if ok is None:
            self._fetching.setdefault(url, set()).add(kind)
        elif url in self._fetching:
            self._fetching[url].discard(kind)
            if not self._fetching[url]:
                del self._fetching[url]
        for r in self._rows:
            if r.result.url == url:
                if ok is None:
                    r.set_busy(kind)
                else:
                    r.set_done(kind, ok)
        self._lock_rows()

    def show_now(self, url: str, now: str):
        """The player has `url` loaded ("playing" / "paused"), or nothing from here
        (url ""): its card says so."""
        for r in self._rows:
            r.set_now(now if url and r.result.url == url else "")

    def progress(self, url: str, frac: float):
        """The link bar's download of `url`: 0..1, or below 0 while it's converted."""
        for r in self._rows:
            if r.result.url == url:
                r.set_progress(frac)

    def _lock_rows(self):
        for r in self._rows:
            r.set_locked(bool(self._fetching) and r.result.url not in self._fetching)

    def _clear(self):
        """Off the screen now, not when Qt gets round to deleting them: a pasted link's
        one card showed after the last search's cards until then."""
        for r in self._rows:
            r.hide()
            self.rows.removeWidget(r)
            self.link_row.removeWidget(r)
            r.deleteLater()
        self._rows = []

    def _work(self, gen: int, query: str, source: str, direct: bool = False):
        try:
            more = {"direct": True} if direct else {}   # the user's "without Tor" click
            self._done.emit(gen, ytdl.search(query, source=source, **more), "")
        except ytdl.TorBlocked as e:   # offered without Tor, never done unasked
            log.info("%s search turned away over Tor", source)
            self._done.emit(gen, "blocked", html.escape(str(e)))
        except Exception as e:  # noqa: BLE001 - shown in the panel
            log.info("%s search failed for %r: %s", source, query, e)
            # rich text: the plain words, and a "Report it" link when it's one for us
            self._done.emit(gen, [], errors.html(e, where=f"Searching {source}"))

    def _work_link(self, gen: int, url: str, direct: bool):
        try:
            self._done.emit(gen, [ytdl.lookup(url, **({"direct": True} if direct else {}))], "")
        except ytdl.TorBlocked as e:
            log.info("link look-up turned away over Tor")
            self._done.emit(gen, "blocked", html.escape(str(e)))
        except Exception as e:  # noqa: BLE001 - shown in the panel
            log.info("link look-up failed for %s: %s", url, e)
            self._done.emit(gen, [], errors.html(e, where="Looking up a link"))

    def _on_done(self, gen: int, results, err: str):
        if gen != self._gen:
            return
        self._loading(False)
        q = html.escape(self.query)
        if err:
            red = theme.status("error")
            if self.link:
                why = _("Can't use this link: {error}", error=err)   # err: rich text
                self.title.setText(f"<span style='color:{red}'>{why}</span>")
            else:
                self.title.setText(_("<span style='color:{red}'>Couldn't search {site}: {err}"
                                     "</span>", red=red, site=self.site, err=err))  # from _work
            self.direct_btn.setVisible(results == "blocked")
            return
        if not results:
            self.title.setText(_("No {site} results for <b>{q}</b>.", site=self.site, q=q))
            return
        self.title.hide()   # the cards say it all; the title is for "no results" / errors
        for r in results:
            row = ResultRow(r, wide=bool(self.link))
            row.play.connect(self.play)
            row.add.connect(self.add)
            if self.link:   # one video: one big card, not a grid of one
                row.setMaximumWidth(LINK_CARD_MAX_W)
                self.link_row.insertWidget(0, row, 10)   # all of it, up to the cap
            else:
                self.rows.addWidget(row)
            self._rows.append(row)
            if not quality.current.web_extras or not r.thumb:   # Settings > Data & quality
                continue
            reply = self.net.get(QNetworkRequest(QUrl(r.thumb)))
            reply.finished.connect(lambda reply=reply, row=row, g=gen: self._on_thumb(
                reply, row, g))
        self._lock_rows()

    def _on_thumb(self, reply, row: ResultRow, gen: int):
        data = reply.readAll()
        reply.deleteLater()
        pm = QPixmap()
        if gen == self._gen and row in self._rows and pm.loadFromData(data):
            row.set_thumb(pm)
