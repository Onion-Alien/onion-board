"""One sound in the Store tab (`SoundRow`): a single line with Play, its name, where it's
from, the votes, Play next, Add and Report. A voice's card (storevoices.VoiceRow) is the
bigger card with a picture, laid out by the same code."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout)

from soundboard.online import store
from soundboard.i18n import _
from soundboard.ui.kit import icons
from soundboard.ui.store import storelook
from soundboard.core.trash import ago
from soundboard.ui.kit.panel import HoverCard, icon_button
from soundboard.ui.sounds.ytlabels import ClampLabel

if TYPE_CHECKING:
    from soundboard.ui.store.storetab import StoreTab

COUNT_W = "99.9k"             # the widest vote count count_text gives
META_MAX = 300                # a line's source column at its widest (SoundRow._meta_w)
PLAY_W = 48                   # a line's Play (its picture only)


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
        self.meta = ClampLabel(meta, lines=1 if line else 3, bold=False)
        self.meta.setObjectName("hint")
        self.meta.set_full(meta, meta)
        self._meta = meta
        for lbl in (self.name, self.meta):   # (they paint their text: never markup)
            lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            lbl.setMinimumWidth(40)
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
        next (its picture only), Add and Report, all on one line."""
        self.btn_play.setText("")
        self.btn_play.setFixedWidth(PLAY_W)   # (it came back 4 px narrower after a play)
        self.btn_queue.setText("")   # (its tooltip says what it does)
        box = QVBoxLayout(self)
        box.setContentsMargins(8, 5, 8, 5)
        box.setSpacing(4)
        self._line = row = QHBoxLayout()
        row.setSpacing(6)
        self._under = QHBoxLayout()   # a narrow tab's second line (compact)
        self._under.setSpacing(6)
        self._under.addStretch(1)
        box.addLayout(row)
        box.addLayout(self._under)
        row.addWidget(self.btn_play)
        row.addWidget(self.btn_stop)
        words = QHBoxLayout()   # (the labels' room for descenders put the words a little
        words.setContentsMargins(4, 4, 6, 0)   # above the buttons' middle: down by 2 px)
        words.setSpacing(12)
        words.addWidget(self.name, 1)
        # (its category and age join it: set_where.) Room goes to it first, up to its
        # most (_meta_w): Stop coming takes it from the name, so it never moves
        words.addWidget(self.meta, 1000)
        self._meta_w()
        self.where.hide()
        row.addLayout(words, 1)
        for b in (self.btn_up, self.btn_down, self.btn_queue, self.btn_add, self.btn_report):
            row.addWidget(b)

    def _meta_w(self):
        """The source column at most two fifths of the words' room (META_MAX at most),
        the name the rest. Counted without Stop, so it's the same on every line and lines
        up down the list. (Its least stays the same: what a line needs never hangs on how
        wide it is.)"""
        stop = self.btn_stop.minimumSizeHint().width() + 6 if not self.btn_stop.isHidden() else 0
        rest = (self._line.minimumSize().width() - self.name.minimumWidth()
                - self.meta.minimumWidth() - stop)
        room = self.width() - 16 - rest   # (16: the line's side margins)
        self.meta.setMaximumWidth(max(self.meta.minimumWidth(), min(META_MAX, room * 2 // 5)))

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
        if self.line:   # one hint after the name: "From Myinstants · Memes · 3 days ago"
            text = " · ".join(w for w in (self._meta, self.where.text()) if w)
            self.meta.set_full(text, text)

    def compact(self, on: bool):
        """A narrow card: Play, Play next and Add show their pictures only (the words
        their tooltips), so Report never goes past the card's edge. A narrow line drops
        its source text and puts Play next, Add and Report on a second line."""
        if on == self._compact:
            return
        self._compact = on
        if self.line:   # (narrow: Play next, Add and Report go to a second line)
            self.meta.setHidden(on)
            to = self._under if on else self._line
            for b in (self.btn_queue, self.btn_add, self.btn_report):
                (self._line if on else self._under).removeWidget(b)
                to.addWidget(b)
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
        icons.set_icon(self.btn_play, "stop" if on else "play", "text", "on_accent")
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
        icons.set_icon(self.btn_play, "pause" if state == "playing" else "play", "text",
                       "on_accent")
        word = self._play_word()
        self.btn_play.setText("" if self._compact or self.line else word)
        self.btn_play.setToolTip(word if live else self._play_tip)
        self.btn_play.setAccessibleName(word)
        self.btn_stop.setVisible(live)
        if self.tile is not None:
            self.tile.set_playing(state == "playing")

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
            if not b.property("steady"):   # room for the widest count, so cards line up
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
