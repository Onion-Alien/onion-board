"""Clean up my mic: hum, hiss and room noise out before the other effects."""
from __future__ import annotations

import math

import numpy as np
from soundboard.audio.dsp import butter
from soundboard.voicefx import Effect, Param, register

from soundboard.voicefx.builtin.parts import F32, _Filter, _Stage, _stft_size


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
        self.stft: _Stage | None = None
        self._layout: dict[int, tuple] = {}     # block size -> the gate's pieces
        self.noise: np.ndarray | None = None   # the noise's power per frequency
        self.prev_gain: np.ndarray | None = None
        self.creep = 1.0

    def latency(self) -> float:
        if self.p["hiss"] <= 0 or self.light:
            return 0.0
        return (self.stft.n if self.stft else _stft_size(self.rate, self.FRAME_S)) / self.rate

    def _gate(self, x, rate):
        """Downward expander, decided per 2.5 ms piece and ramped sample by sample."""
        strength = self.p["gate"]
        n = len(x)
        lay = self._layout.get(n)
        if lay is None:   # the block size's pieces, worked out once (it rarely changes)
            if len(self._layout) > 8:
                self._layout.clear()
            pieces = max(1, n // self.sub)
            edges = np.linspace(0, n, pieces + 1).astype(int)
            lay = self._layout[n] = (pieces, edges, np.diff(edges).tolist(), np.arange(n),
                                     np.concatenate([[-1], edges[1:] - 1]))
        pieces, edges, sizes, at, knots = lay
        if n % pieces == 0:   # (the usual block: equal pieces, one call for them all)
            lv = np.sqrt(np.mean((x * x).reshape(pieces, -1), axis=1) + 1e-12)
        else:
            lv = np.array([np.sqrt(np.mean(x[a:b] ** 2) + 1e-12)
                           for a, b in zip(edges[:-1], edges[1:])])
        db = (20 * np.log10(lv)).tolist()
        dt = n / rate
        # the noise floor: the quietest moment of the last FLOOR_S (between words you
        # always drop to the room's noise), so it learns a noisy room straight away
        # and follows it if it gets louder or quieter
        self.mins.append((dt, max(min(db), -90.0)))
        span = sum(t for t, _ in self.mins)
        while len(self.mins) > 1 and span - self.mins[0][0] >= self.FLOOR_S:
            span -= self.mins.pop(0)[0]
        self.floor_db = min(min(m for _, m in self.mins), -38.0)
        open_at, close_at = max(self.floor_db + 9, -60), max(self.floor_db + 5, -64)
        closed_g = 10 ** (-30 * strength / 20)
        gains = np.empty(pieces + 1)
        gains[0] = g = self.g
        for i, d in enumerate(db):   # (plain floats: numpy scalars cost more here)
            piece = sizes[i] / rate
            if d > open_at:
                self.open, self.held = True, 0.0
            elif self.open and d < close_at:
                self.held += piece
                if self.held > self.HOLD_S:
                    self.open = False
            target = 1.0 if self.open else closed_g
            tau = 0.002 if target > g else 0.06
            g = target + (g - target) * math.exp(-piece / tau)
            gains[i + 1] = g
        ramp = np.interp(at, knots, gains)
        self.g = float(g)
        return (x * ramp).astype(F32)

    def _dehiss(self, spec):
        strength = self.p["hiss"]
        power = (spec.real ** 2 + spec.imag ** 2).astype(np.float64)
        noise = self.noise
        if noise is None:   # start low: what you say first mustn't count as noise
            noise = power.mean(axis=0) * 1e-3 + 1e-12
        frame_db = (10 * np.log10(power.mean(axis=1) + 1e-20)).tolist()
        over = 1.0 + strength            # subtract a bit more than the estimate
        floor = 10 ** (-18 * strength / 20)
        gated = self.p["gate"] > 0 and not self.open
        # the noise estimate goes frame by frame (each frame's decision needs the one
        # before); the gains are then worked out for all the frames at once
        noises = np.empty_like(power)
        for f in range(len(spec)):
            noise_db = 10 * math.log10(float(noise.mean()) + 1e-20)
            if gated or frame_db[f] < noise_db + 3:   # quiet: learn the noise
                noise = 0.9 * noise + 0.1 * power[f]
            else:   # creeps up (~3 dB/s), so a louder room is learned even mid-talk
                noise = noise * self.creep
            noises[f] = noise
        self.noise = noise
        g = np.maximum(1 - over * noises / (power + 1e-20), floor)
        sm = 0.5 * g                     # (0.25, 0.5, 0.25) along frequency, zeros past
        sm[:, 1:] += 0.25 * g[:, :-1]    # the ends: less "musical noise"
        sm[:, :-1] += 0.25 * g[:, 1:]
        prev = self.prev_gain
        for f in range(len(sm)):
            if prev is not None:
                np.maximum(sm[f], 0.6 * prev, out=sm[f])   # fades out, never snaps
            prev = sm[f]
        if len(sm):
            self.prev_gain = sm[-1].copy()
        return spec * sm

    def run(self, x, rate):
        y = self.hp.run(x, "hp", lambda: butter(2, 80, btype="high", fs=rate).astype(F32))
        if self.p["gate"] > 0:
            y = self._gate(y, rate)
        else:
            self.open = True
        want = self.p["hiss"] > 0 and not self.light   # (Use less CPU: no hiss removal)
        if want and self.stft is None:
            self.stft = _Stage(_stft_size(rate, self.FRAME_S), int(rate * 0.01))
            # per frame, so the rise is CREEP_DB a second at any rate
            self.creep = 10 ** (self.CREEP_DB / 10 * self.stft.hop / rate)
        if self.stft is not None:   # (at 0 it fades out first: dropping it jumped 10 ms)
            y = self.stft.run(y, self._dehiss, want)
            if not self.stft.on:
                self.stft = None
        return y
