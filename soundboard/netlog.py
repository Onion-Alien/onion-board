"""Network activity (Settings > Connection): every connection the app makes, so you
can check for yourself where it goes.

soundboard.net records here, so nothing that goes online is missed: urlopen() (the
app's own requests) and the relay (FFmpeg, Qt, yt-dlp and the programs the app
starts) both make their connections with net.connect(). Each entry says which
feature asked, the server and port, the route (direct, the proxy, Tor or this PC),
what happened (connected, blocked by a switch, failed and why), the bytes each way,
why it went online (what you did, or what the app did by itself: see cause()) and,
where the app can read it, the HTTP request line and answer and the TLS
version. A request switched off in Settings > Privacy & security is listed as
blocked: nothing was looked up or sent for it.

Kept in memory only, at most MAX_ENTRIES, and gone when the app closes: unless
"Keep a history" is on (Settings > Connection, or the installer's box: config
netlog_keep), when each connection is also added to FILE_NAME in the app's folder as
it ends, and the next start lists them again (see keep()). The list isn't written to
the app's log (though the log can name a site something failed on, unless "Keep an
app log" is off: soundboard.applog). Never recorded: proxy passwords, the relay's per-launch
secret, request headers and bodies. Query values that look like keys or tokens are
masked (see redact()).

Not listed, because the app doesn't make these connections itself: tor.exe's own
connections to the Tor network (with Tor, every connection listed here leaves
through it), links opened in your browser, and Windows Update / PowerShell
downloads (SECURITY.md, *Not covered*).
"""
from __future__ import annotations

import collections
import dataclasses
import itertools
import json
import logging
import os
import re
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from soundboard.i18n import _

log = logging.getLogger(__name__)

MAX_ENTRIES = 1000
MAX_REQUESTS = 20               # request lines kept per connection
FILE_NAME = "network-activity.jsonl"   # the kept history: one connection per line
MAX_FILE_BYTES = 5 * 1024 * 1024       # then it moves to FILE_NAME + ".old" (one kept)

CONNECTING, CONNECTED, CLOSED, BLOCKED, FAILED = (
    "connecting", "connected", "closed", "blocked", "failed")
APP, RELAY = "app", "relay"     # who made it: urlopen() or the relay
HOW = {APP: "the app itself (Python)",
       RELAY: "the app's relay (radio player, Qt, yt-dlp or a helper program)"}

# query keys whose values are masked, wherever they appear in a name
_SECRET_KEY = re.compile(r"key|token|secret|pass|auth|sig|session|cred", re.I)


@dataclass
class Entry:
    n: int
    started: float               # time.time()
    feature: str
    host: str
    port: int
    how: str
    route: str = ""
    state: str = CONNECTING
    reason: str = ""
    ended: float = 0.0
    sent: int = 0
    received: int = 0
    requests: list[str] = field(default_factory=list)
    tls: str = ""
    cause: str = ""              # why: what you did, or what the app did by itself

    # every change bumps the version, so the view knows to redraw

    def connected(self, route: str) -> None:
        self.route, self.state = route, CONNECTED
        _changed()

    def refused(self, reason: str) -> None:
        """Turned away before anything was looked up or sent."""
        self.state, self.reason, self.ended = BLOCKED, reason, self.started
        _changed()
        _save(self)

    def failed(self, reason: str) -> None:
        self.state, self.reason, self.ended = FAILED, reason, time.time()
        _changed()
        _save(self)

    def closed(self) -> None:
        if self.state in (CONNECTING, CONNECTED):
            self.state, self.ended = CLOSED, time.time()
            _changed()
            _save(self)

    def add_sent(self, n: int) -> None:
        self.sent += n
        _changed()

    def add_received(self, n: int) -> None:
        self.received += n
        _changed()

    def request(self, method: str, target: str) -> None:
        if len(self.requests) < MAX_REQUESTS:
            self.requests.append(f"{method} {redact(target)}")
            _changed()

    def response(self, status: int | str, reason: str = "") -> None:
        """The answer to the last request ("GET /x" → "GET /x → 200 OK")."""
        if self.requests and "→" not in self.requests[-1]:
            self.requests[-1] += f" → {status} {reason}".rstrip()
            _changed()

    def set_tls(self, text: str) -> None:
        self.tls = text
        _changed()

    @property
    def duration(self) -> float:
        return (self.ended or time.time()) - self.started


_lock = threading.Lock()
_entries: collections.deque[Entry] = collections.deque(maxlen=MAX_ENTRIES)
_count = 0
_versions = itertools.count(1)   # next() is atomic: `+= 1` from two threads can lose one
_version = 0
_causes: dict[str, str] = {}     # main feature -> its latest cause()


def _changed() -> None:
    global _version
    _version = next(_versions)


def version() -> int:
    """Changes whenever anything here does (for a view polling for changes)."""
    return _version


def cause(feature: str, text: str) -> None:
    """Why `feature` (a key of net.FEATURES, or "main.sub") is about to go online, in
    the user's words: what they did ("You searched YouTube for “cats”") or what the
    app does by itself ("Automatic update check"). Every connection the feature
    makes from now on says so, until its next cause(): the relay, Qt and the
    programs the app starts can't say which click they're serving, so the latest
    one stands for them all."""
    with _lock:
        _causes[str(feature).partition(".")[0]] = " ".join(str(text).split())


def quoted(text: str, limit: int = 60) -> str:
    """A name or search for a cause(), in quotes, cut short if it's long."""
    t = " ".join(str(text).split())
    return f"“{t if len(t) <= limit else t[:limit - 1].rstrip() + '…'}”"


def begin(feature, host: str, port: int, how: str = APP) -> Entry:
    """A connection about to be made (or refused) for `feature`."""
    global _count
    feature = str(feature or "")
    with _lock:
        _count += 1
        e = Entry(_count, time.time(), feature, str(host), int(port), how,
                  cause=_causes.get(feature.partition(".")[0], ""))
        _entries.append(e)
    _changed()
    return e


def blocked(feature, host: str, port: int, reason: str, how: str = APP) -> Entry:
    """A request refused before anything was looked up or sent."""
    e = begin(feature, host, port, how)
    e.refused(reason)
    return e


def entries() -> list[Entry]:
    """The entries, oldest first, as copies (connections still open keep changing)."""
    with _lock:
        live = list(_entries)
    return [dataclasses.replace(e, requests=list(e.requests)) for e in live]


def clear() -> None:
    """Forget the list, and the kept history on disk (the causes stand: they're for
    what's still to come)."""
    with _lock:
        _entries.clear()
        path = _keep_path
    if path is not None:
        _remove(path)
    _changed()


# --------------------------------------------------------------------------- kept history

_keep_path: Path | None = None   # FILE_NAME while "Keep a history" is on
_file_lock = threading.Lock()
_FIELDS = {f.name for f in dataclasses.fields(Entry)}


def keeping() -> bool:
    return _keep_path is not None


def keep(path: Path | None) -> None:
    """Keep a history in `path` (FILE_NAME in the app's folder), or stop (None).

    On: the last MAX_ENTRIES saved there from earlier starts are listed again (oldest
    first, before this run's), and what this run listed before is added to the file,
    so ticking it later in a run saves what's been listed so far. The file itself
    keeps everything (for the totals: history()) until it passes MAX_FILE_BYTES and
    moves to .old. Off: stops saving and deletes the file, so nothing is left on disk;
    this run's list stays, and ticking it again saves it back."""
    global _keep_path, _count
    old = _keep_path
    if path is None:
        with _lock:
            _keep_path = None
        if old is not None:
            _remove(old)
        _changed()
        return
    path = Path(path)
    if path == old:
        return
    saved = _read(path)
    with _lock:
        seen = {(e.started, e.host, e.port) for e in saved}
        new = [e for e in _entries if (e.started, e.host, e.port) not in seen]
        merged = (saved + new)[-MAX_ENTRIES:]
        for i, e in enumerate(merged, 1):   # one numbering across the runs
            e.n = i
        _count = len(merged)
        _entries.clear()
        _entries.extend(merged)
        _keep_path = path
        ended = [e for e in new if e.state not in (CONNECTING, CONNECTED)]
    _add(path, ended)
    _changed()


def flush() -> None:
    """At quit: save the connections still open (a radio stream, say) as they stand."""
    with _lock:
        still_open = [e for e in _entries if e.state in (CONNECTING, CONNECTED)]
    for e in still_open:
        _save(e)


def _line(e: Entry) -> str:
    return json.dumps(dataclasses.asdict(e), ensure_ascii=False) + "\n"


def _save(e: Entry) -> None:
    """Add one connection to the kept history (from whichever thread ended it)."""
    path = _keep_path
    if path is not None:
        _add(path, [e])


def _add(path: Path, items: list[Entry]) -> None:
    """Add connections to the end of the file, moving it to .old first once it's
    passed MAX_FILE_BYTES (the one .old before it goes): at most about twice that on
    disk."""
    if not items:
        return
    with _file_lock:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > MAX_FILE_BYTES:
                os.replace(path, path.with_name(path.name + ".old"))
            with open(path, "a", encoding="utf-8") as f:
                f.write("".join(_line(e) for e in items))
        except OSError:
            log.warning("couldn't add to the network activity history", exc_info=True)


def _read(path: Path, everything: bool = False) -> list[Entry]:
    """The last MAX_ENTRIES connections saved in `path` (and its .old), oldest first
    (everything: all of them). A damaged line is skipped; one still open when the app
    closed is listed as done; one saved twice (open at quit, then closed) is listed
    once, as it was last."""
    items: dict[tuple, Entry] = {}
    for p in (path.with_name(path.name + ".old"), path):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            try:
                raw = json.loads(line)
                e = Entry(**{k: v for k, v in raw.items() if k in _FIELDS})
                e.started, e.ended = float(e.started), float(e.ended)
                e.port, e.sent, e.received = int(e.port), int(e.sent), int(e.received)
                e.requests = [str(r) for r in e.requests][:MAX_REQUESTS]
            except (ValueError, TypeError, AttributeError):
                continue
            if e.state in (CONNECTING, CONNECTED):
                e.state, e.ended = CLOSED, e.ended or e.started
                e.reason = e.reason or "still open when the app closed"
            if e.state in (CLOSED, BLOCKED, FAILED):
                items[(e.started, e.host, e.port)] = e
    found = list(items.values())
    return found if everything else found[-MAX_ENTRIES:]


def kept_file() -> Path | None:
    """The kept history's file, while "Keep a history" is on and it's been written."""
    path = _keep_path
    return path if path is not None and path.is_file() else None


def history() -> list[Entry]:
    """Everything there is to add up, oldest first: with a kept history, every
    connection saved in it (not just the last MAX_ENTRIES the list shows) and this
    run's still open; without one, this run's list."""
    path = _keep_path
    live = entries()
    if path is None:
        return live
    saved = _read(path, everything=True)
    seen = {(e.started, e.host, e.port) for e in saved}
    return saved + [e for e in live if (e.started, e.host, e.port) not in seen]


def _remove(path: Path) -> None:
    with _file_lock:
        for p in (path, path.with_name(path.name + ".old")):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                log.warning("couldn't delete %s", p.name, exc_info=True)


# --------------------------------------------------------------------------- for the view

def feature_label(feature: str) -> str:
    """What a feature key is for, in words (in the language picked)."""
    from soundboard import net
    if feature == net.TEST:
        return _("Proxy test button")
    main, __, sub = feature.partition(".")
    if main not in net.FEATURES:
        return _("(didn't say)")
    label = net.feature_name(main)
    return f"{label} ({net.site_name(sub)})" if sub in net.SITES else label


def redact(target: str) -> str:
    """A request target with the values of key/token/password-like query parameters
    masked, and the login in front of the host of a whole URL (a proxy client sends
    the whole URL)."""
    path, q, query = target.partition("?")
    scheme, sep, rest = path.partition("://")
    if sep and "/" not in scheme:
        netloc, slash, tail = rest.partition("/")
        if "@" in netloc:
            path = f"{scheme}://•••@{netloc.rpartition('@')[2]}{slash}{tail}"
    if not q:
        return path
    parts = []
    for item in query.split("&"):
        name, eq, _value = item.partition("=")
        if eq and _SECRET_KEY.search(urllib.parse.unquote(name)):
            item = f"{name}=•••"
        parts.append(item)
    return f"{path}?{'&'.join(parts)}"


def size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def where(e: Entry) -> str:
    host = f"[{e.host}]" if ":" in e.host else e.host
    return f"{host}:{e.port}"


def why(e: Entry) -> str:
    return e.cause or "(not recorded)"


def outcome(e: Entry) -> str:
    return {CONNECTING: _("Connecting…"), CONNECTED: _("Open"), CLOSED: _("Done"),
            BLOCKED: _("Blocked"), FAILED: _("Failed")}[e.state]


@dataclass
class Server:
    """Everything sent to one server, for the simple view."""
    host: str
    features: list[str]
    causes: list[str]            # most recent first
    connections: int
    blocked: int
    failed: int
    sent: int
    received: int
    last: float


def servers(items: list[Entry] | None = None) -> list[Server]:
    """The servers contacted (or refused), most recent first."""
    by: dict[str, Server] = {}
    for e in entries() if items is None else items:
        s = by.get(e.host)
        if s is None:
            s = by[e.host] = Server(e.host, [], [], 0, 0, 0, 0, 0, 0.0)
        label = feature_label(e.feature)
        if label not in s.features:
            s.features.append(label)
        if e.cause:
            if e.cause in s.causes:
                s.causes.remove(e.cause)
            s.causes.insert(0, e.cause)   # entries come oldest first
        s.connections += 1
        s.blocked += e.state == BLOCKED
        s.failed += e.state == FAILED
        s.sent += e.sent
        s.received += e.received
        s.last = max(s.last, e.started)
    return sorted(by.values(), key=lambda s: s.last, reverse=True)


_TWO_PART = {"co", "com", "net", "org", "gov", "ac", "edu"}   # bbc.co.uk, abc.net.au


def site(host: str) -> str:
    """The site a server belongs to: "r3---sn-abc.googlevideo.com" → "googlevideo.com",
    "www.bbc.co.uk" → "bbc.co.uk". An IP address or a one-word name stays as it is."""
    host = host.lower().rstrip(".")
    labels = host.split(".")
    if ":" in host or len(labels) <= 2 or labels[-1].isdigit():
        return host
    keep = 3 if len(labels[-1]) == 2 and labels[-2] in _TWO_PART else 2
    return ".".join(labels[-keep:])


@dataclass
class Total:
    """Everything sent to one site (or one server), for the totals window."""
    name: str
    hosts: list[str]
    connections: int = 0
    blocked: int = 0
    failed: int = 0
    sent: int = 0
    received: int = 0
    first: float = 0.0
    last: float = 0.0

    @property
    def data(self) -> int:
        return self.sent + self.received


def totals(items: list[Entry], by_site: bool = True) -> list[Total]:
    """`items` added up per site (by_site) or per server, the most data first."""
    by: dict[str, Total] = {}
    for e in items:
        name = site(e.host) if by_site else e.host
        t = by.get(name)
        if t is None:
            t = by[name] = Total(name, [], first=e.started, last=e.started)
        if e.host not in t.hosts:
            t.hosts.append(e.host)
        t.connections += 1
        t.blocked += e.state == BLOCKED
        t.failed += e.state == FAILED
        t.sent += e.sent
        t.received += e.received
        t.first, t.last = min(t.first, e.started), max(t.last, e.started)
    return sorted(by.values(), key=lambda t: (-t.data, -t.connections, t.name))


def totals_text(rows: list[Total], head: str) -> str:
    """The totals as a tab-separated table, for the clipboard (pastes into a
    spreadsheet)."""
    day = "%Y-%m-%d %H:%M"
    lines = [head, "\t".join(["Site", "Connections", "Blocked", "Failed", "Sent (bytes)",
                              "Received (bytes)", "First", "Last", "Servers"])]
    for t in rows:
        lines.append("\t".join([t.name, str(t.connections), str(t.blocked), str(t.failed),
                                str(t.sent), str(t.received),
                                time.strftime(day, time.localtime(t.first)),
                                time.strftime(day, time.localtime(t.last)),
                                " ".join(t.hosts)]))
    return "\n".join(lines)


def details(e: Entry) -> str:
    """One connection, in full, as text."""
    when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e.started))
    lines = [f"#{e.n}  {when}  {where(e)}",
             f"For: {feature_label(e.feature)}",
             f"Why: {why(e)}",
             f"Made by: {HOW.get(e.how, e.how)}",
             f"Result: {outcome(e)}" + (f": {e.reason}" if e.reason else "")]
    if e.route:
        lines.append(f"Route: {e.route}")
    if e.state not in (BLOCKED,):
        lines.append(f"Sent: {size(e.sent)}  Received: {size(e.received)}  "
                     f"Time: {e.duration:.1f} s")
    if e.tls:
        lines.append(f"Encryption: {e.tls}")
    lines += [f"  {r}" for r in e.requests]
    return "\n".join(lines)


def as_text(items: list[Entry] | None = None) -> str:
    """The whole list, for the clipboard."""
    items = entries() if items is None else items
    kept = "Kept on this PC between starts" if keeping() else "Not saved between starts"
    head = (f"Onion Board network activity: {len(items)} connection(s). {kept}; "
            "review before sharing (it shows the sites you used).")
    return "\n\n".join([head] + [details(e) for e in items])
