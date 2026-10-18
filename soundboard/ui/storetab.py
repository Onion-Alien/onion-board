"""The Store tab: free sounds anyone can add to their board (soundboard.online.store), the best
voted first, in categories, and a way to share your own. Sounds the server brings in from
Myinstants are links like any shared one: played and added from that site.

Nothing goes online until the tab is first opened. Every call runs on a worker thread
and comes back through busy.emit, so a closed tab or window never gets a late answer."""
from __future__ import annotations

import html
import logging
import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QScrollArea,
                               QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from soundboard import errors, library, usage, wheelguard
from soundboard.online import net, store
from soundboard.engine import SR
from soundboard.i18n import _
from soundboard.ui import busy, fit, icons, storelook
from soundboard.trash import ago
from soundboard.ui.panel import HoverCard, hint_label, icon_button, section_label
from soundboard.ui.ytsearch import ClampLabel

log = logging.getLogger(__name__)

PREVIEW = "__store_preview"   # the store's "hear it first" voice (headphones only)
SEARCH_WAIT_MS = 400          # typing pauses this long before the store is searched
ROW_MAX_W = 1060              # the cards stay a column, centred, on a wide window
COUNT_W = "9.9k"              # the widest vote count kept room for
CARD_MIN_W = 400              # a card's narrowest: two side by side when two fit
CARD_GAP = 8                  # between the cards
LIST_GAP = 8                  # between the cards and the scroll bar (DESIGN.md, *Breathing room*)
ONE_ROW = 720                 # a narrower tab puts the toolbar on two rows
LINK_TICK_MS = 250            # how often the cards look at what the player is doing


def meta_line(s: store.Sound) -> str:
    """"by Onion Board · tavern, music", "Shared by a player", for a shared link
    "YouTube link · Shared by a player", and for one the server brought in
    "From Myinstants" (its category has a column of its own)."""
    from soundboard import sourceinfo
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
        self.btn_queue.setVisible(s.is_link)   # (a file of the store's plays to you only)

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
        return _("Play it now") if s.is_link else _("Hear it (only you)")

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


class StoreTab(QWidget):
    """The Store tab. `add_file(path)` adds a fetched sound to the board; `play(data,
    gain)` plays one to the headphones only (None stops it) and says whether it could;
    `open_privacy()` opens Settings > Privacy & security."""
    clip_ready = Signal(object, str)   # (the window wires every tab's; never sent here)
    active_changed = Signal(bool)
    _listed = Signal(int, object, bool, str)     # worker -> UI: (serial, sounds, more, error)
    _fetched = Signal(object, object, str)       # (row, (what, path), error): "play" / "add"
    _voted = Signal(object, object, str)         # (row, (up, down, mine) or None, error)
    _decoded = Signal(object, object, float, int)   # (row, data, gain, serial)
    _cats = Signal(object)                       # [(category, how many)], all; None: failed

    def __init__(self, cfg, add_file: Callable[[str], None],
                 play: Callable[[object, float], bool], open_privacy: Callable[[], object],
                 save: Callable[[], None] = lambda: None,
                 link: Callable[[str, str, str], None] = lambda url, name, kind: None,
                 voices=None, link_state: Callable[[str], str] = lambda url: ""):
        super().__init__()
        self.cfg = cfg
        self.voices = voices   # ui.storevoices.VoiceHooks: the Voices list (None: Sounds only)
        self._mode = "sounds"  # or "voices": community voices instead of sounds
        self._kind = ""        # the Voices list's kind ("" all)
        self._save = save
        # (url, name, kind): the window's link downloader and player. "now" plays it over
        # a link that's playing, "play" after it, "add"; "pause" (or resume) and "stop"
        self._link = link
        self._link_state = link_state   # a link's state in the player (SoundRow.link_look)
        self._add_file = add_file
        self._play = play
        self._open_privacy = open_privacy
        self._closed = False
        self._serial = 0          # the newest list asked for (older answers are dropped)
        self._hear_serial = 0
        self._loaded = False
        self._off = False   # showing "The store is off"
        self._offset = 0
        self._rows: list[SoundRow] = []
        self._playing: SoundRow | None = None
        self._busy: set[tuple[str, str]] = set()   # (sound id, "play" / "add" / "vote")
        self._listed.connect(self._on_listed)
        self._fetched.connect(self._on_fetched)
        self._voted.connect(self._on_voted)
        self._decoded.connect(self._on_decoded)
        self._cats.connect(self._on_cats)
        self._link_tick = QTimer(self, interval=LINK_TICK_MS)   # (while the tab shows)
        self._link_tick.timeout.connect(self._follow_links)
        net.on_change(self._net_changed)   # Settings > Privacy's switch, Offline mode
        self._cat = ""            # the category picked ("" all)

        # one column, centred in the tab (a wide window: room both sides, not all on
        # the right)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        column = QWidget()
        column.setMaximumWidth(ROW_MAX_W)
        col = QVBoxLayout(column)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(12)
        outer.addStretch(1)
        outer.addWidget(column, 100)
        outer.addStretch(1)
        # still new: a green Beta tag right after the title
        beta = QLabel(_("Beta"))
        beta.setObjectName("pill")
        beta.setProperty("tone", "beta")
        beta.setToolTip(_("The sound store is new and still changing."))
        # the banner: Bun in his headphones, the title big, what the store is under it
        head = self.banner = storelook.StoreBanner()
        hv = QVBoxLayout(head)
        hv.setContentsMargins(14, 12, 14, 14)
        hv.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(12)
        self.bun = storelook.make_bun(72)
        top.addWidget(self.bun, 0, Qt.AlignmentFlag.AlignVCenter)
        words = QVBoxLayout()
        words.setSpacing(2)
        words.addStretch(1)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.title = QLabel(_("Community"))
        self.title.setObjectName("storetitle")
        # the kit's display size (a whole page's title); a style sheet, as the theme's
        # QLabel font would win over setFont
        self.title.setStyleSheet("font-size: 17pt; font-weight: 800; background: transparent;")
        title_row.addWidget(self.title)
        title_row.addWidget(beta, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        words.addLayout(title_row)
        # (one line for Sounds and Voices: the same words as the tab's tooltip)
        self.tagline = hint_label(_("Sounds and voices players share, voted on by everyone: "
                                    "add them or share your own"))
        words.addWidget(self.tagline)
        words.addStretch(1)
        top.addLayout(words, 1)
        hv.addLayout(top)
        # the toolbar: Sounds or Voices, the search, the category, Share and Refresh. One
        # row in a wide tab; two in a narrow one, so the card fits the smallest window
        # (wider, a narrow window became the mini player)
        self.mode_btns: dict[str, QPushButton] = {}
        self.modes_box = QWidget()
        modes = QHBoxLayout(self.modes_box)
        modes.setContentsMargins(0, 0, 0, 0)
        modes.setSpacing(4)
        if voices is not None:
            for key, text, icon in (("sounds", _("Sounds"), "sounds"),
                                    ("voices", _("Voices"), "voice")):
                b = QPushButton(text)
                b.setCheckable(True)
                b.setAutoExclusive(True)
                b.setChecked(key == "sounds")
                icons.set_icon(b, icon, "text", "on_accent")
                b.clicked.connect(lambda _c=False, k=key: self.set_mode(k))
                modes.addWidget(b)
                self.mode_btns[key] = b
        else:
            self.modes_box.hide()
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Search sounds"))
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName(_("Search sounds"))
        self.search.setMinimumWidth(120)
        self._search_wait = QTimer(self, singleShot=True, interval=SEARCH_WAIT_MS)
        self._search_wait.timeout.connect(self.reload)
        self.search.textChanged.connect(lambda _t: self._search_wait.start())
        # the sounds' categories (or the voices' kinds), each with how many
        self.cat_pick = QComboBox()
        self.cat_pick.setAccessibleName(_("Category"))
        self.cat_pick.setToolTip(_("Category"))
        self.cat_pick.activated.connect(self._cat_picked)
        self.btn_share = QPushButton(_("Share a sound"))
        self.btn_share.setObjectName("primary")
        self._share_words = True   # (a narrow tab: its icon only, the words its tooltip)
        icons.set_icon(self.btn_share, "upload", "on_accent", "on_accent")
        self.btn_share.clicked.connect(lambda: self.share_voice() if self._mode == "voices"
                                       else self.share())
        self.btn_reload = icon_button("reload", _("Refresh"))
        self.btn_reload.clicked.connect(lambda: self.reload())
        # (in a box that only asks for the two rows' width: asking for one row's, a
        # narrow tab could never get narrow enough to switch to two)
        self.toolbar = QWidget()
        self.toolbar.setObjectName("storebar")   # (theme.py: Share greyed out while down)
        tv = QVBoxLayout(self.toolbar)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(10)
        self._bars = (QHBoxLayout(), QHBoxLayout())
        for bar in self._bars:
            bar.setSpacing(8)
            tv.addLayout(bar)
        hv.addWidget(self.toolbar)
        self._one_row: bool | None = None
        self._lay_toolbar(False)
        col.addWidget(head)
        # the order, over the cards' right edge: Votes (the best voted first) or Added
        # (the newest first)
        self.table_head = QWidget()
        hh = QHBoxLayout(self.table_head)
        hh.setContentsMargins(0, 0, LIST_GAP, 0)
        hh.setSpacing(4)
        hh.addStretch(1)
        self._sort = "top"
        self.sort_btns: dict[str, QPushButton] = {}
        for key, text, tip in (("top", _("Votes"), _("The best voted first")),
                               ("new", _("Added"), _("The newest first"))):
            b = QPushButton(text)
            hh.addWidget(b)
            b.setObjectName("small")   # header-sized; the arrow after the words says
            b.setProperty("quiet", True)   # which one sorts (not checkable: no filled pill)
            b.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            b.setToolTip(tip)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, k=key: (
                k != "top" and usage.used(f"store-sort-{k}"), self.set_sort(k)))
            self.sort_btns[key] = b
        self._sort_look()
        self.table_head.hide()
        col.addWidget(self.table_head)

        # the list, or a message in its place (loading, nothing found, off, failed)
        self.stack = QStackedWidget()
        scroll = self.list_area = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().installEventFilter(self)   # resized: the columns line up again
        body = QWidget()
        self._list = QVBoxLayout(body)
        self._list.setContentsMargins(0, 0, LIST_GAP, 0)   # cards end before the scroll bar
        self._list.setSpacing(CARD_GAP)
        self._grid = QGridLayout()   # the cards: two a row when two fit (_fit_columns)
        self._grid.setSpacing(CARD_GAP)
        self._cols = 0
        self._list.addLayout(self._grid)
        self._fill_cats([])
        self.btn_more = QPushButton(_("Show more"))
        self.btn_more.clicked.connect(self.more)
        self.btn_more.hide()
        self._list.addWidget(self.btn_more, 0, Qt.AlignmentFlag.AlignHCenter)
        self._list.addStretch(1)
        scroll.setWidget(body)
        self.stack.addWidget(scroll)
        self.message = QWidget()
        mv = QVBoxLayout(self.message)
        mv.setContentsMargins(12, 8, 12, 8)
        mv.setSpacing(6)
        mv.addStretch(1)
        self.msg_icon = QLabel()
        self.msg_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mv.addWidget(self.msg_icon)
        self.msg_title = section_label("")
        self.msg_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mv.addWidget(self.msg_title)
        self.msg_text = hint_label("")
        self.msg_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mv.addWidget(self.msg_text)
        br = QHBoxLayout()
        br.addStretch(1)
        self.msg_btn = QPushButton()
        self.msg_btn.clicked.connect(self._message_action)
        br.addWidget(self.msg_btn)
        br.addStretch(1)
        mv.addLayout(br)
        mv.addStretch(2)
        self._msg_do: Callable[[], object] | None = None
        self.stack.addWidget(self.message)
        # the list couldn't be had (the store's down, no connection): sad Bun says so
        from soundboard.ui import oops
        self.oops = oops.OopsPanel()
        self.oops_page = oops.centred(self.oops)
        self.stack.addWidget(self.oops_page)
        self.failed = False   # the list couldn't be had (the tab's tour asks, tabtours.py)
        col.addWidget(self.stack, 1)
        self.note = QLabel()   # the last action's result, for screen readers and tests
        self.note.hide()

    def install(self) -> str:
        """This install's store id (made, and saved, the first time)."""
        new = not getattr(self.cfg, "store_id", "")
        sid = store.install_id(self.cfg)
        if new:
            self._save()
        return sid

    # ------------------------------------------------------------------ the main window
    def start(self):
        pass

    def stop(self):
        self._stop_preview()

    def stop_all(self):
        self._stop_preview()

    def is_active(self) -> bool:
        return False

    def retheme(self):
        pass

    def shutdown(self):
        self._closed = True
        self._search_wait.stop()
        self._link_tick.stop()
        self._stop_preview()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_buns()
        self._fit_toolbar()

    def _fit_buns(self):
        """The banner's Bun when there's room (`fits`), never while the red card's sad
        Bun is out (one Bun at a time)."""
        self.bun.setVisible(storelook.fits(self.width(), self.height())
                            and not getattr(self, "failed", False))

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Type.Resize and obj is self.list_area.viewport():
            self._fit_columns()
            self._hold_rows()
        return super().eventFilter(obj, e)

    def _hold_rows(self):
        """The rows stay where they are on screen when something above the tab comes or
        goes: the download bar opening for a played link pushed the list down, so the row
        just clicked slid away (it looked like a jump back up the list)."""
        vp = self.list_area.viewport()
        top = vp.mapTo(self.window(), QPoint(0, 0)).y()
        was, self._list_top = getattr(self, "_list_top", None), top
        if was is not None and top != was and self.isVisible():
            sb = self.list_area.verticalScrollBar()
            sb.setMaximum(max(sb.maximum(), sb.value() + top - was))   # (its range catches up)
            sb.setValue(sb.value() + top - was)

    def _toolbar_parts(self) -> list[QWidget]:
        return [w for w in (self.modes_box, self.search, self.cat_pick, self.btn_share,
                            self.btn_reload) if not w.isHidden()]

    def _fit_toolbar(self):
        """One row when the card has room for all of it (and the tab is wide), else two."""
        room = min(self.width(), ROW_MAX_W) - 28   # (the banner's side margins)
        parts = self._toolbar_parts()
        full = self._share_w(self._share_label())
        need = sum(full if w is self.btn_share else w.minimumSizeHint().width()
                   if w is self.search else w.sizeHint().width()
                   for w in parts) + 8 * (len(parts) - 1)
        self._lay_toolbar(self.width() >= ONE_ROW and room >= need)
        # the first of two rows, Sounds / Voices and Share, wanted 487 px with Share's
        # words: wider than the mini player's cut-off, so the window went mini on it
        words = bool(self._one_row) or room >= self._modes_w() + 8 + full
        if words != self._share_words:
            self._share_words = words
            self._share_look()

    def _share_label(self) -> str:
        return _("Share a voice") if self._mode == "voices" else _("Share a sound")

    def _share_look(self):
        """Share's words on it, or (narrow) its icon only with the words as its tooltip.
        Greyed out, saying why, while the store's server is down."""
        label = self._share_label()
        down = store.is_down()
        self.btn_share.setEnabled(not down)
        self.btn_share.setText(label if self._share_words else "")
        self.btn_share.setToolTip(store.down_share() if down
                                  else "" if self._share_words else label)
        self.btn_share.setAccessibleName(label)

    def _share_w(self, text: str) -> int:
        """The Share button's width with `text` on it."""
        b = self.btn_share
        was = b.text()
        if was == text:
            return b.sizeHint().width()
        b.setText(text)
        w = b.sizeHint().width()
        b.setText(was)
        return w

    def _modes_w(self) -> int:
        return self.modes_box.sizeHint().width() * (not self.modes_box.isHidden())

    def _lay_toolbar(self, one: bool):
        """The toolbar in one row (a wide tab), or two: Sounds / Voices and Share, then
        the search, the category and Refresh."""
        # the box asks for the two rows' width, whichever is shown
        rows = (self._modes_w() + 8 + self._share_w(""),
                self.search.minimumSizeHint().width() + self.cat_pick.sizeHint().width()
                + self.btn_reload.sizeHint().width() + 16)
        self.toolbar.setMinimumWidth(max(rows))
        if one == self._one_row:
            return
        self._one_row = one
        for bar in self._bars:
            while bar.count():
                bar.takeAt(0)   # (the widgets stay the card's; the stretch goes)
        first, second = self._bars[0], self._bars[0 if one else 1]
        first.addWidget(self.modes_box)
        if not one:
            first.addStretch(1)
            first.addWidget(self.btn_share)
        second.addWidget(self.search, 1)
        second.addWidget(self.cat_pick)
        if one:
            second.addWidget(self.btn_share)
        second.addWidget(self.btn_reload)

    # ------------------------------------------------------------------ the table
    def _sort_look(self):
        """The order the list is in: its column's header with an arrow."""
        for key, b in self.sort_btns.items():
            if key == self._sort:
                icons.set_icon(b, "fold_open", "accent", "accent", size=14)
            else:
                b.setIcon(QIcon())

    def _fit_columns(self, force: bool = False):
        """Two cards side by side when two fit the list, else one. A card narrower than
        its buttons with their words (measured on the first, so longer words or other
        fonts move the step, never cut a card off): every card shows their pictures only."""
        if not self._rows:
            return
        w = self.list_area.viewport().width() - LIST_GAP
        cols = 2 if w >= 2 * CARD_MIN_W + CARD_GAP else 1
        if force or cols != self._cols:
            self._cols = cols
            for r in self._rows:
                self._grid.removeWidget(r)
            for i, r in enumerate(self._rows):
                self._grid.addWidget(r, i // cols, i % cols)
            for c in range(2):
                self._grid.setColumnStretch(c, 1 if c < cols else 0)
        room = (w - CARD_GAP * (cols - 1)) // cols
        first = self._rows[0]
        first.compact(False)
        compact = self._needs(first) > room
        for r in self._rows:
            r.compact(compact)

    @staticmethod
    def _needs(r) -> int:
        """The card's smallest width, as its buttons are now (its own frame included)."""
        lay = r.layout()
        if lay is not None:
            lay.invalidate()
        return max(lay.minimumSize().width() if lay is not None else 0,
                   r.minimumSizeHint().width())

    def showEvent(self, e):
        super().showEvent(e)
        # nothing goes online until the tab is first opened; switched back on in
        # Settings meanwhile, the list comes when it's shown again
        if not self._loaded or (self._off and net.allowed(store.FEATURE)):
            self._loaded = True
            QTimer.singleShot(0, self, self.reload)
        self._link_tick.start()

    def _net_changed(self):
        QTimer.singleShot(0, self, self._follow_switch)   # (any thread)

    def _follow_switch(self):
        """Switched off while a list loads, its cut connection's late failure said
        "Couldn't open the store": say it's off at once (and drop that answer). Back
        on, the list comes again if the tab is showing."""
        if self._closed or not self._loaded:
            return
        on = net.allowed(store.FEATURE)
        if not on and not self._off or on and self._off and self.isVisible():
            back = on and self._off
            self.reload()
            if back:   # (the list just went to "Loading": say why it came back)
                busy.toast(self, _("✓ The store is on again: loading it."), "ok",
                           key="store-switch")

    def hideEvent(self, e):
        self._stop_preview()   # another tab: the sample stops (a link plays on)
        self._link_tick.stop()
        super().hideEvent(e)

    # ------------------------------------------------------------------ the list
    def _sort_key(self) -> str:
        return self._sort

    def set_sort(self, key: str):
        """Votes (the best voted first, "top") or Added (the newest first, "new")."""
        self._sort = "new" if key == "new" else "top"
        self._sort_look()
        self.reload()

    def set_cat(self, key: str):
        """Only one category's sounds ("" all of them)."""
        self._cat = key if key in store.CATS else ""
        self._show_picked(self._cat)
        self.reload()

    def _show_picked(self, key: str):
        i = self.cat_pick.findData(key)
        if i >= 0:
            self.cat_pick.setCurrentIndex(i)

    def _cat_picked(self, i: int):
        key = self.cat_pick.itemData(i) or ""
        if self._mode == "voices":
            self.set_kind(key)
        else:
            if key:
                usage.used("store-category")
            self.set_cat(key)

    def set_mode(self, mode: str):
        """Sounds or Voices: the list, its chips and the Share button change with it."""
        self._mode = "voices" if mode == "voices" and self.voices is not None else "sounds"
        if self._mode in self.mode_btns:
            self.mode_btns[self._mode].setChecked(True)
        voices = self._mode == "voices"
        self._share_look()
        self.search.setPlaceholderText(_("Search the voices") if voices
                                       else _("Search sounds"))
        self._show_cats()
        self.reload()

    def set_kind(self, kind: str):
        """Only one kind of voice ("" all of them)."""
        self._kind = kind if kind in ("fx", "ai", "setup") else ""
        self._show_picked(self._kind)
        self.reload()

    def _show_cats(self):
        """The dropdown's choices: the sounds' categories, or the voices' kinds."""
        if self._mode == "sounds":
            self._fill_cats([])
            self._fetch_cats()
            return
        from soundboard.ui.storevoices import kind_chips
        self._fill_cats([(key, text, storelook.KIND_ICON.get(key, storelook.ALL_ICON))
                         for key, text in kind_chips() if key])
        self._show_picked(self._kind)

    def _fill_cats(self, items: list[tuple[str, str, str]]):
        """"All categories", then (key, text, icon name) for each."""
        self.cat_pick.clear()
        self.cat_pick.addItem(_("All categories"), "")
        for key, text, _icon in items:
            self.cat_pick.addItem(text, key)
        icons.set_item_icons(self.cat_pick, [storelook.ALL_ICON] + [i for _k, _t, i in items])
        wheelguard.snug_combo(self.cat_pick)
        # the list as wide as its longest name (+ padding and scroll bar), never cut off
        view = self.cat_pick.view()
        view.setMinimumWidth(view.sizeHintForColumn(0) + 40)
        if self._one_row is not None:   # (its width changed: still room for one row?)
            self._fit_toolbar()

    def _fetch_cats(self):
        install = self.install()

        def run():
            try:
                busy.emit(self._cats, store.categories(install))
            except Exception as e:  # noqa: BLE001 - the list says why; the chips just wait
                log.info("couldn't read the store's categories: %s", e)
                busy.emit(self._cats, None)
        threading.Thread(target=run, daemon=True, name="store-cats").start()

    def _on_cats(self, got):
        if self._closed:
            return
        self._share_look()
        if got is None or self._mode != "sounds":
            return
        cats, _total = got
        # the name, then how many (a number needs no words)
        self._fill_cats([(key, f"{store.cat_name(key)}  {count_text(n)}",
                          storelook.CAT_ICON.get(key, storelook.ALL_ICON)) for key, n in cats])
        self._show_picked(self._cat)

    def _say(self, icon: str, title: str, text: str, button: str = "",
             do: Callable[[], object] | None = None):
        """The page in place of the list: `icon` over a title, a line and a button
        (a list that couldn't be had: `_problem`)."""
        self.failed = False
        self.msg_icon.setPixmap(icons.pixmap(icon, 44, icons.resolve("muted")))
        self._fit_buns()
        # Bun's down when the store can't show anything, fine while it loads
        self.bun.sad = 0.0 if icon == "store" and not button else 0.7
        self.msg_title.setText(title)
        self.msg_text.setText(text)
        self.msg_text.setVisible(bool(text))
        self.msg_btn.setText(button)
        self.msg_btn.setVisible(bool(button))
        self._msg_do = do
        self.table_head.hide()
        self.stack.setCurrentWidget(self.message)

    def _problem(self, title: str, line: str, fixable: bool = True):
        """The list couldn't be had (the store's down, no connection): the red card in
        its place, Try again reloads. `fixable=False`: the server's down, nothing for
        the user to do but wait."""
        self.failed = True
        self._fit_buns()
        self.oops.show_problem(title, html.escape(line, quote=False), self.reload,
                               fixable=fixable)
        self.table_head.hide()
        self.stack.setCurrentWidget(self.oops_page)

    def _message_action(self):
        if self._msg_do is not None:
            self._msg_do()

    def reload(self):
        """The list again from the top (the search, the order or the category changed,
        Refresh)."""
        self._search_wait.stop()
        self._offset = 0
        self._fetch_list(replace=True)

    def more(self):
        self._fetch_list(replace=False)

    def _fetch_list(self, replace: bool):
        if self._closed:
            return
        self._off = not net.allowed(store.FEATURE)
        if self._off:
            self._serial += 1   # a list still on its way would say "Couldn't open" over this
            busy.set_busy(self.btn_more, False)
            self._clear()
            self._say("offline", _("The store is off"), net.off_message(store.FEATURE),
                      _("Privacy && security settings"), self._open_privacy)
            return
        self._serial += 1
        serial, sort, query, offset, cat = (self._serial, self._sort_key(), self.search.text(),
                                            0 if replace else self._offset, self._cat)
        install, voices, kind = self.install(), self._mode == "voices", self._kind
        if replace:
            self._say("store", _("Loading the store…"), "")
            if self.cat_pick.count() < 2 and not voices:
                self._fetch_cats()
        else:
            busy.set_busy(self.btn_more, True)

        def run():
            try:
                if voices:
                    from soundboard.online import storevoices
                    found, more = storevoices.browse(install, kind, sort, query, offset)
                else:
                    found, more = store.browse(install, sort, query, offset, cat)
                busy.emit(self._listed, serial, (replace, found, False), more, "")
            except Exception as e:  # noqa: BLE001 - offline, switched off, the server…
                log.info("couldn't read the store: %s", e)
                busy.emit(self._listed, serial,
                          (replace, None, e if isinstance(e, store.StoreDown) else None), False,
                          str(e) if isinstance(e, store.StoreError) else errors.plain(e))
        threading.Thread(target=run, daemon=True, name="store-list").start()

    def _on_listed(self, serial: int, got, more: bool, err: str):
        if self._closed or serial != self._serial:
            return
        replace, found, down = got
        busy.set_busy(self.btn_more, False)
        self._share_look()
        if found is None:
            if replace and down:
                usage.used("store-maintenance" if down.back else "store-down")
                self._clear()
                self._problem(*store.down_words(down.back), fixable=False)
            elif replace:
                self._clear()
                self._problem(_("Couldn't open the store"), err)
            else:
                busy.toast(self.window(), html.escape(err), "error")
            return
        if replace:
            self._clear()
        self._offset += len(found)
        from soundboard.online.storevoices import Voice
        from soundboard.ui.storevoices import VoiceRow
        for s in found:
            if isinstance(s, Voice):
                r = VoiceRow(s, self)
                r.set_where("", s.created)   # (its kind starts its second line)
            else:
                r = SoundRow(s, self)
                r.set_where(store.cat_name(s.cat), s.created)
            self._rows.append(r)
        self.btn_more.setVisible(more)
        if not self._rows:
            if self.search.text().strip():
                self._say("search", _("Nothing matches"), _("Try other words."))
            elif self._mode == "voices" and self._kind:
                self._say("search", _("Nothing matches"), "", _("All"), lambda: self.set_kind(""))
            elif self._mode == "voices":
                if store.is_down():   # (no Share button while it's down)
                    self._say("voice", _("No voices here yet"), store.down_share())
                else:
                    self._say("voice", _("No voices here yet"),
                              _("Be the first: share a voice you made."), _("Share a voice"),
                              self.share_voice)
            elif self._cat:   # a way back to All, right here
                self._say("search", _("Nothing matches"), "", _("All"), lambda: self.set_cat(""))
            else:
                if store.is_down():   # (no Share button while it's down)
                    self._say("store", _("No sounds here yet"), store.down_share())
                else:
                    self._say("store", _("No sounds here yet"),
                              _("Be the first: share a sound you made."), _("Share a sound"),
                              self.share)
            return
        self.bun.sad = 0.0
        self.failed = False
        self._fit_buns()
        self.stack.setCurrentWidget(self.list_area)
        self.table_head.show()
        self._fit_columns(force=True)
        self._follow_links()
        if replace:   # a new list starts at its top (the order bar coming in above it
            QTimer.singleShot(0, self, self._to_top)   # moved it: _hold_rows followed)

    def _to_top(self):
        """(Where the list is now is where _hold_rows keeps it from here on.)"""
        self.list_area.verticalScrollBar().setValue(0)
        self._list_top = self.list_area.viewport().mapTo(self.window(), QPoint(0, 0)).y()

    def _clear(self):
        self._stop_preview()
        for r in self._rows:
            self._grid.removeWidget(r)
            r.deleteLater()
        self._rows.clear()
        self._cols = 0
        self.btn_more.hide()

    def _row_alive(self, row: SoundRow) -> bool:
        return not self._closed and row in self._rows

    # ------------------------------------------------------------------ hear and add
    def _get(self, row: SoundRow, what: str):
        """Fetch the row's file (once), then play or add it."""
        key = (row.sound.id, what)
        if key in self._busy:
            return
        self._busy.add(key)
        s = row.sound

        def run():
            try:
                busy.emit(self._fetched, row, (what, str(store.fetch(s))), "")
            except Exception as e:  # noqa: BLE001 - never a crash
                log.info("couldn't fetch store sound %s: %s", s.id, e)
                busy.emit(self._fetched, row, (what, ""),
                          str(e) if isinstance(e, store.StoreError) else errors.plain(e))
        threading.Thread(target=run, daemon=True, name="store-fetch").start()

    def _on_fetched(self, row: SoundRow, got, err: str):
        what, path = got
        self._busy.discard((row.sound.id, what))
        if not self._row_alive(row):
            return
        if what == "add":
            busy.set_busy(row.btn_add, False)
        if not path:
            if what == "play":
                self._stop_preview()
            busy.toast(self.window(), html.escape(_("Couldn't get “{name}”: {error}",
                                                    name=row.sound.name, error=err)), "error")
            return
        if what == "add":
            usage.used("store-added")
            self.bun.cheer()
            self._add_file(path)   # (the window says "Added …" itself)
        else:
            self._decode(row, path)

    def add(self, row: SoundRow):
        if self._is_voice(row):
            assert self.voices is not None   # (only listed with them)
            said = self.voices.take(row.sound)
            usage.used("store-voice-added")
            busy.toast(self.window(), html.escape(said), "ok")
            return
        if row.sound.is_link:   # downloaded from its site, as a pasted link is
            usage.used("store-added")
            self.bun.cheer()
            self._link(row.sound.link, row.sound.name, "add")
            return
        if (row.sound.id, "add") in self._busy:
            return
        busy.set_busy(row.btn_add, True)
        self._get(row, "add")

    @staticmethod
    def _is_voice(row) -> bool:
        from soundboard.online.storevoices import Voice
        return isinstance(row.sound, Voice)

    def _hear_voice(self, row: SoundRow):
        """A community voice's sample: the line said through it, made off the UI thread."""
        serial, v = self._hear_serial, row.sound
        assert not isinstance(v, store.Sound)   # (a voice's row: _is_voice)
        module = self.voices.ai_module() if self.voices is not None else None

        def run():
            from soundboard.online import storevoices
            try:
                data, left_out = storevoices.preview(v, module)
                busy.emit(self._decoded, row, (data, left_out), 1.0, serial)
            except Exception as e:  # noqa: BLE001 - no sound, no crash
                log.info("couldn't make a voice's sample: %s", e)
                busy.emit(self._decoded, row, None, 1.0, serial)
        threading.Thread(target=run, daemon=True, name="store-voice-sample").start()

    def _is_link(self, row) -> bool:
        return not self._is_voice(row) and row.sound.is_link

    def play_clicked(self, row: SoundRow):
        """The card's Play. A link (from its site, as a search hit): played now, over a
        link that's playing; while it plays, Pause (and Resume). Else its sample, to you."""
        if not self._is_link(row):
            self.hear(row, row is not self._playing)
            return
        s = row.sound
        state = self._link_state(s.link)
        if state in ("playing", "paused"):
            self._link(s.link, s.name, "pause")
        elif state != "loading":
            self._stop_preview()
            usage.used("store-heard")
            self._link(s.link, s.name, "now")
        self._follow_links()
        if not row.state:   # (the click switched it on: off until the player has it)
            row.link_look("")

    def stop_clicked(self, row: SoundRow):
        if self._is_link(row):
            self._link(row.sound.link, row.sound.name, "stop")
            self._follow_links()
        else:
            self._stop_preview()

    def queue(self, row: SoundRow):
        """Play next: a link plays after what's playing (Up next), at once if nothing is."""
        if self._is_link(row):
            self._stop_preview()
            usage.used("store-heard")
            self._link(row.sound.link, row.sound.name, "play")
            self._follow_links()

    def _follow_links(self):
        """Every link card shows what the player is doing with it (the bottom strip and
        Up next stop, pause and start it too)."""
        if self._closed:
            return
        for r in self._rows:
            if self._is_link(r):
                state = self._link_state(r.sound.link)
                if state != r.state:
                    r.link_look(state)

    def hear(self, row: SoundRow, on: bool):
        if self._is_voice(row):
            if self._playing is not None and self._playing is not row:
                self._stop_preview()
            self._hear_serial += 1
            if not on:
                self._stop_preview()
                return
            self._playing = row
            row.playing_look(True)
            self._hear_voice(row)
            return
        if self._playing is not None and self._playing is not row:
            self._stop_preview()
        self._hear_serial += 1
        if not on:
            self._stop_preview()
            return
        self._playing = row
        row.playing_look(True)
        self._get(row, "play")

    def _decode(self, row: SoundRow, path: str):
        serial = self._hear_serial

        def run():
            try:
                data = library.decode(path)
                busy.emit(self._decoded, row, data, library.level_gain(data), serial)
            except Exception:  # noqa: BLE001 - a broken file: no sound, no crash
                log.warning("couldn't decode store sound %s", path, exc_info=True)
                busy.emit(self._decoded, row, None, 1.0, serial)
        threading.Thread(target=run, daemon=True, name="store-decode").start()

    def _on_decoded(self, row: SoundRow, data, gain: float, serial: int):
        if not self._row_alive(row) or serial != self._hear_serial or self._playing is not row:
            return
        if isinstance(data, tuple):   # a voice's sample, and whether its AI part was left out
            data, left_out = data
            if left_out:
                busy.toast(self.window(), html.escape(
                    _("You're hearing it without its AI voice: get AI voices (Voice tab "
                      "→ AI voices) to hear all of it.")), "warn", 7000)
        if data is None or not self._play(data, gain):
            self._stop_preview()
            if data is not None:
                busy.toast(self.window(), html.escape(
                    _("Pick your headphones in Settings → Audio to hear the samples.")), "warn")
            return
        usage.used("store-heard")
        self.bun.burst(3)
        QTimer.singleShot(int(len(data) / SR * 1000) + 150, self,
                          lambda s=serial: s == self._hear_serial and self._stop_preview())

    def _stop_preview(self):
        row, self._playing = self._playing, None
        if row is not None:
            try:
                with _blocked(row.btn_play):
                    row.btn_play.setChecked(False)
                row.playing_look(False)
            except RuntimeError:   # its row went meanwhile
                pass
            self._play(None, 1.0)

    # ------------------------------------------------------------------ votes and reports
    def vote(self, row: SoundRow, value: int):
        s = row.sound
        if (s.id, "vote") in self._busy:
            row.show_votes()   # (a click while one is on its way: shown as it was)
            return
        value = 0 if s.mine == value else value   # the same thumb again takes it back
        old = (s.up, s.down, s.mine)
        # shown at once; the store's answer puts in the real counts
        s.up += (value == 1) - (s.mine == 1)
        s.down += (value == -1) - (s.mine == -1)
        s.mine = value
        row.show_votes()
        if value == 1:
            self.bun.burst(4)
        self._busy.add((s.id, "vote"))
        install = self.install()

        def run():
            try:
                if self._is_voice(row):
                    from soundboard.online import storevoices
                    busy.emit(self._voted, row, storevoices.vote(install, s.id, value), "")
                else:
                    busy.emit(self._voted, row, store.vote(install, s.id, value), "")
            except Exception as e:  # noqa: BLE001
                busy.emit(self._voted, row, old,
                          str(e) if isinstance(e, store.StoreError) else errors.plain(e))
        threading.Thread(target=run, daemon=True, name="store-vote").start()

    def _on_voted(self, row: SoundRow, counts, err: str):
        self._busy.discard((row.sound.id, "vote"))
        if not self._row_alive(row):
            return
        row.sound.up, row.sound.down, row.sound.mine = counts
        row.show_votes()
        if err:
            busy.toast(self.window(), html.escape(_("Your vote didn't go through: {error}",
                                                    error=err)), "error")
        else:
            usage.used("store-voted")

    def report_menu(self, row: SoundRow):
        m = QMenu(self)
        m.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        reasons = ((("offensive", _("It's offensive")), ("broken", _("It doesn't work")),
                    ("other", _("Something else"))) if self._is_voice(row) else
                   (("copyright", _("It's someone else's sound")),
                    ("offensive", _("It's offensive")),
                    ("broken", _("It doesn't play")),
                    ("other", _("Something else"))))
        for key, text in reasons:
            m.addAction(text, lambda k=key: self.report(row, k))
        m.popup(row.btn_report.mapToGlobal(row.btn_report.rect().bottomLeft()))

    def report(self, row: SoundRow, reason: str):
        s, install = row.sound, self.install()

        voice = self._is_voice(row)

        def run():
            try:
                if voice:
                    from soundboard.online import storevoices
                    storevoices.report(install, s.id, reason)
                else:
                    store.report(install, s.id, reason)
                busy.emit(self._voted, row, (s.up, s.down, s.mine), "")
            except Exception as e:  # noqa: BLE001
                busy.emit(self._voted, row, (s.up, s.down, s.mine),
                          str(e) if isinstance(e, store.StoreError) else errors.plain(e))
        busy.toast(self.window(), html.escape(_("Thanks: the voice will be checked.") if voice
                                              else _("Thanks: the sound will be checked.")), "ok")
        threading.Thread(target=run, daemon=True, name="store-report").start()

    # ------------------------------------------------------------------ sharing
    def share(self, link: str = "", name: str = ""):
        """The Share a sound window; with `link`, on that link (a sound of yours that
        was downloaded from it)."""
        if not net.allowed(store.FEATURE):
            busy.toast(self.window(), html.escape(net.off_message(store.FEATURE)), "error")
            return
        if store.is_down():
            busy.toast(self.window(), html.escape(store.down_share()), "warn")
            return
        dlg = ShareDialog(self.install(), self, link, name)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.show()

    def share_voice(self, pick: str = ""):
        """The Share a voice window (`pick`: the one picked first, as its list shows it)."""
        if self.voices is None:
            return
        if not net.allowed(store.FEATURE):
            busy.toast(self.window(), html.escape(net.off_message(store.FEATURE)), "error")
            return
        from soundboard.ui.storevoices import open_share
        dlg = open_share(self, self.install(), self.voices, pick)
        if dlg is not None:
            dlg.accepted.connect(lambda: self._mode == "voices" and self.reload())


def _title(text: str) -> QLabel:
    """A small dialog's one big line (as the Send feedback box's)."""
    lab = QLabel(text)
    f = lab.font()
    f.setPointSizeF(f.pointSizeF() * 1.3)
    f.setBold(True)
    lab.setFont(f)
    lab.setWordWrap(True)
    return lab


class _blocked:
    """Signals off on a widget for a `with` block."""

    def __init__(self, w):
        self.w = w

    def __enter__(self):
        self.was = self.w.blockSignals(True)

    def __exit__(self, *_exc):
        self.w.blockSignals(self.was)


class ShareDialog(QDialog):
    """Share a sound with the store: a file (name it, agree it's yours to give away as
    CC0) or a link to a video or sound site (only the link is kept). Two pages: the
    form, then "Thanks, it'll show once it's checked". `link` (and `name`) open it on
    the link, filled in: a sound of yours downloaded from one."""
    _sent = Signal(str)   # worker -> UI: the error, "" when it went

    def __init__(self, install: str, parent=None, link: str = "", name: str = ""):
        super().__init__(parent)
        self.install = install
        self.path = ""
        self.sent = False   # shared: the thanks page is up
        self._closed = False
        self.setWindowTitle(_("Share a sound"))
        self.setMaximumWidth(520)
        self._sent.connect(self._on_sent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)
        self.pages = QStackedWidget()
        lay.addWidget(self.pages)

        form = QWidget()
        v = QVBoxLayout(form)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        v.addWidget(_title(_("Share a sound with everyone")))
        # a file or a link: two choice tiles, the picked one in the accent
        modes = QHBoxLayout()
        modes.setSpacing(8)
        self.mode_btns: dict[str, QPushButton] = {}
        for key, text, icon in (("file", _("A file"), "folder"), ("link", _("A link"), "link")):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setAutoExclusive(True)
            icons.set_icon(b, icon, "text", "on_accent")
            b.clicked.connect(lambda _c=False, k=key: self.set_mode(k))
            modes.addWidget(b)
            self.mode_btns[key] = b
        modes.addStretch(1)
        v.addLayout(modes)
        self.mode_hint = hint_label("")
        v.addWidget(self.mode_hint)
        self.file_box = QWidget()
        pick = QHBoxLayout(self.file_box)
        pick.setContentsMargins(0, 0, 0, 0)
        pick.setSpacing(8)
        self.btn_file = QPushButton(_("Choose a file"))
        icons.set_icon(self.btn_file, "folder")
        self.btn_file.clicked.connect(self.choose)
        pick.addWidget(self.btn_file)
        self.file_lbl = QLabel(_("No file picked"))
        self.file_lbl.setObjectName("hint")
        self.file_lbl.setTextFormat(Qt.TextFormat.PlainText)
        self.file_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        pick.addWidget(self.file_lbl, 1)
        v.addWidget(self.file_box)
        self.link = QLineEdit(link)
        self.link.setPlaceholderText(_("Paste a link: https://www.youtube.com/watch?v=…"))
        self.link.setAccessibleName(_("Link"))
        self.link.textChanged.connect(self._ready)
        v.addWidget(self.link)
        self.name = QLineEdit()
        self.name.setMaxLength(60)
        self.name.setPlaceholderText(_("Name (what it is)"))
        self.name.setAccessibleName(_("Name"))
        self.name.textChanged.connect(self._ready)
        v.addWidget(self.name)
        self.tags = QLineEdit()
        self.tags.setMaxLength(200)
        self.tags.setPlaceholderText(_("Tags, with commas (optional): meme, horn, game"))
        self.tags.setAccessibleName(_("Tags"))
        v.addWidget(self.tags)
        self.agree = QCheckBox(_("This sound is mine to give away"))
        self.agree.toggled.connect(self._ready)
        v.addWidget(self.agree)
        self.terms = terms = hint_label(_(
            "I made or recorded it myself, and I give it away as CC0: anyone may use it for "
            "anything, for free. No songs, clips from shows or games, or other people's "
            "sounds: those are removed.") + " " + _(
            "Is a sound in the store yours? Email {email} and it comes down.",
            email=store.CONTACT))
        terms.setContentsMargins(26, 0, 0, 4)   # under the box's text, not its tick
        terms.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)   # the email
        v.addWidget(terms)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setObjectName("hint")
        self.error.hide()
        v.addWidget(self.error)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.btn_send = QPushButton(_("Share"))
        self.btn_send.setObjectName("primary")
        self.btn_send.clicked.connect(self.send)
        buttons.addWidget(self.btn_send)
        cancel = QPushButton(_("Cancel"))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        buttons.addStretch(1)
        v.addLayout(buttons)
        v.addStretch(1)   # room left over (the other choice's parts hidden) goes below
        self.pages.addWidget(form)

        done = QWidget()
        dv = QVBoxLayout(done)
        dv.setContentsMargins(0, 0, 0, 0)
        dv.setSpacing(10)
        dv.addWidget(_title(_("Thanks for sharing!")))
        dv.addWidget(hint_label(_("It shows in the store once it's been checked, usually "
                                  "within a few days.")))
        db = QHBoxLayout()
        ok = QPushButton(_("Done"))
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        db.addWidget(ok)
        db.addStretch(1)
        dv.addLayout(db)
        dv.addStretch(1)
        self.pages.addWidget(done)
        if name:
            self.name.setText(name[:60])
        self.set_mode("link" if link else "file")
        fit.watch(self)

    def set_mode(self, mode: str):
        """Share a file, or a link."""
        self.mode = "link" if mode == "link" else "file"
        is_link = self.mode == "link"
        self.mode_btns[self.mode].setChecked(True)
        self.file_box.setVisible(not is_link)
        self.agree.setVisible(not is_link)
        self.terms.setVisible(not is_link)
        self.link.setVisible(is_link)
        self.mode_hint.setText(
            _("A YouTube, TikTok, SoundCloud or other video link. Only the link is kept: "
              "whoever adds it gets it from that site. It shows once it's been checked.")
            if is_link else
            _("MP3, OGG, WAV or FLAC, up to 4 MB. It shows in the store once it's been "
              "checked."))
        self._show_error("")
        self._ready()
        if self.isVisible():   # the other choice's parts went: as tall as this one needs
            QTimer.singleShot(0, self, self._shrink)

    def sizeHint(self) -> QSize:
        return QSize(500, super().sizeHint().height())

    def choose(self):
        path, _f = QFileDialog.getOpenFileName(
            self, _("Choose a sound to share"), str(Path.home()),
            _("Sounds") + " (*.mp3 *.ogg *.wav *.flac)")
        if path:
            self.set_file(path)

    def set_file(self, path: str):
        self.path = path
        self.file_lbl.setText(Path(path).name)
        self.file_lbl.setToolTip(path)
        if not self.name.text().strip():
            self.name.setText(Path(path).stem.replace("_", " ")[:60])
        why = store.check_file(path)
        self._show_error(why)
        self._ready()

    def _show_error(self, text: str):
        self.error.setText(text)
        self.error.setVisible(bool(text))
        if text:
            from soundboard import theme
            theme.set_tone(self.error, "error")

    def _ready(self):
        if getattr(self, "mode", "file") == "link":
            url = self.link.text().strip()
            ok = bool(store.link_ok(url) and self.name.text().strip())
            why = _("Paste a link and name it first")
            # a pasted link the store won't take says so at once
            self._show_error("" if not url or store.link_ok(url) else _(
                "The store takes links to YouTube, TikTok, SoundCloud and other video "
                "and sound sites."))
        else:
            ok = bool(self.path and self.name.text().strip() and self.agree.isChecked()
                      and not store.check_file(self.path))
            why = _("Pick a file, name it and tick the box first")
        busy.set_busy(self.btn_send, not ok)   # greyed until it can go (never disabled)
        self.btn_send.setToolTip("" if ok else why)

    def send(self):
        if busy.is_busy(self.btn_send):
            return
        release = busy.hold(self.btn_send, _("Sharing…"))
        self._release = release
        path, name, tags, install = self.path, self.name.text(), self.tags.text(), self.install
        link = self.link.text().strip() if self.mode == "link" else ""

        def run():
            try:
                if link:
                    store.share_link(install, link, name, tags)
                else:
                    store.upload(install, path, name, tags)
                busy.emit(self._sent, "")
            except Exception as e:  # noqa: BLE001
                log.info("couldn't share a sound: %s", e)
                busy.emit(self._sent, str(e) if isinstance(e, store.StoreError)
                          else errors.plain(e))
        threading.Thread(target=run, daemon=True, name="store-share").start()

    def _on_sent(self, err: str):
        if self._closed:
            return
        self._release()
        if err:
            self._show_error(err)
            return
        usage.used("store-shared")
        self.sent = True
        # the stack is as tall as its tallest page: the form goes, so the short thanks
        # page shrinks the window (there's no way back to the form from it)
        form = self.pages.widget(0)
        assert form is not None
        self.pages.setCurrentIndex(1)
        self.pages.removeWidget(form)
        form.hide()
        form.deleteLater()
        lay = self.layout()
        assert lay is not None
        # measured once Qt has given the form's room back (after this event)
        QTimer.singleShot(0, self, self._shrink)

    def _shrink(self):
        """As short as the thanks page: Qt keeps a shown dialog's height, so the
        height is pinned to what's needed for a moment, then let go."""
        lay = self.layout()
        if lay is None:
            return
        lay.activate()
        h = lay.totalMinimumSize().height()
        self.setFixedHeight(h)
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.resize(self.width(), h)

    def done(self, r: int):
        self._closed = True
        super().done(r)

