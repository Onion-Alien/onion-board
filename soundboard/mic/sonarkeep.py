"""SteelSeries Sonar's devices, kept while the app runs with Sonar's mic as its mic.

When Windows' audio restarts (a driver or Windows update, another app's installer,
anything), Sonar moves its mic to another capture device and saves that as the user's
choice, and moves its Game / Chat / Media / Aux channels too. Often the new mic is a
virtual cable that sends only silence: Discord then hears nothing of the user's voice
until they pick their mic again in SteelSeries GG, and it looked like Onion Board's
fault (it's the app that was open). The mic effect's own steps already set Sonar's
devices back after their audio restarts (directmic._sonar_back); this does the same for
one the app didn't make.

So, while the app's mic is Sonar's and comes in fine, the devices Sonar's channels use
are noted every NOTE_S (directmic.sonar_devices: Sonar's local server, no admin needed).
When the mic drops out and comes back within BACK_WITHIN_S (what an audio restart does
to every stream), they're set back to what was noted before it went (directmic.
sonar_set_back), if Sonar moved any. Sonar is never ended. Nothing is noted while the
mic is out, so a choice Sonar made during the restart is never what's kept; a mic the
user picks in GG is noted by the next NOTE_S."""
from __future__ import annotations

import logging
from collections.abc import Callable

log = logging.getLogger(__name__)

NOTE_S = 30.0          # how often Sonar's devices are noted while the mic is fine
BACK_WITHIN_S = 60.0   # the mic came back within this of dropping out: set them back
CHECK_S = 10.0         # after it's back, how long to watch for Sonar moving them


class SonarKeep:
    """The decisions (`tick`, on the UI thread once a second) and the work (`note`,
    `back`, on a worker: Sonar's server takes up to seconds to answer)."""

    def __init__(self, devices: Callable[[], dict | None],
                 set_back: Callable[[dict], bool | None]):
        self._devices, self._set_back = devices, set_back
        self.saved: dict | None = None   # Sonar's devices, from before the mic dropped
        self._saved_at = -1e9            # (when; only the worker writes these two)
        self._lost_at: float | None = None
        self._noted_at = -1e9
        self.busy = False                # a job is with the worker

    def tick(self, now: float, on_sonar: bool, mic_ok: bool) -> str | None:
        """What to do now: "note", "back" or None. `on_sonar`: the app's mic is Sonar's;
        `mic_ok`: it's open and its sound is coming in."""
        if not on_sonar:
            self.saved, self._lost_at = None, None
            return None
        if not mic_ok:
            if self._lost_at is None:
                self._lost_at = now
            return None
        lost, self._lost_at = self._lost_at, None
        if self.busy:
            return None
        if lost is not None:
            if (self.saved is not None and self._saved_at < lost
                    and now - lost <= BACK_WITHIN_S):
                self.busy = True
                return "back"
            return None
        if now - self._noted_at >= NOTE_S:
            self._noted_at = now
            self.busy = True
            return "note"
        return None

    def note(self, now: float) -> None:
        """(Worker) Sonar's devices now noted; nothing kept when Sonar isn't there."""
        try:
            got = self._devices()
            if got:
                if got != self.saved:
                    log.info("Sonar's devices: %s", ", ".join(
                        f"{rid}={dev}" for (_k, rid), (dev, _r) in sorted(got.items())))
                self.saved, self._saved_at = got, now
        finally:
            self.busy = False

    def back(self, wait: Callable[[float], None], clock: Callable[[], float]) -> bool | None:
        """(Worker) the mic came back: for CHECK_S, Sonar's devices compared with what
        was noted, and set back once any moved. None when nothing moved (or no Sonar)."""
        saved = self.saved
        try:
            end = clock() + CHECK_S
            while saved:
                now = self._devices()
                if now is None or any(now.get(k, ("", False))[0] != dev
                                      for k, (dev, _ran) in saved.items()):
                    log.info("the mic came back and Sonar moved its devices (an audio "
                             "restart?): setting them back")
                    ok = self._set_back(saved)
                    log.info("Sonar's devices %s", "set back" if ok else
                             "not set back" if ok is False else "not set back (no answer)")
                    return ok
                if clock() >= end:
                    return None
                wait(1.0)
            return None
        finally:
            self.busy = False
