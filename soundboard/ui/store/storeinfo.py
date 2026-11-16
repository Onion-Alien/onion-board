"""A Store line's facts (`InfoLabel`): where the sound is from, music or a sound effect,
how long it is and when it came, each with its picture, in columns that line up down
the list. A narrower line drops the age, then the words, and keeps the length longest."""
from __future__ import annotations

import time

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter

from soundboard.core.trash import ago
from soundboard.i18n import _
from soundboard.online import store
from soundboard.ui.kit import icons, theme
from soundboard.ui.kit.pixels import snap_to_pixels
from soundboard.ui.sounds.ytlabels import ClampLabel

GAP = 16                      # between two columns
ICON_GAP = 5                  # a picture and its word
SIDE = 14                     # a picture
LEAST = 2 * SIDE + GAP        # its narrowest: the source's and the kind's pictures
SOURCE_MAX = 120              # the source's word at its widest (a long name ends in "…")
MUSIC_FROM = 30               # seconds: longer than this is music, whatever its category
SITE_ICONS = ("youtube", "ytmusic", "tiktok", "soundcloud", "twitch", "myinstants")


def length_text(secs: float) -> str:
    """5s, 35s, 2m 1s, 1h 4m."""
    n = max(1, round(secs))
    if n < 60:
        return _("{s}s", s=n)
    if n < 3600:
        return _("{m}m {s}s", m=n // 60, s=n % 60) if n % 60 else _("{m}m", m=n // 60)
    return _("{h}h {m}m", h=n // 3600, m=n % 3600 // 60)


def is_music(s: store.Sound) -> bool:
    return s.cat == "music" or s.secs > MUSIC_FROM


def kind_of(s: store.Sound) -> tuple[str, str]:
    """(picture, word): music or a sound effect."""
    return ("music", _("Music")) if is_music(s) else ("wave", _("Sound effect"))


def source_of(s: store.Sound) -> tuple[str, str]:
    """(picture, word): the site the server brought it in from, who made it, the site a
    shared link is on, or a player's own file."""
    from soundboard.sounds import sourceinfo
    site = sourceinfo.site_of(s.link) if s.is_link else None
    if s.source and site:
        return (site[0] if site[0] in SITE_ICONS else "browser"), site[1]
    if s.author:
        return "onion", s.author
    if site:
        return (site[0] if site[0] in SITE_ICONS else "link"), _("{site} link", site=site[1])
    return "person", _("Player")


class InfoLabel(ClampLabel):
    """One line's facts, painted: [site] Myinstants   [notes] Music   [clock] 3m 32s
    12 days ago. `full` (its tooltip and what a screen reader says) is the whole
    sentence, the category too."""

    _widths: dict = {}   # (font, language) -> the columns' widths

    def __init__(self, s: store.Sound, said: str):
        super().__init__(said, lines=1, bold=False)
        self.sound = s
        self._said = said        # "From Myinstants", "Shared by a player"…
        self._age = ""
        self.with_len = bool(s.secs)   # (the list's: no line has one, no column for it)
        self.setAccessibleName(said)

    def set_when(self, cat: str, created: int):
        """Its category and when it came."""
        s = self.sound
        self._age = ago(created) if created else ""
        text = " · ".join(w for w in (self._said, cat if cat != kind_of(s)[1] else "",
                                      kind_of(s)[1], length_text(s.secs) if s.secs else "",
                                      self._age) if w)
        self.set_full(text, text)
        self.setAccessibleName(text)

    def set_with_len(self, on: bool):
        if on != self.with_len:
            self.with_len = on
            self.update()

    # ------------------------------------------------------------------ sizes
    def _bold(self) -> QFont:
        f = QFont(self.font())
        f.setWeight(QFont.Weight.DemiBold)
        return f

    def _cols(self) -> tuple[int, int, int, int]:
        """The words' widths (source, kind, length, age): the same on every line, so the
        columns line up. From the longest words there can be, in the app's language."""
        key = (self.font().key(), _("Sound effect"), _("Player"))
        got = InfoLabel._widths.get(key)
        if got is None:
            fm, bold = self.fontMetrics(), QFontMetrics(self._bold())
            now = time.time()
            ages = [ago(now - n, now) for n in (0, 59 * 60, 3600, 2 * 3600, 5 * 3600, 23 * 3600,
                                               86400, 2 * 86400, 5 * 86400, 365 * 86400)]
            sources = ["Myinstants", "Onion Board", _("Player"),
                       _("{site} link", site="YouTube"), _("{site} link", site="SoundCloud")]
            got = (min(SOURCE_MAX, max(fm.horizontalAdvance(t) for t in sources)),
                   max(fm.horizontalAdvance(t) for t in (_("Music"), _("Sound effect"))),
                   max(bold.horizontalAdvance(length_text(n)) for n in (59, 3599, 35999)),
                   max(fm.horizontalAdvance(t) for t in ages))
            InfoLabel._widths[key] = got
        return got

    def _levels(self) -> list[tuple[int, tuple[bool, bool, bool, bool]]]:
        """What a line shows as it gets narrower, widest first: (its width, (the age,
        the kind's word, the source's word, the length)). The last, the two pictures
        alone, is its least."""
        src, kind, length, age = self._cols()
        pic = SIDE + ICON_GAP
        out = []
        for show in ((True, True, True, True), (False, True, True, True),
                     (False, False, True, True), (False, False, False, True),
                     (False, False, False, False)):
            with_age, kind_word, src_word, with_len = show
            w = (pic + (src if src_word else -ICON_GAP) + GAP
                 + pic + (kind if kind_word else -ICON_GAP) + GAP
                 + (pic + length + GAP if with_len and self.with_len else 0)
                 + (age + GAP if with_age else 0) - GAP)
            out.append((w, show))
        return out


    def full_width(self) -> int:
        return self._levels()[0][0]

    def fit(self, room: int) -> int:
        """The widest of its looks that fits `room` (its least when none does)."""
        for w, _show in self._levels():
            if w <= room:
                return max(self.minimumWidth(), w)
        return self.minimumWidth()

    # ------------------------------------------------------------------ painting
    def paintEvent(self, e):
        show = next((lv for w, lv in self._levels() if w <= self.width()), None)
        s = self.sound
        p = QPainter(self)
        snap_to_pixels(p)
        fm = self.fontMetrics()
        side, base = SIDE, fm.ascent()
        top = (fm.height() - side) // 2 + 1
        src_w, kind_w, len_w, _age_w = self._cols()
        muted, x = QColor(theme.T["muted"]), 0

        def cell(icon: str, colour: str, text: str, width: int, ink=muted, font=None):
            nonlocal x
            icons.icon(icon, colour).paint(p, x, top, side, side)
            x += side
            if width:
                p.setFont(font or self.font())
                p.setPen(ink)
                f = QFontMetrics(p.font())
                p.drawText(QPointF(x + ICON_GAP, base),
                           f.elidedText(text, Qt.TextElideMode.ElideRight, width))
                x += ICON_GAP + width
            x += GAP

        if show is None:
            p.end()
            return
        with_age, kind_word, src_word, with_len = show
        icon, word = source_of(s)
        cell(icon, "muted", word, src_w if src_word else 0)
        icon, word = kind_of(s)
        cell(icon, "accent" if icon == "music" else "muted", word, kind_w if kind_word else 0)
        if with_len and self.with_len:
            if s.secs:
                cell("clock", "muted", length_text(s.secs), len_w, QColor(theme.T["text"]),
                     self._bold())
            else:
                x += side + ICON_GAP + len_w + GAP
        if with_age and self._age:
            p.setFont(self.font())
            p.setPen(muted)
            p.drawText(QPointF(x, base), self._age)
        p.end()
