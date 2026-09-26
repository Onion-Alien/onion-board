"""Real-time audio engine.

Three WASAPI streams, each opened at its device's *native* rate (Windows'
built-in resampler, auto_convert, audibly garbles audio — measured ~70% junk on
VB-Cable — so all rate conversion is done here with soxr instead):

  mic  (input)  -> streaming resampler -> ring buffers -> main / monitor
  browser (48 kHz, pushed from the UI thread) -> resampler -> ring buffers -> main / monitor
  main (output) = sounds + browser (when live) + mic -> virtual cable (what others hear)
  mon  (output) = sounds + browser [+ mic in test mode] -> your headphones

Sounds are stored at SR and resampled (cached) to each output's rate. Every
playing Voice keeps its own position per output, so the two output devices
run on independent clocks without drift or glitches.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

import numpy as np
import sounddevice as sd
import soxr

from eq import EQ

log = logging.getLogger(__name__)

SR = 48000  # library storage rate
CH = 2
FADE_S = 0.010  # fade when a sound is stopped early (no clicks)
STALL_S = 1.5   # a stream whose callback hasn't run for this long is dead: reopen it
RETRY_S = 5.0   # how often to retry a device that failed to open


# --------------------------------------------------------------------------- devices

def _wasapi_index() -> int | None:
    for i, api in enumerate(sd.query_hostapis()):
        if "WASAPI" in api["name"]:
            return i
    return None


def rescan() -> bool:
    """Re-enumerate devices (picks up newly plugged ones). Kills open streams — reopen after.

    sounddevice has no public API for this; _terminate/_initialize are what its own
    tests use. If a future version drops them, the app keeps its current device list."""
    try:
        sd._terminate()
        sd._initialize()
        return True
    except Exception:  # noqa: BLE001
        log.exception("device rescan failed")
        try:
            sd._initialize()
        except Exception:  # noqa: BLE001
            pass
        return False


def list_devices(kind: str) -> list[dict]:
    """WASAPI devices of kind 'input' or 'output' as [{index, name}]."""
    api = _wasapi_index()
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    out = []
    for i, d in enumerate(sd.query_devices()):
        if (api is None or d["hostapi"] == api) and d[key] > 0:
            out.append({"index": i, "name": d["name"]})
    return out


def default_device_name(kind: str) -> str | None:
    api = _wasapi_index()
    if api is None:
        return None
    info = sd.query_hostapis(api)
    idx = info["default_input_device" if kind == "input" else "default_output_device"]
    if idx is None or idx < 0:
        return None
    return sd.query_devices(idx)["name"]


def find_device(kind: str, name: str | None) -> int | None:
    if not name:
        return None
    devs = list_devices(kind)
    for d in devs:
        if d["name"] == name:
            return d["index"]
    for d in devs:  # loose match (device renamed / number changed)
        if name.lower() in d["name"].lower() or d["name"].lower() in name.lower():
            return d["index"]
    return None


# Virtual audio cables (VB-Cable, VB-Cable A/B, Hi-Fi Cable, Voicemeeter, …) show up
# as a playback device ("... Input") paired with a recording device ("... Output").
# Audio played into the first comes out of the second, which apps use as a mic.
VIRTUAL_HINTS = ("cable", "vb-audio", "voicemeeter", "virtual")


def is_virtual(name: str | None) -> bool:
    n = (name or "").lower()
    return any(k in n for k in VIRTUAL_HINTS)


def virtual_mic_for(render_name: str | None) -> str | None:
    """The recording device that carries what's played into `render_name`."""
    if not render_name or not is_virtual(render_name):
        return None
    ins = [d["name"] for d in list_devices("input")]
    for a, b in (("Input", "Output"), ("In ", "Out "), ("Input", "Out")):
        cand = render_name.replace(a, b, 1)
        if cand != render_name and cand in ins:
            return cand
    head = render_name.split("(")[0].replace("Input", "Output").strip().lower()
    for n in ins:
        if is_virtual(n) and n.lower().startswith(head):
            return n
    return None


def virtual_outputs() -> list[str]:
    """Playback devices that are virtual cables, best (has a mic side) first."""
    outs = [d["name"] for d in list_devices("output") if is_virtual(d["name"])]
    return sorted(outs, key=lambda n: virtual_mic_for(n) is None)


def resample(data: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst or not len(data):
        return data
    return np.ascontiguousarray(soxr.resample(data, src, dst, quality="VHQ"), dtype=np.float32)


# --------------------------------------------------------------------------- helpers

class Ring:
    """Low-latency ring buffer bridging two audio clocks (mic -> output)."""

    # Drift tracking (opt-in): when the writer's clock runs a little slower or faster
    # than the output device's, the ring slowly drains or fills and eventually glitches.
    # With track_drift, each read takes slightly fewer/more frames than asked and
    # stretches them to fit, steering the fill back to the prefill level. At most
    # ±DRIFT_MAX speed (about 1/3 of a semitone); real clock drift needs ~0.01–0.1%.
    DRIFT_MAX = 0.02

    def __init__(self, rate: int = SR, prefill_s: float = 0.015, max_s: float = 0.08,
                 track_drift: bool = False):
        self.lock = threading.Lock()
        self.prefill_s, self.max_s = prefill_s, max_s
        self.track_drift = track_drift
        self.configure(rate)

    def configure(self, rate: int):
        with self.lock:
            self.cap = max(rate // 2, int(rate * self.max_s * 2))
            self.buf = np.zeros((self.cap, CH), np.float32)
            self.prefill = int(rate * self.prefill_s)   # jitter cushion before (re)starting
            self.max_fill = int(rate * self.max_s)      # beyond this, skip ahead (latency)
            self.r = self.w = self.count = 0
            self.primed = False
            self.ratio = 1.0     # current read speed (drift tracking)
            self._acc = 0.0      # fractional frames carried between reads
            self._integ = 0.0    # learned clock offset

    def clear(self):
        with self.lock:
            self.r = self.w = self.count = 0
            self.primed = False

    def write(self, x: np.ndarray):
        with self.lock:
            n = len(x)
            if n == 0:
                return
            if n >= self.cap:
                x, n = x[-self.cap:], self.cap
            end = self.w + n
            if end <= self.cap:
                self.buf[self.w:end] = x
            else:
                k = self.cap - self.w
                self.buf[self.w:] = x[:k]
                self.buf[: n - k] = x[k:]
            self.w = end % self.cap
            self.count = min(self.count + n, self.cap)
            if self.count > self.max_fill:
                drop = self.count - self.prefill
                self.r = (self.r + drop) % self.cap
                self.count -= drop
            elif self.count == self.cap:
                self.r = self.w

    def read(self, n: int) -> np.ndarray | None:
        with self.lock:
            if not self.primed:
                if self.count < self.prefill + n:
                    return None
                self.primed = True
            m = n
            if self.track_drift:
                # PI control: the integral learns the steady clock offset, so the fill
                # settles back at the full prefill cushion instead of hovering near empty
                err = float(np.clip((self.count - self.prefill) / max(self.prefill, 1), -1, 1))
                lim = self.DRIFT_MAX
                self._integ = float(np.clip(self._integ + err * 0.0002, -lim, lim))
                want = 1.0 + float(np.clip(err * lim * 0.5 + self._integ, -lim, lim))
                self.ratio += (want - self.ratio) * 0.05          # glide, no audible warble
                self._acc += n * self.ratio
                m = max(1, int(self._acc))
                self._acc -= m
            if self.count < m:
                self.primed = False
                self._acc = 0.0
                return None
            if m == n:
                out = self._peek(n)
            else:  # stretch m frames to n (peek one past the end for a seamless joint)
                src = self._peek(min(m + 1, self.count))
                if len(src) < m + 1:
                    src = np.concatenate([src, src[-1:]])
                pos = np.arange(n, dtype=np.float64) * (m / n)
                i = pos.astype(np.int64)
                f = (pos - i).astype(np.float32)[:, None]
                out = src[i] * (1 - f) + src[i + 1] * f
            self.r = (self.r + m) % self.cap
            self.count -= m
            return out

    def _peek(self, n: int) -> np.ndarray:
        end = self.r + n
        if end <= self.cap:
            return self.buf[self.r:end].copy()
        k = self.cap - self.r
        return np.concatenate([self.buf[self.r:], self.buf[: n - k]])


class StreamResampler:
    """Chunk-by-chunk resampler for live mic audio (identity when rates match)."""

    def __init__(self, src: int, dst: int):
        self.same = src == dst
        self.rs = None if self.same else soxr.ResampleStream(src, dst, CH, dtype="float32",
                                                              quality="HQ")

    def __call__(self, x: np.ndarray) -> np.ndarray:
        return x if self.same else self.rs.resample_chunk(x)


def soft_limit(x: np.ndarray, knee: float = 0.89) -> np.ndarray:
    """Transparent below the knee, smoothly saturates above so nothing hard-clips."""
    a = np.abs(x)
    m = a > knee
    if m.any():
        head = 1.0 - knee
        x[m] = np.sign(x[m]) * (knee + head * np.tanh((a[m] - knee) / head))
    return x


def peak(x: np.ndarray) -> float:
    return float(np.max(np.abs(x))) if len(x) else 0.0


def is_xrun(status) -> bool:
    """True if a callback status reports a real drop-out (not just output priming)."""
    if not status:
        return False
    return bool(status.output_underflow or status.output_overflow
                or status.input_underflow or status.input_overflow)


# --------------------------------------------------------------------------- voices

@dataclass(eq=False)
class Voice:
    sid: str
    data: dict                 # out -> (n, 2) float32 at that output's rate
    gain: float
    loop: bool
    preview: bool = False
    pos: dict = field(default_factory=dict)
    done: set = field(default_factory=set)
    stopping: bool = False
    paused: bool = False
    gate: dict = field(default_factory=dict)   # out -> current fade gain (0..1)
    started: float = field(default_factory=time.monotonic)

    def __post_init__(self):
        self.pos = {o: 0 for o in self.data}
        self.gate = {o: 1.0 for o in self.data}

    @property
    def outs(self) -> set:
        return set(self.data)

    @property
    def finished(self) -> bool:
        return self.done >= self.outs

    def seek(self, frac: float):
        for o, d in self.data.items():
            self.pos[o] = int(min(max(frac, 0.0), 0.999) * len(d))
            self.gate[o] = 0.0   # fade in from the new spot (no click)

    def progress(self) -> float:
        for o, d in self.data.items():
            if len(d):
                return (self.pos[o] % len(d)) / len(d)
        return 1.0


# --------------------------------------------------------------------------- engine

class Engine:
    def __init__(self):
        # `voices` is an immutable tuple that is *replaced* (never mutated) under
        # `lock`. The audio callbacks read the current tuple without locking, so they
        # can never block on the UI thread (which would be a priority inversion: the
        # audio thread stalls while a lower-priority thread holds the lock).
        self.lock = threading.Lock()
        self.voices: tuple[Voice, ...] = ()
        self._cache: dict[tuple[str, int], tuple[np.ndarray, np.ndarray]] = {}
        self._cache_lock = threading.Lock()
        self._ramps: dict[int, np.ndarray] = {}   # fade length -> 1..0 ramp (no per-block alloc)

        self.latency = "low"      # sounddevice latency: 'low' or 'high' (safer)
        self.names = {"main": None, "mon": None, "mic": None}   # device names for reopening
        self._last_cb = {"main": 0.0, "mon": 0.0, "mic": 0.0}  # monotonic time of last callback
        self._last_try = {"main": 0.0, "mon": 0.0, "mic": 0.0} # last (re)open attempt
        self.xruns = {"main": 0, "mon": 0, "mic": 0}           # drop-outs reported by PortAudio
        self.cb_errors = {"main": 0, "mon": 0, "mic": 0}       # exceptions inside a callback
        self.stalls = 0                                        # streams reopened by the watchdog

        # live settings (read by audio callbacks; plain attribute writes are atomic)
        self.sound_vol = 1.0      # sounds -> others
        self.mic_vol = 1.0        # mic    -> others
        self.mon_vol = 0.7        # everything -> your headphones
        self.mic_enabled = True   # pass your mic through to the cable
        self.mic_muted = False
        self.monitor_sounds = True
        self.eq_gains: list[float] | None = None   # None = EQ off
        self.eq_target = "voice"                   # 'voice' | 'sounds' | 'all'
        self._eqs: dict[tuple[str, str], EQ] = {}
        self.mic_check = False    # headphones also get your mic (= exactly what others hear)

        self.main_stream = self.mon_stream = self.mic_stream = None
        self.rates = {"main": SR, "mon": SR, "mic": SR}
        self.errors: dict[str, str] = {}

        self.ring_main = Ring()
        self.ring_mon = Ring()
        self._rs_main = StreamResampler(SR, SR)
        self._rs_mon = StreamResampler(SR, SR)

        # browser audio arrives in bursty ~20 ms chunks over IPC, so it gets a
        # bigger cushion than the mic (latency matters less for music than voice)
        self.browser_vol = 1.0
        self.browser_live = True      # browser -> others
        self.browser_monitor = True   # browser -> your headphones
        # Chromium's audio clock isn't the output devices' clock (measured up to ~1.5%
        # apart), so these rings track drift instead of glitching every few seconds
        self.ring_bmain = Ring(prefill_s=0.08, max_s=0.35, track_drift=True)
        self.ring_bmon = Ring(prefill_s=0.08, max_s=0.35, track_drift=True)
        self._rs_bmain = StreamResampler(SR, SR)
        self._rs_bmon = StreamResampler(SR, SR)
        self._browser_heard = 0.0     # monotonic time of the last non-silent chunk

        self.level_main = 0.0
        self.level_mic = 0.0
        self.level_mon = 0.0
        self.level_browser = 0.0

        self._rec_buf: list[np.ndarray] | None = None
        self._rec_frames_left = 0
        self.rec_done: tuple[np.ndarray, int] | None = None   # (audio, rate)
        self._mic_rec: list[np.ndarray] | None = None          # raw mic during a test

    # ----------------------------------------------------------------- streams
    @staticmethod
    def _native_rate(idx: int) -> int:
        return int(sd.query_devices(idx)["default_samplerate"])

    def _open_out(self, key, name, callback):
        idx = find_device("output", name)
        if idx is None:
            raise RuntimeError(f"device not found: {name}")
        rate = self._native_rate(idx)
        chans = min(CH, sd.query_devices(idx)["max_output_channels"])
        if chans < CH:
            raise RuntimeError("mono output devices aren't supported")
        s = sd.OutputStream(device=idx, samplerate=rate, channels=CH, dtype="float32",
                            latency=self.latency, callback=callback)
        self.rates[key] = rate
        self._last_cb[key] = time.monotonic()
        s.start()
        log.info("opened %s output: %s @ %d Hz (latency %s)", key, name, rate, self.latency)
        return s

    def set_main_device(self, name: str | None):
        self._close("main_stream")
        self.errors.pop("main", None)
        self.names["main"] = name
        self._last_try["main"] = time.monotonic()
        if name:
            try:
                self.main_stream = self._open_out("main", name, self._cb_main)
            except Exception as e:  # noqa: BLE001
                log.warning("can't open main output %r: %s", name, e)
                self.errors["main"] = str(e)
        self._reconfigure_mic_paths()

    def set_mon_device(self, name: str | None):
        self._close("mon_stream")
        self.errors.pop("mon", None)
        self.names["mon"] = name
        self._last_try["mon"] = time.monotonic()
        if name:
            try:
                self.mon_stream = self._open_out("mon", name, self._cb_mon)
            except Exception as e:  # noqa: BLE001
                log.warning("can't open headphone output %r: %s", name, e)
                self.errors["mon"] = str(e)
        self._reconfigure_mic_paths()

    def set_mic_device(self, name: str | None):
        self._close("mic_stream")
        self.errors.pop("mic", None)
        self.names["mic"] = name
        self._last_try["mic"] = time.monotonic()
        if name:
            idx = find_device("input", name)
            try:
                if idx is None:
                    raise RuntimeError(f"device not found: {name}")
                rate = self._native_rate(idx)
                chans = min(2, sd.query_devices(idx)["max_input_channels"])
                self.rates["mic"] = rate
                self._reconfigure_mic_paths()
                self._last_cb["mic"] = time.monotonic()
                s = sd.InputStream(device=idx, samplerate=rate, channels=chans, dtype="float32",
                                   latency=self.latency, callback=self._cb_mic)
                s.start()
                self.mic_stream = s
                log.info("opened mic: %s @ %d Hz, %d ch", name, rate, chans)
            except Exception as e:  # noqa: BLE001
                log.warning("can't open mic %r: %s", name, e)
                self.errors["mic"] = str(e)

    def reopen_all(self):
        """Close and reopen every stream with the same devices (after a latency change)."""
        self.set_mic_device(self.names["mic"])
        self.set_main_device(self.names["main"])
        self.set_mon_device(self.names["mon"])

    def check_streams(self) -> list[str]:
        """Watchdog (call about once a second from the UI thread).

        A stream whose callback has stopped being called (headset unplugged, Windows
        changed its sample rate, PC came back from sleep) is closed and reopened. A
        device that failed to open is retried every RETRY_S. Returns the keys that
        were touched, so the UI can refresh its status."""
        now = time.monotonic()
        touched = []
        for key, attr, setter in (("main", "main_stream", self.set_main_device),
                                  ("mon", "mon_stream", self.set_mon_device),
                                  ("mic", "mic_stream", self.set_mic_device)):
            name = self.names[key]
            if not name:
                continue
            if getattr(self, attr) is None:
                if now - self._last_try[key] >= RETRY_S:
                    setter(name)
                    if key not in self.errors:
                        log.info("%s device came back: %s", key, name)
                        touched.append(key)
            elif now - self._last_cb[key] > STALL_S:
                log.warning("%s stream stalled (%.1fs without a callback); reopening %s",
                            key, now - self._last_cb[key], name)
                self.stalls += 1
                setter(name)
                touched.append(key)
        return touched

    def _reconfigure_mic_paths(self):
        r = self.rates
        self._rs_main = StreamResampler(r["mic"], r["main"])
        self._rs_mon = StreamResampler(r["mic"], r["mon"])
        self.ring_main.configure(r["main"])
        self.ring_mon.configure(r["mon"])
        self._rs_bmain = StreamResampler(SR, r["main"])
        self._rs_bmon = StreamResampler(SR, r["mon"])
        self.ring_bmain.configure(r["main"])
        self.ring_bmon.configure(r["mon"])

    # ----------------------------------------------------------------- browser input
    def feed_browser(self, x: np.ndarray):
        """Push a chunk of browser audio ((n, 2) float32 at SR). Call from the UI thread."""
        lvl = peak(x)
        self.level_browser = max(lvl * self.browser_vol, self.level_browser)
        if lvl > 0.003:
            self._browser_heard = time.monotonic()
        if self.main_stream is not None:
            self.ring_bmain.write(self._rs_bmain(x))
        if self.mon_stream is not None:
            self.ring_bmon.write(self._rs_bmon(x))

    def browser_on_air(self) -> bool:
        """True while the browser is audibly going out to others (drives auto push-to-talk)."""
        return (self.browser_live and self.browser_vol > 0
                and time.monotonic() - self._browser_heard < 0.5)

    def _close(self, attr):
        s = getattr(self, attr)
        setattr(self, attr, None)
        out = {"main_stream": "main", "mon_stream": "mon"}.get(attr)
        if out:  # voices can't finish on a device that's gone
            with self.lock:
                for v in self.voices:
                    v.done.add(out)
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:  # noqa: BLE001
                log.debug("closing %s raised", attr, exc_info=True)

    def shutdown(self):
        for a in ("mic_stream", "main_stream", "mon_stream"):
            self._close(a)

    def active_outputs(self) -> set:
        outs = set()
        if self.main_stream is not None:
            outs.add("main")
        if self.mon_stream is not None:
            outs.add("mon")
        return outs

    # ----------------------------------------------------------------- sample cache
    def data_for(self, sid: str, data: np.ndarray, rate: int, src_rate: int = SR) -> np.ndarray:
        """Audio for `sid` at `rate`, resampled once and cached."""
        if rate == src_rate:
            return data
        key = (sid.split(":")[0], rate)   # "abc:preview" shares abc's cache
        with self._cache_lock:
            hit = self._cache.get(key)
        # the cache holds a reference to the source array and compares identity with
        # `is`: comparing id() alone could match a *new* array that happens to be
        # allocated at a freed one's address (e.g. successive test recordings)
        if hit and hit[0] is data:
            return hit[1]
        out = resample(data, src_rate, rate)
        with self._cache_lock:
            self._cache[key] = (data, out)
        return out

    def prepare(self, sid: str, data: np.ndarray):
        """Pre-resample for the currently open outputs (call off the UI thread)."""
        for o in self.active_outputs():
            self.data_for(sid, data, self.rates[o])

    def forget(self, sid: str):
        with self._cache_lock:
            for k in [k for k in self._cache if k[0] == sid]:
                del self._cache[k]

    # ----------------------------------------------------------------- playback
    def play(self, sid: str, data: np.ndarray, gain: float, loop=False, mode="restart",
             preview=False, src_rate: int = SR, start: float = 0.0) -> Voice | None:
        """mode: 'restart' (stop previous instance), 'overlap', 'toggle' (stop if playing)."""
        outs = self.active_outputs()
        if preview:
            # previews are for your ears only; with no headphone device open they must
            # not fall through to the cable (everyone in the call would hear them)
            outs = {"mon"} if "mon" in outs else set()
        if not outs:
            return None
        with self.lock:
            existing = [v for v in self.voices if v.sid == sid and not v.stopping]
            if mode in ("restart", "toggle"):
                for v in existing:
                    v.stopping = True
                if mode == "toggle" and existing:
                    return None
        per_out = {o: self.data_for(sid, data, self.rates[o], src_rate) for o in outs}
        v = Voice(sid, per_out, gain, loop, preview=preview)
        if start > 0:
            v.seek(start)
        with self.lock:
            self.voices = self.voices + (v,)
        return v

    def stop(self, sid: str):
        with self.lock:
            for v in self.voices:
                if v.sid == sid:
                    v.stopping = True

    def stop_all(self):
        with self.lock:
            for v in self.voices:
                v.stopping = True

    def _current(self, sid: str) -> Voice | None:
        cur = [v for v in self.voices if v.sid == sid and not v.stopping and not v.finished]
        return cur[-1] if cur else None

    def set_paused(self, sid: str, paused: bool):
        with self.lock:
            for v in self.voices:
                if v.sid == sid and not v.stopping:
                    v.paused = paused

    def seek(self, sid: str, frac: float) -> bool:
        with self.lock:
            v = self._current(sid)
            if v is None:
                return False
            v.seek(frac)
            return True

    def state(self, sid: str) -> tuple[float, bool] | None:
        """(progress 0..1, paused) of the newest live voice for sid, or None."""
        with self.lock:
            v = self._current(sid)
            return (v.progress(), v.paused) if v else None

    def pause_all(self) -> bool:
        """Pause everything playing, or resume if everything is already paused."""
        with self.lock:
            live = [v for v in self.voices if not v.stopping and not v.finished and not v.preview]
            resume = bool(live) and all(v.paused for v in live)
            for v in live:
                v.paused = not resume
            return not resume

    def set_gain(self, sid: str, gain: float):
        with self.lock:
            for v in self.voices:
                if v.sid == sid:
                    v.gain = gain

    def playing(self) -> dict[str, tuple[float, bool]]:
        """sid -> (progress 0..1, paused) of the newest voice for that sound."""
        res = {}
        with self.lock:
            self.voices = tuple(v for v in self.voices if not v.finished)
            for v in self.voices:
                if not v.stopping:
                    res[v.sid] = (v.progress(), v.paused)
        return res

    def any_playing(self) -> bool:
        """True while a sound is going out to others (drives auto push-to-talk)."""
        with self.lock:
            return any(not v.finished and not v.stopping and not v.preview and not v.paused
                       for v in self.voices)

    # ----------------------------------------------------------------- test record
    def start_test_record(self, seconds: float):
        self.rec_done = None
        self._rec_frames_left = int(seconds * self.rates["main"])
        self._mic_rec = [] if self.mic_stream is not None else None
        self._rec_buf = []

    def take_mic_recording(self) -> tuple[np.ndarray, int] | None:
        """Raw mic captured during the last test (mono, at the mic's rate)."""
        rec, self._mic_rec = self._mic_rec, None
        if not rec:
            return None
        return np.concatenate(rec), self.rates["mic"]

    @property
    def recording(self) -> bool:
        return self._rec_buf is not None

    # ----------------------------------------------------------------- callbacks
    def _ramp(self, n: int) -> np.ndarray:
        """(n, 1) fade-out ramp 1 -> 0, cached (the same few lengths recur every block)."""
        r = self._ramps.get(n)
        if r is None:
            r = self._ramps[n] = np.linspace(1.0, 0.0, n, dtype=np.float32)[:, None]
        return r

    def _render(self, out: str, frames: int, previews_only=False) -> np.ndarray:
        buf = np.zeros((frames, CH), np.float32)
        silent = None   # scratch for voices that must advance but not be heard
        fade = int(FADE_S * self.rates[out])
        # no lock: `self.voices` is an immutable tuple swapped atomically by the UI side
        voices = [v for v in self.voices if out in v.data and out not in v.done]
        for v in voices:
            if previews_only and not v.preview:
                if silent is None:
                    silent = np.zeros((frames, CH), np.float32)
                dst = silent
            else:
                dst = buf
            data = v.data[out]
            n = len(data)
            p = v.pos[out]
            g = np.float32(v.gain)
            if v.stopping:  # short fade-out, then done
                take = min(frames, fade, n - p if not v.loop else fade)
                if take > 0 and n:
                    idx = (np.arange(p, p + take) % n) if v.loop else np.arange(p, p + take)
                    dst[:take] += data[idx] * self._ramp(take) * g
                v.done.add(out)
                continue
            target = 0.0 if v.paused else 1.0
            g0 = v.gate[out]
            if g0 == 0.0 and target == 0.0:
                continue  # paused: hold position, output nothing
            if g0 != target:  # fading in/out for pause, resume or seek
                dst_final = dst
                dst = np.zeros((frames, CH), np.float32)
            w = 0
            while w < frames:
                if p >= n:
                    if v.loop and n:
                        p = 0
                    else:
                        break
                take = min(frames - w, n - p)
                dst[w:w + take] += data[p:p + take] * g
                w += take
                p += take
            v.pos[out] = p
            if g0 != target:
                k = min(frames, fade)
                env = np.full(frames, target, np.float32)
                env[:k] = np.linspace(g0, target, k, dtype=np.float32)
                dst_final += dst * env[:, None]
                v.gate[out] = target
            if p >= n and not v.loop:
                v.done.add(out)
        return buf

    def _eq(self, out: str, part: str, x: np.ndarray) -> np.ndarray:
        """Run x through the EQ if it's on and aimed at `part` ('sounds' / 'voice')."""
        g = self.eq_gains
        if g is None or self.eq_target not in (part, "all"):
            return x
        key = (out, part)
        f = self._eqs.get(key)
        if f is None or f.rate != self.rates[out]:
            f = self._eqs[key] = EQ(self.rates[out])
        return f.process(x, g)

    # Each PortAudio callback is a thin guard around the real work: an exception that
    # escapes a callback makes PortAudio abort the stream for good, silently. Here it
    # is logged (once per stream, so the audio thread never does repeated file I/O),
    # counted, and the block is left silent.
    def _guard(self, key: str, exc: BaseException):
        self.cb_errors[key] += 1
        if self.cb_errors[key] == 1:
            log.error("exception in %s audio callback", key, exc_info=exc)
            self.errors[key] = f"audio callback failed: {exc}"

    def _cb_main(self, outdata, frames, t, status):
        self._last_cb["main"] = time.monotonic()
        if is_xrun(status):
            self.xruns["main"] += 1
        try:
            self._main(outdata, frames)
        except Exception as e:  # noqa: BLE001
            outdata.fill(0)
            self._guard("main", e)

    def _cb_mon(self, outdata, frames, t, status):
        self._last_cb["mon"] = time.monotonic()
        if is_xrun(status):
            self.xruns["mon"] += 1
        try:
            self._mon(outdata, frames)
        except Exception as e:  # noqa: BLE001
            outdata.fill(0)
            self._guard("mon", e)

    def _cb_mic(self, indata, frames, t, status):
        self._last_cb["mic"] = time.monotonic()
        if is_xrun(status):
            self.xruns["mic"] += 1
        try:
            self._mic(indata)
        except Exception as e:  # noqa: BLE001
            self._guard("mic", e)

    def _main(self, outdata, frames):
        mix = self._render("main", frames)
        mix *= np.float32(self.sound_vol)
        b = self.ring_bmain.read(frames)
        if b is not None and self.browser_live:
            mix += b * np.float32(self.browser_vol)
        mix = self._eq("main", "sounds", mix)
        m = self.ring_main.read(frames)
        if m is not None and self.mic_enabled and not self.mic_muted:
            mix += self._eq("main", "voice", m * np.float32(self.mic_vol))
        soft_limit(mix)
        outdata[:] = mix
        self.level_main = max(peak(mix), self.level_main * 0.85)
        if self._rec_buf is not None:
            self._rec_buf.append(mix.copy())
            self._rec_frames_left -= frames
            if self._rec_frames_left <= 0:
                self.rec_done = (np.concatenate(self._rec_buf), self.rates["main"])
                self._rec_buf = None

    def _mon(self, outdata, frames):
        check = self.mic_check
        # in mic check you hear the real output mix: sounds at their outgoing
        # level plus your mic, so you can judge the balance while a song plays
        mix = self._render("mon", frames, previews_only=not (check or self.monitor_sounds))
        m = self.ring_mon.read(frames)
        if check:
            mix *= np.float32(self.sound_vol)
        b = self.ring_bmon.read(frames)
        if b is not None and (self.browser_monitor or (check and self.browser_live)):
            mix += b * np.float32(self.browser_vol)
        mix = self._eq("mon", "sounds", mix)   # you hear the same EQ others get
        if check and m is not None and self.mic_enabled and not self.mic_muted:
            mix += self._eq("mon", "voice", m * np.float32(self.mic_vol))
        mix *= np.float32(self.mon_vol)
        soft_limit(mix)
        outdata[:] = mix
        self.level_mon = max(peak(mix), self.level_mon * 0.85)

    def _mic(self, indata):
        x = indata
        x = np.repeat(x, 2, axis=1) if x.shape[1] == 1 else x[:, :2]
        x = np.ascontiguousarray(x, dtype=np.float32)
        self.level_mic = max(peak(x), self.level_mic * 0.85)
        rec = self._mic_rec
        if rec is not None and self._rec_buf is not None:
            rec.append(x[:, 0].copy())
        if self.main_stream is not None:
            self.ring_main.write(self._rs_main(x))
        if self.mic_check and self.mon_stream is not None:
            self.ring_mon.write(self._rs_mon(x))
