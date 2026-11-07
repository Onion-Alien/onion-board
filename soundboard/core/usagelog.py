"""The app's own warnings and errors as usage count events (usage.py): `log.warning` and
`log.error`, and `run.start` / `run.end` so a run's events can be read together.

A log line's text never leaves this PC: not its message, not the message's arguments
(they can hold paths, sound names, device names). An event says which logger, and for our
own code the file, line and function, plus the error's type and our own frames when it
carried an exception. Anything else logged (Qt, add-ons, libraries) is its logger's name.

The same place again only adds to a count, so a loop is one line, and a run counts at most
MAX_PLACES different ones. Only a `log.error` makes a send of its own; the rest wait for
one that's going anyway (the daily count, a close), since a send per start for a common
warning would be a lot of sends. Only an installed copy with the count on sends any of it."""
from __future__ import annotations

import logging
import re
import time

from soundboard.core.usageevents import LOG_ERROR, LOG_WARNING, RUN_END, RUN_START, event, place
from soundboard.core.usagereports import _OUR_FILE, _tb_frames
from soundboard.core.usagetags import open_bucket

MAX_PLACES = 20   # different places per run: fewer than a send's MAX_PROBLEMS, so reports fit
OUR_LOGGERS = ("crash",)   # ours besides the soundboard.* ones; `qt` says only that Qt spoke
_LOGGER = re.compile(r"[A-Za-z_][\w.\-]{0,60}", re.ASCII)
_WORD = re.compile(r"[A-Za-z_<][\w<>.]{0,60}", re.ASCII)


def _ours(record: logging.LogRecord) -> bool:
    return record.name.startswith("soundboard.") or record.name in OUR_LOGGERS


def _word(text: str) -> str:
    return text if _WORD.fullmatch(text or "") else ""


def _last_line(tb) -> tuple[str, int]:
    """Where a traceback ends, as applog._signature says it, without reading any file."""
    while tb.tb_next is not None:
        tb = tb.tb_next
    return tb.tb_frame.f_code.co_filename, tb.tb_lineno


def _read(record: logging.LogRecord) -> tuple[dict, tuple | None]:
    """What an event may say about a log line, and the error's (type, last file, last line)
    for _covered. Never reads the record's message or arguments."""
    attrs: dict = {"logger": record.name if _LOGGER.fullmatch(record.name) else "other"}
    if not _ours(record):
        return attrs, None
    found = _OUR_FILE.search(record.pathname.replace(chr(92), "/"))
    if found:
        attrs.update(file=found.group(0), line=record.lineno, func=_word(record.funcName))
    exc = record.exc_info
    if not (exc and exc[0]):
        return attrs, None
    attrs["type"] = _word(exc[0].__name__)
    attrs.update(place(_tb_frames(exc[2])))
    return attrs, (exc[0].__name__, *(_last_line(exc[2]) if exc[2] is not None else ("", 0)))


class _Counter(logging.Handler):
    """Counts log lines by place in memory. It can run on an audio callback and on any
    thread: nothing here waits, so it takes no lock (not even logging's own: see handle)
    and two threads racing can at worst lose a count."""

    def __init__(self):
        super().__init__(logging.WARNING)
        self.waiting: dict[str, dict] = {}   # since the last flush
        self.seen: set[str] = set()          # this run, for MAX_PLACES
        self.over = 0                        # lines past MAX_PLACES since the last flush

    def handle(self, record):   # Handler.handle would hold the handler's lock around emit
        self.emit(record)
        return True

    def emit(self, record):
        try:
            if getattr(record, "counted", False):   # applog.COUNTED
                return
            name = LOG_ERROR if record.levelno >= logging.ERROR else LOG_WARNING
            attrs, error = _read(record)
            if getattr(record, "unsaved", False):   # applog: no report to count it after all
                error = None
            key = f"{name} {attrs}"
            have = self.waiting.get(key)
            if have is not None:
                have["count"] += 1
            elif key in self.seen or len(self.seen) < MAX_PLACES:
                self.seen.add(key)
                self.waiting[key] = {"name": name, "at": record.created, "count": 1,
                                     "attrs": attrs, "error": error}
            else:
                self.over += 1
        except Exception:  # noqa: BLE001 - logging must never raise, and this can't log it
            pass


_counter: _Counter | None = None
_started = 0.0   # time.monotonic() at install
_run_start: dict | None = None   # waits like a warning does
_ended = False


def install() -> bool:
    """Start counting, for an installed copy only (usage.enabled: never from source or with
    ONIONBOARD_NO_STATS). Count me in and Offline mode are read at each flush, as they can
    change while it runs. True when it's on."""
    from soundboard.core import usage
    global _counter, _started, _run_start, _ended
    if _counter is not None or not usage.enabled():
        return _counter is not None
    _started, _ended = time.monotonic(), False
    _run_start = event(RUN_START)
    _counter = _Counter()
    logging.getLogger().addHandler(_counter)
    return True


def _covered(one: dict) -> bool:
    """The same exception already counts: as a saved report (applog), a `warned` or a
    `failed` (usage). Otherwise a line logged on its way to one would count twice."""
    from soundboard.core import applog, usage
    if one["error"] is None:
        return False
    if one["error"] in applog._state.get("saved", ()):
        return True
    attrs = one["attrs"]
    if "file" not in attrs:
        return False
    mark = f"{attrs.get('type')}@{attrs['file']}:{attrs['line']}"
    return mark in usage._warned or any(mark in sent for sent in usage._failed)


def flush(cfg, closing: bool = False) -> None:
    """Hand what was counted to the next send (usage.note), on the thread about to ask for
    it. With the count off it's dropped: switching it on later never sends what happened
    meanwhile."""
    from soundboard.core import usage
    global _run_start
    counter = _counter
    if counter is None:
        return
    if not usage.net.allowed(usage.FEATURE):
        counter.waiting, counter.over, _run_start = {}, 0, None
        return
    if not (closing or usage.due(cfg.stats_sent or 0, time.time())
            or any(p["name"] == LOG_ERROR for p in list(counter.waiting.values()))):
        return
    places = list(counter.waiting.values())
    counter.waiting = {}
    over, counter.over = counter.over, 0
    if _run_start:
        usage.note(_run_start)
        _run_start = None
    for p in places:
        if not _covered(p):
            usage.note(event(p["name"], at=p["at"], count=p["count"], **p["attrs"]))
    if over:
        usage.note(event("problems_dropped", count=over))


def ended(cfg) -> None:
    """A clean quit: `run.end` with how long it ran, roughly, and all that waits, for
    usage.at_quit to send."""
    from soundboard.core import usage
    global _ended
    if _counter is None or _ended:
        return
    _ended = True
    flush(cfg, closing=True)
    usage.note(event(RUN_END, lasted=open_bucket(time.monotonic() - _started)))
