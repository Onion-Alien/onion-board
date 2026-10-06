"""Built-in voice effects: plain numpy DSP (filters from soundboard.dsp), cheap enough
for the mic callback.

Every effect works on 1-D float32 blocks and keeps its own memory between blocks.
Recursive delays (echo, reverb) are computed in chunks no longer than their delay,
so each chunk only depends on output that already exists: whole-array numpy maths
instead of a per-sample Python loop.

The effects run in the order they are registered here (pitch first, room last):
a voice is shaped, then squashed, then band-limited and driven, then put in a
space. The presets at the bottom are built from these building blocks.
"""
from __future__ import annotations

import numpy as np
from soundboard.dsp import (SmoothSos, butter, hermite, lfilter, matched_biquad, sosfilt,
                             sosfilt_bank)
from soundboard.voicefx import Effect, Param, register

F32 = np.float32


def _one_pole_lowpass(hz: float, rate: int) -> np.ndarray:
    return butter(1, min(hz, rate * 0.45), btype="low", fs=rate).astype(F32)


def _biquad(kind: str, f0: float, rate: int, gain_db: float, q: float = 0.707) -> np.ndarray:
    """One EQ band as a (1, 6) sos row: 'peak', 'lowshelf' or 'highshelf', matched to
    its analog shape up to Nyquist (dsp.matched_biquad)."""
    return matched_biquad(kind, f0, gain_db, rate, q)[None].astype(F32)


class _Filter:
    """A filter with memory, redesigned only when its settings change. A new design
    (or None: straight through) is crossfaded in over the block, so turning a knob
    doesn't click (dsp.SmoothSos)."""

    def __init__(self):
        self.key = None
        self.sos = None
        self.f = SmoothSos()

    def run(self, x: np.ndarray, key, design) -> np.ndarray:
        if key != self.key:
            self.key, self.sos = key, design()
        return self.f.run(x, self.sos).astype(F32, copy=False)



class _Line:
    """A delay line of `d` samples, as a ring: take() the oldest c (c <= d), then
    put() c new ones in their place. Was a np.concatenate of the whole line per
    block (a 1 s echo copied 190 KB every few ms)."""

    def __init__(self, d: int):
        self.buf = np.zeros(d, F32)
        self.at = 0     # the oldest sample

    def __len__(self) -> int:
        return len(self.buf)

    def take(self, c: int) -> np.ndarray:
        """The oldest c samples (a view when they don't wrap: use before put)."""
        a, d = self.at, len(self.buf)
        if a + c <= d:
            return self.buf[a:a + c]
        return np.concatenate([self.buf[a:], self.buf[:a + c - d]])

    def put(self, v: np.ndarray) -> None:
        """Replace the oldest len(v) samples with v (the newest)."""
        a, d, c = self.at, len(self.buf), len(v)
        k = min(c, d - a)
        self.buf[a:a + k] = v[:k]
        if c > k:
            self.buf[:c - k] = v[k:]
        self.at = (a + c) % d


class _Stft:
    """Streaming short-time Fourier processing for one mono stream: `run(x, fn)`
    cuts the input into Hann-windowed frames (hop = n/4), hands all the frames that
    are ready to fn((frames, bins) complex) -> same shape, and overlap-adds the
    result. Always returns len(x) samples; the delay is exactly n samples (one frame,
    because a frame can only be processed once all of it has arrived)."""

    def __init__(self, n: int):
        self.n = n = max(64, n - n % 4)
        self.hop = n // 4
        self.win = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n) / n)).astype(F32)
        self.norm = F32(self.hop / float(np.sum(self.win ** 2)))
        self.buf = np.zeros(n - self.hop, F32)     # the last frame's overlap
        self.acc = np.zeros(n, F32)                 # overlap-add still being summed
        self.out = np.zeros(self.hop, F32)          # finished output, not yet handed back

    def run(self, x: np.ndarray, fn) -> np.ndarray:
        n, hop = self.n, self.hop
        buf = np.concatenate([self.buf, x])
        frames = (len(buf) - n) // hop + 1 if len(buf) >= n else 0
        done = [self.out]
        if frames > 0:
            idx = np.arange(n)[None, :] + hop * np.arange(frames)[:, None]
            spec = np.fft.rfft(buf[idx] * self.win, axis=1)
            y = np.fft.irfft(fn(spec), n, axis=1).astype(F32) * (self.win * self.norm)
            acc = np.concatenate([self.acc, np.zeros(hop * frames, F32)])
            for f in range(frames):
                acc[f * hop:f * hop + n] += y[f]
            done.append(acc[:hop * frames])
            self.acc = acc[hop * frames:].copy()
            buf = buf[hop * frames:]
        self.buf = buf.copy()
        out = np.concatenate(done)
        self.out = out[len(x):].copy()
        return out[:len(x)]


def _stft_size(rate: int, seconds: float) -> int:
    return max(64, int(rate * seconds) // 4 * 4)


class _PitchTracker:
    """The voice's pitch, block by block (YIN on the last ~32 ms, decimated to about
    12 kHz so it costs next to nothing). `update(x)` returns Hz, or 0 while there's
    no clear pitch (silence, breath, s and f sounds)."""

    LO_HZ, HI_HZ = 65.0, 1000.0

    def __init__(self, rate: int):
        self.dec = max(1, int(rate // 12000))
        self.sr = rate / self.dec
        self.tmin = max(2, int(self.sr / self.HI_HZ))
        self.tmax = int(self.sr / self.LO_HZ) + 1
        self.hist = np.zeros(2 * self.tmax * self.dec, F32)
        self.f0 = 0.0

    @property
    def window(self) -> int:
        """Input samples one measurement looks at."""
        return len(self.hist)

    def update(self, x: np.ndarray) -> float:
        h, n = self.hist, len(x)
        if n >= len(h):
            h[:] = x[n - len(h):]
        else:
            h[:-n] = h[n:]
            h[-n:] = x
        return self.measure(h)

    def measure(self, h: np.ndarray) -> float:
        """Pitch of exactly `window` samples."""
        w = h.reshape(-1, self.dec).mean(axis=1).astype(np.float64)
        w -= w.mean()
        if float(np.sqrt(np.mean(w * w))) < 3e-3:      # about -50 dBFS: nothing to track
            self.f0 = 0.0
            return 0.0
        tmax, size = self.tmax, len(w) - self.tmax
        cs = np.concatenate([[0.0], np.cumsum(w * w)])
        e0 = cs[size]
        et = cs[size:size + tmax] - cs[:tmax]          # energy of w[t : t + size]
        m = 1 << int(np.ceil(np.log2(len(w) + size)))
        r = np.fft.irfft(np.fft.rfft(w, m) * np.conj(np.fft.rfft(w[:size], m)), m)[:tmax]
        d = np.maximum(e0 + et - 2 * r, 0.0)
        d[0] = 0.0
        cm = d[1:] * np.arange(1, tmax) / np.maximum(np.cumsum(d[1:]), 1e-12)
        cm = np.concatenate([[1.0], cm])
        cand = np.flatnonzero(cm[self.tmin:] < 0.2)
        if len(cand):
            t = int(cand[0]) + self.tmin
            while t + 1 < tmax and cm[t + 1] < cm[t]:
                t += 1
        else:
            t = int(np.argmin(cm[self.tmin:])) + self.tmin
            if cm[t] > 0.35:
                self.f0 = 0.0
                return 0.0
        if 0 < t < tmax - 1:                            # parabolic: between two lags
            a, b, c = cm[t - 1], cm[t], cm[t + 1]
            den = a - 2 * b + c
            tt = t + (0.5 * (a - c) / den if abs(den) > 1e-12 else 0.0)
        else:
            tt = float(t)
        self.f0 = self.sr / tt
        return self.f0


def _snap(hz: float) -> float:
    """The nearest note (equal temperament, A = 440 Hz)."""
    return 440.0 * 2.0 ** (round(12 * np.log2(hz / 440.0)) / 12)


def _envelope_shift(spec: np.ndarray, factor: float, lifter: int) -> np.ndarray:
    """Move each frame's spectral envelope (the voice's formants: the size and shape
    of the throat and mouth) by `factor` along the frequency axis while keeping its
    fine structure (the pitch's harmonics). The envelope is the low part of the
    cepstrum; each bin is scaled by envelope(f / factor) / envelope(f)."""
    n = 2 * (spec.shape[1] - 1)
    logm = np.log(np.abs(spec) + 1e-7)
    cep = np.fft.irfft(logm, n, axis=1)
    cep[:, lifter:n - lifter + 1] = 0.0
    env = np.fft.rfft(cep, axis=1).real
    k = np.arange(spec.shape[1]) / factor
    i0 = np.minimum(k.astype(np.int64), spec.shape[1] - 1)
    i1 = np.minimum(i0 + 1, spec.shape[1] - 1)
    f = np.minimum(k - i0, 1.0)
    warped = env[:, i0] * (1 - f) + env[:, i1] * f
    return spec * np.exp(np.clip(warped - env, -3.5, 3.5))


# --------------------------------------------------------------------------- clean-up

@register
class Cleanup(Effect):
    """Your mic, cleaned before any other effect touches it: rumble below 80 Hz
    filtered out, a noise gate that closes between words (it learns your room's
    noise level by itself), and hiss removal (a spectral filter that learns the
    noise's sound while you're quiet). Pitch shifting and distortion turn steady
    noise into warble and fizz, so this is most of what makes a changed voice
    sound clean."""

    type = "cleanup"
    name = "Clean up my mic"
    description = "Removes hum, hiss and room noise before the other effects."
    params = (Param("gate", "Noise gate", 0, 1, 0.6, "", 0, ("off", "strong")),
              Param("hiss", "Hiss removal", 0, 1, 0.5, "", 0, ("off", "strong")))

    SUB_S = 0.0025      # the gate decides every 2.5 ms
    HOLD_S = 0.2        # and stays open this long after you stop
    FLOOR_S = 1.5       # the room's noise: the quietest moment this far back
    FRAME_S = 0.0107    # hiss removal's frame (its added latency): 512 at 48 kHz
    CREEP_DB = 3.0      # how fast (dB/s) the noise estimate rises while you talk

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        rate = rate or 48000
        self.hp = _Filter()
        self.sub = max(16, int(rate * self.SUB_S))
        self.floor_db = -70.0
        self.mins: list[tuple[float, float]] = []   # (seconds, quietest dB) per block
        self.open = False
        self.held = 0.0
        self.g = 1.0
        self.stft: _Stft | None = None
        self.noise: np.ndarray | None = None   # the noise's power per frequency
        self.prev_gain: np.ndarray | None = None
        self.creep = 1.0

    def latency(self) -> float:
        if self.p["hiss"] <= 0:
            return 0.0
        return (self.stft.n if self.stft else _stft_size(self.rate, self.FRAME_S)) / self.rate

    def _gate(self, x, rate):
        """Downward expander, decided per 2.5 ms piece and ramped sample by sample."""
        strength = self.p["gate"]
        n, sub = len(x), self.sub
        pieces = max(1, n // sub)
        edges = np.linspace(0, n, pieces + 1).astype(int)
        lv = np.array([np.sqrt(np.mean(x[a:b] ** 2) + 1e-12)
                       for a, b in zip(edges[:-1], edges[1:])])
        db = 20 * np.log10(lv)
        dt = n / rate
        # the noise floor: the quietest moment of the last FLOOR_S (between words you
        # always drop to the room's noise), so it learns a noisy room straight away
        # and follows it if it gets louder or quieter
        self.mins.append((dt, max(float(db.min()), -90.0)))
        span = sum(t for t, _ in self.mins)
        while len(self.mins) > 1 and span - self.mins[0][0] >= self.FLOOR_S:
            span -= self.mins.pop(0)[0]
        self.floor_db = min(min(m for _, m in self.mins), -38.0)
        open_at, close_at = max(self.floor_db + 9, -60), max(self.floor_db + 5, -64)
        closed_g = 10 ** (-30 * strength / 20)
        gains = np.empty(pieces)
        g = self.g
        for i, d in enumerate(db):
            piece = (edges[i + 1] - edges[i]) / rate
            if d > open_at:
                self.open, self.held = True, 0.0
            elif self.open and d < close_at:
                self.held += piece
                if self.held > self.HOLD_S:
                    self.open = False
            target = 1.0 if self.open else closed_g
            tau = 0.002 if target > g else 0.06
            g = target + (g - target) * np.exp(-piece / tau)
            gains[i] = g
        ramp = np.interp(np.arange(n), np.r_[-1, edges[1:] - 1], np.r_[self.g, gains])
        self.g = float(g)
        return (x * ramp).astype(F32)

    def _dehiss(self, spec):
        strength = self.p["hiss"]
        power = (spec.real ** 2 + spec.imag ** 2).astype(np.float64)
        if self.noise is None:   # start low: what you say first mustn't count as noise
            self.noise = power.mean(axis=0) * 1e-3 + 1e-12
        frame_db = 10 * np.log10(power.mean(axis=1) + 1e-20)
        out = np.empty_like(spec)
        over = 1.0 + strength            # subtract a bit more than the estimate
        floor = 10 ** (-18 * strength / 20)
        for f in range(len(spec)):
            noise_db = 10 * np.log10(self.noise.mean() + 1e-20)
            gated = self.p["gate"] > 0 and not self.open
            if gated or frame_db[f] < noise_db + 3:   # quiet: learn the noise
                self.noise = 0.9 * self.noise + 0.1 * power[f]
            else:   # creeps up (~3 dB/s), so a louder room is learned even mid-talk
                self.noise *= self.creep
            g = np.maximum(1 - over * self.noise / (power[f] + 1e-20), floor)
            g = np.convolve(g, (0.25, 0.5, 0.25), "same")     # less "musical noise"
            if self.prev_gain is not None:
                g = np.maximum(g, 0.6 * self.prev_gain)      # fades out, never snaps
            self.prev_gain = g
            out[f] = spec[f] * g
        return out

    def run(self, x, rate):
        y = self.hp.run(x, "hp", lambda: butter(2, 80, btype="high", fs=rate).astype(F32))
        if self.p["gate"] > 0:
            y = self._gate(y, rate)
        else:
            self.open = True
        if self.p["hiss"] > 0:
            if self.stft is None:
                self.stft = _Stft(_stft_size(rate, self.FRAME_S))
                # per frame, so the rise is CREEP_DB a second at any rate
                self.creep = 10 ** (self.CREEP_DB / 10 * self.stft.hop / rate)
            y = self.stft.run(y, self._dehiss)
        else:
            self.stft = None
        return y


# --------------------------------------------------------------------------- pitch

@register
class PitchShift(Effect):
    """Time-domain pitch shifter (WSOLA, the SoundTouch approach).

    The voice is first time-stretched by the pitch ratio: it is cut into short
    overlapping sequences, and each one is spliced onto the previous at the
    offset where the two waveforms line up best (a cross-correlation search), so
    the splices fall on the voice's own period and don't beat against it. Then
    the stretched audio is resampled back to the original length, which moves
    the pitch and the formants together (the chipmunk / giant sound people expect
    from a voice changer). Latency is about SEQ + SEEK + one block, ~50 ms.

    Natural sound and Voice size move the formants on their own (_envelope_shift,
    one more ~20 ms frame): Natural 100% puts them back where your own voice has
    them, so a pitch change sounds like another person rather than a cartoon, and
    Voice size makes the throat behind the voice bigger or smaller (below 100% Mix
    it reshapes the blended-in own voice as well, in its own frame). Both at 0 (the
    default, and what sounds and music use) skip that stage entirely.

    Autotune snaps the voice to the nearest note: a pitch tracker on the input picks
    the correction, which glides in (slow: natural tuning) or jumps (100%: the hard
    T-Pain effect).

    While bypassed (0 st) it keeps the last HIST_S of input, and switching on
    stretches that first, so the output doesn't go silent for the latency.
    Switching on or off crossfades dry <-> wet over XF_MS (no click).
    """

    type = "pitch"
    name = "Pitch"
    description = ("Higher or lower; a cartoon or a real-sounding person; a bigger or "
                   "smaller throat; autotune.")
    params = (Param("semitones", "Pitch", -12, 12, 0, " st", 0.5, ("lower", "higher")),
              Param("natural", "Natural sound", 0, 1, 0, "", 0, ("cartoon", "real person")),
              Param("size", "Voice size", -12, 12, 0, "", 0.5, ("smaller", "bigger")),
              Param("tune", "Autotune", 0, 1, 0, "", 0, ("off", "robotic")),
              Param("mix", "Mix", 0, 1, 1),
              Param("gap", "Gap between voices", 0, 1, 1, "", 0, ("together", "echo")),
              Param("blur", "Blur on the new voice", 0, 1, 0, "", 0, ("clear", "blurry")))

    SEQ_MS = 30.0       # one sequence of voice, copied to the output
    SEEK_MS = 10.0      # how far the splice point may move to line up
    OVL_MS = 7.0        # crossfade between one sequence and the next
    XF_MS = 10.0        # dry <-> wet crossfade when it switches on or off
    HIST_S = 0.35       # input kept while bypassed (enough to prime it at -24 st)
    FORMANT_S = 0.02    # the formant stage's frame (its added latency)
    LIFTER_S = 0.0011   # cepstrum kept as the envelope: shorter than any voice's period
    GAP_MAX_S = 0.15    # longest the blended-in voice can be held back to line up
    GAP_PER_OCTAVE_S = 0.0073   # the shifted voice's extra delay per octave down
    BLUR_SIZE, BLUR_TONE = 0.0, 9000.0   # the room Blur puts round the shifted voice: small
    BLUR_SCOOP_HZ, BLUR_SCOOP_DB = 500.0, 20.0   # ...minus its middle

    def __init__(self, rate, values=None, channels: int = 0):
        """channels: 0 for a mono voice ((n,) blocks); 2 for stereo (n, 2) blocks, cut
        and spliced at the same places in both channels (the engine's live pitch on
        music: channels spliced on their own smear the stereo picture, and flange
        once a call folds them to mono)."""
        super().__init__(rate, values)
        self.shape = (channels,) if channels else ()
        self.seq = int(rate * self.SEQ_MS / 1000)
        self.seek = int(rate * self.SEEK_MS / 1000)
        self.ovl = int(rate * self.OVL_MS / 1000)
        self.fade_in = np.linspace(0, 1, self.ovl, endpoint=False, dtype=F32)
        if channels:
            self.fade_in = self.fade_in[:, None]
        self.fade_out = F32(1) - self.fade_in
        self.aa = _Filter()
        self.running = False
        self.hist = np.zeros((int(rate * self.HIST_S),) + self.shape, F32)
        self.xf = max(1, int(rate * self.XF_MS / 1000))
        self.wet_g = 0.0        # 0 = dry, 1 = wet
        self.ratio, self.mix = 1.0, 1.0
        self.formant = 1.0      # formant correction applied after the shift (1 = none)
        self.fstage: _Stft | None = None
        self.dstage: _Stft | None = None   # Voice size on the unshifted voice (Mix < 100%)
        self.dhist = np.zeros(int(rate * self.GAP_MAX_S), F32)   # blended-in voice, held back
        self.verb: Reverb | None = None     # Blur: a reverb on the shifted voice only
        self.lifter = max(8, int(rate * self.LIFTER_S))
        self.tracker: _PitchTracker | None = None
        self.tune_st = 0.0      # autotune's correction right now, in semitones
        self._reset(1.0)

    def _need(self, tempo: float) -> int:
        """Input the stretcher needs on hand before it can cut the next sequence."""
        return max(self.seek + self.seq, int((self.seq - self.ovl) * tempo) + 2)

    def _reset(self, ratio: float):
        self.inb = np.zeros((0,) + self.shape, F32)   # mic audio waiting to be stretched
        self.mid = np.zeros((self.ovl,) + self.shape, F32)   # the last sequence's tail
        self.skip = 0.0                         # fractional input position carried over
        # The stretcher can only start once it has a sequence's worth of input, so the
        # resampler starts that far behind (the effect's latency); the head start is
        # exactly what keeps it fed afterwards, whatever the mic's block size.
        # (autotune moves the ratio as you talk: a little more head start for that)
        head = self._need(1 / ratio) * ratio * (1.08 if self.p.get("tune", 0) > 0 else 1.0)
        # (its first sample is the one before the resampler's position: _resample)
        self.stretched = np.zeros((int(head) + 5,) + self.shape, F32)
        self.rs_phase = 0.0
        self.pads = 0                           # times the resampler still had to wait

    def _stretch(self, tempo: float) -> list[np.ndarray]:
        """Consume `inb`, producing (seq - ovl)-sample chunks at 1/tempo the speed."""
        seq, ovl, seek = self.seq, self.ovl, self.seek
        body = seq - ovl
        need = self._need(tempo)
        out = []
        while len(self.inb) >= need:
            cand = self.inb[:seek + ovl]
            if cand.ndim == 1:
                corr = np.correlate(cand, self.mid, "valid")      # seek + 1 candidates
                cs = np.cumsum(cand.astype(np.float64) ** 2)
            else:   # all channels together: one splice point for all of them
                corr = sum(np.correlate(cand[:, c], self.mid[:, c], "valid")
                           for c in range(cand.shape[1]))
                cs = np.cumsum((cand.astype(np.float64) ** 2).sum(1))
            energy = cs[ovl - 1:] - np.concatenate([[0.0], cs[:seek]])
            k = int(np.argmax(corr / np.sqrt(energy + 1e-9)))
            s = self.inb[k:k + seq]
            out.append(self.mid * self.fade_out + s[:ovl] * self.fade_in)
            out.append(s[ovl:body])
            self.mid = s[body:].copy()
            adv = body * tempo + self.skip
            i = int(adv)
            self.skip = adv - i
            self.inb = self.inb[i:]
        return out

    def _resample(self, ratio: float, n: int) -> np.ndarray:
        """n samples read from `stretched` at `ratio` (cubic: linear dulled the top
        and left images). stretched[0] is the sample before position 0."""
        buf, ph = self.stretched, self.rs_phase
        need = int(1 + ph + (n - 1) * ratio) + 3
        if len(buf) < need:                      # the stretcher isn't ahead yet: wait
            buf = np.concatenate([buf, np.zeros((need - len(buf),) + buf.shape[1:], F32)])
            self.pads += 1
        pos = 1 + ph + ratio * np.arange(n, dtype=np.float64)
        i = pos.astype(np.int64)
        f = (pos - i).astype(F32)
        if buf.ndim == 2:
            f = f[:, None]
        y = hermite(buf[i - 1], buf[i], buf[i + 1], buf[i + 2], f)
        nph = ph + n * ratio
        cut = int(nph)
        self.stretched, self.rs_phase = buf[cut:], nph - cut
        return y

    def _add_stretched(self, chunks, ratio: float, rate: int):
        new = np.concatenate(chunks)
        if ratio > 1.02:                         # about to read faster: keep aliasing out
            cut = 0.45 * rate / ratio
            new = self.aa.run(new, round(cut), lambda: butter(
                4, cut, btype="low", fs=rate).astype(F32))
        self.stretched = np.concatenate([self.stretched, new])

    def _remember(self, x):
        h, n = self.hist, len(x)
        if n >= len(h):
            h[:] = x[n - len(h):]
        else:
            h[:-n] = h[n:]
            h[-n:] = x

    def _prime(self, ratio: float, rate: int):
        """Start at `ratio` with the recent input already stretched, so the
        resampler's head start is real audio instead of zeros."""
        self._reset(ratio)
        head = len(self.stretched)
        k = self._need(1 / ratio) + int((head + self.seq) / ratio)
        self.inb = self.hist[len(self.hist) - min(k, len(self.hist)):].copy()
        chunks = self._stretch(1.0 / ratio)
        if chunks:
            self._add_stretched(chunks, ratio, rate)
        # keep what a fresh start holds after being fed len(inb) samples
        keep = max(head - int(len(self.inb) * ratio), 0)
        self.stretched = self.stretched[len(self.stretched) - keep:]

    def _target(self, x, rate) -> tuple[float, float]:
        """(pitch ratio, formant correction) for this block."""
        p = self.p
        base = 2.0 ** (p["semitones"] / 12.0)
        tune = p.get("tune", 0.0)
        if tune > 0:
            if self.tracker is None:
                self.tracker = _PitchTracker(rate)
            # the shifter plays what you said ~40 ms ago, so measure the pitch there
            tr = self.tracker
            recent = np.concatenate([self.hist, x])
            if recent.ndim == 2:
                recent = recent.mean(1)
            lag = int(self._need(1.0 / max(base, 1e-3))) - tr.window // 2
            end = min(len(recent), max(tr.window, len(recent) - max(lag, 0)))
            f0 = tr.measure(recent[end - tr.window:end])
            if f0 > 0:
                note = 12 * np.log2(f0 * base / 440.0)
                want = round(note) - note
                tau = 0.005 + 0.15 * (1 - tune)          # 100%: jumps (T-Pain)
                a = 1.0 if tune >= 0.98 else 1 - np.exp(-len(x) / (rate * tau))
                self.tune_st += (want - self.tune_st) * a
        else:
            self.tune_st = 0.0
        ratio = base * 2.0 ** (self.tune_st / 12.0)
        # where the formants should end up, relative to your own voice: following the
        # pitch (a cartoon) or staying put (a real person), then made bigger/smaller
        want = base ** (1.0 - p.get("natural", 0.0)) * 2.0 ** (-p.get("size", 0.0) / 12.0)
        return ratio, want / ratio

    def _wants_formants(self) -> bool:
        p = self.p
        base = 2.0 ** (p["semitones"] / 12.0)
        shift = base ** -p.get("natural", 0.0) * 2.0 ** (-p.get("size", 0.0) / 12)
        return abs(np.log2(shift)) > 1e-3

    def latency(self) -> float:
        p = self.p
        if not (self.running or abs(p["semitones"]) >= 0.01 or p.get("size", 0)
                or p.get("tune", 0) > 0):
            return 0.0
        ratio = 2.0 ** (p["semitones"] / 12.0)
        s = self._need(1 / ratio) / self.rate
        if self.fstage is not None or self._wants_formants():
            n = self.fstage.n if self.fstage else _stft_size(self.rate, self.FORMANT_S)
            s += n / self.rate
        return s

    def _hold_back(self, dry, rate):
        """The shifted voice comes out ~40-80 ms after your own: below 100% Mix that
        is a slapback echo under the voice. Gap between voices at 0 holds your own
        voice back by the difference so the two line up; 1 (old saves) leaves it."""
        h, n = self.dhist, len(dry)
        buf = np.concatenate([h, dry])
        self.dhist = buf[-len(h):]
        # (lower pitches come out a little later than latency(), higher ones earlier:
        # each stretched sequence plays slower or faster than it was said, ~7 ms/octave)
        lag = ((self.latency() + self.GAP_PER_OCTAVE_S * np.log2(1.0 / self.ratio)) * rate
               - (self.dstage.n if self.dstage is not None else 0))
        k = min(int(round((1.0 - self.p.get("gap", 1.0)) * max(lag, 0.0))), len(h))
        if k <= 0:
            return dry
        return buf[len(buf) - n - k:len(buf) - k]

    def run(self, x, rate):
        p = self.p
        mix = p["mix"]
        on = (abs(p["semitones"]) >= 0.01 or abs(p.get("size", 0)) >= 0.01
              or p.get("tune", 0) > 0) and mix > 0
        if not on and not self.running:
            self._remember(x)
            return x
        if on:
            ratio, formant = self._target(x, rate)
            if not self.running:
                self.running = True
                self._prime(ratio, rate)
            self.ratio, self.mix, self.formant = ratio, mix, formant
        ratio, mix = self.ratio, self.mix       # switching off: fade out at the old ones
        self._remember(x)
        self.inb = np.concatenate([self.inb, x])
        chunks = self._stretch(1.0 / ratio)
        if chunks:
            self._add_stretched(chunks, ratio, rate)
        wet = self._resample(ratio, len(x))
        if self.fstage is None and abs(np.log2(self.formant)) > 1e-3:
            self.fstage = _Stft(_stft_size(rate, self.FORMANT_S))
        if self.fstage is not None:   # once on, it stays on: its delay mustn't jump
            c = self.formant
            wet = self.fstage.run(wet, lambda spec: spec if abs(np.log2(c)) <= 1e-3
                                  else _envelope_shift(spec, c, self.lifter))
        blur = p.get("blur", 0.0)
        if self.verb is None and blur > 0:
            self.verb = Reverb(rate, {"size": self.BLUR_SIZE, "tone": self.BLUR_TONE, "mix": 1})
            self.verb_eq = _Filter()
        if self.verb is not None:     # once on, it stays on: its tail mustn't cut off
            # the room alone (Reverb at full Mix gives 0.4 dry + 0.8 room), with its
            # middle scooped out so the words stay clear and only lows and highs smear
            room = (self.verb.run(wet, rate) - F32(0.4) * wet) * F32(1.25)
            room = self.verb_eq.run(room, "scoop", lambda: _biquad(
                "peak", self.BLUR_SCOOP_HZ, rate, -self.BLUR_SCOOP_DB, 0.7))
            wet = wet + room * F32(blur)
        if mix < 1:
            # Voice size reshapes the blended-in voice too, or your own voice stays
            # recognisable under the effect
            dry, d = x, 2.0 ** (-p.get("size", 0.0) / 12.0)
            if self.dstage is None and abs(np.log2(d)) > 1e-3:
                self.dstage = _Stft(_stft_size(rate, self.FORMANT_S))
            if self.dstage is not None:
                dry = self.dstage.run(x, lambda spec: spec if abs(np.log2(d)) <= 1e-3
                                      else _envelope_shift(spec, d, self.lifter))
            dry = self._hold_back(dry, rate)
            wet = dry * F32(1 - mix) + wet * F32(mix)
        g0, target = self.wet_g, 1.0 if on else 0.0
        if g0 == target:
            return wet
        step = (1.0 / self.xf) * (1 if target > g0 else -1)
        env = np.clip(g0 + step * np.arange(1, len(x) + 1), 0.0, 1.0).astype(F32)
        self.wet_g = float(env[-1]) if len(x) else g0
        if x.ndim == 2:
            env = env[:, None]
        if not on and self.wet_g <= 0.0:
            self.running = False
            self.fstage = self.dstage = self.verb = None
            self.dhist[:] = 0
            self.tune_st = 0.0
        return x + (wet - x) * env


# --------------------------------------------------------------------------- growl

@register
class Growl(Effect):
    """A second voice an octave below yours, the way an octave pedal makes one: a
    square wave that flips at every other cycle of your voice (so it runs at half
    your pitch) multiplied with the voice. No delay, nothing to track: demons and
    monsters."""

    type = "growl"
    name = "Monster growl"
    description = "Adds a rough voice an octave below yours."
    params = (Param("amount", "Growl", 0, 1, 0.5, "", 0, ("subtle", "monster")),
              Param("tone", "Tone", 300, 3000, 1200, " Hz", 50, ("dark", "raspy")))

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.track = _Filter()
        self.tone = _Filter()
        self.sign = 1.0
        self.parity = 0

    def run(self, x, rate):
        lo = self.track.run(x, "t", lambda: butter(2, 350, btype="low", fs=rate).astype(F32))
        level = float(np.sqrt(np.mean(lo * lo)) + 1e-9)
        s = np.where(np.abs(lo) > level * 0.3, np.sign(lo), 0.0)
        s[0] = s[0] or self.sign
        idx = np.where(s != 0, np.arange(len(s)), 0)
        s = s[np.maximum.accumulate(idx)]              # hold the last sign (hysteresis)
        rising = np.diff(np.r_[self.sign, s]) > 0
        flips = np.cumsum(rising) + self.parity
        sq = np.where(flips % 2 == 0, 1.0, -1.0).astype(F32)
        self.sign, self.parity = float(s[-1]), int(flips[-1] % 2)
        tone = self.p["tone"]
        sub = self.tone.run(x * sq, round(tone), lambda: butter(
            2, min(tone, rate * 0.45), btype="low", fs=rate).astype(F32))
        return x + sub * F32(1.6 * self.p["amount"])


# --------------------------------------------------------------------------- robot

@register
class Robot(Effect):
    """Channel vocoder: the voice's spectral envelope, band by band, imposed on a
    buzzing synthesizer note. The words stay clear, the pitch is the buzz's: the
    classic robot / Daft Punk sound (not the ring-modulated 'dalek' garble)."""

    type = "robot"
    name = "Robot"
    description = "Your words spoken by a buzzing synthesizer (vocoder)."
    params = (Param("freq", "Buzz pitch", 40, 400, 100, " Hz", 1),
              Param("follow", "Follow my pitch", 0, 1, 0, "", 1),
              Param("noise", "Breath", 0, 1, 0.2),
              Param("mix", "Mix", 0, 1, 1))

    BANDS = 16
    LO_HZ, HI_HZ = 120.0, 7500.0
    ENV_HZ = 40.0

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        rate = rate or 48000                    # the chain builds effects before the mic opens
        hi = min(self.HI_HZ, rate * 0.42)
        edges = np.geomspace(self.LO_HZ, hi, self.BANDS + 1)
        self.bank = np.stack([butter(2, [edges[i], edges[i + 1]], btype="band", fs=rate)
                              for i in range(self.BANDS)]).astype(F32)
        self.state = None        # the bank's memory, for (voice, carrier)
        self.env_sos = butter(1, self.ENV_HZ, btype="low", fs=rate).astype(F32)
        self.env_zi = np.zeros((1, 2 * self.BANDS, 2), F32)
        self.harmonics = np.arange(1, int(hi / self.params[0].lo) + 1, dtype=np.float64)
        self.phase = 0.0
        self.rng = np.random.default_rng(1)
        self.tracker: _PitchTracker | None = None
        self.f = float(self.p["freq"])

    def _carrier(self, n: int, rate: int) -> np.ndarray:
        f, nz = self.f, self.p["noise"]
        k = self.harmonics[: int(min(self.HI_HZ, rate * 0.42) / f)]
        ph = self.phase + 2 * np.pi * f / rate * np.arange(1, n + 1)
        self.phase = float(ph[-1] % (2 * np.pi))
        saw = (np.sin(np.outer(k, ph)) / k[:, None]).sum(0) * (2 / np.pi)   # band-limited
        noise = self.rng.standard_normal(n) * 0.35
        return (saw * (1 - nz) + noise * nz).astype(F32)

    def run(self, x, rate):
        n = len(x)
        if self.p.get("follow", 0) >= 0.5:
            # talkbox: the buzz sings the note you're speaking, snapped to the scale
            if self.tracker is None:
                self.tracker = _PitchTracker(rate)
            f0 = self.tracker.update(x)
            if f0 > 0:
                self.f = min(max(_snap(f0), self.params[0].lo), self.params[0].hi)
        else:
            self.f = float(self.p["freq"])
        pair = np.stack([x, self._carrier(n, rate)])
        y, self.state = sosfilt_bank(self.bank, pair, self.state)   # (bands, 2, n)
        bands = np.concatenate([y[:, 0], y[:, 1]])                 # voice's, then carrier's
        env, self.env_zi = sosfilt(self.env_sos, np.abs(bands), zi=self.env_zi)
        gain = np.minimum(env[:self.BANDS] / (env[self.BANDS:] + F32(2e-3)), F32(20))
        wet = (gain * bands[self.BANDS:]).sum(0).astype(F32)
        mix = F32(self.p["mix"])
        return wet if mix >= 1 else x * (1 - mix) + wet * mix


# --------------------------------------------------------------------------- dynamics

@register
class Compressor(Effect):
    """Block-wise peak compressor: gain is decided once per block and ramped across
    it (fast attack, slow release), so there is no per-sample loop."""

    type = "compressor"
    name = "Compressor"
    description = "Evens out your volume: quiet words louder, shouting tamed."
    params = (Param("threshold", "Kicks in at", -40, 0, -20, " dB", 1),
              Param("ratio", "Squash", 1, 20, 4, ":1", 0.5),
              Param("boost", "Boost", 0, 24, 6, " dB", 1))

    ATTACK_S, RELEASE_S = 0.004, 0.15

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.g = 1.0

    def run(self, x, rate):
        n = len(x)
        level = 20 * np.log10(float(np.max(np.abs(x))) + 1e-9)
        over = level - self.p["threshold"]
        target = 10 ** (-over * (1 - 1 / self.p["ratio"]) / 20) if over > 0 else 1.0
        tau = self.ATTACK_S if target < self.g else self.RELEASE_S
        g = target + (self.g - target) * np.exp(-n / (rate * tau))
        ramp = np.linspace(self.g, g, n + 1, dtype=F32)[1:]
        self.g = float(g)
        return x * ramp * F32(10 ** (self.p["boost"] / 20))


@register
class Tone(Effect):
    type = "tone"
    name = "Tone"
    description = "Bass, mid, presence and treble, like the EQ on a mixer."
    params = (Param("bass", "Bass", -12, 12, 0, " dB", 1),
              Param("mid", "Mid", -12, 12, 0, " dB", 1),
              Param("presence", "Presence", -12, 12, 0, " dB", 1),
              Param("treble", "Treble", -12, 12, 0, " dB", 1))

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.f = _Filter()

    def run(self, x, rate):
        b, m, p, t = self.p["bass"], self.p["mid"], self.p["presence"], self.p["treble"]
        if not (b or m or p or t) and self.f.f.idle:
            return x
        # all at 0: fade out to straight through (then, once the fade has run its
        # course, the line above skips it; cutting it short would strand the fade)
        return self.f.run(x, (b, m, p, t), lambda: None if not (b or m or p or t) else np.vstack([
            _biquad("lowshelf", 160, rate, b), _biquad("peak", 1000, rate, m, 1.0),
            _biquad("peak", 2500, rate, p, 1.0), _biquad("highshelf", 6000, rate, t)]))


# --------------------------------------------------------------------------- tone

@register
class Radio(Effect):
    """Band-limited, overdriven voice with a bed of static in the same band."""

    type = "radio"
    name = "Radio"
    description = "Walkie-talkie, telephone or megaphone band-limiting."
    params = (Param("low", "Low cut", 150, 1200, 400, " Hz", 10),
              Param("high", "High cut", 1500, 7000, 3000, " Hz", 50),
              Param("drive", "Crunch", 0, 24, 6, " dB", 1),
              Param("noise", "Static", 0, 0.05, 0.004),
              Param("squelch", "Click when I talk", 0, 1, 0, "", 1))

    HOLD_S = 0.3         # quiet this long = you let go of the talk button

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.bp = _Filter()
        self.bp_noise = _Filter()
        self.rng = np.random.default_rng()
        self.talking = False
        self.quiet = 0.0
        self.pending = np.zeros(0, F32)    # a click or a burst still playing out

    def _burst(self, rate, secs, level, click=False) -> np.ndarray:
        n = int(rate * secs)
        t = np.arange(n) / rate
        env = np.exp(-t / (secs * (0.15 if click else 0.35)))
        z = self.rng.standard_normal(n) * env * level
        if click:   # the key: a sharp tick with a little tone in it
            z += np.sin(2 * np.pi * 1800 * t) * env * level * 1.5
        return z.astype(F32)

    def _squelch(self, x, rate) -> np.ndarray:
        """Walkie-talkie clicks: a key click when you start talking and the "kshh"
        of letting go of the button when you stop."""
        n = len(x)
        level = 20 * np.log10(float(np.sqrt(np.mean(x * x))) + 1e-9)
        if level > -42:
            if not self.talking:
                self.talking = True
                self.pending = self._burst(rate, 0.03, 0.25, click=True)
            self.quiet = 0.0
        elif self.talking:
            self.quiet += n / rate
            if self.quiet > self.HOLD_S:
                self.talking = False
                self.pending = self._burst(rate, 0.18, 0.12)
        add = np.zeros(n, F32)
        k = min(n, len(self.pending))
        add[:k] = self.pending[:k]
        self.pending = self.pending[k:]
        return add

    def run(self, x, rate):
        lo, hi = self.p["low"], self.p["high"]
        hi = min(max(hi, lo * 1.5), rate * 0.45)

        def design():
            return butter(2, [lo, hi], btype="band", fs=rate).astype(F32)

        y = self.bp.run(x, (lo, hi), design)
        g = F32(10 ** (self.p["drive"] / 20))
        y = np.tanh(y * g) / F32(min(float(g), 4.0) ** 0.5)
        if self.p["noise"] > 0:
            hiss = self.rng.standard_normal(len(y)).astype(F32) * F32(self.p["noise"] * 3)
            y += self.bp_noise.run(hiss, (lo, hi), design)
        if self.p.get("squelch", 0) >= 0.5:
            y = y + self._squelch(x, rate)
        return y


@register
class Distortion(Effect):
    type = "distortion"
    name = "Distortion"
    description = "Overdriven, crunchy voice."
    params = (Param("drive", "Drive", 0, 36, 12, " dB", 1),
              Param("tone", "Tone", 1000, 12000, 6000, " Hz", 100),
              Param("level", "Volume", 0.05, 1, 0.5))

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.lp = _Filter()

    def run(self, x, rate):
        g = F32(10 ** (self.p["drive"] / 20))
        y = np.tanh(x * g) * F32(self.p["level"])
        tone = self.p["tone"]
        return self.lp.run(y, tone, lambda: _one_pole_lowpass(tone, rate))


@register
class Shout(Effect):
    """Reacts to how loud you are: talk normally and nothing happens, shout and the
    voice blows out like a megaphone (band-limited and overdriven), fading back as
    you calm down."""

    type = "shout"
    name = "Shout blowout"
    description = "Shout and your voice blows out like a megaphone."
    params = (Param("threshold", "Kicks in at", -40, -3, -16, " dB", 1, ("whisper", "yell")),
              Param("drive", "Crunch", 0, 30, 14, " dB", 1))

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.bp = _Filter()
        self.env = -90.0
        self.amt = 0.0

    def run(self, x, rate):
        n = len(x)
        level = 20 * np.log10(float(np.max(np.abs(x))) + 1e-9)
        tau = 0.01 if level > self.env else 0.25
        self.env = level + (self.env - level) * float(np.exp(-n / (rate * tau)))
        target = min(max((self.env - self.p["threshold"]) / 6.0, 0.0), 1.0)
        a = np.linspace(self.amt, target, n + 1, dtype=F32)[1:]
        self.amt = target
        # the top edge stays under Nyquist (an 8 kHz mic can't take a 4 kHz edge)
        y = self.bp.run(x, "bp", lambda: butter(2, [500, min(4000, 0.45 * rate)],
                                                btype="band", fs=rate).astype(F32))
        g = F32(10 ** (self.p["drive"] / 20))
        wet = np.tanh(y * g) * F32(0.5)
        return x * (1 - a) + wet * a


@register
class Helmet(Effect):
    """A very short echo fed back on itself (a comb filter): the boxy, metallic ring
    of talking inside a helmet, a mask or a tin can."""

    type = "helmet"
    name = "Helmet"
    description = "Talking inside a helmet, mask or metal box."
    params = (Param("size", "Helmet size", 0.5, 8, 2.5, " ms", 0.1, ("tin can", "big helmet")),
              Param("ring", "Metal ring", 0, 0.9, 0.55),
              Param("mix", "Mix", 0, 1, 0.5))

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.hist = _Line(self._len())

    def _len(self) -> int:
        return max(2, int(self.rate * self.p["size"] / 1000))

    def run(self, x, rate):
        d = self._len()
        if d != len(self.hist):
            self.hist = _Line(d)
        fb, mix = F32(self.p["ring"]), F32(self.p["mix"])
        out = np.empty_like(x)
        hist, n, i = self.hist, len(x), 0
        while i < n:
            c = min(d, n - i)
            v = x[i:i + c] + fb * hist.take(c)
            out[i:i + c] = v
            hist.put(v)
            i += c
        wet = out * F32(1 - float(fb) * 0.7)      # about as loud as the dry voice
        return x * (1 - mix) + wet * mix


# --------------------------------------------------------------------------- space

@register
class Chorus(Effect):
    """Two copies of the voice on slowly wandering delays, mixed with the original."""

    type = "chorus"
    name = "Chorus"
    description = "Doubled, wobbling voice: subtle shimmer to full alien warble."
    params = (Param("rate", "Speed", 0.1, 8, 1.0, " Hz", 0.1),
              Param("depth", "Depth", 0.5, 15, 4, " ms", 0.5),
              Param("mix", "Mix", 0, 1, 0.5))

    MAX_MS = 20.0

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.h = int(rate * self.MAX_MS / 1000) + 2
        self.hist = np.zeros(self.h, F32)
        self.phase = 0.0

    def run(self, x, rate):
        n = len(x)
        buf = np.concatenate([self.hist, x])
        self.hist = buf[-self.h:].copy()
        ph = self.phase + 2 * np.pi * self.p["rate"] / rate * np.arange(1, n + 1)
        self.phase = float(ph[-1] % (2 * np.pi))
        depth = min(self.p["depth"], self.MAX_MS - 1.5) * rate / 1000
        base = self.h - 1 + np.arange(n, dtype=np.float64) - 1.0 * rate / 1000
        wet = np.zeros(n, np.float64)
        for off in (0.0, np.pi / 2):
            pos = base - depth * (1 + np.sin(ph + off)) * 0.5
            i = pos.astype(np.int64)
            f = pos - i
            wet += buf[i] * (1 - f) + buf[i + 1] * f
        mix = F32(self.p["mix"])
        return x * (1 - mix) + wet.astype(F32) * (mix * F32(0.5))


@register
class Echo(Effect):
    type = "echo"
    name = "Echo"
    description = "Repeating echo, from slapback to canyon."
    params = (Param("delay", "Delay", 40, 1000, 250, " ms", 10),
              Param("feedback", "Repeats", 0, 0.9, 0.35),
              Param("mix", "Mix", 0, 1, 0.4),
              Param("tone", "Tone", 1000, 12000, 12000, " Hz", 100))

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.hist = _Line(self._len())
        self.lp = _Filter()

    def _len(self) -> int:
        return max(1, int(self.rate * self.p["delay"] / 1000))

    def run(self, x, rate):
        d = self._len()
        if d != len(self.hist):      # delay slider moved: start a fresh line
            self.hist = _Line(d)
        fb, mix, tone = F32(self.p["feedback"]), F32(self.p["mix"]), self.p["tone"]
        out = np.empty_like(x)
        hist, n, i = self.hist, len(x), 0
        while i < n:
            c = min(d, n - i)
            delayed = hist.take(c)
            if tone < 12000:         # each repeat comes back a little darker
                delayed = self.lp.run(delayed, tone, lambda: _one_pole_lowpass(tone, rate))
            out[i:i + c] = x[i:i + c] + mix * delayed
            hist.put(x[i:i + c] + fb * delayed)
            i += c
        return out


@register
class Reverb(Effect):
    """Freeverb: eight parallel damped combs into four allpasses. The damping
    (a lowpass inside each comb's feedback) is what keeps it from ringing like
    a metal pipe: real rooms swallow highs faster than lows."""

    type = "reverb"
    name = "Reverb"
    description = "Room, hall or cave."
    params = (Param("size", "Size", 0, 1, 0.5),
              Param("tone", "Brightness", 1500, 12000, 5000, " Hz", 100),
              Param("mix", "Mix", 0, 1, 0.3))

    COMBS = (1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617)     # samples at 44.1 kHz
    ALLPASSES = (556, 441, 341, 225)

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        k = rate / 44100
        self.combs = [np.zeros(int(d * k), F32) for d in self.COMBS]
        self.damp = [np.zeros(1, F32) for _ in self.COMBS]        # lowpass memory per comb
        self.aps = [(np.zeros(int(d * k), F32),) * 2 for d in self.ALLPASSES]
        self.hp = _Filter()

    def _comb(self, x, k, g, a):
        """v[n] = x[n] + g·lp(v[n-D]); lp is a one-pole with coefficient a."""
        hist, n = self.combs[k], len(x)
        d = len(hist)
        out = np.empty(n, F32)
        i = 0
        while i < n:
            c = min(d, n - i)
            fed, self.damp[k] = lfilter([1 - a], [1, -a], hist[:c], zi=self.damp[k])
            v = x[i:i + c] + F32(g) * fed.astype(F32)
            out[i:i + c] = v
            hist = np.concatenate([hist[c:], v])
            i += c
        self.combs[k] = hist
        return out

    def _all_combs(self, x, g, a):
        """All the combs at once, for a block no longer than the shortest delay (the
        usual case): each one's feedback is then already in its history, so the
        eight damping filters run as one call over an (8, n) array."""
        n = len(x)
        fed, zf = lfilter([1 - a], [1, -a], np.stack([h[:n] for h in self.combs]),
                          zi=np.stack(self.damp))
        v = x[None] + F32(g) * fed.astype(F32)
        for k, h in enumerate(self.combs):
            self.combs[k] = np.concatenate([h[n:], v[k]])
            self.damp[k] = zf[k]
        return v.sum(axis=0)

    def run(self, x, rate):
        g = 0.7 + 0.28 * self.p["size"]
        a = float(np.exp(-2 * np.pi * self.p["tone"] / rate))
        if len(x) <= min(len(h) for h in self.combs):
            wet = self._all_combs(x, g, a)
        else:
            wet = np.zeros_like(x)
            for k in range(len(self.combs)):
                wet += self._comb(x, k, g, a)
        wet *= F32(0.25 * np.sqrt(1 - g * g))     # same loudness at every size
        for k, (xh, yh) in enumerate(self.aps):
            wet, xh, yh = _allpass(wet, xh, yh, 0.5)
            self.aps[k] = (xh, yh)
        # the combs pile up below ~150 Hz (they all agree there): keep the mud out
        wet = self.hp.run(wet, "hp", lambda: butter(
            2, 150, btype="high", fs=rate).astype(F32))
        mix = F32(self.p["mix"])
        return x * (1 - F32(0.6) * mix) + wet * (mix * F32(0.8))


def _allpass(x, xh, yh, g):
    """Schroeder allpass: y[n] = -g·x[n] + x[n-D] + g·y[n-D]."""
    d, n = len(xh), len(x)
    out = np.empty(n, F32)
    i = 0
    while i < n:
        c = min(d, n - i)
        xc = x[i:i + c]
        y = F32(-g) * xc + xh[:c] + F32(g) * yh[:c]
        out[i:i + c] = y
        xh = np.concatenate([xh[c:], xc])
        yh = np.concatenate([yh[c:], y])
        i += c
    return out, xh, yh


# --------------------------------------------------------------------------- presets

# name -> the effects that are on, with their settings (everything else is off).
# Kept short on purpose: every voice here should sound like the thing it's named
# after, straight away, on a normal headset mic. "natural": 1 keeps the voice's
# formants where a real person's would be (a different person, not a cartoon).
# Clean up my mic isn't part of any voice: it stays as you set it.
PRESETS: dict[str, dict[str, dict]] = {
    "Chipmunk":          {"pitch": {"semitones": 8},
                          "compressor": {"threshold": -24, "ratio": 2.5, "boost": 5}},
    "Deep voice":        {"pitch": {"semitones": -4, "natural": 1, "size": 2},
                          "compressor": {"threshold": -22, "ratio": 3, "boost": 6},
                          "tone": {"bass": 3, "presence": 2, "treble": -1}},
    "Female voice":      {"pitch": {"semitones": 5, "natural": 1, "size": -2.5},
                          "compressor": {"threshold": -24, "ratio": 2.5, "boost": 5},
                          "tone": {"bass": -3, "presence": 2, "treble": 2}},
    "Male voice":        {"pitch": {"semitones": -5, "natural": 1, "size": 2.5},
                          "compressor": {"threshold": -22, "ratio": 3, "boost": 6},
                          "tone": {"bass": 3, "presence": 1, "treble": -1}},
    "Demon":             {"pitch": {"semitones": -6, "natural": 1, "size": 5},
                          "growl": {"amount": 0.7, "tone": 900},
                          "compressor": {"threshold": -24, "ratio": 4, "boost": 8},
                          "distortion": {"drive": 6, "tone": 3500, "level": 0.8},
                          "reverb": {"size": 0.8, "tone": 2500, "mix": 0.3}},
    "Robot":             {"robot": {"freq": 100, "noise": 0.2, "mix": 1},
                          "compressor": {"threshold": -24, "ratio": 3, "boost": 10},
                          "reverb": {"size": 0.25, "tone": 6000, "mix": 0.12}},
    "Talkbox":           {"robot": {"freq": 110, "follow": 1, "noise": 0.05, "mix": 1},
                          "compressor": {"threshold": -24, "ratio": 3, "boost": 10},
                          "chorus": {"rate": 0.6, "depth": 3, "mix": 0.3}},
    "Autotune":          {"pitch": {"semitones": 0, "tune": 1},
                          "compressor": {"threshold": -22, "ratio": 3, "boost": 5},
                          "reverb": {"size": 0.35, "tone": 6000, "mix": 0.18}},
    "Masked caller":     {"pitch": {"semitones": -6, "natural": 0.6, "size": 2},
                          "compressor": {"threshold": -26, "ratio": 5, "boost": 8},
                          "radio": {"low": 200, "high": 5000, "drive": 6, "noise": 0.0},
                          "distortion": {"drive": 4, "tone": 4000, "level": 0.8}},
    "Anonymous":         {"pitch": {"semitones": -4, "natural": 1, "size": -4},
                          "compressor": {"threshold": -24, "ratio": 3, "boost": 6},
                          "chorus": {"rate": 0.2, "depth": 2, "mix": 0.2}},
    # the hidden detective talking through a TV, matched line by line to the show:
    # the voice and a copy 7 st down blended (deep and high at once, no one clear
    # pitch), both with a much smaller throat so it isn't your voice any more, thin
    # on bass and top, strong in the mids, and a metallic ring over it
    "Secret detective":  {"pitch": {"semitones": -7, "size": -7, "mix": 0.5},
                          "compressor": {"threshold": -26, "ratio": 5, "boost": 9},
                          "tone": {"bass": -10, "mid": 7, "presence": 3, "treble": -9},
                          "radio": {"low": 150, "high": 6700, "drive": 0, "noise": 0.0},
                          "helmet": {"size": 1.8, "ring": 0.49, "mix": 0.79}},
    "Dark lord":         {"pitch": {"semitones": -3, "natural": 1, "size": 3},
                          "compressor": {"threshold": -26, "ratio": 4, "boost": 8},
                          "tone": {"bass": 4, "presence": 1, "treble": -3},
                          "helmet": {"size": 3, "ring": 0.6, "mix": 0.45},
                          "reverb": {"size": 0.2, "tone": 4000, "mix": 0.1}},
    "Hothead":           {"shout": {"threshold": -14, "drive": 16}},
    "Alien":             {"pitch": {"semitones": 5, "mix": 0.6},
                          "compressor": {"threshold": -24, "ratio": 3, "boost": 13},
                          "chorus": {"rate": 4.0, "depth": 3, "mix": 0.6},
                          "reverb": {"size": 0.55, "tone": 8000, "mix": 0.25}},
    "Ghost":             {"pitch": {"semitones": -3},
                          "compressor": {"threshold": -24, "ratio": 3, "boost": 11},
                          "chorus": {"rate": 0.3, "depth": 8, "mix": 0.5},
                          "echo": {"delay": 300, "feedback": 0.45, "mix": 0.3, "tone": 2500},
                          "reverb": {"size": 0.9, "tone": 2500, "mix": 0.4}},
    "Walkie-talkie":     {"compressor": {"threshold": -30, "ratio": 8, "boost": 16},
                          "radio": {"low": 450, "high": 2700, "drive": 10, "noise": 0.01,
                                    "squelch": 1}},
    "Old telephone":     {"compressor": {"threshold": -25, "ratio": 4, "boost": 10},
                          "radio": {"low": 300, "high": 3400, "drive": 4, "noise": 0.002}},
    "Megaphone":         {"compressor": {"threshold": -28, "ratio": 6, "boost": 8},
                          "tone": {"bass": 0, "presence": 6, "treble": 0},
                          "radio": {"low": 500, "high": 4500, "drive": 16, "noise": 0.0},
                          "echo": {"delay": 70, "feedback": 0.15, "mix": 0.25, "tone": 3000}},
    "Stadium announcer": {"compressor": {"threshold": -26, "ratio": 5, "boost": 10},
                          "tone": {"bass": -2, "presence": 5, "treble": 0},
                          "radio": {"low": 250, "high": 6000, "drive": 4, "noise": 0.0},
                          "echo": {"delay": 420, "feedback": 0.3, "mix": 0.3, "tone": 4000},
                          "reverb": {"size": 0.85, "tone": 5000, "mix": 0.3}},
    "Cave":              {"tone": {"bass": 2, "presence": 0, "treble": -3},
                          "echo": {"delay": 350, "feedback": 0.4, "mix": 0.3, "tone": 2500},
                          "reverb": {"size": 0.95, "tone": 3000, "mix": 0.4}},
    "Podcast voice":     {"compressor": {"threshold": -22, "ratio": 3, "boost": 5},
                          "tone": {"bass": 3, "presence": 3, "treble": 1}},
}

PRESET_ICONS = {"Chipmunk": "🐿️", "Deep voice": "🐻", "Female voice": "👩", "Male voice": "👨",
                "Demon": "👹", "Robot": "🤖", "Talkbox": "🎹", "Autotune": "🎤",
                "Masked caller": "🔪", "Anonymous": "🕶️", "Secret detective": "🕵️",
                "Dark lord": "⛑️",
                "Hothead": "😡", "Alien": "👽", "Ghost": "👻", "Walkie-talkie": "📻",
                "Old telephone": "☎️", "Megaphone": "📢", "Stadium announcer": "🏟️",
                "Cave": "🦇", "Podcast voice": "🎙️"}
