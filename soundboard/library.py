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
import math
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import ClassVar

import numpy as np
import soundfile as sf
import soxr

from soundboard.engine import SR
from soundboard.eq import BANDS as EQ_BANDS
from soundboard.eq import MAX_DB as EQ_MAX_DB

log = logging.getLogger(__name__)

APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "OnionBoard"
# from when this app was called Soundboard; see migrate_from_soundboard() below
OLD_APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "Soundboard"
SOUNDS_DIR = APP_DIR / "sounds"
CACHE_DIR = APP_DIR / "cache"
THUMBS_DIR = APP_DIR / "thumbs"   # pad pictures (soundboard.thumbs)
CONFIG_PATH = APP_DIR / "config.json"
CONFIG_VERSION = 4
CONFIG_BACKUPS = 3   # config.json.1 … .3, rotated on every save that changes something
# where install-vbcable.ps1 lives: installer/ in a source checkout, or the frozen
# app's _internal folder (PyInstaller's _MEIPASS; build.ps1 bundles it at its root)
RESOURCE_DIR = (Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS")
                else Path(__file__).resolve().parent.parent / "installer")

AUDIO_EXTS = {".wav", ".mp3", ".ogg", ".flac", ".opus", ".m4a", ".aac", ".wma",
              ".aiff", ".aif", ".webm", ".mp4", ".mkv", ".mov"}
MAX_SECONDS = 15 * 60
FFMPEG_TIMEOUT = 120
TARGET_RMS_DB = -17.0  # loudness everything is levelled to when "Level volumes" is on
I16 = 32767.0

PAD_COLORS = ["#7c5cff", "#ff5c8a", "#1fb6ff", "#13ce66", "#ffb020", "#ff7849",
              "#00c2b2", "#e056fd", "#5c7cfa", "#94a3b8"]


MIGRATION_ERRORS: list[str] = []


def fits_type(default, v) -> bool:
    """Is `v` an acceptable value for a setting whose default is `default`? Used on
    everything read back from disk, so a hand-edited or damaged value falls back to
    the default instead of crashing the window that uses it."""
    if isinstance(default, bool):
        return isinstance(v, bool)
    if isinstance(default, float):   # json accepts NaN / Infinity: a NaN volume would
        return (isinstance(v, (int, float)) and not isinstance(v, bool)   # poison the mix
                and math.isfinite(v))
    if isinstance(default, int):
        return isinstance(v, int) and not isinstance(v, bool)
    if default is None:
        return v is None or isinstance(v, (str, int, float))
    return isinstance(v, type(default))


def _typed(raw: dict, defaults, what: str) -> dict:
    """Keep only raw's known fields whose type fits (floats given as ints become floats)."""
    out = {}
    for k, v in raw.items():
        if k not in type(defaults).__dataclass_fields__:
            continue
        want = getattr(defaults, k)
        if not fits_type(want, v):
            log.warning("ignored %s setting %s=%r (expected %s)", what, k, v, type(want).__name__)
            continue
        out[k] = float(v) if isinstance(want, float) else v
    return out


VOLUME_MAX = 10.0             # the mixer's volume boxes take up to 1000 %
PAD_WIDTH_RANGE = (110, 240)  # the Sounds tab's pad-size slider
# settings shown on a control with a fixed range: a value from a hand-edited config or
# someone's backup is brought into it (Qt raises OverflowError on one past an int)
SETTING_RANGES = {"sound_vol": (0.0, VOLUME_MAX), "mic_vol": (0.0, VOLUME_MAX),
                  "mon_vol": (0.0, VOLUME_MAX), "pad_width": PAD_WIDTH_RANGE,
                  "duck_db": (-24.0, 0.0), "replay_seconds": (5, 120)}


def clean_setting(k: str, v):
    """Setting `k` (already of the right type) as the app can use it: brought into the
    range of its control. None if it's unusable, so the default applies instead."""
    if k in SETTING_RANGES:
        lo, hi = SETTING_RANGES[k]
        return min(max(v, lo), hi)
    if k == "eq_gains":   # one finite gain per band, within the EQ's sliders
        if len(v) != len(EQ_BANDS) or not all(
                isinstance(g, (int, float)) and not isinstance(g, bool) and math.isfinite(g)
                for g in v):
            return None
        return [min(max(float(g), -EQ_MAX_DB), EQ_MAX_DB) for g in v]
    if k == "dest":   # {"mode": key, "custom": [mode dicts]} (soundboard.destination)
        v = dict(v)
        if not isinstance(v.get("mode", ""), str):
            v.pop("mode")
        if "custom" in v:
            custom = v["custom"]
            if isinstance(custom, list):
                v["custom"] = [d for d in custom if isinstance(d, dict)]
            else:
                v.pop("custom")
    return v


def _is_our_old_folder() -> bool:
    """%APPDATA%\\Soundboard is a common name: only take it if it looks like ours
    (a config.json of ours, or a sounds folder), never another program's data."""
    if (OLD_APP_DIR / "sounds").is_dir():
        return True
    try:
        raw = json.loads((OLD_APP_DIR / "config.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False
    return isinstance(raw, dict) and ("sounds" in raw or "version" in raw)


def migrate_from_soundboard() -> None:
    """One-time move of %APPDATA%\\Soundboard (sounds, settings, cache, browser
    profile) into %APPDATA%\\OnionBoard, for anyone who installed this app back when
    it was called Soundboard. Must run before anything creates APP_DIR - called first
    thing in app.py's main(), ahead of applog.setup()."""
    # Keyed on the new config, not the new folder: the installer's cable step can
    # create APP_DIR (its restart marker) before the app's first launch, and a move
    # that failed halfway must be retried next launch rather than silently skipped.
    if not OLD_APP_DIR.is_dir() or CONFIG_PATH.exists() or not _is_our_old_folder():
        return
    if not APP_DIR.exists():
        try:
            OLD_APP_DIR.rename(APP_DIR)
            return
        except OSError:
            pass   # different drive, a file in use: go item by item below
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        # the config goes last, so it only exists once everything it points at does
        for item in sorted(OLD_APP_DIR.iterdir(), key=lambda p: p.name.startswith("config.json")):
            dst = APP_DIR / item.name
            if dst.exists():
                continue
            try:
                item.rename(dst)
            except OSError:   # copy instead, keep the old one
                stage = dst.with_name(dst.name + ".migrating")
                if stage.is_dir():
                    shutil.rmtree(stage)
                if item.is_dir():
                    shutil.copytree(item, stage)
                else:
                    shutil.copy2(item, stage)
                stage.rename(dst)
    except OSError as e:
        # logging isn't set up yet (it writes into APP_DIR); remembered for later
        MIGRATION_ERRORS.append(f"couldn't move {OLD_APP_DIR} to {APP_DIR}: {e}")


@dataclass
class SoundMeta:
    id: str
    name: str
    file: str                 # absolute path (usually inside SOUNDS_DIR)
    volume: float = 1.0       # 0..2 user gain
    hotkey: str = ""
    mode: str = "restart"     # restart | overlap | toggle | solo (stops the other sounds)
    loop: bool = False
    color: str = PAD_COLORS[0]
    level_gain: float = 1.0   # computed loudness-levelling gain
    duration: float = 0.0
    fingerprint: str = ""     # of the source file, to notice a re-import of the same file
    fx: dict = field(default_factory=dict)   # speed, pitch, EQ, boost… (soundboard.soundfx)
    image: str = ""           # pad picture, absolute path (usually inside THUMBS_DIR)
    tags: list[str] = field(default_factory=list)   # the categories it's in (Config.categories)
    fade_in: float = 0.0      # seconds: rises from silence when it starts
    fade_out: float = 0.0     # seconds: falls to silence when stopped / near its end
    hold: bool = False        # plays only while its hotkey / MIDI pad is held down


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
    overlay_hotkey: str = "`"         # in-game overlay (see ui.overlay)
    overlay_key_checked: bool = False   # "`" looked at against the keyboard layout once
    cue_sounds: bool = True           # beep in the headphones when a hotkey records / saves
    theme: str = "Dark"
    eq_enabled: bool = False
    eq_target: str = "voice"          # voice | sounds | all
    eq_preset: str = "Flat (off)"
    eq_gains: list[float] = field(default_factory=lambda: [0.0] * 7)
    dest: dict = field(default_factory=dict)   # who's listening (soundboard.destination)
    send_mono: bool = True    # phase-aware mono into the cable (soundboard.sendfx.SmartMono)
    duck_db: float = 0.0      # lower the sounds this much while you talk; 0 = off
    mic_gate: bool = False    # mute your mic while a sound plays (only the sound goes out)
    ptt_key: str = ""           # key held down while sounds play (game push-to-talk)
    always_on_top: bool = False
    pad_width: int = 150
    tab: int = 0     # 0 = sounds, 1 = radio, 2 = apps, 3 = triggers, 4 = voice, 5 = setup
    # fetch newer yt-dlp versions from PyPI by itself: opt-in, since that's code the app
    # runs (named *_optin so configs saved while it defaulted to on start off again)
    ytdlp_auto_optin: bool = False
    latency: str = "low"              # audio buffering: 'low' | 'high' (safer on flaky devices)
    setup_done: bool = False          # the quick-setup guide has been completed
    voice_discord_tip_shown: bool = False   # "Got it" on the voice changer's Studio notice
    voice_fx: dict = field(default_factory=dict)   # voice changer (see ui.voicepanel)
    speech: dict = field(default_factory=dict)     # text-to-speech / live voice settings
    overlay: dict = field(default_factory=dict)    # in-game overlay (ui.overlay.OverlaySettings)
    radio: dict = field(default_factory=dict)      # Radio tab: vol, monitor, favorites, last
    apps: dict = field(default_factory=dict)       # Apps tab: exe -> {vol, monitor} to re-capture
    # Triggers tab: on, interval_ms, monitor (the screen for triggers that don't pick
    # their own), triggers (soundboard.screenwatch.Trigger)
    screen: dict = field(default_factory=dict)
    categories: list[str] = field(default_factory=list)   # pad categories, in tab order
    category: str = ""                # the category the Sounds tab shows; "" = all
    tray: bool = True                 # closing the window keeps the app in the tray
    autostart_hidden: bool = True     # started with Windows: straight to the tray
    # look at GitHub Releases for a newer version, at most once a day (soundboard.updates).
    # Was the opt-in update_check_optin, off by default: renamed so every config starts on
    update_check: bool = True
    update_checked: float = 0.0       # time.time() of the last check
    update_skip: str = ""             # a version the user said to skip
    update_pending: str = ""          # the version an update is installing (see updates.py)
    random_hotkey: str = ""           # plays a random sound from the category showing
    category_hotkeys: dict = field(default_factory=dict)   # category -> its random-sound key
    # instant replay (soundboard.replay): while this hotkey is set, the last
    # replay_seconds of everything you hear (except Onion Board's own sounds) are kept
    # in memory, and the key saves them as a new pad
    replay_hotkey: str = ""
    replay_seconds: int = 30
    # local control API for Stream Deck / scripts (soundboard.remote): off unless turned on
    api_enabled: bool = False
    api_port: int = 7474
    api_token: str = ""
    sounds: list[SoundMeta] = field(default_factory=list)

    # set by load() when the settings weren't read cleanly, for the window to tell the
    # user (not a dataclass field, so it's never saved)
    load_note: ClassVar[str] = ""

    @classmethod
    def load(cls) -> Config:
        """Read config.json. A corrupt file is set aside (config.json.broken-<time>)
        and the newest backup that loads is used instead; only if there is none
        do the defaults apply. A missing file with backups beside it (deleted, or lost
        mid-save) is recovered the same way, before a save rotates the backups away.
        The pad list is never silently thrown away."""
        raw, err, missing = None, None, False
        for attempt in range(5):   # OneDrive / antivirus can hold the file for a moment
            try:
                raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))   # sig: a BOM is fine
                break
            except FileNotFoundError as e:
                if not any(CONFIG_PATH.with_name(f"config.json.{i}").exists()
                           for i in range(1, CONFIG_BACKUPS + 1)):
                    return cls()   # a first start
                err, missing = e, True
                break
            except ValueError as e:
                err = e
                break
            except OSError as e:
                err = e
                time.sleep(0.2 * (attempt + 1))
        if raw is not None:
            try:
                return cls.from_raw(raw)
            except (TypeError, ValueError, KeyError, AttributeError) as e:
                err = e
        log.error("config %s is unreadable: %r", CONFIG_PATH, err)
        broken = "" if missing else cls._set_aside()
        kept = ("" if missing else
                f" The damaged file was kept as {broken or 'config.json'}.")
        what = "missing" if missing else "damaged"
        for name, raw in cls._backups():
            try:
                cfg = cls.from_raw(raw)
            except (TypeError, ValueError, KeyError, AttributeError):
                log.warning("backup %s doesn't load either", name, exc_info=True)
                continue
            log.warning("recovered settings from backup %s", name)
            cfg.load_note = (f"Your settings file was {what}, so the last good copy "
                             f"({name}) was loaded instead.{kept}")
            return cfg
        cfg = cls()
        cfg.load_note = (f"Your settings file was {what} and no backup could be read, so "
                         "Onion Board started with default settings. Your sound files are "
                         f"still in {SOUNDS_DIR}.{kept}")
        return cfg

    @classmethod
    def _set_aside(cls) -> str:
        try:
            broken = CONFIG_PATH.with_name(f"config.json.broken-{time.strftime('%Y%m%d-%H%M%S')}")
            CONFIG_PATH.replace(broken)
            log.warning("set the damaged config aside as %s", broken.name)
            return broken.name
        except OSError:
            log.debug("couldn't set the damaged config aside", exc_info=True)
            return ""

    @classmethod
    def _backups(cls):
        """(name, parsed json) of each backup that parses, newest first."""
        for i in range(1, CONFIG_BACKUPS + 1):
            p = CONFIG_PATH.with_name(f"config.json.{i}")
            try:
                yield p.name, json.loads(p.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue

    @classmethod
    def from_raw(cls, raw: dict) -> Config:
        if not isinstance(raw, dict):   # e.g. a top-level [] - damaged, try the backups
            raise ValueError(f"config is a {type(raw).__name__}, not an object")
        raw = dict(raw)
        version = max(1, int(raw.get("version", 1) or 1))   # nothing older than v1 exists
        for v in range(version, CONFIG_VERSION):
            raw = MIGRATIONS[v](raw)
        sounds = []
        blank = SoundMeta(id="", name="", file="")
        raw_sounds = raw.pop("sounds", [])
        for s in raw_sounds if isinstance(raw_sounds, list) else []:
            if not isinstance(s, dict) or not all(isinstance(s.get(k), str) and s.get(k)
                                                  for k in ("id", "name", "file")):
                log.warning("skipped a damaged sound entry in the config: %r", s)
                continue
            s = _typed(s, blank, f"sound {s['name']!r}")
            for k in ("file", "image"):   # v0.1.0 stored full paths into the old folder
                if s.get(k) and Path(s[k]).is_absolute() and Path(s[k]).is_relative_to(OLD_APP_DIR):
                    s[k] = str(APP_DIR / Path(s[k]).relative_to(OLD_APP_DIR))
            if not Path(s["file"]).is_absolute():
                s["file"] = str(SOUNDS_DIR / s["file"])   # stored relative to the library
            if s.get("image") and not Path(s["image"]).is_absolute():
                s["image"] = str(THUMBS_DIR / s["image"])
            s["tags"] = clean_tags(s.get("tags"))
            for k in ("fade_in", "fade_out"):
                s[k] = clean_fade(s.get(k))
            for k, lo, hi in (("volume", 0.0, 2.0), ("level_gain", 0.1, 6.0)):
                if k in s:   # the Edit dialog's slider can't take any number
                    s[k] = min(max(s[k], lo), hi)
            sounds.append(SoundMeta(**s))
        # configs from before the setup guide existed: whoever already picked an output
        # device has been set up by hand, so don't greet them with the guide
        raw.setdefault("setup_done", bool(raw.get("main_device")))
        known = _typed(raw, cls(), "config")
        for k, v in list(known.items()):
            if v is None:   # a device: None is the system default
                continue
            known[k] = clean_setting(k, v)
            if known[k] is None:
                log.warning("ignored config setting %s=%r (out of range)", k, v)
                del known[k]
        known["version"] = CONFIG_VERSION
        cfg = cls(**known, sounds=sounds)
        cfg.categories = clean_tags(cfg.categories)
        for m in sounds:   # a category a sound is in always has a tab
            m.tags = merge_tags(m.tags, cfg.categories)
        if cfg.category not in cfg.categories:
            cfg.category = ""
        return cfg

    def to_raw(self) -> dict:
        d = asdict(self)
        d["version"] = CONFIG_VERSION
        for s in d["sounds"]:   # files inside the library are stored by name only, so the
            p = Path(s["file"])  # whole %APPDATA%\OnionBoard folder can move or be restored
            if p.is_absolute() and p.parent == SOUNDS_DIR:
                s["file"] = p.name
            if s["image"] and Path(s["image"]).parent == THUMBS_DIR:
                s["image"] = Path(s["image"]).name
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
                try:
                    _rotate_backups()
                except OSError:   # a backup locked for a moment mustn't block the save
                    log.warning("couldn't rotate the config backups", exc_info=True)
            tmp.replace(CONFIG_PATH)
            return True
        except OSError:
            log.exception("couldn't save settings to %s", CONFIG_PATH)
            return False


MAX_FADE_S = 10.0


def clean_fade(v) -> float:
    """A fade length in seconds, 0..MAX_FADE_S (anything unreadable is no fade)."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.0
    return min(max(v, 0.0), MAX_FADE_S) if v == v else 0.0


def clean_tags(tags) -> list[str]:
    """Category names: strings, trimmed, at most 30 characters, no duplicates
    (ignoring case), in order."""
    out, seen = [], set()
    for t in tags if isinstance(tags, list) else []:
        t = str(t).strip()[:30] if isinstance(t, str) else ""
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def merge_tags(tags: list[str], categories: list[str]) -> list[str]:
    """`tags` spelled the way `categories` already spells them (ignoring case), so an
    imported "memes" lands in the existing "Memes". Tags that aren't a category yet
    are appended to `categories`, which is changed in place."""
    by_lower = {c.lower(): c for c in categories}
    out = []
    for t in clean_tags(tags):
        c = by_lower.get(t.lower())
        if c is None:
            categories.append(t)
            c = by_lower[t.lower()] = t
        out.append(c)
    return out


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


def _migrate_2_to_3(raw: dict) -> dict:
    """v3 removed the Browser tab (tab 1): later tabs move down one, and the Browser
    tab itself opens Sounds. Its settings and hotkeys are simply no longer read."""
    tab = raw.get("tab")
    if isinstance(tab, int) and not isinstance(tab, bool):
        raw["tab"] = 0 if tab <= 1 else tab - 1
    return raw


def _migrate_3_to_4(raw: dict) -> dict:
    """v4 added the Triggers tab after Apps (tab 3): Voice and Setup move up one."""
    tab = raw.get("tab")
    if isinstance(tab, int) and not isinstance(tab, bool) and tab >= 3:
        raw["tab"] = tab + 1
    return raw


MIGRATIONS = {1: _migrate_1_to_2, 2: _migrate_2_to_3, 3: _migrate_3_to_4}


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


def original_frames(meta: SoundMeta) -> int:
    """Length of a sound as imported (before effects or trim), in frames at SR:
    from the cache's header when it's there (no audio is read), else the file's."""
    p = cache_path(meta.id)
    try:
        if p.exists():
            return int(np.load(p, mmap_mode="r").shape[0])
    except Exception:  # noqa: BLE001
        log.debug("couldn't read the cache header of %s", meta.id, exc_info=True)
    try:
        info = sf.info(meta.file)
        return int(min(info.frames / info.samplerate, MAX_SECONDS) * SR)
    except Exception:  # noqa: BLE001 - m4a/video etc.: decode it
        return len(load_original(meta))


def peaks(data: np.ndarray, n: int) -> np.ndarray:
    """(n,) loudest absolute sample in each of n equal slices of (m, 2) audio,
    0..1: enough to draw a waveform."""
    if not len(data) or n <= 0:
        return np.zeros(max(n, 0), np.float32)
    scale = 1 / I16 if data.dtype == np.int16 else 1.0
    edges = np.linspace(0, len(data), n + 1).astype(np.int64)
    out = np.zeros(n, np.float32)
    for i in range(n):
        a, b = edges[i], max(edges[i + 1], edges[i] + 1)
        seg = data[a:min(b, len(data))]
        if len(seg):
            out[i] = float(np.abs(seg).max()) * scale
    return np.clip(out, 0.0, 1.0)


def original_peaks(meta: SoundMeta, n: int = 400) -> tuple[np.ndarray, float]:
    """(waveform peaks, length in seconds) of a sound as imported, for the trim
    control. Read from the cache without loading it (every few frames of a long
    one: plenty for n columns). No cache yet: no peaks, the length from the file."""
    p = cache_path(meta.id)
    try:
        if p.exists():
            data = np.load(p, mmap_mode="r")
            step = max(1, len(data) // 400_000)
            return peaks(np.asarray(data[::step]), n), len(data) / SR
    except Exception:  # noqa: BLE001
        log.debug("couldn't read the cache of %s for its waveform", meta.id, exc_info=True)
    try:
        return np.zeros(0, np.float32), original_frames(meta) / SR
    except Exception:  # noqa: BLE001 - the file is gone: nothing to trim
        return np.zeros(0, np.float32), 0.0


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
    to be copied whole, and the library stays playable if ffmpeg goes away. So is a
    file libsndfile reads under a name outside AUDIO_EXTS (.au, .caf, .w64…): only
    those come back in from a backup (soundboard.backup)."""
    data, via_ffmpeg = _decode(src)
    if not len(data):
        raise ValueError("this file has no audio in it")
    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    sid = uuid.uuid4().hex[:10]
    srcp = Path(src)
    as_flac = via_ffmpeg or srcp.suffix.lower() not in AUDIO_EXTS
    if as_flac:
        dest = SOUNDS_DIR / f"{sid}_{_safe_name(srcp.stem)}.flac"
    else:
        # capped: a long source name plus the id would pass Windows' 255-character limit
        dest = SOUNDS_DIR / f"{sid}_{srcp.stem[:80].strip() or 'sound'}{srcp.suffix.lower()}"
    # Never fall back to using `src` in place: a download's temp folder is deleted
    # right after this. A failed copy leaves nothing behind and says what to do.
    try:
        if as_flac:
            sf.write(dest, data, SR, subtype="PCM_16")
        else:
            shutil.copy2(srcp, dest)
        meta = SoundMeta(id=sid, name=srcp.stem.replace("_", " ").strip()[:40],
                         file=str(dest), color=color, level_gain=level_gain(data),
                         duration=len(data) / SR, fingerprint=fingerprint(src))
        return meta, store_cached(sid, data)
    except Exception as e:
        log.warning("couldn't copy %s into the library", src, exc_info=True)
        dest.unlink(missing_ok=True)
        if isinstance(e, OSError):
            raise OSError(f"couldn't save it into your Sounds folder ({e.strerror or e}). "
                          "Check the disk isn't full and try again.") from e
        raise


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
    image = meta.image
    if image and Path(image).parent == THUMBS_DIR:   # its own copy, like the audio
        try:
            image = str(THUMBS_DIR / f"{sid}{Path(image).suffix}")
            shutil.copy2(meta.image, image)
        except OSError:
            log.debug("couldn't copy the picture of %s", meta.id, exc_info=True)
            image = ""
    return SoundMeta(id=sid, name=name[:40], file=str(dest), volume=meta.volume,
                     mode=meta.mode, loop=meta.loop, color=meta.color,
                     level_gain=meta.level_gain, duration=meta.duration,
                     fingerprint="", fx=dict(meta.fx), image=image, tags=list(meta.tags),
                     fade_in=meta.fade_in, fade_out=meta.fade_out, hold=meta.hold)


def recycle(path: Path) -> bool:
    """Send a file to the Windows Recycle Bin (so it can still be restored from
    there). False if that isn't possible: the caller deletes it instead."""
    if sys.platform != "win32" or not path.exists():
        return False
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                    ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]
    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 4, 16, 64, 1024
    op = SHFILEOPSTRUCTW(wFunc=FO_DELETE, pFrom=str(path.resolve()) + chr(0),
                         fFlags=FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI)
    try:
        ok = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0
        return ok and not op.fAnyOperationsAborted and not path.exists()
    except Exception:  # noqa: BLE001
        log.debug("recycling %s failed", path, exc_info=True)
        return False


# tests switch this off so they never fill the real Recycle Bin
USE_RECYCLE_BIN = True


def delete_file(meta: SoundMeta):
    """Remove a sound's files: the audio goes to the Recycle Bin (it's the one thing
    that can't be made again), its picture and decoded cache are deleted."""
    p = Path(meta.file)
    try:
        if p.parent == SOUNDS_DIR and not (USE_RECYCLE_BIN and recycle(p)):
            p.unlink(missing_ok=True)
        if meta.image and Path(meta.image).parent == THUMBS_DIR:
            Path(meta.image).unlink(missing_ok=True)
        for c in CACHE_DIR.glob(f"{meta.id}*.npy"):
            if c.stem == meta.id or c.stem.startswith(meta.id + "."):
                c.unlink(missing_ok=True)
    except OSError:
        log.warning("couldn't delete %s", p, exc_info=True)
