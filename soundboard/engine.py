"""Real-time audio engine.

Three WASAPI streams, each opened at its device's *native* rate (Windows'
built-in resampler, auto_convert, audibly garbles audio — measured ~70% junk on
VB-Cable — so all rate conversion is done here with soxr instead):

  mic  (input)  -> streaming resampler -> ring buffers -> main / monitor
  radio   (48 kHz, pushed from the UI thread) -> resampler -> ring buffers -> main / monitor
  aux     (48 kHz, pushed from a capture thread: one per captured program, Apps tab)
          -> the same path again, each with its own rings, volume and switches
  main (output) = sounds + radio / programs (when live) + mic -> the send device: a virtual
                  cable or any other output you picked (what others hear)
  mon  (output) = sounds + radio / programs [+ mic in test mode] -> your headphones
  obs  (output, optional) = sounds + radio / programs (when live) [+ mic] -> a device
       OBS captures: what others get, without the voice chat shaping, as its own track

Sounds are stored at SR and resampled (cached) to each output's rate. Every
playing Voice keeps its own position per output, so the two output devices
run on independent clocks without drift or glitches.

Live speed / pitch (the ⏩ controls): sounds play at `sound_speed` by reading
their data at a fractional rate (like a tape), and a pitch shifter on the sounds
bus corrects the pitch back (`sound_keep_pitch`) and adds `sound_pitch`. The
app's own playback (test recording, cue beeps, the setup tune, previews) is
`fixed`: played at speed 1 and mixed in after the pitch shifter. The live
effects (`sound_fx`: bass, reverb, echo… soundboard.livefx) come after the pitch.
Per-sound effects are baked in ahead of time instead (soundboard.soundfx).
"""
from __future__ import annotations

import logging
import threading
import time
import weakref
from collections import OrderedDict
from dataclasses import dataclass, field

import numpy as np
import sounddevice as sd
import soxr

from soundboard import destination, directmic, livefx, mapped, sharestore
from soundboard.dsp import hermite
from soundboard.eq import EQ
from soundboard.sendfx import Ducker, Limiter, SafetyLimiter, SmartMono
from soundboard.voicefx.builtin import PitchShift
from soundboard import errors

log = logging.getLogger(__name__)

SR = 48000  # library storage rate
CH = 2
FADE_S = 0.010  # fade when a sound is stopped early (no clicks)
STALL_S = 1.5   # a stream whose callback hasn't run for this long is dead: reopen it
RETRY_S = 5.0   # how often to retry a device that failed to open
# What each Audio buffering choice asks PortAudio for. Windows' shared mode never goes
# below its own 10 ms period, so 'low' and PortAudio's 'high' (10 ms) both came out as
# 22 ms with ~10 ms to spare per block; asking for a number buys real room.
BUFFER = {"low": "low", "high": 0.04}
I16_SCALE = np.float32(1 / 32767.0)   # int16 sound data -> float
CACHE_BUDGET = 192 << 20               # bytes of resampled copies kept for non-48 kHz devices
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


def list_name(index: int) -> str:
    """A device's name as the device lists show it."""
    return sd.query_devices(index)["name"]


def find_device(kind: str, name: str | None) -> int | None:
    if not name:
        return None
    devs = list_devices(kind)
    for d in devs:
        if d["name"] == name:
            return d["index"]
    squash = " ".join(name.split()).lower()   # Windows' own name may space it differently
    for d in devs:
        if " ".join(d["name"].split()).lower() == squash:
            return d["index"]
    for d in devs:  # loose match (device renamed / number changed)
        if name.lower() in d["name"].lower() or d["name"].lower() in name.lower():
            return d["index"]
    return None


# Virtual audio cables (VB-Cable, VB-Cable A/B, Hi-Fi Cable, Voicemeeter, …) show up
# as a playback device ("... Input") paired with a recording device ("... Output").
# Audio played into the first comes out of the second, which apps use as a mic.
# Not plain "virtual": real USB headsets are called e.g. "Speakers (HyperX Virtual
# Surround Sound)", and matching that hid a tester's headset from every device list.
VIRTUAL_HINTS = ("cable", "vb-audio", "voicemeeter", "virtual audio cable")


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


def same_cable(a: str | None, b: str | None) -> bool:
    """Are `a` and `b` playback ends of one virtual cable? VB-Cable lists "CABLE Input"
    and "CABLE In 16ch" (both "(VB-Audio Virtual Cable)"), and both come out of the
    same "CABLE Output": the product name in brackets tells cables apart."""
    if not (a and b and is_virtual(a) and is_virtual(b)):
        return False
    if a == b:
        return True
    pa, pb = (n[n.rfind("("):].lower() if "(" in n else None for n in (a, b))
    return pa is not None and pa == pb


def virtual_outputs() -> list[str]:
    """Playback devices that are virtual cables, best (has a mic side) first."""
    outs = [d["name"] for d in list_devices("output") if is_virtual(d["name"])]
    return sorted(outs, key=lambda n: virtual_mic_for(n) is None)


def resample(data: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst or not len(data):
        return data
    return np.ascontiguousarray(soxr.resample(data, src, dst, quality="VHQ"), dtype=np.float32)


# --------------------------------------------------------------------------- helpers

# A loop's end is crossfaded into its start over this long, so a loop not cut at a zero
# crossing doesn't tick on every pass. After the first pass it plays [xf, n): the
# blended end leads straight on from the start's xf-th frame, no gap and no jump.
LOOP_XF_S = 0.005


def loop_xf(n: int, rate: int) -> int:
    """The loop crossfade, in frames, for a sound of n frames (0: too short for one)."""
    xf = int(LOOP_XF_S * rate)
    return xf if n > 4 * xf else 0


def loop_wrap(p, n: int, xf: int):
    """A position that ran past the end of a loop, brought back into [xf, n)."""
    return p if p < n else xf + (p - xf) % (n - xf)


def span(data: np.ndarray, k0: int, k1: int, loop: bool, xf: int = 0) -> np.ndarray:
    """Frames k0..k1 of `data` as float32 (not scaled), counted along the sound as it
    plays: a one-shot is silent before its start and after its end; a loop wraps, with
    its end crossfaded into its start over `xf` frames (see LOOP_XF_S)."""
    n = len(data)
    if not loop:
        out = np.zeros((k1 - k0,) + data.shape[1:], np.float32)
        a, b = max(k0, 0), min(k1, n)
        if a < b:
            out[a - k0:b - k0] = data[a:b]
        return out
    head = n - xf   # where the blend into the start begins
    if 0 <= k0 and k1 <= head:
        return data[k0:k1].astype(np.float32)
    k = np.arange(k0, k1)
    r = np.where(k < xf, k, xf + (k - xf) % head)
    out = data[np.maximum(r, 0)].astype(np.float32)
    if xf:
        m = r >= head
        if m.any():
            a = ((r[m] - head) / xf).astype(np.float32)[:, None]
            out[m] += (data[r[m] - head].astype(np.float32) - out[m]) * a
    out[k < 0] = 0
    return out


# Speeding a sound up reads it faster than it was made: anything above the output's
# Nyquist / speed would fold back down as metallic hash (cymbals, "s" sounds). A
# windowed-sinc lowpass takes it out first. Linear phase, centred: no delay, and
# stateless, so seeks, loops and speed changes need nothing special.
AA_DB = 70.0


def _aa_taps(speed: float) -> np.ndarray:
    """Lowpass for reading at `speed` (> 1): flat to 0.4 / speed (19 kHz heard at
    48 kHz), AA_DB down from 0.6 / speed (what would fold back under ~19 kHz)."""
    key = round(speed, 3)
    h = _AA_CACHE.get(key)
    if h is None:
        width = 0.2 / key                                  # cycles per source frame
        beta = 0.1102 * (AA_DB - 8.7)
        taps = int(np.ceil((AA_DB - 8) / (2.285 * 2 * np.pi * width))) | 1
        t = np.arange(taps) - taps // 2
        h = (np.sinc(t / key) / key * np.kaiser(taps, beta)).astype(np.float32)
        h /= h.sum()
        if len(_AA_CACHE) > 64:
            _AA_CACHE.clear()
        _AA_CACHE[key] = h
    return h


_AA_CACHE: dict[float, np.ndarray] = {}

# A sound that starts away from zero (a clip trimmed mid-waveform, a start position
# part-way in) would jump from silence to that level: a pop. It rises over this instead,
# too short to soften a drum hit.
START_FADE_S = 0.002


def _hard_start(data: np.ndarray) -> bool:
    """True if `data` begins far enough from zero to pop (about -34 dBFS)."""
    if not len(data):
        return False
    lim = 650 if data.dtype == np.int16 else 0.02
    return bool(np.max(np.abs(data[0].astype(np.float32))) > lim)


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
    # auto_drift's early estimate: the writer's frames against the reader's, fitted
    # every EST_CHECK_S once there are EST_MIN_S of them. Tracking starts after two fits
    # in a row say the same side, by at least DRIFT_MIN and well beyond their own noise
    # (a ring that is on time never starts: no stretching, no pitch wobble).
    EST_CHECK_S, EST_MIN_S, EST_MAX_S = 1.0, 2.0, 30.0
    DRIFT_MIN = 0.00005
    MIC_KP, MIC_KI = 0.004, 0.000005   # the mic rings' drift controller (see _mic_err)

    def __init__(self, rate: int = SR, prefill_s: float = 0.015, max_s: float = 0.08,
                 track_drift: bool = False, grow_to_s: float = 0.0, auto_drift: bool = False):
        self.lock = threading.Lock()
        self.prefill_s, self.max_s = prefill_s, max_s
        self.track_drift = track_drift
        # auto_drift: start without drift tracking, and switch it on as soon as the
        # writer's clock is measured to be off (a wireless headset's mic or a USB
        # interface against the output clock), before the ring ever runs dry or
        # skips; failing that, once it has had to skip or refill twice
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
            self.rate = rate
            self._est_reset()

    def _est_reset(self):
        """Start the clock estimate over (a gap, a skip, a restart: the old fit is moot)."""
        self._wrote = 0          # frames written since the estimate started
        self._ex = 0             # frames read since then (the reader's clock)
        self._sums = [0.0] * 6   # n, Σx, Σd, Σxx, Σxd, Σdd with d = written - read
        self._est_next = int(self.rate * self.EST_MIN_S)
        self._est_side = 0       # the side the last fit came out on (+1 fast, -1 slow)
        self.drift_est = 1.0     # the last fit's writer/reader clock ratio

    def _mic_err(self, n: int) -> float:
        """The drift controller's error for a mic ring, aimed at the fill a read finds
        right after priming: the cushion plus the read (aimed at the bare cushion, it
        read the ring dry again and again: the mic's is only 1.5 blocks). The fill a
        read finds swings by a whole block as the two clocks' blocks slide past each
        other (every 20 s at 0.05% apart), so the mic's gains are gentler than the
        radio's: with those it wobbled by up to 1% (now 0.05%, 0.35% at worst). (Averaging
        the fill instead lags the loop, and it swings.) The integral is slow (MIC_KI):
        tracking often starts with the fill at the top of that swing, and a faster one
        took it for drift and wound up to 4x the real offset, reading the ring dry (a
        0.2% fast mic clicked ~10 s in, in half the runs). The seed and kp carry the
        start; the integral only trims what's left, over ~30 s."""
        aim = self.prefill + n
        return min(max((self.count - aim) / aim, -1.0), 1.0)   # (np.clip: ~5 us a number)

    def _estimate(self, n: int):
        """After a read of n frames: fit the writer's clock against the reader's and
        switch drift tracking on, seeded with the fit, once it's clearly off."""
        self._ex += n
        x, d = float(self._ex), float(self._wrote - self._ex)
        sm = self._sums
        sm[0] += 1
        sm[1] += x
        sm[2] += d
        sm[3] += x * x
        sm[4] += x * d
        sm[5] += d * d
        if self._ex < self._est_next:
            return
        self._est_next = self._ex + int(self.rate * self.EST_CHECK_S)
        k, sx, sd, sxx, sxd, sdd = sm
        vxx, vxd, vdd = sxx - sx * sx / k, sxd - sx * sd / k, sdd - sd * sd / k
        if k < 8 or vxx <= 0:
            return
        slope = vxd / vxx                                 # writer/reader ratio - 1
        se = (max(vdd - slope * vxd, 0.0) / (k - 2) / vxx) ** 0.5
        self.drift_est = 1.0 + slope
        side = (slope > 0) - (slope < 0)
        if abs(slope) < max(self.DRIFT_MIN, 6 * se):
            side = 0
        if side and side == self._est_side:
            lim = self.DRIFT_MAX
            self._integ = min(max(slope, -lim), lim)   # read at the writer's pace
            self.track_drift = True
        self._est_side = side
        if self._ex >= self.rate * self.EST_MAX_S:   # on time so far: start a fresh fit
            self._est_reset()

    def _glitched(self):
        """Count toward switching drift tracking on (auto_drift)."""
        self._est_reset()
        if self.auto_drift and not self.track_drift and self.underruns + self.overflows >= 2:
            self.track_drift = True

    def clear(self):
        with self.lock:
            self.r = self.w = self.count = 0
            self.primed = False
            self._fade_in = True
            self._est_reset()

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
            if self.primed:
                self._wrote += n
            if self.count > self.max_fill:   # (always so once unread frames were overwritten)
                # keep the newest `prefill` frames: they end at w (r + count only
                # equals w if nothing unread was overwritten, so count back from w)
                self.r = (self.w - self.prefill) % self.cap
                self.count = self.prefill
                self.overflows += 1
                self._glitched()
                self._fade_in = True

    def read(self, n: int) -> np.ndarray | None:
        with self.lock:
            if not self.primed:
                if self.count < self.prefill + n:
                    return None
                self.primed = True
                self._fade_in = True
                self._est_reset()
            m = n
            if self.track_drift:
                # PI control: the integral learns the steady clock offset, so the fill
                # settles back at the full prefill cushion instead of hovering near empty
                lim = self.DRIFT_MAX
                if self.auto_drift:
                    err, kp, ki = self._mic_err(n), self.MIC_KP, self.MIC_KI
                else:
                    err = min(max((self.count - self.prefill) / max(self.prefill, 1),
                                  -1.0), 1.0)
                    kp, ki = lim * 0.5, 0.0002
                self._integ = min(max(self._integ + err * ki, -lim), lim)
                want = 1.0 + min(max(err * kp + self._integ, -lim), lim)
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
            if self.auto_drift and not self.track_drift:
                self._estimate(n)
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


class DirectFifo:
    """The clean mic on its way to what others hear, in "straight into my mic" mode.
    Writer and reader run on the same clock (the mic's) one right after the other, so
    unlike Ring there's no cushion: a read takes what's there. Short (a resampler's
    start-up delay), it's padded once with silence at the front; then every read finds
    what it needs.

    One write can be many reads long: when the board's thread wakes late it takes all
    the mic that came in meanwhile (40 ms, 100 ms...) and renders the same stretch in
    10 ms reads. That's all audio still to be sent, never a pile-up; dropping it there
    cut 20-40 ms holes out of the voice whenever the PC was busy. Only what's left over
    from earlier writes and never read (a stall) is stale: over MAX_S, it's dropped when
    the next write comes in."""

    MAX_S = 0.03

    def __init__(self, rate: int = SR):
        self.rate = rate
        self.parts: list[np.ndarray] = []
        self.count = 0

    def clear(self):
        self.parts, self.count = [], 0

    def write(self, x: np.ndarray):
        if not len(x):
            return
        if self.count > self.MAX_S * self.rate:   # a stall's leftovers: too late to send
            self.clear()
        self.parts.append(x)
        self.count += len(x)

    def read(self, n: int) -> np.ndarray | None:
        if not self.count:
            return None
        buf = self.parts[0] if len(self.parts) == 1 else np.concatenate(self.parts)
        if len(buf) >= n:
            out, rest = buf[:n], buf[n:]
        else:
            out = np.zeros((n, buf.shape[1]), np.float32)
            out[n - len(buf):] = buf
            rest = buf[:0]
        self.parts = [rest] if len(rest) else []
        self.count = len(rest)
        return out


class CableTap:
    """Straight into my mic, and the virtual cable too: a copy of what others hear is
    played into the cable, so a voice app still set to the cable's far end keeps
    hearing everything. The send mix is made on the mic's clock and the cable plays on
    its own, so it goes through a Ring that tracks the drift between them."""

    def __init__(self, name: str, latency="low"):
        idx = find_device("output", name)
        if idx is None:
            raise RuntimeError(f"device not found: {name}")
        self.name = name
        self.rate = int(sd.query_devices(idx)["default_samplerate"])
        self.ring = Ring(self.rate, prefill_s=0.03, max_s=0.2, auto_drift=True)
        self._rs = StreamResampler(SR, self.rate)
        self.last_cb = time.monotonic()
        self.stream = sd.OutputStream(device=idx, samplerate=self.rate, channels=CH,
                                      dtype="float32", latency=latency, callback=self._cb)
        self.stream.start()

    def write(self, mix: np.ndarray):
        self.ring.write(self._rs(mix))

    def _cb(self, outdata, frames, t, status):
        self.last_cb = time.monotonic()
        x = self.ring.read(frames)
        if x is None:
            outdata.fill(0)
        else:
            outdata[:] = x

    def close(self):
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:  # noqa: BLE001 - a device that's gone
            log.debug("closing the cable tap raised", exc_info=True)


class StreamResampler:
    """Chunk-by-chunk resampler for live mic audio (identity when rates match)."""

    def __init__(self, src: int, dst: int):
        self.same = src == dst
        self.src, self.dst = src, dst
        self.rs = None if self.same else soxr.ResampleStream(src, dst, CH, dtype="float32",
                                                              quality="HQ")
        self.fed = self.made = 0   # frames in (at src) and out (at dst) so far

    def __call__(self, x: np.ndarray) -> np.ndarray:
        if self.same:
            return x
        y = self.rs.resample_chunk(x)
        self.fed += len(x)
        self.made += len(y)
        return y

    def held(self) -> float:
        """Frames (at dst) it has taken in but not given out yet: its delay."""
        return 0.0 if self.same else max(0.0, self.fed * self.dst / self.src - self.made)


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
    """Stereo real-time pitch shifter (a voicefx PitchShift on both channels at once,
    spliced at the same places: see its `channels`). Keeps its recent input while
    bypassed, so switching it on or off crossfades instead of dropping out for its
    latency."""

    def __init__(self, rate: int):
        self.rate = rate
        self.shift = PitchShift(rate, channels=CH)
        self._st = 0.0

    def process(self, x: np.ndarray, semitones: float) -> np.ndarray:
        if semitones != self._st:
            self._st = semitones   # set directly: past the voice changer's ±12 limit
            self.shift.p = {"semitones": float(semitones), "mix": 1.0}
        return self.shift.run(x, self.rate)

    def skip_silence(self, n: int):
        """What n frames of silence at 0 st would have done (only kept as history)."""
        h = self.shift.hist
        self.shift._remember(np.zeros((min(n, len(h)), CH), np.float32))


# --------------------------------------------------------------------------- voices

class AuxSource:
    """A pushed 48 kHz stereo source with its own rings, volume and switches: one
    per program captured by the Apps tab. Pushed from the capture's own thread (a
    ring has one writer), read by the output callbacks. Comes and goes at runtime:
    Engine.aux is a tuple replaced under the lock, like the voices."""

    MAKEUP_WINDOW_S = 4.0   # how much of its recent audio the make-up is measured on
    MAKEUP_EVERY_S = 2.0    # ...and how often

    def __init__(self, key, rates: dict | None = None):
        self.key = key
        self.vol = 1.0
        self.live = True        # -> others (the whole point of capturing a program)
        self.stream = True      # -> the stream output (Apps tab: Call + stream / Stream only)
        self.monitor = False    # -> your headphones (the program already plays there)
        self.level = 0.0
        # the program's audio clock is its device's, not ours: track drift; and a
        # program that goes quiet stops sending at all, so start again quickly
        self.ring_main = Ring(prefill_s=0.05, max_s=0.6, track_drift=True, grow_to_s=0.25)
        self.ring_mon = Ring(prefill_s=0.05, max_s=0.6, track_drift=True, grow_to_s=0.25)
        self.ring_obs = Ring(prefill_s=0.05, max_s=0.6, track_drift=True, grow_to_s=0.25)
        self._rs_main = StreamResampler(SR, SR)
        self._rs_mon = StreamResampler(SR, SR)
        self._rs_obs = StreamResampler(SR, SR)
        self._heard = 0.0
        # the power each destination low cut takes from it (destination.cut_shares),
        # measured on its last few seconds now and then: its make-up gain, as a
        # sound's (Voice.makeup), so a bass-heavy song isn't quieter sent this way
        self.cut_share: dict = {}
        self._hist = np.zeros((int(SR * self.MAKEUP_WINDOW_S), CH), np.float32)
        self._hist_w = self._hist_n = self._since = 0
        self._gain: dict = {}   # out -> the make-up gain it's gliding at
        if rates:
            self.configure(rates)

    def configure(self, rates: dict, outs=("main", "mon", "obs")):
        if "main" in outs:
            self._rs_main = StreamResampler(SR, rates["main"])
            self.ring_main.configure(rates["main"])
        if "mon" in outs:
            self._rs_mon = StreamResampler(SR, rates["mon"])
            self.ring_mon.configure(rates["mon"])
        if "obs" in outs and "obs" in rates:
            self._rs_obs = StreamResampler(SR, rates["obs"])
            self.ring_obs.configure(rates["obs"])

    def feed(self, x: np.ndarray, main: bool, mon: bool, obs: bool = False):
        lvl = peak(x)
        if not np.isfinite(lvl):   # a program's capture can hand over a broken block
            x = finite(np.array(x, dtype=np.float32))
            lvl = peak(x)
        self.level = max(lvl * self.vol, self.level)
        if lvl > 0.003:
            self._heard = time.monotonic()
        if main:
            self._measure(x)
        if main:
            self.ring_main.write(self._rs_main(x))
        if mon:
            self.ring_mon.write(self._rs_mon(x))
        if obs:
            self.ring_obs.write(self._rs_obs(x))

    def on_air(self) -> bool:
        return self.live and self.vol > 0 and time.monotonic() - self._heard < 0.5

    def _measure(self, x: np.ndarray):
        """Keep its recent audio and, every MAKEUP_EVERY_S, re-measure cut_share
        (capture thread: a few ms, never on an audio callback)."""
        h, n = self._hist, len(x)
        if n >= len(h):
            x, n = x[-len(h):], len(h)
        end = self._hist_w + n
        if end <= len(h):
            h[self._hist_w:end] = x
        else:
            k = len(h) - self._hist_w
            h[self._hist_w:] = x[:k]
            h[:n - k] = x[k:]
        self._hist_w = end % len(h)
        self._hist_n = min(self._hist_n + n, len(h))
        self._since += n
        if self._since < SR * self.MAKEUP_EVERY_S or self._hist_n < SR:
            return
        self._since = 0
        # the last _hist_n frames, read from the ring in place (np.roll copied all
        # 1.5 MB of it every time)
        new = destination.cut_shares(h, SR, at=(self._hist_w - self._hist_n) % len(h),
                                     length=self._hist_n)
        if new:   # silence measures nothing: keep what it had
            old = self.cut_share
            self.cut_share = {c: 0.5 * old.get(c, v) + 0.5 * v for c, v in new.items()}

    def gain(self, out: str, lowcut: int) -> float:
        """Its volume times the make-up for `lowcut` (0: none), gliding to a new
        value over a few blocks so a re-measure never steps (audio callback)."""
        want = self.vol * (destination.makeup(self.cut_share.get(lowcut, 0.0)) if lowcut else 1.0)
        g = self._gain.get(out, want)
        g += (want - g) * 0.1
        self._gain[out] = g
        return g


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
    # out -> source frames per output frame: 1 when `data` was made at that output's
    # rate; otherwise the source is read at this rate (the resampled copy wasn't
    # ready when it started, and playing must never wait for one: see Engine.play)
    step: dict = field(default_factory=dict)
    # outs whose stream closed under it mid-play (a rescan, a stalled device): done
    # there for now, but a reopen at the same rate resumes it from its own position
    cut: set = field(default_factory=set)
    # out -> the gain its last block ended at (_render glides from there to a new one)
    gnow: dict = field(default_factory=dict)

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
        # an output that's done stops moving (and never takes its seek): read a live one
        live = [o for o in self.data if o not in self.done]
        for o in live + [o for o in self.data if o in self.done]:
            d = self.data[o]
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
        # (sid, rate) -> (weak ref to the source array, resampled copy); LRU, bounded by
        # CACHE_BUDGET. The source is held weakly, here and in _shares: the library keeps
        # its sounds alive, while a preview's or a link's audio is only held by its voice
        # and must be freed when that ends (an effects preview of a song is ~70 MB)
        self._cache: OrderedDict[tuple[str, int], tuple[weakref.ref, np.ndarray]] = OrderedDict()
        self._cache_bytes = 0
        self._cache_lock = threading.Lock()
        self._resampling: set[tuple[str, int]] = set()   # cache keys being made on a thread
        # sid -> (source array, src rate, destination.cut_shares): worked out once per
        # sound (at load, by prepare), not on every press
        self._shares: dict[str, tuple[weakref.ref, int, dict]] = {}
        # a source array died: its entries get dropped on the next _sweep. The weakref
        # callback only appends here: it can fire on any thread, even one holding
        # _cache_lock, so it mustn't take a lock itself
        self._dead: list[None] = []
        # sid -> times forget() was called: a prepare still running when its sound is
        # removed mustn't put the audio back afterwards (it'd hold a mapped cache file
        # open, so the file couldn't be deleted until the app closed)
        self._forgets: dict[str, int] = {}

        self.latency = "low"      # sounddevice latency: 'low' or 'high' (safer)
        keys = ("main", "mon", "mic", "obs")
        self.names = dict.fromkeys(keys)          # device names for reopening
        self._last_cb = dict.fromkeys(keys, 0.0)  # monotonic time of last callback
        self._last_try = dict.fromkeys(keys, 0.0)   # last (re)open attempt
        self.xruns = dict.fromkeys(keys, 0)       # drop-outs reported by PortAudio
        self.cb_errors = dict.fromkeys(keys, 0)   # exceptions inside a callback
        self._cb_err_base = dict.fromkeys(keys, 0)   # cb_errors when the stream opened
        self._cb_err_seen = dict.fromkeys(keys, 0)   # cb_errors at the last check_streams
        self.stalls = 0                                       # streams reopened by the watchdog

        # live settings (read by audio callbacks; plain attribute writes are atomic)
        self.sound_vol = 1.0      # sounds -> others
        self.mic_vol = 1.0        # mic    -> others
        self.mon_vol = 0.7        # everything -> your headphones
        self.obs_vol = 1.0        # everything -> the stream output (OBS)
        self.obs_voice = True     # your mic goes to the stream output too (when sent)
        self.mic_enabled = True   # pass your mic through to the send device
        self.sending = True       # master switch: False sends silence to others
        self.mic_muted = False
        self.monitor_sounds = True
        self.eq_gains: list[float] | None = None   # None = EQ off
        self.eq_target = "voice"                   # 'voice' | 'sounds' | 'all'
        self.dest = None                           # destination.Dest shaping the sounds bus
        self._dests: dict[str, object] = {}        # out -> destination.Processor
        self._eqs: dict[tuple[str, str], EQ] = {}
        self.mic_check = False    # headphones also get your mic (= exactly what others hear)
        self.mon_voice_only = False   # ...but only your (changed) voice: the Voice tab's
        self.voice_chain = None   # voicefx.VoiceChain: voice changer / live speech tap on the mic
        # the send stage (soundboard.sendfx): what makes the mix survive voice chat
        self.send_mono = True     # phase-aware mono into the send device (every voice chat is mono)
        self.duck_db = 0.0        # lower the sounds this much while you talk (0 = off)
        self.mic_gate = False     # mute your mic while a sound plays (only the sounds go out)
        self._gate: dict[str, float] = {}   # output -> the mic's current gate gain
        self.limiter_on = True    # hold the send device's peaks at sendfx.CEILING_DB
        self._send: dict[tuple[str, str], object] = {}   # (out, kind) -> its sendfx stage
        self._quiet: dict[str, int] = {}   # out -> frames of silence on its sounds bus
        self._idle_n: dict[str, int] = {}  # out -> frames its sounds bus skipped (_bus_idle)
        self._glides: dict = {}   # (out, what) -> the volume its last block ended at (_vol)
        self.sound_speed = 1.0        # live playback speed of every sound (0.25..4)
        self.sound_pitch = 0.0        # live pitch of every sound, semitones
        self.sound_keep_pitch = True  # speed changes leave the pitch alone
        self.sound_fx: dict = {}      # live effects on every sound (livefx), {} = none
        self._spitch: dict[str, LivePitch] = {}
        self._sfx: dict[str, livefx.LiveFx] = {}

        self.main_stream = self.mon_stream = self.mic_stream = self.obs_stream = None
        # "straight into my mic" (soundboard.directmic): what others hear goes into the
        # real mic inside Windows. The board's mic is then the clean mic the effect hands
        # over (never its own sounds coming back), and the send mix runs on its clock.
        self.main_direct = False
        self.direct_mode = directmic.MODE_REPLACE   # the send mix replaces the mic
        self.direct_lead_s = directmic.LEAD_S
        self.fifo_direct = DirectFifo()
        # ...and the cable gets the same, for a voice app still set to it (CableTap)
        self.tap: CableTap | None = None
        # Setup -> Devices -> Also send to: a copy of what others hear into each of these
        # (set_copy_devices). A new tuple each change: the audio thread reads it once.
        self.copies: tuple[CableTap, ...] = ()
        self.copy_names: tuple[str, ...] = ()
        self._copy_try: dict[str, float] = {}
        self.tap_name: str | None = None
        self._tap_try = 0.0
        self.rates = {"main": SR, "mon": SR, "mic": SR, "obs": SR}
        self.errors: dict[str, str] = {}

        # the mic's clock is its own device's: drift tracking switches itself on if it
        # turns out to wander from the output's (see Ring.auto_drift)
        self.ring_main = Ring(auto_drift=True)
        self.ring_mon = Ring(auto_drift=True)
        self.ring_obs = Ring(auto_drift=True)
        self._rs_main = StreamResampler(SR, SR)
        self._rs_mon = StreamResampler(SR, SR)
        self._rs_obs = StreamResampler(SR, SR)

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
        self.ring_robs = Ring(prefill_s=0.1, max_s=0.6, track_drift=True, grow_to_s=0.3)
        self._rs_rmain = StreamResampler(SR, SR)
        self._rs_rmon = StreamResampler(SR, SR)
        self._rs_robs = StreamResampler(SR, SR)
        self._radio_heard = 0.0
        self.aux: tuple[AuxSource, ...] = ()   # captured programs (Apps tab), see AuxSource

        self.level_main = 0.0
        self.level_mic = 0.0
        self.level_mon = 0.0
        self.level_obs = 0.0
        self.level_radio = 0.0
        # anything playing — sounds, the radio, captured programs — wherever it goes
        # (to others or only to your headphones), without your mic: the logo's cue
        self.level_play = 0.0

        self._rec_buf: list[np.ndarray] | None = None
        self._rec_frames_left = 0
        self._rec_done: tuple[list, int] | np.ndarray | None = None   # see rec_done
        self._mic_pow = [0.0, 0.0]   # each mic channel's recent power (_mic_channels)
        self._mic_dead: int | None = None   # the mic channel found dead, if one is
        self._mon_fed = False        # the mic wrote to ring_mon last block (mic check)
        self._obs_fed = False        # ...and to ring_obs (your voice on the stream output)
        self._mic_rec: list[np.ndarray] | None = None          # mic during a test (see _mic)
        # Record a sound: the mic's blocks while set to a list (start_mic_take); the UI
        # thread moves them to disk as they come. Separate from the test's _mic_rec
        self._take: list[np.ndarray] | None = None
        self._take_fx = False        # the take is the mic after the voice changer
        # Record a sound from what's playing: the sounds bus plus the radio, before your
        # mic is added, at the main output's rate (start_play_take)
        self._play_take: list[np.ndarray] | None = None
        self.play_take_out = "main"   # ...taken from this output ("mon": no send device)
        # a copy of every block sent to the send device while set to a list (the voice chat
        # check compares it with what Discord plays back); None = off
        self.main_tap: list[np.ndarray] | None = None

    # ----------------------------------------------------------------- streams
    @staticmethod
    def _native_rate(idx: int) -> int:
        return int(sd.query_devices(idx)["default_samplerate"])

    def _open_out(self, key, name, callback):
        if key == "main" and name == directmic.DEVICE:
            return self._open_direct(callback)
        idx = find_device("output", name)
        if idx is None:
            raise RuntimeError(f"device not found: {name}")
        rate = self._native_rate(idx)
        chans = min(CH, sd.query_devices(idx)["max_output_channels"])
        if chans < CH:
            raise RuntimeError("mono output devices aren't supported")
        s = sd.OutputStream(device=idx, samplerate=rate, channels=CH, dtype="float32",
                            latency=BUFFER.get(self.latency, "low"), callback=callback)
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

    def _open_direct(self, callback):
        """What others hear -> straight into the real mic (soundboard.directmic)."""
        try:
            s = directmic.DirectMicStream(callback, mic_callback=self._mic_direct,
                                          mode=self.direct_mode, lead_s=self.direct_lead_s,
                                          voice_delay=self._direct_voice_delay)
        except FileNotFoundError:
            raise RuntimeError("Onion Board isn't attached to your mic yet") from None
        self.fifo_direct.clear()
        self._last_cb["main"] = time.monotonic()
        s.start()
        self._stream_opened("main")
        rate = directmic.RATE
        if rate != self.rates["main"]:
            self.rates["main"] = rate
            self._reconfigure_out("main")
        else:
            self._clear_out("main")
        self._resume_voices("main", rate)
        log.info("opened main output: straight into the mic")
        return s

    def _direct_voice_delay(self) -> float:
        """Frames (at the send rate) the newest frame of the send mix is behind the newest
        clean mic, in your voice: what the resampler holds back, what waits in the fifo,
        the limiter's lookahead. (The mic effect fills in for a late block with the mic
        from the same moment; a voice changer's own delay doesn't count: the effect
        doesn't fill in with your real voice then, see _direct_mic_gain.)"""
        d = self._rs_main.held() + self.fifo_direct.count
        if self.limiter_on:
            d += self._stage("main", Limiter).la
        return d

    def effect_alive(self) -> bool:
        """The mic effect is running: a program is recording the mic it's on."""
        s = self.main_stream
        return isinstance(s, directmic.DirectMicStream) and s.effect_alive()

    def set_tap_device(self, name: str | None):
        """Also play what others hear into `name` (the virtual cable) while it goes
        straight into the mic; None = don't."""
        old, self.tap = self.tap, None
        if old is not None:
            old.close()
        self.tap_name = name
        self._tap_try = time.monotonic()
        if name:
            try:
                self.tap = CableTap(name, BUFFER.get(self.latency, "low"))
                log.info("also sending into %s", name)
            except Exception as e:  # noqa: BLE001 - the mic still works; retried
                log.warning("can't also send into %s: %s", name, e)

    def set_copy_devices(self, names):
        """Also play what others hear into each of `names` (Setup -> Devices -> Also send
        to: Voicemeeter, OBS, a second cable...). Ones already open stay open; one that
        won't open is retried by check_streams."""
        names = tuple(dict.fromkeys(n for n in names if n))
        keep = {t.name: t for t in self.copies if t.name in names}
        old, self.copies = self.copies, tuple(keep.values())
        self.copy_names = names
        for t in old:
            if t.name not in keep:
                t.close()
        for n in names:
            if n not in keep:
                self._open_copy(n)

    def _open_copy(self, name: str):
        self._copy_try[name] = time.monotonic()
        try:
            t = CableTap(name, BUFFER.get(self.latency, "low"))
        except Exception as e:  # noqa: BLE001 - the rest still works; retried
            log.warning("can't also send into %s: %s", name, e)
            return
        log.info("also sending into %s", name)
        self.copies = (*self.copies, t)

    def copies_down(self) -> list[str]:
        """The "Also send to" devices that aren't open (unplugged, or busy)."""
        up = {t.name for t in self.copies}
        return [n for n in self.copy_names if n not in up]

    def _check_copies(self, now: float):
        """The "Also send to" copies' watchdog (see check_streams)."""
        for t in self.copies:
            if now - t.last_cb > STALL_S:
                log.warning("copy to %s stalled; reopening", t.name)
                self.copies = tuple(c for c in self.copies if c is not t)
                t.close()
                self._open_copy(t.name)
        for n in self.copies_down():
            if now - self._copy_try.get(n, 0.0) >= RETRY_S:
                self._open_copy(n)

    def _check_tap(self, now: float):
        """The cable tap's own watchdog (see check_streams)."""
        name = self.tap_name
        if not name:
            return
        if self.tap is None:
            if now - self._tap_try >= RETRY_S:
                self.set_tap_device(name)
        elif now - self.tap.last_cb > STALL_S:
            log.warning("cable tap stalled; reopening %s", name)
            self.set_tap_device(name)

    def direct_apps(self) -> int:
        """Apps whose mic stream carries the board right now (its own one too)."""
        s = self.direct_stream()
        return s.apps() if s is not None else 0

    def direct_stream(self):
        s = self.main_stream
        return s if self.main_direct and isinstance(s, directmic.DirectMicStream) else None

    def _mic_direct(self, x: np.ndarray, rate: int):
        """A block of the clean mic, from the mic effect (its stream's thread)."""
        if rate != self.rates["mic"]:
            log.info("mic rate %d -> %d (the mic effect's)", self.rates["mic"], rate)
            self.rates["mic"] = rate
            self._reconfigure_mic_resamplers()
        self._last_cb["mic"] = time.monotonic()
        self._mic(x, direct=True)

    def _resume_voices(self, key: str, rate: int):
        """Output `key` was reopened: sounds still playing on another output pick
        up here again, at the same spot (with a short fade in); sounds this output
        was cut from while every output was closed (a device rescan) pick up where
        they were cut. Data made for another rate is useless, so those stay done."""
        with self.lock:
            for v in self.voices:
                if (key not in v.done or v.stopping or not len(v.data.get(key, ()))
                        or v.rates.get(key) != rate):
                    continue
                other = next((o for o in v.data if o != key and o not in v.done
                              and len(v.data[o])), None)
                if other is None:
                    if key not in v.cut:
                        continue
                    other = key   # nothing else playing it: its own spot
                d = v.data[other]
                frac = v.seek_to.get(other)
                if frac is None:
                    frac = (v.pos[other] % len(d)) / len(d)
                v.cut.discard(key)
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
        self.main_direct = name == directmic.DEVICE
        self._last_try["main"] = time.monotonic()
        if name:
            try:
                self.main_stream = self._open_out("main", name, self._cb_main)
            except Exception as e:  # noqa: BLE001
                log.warning("can't open main output %r: %s", name, e)
                self.errors["main"] = errors.plain(e)

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
                self.errors["mon"] = errors.plain(e)

    def set_obs_device(self, name: str | None):
        """The stream output: a device OBS captures (None = off)."""
        self._close("obs_stream")
        self.errors.pop("obs", None)
        self.names["obs"] = name
        self._last_try["obs"] = time.monotonic()
        if name:
            try:
                self.obs_stream = self._open_out("obs", name, self._cb_obs)
            except Exception as e:  # noqa: BLE001
                log.warning("can't open stream output %r: %s", name, e)
                self.errors["obs"] = errors.plain(e)

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
                                   latency=BUFFER.get(self.latency, "low"),
                                   callback=self._cb_mic)
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
                self.errors["mic"] = errors.plain(e)
                if s is not None:
                    self._close_quietly(s, "mic")
                if self.rates["mic"] != old_rate:
                    self.rates["mic"] = old_rate
                    self._reconfigure_mic_resamplers()

    def reopen_all(self):
        """Close and reopen every stream with the same devices (after a latency change)."""
        self.set_mic_device(self.names["mic"])
        self.set_main_device(self.names["main"])
        self.set_tap_device(self.tap_name)
        copies = self.copy_names
        self.set_copy_devices(())
        self.set_copy_devices(copies)
        self.set_mon_device(self.names["mon"])
        self.set_obs_device(self.names["obs"])

    def check_streams(self) -> list[str]:
        """Watchdog (call about once a second from the UI thread).

        A stream whose callback has stopped being called (headset unplugged, Windows
        changed its sample rate, PC came back from sleep) is closed and reopened. A
        device that failed to open is retried every RETRY_S. Returns the keys that
        were touched (reopened, came back, or whose callback raised since the last
        check), so the UI can refresh its status from errors_snapshot()."""
        now = time.monotonic()
        touched = []
        self._check_tap(now)
        self._check_copies(now)
        for key, attr, setter in (("main", "main_stream", self.set_main_device),
                                  ("mon", "mon_stream", self.set_mon_device),
                                  ("mic", "mic_stream", self.set_mic_device),
                                  ("obs", "obs_stream", self.set_obs_device)):
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
        self._rs_obs = StreamResampler(r["mic"], r["obs"])

    def _reconfigure_out(self, key: str):
        """Rebuild what feeds output `key` for its (new) rate. Only that output's
        rings are reset: the other output plays on without a gap."""
        r = self.rates
        if key == "main":
            self._rs_main = StreamResampler(r["mic"], r["main"])
            self._rs_rmain = StreamResampler(SR, r["main"])
            rings = (self.ring_main, self.ring_rmain)
        elif key == "obs":
            self._rs_obs = StreamResampler(r["mic"], r["obs"])
            self._rs_robs = StreamResampler(SR, r["obs"])
            rings = (self.ring_obs, self.ring_robs)
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
        elif key == "obs":
            rings = [self.ring_obs, self.ring_robs]
            rings += [a.ring_obs for a in self.aux]
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
        self._reconfigure_out("obs")

    # ----------------------------------------------------------------- radio input
    def feed_radio(self, x: np.ndarray):
        """Push a chunk of radio audio ((n, 2) float32 at SR). Called from one thread at
        a time (the radio's decoding thread), like feed_aux."""
        lvl = peak(x)
        self.level_radio = max(lvl * self.radio_vol, self.level_radio)
        if lvl > 0.003:
            self._radio_heard = time.monotonic()
        if self.main_stream is not None:
            self.ring_rmain.write(self._rs_rmain(x))
        if self.mon_stream is not None:
            self.ring_rmon.write(self._rs_rmon(x))
        if self.obs_stream is not None:
            self.ring_robs.write(self._rs_robs(x))

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
        src.feed(x, self.main_stream is not None, self.mon_stream is not None,
                 self.obs_stream is not None)

    def aux_on_air(self) -> bool:
        """True while any captured program is audibly going out to others."""
        return any(a.on_air() for a in self.aux)

    def _close(self, attr):
        s = getattr(self, attr)
        setattr(self, attr, None)
        out = {"main_stream": "main", "mon_stream": "mon", "obs_stream": "obs"}.get(attr)
        if out:  # voices can't finish on a device that's gone
            with self.lock:
                for v in self.voices:
                    if out in v.data and out not in v.done:
                        v.cut.add(out)
                    v.done.add(out)
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:  # noqa: BLE001
                log.debug("closing %s raised", attr, exc_info=True)

    def shutdown(self):
        for a in ("mic_stream", "main_stream", "mon_stream", "obs_stream"):
            self._close(a)
        self.set_tap_device(None)
        self.set_copy_devices(())

    def active_outputs(self) -> set:
        outs = set()
        if self.main_stream is not None:
            outs.add("main")
        if self.mon_stream is not None:
            outs.add("mon")
        if self.obs_stream is not None:
            outs.add("obs")
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
        if hit and hit[0]() is data:
            return hit[1]
        self._sweep()
        gen = self._forgets.get(key[0], 0)
        if data.dtype == np.int16:   # library audio: resample in float, keep the copy compact
            f = data.astype(np.float32)   # in place from here: a song's float copy is
            f *= I16_SCALE                # ~70 MB, and each temporary would be another
            out = resample(f, src_rate, rate)
            del f
            if not out.flags.writeable:
                out = out.copy()
            if len(out) and float(np.max(np.abs(out))) > 1.0:   # resampling overshot
                from soundboard.library import _under_full_scale   # (it imports us)
                out = _under_full_scale(out)
            out *= 32767.0
            np.rint(out, out=out)
            np.clip(out, -32768, 32767, out=out)
            out = out.astype(np.int16)
        else:
            out = resample(data, src_rate, rate)
        with self._cache_lock:
            if self._forgets.get(key[0], 0) != gen:
                return out   # forgotten meanwhile: use it, don't keep it
            old = self._cache.pop(key, None)
            if old is not None:
                self._cache_bytes -= old[1].nbytes
            self._cache[key] = (self._ref(data), out)
            self._cache_bytes += out.nbytes
            while self._cache_bytes > CACHE_BUDGET and len(self._cache) > 1:
                _, (_, dropped) = self._cache.popitem(last=False)
                self._cache_bytes -= dropped.nbytes
        return out

    def _cached(self, sid: str, data: np.ndarray, rate: int, src_rate: int) -> np.ndarray | None:
        """data_for's answer if it's ready without any work, else None."""
        if rate == src_rate:
            return data
        with self._cache_lock:
            hit = self._cache.get((sid.split(":")[0], rate))
        return hit[1] if hit and hit[0]() is data else None

    def _resample_soon(self, sid: str, data: np.ndarray, rate: int, src_rate: int):
        """Make data_for's copy on a thread (once per sound and rate at a time)."""
        key = (sid.split(":")[0], rate)
        with self._cache_lock:
            if key in self._resampling:
                return
            self._resampling.add(key)

        def run():
            try:
                self.data_for(sid, data, rate, src_rate)
            except Exception:  # noqa: BLE001 - the next press reads the source again
                log.debug("resampling %s failed", sid, exc_info=True)
            finally:
                with self._cache_lock:
                    self._resampling.discard(key)

        threading.Thread(target=run, daemon=True, name="resample").start()

    def cut_shares(self, sid: str, data: np.ndarray, src_rate: int = SR) -> dict:
        """destination.cut_shares of a sound, worked out once (~12 ms for a song)."""
        key = sid.split(":")[0]
        hit = self._shares.get(key)
        if hit is not None and hit[0]() is data and hit[1] == src_rate:
            return hit[2]
        self._sweep()
        gen = self._forgets.get(key, 0)
        shares = sharestore.lookup(data, src_rate)   # a long song's, from the last start
        if shares is None:
            shares = destination.cut_shares(data, src_rate)
            sharestore.remember(data, src_rate, shares)   # (does nothing unless mapped)
        with self._cache_lock:
            if self._forgets.get(key, 0) == gen:   # not forgotten meanwhile
                self._shares[key] = (self._ref(data), src_rate, shares)
        return shares

    def _ref(self, data: np.ndarray) -> weakref.ref:
        dead = self._dead   # not self: the ref mustn't keep the engine alive
        return weakref.ref(data, lambda _r: dead.append(None))

    def _sweep(self):
        """Drop the cache and shares entries whose source array is gone."""
        if not self._dead:
            return
        with self._cache_lock:
            self._dead.clear()
            for k in [k for k, v in self._shares.items() if v[0]() is None]:
                del self._shares[k]
            for k in [k for k, v in self._cache.items() if v[0]() is None]:
                self._cache_bytes -= self._cache.pop(k)[1].nbytes

    def prepare(self, sid: str, data: np.ndarray):
        """Pre-resample for the currently open outputs (call off the UI thread), as
        long as the copies fit in CACHE_BUDGET. Past it, each new copy would only push
        out an earlier one: a big board on a 44.1 kHz headset resampled every song at
        every start and threw most of them away. Those are made when pressed instead
        (play reads the source at the device's rate meanwhile).
        Long sounds on disk (mapped) aren't copied here at all: a copy reads the whole
        file and keeps it in RAM, which undoes mapping it (8 songs cost 242 MB and
        1.8 s at every start on a 44.1 kHz headset). Their copy is made on first press."""
        self.cut_shares(sid, data)
        if mapped.is_mapped(data):
            return
        for o in self.active_outputs():
            rate = self.rates[o]
            if self._cached(sid, data, rate, SR) is None:
                need = data.nbytes * rate / SR
                if self._cache_bytes + need > CACHE_BUDGET:
                    continue
            self.data_for(sid, data, rate)

    def forget(self, sid: str):
        with self._cache_lock:
            for s in (sid, sid + "~fx"):   # and its effects preview
                self._forgets[s] = self._forgets.get(s, 0) + 1
                self._shares.pop(s, None)
                for k in [k for k in self._cache if k[0] == s]:
                    self._cache_bytes -= self._cache.pop(k)[1].nbytes

    # ----------------------------------------------------------------- playback
    def play(self, sid: str, data: np.ndarray, gain: float, loop=False, mode="restart",
             preview=False, src_rate: int = SR, start: float = 0.0,
             fade_in: float = 0.0, fade_out: float = 0.0,
             only: str | tuple[str, ...] | None = None) -> Voice | None:
        """mode: 'restart' (stop previous instance), 'overlap', 'toggle' (stop if playing),
        'solo' (stop every other sound, then restart this one).
        fade_in / fade_out (seconds): a rise from silence at the start; a fall to silence
        when it's stopped and, for a one-shot, over its last fade_out seconds.
        only: 'main' or 'mon' plays on that output alone (the voice chat check); a tuple
        of outputs plays on those ('main', 'obs': others hear it, you don't)."""
        outs = self.active_outputs()
        if only is not None:
            outs &= {only} if isinstance(only, str) else set(only)
        if preview:
            # previews are for your ears only; with no headphone device open they must
            # not fall through to the send device (everyone in the call would hear them)
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
        # this runs on the UI thread (or a hotkey's): resampling a song for a 44.1 kHz
        # device takes up to a second, so a copy that isn't ready yet is made on a
        # thread for next time and this press reads the source at the output's rate
        per_out, step = {}, {}
        for o in outs:
            d = self._cached(sid, data, rates_used[o], src_rate)
            if d is None:
                self._resample_soon(sid, data, rates_used[o], src_rate)
                d, step[o] = data, src_rate / rates_used[o]
            per_out[o] = d
        for d in {id(d): d for d in per_out.values()}.values():
            mapped.warm(d, int(start * len(d)))   # a long sound on disk: read it in first
        if fade_in <= 0 and (start > 0 or _hard_start(data)):
            fade_in = START_FADE_S   # starts mid-waveform: a tiny rise instead of a pop
        v = Voice(sid, per_out, gain, loop, preview=preview, rates=rates_used,
                  fade_in=max(0.0, float(fade_in)), fade_out=max(0.0, float(fade_out)),
                  fixed=is_fixed(sid), cut_share=self.cut_shares(sid, data, src_rate),
                  step=step)
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
        for d in {id(d): d for d in v.data.values()}.values():
            mapped.warm(d, int(frac * len(d)))   # before the audio thread jumps there
        with self.lock:
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
        self._sweep()   # the UI polls this: a finished preview's audio goes here
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
    @property
    def rec_done(self) -> tuple[np.ndarray, int] | None:
        """(audio, rate) of the finished test recording, or None."""
        done = self._rec_done
        if done is None:
            return None
        blocks, rate = done
        if isinstance(blocks, list):
            done = self._rec_done = (np.concatenate(blocks), rate)
        return done

    @rec_done.setter
    def rec_done(self, value):
        self._rec_done = value

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

    def start_mic_take(self, processed: bool = False) -> list[np.ndarray]:
        """Record a sound with the mic: from now on every mic block (the raw mic, or with
        `processed` the mic after the voice changer) is appended, as a copy at the mic's
        rate (`rates["mic"]`), to the list returned. The caller takes blocks off its
        front as it goes (`del blocks[:n]`: safe against the audio thread's append) and
        ends it with stop_mic_take(). A test recording running meanwhile is untouched."""
        self._take_fx = processed
        self._take = blocks = []
        return blocks

    def stop_mic_take(self) -> list[np.ndarray]:
        """End the take; returns its list (with any blocks not yet taken off it)."""
        blocks, self._take = self._take, None
        return blocks if blocks is not None else []

    @property
    def taking(self) -> bool:
        return self._take is not None

    def start_play_take(self) -> list[np.ndarray]:
        """Record a sound from what's playing: from now on every block of your sounds
        (web results and the link bar's too) and the radio, as you hear them and
        without your mic, is appended at the main output's rate (`rates["main"]`) to
        the list returned, like start_mic_take. With no send device open it's taken from
        your headphones instead (`play_take_out`, at that rate)."""
        self.play_take_out = "main" if self.main_stream is not None else "mon"
        self._play_take = blocks = []
        return blocks

    def stop_play_take(self) -> list[np.ndarray]:
        blocks, self._play_take = self._play_take, None
        return blocks if blocks is not None else []

    @property
    def play_taking(self) -> bool:
        return self._play_take is not None

    # ----------------------------------------------------------------- callbacks
    def _render(self, out: str, frames: int, previews_only=False,
                fixed=False, makeup=True) -> np.ndarray:
        """Mix the voices playing on `out`: the sounds (at the live speed) or, with
        `fixed`, the app's own playback (always at speed 1). `makeup`: this mix goes
        through _dest, so give back what its low cut takes (paths that skip _dest
        must not get the boost without the cut)."""
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
            if makeup and dest is not None and dest.lowcut:
                g = g * np.float32(v.makeup(dest.lowcut))
            g0 = v.gate[out]
            rate = self.rates[out]
            st = v.step.get(out, 1.0)
            vspeed = speed * st   # source frames per output frame
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
            tail = int(v.fade_out * rate * st) if v.fade_out > 0 and not v.loop else 0
            p_start = float(p)
            near_end = tail and n - p_start < tail + frames * max(vspeed, 1.0) + 1
            # a gain change (its slider, or the mode's make-up) glides over the block
            # instead of stepping, which crackles on held notes and bass
            g_was = v.gnow.get(out, g)
            v.gnow[out] = g
            glide = g_was != g
            if glide:
                g_top = np.float32(max(abs(g_was), abs(g)))
                if not g_top:
                    glide = False
                else:
                    g_env = np.linspace(g_was / g_top, g / g_top, frames + 1,
                                        dtype=np.float32)[1:]
                    g = g_top
            shaped = g0 != target or near_end or glide
            if shaped:
                dst_final = dst
                dst = np.zeros((frames, CH), np.float32)
            xf = loop_xf(n, rate) if v.loop else 0
            if abs(vspeed - 1.0) < 1e-4:
                p = int(p)
                if v.loop:
                    dst += span(data, p, p + frames, True, xf) * g
                    p = loop_wrap(p + frames, n, xf)
                elif p < n:
                    take = min(frames, n - p)
                    dst[:take] += data[p:p + take] * g
                    p += take
            else:
                p = self._render_speed(dst, data, float(p), vspeed, g, v.loop, xf)
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
                if glide:
                    env = env * g_env
                if near_end:
                    at = p_start + vspeed * np.arange(frames, dtype=np.float32)
                    env = env * np.clip((n - at) / tail, 0.0, 1.0)
                dst_final += dst * env[:, None]
                if v.stopping and v.gate[out] <= 0.0:
                    v.done.add(out)
            if p >= n and not v.loop:
                v.done.add(out)
        return buf

    @staticmethod
    def _render_speed(dst, data, p: float, speed: float, g, loop: bool, xf: int = 0):
        """Add `data` read from position p at `speed` (cubic interpolation, lowpassed
        first when faster than 1: _aa_taps) into dst; returns the new position
        (len(data) once a one-shot has ended). A loop wraps through its crossfade
        (`xf` frames: span)."""
        n = len(data)
        if n < 2:
            return n
        pos = p + speed * np.arange(len(dst), dtype=np.float64)   # along the sound as played
        if not loop:
            pos = pos[:int(np.searchsorted(pos, n - 1))]   # frames before the end
        if len(pos):
            i = pos.astype(np.int64)
            f = (pos - i).astype(np.float32)[:, None]
            h = _aa_taps(speed) if speed > 1.0 + 1e-4 else None
            pad = 1 + (len(h) // 2 if h is not None else 0)
            lo = int(i[0]) - pad
            # only the few frames this block uses are converted and filtered (four
            # gathers straight from a song's int16 cost ~70 us per sound and output)
            w = span(data, lo, int(i[-1]) + 2 + pad, loop, xf)
            if h is not None:
                for c in range(w.shape[1]):
                    w[:, c] = np.convolve(w[:, c], h, "same")
            i0 = i - lo
            p0, p1, p2, p3 = w[i0 - 1], w[i0], w[i0 + 1], w[i0 + 2]
            if not loop:   # past either end: continue the line (a ramp stays a ramp)
                first, last = i == 0, i + 2 > n - 1
                p0[first] = 2 * p1[first] - p2[first]
                p3[last] = 2 * p2[last] - p1[last]
            dst[:len(pos)] += hermite(p0, p1, p2, p3, f) * g
        p += speed * len(dst)
        if loop:
            return loop_wrap(p, n, xf)
        return p if p < n - 1 else n

    def _sounds(self, out: str, frames: int, previews_only=False,
                makeup=True) -> np.ndarray:
        """The sounds bus: sounds at the live speed through the live pitch, plus the
        app's own playback (fixed voices) as it is. makeup=False where the bus skips
        _dest (the stream output, hear-my-voice)."""
        mix = self._fx(out, self._pitch(out, self._render(out, frames, previews_only,
                                                          makeup=makeup)))
        if any(v.fixed for v in self.voices):
            mix += self._render(out, frames, previews_only, fixed=True, makeup=makeup)
        return mix

    def _sound_st(self) -> float:
        """The live pitch's shift in semitones (see _pitch)."""
        st = float(self.sound_pitch)
        if self.sound_keep_pitch and abs(self.sound_speed - 1.0) >= 1e-4:
            st -= 12.0 * float(np.log2(max(self.sound_speed, 1e-3)))
        return st

    def _pitch(self, out: str, x: np.ndarray) -> np.ndarray:
        """Live pitch on the sounds bus: the user's shift, plus the correction that
        undoes the speed's pitch change when keep-pitch is on."""
        st = self._sound_st()
        f = self._spitch.get(out)
        if f is None or f.rate != self.rates[out]:   # made at 0 st too: it needs the history
            f = self._spitch[out] = LivePitch(self.rates[out])
        return f.process(x, st)   # at 0 st it only keeps its history fresh

    def _fx(self, out: str, x: np.ndarray) -> np.ndarray:
        """Live effects on the sounds bus (livefx). Made when a knob comes off 0 and
        dropped once they're all back at 0 and the last change has faded out."""
        fx = self.sound_fx
        f = self._sfx.get(out)
        if f is None or f.rate != self.rates[out]:
            if not fx:
                return x
            f = self._sfx[out] = livefx.LiveFx(self.rates[out])
        y = f.process(x, fx)
        if not fx and f.idle:
            self._sfx.pop(out, None)
        return y

    def _eq(self, out: str, part: str, x: np.ndarray) -> np.ndarray:
        """Run x through the EQ if it's on and aimed at `part` ('sounds' / 'voice')."""
        g = self.eq_gains
        key = (out, part)
        f = self._eqs.get(key)
        if g is None or self.eq_target not in (part, "all"):
            # off here: fade back to the dry sound (switching straight to it clicked),
            # then drop the filter, so its old memory can't click when it's back on
            if f is None:
                return x
            y = f.process(x, None) if f.rate == self.rates[out] else x
            if f.idle or y is x:
                self._eqs.pop(key, None)
            return y
        if f is None or f.rate != self.rates[out]:
            # switched on mid-stream: fade in from the dry sound, as it fades out
            f = self._eqs[key] = EQ(self.rates[out], fade_in=f is None)
        return f.process(x, g)

    def _stage(self, out: str, kind: type):
        """This output's Limiter / SmartMono / Ducker, made for its current rate."""
        key = (out, kind.__name__)
        f = self._send.get(key)
        if f is None or f.rate != self.rates[out]:
            f = self._send[key] = kind(self.rates[out])
        return f

    def _lowcut(self) -> int:
        """The destination mode's low cut (Hz), 0 with none: captured programs get
        the make-up for it (AuxSource.gain), as sounds do (Voice.makeup)."""
        d = self.dest
        return d.lowcut if d is not None else 0

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
            self.errors[key] = f"audio callback failed: {errors.plain(exc)}"

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

    def _cb_obs(self, outdata, frames, t, status):
        self._last_cb["obs"] = time.monotonic()
        if is_xrun(status):
            self.xruns["obs"] += 1
        try:
            self._obs(outdata, frames)
        except Exception as e:  # noqa: BLE001
            outdata.fill(0)
            self._guard("obs", e)

    def _cb_mic(self, indata, frames, t, status):
        self._last_cb["mic"] = time.monotonic()
        if is_xrun(status):
            self.xruns["mic"] += 1
        try:
            d = self.direct_stream()
            if d is not None and d.mic_live:
                # this block went through the mic effect, sounds and all: the clean one
                # came from the effect already; take it now rather than at the next poll
                d.pump()
                return
            self._mic(indata)
        except Exception as e:  # noqa: BLE001
            self._guard("mic", e)

    def _main(self, outdata, frames):
        idle = self._bus_idle("main", frames)   # nothing to mix: the sounds bus is silence
        if idle:
            mix = np.zeros((frames, CH), np.float32)
            self._glides[("main", "sounds")] = float(self.sound_vol)
            play = 0.0
        else:
            self._wake_bus("main")
            mix = self._vol("main", "sounds", self._sounds("main", frames), self.sound_vol)
            play = peak(mix)
        take = self._play_take   # read once: the UI may end it meanwhile
        took = mix.copy() if take is not None and self.play_take_out == "main" else None
        r = self.ring_rmain.read(frames)
        if r is not None:
            idle = False
            play = max(play, peak(r) * self.radio_vol)
            mix += self._vol("main", "radio", r, self.radio_vol if self.radio_live else 0.0)
            if took is not None:   # the radio as you hear it, sent out or not
                took += r * np.float32(self.radio_vol)
        if took is not None:
            take.append(took)
        lowcut = self._lowcut()
        for a in self.aux:
            x = a.ring_main.read(frames)
            if x is not None:
                idle = False
                play = max(play, peak(x) * a.vol)
                g = a.gain("main", lowcut) if a.live else 0.0
                mix += self._vol("main", ("aux", a.key), x, g)
        self.level_play = max(play, self.level_play * 0.85)
        if not idle:
            finite(mix)
        if self.main_direct:
            m = self.fifo_direct.read(frames)
            add = self.direct_mode == directmic.MODE_REPLACE
            mix = self._send_bus("main", mix, m, add_mic=add, silent=idle)
            self._direct_mic_gain()
        else:
            m, add = self.ring_main.read(frames), True
            mix = self._send_bus("main", mix, m, silent=idle)
        # still silence unless the mic went in: every stage below would only pass zeros
        silent = idle and not (add and m is not None and self.mic_enabled and not self.mic_muted)
        # muted: others get silence (faded, not cut), nothing else changes
        if silent:
            self._glides[("main", "send")] = 1.0 if self.sending else 0.0
        else:
            mix = self._vol("main", "send", mix, 1.0 if self.sending else 0.0)
        if self.limiter_on:
            lim = self._stage("main", Limiter)
            if not silent:
                mix = lim.process(mix)
            else:
                y = lim.silence(frames)   # None: at rest, zeros out
                if y is not None:
                    mix, silent = y, False
        if silent:
            outdata.fill(0)
            self.level_main *= 0.85
        else:
            soft_limit(mix)
            outdata[:] = mix
            self.level_main = max(peak(mix), self.level_main * 0.85)
        cable = self.tap
        if cable is not None and self.main_direct:
            cable.write(mix)
        for c in self.copies:   # Also send to
            c.write(mix)
        tap = self.main_tap
        if tap is not None:
            tap.append(mix.copy())
        rec = self._rec_buf   # read once: cancel_test_record may clear it meanwhile
        if rec is not None:
            rec.append(mix.copy())
            self._rec_frames_left -= frames
            if self._rec_frames_left <= 0 and self._rec_buf is rec:   # not cancelled
                self._rec_buf = None
                # joined by whoever reads rec_done: seconds of audio is too much
                # to copy in an audio callback
                self._rec_done = (rec, self.rates["main"])

    def _mon(self, outdata, frames):
        check = self.mic_check and self.sending   # muted: they hear nothing, so neither do you
        if check and self.mon_voice_only:
            self._mon_voice(outdata, frames)
            return
        # in mic check you hear the real output mix: sounds at their outgoing
        # level plus your mic, so you can judge the balance while a song plays
        idle = not check and self._bus_idle("mon", frames)
        if idle:
            mix = np.zeros((frames, CH), np.float32)
            self._glides[("mon", "sounds")] = 1.0
            play = 0.0
        else:
            self._wake_bus("mon")
            mix = self._sounds("mon", frames, previews_only=not (check or self.monitor_sounds))
        m = self.ring_mon.read(frames)
        if not idle:
            mix = self._vol("mon", "sounds", mix, self.sound_vol if check else 1.0)
            # the main output sees the rest; this one counts with no send device too
            play = peak(mix)
        take = self._play_take   # no send device: what's playing is recorded from here
        took = mix.copy() if take is not None and self.play_take_out == "mon" else None
        r = self.ring_rmon.read(frames)
        if r is not None:
            idle = False
            play = max(play, peak(r) * self.radio_vol)
            on = self.radio_monitor or (check and self.radio_live)
            mix += self._vol("mon", "radio", r, self.radio_vol if on else 0.0)
            if took is not None:
                took += r * np.float32(self.radio_vol)
        if took is not None:
            take.append(took)
        lowcut = self._lowcut()   # the headphones get the mode's shaping too (_dest)
        for a in self.aux:
            x = a.ring_mon.read(frames)
            if x is not None:
                idle = False
                play = max(play, peak(x) * a.vol)
                on = a.monitor or (check and a.live)
                mix += self._vol("mon", ("aux", a.key), x, a.gain("mon", lowcut) if on else 0.0)
        self.level_play = max(play, self.level_play)   # _main decays it; no main: the UI does
        if idle:   # silence all the way: only the volume's glide and the limiter to keep
            self._bus_quiet("mon", mix, silent=True)
            self._glides[("mon", "out")] = float(self.mon_vol)
            y = self._stage("mon", SafetyLimiter).silence(frames)
            if y is None:
                outdata.fill(0)
                self.level_mon *= 0.85
                return
            mix = y
        else:
            finite(mix)
            if check:   # you hear what others get: the same send stage, your mic in it
                mix = self._send_bus("mon", mix, m)
                if self.limiter_on:
                    mix = self._stage("mon", Limiter).process(mix)
            elif not self._bus_quiet("mon", mix):
                mix = self._dest("mon", self._eq("mon", "sounds", mix))
            mix = self._vol("mon", "out", mix, self.mon_vol)
            mix = self._stage("mon", SafetyLimiter).process(mix)
        outdata[:] = mix
        self.level_mon = max(peak(mix), self.level_mon * 0.85)

    def _mon_voice(self, outdata, frames):
        """Hear my voice: your changed voice alone in your headphones (previews still
        play), to tune a voice without your sounds over it."""
        mix = self._sounds("mon", frames, previews_only=True, makeup=False)   # no _dest here
        self.ring_rmon.read(frames)        # keep the others' rings drained meanwhile
        for a in self.aux:
            a.ring_mon.read(frames)
        m = self.ring_mon.read(frames)
        if m is not None:
            on = self.mic_enabled and not self.mic_muted
            mix += self._vol("mon", "mic", m, self.mic_vol if on else 0.0)
        mix = self._vol("mon", "out", finite(mix), self.mon_vol)
        mix = self._stage("mon", SafetyLimiter).process(mix)
        outdata[:] = mix
        self.level_mon = max(peak(mix), self.level_mon * 0.85)

    def device_delay(self) -> float | None:
        """Seconds your mic and send device add on their own (what the drivers report,
        plus the mic ring's cushion), or None while they aren't open."""
        try:
            mic, out = self.mic_stream, self.main_stream
            if mic is None or out is None:
                return None
            return float(mic.latency) + float(out.latency) + 0.015
        except Exception:  # noqa: BLE001 - a stream closing meanwhile
            return None

    def _obs(self, outdata, frames):
        """The stream output: what others get (sounds, the live radio and programs,
        your mic if obs_voice), clean: no voice chat shaping, no mono, its own volume."""
        mix = self._sounds("obs", frames, makeup=False)   # clean: no _dest, so no makeup
        mix = self._vol("obs", "sounds", mix, self.sound_vol)
        r = self.ring_robs.read(frames)
        if r is not None:
            mix += self._vol("obs", "radio", r, self.radio_vol if self.radio_live else 0.0)
        for a in self.aux:
            x = a.ring_obs.read(frames)
            if x is not None:
                mix += self._vol("obs", ("aux", a.key), x, a.vol if a.stream else 0.0)
        mix = self._eq("obs", "sounds", finite(mix))
        m = self.ring_obs.read(frames)
        if m is None:
            self._glides[("obs", "mic")] = 0.0   # nothing coming: it fades in when it does
        else:
            on = self.obs_voice and self.mic_enabled and not self.mic_muted
            if on or self._glides.get(("obs", "mic"), 0.0):   # on, or still fading out
                m = self._vol("obs", "mic", self._gated("obs", m), self.mic_vol if on else 0.0)
                mix += self._eq("obs", "voice", m)
        # muted: the stream gets silence too (faded, not cut)
        mix = self._vol("obs", "out", mix, self.obs_vol if self.sending else 0.0)
        if self.limiter_on:
            mix = self._stage("obs", Limiter).process(mix)
        mix = self._stage("obs", SafetyLimiter).process(mix)
        outdata[:] = mix
        self.level_obs = max(peak(mix), self.level_obs * 0.85)

    def _send_bus(self, out: str, mix: np.ndarray, m: np.ndarray | None,
                  add_mic: bool = True, silent: bool = False) -> np.ndarray:
        """The sounds bus shaped for voice chat (EQ, destination mode, ducking under
        your voice, phase-aware mono), with the mic block `m` added on top (unless not
        `add_mic`: the mic effect's add mode, where Windows keeps the mic itself).
        `silent`: the bus is known to be zeros (_bus_idle), so there's nothing to shape."""
        mic_on = m is not None and self.mic_enabled and not self.mic_muted
        quiet = self._bus_quiet(out, mix, silent)
        if not quiet:
            mix = self._dest(out, self._eq(out, "sounds", mix))
        if self.duck_db < 0 or (out, "Ducker") in self._send:
            g = self._stage(out, Ducker).process(m if mic_on else None, len(mix), self.duck_db)
            if not isinstance(g, float) and not silent:
                mix = mix * g
        # a mode that already made the bus mono (every built-in one) needs no second pass
        if self.send_mono and not quiet and not (self.dest is not None and self.dest.mono):
            mix = self._stage(out, SmartMono).process(mix)
        if mic_on and add_mic:
            m = self._gated(out, m)
            mix += self._eq(out, "voice", self._vol(out, "mic", m, self.mic_vol))
        elif mic_on:
            self._gated(out, m)   # (keeps the gate's level current for _direct_mic_gain)
        return mix

    def _direct_mic_gain(self):
        """The real mic's level, applied by the mic effect (mute, mic volume, the gate
        while a sound plays, and nothing at all while sending is off). Add mode: always
        heard. Replace mode: only when the effect fills in for a block the board was
        late with; a changed voice then stays quiet rather than let the real one out."""
        d = self.direct_stream()
        if d is None:
            return
        on = self.mic_enabled and not self.mic_muted and self.sending
        if self.direct_mode == directmic.MODE_REPLACE:
            chain = self.voice_chain
            on = on and not (chain is not None and getattr(chain, "changes_voice", True))
        d.set_mic_gain(self.mic_vol * self._gate.get("main", 1.0) if on else 0.0)

    def _vol(self, out: str, what, x: np.ndarray, v: float) -> np.ndarray:
        """x times the volume v, gliding over the block from where the last block of
        (out, what) ended. A slider moved, a mute or a switch thrown would otherwise
        step the level in one sample: a crackle while dragging, a click on mute."""
        key = (out, what)
        v = float(v)
        g0 = self._glides.get(key, v)
        self._glides[key] = v
        if g0 == v:
            return x if v == 1.0 else x * np.float32(v)
        env = np.linspace(g0, v, len(x) + 1, dtype=np.float32)[1:]
        return x * (env[:, None] if x.ndim == 2 else env)

    QUIET_S = 0.5   # this long with nothing on a sounds bus: its filters have rung out

    def _bus_quiet(self, out: str, mix: np.ndarray, silent: bool = False) -> bool:
        """True once the sounds bus of `out` has carried only zeros for QUIET_S. Its EQ,
        mode shaping and mono downmix would only be filtering silence then (~1 ms of
        every 10 ms block in a voice chat mode, with nothing playing), so they're
        skipped; their state has long decayed, and the next sound picks them up.
        `silent`: mix is known to be zeros, so there's no need to look."""
        if not silent and mix.any():
            self._quiet[out] = 0
            return False
        n = self._quiet.get(out, 0) + len(mix)
        self._quiet[out] = n
        return n > self.QUIET_S * self.rates[out]

    IDLE_FAST = True   # _bus_idle may skip the mixer (False: every block mixes, as before)

    def _bus_idle(self, out: str, frames: int) -> bool:
        """True when this block of out's sounds bus is sure to be silence that changes
        nothing: no sound live on it, no live effect or pitch at work, and its filters
        long rung out (_bus_quiet). The callback then skips the mixer, which with
        nothing playing was most of the engine's CPU. _wake_bus catches up after."""
        if not self.IDLE_FAST or self._quiet.get(out, 0) <= self.QUIET_S * self.rates[out]:
            return False
        if self.sound_fx or out in self._sfx or abs(self._sound_st()) >= 0.01:
            return False
        f = self._spitch.get(out)
        if f is not None and f.shift.running:   # still fading out
            return False
        for v in self.voices:
            if out in v.data and out not in v.done:
                return False
        self._idle_n[out] = self._idle_n.get(out, 0) + frames
        return True

    def _wake_bus(self, out: str):
        """Before the mixer runs again after idle blocks: the live pitch gets the
        silence it would have kept meanwhile, so switching it on starts as before."""
        n = self._idle_n.pop(out, 0)
        if n:
            f = self._spitch.get(out)
            if f is not None:
                f.skip_silence(n)

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

    MIC_DEAD = 0.01   # a mic channel under this share of the other's power (-20 dB) is dead
    MIC_ALIVE = 0.05  # ...and alive again above this (-13 dB): no flapping in between

    def _mic_channels(self, x: np.ndarray) -> np.ndarray:
        """A two-channel mic with one live input (an audio interface's input 1, a
        headset adapter): the live channel is copied over the dead one. Otherwise
        voice chat's mono mix would halve it (-6 dB), and mic check is one-sided."""
        p = np.einsum("ij,ij->j", x, x)   # each channel's power, in one go
        a = self._mic_pow
        a[0] += (float(p[0]) - a[0]) * 0.05   # ~0.2 s at 10 ms blocks
        a[1] += (float(p[1]) - a[1]) * 0.05
        if a[0] + a[1] > 1e-6 * len(x):   # the mic hears something (about -60 dBFS)
            d = self._mic_dead
            if d is not None and a[d] > a[1 - d] * self.MIC_ALIVE:
                d = None
            if d is None:
                d = 0 if a[0] < a[1] * self.MIC_DEAD else 1 if a[1] < a[0] * self.MIC_DEAD else None
            self._mic_dead = d
        d = self._mic_dead
        if d is not None:
            x[:, d] = x[:, 1 - d]
        return x

    def _mic(self, indata, direct: bool = False):
        x = indata
        two = x.shape[1] >= 2
        x = np.repeat(x, 2, axis=1) if x.shape[1] == 1 else x[:, :2]
        x = np.ascontiguousarray(x, dtype=np.float32)
        if two:   # a copy (it may still be a view of PortAudio's buffer): written to
            x = self._mic_channels(x.copy() if np.shares_memory(x, indata) else x)
        self.level_mic = max(peak(x), self.level_mic * 0.85)
        rec = self._mic_rec
        raw = x[:, 0].copy() if rec is not None and self._rec_buf is not None else None
        take = self._take   # Record a sound: one copy and one append, nothing more
        if take is not None and not self._take_fx:
            take.append(x.copy())
        chain = self.voice_chain
        if chain is not None:   # after the meter: that judges the real mic
            x = chain.process(x, self.rates["mic"])
        if raw is not None:     # a test: the real mic (did you talk?) and what's sent
            rec.append(np.stack([raw, x[:, 0]], 1))
        if take is not None and self._take_fx:
            take.append(x.copy())
        if self.main_stream is not None:
            if not self.main_direct:
                self.ring_main.write(self._rs_main(x))
            elif direct:   # straight into the mic: the same stretch goes out right after
                self.fifo_direct.write(self._rs_main(x))
        fed = self.mic_check and self.mon_stream is not None
        if fed:
            self.ring_mon.write(self._rs_mon(x))
        elif self._mon_fed:   # mic check stopped: an emptied ring isn't clock drift
            self.ring_mon.clear()
        self._mon_fed = fed
        fed = self.obs_voice and self.obs_stream is not None
        if fed:
            self.ring_obs.write(self._rs_obs(x))
        elif self._obs_fed:
            self.ring_obs.clear()
        self._obs_fed = fed
