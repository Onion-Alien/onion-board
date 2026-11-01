"""The language voices: Piper voices that read translated lines out loud.

Each translation add-on brings one (speech/translation.py puts it in
translation\\xx\\voice\\). They're read by the AI voices add-on's reader.py, run in
that add-on's own Python and kept running between lines:

    PiperReader.synth(text, voice.onnx) --stdin JSON--> reader.py --> a .wav
                                        <--stdout {"ok": true}--

Like Windows speech before it (tts.py), the reader closes after IDLE_CLOSE_S
without a line, so a loaded voice (~60 MB each) doesn't sit in memory all evening.
A voice's id in the voice lists is `piper:<language>`.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from soundboard.speech.tts import TTS_RATE, _pump, _remove

log = logging.getLogger(__name__)

PREFIX = "piper:"
START_TIMEOUT_S = 60.0      # its Python, onnxruntime and Piper: a cold disk is slow
LINE_TIMEOUT_S = 30.0       # a voice's first line loads it (~2 s), the rest are quick
IDLE_CLOSE_S = 600.0
IDLE_CHECK_S = 30.0
TARGET_RMS = 0.1            # -20 dBFS: where a Windows voice's line sits
PEAK = 0.9


def level(mono: np.ndarray) -> np.ndarray:
    """A line at about the loudness Windows' voices had (Piper's come out at full scale,
    up to 7 dB louder, and the voice changer's effects then clipped them)."""
    rms = float(np.sqrt(np.mean(mono ** 2))) if len(mono) else 0.0
    if rms < 1e-6:
        return mono
    gain = min(TARGET_RMS / rms, PEAK / max(float(np.abs(mono).max()), 1e-6))
    return (mono * gain).astype(np.float32)


def voice_id(language: str) -> str:
    return PREFIX + language


def reader_command() -> tuple[list[str], Path] | None:
    """The AI voices add-on's reader (argv, its folder), or None when that add-on
    isn't installed. Raises RuntimeError for one from before the reader came."""
    from soundboard.addons import modules as mods
    from soundboard.speech.aivoice import MODULE_ID
    m = next((m for m in mods.discover() if m.id == MODULE_ID and not m.error), None)
    if m is None or not m.installed:
        return None
    if not (m.path / "reader.py").is_file():
        raise RuntimeError("the language voices need the newest AI voices: press Update AI "
                           "voices under More options on the AI voices tab")
    return m.resolved_command()[:1] + [str(m.path / "reader.py")], m.path


class PiperReader:
    """Reads lines with the language voices, one at a time (synth is called from the
    Speaker's thread)."""

    def __init__(self, command=reader_command):
        self._command = command
        self._proc: subprocess.Popen | None = None
        self._out: queue.Queue[str | None] = queue.Queue()
        self._lock = threading.Lock()
        self._used = 0.0
        self._idle: threading.Thread | None = None

    def _start(self):
        if self._proc is not None and self._proc.poll() is None:
            return
        found = self._command()
        if found is None:
            raise RuntimeError("the language voices need AI voices: install AI voices on "
                               "the AI voices tab")
        argv, cwd = found
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        self._proc = subprocess.Popen(
            argv, cwd=str(cwd), env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._out = queue.Queue()
        threading.Thread(target=_pump, args=(self._proc.stdout, self._out),
                         name="piper-stdout", daemon=True).start()
        ans = self._answer(START_TIMEOUT_S)
        if not ans.get("ready"):
            self.close()
            raise RuntimeError(ans.get("error") or "the language voices didn't start")
        log.info("language voice reader ready")
        self._used = time.monotonic()
        if self._idle is None:
            self._idle = threading.Thread(target=self._idle_loop, name="piper-idle",
                                          daemon=True)
            self._idle.start()

    def _answer(self, timeout: float) -> dict:
        try:
            line = self._out.get(timeout=timeout)
        except queue.Empty:
            log.warning("the language voice reader didn't answer in %.0f s", timeout)
            self.close(kill=True)
            raise RuntimeError("the language voice stopped answering. It restarts on its "
                               "own; try again.") from None
        if line is None:
            self.close(kill=True)
            raise RuntimeError("the language voice reader stopped")
        try:
            ans = json.loads(line)
        except ValueError:
            ans = None
        return ans if isinstance(ans, dict) else {"error": line.strip()[:200]}

    def synth(self, text: str, model: Path, rate: int = 0) -> tuple[np.ndarray, int]:
        """`text` read by the voice in `model`: (float32 mono, sample rate). `rate`
        is -10..10 like Windows'."""
        text = " ".join(text.split())
        if not text:
            return np.zeros(0, np.float32), TTS_RATE
        fd, path = tempfile.mkstemp(prefix="sb-piper-", suffix=".wav")
        os.close(fd)
        try:
            with self._lock:
                self._start()
                p = self._proc
                assert p is not None and p.stdin is not None
                p.stdin.write(json.dumps({
                    "text": text, "model": str(model), "out": path,
                    "speed": 2 ** (max(-10, min(10, rate)) / 10)}) + "\n")
                p.stdin.flush()
                ans = self._answer(LINE_TIMEOUT_S)
                self._used = time.monotonic()
            if not ans.get("ok"):
                raise RuntimeError(ans.get("error") or "the language voice couldn't read it")
            data, sr = sf.read(path, dtype="float32", always_2d=False)
            return level(np.ascontiguousarray(data, np.float32)), int(sr)
        finally:
            _remove(path)

    def _idle_loop(self):
        while True:
            time.sleep(IDLE_CHECK_S)
            with self._lock:
                if self._proc is not None and time.monotonic() - self._used >= IDLE_CLOSE_S:
                    log.info("language voice reader unused for %.0f min: closed",
                             IDLE_CLOSE_S / 60)
                    self.close()
                if self._proc is None:
                    self._idle = None
                    return

    def close(self, kill: bool = False):
        p, self._proc = self._proc, None
        if p is None:
            return
        try:
            if kill:
                raise OSError
            assert p.stdin is not None
            p.stdin.close()
            p.wait(timeout=2)
        except Exception:  # noqa: BLE001
            p.kill()
