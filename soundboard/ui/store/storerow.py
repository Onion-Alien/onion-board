"""One sound in the Store tab (`SoundRow`): a single line with Play, its name, its facts
(storeinfo.InfoLabel: where it's from, music or a sound effect, how long, when it came),
the votes, Play next, Add and Report. A voice's card (storevoices.VoiceRow) is the bigger
card with a picture, laid out by the same code."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout)

from soundboard.online import store
from soundboard.i18n import _
from soundboard.ui.kit import icons
from soundboard.ui.store import storeinfo, storelook
from soundboard.ui.store.storeinfo import InfoLabel
from soundboard.core.trash import ago
from soundboard.ui.kit.panel import HoverCard, icon_button
from soundboard.ui.sounds.ytlabels import ClampLabel

if TYPE_CHECKING:
    from soundboard.ui.store.storetab import StoreTab

COUNT_W = "99.9k"             # the widest vote count count_text gives
NAME_ROOM = 200               # a line's name keeps this much before its facts get more
PLAY_W = 48                   # a line's Play (its picture only)
# a narrow line (compact): Play a square beside two lines, the name and Add, then the
# facts and the quiet buttons
C_PAD = 12                    # the line's padding
C_PLAY = 42                   # Play's square
C_GAP = 12                    # Play to the lines beside it
C_LINES = 8                   # between those two lines
C_BTN = 32                    # Add's and the quiet buttons' height
C_ADD_W = 63                  # Add at its narrowest


def meta_line(s: store.Sound) -> str:
    """"by Onion Board · tavern, music", "Shared by a player", for a shared link
    "YouTube link · Shared by a player", and for one the server brought in
    "From Myinstants" (its category has a column of its own)."""
    from soundboard.sounds import sourceinfo
    site = sourceinfo.site_of(s.link) if s.is_link else None
    if s.source and site:
        return _("From {site}", site=site[1])
    who = _("by {name}", name=s.author) if s.author else _("Shared by a player")
    where = [_("{site} link", site=site[1])] if site else []
    return " · ".join([*where, who, *([", ".join(s.tags)] if s.tags else [])])


def count_text(n: int) -> str:
    """A count in at most 5 characters: 950, 4.4k, 78.4k, 337k, 1.2M."""
    if n < 1000:
        return str(n)
    if n >= 999_500:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 99_950:
        return f"{n / 1000:.0f}k"
    return f"{n / 1000:.1f}k".replace(".0k", "k")


class SoundRow(HoverCard):
    """One sound on one line: Play, its name, where it's from, its category and when it
    came, the votes, Play next, Add and Report. A link's Play plays it now (over a link
    that's playing) and turns Pause while it plays; Play next waits for what's playing."""

    def __init__(self, s: store.Sound, tab: StoreTab, parent=None):
        super().__init__(parent)
        self._build(s, tab, meta_line(s), self.btn_play_tip(s), _("Add it to your Sounds"),
                    _("Report this sound"), line=True)

    def _build(self, s, tab, meta: str, play_tip: str, add_tip: str, report_tip: str,
               line: bool = False):
        """The parts: on one `line` (a sound), or a card with a picture (a voice:
        storevoices.VoiceRow)."""
        self.sound = s
        self.state = ""   # its link in the player: "", "loading", "playing", "paused"
        self.line = line
        self._compact = False
        self._play_tip = play_tip
        # a card's picture: an emoji for what it is, on its category's colour (a click plays)
        self.tile = None if line else storelook.SoundTile(s, lambda: self.btn_play.click())
        if self.tile is not None:
            self.tile.setToolTip(play_tip)
        # the name and the votes; where it's from, then its category and when it came
        # (one line each, ending in "…" when the card is narrow: the whole text on hover)
        self.name = ClampLabel(s.name, lines=1)
        self.name.set_full(s.name, s.name)
        # (a voice's card: up to 3 lines, so its words, 140 characters at most, can be read)
        self.info = InfoLabel(s, meta) if line else None   # (a line's facts, in columns)
        self.meta = self.info or ClampLabel(meta, lines=3, bold=False)
        self.meta.setObjectName("hint")
        self.meta.set_full(meta, meta)
        self._meta = meta
        for lbl in (self.name, self.meta):   # (they paint their text: never markup)
            lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            lbl.setMinimumWidth(40)
        if line:
            self.meta.setMinimumWidth(storeinfo.LEAST)
        self.where = QLabel()
        self.where.setObjectName("hint")
        self.where.setTextFormat(Qt.TextFormat.PlainText)
        self.btn_up = self._vote_button("like", _("I like it"))
        self.btn_up.clicked.connect(lambda: tab.vote(self, 1))
        self.btn_down = self._vote_button("dislike", _("Not for me"))
        self.btn_down.clicked.connect(lambda: tab.vote(self, -1))
        # what you can do with it
        self.btn_play = QPushButton(_("Play"))
        self.btn_play.setCheckable(True)   # (switched on while it plays)
        self.btn_play.setToolTip(play_tip)
        self.btn_play.setAccessibleName(_("Play"))
        icons.set_icon(self.btn_play, "play", "text", "on_accent")
        self.btn_play.clicked.connect(lambda: tab.play_clicked(self))
        self.btn_stop = icon_button("stop", _("Stop"), quiet=False)
        self.btn_stop.setFixedSize(32, 32)
        self.btn_stop.clicked.connect(lambda: tab.stop_clicked(self))
        self.btn_stop.hide()   # (while its link plays)
        self.btn_queue = QPushButton(_("Play next"))
        self.btn_queue.setToolTip(_("Queue: waits for the sounds playing to finish"))
        self.btn_queue.setAccessibleName(_("Play next"))
        icons.set_icon(self.btn_queue, "next")
        self.btn_queue.clicked.connect(lambda: tab.queue(self))
        self.btn_add = QPushButton(_("Add"))
        self.btn_add.setToolTip(add_tip)
        self.btn_add.setAccessibleName(add_tip)
        icons.set_icon(self.btn_add, "plus")
        self.btn_add.clicked.connect(lambda: tab.add(self))
        self.btn_report = icon_button("flag", report_tip)
        self.btn_report.clicked.connect(lambda: tab.report_menu(self))
        if line:
            self._lay_line()
        else:
            self._lay_card()
        self.show_votes()

    def _lay_line(self):
        """Play, the name, where it's from, then its category and age, the votes, Play
        next (its picture only), Add and Report, all on one line. Narrow (compact), Play
        stands beside two lines: the name and Add, then the facts and the quiet buttons."""
        self.btn_play.setText("")
        self.btn_play.setFixedWidth(PLAY_W)   # (it came back 4 px narrower after a play)
        self.btn_queue.setText("")   # (its tooltip says what it does)
        self._box = box = QHBoxLayout(self)
        box.setContentsMargins(8, 5, 8, 5)
        box.setSpacing(6)
        box.addWidget(self.btn_play)
        box.addWidget(self.btn_stop)
        self._col = col = QVBoxLayout()
        col.setSpacing(2)
        self._line = row = QHBoxLayout()
        row.setSpacing(6)
        self._under = QHBoxLayout()   # a narrow tab's second line (compact)
        self._under.setSpacing(2)   # (quiet buttons side by side, as a vote pair)
        self._under.addStretch(1)
        col.addLayout(row)
        col.addLayout(self._under)
        box.addLayout(col, 1)
        words = QHBoxLayout()   # (the labels' room for descenders put the words a little
        words.setContentsMargins(4, 4, 6, 0)   # above the buttons' middle: down by 2 px)
        words.setSpacing(12)
        words.addWidget(self.name, 1)
        # (its facts: set_where gives it the age.) Room goes to it first, up to its
        # most (_meta_w): Stop coming takes it from the name, so it never moves
        words.addWidget(self.meta, 1000)
        self._words = words
        self._meta_w()
        self.where.hide()
        row.addLayout(words, 1)
        for b in (self.btn_up, self.btn_down, self.btn_queue, self.btn_add, self.btn_report):
            row.addWidget(b)

    def _meta_w(self):
        """The facts as wide as the widest of their looks that leaves the name NAME_ROOM
        (all four with their words, then fewer: InfoLabel.fit), the name the rest. Counted
        without Stop, so it's the same on every line and lines up down the list. (Its
        least stays the same: what a line needs never hangs on how wide it is.)"""
        if self.info is None:
            return
        stop = self.btn_stop.minimumSizeHint().width() + 6 if not self.btn_stop.isHidden() else 0
        if self._compact:   # (narrow: the facts share the second line with the buttons)
            self._under.invalidate()
            # (what the layout counts for the facts now, whatever they were)
            meta = self._under.itemAt(self._under.indexOf(self.meta))
            # (contentsRect: inside its frame; 16: the line's side margins; Play beside)
            beside = self.contentsRect().width() - 2 * C_PAD - C_PLAY - C_GAP - stop
            room = (beside - self._under.sizeHint().width()
                    + (meta.sizeHint().width() if meta is not None else 0))
            # as many facts as fit; none on the narrowest tab (their tooltip still says them)
            self.info.setMaximumWidth(self.info.fit(room) if room >= storeinfo.SIDE else 0)
            self._under.invalidate()
            # the name on one line when it fits beside Add, else two (then "…")
            room = beside - self._line.spacing() - max(C_ADD_W, self.btn_add.sizeHint().width())
            fm = QFontMetrics(self.name.font())
            lines = 1 if fm.horizontalAdvance(self.name.full) <= room else 2
            if lines != self.name.lines:
                self.name.lines = lines
                self.name._fit()
            return
        # (the whole line's least, its side margins and Play included)
        rest = (self._box.minimumSize().width() - self.name.minimumWidth()
                - self.meta.minimumWidth() - stop)
        self.info.setMaximumWidth(self.info.fit(self.width() - rest - NAME_ROOM))

    def _dense(self, on: bool):
        """A narrow line's look: Play a soft accent square beside both lines, Add the
        filled button by the name, and the votes, Play next and Report quiet (no box
        until hovered, a vote switched on a soft accent, so Add stays the one that
        stands out) with 16 px pictures. Wide, they're back to the line's own looks."""
        vote_on = "text" if on else "on_accent"   # (dark ink on the soft accent)
        tools = (self.btn_up, self.btn_down, self.btn_queue, self.btn_report)
        for b, icon, col, on_col, name in (
                (self.btn_up, "like", "muted", vote_on, "votebutton"),
                (self.btn_down, "dislike", "muted", vote_on, "votebutton"),
                (self.btn_queue, "list_plus" if on else "next", "muted" if on else None, None,
                 ""),
                (self.btn_report, "more" if on else "flag", "muted" if on else None, None,
                 "iconbutton"),
                (self.btn_add, "plus", "on_accent" if on else None, None, "")):
            b.setObjectName(("primary" if b is self.btn_add else "storetool") if on else name)
            icons.set_icon(b, icon, col, on_col, size=16 if on else 18)
        self.btn_add.setProperty("small", on)
        self.btn_play.setObjectName("storeplay" if on else "")
        for b in (*tools, self.btn_add, self.btn_play):
            b.setMinimumSize(0, 0)
            b.setMaximumSize(16777215, 16777215)
        if on:
            self.btn_play.setFixedSize(C_PLAY, C_PLAY)
            for b in (*tools, self.btn_add):
                b.setFixedHeight(C_BTN)
            for b in (self.btn_queue, self.btn_report):
                b.setFixedWidth(C_BTN)
            self.btn_add.setMinimumWidth(C_ADD_W)
        else:
            self.btn_play.setFixedWidth(PLAY_W)
        self._play_icon()
        for b in (*tools, self.btn_add, self.btn_play):
            b.style().unpolish(b)
            b.style().polish(b)
        for b in (self.btn_up, self.btn_down):   # (their room for the widest count, again)
            b.setProperty("steady", False)
            b.setMinimumWidth(0)
        self.show_votes()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.line:
            self._meta_w()

    def _lay_card(self):
        """A voice's card: its picture, name and votes, where it's from and when it came,
        then its buttons in a row."""
        g = QGridLayout(self)
        g.setContentsMargins(10, 10, 10, 10)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(4)
        assert self.tile is not None   # (a card always has its picture)
        g.addWidget(self.tile, 0, 0, 2, 1, Qt.AlignmentFlag.AlignTop)
        top = QHBoxLayout()
        top.setSpacing(4)
        top.addWidget(self.name, 1)
        top.addWidget(self.btn_up)
        top.addWidget(self.btn_down)
        g.addLayout(top, 0, 1)
        g.addWidget(self.meta, 1, 1, Qt.AlignmentFlag.AlignTop)
        acts = QHBoxLayout()
        acts.setSpacing(6)
        for b in (self.btn_play, self.btn_stop, self.btn_queue, self.btn_add):
            acts.addWidget(b)
        acts.addStretch(1)
        acts.addWidget(self.where)   # (by the buttons: the words above get the card's width)
        acts.addWidget(self.btn_report)
        g.addLayout(acts, 2, 0, 1, 2)
        g.setColumnStretch(1, 1)

    def set_where(self, cat: str, created: int):
        """Its category and when it came: "Memes · 3 days ago"."""
        self.where.setText(" · ".join(w for w in (cat, ago(created) if created else "") if w))
        if self.info is not None:   # (the whole sentence is their tooltip)
            self.info.set_when(cat, created)
            self._meta_w()

    def compact(self, on: bool):
        """A narrow card: Play, Play next and Add show their pictures only (the words
        their tooltips), so Report never goes past the card's edge. A narrow line has
        Play beside two lines: the name (on up to 2 lines) and Add, then its facts (as
        many as fit) on the left and the votes, Play next and Report on the right."""
        if on == self._compact:
            return
        self._compact = on
        if self.line:
            btns = (self.btn_up, self.btn_down, self.btn_queue, self.btn_add, self.btn_report)
            self.meta.setMinimumWidth(0 if on else storeinfo.LEAST)   # (see _meta_w)
            box = self._box
            if self.info is not None:
                self.info.set_brief(on)
            for b in btns:
                self._line.removeWidget(b)
                self._under.removeWidget(b)
            if on:
                self._words.removeWidget(self.meta)
                self._under.insertWidget(0, self.meta, 1000, Qt.AlignmentFlag.AlignVCenter)
                for b in btns:
                    if b is self.btn_add:
                        self._line.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
                    else:
                        self._under.addWidget(b)
            else:
                self._under.removeWidget(self.meta)
                self._words.addWidget(self.meta, 1000)
                for b in btns:
                    self._line.addWidget(b)
            # (Play in the middle of both lines; the name in the middle of Add)
            mid = Qt.AlignmentFlag.AlignVCenter if on else Qt.AlignmentFlag(0)
            box.setAlignment(self.btn_play, mid)
            self._words.setAlignment(self.name, mid)
            self.name.lines = 1   # (_meta_w makes it 2 when it needs them)
            self.name._fit()
            self._words.setContentsMargins(*((0, 2, 0, 0) if on else (4, 4, 6, 0)))
            box.setContentsMargins(*((C_PAD,) * 4 if on else (8, 5, 8, 5)))
            box.setSpacing(C_GAP if on else 6)
            self._col.setSpacing(C_LINES if on else 2)
            self._dense(on)
            return
        for b, text in ((self.btn_play, self._play_word()), (self.btn_queue, _("Play next")),
                        (self.btn_add, _("Add"))):
            b.setText("" if on else text)
        self.btn_queue.setToolTip(_("Play next") if on
                                  else _("Queue: waits for the sounds playing to finish"))

    @staticmethod
    def btn_play_tip(s: store.Sound) -> str:
        return _("Play it now")

    def _play_word(self) -> str:
        if self.state == "playing":
            return _("Pause")
        if self.state == "paused":
            return _("Resume")
        return _("Stop") if self.btn_play.isChecked() and not self.state else _("Play")

    def playing_look(self, on: bool):
        """A sample to your headphones: Play turns Stop (and the picture's bars bounce)
        while it plays. The switched-on button is drawn in the accent with on_accent ink
        (a quiet one on the card was black on near-black in Amber Terminal)."""
        with _blocked(self.btn_play):
            self.btn_play.setChecked(on)
        self._play_icon()
        self.btn_play.setText("" if self._compact or self.line
                              else _("Stop") if on else _("Play"))
        self.btn_play.setToolTip(_("Stop") if on else self._play_tip)
        self.btn_play.setAccessibleName(_("Stop") if on else _("Play"))
        if self.tile is not None:
            self.tile.set_playing(on)

    def link_look(self, state: str):
        """Its link in the player: Play is switched on while it loads and plays, says
        Pause while it plays and Resume while it's paused, and Stop shows beside it."""
        self.state = state
        live = state in ("playing", "paused")
        with _blocked(self.btn_play):
            self.btn_play.setChecked(bool(state))
        self._play_icon()
        word = self._play_word()
        self.btn_play.setText("" if self._compact or self.line else word)
        self.btn_play.setToolTip(word if live else self._play_tip)
        self.btn_play.setAccessibleName(word)
        self.btn_stop.setVisible(live)
        if self.tile is not None:
            self.tile.set_playing(state == "playing")

    def _play_icon(self):
        """Play's picture: Pause while its link plays, Stop while a sample plays, else
        Play; on a narrow line's soft square, drawn as an outline in the accent."""
        name = ("pause" if self.state == "playing" else "play" if self.state
                else "stop" if self.btn_play.isChecked() else "play")
        if self._compact and self.line:
            icons.set_icon(self.btn_play, "play_line" if name == "play" else name, "accent",
                           "on_accent")
        else:
            icons.set_icon(self.btn_play, name, "text", "on_accent")

    def _vote_button(self, icon: str, tip: str) -> QPushButton:
        b = QPushButton()
        b.setObjectName("votebutton")
        b.setProperty("quiet", True)
        b.setCheckable(True)
        icons.set_icon(b, icon, "muted", "on_accent")
        b.setToolTip(tip)
        b.setAccessibleName(tip)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        return b

    def show_votes(self):
        s = self.sound
        for b, n, on in ((self.btn_up, s.up, s.mine == 1), (self.btn_down, s.down, s.mine == -1)):
            b.setText(count_text(n))
            b.setChecked(on)
            # room for the widest count, so cards line up (a narrow line's: its own count)
            if not b.property("steady") and not (self._compact and self.line):
                b.setProperty("steady", True)
                was = b.text()
                b.setText(COUNT_W)
                b.setMinimumWidth(b.sizeHint().width())
                b.setText(was)
        self.btn_up.setAccessibleName(_("I like it ({n})", n=s.up))
        self.btn_down.setAccessibleName(_("Not for me ({n})", n=s.down))


class _blocked:
    """Signals off on a widget for a `with` block."""

    def __init__(self, w):
        self.w = w

    def __enter__(self):
        self.was = self.w.blockSignals(True)

    def __exit__(self, *_exc):
        self.w.blockSignals(self.was)
