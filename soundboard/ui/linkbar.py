"""The Sounds tab's link bar: paste a web link into "Search sounds" and this row
appears under it. It looks the link up with yt-dlp (YouTube, SoundCloud, TikTok,
Twitter/X, Reddit, most video sites, and plain links to audio / video files), then
offers **Add as sound** (downloaded, imported like a dropped file) or **Play once**
(downloaded and played through the pads' path, nothing kept in the library).

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

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from soundboard import net, netlog, quality, theme, thumbs, ytdl
from soundboard.library import (SR, decode, fingerprint, import_file, level_gain, to_int16)
from soundboard.ui import busy, icons
from soundboard.ui.widgets import fmt_time
from soundboard import errors

log = logging.getLogger(__name__)

PLAY_ID = "__link__"   # the engine voice of Play once
PROBE_DELAY_MS = 400


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
        self._got = None              # (url, file, int16 audio) of the last download
        self._kept = None             # (url, int16 audio) of the last add: Play after it is instant
        self._queued = ""             # "add" / "play" asked for while another download ran
        self._msg.connect(self._on_msg)
        # a link typed by hand is a new "link" at every keystroke: look up only the
        # one the typing stops at
        self._probe_timer = QTimer(self, singleShot=True, interval=PROBE_DELAY_MS)
        self._probe_timer.timeout.connect(self._probe_now)

        self.setObjectName("card")
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 6, 10, 6)
        h.setSpacing(8)
        self.info = QLabel()
        self.info.setTextFormat(Qt.RichText)
        self.info.setWordWrap(True)
        errors.linkify(self.info)   # an error's "Report it" link
        h.addWidget(self.info, 1)
        self.btn_play = QPushButton("Play once")
        self.btn_play.setToolTip("Download it and play it through your mic once — it isn't "
                                 "added to your Sounds")
        icons.set_icon(self.btn_play, "play", size=14)
        self.btn_play.clicked.connect(self.play_once)
        self.btn_add = QPushButton("Add as sound")
        self.btn_add.setObjectName("primary")
        self.btn_add.setToolTip("Download its audio and add it to your Sounds (Enter)")
        icons.set_icon(self.btn_add, "plus", "on_accent", size=14)
        self.btn_add.clicked.connect(self.add)
        # Tor mode, after the site turned Tor away even over new routes: only this click
        # makes one download go without Tor (ytdl.TorBlocked)
        self.btn_direct = QPushButton("Try this one without Tor")
        self.btn_direct.setToolTip("Download just this one link straight from the site, not "
                                   "through Tor: the site will see your own address")
        self.btn_direct.clicked.connect(self._without_tor)
        self.btn_direct.hide()
        self._blocked = ""            # "add" / "play" that Tor couldn't do for this link
        h.addWidget(self.btn_direct)
        h.addWidget(self.btn_play)
        h.addWidget(self.btn_add)
        self.hide()

    # ------------------------------------------------------------------ state
    def set_text(self, text: str):
        """Whatever is in the search box: a link shows the bar, anything else hides it.
        Only a change counts: the board re-filters with the same text after every add,
        which mustn't drop a web-search pick that's downloading or waiting its turn."""
        if text == self._text:
            return
        self._text = text
        url = ytdl.as_link(text)
        if url == self.url:
            return
        self.url = url
        self.title = ""
        self._queued = ""
        self._blocked = ""
        self._drop_download()
        self.setVisible(bool(url))
        if not url:
            self._probe_timer.stop()
            return
        if not ytdl.site_allowed(url):   # switched off in Settings > Privacy: no look-up
            self._probe_timer.stop()
            self._say(html.escape(net.off_message(ytdl.site_feature(url))),
                      theme.status("warn"))
            self._buttons()
            return
        self._say(f"Looking up <b>{html.escape(self._host())}</b>…")
        self._buttons()
        self._probe_timer.start()

    def _probe_now(self):
        if self.url:
            netlog.cause(ytdl.FEATURE, "You pasted a link: looking up its name and "
                                       "length")
            threading.Thread(target=self._probe, args=(self.url,), daemon=True,
                             name="link-probe").start()

    def open(self, url: str, title: str, secs: float = 0.0):
        """A video picked from the YouTube search: already looked up, so no probe."""
        if url != self.url:
            if self._queued:   # a pick waiting its turn is replaced: its row stops waiting
                self.done.emit(self.url, self._queued, False)
            self.url = url
            self._queued = ""
            self._blocked = ""
            self._probe_timer.stop()
            self._drop_download()
        self.title = title
        self.show()
        dur = f" · {fmt_time(secs)}" if secs else ""
        self._say(f"<b>{html.escape(title)}</b>{dur} "
                  f"<span style='color:{theme.T['muted']}'>· {html.escape(self._host())}</span>")
        self._buttons()

    def _host(self) -> str:
        return self.url.split("/")[2].removeprefix("www.") if self.url else ""

    def _say(self, text: str, color: str = ""):
        self.info.setText(f"<span style='color:{color}'>{text}</span>" if color else text)

    def _buttons(self):
        self.btn_direct.setVisible(bool(self._blocked) and not self._busy)
        # already added: no second "Add as sound" next to "✓ Added …"
        self.btn_add.setVisible(not self.url or self.url != getattr(self, "_added", ""))
        ok = bool(self.url) and not self._busy and ytdl.site_allowed(self.url)
        self.btn_add.setEnabled(ok)
        self.btn_play.setEnabled(ok)
        self.btn_add.setText("Adding…" if self._busy == "add" else "Add as sound")
        self.btn_play.setText("Loading…" if self._busy == "play" else "Play once")

    def _drop_download(self):
        if self._got is not None:
            _drop_temp(self._got[1])
            self._got = None

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
            self._play(have[-1])
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
        self._say(f"<b>{name}</b> is next: waiting for the download before it to finish…")
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
                bool(self.cfg.ytdlp_auto_optin), direct, video)
        what = netlog.quoted(self.title) if self.title else "a link"
        netlog.cause(ytdl.FEATURE, (f"You clicked Play on {what}" if kind == "play" else
                                    f"You added {what} as a sound")
                     + (" (without Tor)" if direct else ""))
        # a failed download may update the downloader first (ytdl.download_audio)
        netlog.cause(ytdl.UPDATE_FEATURE, f"A download of {what} failed: checking for a "
                                          "newer downloader")
        threading.Thread(target=self._work, args=args, daemon=True, name="link-dl").start()

    def _play(self, data):
        gain = level_gain(data.astype(np.float32) / 32768) if self.cfg.level_volumes else 1.0
        v = self.engine.play(PLAY_ID, data, gain, mode="restart")
        if v is None:
            self._say("No audio device is open — pick one in Setup.", theme.status("warn"))
        else:
            self.played.emit(self.title or "Link", data, gain)
            name = html.escape(self.title or "it")
            self._say(f"▶ Playing <b>{name}</b> ({fmt_time(len(data) / SR)}) — "
                      "<i>Add as sound</i> keeps it.")

    # ------------------------------------------------------------------ workers
    def _probe(self, url: str):
        try:
            self._msg.emit("found", url, ytdl.probe(url))
        except Exception as e:  # noqa: BLE001 - shown in the bar
            log.info("link lookup failed for %s: %s", url, e)
            self._msg.emit("probe-error", url, errors.plain(e))

    def _work(self, kind, url, got, color, known, auto_update, direct=False, video=False):
        """Download (unless `got` already holds it), then import or decode."""
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
                self._msg.emit("play", url, (path, to_int16(decode(str(path)))))
                keep = True   # the UI keeps it so Add as sound needn't download again
                return
            fp = fingerprint(str(path))
            if fp and fp in known:
                raise ytdl.DownloadError(f"It's already in your Sounds as “{known[fp]}”.")
            meta, data = import_file(str(path), color)
            if (pic := thumbs.find_in(Path(path).parent)) is not None:
                meta.image = thumbs.store(pic, meta.id)   # the video's thumbnail
            self.engine.prepare(meta.id, data)
            saved = ""
            if video:
                try:
                    kept = ytdl.save_video(path, title or meta.name)
                    saved = (f"Video saved in {kept.parent}." if kept else
                             "No video was saved: this site only gave the sound.")
                except OSError as e:
                    log.warning("couldn't keep the video of %s: %s", url, e)
                    saved = f"The video couldn't be saved ({errors.plain(e)})."
            self._msg.emit("added", url, (meta, data, title, saved))
        except ytdl.TorBlocked as e:   # the bar offers to try it without Tor
            log.warning("link %s turned away over Tor for %s", kind, url)
            self._msg.emit("blocked", url, (kind, html.escape(
                f"Couldn't {'add' if kind == 'add' else 'play'} it: {e}")))
        except Exception as e:  # noqa: BLE001 - shown in the bar, logged
            log.warning("link %s failed for %s: %s", kind, url, e)
            hint = ("" if not isinstance(e, ytdl.FetchError) or auto_update else
                    " A newer yt-dlp may fix this: Settings → Updates → Update now.")
            doing = "add" if kind == "add" else "play"
            # rich text: the plain words, and a "Report it" link when it's one for us
            self._msg.emit("error", url, errors.html(e, f"Couldn't {doing} it: ",
                                                     where=f"Couldn't {doing} a link")
                           + html.escape(hint))
        finally:
            if not keep and path is not None:
                _drop_temp(path)

    def _on_msg(self, kind: str, url: str, payload):
        current = url == self.url
        if kind == "found":
            if current:
                self.title, secs = payload
                dur = f" · {fmt_time(secs)}" if secs else ""
                self._say(f"<b>{html.escape(self.title)}</b>{dur} "
                          f"<span style='color:{theme.T['muted']}'>"
                          f"· {html.escape(self._host())}</span>")
            return
        if kind == "probe-error":
            if current and not self._busy:
                self._say(html.escape(f"Can't use this link: {payload}"), theme.status("error"))
            return
        if kind == "title":
            if current:
                self.title = self.title or payload
            return
        if kind == "progress":
            self.progress.emit(url, payload)
            if current:
                t = ("Adding…" if self._busy == "add" else "Loading…")
                t = t if payload < 0 else f"{t} {payload:.0%}"
                (self.btn_add if self._busy == "add" else self.btn_play).setText(t)
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
            self._kept = (url, data)
            meta.name = (title or (current and self.title) or meta.name)[:40]
            self.sound_ready.emit(meta, data)
            if current:
                self._say(f"✓ Added <b>{html.escape(meta.name)}</b> to your Sounds."
                          + (f" {html.escape(saved)}" if saved else ""), theme.status("ok"))
            else:   # another link is showing now: still say this one made it
                busy.toast(self.window(), f"✓ Added <b>{html.escape(meta.name)}</b> to your "
                                          "Sounds.", "ok")
            self.done.emit(url, "add", True)
        elif kind == "play":
            path, data = payload
            if current:
                self._got = (url, Path(path), data)
                self._play(data)
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
