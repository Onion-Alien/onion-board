"""Voice-chat mic processing, simulated: what Discord or a game does to our sounds
*before* the codec, when its voice cleanup is left on.

Development tool, like soundboard.codecsim: the bench runs sounds through it to
put numbers on the damage, and the tests use it to check that the Discord check
(soundboard.chatcheck) recognises each kind. The models follow the classic
designs these services build on (WebRTC's noise suppressor, gain controller and
voice-activity gate), not any one product's exact tuning:

  suppress   noise suppression: a noise estimate by minimum statistics (the
             quietest recent level in each frequency band is taken to be noise)
             and a Wiener-style gain. Steady music *is* its own minimum, so it is
             treated as noise and pulled down within a second or so.
  agc        automatic gain control: steers the level toward a target at a few dB
             per second, raising quiet parts and pumping after loud ones.
  gate       voice-activity gate: open above a threshold, closes after a short
             hang, so quiet intros, fades and gaps are cut.

    y = process(x, ("suppress", "agc", "gate"))    # (n, 2) float32 at 48 kHz
"""
from __future__ import annotations

import numpy as np

SR = 48000
F32 = np.float32
STAGES = ("suppress", "agc", "gate")


def _mono(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, np.float64)
    return x.mean(axis=1) if x.ndim == 2 else x


def suppress(x: np.ndarray, rate: int = SR, window_s: float = 1.5,
             floor: float = 0.1) -> np.ndarray:
    """Noise suppression by minimum statistics + Wiener gain (mono in, mono out)."""
    n_fft, hop = 1024, 512
    win = np.sqrt(np.hanning(n_fft + 1)[:-1])       # sqrt-Hann analysis + synthesis
    pad = np.concatenate([np.zeros(n_fft), x, np.zeros(n_fft)])
    frames = 1 + (len(pad) - n_fft) // hop
    out = np.zeros(len(pad))
    smooth = None
    hist: list[np.ndarray] = []
    keep = max(1, int(window_s * rate / hop))
    for k in range(frames):
        seg = pad[k * hop:k * hop + n_fft] * win
        spec = np.fft.rfft(seg)
        power = np.abs(spec) ** 2
        smooth = power if smooth is None else 0.8 * smooth + 0.2 * power
        hist.append(smooth)
        if len(hist) > keep:
            hist.pop(0)
        noise = np.min(hist, axis=0) * 1.5            # bias: the minimum sits under the mean
        gain = np.maximum(1.0 - noise / np.maximum(smooth, 1e-20), floor)
        out[k * hop:k * hop + n_fft] += np.fft.irfft(spec * gain, n_fft) * win
    return out[n_fft:n_fft + len(x)]


def agc(x: np.ndarray, rate: int = SR, target_db: float = -18.0, speed_db_s: float = 6.0,
        max_gain_db: float = 24.0) -> np.ndarray:
    """A slow adaptive gain: every 10 ms frame nudges the gain toward what would put
    that frame at target_db, by at most speed_db_s per second (faster downward)."""
    n = rate // 100
    out = np.array(x, np.float64)
    g = 0.0
    for i in range(0, len(x), n):
        f = out[i:i + n]
        lvl = 10 * np.log10(np.mean(f ** 2) + 1e-12)
        if lvl > -60:                                  # only adapts on something
            want = np.clip(target_db - lvl, -max_gain_db, max_gain_db)
            step = speed_db_s * (n / rate) * (3 if want < g else 1)
            g += np.clip(want - g, -step, step)
        f *= 10 ** (g / 20)
    return out


def gate(x: np.ndarray, rate: int = SR, threshold_db: float = -40.0,
         hang_s: float = 0.2) -> np.ndarray:
    """Voice-activity gate: 10 ms frames under the threshold (after a hang) are cut,
    with 5 ms ramps."""
    n = rate // 100
    k = len(x) // n + 1
    open_ = np.zeros(k)
    hang = 0.0
    for j in range(k):
        f = x[j * n:(j + 1) * n]
        lvl = 10 * np.log10(np.mean(f ** 2) + 1e-12) if len(f) else -120
        if lvl > threshold_db:
            hang = hang_s
        else:
            hang = max(0.0, hang - n / rate)
        open_[j] = 1.0 if hang > 0 else 0.0
    env = np.repeat(open_, n)[:len(x)]
    ramp = max(1, int(0.005 * rate))
    env = np.convolve(env, np.ones(ramp) / ramp, mode="same")
    return x * env


def process(x: np.ndarray, stages=STAGES, rate: int = SR) -> np.ndarray:
    """Run x ((n, 2) or (n,) float at `rate`) through the chosen stages, in the order
    a voice chat applies them (suppress, agc, gate). Returns (n, 2) float32: the
    mic capture is mono, so both channels are the same."""
    y = _mono(x)
    for name in STAGES:
        if name in stages:
            y = {"suppress": suppress, "agc": agc, "gate": gate}[name](y, rate)
    return np.repeat(y[:, None], 2, axis=1).astype(F32)


__all__ = ["STAGES", "agc", "gate", "process", "suppress"]
