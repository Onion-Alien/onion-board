"""One sound's card in the Store tab (`SoundRow`): its tile, Play / Add / vote buttons and
the line saying who shared it."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy

from soundboard.online import store
from soundboard.i18n import _
from soundboard.ui.kit import icons
from soundboard.ui.store import storelook
from soundboard.core.trash import ago
from soundboard.ui.kit.panel import HoverCard, icon_button
from soundboard.ui.sounds.ytlabels import ClampLabel

if TYPE_CHECKING:
    from soundboard.ui.store.storetab import StoreTab

COUNT_W = "9.9k"              # the widest vote count kept room for


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
    return f"{n / 1000:.1f}k".replace(".0k", "k") if n >= 1000 else str(n)


class SoundRow(HoverCard):
    """One sound's card: its picture, name and votes, where it's from and when it came,
    then Play, Stop, Play next, Add and Report. A link's Play plays it now (over a link
    that's playing) and turns Pause while it plays; Play next waits for what's playing."""

    def __init__(self, s: store.Sound, tab: StoreTab):
        super().__init__()
        self._build(s, tab, meta_line(s), self.btn_play_tip(s), _("Add it to your Sounds"),
                    _("Report this sound"))

    def _build(self, s, tab, meta: str, play_tip: str, add_tip: str, report_tip: str):
        """The card's parts (a voice's card too: storevoices.VoiceRow)."""
        self.sound = s
        self.state = ""   # its link in the player: "", "loading", "playing", "paused"
        self._compact = False
        self._play_tip = play_tip
        g = QGridLayout(self)
        g.setContentsMargins(10, 10, 10, 10)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(4)
        # its picture: an emoji for what it is, on its category's colour (a click plays)
        self.tile = storelook.SoundTile(s, lambda: self.btn_play.click())
        self.tile.setToolTip(play_tip)
        g.addWidget(self.tile, 0, 0, 2, 1, Qt.AlignmentFlag.AlignTop)
        # the name and the votes; where it's from, then its category and when it came
        # (one line each, ending in "…" when the card is narrow: the whole text on hover)
        self.name = ClampLabel(s.name, lines=1)
        self.name.set_full(s.name, s.name)
        self.meta = ClampLabel(meta, lines=1, bold=False)
        self.meta.setObjectName("hint")
        self.meta.set_full(meta, meta)
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
        top = QHBoxLayout()
        top.setSpacing(4)
        top.addWidget(self.name, 1)
        top.addWidget(self.btn_up)
        top.addWidget(self.btn_down)
        g.addLayout(top, 0, 1)
        mid = QHBoxLayout()
        mid.setSpacing(8)
        mid.addWidget(self.meta, 1)
        mid.addWidget(self.where)
        g.addLayout(mid, 1, 1)
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
        acts = QHBoxLayout()
        acts.setSpacing(6)
        for b in (self.btn_play, self.btn_stop, self.btn_queue, self.btn_add):
            acts.addWidget(b)
        acts.addStretch(1)
        acts.addWidget(self.btn_report)
        g.addLayout(acts, 2, 0, 1, 2)
        g.setColumnStretch(1, 1)
        self.show_votes()

    def set_where(self, cat: str, created: int):
        """Its category and when it came: "Memes · 3 days ago"."""
        self.where.setText(" · ".join(w for w in (cat, ago(created) if created else "") if w))

    def compact(self, on: bool):
        """A narrow card: Play, Play next and Add show their pictures only (the words
        their tooltips), so Report never goes past the card's edge."""
        if on == self._compact:
            return
        self._compact = on
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
        self.btn_play.setText("" if self._compact else _("Stop") if on else _("Play"))
        self.btn_play.setToolTip(_("Stop") if on else self._play_tip)
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
        self.btn_play.setText("" if self._compact else word)
        self.btn_play.setToolTip(word if live else self._play_tip)
        self.btn_play.setAccessibleName(word)
        self.btn_stop.setVisible(live)
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
