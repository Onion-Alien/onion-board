"""Runs a service module (e.g. live speech recognition) as a separate process.

    app                                   module process
    ---                                   --------------
    listen on 127.0.0.1:<random>
    launch  argv --port P --token T  -->  connect, send hello{token}
    mic tap -> deque -> sender thread -->  audio frames (int16 mono 16 kHz)
    reader thread -> on_event(dict)  <--  status / ready / vad / final / error

`feed()` is called from the audio thread, so it only appends to a bounded deque (no
locks, no I/O); a sender thread drains it, resamples to 16 kHz and writes to the
socket. If the module falls behind, the oldest audio is dropped, never the mic.
"""
from __future__ import annotations

import logging
import secrets
import socket
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from collections.abc import Callable

import numpy as np
import soxr

from soundboard.speech import protocol

log = logging.getLogger(__name__)

CONNECT_TIMEOUT_S = 30.0
QUEUE_BLOCKS = 400          # ~4 s of 10 ms mic blocks


class ServiceHost:
    def __init__(self, argv: list[str], on_event: Callable[[dict], None],
                 cwd: Path | None = None, log_path: Path | None = None, name: str = "module"):
        self.argv, self.cwd, self.log_path, self.name = argv, cwd, log_path, name
        self.on_event = on_event
        self._proc: subprocess.Popen | None = None
        self._sock: socket.socket | None = None
        self._q: deque[tuple[np.ndarray, int]] = deque(maxlen=QUEUE_BLOCKS)
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
        srv.listen(1)
        srv.settimeout(0.25)
        port, token = srv.getsockname()[1], secrets.token_hex(16)
        out = subprocess.DEVNULL
        try:
            if self.log_path:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                out = open(self.log_path, "ab")  # noqa: SIM115
            self._proc = subprocess.Popen(
                self.argv + ["--port", str(port), "--token", token], cwd=self.cwd,
                stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            srv.close()
            raise RuntimeError(f"couldn't start {self.name}: {e}") from e
        finally:
            if out is not subprocess.DEVNULL:
                out.close()      # the child has its own handle
        log.info("started %s (pid %d): %s", self.name, self._proc.pid, " ".join(self.argv))
        threading.Thread(target=self._serve, args=(srv, token), name=f"{self.name}-reader",
                         daemon=True).start()

    def stop(self):
        self._stop.set()
        self.send_json({"type": "quit"})
        s, self._sock = self._sock, None
        if s is not None:
            try:
                s.close()
            except OSError:
                pass
        p, self._proc = self._proc, None
        self.connected = False
        if p is not None:
            try:
                p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                p.kill()
        self._q.clear()

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # ------------------------------------------------------------ audio thread
    def feed(self, mono: np.ndarray, rate: int):
        """Mic tap (audio thread): hand over a block; never blocks."""
        if self.connected:
            if len(self._q) == self._q.maxlen:
                self.dropped += 1
            self._q.append((mono.copy(), rate))

    # ------------------------------------------------------------ threads
    def send_json(self, obj: dict):
        s = self._sock
        if s is None:
            return
        try:
            with self._send_lock:
                protocol.send_json(s, obj)
        except OSError:
            pass

    def _serve(self, srv: socket.socket, token: str):
        deadline = time.monotonic() + CONNECT_TIMEOUT_S
        conn = None
        try:
            while conn is None:
                if self._stop.is_set() or not self.running:
                    code = None if self._proc is None else self._proc.poll()
                    self._emit_stopped(f"{self.name} exited before connecting (code {code})"
                                       if code is not None else "")
                    return
                if time.monotonic() > deadline:
                    self._emit_stopped(f"{self.name} didn't connect")
                    self.stop()
                    return
                try:
                    conn, _ = srv.accept()
                except TimeoutError:
                    continue
        finally:
            srv.close()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        conn.settimeout(10)
        try:
            first = protocol.recv(conn)
            hello = protocol.decode_json(first[1]) if first and first[0] == protocol.JSON else {}
        except (OSError, ValueError):
            hello = {}
        if hello.get("type") != "hello" or not secrets.compare_digest(
                str(hello.get("token", "")), token):
            conn.close()
            self._emit_stopped(f"{self.name} failed the handshake")
            self.stop()
            return
        conn.settimeout(None)
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
        except (OSError, ValueError) as e:
            if not self._stop.is_set():
                reason = str(e)
        self.connected = False
        self._emit_stopped(reason)

    def _emit_stopped(self, reason: str):
        if reason:
            log.warning("%s: %s", self.name, reason)
        self.on_event({"type": "stopped", "text": reason})

    def _send_audio(self, conn: socket.socket):
        rs, rs_rate = None, 0
        while self.connected and not self._stop.is_set():
            if not self._q:
                time.sleep(0.02)
                continue
            blocks = []
            while self._q:
                blocks.append(self._q.popleft())
            for x, rate in blocks:
                if rate != rs_rate:
                    rs, rs_rate = soxr.ResampleStream(rate, protocol.AUDIO_RATE, 1,
                                                      dtype="float32", quality="HQ"), rate
                y = x if rate == protocol.AUDIO_RATE else rs.resample_chunk(x)
                pcm = np.clip(np.rint(y * 32767), -32768, 32767).astype("<i2").tobytes()
                try:
                    with self._send_lock:
                        protocol.send(conn, protocol.AUDIO, pcm)
                except OSError:
                    return
