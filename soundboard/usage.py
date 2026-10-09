"""The anonymous usage count: how many people use Onion Board, and which versions.

Once a day the installed app sends one "still here" to the project's GoatCounter
(a privacy-friendly counter): the version number and a random ID made on this PC, so
the same person isn't counted twice. Also a one-off "first start" (with where they
heard about the app, if they picked it on the installer's last page), and "updated" when
*Update now* installs a new version. With the daily one: which tabs were opened since the
last one (their names only). Soon after a start: how many problems there were since the
last send, as counts, never the report itself: a crash report or a freeze saved
(`crash/<version>`, `error/<version>`, `freeze/<version>`, with the error's type and
the file and line of this app's own code it happened in, e.g. `error/1.9.8/KeyError@
soundboard/engine.py:1090`: never its message or anything else from the report), or
the last run ending without the app closing itself (`unclean-exit/<version>/<why>`:
a hard crash, ended in Task Manager, a power cut; exitwatch.py works out which, on
this PC). And `uninstall/<version>` when the uninstaller removes it.
With the daily one, a rough picture of how it's used, each as a bucket or a name from a
fixed list: how long ago it was installed (`age/days-2-7`), where sounds go
(`route/mic`), how many sounds the board has and how many were played since the last
one (`sounds/11-50`, `played/1-10`), the app's language (`lang/de`), and which features
were used since then (`used/voice-changer`, `used/more-tabs-added-radio`: the names
in FEATURES only). And once each,
the first steps of a new install (`step/added-sound`, `step/played-sound`,
`step/sent-to-others`), to see where new people get stuck; never for a copy that was
counted before these existed. Also once each, switching on a tab a new user starts
without (`step/added-radio-tab`, `-apps-`, `-triggers-`): sent when it happens, since
a tab opened after the first daily count waits a day, and most people trying the app
never send that one.
And when someone answers *Send feedback*'s "What would you improve?", their picks
(`improve/sounds`: names from IMPROVE only), and what they typed under Other as dashed
words (`improve/other/more-anime-sounds`), with email addresses, links and long numbers
taken out first.
Nothing else: no name, sounds, settings, devices, games or IP address in the message
(GoatCounter sees the connection's address like any site does, and isn't sent it to
keep or look up).

On unless switched off: the installer's "Count me in" box, or Settings > Privacy &
security > Usage count (soundboard.net, so it also obeys Offline mode, a proxy and
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
import urllib.request
import uuid
from pathlib import Path

from soundboard import __version__, net, netlog

log = logging.getLogger(__name__)

FEATURE = "usage_stats"   # its switch in Settings > Privacy & security (soundboard.net)
ENDPOINT = "https://onionalien.goatcounter.com/api/v0/count"
# a key that can only add counts (GoatCounter's "Record pageviews" permission), not
# read or change anything; "" sends nothing
TOKEN = "1mdp7aoiksvjn2e3oitmjdaqd1u33msk6p74g7samuec2tufwr"  # gitleaks:allow (count-only)
EVERY_S = 24 * 3600
# the installer's "Where did you hear about Onion Board?" picks; Other's typed answer
# goes through heard_tag() too, and anything else is sent as "other-<words>" or not at all
HEARD = ("youtube", "reddit", "github", "google", "friend")
HEARD_ALIASES = {"yt": "youtube", "you tube": "youtube", "youtube.com": "youtube",
                 "reddit.com": "reddit", "github.com": "github", "a friend": "friend",
                 "friends": "friend", "google.com": "google", "x": "twitter",
                 "twitter.com": "twitter", "tiktok.com": "tiktok", "tik tok": "tiktok"}
HEARD_MAX = 24   # characters of a typed answer, after tidying
TIMEOUT_S = 15
# the tabs whose use is counted (mainwindow.TABS); anything else is never sent
TABS = ("sounds", "radio", "apps", "triggers", "voice", "setup")
RUNNING = "running.txt"     # in the app folder while the app runs (mark_running)
MAX_PROBLEMS = 10           # problem events per send: a bug in a loop isn't 1000 hits
VERSION_RE = r"[0-9][0-9A-Za-z.\-]{0,20}"
# what else is counted, only ever these names (see the docstring)
FEATURES = ("add-files", "youtube", "record", "clip", "clip-editor", "import-board",
            "voice-changer", "text-to-speech", "hotkeys", "phone-remote", "also-send",
            # + More tabs: opened it, added a tab from it, or closed it adding none; and
            # a tab hidden from its right-click menu
            "more-tabs-opened", "more-tabs-closed",
            *(f"more-tabs-added-{k}" for k in ("radio", "apps", "triggers", "voice")),
            *(f"tab-hidden-{k}" for k in ("radio", "apps", "triggers", "voice")))
STEPS = ("added-sound", "played-sound", "sent-to-others",
         # a tab a new user starts without (+ More tabs, Settings > Tabs)
         "added-radio-tab", "added-apps-tab", "added-triggers-tab")
ROUTES = ("cable", "device", "off", "mic")   # library.ROUTES
# the feedback box's "What would you improve?" picks (ui/feedbackdialog.py)
IMPROVE = ("sounds", "setup", "voice-chat", "voice-changer", "speed", "looks", "bugs",
           "other")
OTHER_MAX = 100   # characters of what was typed under Other, as dashed words
LANG_RE = r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,4})?"
DAY_S = 24 * 3600


def enabled() -> bool:
    """Could anything be sent at all: the installed app, with a key, not on a dev PC."""
    return (bool(TOKEN) and bool(getattr(sys, "frozen", False))
            and not os.environ.get("ONIONBOARD_NO_STATS"))


def install_id(cfg) -> str:
    """This PC's random ID (made once, kept in config.json)."""
    if not cfg.stats_id:
        cfg.stats_id = uuid.uuid4().hex
    return cfg.stats_id


def _wordlike(w: str) -> bool:
    """A word, a short name ("tv") or a number: not keyboard mashing ("asdfgh")."""
    return w.isdigit() or ((len(w) <= 3 or bool(re.search(r"[aeiouy]", w)))
                           and not re.search(r"[^aeiouy\d]{5}", w))


def heard_tag(text: str) -> str:
    """The installer's answer as a short tag for the first-start event: one of HEARD,
    "other-<a-few-words>" for a typed answer that reads like a name (a site, an app,
    "discord server"), or "" for none. Typed text that doesn't look like that is
    dropped, not sent: an email address, a link with a path, a number (a phone),
    symbols, keyboard mashing or more than three words."""
    t = " ".join(str(text or "").lower().split())
    t = HEARD_ALIASES.get(t, t)
    if t in HEARD:
        return t
    if (not t or len(t) > HEARD_MAX or "@" in t or "/" in t
            or not re.fullmatch(r"[a-z0-9 .\-]+", t) or re.search(r"\d{3}", t)):
        return ""
    words = re.findall(r"[a-z0-9]+", t.replace(".com", ""))
    if not 1 <= len(words) <= 3 or not all(_wordlike(w) for w in words):
        return ""
    for w in words:   # "a youtube video", "my friend", "google search"
        w = HEARD_ALIASES.get(w, w)
        if w in HEARD:
            return w
    return "other-" + "-".join(words)


def _event(name: str, sid: str) -> dict:
    return {"path": name, "title": name, "event": True, "session": sid}


def hits(cfg, now: float, event: str = "", extra=()) -> list[dict]:
    """What a send would say: the daily "still here" for this version if one is due
    (with "first-start" the first time ever, and the tabs opened since the last one),
    or the one `event`. `extra` (problem events) go now, due or not."""
    sid = install_id(cfg)
    if event:
        return [_event(event, sid)]
    out = [_event(e, sid) for e in extra]
    if now - cfg.stats_sent < EVERY_S:
        return out
    out.insert(0, {"path": f"/app/{__version__}", "title": f"Onion Board {__version__}",
                   "session": sid})
    if not cfg.stats_sent:
        heard = heard_tag(cfg.stats_heard)
        out.append(_event(f"first-start/heard-{heard}" if heard else "first-start", sid))
    out += [_event(f"tab/{t}", sid) for t in cfg.stats_tabs if t in TABS]
    out += [_event(e, sid) for e in about(cfg, now)]
    return out


def bucket(n: int) -> str:
    """A count as a rough bucket: 0, 1-10, 11-50, 51-plus."""
    return "0" if n <= 0 else "1-10" if n <= 10 else "11-50" if n <= 50 else "51-plus"


def age_bucket(days: float) -> str:
    """How long ago it was installed, roughly."""
    return ("day-1" if days < 1 else "days-2-7" if days < 7 else "days-8-30" if days < 30
            else "days-31-plus")


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
            from soundboard.library import APP_DIR
            born = min(born, APP_DIR.stat().st_ctime)   # created, on Windows
        except (OSError, ImportError):
            pass
        cfg.stats_started = born
        cfg.stats_steps = list(STEPS)
        cfg.stats_plays = total_plays(cfg)
    else:
        cfg.stats_started = now


_used: set[str] = set()   # features used this run, kept in cfg by remember()


def used(key: str) -> None:
    """Feature `key` (one of FEATURES) was used, for the next daily count."""
    if key in FEATURES:
        _used.add(key)


def remember(cfg) -> None:
    """Keep this run's used() features in cfg (so they survive a quit before the
    next daily count)."""
    have = cfg.stats_used if isinstance(cfg.stats_used, list) else []
    new = [k for k in FEATURES if k in _used and k not in have]
    _used.clear()
    if new:
        cfg.stats_used = [*have, *new]


def features_now(cfg) -> list[str]:
    """Features that are set up, counted as used every day they are."""
    out = []
    if any(getattr(m, "hotkey", "") for m in cfg.sounds) or cfg.category_hotkeys:
        out.append("hotkeys")
    if cfg.remote_addons or cfg.api_enabled:
        out.append("phone-remote")
    if cfg.also_send:
        out.append("also-send")
    return out


def about(cfg, now: float) -> list[str]:
    """The daily count's picture of how it's used (see the docstring): buckets and
    names from fixed lists only."""
    out = [f"age/{age_bucket((now - (cfg.stats_started or now)) / DAY_S)}"]
    if cfg.route in ROUTES:
        out.append(f"route/{cfg.route}")
    out.append(f"sounds/{bucket(len(cfg.sounds))}")
    out.append(f"played/{bucket(total_plays(cfg) - cfg.stats_plays)}")
    lang = cfg.language if re.fullmatch(LANG_RE, cfg.language or "") else "auto"
    out.append(f"lang/{lang}")
    have = (set(cfg.stats_used if isinstance(cfg.stats_used, list) else [])
            | set(features_now(cfg)))
    out += [f"used/{k}" for k in FEATURES if k in have]
    return out


def tab_opened(cfg, key: str) -> None:
    """Remember that tab `key` was opened, for the next daily count."""
    tabs = cfg.stats_tabs if isinstance(cfg.stats_tabs, list) else []
    if key in TABS and key not in tabs:
        cfg.stats_tabs = [*tabs, key]


# a stack line in a report: `File "...\soundboard\engine.py", line 1090, in ...`; only
# our own files count, named from the package folder down (never the folder above it)
_OUR_FRAME = re.compile(r'^\s*File "(?:[^"]*[\\/])?(soundboard(?:[\\/][a-z0-9_]+)?'
                        r'[\\/][a-z0-9_]+\.py)", line (\d+)', re.M)
_ANY_FRAME = re.compile(r'^\s*File ".*", line \d+', re.M)
_ERROR_TYPE = re.compile(r"([A-Za-z_][\w.]*)(?::|$)")


def _where(stack: str) -> str:
    """`soundboard/engine.py:1090`: the deepest of our own lines in a report's stack
    (the same file and line anyone can look up in the public source), or "".
    threadnames.py only wraps Thread.start / run, so its lines name their caller."""
    frames = [(file.replace(chr(92), "/"), line)
              for file, line in _OUR_FRAME.findall(stack)]
    frames = [f for f in frames if f[0] != "soundboard/threadnames.py"] or frames
    if not frames:
        return ""
    file, line = frames[-1]
    return f"{file}:{line}"


def _error_type(stack: str) -> str:
    """`KeyError` from the traceback's last line: the type only, never its message
    (a message can hold a path, a device or a user name)."""
    frames = list(_ANY_FRAME.finditer(stack))
    if not frames:
        return ""
    for line in stack[frames[-1].end():].splitlines()[1:]:
        if line.strip() and not line[:1].isspace():   # past the frame's code lines
            m = _ERROR_TYPE.match(line)
            name = m.group(1).rsplit(".", 1)[-1] if m else ""
            return name if len(name) <= 40 else ""
    return ""


def _report_event(path: Path) -> str:
    """`crash/1.9.6`, `error/1.9.6` or `freeze/1.9.6` for a saved report (applog.py),
    then where it happened when the stack shows it: `error/1.9.6/KeyError@
    soundboard/engine.py:1090`, `freeze/1.9.6@soundboard/directmic.py:184`."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read(64_000)
    except OSError:
        return ""
    head = text[:600]
    if head.startswith("Onion Board ended without closing"):   # exitwatch.py: counted
        return ""                                          # as unclean-exit/ already
    m = re.search(rf"^Version:\s*({VERSION_RE})\s*$", head, re.M)
    ver = m.group(1) if m else __version__
    # the stack only: never the log lines saved below it
    stack = re.split(r"^Last \d+ log lines\s*$", text, maxsplit=1, flags=re.M)[0]
    stack = stack.split("\n\n", 1)[-1]
    # a freeze: the window's own stack, never the other threads hangwatch.py adds
    stack = re.split(r"^Other threads\s*$", stack, maxsplit=1, flags=re.M)[0]
    where = _where(stack)
    if "froze for" in head.split("\n", 1)[0]:
        return f"freeze/{ver}" + (f"@{where}" if where else "")
    kind = "crash" if re.search(r"^Fatal:", head, re.M) else "error"
    etype = _error_type(stack)
    tag = "@".join(p for p in (etype, where) if p)
    return f"{kind}/{ver}" + (f"/{tag}" if tag else "")


def problems(app_dir: Path, since: float) -> tuple[list[str], float]:
    """Events for the crash / freeze reports saved in app_dir after `since` (a file
    time), and the newest such time. Only the kind and version are read out."""
    from soundboard.applog import REPORTS_DIR
    out, newest = [], since
    try:
        files = sorted((f.stat().st_mtime, f.name, f)
                       for f in (app_dir / REPORTS_DIR).glob("crash-*.txt"))
    except OSError:
        return [], since
    for mtime, _name, f in files:
        if mtime <= since:
            continue
        newest = max(newest, mtime)
        ev = _report_event(f)
        if ev and len(out) < MAX_PROBLEMS:
            out.append(ev)
    return out, newest


def mark_running(app_dir: Path) -> str:
    """At start: note that the app is running. Returns `unclean-exit/<version>` when the
    last run never got to mark_stopped (it crashed hard, was ended in Task Manager, or
    the PC lost power), else ""."""
    path = app_dir / RUNNING
    event = ""
    try:
        old = path.read_text(encoding="utf-8").strip()
        if re.fullmatch(VERSION_RE, old):
            event = f"unclean-exit/{old}"
    except OSError:
        pass
    try:
        path.write_text(__version__, encoding="utf-8")
    except OSError:
        pass
    return event


def mark_stopped(app_dir: Path) -> None:
    """At a real quit (MainWindow.shutdown, also when Windows ends the session)."""
    try:
        (app_dir / RUNNING).unlink(missing_ok=True)
    except OSError:
        pass


_pending: list[str] = []   # an unclean exit found at start, for the next send


def note(event: str) -> None:
    """Send `event` with the next count."""
    if event:
        _pending.append(event)


def uninstall_event() -> str:
    return f"uninstall/{__version__}"


def update_event(to: str) -> str:
    """The event for *Update now* from this version to `to`."""
    return f"update-now/{__version__}-to-{to}"


def send(payload: list[dict]) -> bool:
    """POST them to the counter. True if it took them. Call off the UI thread."""
    body = json.dumps({"hits": payload}).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
        "Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json",
        "User-Agent": "OnionBoard"})
    try:
        with net.urlopen(req, timeout=TIMEOUT_S, feature=FEATURE) as r:
            return 200 <= r.status < 300
    except Exception as e:  # noqa: BLE001 - offline, switched off meanwhile, counter down
        log.info("usage count not sent: %s", e)
        return False


def maybe_send(cfg, saved=None, event: str = "", app_dir: Path | None = None) -> None:
    """The daily count if it's due (or `event` now), on a thread, when it's allowed.
    Problems since the last send go too, due or not: note()d ones, and with `app_dir`
    the reports saved there. `saved()` is called on that thread after cfg changed."""
    if not enabled() or not net.allowed(FEATURE):
        return
    now = time.time()
    settle(cfg, now)
    remember(cfg)
    extra, taken, newest = [], 0, 0.0
    if not cfg.stats_problems_seen:   # first run with this: older reports aren't news
        cfg.stats_problems_seen = now
    if not event:
        taken = len(_pending)
        extra = _pending[:taken]
        if app_dir is not None:
            found, newest = problems(app_dir, cfg.stats_problems_seen)
            extra += found
        extra = extra[:MAX_PROBLEMS]
    payload = hits(cfg, now, event, extra)
    if not payload:
        return
    daily = not event and not payload[0].get("event")
    tabs = [h["path"][4:] for h in payload if h["path"].startswith("tab/")]
    feats = [h["path"][5:] for h in payload if h["path"].startswith("used/")]
    plays = total_plays(cfg)
    netlog.cause(FEATURE, "Anonymous usage count" + (f" ({event})" if event
                                                     else " (once a day)" if daily
                                                     else " (problems)"))

    def run():
        if not send(payload) or event:
            return
        if daily:
            cfg.stats_sent = now
            cfg.stats_tabs = [t for t in cfg.stats_tabs if t not in tabs]
            cfg.stats_used = [k for k in cfg.stats_used if k not in feats]
            cfg.stats_plays = plays
        del _pending[:taken]
        cfg.stats_problems_seen = max(cfg.stats_problems_seen, newest)
        if saved is not None:
            saved()
    threading.Thread(target=run, daemon=True, name="usage-count").start()


def step(cfg, name: str, saved=None) -> None:
    """A new install's first time doing `name` (one of STEPS): sent right away, once.
    A copy counted before these existed never sends them (settle)."""
    if name not in STEPS or not enabled() or not net.allowed(FEATURE):
        return
    settle(cfg, time.time())
    if name in cfg.stats_steps:
        return
    cfg.stats_steps = [*cfg.stats_steps, name]
    maybe_send(cfg, saved, event=f"step/{name}")


def other_tag(text: str) -> str:
    """What was typed under Other as dashed words ("more-anime-sounds"), any language.
    Anything that could say who someone is is dropped first: an email address, a link,
    a long number (a phone), an @name. At most OTHER_MAX characters, cut at a word."""
    words = []
    for w in str(text or "").lower().split():
        if ("@" in w or "/" in w or "www." in w or re.search(r"\.[a-z]{2,4}$", w)
                or re.search(r"\d{4,}", w)):
            continue
        words += [p for p in re.split(r"[\W_]+", w) if p]
    out = ""
    for w in words:
        if len(out) + len(w) + 1 > OTHER_MAX:
            break
        out = f"{out}-{w}" if out else w
    return out


def improve(cfg, picks, other: str = "") -> bool:
    """The feedback box's "What would you improve?" picks, sent now as `improve/<name>`
    (names from IMPROVE only), and what was typed under Other as `improve/other/<words>`
    (other_tag). False when nothing can be sent (usage count off, offline, running from
    source)."""
    events = [f"improve/{k}" for k in IMPROVE if k in picks]
    tag = other_tag(other) if "other" in picks else ""
    if tag:
        events = [e if e != "improve/other" else f"improve/other/{tag}" for e in events]
    if not events or not enabled() or not net.allowed(FEATURE):
        return False
    sid = install_id(cfg)
    netlog.cause(FEATURE, "Anonymous usage count (feedback picks)")
    threading.Thread(target=send, args=([_event(e, sid) for e in events],), daemon=True,
                     name="usage-count").start()
    return True


def send_now(cfg, event: str) -> bool:
    """Send one `event` and wait for it (the uninstaller's `--uninstall-count`)."""
    if not enabled() or not net.allowed(FEATURE):
        return False
    netlog.cause(FEATURE, f"Anonymous usage count ({event})")
    return send(hits(cfg, time.time(), event))
