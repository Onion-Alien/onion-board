"""The anonymous usage count: how many people use Onion Board, and which versions.

Once a day the installed app sends one "still here" to the project's own server: the
version number and a short tag made from a random ID on this PC (the ID itself stays
here), so the same person isn't counted twice and we can follow how people use the app over time
(which tabs, which versions, whether they come back) to see what to improve.
Also a one-off "first start" (with where they
heard about the app, if they picked it on the installer's last page), and "updated" when
*Update now* installs a new version. With the daily one: which tabs were opened since the
last one (their names only). Soon after a start: how many problems there were since the
last send, as counts, never the report itself: a crash report or a freeze saved
(`crash/<version>`, `error/<version>`, `freeze/<version>`, with the error's type and
the file and line of this app's own code it happened in, e.g. `error/1.9.8/KeyError@
soundboard/audio/engine.py:1090`; also the line that called it and the library function it
was raised or stuck in, and for a freeze how long it lasted and whether the window or
another thread was busy:
never its message or anything else from the report), an error the app caught itself and
showed as a warning instead of crashing (`warned/<version>/<type>@<soundboard/…py:line>`
from `warned()`, the type and the deepest line of our own code it came from, never the
message), a failure its fixed reason (FEATURES) only calls "other" or "timed out", with what
was known where it failed (`failed/<version>/dl-other/ExtractorError/http-410`: the
error's type and our own line, a web status, a Windows error or exit number, or which
wait ran out; failed()), or the last run ending without the app closing itself
(`unclean-exit/<version>/<why>`: a hard crash, ended in Task Manager, a power cut;
exitwatch.py works out which, on this PC), or a run that died before it even started
(`startup-failed/<version>` when the breadcrumb bootmark.py leaves in main.py is still
there the next time, with the native stacks or Windows' own error for it when either is
there). Past MAX_PROBLEMS in one send, one `problems-dropped/<bucket>` says roughly
how many more. On the first start of a new version, `updated/<from>-to-<to>` (so an
update that never finished shows up as an *Update now* without one). One-off events
wait in config.json until a send takes them; at a real quit, what waits (those, and
the tabs and features used since the last daily count) is sent then, so the last
day before someone stops using the app isn't lost (at_quit). And
`uninstall/<version>` when the uninstaller removes it.
With the daily one, a rough picture of how it's used, each as a bucket or a name from a
fixed list: how long ago it was installed (`age/days-2-7`), where sounds go
(`route/mic`), how many sounds the board has and how many were played since the last
one (`sounds/11-50`, `played/1-10`), how long the app was open since then
(`open/1-3h`), how many sounds were fetched from a link or a web search since then
(`downloads/2-5`), how many times it was started since then (`launches/2-5`), the system
(`os/win11`, `os/win10`), the language it's showing and whether it was picked
(`lang/de/picked`, `lang/en/default`), Windows' own language as one the app ships
(`lang-windows/de`: lang_tags()), its theme (`theme/dark`: a
built-in theme's name, else `other`), how many achievements were earned
(`achievements/3-5`) and their score (`ach-score/51-150`), and which features
were used since then (`used/voice-changer`, `used/more-tabs-added-radio`: the names
in FEATURES only; for the Triggers tab, the names the Onion Watch add-on passes to
triggershost.BoardHost.count, as `used/triggers-mode-colour`). A use is only noted
on this PC (used()); it goes with the next daily count, as a yes for that name, never
how many times. And once each,
the first steps of a new install (`step/added-sound`, `step/played-sound`,
`step/sent-to-others`), to see where new people get stuck; never for a copy that was
counted before these existed. Also once each, switching on a tab a new user starts
without (`step/added-radio-tab`, `-apps-`, `-triggers-`): sent when it happens, since
a tab opened after the first daily count waits a day, and most people trying the app
never send that one.
And when someone answers *Send feedback*'s "What would you improve?", their picks
(`improve/sounds`: names from IMPROVE only, sent with a tag from a one-off random ID, not
this PC's), the follow-up ticks under a pick (`improve/sounds/memes`: IMPROVE_MORE only),
and what they typed under Other or Fewer bugs as dashed
words (`improve/other/more-anime-sounds`), with email addresses, links and long numbers
taken out first.
And with the daily one, only for a streamer who ticked the Twitch card's "Let the Onion
Board developer see this channel's name" (off until then) and only while connected, that
channel's Twitch login (`twitch-channel/<login>`).
Nothing else: no name, sounds, settings, devices, games or IP address in the message
(the server sees the connection's address like any site does, and doesn't keep it).

On unless switched off: the installer's "Count me in" box, or Settings > Privacy &
security > Usage count (soundboard.online.net, so it also obeys Offline mode, a proxy and
Tor). Copies from before it existed start with it off: they were installed as an app
that sent nothing. A copy running from source never sends anything, and neither does
one on a PC with ONIONBOARD_NO_STATS set (the developer's own PCs and test VMs)."""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from soundboard import __version__, i18n
from soundboard.core import achievements
from soundboard.core import usageevents
from soundboard.core.usageevents import (  # noqa: F401  (usage.X keeps working)
    DAILY, event, FEATURE_ON, FEATURE_USED, merged, older, place, RUN, TAB)
from soundboard.core.usagereports import (  # noqa: F401  (usage.X keeps working)
    ALL_HELD_MARK, BUSY, GC_SWEEP_MARK, IN_DIALOG_MARK, mark_running, mark_stopped,
    MAX_PROBLEMS, MEM_HIGH, PAGING_PER_S, problems, RUNNING, startup_failed, VERSION_RE,
    _ANY_FRAME, _blocked_in, _busy, _error_attrs, _ERROR_TYPE, _error_type, _frames,
    _freeze_attrs, _INNER, _lasted, _memory, _OUR_FILE, _OUR_FRAME, _ours, _report_event,
    _tb_frames, _tb_where, _where)
from soundboard.core.usagetags import (  # noqa: F401  (usage.X keeps working)
    ach_bucket, ach_tag, age_bucket, bucket, DL_SITES, download_bucket, download_site,
    HEARD, HEARD_ALIASES, HEARD_MAX, heard_tag, launch_bucket, open_bucket, os_tag,
    OTHER_MAX, other_tag, score_bucket, theme_tag, user_tag, _DL_HOSTS, _wordlike)
from soundboard.online import net, netlog
from soundboard.core.usagenames import (  # noqa: F401
    ADDON_FAILS,
    ADDONS,
    APPS_BUILT_IN,
    BUGS_MAX,
    BUN_GAMES,
    CLIP_ACTIONS,
    DAY_S,
    DL_FAILS,
    FEATURES,
    IMPROVE,
    IMPROVE_MORE,
    LANG_RE,
    LIVE_CONTROLS,
    LIVE_PRESETS,
    LIVE_TABS,
    MIC_FAILS,
    MIC_NO_LOAD,
    MIC_KINDS,
    MIC_UNSTARTED,
    MIC_RAISED,
    MIC_STUCK,
    MIC_TESTS,
    PACKS,
    PRESS_MODES,
    RECOVERY,
    RECOVERY_FAILS,
    ROUTES,
    SETTINGS_PAGES,
    SPLASH_RARES,
    STEPS,
    TABS,
    TRIGGERS_FEATURES,
    TWITCH_LOGIN_RE,
    VOICE_SERVERS,
    VOICE_TABS,
)

log = logging.getLogger(__name__)

FEATURE = "usage_stats"   # its switch in Settings > Privacy & security (soundboard.online.net)
# the project's own server; "" sends nothing. No key: one in a public repo would stop no one,
# so the server limits what a send can be and how many it takes (SECURITY.md).
ENDPOINT = "https://onion-board-count.onion-alien.workers.dev/v2/events"
EVERY_S = 24 * 3600
TIMEOUT_S = 15


def enabled() -> bool:
    """Could anything be sent at all: the installed app, with a server, not on a dev PC."""
    return (bool(ENDPOINT) and bool(getattr(sys, "frozen", False))
            and not os.environ.get("ONIONBOARD_NO_STATS"))


def _off(cfg) -> bool:
    """The count's switch is off (or Offline mode is on). Also true the moment the switch
    is saved off, before net is told (the opt-out request runs first): a timer or the quit
    could send with the install ID meanwhile."""
    off = cfg.net_off if isinstance(cfg.net_off, list) else []
    return not net.allowed(FEATURE) or FEATURE in off


def install_id(cfg) -> str:
    """This PC's random ID (made once, kept in config.json)."""
    if not cfg.stats_id:
        cfg.stats_id = uuid.uuid4().hex
    return cfg.stats_id


def due(sent: float, now: float) -> bool:
    """Is the daily count due: a new day on this PC's clock since the last one, or a
    whole day gone by. By the calendar, not 24 hours: someone who used it at 8 pm
    and again at 6 pm the next day counts on both days (with a 24-hour rule the
    second day went with the third, and looked like a day off)."""
    if now - sent >= EVERY_S:
        return True
    return now > sent and time.localtime(now)[:3] != time.localtime(sent)[:3]


def hits(cfg, now: float, one: dict | None = None, extra=()) -> list[dict]:
    """What a send would say: the daily event for this version if one is due (with
    "first_start" the first time ever, the tabs opened and the features used since the last
    one), or the one event `one`. `extra` (problem events) go now, due or not."""
    install_id(cfg)
    if one:
        return [one]
    out = list(extra)
    if not due(cfg.stats_sent, now):
        return out
    attrs, on = about(cfg, now)
    out.insert(0, event(DAILY, at=now, **attrs))
    if not cfg.stats_sent:
        out.append(event("first_start", at=now, heard=heard_tag(cfg.stats_heard)))
    out += [event(TAB, at=now, tab=t) for t in cfg.stats_tabs if t in TABS]
    uses = _feature_uses(cfg)
    out += [event(FEATURE_USED, at=now, count=uses[k], feature=k) for k in FEATURES if k in uses]
    out += [event(FEATURE_ON, at=now, feature=k) for k in FEATURES if k in on and k not in uses]
    login = cfg.twitch_login
    if cfg.twitch_share and cfg.twitch_token and re.fullmatch(TWITCH_LOGIN_RE, login or ""):
        # only when the streamer ticked the Twitch card's box, and only while connected
        out.append(event("twitch_channel", at=now, login=login))
    return out


def _feature_uses(cfg) -> dict[str, int]:
    """How many times each feature in cfg.stats_used was used since the last send. One an
    older version noted, with no number, counts once."""
    counts = cfg.stats_use_counts if isinstance(cfg.stats_use_counts, dict) else {}
    have = cfg.stats_used if isinstance(cfg.stats_used, list) else []
    out = {}
    for k in have:
        n = counts.get(k)
        out[k] = n if isinstance(n, int) and not isinstance(n, bool) and n > 0 else 1
    return out


# how long the app was open: added up every OPEN_TICK_S (open_tick); a longer gap than
# OPEN_GAP_S (the PC slept or hibernated) counts as nothing
OPEN_TICK_S = 300
OPEN_GAP_S = 600
_open_mark: float | None = None


def open_tick(cfg, now: float | None = None) -> None:
    """Add the time since the last tick to cfg.stats_open_s (for the next daily count's
    `open/`). Called at start, every OPEN_TICK_S, before a send and at quit."""
    global _open_mark
    now = time.monotonic() if now is None else now
    counting = enabled() and net.allowed(FEATURE)   # off: nothing piles up for later
    if counting and _open_mark is not None and 0 < now - _open_mark <= OPEN_GAP_S:
        cfg.stats_open_s = max(0.0, float(cfg.stats_open_s or 0)) + (now - _open_mark)
    _open_mark = now


def downloaded(cfg, url: str, via: str, kind: str, ok: bool, why: str = "") -> None:
    """A link or web-search pick finished (ui/sounds/linkbar.py): `via` "link" or "search",
    `kind` "add" or "play", `why` it failed (DL_FAILS). Counted as used() names, and one
    more for the next daily `downloads/` when it worked (only while the count is on,
    like open_tick)."""
    site = download_site(url)
    achievements.downloaded(site, ok, kind)
    if not ok:
        used(f"dl-failed-{site}")
        used(f"dl-failed-why-{why if why in DL_FAILS else 'other'}")
        return
    for k in (site, via, kind):
        used(f"dl-{k}")
    if enabled() and net.allowed(FEATURE):
        cfg.stats_downloads = max(0, int(cfg.stats_downloads or 0)) + 1


def started(cfg) -> None:
    """At start: count this launch for the next daily count's `launches/`, and when
    another version ran here last, keep `updated/<from>-to-<to>` for the next send
    (however it was updated: *Update now*, the installer, a download). Nothing piles
    up while the count is off; the version is noted either way."""
    old, cfg.stats_version = cfg.stats_version, __version__
    if not enabled() or not net.allowed(FEATURE):
        return
    cfg.stats_launches = max(0, int(cfg.stats_launches or 0)) + 1
    if old and old != __version__ and re.fullmatch(VERSION_RE, old):
        _keep(cfg, [event("updated", **{"from": old})])


def total_plays(cfg) -> int:
    return sum(max(0, int(getattr(m, "plays", 0) or 0)) for m in cfg.sounds)


def settle(cfg, now: float) -> None:
    """Once: when this install started, for age/. A copy counted before this existed
    (or with sounds already played) isn't a new install: its age comes from the app
    folder, and its first steps are long done, so they're never sent."""
    if cfg.stats_started:
        return
    if cfg.stats_sent or total_plays(cfg):
        born = cfg.stats_sent or now
        try:
            from soundboard.sounds.library import APP_DIR
            born = min(born, APP_DIR.stat().st_ctime)   # created, on Windows
        except (OSError, ImportError):
            pass
        cfg.stats_started = born
        cfg.stats_steps = list(STEPS)
        cfg.stats_plays = total_plays(cfg)
    else:
        cfg.stats_started = now


_used: set[str] = set()   # features used this run, kept in cfg by remember()
_use_counts: dict[str, int] = {}   # how many times each, this run


def addon_tag(module_id: str) -> str:
    """An add-on's id as a count's word: one of ADDONS, else "other"."""
    return module_id if module_id in ADDONS else "other"


def used(key: str) -> None:
    """Feature `key` (one of FEATURES) was used, for the next daily count (and for
    Settings > Achievements' counting)."""
    achievements.event(key)
    if key in FEATURES and net.allowed(FEATURE):   # off: nothing piles up for later
        _used.add(key)
        _use_counts[key] = _use_counts.get(key, 0) + 1


def ffmpeg_state(cfg, state: str, fault: str = "") -> None:
    """Remember a broken copy or failed get until a later check verifies it works.
    The marker survives daily sends and restarts; missing on a new install is normal,
    and an unknown check or a cancelled get cannot prove recovery. A check that only
    timed out ("slow") is neither: on a new install's first start the virus scan of the
    new ffmpeg.exe can outlast it, and it works a moment later. If the get it starts
    then fails, get-failed still counts. Only fixed feature
    names are counted, never a path or error message; a broken one also with `fault`
    (ffmpegget.Health.fault: `gone`, `err-193`, `exit-N`) by failed().
    On purpose, only this count's own switch (and Offline / Tor) stop it, not FFmpeg's
    download switch: the check that finds a broken copy is local, so with that switch off
    a broken copy still counts, no get runs (so no get-failed), and a copy the user fixes
    themselves still counts as recovered on the next check.
    """
    if not enabled() or not net.allowed(FEATURE) or net.mode() == net.TOR:
        cfg.stats_ffmpeg_failed = False
        return
    if state == "slow":
        return
    if state in ("broken", "get-failed"):
        cfg.stats_ffmpeg_failed = True
        if state == "broken":
            used("ffmpeg-broken")
            failed("ffmpeg-broken", fault)
    elif state == "ok" and cfg.stats_ffmpeg_failed:
        used("ffmpeg-recovered")
        cfg.stats_ffmpeg_failed = False


def remember(cfg) -> None:
    """Keep this run's used() features in cfg (so they survive a quit before the
    next daily count). With the count off, nothing is kept: what waited is dropped, so
    switching it back on never sends what happened while it was off."""
    if _off(cfg):
        _used.clear()
        _use_counts.clear()
        del _pending[:]
        cfg.stats_used, cfg.stats_pending, cfg.stats_tabs = [], [], []
        cfg.stats_events, cfg.stats_use_counts = [], {}
        cfg.stats_problems_seen = max(cfg.stats_problems_seen or 0, time.time())
        return
    have = cfg.stats_used if isinstance(cfg.stats_used, list) else []
    new = [k for k in FEATURES if k in _used and k not in have]
    _used.clear()
    if new:
        cfg.stats_used = [*have, *new]
    counts = dict(cfg.stats_use_counts) if isinstance(cfg.stats_use_counts, dict) else {}
    for k, n in list(_use_counts.items()):
        if k in FEATURES:
            counts[k] = min(max(0, int(counts.get(k) or 0)) + n, usageevents.MAX_COUNT)
    _use_counts.clear()
    cfg.stats_use_counts = counts
    if isinstance(cfg.stats_pending, list) and cfg.stats_pending:   # left by an older version
        _keep(cfg, [older(e) for e in cfg.stats_pending if isinstance(e, str)])
        cfg.stats_pending = []
    if _pending:   # note()d events: kept in cfg too, so a quit before the send keeps them
        taken = _pending[:]
        del _pending[:len(taken)]
        _keep(cfg, taken)
    elif not isinstance(cfg.stats_events, list):
        cfg.stats_events = []


def features_now(cfg) -> list[str]:
    """Features that are set up, counted as used every day they are."""
    out = []
    if any(getattr(m, "hotkey", "") for m in cfg.sounds) or cfg.category_hotkeys:
        out.append("hotkeys")
    if cfg.remote_addons or cfg.api_enabled:
        out.append("phone-remote")
    stream = cfg.api_stream if cfg.api_enabled and isinstance(cfg.api_stream, dict) else {}
    if stream.get("chat"):
        out.append("api-chat-rules")
    if stream.get("alerts") and stream.get("alerts_on", True) is not False:
        out.append("api-alerts")
    if cfg.hidden_from_all:
        out.append("hidden-from-all")
    fx = cfg.voice_fx if isinstance(cfg.voice_fx, dict) else {}
    bg = (fx.get("effects") or {}).get("backdrop") if fx.get("enabled") else None
    if isinstance(bg, dict) and bg.get("on"):
        from soundboard.voicefx import backdrop
        if bg.get("sounds") or any(_positive(bg.get(k)) for k in backdrop.LAYERS):
            out.append("voice-background")
        if bg.get("sounds"):
            out.append("voice-background-sounds")
    if cfg.also_send:
        out.append("also-send")
    if not cfg.theme_texture:
        out.append("textures-off")
    from soundboard.online import quality
    if not quality.current.keep_source:
        out.append("source-off")
    if set(cfg.apps_categories or ()) - set(APPS_BUILT_IN):
        out.append("apps-own-categories")
    if not cfg.sidebar_open:
        out.append("rail-shut")
    if cfg.net_mode in ("proxy", "tor"):
        out.append(f"net-{cfg.net_mode}")
    if cfg.net_offline:
        out.append("net-offline")
    if cfg.playing_background:
        out.append("playing-bg")
    modes = {getattr(m, "mode", "") for m in cfg.sounds}
    out += [f"press-{k}" for k in PRESS_MODES if k in modes]
    for key, view in (("sounds", cfg.pad_view), ("apps", cfg.app_view)):
        if view == "list":
            out.append(f"view-list-{key}")
    if cfg.voice_view == "advanced":
        out.append("view-advanced-voice")
    if not cfg.hotkeys_share:
        out.append("hotkeys-share-off")
    if cfg.voice_hotkeys:
        out.append("voice-hotkeys")
    if cfg.ptt_key:
        out.append("auto-ptt")
    if not cfg.voice_level:
        out.append("voice-leveler-off")
    voices = [(getattr(m, "fx", None) or {}).get("voice") for m in cfg.sounds]
    voices = [v for v in voices if isinstance(v, dict) and v]
    if voices:
        out.append("sound-voice")
    if any(v.get("ai") for v in voices):
        out.append("sound-ai-voice")
    if cfg.lite_mode:
        out.append("lite-mode")
    if cfg.light_voice in ("on", "off"):   # picked by hand ("auto" follows Lite mode)
        out.append(f"light-voice-{cfg.light_voice}")
    if cfg.twitch_token:
        out.append("twitch-connected")
    if cfg.achievement_popups:
        out.append("achievement-popups")
        if cfg.achievement_sound:
            out.append("achievement-chime")
    from soundboard.mic import michelper
    if cfg.route == "mic" and michelper.known():   # its last check's answer, no new one
        out.append("mic-helper")
    if not cfg.mic_helper:
        out.append("mic-helper-off")
    return out


def _positive(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0


def achieved(ach_id: str) -> None:
    """An achievement was earned (core/achievements.py): its id, for the next daily count.
    Ids not in its fixed list (a newer version's) are never sent."""
    if ach_id in achievements.BY_ID:
        used(ach_tag(ach_id))


def live_preset_tag(name: str) -> str:
    """A Live controls effect preset's name as a count's word ("Bass boosted" ->
    bass-boosted); one not in LIVE_PRESETS is "other"."""
    tag = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return tag if tag in LIVE_PRESETS else "other"


def game_tag(name: str) -> str:
    """A Bun game's name as a count's word: one of BUN_GAMES, else "other"."""
    return name if name in BUN_GAMES else "other"


def pack_tag(pack_id: str) -> str:
    """A free pack's id as a count's word: one of PACKS, else "other" (a pack from
    the online list that's newer than this version)."""
    return pack_id if pack_id in PACKS else "other"


def about(cfg, now: float) -> tuple[dict, list[str]]:
    """The daily event's picture of how it's used (see the docstring): buckets and names
    from fixed lists only. And the features that are set up today."""
    got = cfg.achievements.get("got") if isinstance(cfg.achievements, dict) else None
    got = got if isinstance(got, dict) else {}
    score = sum(achievements.points(a) for a in achievements.ALL if a.id in got)
    attrs = {"age": age_bucket((now - (cfg.stats_started or now)) / DAY_S),
             "route": cfg.route if cfg.route in ROUTES else "",
             "sounds": bucket(len(cfg.sounds)),
             "played": bucket(total_plays(cfg) - cfg.stats_plays),
             "open": open_bucket(cfg.stats_open_s or 0),
             "downloads": download_bucket(cfg.stats_downloads or 0),
             **lang_attrs(cfg),
             "theme": theme_tag(cfg.theme),
             "launches": launch_bucket(cfg.stats_launches or 0),
             "achievements": ach_bucket(len(got)),
             "ach_score": score_bucket(score)}
    return attrs, features_now(cfg)


def lang_attrs(cfg) -> dict:
    """The language the app is showing and where it came from (`lang`: `de`, `lang_source`:
    picked in Settings, `default` when none is picked so English, or `windows` once the
    board follows Windows by itself). And Windows' own display language as a catalog the
    app ships (`lang_windows`; `en` when none fits), to see which languages people would
    like. Language codes only, never the locale."""
    def code(c: str) -> str:
        return c if re.fullmatch(LANG_RE, c or "") else "other"
    if cfg.language:
        source = "picked"
    else:
        source = "windows" if i18n.FOLLOW_WINDOWS else "default"
    return {"lang": code(i18n.current()), "lang_source": source,
            "lang_windows": code(i18n.resolve(i18n.windows_language()))}


def tab_opened(cfg, key: str) -> None:
    """Remember that tab `key` was opened, for the next daily count."""
    tabs = cfg.stats_tabs if isinstance(cfg.stats_tabs, list) else []
    if key in TABS and key not in tabs and not _off(cfg):
        cfg.stats_tabs = [*tabs, key]


_pending: list[dict] = []   # events for the next send, such as an unclean exit found at start
MAX_PENDING = 50            # one-off events kept in cfg.stats_events while unsent


def note(one: dict | None) -> None:
    """Send event `one` with the next count (any thread: remember() moves it into cfg)."""
    if one and net.allowed(FEATURE):   # off: nothing piles up for later
        _pending.append(one)


def _keep(cfg, events) -> None:
    """Keep one-off events in cfg.stats_events until a send takes them."""
    have = [e for e in (cfg.stats_events if isinstance(cfg.stats_events, list) else [])
            if isinstance(e, dict)]
    cfg.stats_events = usageevents.worst_first(
        merged([*have, *(e for e in events if e)]), MAX_PENDING)[:MAX_PENDING]


_warned: set[str] = set()   # reportable problems handled this run, for warned()


def warned(e: BaseException) -> None:
    """The app caught an error it couldn't fix and showed the user itself, as a warning
    instead of a crash (errors.warn / errors.html): count that it happened, once per
    distinct (type, place) per run, as a `warned` event with the type and the chain of our
    own code it came from (like `error` events), never its message (a message can hold a
    path, a device or a user name). A string problem (no traceback) isn't counted."""
    if not isinstance(e, BaseException):
        return
    frames = _tb_frames(e.__traceback__)
    _warned_event(type(e).__name__, frames[-1].rsplit(":", 1)[0] if frames else "", frames)


def warned_at(kind: str, where: str = "") -> None:
    """warned() for an error caught in another process (the mic effect's admin step,
    read back from its log): its type `kind` (`struct.error`) and `where`, the deepest
    of our own lines (`soundboard/mic/micadmin.py:445`), or "" if none. Anything else
    isn't counted."""
    if not re.fullmatch(r"[A-Za-z_][\w.]{0,60}", kind or ""):
        return
    if where and not re.fullmatch(_OUR_FILE.pattern + r":\d{1,6}", where):
        where = ""
    _warned_event(kind, where, [f"{where}:"] if where else [])


def _warned_event(kind: str, where: str, frames: list[str]) -> None:
    key = f"{kind}@{where}" if where else kind
    if key in _warned:
        return
    _warned.add(key)
    note(event("warned", version=__version__, type=kind, **place(frames)))


# the counts that only said "another reason" or "timed out", given a detail by failed()
FAILED = ("dl-other", "search-other", "search-timeout", "ffmpeg-broken", "ffmpeg-get",
          "mic-code-1", "mic-code", "addon-other", "addon-step")
# one part of a failed() detail: a word or number we made (`helper`, `http-403`,
# `err-10013`), or an error's type with the deepest of our own lines
# (`OSError@soundboard/addons/modules.py:771`); never a message, a path or a link
_DETAIL = re.compile(r"[A-Za-z_][\w.-]{0,60}(?:@" + _OUR_FILE.pattern + r":\d{1,6})?")
_failed: set[str] = set()   # failed() details sent this run


def failed(what: str, *detail: str) -> None:
    """Count `what` (one of FAILED), a count that only says it failed, with what was known
    where it did: a `failed` event whose `detail` is a list of words or numbers we made or
    an error's type and place (error_detail, timeout_kind), and those as fields of their own
    when they have one (_detail_fields). Never its message. Once per distinct one per run;
    a part that isn't one of those is left out."""
    parts = [d for d in detail if d and _DETAIL.fullmatch(d)][:3]
    if what not in FAILED or not parts:
        return
    key = "/".join((what, *parts))
    if key in _failed:
        return
    _failed.add(key)
    note(event("failed", version=__version__, what=what, detail=parts,
               **_detail_fields(parts)))


def _detail_fields(parts: list[str]) -> dict:
    """failed()'s words as fields: `OSError@soundboard/x.py:12` as type, file and line,
    `http-404` as http, `err-5` as win_error, `errno-13` as errno."""
    out: dict = {}
    for p in parts:
        kind, at, where = p.partition("@")
        if at:
            file, _, line = where.rpartition(":")
            out.update(type=kind, file=file, line=int(line))
        elif m := re.fullmatch(r"(http|err|errno)-(\d{1,10})", p):
            key = {"http": "http", "err": "win_error", "errno": "errno"}[m.group(1)]
            out[key] = int(m.group(2))
    return out


def error_detail(e: BaseException | None) -> list[str]:
    """What failed() may say about exception `e`: its type (yt-dlp's own class for a
    download error, `.kind`), where in our code it was raised when that's known, and the
    number it carried: a web status (`http-404`), a Windows error (`err-5`) or an errno
    (`errno-13`), read from the exception or its text. Nothing else of the text."""
    if e is None:
        return []
    kind = getattr(e, "kind", "") or type(e).__name__
    where = _tb_where(e.__traceback__)
    out = [f"{kind}@{where}" if where else kind]
    text = f"{getattr(e, 'raw', '')} {e}"
    code = getattr(e, "code", None)
    m = re.search(r"HTTP Error (\d{3})", text)
    if isinstance(code, int) and 100 <= code <= 599:
        out.append(f"http-{code}")
    elif m:
        out.append(f"http-{m.group(1)}")
    win = getattr(e, "winerror", None)
    num = getattr(e, "errno", None)
    m = re.search(r"\[WinError (\d{1,10})\]", text)
    m2 = re.search(r"\[Errno (\d{1,5})\]", text)
    if isinstance(win, int):
        out.append(f"err-{win}")
    elif m:
        out.append(f"err-{m.group(1)}")
    elif isinstance(num, int):
        out.append(f"errno-{num}")
    elif m2:
        out.append(f"errno-{m2.group(1)}")
    return out


def failure_detail(why: str, e: BaseException | None) -> list[str]:
    """What failed() may add to a download or search that failed with DL_FAILS `why`:
    for "other" the error (error_detail), for "timeout" which wait ran out
    (timeout_kind); nothing for the others, their word says it."""
    if why == "other":
        return error_detail(e)
    return [timeout_kind(e)] if why == "timeout" else []


def timeout_kind(e: BaseException | str | None) -> str:
    """Which wait ran out, from a timed-out download's text: our own wait for the download
    helper (`helper`), the connection being made (`connect`), the secure handshake
    (`handshake`), an answer that stopped coming (`read`), else `other`."""
    if getattr(e, "kind", "") == "helper-timeout":
        return "helper"
    text = f"{getattr(e, 'raw', '')} {e}".lower()
    return ("handshake" if "handshake" in text else
            "connect" if re.search(r"connect(?:ion)?\b[^.]{0,80}timed? ?out|connect timeout",
                                   text) else
            "read" if re.search(r"read timed? ?out|read operation timed out", text) else
            "other")


def uninstall_event() -> dict:
    return event("uninstall")


OPT_OUT_WHERE = ("installer", "settings")
OPT_OUT_TIMEOUT_S = 5   # the installer waits on it: never long


def opt_out(where: str) -> bool:
    """Count me in switched from on to off (`where`: the installer's box or Settings):
    one last `opt_out` event so we know how many people aren't counted, then nothing
    ever again. No random ID, no tag: it can't be tied to anything they
    sent before. Only while the count is still allowed (call it before switching it
    off), and never in Tor mode (SECURITY.md). Waits for the answer: call it off the
    UI thread."""
    if (where not in OPT_OUT_WHERE or not enabled() or not net.allowed(FEATURE)
            or net.mode() == net.TOR):
        return False
    netlog.cause(FEATURE, f"Anonymous usage count (opt-out {where}, the last one)")
    return send([event("opt_out", where=where)], timeout=OPT_OUT_TIMEOUT_S)


def update_event(to: str) -> dict:
    """The event for *Update now* from this version to `to`."""
    return event("update_now", to=to)


MAX_EVENTS = 100   # the server's most per request: a longer list goes in parts


def send(events: list[dict], timeout: float = TIMEOUT_S, install: str = "", run: str = "") -> bool:
    """POST them to the counter, MAX_EVENTS at a time. True if it took them all (it stops
    at the first part it didn't take). Call off the UI thread."""
    for i in range(0, max(len(events), 1), MAX_EVENTS):
        if not _send_part(events[i:i + MAX_EVENTS], timeout, install, run):
            return False
    return True


def _send_part(events: list[dict], timeout: float, install: str, run: str) -> bool:
    """One request: usageevents.message."""
    body = json.dumps(usageevents.message(events, install, run)).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "OnionBoard"})
    try:
        with net.urlopen(req, timeout=timeout, feature=FEATURE) as r:
            return 200 <= r.status < 300
    except Exception as e:  # noqa: BLE001 - offline, switched off meanwhile, counter down
        log.info("usage count not sent: %s", e)
        return False


def _tagged(cfg) -> dict:
    """send()'s arguments for a send from this PC: its tag, and this start of the app."""
    return {"install": user_tag(install_id(cfg)), "run": RUN}


MEMORY_FULL = 90   # % of the PC's memory in use from which the count waits


def _memory_full() -> bool:
    """The PC is short of memory: Windows is swapping to disk, and even starting the
    count's thread could stall the window for many seconds. A PC that stays this full
    all day goes uncounted: fine, the count never slows anyone down."""
    from soundboard.core import hangwatch
    load = hangwatch.memory_load()
    return load is not None and load >= MEMORY_FULL


def maybe_send(cfg, on_sent=None, one: dict | None = None, app_dir: Path | None = None) -> None:
    """The daily count if it's due (or the event `one` now), on a thread, when it's allowed.
    Problems since the last send go too, due or not: note()d ones, and with `app_dir`
    the reports saved there.

    The thread only sends what was gathered here; cfg belongs to the UI thread, which
    keeps adding to the same stats_* fields (tab_opened, downloaded, remember). Once a
    count (not a `one`) went, `on_sent(apply)` is called on that thread: the caller
    runs apply() on the thread that owns cfg (the main window queues it to the UI
    thread), and apply clears exactly what was sent, keeping anything added meanwhile.
    Without on_sent, apply runs right there (a caller with no UI thread)."""
    if not enabled() or _off(cfg):
        return
    if not one and _memory_full():   # a later check sends it; an event goes anyway
        return
    now = time.time()
    settle(cfg, now)
    remember(cfg)
    if not cfg.stats_problems_seen:   # first run with this: older reports aren't news
        cfg.stats_problems_seen = now
    pending = [] if one else list(cfg.stats_events)   # remember() made it a clean list
    taken, since = pending[:], cfg.stats_problems_seen
    open_tick(cfg)
    base = hits(cfg, now, one)   # the daily count or the event; problems join on the thread
    if not base and not pending and app_dir is None:
        return
    daily = bool(base) and not one and base[0]["name"] == DAILY
    tabs = [e["attrs"]["tab"] for e in base if e["name"] == TAB]
    uses = {e["attrs"]["feature"]: e.get("count", 1) for e in base if e["name"] == FEATURE_USED}
    plays = total_plays(cfg)
    opened = cfg.stats_open_s or 0
    launches = cfg.stats_launches or 0
    downloads = cfg.stats_downloads or 0
    netlog.cause(FEATURE, "Anonymous usage count" + (f" ({one['name']})" if one
                                                     else " (once a day)" if daily
                                                     else " (problems)"))

    def apply():   # on the thread that owns cfg: only what this count took
        if daily:
            cfg.stats_sent = now
            cfg.stats_tabs = [t for t in cfg.stats_tabs if t not in tabs]
            _forget_uses(cfg, uses)
            cfg.stats_plays = plays
            cfg.stats_open_s = max(0.0, (cfg.stats_open_s or 0) - opened)   # since then
            cfg.stats_launches = max(0, (cfg.stats_launches or 0) - launches)
            cfg.stats_downloads = max(0, (cfg.stats_downloads or 0) - downloads)
        cfg.stats_events = _without(cfg.stats_events, taken)
        cfg.stats_problems_seen = max(cfg.stats_problems_seen, newest[0])

    newest = [0.0]
    tag = _tagged(cfg)

    def run():   # the saved reports and the network only: never touches cfg
        # the reports folder is read here, not on the UI thread that called: a send
        # follows each saved report, so it comes when the PC is already struggling
        extra, newest[0] = ([], 0.0) if one else _with_reports(pending, app_dir, since)
        payload = [*base[:1], *extra, *base[1:]]   # as hits()
        if payload and send(payload, **tag) and not one:
            (on_sent or (lambda f: f()))(apply)
    threading.Thread(target=run, daemon=True, name="usage-count").start()


def _forget_uses(cfg, uses: dict[str, int]) -> None:
    """Take what a send said out of cfg: uses added meanwhile stay for the next one."""
    counts = cfg.stats_use_counts if isinstance(cfg.stats_use_counts, dict) else {}
    left = {k: counts[k] - uses.get(k, 0) for k in counts
            if isinstance(counts[k], int) and counts[k] > uses.get(k, 0)}
    cfg.stats_use_counts = left
    cfg.stats_used = [k for k in cfg.stats_used if k not in uses or k in left]


def _waiting(cfg, now: float, app_dir: Path | None) -> tuple[list[dict], list[dict], float]:
    """The one-off and problem events waiting for a send: (the events, the ones taken
    from cfg.stats_pending, the newest report's time). Call after remember()."""
    if not cfg.stats_problems_seen:   # first run with this: older reports aren't news
        cfg.stats_problems_seen = now
    taken = list(cfg.stats_events)   # remember() just made it a clean list
    extra, newest = _with_reports(taken, app_dir, cfg.stats_problems_seen)
    return extra, taken, newest


def _with_reports(extra: list[dict], app_dir: Path | None,
                  since: float) -> tuple[list[dict], float]:
    """`extra` and the events for the reports saved in app_dir after `since`, the same one
    twice as one with a count, at most MAX_PROBLEMS different ones (one `problems_dropped`
    says how many more), and the newest report's time. Reads the disk: maybe_send calls it
    on its thread."""
    extra, skipped, newest = list(extra), [0], 0.0
    if app_dir is not None:
        found, newest = problems(app_dir, since, skipped)
        extra += found
    extra = usageevents.worst_first(merged(extra), MAX_PROBLEMS)
    dropped = skipped[-1] + sum(e.get("count", 1) for e in extra[MAX_PROBLEMS:])
    extra = extra[:MAX_PROBLEMS]
    if dropped:   # a bug in a loop: one count saying how many more
        extra.append(event("problems_dropped", count=dropped))
    return extra, newest


def _without(have, sent) -> list[dict]:
    """`have` with each of `sent` taken out once: any added meanwhile stay."""
    left = [e for e in (have if isinstance(have, list) else []) if isinstance(e, dict)]
    for e in sent:
        if e in left:
            left.remove(e)
    return left


QUIT_WAIT_S = 2.0   # the longest a quit waits for at_quit's send (it runs while the rest closes)


def at_quit(cfg, app_dir: Path | None = None):
    """At a real quit: what's waiting for the next count, sent now, so the last day
    someone used the app isn't lost when they never start it again (or closed it
    within a minute of starting). Only the events the next count would carry anyway:
    the features used (not features_now, which the daily count adds), the tabs opened and
    the one-off and problem events waiting. Never the daily count
    itself or its buckets, and nothing when nothing waits.

    Starts the send on a thread and returns finish(), or None when nothing goes. Call
    finish() later in the quit, on the thread that owns cfg: it waits what's left of
    QUIT_WAIT_S and returns True when the counter took them, after clearing exactly
    those from cfg (save it after). If it didn't (offline, too slow), they stay for
    the next count."""
    if not enabled() or _off(cfg):
        return None
    now = time.time()
    settle(cfg, now)
    remember(cfg)
    all_uses = _feature_uses(cfg)
    uses = {k: all_uses[k] for k in FEATURES if k in all_uses}
    tabs = [t for t in TABS if t in (cfg.stats_tabs if isinstance(cfg.stats_tabs, list)
                                     else [])]
    extra, taken, newest = _waiting(cfg, now, app_dir)
    payload = [*(event(FEATURE_USED, at=now, count=n, feature=k) for k, n in uses.items()),
               *(event(TAB, at=now, tab=t) for t in tabs), *extra]
    if not payload:
        return None
    tag = _tagged(cfg)
    netlog.cause(FEATURE, "Anonymous usage count (at quit)")
    done: list[bool] = []
    end = time.monotonic() + QUIT_WAIT_S
    t = threading.Thread(target=lambda: done.append(send(payload, timeout=QUIT_WAIT_S, **tag)),
                         daemon=True, name="usage-count")
    t.start()

    def finish() -> bool:
        t.join(max(0.0, end - time.monotonic()))
        if not (done and done[0]):
            return False
        _forget_uses(cfg, uses)
        cfg.stats_tabs = [k for k in cfg.stats_tabs if k not in tabs]
        cfg.stats_events = _without(cfg.stats_events, taken)
        cfg.stats_problems_seen = max(cfg.stats_problems_seen, newest)
        return True
    return finish


def step(cfg, name: str, on_sent=None) -> None:
    """A new install's first time doing `name` (one of STEPS): sent right away, once.
    A copy counted before these existed never sends them (settle)."""
    if name not in STEPS or not enabled() or not net.allowed(FEATURE):
        return
    settle(cfg, time.time())
    if name in cfg.stats_steps:
        return
    cfg.stats_steps = [*cfg.stats_steps, name]
    maybe_send(cfg, on_sent, one=event("step", step=name))


def improve(cfg, picks, other: str = "", bugs: str = "") -> bool:
    """The feedback box's "What would you improve?" picks, sent now as `improve` events:
    `pick` (names from IMPROVE only), `more` their follow-up ticks (`sounds/memes` in
    `picks`, names from IMPROVE_MORE only) and `said` what was typed under Other or Fewer
    bugs (other_tag, BUGS_MAX for bugs). Anonymous: they go with a one-off random ID made
    for this send and no run, never this PC's stats_id, so they can't be linked to the
    daily count or to each other. False when nothing can be sent (usage count off, offline,
    running from source)."""
    events = []
    for k in IMPROVE:
        if k not in picks:
            continue
        events.append(event("improve", pick=k, said=other_tag(other) if k == "other" else ""))
        events += [event("improve", pick=k, more=sub) for sub in IMPROVE_MORE.get(k, ())
                   if f"{k}/{sub}" in picks]
        said = other_tag(bugs, BUGS_MAX) if k == "bugs" else ""
        if said:
            events.append(event("improve", pick="bugs", said=said))
    if not events or not enabled() or not net.allowed(FEATURE):
        return False
    tag = user_tag(uuid.uuid4().hex)   # never install_id(cfg): the box says it is not linked
    netlog.cause(FEATURE, "Anonymous usage count (feedback picks)")
    threading.Thread(target=send, args=(events,), kwargs={"install": tag}, daemon=True,
                     name="usage-count").start()
    return True


def send_now(cfg, one: dict) -> bool:
    """Send event `one` and wait for it (the uninstaller's `--uninstall-count`)."""
    if not enabled() or not net.allowed(FEATURE):
        return False
    netlog.cause(FEATURE, f"Anonymous usage count ({one['name']})")
    return send(hits(cfg, time.time(), one), **_tagged(cfg))
