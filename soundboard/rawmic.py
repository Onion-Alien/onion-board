"""Apps that record the mic without going through Onion Board (straight into my mic).

The mic effect (soundboard.directmic) runs on every stream Windows puts through the
mic's normal processing. An app that opens the mic in *raw* mode ("bypass system
processing", Discord's Studio profile, some games' voice chat) skips every effect,
ours too, so it hears the plain mic and none of the sounds.

Windows can't be asked which way a stream was opened, but two counts can be compared:
the apps recording the mic (appaudio.recording_apps, the board's own process included)
and the streams the effect runs on (its live slots, RingWriter.apps). More apps than
streams for a while: one of them gets the plain mic. Which one: the app that wasn't
there the last time the counts matched, else every app (the one reopened raw).

No false alarms: the counts only have to be short for GRACE_S in a row, and an app
must have been recording that long (one starting up opens its stream before the
effect's first block). The board's own stream is one of the effect's, so the board
counts as an app, but is never named.
"""
from __future__ import annotations

import os

GRACE_S = 5.0   # how long the effect must be short of streams before it's said


class BypassWatch:
    """Feed it each look (update); `culprits` is who to name, [] while all is fine."""

    def __init__(self, me: int | None = None):
        self.me = os.getpid() if me is None else me
        self._since: dict[int, float] = {}   # pid -> when first seen recording
        self._ok: set[int] = set()           # pids recording when the counts last matched
        self._short_since: float | None = None
        self.culprits: list = []             # [appaudio.App]

    def reset(self):
        self._since.clear()
        self._ok.clear()
        self._short_since = None
        self.culprits = []

    def update(self, apps, streams: int, now: float) -> list:
        """`apps`: who records the mic now (appaudio.App, the board's own included);
        `streams`: how many the effect runs on. Returns the apps to name."""
        live = {a.pid: a for a in apps if a.active}
        for pid in list(self._since):
            if pid not in live:
                del self._since[pid]
                self._ok.discard(pid)
        for pid in live:
            self._since.setdefault(pid, now)
        if streams >= len(live):
            self._ok |= live.keys()
            self._short_since = None
            self.culprits = []
            return self.culprits
        if self._short_since is None:
            self._short_since = now
        others = [a for pid, a in live.items()
                  if pid != self.me and now - self._since[pid] >= GRACE_S]
        if now - self._short_since < GRACE_S:
            others = []
        new = [a for a in others if a.pid not in self._ok]
        self.culprits = sorted(new or others, key=lambda a: a.name.lower())
        return self.culprits


__all__ = ["GRACE_S", "BypassWatch"]
