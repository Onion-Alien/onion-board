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

import logging
import os
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

enabled = False
_lock = threading.Lock()
_idle: list[_Helper] = []
_gen = 0                # bumped by drop_all(): helpers started before don't come back
_warming = False


class Unavailable(RuntimeError):
    """The helper couldn't start or died: the caller runs it in-process instead."""


class RemoteError(Exception):
    """yt-dlp's error in the helper; `kind` is its class ("module.Name")."""

    def __init__(self, kind: str, text: str):
        super().__init__(text)
        self.kind = kind


def _command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, ARG]
    main = Path(__file__).resolve().parent.parent / "main.py"
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
        t = threading.Thread(target=lambda: got.append(listener.accept()), daemon=True,
                             name="ytdl-helper-accept")
        t.start()
        t.join(START_TIMEOUT_S)
        if not got:
            self.proc.kill()
            listener.close()
            raise Unavailable("the download helper didn't start")
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

    def call(self, request: tuple, timeout: float, progress=None):
        try:
            self.conn.send(request)
            while True:
                if not self.conn.poll(timeout):
                    self.kill()
                    raise TimeoutError(f"no answer from the download helper in {timeout:.0f} s")
                kind, value = self.conn.recv()
                if kind == "progress":
                    if progress:
                        progress(value)
                    continue
                if kind == "alive":   # downloading, size unknown: not stuck
                    continue
                return kind, value
        except (EOFError, OSError, BrokenPipeError) as e:
            self.kill()
            raise Unavailable(f"the download helper stopped: {e}") from e


def _take() -> _Helper:
    with _lock:
        while _idle:
            h = _idle.pop()
            if h.alive():
                return h
            h.kill()
    return _Helper()


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
            _give_back(_Helper())
        except Exception as e:  # noqa: BLE001 - the next call starts one (or runs in-process)
            log.info("couldn't start the download helper ahead: %s", e)
        finally:
            _warming = False
    threading.Thread(target=start, daemon=True, name="ytdl-helper-warm").start()


def drop_all():
    """yt-dlp was updated or reset, or the app is closing: no helper keeps the old copy."""
    global _gen
    with _lock:
        _gen += 1
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
    if isinstance(out.get("entries"), list) or "entries" in info:
        out["entries"] = [_slim(e) for e in (info.get("entries") or ()) if e]
    return out


def _lookup(conn, yt_dlp, target: str, opts: dict):
    with yt_dlp.YoutubeDL(opts) as ydl:
        return _slim(ydl.extract_info(target, download=False))


def _download(conn, yt_dlp, url: str, opts: dict, max_seconds: float):
    """ytdl._run's yt-dlp part: (info, the file yt-dlp names). Says how far it got
    (or, when the site gives no size, that it's still going: at least once a second):
    the app takes a download that says nothing for DOWNLOAD_QUIET_S as stuck."""
    last = [0.0]

    def hook(d):
        if d.get("status") != "downloading":
            return
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
    from soundboard import ytdl
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
