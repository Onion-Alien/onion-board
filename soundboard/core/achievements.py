"""Achievements (Settings > Achievements): milestones for using the app, kept on this
PC only, in cfg.achievements. All the usage count (usage.py) sends of them is which
ones were earned, by id (usage.achieved), and roughly how many and their score: never
when, or the counts behind them. Each is worth its rarity's POINTS towards the score.

Counting is cheap on purpose: a used() feature, a play or a vote is one dict lookup,
an add to a number or a set, and a check of only the achievements that number feeds.
Time-based ones (voices, program audio, radio) add up on the window's 5-minute usage
tick (tick()) from when their tab's live switch went on (live()), with no timer of
their own. Nothing is saved here: the numbers live in cfg and go out with its next save
(tick() asks for one when something changed).

cfg.achievements holds "n" (counts), "s" (sets, as lists: stations, voices, themes…),
"got" ({achievement id: when it was earned}) and "seen" (the newest launch date and
the last sound count, for days opened and sounds added).

on_unlock: functions called with an achievement's id as it's earned (for a pop-up).
Events can come from other threads (the control API), so a listener that touches
widgets must hand over to the UI thread itself."""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from collections.abc import Callable

from soundboard.core.continents import CONTINENT

# the rarities, commonest first: the rare loading screens' tiers (ui/bun/splashacts.py
# RARES, splash.tier_name), whose colours the badges wear: Uncommon = Golden Bun,
# Rare = Ice, Legendary = Galaxy, Super Rare = Rainbow
TIERS = ("common", "uncommon", "rare", "legendary", "super")
# what each rarity is worth towards the score (score()): the rarer, the more
POINTS = {"common": 10, "uncommon": 25, "rare": 50, "legendary": 100, "super": 200}

log = logging.getLogger(__name__)

HOUR = 3600


@dataclass(frozen=True)
class Ach:
    id: str
    stat: str          # the number or set it counts (value())
    goal: float        # earned when the stat reaches this
    tier: str          # one of TIERS
    hidden: bool       # "???" until earned
    icon: str          # an icons.SHAPES name for the placeholder badge


# In the order the page shows them. Time goals are in seconds.
ALL: tuple[Ach, ...] = (
    # sounds on the board and played
    Ach("first_blood", "plays", 1, "common", False, "play"),
    Ach("spammer", "plays", 1000, "uncommon", False, "flame"),
    Ach("menace", "plays", 10000, "rare", False, "flame"),
    Ach("collector", "sounds_added", 100, "common", False, "sounds"),
    Ach("hoarder", "sounds_added", 250, "uncommon", False, "sounds"),
    Ach("dragon_hoard", "sounds_added", 1000, "legendary", False, "sounds"),
    # voices, radio, the store
    Ach("new_voice", "voice_s", HOUR, "common", False, "voice"),
    Ach("voice_actor", "voice_s", 10 * HOUR, "uncommon", False, "voice"),
    Ach("method_actor", "voice_s", 100 * HOUR, "legendary", False, "voice"),
    Ach("station_hopper", "stations", 100, "uncommon", False, "radio"),
    Ach("radio_head", "stations", 1000, "legendary", False, "radio"),
    Ach("critic", "upvotes", 10, "common", False, "like"),
    Ach("tastemaker", "upvotes", 100, "rare", False, "like"),
    Ach("regular", "days", 30, "uncommon", False, "history"),
    Ach("veteran", "days", 365, "legendary", False, "history"),
    Ach("one_hit_wonder", "top_plays", 500, "rare", False, "play"),
    Ach("tidy_desk", "tabs", 5, "common", False, "folder"),
    Ach("download_fiend", "dl_add", 100, "rare", False, "download"),
    Ach("weekend_warrior", "weekends", 10, "uncommon", False, "history"),
    Ach("on_a_roll", "streak", 7, "uncommon", False, "flame"),
    Ach("unbreakable", "streak", 30, "rare", False, "flame"),
    # hidden from here on: "???" until earned
    Ach("golden_bun", "splash_gold", 1, "uncommon", True, "bun"),
    Ach("ice_bun", "splash_ice", 1, "rare", True, "bun"),
    Ach("galaxy_bun", "splash_galaxy", 1, "legendary", True, "bun"),
    Ach("rainbow_bun", "splash_rainbow", 1, "super", True, "bun"),
    Ach("catch_em_all", "rares", 3, "legendary", True, "star"),
    Ach("gamer_bun", "pong_won", 1, "uncommon", True, "gamepad"),
    Ach("sore_loser", "pong_lost", 1, "common", True, "gamepad"),
    Ach("arcade_rat", "games", 4, "rare", True, "gamepad"),
    Ach("rise_and_shine", "bun_woken", 1, "uncommon", True, "bun"),
    Ach("chatterbox", "bun_talk", 50, "uncommon", True, "chat"),
    Ach("who_hoots", "hoot_talk", 1, "common", True, "triggers"),
    Ach("bun_mode", "bun_mode", 1, "common", True, "bun"),
    Ach("panic_button", "stop_all", 50, "uncommon", True, "stop_all"),
    Ach("silent_but_deadly", "vol0", 1, "uncommon", True, "volume_off"),
    Ach("gremlin", "play_3am", 1, "rare", True, "ghost"),
    Ach("pack_rat", "packs", 6, "uncommon", True, "archive"),
    Ach("defector", "import_board", 1, "common", True, "download"),
    Ach("clip_it", "clip", 1, "common", True, "scissors"),
    Ach("producer", "clip_editor", 1, "common", True, "scissors"),
    Ach("link_grabber", "dl_add", 1, "common", True, "link"),
    Ach("hotkey_hero", "hotkeys", 10, "uncommon", True, "keyboard"),
    Ach("second_chances", "restored", 1, "common", True, "reload"),
    Ach("mic_check", "record", 1, "common", True, "record"),
    Ach("puppet_master", "apps_s", 10 * HOUR, "rare", True, "apps"),
    Ach("shapeshifter", "voices", 25, "rare", True, "voice"),
    Ach("mad_scientist", "voice_saved", 1, "common", True, "sliders"),
    Ach("polyglot", "translate", 1, "uncommon", True, "speech"),
    Ach("robot_mouth", "ai_made", 1, "rare", True, "robot"),
    Ach("dice_roll", "voice_roll", 20, "common", True, "shuffle"),
    Ach("world_tour", "countries", 25, "rare", True, "radio"),
    Ach("night_owl", "radio_run_s", 3 * HOUR, "uncommon", True, "radio"),
    Ach("contributor", "store_shared", 1, "uncommon", True, "upload"),
    Ach("fashionista", "themes", 10, "uncommon", True, "palette"),
    Ach("rainbow_road", "themes", 33, "rare", True, "palette"),   # every theme (set_goal)
    Ach("seasons", "months", 12, "legendary", True, "leaf"),
    Ach("onion_onion", "tor", 1, "rare", True, "tor"),
    Ach("off_the_grid", "offline", 1, "uncommon", True, "offline"),
    Ach("remote_control", "phone", 1, "common", True, "phone"),
    Ach("streamer", "chat_command", 1, "uncommon", True, "twitch"),
    Ach("watcher", "trigger", 1, "common", True, "eye"),
    Ach("no_life", "open_run_s", 24 * HOUR, "rare", True, "trophy"),
    # the Onion Alien on Settings > About
    Ach("onion_poke", "onion_poked", 1, "common", True, "onion"),
    Ach("onion_tears", "onion_tears", 1, "uncommon", True, "onion"),
    Ach("swallowed_whole", "onion_eaten", 1, "rare", True, "onion"),
    Ach("pretty_please", "onion_please", 1, "uncommon", True, "onion"),
    # long sounds, lots at once, silly pitch
    Ach("long_haul", "longest_s", HOUR, "rare", True, "history"),
    Ach("full_album", "album", 1, "legendary", True, "music"),
    Ach("wall_of_noise", "at_once", 10, "rare", True, "volume"),
    Ach("chipmunk", "pitch_up", 1, "common", True, "sliders"),
    Ach("demon_mode", "pitch_down", 1, "common", True, "sliders"),
    # a sound played on the day (this PC's clock)
    Ach("spooky_season", "halloween", 1, "uncommon", True, "ghost"),
    Ach("ho_ho_honk", "christmas", 1, "uncommon", True, "star"),
    Ach("happy_new_noise", "new_year", 1, "legendary", True, "star"),
    # odd things to do
    Ach("disco_mode", "disco", 1, "uncommon", True, "palette"),
    Ach("hermit", "hermit", 1, "rare", True, "offline"),
    Ach("pulled_plug", "unplugged", 1, "common", True, "mic_off"),
    Ach("old_school", "konami", 1, "rare", True, "gamepad"),
    # how you play
    Ach("speed_run", "speed_run", 1, "uncommon", True, "flame"),
    Ach("broken_record", "same_day", 50, "uncommon", True, "reload"),
    Ach("deep_cut", "deep_cut", 1, "common", True, "history"),
    Ach("clicker", "click_plays", 1000, "uncommon", True, "play"),
    Ach("keyboard_warrior", "hotkey_plays", 1000, "rare", True, "keyboard"),
    Ach("tray_ninja", "tray_plays", 100, "uncommon", True, "keyboard"),
    Ach("phone_home", "phone_plays", 100, "uncommon", True, "phone"),
    Ach("chat_puppet", "chat_command", 100, "rare", True, "twitch"),
    Ach("triggered", "trigger", 100, "uncommon", True, "eye"),
    Ach("wait_your_turn", "queued", 1, "common", True, "list"),
    Ach("whisper", "whisper", 20, "common", True, "volume"),
    Ach("loop_de_loop", "loop_s", 10 * 60, "uncommon", True, "reload"),
    Ach("fast_forward", "speed_max", 1, "common", True, "forward"),
    Ach("slow_mo", "speed_min", 1, "common", True, "back"),
    Ach("silence", "quiet_s", HOUR, "common", True, "volume_off"),
    # the board itself
    Ach("blink", "blink", 1, "common", True, "wink"),
    Ach("nice", "nice", 1, "uncommon", True, "wink"),
    Ach("marie_kondo", "deleted", 50, "uncommon", True, "trash"),
    Ach("ctrl_z", "restored", 10, "common", True, "reload"),
    Ach("name_tag", "renamed", 25, "common", True, "rename"),
    Ach("painter", "recoloured", 25, "common", True, "palette"),
    Ach("backup_plan", "backup", 1, "common", True, "archive"),
    Ach("fresh_start", "fresh_start", 1, "common", True, "reload"),
    # links and searches
    Ach("bulk_buyer", "bulk_links", 10, "uncommon", True, "link"),
    Ach("site_seer", "sites", 5, "uncommon", True, "link"),
    Ach("search_engine", "searches", 100, "uncommon", True, "search"),
    Ach("deja_vu", "dup", 1, "common", True, "copy"),
    Ach("not_found", "dl_failed", 5, "common", True, "warn"),
    # radio, voices, Bun
    Ach("station_loyalist", "station_s", 10 * HOUR, "rare", True, "radio"),
    Ach("seven_seas", "continents", 6, "legendary", True, "radio"),
    Ach("quick_change", "run_voices", 10, "uncommon", True, "voice"),
    Ach("talk_show", "voice_run_s", 3 * HOUR, "uncommon", True, "mic"),
    Ach("lost_in_translation", "translate_s", HOUR, "rare", True, "speech"),
    Ach("petting_zoo", "bun_clicks", 100, "uncommon", True, "bun"),
    Ach("owl_pal", "hoot_talk", 25, "uncommon", True, "triggers"),
    Ach("grid_master", "whack_won", 10, "uncommon", True, "gamepad"),
    Ach("rock_solid", "hr_streak", 3, "rare", True, "gamepad"),
    Ach("pack_leader", "store_shared", 10, "rare", True, "upload"),
    # the app
    Ach("babel", "lang_switch", 5, "common", True, "speech"),
    Ach("big_picture", "big_ui", 1, "common", True, "expand"),
    Ach("pocket_size", "mini_s", HOUR, "uncommon", True, "fold"),
    Ach("zen", "lite_on", 1, "common", True, "leaf"),
    # when
    Ach("early_bird", "early", 1, "common", True, "star"),
    Ach("night_shift", "night_s", HOUR, "uncommon", True, "ghost"),
    Ach("comeback_kid", "comeback", 1, "uncommon", True, "history"),
    Ach("leet", "leet", 1, "uncommon", True, "keyboard"),
    Ach("april_fool", "april_fool", 1, "uncommon", True, "laugh"),
    Ach("friday_13th", "friday13", 1, "rare", True, "ghost"),
    Ach("leap_of_faith", "leap_day", 1, "super", True, "star"),
    # the hunt itself
    Ach("overachiever", "all_got", 50, "legendary", True, "trophy"),
    Ach("high_score", "score", 3000, "rare", True, "trophy"),
    Ach("achievement_hunter", "hidden_got", 10, "rare", True, "trophy"),
    Ach("completionist", "all_got", 1, "super", True, "trophy"),   # every other (_goals)
)
BY_ID = {a.id: a for a in ALL}
_BY_STAT: dict[str, list[Ach]] = {}
for _a in ALL:
    _BY_STAT.setdefault(_a.stat, []).append(_a)
del _a

# the stats kept as sets (their value is how many), and the most each needs to hold
SETS = {"stations": 1000, "countries": 300, "upvotes": 100, "voices": 25, "themes": 64,
        "months": 12, "games": 4, "packs": 6, "rares": 3, "weekends": 10, "sites": 5,
        "continents": 6}
# the stats that keep the most seen, not a running total (at_least)
BEST = {"hotkeys", "radio_run_s", "open_run_s", "sounds_added", "longest_s", "at_once",
        "hidden_got", "all_got", "top_plays", "tabs", "streak", "same_day", "loop_s",
        "station_s", "run_voices", "voice_run_s", "hr_streak", "night_s", "quiet_s",
        "bulk_links", "score", "speed_run", "deep_cut", "blink", "nice", "early", "leet",
        "april_fool", "friday13", "leap_day", "comeback", "big_ui", "lite_on", "speed_max",
        "speed_min", "fresh_start"}

# usage.used() names that count (the rest add up for nothing here)
EVENTS = {
    "egg-pong-won": "pong_won", "egg-pong-lost": "pong_lost", "egg-bun-woken": "bun_woken",
    "bun-talk": "bun_talk", "hoot-talk": "hoot_talk", "bun-mode": "bun_mode",
    "stop-all": "stop_all", "sound-vol-0": "vol0", "import-board": "import_board",
    "clip": "clip", "clip-editor": "clip_editor", "dl-add": "dl_add", "record": "record",
    "voice-saved": "voice_saved", "translate-on": "translate", "ai-voice-made": "ai_made",
    "voice-roll": "voice_roll", "store-shared": "store_shared",
    "remote-used-phone": "phone", "api-chat-command": "chat_command",
    "triggers-went-off": "trigger", "mic-unplugged": "unplugged",
    "dl-already-have": "dup",
    "egg-onion-poked": "onion_poked", "egg-onion-eaten": "onion_eaten",
    "egg-onion-please": "onion_please",
    **{f"splash-{k}": f"splash_{k}" for k in ("gold", "ice", "galaxy", "rainbow")},
}
# usage.used() prefixes whose rest goes in a set: egg-game-pong -> games {"pong"}
PREFIX_SETS = (("egg-game-", "games", ("pong", "dodge", "homerun", "whack")),
               ("pack-added-", "packs", ("streamer", "esports", "general", "podcast",
                                         "halloween", "gm-starter")),
               ("splash-", "rares", ("gold", "ice", "galaxy")))
LIVE = {"voice": "voice_s", "apps": "apps_s", "radio": "radio_run_s",
        "translate": "translate_s", "mini": "mini_s"}
DISCO = (10, 30.0)     # Disco Mode: this many theme switches inside this many seconds
ALBUM_END = 0.99       # Full Album: a long sound last seen this far through, then gone
# (month, day, hour, minute) a sound is played on, None for any: Spooky Season, Ho Ho
# Honk, and Happy New Noise in the first minute of the year
DATES = {"halloween": (10, 31, None, None), "christmas": (12, 25, None, None),
         "new_year": (1, 1, 0, 0), "april_fool": (4, 1, None, None),
         "leap_day": (2, 29, None, None), "leet": (None, None, 13, 37)}
EARLY_HOUR = 5         # Early Bird: a sound played between 5 and 6 in the morning
NIGHT_HOURS = range(1, 5)   # Night Shift: the app open between 1 and 5 in the morning
SPEED_RUN = (10, 10.0)  # Speed Run: this many sounds inside this many seconds
DEEP_CUT_DAYS = 30     # Deep Cut: a sound not played for this many days
STREAK_GAP = 1         # days between two launches that still keep the streak
COMEBACK_DAYS = 30     # Comeback Kid: away at least this long
WHISPER = 0.05         # Whisper: played this quietly (the pad's volume x Sounds)
NICE = 69              # Nice: exactly this many sounds on the board
SHORT_S = 1.0          # Blink: a sound shorter than this
STATIONS_KEPT = 200    # radio stations whose listening time is kept (Station Loyalist)
META = ("hidden_got", "all_got", "score")   # the hunt's own: counted from what's earned

on_unlock: list[Callable[[str], None]] = []

_lock = threading.RLock()
_cfg = None
_sets: dict[str, set[str]] = {}
_live: dict[str, float] = {}     # LIVE key -> its time counted up to (time.monotonic)
_on_since: dict[str, float] = {}  # LIVE key -> when it went on
_started = 0.0                   # this run's start, for open_run_s
_dirty = False
_goals: dict[str, float] = {"completionist": len(ALL) - 1}   # set_goal()
_switches: list[float] = []      # the last theme switches' times (Disco Mode)
_long: dict[str, float] = {}     # a long sound playing -> how far through, last seen
_recent: deque = deque(maxlen=SPEED_RUN[0])   # the last plays' times (Speed Run)
_today: dict[str, int] = {}      # sid -> plays today (Broken Record), for _today_day
_today_day = ""
_last_play = 0.0                 # the last sound's time.monotonic() (Silence), 0: none yet
_last_tick = 0.0                 # the last tick's time.monotonic() (Night Shift)
_loops: dict[str, float] = {}    # a looping sound playing -> when it was first seen
_station = ""                    # the radio station playing (Station Loyalist)
_voices_run: set[str] = set()    # voices picked this run (Quick Change)
_hr_run = 0                      # home runs in a row off Bun (Rock Solid)


def attach(cfg, now: float | None = None, today: str | None = None,
           month: int | None = None) -> None:
    """Start counting into `cfg` (the window's, at start): this launch's day and month
    count, and the sounds already on the board count as added."""
    global _cfg, _started, _dirty
    with _lock:
        d = cfg.achievements if isinstance(cfg.achievements, dict) else {}
        for k in ("n", "s", "got", "seen"):
            if not isinstance(d.get(k), dict):
                d[k] = {}
        cfg.achievements = d
        _cfg = cfg
        _sets.clear()
        for k, v in d["s"].items():
            if isinstance(v, list):
                _sets[k] = {str(x) for x in v}
        _live.clear()
        _on_since.clear()
        _started = time.monotonic() if now is None else now
        _dirty = False
        lt = time.localtime()
        today = today or time.strftime("%Y-%m-%d", lt)
        if d["seen"].get("day") != today:
            _new_day(d["seen"], d["seen"].get("day"), today)
            d["seen"]["day"] = today
            bump("days")
        add("months", str(lt.tm_mon if month is None else month))
        sounds_now(len(getattr(cfg, "sounds", ()) or ()))
        _switches.clear()
        _long.clear()
        _recent.clear()
        _today.clear()
        _loops.clear()
        _voices_run.clear()
        global _last_play, _last_tick, _hr_run, _station
        _last_play, _last_tick, _hr_run, _station = 0.0, _started, 0, ""
        for stat in list(d["n"]):   # set while the window was closed (a reset's Fresh Start)
            _check(stat)
        _meta()   # what was earned before the hunt's own were added counts


def _new_day(seen: dict, last: str | None, today: str) -> None:
    """The first launch on `today` (`last`: the one before, or None): days in a row,
    a weekend's week, and back after a long time away."""
    import datetime
    try:
        now = datetime.date.fromisoformat(today)
    except ValueError:
        return
    if now.weekday() >= 5:   # Saturday or Sunday: that week's weekend counts
        year, week, __ = now.isocalendar()
        add("weekends", f"{year}-{week:02d}")
    try:
        gap = (now - datetime.date.fromisoformat(last)).days if last else None
    except ValueError:
        gap = None
    run = seen.get("run")
    run = run + 1 if gap is not None and gap <= STREAK_GAP and isinstance(run, int) else 1
    seen["run"] = run
    at_least("streak", run)
    if gap is not None and gap >= COMEBACK_DAYS:
        at_least("comeback", 1)


def detach() -> None:
    """Stop counting (the window closed; the tests' next window attaches afresh)."""
    global _cfg
    with _lock:
        _cfg = None
        _live.clear()
        _on_since.clear()


def set_goal(ach_id: str, goal: float) -> None:
    """A goal only known at run time (Rainbow Road: how many themes there are)."""
    _goals[ach_id] = goal
    with _lock:
        if _cfg is not None:
            _check(BY_ID[ach_id].stat)


def goal(a: Ach) -> float:
    return _goals.get(a.id, a.goal)


def value(stat: str) -> float:
    """A stat's number now (a set's size)."""
    with _lock:
        if _cfg is None:
            return 0
        if stat in SETS:
            return len(_sets.get(stat, ()))
        n = _cfg.achievements["n"].get(stat, 0)
        return n if isinstance(n, (int, float)) else 0


def got(ach_id: str) -> float:
    """When `ach_id` was earned (a Unix time), or 0."""
    with _lock:
        if _cfg is None:
            return 0
        t = _cfg.achievements["got"].get(ach_id, 0)
        return t if isinstance(t, (int, float)) else 0


def points(a: Ach) -> int:
    """What earning `a` adds to the score."""
    return POINTS.get(a.tier, 0)


def max_score() -> int:
    """The score with every achievement earned."""
    return sum(points(a) for a in ALL)


def score() -> int:
    """The points of every achievement earned so far."""
    with _lock:
        if _cfg is None:
            return 0
        gots = _cfg.achievements["got"]
        return sum(points(a) for a in ALL if a.id in gots)


def earned() -> int:
    with _lock:
        return 0 if _cfg is None else sum(1 for a in ALL if a.id in _cfg.achievements["got"])


# ------------------------------------------------------------------ counting
def bump(stat: str, n: float = 1) -> None:
    global _dirty
    with _lock:
        if _cfg is None:
            return
        c = _cfg.achievements["n"]
        old = c.get(stat, 0)
        c[stat] = (old if isinstance(old, (int, float)) else 0) + n
        _dirty = True
        _check(stat)


def at_least(stat: str, n: float) -> None:
    """Keep the most `stat` has been (a run's length, how many hotkeys)."""
    global _dirty
    with _lock:
        if _cfg is None:
            return
        c = _cfg.achievements["n"]
        old = c.get(stat, 0)
        if not isinstance(old, (int, float)) or n > old:
            c[stat] = n
            _dirty = True
            _check(stat)


def add(stat: str, item: str) -> None:
    """Put `item` in set `stat` (counted once however often it comes)."""
    global _dirty
    with _lock:
        if _cfg is None or not item:
            return
        have = _sets.setdefault(stat, set())
        if item in have or len(have) >= SETS.get(stat, 1000):
            return
        have.add(item)
        _cfg.achievements["s"].setdefault(stat, []).append(item)
        _dirty = True
        _check(stat)


def event(key: str) -> None:
    """A usage.used() feature name."""
    if _cfg is None:
        return
    stat = EVENTS.get(key)
    if stat:
        bump(stat)
    for prefix, stat, keep in PREFIX_SETS:
        if key.startswith(prefix) and key[len(prefix):] in keep:
            add(stat, key[len(prefix):])


def played(hour: int | None = None, when: time.struct_time | None = None, sid: str = "",
           plays: int = 0, gain: float = 1.0, now: float | None = None) -> None:
    """A sound was played (the 3 AM one counts the hour it was played in, the days
    the date). `sid` the board's sound, its `plays` so far and how loud (`gain`, its
    volume times the Sounds volume)."""
    global _last_play, _today_day
    lt = time.localtime() if when is None else when
    now = time.monotonic() if now is None else now
    bump("plays")
    h = lt.tm_hour if hour is None else hour
    if h == 3:
        bump("play_3am")
    if h == EARLY_HOUR:
        at_least("early", 1)
    for stat, (month, day, hr, minute) in DATES.items():
        if (month in (None, lt.tm_mon) and day in (None, lt.tm_mday)
                and hr in (None, h) and minute in (None, lt.tm_min)):
            if stat in BEST:
                at_least(stat, 1)
            else:
                bump(stat)
    if lt.tm_mday == 13 and lt.tm_wday == 4:
        at_least("friday13", 1)
    with _lock:
        _last_play = now
        _recent.append(now)
        count, secs = SPEED_RUN
        if len(_recent) == count and now - _recent[0] <= secs:
            at_least("speed_run", 1)
        if not sid or _cfg is None:
            return
        at_least("top_plays", plays)
        if 0 < gain <= WHISPER:
            bump("whisper")
        day = time.strftime("%Y-%m-%d", lt)
        if day != _today_day:
            _today.clear()
            _today_day = day
        _today[sid] = _today.get(sid, 0) + 1
        at_least("same_day", _today[sid])
        # each sound's last day played: a long gap is a Deep Cut (kept only for sounds
        # on the board, so it never grows past it)
        last = _cfg.achievements["seen"].setdefault("last", {})
        if not isinstance(last, dict):
            last = _cfg.achievements["seen"]["last"] = {}
        today = int(time.mktime(lt) // 86400)
        before = last.get(sid)
        if isinstance(before, int) and today - before >= DEEP_CUT_DAYS:
            at_least("deep_cut", 1)
        last[sid] = today


def played_by(how: str, hidden: bool = False) -> None:
    """How a sound was started: "click" (its pad), "hotkey" (`hidden`: with the window
    closed or minimised) or "phone" (the phone remote)."""
    if how == "hotkey":
        bump("hotkey_plays")
        if hidden:
            bump("tray_plays")
    elif how in ("click", "phone"):
        bump(f"{how}_plays")


def speed(value: float, lowest: float, highest: float) -> None:
    """The live speed was set by hand: all the way up or down."""
    if value >= highest:
        at_least("speed_max", 1)
    elif value <= lowest:
        at_least("speed_min", 1)


def downloaded(site: str, ok: bool, kind: str) -> None:
    """A link or search pick finished: `site` (usage.download_site's word) for an Add
    that worked, or one more that failed."""
    if not ok:
        bump("dl_failed")
    elif kind == "add":
        add("sites", site)


def links_added(n: int) -> None:
    """Add all on `n` pasted links at once."""
    at_least("bulk_links", n)


def voice_picked(name: str) -> None:
    """A voice was picked on the Voice tab: the different ones this run."""
    with _lock:
        if not name or len(_voices_run) >= 100:
            return
        _voices_run.add(name)
        at_least("run_voices", len(_voices_run))


def game_point(game: str, who: str) -> None:
    """A point in one of Bun's games (`who` "you" or "bun"). Home run: home runs in a
    row (a strike ends the run), across games."""
    global _hr_run
    if game == "homerun":
        _hr_run = _hr_run + 1 if who == "you" else 0
        at_least("hr_streak", _hr_run)


def game_won(game: str) -> None:
    """You won one of Bun's games."""
    if game == "whack":
        bump("whack_won")


def at_once(n: int) -> None:
    """`n` of the board's sounds are playing together now (one just started)."""
    at_least("at_once", n)


def pitched(semitones: float) -> None:
    """The live pitch was set by hand: all the way up or down (its normal range)."""
    if semitones >= 12:
        at_least("pitch_up", 1)
    elif semitones <= -12:
        at_least("pitch_down", 1)


def theme_switched(now: float | None = None) -> None:
    """A theme was picked: DISCO's many in a row is Disco Mode."""
    count, secs = DISCO
    now = time.monotonic() if now is None else now
    with _lock:
        _switches.append(now)
        del _switches[:-count]
        if len(_switches) == count and now - _switches[0] <= secs:
            at_least("disco", 1)


def heard(progress: dict[str, float]) -> None:
    """The long sounds (an hour or more, not looping) playing now, sid -> 0..1 through
    (the window's tick). One last seen at its end and gone now played all the way
    through: Full Album."""
    if not progress and not _long:
        return
    with _lock:
        for sid in [s for s in _long if s not in progress]:
            if _long.pop(sid) >= ALBUM_END:
                bump("album")
        _long.update(progress)


def station(uuid: str, country: str, cc: str = "", now: float | None = None) -> None:
    """A radio station started playing (`cc` its ISO country code)."""
    global _station
    add("stations", (uuid or "")[:12])
    add("countries", (country or "").upper()[:3])
    add("continents", CONTINENT.get((cc or "").upper(), ""))
    with _lock:
        if "radio" in _live:   # the one before has its time so far
            _settle("radio", time.monotonic() if now is None else now)
        _station = (uuid or "")[:12]


def voted(sound_id: str, mine: int) -> None:
    """A store vote went through; `mine` is this install's vote now (1 = up)."""
    if mine == 1:
        add("upvotes", str(sound_id)[:24])


def sounds_now(n: int) -> None:
    """The board has `n` sounds: what it gained since last time counts as added."""
    global _dirty
    with _lock:
        if _cfg is None:
            return
        seen = _cfg.achievements["seen"]
        last = seen.get("sounds")
        seen["sounds"] = n
        if not isinstance(last, int):   # the first time: what's on the board counts
            at_least("sounds_added", n)
        elif n > last:
            bump("sounds_added", n - last)
        if n == NICE:
            at_least("nice", 1)
        _dirty = True


def live(key: str, on: bool, now: float | None = None) -> None:
    """A tab's live switch (LIVE: the voice changer heard, a program sent, the radio
    on) went on or off: the time between counts."""
    with _lock:
        if _cfg is None or key not in LIVE:
            return
        now = time.monotonic() if now is None else now
        if on:
            if key not in _live:
                _live[key] = _on_since[key] = now
        elif key in _live:
            _settle(key, now)
            del _live[key], _on_since[key]


def tick(now: float | None = None, tor: bool = False, offline: bool = False,
         hotkeys: int = 0, sounds: int | None = None, longest: float = 0,
         shortest: float = 0, tabs: int = 0, looping=(), hour: int | None = None) -> bool:
    """The window's usage tick: live time so far, this run's length and what's set up
    now (`longest` / `shortest`: the longest and shortest sound on the board, in
    seconds; `tabs` how many; `looping` the looping sounds playing). True when
    something changed since the last tick (save the settings)."""
    global _dirty, _last_tick
    with _lock:
        if _cfg is None:
            return False
        now = time.monotonic() if now is None else now
        for key in list(_live):
            _settle(key, now)
        at_least("open_run_s", now - _started)
        h = time.localtime().tm_hour if hour is None else hour
        if h in NIGHT_HOURS and now > _last_tick:
            bump("night_s", now - _last_tick)
        _last_tick = now
        at_least("quiet_s", now - (_last_play or _started))
        for sid in [s for s in _loops if s not in looping]:
            del _loops[sid]
        for sid in looping:
            at_least("loop_s", now - _loops.setdefault(sid, now))
        if 0 < shortest < SHORT_S:
            at_least("blink", 1)
        if tabs:
            at_least("tabs", tabs)
        for stat, on in (("tor", tor), ("offline", offline), ("hermit", tor and offline)):
            if on and not value(stat):
                bump(stat)
        if longest:
            at_least("longest_s", longest)
        if hotkeys:
            at_least("hotkeys", hotkeys)
        if sounds is not None:
            sounds_now(sounds)
        changed, _dirty = _dirty, False
        return changed


def _settle(key: str, now: float) -> None:
    """Add a live stretch's time since the last settle to its total; for the radio, its
    longest run without a break."""
    if key == "radio":
        at_least("radio_run_s", now - _on_since[key])
        if _cfg is not None and _station and now > _live[key]:   # this station's, all told
            kept = _cfg.achievements["seen"].setdefault("stations_s", {})
            if not isinstance(kept, dict):
                kept = _cfg.achievements["seen"]["stations_s"] = {}
            if _station in kept or len(kept) < STATIONS_KEPT:
                kept[_station] = kept.get(_station, 0) + now - _live[key]
                at_least("station_s", kept[_station])
    elif now > _live[key]:
        bump(LIVE[key], now - _live[key])
        if key == "voice":   # the longest stretch without a break (Talk Show)
            at_least("voice_run_s", now - _on_since[key])
    _live[key] = now


def _check(stat: str) -> None:
    if _cfg is None:
        return
    gots = _cfg.achievements["got"]
    for a in _BY_STAT.get(stat, ()):
        if a.id not in gots and value(stat) >= goal(a):
            gots[a.id] = round(time.time())
            for f in list(on_unlock):
                try:
                    f(a.id)
                except Exception:   # a listener's bug never stops the counting
                    log.exception("achievement listener")
            if stat not in META:
                _meta()
            elif stat != "score":   # (a hunt's own one adds to the score too)
                at_least("score", score())


def _meta() -> None:
    """Achievement Hunter (hidden ones earned) and Completionist (every other one)."""
    if _cfg is None:
        return
    gots = _cfg.achievements["got"]
    at_least("hidden_got", sum(1 for a in ALL if a.hidden and a.id in gots))
    at_least("all_got", sum(1 for a in ALL if a.id != "completionist" and a.id in gots))
    at_least("score", sum(points(a) for a in ALL if a.id in gots))
