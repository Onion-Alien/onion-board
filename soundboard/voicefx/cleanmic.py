"""Clean mic: background noise (fans, keyboards, a TV) taken out of your mic.

RNNoise (BSD-3, licenses/RNNoise-BSD-3.txt) does it: a small neural network that keeps
the voice and drops the rest, 48 kHz, 10 ms at a time, about 5% of one CPU core. Its
rnnoise.dll comes from scripts/buildtools/fetch_rnnoise.py: build.ps1 bundles it as the
frozen app's rnnoise folder; a source run finds it where that script leaves it
(build/rnnoise). Without it Clean mic just isn't offered (`available()`).

Strong is DeepFilterNet (voicefx.deepfilter), an optional download: the Cleaner hands
the mic to it once it's there and running, and cleans with RNNoise (Normal) while it
starts or after it has stopped (`note` says why).

Whichever cleans, `Tidy` then filters out rumble under 80 Hz and (Normal, Strong) turns
the mic down between your words: the network keeps any voice, a TV's or a quiet one
across the room too, and a gate that learns your room's level drops those while you're
quiet. No delay of its own.

The card's ⚙ settings, laid out like a voice chat app's: Input volume (the mic turned up
or down before any of it), Input sensitivity (the gate's own threshold instead of the
learned one), the strength or "off" (no network: only the rest), and automatic gain
control (`Agc`, last: your voice held at one loudness). All of it is the mic's alone:
the board's sounds are mixed in after the voice chain, never through it.

The voice chain runs a `Cleaner` first on every mic block (VoiceChain.set_clean), so
the voice changer, AI voices and speech recognition all get the cleaned mic.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import threading
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

RATE = 48000
FRAME = 480          # RNNoise's frame: 10 ms at 48 kHz
DELAY = 960          # its output trails its input by two frames (measured: 20 ms)
SCALE = 32768.0      # it works on 16-bit sample values held in floats
STRENGTHS = ("light", "normal", "strong")
LEVELS = ("off",) + STRENGTHS   # Noise suppression's choices: "off" runs no network
DEFAULT = "normal"
VOLUME_MAX = 200     # Input volume, % (100: as it is)
SENSE_LO = -100      # Input sensitivity's dB range when it isn't automatic
SENSE_DEFAULT = -50
# the presets: what each sets (Input sensitivity's dB only counts when it isn't automatic)
PRESETS = {
    "normal": {"strength": "normal", "volume": 100, "auto_sense": True, "agc": False},
    "loud": {"strength": "strong", "volume": 100, "auto_sense": False, "sense_db": -50,
             "agc": False},
    "voice": {"strength": "strong", "volume": 100, "auto_sense": False, "sense_db": -40,
              "agc": True},
    "quiet": {"strength": "light", "volume": 100, "auto_sense": True, "agc": False},
}
LIGHT_DRY = 10 ** (-12 / 20)   # Light: the mic as it was, 12 dB under the cleaned one
RUMBLE_HZ = 80                 # Tidy's high-pass
NAME = "rnnoise.dll"
DIR = (Path(sys._MEIPASS) / "rnnoise" if hasattr(sys, "_MEIPASS")   # pyright: ignore[reportAttributeAccessIssue]
       else Path(__file__).resolve().parents[2] / "build" / "rnnoise")

_lock = threading.Lock()
_lib: ctypes.CDLL | None = None
_tried = False
_why = ""


def _load() -> ctypes.CDLL | None:
    """rnnoise.dll, loaded once (any thread); None when it's missing or won't load."""
    global _lib, _tried, _why
    if _tried:
        return _lib
    with _lock:
        if _tried:
            return _lib
        path = DIR / NAME
        try:
            if not path.is_file():
                raise OSError(f"{path} is missing")
            lib = ctypes.CDLL(str(path))
            lib.rnnoise_create.restype = ctypes.c_void_p
            lib.rnnoise_create.argtypes = [ctypes.c_void_p]
            lib.rnnoise_destroy.restype = None
            lib.rnnoise_destroy.argtypes = [ctypes.c_void_p]
            lib.rnnoise_process_frame.restype = ctypes.c_float
            lib.rnnoise_process_frame.argtypes = [ctypes.c_void_p,
                                                  ctypes.POINTER(ctypes.c_float),
                                                  ctypes.POINTER(ctypes.c_float)]
            lib.rnnoise_get_frame_size.restype = ctypes.c_int
            if lib.rnnoise_get_frame_size() != FRAME:
                raise OSError("unexpected RNNoise frame size")
            _lib = lib
        except (OSError, AttributeError) as ex:
            _why = str(ex)
            log.info("Clean mic unavailable: %s", ex)
        _tried = True
    return _lib


def available() -> bool:
    """RNNoise is here and loads: Clean mic can be offered."""
    return _load() is not None


def why() -> str:
    """Why it isn't available (for the log), or ""."""
    _load()
    return _why


class Tidy:
    """After the network, at 48 kHz: rumble under RUMBLE_HZ filtered out, and with
    `gate` on, a downward expander that turns the mic down 18 dB between your words.
    It decides every 2.5 ms, stays open 0.2 s after you stop, and takes the room's
    level as the quietest moment of the last 1.5 s, so a noisy room is learned at once
    and followed when it changes. (Voice changer's old Clean up my mic, at its default.)
    `sense` (dB, Input sensitivity) sets where it opens instead: closed again 4 dB under.
    `peak_db` (the loudest 2.5 ms of the last block), `open_db` (where it opens now) and
    `talking` (that block was over it) are kept with the gate off too: AGC and the
    card's sensitivity bar read them."""

    SUB = 120            # samples a decision: 2.5 ms
    HOLD_S = 0.2
    FLOOR_S = 1.5
    CLOSED = 10 ** (-18 / 20)

    def __init__(self, gate: bool = True, sense: float | None = None):
        from soundboard.audio.dsp import SmoothSos, butter
        self.gate = gate
        self.sense = sense
        self._hp = SmoothSos()
        self._sos = butter(2, RUMBLE_HZ, btype="high", fs=RATE)
        self.floor_db = -70.0
        self.mins: list[tuple[float, float]] = []   # (seconds, quietest dB) a block
        self.open = False
        self.held = 0.0
        self.g = 1.0
        self.peak_db = -120.0
        self.open_db = -60.0

    @property
    def talking(self) -> bool:
        return self.peak_db > self.open_db

    def run(self, y: np.ndarray) -> np.ndarray:
        if not len(y):
            return y
        y = self._hp.run(y, self._sos).astype(np.float32, copy=False)
        return self._gate(y)

    def _gate(self, x: np.ndarray) -> np.ndarray:
        n = len(x)
        pieces = max(1, n // self.SUB)
        edges = np.linspace(0, n, pieces + 1).astype(int)
        lv = np.array([np.sqrt(np.mean(x[a:b] ** 2) + 1e-12)
                       for a, b in zip(edges[:-1], edges[1:])])
        db = (20 * np.log10(lv)).tolist()
        self.peak_db = max(db)
        self.mins.append((n / RATE, max(min(db), -90.0)))
        span = sum(t for t, _ in self.mins)
        while len(self.mins) > 1 and span - self.mins[0][0] >= self.FLOOR_S:
            span -= self.mins.pop(0)[0]
        self.floor_db = min(min(m for _, m in self.mins), -38.0)
        if self.sense is None:
            open_at, close_at = max(self.floor_db + 9, -60), max(self.floor_db + 5, -64)
        else:
            open_at, close_at = self.sense, self.sense - 4
        self.open_db = open_at
        gate = self.gate
        gains = np.empty(pieces + 1)
        gains[0] = g = self.g
        for i, d in enumerate(db):   # (plain floats: numpy scalars cost more here)
            piece = (edges[i + 1] - edges[i]) / RATE
            if d > open_at:
                self.open, self.held = True, 0.0
            elif self.open and d < close_at:
                self.held += piece
                if self.held > self.HOLD_S:
                    self.open = False
            target = 1.0 if self.open or not gate else self.CLOSED
            tau = 0.002 if target > g else 0.06
            g = target + (g - target) * float(np.exp(-piece / tau))
            gains[i + 1] = g
        knots = np.concatenate([[-1], edges[1:] - 1])
        self.g = float(g)
        return (x * np.interp(np.arange(n), knots, gains)).astype(np.float32)


class Agc:
    """Automatic gain control, last, on the voice alone: while you talk (`Tidy.open`)
    its level is followed over ~0.4 s and turned towards TARGET_DB, at most MAX_UP dB up
    or MAX_DOWN down; between words the gain holds, so the room isn't pulled up. Peaks
    never go over PEAK."""

    TARGET_DB = -20.0     # a 2.5 ms piece's loudness while talking, as Tidy measures it
    MAX_UP, MAX_DOWN = 18.0, 12.0
    PEAK = 10 ** (-1 / 20)
    FOLLOW_S, UP_S, DOWN_S = 0.4, 1.0, 0.3

    def __init__(self):
        self.level_db: float | None = None   # your voice's loudness, once you've talked
        self.gain_db = 0.0
        self._g = 1.0

    def run(self, y: np.ndarray, talking: bool, piece_db: float) -> np.ndarray:
        n = len(y)
        if not n:
            return y
        dt = n / RATE
        if talking:
            lv = piece_db if self.level_db is None else self.level_db
            self.level_db = lv + (piece_db - lv) * (1 - float(np.exp(-dt / self.FOLLOW_S)))
            want = min(max(self.TARGET_DB - self.level_db, -self.MAX_DOWN), self.MAX_UP)
            tau = self.UP_S if want > self.gain_db else self.DOWN_S
            self.gain_db = want + (self.gain_db - want) * float(np.exp(-dt / tau))
        g = 10 ** (self.gain_db / 20)
        peak = float(np.max(np.abs(y)))
        if peak * g > self.PEAK:   # never over the top: down at once
            g = self.PEAK / peak
            self.gain_db = 20 * float(np.log10(g))
        out = y * np.linspace(self._g, g, n, dtype=np.float32)
        top = float(np.max(np.abs(out)))
        if top > self.PEAK:   # (the ramp down from a louder gain: not over it either)
            out *= np.float32(self.PEAK / top)
            g = min(g, self._g * self.PEAK / top)
            self.gain_db = min(self.gain_db, 20 * float(np.log10(max(g, 1e-6))))
        self._g = g
        return out.astype(np.float32, copy=False)


def clean_settings(raw) -> dict:
    """The saved settings, damaged values replaced: {"on": bool, "strength": "off" |
    "light" | "normal" | "strong", "volume": 0-200 (%), "auto_sense": bool, "sense_db":
    -100-0, "agc": bool}. (Versions before the ⚙ saved only on and strength, and drop
    the rest; "off" there reads as Normal.)"""
    raw = raw if isinstance(raw, dict) else {}
    s = raw.get("strength")

    def num(key, lo, hi, default):
        v = raw.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not np.isfinite(v):
            return default
        return min(max(round(v), lo), hi)
    return {"on": raw.get("on") is True, "strength": s if s in LEVELS else DEFAULT,
            "volume": num("volume", 0, VOLUME_MAX, 100),
            "auto_sense": raw.get("auto_sense") is not False,
            "sense_db": num("sense_db", SENSE_LO, 0, SENSE_DEFAULT),
            "agc": raw.get("agc") is True}


def preset_of(s: dict) -> str:
    """The preset these settings are, or "custom"."""
    for key, p in PRESETS.items():
        if all(s.get(k) == v for k, v in p.items()
               if k != "sense_db" or not p["auto_sense"]):
            return key
    return "custom"


def options(s: dict) -> dict:
    """What the Cleaner needs of the settings, besides the strength."""
    return {"volume": s.get("volume", 100), "sense": None if s.get("auto_sense", True)
            else s.get("sense_db", SENSE_DEFAULT), "agc": bool(s.get("agc"))}


class Cleaner:
    """One mic's noise remover. `process(mono)` (the audio thread) returns a block of
    the same length, the cleaned voice `latency()` seconds late. At another rate than
    48 kHz the mic is resampled there and back. Raises RuntimeError when RNNoise isn't
    available or won't start. `opts`: `options()` of the card's settings."""

    def __init__(self, rate: int, strength: str = DEFAULT, opts: dict | None = None):
        lib = _load()
        if lib is None:
            raise RuntimeError(f"RNNoise isn't available: {_why}")
        state = lib.rnnoise_create(None)
        if not state:
            raise RuntimeError("RNNoise didn't start")
        self._lib, self._state = lib, state
        self.rate = int(rate)
        self.strength = DEFAULT
        self._deep = None   # voicefx.deepfilter.Stream while Strong is picked
        self.note = ""      # why Strong stopped (RNNoise cleans instead), for the card
        self._tidy = Tidy()
        self._agc: Agc | None = None
        self._volume = 1.0
        self._sense: float | None = None
        self.set_options(opts or {})
        self.set_strength(strength)
        self._frame = np.zeros(FRAME, np.float32)
        self._ptr = self._frame.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        self._pending = np.zeros(0, np.float32)    # 48 kHz samples short of a frame
        self._dry = np.zeros(DELAY, np.float32)   # the input the output trails (Light)
        self._up = self._down = None
        prime = FRAME
        if self.rate != RATE:
            import soxr
            # low quality: still flat to ~17 kHz, plenty for a voice, and next to no
            # delay (~0.5 ms there and back; medium and high added 20-30 ms)
            self._up = soxr.ResampleStream(self.rate, RATE, 1, dtype="float32", quality="LQ")
            self._down = soxr.ResampleStream(RATE, self.rate, 1, dtype="float32", quality="LQ")
            prime = int(np.ceil(FRAME * self.rate / RATE)) + 64   # and their slack
        # what goes out, at the mic's rate: started with silence so a block can always
        # be answered in full while the next frame fills
        self._out = np.zeros(prime, np.float32)
        self._prime = prime
        self._late = 0     # silence added since, when the resamplers were slow to start
        self.level = 0.0   # the cleaned voice's peak, for the tab's meter (any thread reads)

    def set_options(self, opts: dict):
        """Input volume (%), Input sensitivity (dB, None: automatic), AGC on or off."""
        self._volume = min(max(float(opts.get("volume", 100)), 0.0), VOLUME_MAX) / 100
        self._sense = self._tidy.sense = opts.get("sense")
        if opts.get("agc") and self._agc is None:
            self._agc = Agc()
        elif not opts.get("agc"):
            self._agc = None
        self._set_gate()

    def _set_gate(self):
        # (Light keeps some of the room, unless a sensitivity is set)
        self._tidy.gate = self.strength != "light" or self._sense is not None

    @property
    def gate_db(self) -> tuple[float, float]:
        """(the loudest moment of the last block, where the gate opens), in dB: the
        sensitivity bar's (any thread reads)."""
        t = self._tidy
        return t.peak_db, t.open_db

    def set_strength(self, strength: str):
        self.strength = strength if strength in LEVELS else DEFAULT
        self._mix = LIGHT_DRY if self.strength == "light" else 0.0
        self._set_gate()
        if self.strength == "strong" and self._deep is None:
            from soundboard.voicefx import deepfilter
            self.note = ""
            self._deep = deepfilter.Stream()
        elif self.strength != "strong" and self._deep is not None:
            self._deep.close()
            self._deep = None

    def latency(self) -> float:
        deep = self._deep
        own = (deep.latency() if deep is not None and deep.ready
               else 0.0 if self.strength == "off" else DELAY / RATE)
        return own + (self._prime + self._late) / self.rate

    def process(self, mono: np.ndarray) -> np.ndarray:
        n = len(mono)
        x = np.asarray(mono, np.float32)
        if self._volume != 1.0:
            x = x * np.float32(self._volume)
        if self._up is not None:
            x = self._up.resample_chunk(x)
        if self.strength == "off":   # no network: only the gate and the rest
            if len(self._pending):
                x = np.concatenate([self._pending, x])
                self._pending = np.zeros(0, np.float32)
            return self._send(x, n)
        deep = self._deep
        if deep is not None:
            if len(self._pending) and deep.ready:
                x = np.concatenate([self._pending, x])
                self._pending = np.zeros(0, np.float32)
            y = deep.feed(x)
            if deep.error:   # Strong has stopped: Normal from now on
                self.note = deep.error
                deep.close()
                self._deep = None
            elif y is not None:
                return self._send(y, n)
        if len(self._pending):
            x = np.concatenate([self._pending, x])
        whole = len(x) // FRAME * FRAME
        self._pending = x[whole:].copy()
        if whole:
            y = np.empty(whole, np.float32)
            frame, ptr, state, run = self._frame, self._ptr, self._state, \
                self._lib.rnnoise_process_frame
            mix = self._mix
            for i in range(0, whole, FRAME):
                frame[:] = x[i:i + FRAME]
                frame *= SCALE
                run(state, ptr, ptr)
                out = y[i:i + FRAME]
                np.multiply(frame, 1.0 / SCALE, out=out)
                if mix:   # Light: some of the mic as it was, lined up with the output
                    out += self._dry[:FRAME] * np.float32(mix)
                self._dry = np.concatenate([self._dry[FRAME:], x[i:i + FRAME]])
            return self._send(y, n)
        return self._send(np.zeros(0, np.float32), n)

    def _send(self, y: np.ndarray, n: int) -> np.ndarray:
        """Cleaned 48 kHz samples in, `n` at the mic's rate out."""
        if len(y):
            y = self._tidy.run(y)
            agc = self._agc
            if agc is not None:
                y = agc.run(y, self._tidy.talking, self._tidy.peak_db)
            if self._down is not None:
                y = self._down.resample_chunk(y)
            self._out = np.concatenate([self._out, y])
        got = self._out
        if len(got) >= n:
            res, self._out = got[:n], got[n:]
        else:   # (the resamplers held back more than the slack: that much later for good)
            self._late += n - len(got)
            res = np.concatenate([np.zeros(n - len(got), np.float32), got])
            self._out = np.zeros(0, np.float32)
        if len(res):
            self.level = float(np.max(np.abs(res)))
        return res

    def close(self):
        if self._deep is not None:
            self._deep.close()
            self._deep = None
        state, self._state = self._state, None
        if state:
            self._lib.rnnoise_destroy(state)

    def __del__(self):
        try:
            self.close()
        except Exception:  # noqa: BLE001 - at interpreter exit the library may be gone
            pass


def clean_clip(mono: np.ndarray, rate: int, strength: str = DEFAULT,
               opts: dict | None = None) -> np.ndarray:
    """A whole recording cleaned (Hear the difference's After), lined up with the
    recording and the same length. Off the UI thread: ~5% of the clip's length (Strong:
    about a third; it raises RuntimeError when it can't run)."""
    opts = opts or {}
    m = np.asarray(mono, np.float32)
    if rate != RATE:
        import soxr
        m = soxr.resample(m, rate, RATE).astype(np.float32)
    if strength == "strong":
        from soundboard.voicefx import deepfilter
        m = m * np.float32(min(max(float(opts.get("volume", 100)), 0.0), VOLUME_MAX) / 100)
        tidy, out = Tidy(sense=opts.get("sense")), deepfilter.clean_clip(m)
        agc = Agc() if opts.get("agc") else None
        parts = []
        for c in np.array_split(out, max(1, len(out) // 4800)):
            c = tidy.run(c)
            parts.append(agc.run(c, tidy.talking, tidy.peak_db) if agc is not None else c)
        out = np.concatenate(parts)
        if rate != RATE:
            import soxr
            out = soxr.resample(out, RATE, rate).astype(np.float32)
        n = len(mono)
        if len(out) < n:
            out = np.concatenate([out, np.zeros(n - len(out), np.float32)])
        return out[:n]
    c = Cleaner(RATE, strength, opts)
    try:
        lag = (0 if strength == "off" else DELAY) + c._prime
        m = np.concatenate([m, np.zeros(lag, np.float32)])
        out = np.concatenate([c.process(m[i:i + 4800]) for i in range(0, len(m), 4800)])
        out = out[lag:]
    finally:
        c.close()
    if rate != RATE:
        import soxr
        out = soxr.resample(out, RATE, rate).astype(np.float32)
    n = len(mono)
    return out[:n] if len(out) >= n else np.concatenate([out, np.zeros(n - len(out), np.float32)])
