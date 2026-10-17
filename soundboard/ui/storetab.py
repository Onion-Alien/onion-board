"""The Store tab: free sounds anyone can add to their board (soundboard.store), the best
voted first, and a way to share your own.

Nothing goes online until the tab is first opened. Every call runs on a worker thread
and comes back through busy.emit, so a closed tab or window never gets a late answer."""
from __future__ import annotations

import html
import logging
import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QHBoxLayout,
                               QLabel, QLineEdit, QMenu, QPushButton, QScrollArea,
                               QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from soundboard import errors, library, net, store, usage, ytdl
from soundboard.engine import SR
from soundboard.i18n import _
from soundboard.ui import busy, fit, icons
from soundboard.ui.panel import (HoverCard, card, hint_label, icon_button, info_button,
                                 section_label)
from soundboard.ui.widgets import DropdownMenu
from soundboard.ui.ytsearch import ClampLabel

log = logging.getLogger(__name__)

PREVIEW = "__store_preview"   # the store's "hear it first" voice (headphones only)
SEARCH_WAIT_MS = 400          # typing pauses this long before the store is searched
ROW_MAX_W = 760               # the list stays a readable column on a wide window
COUNT_W = "9.9k"              # the widest vote count kept room for
TRENDING = "trending"         # the order menu's Trending on Myinstants: not the store's
TREND_PAGE = 20               # trending sounds asked for at a time


def meta_line(s: store.Sound) -> str:
    """"by Onion Board · tavern, music", "Shared by a player", or for a shared link
    "YouTube link · Shared by a player"."""
    from soundboard import sourceinfo
    who = _("by {name}", name=s.author) if s.author else _("Shared by a player")
    site = sourceinfo.site_of(s.link) if s.is_link else None
    where = [_("{site} link", site=site[1])] if site else []
    return " · ".join([*where, who, *([", ".join(s.tags)] if s.tags else [])])


def trend_sound(r: ytdl.Result) -> store.Sound:
    """A Myinstants trending hit as a row: a link, played or added from Myinstants."""
    return store.Sound("myinstants:" + r.id, r.title, "link", link=r.url, author="Myinstants")


def count_text(n: int) -> str:
    return f"{n / 1000:.1f}k".replace(".0k", "k") if n >= 1000 else str(n)


class SoundRow(HoverCard):
    """One sound: play it, vote on it, add it to your board, or report it."""

    def __init__(self, s: store.Sound, tab: StoreTab, trending: bool = False):
        super().__init__()
        self.sound = s
        self.trending = trending   # from Myinstants: no votes or reports (not the store's)
        self.setMaximumWidth(ROW_MAX_W)
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 8, 12, 8)
        h.setSpacing(8)
        self.btn_play = icon_button("play", _("Play it once (from the site)") if s.is_link
                                    else _("Hear it (only you)"))
        self.btn_play.setCheckable(True)
        self.btn_play.setFixedSize(32, 32)
        self.btn_play.toggled.connect(lambda on: tab.hear(self, on))
        h.addWidget(self.btn_play)
        words = QVBoxLayout()
        words.setSpacing(0)
        # one line each, ending in "…" when the row is narrow (the whole text on hover)
        self.name = ClampLabel(s.name, lines=1)
        self.name.set_full(s.name, s.name)
        meta = _("Trending on Myinstants") if trending else meta_line(s)
        self.meta = ClampLabel(meta, lines=1, bold=False)
        self.meta.setObjectName("hint")
        self.meta.set_full(meta, meta)
        for lbl in (self.name, self.meta):
            lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            lbl.setMinimumWidth(40)
        words.addWidget(self.name)
        words.addWidget(self.meta)
        h.addLayout(words, 1)
        self.btn_up = self._vote_button("like", _("I like it"))
        self.btn_up.clicked.connect(lambda: tab.vote(self, 1))
        self.btn_down = self._vote_button("dislike", _("Not for me"))
        self.btn_down.clicked.connect(lambda: tab.vote(self, -1))
        h.addWidget(self.btn_up)
        h.addWidget(self.btn_down)
        self.btn_add = icon_button("plus", _("Add it to your Sounds"), quiet=False)
        self.btn_add.setFixedSize(32, 32)
        self.btn_add.clicked.connect(lambda: tab.add(self))
        h.addWidget(self.btn_add)
        self.btn_report = icon_button("flag", _("Report this sound"))
        self.btn_report.clicked.connect(lambda: tab.report_menu(self))
        h.addWidget(self.btn_report)
        for b in (self.btn_up, self.btn_down, self.btn_report):
            b.setVisible(not trending)
        self.show_votes()

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
            if not b.property("steady"):   # room for the widest count, so rows line up
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

    def __init__(self, cfg, add_file: Callable[[str], None],
                 play: Callable[[object, float], bool], open_privacy: Callable[[], object],
                 save: Callable[[], None] = lambda: None,
                 link: Callable[[str, str, str], None] = lambda url, name, kind: None):
        super().__init__()
        self.cfg = cfg
        self._save = save
        self._link = link   # (url, name, "play" / "add"): the window's link downloader
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

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)
        info = info_button(_("Every sound here is CC0: free for anyone to use for anything, "
                             "no credit needed. Sounds people share are checked before they "
                             "show up. Vote for the ones you like so others find them."))
        # (no hint line: the ⓘ says it, and the tab fits the smallest window)
        head, hv = card(_("Sound store"), icon="store", beside=info)
        head.setMaximumWidth(ROW_MAX_W)
        # the main button on a row of its own: beside the search box and the order, the
        # card was wider than the smallest window (that turns into the mini player)
        share_row = QHBoxLayout()
        self.btn_share = QPushButton(_("Share a sound"))
        self.btn_share.setObjectName("primary")
        icons.set_icon(self.btn_share, "upload", "on_accent", "on_accent")
        self.btn_share.clicked.connect(lambda: self.share())
        share_row.addWidget(self.btn_share)
        share_row.addStretch(1)
        hv.addLayout(share_row)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Search the store"))
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName(_("Search the store"))
        self._search_wait = QTimer(self, singleShot=True, interval=SEARCH_WAIT_MS)
        self._search_wait.timeout.connect(self.reload)
        self.search.textChanged.connect(lambda _t: self._search_wait.start())
        row.addWidget(self.search, 1)
        # the order: one quiet button with a menu, as the Sounds tab's order button
        self._sort = "top"
        self.btn_sort = QPushButton()
        self.btn_sort.setProperty("quiet", True)
        self.btn_sort.setProperty("toolbarMenu", True)
        self.btn_sort.setAccessibleName(_("Order"))
        icons.set_icon(self.btn_sort, "sort")
        sort_menu = DropdownMenu(self.btn_sort)
        sort_menu.setToolTipsVisible(True)
        group = QActionGroup(sort_menu)
        self.sort_actions = {}
        for key, text, tip in (("top", _("Top"), _("The best voted first")),
                               ("new", _("New"), _("The newest first")),
                               (TRENDING, _("Trending on Myinstants"),
                                _("The meme sounds people play most on Myinstants right "
                                  "now"))):
            if key == TRENDING:
                sort_menu.addSeparator()
            a = sort_menu.addAction(text)
            a.setCheckable(True)
            a.setChecked(key == "top")
            a.setToolTip(tip)
            group.addAction(a)
            a.triggered.connect(lambda _c=False, k=key: self.set_sort(k))
            self.sort_actions[key] = a
        self.btn_sort.setMenu(sort_menu)
        self.btn_sort.setText(_("Top"))
        row.addWidget(self.btn_sort)
        self.btn_reload = icon_button("reload", _("Refresh"))
        self.btn_reload.clicked.connect(lambda: self.reload())
        row.addWidget(self.btn_reload)
        hv.addLayout(row)
        outer.addWidget(head)

        # the list, or a message in its place (loading, nothing found, off, failed)
        self.stack = QStackedWidget()
        scroll = self.list_area = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        self._list = QVBoxLayout(body)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(6)
        self.btn_more = QPushButton(_("Show more"))
        self.btn_more.clicked.connect(self.more)
        self.btn_more.hide()
        self._list.addWidget(self.btn_more, 0, Qt.AlignmentFlag.AlignLeft)
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
        self.stack.setMaximumWidth(ROW_MAX_W)   # the list and its messages: one column
        outer.addWidget(self.stack, 1)
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
        self._stop_preview()

    def showEvent(self, e):
        super().showEvent(e)
        # nothing goes online until the tab is first opened; switched back on in
        # Settings meanwhile, the list comes when it's shown again
        if not self._loaded or (self._off and net.allowed(store.FEATURE)):
            self._loaded = True
            QTimer.singleShot(0, self, self.reload)

    def hideEvent(self, e):
        self._stop_preview()   # another tab: the sample stops
        super().hideEvent(e)

    # ------------------------------------------------------------------ the list
    def _sort_key(self) -> str:
        return self._sort

    def set_sort(self, key: str):
        """Top (the best voted first), New, or Trending on Myinstants (not the store's
        sounds: Myinstants' trending page, ytdl.trending)."""
        self._sort = key if key in ("new", TRENDING) else "top"
        self.sort_actions[self._sort].setChecked(True)
        self.btn_sort.setText({"new": _("New"), TRENDING: _("Trending")}.get(self._sort,
                                                                            _("Top")))
        self.reload()

    @property
    def trending(self) -> bool:
        return self._sort == TRENDING

    def _say(self, icon: str, title: str, text: str, button: str = "",
             do: Callable[[], object] | None = None):
        self.msg_icon.setPixmap(icons.pixmap(icon, 32, icons.resolve("muted")))
        self.msg_title.setText(title)
        self.msg_text.setText(text)
        self.msg_text.setVisible(bool(text))
        self.msg_btn.setText(button)
        self.msg_btn.setVisible(bool(button))
        self._msg_do = do
        self.stack.setCurrentWidget(self.message)

    def _message_action(self):
        if self._msg_do is not None:
            self._msg_do()

    def reload(self, direct: bool = False):
        """The list again from the top (the search or the order changed, Refresh).
        `direct`: trending without Tor (the user's click, after Tor was turned away)."""
        self._search_wait.stop()
        self._offset = 0
        self._fetch_list(replace=True, direct=direct)

    def more(self):
        self._fetch_list(replace=False)

    def _fetch_list(self, replace: bool, direct: bool = False):
        if self._closed:
            return
        if self.trending:
            self._fetch_trending(replace, direct)
            return
        self._off = not net.allowed(store.FEATURE)
        if self._off:
            self._clear()
            self._say("offline", _("The store is off"), net.off_message(store.FEATURE),
                      _("Privacy && security settings"), self._open_privacy)
            return
        self._serial += 1
        serial, sort, query, offset = (self._serial, self._sort_key(), self.search.text(),
                                       0 if replace else self._offset)
        install = self.install()
        if replace:
            self._say("store", _("Loading the store…"), "")
        else:
            busy.set_busy(self.btn_more, True)

        def run():
            try:
                found, more = store.browse(install, sort, query, offset)
                busy.emit(self._listed, serial, (replace, found), more, "")
            except Exception as e:  # noqa: BLE001 - offline, switched off, the server…
                log.info("couldn't read the store: %s", e)
                busy.emit(self._listed, serial, (replace, None), False,
                          str(e) if isinstance(e, store.StoreError) else errors.plain(e))
        threading.Thread(target=run, daemon=True, name="store-list").start()

    def _fetch_trending(self, replace: bool, direct: bool):
        """Myinstants' trending sounds, `TREND_PAGE` at a time; a search filters them
        by name (Myinstants' trending page has no search of its own)."""
        self._off = not ytdl.site_allowed("myinstants")
        if self._off:
            self._clear()
            self._say("offline", _("Trending on Myinstants"),
                      net.off_message(ytdl.site_feature("myinstants")),
                      _("Privacy && security settings"), self._open_privacy)
            return
        self._serial += 1
        serial, start = self._serial, 1 if replace else self._offset + 1
        if replace:
            usage.used("search-trending")
            self._say("myinstants", _("Loading what's trending on Myinstants…"), "")
        else:
            busy.set_busy(self.btn_more, True)

        def run():
            try:
                hits = ytdl.trending(count=start - 1 + TREND_PAGE, direct=direct, start=start)
                busy.emit(self._listed, serial, (replace, [trend_sound(r) for r in hits]),
                          len(hits) >= TREND_PAGE, "")
            except ytdl.TorBlocked as e:   # offered without Tor, never done unasked
                busy.emit(self._listed, serial, (replace, None), False, "tor:" + str(e))
            except Exception as e:  # noqa: BLE001 - offline, switched off, the site…
                log.info("couldn't read Myinstants' trending: %s", e)
                busy.emit(self._listed, serial, (replace, None), False,
                          str(e) if isinstance(e, ytdl.DownloadError) else errors.plain(e))
        threading.Thread(target=run, daemon=True, name="store-trending").start()

    def _on_listed(self, serial: int, got, more: bool, err: str):
        if self._closed or serial != self._serial:
            return
        replace, found = got
        busy.set_busy(self.btn_more, False)
        if found is None:
            if self.trending and replace:
                self._clear()
                tor = err.startswith("tor:")
                self._say("warn", _("Trending on Myinstants"), err.removeprefix("tor:"),
                          _("Try this one without Tor") if tor else _("Try again"),
                          (lambda: self.reload(direct=True)) if tor else self.reload)
            elif replace:
                self._clear()
                self._say("warn", _("Couldn't open the store"), err, _("Try again"), self.reload)
            else:
                busy.toast(self.window(), html.escape(err), "error")
            return
        if replace:
            self._clear()
        self._offset += len(found)
        if self.trending:   # filtered by the search box's words, here
            words = self.search.text().casefold().split()
            found = [s for s in found if all(w in s.name.casefold() for w in words)]
        for s in found:
            r = SoundRow(s, self, trending=self.trending)
            self._list.insertWidget(self._list.indexOf(self.btn_more), r)
            self._rows.append(r)
        self.btn_more.setVisible(more)
        if not self._rows:
            if self.trending and more and self.search.text().strip():
                self.stack.setCurrentWidget(self.list_area)   # Show more may find some
                return
            if self.trending and not self.search.text().strip():
                self._say("myinstants", _("Nothing is trending on Myinstants right now."), "")
            elif self.search.text().strip():
                self._say("search", _("Nothing matches"), _("Try other words."))
            else:
                self._say("store", _("No sounds here yet"),
                          _("Be the first: share a sound you made."), _("Share a sound"),
                          self.share)
            return
        self.stack.setCurrentWidget(self.list_area)

    def _clear(self):
        self._stop_preview()
        for r in self._rows:
            self._list.removeWidget(r)
            r.deleteLater()
        self._rows.clear()
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
            self._add_file(path)   # (the window says "Added …" itself)
        else:
            self._decode(row, path)

    def add(self, row: SoundRow):
        if row.sound.is_link:   # downloaded from its site, as a pasted link is
            usage.used("store-added")
            self._link(row.sound.link, row.sound.name, "add")
            return
        if (row.sound.id, "add") in self._busy:
            return
        busy.set_busy(row.btn_add, True)
        self._get(row, "add")

    def hear(self, row: SoundRow, on: bool):
        if row.sound.is_link:   # the site's own download, played once (as a search hit)
            with _blocked(row.btn_play):
                row.btn_play.setChecked(False)
            if on:
                self._stop_preview()
                usage.used("store-heard")
                self._link(row.sound.link, row.sound.name, "play")
            return
        if self._playing is not None and self._playing is not row:
            self._stop_preview()
        self._hear_serial += 1
        if not on:
            self._stop_preview()
            return
        self._playing = row
        icons.set_icon(row.btn_play, "stop")
        row.btn_play.setToolTip(_("Stop"))
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
        if data is None or not self._play(data, gain):
            self._stop_preview()
            if data is not None:
                busy.toast(self.window(), html.escape(
                    _("Pick your headphones in Settings → Audio to hear the samples.")), "warn")
            return
        usage.used("store-heard")
        QTimer.singleShot(int(len(data) / SR * 1000) + 150, self,
                          lambda s=serial: s == self._hear_serial and self._stop_preview())

    def _stop_preview(self):
        row, self._playing = self._playing, None
        if row is not None:
            try:
                with _blocked(row.btn_play):
                    row.btn_play.setChecked(False)
                icons.set_icon(row.btn_play, "play")
                row.btn_play.setToolTip(_("Hear it (only you)"))
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
        self._busy.add((s.id, "vote"))
        install = self.install()

        def run():
            try:
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
        for key, text in (("copyright", _("It's someone else's sound")),
                          ("offensive", _("It's offensive")),
                          ("broken", _("It doesn't play")),
                          ("other", _("Something else"))):
            m.addAction(text, lambda k=key: self.report(row, k))
        m.popup(row.btn_report.mapToGlobal(row.btn_report.rect().bottomLeft()))

    def report(self, row: SoundRow, reason: str):
        s, install = row.sound, self.install()

        def run():
            try:
                store.report(install, s.id, reason)
                busy.emit(self._voted, row, (s.up, s.down, s.mine), "")
            except Exception as e:  # noqa: BLE001
                busy.emit(self._voted, row, (s.up, s.down, s.mine),
                          str(e) if isinstance(e, store.StoreError) else errors.plain(e))
        busy.toast(self.window(), html.escape(_("Thanks: the sound will be checked.")), "ok")
        threading.Thread(target=run, daemon=True, name="store-report").start()

    # ------------------------------------------------------------------ sharing
    def share(self, link: str = "", name: str = ""):
        """The Share a sound window; with `link`, on that link (a sound of yours that
        was downloaded from it)."""
        if not net.allowed(store.FEATURE):
            busy.toast(self.window(), html.escape(net.off_message(store.FEATURE)), "error")
            return
        dlg = ShareDialog(self.install(), self, link, name)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.show()


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

