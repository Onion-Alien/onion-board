"""Sound library: decoding, loudness analysis, the decoded-audio cache and config.

Audio in memory is int16 stereo at SR ((n, 2), the engine scales it on the fly).
That is half the RAM of float32 and it round-trips losslessly through the cache
folder, so after the first run a sound loads by reading one file instead of
decoding and resampling it again.
"""
from __future__ import annotations

import collections
import contextlib
import hashlib
import itertools
import json
import logging
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from functools import cache, lru_cache
from pathlib import Path
from typing import ClassVar, NamedTuple

import numpy as np
import soundfile as sf
import soxr

from soundboard import __version__, mapped, sourceinfo, winpath
from soundboard.engine import SR
from soundboard.eq import BANDS as EQ_BANDS
from soundboard.eq import MAX_DB as EQ_MAX_DB
from soundboard.i18n import _, ngettext

log = logging.getLogger(__name__)

# usable_dir: spelled out through any folder link Windows won't follow (soundboard.winpath)
APP_DIR = winpath.usable_dir(Path(os.environ.get("APPDATA", Path.home())) / "OnionBoard")
# from when this app was called Soundboard; see migrate_from_soundboard() below
OLD_APP_DIR = winpath.usable_dir(Path(os.environ.get("APPDATA", Path.home())) / "Soundboard")
SOUNDS_DIR = winpath.usable_dir(APP_DIR / "sounds")
CACHE_DIR = winpath.usable_dir(APP_DIR / "cache")
CACHE_GRACE_S = 600   # prune_cache leaves a new sound's cache this long (an import in flight)
# cache files a delete was refused for (still mapped, see _unlink): not new imports, so
# prune_cache retries them at once instead of after CACHE_GRACE_S
_refused: set[Path] = set()
THUMBS_DIR = winpath.usable_dir(APP_DIR / "thumbs")   # pad pictures (soundboard.thumbs)
CONFIG_PATH = APP_DIR / "config.json"
# privacy.json beside config.json: a copy of the Privacy & security settings: a version
# from before them drops them when it saves, and the next newer start takes them back
PRIVACY_KEYS = ("net_mode", "net_proxy", "net_off", "net_offline", "netlog_keep",
                "tor_bridges", "app_log")
# ...and which What's new was seen, which those versions drop too (it showed again after
# going back a version and returning). Versions that read privacy.json take only
# PRIVACY_KEYS from it, so the extra key is safe for them.
SIDE_KEYS = PRIVACY_KEYS + ("whats_new_seen",)
CONFIG_VERSION = 4
LOAD_TRIES = 12      # ~10 s of retries while config.json is locked
# a new user's first window: Sounds, Voice and Setup; the rest wait under + More tabs
BASIC_TABS_OFF = ("radio", "apps", "triggers")
CONFIG_BACKUPS = 3   # config.json.1 … .3, rotated on a save that changes something...
ROTATE_EVERY_S = 3600   # ...at most once an hour (the first change of a session always)
# where install-vbcable.ps1 lives: installer/ in a source checkout, or the frozen
# app's _internal folder (PyInstaller's _MEIPASS; build.ps1 bundles it at its root)
RESOURCE_DIR = (Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS")   # pyright: ignore[reportAttributeAccessIssue]
                else Path(__file__).resolve().parent.parent / "installer")

AUDIO_EXTS = {".wav", ".mp3", ".ogg", ".flac", ".opus", ".m4a", ".aac", ".wma",
              ".aiff", ".aif", ".webm", ".mp4", ".mkv", ".mov"}
MAX_SECONDS = 120 * 60
FFMPEG_TIMEOUT = 300
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


UI_SCALES = (80, 90, 100, 110, 125, 150)   # the interface sizes Settings offers (percent)


@cache
def field_names(cls) -> frozenset[str]:
    """A dataclass's settings: its fields, not its ClassVars (which __dataclass_fields__
    lists too, e.g. Config.read_only)."""
    return frozenset(f.name for f in fields(cls))


def _typed(raw: dict, defaults, what: str) -> dict:
    """Keep only raw's known fields whose type fits (floats given as ints become floats)."""
    out = {}
    known = field_names(type(defaults))
    for k, v in raw.items():
        if k not in known:
            continue
        want = getattr(defaults, k)
        if not fits_type(want, v):
            log.warning("ignored %s setting %s=%r (expected %s)", what, k, v, type(want).__name__)
            continue
        out[k] = float(v) if isinstance(want, float) else v
    return out


@lru_cache(maxsize=4096)
def _stored_path(path: str, folder: Path, absolute: bool) -> str:
    """`path` as config.json keeps it: just the name when it's a file in `folder` (only
    an absolute path, with `absolute`). Remembered: every save (each drag of a pad, each
    volume change) asked pathlib this for every sound, ~3 ms of it with 200 sounds."""
    p = Path(path)
    if (p.is_absolute() or not absolute) and p.parent == folder:
        return p.name
    if absolute and p.is_absolute() and p.is_relative_to(folder):   # a sound in one of
        return p.relative_to(folder).as_posix()   # its folders: "YouTube/Song.flac"
    return path


# A newer version's settings, kept so this one's save writes them back (an older
# version opening newer settings must lose nothing). Set on a loaded Config / SoundMeta
# as plain attributes, not dataclass fields: asdict() and == never see them.
#   _raw_extra  keys this version doesn't know, as they were
#   _raw_kept   {key: (the value used instead, the value as it was)}: a choice this
#               version doesn't know (a newer route, net_mode, mode), written back as
#               it was unless it has been changed here since
def _with_raw(d: dict, obj) -> dict:
    """asdict(obj) `d` with obj's newer-version settings put back in."""
    for k, v in getattr(obj, "_raw_extra", {}).items():
        d.setdefault(k, v)
    for k, (used, was) in getattr(obj, "_raw_kept", {}).items():
        if d.get(k) == used:
            d[k] = was
    return d


VOLUME_MAX = 10.0             # the mixer's volume boxes take up to 1000 %
PAD_WIDTH_RANGE = (110, 240)  # the Sounds tab's pad-size slider
# settings shown on a control with a fixed range: a value from a hand-edited config or
# someone's backup is brought into it (Qt raises OverflowError on one past an int)
NET_MODES = ("direct", "proxy", "tor")   # soundboard.net.MODES
TOR_BRIDGES = ("", "snowflake", "obfs4")   # soundboard.tor.BRIDGES
# where what others hear goes (Config.route; Setup -> Devices -> Send my sounds to):
#   cable  - a virtual cable, whose other end Discord / the game uses as its mic
#   device - any output picked by hand (Voicemeeter, a mixer, a second sound card, a
#            device OBS captures): no cable needed, and none is picked in its place
#   off    - nowhere: sounds play in your headphones (and the stream output) only
#   mic    - straight into your real mic (the mic effect, soundboard.directmic): Discord
#            and games keep their normal mic, no cable. New users start with it
#            (Config.first_start); the cable is the fallback.
ROUTES = ("cable", "device", "off", "mic")
# settings whose unknown value (a newer version's choice) clean_setting replaces with
# a safe one: the value as it was is still written back (see _with_raw)
NEWER_CHOICES = ("route", "net_mode", "tor_bridges", "pad_sort", "pad_view", "list_rows",
                 "app_clip_group")
# the Sounds tab's orders: as dragged, A-Z, the newest first, the most played first
PAD_SORTS = ("custom", "name", "newest", "plays")
PAD_VIEWS = ("grid", "list")
# the list view's row heights (ui.widgets.LIST_ROW_H)
LIST_ROWS = ("small", "medium", "large")
SETTING_RANGES = {"sound_vol": (0.0, VOLUME_MAX), "mic_vol": (0.0, VOLUME_MAX),
                  "mon_vol": (0.0, VOLUME_MAX), "obs_vol": (0.0, VOLUME_MAX),
                  "pad_width": PAD_WIDTH_RANGE, "app_card_width": (240, 480),
                  "app_clip_height": (0, 600),
                  "playing_background_opacity": (0, 100),
                  "duck_db": (-24.0, 0.0), "replay_seconds": (5, 120)}


def clean_programs(v) -> dict[str, str]:
    """Config.category_programs as the app can use it: {exe file name, lower case:
    category}; entries that aren't a plain file name and a category name are dropped."""
    out: dict[str, str] = {}
    if not isinstance(v, dict):
        return out
    for exe, cat in v.items():
        if not isinstance(exe, str) or not isinstance(cat, str) or not cat.strip():
            continue
        name = exe.strip().lower()
        if name and name not in (".", "..") and not any(c in name for c in "/\\:"):
            out[name] = cat.strip()
    return out


def clean_setting(k: str, v):
    """Setting `k` (already of the right type) as the app can use it: brought into the
    range of its control. None if it's unusable, so the default applies instead."""
    if k in SETTING_RANGES:
        lo, hi = SETTING_RANGES[k]
        return min(max(v, lo), hi)
    if k == "category_programs":   # {exe file name: category}; anything else is dropped
        return clean_programs(v)
    if k == "net_mode":   # a mode this version doesn't know (a newer one's): fail
        return v if v in NET_MODES else "proxy"   # closed, never quietly direct
    if k in ("net_off", "tabs_off", "tips_seen", "sidebar_order"):   # keys; unknown ones kept
        # newer version's switch stays off after a downgrade and an upgrade
        return list(dict.fromkeys(x for x in v if isinstance(x, str) and x))
    if k == "route":   # a newer version's route: back to the cable, the safe default
        return v if v in ROUTES else "cable"
    if k == "pad_sort":
        return v if v in PAD_SORTS else "custom"
    if k == "pad_view":
        return v if v in PAD_VIEWS else "grid"
    if k == "list_rows":
        return v if v in LIST_ROWS else "medium"
    if k == "subcategories":   # {category: [names]}; anything else is dropped
        out = {}
        for c, subs in v.items():
            c = clean_tags([c])[0] if isinstance(c, str) and clean_tags([c]) else ""
            if c and SUB_SEP not in c:
                out[c] = [s for s in clean_tags(subs) if SUB_SEP not in s]
        return {c: subs for c, subs in out.items() if subs}
    if k == "app_clip_group":
        return v if v in ("newest", "app", "day") else "app"
    if k == "category_colors":   # {category: "#rrggbb"}; anything else is dropped
        return {c: col for c, col in v.items() if isinstance(c, str) and isinstance(col, str)
                and re.fullmatch(r"#[0-9a-fA-F]{6}", col)}
    if k == "tor_bridges":   # an unknown kind: still hide Tor, with the default bridge
        return v if v in TOR_BRIDGES else "snowflake"
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


_OUR_SOUND_FILE = re.compile(r"[0-9a-f]{10}_")


def _is_our_old_folder() -> bool:
    """%APPDATA%\\Soundboard is a common name: only take it if it looks like ours
    (a config.json of ours, or a sounds folder of our files), never another program's data."""
    try:   # our sound files are named <10-hex id>_<name>
        if any(_OUR_SOUND_FILE.match(f.name) for f in (OLD_APP_DIR / "sounds").iterdir()):
            return True
    except OSError:
        pass
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
    mode: str = "restart"     # restart | overlap | toggle | solo | queue (PRESS_MODE)
    #                           | queue (waits for the sounds playing to finish)
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
    only_them: bool = False   # goes out to others but not into your own headphones
    delay: float = 0.0        # seconds between the press and the sound starting
    cooldown: float = 0.0     # seconds after it starts during which presses are ignored
    plays: int = 0            # times it was played (the Sounds tab's Most played order)
    added: float = 0.0        # time.time() it joined the board; 0 = before this was kept
    pack: str = ""            # the sound pack it came from (backup.packs()), or ""
    pack_item: str = ""       # its folder in that pack, to reset it to how it came
    source: dict = field(default_factory=dict)   # the video it came from (sourceinfo)


@dataclass
class Config:
    copy_local_sounds: bool = True   # new local imports get their own copy (False: a link)
    version: int = CONFIG_VERSION
    route: str = "cable"      # where what others hear goes: ROUTES ("mic": see mic_first)
    # straight into my mic became the main way in 1.9.1: settings on the cable were
    # moved to it once (from_raw); after that a route picked by hand stays as picked
    mic_first: bool = False
    cable_tip_done: bool = False   # told once that a voice app is still on the cable
    mute_warning_off: bool = False   # "This won't mute you yet": Don't show this again
    main_device: str | None = None
    mon_device: str | None = None
    # the headphones are Windows' default output, and move with it when it changes
    # (off once another device is picked for them)
    mon_follows_default: bool = True
    mic_device: str | None = None
    # the stream output: a device OBS captures, getting what others hear without the
    # voice chat shaping (None = off; engine.Engine._obs)
    obs_device: str | None = None
    obs_vol: float = 1.0
    obs_voice: bool = True            # your mic goes to the stream output too
    # Setup -> Devices -> Also play on: more devices that get a copy of what others hear,
    # on top of "Send my sounds to" (streamers: Voicemeeter, OBS, a second cable...;
    # engine.Engine.set_copy_devices)
    also_send: list[str] = field(default_factory=list)
    sound_vol: float = 1.0
    mic_vol: float = 1.0
    mon_vol: float = 0.7
    mic_enabled: bool = True
    monitor_sounds: bool = True
    level_volumes: bool = True
    stop_hotkey: str = "ctrl+alt+s"
    pause_hotkey: str = ""
    skip_hotkey: str = ""             # the player's ⏭: the next sound in Up next
    overlay_hotkey: str = "`"         # in-game overlay (see ui.overlay)
    overlay_key_checked: bool = False   # "`" looked at against the keyboard layout once
    cue_sounds: bool = True           # beep in the headphones when a hotkey records / saves
    pong_sounds: bool = True          # Pong with Bun's sounds (its speaker button)
    theme: str = "Dark"
    # the app's language, a catalog code (assets/lang); "" = never picked (i18n.startup)
    language: str = ""
    # the whole interface's size in percent (Settings > Appearance), on top of Windows'
    # display scaling; read before the app starts (app.ui_scale_startup)
    ui_scale: int = 100
    live_color: str = ""   # own colour for the "it's on" highlights ("" = the theme's)
    theme_texture: bool = False  # True = each theme's own pattern on the panels; plain by default
    eq_enabled: bool = False
    eq_target: str = "voice"          # voice | sounds | all
    eq_preset: str = "Flat (off)"
    eq_gains: list[float] = field(default_factory=lambda: [0.0] * 7)
    dest: dict = field(default_factory=dict)   # who's listening (soundboard.destination)
    send_mono: bool = True    # phase-aware mono for the send device (sendfx.SmartMono)
    duck_db: float = -12.0    # lower the sounds this much while you talk; 0 = off
    duck_on: bool = False     # ducking was switched on once for older settings (from_raw)
    mic_gate: bool = False    # mute your mic while a sound plays (only the sound goes out)
    ptt_key: str = ""           # key held down while sounds play (game push-to-talk)
    always_on_top: bool = False
    # A quiet icon dot by default; saved bar preferences still take precedence.
    live_tab_green: bool = False
    playing_background: bool = False
    playing_background_opacity: int = 20
    pad_width: int = 150
    pad_sort: str = "custom"   # the Sounds tab's order: PAD_SORTS
    pad_view: str = "grid"     # "grid" (cards) or "list" (one-line rows)
    list_rows: str = "medium"  # the list view's row height: LIST_ROWS
    app_card_width: int = 300
    app_clip_height: int = 0   # saved clips: 0 fits the rows, otherwise the dragged height
    app_clip_group: str = "app"   # saved clips grouped by app, day, or newest first
    app_clips_expanded: bool = True   # fold the saved clips down to their header
    app_clips_keep_forever: bool = False   # otherwise expire after seven inactive days
    sidebar_open: bool = True   # the tab rail opened out to show the tabs' names
    sidebar_order: list[str] = field(default_factory=list)   # stable tab keys, visual order
    tab: int = 0     # 0 = sounds, 1 = radio, 2 = apps, 3 = triggers, 4 = voice, 5 = setup
    # Settings > Tabs: the tabs switched off ("radio", "apps", "triggers", "voice"), gone
    # from the window and never built (a new user starts with BASIC_TABS_OFF)
    tabs_off: list[str] = field(default_factory=list)
    # fetch newer yt-dlp versions from PyPI by itself: opt-in, since that's code the app
    # runs (named *_optin so configs saved while it defaulted to on start off again)
    ytdlp_auto_optin: bool = False
    latency: str = "low"              # audio buffering: 'low' | 'high' (safer on flaky devices)
    setup_done: bool = False          # the quick-setup guide has been completed
    # what the quick-setup guide's first page was told the app is for (USES in
    # ui/setupwizard.py). "" = not asked yet: only a brand-new install starts so
    # (first_start), so the question comes once, on the first launch
    use_mode: str = "normal"
    # "Did you know?" tips (soundboard.tips): on / off, the ones shown, the day of the last
    tips_on: bool = True
    tips_seen: list = field(default_factory=list)
    tip_day: str = ""
    voice_discord_tip_shown: bool = False   # "Got it" on the voice changer's Studio notice
    # set up for the app you're using (soundboard.appsetup): ask, apps {exe: simple mode},
    # never [exe]. Older versions keep it untouched
    app_setup: dict = field(default_factory=dict)
    voice_fx: dict = field(default_factory=dict)   # voice changer (see ui.voicepanel)
    speech: dict = field(default_factory=dict)     # text-to-speech / live voice settings
    overlay: dict = field(default_factory=dict)    # in-game overlay (ui.overlay.OverlaySettings)
    bun: dict = field(default_factory=dict)        # Bun mode: on, size, pos (ui.bunmode)
    radio: dict = field(default_factory=dict)      # Radio tab: vol, monitor, favorites, last
    data: dict = field(default_factory=dict)       # Settings > Data & quality (soundboard.quality)
    apps: dict = field(default_factory=dict)       # Apps tab: exe -> {vol, monitor, to, path}
    # Apps tab: a second program with the same .exe name in another folder, by its path
    # (appspanel.path_key) -> {vol, monitor, to, exe}. Its own key, so older versions
    # keep it untouched and only ever see the first program of each name in `apps`
    apps_paths: dict = field(default_factory=dict)
    apps_hidden: list[str] = field(default_factory=list)   # Apps tab: programs taken off with ✕
    apps_categories: list[str] = field(default_factory=list)  # Apps tab: category order
    # Triggers tab: on, interval_ms, monitor (the screen for triggers that don't pick
    # their own), triggers (the Onion Watch add-on's Trigger.to_raw)
    screen: dict = field(default_factory=dict)
    categories: list[str] = field(default_factory=list)   # pad categories, in tab order
    category: str = ""                # the category the Sounds tab shows; "" = all
    # subcategories: {category: [names]}. A sound in one carries the tags "Cat" and
    # "Cat / Sub" (SUB_SEP), so an older version just shows an extra tab
    subcategories: dict = field(default_factory=dict)
    subcategory: str = ""             # the one showing inside `category`; "" = all of it
    category_colors: dict = field(default_factory=dict)   # category -> "#rrggbb" on its tab
    tray: bool = True                 # closing the window keeps the app in the tray
    autostart_hidden: bool = True     # started with Windows: straight to the tray
    # look at GitHub Releases for a newer version, at most every 6 hours (soundboard.updates).
    # Was the opt-in update_check_optin, off by default: renamed so every config starts on
    update_check: bool = True
    update_checked: float = 0.0       # time.time() of the last check
    update_skip: str = ""             # a version the user said to skip
    update_pending: str = ""          # the version an update is installing (see updates.py)
    # the newest version whose What's new (ui/whatsnew.py) was shown; a first start has
    # nothing to catch up on, a config without it is from an older version
    whats_new_seen: str = __version__
    # the version that last moved an older mic part on by itself (ui: _auto_mic_update),
    # so a "No" at Windows' prompt isn't asked again until the next version
    mic_update_tried: str = ""
    random_hotkey: str = ""           # plays a random sound from the category showing
    last_hotkey: str = ""             # plays the last sound played again
    next_cat_hotkey: str = ""         # shows the next category (random key + overlay follow)
    prev_cat_hotkey: str = ""         # ... and the one before
    vol_up_hotkey: str = ""           # sounds 10 % louder
    vol_down_hotkey: str = ""         # sounds 10 % quieter
    mic_hotkey: str = ""              # send my mic on / off
    voice_hotkey: str = ""            # the voice changer on / off
    voice_hold_hotkey: str = ""       # the voice changer on only while held
    hotkeys_off_hotkey: str = ""      # every other hotkey off / on (this one keeps working)
    # a sound's hotkey only works while its category is showing, so one key can play a
    # different sound in each category (keybind profiles)
    scoped_hotkeys: bool = False
    single_click: bool = False        # one click on a pad plays it (not a double-click)
    category_hotkeys: dict = field(default_factory=dict)   # category -> its random-sound key
    # Switch category when a program is in front (soundboard.catswitch): {"game.exe":
    # category}, set by the user from a category's menu; and the switch for all of it
    category_programs: dict = field(default_factory=dict)
    category_programs_on: bool = True
    # instant replay (soundboard.replay): while this hotkey is set, the last
    # replay_seconds of everything you hear (except Onion Board's own sounds) are kept
    # in memory, and the key saves them as a new pad
    replay_hotkey: str = ""
    replay_seconds: int = 30
    # local control API for Stream Deck / scripts (soundboard.remote): off unless turned on
    api_enabled: bool = False
    api_port: int = 7474
    api_token: str = ""
    # "remote" add-ons' own settings (soundboard.ui.remotehost), by add-on id: Onion
    # Pocket's on / off, port and key
    remote_addons: dict = field(default_factory=dict)
    # Settings > Connection (soundboard.net): "direct", "proxy" through
    # net_proxy (socks5h://host:port or http://host:port), or "tor" (soundboard.tor)
    net_mode: str = "direct"
    net_proxy: str = ""
    # Settings > Privacy & security, the switches (soundboard.net.FEATURES): the
    # features switched off (opt-out: everything's on by default), and Offline mode
    net_off: list[str] = field(default_factory=list)
    net_offline: bool = False
    # Network activity's "Keep a history" (soundboard.netlog.keep): off = memory only
    netlog_keep: bool = False
    # "Keep an app log" (soundboard.applog.keep): off = onionboard.log isn't written
    app_log: bool = True
    # "Hide that I'm using Tor": "" (off), "snowflake" or "obfs4" bridges
    tor_bridges: str = ""
    # the anonymous usage count (soundboard.usage; its switch is "usage_stats" in
    # net_off): this PC's random ID, made on the first send, and when the last daily
    # one went. A config without stats_id is from before the count existed.
    stats_id: str = ""
    stats_sent: float = 0.0
    # the installer's "Where did you hear about Onion Board?", sent once with the
    # first-start event (usage.heard_tag tidies it, or drops it)
    stats_heard: str = ""
    # tabs opened since the last daily count, and the newest crash / freeze report
    # already counted (its file time)
    stats_tabs: list[str] = field(default_factory=list)
    stats_problems_seen: float = 0.0
    # when this install started (usage.settle), its first steps already counted, the
    # features used since the last daily count, and the plays counted by then
    stats_started: float = 0.0
    stats_steps: list[str] = field(default_factory=list)
    stats_used: list[str] = field(default_factory=list)
    stats_plays: int = 0
    # seconds the app was open since the last daily count (usage.open_tick)
    stats_open_s: float = 0.0
    # sounds fetched from a link or web search since the last daily count (usage.downloaded)
    stats_downloads: int = 0
    # starts since the last daily count, the version that last ran here (for
    # updated/<from>-to-<to>), and one-off events still waiting to be sent
    stats_launches: int = 0
    stats_version: str = ""
    stats_pending: list[str] = field(default_factory=list)
    # an observed FFmpeg startup/get failure awaiting a verified working copy
    stats_ffmpeg_failed: bool = False
    sounds: list[SoundMeta] = field(default_factory=list)

    # set by load() when the settings weren't read cleanly, for the window to tell the
    # user (not a dataclass field, so it's never saved)
    load_note: ClassVar[str] = ""
    # set by load() when config.json stayed locked: a backup was loaded, and saving
    # would overwrite the user's newest settings with it
    read_only: ClassVar[bool] = False

    @classmethod
    def load(cls) -> Config:
        """Read config.json. A corrupt file is set aside (config.json.broken-<time>)
        and the newest backup that loads is used instead; only if there is none
        do the defaults apply. A missing file with backups beside it (deleted, or lost
        mid-save) is recovered the same way, before a save rotates the backups away.
        A recovered backup is written back as config.json at once.
        The pad list is never silently thrown away."""
        raw, err, missing, locked = None, None, False, False
        for attempt in range(LOAD_TRIES):   # OneDrive / antivirus can hold it for a moment
            try:
                raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))   # sig: a BOM is fine
                locked = False
                break
            except FileNotFoundError as e:
                if not any(CONFIG_PATH.with_name(f"config.json.{i}").exists()
                           for i in range(1, CONFIG_BACKUPS + 1)):
                    return cls.first_start()
                err, missing = e, True
                break
            except ValueError as e:
                err, locked = e, False
                break
            except OSError as e:   # locked (sharing violation, access denied): not damage
                err, locked = e, True
                time.sleep(min(0.2 * (attempt + 1), 1.0))
        if raw is not None:
            try:
                cfg = cls.from_raw(raw)
                cls._keep_newer(raw)
                if isinstance(raw, dict) and "net_off" not in raw:
                    cfg._restore_privacy()
                    if "stats_id" not in raw and "usage_stats" not in cfg.net_off:
                        cfg.net_off.append("usage_stats")   # as from_raw: off for them
                return cfg
            except (TypeError, ValueError, KeyError, AttributeError) as e:
                err = e
        if locked:   # it may be fine: load a backup, but never save over the newest edits
            log.error("config %s stayed locked: %r; not saving this session", CONFIG_PATH, err)
            for name, raw in cls._backups():
                try:
                    cfg = cls.from_raw(raw)
                except (TypeError, ValueError, KeyError, AttributeError):
                    continue
                cfg.read_only = True   # pyright: ignore[reportAttributeAccessIssue]  # ClassVar: per instance here
                cfg.load_note = _("Your settings file was locked by another program, so "   # pyright: ignore[reportAttributeAccessIssue]
                                  "the last copy ({name}) was loaded instead. Changes won't "
                                  "be saved until you restart Onion Board.", name=name)
                return cfg
            cfg = cls()
            cfg.read_only = True   # pyright: ignore[reportAttributeAccessIssue]
            cfg.load_note = _("Your settings file was locked by another program, so "   # pyright: ignore[reportAttributeAccessIssue]
                              "Onion Board started with default settings. Changes won't be "
                              "saved until you restart it.")
            return cfg
        log.error("config %s is unreadable: %r", CONFIG_PATH, err)
        damaged = ""
        if not missing:   # its pads may still be readable (see _salvage)
            with contextlib.suppress(OSError):
                damaged = CONFIG_PATH.read_text(encoding="utf-8-sig", errors="replace")
        broken = "" if missing else cls._set_aside()
        kept = ("" if missing else " " + _("The damaged file was kept as {file}.",
                                           file=broken or "config.json")
                + " " + _("Both files are in {folder}.", folder=CONFIG_PATH.parent))
        for name, raw in cls._backups():
            try:
                cfg = cls.from_raw(raw)
            except (TypeError, ValueError, KeyError, AttributeError):
                log.warning("backup %s doesn't load either", name, exc_info=True)
                continue
            log.warning("recovered settings from backup %s", name)
            back = cls._salvage(cfg, damaged)
            if missing or broken:   # put it back as config.json now, not at the next
                cfg.save()          # change (a damaged file left in place stays kept)
            cfg.load_note = (_("Your settings file was missing, so the last good copy "   # pyright: ignore[reportAttributeAccessIssue]
                               "({name}) was loaded instead.", name=name) if missing else
                             _("Your settings file was damaged, so the last good copy "
                               "({name}) was loaded instead.", name=name)) + back + kept
            return cfg
        cfg = cls()
        back = cls._salvage(cfg, damaged)
        if back and (missing or broken):   # the pads found are on disk again at once
            cfg.save()
        cfg.load_note = (_("Your settings file was missing and no backup could be read, "   # pyright: ignore[reportAttributeAccessIssue]
                           "so Onion Board started with default settings. Your sound files "
                           "are still in {folder}.", folder=SOUNDS_DIR) if missing else
                         _("Your settings file was damaged and no backup could be read, "
                           "so Onion Board started with default settings. Your sound files "
                           "are still in {folder}.", folder=SOUNDS_DIR)) + back + kept
        return cfg

    @classmethod
    def _salvage(cls, cfg: Config, damaged: str) -> str:
        """Pads the recovered settings don't have, put back on the board: the sound
        entries still whole in the damaged file (a file cut off mid-save keeps the pads
        before the cut), then audio in the library's folders that no pad uses (added
        after the backup was made). Adds to cfg.sounds; returns the sentence saying how
        many came back ("" for none)."""
        have = {os.path.normcase(m.file) for m in cfg.sounds}
        ids = {m.id for m in cfg.sounds}
        found: list[SoundMeta] = []
        entries = _sound_entries(damaged)
        if entries:
            v = re.search(r'"version"\s*:\s*(\d{1,4})\b', damaged)
            try:
                found = cls.from_raw({"version": int(v.group(1)) if v else CONFIG_VERSION,
                                      "sounds": entries}).sounds
            except (TypeError, ValueError, KeyError, AttributeError, IndexError):
                log.warning("couldn't read the pads in the damaged config", exc_info=True)
        for p in _library_audio():
            found.append(SoundMeta(id=uuid.uuid4().hex[:10], file=str(p),
                                   name=_OUR_SOUND_FILE.sub("", p.stem, count=1)[:40].strip()
                                   or "Sound", added=_mtime(p)))
        n = 0
        for m in found:
            key = os.path.normcase(m.file)
            if key in have or m.id in ids:
                continue
            have.add(key)
            ids.add(m.id)
            cfg.sounds.append(m)
            n += 1
        if not n:
            return ""
        log.warning("put back %d pad(s) the recovered settings didn't have", n)
        return " " + ngettext("{n} pad was found and put back on the board.",
                              "{n} pads were found and put back on the board.", n)

    @classmethod
    def first_start(cls) -> Config:
        """A new user's settings: what others hear goes straight into their mic (one
        click to set up, nothing to pick in Discord). Settings saved by any earlier
        version keep the route they had (the cable, unless they chose another)."""
        cfg = cls()
        cfg.route = "mic"
        cfg.mic_first = True
        cfg.duck_on = True
        cfg.tabs_off = list(BASIC_TABS_OFF)   # a plain soundboard first; + More tabs adds them
        cfg.use_mode = ""   # the guide asks what it's for (and adds the tabs that fit)
        return cfg

    def _restore_privacy(self):
        """config.json was saved by a version without Privacy & security (an older one
        opened after this, or before it ever ran): take its switches back from
        privacy.json, so a switched-off feature or Tor doesn't quietly come back on
        (and What's new already seen doesn't show again)."""
        try:
            raw = json.loads(_privacy_path().read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            log.warning("couldn't read %s", _privacy_path(), exc_info=True)
            return
        if not isinstance(raw, dict):
            return
        kept = _typed({k: v for k, v in raw.items() if k in SIDE_KEYS}, Config(), "privacy")
        for k, v in kept.items():
            v = clean_setting(k, v)
            if v is not None:
                setattr(self, k, v)
        log.info("an older version saved the settings: privacy settings restored from %s",
                 _privacy_path().name)

    @classmethod
    def _keep_newer(cls, raw: dict):
        """A config written by a newer version has fields this one doesn't know, and
        the next save drops them: keep a copy (config.json.newer) the first time."""
        try:
            version = int(raw.get("version", 1) or 1)
        except (TypeError, ValueError, OverflowError):   # 1e999 is inf
            return
        newer = CONFIG_PATH.with_name("config.json.newer")
        if version <= CONFIG_VERSION or newer.exists():
            return
        try:
            shutil.copy2(CONFIG_PATH, newer)
            log.warning("config is from a newer version (v%s, this one reads v%s): kept a "
                        "copy as %s", version, CONFIG_VERSION, newer.name)
        except OSError:
            log.warning("couldn't keep a copy of the newer config", exc_info=True)

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
        try:   # nothing older than v1 exists
            version = max(1, int(raw.get("version", 1) or 1))
        except OverflowError as e:   # "version": 1e999 reads as inf
            raise ValueError(f"config version {raw.get('version')!r} isn't a number") from e
        for v in range(version, CONFIG_VERSION):
            raw = MIGRATIONS[v](raw)
        if not raw.get("mic_first"):
            # once: the cable route moves to straight into my mic, the main way now (the
            # cable still gets everything until the mic is set up, and alongside it
            # after). main_device stays the cable, so an older version opening these
            # settings still sends through it. Another device or nowhere stays put.
            if raw.get("route", "cable") == "cable":
                raw["route"] = "mic"
            raw["mic_first"] = True
        if not raw.get("duck_on"):
            # once: lowering the sounds while you talk is on by default now (your voice
            # was buried under a song). Off was the old default, so it moves to -12 dB;
            # a depth someone picked stays, and Off picked after this stays off.
            if not raw.get("duck_db"):
                raw["duck_db"] = -12.0
            raw["duck_on"] = True
        sounds = []
        blank = SoundMeta(id="", name="", file="")
        raw_sounds = raw.pop("sounds", [])
        for s in raw_sounds if isinstance(raw_sounds, list) else []:
            if not isinstance(s, dict) or not all(isinstance(s.get(k), str) and s.get(k)
                                                  for k in ("id", "name", "file")):
                log.warning("skipped a damaged sound entry in the config: %r", s)
                continue
            extra = {k: v for k, v in s.items() if k not in SoundMeta.__dataclass_fields__}
            kept = ({"mode": ("restart", s["mode"])}
                    if isinstance(s.get("mode"), str) and s["mode"] not in MODES else {})
            s = _typed(s, blank, f"sound {s['name']!r}")
            for k in ("file", "image"):   # v0.1.0 stored full paths into the old folder
                if s.get(k) and Path(s[k]).is_absolute() and Path(s[k]).is_relative_to(OLD_APP_DIR):
                    s[k] = str(APP_DIR / Path(s[k]).relative_to(OLD_APP_DIR))
            if not Path(s["file"]).is_absolute():
                s["file"] = str(SOUNDS_DIR / s["file"])   # stored relative to the library
            if s.get("image") and not Path(s["image"]).is_absolute():
                s["image"] = str(THUMBS_DIR / s["image"])
            s["tags"] = clean_tags(s.get("tags"))
            s["source"] = sourceinfo.clean(s.get("source"))
            for k in ("fade_in", "fade_out"):
                s[k] = clean_fade(s.get(k))
            for k in ("delay", "cooldown"):
                if k in s:
                    s[k] = clean_wait(s[k], k)
            if s.get("mode") not in MODES:
                s["mode"] = "restart"
            for k, lo, hi in (("volume", 0.0, 2.0), ("level_gain", 0.1, 6.0),
                              ("plays", 0, 10**9), ("added", 0.0, 1e11)):
                if k in s:   # the Edit dialog's slider can't take any number
                    s[k] = min(max(s[k], lo), hi)
            m = SoundMeta(**s)
            if extra:   # not dataclass fields on purpose (see _raw_extra above)
                m._raw_extra = extra   # pyright: ignore[reportAttributeAccessIssue]
            if kept:
                m._raw_kept = kept   # pyright: ignore[reportAttributeAccessIssue]
            sounds.append(m)
        # configs from before the setup guide existed: whoever already picked an output
        # device has been set up by hand, so don't greet them with the guide
        raw.setdefault("setup_done", bool(raw.get("main_device")))
        # ...and from before What's new: everything in it is new to them
        raw.setdefault("whats_new_seen", "")
        # ...and from before the usage count: they installed an app that sent nothing,
        # so it starts switched off for them (new installs: on, unless the installer's
        # box was unticked)
        if "stats_id" not in raw:
            raw["stats_id"] = ""
            off = raw.get("net_off")
            if isinstance(off, list) and "usage_stats" not in off:
                raw["net_off"] = [*off, "usage_stats"]
            elif "net_off" not in raw:
                raw["net_off"] = ["usage_stats"]
        known = _typed(raw, cls(), "config")
        extra = {k: v for k, v in raw.items() if k not in cls.__dataclass_fields__}
        kept = {}
        for k, v in list(known.items()):
            if v is None:   # a device: None is the system default
                continue
            known[k] = clean_setting(k, v)
            if known[k] is None:
                log.warning("ignored config setting %s=%r (out of range)", k, v)
                del known[k]
            elif k in NEWER_CHOICES and known[k] != v:
                kept[k] = (known[k], v)
        known["version"] = CONFIG_VERSION
        cfg = cls(**known, sounds=sounds)
        if extra:   # not dataclass fields on purpose (see _raw_extra above)
            cfg._raw_extra = extra   # pyright: ignore[reportAttributeAccessIssue]
        if kept:
            cfg._raw_kept = kept   # pyright: ignore[reportAttributeAccessIssue]
        # a "Cat / Sub" tab (an older version saved one for a subcategory, or a name
        # typed with " / " before there were any) is the subcategory again
        cats, cfg.categories = clean_tags(cfg.categories), []
        merge_tags(cats, cfg.categories, cfg.subcategories)
        for m in sounds:   # a category a sound is in always has a tab
            m.tags = merge_tags(m.tags, cfg.categories, cfg.subcategories)
        if cfg.category not in cfg.categories:
            cfg.category = ""
        if cfg.subcategory not in cfg.subcategories.get(cfg.category, []):
            cfg.subcategory = ""
        return cfg

    def to_raw(self) -> dict:
        d = _with_raw(asdict(self), self)
        d["version"] = CONFIG_VERSION
        for s, m in zip(d["sounds"], self.sounds):
            _with_raw(s, m)
        # files inside the library are stored by name only, so the whole
        # %APPDATA%\OnionBoard folder can move or be restored
        for s in d["sounds"]:
            s["file"] = _stored_path(s["file"], SOUNDS_DIR, True)
            if s["image"]:
                s["image"] = _stored_path(s["image"], THUMBS_DIR, False)
        return d

    def save(self) -> bool:
        """Write atomically, keeping the last CONFIG_BACKUPS good copies. Returns
        False (and logs) instead of raising. Blocks while the disk is slow (an
        antivirus scan can take seconds): the window saves through Saver instead."""
        if self.read_only:
            log.warning("not saving settings: config.json was locked at startup")
            return False
        return _write(self.snapshot())

    def snapshot(self) -> tuple[int, dict, str]:
        """Everything save() writes, copied now (on the thread that changes the config)
        so another thread can write it. The number orders snapshots: an older one is
        never written over a newer one."""
        global _snap_seq
        # not _write_lock: the writer holds that while it's on the disk, and a slow
        # disk would freeze the window that's only copying the settings
        with _seq_lock:
            _snap_seq += 1
            seq = _snap_seq
        return (seq, self.to_raw(),
                json.dumps({k: getattr(self, k) for k in SIDE_KEYS}, indent=2))


_write_lock = threading.Lock()   # one writer at a time: Saver's thread or a direct save()
_seq_lock = threading.Lock()     # numbering snapshots (never held across disk I/O)
_snap_seq = 0       # the last snapshot's number (Config.snapshot)
_written_seq = 0    # ...and the newest one written


def _write_privacy(text: str):
    path = _privacy_path()
    try:
        if path.read_text(encoding="utf-8") == text:
            return
    except OSError:
        pass
    try:
        atomic_write_text(path, text)
    except OSError:
        log.warning("couldn't save %s", path, exc_info=True)


def _durable_tmp(path: Path, text: str) -> Path:
    """`text` in a new temp file next to `path`, flushed to the disk (fsync) before it
    returns: renamed over `path` without that, a power cut could leave `path` empty or
    full of NULs. The temp file is removed if writing it fails."""
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return tmp


def atomic_write_text(path: Path, text: str):
    """Replace `path` with `text` so a crash or power cut leaves the old file or the new
    one, never a broken one. Raises OSError."""
    tmp = _durable_tmp(Path(path), text)
    try:
        _replace(tmp, Path(path))
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _replace(tmp: Path, path: Path, tries: int = 6):
    """tmp.replace(path), tried again for a moment while something (an antivirus scan,
    the search indexer, a backup tool) has `path` open: one such lock made a whole
    save fail and showed "Couldn't save your settings" though the next save was fine."""
    for i in range(tries):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.05 * (i + 1))


def _write(snap: tuple[int, dict, str]) -> bool:
    """Write a Config.snapshot() to config.json (+ privacy.json), unless a newer one
    is already there."""
    global _written_seq
    seq, raw, privacy = snap
    with _write_lock:
        if seq < _written_seq:
            return True   # a newer snapshot got there first
        try:
            APP_DIR.mkdir(parents=True, exist_ok=True)
            text = json.dumps(raw, indent=2)
            _write_privacy(privacy)
            damaged = False
            try:
                old = CONFIG_PATH.read_text(encoding="utf-8-sig")
                if old == text:
                    _written_seq = seq
                    return True   # nothing changed: don't churn the backups
                # a damaged file that couldn't be set aside isn't a backup: rotating it
                # in would push out a good one
                damaged = not isinstance(json.loads(old), dict)
            except ValueError:   # includes UnicodeDecodeError
                damaged = True
            except OSError:
                pass
            tmp = _durable_tmp(CONFIG_PATH, text)
            try:
                if CONFIG_PATH.exists() and not damaged and _rotate_due():
                    try:
                        _rotate_backups()
                        _rotated[CONFIG_PATH] = time.monotonic()
                    except OSError:   # a backup locked for a moment mustn't block the save
                        log.warning("couldn't rotate the config backups", exc_info=True)
                _replace(tmp, CONFIG_PATH)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
            _written_seq = seq
            return True
        except OSError:
            log.exception("couldn't save settings to %s", CONFIG_PATH)
            return False


class Saver:
    """Saves a Config on a background thread, so a slow disk (an antivirus scan of
    the new file took 2-7 s) doesn't freeze the window. save() copies the settings
    right away; the newest copy is the one written, and `done(ok)` is called on the
    saver's thread after each write. save(then) keeps `then` until a write covers that
    copy; finished() hands it back with how that write went."""

    def __init__(self, cfg: Config, done=None):
        self.cfg = cfg
        self._done = done
        self._cond = threading.Condition()
        self._pending: tuple | None = None
        self._pending_n = 0                  # the save() that copy is from
        self._count = 0                      # save() calls so far
        self._then: list[tuple[int, Callable[[bool], None]]] = []
        self._written: collections.deque[tuple[int, bool]] = collections.deque(maxlen=64)
        self._busy = False
        self._thread: threading.Thread | None = None

    def save(self, then: Callable[[bool], None] | None = None):
        with self._cond:
            self._count += 1
            n = self._count
            if then is not None:
                self._then.append((n, then))
        if self.cfg.read_only:   # logs it; nothing to write
            ok = self.cfg.save()
            with self._cond:
                self._written.append((n, ok))
            if self._done:
                self._done(ok)
            return
        snap = self.cfg.snapshot()
        with self._cond:
            self._pending, self._pending_n = snap, n
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="config-save",
                                                daemon=True)
                self._thread.start()
            self._cond.notify_all()

    def _run(self):
        while True:
            with self._cond:
                while self._pending is None:
                    # timed out with nothing pending: idle, the next save starts a new
                    # thread (a save() can take the lock as the wait times out: still
                    # this thread's to write)
                    if not self._cond.wait(30) and self._pending is None:
                        self._thread = None
                        return
                snap, n, self._pending, self._busy = self._pending, self._pending_n, None, True
            try:
                ok = _write(snap)
            except Exception:  # noqa: BLE001 - a save must never kill the saver
                log.exception("saving settings failed")
                ok = False
            with self._cond:
                self._busy = False
                self._written.append((n, ok))   # every save() up to n is in this one
                self._cond.notify_all()
            if self._done:
                try:
                    self._done(ok)
                except Exception:  # noqa: BLE001
                    log.exception("after saving settings")

    def finished(self) -> list[tuple[Callable[[bool], None], bool]]:
        """The save(then)s whose copy (or a newer one) has been written since, each with
        how that write went (ok). Call it from the thread `then` belongs to."""
        with self._cond:
            out, keep = [], []
            for n, then in self._then:
                ok = next((w_ok for w_n, w_ok in self._written if w_n >= n), None)
                if ok is None:
                    keep.append((n, then))
                else:
                    out.append((then, ok))
            self._then = keep
            return out

    def flush(self, timeout: float = 10.0) -> bool:
        """Wait until everything handed to save() is written. True when it is."""
        end = time.monotonic() + timeout
        with self._cond:
            while self._pending is not None or self._busy:
                left = end - time.monotonic()
                if left <= 0:
                    return False
                self._cond.wait(left)
        return True

MAX_FADE_S = 10.0
MAX_DELAY_S = 10.0      # a sound's "wait before playing"
MAX_COOLDOWN_S = 60.0   # a sound's "ignore presses for"
MODES = ("restart", "overlap", "toggle", "solo", "queue")   # SoundMeta.mode
# how a pad press plays each mode: the default ("restart") is one sound at a time, a new
# one stops the others (it only restarted itself before); "solo" is the same now, and
# Overlap is the way to layer sounds. A Queue sound starts once the others are done.
PRESS_MODE = {"restart": "solo", "queue": "restart"}


def sorted_sounds(sounds: list[SoundMeta], how: str) -> list[SoundMeta]:
    """The sounds in the Sounds tab's order `how` (PAD_SORTS). Ties keep the board's
    own order; sounds from before `added` was kept count as older than any since, and
    among themselves the later in the board the newer (new sounds are added at the end)."""
    if how == "name":
        return sorted(sounds, key=lambda m: m.name.casefold())
    if how == "plays":
        return sorted(sounds, key=lambda m: -m.plays)
    if how == "newest":
        order = {id(m): i for i, m in enumerate(sounds)}
        return sorted(sounds, key=lambda m: (-m.added, -order[id(m)]))
    return list(sounds)


def clean_fade(v) -> float:
    """A fade length in seconds, 0..MAX_FADE_S (anything unreadable is no fade)."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.0
    return min(max(v, 0.0), MAX_FADE_S) if v == v else 0.0


def clean_wait(v, kind: str = "delay") -> float:
    """A delay or cooldown in seconds, within its slider (anything unreadable is 0)."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.0
    hi = MAX_COOLDOWN_S if kind == "cooldown" else MAX_DELAY_S
    return min(max(v, 0.0), hi) if v == v else 0.0


SUB_SEP = " / "   # "Cat / Sub": the tag a sound in a subcategory carries (besides "Cat")


def split_tag(tag: str) -> tuple[str, str]:
    """("Cat", "Sub") for "Cat / Sub", ("Cat", "") for a plain category."""
    cat, sep, sub = tag.partition(SUB_SEP)
    return (cat, sub) if sep else (tag, "")


def sub_tag(cat: str, sub: str) -> str:
    return f"{cat}{SUB_SEP}{sub}"


def plain_name(name: str) -> str:
    """A name typed for a category or subcategory: one that can't be mistaken for a
    "Cat / Sub" tag."""
    return (clean_tags([name.replace(SUB_SEP, " - ")]) or [""])[0]


def clean_tags(tags) -> list[str]:
    """Category names: strings, trimmed, at most 30 characters, no duplicates
    (ignoring case), in order. A "Cat / Sub" tag keeps 30 characters of each part."""
    out, seen = [], set()
    for t in tags if isinstance(tags, list) else []:
        if not isinstance(t, str):
            continue
        cat, sub = split_tag(t.strip())
        cat, sub = cat.strip()[:30].strip(), sub.strip()[:30].strip()
        t = sub_tag(cat, sub) if cat and sub else cat
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def in_view(tags: list[str], cat: str, sub: str = "") -> bool:
    """Is a sound with `tags` on the Sounds tab showing `cat` (and its subcategory
    `sub`)? "" for `cat` is every sound."""
    if not cat:
        return True
    return (sub_tag(cat, sub) if sub else cat) in tags


def sub_names(tags: list[str], cat: str) -> list[str]:
    """The subcategories of `cat` that `tags` are in."""
    return [s for c, s in map(split_tag, tags) if s and c == cat]


def merge_tags(tags: list[str], categories: list[str],
               subs: dict | None = None) -> list[str]:
    """`tags` spelled the way `categories` already spells them (ignoring case), so an
    imported "memes" lands in the existing "Memes". Tags that aren't a category yet
    are appended to `categories`, which is changed in place. A "Cat / Sub" tag is no
    tab of its own: "Cat" is added (to the tags and `categories`) and, when `subs`
    is given, "Sub" is listed in it under "Cat"."""
    by_lower = {c.lower(): c for c in categories}

    def top(name: str) -> str:
        c = by_lower.get(name.lower())
        if c is None:
            categories.append(name)
            c = by_lower[name.lower()] = name
        return c

    out = []
    for t in clean_tags(tags):
        cat, sub = split_tag(t)
        cat = top(cat)
        if sub:
            known = subs.setdefault(cat, []) if subs is not None else []
            sub = {k.lower(): k for k in known}.get(sub.lower(), sub)
            if subs is not None and sub not in known:
                known.append(sub)
            out.append(cat)
            out.append(sub_tag(cat, sub))
        else:
            out.append(cat)
    return list(dict.fromkeys(out))


def group_pack_tags(sounds: list, pack_name: str, own: set[str] | None = None) -> bool:
    """A pack with several categories goes into one tab named after it, each of its
    categories a subcategory ("GM starter pack" with Tavern, Combat…) rather than a tab
    apiece: a sound's tags become [pack, "pack / category"]. `own` limits it to those
    categories (lower case), so a category the user added to a pack's sound stays as it
    is; None is every tag. Returns whether anything moved."""
    group = plain_name(pack_name)
    if not group:
        return False
    moved = False
    for m in sounds:
        tags, hit = [], False
        for t in m.tags:
            c, sub = split_tag(t)
            if sub or c.lower() == group.lower() or (own is not None and c.lower() not in own):
                tags.append(t)
            else:
                tags += [group, sub_tag(group, c)]
                hit = True
        if hit:
            m.tags = clean_tags(tags)
            moved = True
    return moved


def _privacy_path() -> Path:
    return CONFIG_PATH.with_name("privacy.json")


_rotated: dict[Path, float] = {}   # config path -> when its backups last rotated


def _rotate_due() -> bool:
    """Rotate the backups now? A volume slider dragged about saves many times a
    minute: rotating on each one copied the file every time and soon pushed out
    every copy older than a few seconds. Once an hour keeps .1 the settings as
    they were when this session (or hour) began."""
    last = _rotated.get(CONFIG_PATH)
    return last is None or time.monotonic() - last >= ROTATE_EVERY_S


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
    """The app's own FFmpeg (ffmpegget downloads it there when winget can't fix one),
    else ffmpeg on PATH, or where winget links it (the installer's M4A/video option uses
    winget, and a process started before that doesn't see the new PATH yet)."""
    own = APP_DIR / "ffmpeg" / "bin" / "ffmpeg.exe"
    if os.name == "nt" and own.is_file():
        return str(own)
    found = shutil.which("ffmpeg")
    if found:
        return found
    for env, sub in (("LOCALAPPDATA", "Microsoft/WinGet/Links"),   # per-user install
                     ("ProgramFiles", "WinGet/Links")):            # machine-wide install
        base = os.environ.get(env)
        if base and (Path(base) / sub / "ffmpeg.exe").is_file():
            return str(Path(base) / sub / "ffmpeg.exe")
    return None


def _ffmpeg_words(stderr: str) -> str:
    """ffmpeg's error as words for people ("[out#0/f32le @ 0000…] Output file does not
    contain any stream" was shown as is); the original goes to the log."""
    s = stderr.lower()
    if (not s or "does not contain any stream" in s or "matches no streams" in s
            or "output file is empty" in s):
        return _("this file has no audio in it")
    if "invalid data found" in s or "could not find codec" in s or "unknown format" in s:
        return _("It isn't a sound file that can be read, or it's damaged.")
    return stderr


# A file is read a second at a time, whatever its length. A sound up to STREAM_S comes
# back whole (float32 in RAM, as it always did); a longer one never is: it's resampled,
# measured and written into its cache (and its converted copy) piece by piece, then
# played from the cache file (mapped). A two-hour import used to hold its float32 audio
# (2.8 GB) and a few copies of it at once; now it holds about a second of it.
STREAM_S = 60
LEVEL_WIN = 2400   # level_gain's blocks (50 ms); a second (SR) is a whole number of them


class _SourceError(Exception):
    """libsndfile couldn't open or read the file: ffmpeg gets a go (m4a/aac/video etc.)."""


def _stereo(x: np.ndarray) -> np.ndarray:
    if x.shape[1] == 1:
        return np.repeat(x, 2, axis=1)
    return x[:, :2] if x.shape[1] > 2 else x


def _sf_pieces(f, left: int):
    while left > 0:
        try:
            x = f.read(frames=min(f.samplerate, left), dtype="float32", always_2d=True)
        except Exception as e:  # noqa: BLE001 - libsndfile opened it but can't decode it
            raise _SourceError(e) from e
        if not len(x):
            return
        left -= len(x)
        yield x


@contextlib.contextmanager
def _sf_source(path: str):
    """(rate, pieces) of the file's first MAX_SECONDS, by libsndfile."""
    try:
        f = sf.SoundFile(path)
    except Exception as e:  # noqa: BLE001
        raise _SourceError(e) from e
    with f:
        yield f.samplerate, _sf_pieces(f, int(MAX_SECONDS * f.samplerate))


class _Stopwatch:
    """Kills ffmpeg once it has been waited on for FFMPEG_TIMEOUT in all: only the time
    spent waiting for its audio counts, not the import's own work on each piece."""

    def __init__(self, p: subprocess.Popen, out):
        self.p, self.out, self.spent, self.since, self.fired = p, out, 0.0, None, False
        self.done = threading.Event()
        threading.Thread(target=self._run, daemon=True, name="ffmpeg-timeout").start()

    def _run(self):
        while not self.done.wait(0.25):
            since = self.since
            if since is not None and self.spent + time.monotonic() - since > FFMPEG_TIMEOUT:
                self.fired = True
                self.p.kill()
                return

    def read(self, n: int) -> bytes:
        self.since = time.monotonic()
        try:
            return self.out.read(n)
        finally:
            self.spent += time.monotonic() - self.since
            self.since = None


def _ffmpeg_pieces(path: str, p: subprocess.Popen, err, watch: _Stopwatch):
    got = 0
    while True:
        b = watch.read(SR * 8)   # a second of f32le stereo
        if not b:
            break
        n = len(b) // 8 * 8
        got += n
        if n:
            yield np.frombuffer(b, np.float32, count=n // 4).reshape(-1, 2)
    code = p.wait()
    if watch.fired:
        raise RuntimeError(_("ffmpeg took longer than {seconds}s", seconds=FFMPEG_TIMEOUT))
    if code != 0 or not got:
        err.seek(0)
        msg = err.read().decode(errors="ignore").strip()
        log.info("ffmpeg couldn't decode %s: %s", path, msg)
        raise RuntimeError(_ffmpeg_words(msg))


@contextlib.contextmanager
def _ffmpeg_source(path: str, cause: BaseException | None = None):
    """(SR, pieces) of the file's first MAX_SECONDS, by ffmpeg (streamed, never all of
    its output at once). The process is gone when this ends, however it ends."""
    ff = _ffmpeg()
    if not ff:
        from soundboard import usage   # the name only, never the file
        usage.used("needs-ffmpeg")
        raise RuntimeError(_("This file needs FFmpeg to play. Get it in "
                             "Settings > Data & quality.")) from cause
    with tempfile.TemporaryFile() as err:
        try:
            p = subprocess.Popen([ff, "-v", "error", "-i", path, "-vn", "-t", str(MAX_SECONDS),
                                  "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=err,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:   # a broken ffmpeg: about the file's format, not the disk
            raise RuntimeError(str(e)) from e
        out = p.stdout
        assert out is not None   # stdout=PIPE
        watch = _Stopwatch(p, out)
        try:
            yield SR, _ffmpeg_pieces(path, p, err, watch)
        finally:
            watch.done.set()
            if p.poll() is None:
                p.kill()
            out.close()
            p.wait()


class _Long(NamedTuple):
    """A sound over STREAM_S, imported straight into its cache (_read)."""
    audio: np.ndarray    # (n, 2) int16, mapped from the cache file
    gain: float          # level_gain() of it
    frames: int
    via_ffmpeg: bool


def _read(path: str, sid: str | None = None,
          store: Callable[[bool], Path | None] | None = None) -> tuple[np.ndarray, bool] | _Long:
    """(audio as (n, 2) float32 at SR, decoded-by-ffmpeg?), or with `sid`, for a sound
    over STREAM_S: a _Long, its audio already in sid's cache and, when store(via_ffmpeg)
    names a file, saved there as it was decoded (write_stored's format).

    Only the first MAX_SECONDS are ever read: libsndfile is asked for that many
    frames and ffmpeg is given -t."""
    try:
        return _read_from(path, sid, store, None)
    except _SourceError as e:
        log.debug("libsndfile can't read %s (%s); trying ffmpeg", path, e.__cause__)
        return _read_from(path, sid, store, e.__cause__)


def _read_from(path, sid, store, ffmpeg_cause):
    via_ffmpeg = ffmpeg_cause is not None
    src = _ffmpeg_source(path, ffmpeg_cause) if via_ffmpeg else _sf_source(path)
    with src as (rate, pieces):
        head, n = [], 0
        for x in pieces:
            head.append(_stereo(x))
            n += len(x)
            if sid is not None and n > STREAM_S * rate:
                rest = (_stereo(x) for x in pieces)
                return _stream(itertools.chain(head, rest), rate, sid,
                               store(via_ffmpeg) if store else None, via_ffmpeg)
        data = np.concatenate(head) if head else np.zeros((0, 2), np.float32)
    del head
    if rate != SR:
        data = soxr.resample(data, rate, SR, quality="VHQ").astype(np.float32, copy=False)
    return np.ascontiguousarray(data, dtype=np.float32), via_ffmpeg


def _decode(path: str) -> tuple[np.ndarray, bool]:
    """(audio as (n, 2) float32 at SR, decoded-by-ffmpeg?), whole."""
    got = _read(path)
    assert not isinstance(got, _Long)   # only with a sid
    return got


def decode(path: str) -> np.ndarray:
    """Decode any audio file to (n, 2) float32 at SR with high-quality resampling."""
    return _decode(path)[0]


_NPY_HEAD = 128   # a streamed cache file's header, written last when the length is known


def _npy_header(f, frames: int) -> None:
    """The .npy header of (frames, 2) int16, padded to _NPY_HEAD bytes (np.load reads it)."""
    h = f"{{'descr': '<i2', 'fortran_order': False, 'shape': ({frames}, 2), }}"
    h = h.ljust(_NPY_HEAD - 11) + "\n"
    f.seek(0)
    f.write(b"\x93NUMPY\x01\x00" + struct.pack("<H", len(h)) + h.encode("latin1"))


def _i16(x: np.ndarray) -> np.ndarray:
    """to_int16's rounding of float audio already under full scale (or limited)."""
    y = x * I16
    np.rint(y, out=y)
    np.clip(y, -I16 - 1, I16, out=y)
    return y.astype("<i2")


def _stream(pieces, rate: int, sid: str, store: Path | None, via_ffmpeg: bool) -> _Long:
    """The streamed half of _read: resample, then a second at a time measure the level
    and write the stored copy and the int16 cache. Exactly what decode → write_stored →
    level_gain → store_cached make of the whole thing: to_int16 turns a sound that
    goes over full scale down with the limiter (_under_full_scale, run a second at a
    time from the start), else only rounds it. Which one is known only at the end, so
    both are written and the right one kept."""
    from soundboard.sendfx import Limiter
    rs = soxr.ResampleStream(rate, SR, 2, dtype="float32", quality="VHQ") if rate != SR else None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = cache_path(sid)
    tag = uuid.uuid4().hex[:8]   # unique: another thread may be writing this sound's cache
    tmp = {False: dest.with_name(f"{sid}.{tag}.tmp.npy"),
           True: dest.with_name(f"{sid}.{tag}.lim.tmp.npy")}
    lim = Limiter(SR, ceiling_db=-0.05)
    st = {"n": 0, "lim_n": 0, "skip": lim.la, "peak": 0.0}
    rms: list[np.ndarray] = []
    try:
        with contextlib.ExitStack() as stack:
            files = {k: stack.enter_context(open(p, "wb")) for k, p in tmp.items()}
            for f in files.values():
                f.write(bytes(_NPY_HEAD))
            out = stack.enter_context(_stored_writer(store)) if store is not None else None

            def limited(y):
                d = min(st["skip"], len(y))   # the limiter's first `la` frames are its delay
                y, st["skip"] = y[d:], st["skip"] - d
                y = y[:st["n"] - st["lim_n"]]
                if len(y):
                    files[True].write(_i16(y).tobytes())
                    st["lim_n"] += len(y)

            def second(x):
                st["peak"] = max(st["peak"], float(np.max(np.abs(x))))
                rms.append(_block_rms(x))
                if out is not None:
                    out.write(x)
                files[False].write(_i16(x).tobytes())
                st["n"] += len(x)
                limited(lim.process(x))

            buf = np.zeros((0, 2), np.float32)

            def feed(y):
                nonlocal buf
                buf = np.concatenate([buf, y]) if len(buf) else y
                while len(buf) >= SR:
                    second(np.ascontiguousarray(buf[:SR], np.float32))
                    buf = buf[SR:]

            for x in pieces:
                feed(rs.resample_chunk(x) if rs is not None else x)
            if rs is not None:
                feed(rs.resample_chunk(np.zeros((0, 2), np.float32), last=True))
            if len(buf):
                second(np.ascontiguousarray(buf, np.float32))
            limited(lim.process(np.zeros((lim.la, 2), np.float32)))   # push the delay out
            for f in files.values():
                _npy_header(f, st["n"])
        keep = tmp[st["peak"] > 1.0]
        try:
            keep.replace(dest)
            _refused.discard(dest)   # a new file there: in use again, not a leftover
        except OSError:   # dest mapped by audio still in use: play the new file where it is
            log.warning("couldn't put the cache of %s in place", sid, exc_info=True)
            dest = keep
        audio = mapped.load(dest)
    finally:
        for p in tmp.values():
            if p != dest:
                p.unlink(missing_ok=True)
    gain = _gain(float(st["peak"]), np.concatenate(rms) if rms else np.zeros(0, np.float32))
    return _Long(audio, gain, st["n"], via_ffmpeg)


def to_int16(data: np.ndarray) -> np.ndarray:
    """float32 [-1, 1] -> int16 (the in-memory / cached format). int16 passes through.
    Peaks over full scale (loud MP3 / AAC masters decode up to ~+1.5 dB, and resampling
    adds a little) are turned down by a limiter first: clipped here, the flat tops
    would be in the cache for good, crackling on every kick and snare."""
    if data.dtype == np.int16:
        return data
    if len(data) and float(np.max(np.abs(data))) > 1.0:
        data = _under_full_scale(data)
    # one float copy, rounded and clipped in place: a 15-minute song is ~350 MB of
    # float32, and each temporary would be another
    y = data * I16
    np.rint(y, out=y)
    np.clip(y, -I16 - 1, I16, out=y)
    return np.ascontiguousarray(y.astype(np.int16))


def _under_full_scale(data: np.ndarray, chunk: int = SR) -> np.ndarray:
    """(n, 2) audio through a lookahead limiter just under 0 dBFS (sendfx.Limiter: no
    distortion, the level elsewhere untouched), a second at a time."""
    from soundboard.sendfx import Limiter
    if data.ndim != 2 or data.shape[1] != 2:
        return data              # (only stereo is stored; anything else just clips)
    lim = Limiter(SR, ceiling_db=-0.05)
    n = len(data)
    out = np.empty((n, 2), np.float32)
    at, skip = 0, lim.la         # the limiter's first `la` samples are its delay line

    def put(y):
        nonlocal at, skip
        d = min(skip, len(y))
        y, skip = y[d:], skip - d
        k = min(len(y), n - at)
        out[at:at + k] = y[:k]
        at += k

    for i in range(0, n, chunk):
        put(lim.process(np.asarray(data[i:i + chunk], np.float32)))
    put(lim.process(np.zeros((lim.la, 2), np.float32)))   # push the delay out
    return out


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
    """The cached int16 audio for a sound, or None if there is none (or it's damaged).
    A long one stays on disk, memory-mapped (soundboard.mapped)."""
    p = cache_path(sid, fx_key)
    if not p.exists():
        return None
    try:
        data = mapped.load(p)
        if data.dtype == np.int16 and data.ndim == 2 and data.shape[1] == 2:
            return data
        log.warning("cache %s has the wrong shape/dtype; ignoring it", p.name)
    except Exception:  # noqa: BLE001
        log.warning("cache %s is unreadable; ignoring it", p.name, exc_info=True)
    return None


def store_cached(sid: str, data: np.ndarray, fx_key: str = "") -> np.ndarray:
    """Write a sound's audio to the cache (atomically) and return it as int16 (a long
    one mapped from the file written, soundboard.mapped)."""
    i16 = to_int16(data)
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        dest = cache_path(sid, fx_key)
        tmp = dest.with_name(f"{dest.stem}.{uuid.uuid4().hex[:8]}.tmp.npy")   # unique per writer
        try:
            np.save(tmp, i16)
            _replace(tmp, dest)   # another writer's replace can hold dest a moment
        finally:
            tmp.unlink(missing_ok=True)
        _refused.discard(dest)   # a new file there: in use again, not a leftover
    except OSError:   # e.g. dest is mapped by audio still in use: prune_cache tidies up
        log.warning("couldn't write cache for %s", sid, exc_info=True)
        return i16
    return mapped.adopt(i16, dest)   # a long one: the file, not this copy


def load_original(meta: SoundMeta) -> np.ndarray:
    """int16 audio of the sound as imported (no effects): cache, else decode."""
    data = load_cached(meta.id)
    if data is None:
        got = _read(meta.file, meta.id)   # a long one goes straight into the cache
        data = got.audio if isinstance(got, _Long) else store_cached(meta.id, got[0])
    return data


def decode_int16(path: str) -> tuple[np.ndarray, float]:
    """(int16 audio, level_gain) of a file that isn't a sound of the library (a link
    played before it's added). A long one is streamed into a cache file of its own
    (mapped; prune_cache takes it once nothing plays it), like an import."""
    got = _read(path, f"play-{uuid.uuid4().hex[:10]}")
    if isinstance(got, _Long):
        return got.audio, got.gain
    return to_int16(got[0]), level_gain(got[0])


class Cancelled(Exception):
    """A render given up on partway (render_cached's `cancel`): a newer one replaced it."""


def load_sound(meta: SoundMeta, cancel: Callable[[], bool] | None = None) -> np.ndarray:
    """int16 audio for a library sound as it plays, effects included. The first
    load after its effects change renders them (slow for long sounds); after that
    it is one file read. cancel: see render_cached."""
    from soundboard import soundfx
    key = soundfx.key(meta.fx)
    if not key:
        return load_original(meta)
    data = load_cached(meta.id, key)
    if data is None:
        data = render_cached(meta.id, load_original(meta), meta.fx, cancel)
    return data


REVERSE_CHUNK = 1 << 20   # frames swapped at a time when a render is reversed on disk


def _reverse_frames(path: Path, frames: int) -> None:
    """Reverse the frames of a (frames, 2) int16 .npy in place, a piece at a time."""
    if frames < 2:
        return
    mm = np.load(path, mmap_mode="r+")
    lo, hi = 0, frames
    while hi - lo > 1:
        k = min(REVERSE_CHUNK, (hi - lo) // 2)
        a = mm[lo:lo + k][::-1].copy()
        mm[lo:lo + k] = mm[hi - k:hi][::-1]
        mm[hi - k:hi] = a
        lo, hi = lo + k, hi - k
    mm.flush()
    del mm   # unmapped now: Windows can't rename a file that's still mapped


def render_cached(sid: str, data: np.ndarray, fx: dict | None,
                  cancel: Callable[[], bool] | None = None) -> np.ndarray:
    """Render a sound's effects (soundfx.render_into) straight into its cache file for
    these effects and return it as int16 (a long one mapped, soundboard.mapped). Only
    a few seconds of it are in memory at a time, however long it is. If the file
    can't be written it's rendered in memory instead, like store_cached does.
    cancel: asked between pieces; True stops the render (raises Cancelled, nothing
    kept). A 2-hour song's pitch shift takes minutes, and each edit saved meanwhile
    started another one alongside it."""
    from soundboard import soundfx
    key = soundfx.key(fx)
    if not key:
        return to_int16(data)   # nothing to render (never trimmed either)
    dest = cache_path(sid, key)
    tmp = dest.with_name(f"{dest.stem}.{uuid.uuid4().hex[:8]}.tmp.npy")
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(tmp, "wb") as f:
            n = 0

            def start():
                nonlocal n
                f.seek(0)
                f.truncate()
                f.write(bytes(_NPY_HEAD))
                n = 0

            def put(x):
                nonlocal n
                if cancel is not None and cancel():
                    raise Cancelled
                f.write(_i16(x).tobytes())        # x is in [-1, 1]: no limiter
                n += len(x)

            soundfx.render_into(data, fx, start, put)
            _npy_header(f, n)
        if soundfx.clean(fx)["reverse"]:
            _reverse_frames(tmp, n)
        tmp.replace(dest)
        _refused.discard(dest)
    except OSError:   # e.g. dest is mapped by audio still in use: prune_cache tidies up
        log.warning("couldn't write the effects cache for %s; rendering in memory", sid,
                    exc_info=True)
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        return to_int16(soundfx.render(data, fx))
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise
    out = load_cached(sid, key)
    return out if out is not None else to_int16(soundfx.render(data, fx))


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
    effects versions that were replaced. Recent files of a sound `keep` doesn't know
    are left alone, like thumbs.prune does: an import still running has stored its
    cache (or is writing its .tmp.npy) before the sound joins the library."""
    ids = {k.split(".")[0] for k in keep}
    try:
        files = list(CACHE_DIR.glob("*.npy"))
    except OSError:
        log.debug("cache prune failed", exc_info=True)
        return
    for p in files:
        if p.stem in keep:
            continue
        fresh = ((p.name.split(".")[0] not in ids or p.name.endswith(".tmp.npy"))
                 and p not in _refused)
        try:
            if fresh and time.time() - p.stat().st_mtime < CACHE_GRACE_S:
                continue
        except OSError:
            continue
        _unlink(p)


def _unlink(p: Path) -> bool:
    """Delete a cache file. False if it can't go yet: Windows refuses while a mapped
    array still points into it (a sound just removed, still on its way out of the
    engine). It isn't in cache_keep any more, so the next prune_cache takes it (at
    once, not after CACHE_GRACE_S: it's in _refused)."""
    try:
        p.unlink(missing_ok=True)
    except OSError:
        log.debug("cache file %s is still in use; left for later", p.name)
        _refused.add(p)
        return False
    _refused.discard(p)
    return True


def unlink_cache(sid: str) -> None:
    """Delete every cache file of a sound (its original and effects versions)."""
    try:
        files = list(CACHE_DIR.glob(f"{sid}*.npy"))
    except OSError:
        return
    for c in files:
        if c.stem == sid or c.stem.startswith(sid + "."):
            _unlink(c)


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
    starts = np.linspace(0, len(data), n + 1).astype(np.int64)[:-1]
    at = np.minimum(starts, len(data) - 1)   # more slices than frames: the last ones are empty
    # max and min, not abs: abs of an int16 -32768 is still -32768. Per channel, then
    # both: numpy's max(axis=1) over two columns is many times slower
    hi = np.maximum(np.maximum.reduceat(data[:, 0], at), np.maximum.reduceat(data[:, -1], at))
    lo = np.minimum(np.minimum.reduceat(data[:, 0], at), np.minimum.reduceat(data[:, -1], at))
    hi, lo = hi.astype(np.float32), lo.astype(np.float32)
    out = np.maximum(hi, -lo) * np.float32(scale)
    out[starts >= len(data)] = 0.0
    return np.clip(out, 0.0, 1.0)


PEAK_READS = 4      # original_peaks: short reads per waveform column of a long sound...
PEAK_CHUNK = 1024   # ...of this many frames (4 KB of int16 stereo: one page each)


def original_peaks(meta: SoundMeta, n: int = 400) -> tuple[np.ndarray, float]:
    """(waveform peaks, length in seconds) of a sound as imported, for the trim
    control. Read from the cache without loading it: a long one gives a few short
    reads spread over each column, plenty to draw it. No cache yet: no peaks, the
    length from the file."""
    p = cache_path(meta.id)
    try:
        if p.exists():
            data = np.load(p, mmap_mode="r")
            return _sampled_peaks(data, n), len(data) / SR
    except Exception:  # noqa: BLE001
        log.debug("couldn't read the cache of %s for its waveform", meta.id, exc_info=True)
    try:
        return np.zeros(0, np.float32), original_frames(meta) / SR
    except Exception:  # noqa: BLE001 - the file is gone: nothing to trim
        return np.zeros(0, np.float32), 0.0


def _sampled_peaks(data: np.ndarray, n: int) -> np.ndarray:
    """peaks() of a memory-mapped (m, 2) array, touching only PEAK_READS chunks of
    PEAK_CHUNK frames per column (every frame of a short one). A plain stride over
    the whole file would still read every page of it."""
    if n <= 0 or len(data) <= n * PEAK_READS * PEAK_CHUNK:
        return peaks(np.asarray(data), n)
    edges = np.linspace(0, len(data), n + 1)
    width = edges[1] - edges[0]
    offsets = (np.arange(PEAK_READS) + 0.5) * (width / PEAK_READS) - PEAK_CHUNK / 2
    starts = np.clip((edges[:-1, None] + offsets).astype(np.int64), 0, len(data) - PEAK_CHUNK)
    picked = np.asarray(data[(starts[..., None] + np.arange(PEAK_CHUNK)).ravel()])
    return peaks(picked, n)   # n equal slices of it = each column's own chunks


def fingerprint(path: str) -> str:
    """Cheap identity for a source file: size + hash of its first and last megabyte
    (a file of up to 1 MB hashes as it always did, whole)."""
    try:
        p = Path(path)
        h = hashlib.blake2b(digest_size=12)
        size = p.stat().st_size
        h.update(str(size).encode())
        with p.open("rb") as f:
            h.update(f.read(1 << 20))
            if size > 1 << 20:
                f.seek(max(size - (1 << 20), 1 << 20))
                h.update(f.read(1 << 20))
        return h.hexdigest()
    except OSError:
        return ""


def _block_rms(data: np.ndarray) -> np.ndarray:
    """RMS of the mono mix in each whole LEVEL_WIN block (a part-block at the end is left
    out). Block by block, so any run of whole seconds can be done on its own."""
    mono = data.mean(axis=1)
    n = len(mono) // LEVEL_WIN
    return np.sqrt((mono[: n * LEVEL_WIN].reshape(n, LEVEL_WIN) ** 2).mean(axis=1))


def _gain(pk: float, rms: np.ndarray, r: float = 0.0) -> float:
    """level_gain from the loudest sample and the block RMS (`r` when there's no block)."""
    if len(rms):
        # RMS over the loud part only, so silence padding doesn't skew it
        rms = rms[rms > rms.max() * 0.1] if rms.max() > 0 else rms
        r = float(np.sqrt((rms ** 2).mean())) if len(rms) else 0.0
    if r <= 1e-6:
        return 1.0
    g = 10 ** ((TARGET_RMS_DB - 20 * np.log10(r)) / 20)
    if pk > 0:
        g = min(g, 0.95 / pk * 1.4)  # allow a little limiter work, not a lot
    return float(np.clip(g, 0.1, 6.0))


def level_gain(data: np.ndarray) -> float:
    """Gain that brings the sound to TARGET_RMS_DB without letting peaks exceed ~-0.5 dBFS."""
    if not len(data):
        return 1.0
    pk = float(np.max(np.abs(data)))
    if len(data) >= LEVEL_WIN:
        return _gain(pk, _block_rms(data))
    return _gain(pk, np.zeros(0), float(np.sqrt((data.mean(axis=1) ** 2).mean())))


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip()[:40] or "clip"


# Where a new sound's file goes, inside SOUNDS_DIR. Plain folders and the sound's own
# name, so the folder reads like a music library in Explorer (and still does if Onion
# Board is uninstalled and the sounds are kept). Files from before this were all in
# SOUNDS_DIR itself as "<id>_<name>": tidy_files() moves them in. English on purpose:
# a folder on disk mustn't change with the language picked (or the pseudo one).
RECORDINGS = "Recordings"   # recorded clips, Replay, voice lines saved as sounds
MY_SOUNDS = "My sounds"     # files added from the PC, other soundboards, old sounds
DOWNLOADS = "Downloads"     # a link from a site not named in _SITES
_SITES = {"youtube.com": "YouTube", "youtu.be": "YouTube", "tiktok.com": "TikTok",
          "soundcloud.com": "SoundCloud", "instagram.com": "Instagram",
          "twitter.com": "X", "x.com": "X", "reddit.com": "Reddit", "redd.it": "Reddit",
          "twitch.tv": "Twitch", "facebook.com": "Facebook", "fb.watch": "Facebook",
          "vimeo.com": "Vimeo", "bandcamp.com": "Bandcamp", "kick.com": "Kick",
          "dailymotion.com": "Dailymotion", "bilibili.com": "Bilibili",
          "myinstants.com": "Myinstants", "streamable.com": "Streamable"}
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
             *(f"lpt{i}" for i in range(1, 10))}
_claim_lock = threading.Lock()


def site_folder(url: str) -> str:
    """The folder a sound downloaded from `url` goes in: the site's name."""
    from urllib.parse import urlsplit
    try:
        host = (urlsplit(url.strip()).hostname or "").lower()
    except ValueError:
        host = ""
    for site, folder in _SITES.items():
        if host == site or host.endswith("." + site):
            return folder
    return DOWNLOADS


def file_stem(name: str) -> str:
    """`name` as a file name Windows takes: no <>:"/|?* (or backslash) or control characters, no
    trailing dot or space, not a device name (CON, NUL...), not too long."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    s = " ".join(s.split()).strip(" .")[:80].strip(" .")
    if s.split(".")[0].lower() in _RESERVED:
        s = f"_{s}"
    return s or "Sound"


def owns(path: str | Path) -> bool:
    """A file the library keeps itself: anywhere in SOUNDS_DIR (its own folders too)."""
    p = Path(path)
    return p.is_absolute() and p != SOUNDS_DIR and p.is_relative_to(SOUNDS_DIR)


def _folder_of(p: Path) -> str:
    """The library folder a file of ours is in ("YouTube"), "" for SOUNDS_DIR itself
    or a file from elsewhere."""
    if not owns(p) or p.parent == SOUNDS_DIR:
        return ""
    return p.parent.relative_to(SOUNDS_DIR).as_posix()


def new_file(name: str, ext: str, folder: str) -> Path:
    """A free path for a new sound file named after the sound ("Name (2)" when that's
    taken), made empty at once so two sounds saved together never get the same one."""
    where = SOUNDS_DIR / folder
    where.mkdir(parents=True, exist_ok=True)
    stem, ext = file_stem(name), ext.lower()
    with _claim_lock:
        for n in range(1, 10000):
            p = where / (f"{stem}{ext}" if n == 1 else f"{stem} ({n}){ext}")
            try:
                with open(p, "xb"):
                    return p
            except FileExistsError:
                continue
    raise OSError(f"no free file name for {stem}{ext} in {where}")


def discard(p: Path) -> None:
    """Undo new_file() after a failed save: the file, and its folder if that's empty now."""
    p.unlink(missing_ok=True)
    if p.parent != SOUNDS_DIR:
        try:
            p.parent.rmdir()   # only goes when empty
        except OSError:
            pass


# Audio the library makes itself (a download, a recording) is kept as Settings > Data
# & quality says (quality.SAVE_FORMATS). MP3 by default: it plays in anything, and is
# ~a quarter of a FLAC that holds no more than the compressed download did. ~V2 VBR
# (~190 kbps on music). libsndfile's MP3 starts on time and keeps the length (no
# encoder gap before a pad's hit). FLAC where it can't write MP3 (an old system
# libsndfile). Only the saved file: a sound plays from its cache, made at import from
# the audio as it came.
_CAN_MP3 = "MP3" in sf.available_formats()
MP3_QUALITY = 0.2   # libsndfile's compression_level: 0 best .. 1 smallest


def stored_ext() -> str:
    from soundboard import quality
    return ".mp3" if quality.current.save_format == "mp3" and _CAN_MP3 else ".flac"


def _stored_writer(dest: Path) -> sf.SoundFile:
    """An open writer for library audio ((n, 2) at SR), in the format `dest`'s extension says."""
    if dest.suffix.lower() == ".mp3":
        return sf.SoundFile(dest, "w", SR, 2, format="MP3", compression_level=MP3_QUALITY)
    return sf.SoundFile(dest, "w", SR, 2, subtype="PCM_16")


def write_stored(dest: Path, data: np.ndarray) -> None:
    """Write library audio ((n, 2) at SR) to `dest`, as its extension says."""
    with _stored_writer(dest) as f:
        f.write(data)


def import_file(src: str, color: str, name: str = "",
                folder: str = MY_SOUNDS, *, copy: bool = True) -> tuple[SoundMeta, np.ndarray]:
    """Decode, optionally bring into the library, and return metadata + int16 audio.
    `copy=False` links a persistent local source without changing its format. Both
    modes populate the same decoded cache; temporary sources must keep `copy=True`.
    The copy is SOUNDS_DIR/`folder`/`name`.ext (`name`: the sound's name, else the
    file's own; a download passes its title, its temp file is named by video id).

    Plain audio files are copied as they are. Anything that needed ffmpeg (a
    download, video, m4a, aac, wma) is stored as an MP3 of its *audio* instead
    (stored_ext()): a 300 MB video used to be copied whole, and the library stays
    playable if ffmpeg goes away. So is a file libsndfile reads under a name outside
    AUDIO_EXTS (.au, .caf, .w64…): only those come back in from a backup
    (soundboard.backup)."""
    sid = uuid.uuid4().hex[:10]
    srcp = Path(src)
    name = name.strip() or srcp.stem.replace("_", " ").strip()
    # Never fall back to using `src` in place: a download's temp folder is deleted
    # right after this. A failed copy leaves nothing behind and says what to do.
    dest = None

    def store(via_ffmpeg: bool) -> Path | None:
        """A long sound to convert is saved while it's decoded (_read): here."""
        nonlocal dest
        if copy and (via_ffmpeg or srcp.suffix.lower() not in AUDIO_EXTS):
            dest = dest or new_file(name, stored_ext(), folder)
            return dest
        return None

    try:
        got = _read(src, sid, store)
        if isinstance(got, _Long):
            if copy and dest is None:          # plain audio: copied as it is
                dest = new_file(name, srcp.suffix, folder)
                shutil.copy2(srcp, dest)
            meta = SoundMeta(id=sid, added=time.time(), name=name[:40].strip() or "Sound",
                             file=str(dest) if copy else str(srcp.absolute()), color=color,
                             level_gain=got.gain, duration=got.frames / SR,
                             fingerprint=fingerprint(src))
            return meta, got.audio
    except Exception as e:
        if dest is None and not isinstance(e, OSError):
            raise                              # it couldn't be read: said as it is
        log.warning("couldn't copy %s into the library", src, exc_info=True)
        if dest is not None:
            discard(dest)
        if isinstance(e, OSError):
            raise OSError(_("couldn't save it into your Sounds folder ({error}). Check "
                            "the disk isn't full and try again.", error=e.strerror or e)) from e
        raise
    data, via_ffmpeg = got
    if not len(data):
        raise ValueError(_("this file has no audio in it"))
    convert = via_ffmpeg or srcp.suffix.lower() not in AUDIO_EXTS
    if not copy:
        # The same decoded cache feeds playback and effects in either storage mode.
        # Only persistent local files may use this path; temporary imports must copy.
        meta = SoundMeta(id=sid, added=time.time(), name=name[:40].strip() or "Sound",
                         file=str(srcp.absolute()), color=color, level_gain=level_gain(data),
                         duration=len(data) / SR, fingerprint=fingerprint(src))
        return meta, store_cached(sid, data)
    try:
        dest = new_file(name, stored_ext() if convert else srcp.suffix, folder)
        if convert:
            write_stored(dest, data)
        else:
            shutil.copy2(srcp, dest)
        meta = SoundMeta(id=sid, added=time.time(), name=name[:40].strip() or "Sound",
                         file=str(dest), color=color, level_gain=level_gain(data),
                         duration=len(data) / SR, fingerprint=fingerprint(src))
        return meta, store_cached(sid, data)
    except Exception as e:
        log.warning("couldn't copy %s into the library", src, exc_info=True)
        if dest is not None:
            discard(dest)
        if isinstance(e, OSError):
            raise OSError(_("couldn't save it into your Sounds folder ({error}). Check "
                            "the disk isn't full and try again.", error=e.strerror or e)) from e
        raise


def save_clip(data: np.ndarray, name: str, color: str) -> tuple[SoundMeta, np.ndarray]:
    """Store recorded audio ((n, 2) float32 at SR) as stored_ext() says; return
    metadata + int16 audio."""
    sid = uuid.uuid4().hex[:10]
    dest = new_file(name, stored_ext(), RECORDINGS)
    try:
        write_stored(dest, data)
    except BaseException:
        discard(dest)
        raise
    meta = SoundMeta(id=sid, name=name[:40], file=str(dest), color=color, added=time.time(),
                     level_gain=level_gain(data), duration=len(data) / SR,
                     fingerprint=fingerprint(str(dest)))
    return meta, store_cached(sid, data)


def silence_bounds(data: np.ndarray, threshold: float = 0.002,
                   pad_s: float = 0.05) -> tuple[int, int]:
    """(start, end) frames of a recording with the dead air at both ends cut off (a
    tiny pad kept so it doesn't start abruptly); (0, 0) if it's all quiet."""
    loud = np.flatnonzero(np.max(np.abs(data), axis=1) > threshold)
    if not len(loud):
        return 0, 0
    pad = int(pad_s * SR)
    return max(int(loud[0]) - pad, 0), min(int(loud[-1]) + pad, len(data))


def trim_silence(data: np.ndarray, threshold: float = 0.002, pad_s: float = 0.05) -> np.ndarray:
    """Cut dead air off both ends of a recording (keeps a tiny pad so it doesn't start abruptly)."""
    a, b = silence_bounds(data, threshold, pad_s)
    return data[a:b]


def duplicate(meta: SoundMeta, name: str) -> SoundMeta:
    """A copy of a sound with its own library file (so removing either one never
    takes the other's audio with it), cache, id and no hotkey."""
    sid = uuid.uuid4().hex[:10]
    src = Path(meta.file)
    dest = src
    if src.is_file():   # next to the original (one from outside: in My sounds)
        dest = new_file(name, src.suffix, _folder_of(src) or MY_SOUNDS)
        try:
            shutil.copy2(src, dest)
        except BaseException:
            discard(dest)
            raise
        sourceinfo.write(dest, meta.source)   # its own "Song (copy).txt"
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
    return SoundMeta(id=sid, name=name[:40], file=str(dest), added=time.time(),
                     volume=meta.volume,
                     mode=meta.mode, loop=meta.loop, color=meta.color,
                     level_gain=meta.level_gain, duration=meta.duration,
                     fingerprint="", fx=dict(meta.fx), image=image, tags=list(meta.tags),
                     fade_in=meta.fade_in, fade_out=meta.fade_out, hold=meta.hold,
                     only_them=meta.only_them, delay=meta.delay, cooldown=meta.cooldown,
                     source=dict(meta.source))


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


def loose_sounds(cfg: Config) -> list[Path]:
    """Audio files put in the sounds folder by hand (dragged there in Explorer): not
    one of the library's own files (in its folders, or "<id>_name" from before), and
    no sound's file."""
    try:
        files = list(SOUNDS_DIR.iterdir())
    except OSError:
        return []
    used = {os.path.normcase(m.file) for m in cfg.sounds}
    return sorted(p for p in files
                  if p.suffix.lower() in AUDIO_EXTS and not _OUR_SOUND_FILE.match(p.name)
                  and os.path.normcase(str(p)) not in used and p.is_file())



def _sound_entries(text: str) -> list:
    """The pad entries still whole in a damaged config's text: each object of its
    "sounds" list up to the first one that's cut off or garbled ([] when there's no
    list to read)."""
    m = re.search(r'"sounds"\s*:\s*\[', text)
    if not m:
        return []
    dec, i, out = json.JSONDecoder(), m.end(), []
    while True:
        while i < len(text) and text[i] in " \t\r\n,":
            i += 1
        if i >= len(text) or text[i] != "{":
            return out
        try:
            obj, i = dec.raw_decode(text, i)
        except ValueError:
            return out
        out.append(obj)


def _library_audio() -> list[Path]:
    """The audio the library keeps in its sounds folder: its folders' files, and the
    "<id>_name" ones from before folders (a file dragged in by hand is the loose-sounds
    offer's, not a lost pad)."""
    out = []
    try:
        for p in sorted(SOUNDS_DIR.rglob("*")):
            if (p.suffix.lower() in AUDIO_EXTS and p.is_file()
                    and (p.parent != SOUNDS_DIR or _OUR_SOUND_FILE.match(p.name))):
                out.append(p)
    except OSError:
        log.warning("couldn't list %s", SOUNDS_DIR, exc_info=True)
    return out


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return time.time()

def delete_file(meta: SoundMeta):
    """Remove a sound's files: the audio goes to the Recycle Bin (it's the one thing
    that can't be made again), its picture and decoded cache are deleted."""
    p = Path(meta.file)
    try:
        if owns(p) and not (USE_RECYCLE_BIN and recycle(p)):
            p.unlink(missing_ok=True)
        if owns(p) and meta.source:
            sourceinfo.remove(p)
        if meta.image and Path(meta.image).parent == THUMBS_DIR:
            Path(meta.image).unlink(missing_ok=True)
    except OSError:
        log.warning("couldn't delete %s", p, exc_info=True)
    unlink_cache(meta.id)


_VIDEO_ID = re.compile(r"(?=.*[0-9A-Z])[A-Za-z0-9_-]{11}")   # a YouTube video's


def _old_folder(rest: str) -> str:
    """The folder for a file from before library folders, by the "<name>" of its
    "<id>_<name>": downloads were named by their video id."""
    if _VIDEO_ID.fullmatch(rest):
        return "YouTube"
    if rest.isdigit() and len(rest) >= 8:   # TikTok, X...: a long number
        return DOWNLOADS
    return MY_SOUNDS


def _tidy_journal() -> Path:
    """tidy_files' list of moves ("<was>\\t<now>" a line), written before each one and
    deleted once the settings are saved: a crash or power cut in between is undone at
    the next start (_undo_tidy)."""
    return APP_DIR / "tidy-moves.txt"


def _undo_tidy(cfg: Config) -> int:
    """A tidy_files that stopped before its settings were saved: the sounds still name
    the old files, so put back each one that moved (and drop a name claimed but never
    used). Moves the settings already know about stay. The list is kept while a file
    won't move back (open in another program), for the next start. Returns how many
    went back."""
    journal = _tidy_journal()
    try:
        lines = journal.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return 0
    except OSError:
        log.warning("couldn't read %s", journal, exc_info=True)
        return 0
    used = {os.path.normcase(m.file) for m in cfg.sounds}
    back, stuck = 0, False
    for line in lines:
        was, sep, now = line.partition("\t")
        if not sep:   # cut short by the power cut: its move never happened
            continue
        was_p, now_p = Path(was), Path(now)
        if os.path.normcase(now) in used or not now_p.is_file():
            continue
        try:
            if os.path.normcase(was) in used and not was_p.exists():
                os.replace(now_p, was_p)
                back += 1
            elif now_p.stat().st_size == 0:   # claimed by new_file, never filled
                discard(now_p)
        except OSError:
            log.warning("couldn't put %s back after an unfinished tidy", now, exc_info=True)
            stuck = True
    if not stuck:
        journal.unlink(missing_ok=True)
    if back:
        log.warning("put %d sound files back after an unfinished tidy", back)
    return back


def tidy_files(cfg: Config) -> int:
    """Move the sound files from before library folders ("<id>_<name>" in SOUNDS_DIR
    itself) into them, under the sound's own name: "YouTube/Never Gonna Give You
    Up.flac". At the start, before anything reads them. A file that can't move (open
    in another program) stays as it is, for the next start. The settings are saved
    at once: if they can't be, the files go back; if the app stops before then, the
    next start puts them back (_undo_tidy) and tries again. Returns how many moved."""
    if cfg.read_only:
        return 0
    _undo_tidy(cfg)
    if _tidy_journal().exists():   # some couldn't go back yet: don't add to the list
        return 0
    moved: dict[Path, Path] = {}
    journal = None
    changed: list[tuple[SoundMeta, str]] = []
    for m in cfg.sounds:
        p = Path(m.file)
        if p.parent != SOUNDS_DIR or not _OUR_SOUND_FILE.match(p.name):
            continue
        if p not in moved:   # two sounds on one file: both follow it
            if not p.is_file():
                continue
            rest = Path(p.name[11:]).stem
            dest = None
            try:
                dest = new_file(m.name or rest, p.suffix, _old_folder(rest))
                if journal is None:
                    journal = open(_tidy_journal(), "a", encoding="utf-8")  # noqa: SIM115
                journal.write(f"{p}\t{dest}\n")
                journal.flush()
                os.fsync(journal.fileno())   # on disk before the move it undoes
                os.replace(p, dest)
            except OSError:
                log.warning("couldn't move %s into a library folder", p.name, exc_info=True)
                if dest is not None:
                    dest.unlink(missing_ok=True)
                continue
            moved[p] = dest
        changed.append((m, m.file))
        m.file = str(moved[p])
    if journal is not None:
        journal.close()
    saved = not moved or cfg.save()
    if saved:
        try:
            _tidy_journal().unlink(missing_ok=True)
        except OSError:   # harmless: the sounds name the new files, nothing goes back
            log.warning("couldn't remove the tidy list", exc_info=True)
    if not saved:
        log.warning("couldn't save the settings: the sound files go back where they were")
        all_back = True
        for was, now in moved.items():
            try:
                os.replace(now, was)
            except OSError:   # then the sounds keep the new place: saved next time, or
                log.warning("couldn't move %s back", now, exc_info=True)
                all_back = False   # if never saved, the kept list puts it back next start
                continue
            for m, old in changed:
                if Path(old) == was:
                    m.file = old
        if all_back:
            _tidy_journal().unlink(missing_ok=True)
        return 0
    if moved:
        log.info("moved %d sound files into library folders", len(moved))
    return len(moved)
