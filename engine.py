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

import threading
import time
from dataclasses import dataclass, field

import numpy as np
import sounddevice as sd
import soxr

from eq import EQ

SR = 48000  # library storage rate
CH = 2
FADE_S = 0.010  # fade when a sound is stopped early (no clicks)


# --------------------------------------------------------------------------- devices

def _wasapi_index() -> int | None:
    for i, api in enumerate(sd.query_hostapis()):
        if "WASAPI" in api["name"]:
            return i
    return None


def rescan():
    """Re-enumerate devices (picks up newly plugged ones). Kills open streams — reopen after."""
    sd._terminate()
    sd._initialize()


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


def resample(data: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst or not len(data):
        return data
    return np.ascontiguousarray(soxr.resample(data, src, dst, quality="VHQ"), dtype=np.float32)


# --------------------------------------------------------------------------- helpers

class Ring:
    """Low-latency ring buffer bridging two audio clocks (mic -> output)."""

    def __init__(self, rate: int = SR, prefill_s: float = 0.015, max_s: float = 0.08):
        self.lock = threading.Lock()
        self.prefill_s, self.max_s = prefill_s, max_s
        self.configure(rate)

    def configure(self, rate: int):
        with self.lock:
            self.cap = max(rate // 2, int(rate * self.max_s * 2))
            self.buf = np.zeros((self.cap, CH), np.float32)
            self.prefill = int(rate * self.prefill_s)   # jitter cushion before (re)starting
            self.max_fill = int(rate * self.max_s)      # beyond this, skip ahead to keep latency low
            self.r = self.w = self.count = 0
            self.primed = False

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
            if self.count < n:
                self.primed = False
                return None
            end = self.r + n
            if end <= self.cap:
                out = self.buf[self.r:end].copy()
            else:
                k = self.cap - self.r
                out = np.concatenate([self.buf[self.r:], self.buf[: n - k]])
            self.r = end % self.cap
            self.count -= n
            return out


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
        self.lock = threading.Lock()
        self.voices: list[Voice] = []
        self._cache: dict[tuple[str, int], tuple[int, np.ndarray]] = {}
        self._cache_lock = threading.Lock()

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
        self.ring_bmain = Ring(prefill_s=0.06, max_s=0.30)
        self.ring_bmon = Ring(prefill_s=0.06, max_s=0.30)
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
                            latency="low", callback=callback)
        self.rates[key] = rate
        s.start()
        return s

    def set_main_device(self, name: str | None):
        self._close("main_stream")
        self.errors.pop("main", None)
        if name:
            try:
                self.main_stream = self._open_out("main", name, self._cb_main)
            except Exception as e:  # noqa: BLE001
                self.errors["main"] = str(e)
        self._reconfigure_mic_paths()

    def set_mon_device(self, name: str | None):
        self._close("mon_stream")
        self.errors.pop("mon", None)
        if name:
            try:
                self.mon_stream = self._open_out("mon", name, self._cb_mon)
            except Exception as e:  # noqa: BLE001
                self.errors["mon"] = str(e)
        self._reconfigure_mic_paths()

    def set_mic_device(self, name: str | None):
        self._close("mic_stream")
        self.errors.pop("mic", None)
        if name:
            idx = find_device("input", name)
            try:
                if idx is None:
                    raise RuntimeError(f"device not found: {name}")
                rate = self._native_rate(idx)
                chans = min(2, sd.query_devices(idx)["max_input_channels"])
                self.rates["mic"] = rate
                self._reconfigure_mic_paths()
                s = sd.InputStream(device=idx, samplerate=rate, channels=chans, dtype="float32",
                                   latency="low", callback=self._cb_mic)
                s.start()
                self.mic_stream = s
            except Exception as e:  # noqa: BLE001
                self.errors["mic"] = str(e)

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
                pass

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
        if hit and hit[0] == id(data):
            return hit[1]
        out = resample(data, src_rate, rate)
        with self._cache_lock:
            self._cache[key] = (id(data), out)
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
        if preview and "mon" in outs:
            outs = {"mon"}
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
            self.voices.append(v)
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
            self.voices = [v for v in self.voices if not v.finished]
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
    def _render(self, out: str, frames: int, previews_only=False) -> np.ndarray:
        buf = np.zeros((frames, CH), np.float32)
        silent = np.zeros((frames, CH), np.float32)
        fade = int(FADE_S * self.rates[out])
        with self.lock:
            voices = [v for v in self.voices if out in v.data and out not in v.done]
        for v in voices:
            dst = silent if (previews_only and not v.preview) else buf
            data = v.data[out]
            n = len(data)
            p = v.pos[out]
            g = np.float32(v.gain)
            if v.stopping:  # short fade-out, then done
                take = min(frames, fade, n - p if not v.loop else fade)
                if take > 0 and n:
                    idx = (np.arange(p, p + take) % n) if v.loop else np.arange(p, p + take)
                    ramp = np.linspace(1.0, 0.0, take, dtype=np.float32)[:, None]
                    dst[:take] += data[idx] * ramp * g
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

    def _cb_main(self, outdata, frames, t, status):
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

    def _cb_mon(self, outdata, frames, t, status):
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

    def _cb_mic(self, indata, frames, t, status):
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
