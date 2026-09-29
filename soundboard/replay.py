"""Instant replay: keeps the last N seconds of everything this PC plays (your friends
in Discord, the game, a video) and saves them as a new pad on a hotkey, for the
"clip that!" moment after someone says something funny.

It's Windows' process loopback (soundboard.appaudio) in "everything except this
process" mode, so Onion Board's own sounds and radio aren't in the clip. The audio is
only held in memory (a ring buffer, soundboard.recorder.Recorder) and nothing is
kept until the hotkey is pressed. It only runs while the hotkey is set.
"""
from __future__ import annotations

import logging
import os
import threading

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

from soundboard import appaudio
from soundboard.library import trim_silence
from soundboard.recorder import Recorder

log = logging.getLogger(__name__)

RETRY_MS = 3000        # a capture that ended (the output device changed) starts again


class InstantReplay(QObject):
    """`set_enabled(True)` starts listening (on a thread: Windows can take a moment);
    `clip()` returns the last `seconds`, silence at the ends trimmed. `error` says
    why it isn't running, `state_changed` fires when that changes."""
    state_changed = Signal()
    _started = Signal(object, str)   # (capture or None, error), from the start thread

    def __init__(self, seconds: int = 30, capture_cls=None):
        super().__init__()
        self.seconds = int(seconds)
        self.error = ""
        self._capture_cls = capture_cls or appaudio.AppCapture
        self._rec = Recorder(seconds=self.seconds)
        self._cap = None
        self._enabled = False
        self._starting = False
        self._lock = threading.Lock()
        self._timer = QTimer(self)
        self._timer.setInterval(RETRY_MS)
        self._timer.timeout.connect(self._check)
        self._started.connect(self._on_started)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def running(self) -> bool:
        return self._cap is not None and self._cap.running

    def set_enabled(self, on: bool, seconds: int | None = None):
        if seconds is not None and int(seconds) != self.seconds:
            self.seconds = int(seconds)
            with self._lock:
                self._rec = Recorder(seconds=self.seconds)
        if on == self._enabled:
            return
        self._enabled = on
        if on:
            ok, why = appaudio.supported()
            if not ok:
                self.error = why
                self.state_changed.emit()
                return
            self._start()
            self._timer.start()
        else:
            self._timer.stop()
            self._stop()
            self.error = ""
            with self._lock:
                self._rec.clear_replay()
            self.state_changed.emit()

    def clip(self) -> np.ndarray:
        with self._lock:
            data = self._rec.last()
        return trim_silence(data)

    def stop(self):
        """App exit."""
        self._enabled = False
        self._timer.stop()
        self._stop()

    # -- capture
    def _push(self, x: np.ndarray):   # the capture thread
        with self._lock:
            self._rec.push(x)

    def _start(self):
        if self._starting:
            return
        self._starting = True

        def run():
            cap = self._capture_cls(os.getpid(), self._push, include_tree=False,
                                    name="instant replay")
            ok = cap.start()
            self._started.emit(cap if ok else None, "" if ok else (cap.error or "failed"))
        threading.Thread(target=run, name="replay-start", daemon=True).start()

    def _on_started(self, cap, error: str):
        self._starting = False
        if not self._enabled:   # switched off while it was starting
            if cap is not None:
                cap.stop()
            return
        self._cap = cap
        if error != self.error:
            if error:
                log.warning("instant replay: %s", error)
            self.error = error
        self.state_changed.emit()

    def _stop(self):
        cap, self._cap = self._cap, None
        if cap is not None:
            threading.Thread(target=cap.stop, name="replay-stop", daemon=True).start()

    def _check(self):
        if self._enabled and not self._starting and not self.running:
            self._stop()
            self._start()
