"""The settings (`Config`) and each sound's settings (`SoundMeta`): their defaults,
what a saved value may be, loading config.json (backups, salvage, older and newer
versions) and the one-time move from %APPDATA%\\Soundboard."""
from __future__ import annotations

import contextlib
import copy
import json
import logging
import math
import os
import re
import shutil
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field, fields
from functools import cache, lru_cache
from pathlib import Path
from typing import ClassVar

from soundboard import __version__
from soundboard.sounds import paths, saving, sourceinfo, tags
from soundboard.audio.eq import BANDS as EQ_BANDS
from soundboard.audio.eq import MAX_DB as EQ_MAX_DB
from soundboard.i18n import _, ngettext
from soundboard.sounds.saving import CONFIG_BACKUPS, _privacy_path
from soundboard.sounds.tags import SUB_SEP, clean_tags

log = logging.getLogger("soundboard.sounds.library")


# the tabs with a quick how-to on their first visit (ui/setup/tabtours.py)
TOUR_TABS = ("radio", "apps", "voice", "store")
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

AUDIO_EXTS = {".wav", ".mp3", ".ogg", ".flac", ".opus", ".m4a", ".aac", ".wma",
              ".aiff", ".aif", ".webm", ".mp4", ".mkv", ".mov"}

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


_ATOMS = frozenset((str, int, float, bool, type(None)))


def _plain(v):
    """A copy of a setting's value, as asdict() makes it: lists and dicts copied
    all the way down, so another thread can write it while this one changes the
    config. Settings hold only JSON types, so this is all asdict() did for them."""
    t = type(v)
    if t in _ATOMS:
        return v
    if t is dict:
        return {k: x if type(x) in _ATOMS else _plain(x) for k, x in v.items()}
    if t is list or t is tuple:
        out = [x if type(x) in _ATOMS else _plain(x) for x in v]
        return out if t is list else tuple(out)
    return asdict(v) if hasattr(type(v), "__dataclass_fields__") else copy.deepcopy(v)


def _fields_raw(obj, names) -> dict:
    """asdict(obj) for a Config / SoundMeta, without asdict's call per value: every
    save copies every sound, and asdict() made ~70 Python calls per sound for it."""
    return {n: v if type(v) in _ATOMS else _plain(v)
            for n in names for v in (getattr(obj, n),)}


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
NET_MODES = ("direct", "proxy", "tor")   # soundboard.online.net.MODES
TOR_BRIDGES = ("", "snowflake", "obfs4")   # soundboard.online.tor.BRIDGES
# where what others hear goes (Config.route; Setup -> Devices -> Send my sounds to):
#   cable  - a virtual cable, whose other end Discord / the game uses as its mic
#   device - any output picked by hand (Voicemeeter, a mixer, a second sound card, a
#            device OBS captures): no cable needed, and none is picked in its place
#   off    - nowhere: sounds play in your headphones (and the stream output) only
#   mic    - straight into your real mic (the mic effect, soundboard.mic.directmic): Discord
#            and games keep their normal mic, no cable. New users start with it
#            (Config.first_start); the cable is the fallback.
ROUTES = ("cable", "device", "off", "mic")
# settings whose unknown value (a newer version's choice) clean_setting replaces with
# a safe one: the value as it was is still written back (see _with_raw)
NEWER_CHOICES = ("route", "net_mode", "tor_bridges", "pad_sort", "pad_view", "list_rows",
                 "app_clip_group", "app_view", "voice_view")
# the Sounds tab's orders: as dragged, A-Z, the newest first, the most played first
PAD_SORTS = ("custom", "name", "newest", "plays")
PAD_VIEWS = ("grid", "list")
# the list view's row heights (ui.widgets.LIST_ROW_H)
LIST_ROWS = ("small", "medium", "large")
SETTING_RANGES = {"sound_vol": (0.0, VOLUME_MAX), "mic_vol": (0.0, VOLUME_MAX),
                  "mon_vol": (0.0, VOLUME_MAX), "obs_vol": (0.0, VOLUME_MAX),
                  "pad_width": PAD_WIDTH_RANGE, "app_card_width": (240, 480),
                  "app_clip_height": (0, 600), "voice_clip_height": (0, 600),
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


def clean_hotkey(combo: str, what: str) -> str:
    """A saved hotkey, or "" (with a log line) if no keyboard could ever send it: older
    versions saved any text. It stays as written otherwise, for older versions."""
    if not combo:
        return ""
    from soundboard.control import winkeys  # Win32; only needed once there's a key
    if winkeys.check(combo, mouse=what == "ptt_key")[1]:   # a side button: PTT only
        log.warning("dropped the hotkey %r of %s: no key can send it", combo[:80], what)
        return ""
    return combo


def clean_setting(k: str, v):
    """Setting `k` (already of the right type) as the app can use it: brought into the
    range of its control. None if it's unusable, so the default applies instead."""
    if k.endswith("_hotkey") or k == "ptt_key":
        return clean_hotkey(v, k)
    if k in ("category_hotkeys", "voice_hotkeys"):   # {category / voice: its key}
        return {c: key for c, key in v.items()
                if isinstance(c, str) and isinstance(key, str)
                and clean_hotkey(key, f"category {c!r}")}
    if k == "tab_keys":   # {tab: its key}; "" = none, so it has no Ctrl+number either
        return {t: key for t, key in v.items()
                if isinstance(t, str) and isinstance(key, str)
                and (not key or clean_hotkey(key, f"tab {t!r}"))}
    if k in SETTING_RANGES:
        lo, hi = SETTING_RANGES[k]
        return min(max(v, lo), hi)
    if k == "hidden_from_all":   # category names; ones that aren't a tab go after loading
        return list(dict.fromkeys(x for x in v if isinstance(x, str) and x))
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
    if k == "light_voice":
        return v if v in ("auto", "on", "off") else "auto"
    if k in ("pad_view", "app_view", "voice_view"):
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
    if k == "dest":   # {"mode": key, "custom": [mode dicts]} (soundboard.mic.destination)
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
        if any(_OUR_SOUND_FILE.match(f.name) for f in (paths.OLD_APP_DIR / "sounds").iterdir()):
            return True
    except OSError:
        pass
    try:
        raw = json.loads((paths.OLD_APP_DIR / "config.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False
    # both, as ours: a number version and a list of sounds with files ("sounds" or
    # "version" alone matched other programs' settings, a %APPDATA%\soundboard of
    # theirs, which was then moved in here)
    if not isinstance(raw, dict):
        return False
    version, sounds = raw.get("version"), raw.get("sounds")
    return (isinstance(version, int) and not isinstance(version, bool)
            and 0 < version <= CONFIG_VERSION and isinstance(sounds, list)
            and all(isinstance(s, dict) and isinstance(s.get("file"), str) for s in sounds))


def scrub_old_configs(names) -> None:
    """Blank the Config fields `names` (a login the user removed) in config.json's
    older copies too: config.json.1… and the set-aside config.json.broken-<time> kept
    it in plain text after Disconnect. A copy that can't be read is left alone."""
    fresh = Config().to_raw()
    olds = [paths.CONFIG_PATH.with_name(f"config.json.{i}")
            for i in range(1, saving.CONFIG_BACKUPS + 1)]
    olds += sorted(paths.CONFIG_PATH.parent.glob("config.json.broken-*"))
    for p in olds:
        try:
            raw = json.loads(p.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(raw, dict) or not any(raw.get(n) for n in names):
            continue
        raw.update({n: fresh.get(n) for n in names if n in raw})
        try:
            saving.atomic_write_text(p, json.dumps(raw, indent=2))
        except OSError:
            log.warning("couldn't clear an old copy of the settings", exc_info=True)


def migrate_from_soundboard() -> None:
    """One-time move of %APPDATA%\\Soundboard (sounds, settings, cache, browser
    profile) into %APPDATA%\\OnionBoard, for anyone who installed this app back when
    it was called Soundboard. Must run before anything creates APP_DIR - called first
    thing in app.py's main(), ahead of applog.setup()."""
    # Keyed on the new config, not the new folder: the installer's cable step can
    # create APP_DIR (its restart marker) before the app's first launch, and a move
    # that failed halfway must be retried next launch rather than silently skipped.
    if not paths.OLD_APP_DIR.is_dir() or paths.CONFIG_PATH.exists() or not _is_our_old_folder():
        return
    if not paths.APP_DIR.exists():
        try:
            paths.OLD_APP_DIR.rename(paths.APP_DIR)
            return
        except OSError:
            pass   # different drive, a file in use: go item by item below
    try:
        paths.APP_DIR.mkdir(parents=True, exist_ok=True)
        # the config goes last, so it only exists once everything it points at does
        for item in sorted(paths.OLD_APP_DIR.iterdir(),
                           key=lambda p: p.name.startswith("config.json")):
            dst = paths.APP_DIR / item.name
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
        MIGRATION_ERRORS.append(f"couldn't move {paths.OLD_APP_DIR} to {paths.APP_DIR}: {e}")


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
    fx: dict = field(default_factory=dict)   # speed, pitch, EQ, boost… (soundboard.audio.soundfx)
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
    settings_advanced: bool = False   # Settings shows its advanced pages (Show advanced)
    edit_advanced: bool = False   # Edit sound opens in its Advanced view
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
    hotkeys_share: bool = True        # the game still gets a hotkey's key (winkeys.Hotkeys.share)
    pong_sounds: bool = True          # Pong with Bun's sounds (its speaker button)
    theme: str = "Dark"
    # limited-edition themes picked while on offer: theirs for good (theme.kept)
    kept_themes: list[str] = field(default_factory=list)
    # the app's language, a catalog code (assets/lang); "" = never picked (i18n.startup)
    language: str = ""
    # the whole interface's size in percent (Settings > Appearance), on top of Windows'
    # display scaling; read before the app starts (app.ui_scale_startup)
    ui_scale: int = 100
    live_color: str = ""   # own colour for the "it's on" highlights ("" = the theme's)
    # True = each theme's own pattern on the panels (new installs); False = Plain. Every
    # saved config has it, so changing this default only reaches new installs
    theme_texture: bool = True
    # Lite mode (ui/settings/lite.py): animations, Bun's idle moves and the textures off
    lite_mode: bool = False
    lite_hint_done: bool = False   # a slower PC was told about lite mode once
    store_seen: bool = False   # the Community tab was opened once: its "New" mark is gone
    # Use less CPU for the voice features (the voice changer card): "on", "off", or
    # "auto" = on while lite mode is (soundboard.voicefx.set_light)
    light_voice: str = "auto"
    eq_enabled: bool = False
    eq_target: str = "voice"          # voice | sounds | all
    eq_preset: str = "Flat (off)"
    eq_gains: list[float] = field(default_factory=lambda: [0.0] * 7)
    dest: dict = field(default_factory=dict)   # who's listening (soundboard.mic.destination)
    send_mono: bool = True    # phase-aware mono for the send device (sendfx.SmartMono)
    duck_db: float = 0.0      # lower the sounds this much while you talk; 0 = off
    duck_on: bool = False     # older versions switch ducking on once unless this is set
    duck_off: bool = False    # the old -12 dB default went back to Off once (from_raw)
    clean_moved: bool = False   # Clean up my mic moved to Clean mic once (from_raw)
    mic_gate: bool = False    # mute your mic while a sound plays (only the sound goes out)
    discord_restore: bool = True   # put Discord back for talking on quit (discordtalk)
    # the mic helper: admin steps of the mic effect without Windows asking each time
    # (Settings > Audio > Mic effect; off: removed, Windows asks: directmic.set_helper)
    mic_helper: bool = True
    discord_talk: dict = field(default_factory=dict)   # Discord folder -> how you talk there
    voice_level: bool = True  # keep your voice at one volume (sendfx.VoiceLeveler)
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
    app_view: str = "grid"     # the Apps tab: cards or a list (PAD_VIEWS)
    voice_view: str = "grid"   # the Voice tab's voices: picture cards or a list
    # Clean mic switches on whenever a voice is turned on (Settings > Audio). Older
    # versions keep it untouched
    clean_with_voice: bool = True
    app_clip_height: int = 0   # saved clips: 0 fits the rows, otherwise the dragged height
    app_clip_group: str = "app"   # saved clips grouped by app, day, or newest first
    app_clips_expanded: bool = True   # fold the saved clips down to their header
    app_clips_keep_forever: bool = False   # otherwise expire after seven inactive days
    voice_clip_height: int = 0   # the Voice tab's recordings: as app_clip_height
    voice_clips_expanded: bool = True   # ...folded down to their header or not
    sidebar_open: bool = True   # the tab rail opened out to show the tabs' names
    sidebar_order: list[str] = field(default_factory=list)   # stable tab keys, visual order
    # a tab's own key to jump to it (tab key -> combo, "" = none); a tab not in it has
    # Ctrl+1... by its place on the rail
    tab_keys: dict = field(default_factory=dict)
    # 0 = sounds, 1 = radio, 2 = apps, 3 = triggers, 4 = voice, 5 = setup, 6 = store, 7 = chat
    tab: int = 0
    # Settings > Tabs: the tabs switched off ("radio", "apps", "triggers", "voice"), gone
    # from the window and never built (a new user starts with BASIC_TABS_OFF)
    tabs_off: list[str] = field(default_factory=list)
    # the Store tab's random id for this install (soundboard.online.store: one vote per sound);
    # "" until the store is first used
    store_id: str = ""
    # the Chat tab's rules version this user accepted, from 2.3.0 and 2.3.1 (the tab is gone
    # now): kept so a config saved here still tells those versions chat was dealt with
    chat_rules: int = 0
    # fetch newer yt-dlp versions from PyPI by itself: opt-in, since that's code the app
    # runs (named *_optin so configs saved while it defaulted to on start off again)
    ytdlp_auto_optin: bool = False
    latency: str = "low"              # audio buffering: 'low' | 'high' (safer on flaky devices)
    setup_done: bool = False          # the quick-setup guide has been completed
    # what the quick-setup guide's first page was told the app is for (USES in
    # ui/setup/setupwizard.py). "" = not asked yet: only a brand-new install starts so
    # (first_start), so the question comes once, on the first launch
    use_mode: str = "normal"
    # the old "Did you know?" tips' switch and day (no longer shown; kept so settings from
    # older versions load as they were). tips_seen: what was shown once (tours, offers)
    tips_on: bool = True
    # each tab's quick how-to the first time it's opened, and the first-run tour
    # (ui/setup/tabtours.py, ui/setup/firsttour.py); seen ones are in tips_seen
    tutorials_on: bool = True
    tips_seen: list = field(default_factory=list)
    tip_day: str = ""
    # set up for the app you're using (soundboard.mic.appsetup): ask, apps {exe: simple mode},
    # never [exe]. Older versions keep it untouched
    app_setup: dict = field(default_factory=dict)
    voice_fx: dict = field(default_factory=dict)   # voice changer (see ui.voicepanel)
    speech: dict = field(default_factory=dict)     # text-to-speech / live voice settings
    overlay: dict = field(default_factory=dict)    # in-game overlay (ui.overlay.OverlaySettings)
    bun: dict = field(default_factory=dict)        # Bun mode: on, size, pos (ui.bunmode)
    window_maximized: bool = False   # the window was maximised last time: it opens that way
    radio: dict = field(default_factory=dict)      # Radio tab: vol, monitor, favorites, last
    data: dict = field(default_factory=dict)       # Settings > Data & quality (online.quality)
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
    hidden_from_all: list[str] = field(default_factory=list)   # categories All leaves out
    tray: bool = True                 # closing the window keeps the app in the tray
    autostart_hidden: bool = True     # started with Windows: straight to the tray
    # look at GitHub Releases for a newer version, at most every 6 hours (soundboard.core.updates).
    # Was the opt-in update_check_optin, off by default: renamed so every config starts on
    update_check: bool = True
    update_checked: float = 0.0       # time.time() of the last check
    update_skip: str = ""             # a version the user said to skip
    update_pending: str = ""          # the version an update is installing (see updates.py)
    # a new version found as the app starts installs itself (UpdateControl, "auto")
    update_auto: bool = True
    update_auto_tried: str = ""       # ...once per version: a failed one isn't retried
    # the newest version whose What's new (ui/setup/whatsnew.py) was shown; a first start has
    # nothing to catch up on, a config without it is from an older version
    whats_new_seen: str = __version__
    # Invite a friend (soundboard.core.invite): the name put on their invite links, and
    # who invited them (from the installer, greeted once on the first start)
    invite_name: str = ""
    invited_by: str = ""
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
    voices_hotkey: str = ""           # every voice off (remembered) / back on (Voice tab)
    voice_hold_hotkey: str = ""       # the voice changer on only while held
    voice_random_hotkey: str = ""     # a random voice from the Voice tab's cards
    hotkeys_off_hotkey: str = ""      # every other hotkey off / on (this one keeps working)
    # a sound's hotkey only works while its category is showing, so one key can play a
    # different sound in each category (keybind profiles)
    scoped_hotkeys: bool = False
    single_click: bool = True         # one click on a pad plays it (False: a double-click;
                                      # saved configs keep theirs)
    category_hotkeys: dict = field(default_factory=dict)   # category -> its random-sound key
    voice_hotkeys: dict = field(default_factory=dict)      # voice name -> the key that picks it
    # Switch category when a program is in front (soundboard.sounds.catswitch): {"game.exe":
    # category}, set by the user from a category's menu; and the switch for all of it
    category_programs: dict = field(default_factory=dict)
    category_programs_on: bool = True
    # instant replay (soundboard.audio.replay): while this hotkey is set, the last
    # replay_seconds of everything you hear (except Onion Board's own sounds) are kept
    # in memory, and the key saves them as a new pad
    replay_hotkey: str = ""
    replay_seconds: int = 30
    # local control API for Stream Deck / scripts (soundboard.control.remote): off unless turned on
    api_enabled: bool = False
    api_port: int = 7474
    api_token: str = ""
    # the control API's chat commands and alerts (soundboard.control.streamapi): {"chat": {...},
    # "alerts": {type: [rule, ...]}, "alerts_on": bool}; set through /api/chat_rules
    # and /api/alerts
    api_stream: dict = field(default_factory=dict)
    # Settings → Remote's *Connect Twitch* (soundboard.control.twitchlink): the sign-in, empty
    # when not connected. The tokens are passwords: never exported with a backup or logged
    twitch_token: str = ""
    twitch_refresh: str = ""
    twitch_login: str = ""
    twitch_user_id: str = ""
    # the card's "let the developer see this channel's name" box (off until ticked; reset
    # on Disconnect, so a new account is asked again): the daily usage count adds
    # twitch-channel/<login> while connected (soundboard.core.usage.hits)
    twitch_share: bool = False
    # "remote" add-ons' own settings (soundboard.ui.settings.remotehost), by add-on id: Onion
    # Pocket's on / off, port and key
    remote_addons: dict = field(default_factory=dict)
    # Settings > Connection (soundboard.online.net): "direct", "proxy" through
    # net_proxy (socks5h://host:port or http://host:port), or "tor" (soundboard.online.tor)
    net_mode: str = "direct"
    net_proxy: str = ""
    # Settings > Privacy & security, the switches (soundboard.online.net.FEATURES): the
    # features switched off (opt-out: everything's on by default), and Offline mode
    net_off: list[str] = field(default_factory=list)
    net_offline: bool = False
    # Network activity's "Keep a history" (soundboard.online.netlog.keep): off = memory only
    netlog_keep: bool = False
    # "Keep an app log" (soundboard.core.applog.keep): off = onionboard.log isn't written
    app_log: bool = True
    # "Hide that I'm using Tor": "" (off), "snowflake" or "obfs4" bridges
    tor_bridges: str = ""
    # the anonymous usage count (soundboard.core.usage; its switch is "usage_stats" in
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
    # *Enjoying Onion Board?* (soundboard.core.enjoy): seconds open per date, "" / "done"
    enjoy_days: dict = field(default_factory=dict)
    enjoy_state: str = ""
    # an observed FFmpeg startup/get failure awaiting a verified working copy
    stats_ffmpeg_failed: bool = False
    # Settings > Achievements' counts, sets and what's earned (soundboard.core.achievements):
    # this PC's own, never sent or exported
    achievements: dict = field(default_factory=dict)
    # Settings > Achievements: the "Achievement unlocked" pop-up, and its chime (both
    # off unless turned on)
    achievement_popups: bool = False
    achievement_sound: bool = False
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
                # sig: a BOM is fine
                raw = json.loads(paths.CONFIG_PATH.read_text(encoding="utf-8-sig"))
                locked = False
                break
            except FileNotFoundError as e:
                if not any(paths.CONFIG_PATH.with_name(f"config.json.{i}").exists()
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
            log.error("config %s stayed locked: %r; not saving this session",
                      paths.CONFIG_PATH, err)
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
        log.error("config %s is unreadable: %r", paths.CONFIG_PATH, err)
        damaged = ""
        if not missing:   # its pads may still be readable (see _salvage)
            with contextlib.suppress(OSError):
                damaged = paths.CONFIG_PATH.read_text(encoding="utf-8-sig", errors="replace")
        broken = "" if missing else cls._set_aside()
        kept = ("" if missing else " " + _("The damaged file was kept as {file}.",
                                           file=broken or "config.json")
                + " " + _("Both files are in {folder}.", folder=paths.CONFIG_PATH.parent))
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
                           "are still in {folder}.", folder=paths.SOUNDS_DIR) if missing else
                         _("Your settings file was damaged and no backup could be read, "
                           "so Onion Board started with default settings. Your sound files "
                           "are still in {folder}.", folder=paths.SOUNDS_DIR)) + back + kept
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
        cfg.duck_off = True
        cfg.clean_moved = True
        # a plain soundboard first; + More tabs adds them ("chat": the removed Chat tab, so
        # 2.3.0 / 2.3.1 opening this config keep it hidden)
        cfg.tabs_off = [*BASIC_TABS_OFF, "chat"]
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
        newer = paths.CONFIG_PATH.with_name("config.json.newer")
        if version <= CONFIG_VERSION or newer.exists():
            return
        try:
            shutil.copy2(paths.CONFIG_PATH, newer)
            log.warning("config is from a newer version (v%s, this one reads v%s): kept a "
                        "copy as %s", version, CONFIG_VERSION, newer.name)
        except OSError:
            log.warning("couldn't keep a copy of the newer config", exc_info=True)

    @classmethod
    def _set_aside(cls) -> str:
        try:
            broken = paths.CONFIG_PATH.with_name(
                f"config.json.broken-{time.strftime('%Y%m%d-%H%M%S')}")
            paths.CONFIG_PATH.replace(broken)
            log.warning("set the damaged config aside as %s", broken.name)
            return broken.name
        except OSError:
            log.debug("couldn't set the damaged config aside", exc_info=True)
            return ""

    @classmethod
    def _backups(cls):
        """(name, parsed json) of each backup that parses, newest first."""
        for i in range(1, CONFIG_BACKUPS + 1):
            p = paths.CONFIG_PATH.with_name(f"config.json.{i}")
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
        if not raw.get("duck_off"):
            # once: lowering the sounds while you talk is off by default again. Settings
            # that got the old -12 dB default go back to Off; another depth someone
            # picked stays, and -12 dB picked after this stays. duck_on stays set so an
            # older version doesn't switch it back on.
            if raw.get("duck_on") and raw.get("duck_db") == -12.0:
                raw["duck_db"] = 0.0
            raw["duck_on"] = True
            raw["duck_off"] = True
        if not raw.get("clean_moved"):
            _move_clean_up(raw)
            raw["clean_moved"] = True
        _rename_theme(raw, "Barbie", "Bubblegum")   # the pink theme's old name
        sounds = []
        blank = SoundMeta(id="", name="", file="")
        has_sounds = "sounds" in raw
        raw_sounds = raw.pop("sounds", None)
        if raw_sounds is None and not has_sounds:
            raw_sounds = []
        elif not isinstance(raw_sounds, list):   # damaged / hand-edited (null too: no version
            # writes it): never save over the pads with an empty list; load() sets the
            # file aside and recovers them
            raise ValueError(f"config 'sounds' is a {type(raw_sounds).__name__}, not a list")
        for s in raw_sounds:
            if not isinstance(s, dict) or not all(isinstance(s.get(k), str) and s.get(k)
                                                  for k in ("id", "name", "file")):
                log.warning("skipped a damaged sound entry in the config: %r", s)
                continue
            extra = {k: v for k, v in s.items() if k not in SoundMeta.__dataclass_fields__}
            kept = ({"mode": ("restart", s["mode"])}
                    if isinstance(s.get("mode"), str) and s["mode"] not in MODES else {})
            s = _typed(s, blank, f"sound {s['name']!r}")
            for k in ("file", "image"):   # v0.1.0 stored full paths into the old folder
                if (s.get(k) and Path(s[k]).is_absolute()
                        and Path(s[k]).is_relative_to(paths.OLD_APP_DIR)):
                    s[k] = str(paths.APP_DIR / Path(s[k]).relative_to(paths.OLD_APP_DIR))
            if not Path(s["file"]).is_absolute():
                s["file"] = str(paths.SOUNDS_DIR / s["file"])   # stored relative to the library
            if s.get("image") and not Path(s["image"]).is_absolute():
                s["image"] = str(paths.THUMBS_DIR / s["image"])
            s["tags"] = clean_tags(s.get("tags"))
            s["hotkey"] = clean_hotkey(s.get("hotkey", ""), f"sound {s['name']!r}")
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
        # ...and from before the tabs' how-tos: they've been using those tabs already
        if "tutorials_on" not in raw and raw.get("setup_done"):
            seen = raw.get("tips_seen")
            raw["tips_seen"] = [*(seen if isinstance(seen, list) else []),
                                *(f"tour-{t}" for t in TOUR_TABS)]
        # ...and from before What's new: everything in it is new to them
        raw.setdefault("whats_new_seen", "")
        # ...and from before the Chat tab (2.3.0 / 2.3.1 only): kept off, so going back to
        # one of those versions doesn't show it
        if "chat_rules" not in raw:
            off = raw.get("tabs_off")
            raw["tabs_off"] = [*(off if isinstance(off, list) else []), "chat"]
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
        tags.merge_tags(cats, cfg.categories, cfg.subcategories)
        for m in sounds:   # a category a sound is in always has a tab
            m.tags = tags.merge_tags(m.tags, cfg.categories, cfg.subcategories)
        cfg.hidden_from_all = [c for c in cfg.hidden_from_all if c in cfg.categories]
        if cfg.category not in cfg.categories:
            cfg.category = ""
        if cfg.subcategory not in cfg.subcategories.get(cfg.category, []):
            cfg.subcategory = ""
        return cfg

    def to_raw(self) -> dict:
        d = _with_raw(_fields_raw(self, _CONFIG_FIELDS), self)
        d["version"] = CONFIG_VERSION
        d["sounds"] = [_with_raw(_fields_raw(m, _SOUND_FIELDS), m) for m in self.sounds]
        # files inside the library are stored by name only, so the whole
        # %APPDATA%\OnionBoard folder can move or be restored
        for s in d["sounds"]:
            s["file"] = _stored_path(s["file"], paths.SOUNDS_DIR, True)
            if s["image"]:
                s["image"] = _stored_path(s["image"], paths.THUMBS_DIR, False)
        return d

    def save(self) -> bool:
        """Write atomically, keeping the last CONFIG_BACKUPS good copies. Returns
        False (and logs) instead of raising. Blocks while the disk is slow (an
        antivirus scan can take seconds): the window saves through Saver instead."""
        if self.read_only:
            log.warning("not saving settings: config.json was locked at startup")
            return False
        return saving._write(self.snapshot())

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


# what Config.to_raw copies, in asdict()'s order
_SOUND_FIELDS = tuple(f.name for f in fields(SoundMeta))
_CONFIG_FIELDS = tuple(f.name for f in fields(Config) if f.name != "sounds")

_seq_lock = threading.Lock()     # numbering snapshots (never held across disk I/O)
_snap_seq = 0       # the last snapshot's number (Config.snapshot)

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


def _rename_theme(raw: dict, old: str, new: str) -> None:
    """A theme that changed its name: the chosen theme and the themes tried (an
    achievement counts them) move to the new one."""
    if raw.get("theme") == old:
        raw["theme"] = new
    ach = raw.get("achievements")
    tried = ach.get("s") if isinstance(ach, dict) else None
    if not isinstance(tried, dict):
        return
    themes = tried.get("themes")
    if isinstance(themes, list) and old in themes:
        tried["themes"] = list(dict.fromkeys(new if t == old else t for t in themes))


def _move_clean_up(raw: dict) -> None:
    """Once: the voice changer's Clean up my mic effect is gone, Clean mic (the Voice
    tab) does the job. It started on and only ran under a voice, so Clean mic goes on
    (Normal) for whoever used the voice changer with it on; nobody else's mic changes,
    and a Clean mic already set stays as it is. (An older version opening these
    settings just has its effect back as it starts: on.)"""
    fx, speech = raw.get("voice_fx"), raw.get("speech")
    if not isinstance(fx, dict) or not fx:
        return
    if isinstance(speech, dict) and "clean" in speech:
        return
    got = fx.get("effects")
    effects: dict = got if isinstance(got, dict) else {}
    old = effects.get("cleanup")
    if isinstance(old, dict) and old.get("on") is False:
        return
    preset = fx.get("preset")
    used = (fx.get("enabled") is True
            or (isinstance(preset, str) and preset not in ("", "Custom"))
            or any(isinstance(c, dict) and c.get("on") is True
                   for t, c in effects.items() if t not in ("cleanup", "backdrop")))
    if not used:
        return
    raw["speech"] = {**(speech if isinstance(speech, dict) else {}),
                     "clean": {"on": True, "strength": "normal"}}


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
        for p in sorted(paths.SOUNDS_DIR.rglob("*")):
            if (p.suffix.lower() in AUDIO_EXTS and p.is_file()
                    and (p.parent != paths.SOUNDS_DIR or _OUR_SOUND_FILE.match(p.name))):
                out.append(p)
    except OSError:
        log.warning("couldn't list %s", paths.SOUNDS_DIR, exc_info=True)
    return out


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return time.time()
