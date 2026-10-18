"""A sound's effects rendered in a helper process, so a slow render never holds up the app.

A song said in an AI voice takes minutes (the voice helper converts about three times
faster than it plays), and the render's Python side (feeding the voice, the stretch,
the effects, block by block) ran on a thread in the app: it took the GIL from the audio
callbacks and the UI for all that time, heard as stutter and felt as lag. In its own
process, at below-normal priority, it shares nothing with them. The child writes the
render into the same cache file library.render_cached would; the app then just maps it.

    app ── ("render", meta, fx, dirs) ──> helper: library.render_cached
        <── ("progress", 0..1) ...  ("ok" | "cancelled" | "err", text)
    app ── "cancel" ──> helper stops (its AI voice helper too), leaves nothing behind

The app turns it on (`enabled`); tests and scripts render in-process as before, and so
does the app when the helper can't start (Unavailable). One helper per render: they're
seconds to minutes long, so starting one (about a second) is not worth keeping one warm.
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

ARG = "--render-worker"
ADDR_ENV, KEY_ENV = "OB_RENDER_ADDR", "OB_RENDER_KEY"
START_TIMEOUT_S = 30    # to start and connect back
QUIT_S = 5              # after "cancel", how long it has to tidy up before it's killed
SLOW_S = 20.0           # sounds this long (or said in an AI voice) render in the helper
PROGRESS_S = 0.2        # the helper says how far it is at most this often

enabled = False


class Unavailable(RuntimeError):
    """The helper couldn't start or died: the caller renders in-process instead."""


def worth_it(fx: dict | None, duration: float) -> bool:
    """A render slow enough for the helper: an AI voice, or a long sound."""
    from soundboard import soundfx
    voice = soundfx.clean(fx).get("voice") or {}
    return bool(voice.get("ai")) or duration >= SLOW_S


def _command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, ARG]
    main = Path(__file__).resolve().parent.parent / "main.py"
    return [sys.executable, str(main), ARG]


def render(meta, cancel, progress=None) -> None:
    """Render `meta`'s effects into its cache file (library.render_cached) in a helper.
    cancel() is asked a few times a second: True stops it (raises library.Cancelled);
    progress(frac) as it goes. Raises Unavailable when there's no helper (render it
    in-process), RuntimeError with the helper's words when the render failed."""
    from soundboard.sounds import library
    key = os.urandom(32)
    listener = Listener(family="AF_PIPE" if sys.platform == "win32" else "AF_UNIX",
                        authkey=key)
    env = dict(os.environ, **{ADDR_ENV: listener.address, KEY_ENV: key.hex()})
    flags = 0
    if sys.platform == "win32":   # no console, and behind the app for the CPU (its AI
        # voice helper inherits the lower priority)
        flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
    try:
        proc = subprocess.Popen(_command(), env=env, creationflags=flags,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, close_fds=True)
    except OSError as e:
        listener.close()
        raise Unavailable(f"couldn't start the render helper: {e}") from e
    got: list = []

    def accept():
        try:
            got.append(listener.accept())
        except (OSError, EOFError) as e:   # woken by _wake(), or the child broke
            log.debug("render helper's connection: %s", e)
    t = threading.Thread(target=accept, daemon=True, name="render-helper-accept")
    t.start()
    deadline = time.monotonic() + START_TIMEOUT_S
    while t.is_alive() and proc.poll() is None and time.monotonic() < deadline:
        if cancel():
            break
        t.join(0.05)
    t.join(0.2)
    if not got:
        code = proc.poll()
        _kill(proc)
        _wake(listener.address)
        t.join(2)
        listener.close()
        if cancel():
            raise library.Cancelled
        raise Unavailable("the render helper didn't start" if code is None else
                          f"the render helper quit at start (code {code})")
    listener.close()
    conn = got[0]
    try:
        conn.send(("render", meta, meta.fx, str(library.APP_DIR), str(library.CACHE_DIR)))
        asked = None   # when "cancel" was sent
        while True:
            if asked is None and cancel():
                conn.send("cancel")
                asked = time.monotonic()
            if asked is not None and time.monotonic() - asked > QUIT_S:
                log.info("the render helper didn't stop in %d s; killing it", QUIT_S)
                raise library.Cancelled
            if not conn.poll(0.1):
                if proc.poll() is not None:
                    raise Unavailable(f"the render helper stopped (code {proc.returncode})")
                continue
            kind, value = conn.recv()
            if kind == "progress":
                if progress is not None and asked is None:
                    progress(value)
            elif kind == "ok":
                return
            elif kind == "cancelled":
                raise library.Cancelled
            else:
                raise RuntimeError(value)
    except (EOFError, OSError) as e:
        if cancel():
            raise library.Cancelled from None
        raise Unavailable(f"the render helper stopped: {e}") from e
    finally:
        try:
            conn.close()
        except OSError:
            pass
        try:
            proc.wait(QUIT_S)
        except subprocess.TimeoutExpired:
            _kill(proc)


def _kill(proc):
    if proc.poll() is None:
        proc.kill()
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        log.info("the render helper (%s) is slow to quit", proc.pid)


def _wake(address):
    """Connects to a Listener waiting in accept() and hangs up, so accept() returns."""
    try:
        Client(address).close()
    except OSError:
        pass


# ---------------------------------------------------------------------- the helper

def child_main() -> int:
    """The helper process (main.py ARG): one render, then it quits."""
    addr, key = os.environ.pop(ADDR_ENV, ""), os.environ.pop(KEY_ENV, "")
    if not addr or not key:
        return 2
    for name in ("stdout", "stderr"):   # pythonw / a windowed build has none
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    logging.basicConfig(level=logging.WARNING)
    conn = Client(addr, authkey=bytes.fromhex(key))
    try:
        op, meta, fx, app_dir, cache_dir = conn.recv()
    except (EOFError, OSError):
        return 0
    if op != "render":
        return 2
    from soundboard.sounds import library
    library.APP_DIR, library.CACHE_DIR = Path(app_dir), Path(cache_dir)
    stop = [False]

    def cancel() -> bool:
        if not stop[0]:
            try:
                if conn.poll():   # "cancel", or the app went away (EOF)
                    stop[0] = True
            except (EOFError, OSError):
                stop[0] = True
        return stop[0]
    told = [0.0]

    def progress(frac: float):
        now = time.monotonic()
        if now - told[0] >= PROGRESS_S:
            told[0] = now
            try:
                conn.send(("progress", float(frac)))
            except (EOFError, OSError):
                stop[0] = True
    try:
        library.render_cached(meta.id, library.load_original(meta), fx, cancel, progress)
        result = ("ok", "")
    except library.Cancelled:
        result = ("cancelled", "")
    except BaseException as e:  # noqa: BLE001 - sent back for the app to word
        from soundboard.core import errors
        result = ("err", errors.plain(e))
    try:
        conn.send(result)
    except (EOFError, OSError):
        pass
    return 0
