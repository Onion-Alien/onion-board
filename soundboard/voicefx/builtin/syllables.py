"""Critter chatter, Fart and Drum kit: every syllable you say comes out as a cute
blip, a fart or a drum hit. They listen the way the animals do (animals._Critter)."""
from __future__ import annotations

import numpy as np
from soundboard.audio.dsp import butter, sosfilt
from soundboard.voicefx import Param, critters, register

from soundboard.voicefx.builtin.animals import _Critter, _formants
from soundboard.voicefx.builtin.parts import F32

_PENTA = np.array([0.0, 2, 4, 7, 9])   # the chatter's notes (a major five-note scale)


class _Shots:
    """Sounds made whole when they start (a blip, a drum hit) played out block by
    block: [samples, position, gain, seconds playing, step]. A recording made at
    another rate than the mic's is read `step` samples a sample, so it keeps its
    pitch."""

    def __init__(self):
        self.playing: list[list] = []

    def start(self, buf: np.ndarray, gain: float, step: float = 1.0):
        self.playing.append([buf, 0.0, gain, 0.0, step])

    def louder(self, want: float, until_s: float):
        """A sound still starting gets as loud as you get (your loudness is still
        rising as a syllable starts)."""
        for v in self.playing:
            if v[3] < until_s:
                v[2] = max(v[2], want)

    def run(self, n: int, rate: int) -> np.ndarray:
        out = np.zeros(n, F32)
        keep = []
        for v in self.playing:
            buf, pos, gain, _age, step = v
            if step == 1.0:
                p = int(pos)
                seg = buf[p:p + n]
            else:
                idx = pos + step * np.arange(n)
                idx = idx[idx < len(buf) - 1]
                i0 = idx.astype(np.int64)
                fr = (idx - i0).astype(F32)
                seg = buf[i0] * (1 - fr) + buf[i0 + 1] * fr
            out[:len(seg)] += seg * F32(gain)
            v[1] = pos + step * n
            v[3] += n / rate
            if v[1] < len(buf) - 1:
                keep.append(v)
        self.playing = keep
        return out


def _filtered(sos, x) -> np.ndarray:
    """x through a filter, from scratch (a drum made whole)."""
    y = sosfilt(sos, x)
    assert isinstance(y, np.ndarray)
    return y


def _mix(x: np.ndarray, wet: np.ndarray, mix: float) -> np.ndarray:
    wet = np.tanh(wet)     # (blips or hits on top of each other stay under full scale)
    m = F32(mix)
    return wet.astype(F32) if m >= 1 else (x * (1 - m) + wet * m).astype(F32)


@register
class Chatter(_Critter):
    """Cute gibberish talk, like the little villagers of a cosy game. Every syllable
    is a short pitched blip (a long one gets a few in a row), each on a random
    little vowel and a note of a five-note scale high above your voice: your tune
    moves it (a question still goes up), a random step either way makes it babble.
    Made in code: nothing to download."""

    type = "chatter"
    name = "Critter chatter"
    description = "Every syllable you say comes out as cute gibberish blips."
    params = (Param("note", "Pitch", -12, 12, 0, " st", 1, ("lower", "higher")),
              Param("follow", "Follow my tune", 0, 1, 0.7, "", 0, ("one note", "my tune")),
              Param("mix", "Mix", 0, 1, 1))

    BASE_HZ = 600.0
    BLIP_S = (0.05, 0.1)   # one blip's length (random in between)
    GAP_S_BLIPS = 0.012     # quiet between blips in a row
    NEXT_S = 0.05           # a new syllable starts a new blip at most this often
    JITTER_ST = 2.0         # the random step either way, semitones
    FOLLOW_SCALE = 1.5      # your tune, a bit bigger (they're expressive)
    LEVEL = 1.6             # the blips' loudness against yours (they fill less time)
    WAIT_S = 0.05           # a syllable's first blip waits for its pitch to be read
    # little mouths: (centre Hz, width Hz, gain), a small throat's "a e i o u"
    VOWELS = np.array([[[1100, 400, 1.0], [1900, 500, 0.7], [3600, 700, 0.3]],
                       [[650, 300, 1.0], [2600, 500, 0.8], [3900, 700, 0.3]],
                       [[450, 250, 0.8], [3200, 500, 1.0], [4300, 700, 0.4]],
                       [[700, 300, 1.0], [1200, 400, 0.6], [3300, 700, 0.2]],
                       [[450, 250, 1.0], [1000, 400, 0.5], [3100, 700, 0.15]]], F32)

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.shots = _Shots()
        self.clock = 0.0
        self.last_start = -1e9
        self.free_at = 0.0     # when the blip playing now has ended
        self.pending = False   # a new syllable waiting for its first blip

    def _blip(self, rate: int) -> tuple[np.ndarray, float]:
        """A new blip: its samples (rms 1) and its length in seconds."""
        rng = self.rng
        secs = float(rng.uniform(*self.BLIP_S))
        n = max(16, int(secs * rate))
        semis = self.p["note"] + float(np.clip(self.rel * self.p["follow"]
                                               * self.FOLLOW_SCALE, -12, 12))
        semis += float(rng.uniform(-self.JITTER_ST, self.JITTER_ST))
        notes = 12 * np.floor(semis / 12) + _PENTA
        notes = np.concatenate([notes, [notes[0] + 12]])
        st = float(notes[np.argmin(np.abs(notes - semis))])
        f0 = self.BASE_HZ * 2 ** (st / 12)
        t = np.arange(n) / rate
        # a chirp: a touch up as it starts, down as it ends
        f = f0 * 2 ** ((1.0 - 2.5 * t / secs) / 12)
        ph = np.cumsum(2 * np.pi * f / rate)
        top = min(7000.0, 0.45 * rate)
        ks = np.arange(1, max(1, int(top / (f0 * 1.1))) + 1)
        amps = _formants(ks * f0, self.VOWELS[int(rng.integers(len(self.VOWELS)))])
        wave = np.sin(np.outer(ks, ph)).T @ amps
        a = max(1, int(0.006 * rate))
        r = max(1, int(0.35 * n))
        env = np.ones(n)
        env[:a] = np.linspace(0, 1, a)
        env[-r:] = 0.5 + 0.5 * np.cos(np.linspace(0, np.pi, r))
        wave *= env
        rms = float(np.sqrt(np.mean(wave * wave)))
        return (wave / max(rms, 1e-9)).astype(F32), secs

    def run(self, x, rate):
        n = len(x)
        if n == 0:
            return x
        fresh = self._listen(x, rate)
        self.clock += n / rate
        want = min(max(self.level, self.GATE), self.MOST) * self.LEVEL
        if fresh and self.clock - self.last_start >= self.NEXT_S:
            self.pending = True
        first = self.pending and (self.since >= self.WAIT_S or not self.talking)
        if first or (self.talking and not self.pending and self.clock >= self.free_at):
            self.pending = False
            buf, secs = self._blip(rate)
            self.shots.start(buf, want)
            self.last_start = self.clock
            self.free_at = self.clock + secs + self.GAP_S_BLIPS
        self.shots.louder(want, 0.03)
        if not self.shots.playing:
            return _mix(x, np.zeros(n, F32), self.p["mix"])
        return _mix(x, self.shots.run(n, rate), self.p["mix"])


@register
class Fart(_Critter):
    """Every syllable a fart, picked at random. The farts are real public-domain
    recordings (voicefx.critters, downloaded the first time the voice is used).
    Until they're in (or offline) it makes one up: a low, rough, flapping buzz."""

    type = "fart"
    name = "Fart"
    description = "Every syllable you say comes out as a fart."
    params = (Param("note", "Pitch", -12, 12, 0, " st", 1, ("lower", "higher")),
              Param("follow", "Follow my tune", 0, 1, 0.4, "", 0, ("one note", "my tune")),
              Param("mix", "Mix", 0, 1, 1))

    BASE_HZ = 75.0
    HOLD_S = 0.14
    GAP_S = 0.12
    MOUTHS = np.array([[[220, 200, 1.0], [550, 300, 0.6], [1400, 500, 0.25]],
                       [[300, 250, 1.0], [800, 400, 0.5], [1800, 600, 0.2]]], F32)
    BREATH = 0.35
    BREATH_BAND = (150, 1500)
    TOP_HZ = 3000.0
    VIB_DEPTH = 0.0
    FART_S = 0.3           # a made-up one lasts this long if you don't hold it

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.held = 0.0        # seconds into the syllable now (the made-up one)
        self.flap = 0.0

    def _listen(self, x, rate):
        fresh = super()._listen(x, rate)
        self.held = self.held + len(x) / rate if self.talking and not fresh else 0.0
        return fresh

    def _call(self, since, loud, rel, dt):
        if since > 1e8:
            return rel, 0.0, 0.0
        if loud:
            gain = min(since / 0.01, 1.0)
        else:
            gain = max(0.0, 1.0 - (since - self.held) / 0.08) if since < self.FART_S else 0.0
            gain = min(gain, max(0.0, 1.0 - since / self.FART_S * 0.5))
        self.flap = float(np.clip(self.flap + self.rng.normal(0, 0.5), -2.5, 2.5))
        return rel - 3.0 * min(since / 0.4, 1.0) + self.flap, gain * 1.4, min(since / 0.1, 1.0)

    def _voice(self, wave):
        # flapping: the buzz chopped by a fast, uneven flutter, then pushed rough
        n = len(wave)
        rate = self.rate or 48000
        flut = 0.6 + 0.4 * np.sin(np.cumsum(np.full(n, 2 * np.pi * 28 / rate))
                                  + self.rng.uniform(0, 2 * np.pi))
        return np.tanh(wave * flut.astype(F32) * F32(1.8)).astype(F32)


@register
class Drums(_Critter):
    """Your syllables become drums, picked by how each one starts: a low, voiced
    start ("b", "d", "m", a vowel) is a kick, a sharp bright one ("t", "k", "p", "ch")
    a snare, a hiss ("s", "sh", "f") a hi-hat. Each hit is as loud as you, and a
    syllable held on gets another hit; when you stop after a few, a crash cymbal
    tops it off. The drums are a real kit's, recorded (voicefx.critters, downloaded
    the first time the voice is used); until they're in (or offline) it plays drums
    made in code."""

    type = "drums"
    name = "Drum kit"
    description = "Every syllable you say comes out as a drum hit."
    params = (Param("tone", "Tone", -12, 12, 0, " st", 1, ("lower", "higher")),
              Param("mix", "Mix", 0, 1, 1))

    KINDS = ("kick", "snare", "hat", "crash")   # critters.SOURCES["drum-" + each]
    REPEAT_S = 0.3         # a syllable held this long gets another hit
    LEVEL = 1.5            # the hits' loudness against yours
    SPEC = 1024
    END_S = 0.2            # quiet this long after a few hits: the crash
    END_HITS = 3           # (after at least this many)
    # a recording's loudness against a made-up drum's (they're levelled over their
    # whole length; a hit's loudness is all at its start)
    REC_LEVEL = {"kick": 0.6, "snare": 0.6, "hat": 0.6, "crash": 0.35}

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        rate = rate or 48000
        self.shots = _Shots()
        self.hist = np.zeros(self.SPEC, F32)
        self.win = np.hanning(self.SPEC).astype(F32)
        self.fr = np.fft.rfftfreq(self.SPEC, 1 / rate)
        self.kits: dict = {}
        self._kit(rate)        # (made now, not on the first hit)
        self.hit_at = 0.0      # seconds into the syllable of the last hit
        self.hits: list[str] = []   # what it played (the tests read it)
        self.run_hits = 0      # hits since you started talking again
        self.run_loud = 0.0    # how loud they were, the loudest
        self.quiet_s = 0.0

    @classmethod
    def prepare(cls, cfg):
        for drum in cls.KINDS:
            critters.fetch("drum-" + drum)

    def _hit(self, drum: str, want: float, rate: int):
        """Start one `drum`: a recorded one when they're in, else a made-up one."""
        recs = critters.calls("drum-" + drum)
        if recs:
            step = 2 ** (self.p["tone"] / 12) * critters.RATE / rate
            rec = recs[int(self.rng.integers(len(recs)))]
            self.shots.start(rec, want * self.REC_LEVEL[drum] / critters.CALL_RMS, step)
        else:
            takes = self._kit(rate)[drum]
            self.shots.start(takes[int(self.rng.integers(len(takes)))], want)
        if len(self.hits) < 1000:
            self.hits.append(drum)

    def _kit(self, rate: int) -> dict:
        """Two takes of each drum at this Tone (rms of their first 50 ms: 1)."""
        key = (rate, self.p["tone"])
        kit = self.kits.get(key)
        if kit is None:
            rng = np.random.default_rng(7)
            up = 2 ** (self.p["tone"] / 12)
            kit = {"kick": [self._kick(rate, up * k) for k in (1.0, 0.94)],
                   "snare": [self._snare(rate, up * k, rng) for k in (1.0, 1.06)],
                   "hat": [self._hat(rate, up * k, rng) for k in (1.0, 0.9)],
                   "crash": [self._crash(rate, up, rng)]}
            self.kits = {key: kit}
            kit = self.kits[key]
        return kit

    @staticmethod
    def _norm(x: np.ndarray, rate: int) -> np.ndarray:
        head = x[:max(1, int(0.05 * rate))]
        x = x / max(float(np.sqrt(np.mean(head * head))), 1e-9)
        fade = min(len(x), int(0.01 * rate))
        x[-fade:] *= np.linspace(1, 0, fade)
        return x.astype(F32)

    def _kick(self, rate, up):
        t = np.arange(int(0.32 * rate)) / rate
        f = (50 + 110 * np.exp(-t / 0.035)) * up
        body = np.sin(np.cumsum(2 * np.pi * f / rate)) * np.exp(-t / 0.12)
        click = np.exp(-t / 0.002) * 0.6
        return self._norm(np.tanh(1.5 * (body + click)), rate)

    def _snare(self, rate, up, rng):
        t = np.arange(int(0.22 * rate)) / rate
        noise = rng.standard_normal(len(t))
        hi = min(9000.0 * up, 0.45 * rate)
        lo = min(1200.0 * up, 0.5 * hi)
        noise = _filtered(butter(2, [lo, hi], btype="band", fs=rate), noise)
        noise = noise / max(float(np.std(noise)), 1e-9) * np.exp(-t / 0.06)
        tone = np.sin(2 * np.pi * 190 * up * t) * np.exp(-t / 0.03) * 0.8
        return self._norm(noise + tone, rate)

    def _hat(self, rate, up, rng):
        t = np.arange(int(0.08 * rate)) / rate
        lo = min(7000.0 * up, 0.38 * rate)
        noise = _filtered(butter(2, lo, btype="high", fs=rate), rng.standard_normal(len(t)))
        return self._norm(noise * np.exp(-t / 0.018), rate)

    def _crash(self, rate, up, rng):
        # a cymbal: six detuned square waves (its metal) and noise, kept to the highs,
        # ringing out for a second and a half
        t = np.arange(int(1.6 * rate)) / rate
        metal = sum(np.sign(np.sin(2 * np.pi * f * up * t + rng.uniform(0, 6.3)))
                    for f in (410.6, 608.8, 739.2, 1045.4, 1080.0, 1600.0))
        hi = min(12000.0, 0.45 * rate)
        lo = min(3500.0, 0.4 * hi)
        metal = _filtered(butter(2, [lo, hi], btype="band", fs=rate), metal)
        noise = _filtered(butter(2, min(5000.0, 0.4 * rate), btype="high", fs=rate),
                        rng.standard_normal(len(t)))
        x = (metal / max(float(np.std(metal)), 1e-9) * 0.6
             + noise / max(float(np.std(noise)), 1e-9))
        env = np.minimum(t / 0.002, 1) * (0.35 * np.exp(-t / 0.08) + 0.65 * np.exp(-t / 0.5))
        return self._norm(x * env, rate)

    def _which(self) -> str:
        """The drum for how you're sounding now: from the last ~21 ms's spectrum."""
        s = np.abs(np.fft.rfft(self.hist * self.win)) ** 2
        total = float(s.sum())
        if total < 1e-12:
            return "kick"
        centre = float((self.fr * s).sum() / total)
        low = float(s[self.fr < 300].sum() / total)
        if centre > 3800:
            return "hat"
        if centre > 1600 or low < 0.12:
            return "snare"
        return "kick"

    def run(self, x, rate):
        n = len(x)
        if n == 0:
            return x
        h = self.hist
        if n >= len(h):
            h[:] = x[n - len(h):]
        else:
            h[:-n] = h[n:]
            h[-n:] = x
        fresh = self._listen(x, rate)
        want = min(max(self.level, self.GATE), self.MOST) * self.LEVEL
        if fresh:
            self.hit_at = 0.0
        again = self.talking and self.since - self.hit_at >= self.REPEAT_S
        if fresh or again:
            self._hit(self._which(), want, rate)
            self.hit_at = self.since
            self.run_hits += 1
            self.run_loud = max(self.run_loud, want)
        # you've stopped after a few hits: a crash on top
        self.quiet_s = 0.0 if self.talking else self.quiet_s + n / rate
        if self.quiet_s >= self.END_S and self.run_hits:
            if self.run_hits >= self.END_HITS:
                self._hit("crash", self.run_loud * 0.7, rate)
            self.run_hits, self.run_loud = 0, 0.0
        self.shots.louder(want, 0.03)
        if not self.shots.playing:
            return _mix(x, np.zeros(n, F32), self.p["mix"])
        return _mix(x, self.shots.run(n, rate), self.p["mix"])
