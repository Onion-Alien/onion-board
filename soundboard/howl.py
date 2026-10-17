"""The howl stopper: catches the squeal of a mic hearing its own speakers.

"Hear what they hear" plays your mic back to the headphones output. When that output
is a speaker, the mic picks the speaker up again, and past a certain volume the loop
feeds itself: one note grows until it squeals. Voice chat apps cancel the echo; this
path doesn't, so the engine runs every mic block through a `HowlGuard` while the mic
is played back, and stops playing it back once the guard says it's howling.

A howl looks like nothing else the mic hears: one loud, pure note that keeps exactly
the same pitch, block after block. Talking moves its pitch and spreads its energy over
many harmonics; a whistle or a sung note wobbles. The guard wants all three (loud, one
note holding most of the energy, the same frequency bin) for HOLD_S in a row, or the
mic pinned loud and dense near full scale for CLIP_S (a loop that saturates instead of ringing).

Runs on the audio thread: fixed buffers, one small FFT per hop, no locks.

`is_speaker` says whether the headphones output is really a speaker, so turning
Hear what they hear on can warn first (the UI asks Windows on a thread).
"""
from __future__ import annotations

import numpy as np

F32 = np.float32

LOUD = 0.1          # peak a howl reaches at least (-20 dBFS); talking at arm's length is below
PURE = 0.8          # share of the band's energy in the loudest note's 3 bins
LOW_HZ, HIGH_HZ = 250.0, 8000.0   # where a speaker-to-mic howl lands
HOLD_S = 0.7        # the same note this long: a howl
CLIP = 0.95         # peak that counts as pinned...
DENSE = 0.25        # ...with this RMS too (a loop fills every sample; shouting has gaps)
CLIP_S = 2.0        # pinned this long (with a few gaps): a saturated loop
CLIP_SHARE = 0.9    # share of the hops in CLIP_S that must be pinned


SPEAKERS, DISPLAY_AUDIO = 1, 9   # EndpointFormFactor values that play into the room
# Many USB headsets tell Windows they're speakers (form factor 1), so the name has the
# last word: Windows calls them "Headphones (...)" or "Speakers (... Headset)"
EAR_HINTS = ("headphone", "headset", "earphone", "earbud", "buds", "airpods", "hands-free",
             "handsfree", "in-ear")


def is_speaker(name: str | None, form_factors: dict[str, int]) -> bool:
    """Does the output `name` (as PortAudio lists it: MME cuts it at 31 characters)
    play into the room, where the mic can hear it? `form_factors`: from
    appaudio.output_form_factors(). False when it can't tell."""
    if not name:
        return False
    low = name.lower()
    if any(h in low for h in EAR_HINTS):
        return False
    squash = " ".join(low.split())
    for full, ff in form_factors.items():
        f = " ".join(full.lower().split())
        if f == squash or f.startswith(squash) or squash.startswith(f):
            return ff in (SPEAKERS, DISPLAY_AUDIO) and not any(h in f for h in EAR_HINTS)
    return False


class HowlGuard:
    """Feed it the mic (mono float32 at `rate`); `feed` returns True once it howls.
    `reset()` after acting on it, or when the playback stops."""

    def __init__(self, rate: int):
        self.rate = int(rate)
        self.n = 2048 if self.rate >= 32000 else 1024    # ~43 ms at 48 kHz, 23 Hz bins
        self.hop = self.n // 2
        self._buf = np.zeros(self.n, F32)
        self._fill = 0
        self._win = np.hanning(self.n).astype(F32)
        hz = self.rate / self.n
        self._lo = max(1, int(LOW_HZ / hz))
        self._hi = min(self.n // 2, int(HIGH_HZ / hz) + 1)
        hop_s = self.hop / self.rate
        self._need = max(2, int(round(HOLD_S / hop_s)))
        self._clip_hops = max(2, int(round(CLIP_S / hop_s)))
        self._clips = np.zeros(self._clip_hops, bool)
        self.reset()

    def reset(self):
        self._fill = 0
        self._bin = -1
        self._run = 0
        self._clips[:] = False
        self._clip_at = 0
        self._hops = 0

    def feed(self, x: np.ndarray) -> bool:
        """Add a block of mic samples; True when the last stretch was a howl."""
        x = np.asarray(x, F32).ravel()
        howl = False
        i = 0
        while i < len(x):
            take = min(len(x) - i, self.n - self._fill)
            self._buf[self._fill:self._fill + take] = x[i:i + take]
            self._fill += take
            i += take
            if self._fill == self.n:
                howl = self._hop() or howl
                self._buf[:self.hop] = self._buf[self.hop:]   # half overlap
                self._fill = self.hop
        return howl

    def _hop(self) -> bool:
        buf = self._buf
        top = float(np.max(np.abs(buf)))
        self._hops += 1
        self._clips[self._clip_at] = top >= CLIP and float(np.sqrt(np.mean(buf * buf))) >= DENSE
        self._clip_at = (self._clip_at + 1) % self._clip_hops
        if (self._hops >= self._clip_hops
                and np.count_nonzero(self._clips) >= CLIP_SHARE * self._clip_hops):
            return True
        if top < LOUD:
            self._run, self._bin = 0, -1
            return False
        p = np.abs(np.fft.rfft(buf * self._win)[self._lo:self._hi]) ** 2
        total = float(p.sum())
        k = int(np.argmax(p))
        note = float(p[max(0, k - 1):k + 2].sum())
        if total <= 0.0 or note < PURE * total:
            self._run, self._bin = 0, -1
            return False
        # a ringing note sits in one bin; at a bin's edge it may flip to the next one.
        # Measured from where the run started, so a slow slide (a whistle) can't creep
        if self._bin >= 0 and abs(k - self._bin) <= 1:
            self._run += 1
        else:
            self._run, self._bin = 1, k
        return self._run >= self._need
