"""Whistle and Kazoo: your tune, whistled or buzzed through a kazoo. Your voice is
only listened to (the way the animals do, animals._Critter): its loudness and its
tune drive a sound made in code."""
from __future__ import annotations

import numpy as np
from soundboard.audio.dsp import butter
from soundboard.voicefx import Param, register

from soundboard.voicefx.builtin.animals import _Critter, _formants
from soundboard.voicefx.builtin.parts import F32, _Filter, _harmonics


class _Tune(_Critter):
    """A held tone that follows you: as loud as you (gone when you stop), its pitch
    gliding after your tune (how far you are above or below your usual pitch, times
    Follow my tune), a little vibrato. Quieter on sounds with no pitch ("s", "f"). A
    subclass makes the sound from the phase it's given (`_sound`)."""

    needs_download = False  # (made in code)
    GLIDE_S = 0.03         # the pitch slides to a new note this fast
    UNVOICED = 0.3         # how loud it stays on a sound with no pitch
    LEVEL = 1.4            # its loudness against yours
    ATTACK_S, RELEASE_S = 0.012, 0.04

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.st = None         # the pitch now (semitones from BASE_HZ, glided)
        self.voiced = 0.0
        self.words = _Filter()

    @classmethod
    def prepare(cls, cfg):
        pass                # nothing to download

    def _base_st(self) -> float:
        """The tune's middle (semitones from BASE_HZ)."""
        return 0.0

    def run(self, x, rate):
        n = len(x)
        if n == 0:
            return x
        self._listen(x, rate)
        dt = n / rate
        pitched = self.talking and self.tracker.f0 > 0 and self.filled >= self.tracker.window
        v_goal = 1.0 if pitched else self.UNVOICED
        self.voiced += (1 - np.exp(-dt / 0.02)) * (v_goal - self.voiced)
        goal = (min(self.level, self.MOST) * self.LEVEL * self.voiced) if self.talking else 0.0
        mix = self.p["mix"]
        if self.amp < 1e-5 and goal < 1e-5:
            self.amp, self.st = 0.0, None
            return (x * F32(1 - mix)).astype(F32)
        st_goal = self._base_st() + self.p["note"] + self.rel * self.p["follow"]
        st0 = st_goal if self.st is None else self.st
        self.st = st0 + (1 - np.exp(-dt / self.GLIDE_S)) * (st_goal - st0)
        tau = self.ATTACK_S if goal > self.amp else self.RELEASE_S
        amp0 = self.amp
        self.amp += (1 - np.exp(-dt / tau)) * (goal - self.amp)
        t = np.arange(1, n + 1) / rate
        f = self.BASE_HZ * 2 ** (np.linspace(st0, self.st, n + 1)[1:] / 12)
        f = f * (1 + self.VIB_DEPTH * np.sin(self.vib + 2 * np.pi * self.VIB_HZ * t))
        self.vib = float((self.vib + 2 * np.pi * self.VIB_HZ * dt) % (2 * np.pi))
        ph = self.phase + np.cumsum(2 * np.pi * f / rate)
        self.phase = float(ph[-1] % (2 * np.pi))
        g = np.linspace(amp0, self.amp, n, endpoint=False).astype(F32)
        wet = self._sound(ph, float(f[-1]), x, rate) * g + self._words(x, rate)
        wet = np.tanh(wet).astype(F32)     # (a shout or noise stays under full scale)
        return wet if mix >= 1 else (x * F32(1 - mix) + wet * F32(mix)).astype(F32)

    def _sound(self, ph: np.ndarray, f: float, x: np.ndarray, rate: int) -> np.ndarray:
        raise NotImplementedError

    def _words(self, x: np.ndarray, rate: int):
        """Some of your own voice kept on top (Words), or 0."""
        return F32(0)


@register
class Whistle(_Tune):
    """Your tune whistled: a near-pure tone high up in whistling range (well above
    any voice), with a breath of air around it and a small vibrato."""

    type = "whistle"
    name = "Whistle"
    description = "Your words come out whistled, following your tune."
    params = (Param("note", "Pitch", -12, 12, 0, " st", 1, ("lower", "higher")),
              Param("follow", "Follow my tune", 0, 1.5, 1.2, "", 0, ("one note", "my tune")),
              Param("mix", "Mix", 0, 1, 1))

    BASE_HZ = 1250.0
    VIB_HZ, VIB_DEPTH = 5.2, 0.006
    AIR = 0.12             # breath noise, of the tone's loudness

    def _sound(self, ph, f, x, rate):
        n = len(ph)
        tone = np.sin(ph) + 0.05 * np.sin(2 * ph)
        lo, hi = min(1500.0, 0.3 * rate), min(7000.0, 0.45 * rate)
        air = self.breath.run(self.rng.standard_normal(n).astype(F32), ("air", rate),
                              lambda: butter(2, [lo, hi], btype="band",
                                             fs=rate).astype(F32))
        return (tone * 1.4 + air * F32(self.AIR * 2.5)).astype(F32)


class _WordsTune(_Tune):
    def _words(self, x, rate):
        words = self.p["words"]
        if words <= 0:
            return F32(0)
        hp = min(2500.0, 0.4 * rate)
        hiss = self.words.run(x, ("hp", rate),
                              lambda: butter(2, hp, btype="high", fs=rate).astype(F32))
        # (as loud as your hiss, up to a shout's: full-scale noise isn't let through)
        cap = min(1.0, self.MOST / max(float(np.sqrt(np.mean(x * x))), 1e-9))
        return hiss * F32(2.5 * words * cap)


@register
class Kazoo(_WordsTune):
    """Your tune buzzed through a kazoo: a bright buzz at your own pitch (a deep voice
    lifted a little), through the kazoo's nasal, paper-thin resonance, with a little
    rattle. A bit of your own hiss ("Words") keeps the consonants, so you can still
    just about be followed."""

    type = "kazoo"
    name = "Kazoo"
    description = "Your words come out buzzed through a kazoo, following your tune."
    params = (Param("note", "Pitch", -12, 12, 0, " st", 1, ("lower", "higher")),
              Param("follow", "Follow my tune", 0, 1.5, 1.0, "", 0, ("one note", "my tune")),
              Param("words", "Words", 0, 1, 0.35, "", 0, ("only singing", "clear words")),
              Param("mix", "Mix", 0, 1, 1))

    BASE_HZ = 1.0          # (the tune's middle is your own pitch: _base_st)
    VIB_HZ, VIB_DEPTH = 5.0, 0.004
    UNVOICED = 0.15
    LOWEST_HZ = 150.0
    PEAKS = np.array([[550, 300, 0.5], [1250, 450, 1.0], [2600, 700, 0.8],
                      [4200, 1200, 0.35]], F32)

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.amps = None

    def _base_st(self):
        # your usual pitch (12 * log2 Hz), a deep voice lifted to LOWEST_HZ (a low buzz
        # just rumbles); that until it's heard you
        return max(self.home if self.heard else 0.0, 12 * np.log2(self.LOWEST_HZ))

    def _sound(self, ph, f, x, rate):
        top = min(7500.0, rate * 0.45)
        k_n = max(1, int(top / (f * 1.03)))
        ks = np.arange(1, k_n + 1)
        amps = _formants(ks * f, self.PEAKS) / ks ** 0.15
        amps = amps / np.sqrt(0.5 * float((amps * amps).sum()))
        old = self.amps if self.amps is not None and len(self.amps) == k_n else amps
        self.amps = amps
        buzz = _harmonics(ph, old, amps)
        # the paper's rattle: clipped a little, its loudness fluttering
        flut = 1 + 0.08 * self.rng.standard_normal(1)[0]
        return (np.tanh(buzz * 0.9) * 1.25 * flut).astype(F32)


@register
class NasalHum(_WordsTune):
    """Your tune as a grumpy nasal hum: a low-mid buzzy glottal wave shaped through a
    pinched nasal formant bank, following your tune with a small vibrato. A touch of
    your own hiss ("Words") keeps consonants clear enough to follow."""

    type = "nasal_hum"
    name = "Nasal hum"
    description = "A nasal hum that follows your pitch."
    params = (Param("note", "Pitch", -12, 12, 0, " st", 1, ("lower", "higher")),
              Param("follow", "Follow my tune", 0, 1, 0.4, "", 0, ("one note", "my tune")),
              Param("words", "Words", 0, 1, 0.2, "", 0, ("only humming", "clear words")),
              Param("mix", "Mix", 0, 1, 1))

    BASE_HZ = 125.0
    VIB_HZ, VIB_DEPTH = 4.2, 0.007
    GLIDE_S = 0.035
    UNVOICED = 0.25
    PEAKS = np.array([[300, 130, 1.2], [1050, 260, 1.0], [2350, 450, 0.45]], F32)

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.amps = None

    def _sound(self, ph, f, x, rate):
        top = min(4500.0, rate * 0.45)
        k_n = max(1, int(top / max(f * 1.03, 1.0)))
        ks = np.arange(1, k_n + 1)
        amps = _formants(ks * f, self.PEAKS) / ks ** 0.35
        norm = np.sqrt(0.5 * float((amps * amps).sum()))
        if norm > 1e-12:
            amps = amps / norm
        old = self.amps if self.amps is not None and len(self.amps) == k_n else amps
        self.amps = amps
        hum = _harmonics(ph, old, amps)
        return (np.tanh(hum * 0.85) * 1.25).astype(F32)


@register
class ArcadeMelody(_WordsTune):
    """Each syllable you say steps to the next note of an upbeat minor-key 8-bit arcade
    melody, played on a band-limited square wave with a snappy chip envelope."""

    type = "arcade_melody"
    name = "Arcade melody"
    description = "Play a chip melody with each syllable."
    params = (Param("note", "Pitch", -12, 12, 0, " st", 1, ("lower", "higher")),
              Param("words", "Words", 0, 1, 0.15, "", 0, ("only synth", "clear words")),
              Param("mix", "Mix", 0, 1, 1))

    BASE_HZ = 440.0        # A4: bright 8-bit arcade lead register
    VIB_HZ, VIB_DEPTH = 6.0, 0.004
    GLIDE_S = 0.003        # crisp chiptune step without clicking
    ATTACK_S, RELEASE_S = 0.006, 0.035
    HOLD_STEP_S = 0.28     # a long held vowel steps to the next note on the beat
    LEVEL = 1.4
    # original upbeat 16-note A-minor arcade arpeggio phrase (semitones from A4)
    MELODY = (0, 7, 12, 10, 7, 5, 7, 3, 0, 3, 7, 10, 12, 10, 7, 5)

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.note_idx = -1
        self.note_age = 0.0
        self.step_at = 0.0
        self.amps: np.ndarray | None = None

    def run(self, x, rate):
        n = len(x)
        if n == 0:
            return x
        fresh = self._listen(x, rate)
        dt = n / rate
        if fresh:
            self.note_idx = (self.note_idx + 1) % len(self.MELODY)
            self.note_age = 0.0
            self.step_at = 0.0
        elif self.talking and self.since - self.step_at >= self.HOLD_STEP_S:
            self.note_idx = (self.note_idx + 1) % len(self.MELODY)
            self.note_age = 0.0
            self.step_at = self.since
        else:
            self.note_age += dt
        pluck = 0.55 + 0.45 * float(np.exp(-self.note_age / 0.07))
        goal = (min(self.level, self.MOST) * self.LEVEL * pluck) if self.talking else 0.0
        mix = self.p["mix"]
        if self.amp < 1e-5 and goal < 1e-5:
            self.amp, self.st = 0.0, None
            return (x * F32(1 - mix)).astype(F32)
        idx = max(0, self.note_idx)
        st_goal = float(self.MELODY[idx]) + self.p["note"]
        st0 = st_goal if self.st is None else self.st
        self.st = st0 + (1 - np.exp(-dt / self.GLIDE_S)) * (st_goal - st0)
        tau = self.ATTACK_S if goal > self.amp else self.RELEASE_S
        amp0 = self.amp
        self.amp += (1 - np.exp(-dt / tau)) * (goal - self.amp)
        t = np.arange(1, n + 1) / rate
        f = self.BASE_HZ * 2 ** (np.linspace(st0, self.st, n + 1)[1:] / 12)
        f = f * (1 + self.VIB_DEPTH * np.sin(self.vib + 2 * np.pi * self.VIB_HZ * t))
        self.vib = float((self.vib + 2 * np.pi * self.VIB_HZ * dt) % (2 * np.pi))
        ph = self.phase + np.cumsum(2 * np.pi * f / rate)
        self.phase = float(ph[-1] % (2 * np.pi))
        g = np.linspace(amp0, self.amp, n, endpoint=False).astype(F32)
        wet = self._sound(ph, float(f[-1]), x, rate) * g + self._words(x, rate)
        wet = np.tanh(wet).astype(F32)
        return wet if mix >= 1 else (x * F32(1 - mix) + wet * F32(mix)).astype(F32)

    def _sound(self, ph, f, x, rate):
        # band-limited 8-bit square wave: odd harmonics 1, 1/3, 1/5, 1/7 up to Nyquist
        top = min(7000.0, rate * 0.45)
        k_n = max(1, min(7, int(top / max(f * 1.03, 1.0))))
        ks = np.arange(1, k_n + 1)
        amps = np.where(ks % 2 == 1, 1.0 / ks, 0.0).astype(F32)
        amps = amps / np.sqrt(0.5 * float((amps * amps).sum()))
        old = self.amps if self.amps is not None and len(self.amps) == k_n else amps
        self.amps = amps
        return _harmonics(ph, old, amps).astype(F32)
