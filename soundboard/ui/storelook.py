"""The Store tab's pictures: a sound's tile (an emoji picked from its name, tags and
category on a coloured square, with bars that bounce while its sample plays) and the
banner at the top (Bun in his headphones, the tab's title on a soft accent glow)."""
from __future__ import annotations

import re
import time
import zlib
from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QFrame, QWidget

from soundboard import store, theme

if TYPE_CHECKING:
    from soundboard.ui.bunnywidget import BunnyWidget

TILE = 44        # a row's picture, px square
BUN_ROOM = 470   # the banner hides Bun below this width (the title and buttons need it)

# a category's own emoji (and its tile's colour, by its place in store.CATS)
CAT_EMOJI = {"memes": "😂", "reactions": "😮", "games": "🎮", "movies": "🎬", "tv": "📺",
             "music": "🎵", "sports": "⚽", "viral": "🔥", "pranks": "🤡", "politics": "🏛️",
             "streamer": "📡", "esports": "🏆", "podcast": "🎙️", "spooky": "👻"}
FALLBACK = "🔊"

# words in a sound's name or tags -> its emoji; the first that matches wins, so the
# more telling words come first ("tavern crowd" is a tavern, not applause)
WORDS: tuple[tuple[str, str], ...] = (
    ("tavern|inn|pub|beer|ale", "🍺"), ("horn|airhorn|mlg|megaphone", "📢"),
    ("trombone|sad|cry|crying|sob", "😢"),
    ("fanfare|victory|win|winner|level up|achievement", "🏆"), ("bruh|bro", "😐"),
    ("vine boom|boom|explosion|explode|nuke|bomb", "💥"), ("laugh|lol|haha|giggle", "🤣"),
    ("scream|yell|shout|aaa", "😱"), ("fart|toot", "💨"), ("burp", "🤢"),
    ("knock|door|creak", "🚪"), ("ghost|haunt|spooky|horror|scary|jumpscare", "👻"),
    ("zombie|monster|growl|roar", "🧟"), ("keyboard|typing|type", "⌨️"),
    ("phone|ring|ringtone|call", "📱"), ("alarm|siren|alert|warning", "🚨"),
    ("bell|ding|chime", "🔔"), ("clap|applause|cheer|crowd", "👏"),
    ("drum|rimshot|ba dum|badum", "🥁"), ("guitar|riff", "🎸"), ("piano", "🎹"),
    ("sax|saxophone|jazz", "🎷"), ("trumpet", "🎺"), ("violin", "🎻"),
    ("song|music|beat|tune|remix|dj", "🎵"),
    ("sword|blade|slash|clang", "⚔️"), ("magic|spell|wizard|fireball", "✨"),
    ("dragon", "🐉"), ("gun|shot|shoot|pew|laser|blaster", "🔫"),
    ("car|engine|race|drift|vroom", "🏎️"), ("train", "🚂"), ("plane|jet", "✈️"),
    ("rain|thunder|storm|lightning", "⛈️"), ("wind|whoosh|swoosh", "🌬️"),
    ("water|splash|bubble|drip", "💧"), ("fire|flame|burn", "🔥"),
    ("cat|meow", "🐱"), ("dog|bark|woof", "🐶"), ("cow|moo", "🐮"), ("duck|quack", "🦆"),
    ("owl|hoot", "🦉"), ("goat", "🐐"), ("chicken|rooster|cluck", "🐔"),
    ("bird|tweet|chirp", "🐦"), ("wolf|howl", "🐺"), ("pig|oink", "🐷"),
    ("frog|ribbit", "🐸"), ("monkey|ape", "🐵"),
    ("wow|omg|whoa|surprise|shock", "😮"), ("no|nope|wrong|error|fail", "❌"),
    ("yes|correct|right|ding ding", "✅"), ("money|cash|coin|cha ching|kaching", "💰"),
    ("kiss|love|heart|romance", "❤️"), ("sus|among us|impostor|imposter", "🔴"),
    ("hello|hi|hey|greet", "👋"), ("bye|goodbye|outro", "🫡"),
    ("sleep|snore|yawn", "😴"), ("eat|chew|crunch|food|nom", "🍔"),
    ("goal|football|soccer|ball", "⚽"), ("basketball|dunk", "🏀"),
    ("whistle|referee", "🏁"), ("wrestle|wrestling|bonk|punch|hit|slap|smack", "👊"),
    ("ninja", "🥷"), ("robot|beep|boop|computer", "🤖"), ("alien|ufo", "👽"),
    ("clock|tick|timer|countdown", "⏰"), ("camera|shutter|photo", "📸"),
    ("game over|gameover|you died|death|dead", "💀"), ("coin|mario|8 bit|8-bit|retro", "🕹️"),
    ("drama|dun dun|suspense", "🎭"), ("news|breaking", "📰"),
    ("podcast|intro|mic", "🎙️"), ("stream|twitch|chat", "📡"),
)
_WORD_RES = [(re.compile(r"(?<![a-z])(?:" + words + r")(?![a-z])"), e) for words, e in WORDS]


def sound_emoji(s: store.Sound) -> str:
    """The emoji a sound's tile shows: from a word in its name, then its tags, then its
    category's, else a speaker."""
    for text in (s.name, " ".join(s.tags)):
        low = (text or "").lower()
        for rx, emoji in _WORD_RES:
            if rx.search(low):
                return emoji
    return CAT_EMOJI.get(s.cat, FALLBACK)


def tile_hue(s: store.Sound) -> int:
    """The tile's colour, 0..359: the category's own, else one from the sound's id (the
    same sound always gets the same colour)."""
    if s.cat in store.CATS:
        return round(store.CATS.index(s.cat) * 360 / len(store.CATS) + 12) % 360
    return zlib.crc32(s.id.encode()) % 360


def emoji_font(px: int) -> QFont:
    f = QFont("Segoe UI Emoji")
    f.setPixelSize(px)
    return f


class SoundTile(QWidget):
    """A sound's picture: its emoji on a rounded, coloured square. While its sample plays
    (`set_playing`) three bars bounce over the bottom of it. A click is the row's play."""

    def __init__(self, s: store.Sound, on_click=None, parent=None):
        super().__init__(parent)
        self.emoji = sound_emoji(s)
        self.hue = tile_hue(s)
        self._click = on_click
        self._playing = False
        self._badge = False   # a play mark in its corner: it's the row's only play button
        self._t0 = time.monotonic()
        self._tick = QTimer(self, interval=40)
        self._tick.timeout.connect(self.update)
        self.setFixedSize(TILE, TILE)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        if on_click is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    @property
    def playing(self) -> bool:
        return self._playing

    def set_playing(self, on: bool):
        self._playing = on
        if on:
            self._t0 = time.monotonic()
            self._tick.start()
        else:
            self._tick.stop()
        self.update()

    def set_badge(self, on: bool):
        self._badge = on
        self.update()

    def hideEvent(self, e):
        self._tick.stop()   # (shown again while playing, the next set_playing starts it)
        super().hideEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._click is not None:
            self._click()
            e.accept()
            return
        super().mousePressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        light = theme.is_light()
        top = QColor.fromHsl(self.hue, 170, 150 if light else 118)
        bottom = QColor.fromHsl((self.hue + 28) % 360, 190, 118 if light else 82)
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, top)
        g.setColorAt(1, bottom)
        path = QPainterPath()
        path.addRoundedRect(r, r.width() * 0.26, r.width() * 0.26)
        p.fillPath(path, g)
        # a soft shine across the top: the tile looks like a button, not a sticker
        shine = QLinearGradient(r.topLeft(), r.center())
        shine.setColorAt(0, QColor(255, 255, 255, 70))
        shine.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillPath(path, shine)
        p.setClipPath(path)
        if self._playing:
            p.fillRect(r, QColor(0, 0, 0, 70))
        p.setFont(emoji_font(round(r.height() * (0.46 if self._playing else 0.56))))
        er = r.adjusted(0, -r.height() * 0.16, 0, 0) if self._playing else r
        p.drawText(er, Qt.AlignmentFlag.AlignCenter, self.emoji)
        if self._playing:   # three bouncing bars along the bottom
            t = time.monotonic() - self._t0
            bw, gap = r.width() * 0.12, r.width() * 0.07
            x = r.center().x() - (3 * bw + 2 * gap) / 2
            for i in range(3):
                k = 0.35 + 0.65 * abs(_wave(t * (5.5 + i * 1.7) + i * 1.3))
                h = r.height() * 0.3 * k
                bar = QRectF(x + i * (bw + gap), r.bottom() - 5 - h, bw, h)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 235))
                p.drawRoundedRect(bar, bw / 2, bw / 2)
        elif self._badge:   # a small round play mark, bottom right
            d = r.width() * 0.4
            c = QRectF(r.right() - d - 2, r.bottom() - d - 2, d, d)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 150))
            p.drawEllipse(c)
            tri = QPainterPath()
            k = d * 0.22
            tri.moveTo(c.center().x() - k * 0.8, c.center().y() - k)
            tri.lineTo(c.center().x() + k * 1.1, c.center().y())
            tri.lineTo(c.center().x() - k * 0.8, c.center().y() + k)
            tri.closeSubpath()
            p.fillPath(tri, QColor(255, 255, 255))
        p.end()


def _wave(x: float) -> float:
    """A smooth -1..1 wobble (two sines, so the bars never move in step)."""
    import math
    return 0.6 * math.sin(x) + 0.4 * math.sin(x * 2.3 + 0.7)


class StoreBanner(QFrame):
    """The card at the top of the tab, on a soft glow from the accent to the logo's second
    colour. `bun` (if any) sits at its start and goes when the card is too narrow for
    him."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.bun: QWidget | None = None

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.bun is not None:
            self.bun.setVisible(self.width() >= BUN_ROOM)

    def paintEvent(self, e):
        super().paintEvent(e)   # the card itself, from the style sheet
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        a = QColor(theme.T.get("accent", "#7c5cff"))
        b = QColor(theme.T.get("accent2", theme.T.get("accent", "#ff5ca8")))
        a.setAlpha(46)
        b.setAlpha(22)
        g = QLinearGradient(r.topLeft(), r.topRight())
        g.setColorAt(0, a)
        g.setColorAt(0.55, b)
        g.setColorAt(1, QColor(0, 0, 0, 0))
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        p.fillPath(path, g)
        p.end()


def make_bun(height: int = 62) -> BunnyWidget:
    """Bun in his headphones for the banner: he bobs and fidgets, hops when clicked, and
    the tab cheers him up (`cheer`) or saddens him (his `sad`) as things happen."""
    from soundboard.ui.bunnywidget import BunnyWidget

    class StoreBun(BunnyWidget):
        def mousePressEvent(self, ev):
            if ev.button() == Qt.MouseButton.LeftButton:
                self.cheer()
            super().mousePressEvent(ev)

    bun = StoreBun("headphones", height=height, pad=12, dances=True)
    bun.setCursor(Qt.CursorShape.PointingHandCursor)
    return bun


def emoji_icon(emoji: str, size: int = 16):
    """An emoji as a button's icon (a category chip's), drawn at 2x for a sharp edge."""
    from PySide6.QtGui import QIcon, QPixmap
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2.0)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setFont(emoji_font(round(size * 0.9)))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, emoji)
    p.end()
    return QIcon(pm)
