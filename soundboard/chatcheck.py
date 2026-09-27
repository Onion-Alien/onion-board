"""Voice chat check: what does Discord's own processing do to our sounds?

Discord (and most voice chats) run the mic through noise suppression, an
automatic gain control and a voice-activity gate before anything is sent. They
are built for a voice, and treat music as noise: noise suppression eats steady
sounds, the gate cuts quiet parts and fades, the gain control pumps the volume.
None of that happens in our app, so our own tests can't hear it.

Discord's Mic Test ("Let's Check") plays your mic back to you through all of
that processing. The check plays TEST_SIGNAL into the cable while the Mic Test
runs, captures what Discord plays back (per-program capture, soundboard.appaudio)
and compares the two:

    sig = test_signal()                    # what we send (played into the cable)
    res = analyze(sent, heard, rate)       # sent = the recorded main mix, heard = Discord
    res["issues"]  ->  ["suppression", "gate", "agc"]  (or [] = clean)

The signal has three parts: steady loud music (noise suppression fades it out or
garbles it), the same music 26 dB quieter (a gate cuts it, a gain control lifts
it) and a loud drum loop (after the quiet part a gain control comes back too
loud, then settles). Everything is measured as the gain Discord applied, block by
block, relative to the start, so its output volume doesn't matter.
"""
from __future__ import annotations

import numpy as np

SR = 48000
F32 = np.float32
# (start, end) seconds of each part of the test signal
PART_STEADY = (0.0, 2.5)
PART_QUIET = (2.5, 3.8)
PART_DRUMS = (3.8, 6.0)
LENGTH_S = PART_DRUMS[1]
QUIET_DB = -26.0
BLOCK_S = 0.05
MAX_LAG_S = 2.5          # Discord's Mic Test plays back after a short delay

# what the verdicts mean, for the UI
ISSUES = {
    "not_heard": "Discord didn't play the test back",
    "suppression": "Noise suppression is removing your sounds",
    "gate": "Quiet parts of your sounds are being cut off",
    "agc": "Automatic gain control is pumping the volume",
}


def test_signal(rate: int = SR, seed: int = 7) -> np.ndarray:
    """The check's test sound: (n, 2) float32, identical channels."""
    n = int(LENGTH_S * rate)
    t = np.arange(n) / rate
    rng = np.random.default_rng(seed)
    # steady music: an A-minor chord of rich tones over a soft pink bed
    chord = np.zeros(n)
    for f in (110.0, 220.0, 261.63, 329.63, 440.0):
        for k in range(1, 7):
            chord += np.sin(2 * np.pi * f * k * t + rng.uniform(0, 6.28)) / (k * k)
    spec = np.fft.rfft(rng.standard_normal(n))
    fr = np.fft.rfftfreq(n, 1 / rate)
    spec[1:] /= np.sqrt(fr[1:])
    spec[0] = 0
    bed = np.fft.irfft(spec, n)
    music = chord / np.abs(chord).max() + 0.3 * bed / np.abs(bed).max()
    # a drum loop: kick on the beat, a noisy snare off it (120 bpm)
    drums = np.zeros(n)
    for b in np.arange(0, LENGTH_S, 0.25):
        i = int(b * rate)
        tt = t[: n - i]
        if int(b / 0.25) % 2 == 0:
            drums[i:] += np.sin(2 * np.pi * (55 + 90 * np.exp(-tt * 35)) * tt) * np.exp(-tt * 9)
        else:
            drums[i:] += rng.standard_normal(n - i) * np.exp(-tt * 22) * 0.6
    out = np.zeros(n)
    a, b = (int(x * rate) for x in PART_STEADY)
    out[a:b] = music[a:b]
    a, b = (int(x * rate) for x in PART_QUIET)
    out[a:b] = music[a:b] * 10 ** (QUIET_DB / 20)
    a, b = (int(x * rate) for x in PART_DRUMS)
    out[a:b] = drums[a:b] / np.abs(drums[a:b]).max() + 0.3 * music[a:b]
    # short ramps at the joins and ends (no clicks, which a gate would key on)
    ramp = int(0.01 * rate)
    env = np.ones(n)
    env[:ramp] = np.linspace(0, 1, ramp)
    env[-ramp:] = np.linspace(1, 0, ramp)
    out *= env
    out *= 0.35 / np.abs(out).max()
    return np.repeat(out[:, None], 2, axis=1).astype(F32)


def _mono(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, np.float64)
    return x.mean(axis=1) if x.ndim == 2 else x


def _align(sent: np.ndarray, heard: np.ndarray, rate: int) -> tuple[int, float]:
    """(lag of heard behind sent in samples, normalised correlation peak 0..1)."""
    n = 1 << int(np.ceil(np.log2(len(sent) + len(heard))))
    xc = np.fft.irfft(np.fft.rfft(heard, n) * np.conj(np.fft.rfft(sent, n)), n)
    m = min(int(MAX_LAG_S * rate), len(heard))
    lag = int(np.abs(xc[:m]).argmax())
    k = min(len(sent), len(heard) - lag)
    if k <= 0:
        return lag, 0.0
    s, h = sent[:k], heard[lag:lag + k]
    peak = abs(float((s * h).sum())) / (np.sqrt((s * s).sum() * (h * h).sum()) + 1e-12)
    return lag, float(peak)


def _envelope_match(sent: np.ndarray, heard: np.ndarray, rate: int) -> tuple[int, float]:
    """(lag in samples, correlation) of the two signals' loudness curves (10 ms blocks,
    in dB): does the playback get loud and quiet when the test does?"""
    n = rate // 100

    def env(x):
        k = len(x) // n
        e = np.sqrt((x[: k * n].reshape(k, n) ** 2).mean(axis=1))
        return 20 * np.log10(np.maximum(e, 1e-5))
    es, eh = env(sent), env(heard)
    best, best_lag = -1.0, 0
    for lag in range(0, min(int(MAX_LAG_S * 100), len(eh) - len(es) // 2) + 1):
        a = es[: len(eh) - lag]
        b = eh[lag:lag + len(a)]
        if len(a) < 50 or a.std() < 1e-6 or b.std() < 1e-6:
            continue
        c = float(np.corrcoef(a, b)[0, 1])
        if c > best:
            best, best_lag = c, lag
    return best_lag * n, max(best, 0.0)


def _db(x: float) -> float:
    return float(20 * np.log10(max(x, 1e-9)))


def block_gains(sent: np.ndarray, heard: np.ndarray, rate: int) -> tuple[np.ndarray, np.ndarray]:
    """Per BLOCK_S block of the aligned signals: (gain heard/sent in dB by projection,
    correlation 0..1). Blocks where we sent (almost) nothing are NaN."""
    n = max(1, int(BLOCK_S * rate))
    k = min(len(sent), len(heard)) // n
    s = sent[: k * n].reshape(k, n)
    h = heard[: k * n].reshape(k, n)
    ss = (s * s).sum(axis=1)
    hh = (h * h).sum(axis=1)
    sh = (s * h).sum(axis=1)
    live = ss / n > 10 ** (-60 / 10)
    with np.errstate(divide="ignore", invalid="ignore"):
        g = np.where(live, 20 * np.log10(np.maximum(np.abs(sh) / np.maximum(ss, 1e-20), 1e-9)),
                     np.nan)
        rho = np.where(live, np.abs(sh) / np.sqrt(ss * hh + 1e-30), np.nan)
    return g, rho


def analyze(sent: np.ndarray, heard: np.ndarray, rate: int = SR) -> dict:
    """Compare the recorded send (the test signal as it went into the cable) with
    what Discord played back. `sent` should start where the test signal starts."""
    s, h = _mono(sent), _mono(heard)
    res = {"issues": [], "lag_s": None, "match": 0.0, "steady_drop_db": None,
           "quiet_db": None, "pump_db": None, "fidelity": None}
    if len(s) < rate or len(h) < rate or _db(float(np.sqrt((h ** 2).mean()))) < -70:
        res["issues"] = ["not_heard"]
        return res
    lag, match = _align(s, h, rate)
    res["lag_s"], res["match"] = lag / rate, match
    if match < 0.08:
        # nothing that looks like our waveform. If the playback's loudness still
        # follows the test (loud, quiet, drums) it was ours, garbled beyond
        # recognition: a neural denoiser does that to music
        elag, ecorr = _envelope_match(s, h, rate)
        res["envelope_match"] = ecorr
        if ecorr > 0.6:
            res["lag_s"], res["fidelity"] = elag / rate, match
            res["issues"] = ["suppression"]
        else:
            res["issues"] = ["not_heard"]
        return res
    h = h[lag:]
    g, rho = block_gains(s, h, rate)

    def part(p, skip=0.0, until=None):
        a = int((p[0] + skip) / BLOCK_S)
        b = int((until if until is not None else p[1]) / BLOCK_S)
        return slice(a, min(b, len(g)))

    ref = np.nanmedian(g[part(PART_STEADY, 0.1, 0.6)])        # the start: nothing adapted yet
    steady_end = np.nanmedian(g[part(PART_STEADY, 1.6)])
    quiet = np.nanmedian(g[part(PART_QUIET, 0.3)])
    drums_start = np.nanmedian(g[part(PART_DRUMS, 0.05, PART_DRUMS[0] + 0.4)])
    drums_end = np.nanmedian(g[part(PART_DRUMS, 1.2)])
    fid = np.nanmedian(np.concatenate([rho[part(PART_STEADY, 0.1)], rho[part(PART_DRUMS, 0.1)]]))
    if not np.isfinite(ref):
        res["issues"] = ["not_heard"]
        return res
    res["fidelity"] = float(fid)
    res["steady_drop_db"] = float(steady_end - ref) if np.isfinite(steady_end) else -60.0
    res["quiet_db"] = float(quiet - ref) if np.isfinite(quiet) else -60.0
    res["pump_db"] = (float(drums_start - drums_end)
                      if np.isfinite(drums_start) and np.isfinite(drums_end) else 0.0)
    issues = []
    # noise suppression: steady music fades away, or what comes back no longer
    # looks like what we sent (spectral subtraction / a neural denoiser)
    suppressed = res["steady_drop_db"] < -6.0 or fid < 0.7
    if suppressed:
        issues.append("suppression")
    # a gate: the quiet part is gone. Suppression also pulls it down (it's steady
    # music too), so with suppression on only a real cut counts
    if res["quiet_db"] < -35.0 or (res["quiet_db"] < -12.0 and not suppressed):
        issues.append("gate")
    # a gain control: the quiet part comes back lifted, or after it the loud part
    # starts too loud and settles (which suppression re-adapting also looks like)
    if res["quiet_db"] > 4.0 or (res["pump_db"] > 3.0 and not suppressed):
        issues.append("agc")
    res["issues"] = issues
    return res


__all__ = ["ISSUES", "LENGTH_S", "SR", "analyze", "block_gains", "test_signal"]
