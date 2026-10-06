"""The anonymous usage count: how many people use Onion Board, and which versions.

Once a day the installed app sends one "still here" to the project's GoatCounter
(a privacy-friendly counter): the version number and a random ID made on this PC, so
the same person isn't counted twice. Also a one-off "first start" (with where they
heard about the app, if they picked it on the installer's last page), and "updated" when
*Update now* installs a new version. Nothing else: no name, sounds, settings, devices,
games or IP address in the message (GoatCounter sees the connection's address like any
site does, and isn't sent it to keep or look up).

On unless switched off: the installer's "Count me in" box, or Settings > Privacy &
security > Usage count (soundboard.net, so it also obeys Offline mode, a proxy and
Tor). Copies from before it existed start with it off: they were installed as an app
that sent nothing. A copy running from source never sends anything."""
from __future__ import annotations

import json
import logging
import re
import sys
import threading
import time
import urllib.request
import uuid

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


def enabled() -> bool:
    """Could anything be sent at all: the installed app, with a key."""
    return bool(TOKEN) and bool(getattr(sys, "frozen", False))


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


def hits(cfg, now: float, event: str = "") -> list[dict]:
    """What a send would say: the daily "still here" for this version if one is due
    (and "first-start" the first time ever), or the one `event`."""
    sid = install_id(cfg)
    if event:
        return [{"path": event, "title": event, "event": True, "session": sid}]
    if now - cfg.stats_sent < EVERY_S:
        return []
    out = [{"path": f"/app/{__version__}", "title": f"Onion Board {__version__}",
            "session": sid}]
    if not cfg.stats_sent:
        heard = heard_tag(cfg.stats_heard)
        first = f"first-start/heard-{heard}" if heard else "first-start"
        out.append({"path": first, "title": first, "event": True, "session": sid})
    return out


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


def maybe_send(cfg, saved=None, event: str = "") -> None:
    """The daily count if it's due (or `event` now), on a thread, when it's allowed.
    `saved()` is called on that thread after cfg.stats_sent changed."""
    if not enabled() or not net.allowed(FEATURE):
        return
    now = time.time()
    payload = hits(cfg, now, event)
    if not payload:
        return
    netlog.cause(FEATURE, "Anonymous usage count" + (f" ({event})" if event
                                                     else " (once a day)"))

    def run():
        if send(payload) and not event:
            cfg.stats_sent = now
            if saved is not None:
                saved()
    threading.Thread(target=run, daemon=True, name="usage-count").start()
