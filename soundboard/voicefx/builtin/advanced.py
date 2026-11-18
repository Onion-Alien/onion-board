"""Optional finishing controls for custom voices. Existing voices leave these off."""
from __future__ import annotations

import numpy as np

from soundboard.voicefx import Effect, Param, register
from soundboard.voicefx.builtin.parts import F32, _Filter, _Line, _biquad, _glide


@register
class VoiceEqualizer(Effect):
    type = "voice_eq"
    name = "Parametric equalizer"
    description = "Shape three bands of your voice, with a frequency, gain and width for each."
    params = tuple(q for i, hz in enumerate((180, 1200, 4500), 1) for q in (
        Param(f"freq{i}", f"Band {i} frequency", 40, 16000, hz, " Hz", 10),
        Param(f"gain{i}", f"Band {i} gain", -12, 12, 0, " dB", 0.5),
        Param(f"q{i}", f"Band {i} width", 0.2, 8, 1, " Q", 0.1,
              ("wide", "narrow"))))

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.f = _Filter()

    def run(self, x, rate):
        p = self.p
        key = tuple(p[q.key] for q in self.params)
        gains = any(p[f"gain{i}"] for i in range(1, 4))
        if not gains and self.f.f.idle:
            return x
        return self.f.run(x, key, lambda: np.vstack([
            _biquad("peak", min(p[f"freq{i}"], rate * 0.45), rate,
                    p[f"gain{i}"], p[f"q{i}"]) for i in range(1, 4)
        ]) if gains else None)


@register
class VoiceOutput(Effect):
    type = "voice_output"
    name = "Voice blend & output"
    description = "Blend your original voice with the effects and set the final volume."
    params = (Param("mix", "Effect amount", 0, 1, 1, "", 0,
                    ("original", "fully effected")),
              Param("level", "Output level", -24, 6, 0, " dB", 0.5))

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self._dry = None
        self._mix = self.p["mix"]
        self._gain = 10 ** (self.p["level"] / 20)

    def run(self, x, rate):
        return x

    def finish(self, dry, wet, rate, latency):
        """Align the original with the preceding effects before blending."""
        delay = max(0, round(latency * rate))
        if delay:
            if self._dry is None or len(self._dry) != delay:
                self._dry = _Line(delay)
            aligned = np.empty_like(dry)
            for a in range(0, len(dry), delay):
                n = min(delay, len(dry) - a)
                aligned[a:a + n] = self._dry.take(n)
                self._dry.put(dry[a:a + n])
            dry = aligned
        else:
            self._dry = None
        mix, gain = self.p["mix"], 10 ** (self.p["level"] / 20)
        amount = _glide(self._mix, mix, len(wet))
        volume = _glide(self._gain, gain, len(wet))
        self._mix, self._gain = mix, gain
        return ((dry + (wet - dry) * amount) * volume).astype(F32, copy=False)
