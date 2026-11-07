"""The computer voice's lines through the voice changer, in a helper process.

VoiceChain.render is Python and numpy from start to end, on a thread in the app: while
it runs it fights the audio callbacks for the GIL, and on a slower PC with a lot playing
others heard the mic drop out and the line took seconds to start. In its own process it
shares nothing with them.

    app ── ("line", effects, mono, rate, light) ──> helper: VoiceChain.render
        <── ("ok", rendered) | ("err", text)

A line can't wait for a helper to start, so the first one renders in the app as it
always did while the helper starts behind it; the helper then stays, as lines tend to
come in bursts, and quits by itself after IDLE_S without one. render() returning None
means "do it here": no helper (yet), an effect the helper can't run, or it failed. The
app turns it on (`enabled`); tests and scripts render in-process.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from multiprocessing.connection import Client, Connection, Listener
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

ARG = "--line-helper"
ADDR_ENV, KEY_ENV = "OB_LINE_ADDR", "OB_LINE_KEY"
START_TIMEOUT_S = 30    # to start and connect back
LINE_TIMEOUT_S = 60     # for one line; after that it's stuck
IDLE_S = 300            # the helper quits after this long without a line

enabled = False


def can_render(effects: dict) -> bool:
    """The helper has what these effects need: they're ours, and need nothing from the
    app. An add-on's isn't loaded there, the backdrop plays the app's own loops, and an
    effect with a `prepare` fetches or loads what it plays."""
    from soundboard import voicefx
    for etype in effects:
        cls = voicefx.REGISTRY.get(etype)
        if (cls is None or etype == "backdrop"
                or not cls.__module__.startswith("soundboard.voicefx.builtin")
                or cls.prepare.__func__ is not voicefx.Effect.prepare.__func__):
            return False
    return True


def _command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, ARG]
    main = Path(__file__).resolve().parents[2] / "main.py"
    return [sys.executable, str(main), ARG]


class LineHelper:
    """The app's side: one helper, one line at a time."""

    def __init__(self):
        self._lock = threading.Lock()    # held while a line is with the helper
        self._conn: Connection | None = None
        self._proc: subprocess.Popen | None = None
        self._starting = False
        self._closed = False

    def render(self, effects: dict, mono: np.ndarray, rate: int,
               light: bool = False) -> np.ndarray | None:
        """`mono` through `effects` ({type: settings}, the ones VoiceChain.render_effects
        gives), or None: render it in the app. Blocks: call it off the UI thread."""
        if not enabled or self._closed or not effects or not can_render(effects):
            return None
        with self._lock:
            conn = self._conn
            if conn is None:
                self._start()
                return None
            try:
                conn.send(("line", effects, np.asarray(mono, np.float32), rate, light))
                kind, value = self._reply(conn)
            except (EOFError, OSError, TimeoutError) as e:
                # (it also quits after IDLE_S: the next line starts it again)
                log.debug("the line helper's gone: %s", e)
                self._drop()
                self._start()
                return None
        if kind == "ok":
            return value
        log.warning("the line helper couldn't render a line: %s", value)
        return None

    def _reply(self, conn: Connection):
        deadline = time.monotonic() + LINE_TIMEOUT_S
        while not conn.poll(0.1):
            proc = self._proc
            if proc is not None and proc.poll() is not None:
                raise EOFError(f"stopped (code {proc.returncode})")
            if time.monotonic() > deadline:
                raise TimeoutError("no answer")
        return conn.recv()

    def _start(self):
        """(Under the lock.) Start it behind the line that asked."""
        if self._starting:
            return
        self._starting = True
        threading.Thread(target=self._connect, daemon=True, name="line-helper-start").start()

    def _connect(self):
        conn = proc = None
        try:
            key = os.urandom(32)
            listener = Listener(family="AF_PIPE" if sys.platform == "win32" else "AF_UNIX",
                                authkey=key)
            try:
                env = dict(os.environ, **{ADDR_ENV: listener.address, KEY_ENV: key.hex()})
                flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                proc = subprocess.Popen(_command(), env=env, creationflags=flags,
                                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, close_fds=True)
                got: list = []
                t = threading.Thread(target=lambda: got.append(listener.accept()), daemon=True,
                                     name="line-helper-accept")
                t.start()
                t.join(START_TIMEOUT_S)
                if got:
                    conn = got[0]
                else:   # wakes the accept, which then fails on the wrong key
                    log.info("the line helper didn't start (%s)", proc.poll())
                    _kill(proc)
                    try:
                        Client(listener.address).close()
                    except Exception:  # noqa: BLE001 - only to end the accept
                        pass
                    proc = None
            finally:
                listener.close()
        except Exception:  # noqa: BLE001 - lines just render in the app
            log.info("couldn't start the line helper", exc_info=True)
            if proc is not None:
                _kill(proc)
            proc = None
        with self._lock:
            self._starting = False
            if self._closed:
                if conn is not None:
                    conn.close()
                if proc is not None:
                    _kill(proc)
                return
            self._conn, self._proc = conn, proc

    def _drop(self):
        conn, proc, self._conn, self._proc = self._conn, self._proc, None, None
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass
        if proc is not None:
            _kill(proc)

    def close(self):
        """The helper goes too. Doesn't wait for a line that's with it."""
        self._closed = True
        if self._lock.acquire(timeout=0.2):
            try:
                self._drop()
            finally:
                self._lock.release()
        else:
            proc = self._proc
            if proc is not None and proc.poll() is None:
                proc.kill()   # its line fails with EOF, and renders in the app


def _kill(proc: subprocess.Popen):
    if proc.poll() is None:
        proc.kill()
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        log.info("the line helper (%s) is slow to quit", proc.pid)


# ---------------------------------------------------------------------- the helper

def child_main() -> int:
    """The helper process (main.py ARG): lines until the app goes, or IDLE_S of none."""
    addr, key = os.environ.pop(ADDR_ENV, ""), os.environ.pop(KEY_ENV, "")
    if not addr or not key:
        return 2
    for name in ("stdout", "stderr"):   # pythonw / a windowed build has none
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    logging.basicConfig(level=logging.WARNING)
    # (first: connected means ready, and a line never waits for these)
    from soundboard import voicefx
    from soundboard.core import errors
    conn = Client(addr, authkey=bytes.fromhex(key))
    while True:
        try:
            if not conn.poll(IDLE_S):
                return 0
            op, effects, mono, rate, light = conn.recv()
        except (EOFError, OSError):
            return 0
        if op != "line":
            return 2
        try:
            voicefx.set_light(light)
            chain = voicefx.VoiceChain()
            chain.configure({"enabled": True, "effects": effects})
            result = ("ok", chain.render(mono, rate))
        except Exception as e:  # noqa: BLE001 - sent back: the app renders it itself
            result = ("err", errors.plain(e))
        try:
            conn.send(result)
        except (EOFError, OSError):
            return 0
