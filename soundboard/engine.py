"""Real-time audio engine.

Three WASAPI streams, each opened at its device's *native* rate (Windows'
built-in resampler, auto_convert, audibly garbles audio — measured ~70% junk on
VB-Cable — so all rate conversion is done here with soxr instead):

  mic  (input)  -> streaming resampler -> ring buffers -> main / monitor
  radio   (48 kHz, pushed from the UI thread) -> resampler -> ring buffers -> main / monitor
  aux     (48 kHz, pushed from a capture thread: one per captured program, Apps tab)
          -> the same path again, each with its own rings, volume and switches
  main (output) = sounds + radio / programs (when live) + mic -> virtual cable (what others hear)
  mon  (output) = sounds + radio / programs [+ mic in test mode] -> your headphones

Sounds are stored at SR and resampled (cached) to each output's rate. Every
playing Voice keeps its own position per output, so the two output devices
run on independent clocks without drift or glitches.

Live speed / pitch (the ⏩ controls): sounds play at `sound_speed` by reading
their data at a fractional rate (like a tape), and a pitch shifter on the sounds
bus corrects the pitch back (`sound_keep_pitch`) and adds `sound_pitch`. The
app's own playback (test recording, cue beeps, the setup tune, previews) is
`fixed`: played at speed 1 and mixed in after the pitch shifter.
Per-sound effects are baked in ahead of time instead (soundboard.soundfx).
"""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

import numpy as np
import sounddevice as sd
import soxr

from soundboard import destination
from soundboard.eq import EQ
from soundboard.sendfx import Ducker, Limiter, SmartMono
from soundboard.voicefx.builtin import PitchShift

log = logging.getLogger(__name__)

SR = 48000  # library storage rate
CH = 2
FADE_S = 0.010  # fade when a sound is stopped early (no clicks)
STALL_S = 1.5   # a stream whose callback hasn't run for this long is dead: reopen it
RETRY_S = 5.0   # how often to retry a device that failed to open
I16_SCALE = np.float32(1 / 32767.0)   # int16 sound data -> float
CACHE_BUDGET = 512 << 20               # bytes of resampled copies kept for non-48 kHz devices
# the app's own playback: the test recording, cue beeps, the setup wizard's tune. With
# previews ("<sid>:preview", "<sid>~fx:preview") they ignore the live speed / pitch
FIXED_SIDS = frozenset({"__test__", "__cue__", "__setup__", "__check__"})


def is_fixed(sid: str) -> bool:
    """True for voices the live speed / pitch must leave alone (see FIXED_SIDS)."""
    return sid in FIXED_SIDS or sid.endswith(":preview")


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

def hermite(p0, p1, p2, p3, f):
    """4-point cubic (Catmull-Rom) interpolation between p1 and p2 at fraction f.
    Linear interpolation dulls the top end and leaves images around it (measured
    -20 dB against a proper resampler on music); this is much cleaner for the
    cost of two more reads."""
    return p1 + 0.5 * f * (p2 - p0 + f * (2 * p0 - 5 * p1 + 4 * p2 - p3
                                          + f * (3 * (p1 - p2) + p3 - p0)))


class Ring:
    """Low-latency ring buffer bridging two audio clocks (mic -> output)."""

    # Drift tracking (opt-in): when the writer's clock runs a little slower or faster
    # than the output device's, the ring slowly drains or fills and eventually glitches.
    # With track_drift, each read takes slightly fewer/more frames than asked and
    # stretches them to fit, steering the fill back to the prefill level. At most
    # ±DRIFT_MAX speed (about 1/3 of a semitone); real clock drift needs ~0.01–0.1%.
    DRIFT_MAX = 0.02
    # Running dry or skipping ahead is a jump in the waveform, heard as a crack. The
    # frames around it are faded over this long instead, so it's a soft dip.
    FADE_S = 0.004

    def __init__(self, rate: int = SR, prefill_s: float = 0.015, max_s: float = 0.08,
                 track_drift: bool = False, grow_to_s: float = 0.0, auto_drift: bool = False):
        self.lock = threading.Lock()
        self.prefill_s, self.max_s = prefill_s, max_s
        self.track_drift = track_drift
        # auto_drift: start without drift tracking, and switch it on once the ring has
        # had to skip or refill twice (the writer's clock really is off: a wireless
        # headset's mic against the cable, say)
        self.auto_drift = auto_drift
        # grow_to_s: a writer that stalls now and then (the radio) gets a bigger
        # cushion each time the ring runs dry, up to this, so it stops skipping
        self.grow_to_s = grow_to_s
        self.underruns = 0   # ran dry while playing (a gap)
        self.overflows = 0   # skipped ahead to cut latency (a jump)
        self.configure(rate)

    def configure(self, rate: int):
        with self.lock:
            self.cap = max(rate // 2, int(rate * self.max_s * 2))
            self.buf = np.zeros((self.cap, CH), np.float32)
            self.prefill = int(rate * self.prefill_s)   # jitter cushion before (re)starting
            self.max_fill = int(rate * self.max_s)      # beyond this, skip ahead (latency)
            self.max_prefill = max(self.prefill, int(rate * self.grow_to_s))
            self.fade = max(1, int(rate * self.FADE_S))
            self._fade_in = True
            self.r = self.w = self.count = 0
            self.primed = False
            self.ratio = 1.0     # current read speed (drift tracking)
            self._acc = 0.0      # fractional frames carried between reads
            self._integ = 0.0    # learned clock offset
            self._last = np.zeros((1, CH), np.float32)   # the frame before the next read

    def _glitched(self):
        """Count toward switching drift tracking on (auto_drift)."""
        if self.auto_drift and not self.track_drift and self.underruns + self.overflows >= 2:
            self.track_drift = True

    def clear(self):
        with self.lock:
            self.r = self.w = self.count = 0
            self.primed = False
            self._fade_in = True

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
                self.overflows += 1
                self._glitched()
                self._fade_in = True
            elif self.count == self.cap:
                self.r = self.w
                self._fade_in = True

    def read(self, n: int) -> np.ndarray | None:
        with self.lock:
            if not self.primed:
                if self.count < self.prefill + n:
                    return None
                self.primed = True
                self._fade_in = True
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
                # ran dry: play out what's left, fading to silence, then wait for
                # the cushion to refill (a bigger one next time if it can grow)
                self.primed = False
                self._acc = 0.0
                self.underruns += 1
                self._glitched()
                self.prefill = min(self.max_prefill, int(self.prefill * 1.5))
                k = min(self.count, n)
                if not k:
                    return None
                out = np.zeros((n, CH), np.float32)
                out[:k] = self._peek(k) * np.linspace(1, 0, k, dtype=np.float32)[:, None]
                self.r = (self.r + k) % self.cap
                self.count -= k
                return out
            if m == n:
                out = self._peek(n)
            else:  # stretch m frames to n (cubic, with a frame either side for the joints)
                src = self._peek(min(m + 2, self.count))
                while len(src) < m + 2:
                    src = np.concatenate([src, src[-1:]])
                src = np.concatenate([self._last, src])      # src[k + 1] is frame k
                pos = np.arange(n, dtype=np.float64) * (m / n)
                i = pos.astype(np.int64) + 1
                f = (pos - (i - 1)).astype(np.float32)[:, None]
                out = hermite(src[i - 1], src[i], src[i + 1], src[i + 2], f)
            self._last = self._peek_at(m - 1)
            self.r = (self.r + m) % self.cap
            self.count -= m
            if self._fade_in:   # (re)starting or after a skip: no hard edge
                self._fade_in = False
                k = min(self.fade, n)
                out[:k] *= np.linspace(0, 1, k, dtype=np.float32)[:, None]
            return out

    def _peek_at(self, k: int) -> np.ndarray:
        """Frame k after the read position, as (1, CH)."""
        return self.buf[(self.r + k) % self.cap][None, :].copy()

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


def finite(x: np.ndarray) -> np.ndarray:
    """`x` with any NaN / Inf sample made silent (in place). One such sample would stay
    in the send chain's filters for good: the call would hear nothing until a restart."""
    if len(x) and not np.isfinite(np.max(np.abs(x))):
        np.nan_to_num(x, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
    return x


def is_xrun(status) -> bool:
    """True if a callback status reports a real drop-out (not just output priming)."""
    if not status:
        return False
    return bool(status.output_underflow or status.output_overflow
                or status.input_underflow or status.input_overflow)


class LivePitch:
    """Stereo real-time pitch shifter (one voicefx PitchShift per channel). Keeps
    its recent input while bypassed, so switching it on or off crossfades
    instead of dropping out for its latency."""

    def __init__(self, rate: int):
        self.rate = rate
        self._ch = (PitchShift(rate), PitchShift(rate))
        self._st = 0.0

    def process(self, x: np.ndarray, semitones: float) -> np.ndarray:
        if semitones != self._st:
            self._st = semitones
            for e in self._ch:     # set directly: past the voice changer's ±12 limit
                e.p = {"semitones": float(semitones), "mix": 1.0}
        out = np.empty_like(x)
        for c, e in enumerate(self._ch):
            out[:, c] = e.run(np.ascontiguousarray(x[:, c]), self.rate)
        return out


# --------------------------------------------------------------------------- voices

class AuxSource:
    """A pushed 48 kHz stereo source with its own rings, volume and switches: one
    per program captured by the Apps tab. Pushed from the capture's own thread (a
    ring has one writer), read by the output callbacks. Comes and goes at runtime:
    Engine.aux is a tuple replaced under the lock, like the voices."""

    def __init__(self, key, rates: dict | None = None):
        self.key = key
        self.vol = 1.0
        self.live = True        # -> others (the whole point of capturing a program)
        self.monitor = False    # -> your headphones (the program already plays there)
        self.level = 0.0
        # the program's audio clock is its device's, not ours: track drift; and a
        # program that goes quiet stops sending at all, so start again quickly
        self.ring_main = Ring(prefill_s=0.05, max_s=0.6, track_drift=True, grow_to_s=0.25)
        self.ring_mon = Ring(prefill_s=0.05, max_s=0.6, track_drift=True, grow_to_s=0.25)
        self._rs_main = StreamResampler(SR, SR)
        self._rs_mon = StreamResampler(SR, SR)
        self._heard = 0.0
        if rates:
            self.configure(rates)

    def configure(self, rates: dict, outs=("main", "mon")):
        if "main" in outs:
            self._rs_main = StreamResampler(SR, rates["main"])
            self.ring_main.configure(rates["main"])
        if "mon" in outs:
            self._rs_mon = StreamResampler(SR, rates["mon"])
            self.ring_mon.configure(rates["mon"])

    def feed(self, x: np.ndarray, main: bool, mon: bool):
        lvl = peak(x)
        if not np.isfinite(lvl):   # a program's capture can hand over a broken block
            x = finite(np.array(x, dtype=np.float32))
            lvl = peak(x)
        self.level = max(lvl * self.vol, self.level)
        if lvl > 0.003:
            self._heard = time.monotonic()
        if main:
            self.ring_main.write(self._rs_main(x))
        if mon:
            self.ring_mon.write(self._rs_mon(x))

    def on_air(self) -> bool:
        return self.live and self.vol > 0 and time.monotonic() - self._heard < 0.5


@dataclass(eq=False)
class Voice:
    sid: str
    data: dict                 # out -> (n, 2) int16 or float32 at that output's rate
    gain: float
    loop: bool
    preview: bool = False
    pos: dict = field(default_factory=dict)
    done: set = field(default_factory=set)
    stopping: bool = False
    paused: bool = False
    gate: dict = field(default_factory=dict)   # out -> current fade gain (0..1)
    started: float = field(default_factory=time.monotonic)
    fade_in: float = 0.0       # seconds: rises from silence when it starts
    fade_out: float = 0.0      # seconds: falls to silence when stopped, and before its end
    fading: set = field(default_factory=set)   # outs still on their way up from the start
    # out -> requested position (0..1). seek() only posts it; the audio callback
    # applies it at the start of its next block, since it writes `pos` and `gate`
    # back at the end of every block and would otherwise undo a seek made meanwhile
    seek_to: dict = field(default_factory=dict)
    rates: dict = field(default_factory=dict)   # out -> the rate its data was made at
    fixed: bool = False        # the app's own playback: no live speed / pitch (is_fixed)
    # power share each destination low cut takes from this sound (destination.cut_shares):
    # its make-up gain while a mode with that cut is on
    cut_share: dict = field(default_factory=dict)

    def __post_init__(self):
        self.pos = {o: 0 for o in self.data}
        start = 0.0 if self.fade_in > 0 else 1.0
        self.gate = {o: start for o in self.data}
        self.fading = set(self.data) if self.fade_in > 0 else set()

    @property
    def outs(self) -> set:
        return set(self.data)

    def makeup(self, lowcut: int) -> float:
        """The gain that gives this sound back what `lowcut` takes from it."""
        return destination.makeup(self.cut_share.get(lowcut, 0.0))

    @property
    def finished(self) -> bool:
        return self.done >= self.outs

    def seek(self, frac: float):
        """Ask for a new position (applied by the audio callback: see seek_to)."""
        frac = min(max(frac, 0.0), 0.999)
        self.seek_to = {o: frac for o in self.data}   # one atomic swap

    def _apply_seek(self, out: str):
        """Audio thread (or before the voice is shared): take a pending seek."""
        frac = self.seek_to.pop(out, None)
        if frac is not None:
            self.pos[out] = int(frac * len(self.data[out]))
            self.gate[out] = 0.0   # fade in from the new spot (no click)

    def progress(self) -> float:
        for o, d in self.data.items():
            if len(d):
                frac = self.seek_to.get(o)   # a seek the callback hasn't taken yet
                return frac if frac is not None else (self.pos[o] % len(d)) / len(d)
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
        # (sid, rate) -> (source array, resampled copy); LRU, bounded by CACHE_BUDGET
        self._cache: OrderedDict[tuple[str, int], tuple[np.ndarray, np.ndarray]] = OrderedDict()
        self._cache_bytes = 0
        self._cache_lock = threading.Lock()

        self.latency = "low"      # sounddevice latency: 'low' or 'high' (safer)
        self.names = {"main": None, "mon": None, "mic": None}   # device names for reopening
        self._last_cb = {"main": 0.0, "mon": 0.0, "mic": 0.0}  # monotonic time of last callback
        self._last_try = {"main": 0.0, "mon": 0.0, "mic": 0.0} # last (re)open attempt
        self.xruns = {"main": 0, "mon": 0, "mic": 0}           # drop-outs reported by PortAudio
        self.cb_errors = {"main": 0, "mon": 0, "mic": 0}       # exceptions inside a callback
        self._cb_err_base = {"main": 0, "mon": 0, "mic": 0}    # cb_errors when the stream opened
        self._cb_err_seen = {"main": 0, "mon": 0, "mic": 0}    # cb_errors at the last check_streams
        self.stalls = 0                                       # streams reopened by the watchdog

        # live settings (read by audio callbacks; plain attribute writes are atomic)
        self.sound_vol = 1.0      # sounds -> others
        self.mic_vol = 1.0        # mic    -> others
        self.mon_vol = 0.7        # everything -> your headphones
        self.mic_enabled = True   # pass your mic through to the cable
        self.sending = True       # master switch: False sends silence to others
        self.mic_muted = False
        self.monitor_sounds = True
        self.eq_gains: list[float] | None = None   # None = EQ off
        self.eq_target = "voice"                   # 'voice' | 'sounds' | 'all'
        self.dest = None                           # destination.Dest shaping the sounds bus
        self._dests: dict[str, object] = {}        # out -> destination.Processor
        self._eqs: dict[tuple[str, str], EQ] = {}
        self.mic_check = False    # headphones also get your mic (= exactly what others hear)
        self.voice_chain = None   # voicefx.VoiceChain: voice changer / live speech tap on the mic
        # the send stage (soundboard.sendfx): what makes the mix survive voice chat
        self.send_mono = True     # phase-aware mono into the cable (every voice chat is mono)
        self.duck_db = 0.0        # lower the sounds this much while you talk (0 = off)
        self.mic_gate = False     # mute your mic while a sound plays (only the sounds go out)
        self._gate: dict[str, float] = {}   # output -> the mic's current gate gain
        self.limiter_on = True    # hold the cable's peaks at sendfx.CEILING_DB
        self._send: dict[tuple[str, str], object] = {}   # (out, kind) -> its sendfx stage
        self.sound_speed = 1.0        # live playback speed of every sound (0.25..4)
        self.sound_pitch = 0.0        # live pitch of every sound, semitones
        self.sound_keep_pitch = True  # speed changes leave the pitch alone
        self._spitch: dict[str, LivePitch] = {}

        self.main_stream = self.mon_stream = self.mic_stream = None
        self.rates = {"main": SR, "mon": SR, "mic": SR}
        self.errors: dict[str, str] = {}

        # the mic's clock is its own device's: drift tracking switches itself on if it
        # turns out to wander from the output's (see Ring.auto_drift)
        self.ring_main = Ring(auto_drift=True)
        self.ring_mon = Ring(auto_drift=True)
        self._rs_main = StreamResampler(SR, SR)
        self._rs_mon = StreamResampler(SR, SR)

        # internet radio (Radio tab): decoded by Qt Multimedia on the system clock,
        # which isn't the output devices' clock (up to ~1.5% apart), so these rings
        # track drift instead of glitching every few seconds. It arrives in bursty
        # chunks from the UI thread, so it gets a bigger cushion than the mic, and the
        # cushion grows when it runs dry. Its own volume and switches.
        self.radio_vol = 1.0
        self.radio_live = False       # radio -> others
        self.radio_monitor = True     # radio -> your headphones
        self.ring_rmain = Ring(prefill_s=0.1, max_s=0.6, track_drift=True, grow_to_s=0.3)
        self.ring_rmon = Ring(prefill_s=0.1, max_s=0.6, track_drift=True, grow_to_s=0.3)
        self._rs_rmain = StreamResampler(SR, SR)
        self._rs_rmon = StreamResampler(SR, SR)
        self._radio_heard = 0.0
        self.aux: tuple[AuxSource, ...] = ()   # captured programs (Apps tab), see AuxSource

        self.level_main = 0.0
        self.level_mic = 0.0
        self.level_mon = 0.0
        self.level_radio = 0.0
        # anything playing — sounds, the radio, captured programs — wherever it goes
        # (to others or only to your headphones), without your mic: the logo's cue
        self.level_play = 0.0

        self._rec_buf: list[np.ndarray] | None = None
        self._rec_frames_left = 0
        self.rec_done: tuple[np.ndarray, int] | None = None   # (audio, rate)
        self._mic_rec: list[np.ndarray] | None = None          # mic during a test (see _mic)
        # a copy of every block sent into the cable while set to a list (the voice chat
        # check compares it with what Discord plays back); None = off
        self.main_tap: list[np.ndarray] | None = None

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
        self._last_cb[key] = time.monotonic()
        try:
            s.start()
        except Exception:
            self._close_quietly(s, key)   # else every RETRY_S retry leaks a stream
            raise
        # committed only now, so a failed open leaves the rate and the rings alone.
        # Nothing plays on or writes to this output until its *_stream attribute is
        # set, so callbacks that run before this line render silence and do no harm.
        self._stream_opened(key)
        if rate != self.rates[key]:
            self.rates[key] = rate
            self._reconfigure_out(key)
        else:   # same rate: only drop what was queued for the old stream
            self._clear_out(key)
        self._resume_voices(key, rate)
        log.info("opened %s output: %s @ %d Hz (latency %s)", key, name, rate, self.latency)
        return s

    def _resume_voices(self, key: str, rate: int):
        """Output `key` was reopened: sounds still playing on the other output pick
        up here again, at the same spot (with a short fade in). Data made for
        another rate is useless, so those stay done."""
        with self.lock:
            for v in self.voices:
                if (key not in v.done or v.stopping or not len(v.data.get(key, ()))
                        or v.rates.get(key) != rate):
                    continue
                other = next((o for o in v.data if o != key and o not in v.done
                              and len(v.data[o])), None)
                if other is None:
                    continue
                d = v.data[other]
                frac = v.seek_to.get(other)
                if frac is None:
                    frac = (v.pos[other] % len(d)) / len(d)
                v.seek_to.pop(key, None)
                v.pos[key] = int(frac * len(v.data[key]))
                v.gate[key] = 0.0
                v.fading.discard(key)
                v.done.discard(key)   # last: the callback may render it from here on

    @staticmethod
    def _close_quietly(s, what):
        try:
            s.close()
        except Exception:  # noqa: BLE001
            log.debug("closing %s raised", what, exc_info=True)

    def _stream_opened(self, key):
        # callback errors are counted per stream from here: the first failure on the
        # new stream is logged and reported again (cb_errors stays a running total)
        self._cb_err_base[key] = self.cb_errors[key]

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

    def set_mic_device(self, name: str | None):
        self._close("mic_stream")
        self.errors.pop("mic", None)
        self.names["mic"] = name
        self._last_try["mic"] = time.monotonic()
        if name:
            idx = find_device("input", name)
            old_rate = self.rates["mic"]
            s = None
            try:
                if idx is None:
                    raise RuntimeError(f"device not found: {name}")
                rate = self._native_rate(idx)
                chans = min(2, sd.query_devices(idx)["max_input_channels"])
                s = sd.InputStream(device=idx, samplerate=rate, channels=chans, dtype="float32",
                                   latency=self.latency, callback=self._cb_mic)
                # the mic callback resamples with these from its first block, so they're
                # set before start (cheap: no ring is touched) and undone if it fails
                if rate != old_rate:
                    self.rates["mic"] = rate
                    self._reconfigure_mic_resamplers()
                self._last_cb["mic"] = time.monotonic()
                s.start()
                self._stream_opened("mic")
                self.mic_stream = s
                log.info("opened mic: %s @ %d Hz, %d ch", name, rate, chans)
            except Exception as e:  # noqa: BLE001
                log.warning("can't open mic %r: %s", name, e)
                self.errors["mic"] = str(e)
                if s is not None:
                    self._close_quietly(s, "mic")
                if self.rates["mic"] != old_rate:
                    self.rates["mic"] = old_rate
                    self._reconfigure_mic_resamplers()

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
        were touched (reopened, came back, or whose callback raised since the last
        check), so the UI can refresh its status from errors_snapshot()."""
        now = time.monotonic()
        touched = []
        for key, attr, setter in (("main", "main_stream", self.set_main_device),
                                  ("mon", "mon_stream", self.set_mon_device),
                                  ("mic", "mic_stream", self.set_mic_device)):
            n_err = self.cb_errors[key]
            if n_err != self._cb_err_seen[key]:
                self._cb_err_seen[key] = n_err
                touched.append(key)
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
        return list(dict.fromkeys(touched))

    def errors_snapshot(self) -> dict[str, str]:
        """A copy of `errors` that is safe to iterate. A failing audio callback adds
        to `errors` from its own thread, so iterating the live dict on the UI thread
        can raise "dictionary changed size during iteration". Copying a str-keyed
        dict never releases the GIL, so the copy itself can't be torn."""
        return dict(self.errors)

    def _reconfigure_mic_resamplers(self):
        r = self.rates
        self._rs_main = StreamResampler(r["mic"], r["main"])
        self._rs_mon = StreamResampler(r["mic"], r["mon"])

    def _reconfigure_out(self, key: str):
        """Rebuild what feeds output `key` for its (new) rate. Only that output's
        rings are reset: the other output plays on without a gap."""
        r = self.rates
        if key == "main":
            self._rs_main = StreamResampler(r["mic"], r["main"])
            self._rs_rmain = StreamResampler(SR, r["main"])
            rings = (self.ring_main, self.ring_rmain)
        else:
            self._rs_mon = StreamResampler(r["mic"], r["mon"])
            self._rs_rmon = StreamResampler(SR, r["mon"])
            rings = (self.ring_mon, self.ring_rmon)
        for ring in rings:
            ring.configure(r[key])
        for a in self.aux:
            a.configure(r, (key,))

    def _clear_out(self, key: str):
        """Drop everything queued for output `key` (its stream was reopened)."""
        if key == "main":
            rings = [self.ring_main, self.ring_rmain]
            rings += [a.ring_main for a in self.aux]
        else:
            rings = [self.ring_mon, self.ring_rmon]
            rings += [a.ring_mon for a in self.aux]
        for ring in rings:
            ring.clear()

    def _reconfigure_mic_paths(self):
        """Everything, for the current rates (resets both outputs' rings)."""
        self._reconfigure_mic_resamplers()
        self._reconfigure_out("main")
        self._reconfigure_out("mon")

    # ----------------------------------------------------------------- radio input
    def feed_radio(self, x: np.ndarray):
        """Push a chunk of radio audio ((n, 2) float32 at SR). Call from the UI thread."""
        lvl = peak(x)
        self.level_radio = max(lvl * self.radio_vol, self.level_radio)
        if lvl > 0.003:
            self._radio_heard = time.monotonic()
        if self.main_stream is not None:
            self.ring_rmain.write(self._rs_rmain(x))
        if self.mon_stream is not None:
            self.ring_rmon.write(self._rs_rmon(x))

    def radio_on_air(self) -> bool:
        """True while the radio is audibly going out to others (drives auto push-to-talk)."""
        return (self.radio_live and self.radio_vol > 0
                and time.monotonic() - self._radio_heard < 0.5)

    # ----------------------------------------------------------------- aux sources
    def add_aux(self, key) -> AuxSource:
        """A new pushed source (a captured program). Feed it with feed_aux from any
        one thread; remove_aux when done."""
        src = AuxSource(key, self.rates)
        with self.lock:
            self.aux = tuple(a for a in self.aux if a.key != key) + (src,)
        return src

    def remove_aux(self, key):
        with self.lock:
            self.aux = tuple(a for a in self.aux if a.key != key)

    def feed_aux(self, src: AuxSource, x: np.ndarray):
        """Push a chunk ((n, 2) float32 at SR) of a captured program's audio."""
        src.feed(x, self.main_stream is not None, self.mon_stream is not None)

    def aux_on_air(self) -> bool:
        """True while any captured program is audibly going out to others."""
        return any(a.on_air() for a in self.aux)

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
            if hit is not None:
                self._cache.move_to_end(key)
        # the cache holds a reference to the source array and compares identity with
        # `is`: comparing id() alone could match a *new* array that happens to be
        # allocated at a freed one's address (e.g. successive test recordings)
        if hit and hit[0] is data:
            return hit[1]
        if data.dtype == np.int16:   # library audio: resample in float, keep the copy compact
            out = resample(data.astype(np.float32) * I16_SCALE, src_rate, rate)
            out = np.clip(np.rint(out * 32767.0), -32768, 32767).astype(np.int16)
        else:
            out = resample(data, src_rate, rate)
        with self._cache_lock:
            old = self._cache.pop(key, None)
            if old is not None:
                self._cache_bytes -= old[1].nbytes
            self._cache[key] = (data, out)
            self._cache_bytes += out.nbytes
            while self._cache_bytes > CACHE_BUDGET and len(self._cache) > 1:
                _, (_, dropped) = self._cache.popitem(last=False)
                self._cache_bytes -= dropped.nbytes
        return out

    def prepare(self, sid: str, data: np.ndarray):
        """Pre-resample for the currently open outputs (call off the UI thread)."""
        for o in self.active_outputs():
            self.data_for(sid, data, self.rates[o])

    def forget(self, sid: str):
        with self._cache_lock:
            for k in [k for k in self._cache if k[0] == sid]:
                self._cache_bytes -= self._cache.pop(k)[1].nbytes

    # ----------------------------------------------------------------- playback
    def play(self, sid: str, data: np.ndarray, gain: float, loop=False, mode="restart",
             preview=False, src_rate: int = SR, start: float = 0.0,
             fade_in: float = 0.0, fade_out: float = 0.0,
             only: str | None = None) -> Voice | None:
        """mode: 'restart' (stop previous instance), 'overlap', 'toggle' (stop if playing),
        'solo' (stop every other sound, then restart this one).
        fade_in / fade_out (seconds): a rise from silence at the start; a fall to silence
        when it's stopped and, for a one-shot, over its last fade_out seconds.
        only: 'main' or 'mon' plays on that output alone (the voice chat check)."""
        outs = self.active_outputs()
        if only is not None:
            outs &= {only}
        if preview:
            # previews are for your ears only; with no headphone device open they must
            # not fall through to the cable (everyone in the call would hear them)
            outs = {"mon"} if "mon" in outs else set()
        if not outs:
            return None
        with self.lock:
            existing = [v for v in self.voices if v.sid == sid and not v.stopping]
            if mode in ("restart", "toggle", "solo"):
                for v in existing:
                    v.stopping = True
                if mode == "toggle" and existing:
                    return None
            if mode == "solo":   # other pads only: not previews, cues, TTS or checks
                for v in self.voices:
                    if (v.sid != sid and not v.preview and not v.sid.startswith("__")
                            and not is_fixed(v.sid)):
                        v.stopping = True
        rates_used = {o: self.rates[o] for o in outs}
        per_out = {o: self.data_for(sid, data, rates_used[o], src_rate) for o in outs}
        v = Voice(sid, per_out, gain, loop, preview=preview, rates=rates_used,
                  fade_in=max(0.0, float(fade_in)), fade_out=max(0.0, float(fade_out)),
                  fixed=is_fixed(sid), cut_share=destination.cut_shares(data, src_rate))
        if start > 0:
            v.seek(start)
            for o in v.data:     # not shared yet: apply it now, so progress() is right
                v._apply_seek(o)
        with self.lock:
            # an output closed or reopened at another rate while we resampled: its
            # data is useless, and a voice waiting on it would never finish
            live = self.active_outputs()
            for o in v.data:
                if o not in live or self.rates[o] != rates_used[o]:
                    v.done.add(o)
            if v.finished:
                return None
            self.voices = self.voices + (v,)
        return v

    def stop(self, sid: str):
        with self.lock:
            for v in self.voices:
                if v.sid == sid:
                    v.stopping = True

    def stop_all(self):
        """Stop everything now: the panic button skips the sounds' own fade-outs."""
        with self.lock:
            for v in self.voices:
                v.fade_out = 0.0
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
            # a stopped sound still fading out is still being heard
            return any(not v.finished and not v.preview and not v.paused
                       and not (v.stopping and not any(v.gate.values()))
                       for v in self.voices)

    # ----------------------------------------------------------------- test record
    def start_test_record(self, seconds: float):
        self.rec_done = None
        self._rec_frames_left = int(seconds * self.rates["main"])
        self._mic_rec = [] if self.mic_stream is not None else None
        self._rec_buf = []

    def cancel_test_record(self):
        """Give up on a test recording (its output device stopped mid-way)."""
        self._rec_buf = None      # first: the main callback checks it before finishing
        self._rec_frames_left = 0
        self._mic_rec = None
        self.rec_done = None

    def take_mic_recording(self) -> tuple[np.ndarray, int] | None:
        """The mic captured during the last test, at the mic's rate: (n, 2) with the
        raw mic in column 0 and the mic as sent (after the voice changer) in column 1,
        which is what testcheck.analyze looks for in the output."""
        rec, self._mic_rec = self._mic_rec, None
        if not rec:
            return None
        return np.concatenate(rec), self.rates["mic"]

    @property
    def recording(self) -> bool:
        return self._rec_buf is not None

    # ----------------------------------------------------------------- callbacks
    def _render(self, out: str, frames: int, previews_only=False,
                fixed=False) -> np.ndarray:
        """Mix the voices playing on `out`: the sounds (at the live speed) or, with
        `fixed`, the app's own playback (always at speed 1)."""
        buf = np.zeros((frames, CH), np.float32)
        silent = None   # scratch for voices that must advance but not be heard
        fade = int(FADE_S * self.rates[out])
        speed = 1.0 if fixed else float(self.sound_speed)
        # no lock: `self.voices` is an immutable tuple swapped atomically by the UI side
        voices = [v for v in self.voices
                  if v.fixed == fixed and out in v.data and out not in v.done]
        for v in voices:
            if v.seek_to:
                v._apply_seek(out)
            if not len(v.data[out]):   # nothing to play (even looped): it's over
                v.done.add(out)
                continue
            if previews_only and not v.preview:
                if silent is None:
                    silent = np.zeros((frames, CH), np.float32)
                dst = silent
            else:
                dst = buf
            data = v.data[out]
            n = len(data)
            p = v.pos[out]
            # int16 library audio is scaled here (one multiply that already happens
            # for the gain); float32 is used by cues, previews of test recordings…
            g = np.float32(v.gain) * (I16_SCALE if data.dtype == np.int16 else np.float32(1))
            dest = self.dest
            if dest is not None and dest.lowcut:
                g = g * np.float32(v.makeup(dest.lowcut))
            g0 = v.gate[out]
            rate = self.rates[out]
            if v.stopping:  # fade out (10 ms, or the sound's own fade-out), then done
                if g0 <= 0.0 or v.paused or not n:
                    v.done.add(out)
                    continue
                target, ramp = 0.0, max(fade, int(v.fade_out * rate))
            else:
                target = 0.0 if v.paused else 1.0
                if g0 == 0.0 and target == 0.0:
                    continue  # paused: hold position, output nothing
                # the start's fade-in; pause, resume and seek take 10 ms
                ramp = int(v.fade_in * rate) if out in v.fading and target else fade
            # a one-shot's fade-out before its natural end
            tail = int(v.fade_out * rate) if v.fade_out > 0 and not v.loop else 0
            p_start = float(p)
            near_end = tail and n - p_start < tail + frames * max(speed, 1.0) + 1
            shaped = g0 != target or near_end
            if shaped:
                dst_final = dst
                dst = np.zeros((frames, CH), np.float32)
            if abs(speed - 1.0) < 1e-4:
                p = int(p)
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
            else:
                p = self._render_speed(dst, data, float(p), speed, g, v.loop)
            v.pos[out] = p
            if shaped:
                if g0 != target:   # a straight line from g0 towards target, `ramp` long
                    step = np.float32(1.0 / max(ramp, 1)) * (1 if target > g0 else -1)
                    env = g0 + step * np.arange(1, frames + 1, dtype=np.float32)
                    env = np.clip(env, min(g0, target), max(g0, target))
                    v.gate[out] = float(env[-1])
                    if v.gate[out] == target:
                        v.fading.discard(out)
                else:
                    env = np.full(frames, target, np.float32)
                if near_end:
                    at = p_start + speed * np.arange(frames, dtype=np.float32)
                    env = env * np.clip((n - at) / tail, 0.0, 1.0)
                dst_final += dst * env[:, None]
                if v.stopping and v.gate[out] <= 0.0:
                    v.done.add(out)
            if p >= n and not v.loop:
                v.done.add(out)
        return buf

    @staticmethod
    def _render_speed(dst, data, p: float, speed: float, g, loop: bool):
        """Add `data` read from position p at `speed` (linear interpolation) into
        dst; returns the new position (len(data) once a one-shot has ended)."""
        n = len(data)
        if n < 2:
            return n
        pos = p + speed * np.arange(len(dst), dtype=np.float64)
        if loop:
            pos %= n
            i = pos.astype(np.int64)
            h, j, k = (i - 1) % n, (i + 1) % n, (i + 2) % n
        else:
            m = int(np.searchsorted(pos, n - 1))   # frames before the end
            pos = pos[:m]
            i = pos.astype(np.int64)
            h, j, k = np.maximum(i - 1, 0), i + 1, np.minimum(i + 2, n - 1)
        f = (pos - i).astype(np.float32)[:, None]
        p0, p1, p2, p3 = (data[x].astype(np.float32) for x in (h, i, j, k))
        if not loop:   # past either end: continue the line (a ramp stays a ramp)
            first, last = i == 0, i + 2 > n - 1
            p0[first] = 2 * p1[first] - p2[first]
            p3[last] = 2 * p2[last] - p1[last]
        dst[:len(pos)] += hermite(p0, p1, p2, p3, f) * g
        p += speed * len(dst)
        if loop:
            return p % n
        return p if p < n - 1 else n

    def _sounds(self, out: str, frames: int, previews_only=False) -> np.ndarray:
        """The sounds bus: sounds at the live speed through the live pitch, plus the
        app's own playback (fixed voices) as it is."""
        mix = self._pitch(out, self._render(out, frames, previews_only))
        if any(v.fixed for v in self.voices):
            mix += self._render(out, frames, previews_only, fixed=True)
        return mix

    def _pitch(self, out: str, x: np.ndarray) -> np.ndarray:
        """Live pitch on the sounds bus: the user's shift, plus the correction that
        undoes the speed's pitch change when keep-pitch is on."""
        st = float(self.sound_pitch)
        if self.sound_keep_pitch and abs(self.sound_speed - 1.0) >= 1e-4:
            st -= 12.0 * float(np.log2(max(self.sound_speed, 1e-3)))
        f = self._spitch.get(out)
        if f is None or f.rate != self.rates[out]:   # made at 0 st too: it needs the history
            f = self._spitch[out] = LivePitch(self.rates[out])
        return f.process(x, st)   # at 0 st it only keeps its history fresh

    def _eq(self, out: str, part: str, x: np.ndarray) -> np.ndarray:
        """Run x through the EQ if it's on and aimed at `part` ('sounds' / 'voice')."""
        g = self.eq_gains
        key = (out, part)
        if g is None or self.eq_target not in (part, "all"):
            self._eqs.pop(key, None)   # stale filter state would click when it's back on
            return x
        f = self._eqs.get(key)
        if f is None or f.rate != self.rates[out]:
            f = self._eqs[key] = EQ(self.rates[out])
        return f.process(x, g)

    def _stage(self, out: str, kind: type):
        """This output's Limiter / SmartMono / Ducker, made for its current rate."""
        key = (out, kind.__name__)
        f = self._send.get(key)
        if f is None or f.rate != self.rates[out]:
            f = self._send[key] = kind(self.rates[out])
        return f

    def _dest(self, out: str, x: np.ndarray) -> np.ndarray:
        """Shape the sounds bus for whoever is listening (soundboard.destination)."""
        d = self.dest
        if d is None:
            self._dests.pop(out, None)   # start fresh when it's turned back on
            return x
        f = self._dests.get(out)
        if f is None or f.rate != self.rates[out]:
            f = self._dests[out] = destination.Processor(self.rates[out])
        return f.process(x, d)

    # Each PortAudio callback is a thin guard around the real work: an exception that
    # escapes a callback makes PortAudio abort the stream for good, silently. Here it
    # is logged (once per opened stream, so the audio thread never does repeated file
    # I/O), counted, and the block is left silent. check_streams() reports the key.
    def _guard(self, key: str, exc: BaseException):
        self.cb_errors[key] += 1
        if self.cb_errors[key] - self._cb_err_base[key] == 1:
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
        mix = self._sounds("main", frames)
        mix *= np.float32(self.sound_vol)
        play = peak(mix)
        r = self.ring_rmain.read(frames)
        if r is not None:
            play = max(play, peak(r) * self.radio_vol)
            if self.radio_live:
                mix += r * np.float32(self.radio_vol)
        for a in self.aux:
            x = a.ring_main.read(frames)
            if x is not None:
                play = max(play, peak(x) * a.vol)
                if a.live:
                    mix += x * np.float32(a.vol)
        self.level_play = max(play, self.level_play * 0.85)
        mix = self._send_bus("main", finite(mix), self.ring_main.read(frames))
        if not self.sending:      # muted: others get silence, nothing else changes
            mix.fill(0)
        if self.limiter_on:
            mix = self._stage("main", Limiter).process(mix)
        soft_limit(mix)
        outdata[:] = mix
        self.level_main = max(peak(mix), self.level_main * 0.85)
        tap = self.main_tap
        if tap is not None:
            tap.append(mix.copy())
        rec = self._rec_buf   # read once: cancel_test_record may clear it meanwhile
        if rec is not None:
            rec.append(mix.copy())
            self._rec_frames_left -= frames
            if self._rec_frames_left <= 0 and self._rec_buf is rec:   # not cancelled
                self._rec_buf = None
                self.rec_done = (np.concatenate(rec), self.rates["main"])

    def _mon(self, outdata, frames):
        check = self.mic_check and self.sending   # muted: they hear nothing, so neither do you
        # in mic check you hear the real output mix: sounds at their outgoing
        # level plus your mic, so you can judge the balance while a song plays
        mix = self._sounds("mon", frames, previews_only=not (check or self.monitor_sounds))
        m = self.ring_mon.read(frames)
        if check:
            mix *= np.float32(self.sound_vol)
        play = peak(mix)   # the main output sees the rest; this one counts with no cable too
        r = self.ring_rmon.read(frames)
        if r is not None:
            play = max(play, peak(r) * self.radio_vol)
            if self.radio_monitor or (check and self.radio_live):
                mix += r * np.float32(self.radio_vol)
        for a in self.aux:
            x = a.ring_mon.read(frames)
            if x is not None:
                play = max(play, peak(x) * a.vol)
                if a.monitor or (check and a.live):
                    mix += x * np.float32(a.vol)
        self.level_play = max(play, self.level_play)   # _main decays it; no main: the UI does
        finite(mix)
        if check:   # you hear what others get: the same send stage, your mic in it
            mix = self._send_bus("mon", mix, m)
        else:
            mix = self._dest("mon", self._eq("mon", "sounds", mix))
        mix *= np.float32(self.mon_vol)
        soft_limit(mix)
        outdata[:] = mix
        self.level_mon = max(peak(mix), self.level_mon * 0.85)

    def _send_bus(self, out: str, mix: np.ndarray, m: np.ndarray | None) -> np.ndarray:
        """The sounds bus shaped for voice chat (EQ, destination mode, ducking under
        your voice, phase-aware mono), with the mic block `m` added on top."""
        mic_on = m is not None and self.mic_enabled and not self.mic_muted
        mix = self._dest(out, self._eq(out, "sounds", mix))
        if self.duck_db < 0 or (out, "Ducker") in self._send:
            g = self._stage(out, Ducker).process(m if mic_on else None, len(mix), self.duck_db)
            if not isinstance(g, float):
                mix = mix * g
        if self.send_mono:
            mix = self._stage(out, SmartMono).process(mix)
        if mic_on:
            m = self._gated(out, m)
            mix += self._eq(out, "voice", m * np.float32(self.mic_vol))
        return mix

    GATE_S = 0.04    # how fast the mic fades out / back in around a sound

    def _gated(self, out: str, m: np.ndarray) -> np.ndarray:
        """The mic block, faded out while a sound is going out on `out` (mic_gate)."""
        g0 = self._gate.get(out, 1.0)
        if not self.mic_gate and g0 >= 1.0:
            return m
        playing = self.mic_gate and any(
            out in v.data and not v.preview and not v.paused and not v.finished
            for v in self.voices)
        target = 0.0 if playing else 1.0
        step = len(m) / (self.GATE_S * max(self.rates.get(out, SR), 1))
        g1 = max(g0 - step, target) if target < g0 else min(g0 + step, target)
        self._gate[out] = g1
        if g0 >= 1.0 and g1 >= 1.0:
            return m
        return m * np.linspace(g0, g1, len(m), dtype=np.float32)[:, None]

    def _mic(self, indata):
        x = indata
        x = np.repeat(x, 2, axis=1) if x.shape[1] == 1 else x[:, :2]
        x = np.ascontiguousarray(x, dtype=np.float32)
        self.level_mic = max(peak(x), self.level_mic * 0.85)
        rec = self._mic_rec
        raw = x[:, 0].copy() if rec is not None and self._rec_buf is not None else None
        chain = self.voice_chain
        if chain is not None:   # after the meter: that judges the real mic
            x = chain.process(x, self.rates["mic"])
        if raw is not None:     # a test: the real mic (did you talk?) and what's sent
            rec.append(np.stack([raw, x[:, 0]], 1))
        if self.main_stream is not None:
            self.ring_main.write(self._rs_main(x))
        if self.mic_check and self.mon_stream is not None:
            self.ring_mon.write(self._rs_mon(x))
