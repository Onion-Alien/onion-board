"""Robot, Singing monk and Ring modulator: your words through a synthesizer."""
from __future__ import annotations

import numpy as np
from soundboard.audio.dsp import butter, sosfilt, sosfilt_bank
from soundboard.voicefx import Effect, Param, register

from soundboard.voicefx.builtin.parts import F32, _Filter, _PitchTracker, _glide


def _snap(hz: float) -> float:
    """The nearest note (equal temperament, A = 440 Hz)."""
    return 440.0 * 2.0 ** (round(12 * np.log2(hz / 440.0)) / 12)


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
    LIGHT_BANDS = 8   # Use less CPU: half the bands, each twice as wide (a little coarser)
    LO_HZ, HI_HZ = 120.0, 7500.0
    ENV_HZ = 40.0

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.env_sos = butter(1, self.ENV_HZ, btype="low", fs=rate or 48000).astype(F32)
        self._bands(self.BANDS)
        self.tables: dict[int, np.ndarray] = {}   # harmonics -> one cycle of the buzz
        self.phase = 0.0
        self.rng = np.random.default_rng(1)
        self.tracker: _PitchTracker | None = None
        self.f = float(self.p["freq"])

    TABLE = 16384  # samples in a cycle of the buzz, read with linear interpolation: its
                   # top harmonic (187 at 40 Hz) gets 88 samples a cycle, ~-95 dB off

    def _table(self, k: int) -> np.ndarray:
        """One cycle of the band-limited saw with harmonics 1..k, sum sin(j x) / j * 2/pi,
        made by an inverse FFT (~50 us) the first time a pitch needs that many, with
        its first sample repeated at the end for the interpolation. Summing k sines
        for every sample of every block (k is 75 at 100 Hz) was most of the effect.
        Kept as float32 (64 KB each); follow-my-pitch uses a handful of them."""
        t = self.tables.get(k)
        if t is None:
            n = self.TABLE
            spec = np.zeros(n // 2 + 1, np.complex128)
            j = np.arange(1, k + 1)
            spec[1:k + 1] = -0.5j * n / j * (2 / np.pi)
            cyc = np.fft.irfft(spec, n)
            t = np.append(cyc, cyc[0]).astype(F32)
            if len(self.tables) >= 16:   # follow-my-pitch walks the notes: a few in use
                self.tables.clear()
            self.tables[k] = t
        return t

    def _bands(self, n: int):
        rate = self.rate or 48000               # the chain builds effects before the mic opens
        hi = min(self.HI_HZ, rate * 0.42)
        edges = np.geomspace(self.LO_HZ, hi, n + 1)
        self.bank = np.stack([butter(2, [edges[i], edges[i + 1]], btype="band", fs=rate)
                              for i in range(n)]).astype(F32)
        self.bands = n
        self.state = None        # the bank's memory, for (voice, carrier)
        self.env_zi = np.zeros((1, 2 * n, 2), F32)

    def set_light(self, on: bool):
        super().set_light(on)
        want = self.LIGHT_BANDS if self.light else self.BANDS
        if want != self.bands:   # (a few ms on the mic thread, once, when it flips)
            self._bands(want)

    def _carrier(self, n: int, rate: int) -> np.ndarray:
        f, nz = self.f, self.p["noise"]
        k = int(min(self.HI_HZ, rate * 0.42) / f)
        ph = self.phase + 2 * np.pi * f / rate * np.arange(1, n + 1)
        self.phase = float(ph[-1] % (2 * np.pi))
        pos = np.mod(ph, 2 * np.pi) * (self.TABLE / (2 * np.pi))
        i = pos.astype(np.intp)
        np.minimum(i, self.TABLE - 1, out=i)   # (2*pi itself after rounding)
        t = self._table(k)
        saw = t[i] + (t[i + 1] - t[i]) * (pos - i)                  # band-limited
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
        k = self.bands
        gain = np.minimum(env[:k] / (env[k:] + F32(2e-3)), F32(20))
        wet = (gain * bands[k:]).sum(0).astype(F32)
        mix = F32(self.p["mix"])
        return wet if mix >= 1 else x * (1 - mix) + wet * mix


# The singing monk's vowels, measured off the Delay Lama plugin's output (a held note
# on every vowel, the same on every pitch: one buzz through a vowel filter). Level in
# dB at each of _MONK_HZ, one row per vowel from "oo" (row 0) through "aa" (3) to
# "ee" (last).
_MONK_HZ = np.geomspace(60, 9000, 72).astype(F32)


_MONK_DB = np.array([
    [-36, -36, -35, -35, -34, -34, -34, -34, -34, -34, -34, -34, -33, -33, -32, -31,
     -31, -31, -30, -29, -29, -29, -28, -27, -26, -25, -24, -23, -22, -21, -18, -15,
     -8, -5, -10, -18, -21, -16, -8, -11, -21, -26, -29, -34, -38, -43, -50, -65,
     -65, -67, -64, -47, -39, -33, -17, -21, -36, -47, -38, -31, -47, -56, -34, -34,
     -56, -73, -80, -83, -83, -88, -87, -86],
    [-44, -43, -43, -42, -42, -41, -40, -40, -40, -39, -39, -39, -38, -38, -37, -36,
     -36, -35, -35, -34, -33, -32, -32, -31, -30, -29, -28, -27, -27, -26, -24, -22,
     -21, -19, -14, -5, -12, -20, -20, -11, -9, -21, -26, -30, -34, -39, -45, -56,
     -66, -64, -64, -49, -40, -34, -18, -21, -36, -47, -39, -32, -47, -56, -34, -34,
     -55, -72, -80, -81, -87, -85, -86, -84],
    [-45, -45, -44, -43, -43, -43, -43, -44, -44, -43, -42, -41, -40, -39, -38, -39,
     -39, -39, -38, -37, -36, -36, -35, -34, -33, -31, -31, -30, -30, -29, -27, -26,
     -25, -23, -19, -13, -3, -10, -19, -21, -15, -9, -18, -26, -30, -35, -40, -47,
     -56, -68, -66, -48, -40, -34, -17, -22, -36, -48, -39, -31, -47, -56, -35, -34,
     -56, -73, -80, -86, -81, -90, -87, -84],
    [-45, -45, -44, -43, -43, -42, -42, -41, -41, -40, -40, -39, -38, -38, -37, -37,
     -36, -36, -36, -35, -34, -33, -33, -32, -31, -30, -29, -29, -28, -28, -25, -24,
     -22, -20, -15, -6, -9, -16, -21, -22, -23, -22, -16, -10, -20, -28, -32, -37,
     -43, -52, -58, -48, -40, -33, -16, -22, -37, -48, -39, -31, -47, -55, -34, -34,
     -55, -73, -80, -82, -84, -87, -84, -89],
    [-36, -36, -35, -35, -34, -34, -34, -34, -34, -34, -34, -34, -33, -32, -32, -32,
     -32, -32, -31, -30, -29, -29, -28, -27, -26, -25, -24, -23, -22, -21, -19, -13,
     -7, -5, -10, -18, -22, -25, -28, -31, -33, -33, -31, -28, -22, -10, -16, -27,
     -33, -38, -51, -49, -37, -31, -14, -26, -39, -51, -38, -31, -48, -56, -34, -35,
     -56, -72, -80, -85, -87, -89, -87, -82],
    [-30, -29, -29, -28, -28, -27, -27, -28, -28, -28, -27, -27, -26, -26, -25, -25,
     -25, -25, -24, -23, -23, -22, -22, -21, -19, -16, -14, -13, -9, -3, -4, -13,
     -18, -22, -24, -27, -29, -31, -35, -39, -46, -56, -45, -39, -34, -30, -26, -12,
     -17, -29, -36, -45, -37, -28, -14, -29, -41, -52, -38, -32, -48, -56, -35, -35,
     -56, -72, -76, -82, -77, -81, -85, -86],
    [-29, -29, -29, -29, -28, -28, -27, -26, -25, -25, -24, -24, -23, -23, -22, -21,
     -20, -19, -19, -18, -17, -14, -13, -10, -5, -1, -2, -8, -14, -17, -20, -22,
     -25, -28, -30, -33, -36, -38, -41, -44, -51, -56, -54, -49, -44, -39, -34, -29,
     -20, -11, -26, -33, -34, -27, -14, -30, -41, -53, -39, -32, -47, -56, -35, -34,
     -56, -73, -80, -85, -88, -78, -89, -88],
    [-30, -30, -29, -28, -27, -26, -25, -24, -24, -23, -23, -22, -21, -20, -19, -18,
     -16, -15, -15, -14, -11, -6, -1, 0, -3, -6, -10, -15, -19, -21, -23, -25,
     -28, -31, -33, -36, -38, -41, -46, -50, -62, -74, -68, -61, -50, -44, -38, -34,
     -29, -15, -13, -29, -31, -27, -13, -29, -41, -53, -38, -31, -48, -55, -33, -33,
     -55, -73, -81, -80, -88, -81, -90, -85],
    [-28, -28, -27, -26, -25, -25, -24, -23, -22, -21, -20, -19, -19, -18, -17, -16,
     -14, -12, -9, -6, -4, -1, 0, -3, -10, -14, -16, -18, -21, -23, -24, -27,
     -29, -32, -34, -37, -40, -43, -47, -53, -64, -68, -64, -69, -54, -47, -41, -36,
     -31, -23, -10, -25, -31, -30, -15, -26, -38, -50, -39, -31, -47, -55, -34, -33,
     -55, -71, -81, -83, -86, -85, -83, -90],
    [-28, -27, -26, -25, -25, -24, -23, -22, -22, -21, -20, -19, -17, -16, -15, -14,
     -14, -12, -9, -5, -2, 0, -1, -6, -12, -15, -17, -18, -21, -24, -25, -27,
     -30, -32, -34, -38, -40, -43, -48, -54, -62, -64, -63, -70, -57, -47, -41, -36,
     -31, -24, -10, -24, -32, -32, -17, -23, -37, -48, -39, -31, -47, -55, -34, -34,
     -55, -73, -82, -83, -87, -83, -90, -90],
    [-27, -26, -26, -25, -24, -23, -23, -22, -21, -21, -20, -19, -17, -15, -14, -14,
     -14, -12, -9, -5, -1, 0, -2, -6, -12, -15, -17, -18, -20, -23, -25, -27,
     -29, -32, -34, -38, -40, -43, -48, -55, -61, -63, -61, -68, -59, -47, -42, -37,
     -31, -24, -10, -23, -32, -34, -20, -18, -35, -45, -39, -31, -47, -55, -34, -34,
     -55, -72, -81, -83, -88, -86, -85, -79],
], F32)


_MONK_LOG_HZ = np.log(_MONK_HZ)


_MONK_SCALE = np.array([0, 3, 5, 7, 10, 12])   # minor pentatonic (and the octave): any two fit


@register
class Monk(Effect):
    """A singing monk sings what you say. Your voice is only listened to: its
    loudness starts and stops his notes, every syllable is one sung "y-a" (and an
    "i" as he lets go, the way his covers sing), its pitch picks his note (snapped to
    a five-note scale around his own low note, so talking comes out as a tune), and
    how open your vowel is opens his "a" a little. His voice is a buzz shaped by
    vowel filters measured off the real monk synth, with his vibrato and glide. A bit
    of your own hiss ("Words") keeps the consonants, so you can still be followed."""

    type = "monk"
    name = "Singing monk"
    description = "A monk sings your words: your talking becomes his chant."
    params = (Param("note", "Pitch", -12, 12, 0, " st", 1, ("lower", "higher")),
              Param("follow", "Follow my tune", 0, 1, 0.55, "", 0, ("one note", "my tune")),
              Param("words", "Words", 0, 1, 0.3, "", 0, ("only singing", "clear words")),
              Param("calls", "How many notes", 0, 1, 0, "", 0,
                    ("every syllable", "one a sentence")),
              Param("mix", "Mix", 0, 1, 1))

    BASE_HZ = 130.81            # his note with Pitch at 0 (C3)
    VIB_HZ, VIB_DEPTH = 4.7, 0.015
    GLIDE_S = 0.025             # his slide to a new note (measured: ~60 ms end to end)
    HOLD_S = 0.1                # how long a new note must last before he takes it
    GAP_S = 0.12                # the shortest syllable he sings
    GATE = 0.004                # quieter than this (about -48 dBFS) and he stops
    EE, AA, II = 6.0, 3.0, 5.0  # his vowel rows: a syllable starts "y", sings "a",
    YA_S = 0.05                 # ... slides from "y" to "a" in this long,
                                # and closes to "i" as he lets go
    MOUTH_S = 0.06              # his mouth moves from vowel to vowel this slowly
    # How many notes at "one a sentence": a new one only after a pause this long, or
    # once his note has had this long; a held note moves only after LONG_HOLD_S
    PAUSE_S = 0.4
    PHRASE_S = 4.0
    LONG_HOLD_S = 1.0
    KNEE = F32(0.9)             # his voice is rounded off above this, never past 1

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        rate = rate or 48000
        self.tracker = _PitchTracker(rate)
        self.spec_n = 1 << int(np.ceil(np.log2(rate * 0.021)))
        self.hist = np.zeros(self.spec_n, F32)
        self.win = np.hanning(self.spec_n).astype(F32)
        fr = np.fft.rfftfreq(self.spec_n, 1 / rate)
        self.band = (fr > 200) & (fr < 3500)
        self.band_hz = fr[self.band]
        self.hiss = _Filter()
        self.phase = self.vib = 0.0
        self.f = 0.0                # the note he's singing now (Hz; 0 = not yet)
        self.target = self.cand = 0.0
        self.cand_n = 0.0           # seconds the next note has lasted
        self.home = 0.0             # your usual pitch (semitones), learnt as you talk
        self.heard = 0              # voiced blocks it's learnt from
        self.filled = 0             # input samples the pitch tracker has seen
        self.amp = 0.0
        self.vowel = self.AA
        self.peak = self.dip = 0.0  # loudness since the last syllable (finds the next)
        self.since = 0.0            # seconds into this syllable
        self.quiet = 1e9            # seconds you've been quiet (huge: not yet talked)
        self.pitched = False        # this syllable's note came from your pitch
        self.amps = None            # last block's harmonic levels (glided across)

    def _note(self, f0: float) -> float:
        """Your pitch -> his note: how far you are above or below your usual pitch,
        on a five-note scale around his own note."""
        st = 12 * np.log2(f0)
        # your middle pitch: a running median (a stray octave jump can't drag it), in
        # big steps at first, then slowly following you
        self.heard += 1
        if self.heard == 1:
            self.home = st
        else:
            self.home += np.sign(st - self.home) * max(0.02, 2.0 / self.heard ** 0.75)
        semis = (st - self.home) * self.p["follow"]
        notes = 12 * np.floor(semis / 12) + _MONK_SCALE
        step = float(notes[np.argmin(np.abs(notes - semis))])
        return self.BASE_HZ * 2 ** ((self.p["note"] + step) / 12)

    def _vowel(self) -> float:
        """Brightness of your voice -> his vowel row (0 = "oo" .. 10 = "ee")."""
        s = np.abs(np.fft.rfft(self.hist * self.win))[self.band]
        c = float((self.band_hz * s).sum() / max(float(s.sum()), 1e-9))
        return float(np.interp(np.log(max(c, 1.0)), np.log([500, 900, 2000]), [1, 3, 9]))

    def run(self, x, rate):
        n = len(x)
        if n == 0:
            return x
        h = self.hist
        if n >= len(h):
            h[:] = x[n - len(h):]
        else:
            h[:-n] = h[n:]
            h[-n:] = x
        f0 = self.tracker.update(x)
        self.filled += n
        if self.filled < self.tracker.window:
            f0 = 0.0                                     # half a window: no pitch yet
        level = float(np.sqrt(np.mean(x * x)))
        loud = level > self.GATE
        # a new syllable: sound after quiet, or loudness rising again out of a dip
        self.peak = max(self.peak, level)
        self.dip = min(self.dip, level)
        self.since += n / rate
        # How many notes: every syllable, or towards one a sentence (a new note only
        # after a pause, or once his note has had a long while)
        c = self.p["calls"]
        gap = self.quiet
        self.quiet = 0.0 if loud else self.quiet + n / rate
        fresh = loud and ((self.amp < self.GATE and (gap >= c * self.PAUSE_S or self.f == 0))
                          or (self.since > self.GAP_S + c * (self.PHRASE_S - self.GAP_S)
                              and self.dip < 0.5 * self.peak and level > 2 * self.dip))
        if fresh or not loud:
            self.peak = self.dip = level
        if fresh:
            self.since = 0.0
            self.pitched = False                         # no note of yours heard in it yet
        if loud and f0 > 0:
            note = self._note(f0)
            if self.f == 0 or fresh or not self.pitched:   # a new syllable: straight there
                self.pitched = True
                self.target = self.cand = note
                if self.f == 0 or self.amp < self.GATE:
                    self.f = note
                self.cand_n = 0.0
            elif note != self.cand:
                self.cand, self.cand_n = note, n / rate
            elif note != self.target:
                self.cand_n += n / rate
                if self.cand_n >= self.HOLD_S + c * (self.LONG_HOLD_S - self.HOLD_S):
                    self.target = note
        elif fresh and (self.f == 0 or self.amp < self.GATE):
            # sound with no pitch (a whisper, an "s"): he starts on his own note
            self.f = self.target = self.cand = self.BASE_HZ * 2 ** (self.p["note"] / 12)
            self.cand_n = 0.0
        if self.f == 0:
            return (x * F32(1 - self.p["mix"])).astype(F32, copy=False)
        # loudness: fast up, a little slower down (a sung note, not a gate)
        goal = level * 1.4 if loud else 0.0
        tau = 0.011 if goal > self.amp else 0.015       # measured: ~10 ms in, ~15 ms out
        k = 1 - np.exp(-n / rate / tau)
        amp0, self.amp = self.amp, self.amp + k * (goal - self.amp)
        # his vowel: "y" to "a" in YA_S (a touch less open when yours is closed),
        # "i" as he lets go
        if not loud:
            goal = self.II
        else:
            goal = self.AA + 0.35 * float(np.clip(abs(self._vowel() - 3) / 4, 0, 1))
            if self.since < self.YA_S:                    # "y..." sliding into "a"
                goal += (self.EE - goal) * (1 - self.since / self.YA_S)
        self.vowel += (1 - np.exp(-n / rate / self.MOUTH_S)) * (goal - self.vowel)
        # pitch: glide to the target, plus his vibrato
        t = np.arange(1, n + 1) / rate
        f = self.target + (self.f - self.target) * np.exp(-t / self.GLIDE_S)
        self.f = float(f[-1])
        vib = 1 + self.VIB_DEPTH * np.sin(self.vib + 2 * np.pi * self.VIB_HZ * t)
        self.vib = float((self.vib + 2 * np.pi * self.VIB_HZ * n / rate) % (2 * np.pi))
        ph = self.phase + np.cumsum(2 * np.pi * f * vib / rate)
        self.phase = float(ph[-1] % (2 * np.pi))
        # the buzz through his vowel: every harmonic at the vowel filter's level
        top = min(7000.0, rate * 0.45)       # he has next to nothing above
        k_n = max(1, int(top / (self.f * 1.03)))
        ks = np.arange(1, k_n + 1)
        lo = int(np.clip(np.floor(self.vowel), 0, len(_MONK_DB) - 2))
        a = float(np.clip(self.vowel - lo, 0, 1))
        row = _MONK_DB[lo] * (1 - a) + _MONK_DB[lo + 1] * a
        amps = 10 ** (np.interp(np.log(ks * self.f), _MONK_LOG_HZ, row) / 20)
        amps /= np.sqrt(0.5 * float((amps * amps).sum()))           # rms 1
        old = self.amps
        if old is None or len(old) != k_n:
            old = amps
        self.amps = amps
        ramp = np.linspace(0, 1, n, endpoint=False)
        wave = np.einsum("kn,kn->n", np.sin(np.outer(ks, ph)),
                         old[:, None] + (amps - old)[:, None] * ramp)
        g = np.linspace(amp0, self.amp, n, endpoint=False)
        wet = wave * g
        words = self.p["words"]
        if words > 0:
            hiss = self.hiss.run(x, ("hp", rate),
                                 lambda: butter(2, 2500, btype="high", fs=rate).astype(F32))
            wet = wet + hiss * (2.5 * words)
        # a held "a" on a loud mic can pass full scale: its tops rounded off above
        # KNEE (nothing below it changes)
        wet = wet.astype(F32)
        over = np.abs(wet) > self.KNEE
        if over.any():
            a = np.abs(wet[over])
            wet[over] = np.sign(wet[over]) * (self.KNEE + (1 - self.KNEE)
                                             * np.tanh((a - self.KNEE) / (1 - self.KNEE)))
        mix = F32(self.p["mix"])
        return wet if mix >= 1 else (x * (1 - mix) + wet * mix).astype(F32)


@register
class RingMod(Effect):
    """Ring modulator: the voice multiplied by a sine. Every harmonic of the voice
    turns into a pair, one the sine's pitch above it and one below, so the voice
    loses its own pitch and takes on a metallic, bell-like one: the Dalek at about
    30 Hz, a robot bell higher up. The sine's phase runs on from block to block and
    its pitch glides across a block, so neither a block edge nor a dragged slider
    clicks."""

    type = "ringmod"
    name = "Ring modulator"
    description = "Metallic, bell-like voice: the Dalek."
    params = (Param("freq", "Pitch", 5, 2000, 30, " Hz", 1, ("rumble", "bell")),
              Param("mix", "Mix", 0, 1, 1))

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.phase = 0.0
        self.f = float(self.p["freq"])
        self.mix = None

    def run(self, x, rate):
        n = len(x)
        if n == 0:
            return x
        f, f0 = float(self.p["freq"]), self.f
        self.f = f
        hz = np.linspace(f0, f, n + 1)[1:] if f0 != f else f
        ph = self.phase + 2 * np.pi * np.cumsum(np.broadcast_to(hz, (n,)) / rate)
        self.phase = float(ph[-1] % (2 * np.pi))
        wet = x * np.sin(ph).astype(F32)
        mix = self.p["mix"]
        m = _glide(mix if self.mix is None else self.mix, mix, n)
        self.mix = mix
        return (x * (1 - m) + wet * m).astype(F32, copy=False)
