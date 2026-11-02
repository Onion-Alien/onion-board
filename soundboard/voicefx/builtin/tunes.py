"""Whistle and Kazoo: your tune, whistled or buzzed through a kazoo. Your voice is
only listened to (the way the animals do, animals._Critter): its loudness and its
tune drive a sound made in code."""
from __future__ import annotations

import numpy as np
from soundboard.audio.dsp import butter
from soundboard.voicefx import Param, register

from soundboard.voicefx.builtin.animals import _Critter, _formants
from soundboard.voicefx.builtin.parts import F32, _Filter


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


@register
class Kazoo(_Tune):
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
        n = len(ph)
        top = min(7500.0, rate * 0.45)
        k_n = max(1, int(top / (f * 1.03)))
        ks = np.arange(1, k_n + 1)
        amps = _formants(ks * f, self.PEAKS) / ks ** 0.15
        amps = amps / np.sqrt(0.5 * float((amps * amps).sum()))
        old = self.amps if self.amps is not None and len(self.amps) == k_n else amps
        self.amps = amps
        ramp = np.linspace(0, 1, n, endpoint=False)
        buzz = np.einsum("kn,kn->n", np.sin(np.outer(ks, ph)),
                         old[:, None] + (amps - old)[:, None] * ramp)
        # the paper's rattle: clipped a little, its loudness fluttering
        flut = 1 + 0.08 * self.rng.standard_normal(1)[0]
        return (np.tanh(buzz * 0.9) * 1.25 * flut).astype(F32)

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
