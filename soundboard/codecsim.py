"""Codec round-trip bench: what does Discord / a game do to what we send?

Everything the engine sends to others goes through the listener's
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

from soundboard.dsp import butter, sosfilt
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
    highpass_tail_hz: int = 0   # a gentle 2nd-order high-pass after the steep one (0 = none)
    note: str = ""
    cbr: bool = False      # constant bitrate (Mumble, FiveM) instead of Opus' default VBR
    # the mic cleanup the chat runs with its defaults (codec_bench --defaults): stage
    # names from soundboard.realproc (the real libraries) or soundboard.chatsim (models)
    cleanup: tuple[str, ...] = ()
    gate_db: float | None = None   # voice activation threshold (10 ms RMS), None = push-to-talk
    gate_hang_s: float = 0.2
    proximity: str = ""    # listener side: a soundboard.proxsim "model[:variant]" ("" = none)
    games: str = ""        # what uses it
    confidence: str = "measured"   # measured / sourced / estimate

    @property
    def ceiling_hz(self) -> int:
        return self.rate // 2


# Discord's capture high-pass, measured in a real call (a 60 Hz-18 kHz sweep sent
# through the desktop app on the Studio input profile, received by a second client):
# -33 dB at 70 Hz, -19 at 80, -6 at 90, flat from 100 Hz up. A 13th-order Butterworth
# at 94 Hz matches that within 1 dB. It isn't one of the switchable voice filters:
# Studio (no noise suppression, echo cancellation or auto gain) still has it.
DISCORD_HP = 94

# Vivox's capture high-pass, measured in a real Valorant party (a sweep sent through
# Valorant with push-to-talk held, recorded on a second PC): -19..-25 dB at 70 Hz,
# -7..-12 at 80, -4..-5 at 90, -2..-3 at 100. A bass-heavy song through the same party
# shows a slow tail on top: -5 dB at 80-100 Hz, -3 at 100-120, -1.3 at 120-200. A
# 12th-order Butterworth at 80 Hz followed by a 2nd-order one at 104 Hz fits both (the
# song's bands within 0.5 dB, the sweep points within 1 dB); one steep filter can't
# make the tail.
VIVOX_HP = 80
VIVOX_HP_TAIL = 104

# Game voice stacks. Where a value comes from the stack's source code or SDK docs the
# profile says "sourced"; "estimate" means nothing public pins it down (the bench
# still runs it, read those rows as a best guess). Speex's AGC and noise suppressor
# (Mumble, Dissonance) have no packaged build, so those profiles stand in WebRTC's.
# Gate thresholds are converted from each stack's own scale to 10 ms RMS dBFS.
WEBRTC_CLEANUP = ("webrtc_hpf", "webrtc_ns", "webrtc_agc")

PROFILES: dict[str, Profile] = {p.key: p for p in (
    Profile("discord", "Discord voice, default", 48000, 1, 64, highpass_hz=DISCORD_HP,
            note="64 kbps mono Opus is the default voice-channel bitrate",
            games="Discord"),
    Profile("discord_low", "Discord voice, weak connection", 48000, 1, 24,
            highpass_hz=DISCORD_HP,
            note="Discord adapts down under packet loss; 24 kbps is mid-range of 8-128",
            games="Discord"),
    Profile("discord_128", "Discord voice, boosted 128 kbps", 48000, 1, 128,
            highpass_hz=DISCORD_HP,
            note="a boosted server's higher bitrate; still mono unless stereo is enabled",
            games="Discord"),
    Profile("steam", "Steam voice (CS2 etc.)", 24000, 1, 32,
            note="Opus PLC fed 24 kHz mono: nothing above 12 kHz survives; bitrate is an estimate",
            games="CS2, Dota 2, TF2, Deep Rock Galactic, Unreal games on Steam's voice",
            confidence="sourced"),
    Profile("steam_rust", "Steam voice in 3D (Rust)", 24000, 1, 32, proximity="unity_3d",
            note="Steam's codec, heard through a Unity 3D sound: fades with distance",
            games="Rust", confidence="estimate"),
    Profile("vivox", "Vivox in-game voice (Unity / Unreal)", 48000, 1, 32,
            highpass_hz=VIVOX_HP, highpass_order=12, highpass_tail_hz=VIVOX_HP_TAIL,
            note="measured in a real Valorant party with push-to-talk held: ~87 Hz "
                 "high-pass, full band, no noise suppression or AGC. On voice "
                 "activation only speech is sent. Bitrate is Vivox's 32 kbps default",
            games="Valorant, League of Legends, Rainbow Six Siege, Overwatch 2"),
    Profile("vivox_3d", "Vivox positional channel", 48000, 1, 32,
            cleanup=("webrtc_ns", "webrtc_agc"), gate_db=-45, gate_hang_s=2.0,
            proximity="vivox_3d",
            note="as vivox, 6 dB down, inverse-distance fade from 1 m to silence at 32 m",
            games="games with Vivox proximity chat", confidence="sourced"),
    Profile("vivox_siren14", "Vivox Siren 14 (32 kHz)", 32000, 1, 32,
            note="Vivox's mid codec: 16 kHz ceiling, modelled with Opus at 32 kHz",
            games="older Vivox titles", confidence="sourced"),
    Profile("vivox_siren7", "Vivox Siren 7 (16 kHz)", 16000, 1, 32,
            note="games on Vivox's low-CPU codec; 8 kHz ceiling, modelled with Opus at 16 kHz",
            games="older Vivox titles, consoles", confidence="sourced"),
    Profile("eos", "Epic Online Services voice", 48000, 1, 32, frame_ms=20,
            cleanup=WEBRTC_CLEANUP,
            note="Fortnite's voice since it left Vivox; nothing public on its settings",
            games="Fortnite, EOS games", confidence="estimate"),
    Profile("ue_voip", "Unreal Engine built-in voice", 16000, 1, 20, gate_db=-26,
            note="16 kHz by default (8 kHz ceiling); voice.MicNoiseGateThreshold 0.08",
            games="Unreal games not on Steam / EOS / Vivox voice", confidence="estimate"),
    Profile("photon", "Photon Voice", 24000, 1, 30, gate_db=-43, gate_hang_s=0.5,
            proximity="phasmo",
            note="Photon's defaults: Opus 24 kHz, 30 kbps, 20 ms; gate 0.01 with 500 ms "
                 "release; proximity up to 20 m in Phasmophobia",
            games="Phasmophobia, Photon Unity games", confidence="sourced"),
    Profile("dissonance", "Dissonance (Lethal Company)", 48000, 1, 17, frame_ms=40,
            cleanup=("webrtc_ns", "webrtc_agc"), gate_db=-45, gate_hang_s=0.3,
            proximity="lethal",
            note="Dissonance medium quality (~17 kbps), 40 ms frames, voice activation; "
                 "Speex AGC / noise removal (WebRTC's stand in)",
            games="Lethal Company, Dissonance Unity games", confidence="sourced"),
    Profile("mumble", "Mumble", 48000, 1, 40, application="audio", cbr=True,
            cleanup=("webrtc_ns", "agc"), gate_db=-24, gate_hang_s=0.2,
            note="Mumble's defaults: 40 kbps CBR in Opus' audio mode, Speex noise "
                 "suppression and AGC (stand-ins), amplitude voice activation",
            games="Mumble servers", confidence="sourced"),
    Profile("fivem", "FiveM (GTA RP) voice", 48000, 1, 48, application="audio", cbr=True,
            frame_ms=40, cleanup=WEBRTC_CLEANUP, proximity="pma_voice",
            note="FiveM's Mumble client: 48 kbps CBR audio mode, 40 ms, WebRTC high-pass, "
                 "noise suppression High and AGC; push-to-talk; pma-voice ranges 3/7/15 m",
            games="GTA V roleplay (FiveM)", confidence="sourced"),
    Profile("fivem_radio", "FiveM radio (pma-voice)", 48000, 1, 48, application="audio",
            cbr=True, frame_ms=40, cleanup=WEBRTC_CLEANUP, proximity="pma_voice:radio",
            note="as fivem, then pma-voice's radio: 389-3248 Hz band, ring modulation",
            games="GTA V roleplay radios", confidence="sourced"),
    Profile("svc", "Simple Voice Chat (Minecraft)", 48000, 1, 48,
            cleanup=("rnnoise", "agc"), proximity="svc",
            note="Opus voip 20 ms (bitrate left to Opus, ~48), RNNoise and AGC on, "
                 "push-to-talk; linear fade to silence at 48 blocks",
            games="Minecraft with Simple Voice Chat", confidence="sourced"),
    Profile("vrchat", "VRChat", 48000, 1, 30, cleanup=("rnnoise",), gate_db=-35,
            proximity="vrchat",
            note="RNNoise on, 5% activation threshold; +15 dB, fades 0-25 m with a "
                 "distance low-pass; bitrate is an estimate",
            games="VRChat", confidence="estimate"),
    Profile("webrtc", "Browser / WebRTC voice", 48000, 1, 32, cleanup=WEBRTC_CLEANUP,
            gate_db=-30, proximity="crewlink",
            note="getUserMedia's cleanup (high-pass, noise suppression, AGC), Opus ~32 kbps",
            games="Among Us (BetterCrewLink), Roblox, web games", confidence="sourced"),
    Profile("teamspeak", "TeamSpeak (Opus Voice)", 48000, 1, 29,
            cleanup=("webrtc_ns", "webrtc_agc"), gate_db=-40,
            note="Opus Voice quality 6 (28.7 kbps); background-noise removal and AGC on",
            games="TeamSpeak 3 / 5", confidence="estimate"),
    Profile("zoom", "Zoom meeting", 32000, 1, 40, cleanup=("rnnoise", "webrtc_agc"),
            note="32 kHz (16 kHz ceiling) unless Original sound is on; its own ML noise "
                 "suppression (RNNoise stands in) and gain control; no voice gate. "
                 "The bitrate is a guess",
            games="Zoom", confidence="estimate"),
    Profile("teams", "Microsoft Teams meeting", 32000, 1, 36, cleanup=("rnnoise", "webrtc_agc"),
            note="Satin, super-wideband at 32 kHz (16 kHz ceiling), 6-36 kbps, modelled "
                 "with Opus; ML noise suppression on Auto (RNNoise stands in) and gain "
                 "control; no voice gate",
            games="Microsoft Teams", confidence="estimate"),
    Profile("console_party", "Xbox / PlayStation party", 48000, 1, 32, cleanup=WEBRTC_CLEANUP,
            note="platform voice with its own noise suppression and AGC; nothing public",
            games="Xbox app / party chat, PlayStation party, Sea of Thieves",
            confidence="estimate"),
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


def highpass(x: np.ndarray, hz: float, order: int = 13, tail_hz: float = 0) -> np.ndarray:
    """Butterworth high-pass along axis 0 (a chat app's capture filter), optionally
    followed by a gentle 2nd-order one at tail_hz."""
    sos = butter(order, hz, "highpass", fs=SR)
    if tail_hz:
        sos = np.vstack([sos, butter(2, tail_hz, "highpass", fs=SR)])
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
        src = highpass(src, profile.highpass_hz, profile.highpass_order,
                       profile.highpass_tail_hz)
    if profile.rate != SR:
        src = soxr.resample(src, SR, profile.rate, quality="VHQ").astype(F32)
    ch = src.shape[1]
    raw = np.ascontiguousarray(src).tobytes()
    ogg = _run([ff, "-v", "error", "-f", "f32le", "-ar", str(profile.rate), "-ac", str(ch),
                "-i", "pipe:0", "-c:a", "libopus", "-b:a", f"{profile.bitrate_kbps}k",
                "-application", profile.application, "-frame_duration", str(profile.frame_ms),
                "-vbr", "off" if profile.cbr else "on", "-f", "ogg", "pipe:1"], raw)
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
