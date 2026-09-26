"""Sound library: decoding, loudness analysis, the decoded-audio cache and config.

Audio in memory is int16 stereo at SR ((n, 2), the engine scales it on the fly).
That is half the RAM of float32 and it round-trips losslessly through the cache
folder, so after the first run a sound loads by reading one file instead of
decoding and resampling it again.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr

from soundboard.engine import SR

log = logging.getLogger(__name__)

APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "Soundboard"
SOUNDS_DIR = APP_DIR / "sounds"
CACHE_DIR = APP_DIR / "cache"
CONFIG_PATH = APP_DIR / "config.json"
CONFIG_VERSION = 2
CONFIG_BACKUPS = 3   # config.json.1 … .3, rotated on every save that changes something
# where install-vbcable.ps1 and soundboard.ico live: the repo root, or the frozen
# app's _internal folder when built with PyInstaller
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))

AUDIO_EXTS = {".wav", ".mp3", ".ogg", ".flac", ".opus", ".m4a", ".aac", ".wma",
              ".aiff", ".aif", ".webm", ".mp4", ".mkv", ".mov"}
MAX_SECONDS = 15 * 60
FFMPEG_TIMEOUT = 120
TARGET_RMS_DB = -17.0  # loudness everything is levelled to when "Level volumes" is on
I16 = 32767.0

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
    fingerprint: str = ""     # of the source file, to notice a re-import of the same file
    fx: dict = field(default_factory=dict)   # speed, pitch, EQ, boost… (soundboard.soundfx)


@dataclass
class Config:
    version: int = CONFIG_VERSION
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
    overlay_hotkey: str = "`"         # in-game overlay (see ui.overlay)
    cue_sounds: bool = True           # beep in the headphones when a hotkey records / saves
    theme: str = "Dark"
    eq_enabled: bool = False
    eq_target: str = "voice"          # voice | sounds | all
    eq_preset: str = "Flat (off)"
    eq_gains: list[float] = field(default_factory=lambda: [0.0] * 7)
    ptt_key: str = ""           # key held down while sounds play (game push-to-talk)
    always_on_top: bool = False
    pad_width: int = 150
    tab: int = 0                      # 0 = sounds, 1 = browser, 2 = voice
    browser_url: str = "https://www.youtube.com/"
    browser_vol: float = 1.0
    browser_live: bool = True         # browser audio goes out to others
    browser_monitor: bool = True      # ...and to your headphones
    browser_lite: bool = True         # hide the page while it plays + 144p (light on CPU/GPU)
    # fetch newer yt-dlp versions from PyPI by itself: opt-in, since that's code the app
    # runs (named *_optin so configs saved while it defaulted to on start off again)
    ytdlp_auto_optin: bool = False
    latency: str = "low"              # audio buffering: 'low' | 'high' (safer on flaky devices)
    setup_done: bool = False          # the quick-setup guide has been completed
    voice_fx: dict = field(default_factory=dict)   # voice changer (see ui.voicepanel)
    speech: dict = field(default_factory=dict)     # text-to-speech / live voice settings
    overlay: dict = field(default_factory=dict)    # in-game overlay (ui.overlay.OverlaySettings)
    sounds: list[SoundMeta] = field(default_factory=list)

    @classmethod
    def load(cls) -> Config:
        """Read config.json. A corrupt file is set aside (config.json.broken-<time>)
        and the newest backup that parses is used instead; only if there is none
        do the defaults apply. The pad list is never silently thrown away."""
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError):
            log.exception("config %s is unreadable", CONFIG_PATH)
            raw = cls._recover()
            if raw is None:
                return cls()
        try:
            return cls.from_raw(raw)
        except (TypeError, ValueError, KeyError, AttributeError):
            log.exception("config %s has bad contents", CONFIG_PATH)
            raw = cls._recover()
            try:
                return cls.from_raw(raw) if raw is not None else cls()
            except (TypeError, ValueError, KeyError, AttributeError):
                return cls()

    @classmethod
    def _recover(cls) -> dict | None:
        try:
            broken = CONFIG_PATH.with_name(f"config.json.broken-{time.strftime('%Y%m%d-%H%M%S')}")
            CONFIG_PATH.replace(broken)
            log.warning("set the damaged config aside as %s", broken.name)
        except OSError:
            log.debug("couldn't set the damaged config aside", exc_info=True)
        for i in range(1, CONFIG_BACKUPS + 1):
            p = CONFIG_PATH.with_name(f"config.json.{i}")
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                log.warning("recovered settings from backup %s", p.name)
                return raw
            except (OSError, ValueError):
                continue
        return None

    @classmethod
    def from_raw(cls, raw: dict) -> Config:
        raw = dict(raw)
        version = int(raw.get("version", 1) or 1)
        for v in range(version, CONFIG_VERSION):
            raw = MIGRATIONS[v](raw)
        sounds = []
        for s in raw.pop("sounds", []):
            if not isinstance(s, dict) or not all(s.get(k) for k in ("id", "name", "file")):
                log.warning("skipped a damaged sound entry in the config: %r", s)
                continue
            s = {k: v for k, v in s.items() if k in SoundMeta.__dataclass_fields__}
            if not Path(s["file"]).is_absolute():
                s["file"] = str(SOUNDS_DIR / s["file"])   # stored relative to the library
            sounds.append(SoundMeta(**s))
        # configs from before the setup guide existed: whoever already picked an output
        # device has been set up by hand, so don't greet them with the guide
        raw.setdefault("setup_done", bool(raw.get("main_device")))
        known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        known["version"] = CONFIG_VERSION
        return cls(**known, sounds=sounds)

    def to_raw(self) -> dict:
        d = asdict(self)
        d["version"] = CONFIG_VERSION
        for s in d["sounds"]:   # files inside the library are stored by name only, so the
            p = Path(s["file"])  # whole %APPDATA%\Soundboard folder can move or be restored
            if p.is_absolute() and p.parent == SOUNDS_DIR:
                s["file"] = p.name
        return d

    def save(self) -> bool:
        """Write atomically, keeping the last CONFIG_BACKUPS good copies. Returns
        False (and logs) instead of raising: this runs from a timer on the UI thread."""
        try:
            APP_DIR.mkdir(parents=True, exist_ok=True)
            text = json.dumps(self.to_raw(), indent=2)
            try:
                if CONFIG_PATH.read_text(encoding="utf-8") == text:
                    return True   # nothing changed: don't churn the backups
            except OSError:
                pass
            tmp = CONFIG_PATH.with_suffix(".tmp")
            tmp.write_text(text, encoding="utf-8")
            if CONFIG_PATH.exists():
                _rotate_backups()
            tmp.replace(CONFIG_PATH)
            return True
        except OSError:
            log.exception("couldn't save settings to %s", CONFIG_PATH)
            return False


def _rotate_backups():
    """config.json -> .1, .1 -> .2, … (the oldest falls off)."""
    for i in range(CONFIG_BACKUPS, 0, -1):
        src = CONFIG_PATH if i == 1 else CONFIG_PATH.with_name(f"config.json.{i - 1}")
        dst = CONFIG_PATH.with_name(f"config.json.{i}")
        if src.exists():
            if i == 1:
                shutil.copy2(src, dst)   # keep config.json in place for the atomic replace
            else:
                src.replace(dst)


def _migrate_1_to_2(raw: dict) -> dict:
    """v1 had no version field and absolute sound paths; absolute paths still load
    (from_raw accepts both), and the next save writes them relative. Nothing else."""
    return raw


MIGRATIONS = {1: _migrate_1_to_2}


# --------------------------------------------------------------------------- decoding

def _ffmpeg() -> str | None:
    """ffmpeg on PATH, or where winget links it (the installer's M4A/video option uses
    winget, and a process started before that doesn't see the new PATH yet)."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    for env, sub in (("LOCALAPPDATA", "Microsoft/WinGet/Links"),   # per-user install
                     ("ProgramFiles", "WinGet/Links")):            # machine-wide install
        base = os.environ.get(env)
        if base and (Path(base) / sub / "ffmpeg.exe").is_file():
            return str(Path(base) / sub / "ffmpeg.exe")
    return None


def _decode(path: str) -> tuple[np.ndarray, bool]:
    """(audio as (n, 2) float32 at SR, decoded-by-ffmpeg?).

    Only the first MAX_SECONDS are ever read: libsndfile is asked for that many
    frames and ffmpeg is given -t, so a two-hour file costs the same as a
    fifteen-minute one."""
    via_ffmpeg = False
    try:
        with sf.SoundFile(path) as f:
            sr = f.samplerate
            data = f.read(frames=int(MAX_SECONDS * sr), dtype="float32", always_2d=True)
    except Exception as e:  # noqa: BLE001 - fall back to ffmpeg for m4a/aac/video etc.
        log.debug("libsndfile can't read %s (%s); trying ffmpeg", path, e)
        ff = _ffmpeg()
        if not ff:
            raise RuntimeError("Can't decode this format (install ffmpeg for m4a/aac/video)") from e
        try:
            p = subprocess.run([ff, "-v", "error", "-i", path, "-vn", "-t", str(MAX_SECONDS),
                                "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                               capture_output=True, timeout=FFMPEG_TIMEOUT,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"ffmpeg took longer than {FFMPEG_TIMEOUT}s") from None
        if p.returncode != 0 or not p.stdout:
            msg = p.stderr.decode(errors="ignore").strip() or "ffmpeg failed"
            raise RuntimeError(msg) from None
        data = np.frombuffer(p.stdout, np.float32).reshape(-1, 2).copy()
        sr = SR
        via_ffmpeg = True
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    elif data.shape[1] > 2:
        data = data[:, :2]
    if sr != SR:
        data = soxr.resample(data, sr, SR, quality="VHQ").astype(np.float32)
    return np.ascontiguousarray(data, dtype=np.float32), via_ffmpeg


def decode(path: str) -> np.ndarray:
    """Decode any audio file to (n, 2) float32 at SR with high-quality resampling."""
    return _decode(path)[0]


def to_int16(data: np.ndarray) -> np.ndarray:
    """float32 [-1, 1] -> int16 (the in-memory / cached format). int16 passes through."""
    if data.dtype == np.int16:
        return data
    return np.ascontiguousarray(np.clip(np.rint(data * I16), -I16 - 1, I16).astype(np.int16))


def to_float32(data: np.ndarray) -> np.ndarray:
    if data.dtype == np.float32:
        return data
    return data.astype(np.float32) * np.float32(1 / I16)


# --------------------------------------------------------------------------- decoded cache

def cache_path(sid: str, fx_key: str = "") -> Path:
    """<sid>.npy is the decoded original; <sid>.<fx_key>.npy the version with its
    effects baked in (the key changes whenever the effects do)."""
    return CACHE_DIR / (f"{sid}.{fx_key}.npy" if fx_key else f"{sid}.npy")


def load_cached(sid: str, fx_key: str = "") -> np.ndarray | None:
    """The cached int16 audio for a sound, or None if there is none (or it's damaged)."""
    p = cache_path(sid, fx_key)
    if not p.exists():
        return None
    try:
        data = np.load(p)
        if data.dtype == np.int16 and data.ndim == 2 and data.shape[1] == 2:
            return data
        log.warning("cache %s has the wrong shape/dtype; ignoring it", p.name)
    except Exception:  # noqa: BLE001
        log.warning("cache %s is unreadable; ignoring it", p.name, exc_info=True)
    return None


def store_cached(sid: str, data: np.ndarray, fx_key: str = "") -> np.ndarray:
    """Write a sound's audio to the cache (atomically) and return it as int16."""
    i16 = to_int16(data)
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        dest = cache_path(sid, fx_key)
        tmp = dest.with_suffix(".tmp.npy")
        np.save(tmp, i16)
        tmp.replace(dest)
    except OSError:
        log.warning("couldn't write cache for %s", sid, exc_info=True)
    return i16


def load_original(meta: SoundMeta) -> np.ndarray:
    """int16 audio of the sound as imported (no effects): cache, else decode."""
    data = load_cached(meta.id)
    if data is None:
        data = store_cached(meta.id, decode(meta.file))
    return data


def load_sound(meta: SoundMeta) -> np.ndarray:
    """int16 audio for a library sound as it plays, effects included. The first
    load after its effects change renders them (slow for long sounds); after that
    it is one file read."""
    from soundboard import soundfx
    key = soundfx.key(meta.fx)
    if not key:
        return load_original(meta)
    data = load_cached(meta.id, key)
    if data is None:
        data = store_cached(meta.id, soundfx.render(load_original(meta), meta.fx), key)
    return data


def cache_keep(sounds: list[SoundMeta]) -> set[str]:
    """Cache file stems still in use: every original, and each sound's current effects."""
    from soundboard import soundfx
    keep = set()
    for m in sounds:
        keep.add(m.id)
        k = soundfx.key(m.fx)
        if k:
            keep.add(f"{m.id}.{k}")
    return keep


def prune_cache(keep: set[str]):
    """Delete cache files that aren't in `keep` (see cache_keep): removed sounds and
    effects versions that were replaced."""
    try:
        for p in CACHE_DIR.glob("*.npy"):
            if p.stem not in keep:
                p.unlink(missing_ok=True)
    except OSError:
        log.debug("cache prune failed", exc_info=True)


def fingerprint(path: str) -> str:
    """Cheap identity for a source file: size + hash of its first megabyte."""
    try:
        p = Path(path)
        h = hashlib.blake2b(digest_size=12)
        h.update(str(p.stat().st_size).encode())
        with p.open("rb") as f:
            h.update(f.read(1 << 20))
        return h.hexdigest()
    except OSError:
        return ""


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


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip()[:40] or "clip"


def import_file(src: str, color: str) -> tuple[SoundMeta, np.ndarray]:
    """Decode, bring into the library folder, and return metadata + int16 audio.

    Plain audio files are copied as they are. Anything that needed ffmpeg (video,
    m4a, aac, wma) is stored as a FLAC of its *audio* instead: a 300 MB video used
    to be copied whole, and the library stays playable if ffmpeg goes away."""
    data, via_ffmpeg = _decode(src)
    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    sid = uuid.uuid4().hex[:10]
    srcp = Path(src)
    if via_ffmpeg:
        dest = SOUNDS_DIR / f"{sid}_{_safe_name(srcp.stem)}.flac"
        sf.write(dest, data, SR, subtype="PCM_16")
    else:
        dest = SOUNDS_DIR / f"{sid}_{srcp.name}"
        try:
            shutil.copy2(srcp, dest)
        except OSError:
            log.warning("couldn't copy %s into the library; using it in place", src,
                        exc_info=True)
            dest = srcp
    meta = SoundMeta(id=sid, name=srcp.stem.replace("_", " ").strip()[:40], file=str(dest),
                     color=color, level_gain=level_gain(data), duration=len(data) / SR,
                     fingerprint=fingerprint(src))
    return meta, store_cached(sid, data)


def save_clip(data: np.ndarray, name: str, color: str) -> tuple[SoundMeta, np.ndarray]:
    """Store recorded audio ((n, 2) float32 at SR) as a FLAC; return metadata + int16 audio."""
    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    sid = uuid.uuid4().hex[:10]
    dest = SOUNDS_DIR / f"{sid}_{_safe_name(name)}.flac"
    sf.write(dest, data, SR, subtype="PCM_16")
    meta = SoundMeta(id=sid, name=name[:40], file=str(dest), color=color,
                     level_gain=level_gain(data), duration=len(data) / SR,
                     fingerprint=fingerprint(str(dest)))
    return meta, store_cached(sid, data)


def trim_silence(data: np.ndarray, threshold: float = 0.002, pad_s: float = 0.05) -> np.ndarray:
    """Cut dead air off both ends of a recording (keeps a tiny pad so it doesn't start abruptly)."""
    loud = np.flatnonzero(np.max(np.abs(data), axis=1) > threshold)
    if not len(loud):
        return data[:0]
    pad = int(pad_s * SR)
    return data[max(loud[0] - pad, 0): loud[-1] + pad]


def duplicate(meta: SoundMeta, name: str) -> SoundMeta:
    """A copy of a sound with its own library file (so removing either one never
    takes the other's audio with it), cache, id and no hotkey."""
    sid = uuid.uuid4().hex[:10]
    src = Path(meta.file)
    dest = src
    if src.is_file():
        SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
        dest = SOUNDS_DIR / f"{sid}_{_safe_name(name)}{src.suffix}"
        shutil.copy2(src, dest)
    try:
        if cache_path(meta.id).exists():
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cache_path(meta.id), cache_path(sid))
    except OSError:
        log.debug("couldn't copy the cache for %s", meta.id, exc_info=True)
    return SoundMeta(id=sid, name=name[:40], file=str(dest), volume=meta.volume,
                     mode=meta.mode, loop=meta.loop, color=meta.color,
                     level_gain=meta.level_gain, duration=meta.duration,
                     fingerprint="", fx=dict(meta.fx))


def delete_file(meta: SoundMeta):
    p = Path(meta.file)
    try:
        if p.parent == SOUNDS_DIR:
            p.unlink(missing_ok=True)
        for c in CACHE_DIR.glob(f"{meta.id}*.npy"):
            if c.stem == meta.id or c.stem.startswith(meta.id + "."):
                c.unlink(missing_ok=True)
    except OSError:
        log.warning("couldn't delete %s", p, exc_info=True)
