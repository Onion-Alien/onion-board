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
from soundboard.dsp import SmoothSos, butter, lfilter, matched_biquad, sosfilt, sosfilt_bank
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

    While bypassed (0 st) it keeps the last HIST_S of input, and switching on
    stretches that first, so the output doesn't go silent for the latency.
    Switching on or off crossfades dry <-> wet over XF_MS (no click).
    """

    type = "pitch"
    name = "Pitch"
    description = "Higher (chipmunk) or lower (giant) voice."
    params = (Param("semitones", "Pitch", -12, 12, 0, " st", 1),
              Param("mix", "Mix", 0, 1, 1))

    SEQ_MS = 30.0       # one sequence of voice, copied to the output
    SEEK_MS = 10.0      # how far the splice point may move to line up
    OVL_MS = 7.0        # crossfade between one sequence and the next
    XF_MS = 10.0        # dry <-> wet crossfade when it switches on or off
    HIST_S = 0.35       # input kept while bypassed (enough to prime it at -24 st)

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.seq = int(rate * self.SEQ_MS / 1000)
        self.seek = int(rate * self.SEEK_MS / 1000)
        self.ovl = int(rate * self.OVL_MS / 1000)
        self.fade_in = np.linspace(0, 1, self.ovl, endpoint=False, dtype=F32)
        self.fade_out = F32(1) - self.fade_in
        self.aa = _Filter()
        self.running = False
        self.hist = np.zeros(int(rate * self.HIST_S), F32)
        self.xf = max(1, int(rate * self.XF_MS / 1000))
        self.wet_g = 0.0        # 0 = dry, 1 = wet
        self.ratio, self.mix = 1.0, 1.0
        self._reset(1.0)

    def _need(self, tempo: float) -> int:
        """Input the stretcher needs on hand before it can cut the next sequence."""
        return max(self.seek + self.seq, int((self.seq - self.ovl) * tempo) + 2)

    def _reset(self, ratio: float):
        self.inb = np.zeros(0, F32)             # mic audio waiting to be stretched
        self.mid = np.zeros(self.ovl, F32)      # tail of the last sequence, to line up the next
        self.skip = 0.0                         # fractional input position carried over
        # The stretcher can only start once it has a sequence's worth of input, so the
        # resampler starts that far behind (the effect's latency); the head start is
        # exactly what keeps it fed afterwards, whatever the mic's block size.
        self.stretched = np.zeros(int(self._need(1 / ratio) * ratio) + 4, F32)
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
            corr = np.correlate(cand, self.mid, "valid")          # seek + 1 candidates
            cs = np.cumsum(cand.astype(np.float64) ** 2)
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
        buf, ph = self.stretched, self.rs_phase
        need = int(ph + (n - 1) * ratio) + 2
        if len(buf) < need:                      # the stretcher isn't ahead yet: wait
            buf = np.concatenate([buf, np.zeros(need - len(buf), F32)])
            self.pads += 1
        pos = ph + ratio * np.arange(n, dtype=np.float64)
        i = pos.astype(np.int64)
        f = (pos - i).astype(F32)
        y = buf[i] * (1 - f) + buf[i + 1] * f
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

    def run(self, x, rate):
        st, mix = self.p["semitones"], self.p["mix"]
        on = abs(st) >= 0.01 and mix > 0
        if not on and not self.running:
            self._remember(x)
            return x
        if on:
            ratio = 2.0 ** (st / 12.0)
            if not self.running:
                self.running = True
                self._prime(ratio, rate)
            self.ratio, self.mix = ratio, mix
        ratio, mix = self.ratio, self.mix       # switching off: fade out at the old ones
        self._remember(x)
        self.inb = np.concatenate([self.inb, x])
        chunks = self._stretch(1.0 / ratio)
        if chunks:
            self._add_stretched(chunks, ratio, rate)
        wet = self._resample(ratio, len(x))
        if mix < 1:
            wet = x * F32(1 - mix) + wet * F32(mix)
        g0, target = self.wet_g, 1.0 if on else 0.0
        if g0 == target:
            return wet
        step = (1.0 / self.xf) * (1 if target > g0 else -1)
        env = np.clip(g0 + step * np.arange(1, len(x) + 1), 0.0, 1.0).astype(F32)
        self.wet_g = float(env[-1]) if len(x) else g0
        if not on and self.wet_g <= 0.0:
            self.running = False
        return x + (wet - x) * env


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

    def _carrier(self, n: int, rate: int) -> np.ndarray:
        f, nz = self.p["freq"], self.p["noise"]
        k = self.harmonics[: int(min(self.HI_HZ, rate * 0.42) / f)]
        ph = self.phase + 2 * np.pi * f / rate * np.arange(1, n + 1)
        self.phase = float(ph[-1] % (2 * np.pi))
        saw = (np.sin(np.outer(k, ph)) / k[:, None]).sum(0) * (2 / np.pi)   # band-limited
        noise = self.rng.standard_normal(n) * 0.35
        return (saw * (1 - nz) + noise * nz).astype(F32)

    def run(self, x, rate):
        n = len(x)
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
    description = "Bass, presence and treble, like the EQ on a mixer."
    params = (Param("bass", "Bass", -12, 12, 0, " dB", 1),
              Param("presence", "Presence", -12, 12, 0, " dB", 1),
              Param("treble", "Treble", -12, 12, 0, " dB", 1))

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.f = _Filter()

    def run(self, x, rate):
        b, p, t = self.p["bass"], self.p["presence"], self.p["treble"]
        if not (b or p or t) and self.f.sos is None:
            return x
        # all at 0: fade out to straight through (then the line above skips it)
        return self.f.run(x, (b, p, t), lambda: None if not (b or p or t) else np.vstack([
            _biquad("lowshelf", 160, rate, b), _biquad("peak", 2500, rate, p, 1.0),
            _biquad("highshelf", 6000, rate, t)]))


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
              Param("noise", "Static", 0, 0.05, 0.004))

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.bp = _Filter()
        self.bp_noise = _Filter()
        self.rng = np.random.default_rng()

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
        self.hist = np.zeros(self._len(), F32)
        self.lp = _Filter()

    def _len(self) -> int:
        return max(1, int(self.rate * self.p["delay"] / 1000))

    def run(self, x, rate):
        d = self._len()
        if d != len(self.hist):      # delay slider moved: start a fresh line
            self.hist = np.zeros(d, F32)
        fb, mix, tone = F32(self.p["feedback"]), F32(self.p["mix"]), self.p["tone"]
        out = np.empty_like(x)
        hist, n, i = self.hist, len(x), 0
        while i < n:
            c = min(d, n - i)
            delayed = hist[:c]
            if tone < 12000:         # each repeat comes back a little darker
                delayed = self.lp.run(delayed, tone, lambda: _one_pole_lowpass(tone, rate))
            out[i:i + c] = x[i:i + c] + mix * delayed
            hist = np.concatenate([hist[c:], x[i:i + c] + fb * delayed])
            i += c
        self.hist = hist
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
# after, straight away, on a normal headset mic.
PRESETS: dict[str, dict[str, dict]] = {
    "Chipmunk":          {"pitch": {"semitones": 8},
                          "compressor": {"threshold": -24, "ratio": 2.5, "boost": 5}},
    "Deep voice":        {"pitch": {"semitones": -4},
                          "compressor": {"threshold": -22, "ratio": 3, "boost": 6},
                          "tone": {"bass": 4, "presence": 2, "treble": -2}},
    "Demon":             {"pitch": {"semitones": -8},
                          "compressor": {"threshold": -24, "ratio": 4, "boost": 9},
                          "distortion": {"drive": 8, "tone": 3500, "level": 0.8},
                          "chorus": {"rate": 0.4, "depth": 6, "mix": 0.25},
                          "reverb": {"size": 0.8, "tone": 2500, "mix": 0.35}},
    "Robot":             {"robot": {"freq": 100, "noise": 0.2, "mix": 1},
                          "compressor": {"threshold": -24, "ratio": 3, "boost": 10},
                          "reverb": {"size": 0.25, "tone": 6000, "mix": 0.12}},
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
                          "radio": {"low": 450, "high": 2700, "drive": 10, "noise": 0.01}},
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

PRESET_ICONS = {"Chipmunk": "🐿️", "Deep voice": "🐻", "Demon": "👹", "Robot": "🤖",
                "Alien": "👽", "Ghost": "👻", "Walkie-talkie": "📻", "Old telephone": "☎️",
                "Megaphone": "📢", "Stadium announcer": "🏟️", "Cave": "🦇",
                "Podcast voice": "🎙️"}
