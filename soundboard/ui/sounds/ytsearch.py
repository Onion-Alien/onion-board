"""The Sounds tab's web search: press Enter in "Search sounds" (or the Search
button next to it) and this list takes the pad grid's place. It's a plain list of
hits (thumbnail, title, channel, length) from the site searches in ytdl.SOURCES
(YouTube, YouTube Music, SoundCloud, TikTok sounds, Myinstants), with no web page
and no video. While one runs the list makes way for a loading view: Bun or Hoot
(picked at random each time) over a sliding bar and "Searching YouTube for ...".
Play plays one once and Add adds it as a
pad; both hand the page to the link bar (ui/sounds/linkbar.py), which downloads just its
audio. Sites without a search (Instagram, X…) work by pasting a link into the
search box instead.

A hit's card is ytcard.py (its words: ytlabels.py), the loading view ytwaiting.py.
"""
from __future__ import annotations

import html
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QImage, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from soundboard.core import achievements, usage
from soundboard.online import quality
from soundboard.online import net, netlog, ytdl
from soundboard.ui.window import mouseback
from soundboard.ui.kit import busy, icons, theme
from soundboard.ui.kit.panel import CardGrid, Flow, RoundedFrame
from soundboard.ui.window.responsive import FitWidth
from soundboard.core import errors
from soundboard.i18n import _, ngettext
from soundboard.ui.sounds.ytcard import ResultRow
from soundboard.ui.sounds.ytwaiting import BackHome, SearchingView
# (callers import these from here too)
from soundboard.ui.sounds.ytcard import THUMB_H, THUMB_W, Thumb  # noqa: F401
from soundboard.ui.sounds.ytlabels import (ClampLabel, StatsLabel, _count, fmt_count,  # noqa: F401
                                           plain_tip, stats_text)
from soundboard.ui.sounds.ytwaiting import _BusyOwl  # noqa: F401

log = logging.getLogger(__name__)

CARD_MIN_W = 210             # results are cards, as many across as fit at this width
LINK_CARD_MAX_W = 820        # a pasted link's card: picture beside the words, this wide at most
LINK_LOOKUPS = 4   # pasted links looked up at once (show_links)
PLAYLIST_NAME_MAX = 32   # a pasted playlist's name over its cards, in characters
KIND_BTN_H = 22          # Videos / Playlists: with the toggle's edge, as tall as Back
PAGE = 20          # hits per search, and per Show more
THUMB_TIMEOUT_MS = 15_000     # a picture with no bytes arriving for this long is dropped
THUMB_MAX_BYTES = 5_000_000   # a thumbnail is ~100 kB; a page's og:image can be anything
_decoder: ThreadPoolExecutor | None = None   # thumbnails are decoded here, not on the UI thread
MAX_RESULTS = 200  # Show more stops here: more cards would only cost memory and scrolling
TIPS = {"youtube": _("Search YouTube"),
        "ytmusic": _("Search YouTube Music: songs, the official versions"),
        "soundcloud": _("Search SoundCloud"),
        "tiktok": _("Find TikTok sounds (TikTok's own search needs an account, so this "
                    "looks for them on YouTube, where they get reposted)"),
        "myinstants": _("Search Myinstants: short meme sound buttons")}


def _cap_thumb(reply, got: int, total: int) -> None:
    """Stop a picture that is (or says it will be) far bigger than a thumbnail: a page's
    og:image that's huge or never ends would otherwise grow without limit."""
    if got > THUMB_MAX_BYTES or total > THUMB_MAX_BYTES:
        reply.setProperty("too_big", True)
        reply.abort()


def _thumb_decoder() -> ThreadPoolExecutor:
    global _decoder
    if _decoder is None:
        _decoder = ThreadPoolExecutor(max_workers=2, thread_name_prefix="thumb-decode")
    return _decoder


class KindToggle(QFrame):
    """YouTube's videos or its playlists: two buttons beside Back, the one shown lit
    (the same look as the cards / list switch)."""
    changed = Signal(str)   # "videos" or "playlists"

    def __init__(self):
        super().__init__()
        self.setObjectName("viewtoggle")
        h = QHBoxLayout(self)
        h.setContentsMargins(3, 3, 3, 3)
        h.setSpacing(2)
        self.buttons: dict[str, QPushButton] = {}
        for key, icon, word, tip in (
                ("videos", "play", _("Videos"), _("Show videos")),
                ("playlists", "list", _("Playlists"), _("Show playlists: open one to add "
                                                       "its videos"))):
            b = QPushButton(word)
            b.setObjectName("viewbtn")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            icons.set_icon(b, icon, "muted", "on_accent", size=14)
            b.setToolTip(tip)
            b.clicked.connect(lambda __=False, k=key: self.changed.emit(k))
            h.addWidget(b)
            self.buttons[key] = b
        self.buttons["videos"].setChecked(True)
        self.retheme()

    def kind(self) -> str:
        return "playlists" if self.buttons["playlists"].isChecked() else "videos"

    def retheme(self):
        """Words as well as an icon: the lit one's in the accent's text colour."""
        T = theme.T
        # its own height: the app's sheet sets the toggle buttons' min-height to 0
        css = (f"QPushButton {{ padding:0 12px; min-height:{KIND_BTN_H}px;"
               f" max-height:{KIND_BTN_H}px; color:{T['muted']}; font-weight:600; }}"
               f"QPushButton:checked {{ color:{T['on_accent']}; }}")
        for b in self.buttons.values():
            b.setStyleSheet(css)


class SearchResults(RoundedFrame):
    """`play(Result)` / `add(Result)` when a row's button is pressed; `closed()`
    when its "My sounds" back button is (the owner shows its pads again). Its site
    actions (fill_site_menu: the search button's menu) pick where the search goes and
    re-run it there; source_changed(key) says which one it is now."""
    play = Signal(object)
    add = Signal(object)
    add_all = Signal(list)   # several pasted links' cards: Add all (their results)
    closed = Signal()
    thumb_ready = Signal(str, object)
    source_changed = Signal(str)
    _done = Signal(int, object, str)   # worker -> UI: (search number, results, error)
    _thumb_decoded = Signal(int, str, object)   # worker -> UI: (search number, url, QImage)
    _listed = Signal(str, object, str)   # worker -> UI: (playlist url, its videos, error)

    def __init__(self):
        super().__init__()
        self.query = ""
        self.link = ""          # a pasted link shown as its own card (show_link), not a search
        self.source = "youtube"
        self._gen = 0
        self.failed = False   # the last search came back with an error (firsttour.py)
        self._why = ""        # why it failed, for the usage count (usage.DL_FAILS)
        self._why_more: list[str] = []   # ...and what's known of it (usage.failure_detail)
        # (query, site, playlists?) still being searched
        self._running: tuple[str, str, bool] | None = None
        self._searched_lists = False   # the last search was for playlists
        self._asked = PAGE      # hits asked for so far (Show more asks for the next PAGE)
        self._rows: list[ResultRow] = []
        self.links: list[str] = []   # several links pasted at once (show_links)
        self.playlist = None         # a pasted playlist (ytdl.Playlist): its videos' cards
        self._links_failed = 0       # ...of which this many couldn't be looked up
        self._fetching: dict[str, set[str]] = {}   # url -> {"play", "add"} downloading
        # thumbnails, one network manager per site switch (Settings > Privacy & security)
        self._nams: dict[str, QNetworkAccessManager] = {}
        self._done.connect(self._on_done)
        self._thumb_decoded.connect(self._on_thumb_decoded)
        self._listed.connect(self._on_listed)
        self._listing: dict[str, Any] = {}   # playlist url -> its Add all's busy.hold release

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)   # Back sits as far in from the top as the side
        v.setSpacing(6)
        header = QWidget()
        header.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        header.setContentsMargins(0, 0, 0, 0)   # Back starts where the cards' panels do
        head = Flow(header, gap=8)
        back = self.btn_back = BackHome(_("Back"))   # the way out of the results
        back.setAccessibleName(_("Back to my sounds"))
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        icons.set_icon(back, "back", "danger_text", size=18)
        back.clicked.connect(self._back)
        mouseback.mark(back)
        head.addWidget(back)
        # a YouTube search: its videos or its playlists (a playlist's card opens it)
        self.kind_toggle = KindToggle()
        self.kind_toggle.changed.connect(self._set_kind)
        self.kind_toggle.hide()
        head.addWidget(self.kind_toggle)
        self._opened_from = ""   # the search a playlist was opened from: Back goes there
        # what the cards are when no search words say it: "5 links"
        self.heading = QLabel()
        self.heading.setObjectName("section")
        self.heading.setProperty("head", True)   # no space above: in line with Back
        self.heading.hide()
        head.addWidget(self.heading)
        # several pasted links: all of them to the download queue in one click
        self.add_all_btn = QPushButton()
        self.add_all_btn.setObjectName("primary")
        self.add_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        icons.set_icon(self.add_all_btn, "plus", "on_accent", size=16)
        self.add_all_btn.clicked.connect(self._add_all)
        self.add_all_btn.hide()
        head.addWidget(self.add_all_btn)
        self.site_actions: dict[str, QAction] = {}
        group = QActionGroup(self)
        group.setExclusive(True)
        for key, (name, _prefix) in ytdl.SOURCES.items():
            a = QAction(name, self)
            icons.set_icon(a, key, "accent", "accent")
            a.setCheckable(True)
            a.setChecked(key == self.source)
            a.triggered.connect(lambda _c=False, k=key: self.set_source(k))
            group.addAction(a)
            self.site_actions[key] = a
        v.addWidget(header)
        # "No results", "Can't use this link…", "Couldn't search…": in the middle of the
        # results area, where "Searching…" was, not in a corner under Back
        self.message = QWidget()
        mv = QVBoxLayout(self.message)
        mv.setContentsMargins(24, 0, 24, 0)
        mv.setSpacing(10)
        mv.addStretch(2)
        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.RichText)
        self.title.setWordWrap(True)
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        errors.linkify(self.title)   # an error's "Report it" link
        mv.addWidget(self.title)
        # Tor mode, after the site turned Tor away even over new routes: only this click
        # runs the search without Tor (ytdl.TorBlocked)
        self.direct_btn = QPushButton(_("Search this without Tor"))
        self.direct_btn.setToolTip(_("Run just this search straight from the site, not through "
                                     "Tor: the site will see your own address"))
        self.direct_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        icons.set_icon(self.direct_btn, "tor", size=16)
        self.direct_btn.clicked.connect(self._without_tor)
        self.direct_btn.hide()
        mv.addWidget(self.direct_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        # the search couldn't get through: sad Bun says so, with Try again
        from soundboard.ui.kit import oops
        self.oops = oops.OopsPanel()
        self.oops.hide()
        mv.addWidget(self.oops, 0, Qt.AlignmentFlag.AlignHCenter)
        mv.addStretch(3)
        self.message.hide()
        v.addWidget(self.message, 1)
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
        # the next page of the same search, added below: no paging back and forth
        self.more_btn = QPushButton(_("Show more"))
        self.more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        icons.set_icon(self.more_btn, "fold_open", size=16)
        self.more_btn.clicked.connect(lambda: (usage.used("search-show-more"), self._more()))
        self.more_btn.hide()
        more = QHBoxLayout()
        more.setContentsMargins(0, 4, 0, 0)   # in line with Back and the cards' panels
        more.addWidget(self.more_btn)
        more.addStretch(1)
        lv.addLayout(more)
        self._more_release = None   # busy.hold's release while a page loads
        lv.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.list)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        v.addWidget(scroll, 1)
        self.scroll_area = scroll
        self.hide()
        self.follow_switches()
        net.on_change(self.follow_switches)

    def follow_switches(self):
        """Settings > Privacy & security: a site switched off has its button greyed
        (saying why), and searching moves to one that's on. With finding sounds online
        switched off altogether, open results close."""
        for key, a in self.site_actions.items():
            ok = ytdl.site_allowed(key)
            a.setEnabled(ok)
            a.setToolTip(TIPS.get(key, f"Search {ytdl.SOURCES[key][0]}") if ok
                         else net.off_message(ytdl.site_feature(key)))
        if not ytdl.site_allowed(self.source):
            on = [k for k in self.site_actions if ytdl.site_allowed(k)]
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
        self.site_actions[key].setChecked(True)
        if key != self.source:
            self.source = key
            self.source_changed.emit(key)
            if self.query and not self.isHidden() and not self.link:
                self.search(self.query)
            self._sync_kind()

    def _playlists(self) -> bool:
        """Is the search for YouTube's playlists (the switch beside Back)?"""
        return self.source == "youtube" and self.kind_toggle.kind() == "playlists"

    def _sync_kind(self):
        """The Videos / Playlists switch shows over a YouTube search's results only."""
        self.kind_toggle.setVisible(self.source == "youtube" and bool(self.query)
                                    and not (self.link or self.links))

    def _set_kind(self, kind: str):
        """Videos or Playlists clicked: the same words searched again for those."""
        if (kind == "playlists") == self._searched_lists:
            return   # the one already shown (or on its way)
        usage.used(f"search-{kind}")
        if self.query and not self.link and not self.links:
            self.search(self.query)

    def open_playlist(self, r):
        """A playlist's card opened: its videos as cards, with Add all; Back comes back
        to the playlists found."""
        q = self.query
        if self.show_link(r.url):
            self._opened_from = q

    def _back(self):
        """Back: out of a playlist opened from a search, to that search; else home."""
        q, self._opened_from = self._opened_from, ""
        if q and self.link:
            self.search(q)
        else:
            self.close_results()

    def _row_add(self, r):
        """A card's Add: a playlist's (Add all) lists its videos, then queues them all;
        a video's adds it."""
        if r.source != ytdl.PLAYLIST:
            self.add.emit(r)
            return
        row = next((x for x in self._rows if x.result is r), None)
        if row is None or r.url in self._listing:
            return   # its videos are being listed already
        self._listing[r.url] = busy.hold(row.btn_add, _("Loading…"))
        netlog.cause(ytdl.FEATURE, "You clicked Add all on a playlist: listing its videos")
        threading.Thread(target=self._work_list, args=(r.url,), daemon=True,
                         name="playlist-lookup").start()

    def _work_list(self, url: str):
        try:
            found = ytdl.lookup_all(url)
            hits = list(found) if isinstance(found, ytdl.Playlist) else [found]
            busy.emit(self._listed, url, hits, "")
        except Exception as e:  # noqa: BLE001 - said in a toast
            log.info("playlist look-up failed for %s: %s", url, e)
            busy.emit(self._listed, url, [], errors.html(e, where="Listing a playlist"))

    def _on_listed(self, url: str, hits: list, err: str):
        """A playlist card's Add all, listed: every video to the download queue (the
        same as Add all over its opened cards). Its card may be gone by now (another
        search): the videos are queued all the same, it was the user's click."""
        release = self._listing.pop(url, None)
        row = next((x for x in self._rows if x.result.url == url), None)
        if row is not None and release is not None:
            release(_("Didn't add") if err else None)
        if err:
            busy.toast(self.window(), _("Couldn't add that playlist: {error}", error=err),
                       "error", 8000)
            return
        self.add_all.emit(hits)
        if row is not None:
            row.set_queued_all(len(hits))

    def _row_play(self, r):
        """A card's Play: a playlist's (Open) shows its videos, a video's plays it."""
        if r.source == ytdl.PLAYLIST:
            self.open_playlist(r)
        else:
            self.play.emit(r)

    def fill_site_menu(self, menu: QMenu):
        """The search button's menu: one line per site, the one searched ticked."""
        menu.setToolTipsVisible(True)
        menu.addActions(list(self.site_actions.values()))

    def search(self, query: str, direct: bool = False) -> bool:
        query = " ".join(query.split())
        if not query or not ytdl.site_allowed(self.source):
            return False
        lists = self._playlists()
        if not direct and self._running == (query, self.source, lists) and not self.isHidden():
            return True   # Enter spammed: the same search is still on its way
        achievements.bump("searches")   # (Search Engine)
        self._running = (query, self.source, lists)
        self._searched_lists = lists
        self._opened_from = ""
        self.failed = False
        self._set_links([])
        self.query = query
        self.link = ""
        self._gen += 1
        self._clear()
        self._asked = PAGE
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
                         kwargs={"playlists": lists}, daemon=True, name="web-search").start()
        self._sync_kind()
        return True

    def show_link(self, url: str, direct: bool = False) -> bool:
        """A pasted link: look it up (nothing downloaded) and show it as one card, to
        play or add like a search hit. False when its site is switched off."""
        if not ytdl.site_allowed(url):
            return False
        if url == self.link and not direct and not self.isHidden() and (
                self._rows or self.loading.running()):
            return True   # already showing (Enter after the paste looked it up)
        if url != self.link:   # (Try again keeps the way Back to its search)
            self._opened_from = ""
        self.query = self.link = url
        self._running = None
        self._set_links([])
        self.failed = False
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
        self._sync_kind()
        return True

    def show_links(self, urls: list[str], direct: bool = False) -> bool:
        """Several pasted links: each looked up (nothing downloaded) and shown as a card
        like a search hit, with Add all over them."""
        urls = [u for u in urls if ytdl.site_allowed(u)]
        if not urls:
            return False
        if urls == self.links and not direct and not self.isHidden() and (
                self._rows or self.loading.running()):
            return True   # already showing
        self.query, self.link = " ".join(urls), ""
        self._running = None
        self.failed = False
        self._set_links(urls)
        self._gen += 1
        self._clear()
        netlog.cause(ytdl.FEATURE, f"You pasted {len(urls)} links: looking up their names, "
                                   "pictures and lengths" + (" (without Tor)" if direct else ""))
        text = ngettext("Looking up {n} link…", "Looking up {n} links…", len(urls))
        self.title.setText(text)
        self._loading(True, text)
        self.show()
        self.direct_btn.hide()
        threading.Thread(target=self._work_links, args=(self._gen, list(urls), direct),
                         daemon=True, name="links-lookup").start()
        self._opened_from = ""
        self._sync_kind()
        return True

    def _set_links(self, urls: list[str]):
        """Several links' mode (urls) or not ([]): its heading and Add all."""
        self.links = list(urls)
        self._links_failed = 0
        self.playlist = None
        if not urls:
            self.add_all_btn.hide()
            self.heading.hide()

    def _to_add(self) -> list:
        """The pasted links' cards Add all would still add: not added, not on their way."""
        return [r for r in self._rows if not r._added
                and "add" not in self._fetching.get(r.result.url, ())]

    def _links_heading(self):
        """"5 links", and Add all with how many it still adds (none: it goes)."""
        n = len(self._rows)
        pl = self.playlist
        if pl is None:
            text = ngettext("{n} link", "{n} links", n)
        elif pl.total > n:   # only the first MAX_LINKS are listed
            text = ngettext("{n} of {total} video", "{n} of {total} videos", pl.total,
                            n=n, total=pl.total)
        else:
            text = ngettext("{n} video", "{n} videos", n)
        if pl is not None and pl.title:   # a long name cut short: the count stays in view
            name = pl.title if len(pl.title) <= PLAYLIST_NAME_MAX else (
                pl.title[:PLAYLIST_NAME_MAX - 1].rstrip() + "…")
            text = f"{name}  ·  {text}"
        if self._links_failed:
            text += "  ·  " + ngettext("{n} couldn't be used", "{n} couldn't be used",
                                       self._links_failed)
        self.heading.setText(text)
        self.heading.show()
        n = len(self._to_add())
        self.add_all_btn.setText(_("Add all ({n})", n=n))
        if not n and self.add_all_btn.hasFocus():
            self.btn_back.setFocus()   # (not lost with the button)
        self.add_all_btn.setVisible(n > 0)

    def _add_all(self):
        """Add all: every card's sound not added yet to the download queue
        (searchcontrol.add_all); clicked again, only what's left."""
        results = [r.result for r in self._to_add()]
        if results:
            self.add_all.emit(results)
        self._links_heading()

    def _without_tor(self):
        if self.link:   # (a playlist's too: its videos are self.links)
            self.show_link(self.link, direct=True)
        elif self.links:
            self.show_links(self.links, direct=True)
        else:
            self.search(self.query, direct=True)

    def close_results(self):
        self._gen += 1       # a search still running is ignored when it lands
        self._running = None
        self._loading(False)
        self._clear()
        self.link = ""
        self._set_links([])
        self._opened_from = ""
        self.kind_toggle.hide()
        self.hide()
        self.closed.emit()

    def _loading(self, on: bool, text: str = ""):
        """The loading view in place of the title and list (on), or those back."""
        self.message.hide()   # _say() brings it back for a message
        self.scroll_area.setVisible(not on)
        if on:
            self.loading.start(text)
        else:
            self.loading.stop()

    def _say(self, text: str):
        """A message in the middle of the results area, instead of cards."""
        self.title.setText(text)
        self.title.show()
        self.oops.hide()
        self.scroll_area.hide()
        self.message.show()

    def _fail(self, title: str, err: str):
        """The search (or a link) didn't work: the red card in the
        middle of the results area, Try again runs it once more. The site being down
        isn't something closing the app fixes: no advice to (`errors.site_side`)."""
        self.title.hide()
        down = any(html.escape(w) in err or w in err for w in errors.site_side())
        if down:
            usage.used("search-site-down")
        usage.used("search-failed")
        why = self._why or "other"
        usage.used(f"search-failed-why-{why}")   # the kind only
        if why in ("other", "timeout"):
            usage.failed(f"search-{why}", *self._why_more)
        self._why, self._why_more = "", []
        self.oops.show_problem(title, err, self.try_again, fixable=not down)
        self.oops.show()
        self.scroll_area.hide()
        self.message.show()

    def try_again(self):
        """The same search (link) once more, the same way."""
        if self.link:
            self.show_link(self.link)
        elif self.links:
            self.show_links(self.links)
        else:
            self.search(self.query)

    def mark(self, url: str, kind: str, ok: bool | None = None):
        """A row's Play / Add: busy (ok None) while its audio is fetched, then done."""
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
        if self.links and kind == "add":   # Add all counts what's left
            self._links_heading()

    def show_now(self, url: str, now: str):
        """The player has `url` loaded ("playing" / "paused"), or nothing from here
        (url ""): its card says so."""
        for r in self._rows:
            r.set_now(now if url and r.result.url == url else "")

    def queued(self, url: str, kind: str):
        """The link bar runs one download at a time: this pick waits its turn."""
        for r in self._rows:
            if r.result.url == url:
                r.set_queued(kind)

    def thumb_for(self, url: str) -> QPixmap | None:
        """The picture of `url`'s card, if it has one yet (for the download bar)."""
        return next((r.thumb._pm for r in self._rows
                     if r.result.url == url and r.thumb.has_picture()), None)

    def meta_for(self, url: str) -> tuple[str, float]:
        """The uploader and length of `url`'s card, if it has one (for the download bar)."""
        r = next((r.result for r in self._rows if r.result.url == url), None)
        return (r.channel, r.seconds) if r else ("", 0.0)

    def progress(self, url: str, frac):
        """The link bar's download of `url`: 0..1, 'parsing', or below 0 / 'processing'."""
        for r in self._rows:
            if r.result.url == url:
                r.set_progress(frac)

    def _clear(self):
        """Off the screen now, not when Qt gets round to deleting them: a pasted link's
        one card showed after the last search's cards until then."""
        self.more_btn.hide()
        if self._more_release is not None:   # a page still loading is for the old search
            self._more_release()
            self._more_release = None
        for r in self._rows:
            r.hide()
            self.rows.removeWidget(r)
            self.link_row.removeWidget(r)
            r.deleteLater()
        self._rows = []

    def retheme(self):
        """A theme switch with results open: the cards' own colours follow it."""
        self.kind_toggle.retheme()
        for r in self._rows:
            r._style()
            r.thumb.update()

    def _more(self):
        """Show more: the next PAGE hits of the same search, added under the cards."""
        if (self._more_release is not None or not self.query or self.link
                or self.links):
            return
        start, self._asked = self._asked + 1, min(self._asked + PAGE, MAX_RESULTS)
        self._more_release = busy.hold(self.more_btn, _("Loading…"))
        netlog.cause(ytdl.FEATURE, f"You asked for more {self.site} results for "
                                   f"{netlog.quoted(self.query)}")
        threading.Thread(target=self._work, args=(self._gen, self.query, self.source),
                         kwargs={"start": start, "count": self._asked,
                                 "playlists": self._playlists()},
                         daemon=True, name="web-search-more").start()

    def _work(self, gen: int, query: str, source: str, direct: bool = False,
              start: int = 1, count: int = PAGE, playlists: bool = False):
        """One page of hits for `query` on `source`."""
        try:
            # the user's "without Tor" click
            more: dict[str, Any] = {"direct": True} if direct else {}
            if start > 1:   # Show more (fakes in tests take the first page's arguments)
                more.update(start=start, count=count)
            if playlists:   # (fakes in tests take no such argument)
                more["playlists"] = True
            hits = ytdl.search(query, source=source, **more)
            busy.emit(self._done, gen, hits, "")
        except ytdl.TorBlocked as e:   # offered without Tor, never done unasked
            log.info("%s search turned away over Tor", source)
            busy.emit(self._done, gen, "blocked", html.escape(str(e)))
        except Exception as e:  # noqa: BLE001 - shown in the panel
            log.info("%s search failed for %r: %s", source, query, e)
            self._failed_why(e)
            # rich text: the plain words, and a "Report it" link when it's one for us
            busy.emit(self._done, gen, [], errors.html(e, where=f"Searching {source}"))

    def _failed_why(self, e: BaseException):
        """Why a search or link look-up failed, from yt-dlp's own words, for the usage
        count (_fail)."""
        self._why = errors.download_reason(e)
        self._why_more = usage.failure_detail(self._why, e)

    def _work_link(self, gen: int, url: str, direct: bool):
        try:
            found = ytdl.lookup_all(url, **({"direct": True} if direct else {}))
            busy.emit(self._done, gen, found if isinstance(found, ytdl.Playlist) else [found], "")
        except ytdl.TorBlocked as e:
            log.info("link look-up turned away over Tor")
            busy.emit(self._done, gen, "blocked", html.escape(str(e)))
        except Exception as e:  # noqa: BLE001 - shown in the panel
            log.info("link look-up failed for %s: %s", url, e)
            self._failed_why(e)
            busy.emit(self._done, gen, [], errors.html(e, where="Looking up a link"))

    def _work_links(self, gen: int, urls: list[str], direct: bool):
        """Each pasted link looked up, a few at a time; the ones that work, in the
        order they were pasted (the others counted: _links_failed)."""
        def one(url):
            try:
                return ytdl.lookup(url, **({"direct": True} if direct else {}))
            except ytdl.TorBlocked:
                return "blocked"
            except Exception as e:  # noqa: BLE001 - counted, the rest still show
                log.info("link look-up failed for %s: %s", url, e)
                self._failed_why(e)
                return None
        with ThreadPoolExecutor(max_workers=LINK_LOOKUPS, thread_name_prefix="links") as pool:
            found = list(pool.map(one, urls))
        ok = [f for f in found if f is not None and f != "blocked"]
        if not ok and "blocked" in found:
            busy.emit(self._done, gen, "blocked", html.escape(_("Tor was turned away.")))
            return
        self._links_failed = len(found) - len(ok)
        busy.emit(self._done, gen, ok, "" if ok else html.escape(
            _("None of these links could be looked up.")))

    def _on_done(self, gen: int, results, err: str):
        if gen != self._gen:
            return
        if self._more_release is not None:   # a Show more page: added under the others
            self._more_release()
            self._more_release = None
            if err:
                busy.toast(self.window(), err, "error", 8000)
                return
            seen = {r.result.url for r in self._rows}
            new = [r for r in results if r.url not in seen]
            self._add_rows(new, gen)
            self.more_btn.setVisible(bool(new) and self._asked < MAX_RESULTS)
            return
        self._running = None
        self._loading(False)
        self.more_btn.hide()
        q = html.escape(self.query)
        self.failed = bool(err)
        if err:
            if self.links:
                self._fail(_("Can't use these links"), err)
            elif self.link:   # err: rich text
                self._fail(_("Can't use this link"), err)
                busy.toast(self.window(), _("Can't use this link: {error}", error=err),
                           "error", 8000)   # not only in the panel
            else:
                self._fail(_("Couldn't search {site}", site=self.site), err)  # from _work
            self.direct_btn.setVisible(results == "blocked")
            return
        if not results:
            self._say(_("No {site} results for <b>{q}</b>.", site=self.site, q=q))
            return
        if isinstance(results, ytdl.Playlist):   # a pasted playlist: a card per video
            self._set_links([r.url for r in results])
            self.playlist = results
        # the cards say it all; the message is for "no results" / errors
        self._add_rows(results, gen)
        if self.links:
            self._links_heading()
        # a full first page: there may be more of them
        self.more_btn.setVisible(not self.link and not self.links
                                 and len(results) >= PAGE // 2)

    def _add_rows(self, results, gen: int):
        for r in results:
            one = bool(self.link) and not self.links   # not a playlist's
            row = ResultRow(r, wide=one)
            row.play.connect(self._row_play)
            row.add.connect(self._row_add)
            if one:   # one video: one big card, not a grid of one
                row.setMaximumWidth(LINK_CARD_MAX_W)
                self.link_row.insertWidget(0, row, 10)   # all of it, up to the cap
            else:
                self.rows.addWidget(row)
            self._rows.append(row)
            thumb = net.web_url(r.thumb)   # web links only
            if not quality.current.web_extras or not thumb:   # Settings > Data & quality
                continue
            # under the switch of the server it's on (i.ytimg.com is YouTube's), whatever
            # site the search went to: switching YouTube off stops its pictures too
            feature = ytdl.site_feature(thumb)
            if not net.allowed(feature):
                continue
            req = QNetworkRequest(QUrl(thumb))
            req.setTransferTimeout(THUMB_TIMEOUT_MS)
            reply = self._nam(feature).get(req)
            # Qt's network thread reads on while the UI thread is busy: without a buffer
            # limit a never-ending picture piles up long before _cap_thumb gets to run
            reply.setReadBufferSize(THUMB_MAX_BYTES + 1_000_000)
            reply.downloadProgress.connect(
                lambda got, total, reply=reply: _cap_thumb(reply, got, total))
            reply.finished.connect(lambda reply=reply, row=row, g=gen: self._on_thumb(
                reply, row, g))

    def _nam(self, feature: str) -> QNetworkAccessManager:
        """The network manager whose requests carry `feature` (a site's switch)."""
        nam = self._nams.get(feature)
        if nam is None:
            nam = self._nams[feature] = QNetworkAccessManager(self)
            net.apply_qt(nam, feature)
        return nam

    def _on_thumb(self, reply, row: ResultRow, gen: int):
        """A picture came in (or failed, or was cut off): decode it on a worker, since a
        big one would freeze the window; _on_thumb_decoded shows it."""
        ok = (reply.error() == QNetworkReply.NetworkError.NoError
              and not reply.property("too_big"))
        data = bytes(reply.readAll()) if ok else b""
        reply.deleteLater()
        if (not data or len(data) > THUMB_MAX_BYTES or gen != self._gen
                or row not in self._rows):
            return
        url = row.result.url

        def decode():
            busy.emit(self._thumb_decoded, gen, url, QImage.fromData(data))
        _thumb_decoder().submit(decode)

    def _on_thumb_decoded(self, gen: int, url: str, img: QImage):
        if gen != self._gen or img.isNull():   # a new search, or not a picture
            return
        row = next((r for r in self._rows if r.result.url == url), None)
        if row is None:   # its card went meanwhile
            return
        pm = QPixmap.fromImage(img)
        row.set_thumb(pm)
        self.thumb_ready.emit(url, pm)
