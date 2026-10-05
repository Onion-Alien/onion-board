"""The anonymous usage count: how many people use Onion Board, and which versions.

Once a day the installed app sends one "still here" to the project's GoatCounter
(a privacy-friendly counter): the version number and a random ID made on this PC, so
the same person isn't counted twice. Also a one-off "first start", and "updated" when
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
TIMEOUT_S = 15


def enabled() -> bool:
    """Could anything be sent at all: the installed app, with a key."""
    return bool(TOKEN) and bool(getattr(sys, "frozen", False))


def install_id(cfg) -> str:
    """This PC's random ID (made once, kept in config.json)."""
    if not cfg.stats_id:
        cfg.stats_id = uuid.uuid4().hex
    return cfg.stats_id


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
        out.append({"path": "first-start", "title": "first-start", "event": True,
                    "session": sid})
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
