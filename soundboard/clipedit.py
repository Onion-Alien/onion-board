"""The Apps tab's clip editor, without the window: a rolling buffer of the last
LISTEN_S seconds a program played (with a waveform summary kept as it fills), and
the edits made to a take of it (cut, copy, paste, fade, louder / quieter,
reverse) with undo. Audio is (n, 2) float32 at engine.SR throughout; positions
are frames. The widget is soundboard.ui.clipeditor."""
from __future__ import annotations

import threading

import numpy as np

from soundboard.engine import SR
from soundboard.library import MAX_SECONDS

LISTEN_S = 60            # how far back a listening card can go
BIN = 240                # frames per waveform column (5 ms): fine enough to zoom into
UNDO_BYTES = 300 << 20   # undo steps kept, by the memory their audio takes
FADE_MIN_S = 0.005       # a click-free edge for cuts and pastes
MAX_FRAMES = int(MAX_SECONDS * SR)   # a take never grows past what a sound may be


def bin_peaks(data: np.ndarray, size: int = BIN) -> np.ndarray:
    """The loudest sample in each `size`-frame slice of (n, 2) audio, 0..1 (the
    last slice may be short)."""
    n = len(data)
    if not n:
        return np.zeros(0, np.float32)
    whole = n // size * size
    # max and -min per slice: ~40x faster than abs() over a minute of audio (no
    # 23 MB temporary), which is what every edit redraws from
    r = np.ascontiguousarray(data[:whole]).reshape(whole // size, -1)
    out = np.maximum(r.max(axis=1), -r.min(axis=1)) if whole else np.zeros(0, np.float32)
    if whole < n:
        out = np.append(out, np.abs(data[whole:]).max())
    return np.clip(out.astype(np.float32), 0.0, 1.0)


class LiveBuffer:
    """The last `seconds` of a program's sound, kept as it plays. push() runs on
    the capture thread; snapshot() / peaks() on the UI thread. Only whole BIN-frame
    slices are kept, so the audio and its waveform always line up."""

    def __init__(self, seconds: float = LISTEN_S):
        self.cols = max(1, int(seconds * SR) // BIN)
        self.audio = np.zeros((self.cols * BIN, 2), np.float32)
        self.wave = np.zeros(self.cols, np.float32)
        self.col = 0          # the next column written
        self.filled = 0       # columns holding sound
        self.total = 0        # frames ever kept (the clock the view scrolls by)
        self._part = np.zeros((0, 2), np.float32)   # less than a BIN, waiting for more
        self._lock = threading.Lock()

    def push(self, x: np.ndarray):
        x = np.asarray(x, np.float32)
        if x.ndim == 1:
            x = np.stack([x, x], 1)
        elif x.shape[1] == 1:
            x = np.repeat(x, 2, axis=1)
        with self._lock:
            if len(self._part):
                x = np.concatenate([self._part, x[:, :2]])
            whole = len(x) // BIN * BIN
            self._part = x[whole:].copy()
            if not whole:
                return
            x = x[:whole]
            if len(x) > len(self.audio):
                x = x[-len(self.audio):]
            k = len(x) // BIN
            cols = (self.col + np.arange(k)) % self.cols
            self.audio.reshape(self.cols, BIN, 2)[cols] = x.reshape(k, BIN, 2)
            self.wave[cols] = np.clip(np.abs(x).max(axis=1).reshape(k, BIN).max(axis=1), 0, 1)
            self.col = (self.col + k) % self.cols
            self.filled = min(self.filled + k, self.cols)
            self.total += k * BIN

    def _order(self) -> np.ndarray:
        """Column indices, oldest first."""
        start = (self.col - self.filled) % self.cols
        return (start + np.arange(self.filled)) % self.cols

    def peaks(self) -> tuple[np.ndarray, int]:
        """(waveform columns oldest first, total frames so far)."""
        with self._lock:
            return self.wave[self._order()], self.total

    def snapshot(self) -> np.ndarray:
        """Everything held, oldest first, as a new array."""
        with self._lock:
            return self.audio.reshape(self.cols, BIN, 2)[self._order()].reshape(-1, 2)

    @property
    def seconds(self) -> float:
        return self.filled * BIN / SR

    def clear(self):
        with self._lock:
            self.col = self.filled = 0
            self._part = np.zeros((0, 2), np.float32)


def _ramp(n: int, up: bool) -> np.ndarray:
    r = np.linspace(0.0, 1.0, n, dtype=np.float32) if up else np.linspace(1.0, 0.0, n,
                                                                            dtype=np.float32)
    return r[:, None]


def smooth_join(data: np.ndarray, at: int, limit: int | None = None) -> np.ndarray:
    """A few ms of fade either side of `at` (where a cut or paste joined two bits),
    so the join doesn't click. `limit` caps it (a short pasted bit isn't all fade)."""
    n = min(int(FADE_MIN_S * SR), at, len(data) - at)
    if limit is not None:
        n = min(n, limit)
    if n > 1:
        data[at - n:at] *= _ramp(n, False)
        data[at:at + n] *= _ramp(n, True)
    return data


class Take:
    """A frozen piece of audio being edited: `data`, the selection `a`..`b` (frames;
    a == b is just a cursor, where a paste goes), and undo / redo. Every edit
    returns True if it changed something."""

    def __init__(self, data: np.ndarray):
        self.data = np.ascontiguousarray(data, np.float32)
        self.a = self.b = 0
        self.edited = False   # something was done to it since it was taken
        self._undo: list[tuple[np.ndarray, int, int, bool]] = []
        self._redo: list[tuple[np.ndarray, int, int, bool]] = []

    # -------------------------------------------------------------- selection
    def __len__(self) -> int:
        return len(self.data)

    @property
    def has_selection(self) -> bool:
        return self.b > self.a

    def select(self, a: int, b: int):
        a, b = sorted((int(a), int(b)))
        n = len(self.data)
        self.a, self.b = min(max(a, 0), n), min(max(b, 0), n)

    def select_all(self):
        self.select(0, len(self.data))

    def span(self) -> tuple[int, int]:
        """The selection, or the whole take when nothing is selected."""
        return (self.a, self.b) if self.has_selection else (0, len(self.data))

    def selected(self) -> np.ndarray:
        a, b = self.span()
        return self.data[a:b].copy()

    # -------------------------------------------------------------- undo
    def _push(self):
        self._undo.append((self.data, self.a, self.b, self.edited))
        self._redo.clear()
        used = sum(d.nbytes for d, *_ in self._undo)
        while len(self._undo) > 1 and used > UNDO_BYTES:
            used -= self._undo.pop(0)[0].nbytes

    def _set(self, data: np.ndarray, a: int, b: int):
        self.data = data
        self.edited = True
        self.select(a, b)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append((self.data, self.a, self.b, self.edited))
        self.data, a, b, self.edited = self._undo.pop()
        self.select(a, b)
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append((self.data, self.a, self.b, self.edited))
        self.data, a, b, self.edited = self._redo.pop()
        self.select(a, b)
        return True

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    # -------------------------------------------------------------- edits
    def delete(self) -> bool:
        """Take the selection out; the bits either side close up."""
        if not self.has_selection or (self.a == 0 and self.b == len(self.data)):
            return False
        self._push()
        a, b = self.a, self.b
        data = np.concatenate([self.data[:a], self.data[b:]])
        self._set(smooth_join(data, a), a, a)
        return True

    def crop(self) -> bool:
        """Keep only the selection."""
        if not self.has_selection or (self.a == 0 and self.b == len(self.data)):
            return False
        self._push()
        self._set(self.data[self.a:self.b].copy(), 0, self.b - self.a)
        return True

    def paste(self, piece: np.ndarray) -> bool:
        """Put `piece` at the cursor, or in place of the selection. The pasted part
        ends up selected. Never grows the take past a sound's length cap."""
        if piece is None or not len(piece):
            return False
        a, b = (self.a, self.b) if self.has_selection else (self.a, self.a)
        room = MAX_FRAMES - (len(self.data) - (b - a))
        piece = np.asarray(piece, np.float32)[:max(room, 0)]
        if not len(piece):
            return False
        self._push()
        data = np.concatenate([self.data[:a], piece, self.data[b:]])
        edge = len(piece) // 4
        smooth_join(data, a, edge)
        smooth_join(data, a + len(piece), edge)
        self._set(data, a, a + len(piece))
        return True

    def _apply(self, fn) -> bool:
        a, b = self.span()
        if b <= a:
            return False
        self._push()
        data = self.data.copy()
        data[a:b] = fn(data[a:b])
        self._set(data, self.a, self.b)
        return True

    def fade_in(self) -> bool:
        return self._apply(lambda x: x * _ramp(len(x), True))

    def fade_out(self) -> bool:
        return self._apply(lambda x: x * _ramp(len(x), False))

    def gain(self, factor: float) -> bool:
        """Louder (> 1) or quieter (< 1); never past full scale."""
        return self._apply(lambda x: np.clip(x * float(factor), -1.0, 1.0))

    def reverse(self) -> bool:
        return self._apply(lambda x: x[::-1].copy())

    def silence(self) -> bool:
        return self._apply(lambda x: np.zeros_like(x))

    def normalize(self, peak: float = 0.89) -> bool:
        """As loud as it can go without clipping (about -1 dBFS)."""
        a, b = self.span()
        top = float(np.abs(self.data[a:b]).max()) if b > a else 0.0
        if top < 1e-4:
            return False
        return self.gain(peak / top)
