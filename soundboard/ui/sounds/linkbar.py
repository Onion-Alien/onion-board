"""The Sounds tab's link downloads: a web link pasted into "Search sounds" shows as a
result card (ytsearch.SearchResults.show_link) whose **Add** and **Play** come here,
as do a web search's. yt-dlp fetches it (YouTube, SoundCloud, TikTok, Twitter/X,
Reddit, most video sites, and plain links to audio / video files): **Add** imports it
like a dropped file, **Play** plays it through the pads' path, nothing kept in the
library. The bar itself is a line under the search box that only shows when something
went wrong (and "Try this one without Tor" when Tor was turned away); the card shows
the rest.

One download serves both: after Play once, Add as sound reuses the file instead of
fetching it again. The temp folder is deleted when the link changes or the app closes.
"""
from __future__ import annotations

import html
import logging
import shutil
import tempfile
import threading
from collections.abc import Callable
from typing import Any
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from soundboard.sounds import library, sourceinfo, thumbs, videos
from soundboard.online import quality
from soundboard.ui.kit import theme
from soundboard.core import usage
from soundboard.online import net, netlog, ytdl
from soundboard.sounds.library import SR, decode_int16, fingerprint, import_file, site_folder
from soundboard.ui.kit import busy
from soundboard.ui.kit.widgets import fmt_time
from soundboard.core import errors
from soundboard.i18n import _

log = logging.getLogger(__name__)

PLAY_ID = "__link__"   # the engine voice of Play once
MAX_QUEUED = 30        # Adds of other links waiting their turn (Plays always queue)


def _drop_temp(path) -> None:
    """Delete a download's folder, but only if it is the temp folder ytdl made for it."""
    folder = Path(path).resolve().parent
    if (folder.name.startswith("sb-ytdl-")
            and folder.parent == Path(tempfile.gettempdir()).resolve()):
        shutil.rmtree(folder, ignore_errors=True)


class LinkBar(QFrame):
    """`sound_ready(meta, int16 audio)` fires when Add as sound finished (the audio
    is already stored and prepared); the owner adds it to the library."""
    sound_ready = Signal(object, object)
    played = Signal(str, object, float, str)   # Play once started: (title, audio, gain, url)
    _msg = Signal(str, str, object, object)   # worker -> UI: (kind, url, payload, job)
    done = Signal(str, str, bool)     # (url, "add" | "play", it worked): a search row's busy end
    failed = Signal(str, str)         # (url, kind): it ended in an error, just before its done
    progress = Signal(str, object)    # (url, 0..1 downloaded, or -1/stage while it's converted)
    link_changed = Signal(str)        # the search box's link ("" when it has none now)
    links_changed = Signal(list)      # the search box's links, when several were pasted
    download_started = Signal(str, str, str, float)  # (url, title, kind, seconds)
    queue_updated = Signal(list)      # the picks waiting their turn: [{url, title, kind}]
    up_next_changed = Signal(list)    # downloaded Plays waiting for the one playing: [title]
    queued = Signal(str, str)         # (url, "add" | "play"): a pick now waits its turn
    already_have = Signal(str)        # an Add's fingerprint: it's in the library already

    def __init__(self, engine, cfg, color_for, known_for):
        """`color_for()` gives the next pad colour, `known_for()` {fingerprint: name}
        of the library (to refuse a sound that's already in it)."""
        super().__init__()
        self.engine, self.cfg = engine, cfg
        self._color_for, self._known_for = color_for, known_for
        self.url = ""
        self.many: list[str] = []     # several links pasted at once (ytdl.as_links)
        self.title = ""
        self._secs = 0.0
        self._text = ""               # the search box's text last seen
        self._busy = ""               # "", "add" or "play": one download at a time
        self._busy_url = ""
        self._busy_title = ""         # the running pick's title (another card may show now)
        self._queue_list: list[dict] = []   # other links' picks, run one after another
        # each download is a numbered job: a cancelled one's worker still runs to its end
        # (yt-dlp can't be stopped halfway), and everything it sends after is dropped
        self._job = 0
        self._stop: threading.Event | None = None   # the running job's cancel flag
        self._dropped: set[int] = set()
        self._got = None              # (url, file, int16 audio, gain) of the last download
        # (url, int16 audio, gain) of the last add: Play after it is instant. Dropped with
        # the link, like _got: a 15-minute song is ~170 MB
        self._kept = None
        self._queued = ""             # "add" / "play" asked for while another download ran
        # ...on that running link (url, title, seconds): another card clicked or a search
        # typed meanwhile doesn't drop it, it runs once that download is over
        self._queued_pick = ("", "", 0.0)
        # (title, int16 audio, gain, url) of Plays that finished downloading while
        # another link was playing: they wait their turn instead of cutting it off
        self._up_next: list[tuple] = []
        self._now = ""                # a link whose Play plays over the one playing (play_now)
        self._now_solo = False        # ...as a pad's press does: the board's sounds stop
        self.playing_url = ""         # the link the player last started
        # is one of the board's own songs playing? (MainWindow sets it): a Play waits
        # for it too, it never plays over it
        self.board_busy: Callable[[], bool] = lambda: False
        # url -> its search card's picture (MainWindow sets it): an Add that reuses a
        # Play's download has no picture of its own (Play skips it)
        self.picture_for: Callable[[str], QPixmap | None] = lambda url: None
        self._via: dict[str, str] = {}   # url -> "link" (pasted) or "search", for usage
        self._dups: set[str] = set()     # urls refused as already in the library
        self._why: dict[str, str] = {}   # url -> why its download failed (usage.DL_FAILS)
        self.added_ids: dict[str, str] = {}   # url -> the sound it was added as (this run)
        self._msg.connect(self._on_msg)
        self._shown = False           # the line says something wrong (_say)
        self._off_said = False        # ...and it's net.off_message: redone on a switch
        net.on_change(self._net_changed)

        self.setObjectName("card")
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 6, 10, 6)
        h.setSpacing(8)
        self.info = QLabel()
        self.info.setTextFormat(Qt.TextFormat.RichText)
        self.info.setWordWrap(True)
        errors.linkify(self.info)   # an error's "Report it" link
        h.addWidget(self.info, 1)
        # Tor mode, after the site turned Tor away even over new routes: only this click
        # makes one download go without Tor (ytdl.TorBlocked)
        self.btn_direct = QPushButton(_("Try this one without Tor"))
        self.btn_direct.setToolTip(_("Download just this one link straight from the site, not "
                                     "through Tor: the site will see your own address"))
        self.btn_direct.clicked.connect(self._without_tor)
        self.btn_direct.hide()
        self._blocked = ""            # "add" / "play" that Tor couldn't do for this link
        h.addWidget(self.btn_direct)
        # yt-dlp itself failed and updating it is the user's call (auto-update is
        # opt-in): one click fetches the newest and tries the link again
        self.btn_update = QPushButton(_("Update downloader"))
        self.btn_update.setToolTip(_("Get the newest yt-dlp, the part that downloads from "
                                     "YouTube and other sites, then try this link again"))
        self.btn_update.clicked.connect(self._update_downloader)
        self.btn_update.hide()
        self._fixable = ""            # "add" / "play" a newer yt-dlp may fix for this link
        self._updating = False
        h.addWidget(self.btn_update)
        self.hide()

    # ------------------------------------------------------------------ state
    def set_text(self, text: str):
        """Whatever is in the search box: a link becomes the one Play / Add fetch
        (link_changed tells the window to show its card). Only a change counts: the
        board re-filters with the same text after every add, which mustn't drop a
        web-search pick that's downloading or waiting its turn."""
        if text == self._text:
            return
        self._text = text
        many = ytdl.as_links(text)
        if many != self.many:
            self.many = many
            for u in many:
                self._via[u] = "link"
            self.links_changed.emit(many)
        url = ytdl.as_link(text)
        if url == self.url:
            return
        self.url = url
        self.title = ""
        self._blocked = ""
        self._fixable = ""
        if url:
            self._via[url] = "link"
        self._drop_download()
        self._say_if_off()
        self.link_changed.emit(url)

    def _say_if_off(self):
        """The line says why the link can't go online (switched off in Settings >
        Privacy, or Offline mode), or nothing."""
        self._say("")
        if self.url and not ytdl.site_allowed(self.url):
            self._say(html.escape(net.off_message(ytdl.site_feature(self.url))),
                      theme.status("warn"))
            self._off_said = True

    def _net_changed(self):
        """A switch or Offline mode changed (any thread): the line said the old one's
        words, now redone ("Offline mode" stayed up after it was switched off)."""
        QTimer.singleShot(0, self, self._recheck_off)

    def _recheck_off(self):
        if self._off_said or (self.url and not ytdl.site_allowed(self.url)):
            self._say_if_off()

    def open(self, url: str, title: str, secs: float = 0.0):
        """A video picked from the YouTube search: already looked up, so no probe."""
        self._via.setdefault(url, "search")   # a pasted link's own card stays "link"
        if url != self.url:
            self.url = url
            self._blocked = ""
            self._fixable = ""
            self._drop_download()
        self.title = title
        self._secs = secs
        dur = f" · {fmt_time(secs)}" if secs else ""
        self._say(f"<b>{html.escape(title)}</b>{dur} "   # kept for reading, not shown
                  f"<span style='color:{theme.T['muted']}'>· {html.escape(self._host())}</span>")

    def _host(self) -> str:
        return self.url.split("/")[2].removeprefix("www.") if self.url else ""

    def _say(self, text: str, color: str = ""):
        """The bar's line. Only a problem shows it (the card shows the rest: busy,
        playing, added); the text is kept either way."""
        self.info.setText(f"<span style='color:{color}'>{text}</span>" if color else text)
        self._off_said = False
        self._shown = bool(text) and color in (theme.status("error"), theme.status("warn"))
        self._buttons()

    def _buttons(self):
        self.btn_direct.setVisible(bool(self._blocked) and not self._busy)
        self.btn_update.setVisible(bool(self._fixable) and not self._busy and not self._updating)
        self.setVisible(bool(self.url) and (self._shown or not self.btn_direct.isHidden()
                                            or not self.btn_update.isHidden()))

    def _drop_download(self):
        if self._got is not None:
            _drop_temp(self._got[1])
            self._got = None
        self._kept = None

    def downloading(self) -> bool:
        """A link is being downloaded right now (closing would drop it)."""
        return bool(self._busy)

    def shutdown(self):
        self.engine.stop(PLAY_ID)
        self._up_next.clear()
        self._drop_download()

    # ------------------------------------------------------------------ actions
    def add(self) -> bool:
        if not self.url:
            return False
        if (self.url == getattr(self, "_added", "")
                and any(m.id == getattr(self, "_added_id", None) for m in self.cfg.sounds)):
            self.done.emit(self.url, "add", True)
            return True
        if self._busy:
            if self.url == self._busy_url:
                if self._busy == "add" or self._queued == "add":
                    return True
                self._queue_same("add")
                return True
            return self._queue("add")
        self._start("add")
        return True

    def play_once(self) -> bool:
        if not self.url:
            return False
        # If already downloading this exact sound for play, don't restart
        if self._busy == "play" and self._busy_url == self.url:
            return True
        # If the same URL is already downloading (e.g. for Add), share the download
        if self._busy and self._busy_url == self.url:
            if self._queued == "play":
                return True
            self._queue_same("play")
            return True
        # another link is downloading: this one waits its turn. A Play already
        # loading isn't dropped: five Plays play all five, one after another (_play)
        if self._busy:
            return self._queue("play")

        have = next((g for g in (self._got, self._kept)
                     if g is not None and g[0] == self.url), None)
        if have is not None:
            self._play(*have[-2:])
            self.done.emit(self.url, "play", True)
            return True
        self._start("play")
        return True

    def play_now(self, solo: bool = False) -> bool:
        """Play it now: over a link that's playing, not after it (Play once queues). A
        download already running for another link finishes first, then this one's goes.
        `solo`: it plays as a pad's press does (the Community tab), stopping the sounds
        playing, as a pad's press stops a link."""
        if not self.url:
            return False
        self._now, self._now_solo = self.url, solo
        ok = self.play_once()
        self.move_to_front(self.url)
        return ok

    def play_audio(self, data, gain: float, title: str, url: str, now: bool) -> bool:
        """Audio got elsewhere (a Community upload, `url` its key), played the way a
        Community link's Play (`now`: play_now(solo=True)) or Play next (play_once) is."""
        if now:
            self._now, self._now_solo = url, True
        return self._play(data, gain, title, url)

    def _queue_same(self, kind: str):
        """Add and Play on the link that's downloading: the other one runs after it."""
        self._queued = kind
        self._queued_pick = (self.url, self.title or self._busy_title, self._secs)

    def _queue(self, kind: str) -> bool:
        """Another sound's download is running: an Add waits at the back of the queue,
        a Play goes next."""
        if self.url == self._busy_url and kind == self._busy:
            return True   # already running: don't import the same sound twice
        if any(q["url"] == self.url and q["kind"] == kind for q in self._queue_list):
            return True
        pick = {"url": self.url, "title": self.title, "kind": kind, "seconds": self._secs}
        if kind == "play":
            # a Play goes before the Adds waiting (the running download keeps going)
            # and after the Plays already waiting, so they play in the order clicked
            at = max((i + 1 for i, q in enumerate(self._queue_list) if q["kind"] == "play"),
                     default=0)
            self._queue_list.insert(at, pick)
        elif len(self._queue_list) >= MAX_QUEUED:
            busy.toast(self.window(), _("Queue is full"), "warn")
            return False
        else:
            self._queue_list.append(pick)
        self.queue_updated.emit(list(self._queue_list))
        self.queued.emit(self.url, kind)
        usage.used("dl-queue")
        name = html.escape(self.title or self._host())
        self._say(_("<b>{name}</b> is next: waiting for the download before it to finish…",
                    name=name))
        return True

    def cancel(self, url: str = ""):
        """The download bar's Cancel: the running download (`url` "" or its link), or
        a pick still waiting its turn."""
        if not url or url == self._busy_url:
            if self._busy:
                self._drop_running()
                self._next()
            return
        left = [q for q in self._queue_list if q["url"] != url]
        gone = [q for q in self._queue_list if q["url"] == url]
        if gone:
            self._queue_list = left
            self.queue_updated.emit(list(left))
            for q in gone:
                self.done.emit(url, q["kind"], False)

    def move_to_front(self, url: str):
        """A waiting pick clicked in the download bar's list: it goes next."""
        i = next((i for i, q in enumerate(self._queue_list) if q["url"] == url), None)
        if not i:   # not waiting, or next already
            return
        self._queue_list.insert(0, self._queue_list.pop(i))
        self.queue_updated.emit(list(self._queue_list))

    def cancel_all(self):
        """The download bar's Stop all: the running download and every pick waiting."""
        gone, self._queue_list = self._queue_list, []
        if gone:
            self.queue_updated.emit([])
            for q in gone:
                self.done.emit(q["url"], q["kind"], False)
        if self._busy:
            self._drop_running()

    def _drop_running(self):
        """Stop waiting for the running download: its worker finishes on its own and
        whatever it sends is dropped (_on_msg). Its rows stop waiting too."""
        url, kind = self._busy_url, self._busy
        self._dropped.add(self._job)
        if self._stop is not None:
            self._stop.set()   # the worker skips the import / decode if not there yet
        self._busy, self._busy_url = "", ""
        self.done.emit(url, kind, False)
        if self._queued and url == self._queued_pick[0]:   # Add + Play on that link: both stop
            queued, self._queued = self._queued, ""
            self.done.emit(url, queued, False)
        self._buttons()

    def _without_tor(self):
        """The user's click on "Try this one without Tor": that one download, direct."""
        kind, self._blocked = self._blocked, ""
        if kind and self.url and not self._busy:
            self._start(kind, direct=True)

    def _update_downloader(self):
        """The user's click on "Update downloader": fetch the newest yt-dlp on a worker,
        then try the link again if a newer one came in."""
        kind, url = self._fixable, self.url
        if not kind or not url or self._busy or self._updating:
            return
        self._fixable, self._updating = "", True
        self._say(html.escape(_("Updating the downloader…")))
        netlog.cause(ytdl.UPDATE_FEATURE, "You clicked Update downloader")

        def work():
            before = ytdl.active_version()[0]
            try:
                msg = ytdl.update()
                busy.emit(self._msg, "updated", url,
                          (kind, msg, ytdl.active_version()[0] != before), None)
            except Exception as e:  # noqa: BLE001 - offline, PyPI down: said in the bar
                log.warning("downloader update from the link bar failed: %s", e)
                busy.emit(self._msg, "updated", url, (kind, errors.plain(e), None), None)
        threading.Thread(target=work, daemon=True, name="ytdlp-update").start()

    def _updated(self, url: str, kind: str, msg: str, newer: bool | None):
        """update()'s answer: newer = a new copy is in (try again), False = it was the
        newest already, None = the update failed (msg is why)."""
        self._updating = False
        if url != self.url:   # another link shows now: nothing to retry
            self._buttons()
            return
        if newer and not self._busy:
            self._say("")
            self._start(kind)
            return
        if newer is None:
            self._say(html.escape(_("Couldn't update the downloader: {error}", error=msg)),
                      theme.status("error"))
        else:
            self._say(html.escape(_("The downloader is already the newest. The site may have "
                                    "changed in a way it can't handle yet: try again in a "
                                    "few days.")), theme.status("warn"))

    def _start(self, kind: str, direct: bool = False):
        self._blocked = ""
        self._fixable = ""
        self._busy = kind
        self._busy_url = self.url
        self._busy_title = self.title
        self._buttons()
        self._job += 1
        self._stop = threading.Event()
        self.download_started.emit(self.url, self.title, kind, self._secs)
        got, self._got = self._got, None   # the worker owns (and deletes) it now
        # Settings > Data & quality: Add as sound keeps the video too (Play never does)
        video = kind == "add" and quality.current.save_video
        if got is not None and (got[0] != self.url or video):
            _drop_temp(got[1])
            got = None
        args = (kind, self.url, got, self._color_for(), self._known_for(),
                bool(self.cfg.ytdlp_auto_optin), direct, video, self.title, self._job,
                self._stop)
        what = netlog.quoted(self.title) if self.title else "a link"
        netlog.cause(ytdl.FEATURE, (f"You clicked Play on {what}" if kind == "play" else
                                    f"You added {what} as a sound")
                     + (" (without Tor)" if direct else ""))
        # a failed download may update the downloader first (ytdl.download_audio)
        netlog.cause(ytdl.UPDATE_FEATURE, f"A download of {what} failed: checking for a "
                                          "newer downloader")
        threading.Thread(target=self._work, args=args, daemon=True, name="link-dl").start()

    def _play(self, data, gain: float, title: str | None = None, url: str = "") -> bool:
        """`gain` is the levelling gain the worker worked out (a float copy of a
        whole song is too slow and too big for the UI thread). `title` and `url`: the
        pick's own, when another card shows now."""
        title = self.title if title is None else title
        gain = gain if self.cfg.level_volumes else 1.0
        url = url or self.url
        if url == self._now:   # (play_now) it takes the player's place at once
            solo, self._now, self._now_solo = self._now_solo, "", False
            return self._start_playing(data, gain, title, url, solo)
        if self._in_player() or self._up_next or self.board_busy():
            # another link or one of your sounds is playing (or paused): never play over
            # it, play this after it
            if all(u != url for *_r, u in self._up_next):
                self._up_next.append((title or _("Link"), data, gain, url))
                self.up_next_changed.emit(self.up_next())
                busy.toast(self.window(), _("Up next: “{name}” · Stop all clears the queue",
                                            name=html.escape(title or _("Link"))), "ok")
            return True
        return self._start_playing(data, gain, title, url)

    def _in_player(self) -> bool:
        """A link's Play is playing or paused right now."""
        playing = getattr(self.engine, "playing", None)
        return playing is not None and PLAY_ID in playing()

    def up_next(self) -> list[str]:
        """The titles of the downloaded Plays waiting their turn, in order."""
        return [t for t, *_r in self._up_next]

    def up_next_items(self) -> list[tuple[str, str]]:
        """Up next as (title, url): the download bar lists them by their link."""
        return [(t, u) for t, *_r, u in self._up_next]

    def drop_up_next_url(self, url: str):
        """Take the Play for `url` out of Up next (the download bar's ✕ on its row)."""
        i = next((i for i, (*_r, u) in enumerate(self._up_next) if u == url), -1)
        if i >= 0:
            self.drop_up_next(i)

    def play_next(self, i: int = 0, shown=None) -> bool:
        """Start Up next's song `i` (the first: the one playing ended or was stopped;
        another: its chip was clicked, so it plays now). `shown`: Up next as the chips
        showed it; out of date does nothing (a double click hit a moved chip)."""
        if shown is not None and tuple(self.up_next()) != tuple(shown):
            return False
        if not 0 <= i < len(self._up_next):
            return False
        title, data, gain, url = self._up_next.pop(i)
        self.up_next_changed.emit(self.up_next())
        return self._start_playing(data, gain, title, url)

    def move_up_next(self, i: int, to: int, shown=None) -> bool:
        """Up next's song `i` dragged to place `to`. Out of date `shown` does nothing."""
        if shown is not None and tuple(self.up_next()) != tuple(shown):
            return False
        if not (0 <= i < len(self._up_next) and 0 <= to < len(self._up_next)):
            return False
        self._up_next.insert(to, self._up_next.pop(i))
        self.up_next_changed.emit(self.up_next())
        return True

    def drop_up_next(self, i: int = -1, shown=None):
        """Take Up next's song `i` out (a chip's ✕), or all of them (Stop all)."""
        if shown is not None and tuple(self.up_next()) != tuple(shown):
            return
        if i < 0:
            self._up_next.clear()
        elif i < len(self._up_next):
            del self._up_next[i]
        self.up_next_changed.emit(self.up_next())

    def _start_playing(self, data, gain: float, title: str, url: str,
                       solo: bool = False) -> bool:
        v = self.engine.play(PLAY_ID, data, gain, mode="solo" if solo else "restart")
        if v is None:
            busy.toast(self, html.escape(_("No audio device is open, pick one in Setup.")),
                       "warn")
            return False
        self.playing_url = url
        self.played.emit(title or _("Link"), data, gain, url)
        if title == self.title:
            name = html.escape(title or _("it"))
            self._say(_("▶ Playing <b>{name}</b> ({time}): <i>Add as sound</i> keeps it.",
                        name=name, time=fmt_time(len(data) / SR)))
        return True

    # ------------------------------------------------------------------ workers
    def _work(self, kind, url, got, color, known, auto_update, direct=False, video=False,
              shown="", job=None, stop=None):
        """Download (unless `got` already holds it), then import or decode. `shown`:
        the link's title as the bar has it (the file's name when `got` is used)."""
        def emit(kind, url, payload):
            busy.emit(self._msg, kind, url, payload, job)
        path = got[1] if got else None
        title = ""
        keep = False
        dup = False
        try:
            if path is None:
                emit("progress", url, "parsing")
                more: dict[str, Any] = {}   # only what's asked (fakes in tests take less)
                if direct:
                    more["direct"] = True
                if video:
                    more["video"] = True
                if kind == "play":   # no pad to put the picture on: it only slows it down
                    more["thumbnail"] = False
                path, title = ytdl.download_audio(
                    url, progress=lambda f: emit("progress", url, f),
                    auto_update=auto_update, **more)
                emit("title", url, title)
            if stop is not None and stop.is_set():
                emit("cancelled", url, None)   # while it downloaded: no import, no decode
                return
            emit("progress", url, "processing")
            if kind == "play":
                audio, gain = decode_int16(str(path))   # a long one stays on disk
                emit("play", url, (path, audio, gain))
                del audio
                keep = True   # the UI keeps it so Add as sound needn't download again
                return
            fp = fingerprint(str(path))
            if fp and fp in known:
                emit("dup", url, fp)   # counted apart from a failed download
                dup = True
                raise ytdl.DownloadError(_("It's already in your Sounds as “{name}”.",
                                           name=known[fp]))
            # named after the video, in a folder for the site: YouTube/<title>.flac
            meta, data = import_file(str(path), color, name=title or shown,
                                     folder=site_folder(url))
            try:
                if (pic := thumbs.find_in(Path(path).parent)) is not None:
                    meta.image = thumbs.store(pic, meta.id)   # the video's thumbnail
            except OSError as e:
                log.warning("couldn't keep the thumbnail of %s: %s", url, e)
            # the video's link, channel and views: the pad menu's Open on YouTube
            if quality.current.keep_source:
                meta.source = sourceinfo.read_from(Path(path).parent)
                sourceinfo.write(meta.file, meta.source)
            self.engine.prepare(meta.id, data)
            saved = ""
            if video:
                try:
                    kept = ytdl.save_video(path, title or meta.name)
                    if kept:
                        videos.link(meta.id, kept)   # the player's Video button shows it
                    saved = (_("Video saved in {folder}.", folder=kept.parent) if kept else
                             _("No video was saved: this site only gave the sound.")
                             if library._ffmpeg() else
                             _("No video was saved: saving videos needs FFmpeg "
                               "(Settings > Data & quality)."))
                except OSError as e:
                    log.warning("couldn't keep the video of %s: %s", url, e)
                    saved = _("The video couldn't be saved ({error}).",
                              error=errors.plain(e))
            emit("added", url, (meta, data, title, saved))
        except ytdl.TorBlocked as e:   # the bar offers to try it without Tor
            log.warning("link %s turned away over Tor for %s", kind, url)
            emit("why", url, "proxy")
            emit("blocked", url, (kind, html.escape(
                _("Couldn't add it: {error}", error=e) if kind == "add" else
                _("Couldn't play it: {error}", error=e))))
        except Exception as e:  # noqa: BLE001 - shown in the bar, logged
            log.warning("link %s failed for %s: %s", kind, url, e)
            why = errors.download_reason(e)
            emit("why", url, why)   # for the usage count only
            if why == "other" and not dup:   # what's known of it, never its words
                usage.failed("dl-other", *usage.error_detail(e))
            # a bot check or rate limit is about the user's address, not yt-dlp; with
            # auto-update on, download_audio() already tried a newer one
            fixable = (isinstance(e, ytdl.FetchError) and not auto_update
                       and why != "disk-full" and not getattr(e, "proxy", False)
                       and net.allowed(ytdl.UPDATE_FEATURE)
                       and not ytdl.blocked_by_site(f"{e} {getattr(e, 'raw', '')}"))
            hint = _(" A newer downloader may fix this.") if fixable else ""
            if hint and not errors.describe(e).text.rstrip().endswith((".", "!", "?", "…")):
                hint = "." + hint   # yt-dlp's own words often end without a full stop
            doing = "add" if kind == "add" else "play"
            # rich text: the plain words, and a "Report it" link when it's one for us
            before = _("Couldn't add it: ") if kind == "add" else _("Couldn't play it: ")
            text = (errors.html(e, before, where=f"Couldn't {doing} a link")
                    + html.escape(hint))
            emit("fixable" if fixable else "error", url, (kind, text) if fixable else text)
        finally:
            if not keep and path is not None:
                _drop_temp(path)

    def _on_msg(self, kind: str, url: str, payload, job=None):
        if job in self._dropped:   # a cancelled download, still sending: not the running one
            if kind in ("progress", "title", "dup", "why"):
                return
            self._dropped.discard(job)
            if kind == "play":
                _drop_temp(payload[0])
            elif kind == "added":   # cancelled too late: it's in the library already
                meta, data, title, _saved = payload
                meta.name = (title or meta.name)[:40].strip()
                self._count(url, "add", True)
                self.sound_ready.emit(meta, data)
                busy.toast(self.window(), _("✓ Added <b>{name}</b> to your Sounds.",
                                            name=html.escape(meta.name)), "ok")
            return
        if kind == "cancelled":
            return
        if kind == "updated":   # the Update downloader click's answer, not a download
            self._updated(url, *payload)
            return
        current = url == self.url
        if kind == "title":
            if current:
                self.title = self.title or payload
            return
        if kind == "progress":
            self.progress.emit(url, payload)   # the card's bar and button show it
            return
        if kind == "dup":
            self._dups.add(url)
            if payload:
                self.already_have.emit(payload)   # the board shows where it is
            return
        if kind == "why":
            self._why[url] = payload
            return
        # the download finished one way or another
        was, self._busy = self._busy, ""
        self._busy_url = ""
        busy_title, self._busy_title = self._busy_title, ""
        if kind == "blocked":
            blocked_kind, payload = payload
            kind = "error"
            if current:
                self._blocked = blocked_kind
        elif kind == "fixable":   # the bar offers to update yt-dlp and try again
            fixable_kind, payload = payload
            kind = "error"
            if current:
                self._fixable = fixable_kind
        if kind == "added":
            self._added = url
            self._added_id = payload[0].id
            self.added_ids[url] = payload[0].id
        self._buttons()
        if kind in ("added", "play"):
            self._count(url, "add" if kind == "added" else "play", True)
        elif kind == "error":
            self._count(url, was or "add", False)
        if kind == "added":
            meta, data, title, saved = payload
            if not meta.image and (pm := self.picture_for(url)) is not None:
                meta.image = thumbs.store(pm.toImage(), meta.id)
            if current:   # one for a link no longer showing would never be played
                self._kept = (url, data, meta.level_gain)
            meta.name = (title or (current and self.title) or meta.name)[:40].strip()
            self.sound_ready.emit(meta, data)
            if current:
                self._say(_("✓ Added <b>{name}</b> to your Sounds.",
                            name=html.escape(meta.name))
                          + (f" {html.escape(saved)}" if saved else ""), theme.status("ok"))
            else:   # another link is showing now: still say this one made it
                busy.toast(self.window(), _("✓ Added <b>{name}</b> to your Sounds.",
                                            name=html.escape(meta.name)), "ok")
            self.done.emit(url, "add", True)
            if not current and self._queued == "play" and url == self._queued_pick[0]:
                # its Play was clicked too, then another card: it plays now, with no
                # second download
                self._queued = ""
                self.done.emit(url, "play", self._play(data, meta.level_gain, busy_title, url))
        elif kind == "play":
            path, data, gain = payload
            if current:
                self._got = (url, Path(path), data, gain)
                ok = self._play(data, gain)
            else:
                # another card was clicked while it loaded (to queue an Add, say): the
                # Play still stands, only a newer Play or Cancel stops it (_drop_running)
                _drop_temp(path)
                ok = self._play(data, gain, busy_title, url)
            self.done.emit(url, "play", ok)
        elif kind == "error":
            if current:
                self._say(payload, theme.status("error"))   # already rich text
            else:   # it was for a link no longer showing: don't lose the reason
                busy.toast(self.window(), payload, "error", 8000)
            self.failed.emit(url, was or "add")
            self.done.emit(url, was or "add", False)
            if self._queued and url == self._queued_pick[0]:
                # Both clicks were waiting for this same failed download. A second
                # fetch would leave an error visible even if the retry succeeded.
                queued, self._queued = self._queued, ""
                self.done.emit(url, queued, False)
        self._next()

    def _count(self, url: str, kind: str, ok: bool):
        """For the usage count: the site's name and how it was picked, never the link."""
        if url in self._dups:
            self._dups.discard(url)
            usage.used("dl-already-have")
            return
        usage.downloaded(self.cfg, url, self._via.get(url, "link"), kind, ok,
                         self._why.pop(url, ""))

    def _next(self):
        """The download finished or was cancelled: start what's waiting. The same
        link's other action first (Play after Add needs no download), then the other
        links' picks in the order they were clicked."""
        if self._queued and not self._busy:
            queued, self._queued = self._queued, ""
            url, title, secs = self._queued_pick
            if url != self.url:   # another card was picked meanwhile
                self.open(url, title, secs)
            self.add() if queued == "add" else self.play_once()
        while self._queue_list and not self._busy:
            q = self._queue_list.pop(0)
            self.queue_updated.emit(list(self._queue_list))
            self.open(q["url"], q["title"], q["seconds"])
            self.add() if q["kind"] == "add" else self.play_once()
