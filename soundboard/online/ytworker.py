"""yt-dlp's look-ups and downloads in a helper process, so they never hold up a sound.

yt-dlp is pure Python: a YouTube search parses a megabyte of page with json.loads and
big regular expressions, single C calls that hold the GIL for 30-60 ms. The audio
callbacks need it every 10 ms, so a web search run on a thread in the app was heard
as a stutter in whatever was playing. In its own process it shares nothing with them.

The app turns it on (`enabled`); tests and scripts run yt-dlp in-process as before,
and so does the app when the helper can't start. One helper is kept warm (`warm()`
when the search box is used) and quits by itself after IDLE_S without work. The
helper only runs yt-dlp: its options come from ytdl (the relay, the formats), and
its errors go back to ytdl, which words them for the user.
"""
from __future__ import annotations

import copy
import logging
import os
import re
import subprocess
import sys
import threading
import time
from multiprocessing.connection import Client, Listener
from pathlib import Path

log = logging.getLogger(__name__)

ARG = "--ytdl-worker"
ADDR_ENV, KEY_ENV = "OB_YTDL_ADDR", "OB_YTDL_KEY"
IDLE_S = 600            # a helper with nothing to do quits after this
START_TIMEOUT_S = 30    # to start and connect back
LOOKUP_TIMEOUT_S = 120  # a search or look-up; a download's limit is the caller's
KEEP = 1                # helpers kept waiting
RETRY_S = 300           # after a helper failed to start, in-process until then
STALL_S = 60            # a download whose bytes don't grow for this long is stuck
DRY_ASKS = 20           # a download's requests in a row that bring no new bytes: stuck

enabled = False
_lock = threading.Lock()
_idle: list[_Helper] = []
_gen = 0                # bumped by drop_all(): helpers started before don't come back
_warming = False
_failed_at: float | None = None   # when a helper last failed to start


class Unavailable(RuntimeError):
    """The helper couldn't start or died: the caller runs it in-process instead."""


class Stalled(Exception):
    """A download that stopped growing while yt-dlp kept calling back: a server that
    cuts every piece off makes yt-dlp ask for the same bytes again and again, forever."""


class TooBig(Exception):
    """A download past its size cap while it ran: yt-dlp's max_filesize only looks at the
    size a site gives up front, so one that names none (an endless stream) went on until
    the disk was full."""


def stall_guard(clock=None, cap: int = 0):
    """For a progress hook: `check(downloaded_bytes)` raises Stalled once the count
    hasn't grown for STALL_S, however often yt-dlp says it's still downloading, and
    TooBig once it's past `cap` bytes (0: no cap)."""
    clock = clock or (lambda: time.monotonic())
    best, grew = [-1], [clock()]

    def check(done: int) -> None:
        if cap and done > cap:
            raise TooBig(f"over {cap} bytes")
        now = clock()
        if done > best[0]:
            best[0], grew[0] = done, now
        elif now - grew[0] >= STALL_S:
            raise Stalled(f"no new data for {STALL_S} s")
    return check


def guard_requests(ydl) -> None:
    """From now on (the download, after the look-up), DRY_ASKS requests in a row that
    bring no new bytes raise Stalled. A server that sends nothing for the last piece
    leaves yt-dlp asking for it again at once, with no limit (a chunked download's next
    piece isn't a retry) and no progress call, so stall_guard never hears of it: the
    site got hundreds of requests a minute until the quiet timer gave up."""
    urlopen, add = getattr(ydl, "urlopen", None), getattr(ydl, "add_progress_hook", None)
    if not (callable(urlopen) and callable(add)):
        return
    seen: dict = {}
    dry = [0]

    def hook(d):
        got = d.get("downloaded_bytes") or 0
        if got > seen.get(d.get("filename"), -1):   # per file: a video's sound starts at 0
            seen[d.get("filename")] = got
            dry[0] = 0

    def counted(req, *a, **kw):
        dry[0] += 1
        if dry[0] > DRY_ASKS:
            raise Stalled(f"{DRY_ASKS} requests in a row brought no new data")
        return urlopen(req, *a, **kw)
    add(hook)
    ydl.urlopen = counted


class RemoteError(Exception):
    """yt-dlp's error in the helper; `kind` is its class ("module.Name")."""

    def __init__(self, kind: str, text: str):
        super().__init__(text)
        self.kind = kind


def _command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, ARG]
    main = Path(__file__).resolve().parents[2] / "main.py"
    return [sys.executable, str(main), ARG]


class _Helper:
    def __init__(self):
        self.gen = _gen
        key = os.urandom(32)
        listener = Listener(family="AF_PIPE" if sys.platform == "win32" else "AF_UNIX",
                            authkey=key)
        env = dict(os.environ, **{ADDR_ENV: listener.address, KEY_ENV: key.hex()})
        flags = 0
        if sys.platform == "win32":   # no console, and behind the app for the CPU
            flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
        self.proc = subprocess.Popen(_command(), env=env, creationflags=flags,
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, close_fds=True)
        got: list = []

        def accept():
            try:
                got.append(listener.accept())
            except (OSError, EOFError) as e:   # woken by _wake() below, or the child broke
                log.debug("download helper's connection: %s", e)
        t = threading.Thread(target=accept, daemon=True, name="ytdl-helper-accept")
        t.start()
        deadline = time.monotonic() + START_TIMEOUT_S
        # A helper that already quit (a broken install, yt-dlp failing to import) is
        # seen within a tick, not after the whole START_TIMEOUT_S.
        while t.is_alive() and self.proc.poll() is None and time.monotonic() < deadline:
            t.join(0.05)
        t.join(0.2)   # it connected just before quitting: take the answer
        if not got:
            code = self.proc.poll()
            self.proc.kill()
            _wait(self.proc)
            _wake(listener.address)   # accept() blocks until someone connects
            t.join(2)
            for c in got:
                c.close()
            listener.close()
            raise Unavailable("the download helper didn't start" if code is None else
                              f"the download helper quit at start (code {code})")
        listener.close()
        self.conn = got[0]

    def alive(self) -> bool:
        return self.proc.poll() is None and not self.conn.closed

    def kill(self):
        try:
            self.conn.close()
        except OSError:
            pass
        if self.proc.poll() is None:
            self.proc.kill()
        _wait(self.proc)

    def call(self, request: tuple, timeout: float, progress=None):
        wait = timeout
        try:
            self.conn.send(request)
            while True:
                if not self.conn.poll(wait):
                    self.kill()
                    raise TimeoutError(f"no answer from the download helper in {wait:.0f} s")
                kind, value = self.conn.recv()
                if kind in ("progress", "alive"):
                    # bytes are coming in: from now on a silence of STALL_S is stuck (a
                    # server that cuts every piece off leaves yt-dlp asking again, silently)
                    wait = min(timeout, STALL_S)
                if kind == "progress":
                    if progress:
                        progress(value)
                    continue
                if kind == "alive":   # downloading, size unknown: not stuck
                    continue
                return kind, value
        except TimeoutError:   # an OSError too, but stuck isn't "no helper": not here again
            raise
        except (EOFError, OSError, BrokenPipeError) as e:
            self.kill()
            raise Unavailable(f"the download helper stopped: {e}") from e


def _wait(proc):
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        log.info("the download helper (%s) is slow to quit", proc.pid)


def _wake(address):
    """Connects to a Listener waiting in accept() and hangs up, so accept() returns
    (its handshake fails) and its thread ends."""
    try:
        Client(address).close()
    except OSError:
        pass


def _start() -> _Helper:
    """A new helper. One that can't start is not tried again for RETRY_S: the
    callers run yt-dlp in-process straight away instead of waiting for it each time."""
    global _failed_at
    with _lock:
        if _failed_at is not None and time.monotonic() - _failed_at < RETRY_S:
            raise Unavailable("the download helper failed to start a moment ago")
    try:
        return _Helper()
    except Exception:
        with _lock:
            _failed_at = time.monotonic()
        raise


def _take() -> _Helper:
    with _lock:
        while _idle:
            h = _idle.pop()
            if h.alive():
                return h
            h.kill()
    return _start()


def _give_back(h: _Helper):
    with _lock:
        if h.gen == _gen and h.alive() and len(_idle) < KEEP:
            _idle.append(h)
            return
    h.kill()


def warm():
    """Start a helper now (on a thread) if none is waiting: the search box is in use."""
    global _warming
    if not enabled:
        return
    with _lock:
        if _idle or _warming:
            return
        _warming = True

    def start():
        global _warming
        try:
            _give_back(_start())
        except Exception as e:  # noqa: BLE001 - the next call starts one (or runs in-process)
            log.info("couldn't start the download helper ahead: %s", e)
        finally:
            _warming = False
    threading.Thread(target=start, daemon=True, name="ytdl-helper-warm").start()


def drop_all():
    """yt-dlp was updated or reset, or the app is closing: no helper keeps the old copy
    (and a new copy may start where the old one failed)."""
    global _gen, _failed_at
    with _lock:
        _gen += 1
        _failed_at = None
        old, _idle[:] = list(_idle), []
    for h in old:
        h.kill()


def run(op: str, *args, timeout: float = LOOKUP_TIMEOUT_S, progress=None):
    """`op` (see _OPS) in a helper. Raises RemoteError for yt-dlp's own errors,
    TimeoutError, or Unavailable when there's no helper to run it."""
    try:
        h = _take()
    except Unavailable:
        raise
    except Exception as e:  # noqa: BLE001 - Popen / the pipe: run it in-process
        raise Unavailable(f"couldn't start the download helper: {e}") from e
    kind, value = h.call((op, *args), timeout, progress)
    _give_back(h)
    if kind == "ok":
        return value
    raise RemoteError(*value)


# ---------------------------------------------------------------------- the helper

_LOOKUP_DROP = ("formats", "requested_formats", "thumbnails", "automatic_captions",
                "subtitles", "heatmap", "http_headers", "requested_downloads",
                "fragments", "chapters", "storyboards")


def _slim(info):
    """What the app reads of an info dict, minus the big parts (formats and so on)."""
    if not isinstance(info, dict):
        return info
    out = {k: v for k, v in info.items() if k not in _LOOKUP_DROP and not k.startswith("__")}
    # a flat search entry lists its picture only here (SoundCloud's card art): keep the
    # last, the one the card reads, and drop the rest of the list
    art = next((t["url"] for t in reversed(info.get("thumbnails") or ())
                if isinstance(t, dict) and t.get("url")), None)
    if art:
        out["thumbnails"] = [{"url": art}]
    if isinstance(out.get("entries"), list) or "entries" in info:
        out["entries"] = [_slim(e) for e in (info.get("entries") or ()) if e]
    return out


# Before every search, yt-dlp fetches a YouTube page only to read its settings (the
# "client config"): about a second, half of a search. They don't change from one
# search to the next, so a search with `keep` reuses the last ones for CONFIG_KEEP_S.
# ytdl only asks for that in Direct mode: in Tor mode the settings (they carry a
# visitor id) would tie searches made over different Tor routes together.
CONFIG_KEEP_S = 3600
_CONFIG_IES = ("YoutubeSearch", "YoutubeMusicSearchURL")
_configs: dict[str, tuple[float, dict]] = {}
_configs_lock = threading.Lock()


def forget_configs():
    with _configs_lock:
        _configs.clear()


def _keep_configs(ydl, used: list, fresh: bool = False) -> None:
    """ydl's YouTube searches reuse the kept settings (`used` gets a True each time
    they do; `fresh`: never, they're fetched and kept for the next search). When
    yt-dlp has changed and this can't be done, it fetches them as before."""
    for key in _CONFIG_IES:
        try:
            ie = ydl.get_info_extractor(key)
            fetch = ie._download_ytcfg
        except Exception:  # noqa: BLE001 - yt-dlp changed: leave it as it is
            continue

        def cached(client, video_id, fetch=fetch):
            with _configs_lock:
                hit = _configs.get(client)
            if hit and not fresh and time.monotonic() - hit[0] < CONFIG_KEEP_S:
                used.append(True)
                return copy.deepcopy(hit[1])
            cfg = fetch(client, video_id)
            if cfg:
                with _configs_lock:
                    _configs[client] = (time.monotonic(), copy.deepcopy(cfg))
            return cfg
        ie._download_ytcfg = cached


def extract(yt_dlp, target: str, opts: dict, keep: bool = False):
    """yt-dlp's look-up of `target`. With `keep`, YouTube searches reuse the kept
    settings; if that fails, it's done again the old way, with fresh ones."""
    used: list = []
    lists = PLAYLIST_FILTER in target
    if keep:
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                _keep_configs(ydl, used)
                if lists:
                    _playlist_counts(ydl)
                return ydl.extract_info(target, download=False)
        except Exception as e:  # noqa: BLE001 - retried below, or raised as it is
            if not used:
                raise
            forget_configs()
            log.info("search with the kept YouTube settings failed (%s); fresh ones",
                     str(e)[:120])
    with yt_dlp.YoutubeDL(opts) as ydl:
        if keep:
            _keep_configs(ydl, [], fresh=True)
        if target.startswith("scsearch"):
            _listed_art_only(ydl)
        if lists:
            _playlist_counts(ydl)
        return ydl.extract_info(target, download=False)


PLAYLIST_FILTER = "sp=EgIQAw"   # YouTube's search for playlists (ytsearch.search)
_VIDEOS = re.compile(r"([\d.,]+)\s*([KM]?)\s+(?:videos?|episodes?)", re.I)


def _playlist_counts(ydl):
    """A YouTube playlist search: each card says how many videos the playlist has
    (ytsearch._playlist_hit). The page shows it on the picture ("7 videos"), and yt-dlp
    reads it but keeps only a video's length from there: it goes into the entry as
    playlist_count. Nothing more is asked of YouTube."""
    try:
        ie = ydl.get_info_extractor("YoutubeSearchURL")
        lockup = ie._extract_lockup_view_model
    except Exception:  # noqa: BLE001 - another yt-dlp: the cards say "Playlist", as before
        return

    def counted(view_model):
        entry = lockup(view_model)
        if isinstance(entry, dict) and isinstance(view_model, dict) and (
                view_model.get("contentType") == "LOCKUP_CONTENT_TYPE_PLAYLIST"):
            n = _badge_count(view_model.get("contentImage"))
            if n is not None:
                entry["playlist_count"] = n
        return entry
    ie._extract_lockup_view_model = counted


def _badge_count(node, depth: int = 0) -> int | None:
    """The "N videos" text on a playlist's picture, as a number (None: not there)."""
    if depth > 12:
        return None
    if isinstance(node, dict):
        badge = node.get("thumbnailBadgeViewModel")
        text = badge.get("text") if isinstance(badge, dict) else None
        m = _VIDEOS.fullmatch(text.strip()) if isinstance(text, str) else None
        if m:
            num = float(m.group(1).replace(",", "")) if m.group(2) else float(
                m.group(1).replace(",", "").replace(".", ""))
            return int(num * {"": 1, "K": 1000, "M": 1000000}[m.group(2).upper()])
        nodes = node.values()
    elif isinstance(node, list):
        nodes = node
    else:
        return None
    for v in nodes:
        n = _badge_count(v, depth + 1)
        if n is not None:
            return n
    return None


def _listed_art_only(ydl):
    """A SoundCloud search: yt-dlp asks SoundCloud's picture server about every
    result's full-size cover (one request each, even with search pictures off in
    Settings > Data & quality), and the card only ever shows the 300 px one
    (ytdl._soundcloud_hit). The cover link the search lists is all it needs."""
    try:
        ie = ydl.get_info_extractor("SoundcloudSearch")
    except Exception:  # noqa: BLE001 - another yt-dlp: it just asks, as before
        return

    def listed(info):
        url = info.get("artwork_url") or (info.get("user") or {}).get("avatar_url")
        return [{"url": url}] if isinstance(url, str) and url.startswith("https://") else None
    ie._extract_thumbnails = listed


def _lookup(conn, yt_dlp, target: str, opts: dict, keep: bool = False):
    return _slim(extract(yt_dlp, target, opts, keep))


def _download(conn, yt_dlp, url: str, opts: dict, max_seconds: float):
    """ytdl._run's yt-dlp part: (info, the file yt-dlp names). Says how far it got
    (or, when the site gives no size, that it's still going: at least once a second):
    the app takes a download that says nothing for DOWNLOAD_QUIET_S as stuck."""
    last = [0.0]
    stalled = stall_guard(cap=opts.get("max_filesize") or 0)

    def hook(d):
        if d.get("status") != "downloading":
            return
        stalled(d.get("downloaded_bytes") or 0)
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        now = time.monotonic()
        if not total:
            if now - last[0] >= 1.0:
                last[0] = now
                conn.send(("alive", None))
            return
        f = min(d.get("downloaded_bytes", 0) / total, 1.0)
        if now - last[0] >= 0.1 or f >= 1.0:
            last[0] = now
            conn.send(("progress", f))
    opts = dict(opts, progress_hooks=[hook])
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if info.get("_type") == "playlist" or info.get("is_live"):
            return _slim(info), ""   # the app refuses it (ytdl._check)
        guard_requests(ydl)
        info = ydl.process_ie_result(info, download=True)
        return _slim(info), ydl.prepare_filename(info)


def _ping(conn, yt_dlp):
    """Is it up (tests): its process id and yt-dlp's version."""
    return os.getpid(), getattr(getattr(yt_dlp, "version", None), "__version__", "")


_OPS = {"lookup": _lookup, "download": _download, "ping": _ping}


def child_main() -> int:
    """The helper process (main.py ARG): yt-dlp requests until IDLE_S of nothing."""
    addr, key = os.environ.pop(ADDR_ENV, ""), os.environ.pop(KEY_ENV, "")
    if not addr or not key:
        return 2
    for name in ("stdout", "stderr"):   # pythonw / a windowed build has none
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    logging.basicConfig(level=logging.CRITICAL)
    conn = Client(addr, authkey=bytes.fromhex(key))
    quiet = logging.getLogger("ytdl-helper")
    quiet.disabled = True
    from soundboard.online import ytdl
    with ytdl._ydl() as yt_dlp:   # imported once, up front: a search needn't wait for it
        pass
    while conn.poll(IDLE_S):
        try:
            op, *args = conn.recv()
        except (EOFError, OSError):
            return 0
        try:
            with ytdl._ydl() as yt_dlp:
                args[1:2] = [dict(args[1], logger=quiet)] if len(args) > 1 else []
                result = ("ok", _OPS[op](conn, yt_dlp, *args))
        except BaseException as e:  # noqa: BLE001 - sent back for the app to word
            t = type(e)
            result = ("err", (f"{t.__module__}.{t.__name__}", str(e)))
        try:
            conn.send(result)
        except (EOFError, OSError):
            return 0
    return 0
