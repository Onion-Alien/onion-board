"""The engine's plain parts: the buffers between audio clocks (Ring, DirectFifo), the
stream resampler, the sounds' Voice, the captured programs' AuxSource, the live pitch
shifter, the device thread, and the small sample helpers the mix uses.

Moved out of soundboard.audio.engine as they were; that module still imports every name, so
`from soundboard.audio.engine import Ring` keeps working. Nothing here opens a device or
reads the device list (that's devicelist.py; tests swap its names in engine).
"""
from __future__ import annotations

import functools
import math
import logging
import queue
import threading
import time
from dataclasses import dataclass, field

import numpy as np
import soxr

from soundboard.mic import destination
from soundboard.audio.dsp import hermite
from soundboard.voicefx.builtin import PitchShift

# the engine's logger, as before the move (log lines and filters keep their name)
log = logging.getLogger("soundboard.audio.engine")

SR = 48000  # library storage rate
CH = 2
I16_SCALE = np.float32(1 / 32767.0)   # int16 sound data -> float
STALL_S = 1.5   # a stream whose callback hasn't run for this long is dead: reopen it
RETRY_S = 5.0   # how often to retry a device that failed to open
# a sound cut off by its outputs closing (a rescan, a stalled device) waits this long
# for one to reopen before it counts as finished (a slow driver can take seconds)
CUT_KEEP_S = 30.0
# What each Audio buffering choice asks PortAudio for, for the outputs. Windows' shared
# mode never goes below its own 10 ms period, so 'low' and PortAudio's 'high' (10 ms)
# both came out as 22 ms with ~10 ms to spare per block; asking for a number buys real
# room. The audio callbacks run Python, so they wait whenever the UI thread is in one
# long Qt call (a window or page shown the first time: 60-150 ms on a real screen), and
# with ~10 ms to spare a sound playing skipped each time. 150 ms queued
# covers those; the sounds come that much later, which nobody hears on a soundboard.
BUFFER = {"low": 0.15, "high": 0.25}
# ...and for the mic: what's queued there is your voice's delay, so it stays short
MIC_BUFFER = {"low": "low", "high": 0.04}
# Lite mode's audio block (Engine.set_block): every stream calls back every 20 ms
# instead of the driver's 10, so the audio callbacks run half as often. Each call
# costs about the same at either size (it's mostly Python's per-call overhead), so
# that's most of what they cost with nothing playing. Your voice goes out ~20 ms later
# (the bigger block, and the mic rings' bigger cushion below).
LITE_BLOCK_S = 0.02
# ...and the mic rings at that block: their fill steps a whole block at a time, so they
# need a bigger cushion (at 15 or 20 ms a mic clock 0.2% off ran them dry now and
# then), a higher ceiling (at 80 ms a fast one skipped ahead before tracking started)
# and a longer clock fit (the step is twice the noise in it). (cushion, ceiling) s:
MIC_RING_S, MIC_RING_BIG_S = (0.015, 0.08), (0.025, 0.1)
# the app's own playback: the test recording, cue beeps, the setup wizard's tune, the
# Pong game's sounds (ui/bun/bunpong.py), the mic check's probe (mic/micprobe.py: a
# pitch change would hide it). With
# previews ("<sid>:preview", "<sid>~fx:preview") they ignore the live speed / pitch
FIXED_SIDS = frozenset({"__test__", "__cue__", "__setup__", "__check__", "__pong__",
                        "__probe__"})


def is_fixed(sid: str) -> bool:
    """True for voices the live speed / pitch must leave alone (see FIXED_SIDS)."""
    return sid in FIXED_SIDS or sid.endswith(":preview")


class DeviceWorker:
    """The one thread that does slow device work: closing, opening and re-scanning
    streams, asking Windows for its devices. A driver can take seconds to answer when
    a headset is unplugged, Bluetooth drops or the PC wakes from sleep, and on the UI
    thread that froze the window. Here it only holds up this thread.

    One recovery at a time: claim() first (False: one is running, try again on the
    next check), then run() its steps; whoever claimed calls release() when the last
    step is done. A step that hangs keeps the claim, so nothing piles up behind it.

    The thread stays for good once started. It used to end after 30 s without work and
    the next check (on the UI thread, about once a second) started a new one: starting
    a thread waits for it to run, and on a busy PC short of memory that held the window
    for seconds (freeze reports in run(), `threading.wait`)."""

    def __init__(self, name: str = "devices"):
        self.name = name
        self._q: queue.SimpleQueue = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._idle = threading.Event()
        self._idle.set()

    @property
    def busy(self) -> bool:
        return not self._idle.is_set()

    def claim(self) -> bool:
        with self._lock:
            if not self._idle.is_set():
                return False
            self._idle.clear()
            return True

    def release(self):
        self._idle.set()

    def wait(self, timeout: float | None = None) -> bool:
        """Until nothing is claimed (tests, and quitting). False: still busy."""
        return self._idle.wait(timeout)

    def run(self, fn, done=None):
        """Call fn() on the device thread, then done(its result) there too (None if it
        raised). The caller holds the claim."""
        with self._lock:
            self._q.put((fn, done))
            if self._thread is None:
                self._thread = threading.Thread(target=self._loop, daemon=True, name=self.name)
                self._thread.start()

    def _loop(self):
        while True:
            fn, done = self._q.get()
            t0 = time.monotonic()
            result = None
            try:
                result = fn()
            except Exception:  # noqa: BLE001 - the next recovery must still be able to run
                log.exception("device work failed")
            took = time.monotonic() - t0
            if took > 2:
                log.warning("device work took %.1fs (a slow driver)", took)
            if done is not None:
                try:
                    done(result)
                except Exception:  # noqa: BLE001
                    log.exception("device work's hand-back failed")
                    self.release()


# Held while streams are opened or closed and while PortAudio is re-scanned (torn down
# and started again), which happen on the device thread (DeviceWorker). The device
# lists (engine.list_devices...) never wait for it: during a re-scan PortAudio's list
# is being freed, so they answer from the last list they read instead.
DEVICES = threading.RLock()


def _holding_devices(fn):
    """Engine methods that open or close streams hold DEVICES, so two threads never
    do it at the same time. Call them on the device thread (DeviceWorker; a device
    picked in the window goes through DeviceControl._device_job), not the UI thread: a
    recovery stuck holding DEVICES there would freeze the window."""
    @functools.wraps(fn)
    def run(*a, **k):
        with DEVICES:
            return fn(*a, **k)
    return run


def close_quietly(s, what):
    try:
        s.close()
    except Exception:  # noqa: BLE001
        log.debug("closing %s raised", what, exc_info=True)


def start_or_close(s, what):
    """Start a freshly made stream; if that fails, close it before re-raising, or
    every RETRY_S retry of a busy device leaks one PortAudio stream."""
    try:
        s.start()
    except Exception:
        close_quietly(s, what)
        raise

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
        self.est_scale = 1.0   # auto_drift's fits take this many times longer (set_block)
        self.configure(rate)

    def configure(self, rate: int):
        with self.lock:
            self.cap = max(rate // 2, int(rate * self.max_s * 2))
            self.buf = np.zeros((self.cap, CH), np.float32)
            self.prefill = int(rate * self.prefill_s)   # jitter cushion before (re)starting
            self.max_fill = int(rate * self.max_s)      # beyond this, skip ahead (latency)
            self.max_prefill = max(self.prefill, int(rate * self.grow_to_s))
            self.fade = max(1, int(rate * self.FADE_S))
            self._stop_left = 0   # frames left of a fade_out()
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
        self._est_next = int(self.rate * self.EST_MIN_S * self.est_scale)
        self._est_side = 0       # the side the last fit came out on (+1 fast, -1 slow)
        self.drift_est = 1.0     # the last fit's writer/reader clock ratio

    def _mic_err(self, n: int) -> float:
        """The drift controller's error for a mic ring, aimed at the fill a read finds
        right after priming: the cushion plus the read (aimed at the bare cushion, it
        read the ring dry again and again: the mic's is only 1.5 blocks, 1.25 at lite
        mode's 20 ms blocks). The fill a
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
        self._est_next = self._ex + int(self.rate * self.EST_CHECK_S * self.est_scale)
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
            self._clear()

    def _clear(self):
        self.r = self.w = self.count = 0
        self.primed = False
        self._fade_in = True
        self._stop_left = 0
        self._est_reset()

    def fade_out(self):
        """The source stopped: the next reads play what's queued for `fade` more
        frames, fading to silence, and drop the rest (no hard edge, no play-out)."""
        with self.lock:
            if self.count and self.primed:
                self._stop_left = self.fade
            else:
                self._clear()

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
            if self._stop_left:
                k = min(n, self.count, self._stop_left)
                out = np.zeros((n, CH), np.float32)
                g = (self._stop_left - np.arange(1, k + 1)) / np.float32(self.fade)
                out[:k] = self._peek(k) * g.astype(np.float32)[:, None]
                self.r = (self.r + k) % self.cap
                self.count -= k
                self._stop_left -= k
                if k < n or not self._stop_left:
                    self._clear()
                return out
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
        assert self.rs is not None   # made unless the rates match
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


def loud_boost(x: np.ndarray, vol: float, ceiling: float = 1.0) -> np.ndarray:
    """A volume over 100 %: the extra comes from rounding the peaks off (soft_limit,
    scaled to the `ceiling` of the limiter that follows), so a song gets louder. The
    limiter alone turned the whole song down at each peak: 300 % and 1000 % came out
    the same. At 100 % and below the path stays clean (in place)."""
    if vol <= 1.0:
        return x
    if ceiling == 1.0:
        return soft_limit(x)
    c = np.float32(ceiling)
    x /= c
    soft_limit(x)
    x *= c
    return x


def peak(x: np.ndarray) -> float:
    return float(np.abs(x).max()) if len(x) else 0.0


def finite(x: np.ndarray) -> np.ndarray:
    """`x` with any NaN / Inf sample made silent (in place). One such sample would stay
    in the send chain's filters for good: the call would hear nothing until a restart."""
    finite_peak(x)
    return x


def finite_peak(x: np.ndarray) -> float:
    """finite(x), then peak(x): one pass over |x| for both, unless it had to clean."""
    if not len(x):
        return 0.0
    pk = float(np.abs(x).max())
    if not math.isfinite(pk):
        np.nan_to_num(x, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
        pk = peak(x)
    return pk


def limit_peak(x: np.ndarray, knee: float = 0.89) -> float:
    """soft_limit(x), then peak(x): one pass over |x| for both while nothing is over
    the knee (always, after a Limiter)."""
    if not len(x):
        return 0.0
    pk = float(np.abs(x).max())
    if pk > knee:
        soft_limit(x, knee)
        pk = peak(x)
    return pk


def is_xrun(status) -> bool:
    """True if a callback status reports a real drop-out (not just output priming)."""
    if not status:
        return False
    return bool(status.output_underflow or status.output_overflow
                or status.input_underflow or status.input_overflow)


def _add(acc: np.ndarray | None, x: np.ndarray) -> np.ndarray:
    """acc + x, starting a new sum (a copy: x may be a ring's buffer) when acc is None."""
    if acc is None:
        return np.array(x, dtype=np.float32)
    acc += x
    return acc


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
    cut_at: float = 0.0        # when an output was last cut (see CUT_KEEP_S)
    # out -> the gain its last block ended at (_render glides from there to a new one)
    gnow: dict = field(default_factory=dict)
    # Edit sound's changes heard at once (a livefx.Stage, Engine.set_sound_live; None:
    # none): its speed multiplies the live speed, the rest runs per output in `stage`
    # (out -> livefx.SoundStage). `ring`: out -> frames played on past its end, while
    # its echo / reverb dies away
    live: tuple | None = None
    stage: dict = field(default_factory=dict)
    ring: dict = field(default_factory=dict)

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
    def silent(self) -> bool:
        """No output plays it now (a cut one may still resume: see finished)."""
        return self.done >= self.outs

    @property
    def finished(self) -> bool:
        # cut off everywhere by a rescan isn't finished: the UI's poll would drop it
        # before the outputs reopen, and nothing would be left to resume
        return self.silent and (
            not self.cut or self.stopping or time.monotonic() - self.cut_at > CUT_KEEP_S)

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
                if frac is not None:
                    return frac
                p = self.pos[o]   # (a one-shot's echo tail goes on at its end)
                return (p % len(d) if self.loop else min(p, len(d))) / len(d)
        return 1.0
