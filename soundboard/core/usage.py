"""The anonymous usage count: how many people use Onion Board, and which versions.

Once a day the installed app sends one "still here" to the project's GoatCounter
(a privacy-friendly counter): the version number and a random ID made on this PC, so
the same person isn't counted twice and we can follow how people use the app over time
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
(`improve/sounds`: names from IMPROVE only, sent with a one-off random session, not this
PC's ID), the follow-up ticks under a pick (`improve/sounds/memes`: IMPROVE_MORE only),
and what they typed under Other or Fewer bugs as dashed
words (`improve/other/more-anime-sounds`), with email addresses, links and long numbers
taken out first.
And when someone answers *Enjoying Onion Board?* (shown once ever, after a few days of heavy
use: enjoy.py), their thumb (`feedback/positive`, `feedback/negative`) and what they
typed under it as dashed words (`feedback/positive/more-meme-sounds`, other_tag), plus
`feedback/shown` and `feedback/dismissed` to see how many answer, with a one-off random
session like the improve picks.
And with the daily one, only for a streamer who ticked the Twitch card's "Let the Onion
Board developer see this channel's name" (off until then) and only while connected, that
channel's Twitch login (`twitch-channel/<login>`).
Nothing else: no name, sounds, settings, devices, games or IP address in the message
(GoatCounter sees the connection's address like any site does, and isn't sent it to
keep or look up).

On unless switched off: the installer's "Count me in" box, or Settings > Privacy &
security > Usage count (soundboard.online.net, so it also obeys Offline mode, a proxy and
Tor). Copies from before it existed start with it off: they were installed as an app
that sent nothing. A copy running from source never sends anything, and neither does
one on a PC with ONIONBOARD_NO_STATS set (the developer's own PCs and test VMs:
GoatCounter's "Ignore IPs" can't catch these sends, as they carry no IP)."""
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
from soundboard.core import achievements, enjoy
from soundboard.core.usagereports import (  # noqa: F401  (usage.X keeps working)
    ALL_HELD_MARK, BUSY, GC_SWEEP_MARK, IN_DIALOG_MARK, mark_running, mark_stopped,
    MAX_PROBLEMS, MEM_HIGH, PAGING_PER_S, problems, RUNNING, startup_failed, VERSION_RE,
    _ANY_FRAME, _blocked_in, _busy, _error_tag, _ERROR_TYPE, _error_type, _freeze_tag,
    _INNER, _lasted, _memory, _OUR_FILE, _OUR_FRAME, _ours, _report_event, _tb_where,
    _where)
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
    VOICE_TABS,
)

log = logging.getLogger(__name__)

FEATURE = "usage_stats"   # its switch in Settings > Privacy & security (soundboard.online.net)
ENDPOINT = "https://onionalien.goatcounter.com/api/v0/count"
# a key that can only add counts (GoatCounter's "Record pageviews" permission), not
# read or change anything; "" sends nothing
TOKEN = "1mdp7aoiksvjn2e3oitmjdaqd1u33msk6p74g7samuec2tufwr"  # gitleaks:allow (count-only)
EVERY_S = 24 * 3600
TIMEOUT_S = 15


def enabled() -> bool:
    """Could anything be sent at all: the installed app, with a key, not on a dev PC."""
    return (bool(TOKEN) and bool(getattr(sys, "frozen", False))
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


def _event(name: str, sid: str) -> dict:
    return {"path": name, "title": name, "event": True, "session": sid, "ref": user_tag(sid)}


def due(sent: float, now: float) -> bool:
    """Is the daily count due: a new day on this PC's clock since the last one, or a
    whole day gone by. By the calendar, not 24 hours: someone who used it at 8 pm
    and again at 6 pm the next day counts on both days (with a 24-hour rule the
    second day went with the third, and looked like a day off)."""
    if now - sent >= EVERY_S:
        return True
    return now > sent and time.localtime(now)[:3] != time.localtime(sent)[:3]


def hits(cfg, now: float, event: str = "", extra=()) -> list[dict]:
    """What a send would say: the daily "still here" for this version if one is due
    (with "first-start" the first time ever, and the tabs opened since the last one),
    or the one `event`. `extra` (problem events) go now, due or not."""
    sid = install_id(cfg)
    if event:
        return [_event(event, sid)]
    out = [_event(e, sid) for e in extra]
    if not due(cfg.stats_sent, now):
        return out
    out.insert(0, {"path": f"/app/{__version__}", "title": f"Onion Board {__version__}",
                   "session": sid, "ref": user_tag(sid)})
    if not cfg.stats_sent:
        heard = heard_tag(cfg.stats_heard)
        out.append(_event(f"first-start/heard-{heard}" if heard else "first-start", sid))
    out += [_event(f"tab/{t}", sid) for t in cfg.stats_tabs if t in TABS]
    out += [_event(e, sid) for e in about(cfg, now)]
    login = cfg.twitch_login
    if cfg.twitch_share and cfg.twitch_token and re.fullmatch(TWITCH_LOGIN_RE, login or ""):
        # only when the streamer ticked the Twitch card's box, and only while connected
        out.append(_event(f"twitch-channel/{login}", sid))
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
        enjoy.add(cfg, now - _open_mark)   # per day, for *Enjoying Onion Board?*
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
        _keep(cfg, [f"updated/{old}-to-{__version__}"])


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


def addon_tag(module_id: str) -> str:
    """An add-on's id as a count's word: one of ADDONS, else "other"."""
    return module_id if module_id in ADDONS else "other"


def used(key: str) -> None:
    """Feature `key` (one of FEATURES) was used, for the next daily count (and for
    Settings > Achievements' counting)."""
    achievements.event(key)
    if key in FEATURES and net.allowed(FEATURE):   # off: nothing piles up for later
        _used.add(key)


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
        del _pending[:]
        cfg.stats_used, cfg.stats_pending, cfg.stats_tabs = [], [], []
        cfg.stats_problems_seen = max(cfg.stats_problems_seen or 0, time.time())
        return
    have = cfg.stats_used if isinstance(cfg.stats_used, list) else []
    new = [k for k in FEATURES if k in _used and k not in have]
    _used.clear()
    if new:
        cfg.stats_used = [*have, *new]
    if _pending:   # note()d events: kept in cfg too, so a quit before the send keeps them
        taken = _pending[:]
        del _pending[:len(taken)]
        _keep(cfg, taken)


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
    for key, view in (("sounds", cfg.pad_view), ("apps", cfg.app_view),
                      ("voice", cfg.voice_view)):
        if view == "list":
            out.append(f"view-list-{key}")
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


def about(cfg, now: float) -> list[str]:
    """The daily count's picture of how it's used (see the docstring): buckets and
    names from fixed lists only."""
    out = [f"age/{age_bucket((now - (cfg.stats_started or now)) / DAY_S)}"]
    if cfg.route in ROUTES:
        out.append(f"route/{cfg.route}")
    out.append(f"sounds/{bucket(len(cfg.sounds))}")
    out.append(f"played/{bucket(total_plays(cfg) - cfg.stats_plays)}")
    out.append(f"open/{open_bucket(cfg.stats_open_s or 0)}")
    out.append(f"downloads/{download_bucket(cfg.stats_downloads or 0)}")
    out += lang_tags(cfg)
    out.append(f"theme/{theme_tag(cfg.theme)}")
    out.append(f"os/{os_tag()}")
    out.append(f"launches/{launch_bucket(cfg.stats_launches or 0)}")
    got = cfg.achievements.get("got") if isinstance(cfg.achievements, dict) else None
    got = got if isinstance(got, dict) else {}
    out.append(f"achievements/{ach_bucket(len(got))}")
    score = sum(achievements.points(a) for a in achievements.ALL if a.id in got)
    out.append(f"ach-score/{score_bucket(score)}")
    have = (set(cfg.stats_used if isinstance(cfg.stats_used, list) else [])
            | set(features_now(cfg)))
    out += [f"used/{k}" for k in FEATURES if k in have]
    return out


def lang_tags(cfg) -> list[str]:
    """The language the app is showing and where it came from: `lang/de/picked` (picked
    in Settings), `lang/en/default` (none picked, so English: the board doesn't follow
    Windows by itself yet) or `lang/de/windows` (once it does). And Windows' own display
    language as a catalog the app ships (`lang-windows/pt-BR`; `en` when none fits), to
    see which languages people would like. Language codes only, never the locale."""
    def code(c: str) -> str:
        return c if re.fullmatch(LANG_RE, c or "") else "other"
    if cfg.language:
        source = "picked"
    else:
        source = "windows" if i18n.FOLLOW_WINDOWS else "default"
    return [f"lang/{code(i18n.current())}/{source}",
            f"lang-windows/{code(i18n.resolve(i18n.windows_language()))}"]


def tab_opened(cfg, key: str) -> None:
    """Remember that tab `key` was opened, for the next daily count."""
    tabs = cfg.stats_tabs if isinstance(cfg.stats_tabs, list) else []
    if key in TABS and key not in tabs and not _off(cfg):
        cfg.stats_tabs = [*tabs, key]


_pending: list[str] = []   # an unclean exit found at start, for the next send
MAX_PENDING = 20           # one-off events kept in cfg.stats_pending while unsent


def note(event: str) -> None:
    """Send `event` with the next count (any thread: remember() moves it into cfg)."""
    if event and net.allowed(FEATURE):   # off: nothing piles up for later
        _pending.append(event)


def _keep(cfg, events) -> None:
    """Keep one-off events in cfg.stats_pending until a send takes them."""
    have = [e for e in (cfg.stats_pending if isinstance(cfg.stats_pending, list) else [])
            if isinstance(e, str)]
    cfg.stats_pending = [*have, *(e for e in events if e)][:MAX_PENDING]


_warned: set[str] = set()   # reportable problems handled this run, for warned()


def warned(e: BaseException) -> None:
    """The app caught an error it couldn't fix and showed the user itself, as a warning
    instead of a crash (errors.warn / errors.html): count that it happened, once per
    distinct (type, place) per run, as `warned/<version>/<type>@<soundboard/…py:line>`
    -- the type and the deepest line of our own code it came from (like error/ events),
    never its message (a message can hold a path, a device or a user name). A string
    problem (no traceback) isn't counted."""
    if not isinstance(e, BaseException):
        return
    warned_at(type(e).__name__, _tb_where(e.__traceback__))


def warned_at(kind: str, where: str = "") -> None:
    """warned() for an error caught in another process (the mic effect's admin step,
    read back from its log): its type `kind` (`struct.error`) and `where`, the deepest
    of our own lines (`soundboard/mic/micadmin.py:445`), or "" if none. Anything else
    isn't counted."""
    if not re.fullmatch(r"[A-Za-z_][\w.]{0,60}", kind or ""):
        return
    if where and not re.fullmatch(_OUR_FILE.pattern + r":\d{1,6}", where):
        where = ""
    key = f"{kind}@{where}" if where else kind
    if key in _warned:
        return
    _warned.add(key)
    note(f"warned/{__version__}/{key}")


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
    where it did: `failed/<version>/<what>/<detail>/…`, each part a word or number we
    made or an error's type and place (error_detail, timeout_kind). Never its message.
    Once per distinct one per run; a part that isn't one of those is left out."""
    parts = [d for d in detail if d and _DETAIL.fullmatch(d)][:3]
    if what not in FAILED or not parts:
        return
    key = "/".join((what, *parts))
    if key in _failed:
        return
    _failed.add(key)
    note(f"failed/{__version__}/{key}")


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


def uninstall_event() -> str:
    return f"uninstall/{__version__}"


OPT_OUT_WHERE = ("installer", "settings")
OPT_OUT_TIMEOUT_S = 5   # the installer waits on it: never long


def opt_out(where: str) -> bool:
    """Count me in switched from on to off (`where`: the installer's box or Settings):
    one last "opt-out/<where>" so we know how many people aren't counted, then nothing
    ever again. No random ID, no tag, no session: it can't be tied to anything they
    sent before. Only while the count is still allowed (call it before switching it
    off), and never in Tor mode (SECURITY.md). Waits for the answer: call it off the
    UI thread."""
    if (where not in OPT_OUT_WHERE or not enabled() or not net.allowed(FEATURE)
            or net.mode() == net.TOR):
        return False
    name = f"opt-out/{where}"
    netlog.cause(FEATURE, f"Anonymous usage count ({name}, the last one)")
    return send([{"path": name, "title": name, "event": True}],
                timeout=OPT_OUT_TIMEOUT_S, no_sessions=True)


def update_event(to: str) -> str:
    """The event for *Update now* from this version to `to`."""
    return f"update-now/{__version__}-to-{to}"


MAX_HITS = 100   # GoatCounter's most per request: a longer list goes in parts


def send(payload: list[dict], timeout: float = TIMEOUT_S, no_sessions: bool = False) -> bool:
    """POST them to the counter, MAX_HITS at a time. True if it took them all (it stops
    at the first part it didn't take). Call off the UI thread."""
    for i in range(0, max(len(payload), 1), MAX_HITS):
        if not _send_part(payload[i:i + MAX_HITS], timeout, no_sessions):
            return False
    return True


def _send_part(payload: list[dict], timeout: float, no_sessions: bool) -> bool:
    body = json.dumps({"hits": payload, "no_sessions": True} if no_sessions
                      else {"hits": payload}).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
        "Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json",
        "User-Agent": "OnionBoard"})
    try:
        with net.urlopen(req, timeout=timeout, feature=FEATURE) as r:
            return 200 <= r.status < 300
    except Exception as e:  # noqa: BLE001 - offline, switched off meanwhile, counter down
        log.info("usage count not sent: %s", e)
        return False


MEMORY_FULL = 90   # % of the PC's memory in use from which the count waits


def _memory_full() -> bool:
    """The PC is short of memory: Windows is swapping to disk, and even starting the
    count's thread could stall the window for many seconds. A PC that stays this full
    all day goes uncounted: fine, the count never slows anyone down."""
    from soundboard.core import hangwatch
    load = hangwatch.memory_load()
    return load is not None and load >= MEMORY_FULL


def maybe_send(cfg, on_sent=None, event: str = "", app_dir: Path | None = None) -> None:
    """The daily count if it's due (or `event` now), on a thread, when it's allowed.
    Problems since the last send go too, due or not: note()d ones, and with `app_dir`
    the reports saved there.

    The thread only sends what was gathered here; cfg belongs to the UI thread, which
    keeps adding to the same stats_* fields (tab_opened, downloaded, remember). Once a
    count (not an `event`) went, `on_sent(apply)` is called on that thread: the caller
    runs apply() on the thread that owns cfg (the main window queues it to the UI
    thread), and apply clears exactly what was sent, keeping anything added meanwhile.
    Without on_sent, apply runs right there (a caller with no UI thread)."""
    if not enabled() or _off(cfg):
        return
    if not event and _memory_full():   # a later check sends it; an event goes anyway
        return
    now = time.time()
    settle(cfg, now)
    remember(cfg)
    if not cfg.stats_problems_seen:   # first run with this: older reports aren't news
        cfg.stats_problems_seen = now
    pending = [] if event else list(cfg.stats_pending)   # remember() made it a clean list
    taken, since = pending[:], cfg.stats_problems_seen
    open_tick(cfg)
    base = hits(cfg, now, event)   # the daily count or the event; problems join on the thread
    if not base and not pending and app_dir is None:
        return
    daily = bool(base) and not event and not base[0].get("event")
    paths = [*(h["path"] for h in base), *pending]   # (the reports are neither)
    tabs = [p[4:] for p in paths if p.startswith("tab/")]
    feats = [p[5:] for p in paths if p.startswith("used/")]
    plays = total_plays(cfg)
    opened = cfg.stats_open_s or 0
    launches = cfg.stats_launches or 0
    downloads = cfg.stats_downloads or 0
    netlog.cause(FEATURE, "Anonymous usage count" + (f" ({event})" if event
                                                     else " (once a day)" if daily
                                                     else " (problems)"))

    def apply():   # on the thread that owns cfg: only what this count took
        if daily:
            cfg.stats_sent = now
            cfg.stats_tabs = [t for t in cfg.stats_tabs if t not in tabs]
            cfg.stats_used = [k for k in cfg.stats_used if k not in feats]
            cfg.stats_plays = plays
            cfg.stats_open_s = max(0.0, (cfg.stats_open_s or 0) - opened)   # since then
            cfg.stats_launches = max(0, (cfg.stats_launches or 0) - launches)
            cfg.stats_downloads = max(0, (cfg.stats_downloads or 0) - downloads)
        cfg.stats_pending = _without(cfg.stats_pending, taken)
        cfg.stats_problems_seen = max(cfg.stats_problems_seen, newest[0])

    newest = [0.0]

    def run():   # the saved reports and the network only: never touches cfg
        # the reports folder is read here, not on the UI thread that called: a send
        # follows each saved report, so it comes when the PC is already struggling
        extra, newest[0] = ([], 0.0) if event else _with_reports(pending, app_dir, since)
        payload = [*base[:1], *(_event(e, sid) for e in extra), *base[1:]]   # as hits()
        if payload and send(payload) and not event:
            (on_sent or (lambda f: f()))(apply)
    sid = install_id(cfg)
    threading.Thread(target=run, daemon=True, name="usage-count").start()


def _waiting(cfg, now: float, app_dir: Path | None) -> tuple[list[str], list[str], float]:
    """The one-off and problem events waiting for a send: (the events, the ones taken
    from cfg.stats_pending, the newest report's time). Call after remember()."""
    if not cfg.stats_problems_seen:   # first run with this: older reports aren't news
        cfg.stats_problems_seen = now
    taken = list(cfg.stats_pending)   # remember() just made it a clean list
    extra, newest = _with_reports(taken, app_dir, cfg.stats_problems_seen)
    return extra, taken, newest


def _with_reports(extra: list[str], app_dir: Path | None,
                  since: float) -> tuple[list[str], float]:
    """`extra` and the events for the reports saved in app_dir after `since`, at most
    MAX_PROBLEMS (one `problems-dropped/` says roughly how many more), and the newest
    report's time. Reads the disk: maybe_send calls it on its thread."""
    extra, skipped, newest = list(extra), [0], 0.0
    if app_dir is not None:
        found, newest = problems(app_dir, since, skipped)
        extra += found
    dropped = skipped[-1] + max(0, len(extra) - MAX_PROBLEMS)
    extra = extra[:MAX_PROBLEMS]
    if dropped:   # a bug in a loop: one count saying roughly how many more
        extra.append(f"problems-dropped/{bucket(dropped)}")
    return extra, newest


def _without(have, sent) -> list[str]:
    """`have` with each of `sent` taken out once: any added meanwhile stay."""
    left = [e for e in (have if isinstance(have, list) else []) if isinstance(e, str)]
    for e in sent:
        if e in left:
            left.remove(e)
    return left


QUIT_WAIT_S = 2.0   # the longest a quit waits for at_quit's send (it runs while the rest closes)


def at_quit(cfg, app_dir: Path | None = None):
    """At a real quit: what's waiting for the next count, sent now, so the last day
    someone used the app isn't lost when they never start it again (or closed it
    within a minute of starting). Only the events the next count would carry anyway:
    the features used (`used/`, not features_now, which the daily count adds), the tabs
    opened (`tab/`) and the one-off and problem events waiting. Never the daily count
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
    have = cfg.stats_used if isinstance(cfg.stats_used, list) else []
    feats = [k for k in FEATURES if k in have]
    tabs = [t for t in TABS if t in (cfg.stats_tabs if isinstance(cfg.stats_tabs, list)
                                     else [])]
    extra, taken, newest = _waiting(cfg, now, app_dir)
    events = [*(f"used/{k}" for k in feats), *(f"tab/{t}" for t in tabs), *extra]
    if not events:
        return None
    sid = install_id(cfg)
    payload = [_event(e, sid) for e in events]
    netlog.cause(FEATURE, "Anonymous usage count (at quit)")
    done: list[bool] = []
    end = time.monotonic() + QUIT_WAIT_S
    t = threading.Thread(target=lambda: done.append(send(payload, timeout=QUIT_WAIT_S)),
                         daemon=True, name="usage-count")
    t.start()

    def finish() -> bool:
        t.join(max(0.0, end - time.monotonic()))
        if not (done and done[0]):
            return False
        cfg.stats_used = [k for k in cfg.stats_used if k not in feats]
        cfg.stats_tabs = [k for k in cfg.stats_tabs if k not in tabs]
        cfg.stats_pending = _without(cfg.stats_pending, taken)
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
    maybe_send(cfg, on_sent, event=f"step/{name}")


def improve(cfg, picks, other: str = "", bugs: str = "") -> bool:
    """The feedback box's "What would you improve?" picks, sent now as `improve/<name>`
    (names from IMPROVE only), their follow-up ticks (`sounds/memes` in `picks`) as
    `improve/sounds/memes` (names from IMPROVE_MORE only), what was typed under Other
    as `improve/other/<words>` and under Fewer bugs as `improve/bugs/said/<words>`
    (other_tag, BUGS_MAX for bugs). Anonymous: they go with a one-off random session
    made for this send, never this PC's stats_id, so they can't be linked to the daily
    count or to each other. False when nothing can be sent (usage count off, offline, running from
    source)."""
    events = []
    for k in IMPROVE:
        if k not in picks:
            continue
        tag = other_tag(other) if k == "other" else ""
        events.append(f"improve/{k}/{tag}" if tag else f"improve/{k}")
        events += [f"improve/{k}/{sub}" for sub in IMPROVE_MORE.get(k, ())
                   if f"{k}/{sub}" in picks]
        said = other_tag(bugs, BUGS_MAX) if k == "bugs" else ""
        if said:
            events.append(f"improve/bugs/said/{said}")
    if not events or not enabled() or not net.allowed(FEATURE):
        return False
    sid = uuid.uuid4().hex   # not install_id(cfg): the box says it isn't linked to this PC
    netlog.cause(FEATURE, "Anonymous usage count (feedback picks)")
    threading.Thread(target=send, args=([_event(e, sid) for e in events],), daemon=True,
                     name="usage-count").start()
    return True


SURVEY = ("shown", "dismissed", "positive", "negative")   # feedback/<one of these>


def survey(sid: str, what: str, said: str = "") -> bool:
    """*Enjoying Onion Board?* (ui/window/enjoycontrol.py): `feedback/<what>` (SURVEY names
    only), with what they typed as `feedback/<what>/<words>` (other_tag). `sid` is a
    random session the bar made, never this PC's stats_id. False when nothing can be
    sent (usage count off, offline, running from source)."""
    if what not in SURVEY or not enabled() or not net.allowed(FEATURE):
        return False
    tag = other_tag(said) if what in ("positive", "negative") else ""
    event = f"feedback/{what}/{tag}" if tag else f"feedback/{what}"
    netlog.cause(FEATURE, "Anonymous usage count (feedback)")
    threading.Thread(target=send, args=([_event(event, sid)],), daemon=True,
                     name="usage-count").start()
    return True


def send_now(cfg, event: str) -> bool:
    """Send one `event` and wait for it (the uninstaller's `--uninstall-count`)."""
    if not enabled() or not net.allowed(FEATURE):
        return False
    netlog.cause(FEATURE, f"Anonymous usage count ({event})")
    return send(hits(cfg, time.time(), event))
