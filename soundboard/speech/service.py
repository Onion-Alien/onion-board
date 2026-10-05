"""Runs a service module (e.g. live speech recognition) as a separate process.

    app                                   module process
    ---                                   --------------
    listen on 127.0.0.1:<random>
    launch  argv --port P --token T  -->  connect, send hello{token}
    mic tap -> queue -> sender thread -->  audio frames (int16 mono 16 kHz)
    reader thread -> on_event(dict)  <--  status / ready / vad / final / error

`feed()` is called from the audio thread, so it only puts the block on a queue (no
I/O, never waits); a sender thread sleeps on that queue until a block arrives (no
polling: no wake-ups while nothing is sent), drains it, resamples to 16 kHz and writes to the
socket. If the module falls behind, the oldest audio is dropped, never the mic.
A module that sends audio back (b"B", the AI voices add-on) hands it to `on_audio`
on the reader thread.
"""
from __future__ import annotations

import logging
import queue
import secrets
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from collections.abc import Callable

import numpy as np
import soxr

from soundboard.speech import protocol
from soundboard import errors

log = logging.getLogger(__name__)

CONNECT_TIMEOUT_S = 30.0
SEND_TIMEOUT_S = 5.0        # a module that stops reading can't wedge a send forever
QUIT_WAIT_S = 0.5           # stop(): how long "quit" waits for a busy sender
QUEUE_BLOCKS = 400          # ~4 s of 10 ms mic blocks
HELLO_TIMEOUT_S = 5.0       # a connection has this long to say hello
HELLO_MAX = 4096            # bytes: the first frame, before we know who's calling


class ServiceHost:
    def __init__(self, argv: list[str], on_event: Callable[[dict], None],
                 cwd: Path | None = None, log_path: Path | None = None, name: str = "module",
                 env: dict[str, str] | None = None,
                 on_audio: Callable[[bytes], None] | None = None,
                 make_resampler: Callable[[int, int], object] | None = None):
        """`make_resampler(src, dst)`: a streaming resampler (resample_chunk) for the
        mic -> 16 kHz; default soxr's HQ, which lets its output out in ~30 ms lumps (fine
        for speech recognition; the AI voice uses soundboard.speech.resample)."""
        self.argv, self.cwd, self.log_path, self.name = argv, cwd, log_path, name
        self.on_audio, self.make_resampler = on_audio, make_resampler
        self.env = env          # None: this process's (soundboard.net.child_env makes one)
        self.on_event = on_event
        self._proc: subprocess.Popen | None = None
        self._sock: socket.socket | None = None
        # SimpleQueue: put() never blocks (safe on the audio thread) and the sender's
        # get() sleeps until there's something, so an idle link costs no CPU
        self._q: queue.SimpleQueue[tuple] = queue.SimpleQueue()
        self._stop = threading.Event()
        self._send_lock = threading.Lock()
        self.connected = False
        self.dropped = 0

    # ------------------------------------------------------------ lifecycle
    def start(self):
        if self._proc is not None:
            return
        self._stop.clear()
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(8)            # a stray local caller can't crowd the module out
        srv.settimeout(0.25)
        port, token = srv.getsockname()[1], secrets.token_hex(16)
        out = subprocess.DEVNULL
        try:
            if self.log_path:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                out = open(self.log_path, "ab")  # noqa: SIM115
            self._proc = subprocess.Popen(
                self.argv + ["--port", str(port), "--token", token], cwd=self.cwd, env=self.env,
                stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            srv.close()
            raise RuntimeError(f"couldn't start {self.name}: {errors.plain(e)}") from e
        finally:
            if out is not subprocess.DEVNULL:
                out.close()      # the child has its own handle
        log.info("started %s (pid %d): %s", self.name, self._proc.pid, " ".join(self.argv))
        threading.Thread(target=self._serve, args=(srv, token), name=f"{self.name}-reader",
                         daemon=True).start()

    def stop(self):
        """Never blocks (the UI calls it): "quit" is sent, the link closed and a
        module that won't quit killed, all from a background thread."""
        self._stop.set()
        s, self._sock = self._sock, None
        p, self._proc = self._proc, None
        self.connected = False
        self._drain()
        if s is not None or p is not None:
            threading.Thread(target=self._reap, args=(p, s), name=f"{self.name}-reap",
                             daemon=True).start()

    def _reap(self, p: subprocess.Popen | None, s: socket.socket | None = None):
        if s is not None:
            # after the frame the sender may be in the middle of (it holds the lock;
            # it stops at the next one), so "quit" arrives whole. A sender stuck in a
            # send: no quit, the link is just closed (and the module killed below)
            if self._send_lock.acquire(timeout=QUIT_WAIT_S):
                try:
                    protocol.send_json(s, {"type": "quit"})
                except OSError:
                    pass
                finally:
                    self._send_lock.release()
            try:
                s.close()
            except OSError:
                pass
        if p is None:
            return
        try:
            p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            log.warning("%s didn't quit; killing it", self.name)
            p.kill()

    def _drain(self):
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # ------------------------------------------------------------ audio thread
    def feed(self, mono: np.ndarray, rate: int):
        """Mic tap (audio thread): hand over a block; never blocks."""
        if self.connected:
            if self._q.qsize() >= QUEUE_BLOCKS:      # nobody's reading: drop the oldest
                try:
                    self._q.get_nowait()
                    self.dropped += 1
                except queue.Empty:
                    pass
            self._q.put((mono.copy(), rate))

    def feed_json(self, obj: dict):
        """A small message, queued in order with the audio (audio thread: never blocks)."""
        if self.connected:
            self._q.put((obj, -1))

    # ------------------------------------------------------------ threads
    def send_json(self, obj: dict, wait: float = -1):
        """Send a message now; with `wait` (seconds) give up if the sender is stuck.
        Not from the UI thread: it waits on the sender's lock (feed_json instead)."""
        s = self._sock
        if s is None or not self._send_lock.acquire(timeout=wait):
            return
        try:
            protocol.send_json(s, obj)
        except OSError:
            pass
        finally:
            self._send_lock.release()

    def _serve(self, srv: socket.socket, token: str):
        # any local process can connect to the port, so a connection that fails the
        # handshake is dropped and the wait goes on: only the module's own counts
        deadline = time.monotonic() + CONNECT_TIMEOUT_S
        conn, hello, rejected = None, {}, 0
        try:
            while conn is None:
                if self._stop.is_set() or not self.running:
                    code = None if self._proc is None else self._proc.poll()
                    if code is None:
                        reason = ""
                    elif rejected:
                        reason = f"{self.name} failed the handshake (exited, code {code})"
                    else:
                        reason = f"{self.name} exited before connecting (code {code})"
                    self._emit_stopped(reason)
                    return
                if time.monotonic() > deadline:
                    self._emit_stopped(f"{self.name} failed the handshake" if rejected
                                       else f"{self.name} didn't connect")
                    self.stop()
                    return
                try:
                    c, _ = srv.accept()
                except TimeoutError:
                    continue
                hello = _handshake(c, token, max(0.5, min(HELLO_TIMEOUT_S,
                                                          deadline - time.monotonic())))
                if hello is None:
                    rejected += 1
                    log.warning("%s: dropped a connection that failed the handshake", self.name)
                    c.close()
                else:
                    conn = c
        finally:
            srv.close()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        conn.settimeout(None)
        _send_timeout(conn, SEND_TIMEOUT_S)
        self._sock = conn
        self.connected = True
        self.on_event(hello)
        threading.Thread(target=self._send_audio, args=(conn,), name=f"{self.name}-sender",
                         daemon=True).start()
        reason = ""
        try:
            while not self._stop.is_set():
                msg = protocol.recv(conn)
                if msg is None:
                    break
                if msg[0] == protocol.JSON:
                    self.on_event(protocol.decode_json(msg[1]))
                elif msg[0] == protocol.VOICE and self.on_audio is not None:
                    self.on_audio(msg[1])
        except Exception as e:  # noqa: BLE001
            # anything (a JSON message nested too deep: RecursionError) ends the
            # session with "stopped", so the UI never stays on "listening", mic muted
            if not self._stop.is_set():
                reason = errors.plain(e)
        self.connected = False
        if not self._stop.is_set():
            self.stop()         # it hung up on us: make sure the process goes too
        self._emit_stopped(reason)

    def _emit_stopped(self, reason: str):
        if reason:
            log.warning("%s: %s", self.name, reason)
        self.on_event({"type": "stopped", "text": reason})

    def _send_audio(self, conn: socket.socket):
        rs, rs_rate = None, 0
        while self.connected and not self._stop.is_set():
            try:
                blocks = [self._q.get(timeout=0.25)]      # wakes as soon as a block is put
            except queue.Empty:
                continue                                  # (looks at connected / stop again)
            while True:
                try:
                    blocks.append(self._q.get_nowait())
                except queue.Empty:
                    break
            for x, rate in blocks:
                if self._stop.is_set():     # stop(): its "quit" goes next, nothing after
                    return
                if rate < 0:            # feed_json
                    try:
                        with self._send_lock:
                            protocol.send_json(conn, x)
                    except OSError:
                        return
                    continue
                if rate != rs_rate:
                    rs = (self.make_resampler(rate, protocol.AUDIO_RATE) if self.make_resampler
                          else soxr.ResampleStream(rate, protocol.AUDIO_RATE, 1,
                                                   dtype="float32", quality="HQ"))
                    rs_rate = rate
                y = x if rate == protocol.AUDIO_RATE else rs.resample_chunk(x)
                pcm = np.clip(np.rint(y * 32767), -32768, 32767).astype("<i2").tobytes()
                try:
                    with self._send_lock:
                        protocol.send(conn, protocol.AUDIO, pcm)
                except OSError:
                    return


def _handshake(conn: socket.socket, token: str, timeout: float) -> dict | None:
    """The hello message if `conn` opened with one carrying `token`, else None. Before
    that it's an unknown caller: a small first frame only, and not much time."""
    conn.settimeout(timeout)
    try:
        head = protocol._exact(conn, protocol._HEAD.size)
        if head is None:
            return None
        kind, n = protocol._HEAD.unpack(head)
        if kind != protocol.JSON or n > HELLO_MAX:
            return None
        payload = protocol._exact(conn, n) if n else b""
        hello = protocol.decode_json(payload) if payload is not None else {}
    except Exception:  # noqa: BLE001
        # any bad hello (a dropped socket, junk, JSON nested too deep: RecursionError)
        # is just a rejected caller; it mustn't end the serving thread
        return None
    if hello.get("type") != "hello" or not secrets.compare_digest(
            str(hello.get("token", "")).encode(), token.encode()):
        return None
    return hello


def _send_timeout(sock: socket.socket, seconds: float):
    """A timeout on sends only (reads stay blocking: the reader waits as long as it
    takes for the module to say something)."""
    try:
        if sys.platform == "win32":
            val = int(seconds * 1000)                          # a DWORD of milliseconds
        else:
            val = struct.pack("ll", int(seconds), int(seconds % 1 * 1e6))   # a timeval
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDTIMEO, val)
    except OSError as e:
        log.warning("couldn't set a send timeout: %s", e)
