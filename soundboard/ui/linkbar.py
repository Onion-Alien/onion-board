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
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from soundboard import net, netlog, quality, theme, thumbs, videos, ytdl
from soundboard.library import (SR, decode, fingerprint, import_file, level_gain,
                                site_folder, to_int16)
from soundboard.ui import busy
from soundboard.ui.widgets import fmt_time
from soundboard import errors
from soundboard.i18n import _

log = logging.getLogger(__name__)

PLAY_ID = "__link__"   # the engine voice of Play once


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
    played = Signal(str, object, float)   # Play once started: (title, int16 audio, gain)
    _msg = Signal(str, str, object)   # worker -> UI: (kind, url, payload)
    done = Signal(str, str, bool)     # (url, "add" | "play", it worked): a search row's busy end
    progress = Signal(str, float)     # (url, 0..1 downloaded, or -1 while it's converted)
    link_changed = Signal(str)        # the search box's link ("" when it has none now)

    def __init__(self, engine, cfg, color_for, known_for):
        """`color_for()` gives the next pad colour, `known_for()` {fingerprint: name}
        of the library (to refuse a sound that's already in it)."""
        super().__init__()
        self.engine, self.cfg = engine, cfg
        self._color_for, self._known_for = color_for, known_for
        self.url = ""
        self.title = ""
        self._text = ""               # the search box's text last seen
        self._busy = ""               # "", "add" or "play": one download at a time
        self._got = None              # (url, file, int16 audio, gain) of the last download
        # (url, int16 audio, gain) of the last add: Play after it is instant. Dropped with
        # the link, like _got: a 15-minute song is ~170 MB
        self._kept = None
        self._queued = ""             # "add" / "play" asked for while another download ran
        self._msg.connect(self._on_msg)
        self._shown = False           # the line says something wrong (_say)

        self.setObjectName("card")
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 6, 10, 6)
        h.setSpacing(8)
        self.info = QLabel()
        self.info.setTextFormat(Qt.RichText)
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
        url = ytdl.as_link(text)
        if url == self.url:
            return
        if self._queued:   # a pick waiting its turn is dropped: its row stops waiting
            self.done.emit(self.url, self._queued, False)
        self.url = url
        self.title = ""
        self._queued = ""
        self._blocked = ""
        self._drop_download()
        self._say("")
        if url and not ytdl.site_allowed(url):   # switched off in Settings > Privacy
            self._say(html.escape(net.off_message(ytdl.site_feature(url))),
                      theme.status("warn"))
        self.link_changed.emit(url)

    def open(self, url: str, title: str, secs: float = 0.0):
        """A video picked from the YouTube search: already looked up, so no probe."""
        if url != self.url:
            if self._queued:   # a pick waiting its turn is replaced: its row stops waiting
                self.done.emit(self.url, self._queued, False)
            self.url = url
            self._queued = ""
            self._blocked = ""
            self._drop_download()
        self.title = title
        dur = f" · {fmt_time(secs)}" if secs else ""
        self._say(f"<b>{html.escape(title)}</b>{dur} "   # kept for reading, not shown
                  f"<span style='color:{theme.T['muted']}'>· {html.escape(self._host())}</span>")

    def _host(self) -> str:
        return self.url.split("/")[2].removeprefix("www.") if self.url else ""

    def _say(self, text: str, color: str = ""):
        """The bar's line. Only a problem shows it (the card shows the rest: busy,
        playing, added); the text is kept either way."""
        self.info.setText(f"<span style='color:{color}'>{text}</span>" if color else text)
        self._shown = bool(text) and color in (theme.status("error"), theme.status("warn"))
        self._buttons()

    def _buttons(self):
        self.btn_direct.setVisible(bool(self._blocked) and not self._busy)
        self.setVisible(bool(self.url) and (self._shown or not self.btn_direct.isHidden()))

    def _drop_download(self):
        if self._got is not None:
            _drop_temp(self._got[1])
            self._got = None
        self._kept = None

    def shutdown(self):
        self.engine.stop(PLAY_ID)
        self._drop_download()

    # ------------------------------------------------------------------ actions
    def add(self) -> bool:
        if not self.url:
            return False
        if self._busy:
            return self._queue("add")
        self._start("add")
        return True

    def play_once(self) -> bool:
        if not self.url:
            return False
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

    def _queue(self, kind: str) -> bool:
        """Another download is running (one at a time): do this one after it."""
        if self._queued == kind:
            return False
        self._queued = kind
        name = html.escape(self.title or self._host())
        self._say(_("<b>{name}</b> is next: waiting for the download before it to finish…",
                    name=name))
        return True

    def _without_tor(self):
        """The user's click on "Try this one without Tor": that one download, direct."""
        kind, self._blocked = self._blocked, ""
        if kind and self.url and not self._busy:
            self._start(kind, direct=True)

    def _start(self, kind: str, direct: bool = False):
        self._blocked = ""
        self._busy = kind
        self._buttons()
        got, self._got = self._got, None   # the worker owns (and deletes) it now
        # Settings > Data & quality: Add as sound keeps the video too (Play never does)
        video = kind == "add" and quality.current.save_video
        if got is not None and (got[0] != self.url or video):
            _drop_temp(got[1])
            got = None
        args = (kind, self.url, got, self._color_for(), self._known_for(),
                bool(self.cfg.ytdlp_auto_optin), direct, video, self.title)
        what = netlog.quoted(self.title) if self.title else "a link"
        netlog.cause(ytdl.FEATURE, (f"You clicked Play on {what}" if kind == "play" else
                                    f"You added {what} as a sound")
                     + (" (without Tor)" if direct else ""))
        # a failed download may update the downloader first (ytdl.download_audio)
        netlog.cause(ytdl.UPDATE_FEATURE, f"A download of {what} failed: checking for a "
                                          "newer downloader")
        threading.Thread(target=self._work, args=args, daemon=True, name="link-dl").start()

    def _play(self, data, gain: float):
        """`gain` is the levelling gain the worker worked out (a float copy of a
        whole song is too slow and too big for the UI thread)."""
        gain = gain if self.cfg.level_volumes else 1.0
        v = self.engine.play(PLAY_ID, data, gain, mode="restart")
        if v is None:
            self._say(_("No audio device is open — pick one in Setup."), theme.status("warn"))
        else:
            self.played.emit(self.title or _("Link"), data, gain)
            name = html.escape(self.title or _("it"))
            self._say(_("▶ Playing <b>{name}</b> ({time}) — <i>Add as sound</i> keeps it.",
                        name=name, time=fmt_time(len(data) / SR)))

    # ------------------------------------------------------------------ workers
    def _work(self, kind, url, got, color, known, auto_update, direct=False, video=False,
              shown=""):
        """Download (unless `got` already holds it), then import or decode. `shown`:
        the link's title as the bar has it (the file's name when `got` is used)."""
        path = got[1] if got else None
        title = ""
        keep = False
        try:
            if path is None:
                path, title = ytdl.download_audio(
                    url, progress=lambda f: self._msg.emit("progress", url, f),
                    auto_update=auto_update, **({"direct": True} if direct else {}),
                    **({"video": True} if video else {}))
                self._msg.emit("title", url, title)
            self._msg.emit("progress", url, -1.0)
            if kind == "play":
                audio = decode(str(path))
                self._msg.emit("play", url, (path, to_int16(audio), level_gain(audio)))
                del audio
                keep = True   # the UI keeps it so Add as sound needn't download again
                return
            fp = fingerprint(str(path))
            if fp and fp in known:
                raise ytdl.DownloadError(_("It's already in your Sounds as “{name}”.",
                                           name=known[fp]))
            # named after the video, in a folder for the site: YouTube/<title>.flac
            meta, data = import_file(str(path), color, name=title or shown,
                                     folder=site_folder(url))
            if (pic := thumbs.find_in(Path(path).parent)) is not None:
                meta.image = thumbs.store(pic, meta.id)   # the video's thumbnail
            self.engine.prepare(meta.id, data)
            saved = ""
            if video:
                try:
                    kept = ytdl.save_video(path, title or meta.name)
                    if kept:
                        videos.link(meta.id, kept)   # the player's Video button shows it
                    saved = (_("Video saved in {folder}.", folder=kept.parent) if kept else
                             _("No video was saved: this site only gave the sound."))
                except OSError as e:
                    log.warning("couldn't keep the video of %s: %s", url, e)
                    saved = _("The video couldn't be saved ({error}).",
                              error=errors.plain(e))
            self._msg.emit("added", url, (meta, data, title, saved))
        except ytdl.TorBlocked as e:   # the bar offers to try it without Tor
            log.warning("link %s turned away over Tor for %s", kind, url)
            self._msg.emit("blocked", url, (kind, html.escape(
                _("Couldn't add it: {error}", error=e) if kind == "add" else
                _("Couldn't play it: {error}", error=e))))
        except Exception as e:  # noqa: BLE001 - shown in the bar, logged
            log.warning("link %s failed for %s: %s", kind, url, e)
            # a bot check or rate limit is about the user's address, not yt-dlp
            hint = ("" if not isinstance(e, ytdl.FetchError) or auto_update
                    or ytdl.blocked_by_site(f"{e} {getattr(e, 'raw', '')}") else
                    _(" A newer yt-dlp may fix this: Settings → Updates → Update now."))
            doing = "add" if kind == "add" else "play"
            # rich text: the plain words, and a "Report it" link when it's one for us
            before = _("Couldn't add it: ") if kind == "add" else _("Couldn't play it: ")
            self._msg.emit("error", url, errors.html(e, before,
                                                     where=f"Couldn't {doing} a link")
                           + html.escape(hint))
        finally:
            if not keep and path is not None:
                _drop_temp(path)

    def _on_msg(self, kind: str, url: str, payload):
        current = url == self.url
        if kind == "title":
            if current:
                self.title = self.title or payload
            return
        if kind == "progress":
            self.progress.emit(url, payload)   # the card's bar and button show it
            return
        # the download finished one way or another
        was, self._busy = self._busy, ""
        if kind == "blocked":
            blocked_kind, payload = payload
            kind = "error"
            if current:
                self._blocked = blocked_kind
        if kind == "added":
            self._added = url
        self._buttons()
        if kind == "added":
            meta, data, title, saved = payload
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
        elif kind == "play":
            path, data, gain = payload
            if current:
                self._got = (url, Path(path), data, gain)
                self._play(data, gain)
            else:
                _drop_temp(path)
            self.done.emit(url, "play", current)
        elif kind == "error":
            if current:
                self._say(payload, theme.status("error"))   # already rich text
            else:   # it was for a link no longer showing: don't lose the reason
                busy.toast(self.window(), payload, "error", 8000)
            self.done.emit(url, was or "add", False)
        if self._queued and self.url:
            queued, self._queued = self._queued, ""
            if queued == "add":
                self.add()
            else:
                self.play_once()
