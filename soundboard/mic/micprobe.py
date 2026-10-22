"""After the mic effect is set up: do the board's sounds really come out of the mic?

The effect being in the registry and reading the board's audio says it's loaded, not
that a voice chat hears it. So once a set-up works, the board plays PROBE (half a second
of quiet band-limited noise, about as loud as a quiet room) into the mic only, never into
the user's own headphones, and records the mic meanwhile. The probe is found by
correlating against its known waveform, not by loudness: it scores in the hundreds when
it's there, under ten when it isn't, even under room noise (FOUND sits between).

Apps that sit between the mic and a voice chat (a virtual mic of their own: SteelSeries
Sonar, Voicemeeter, Krisp, NVIDIA Broadcast...) are checked too, without knowing them:
every other mic with sound before the set-up (alive()) is recorded alongside, and one
that sends only exact zeros afterwards was cut off by it. Their own noise removal may
take the probe out, so on their mics only "dead" counts, never "no probe".

    before = alive(other_guids)                    # before the set-up
    res = check(play, real_guid, before)           # after it works; play() starts PROBE
    res.real  -> True (heard) / False (not) / None (couldn't record)
    res.dead  -> [guid, ...]                       # had sound before, only zeros now
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass, field

import numpy as np

log = logging.getLogger(__name__)

SR = 48000
PROBE_S = 0.5
PROBE_DB = -50.0          # RMS, dBFS: about a quiet room's level
BAND = (300.0, 3400.0)    # what every voice path passes
FOUND = 15.0              # score: there (tens to hundreds) / not there (under ten)
LEAD_S = 0.3              # recording before the probe starts
RECORD_S = 1.8            # the probe, plus the way through Windows and the effect
START_S = 3.0             # how long the recordings get to start


def probe(rate: int = SR, seed: int = 7) -> np.ndarray:
    """PROBE_S of noise in BAND, faded in and out, at PROBE_DB RMS (mono float32). The
    same seed gives the same waveform: that's what check() looks for."""
    n = int(rate * PROBE_S)
    spec = np.fft.rfft(np.random.default_rng(seed).standard_normal(n))
    hz = np.fft.rfftfreq(n, 1 / rate)
    spec[(hz < BAND[0]) | (hz > BAND[1])] = 0
    x = np.fft.irfft(spec, n)
    i = np.arange(n)
    x *= np.minimum(1.0, np.minimum(i, i[::-1]) / (0.02 * rate))   # no click
    x /= np.sqrt(np.mean(x ** 2))
    return (x * 10 ** (PROBE_DB / 20)).astype(np.float32)


def score(recording: np.ndarray, rate: int = SR) -> float:
    """How clearly PROBE is in `recording` (mono, `rate`): the peak of its
    cross-correlation with PROBE over the median. Level doesn't matter. A mic at
    another rate is brought to SR first (PROBE is only defined at SR; its band is far
    below either rate's top, so a straight line between samples is enough)."""
    if rate != SR and len(recording) > 1:
        t = np.arange(int(len(recording) * SR / rate)) * (rate / SR)
        recording = np.interp(t, np.arange(len(recording)), recording).astype(np.float32)
    p = probe(SR)
    if len(recording) < len(p):
        return 0.0
    size = 1 << (len(recording) + len(p) - 1).bit_length()
    c = np.fft.irfft(np.fft.rfft(recording, size) * np.conj(np.fft.rfft(p, size)), size)
    c = np.abs(c[:len(recording) - len(p) + 1])
    med = float(np.median(c))
    return float(c.max() / med) if med > 0 else 0.0


def _record(guid: str, seconds: float, started: threading.Event | None = None):
    from soundboard.audio import appaudio
    return appaudio.record_mic(guid, seconds, started=started)


def _is_silent(guid: str) -> bool | None:
    from soundboard.audio import appaudio
    return appaudio.mic_is_silent(guid, seconds=0.5, wait=2.0)


def alive(guids: Collection[str]) -> set[str]:
    """The mics among `guids` with sound now (not only exact zeros), listened to at
    once (a check: never fails)."""
    out: set[str] = set()

    def one(g):
        try:
            if _is_silent(g) is False:
                out.add(g)
        except Exception:  # noqa: BLE001
            log.info("couldn't listen to mic %s", g, exc_info=True)
    threads = [threading.Thread(target=one, args=(g,), daemon=True, name="mic-alive")
               for g in dict.fromkeys(guids)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5.0)
    return out


@dataclass
class Result:
    real: bool | None                 # PROBE heard in the mic; None: couldn't record it
    dead: list[str] = field(default_factory=list)   # had sound before, only zeros now
    scores: dict[str, float] = field(default_factory=dict)


def check(play: Callable[[], object], real: str, others: Collection[str] = ()) -> Result:
    """Record the mic `real` and the mics `others` (those alive() before the set-up),
    call play() (it starts PROBE into the mic) and say what came out. A check: an error
    reads as "couldn't tell"."""
    guids = list(dict.fromkeys([real, *(g for g in others if g != real)]))
    got: dict[str, tuple[np.ndarray, int] | None] = {}
    started = {g: threading.Event() for g in guids}

    def one(g):
        try:
            got[g] = _record(g, RECORD_S, started[g])
        except Exception:  # noqa: BLE001
            log.info("couldn't record mic %s", g, exc_info=True)
            got[g] = None
        started[g].set()   # (failed: nothing to wait for)
    threads = [threading.Thread(target=one, args=(g,), daemon=True, name="mic-probe")
               for g in guids]
    for t in threads:
        t.start()
    end = time.monotonic() + START_S
    for g in guids:
        started[g].wait(max(0.0, end - time.monotonic()))
    time.sleep(LEAD_S)
    play()
    for t in threads:
        t.join(RECORD_S + START_S + 2.0)
    res = Result(real=None)
    for g in guids:
        rec = got.get(g)
        if rec is None:
            continue
        x, rate = rec
        s = score(x, rate)
        res.scores[g] = round(s, 1)
        if g == real:
            res.real = s >= FOUND
        elif len(x) and not np.any(x):
            res.dead.append(g)
    log.info("mic probe: %s", res)
    return res
