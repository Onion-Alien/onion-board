"""Sound library: decoding, loudness analysis and persistent config."""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr

from engine import SR

log = logging.getLogger(__name__)

APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "Soundboard"
SOUNDS_DIR = APP_DIR / "sounds"
CONFIG_PATH = APP_DIR / "config.json"

AUDIO_EXTS = {".wav", ".mp3", ".ogg", ".flac", ".opus", ".m4a", ".aac", ".wma",
              ".aiff", ".aif", ".webm", ".mp4", ".mkv", ".mov"}
MAX_SECONDS = 15 * 60
TARGET_RMS_DB = -17.0  # loudness everything is levelled to when "Level volumes" is on

PAD_COLORS = ["#7c5cff", "#ff5c8a", "#1fb6ff", "#13ce66", "#ffb020", "#ff7849",
              "#00c2b2", "#e056fd", "#5c7cfa", "#94a3b8"]


@dataclass
class SoundMeta:
    id: str
    name: str
    file: str                 # absolute path (usually inside SOUNDS_DIR)
    volume: float = 1.0       # 0..2 user gain
    hotkey: str = ""
    mode: str = "restart"     # restart | overlap | toggle
    loop: bool = False
    color: str = PAD_COLORS[0]
    level_gain: float = 1.0   # computed loudness-levelling gain
    duration: float = 0.0


@dataclass
class Config:
    main_device: str | None = None
    mon_device: str | None = None
    mic_device: str | None = None
    sound_vol: float = 1.0
    mic_vol: float = 1.0
    mon_vol: float = 0.7
    mic_enabled: bool = True
    monitor_sounds: bool = True
    level_volumes: bool = True
    stop_hotkey: str = "ctrl+alt+s"
    pause_hotkey: str = ""
    rec_hotkey: str = "ctrl+alt+r"    # browser: start / stop recording a clip
    clip_hotkey: str = "ctrl+alt+c"   # browser: save the last 15 s
    bplay_hotkey: str = "ctrl+alt+p"  # browser: play / pause
    live_hotkey: str = "ctrl+alt+l"   # browser: LIVE on / off
    cue_sounds: bool = True           # beep in the headphones when a hotkey records / saves
    theme: str = "Dark"
    eq_enabled: bool = False
    eq_target: str = "voice"          # voice | sounds | all
    eq_preset: str = "Flat (off)"
    eq_gains: list[float] = field(default_factory=lambda: [0.0] * 7)
    ptt_key: str = ""           # key held down while sounds play (game push-to-talk)
    always_on_top: bool = False
    show_advanced: bool = False
    pad_width: int = 150
    tab: int = 0                      # 0 = sounds, 1 = browser
    browser_url: str = "https://www.youtube.com/"
    browser_vol: float = 1.0
    browser_live: bool = True         # browser audio goes out to others
    browser_monitor: bool = True      # ...and to your headphones
    browser_lite: bool = True         # hide the page while it plays + 144p (light on CPU/GPU)
    latency: str = "low"              # audio buffering: 'low' | 'high' (safer on flaky devices)
    sounds: list[SoundMeta] = field(default_factory=list)

    @classmethod
    def load(cls) -> Config:
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError):
            log.exception("config %s is unreadable; starting with defaults", CONFIG_PATH)
            return cls()
        sounds = [SoundMeta(**{k: v for k, v in s.items() if k in SoundMeta.__dataclass_fields__})
                  for s in raw.pop("sounds", [])]
        known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        return cls(**known, sounds=sounds)

    def save(self):
        APP_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        tmp.replace(CONFIG_PATH)


# --------------------------------------------------------------------------- decoding

def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def decode(path: str) -> np.ndarray:
    """Decode any audio file to (n, 2) float32 at SR with high-quality resampling."""
    data = sr = None
    try:
        data, sr = sf.read(path, dtype="float32", always_2d=True)
    except Exception as e:  # noqa: BLE001 - fall back to ffmpeg for m4a/aac/video etc.
        log.debug("libsndfile can't read %s (%s); trying ffmpeg", path, e)
        ff = _ffmpeg()
        if not ff:
            raise RuntimeError("Can't decode this format (install ffmpeg for m4a/aac/video)") from e
        p = subprocess.run([ff, "-v", "error", "-i", path, "-vn", "-f", "f32le", "-ac", "2",
                            "-ar", str(SR), "-"], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if p.returncode != 0 or not p.stdout:
            msg = p.stderr.decode(errors="ignore").strip() or "ffmpeg failed"
            raise RuntimeError(msg) from None
        data = np.frombuffer(p.stdout, np.float32).reshape(-1, 2).copy()
        sr = SR
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    elif data.shape[1] > 2:
        data = data[:, :2]
    data = data[: int(MAX_SECONDS * sr)]
    if sr != SR:
        data = soxr.resample(data, sr, SR, quality="VHQ").astype(np.float32)
    return np.ascontiguousarray(data, dtype=np.float32)


def level_gain(data: np.ndarray) -> float:
    """Gain that brings the sound to TARGET_RMS_DB without letting peaks exceed ~-0.5 dBFS."""
    if not len(data):
        return 1.0
    mono = data.mean(axis=1)
    # RMS over the loud part only, so silence padding doesn't skew it
    win = 2400
    n = len(mono) // win
    if n >= 1:
        blocks = mono[: n * win].reshape(n, win)
        rms = np.sqrt((blocks ** 2).mean(axis=1))
        rms = rms[rms > rms.max() * 0.1] if rms.max() > 0 else rms
        r = float(np.sqrt((rms ** 2).mean())) if len(rms) else 0.0
    else:
        r = float(np.sqrt((mono ** 2).mean()))
    if r <= 1e-6:
        return 1.0
    g = 10 ** ((TARGET_RMS_DB - 20 * np.log10(r)) / 20)
    pk = float(np.max(np.abs(data)))
    if pk > 0:
        g = min(g, 0.95 / pk * 1.4)  # allow a little limiter work, not a lot
    return float(np.clip(g, 0.1, 6.0))


def import_file(src: str, color: str) -> tuple[SoundMeta, np.ndarray]:
    """Decode, copy into the library folder, and return metadata + audio."""
    data = decode(src)
    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    sid = uuid.uuid4().hex[:10]
    srcp = Path(src)
    dest = SOUNDS_DIR / f"{sid}_{srcp.name}"
    try:
        shutil.copy2(srcp, dest)
    except OSError:
        log.warning("couldn't copy %s into the library; using it in place", src, exc_info=True)
        dest = srcp
    meta = SoundMeta(id=sid, name=srcp.stem.replace("_", " ").strip()[:40], file=str(dest),
                     color=color, level_gain=level_gain(data), duration=len(data) / SR)
    return meta, data


def save_clip(data: np.ndarray, name: str, color: str) -> SoundMeta:
    """Store recorded audio ((n, 2) float32 at SR) in the library as a WAV; return its metadata."""
    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    sid = uuid.uuid4().hex[:10]
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip()[:40] or "clip"
    dest = SOUNDS_DIR / f"{sid}_{safe}.wav"
    sf.write(dest, data, SR, subtype="FLOAT")
    return SoundMeta(id=sid, name=name[:40], file=str(dest), color=color,
                     level_gain=level_gain(data), duration=len(data) / SR)


def trim_silence(data: np.ndarray, threshold: float = 0.002, pad_s: float = 0.05) -> np.ndarray:
    """Cut dead air off both ends of a recording (keeps a tiny pad so it doesn't start abruptly)."""
    loud = np.flatnonzero(np.max(np.abs(data), axis=1) > threshold)
    if not len(loud):
        return data[:0]
    pad = int(pad_s * SR)
    return data[max(loud[0] - pad, 0): loud[-1] + pad]


def delete_file(meta: SoundMeta):
    p = Path(meta.file)
    try:
        if p.parent == SOUNDS_DIR:
            p.unlink(missing_ok=True)
    except OSError:
        log.warning("couldn't delete %s", p, exc_info=True)
