"""One download job's progress as one number that only goes forward.

A link goes through several steps: it's looked up, its audio comes in (yt-dlp may fetch
it in parts: a video and its sound, or again after a retry), then it's converted. Each
step used to fill its own bar from 0, so the bar ran full and dropped back to empty a
few times for one sound. Here each step is a stretch of the same bar:

    looked up    0 .. LOOKED_UP
    download     LOOKED_UP .. FETCHED   (a new part fills what's left of it)
    converting   FETCHED, until the job's done (1.0)

and the bar never moves back. `batch()` does the same for a whole list of picks.
"""
from __future__ import annotations

LOOKED_UP = 0.05   # where the download starts on the bar
FETCHED = 0.9      # the download's end: converting is the last stretch
NEW_PART = 0.3     # a download falling back this far is the next part, not a wobble


class JobProgress:
    """Feed it the link bar's progress payloads (`update`); `value` is the bar, 0..1."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.value = 0.0
        self.stage = "parsing"   # "parsing", "downloading", "processing", "done"
        self._base = LOOKED_UP   # where the part downloading now starts on the bar
        self._last = 0.0         # that part's own 0..1 last time

    def update(self, payload) -> float:
        """'parsing', 'processing' (or a number below 0), or 0..1 of a part downloaded."""
        if self.stage == "done":
            return self.value
        if payload == "parsing":
            self.stage = "parsing"
        elif payload == "processing" or (isinstance(payload, (int, float)) and payload < 0):
            self.stage = "processing"
            self.value = max(self.value, FETCHED)
        elif isinstance(payload, (int, float)):
            f = max(0.0, min(1.0, float(payload)))
            if self.stage != "downloading":
                self._base, self._last = max(self.value, LOOKED_UP), 0.0
            elif f < self._last - NEW_PART:   # the next part: it fills what's left
                self._base = self.value
            self.stage = "downloading"
            self._last = f
            self.value = max(self.value, self._base + (FETCHED - self._base) * f)
        return self.value

    def finish(self) -> float:
        self.stage = "done"
        self.value = 1.0
        return self.value


def batch(done: int, running: float | None, waiting: int) -> float:
    """A list of picks as one bar: `done` ended (added or failed), the running one's
    0..1 (None: none running) and `waiting` still to start."""
    total = done + (running is not None) + waiting
    if not total:
        return 0.0
    return min(1.0, (done + (running or 0.0)) / total)
