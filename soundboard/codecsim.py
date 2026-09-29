"""Codec round-trip bench: what does Discord / a game do to what we send?

Everything the engine puts into the virtual cable goes through the listener's
voice pipeline: mono downmix, a resample to the codec's rate, Opus at a modest
bitrate, back to 48 kHz on the other side. This module reproduces that path
offline (libopus through ffmpeg, the same ffmpeg the importer uses) so a change
to the engine can be judged in numbers instead of by ear.

    back = roundtrip(x, PROFILES["discord"])
    analyze(x, back)  ->  level / bandwidth / per-band loss / waveform SNR

Nothing here runs in the app; it's a development tool (scripts/codec_bench.py
and tests/test_codecsim.py). Profiles are what the public record says each
service uses; where a number is an estimate the profile says so.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

import numpy as np
import soxr
from scipy.signal import butter, sosfilt

from soundboard.library import FFMPEG_TIMEOUT, _ffmpeg

SR = 48000
F32 = np.float32


@dataclass(frozen=True)
class Profile:
    key: str
    label: str
    rate: int              # sample rate the encoder is fed (sets Opus' bandwidth ceiling)
    channels: int          # 1 = the app captures its mic in mono (all of them do by default)
    bitrate_kbps: int
    application: str = "voip"   # libopus mode: voip favours speech, audio favours fidelity
    frame_ms: int = 20
    highpass_hz: int = 0   # the app's capture high-pass before the encoder (0 = none)
    highpass_order: int = 13
    note: str = ""

    @property
    def ceiling_hz(self) -> int:
        return self.rate // 2


# Discord's capture high-pass, measured in a real call (a 60 Hz-18 kHz sweep sent
# through the desktop app on the Studio input profile, received by a second client):
# -33 dB at 70 Hz, -19 at 80, -6 at 90, flat from 100 Hz up. A 13th-order Butterworth
# at 94 Hz matches that within 1 dB. It isn't one of the switchable voice filters:
# Studio (no noise suppression, echo cancellation or auto gain) still has it.
DISCORD_HP = 94

PROFILES: dict[str, Profile] = {p.key: p for p in (
    Profile("discord", "Discord voice, default", 48000, 1, 64, highpass_hz=DISCORD_HP,
            note="64 kbps mono Opus is the default voice-channel bitrate"),
    Profile("discord_low", "Discord voice, weak connection", 48000, 1, 24,
            highpass_hz=DISCORD_HP,
            note="Discord adapts down under packet loss; 24 kbps is mid-range of 8-128"),
    Profile("discord_128", "Discord voice, boosted 128 kbps", 48000, 1, 128,
            highpass_hz=DISCORD_HP,
            note="a boosted server's higher bitrate; still mono unless stereo is enabled"),
    Profile("steam", "Steam voice (CS2 etc.)", 24000, 1, 32,
            note="Opus PLC fed 24 kHz mono: nothing above 12 kHz survives; bitrate is an estimate"),
    Profile("vivox", "Vivox in-game voice (Unity / Unreal)", 48000, 1, 32,
            note="Opus at Vivox's documented 32 kbps default"),
    Profile("vivox_siren7", "Vivox Siren 7 (16 kHz)", 16000, 1, 32,
            note="games on Vivox's low-CPU codec; 8 kHz ceiling, modelled with Opus at 16 kHz"),
)}

# analysis bands (Hz): roughly where a voice, a bass hit, presence and 'air' live
BANDS = [(0, 100), (100, 300), (300, 1000), (1000, 3000), (3000, 6000),
         (6000, 10000), (10000, 14000), (14000, 20000)]
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def available() -> str | None:
    """Path of an ffmpeg that has libopus, or None (the bench can't run)."""
    ff = _ffmpeg()
    if not ff:
        return None
    try:
        p = subprocess.run([ff, "-hide_banner", "-encoders"], capture_output=True,
                           timeout=30, creationflags=_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return ff if b"libopus" in p.stdout else None


def _run(cmd: list[str], data: bytes) -> bytes:
    p = subprocess.run(cmd, input=data, capture_output=True, timeout=FFMPEG_TIMEOUT,
                       creationflags=_NO_WINDOW)
    if p.returncode != 0 or not p.stdout:
        raise RuntimeError(p.stderr.decode(errors="ignore").strip() or "ffmpeg failed")
    return p.stdout


def downmix(x: np.ndarray) -> np.ndarray:
    """What a mono mic capture gets: the average of both channels, as (n, 1)."""
    x = np.asarray(x, F32)
    if x.ndim == 1:
        return x[:, None]
    return x.mean(axis=1, keepdims=True).astype(F32)


def highpass(x: np.ndarray, hz: float, order: int = 13) -> np.ndarray:
    """Butterworth high-pass along axis 0 (a chat app's capture filter)."""
    sos = butter(order, hz, "highpass", fs=SR, output="sos")
    return sosfilt(sos, np.asarray(x, F32), axis=0).astype(F32)


def roundtrip(x: np.ndarray, profile: Profile, ffmpeg: str | None = None) -> np.ndarray:
    """Send x ((n, 2) float32 at 48 kHz, the engine's main bus) through the profile's
    pipeline and return what the listener gets, as (n', 2) float32 at 48 kHz.
    n' differs from n by the codec's delay; analyze() lines them up."""
    ff = ffmpeg or available()
    if not ff:
        raise RuntimeError("ffmpeg with libopus is needed for the codec bench")
    x = np.asarray(x, F32)
    if x.ndim == 1:
        x = np.repeat(x[:, None], 2, axis=1)
    src = downmix(x) if profile.channels == 1 else x
    if profile.highpass_hz:
        src = highpass(src, profile.highpass_hz, profile.highpass_order)
    if profile.rate != SR:
        src = soxr.resample(src, SR, profile.rate, quality="VHQ").astype(F32)
    ch = src.shape[1]
    raw = np.ascontiguousarray(src).tobytes()
    ogg = _run([ff, "-v", "error", "-f", "f32le", "-ar", str(profile.rate), "-ac", str(ch),
                "-i", "pipe:0", "-c:a", "libopus", "-b:a", f"{profile.bitrate_kbps}k",
                "-application", profile.application, "-frame_duration", str(profile.frame_ms),
                "-vbr", "on", "-f", "ogg", "pipe:1"], raw)
    pcm = _run([ff, "-v", "error", "-i", "pipe:0", "-f", "f32le", "-ar", str(SR),
                "-ac", str(ch), "pipe:1"], ogg)
    out = np.frombuffer(pcm, F32).reshape(-1, ch)
    if ch == 1:
        out = np.repeat(out, 2, axis=1)
    return np.ascontiguousarray(out, dtype=F32)


# --------------------------------------------------------------------------- analysis

def _db(r: float) -> float:
    return float(20 * np.log10(max(r, 1e-9)))


def _mono(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, np.float64)
    return x.mean(axis=1) if x.ndim == 2 else x


def align(orig: np.ndarray, back: np.ndarray, max_lag_s: float = 0.25,
          rate: int = SR) -> tuple[np.ndarray, np.ndarray, int]:
    """Line `back` up with `orig` by cross-correlation (a codec adds delay) and
    return both mono float64 at the same length, plus the lag in samples."""
    o, b = _mono(orig), _mono(back)
    n = 1 << int(np.ceil(np.log2(len(o) + len(b))))
    xc = np.fft.irfft(np.fft.rfft(b, n) * np.conj(np.fft.rfft(o, n)), n)
    m = int(max_lag_s * rate)
    cand = np.concatenate([xc[:m], xc[-m:]])          # lags 0..m and -m..-1
    i = int(np.abs(cand).argmax())
    lag = i if i < m else i - 2 * m                    # back leads (<0) or trails (>0) orig
    if lag > 0:
        b = b[lag:]
    elif lag < 0:
        o = o[-lag:]
    k = min(len(o), len(b))
    return o[:k], b[:k], lag


def _band_power(spec: np.ndarray, freqs: np.ndarray, lo: float, hi: float) -> float:
    m = (freqs >= lo) & (freqs < hi)
    return float((spec[m] ** 2).sum()) if m.any() else 0.0


def _spectra(o: np.ndarray, b: np.ndarray, rate: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Magnitude spectra of both signals over a Hann window (without it a pure tone
    leaks into every bin at -40..-60 dB and reads as 'input energy' up there)."""
    w = np.hanning(len(o))
    return np.abs(np.fft.rfft(o * w)), np.abs(np.fft.rfft(b * w)), np.fft.rfftfreq(len(o), 1 / rate)


def bandwidth_hz(o: np.ndarray, b: np.ndarray, rate: int = SR, drop_db: float = 10.0,
                 bin_hz: float = 250.0) -> float:
    """Highest frequency the codec still carries: the top of the last `bin_hz` bin
    where the output is within `drop_db` of the input, counting only bins where the
    input itself has energy (within 50 dB of its loudest bin)."""
    fo, fb, freqs = _spectra(o, b, rate)
    edges = np.arange(0, rate / 2 + bin_hz, bin_hz)
    po = np.array([_band_power(fo, freqs, lo, hi) for lo, hi in zip(edges[:-1], edges[1:])])
    pb = np.array([_band_power(fb, freqs, lo, hi) for lo, hi in zip(edges[:-1], edges[1:])])
    if po.max() <= 0:
        return 0.0
    floor = po.max() * 1e-5                         # -50 dB
    keep = 0.0
    for i in range(len(po)):
        if po[i] <= floor:
            continue
        if 10 * np.log10(pb[i] / po[i] + 1e-30) >= -drop_db:
            keep = float(edges[i + 1])
    return keep


def spectral_distance_db(o: np.ndarray, b: np.ndarray, rate: int = SR,
                         top_hz: float = 16000.0) -> float:
    """How different the two sound, frame by frame: the mean absolute difference (dB)
    of their third-octave band levels from 100 Hz to top_hz, over 20 ms frames where
    the input is active, after matching overall level. Band energy per whole clip
    (the `bands` numbers) can't see a codec's noise fill or warble, which keeps the
    energy but not the detail; this does. 0 = identical; lower is better."""
    n = int(0.02 * rate)
    k = min(len(o), len(b)) // n
    if k < 2:
        return 0.0
    win = np.hanning(n)
    fo = np.abs(np.fft.rfft(o[: k * n].reshape(k, n) * win, axis=1)) ** 2
    fb = np.abs(np.fft.rfft(b[: k * n].reshape(k, n) * win, axis=1)) ** 2
    freqs = np.fft.rfftfreq(n, 1 / rate)
    edges = 100.0 * 2 ** (np.arange(0, 40) / 3)
    edges = edges[edges <= min(top_hz, rate / 2)]
    idx = [(freqs >= lo) & (freqs < hi) for lo, hi in zip(edges[:-1], edges[1:])]
    idx = [m for m in idx if m.any()]
    po = np.stack([fo[:, m].sum(axis=1) for m in idx], 1)
    pb = np.stack([fb[:, m].sum(axis=1) for m in idx], 1)
    lo_db, lb_db = 10 * np.log10(po + 1e-12), 10 * np.log10(pb + 1e-12)
    lb_db += np.median(lo_db - lb_db)                 # level-matched
    active = lo_db.max(axis=1) > lo_db.max() - 50     # frames with something in them
    loud = lo_db > lo_db.max() - 60                   # bands with something in them
    m = active[:, None] & loud
    if not m.any():
        return 0.0
    return float(np.mean(np.minimum(np.abs(lo_db - lb_db)[m], 30.0)))


def analyze(orig: np.ndarray, back: np.ndarray, rate: int = SR) -> dict:
    """Compare what went in with what came back.

    level_db      overall RMS change (negative = quieter)
    bandwidth_hz  where the codec's ceiling really is for this signal
    bands         [(lo, hi, delta_db)] energy change per BANDS band (None = no input there)
    snr_db        waveform SNR after alignment. Opus isn't a waveform coder above a few
                  kHz, so this is low even when it sounds fine; compare between runs,
                  don't read it as quality on its own
    lag           codec delay in samples (how far back trailed orig)
    spec_dist_db  frame-by-frame spectral distance (spectral_distance_db): how
                  different it sounds, noise fill and warble included; lower = better
    """
    o, b, lag = align(orig, back, rate=rate)
    if not len(o):
        return {"level_db": -180.0, "bandwidth_hz": 0.0, "bands": [], "snr_db": 0.0, "lag": lag,
                "spec_dist_db": 30.0}
    ro, rb = float(np.sqrt((o ** 2).mean())), float(np.sqrt((b ** 2).mean()))
    fo, fb, freqs = _spectra(o, b, rate)
    top = float((fo ** 2).sum()) * 1e-7             # a band with less than this has no input
    bands = []
    for lo, hi in BANDS:
        po, pb = _band_power(fo, freqs, lo, hi), _band_power(fb, freqs, lo, hi)
        bands.append((lo, hi, None if po <= top else float(10 * np.log10(pb / po + 1e-30))))
    g = float((o * b).sum() / ((o ** 2).sum() + 1e-30))   # best gain match before SNR
    err = b - g * o
    snr = float(10 * np.log10((o ** 2).sum() * g * g / ((err ** 2).sum() + 1e-30)))
    return {"level_db": _db(rb / max(ro, 1e-9)), "bandwidth_hz": bandwidth_hz(o, b, rate),
            "bands": bands, "snr_db": snr, "lag": lag,
            "spec_dist_db": spectral_distance_db(o, b, rate)}


def mono_loss_db(x: np.ndarray) -> float:
    """How much a stereo signal loses when a mono mic capture averages its channels.
    0 dB for identical channels, about -3 dB for unrelated ones, far below that when
    they cancel (a wide chorus, an out-of-phase pitch shifter)."""
    x = np.asarray(x, np.float64)
    if x.ndim == 1 or x.shape[1] == 1:
        return 0.0
    stereo = float(np.sqrt((x ** 2).mean()))          # power averaged over both channels
    mono = float(np.sqrt((x.mean(axis=1) ** 2).mean()))
    return max(_db(mono / max(stereo, 1e-9)), -60.0)


# --------------------------------------------------------------------------- test signals

def multitone(seconds: float = 3.0, rate: int = SR, level: float = 0.1) -> np.ndarray:
    """One sine in the middle of every analysis band: per-band loss reads off directly."""
    t = np.arange(int(seconds * rate)) / rate
    x = np.zeros_like(t)
    for lo, hi in BANDS:
        f = np.sqrt(max(lo, 40) * hi)                 # geometric centre
        x += np.sin(2 * np.pi * f * t)
    x *= level / np.abs(x).max()
    return np.repeat(x[:, None].astype(F32), 2, axis=1)


def pink_noise(seconds: float = 3.0, rate: int = SR, level: float = 0.1,
               seed: int = 0) -> np.ndarray:
    """Equal energy per octave: a stand-in for music / a busy sound effect."""
    n = int(seconds * rate)
    rng = np.random.default_rng(seed)
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / rate)
    spec[1:] /= np.sqrt(f[1:])
    spec[0] = 0
    x = np.fft.irfft(spec, n)
    x *= level / np.abs(x).max()
    return np.repeat(x[:, None].astype(F32), 2, axis=1)


def speech_like(seconds: float = 3.0, rate: int = SR, level: float = 0.2,
                seed: int = 1) -> np.ndarray:
    """Bursts of a buzzy 120 Hz tone through a moving band: a codec in voip mode
    treats this the way it treats a voice (the thing it's built to keep)."""
    n = int(seconds * rate)
    t = np.arange(n) / rate
    rng = np.random.default_rng(seed)
    src = np.sign(np.sin(2 * np.pi * 120 * t)) * 0.5 + rng.standard_normal(n) * 0.05
    # formant-ish: slow random centre between 400 and 2500 Hz, 1 kHz wide
    steps = int(seconds * 8) + 1
    centre = np.interp(t, np.linspace(0, seconds, steps), rng.uniform(400, 2500, steps))
    spec = np.fft.rfft(src)
    f = np.fft.rfftfreq(n, 1 / rate)
    # apply an average band-pass (a proper time-varying one isn't needed for a bench)
    c = float(centre.mean())
    spec *= np.exp(-((f - c) / 1000.0) ** 2) + 0.05
    x = np.fft.irfft(spec, n)
    env = ((np.sin(2 * np.pi * 2.5 * t) > 0) * 1.0)   # 200 ms on / 200 ms off
    x *= env
    x *= level / max(np.abs(x).max(), 1e-9)
    return np.repeat(x[:, None].astype(F32), 2, axis=1)


SIGNALS = {"multitone": multitone, "pink noise": pink_noise, "speech-like": speech_like}


def band_label(lo: int, hi: int) -> str:
    def hz(v):
        return f"{v // 1000}k" if v >= 1000 else str(v)
    return f"<{hz(hi)}" if lo == 0 else f"{hz(lo)}-{hz(hi)}"
