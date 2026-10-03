"""Network activity (Settings > Connection): every connection the app makes, so you
can check for yourself where it goes.

soundboard.net records here, so nothing that goes online is missed: urlopen() (the
app's own requests) and the relay (FFmpeg, Qt, yt-dlp and the programs the app
starts) both make their connections with net.connect(). Each entry says which
feature asked, the server and port, the route (direct, the proxy, Tor or this PC),
what happened (connected, blocked by a switch, failed and why), the bytes each way
and, where the app can read it, the HTTP request line and answer and the TLS
version. A request switched off in Settings > Privacy & security is listed as
blocked: nothing was looked up or sent for it.

Kept in memory only, at most MAX_ENTRIES: never written to disk or to the log, and
gone when the app closes. Never recorded: proxy passwords, the relay's per-launch
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
import re
import threading
import time
import urllib.parse
from dataclasses import dataclass, field

MAX_ENTRIES = 1000
MAX_REQUESTS = 20               # request lines kept per connection

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

    # every change bumps the version, so the view knows to redraw

    def connected(self, route: str) -> None:
        self.route, self.state = route, CONNECTED
        _changed()

    def failed(self, reason: str) -> None:
        self.state, self.reason, self.ended = FAILED, reason, time.time()
        _changed()

    def closed(self) -> None:
        if self.state in (CONNECTING, CONNECTED):
            self.state, self.ended = CLOSED, time.time()
            _changed()

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
_version = 0


def _changed() -> None:
    global _version
    _version += 1


def version() -> int:
    """Changes whenever anything here does (for a view polling for changes)."""
    return _version


def begin(feature, host: str, port: int, how: str = APP) -> Entry:
    """A connection about to be made (or refused) for `feature`."""
    global _count
    with _lock:
        _count += 1
        e = Entry(_count, time.time(), str(feature or ""), str(host), int(port), how)
        _entries.append(e)
    _changed()
    return e


def blocked(feature, host: str, port: int, reason: str, how: str = APP) -> Entry:
    """A request refused before anything was looked up or sent."""
    e = begin(feature, host, port, how)
    e.state, e.reason, e.ended = BLOCKED, reason, e.started
    _changed()
    return e


def entries() -> list[Entry]:
    """The entries, oldest first, as copies (connections still open keep changing)."""
    with _lock:
        live = list(_entries)
    return [dataclasses.replace(e, requests=list(e.requests)) for e in live]


def clear() -> None:
    with _lock:
        _entries.clear()
    _changed()


# --------------------------------------------------------------------------- for the view

def feature_label(feature: str) -> str:
    """What a feature key is for, in words."""
    from soundboard import net
    if feature == net.TEST:
        return "Proxy test button"
    main, _, sub = feature.partition(".")
    if main not in net.FEATURES:
        return "(didn't say)"
    label = net.FEATURES[main]
    return f"{label} ({net.SITES[sub]})" if sub in net.SITES else label


def redact(target: str) -> str:
    """A request target with the values of key/token/password-like query parameters
    masked."""
    path, q, query = target.partition("?")
    if not q:
        return target
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


def outcome(e: Entry) -> str:
    return {CONNECTING: "Connecting…", CONNECTED: "Open", CLOSED: "Done",
            BLOCKED: "Blocked", FAILED: "Failed"}[e.state]


@dataclass
class Server:
    """Everything sent to one server, for the simple view."""
    host: str
    features: list[str]
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
            s = by[e.host] = Server(e.host, [], 0, 0, 0, 0, 0, 0.0)
        label = feature_label(e.feature)
        if label not in s.features:
            s.features.append(label)
        s.connections += 1
        s.blocked += e.state == BLOCKED
        s.failed += e.state == FAILED
        s.sent += e.sent
        s.received += e.received
        s.last = max(s.last, e.started)
    return sorted(by.values(), key=lambda s: s.last, reverse=True)


def details(e: Entry) -> str:
    """One connection, in full, as text."""
    when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e.started))
    lines = [f"#{e.n}  {when}  {where(e)}",
             f"For: {feature_label(e.feature)}",
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
    head = (f"Onion Board network activity: {len(items)} connection(s). Kept in "
            "memory only; review before sharing (it shows the sites you used).")
    return "\n\n".join([head] + [details(e) for e in items])
