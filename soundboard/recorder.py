"""A clip recorder for a live stream (the Radio tab): a rolling replay buffer
of the last CLIP_S seconds, plus a manual recording spooled to disk. Clips are
added to the Sounds tab as ordinary pads."""
from __future__ import annotations

import logging
import threading

import numpy as np
import soundfile as sf

from soundboard.engine import SR
from soundboard import library
from soundboard.library import MAX_SECONDS

log = logging.getLogger(__name__)

CLIP_S = 15            # "clip the last N seconds" length


class Recorder:
    """Keeps a rolling CLIP_S-second replay buffer, plus a manual recording.

    The manual recording is spooled to a 16-bit WAV on disk as it happens instead
    of being held in RAM: at the 15-minute cap that is 172 MB on disk versus
    345 MB of float32 chunks *plus* another 345 MB to concatenate them. If the
    spool file can't be opened it falls back to memory."""

    def __init__(self, spool_path=None):
        self.replay = np.zeros((CLIP_S * SR, 2), np.float32)
        self.w = 0
        self.filled = 0
        # looked up now, not at import, so tests that re-point APP_DIR are honoured
        self.spool_path = spool_path or library.APP_DIR / "recording.tmp.wav"
        self._spool: sf.SoundFile | None = None
        self._mem: list[np.ndarray] | None = None
        self._recording = False
        self.rec_frames = 0
        self._lock = threading.RLock()   # push() runs on an audio thread

    def push(self, x: np.ndarray):
        with self._lock:
            self._push(x)

    def _push(self, x: np.ndarray):
        n = len(x)
        cap = len(self.replay)
        if n >= cap:
            x, n = x[-cap:], cap
        end = self.w + n
        if end <= cap:
            self.replay[self.w:end] = x
        else:
            k = cap - self.w
            self.replay[self.w:] = x[:k]
            self.replay[:n - k] = x[k:]
        self.w = end % cap
        self.filled = min(self.filled + n, cap)
        if self._recording and self.rec_frames < MAX_SECONDS * SR:
            if self._spool is not None:
                try:
                    self._spool.write(x)
                except Exception:  # noqa: BLE001 - disk full etc.: keep the rest in memory
                    log.warning("recording spool failed; continuing in memory", exc_info=True)
                    self._close_spool()
                    self._mem = [self._read_spool()]
                    self._mem.append(x.copy())
            else:
                self._mem.append(x.copy())
            self.rec_frames += n

    def last(self) -> np.ndarray:
        with self._lock:
            return self._last()

    def _last(self) -> np.ndarray:
        if self.filled < len(self.replay):
            return self.replay[:self.filled].copy()
        return np.concatenate([self.replay[self.w:], self.replay[:self.w]])

    def start(self):
        with self._lock:
            self._start()

    def _start(self):
        self._stop()
        self.rec_frames = 0
        self._recording = True
        try:
            self.spool_path.parent.mkdir(parents=True, exist_ok=True)
            self._spool = sf.SoundFile(str(self.spool_path), "w", SR, 2, subtype="PCM_16")
        except Exception:  # noqa: BLE001
            log.warning("can't open recording spool %s; recording in memory", self.spool_path,
                        exc_info=True)
            self._spool = None
            self._mem = []

    def stop(self) -> np.ndarray:
        """End the recording and return it as (n, 2) float32 (empty if nothing recorded)."""
        with self._lock:
            return self._stop()

    def _stop(self) -> np.ndarray:
        if not self._recording:
            return np.zeros((0, 2), np.float32)
        self._recording = False
        if self._spool is not None:
            self._close_spool()
            data = self._read_spool()
        else:
            mem, self._mem = self._mem or [], None
            data = np.concatenate(mem) if mem else np.zeros((0, 2), np.float32)
        return data

    def _close_spool(self):
        try:
            self._spool.close()
        except Exception:  # noqa: BLE001
            log.debug("closing the spool raised", exc_info=True)
        self._spool = None

    def _read_spool(self) -> np.ndarray:
        try:
            data, _ = sf.read(str(self.spool_path), dtype="float32", always_2d=True)
        except Exception:  # noqa: BLE001
            log.warning("can't read back the recording spool", exc_info=True)
            data = np.zeros((0, 2), np.float32)
        try:
            self.spool_path.unlink(missing_ok=True)
        except OSError:
            pass
        return data

    @property
    def recording(self) -> bool:
        return self._recording


class ArmedRecorder:
    """A recording that waits for sound (the Apps tab's Record).

    Armed, it listens without keeping anything but a short pre-roll; the first
    chunk louder than TRIGGER starts the real recording, pre-roll included, so the
    attack of the sound isn't cut off. push() runs on the capture thread."""

    TRIGGER = 0.003        # peak (about -50 dBFS): above a program's idle hiss
    PREROLL_S = 0.25

    def __init__(self, spool_path):
        self._rec = Recorder(spool_path)
        self._pre: list[np.ndarray] = []
        self._pre_frames = 0
        self._lock = threading.Lock()
        self.triggered = False
        self._stopped = False

    def push(self, x: np.ndarray):
        with self._lock:
            if self._stopped:   # a chunk that raced stop(): must not start a new spool
                return
            if self.triggered:
                self._rec.push(x)
                return
            if len(x) and float(np.max(np.abs(x))) > self.TRIGGER:
                self.triggered = True
                self._rec.start()
                for chunk in self._pre:
                    self._rec.push(chunk)
                self._pre, self._pre_frames = [], 0
                self._rec.push(x)
                return
            self._pre.append(x.copy())
            self._pre_frames += len(x)
            while self._pre and self._pre_frames - len(self._pre[0]) >= self.PREROLL_S * SR:
                self._pre_frames -= len(self._pre.pop(0))

    @property
    def seconds(self) -> float:
        return self._rec.rec_frames / SR if self.triggered else 0.0

    def stop(self) -> np.ndarray:
        """End it and return what was recorded ((n, 2) float32; empty if the sound
        never started)."""
        with self._lock:
            self._stopped = True
            self._pre = []
            return self._rec.stop()
