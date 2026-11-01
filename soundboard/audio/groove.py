"""What the song playing sounds like, as it plays: its beat and a guess at its style.

Bun mode's Bun dances to it (ui/bun/bunnywidget.py ``set_groove``): on the beat, and in a
way that suits the song: he headbangs to rock, bounces fast to electronic music, nods
to hip-hop, sways to something calm and talks along to someone speaking.

It reads what was just played and a hair of what's about to be (LOOK: the sound is
all there, decoded, and the system reads well ahead of it), so a hit is known the
moment it's heard, not a tick later: every frame and hit carries the clock time it's
heard at, and Bun's moves land on those times (`voice_at`, `last_hit`, `next_hit`).
Each call does a few small FFTs (10 ms frames), so it's cheap enough for the UI tick;
the tempo and style are worked out again from the last few seconds now and then.

    g = Groove()
    g.feed(data, frac)          # each tick: the playing sound's samples and position
    g.style, g.bpm, g.beat(now) # "rock", 128.0, 41.27 (beats since it started)
    g.music                     # False: a soundbite or someone talking, not a song

A new sound is also read ahead once, its first PEEK_S seconds at once (it's all there,
decoded), so whether it's a song is known the moment it starts, not seconds in.
"""
from __future__ import annotations

import time

import numpy as np

from soundboard.audio.engine import SR

HOP = SR // 100          # one frame every 10 ms
WIN = 1024               # FFT size
KEEP = 800               # frames remembered (8 s)
BACKFILL = 400           # frames read at once when a song starts or jumps (4 s)
LOOK = 0.07              # seconds read ahead of what's playing (over a tick and a frame)
AT = 0.5                 # where in its window a frame's sound is heard (0: start, 1: end)
KICK_PEAK = 0.035        # a kick is loudest this long after it starts
TEMPO_EVERY = 0.5        # seconds of audio between tempo checks
STYLE_EVERY = 1.0        # ... and style checks
STYLE_MIN = 250          # frames heard before the first guess (2.5 s)
SWITCH_VOTES = 3         # another tempo or style must win this many checks in a row
CONF_SLOW = 0.1          # the style goes by the beat's sureness averaged over ~5 s...
CONF_STICK = 0.06        # ...and keeps its dance while that's this near a rule's line
ON_BEAT_S = 8.0          # seconds of beats checked for a bass hit on each one...
ON_BEAT_NEAR = 0.05      # ...this close to it (a kick on every beat: four to the floor)
ON_BEAT_STICK = 0.1      # (and the dance stays while that share is this near the line)
BREAK_CONF = 0.6         # electronic stays it through a breakdown this sure of the beat
BPM_LO, BPM_HI = 60.0, 185.0
STYLES = ("pop", "electronic", "rock", "hiphop", "chill", "speech")
CLIP_S = 6.0             # a sound shorter than this is a soundbite, never a song
PEEK_S = 8.0             # seconds of a new sound read ahead at once (music or not)
# a talk video (speech with music under it): this share of voice-range dips and quiet
# frames (features "dips", "quiet"), and a beat this unsure at most
DIPS, QUIET, TALK_CONF = 0.25, 0.4, 0.55

_HANN = np.hanning(WIN).astype(np.float32)
_HZ = SR / WIN
_KICK = slice(1, max(2, round(140 / _HZ)) + 1)          # ~47..140 Hz
_VOICE = slice(round(300 / _HZ), round(3000 / _HZ))
_HIGH = slice(round(3000 / _HZ), round(10000 / _HZ))
_FLAT = slice(round(1000 / _HZ), round(6000 / _HZ))     # where distortion fills it in
_TOP = round(10000 / _HZ)
_DRUMS = round(2000 / _HZ)   # kick, snare body, guitar chugs: no hi-hats or cymbals
# hits: (refractory seconds, how far over its running average a frame must jump);
# "bass" goes by its level instead: BASS_RISE dB up on the last few frames' lowest
HIT_RULES = {"bass": (0.12, 0.0), "drums": (0.16, 1.7)}
BASS_RISE = 5.0
BASS_FLOOR = 24.0            # ...and no more than this far under its recent peak
VOICE_KEEP = 40              # frames of the voice's level kept for lip sync (0.4 s)
HIT_KEEP = 9.0               # seconds of hits remembered
_BINS = np.arange(1, _TOP, dtype=np.float32)


def _db(x):
    return 10 * np.log10(np.maximum(x, 1e-12))


def _peek(data: np.ndarray, frac: float) -> str:
    """The style the next PEEK_S seconds of a sound (from `frac` through it) sound like,
    read all at once ("" if too little is left to tell)."""
    a = int(min(max(frac, 0.0), 1.0) * len(data))
    seg = data[a:a + int(PEEK_S * SR)]
    mono = seg.mean(axis=1, dtype=np.float32)
    if data.dtype == np.int16:
        mono /= 32768.0
    g = Groove()
    starts = HOP * np.arange(max(0, (len(mono) - WIN) // HOP))
    if len(starts) < STYLE_MIN:
        return ""
    g._read(mono[starts[:, None] + np.arange(WIN)], starts / SR)   # (one tempo check)
    return g.guess()


class Groove:
    """The beat and style of one playing sound (`feed` it each tick)."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.style = ""        # "" until it's heard enough to guess
        self._clip = False     # a sound shorter than CLIP_S (a soundbite)
        self._peeked = ""      # the style its first seconds sound like, read ahead
        self.bpm = 0.0
        self.confidence = 0.0  # how sure of the beat (0..1)
        self._conf_slow = 0.0  # ...averaged over a few seconds (what the style goes by)
        self.energy = 0.0      # how loud right now, 0..1
        self.kick = 0.0        # the latest onset's strength, 0..1 (decays)
        self.voice = 0.0       # how loud the vocal range is right now, 0..1 (lip sync)
        self.onset = 0.0       # 0..1 of the frame just read (a hit or a syllable)
        self._vt = np.zeros(0)  # the voice's level a frame (lip sync): when it's heard...
        self._vv = np.zeros(0)  # ...and how loud, 0..1
        self._t_last = 0.0     # when the newest frame read is heard
        self._data_id: int | str = 0   # which sound (its id), or "live" (feed_live)
        self._pos = -1         # next sample to read
        self._prev = None      # the last frame's log spectrum
        self._n = 0            # frames heard
        # flux, kick flux, dB, voice dB, kick dB, high dB, flatness, centroid (octaves
        # from 1 kHz), a row each, one column a frame
        self._ring = np.zeros((8, KEEP), np.float32)
        self._since_tempo = self._since_style = 0
        self._four = 0.0       # how steadily the kick lands on every beat (four to the floor)
        self._acc = None       # the tempo scores, averaged over the checks so far
        self._doubt = 0        # checks in a row that heard the same other tempo...
        self._other = 0.0      # ...this one
        self._votes: tuple[str, int] = ("", 0)
        self._beat0, self._t0 = 0.0, time.monotonic()
        self._peak = 1e-3
        self._vpeak = -90.0    # the vocal range's recent peak, dB (lip sync at any loudness)
        # the hits themselves, (song time on the clock, strength 0..1): "bass" is the
        # kick and the 808 (under ~140 Hz), "drums" kick, snare and riffs (under 2 kHz)
        self.hits: dict[str, list[tuple[float, float]]] = {"bass": [], "drums": []}
        self._hit_avg = {"bass": 0.0, "drums": 0.0}
        self._hit_peak = {"bass": 1e-3, "drums": 1e-3}
        self._hit_last = {"bass": -1e9, "drums": -1e9}
        self._hit_prev = {"bass": 0.0, "drums": 0.0}
        self._bass_db: list[float] = []   # the bass level's last few frames, dB
        self._buf = np.zeros(0, np.float32)   # a stream's samples not framed yet (feed_live)

    # ------------------------------------------------------------------ input
    def feed(self, data: np.ndarray | None, frac: float, now: float | None = None):
        """Read what was played since the last call (`frac`: 0..1 through `data`)."""
        now = time.monotonic() if now is None else now
        if data is None or len(data) < WIN:
            return
        if id(data) != self._data_id:   # another sound
            self.reset()
            self._data_id = id(data)
            self._clip = len(data) < CLIP_S * SR
            if not self._clip:
                self._peeked = _peek(data, frac)
        play = int(min(max(frac, 0.0), 1.0) * len(data))   # the sample playing now
        end = max(0, min(len(data), play + int(LOOK * SR)) - WIN)   # (a little ahead)
        if self._pos < 0 or end < self._pos or end - self._pos > BACKFILL * HOP:
            self._pos = max(0, end - BACKFILL * HOP)   # started, or a seek: catch up
            self._prev = None
        n = (end - self._pos) // HOP
        if n <= 0:
            self.kick *= 0.85
            return
        starts = self._pos + HOP * np.arange(n)
        self._pos += n * HOP
        idx = starts[:, None] + np.arange(WIN)
        seg = data[idx]                                  # (n, WIN, 2)
        mono = seg.mean(axis=2, dtype=np.float32)
        if data.dtype == np.int16:
            mono /= 32768.0
        # when each frame's sound is heard (the clock time of a sample: now, plus how
        # far past what's playing it is)
        self._read(mono, now + (starts + AT * WIN - play) / SR)

    def feed_live(self, chunk: np.ndarray, now: float | None = None, lag: float = 0.0):
        """A stream (the radio): `chunk` is the (n, 2) float32 audio that arrived since
        the last call, its last sample heard `lag` seconds after `now`."""
        now = time.monotonic() if now is None else now
        if self._data_id != "live":   # (a sound's data is an id: an int)
            self.reset()
            self._data_id = "live"
        mono = chunk.mean(axis=1, dtype=np.float32) if chunk.ndim == 2 else chunk
        buf = np.concatenate([self._buf, mono])[-(BACKFILL * HOP + WIN):]
        n = (len(buf) - WIN) // HOP + 1
        if n <= 0:
            self._buf = buf
            return
        starts = HOP * np.arange(n)
        self._buf = buf[n * HOP:]
        self._read(buf[starts[:, None] + np.arange(WIN)],
                   now + lag - (len(buf) - (starts + AT * WIN)) / SR)

    def _read(self, mono: np.ndarray, heard: np.ndarray):
        """Hear a run of frames ((n, WIN) mono), each heard at its `heard` time."""
        n = len(mono)
        mag = np.abs(np.fft.rfft(mono * _HANN, axis=1)).astype(np.float32) * (4.0 / WIN)
        self._frames(mag, heard)
        self._since_tempo += n
        self._since_style += n
        if self._since_tempo >= TEMPO_EVERY * 100 and self._n >= 300:
            self._since_tempo = 0
            self._tempo(self._t_last)
        if self._since_style >= STYLE_EVERY * 100 and self._n >= STYLE_MIN:
            self._since_style = 0
            self._vote(self.guess())

    def _frames(self, mag: np.ndarray, heard: np.ndarray | None = None):
        lm = np.log1p(mag[:, 1:_TOP] * 10000)
        prev = lm[:1] if self._prev is None else self._prev[None, :]
        rise = np.maximum(0.0, np.diff(np.vstack([prev, lm]), axis=0))
        self._prev = lm[-1]
        flux = rise.mean(axis=1)
        kflux = rise[:, _KICK.start - 1:_KICK.stop - 1].mean(axis=1)
        p = mag * mag
        if heard is not None:
            self._t_last = float(heard[-1])
            self._bass_hits(_db(p[:, _KICK].sum(axis=1)), heard)
            self._find_hits("drums", rise[:, :_DRUMS].mean(axis=1), heard)
        total = p[:, 1:_TOP].sum(axis=1)
        band = p[:, _FLAT] + 1e-12
        flat = np.exp(np.log(band).mean(axis=1)) / band.mean(axis=1)
        cent = (p[:, 1:_TOP] * _BINS).sum(axis=1) / np.maximum(total, 1e-12)
        rows = np.stack([flux, kflux, _db(total), _db(p[:, _VOICE].sum(axis=1)),
                         _db(p[:, _KICK].sum(axis=1)), _db(p[:, _HIGH].sum(axis=1)), flat,
                         np.log2(np.maximum(cent * _HZ, 50) / 1000)])
        k = rows.shape[1]
        if k >= KEEP:
            self._ring[:] = rows[:, -KEEP:]
        else:
            self._ring = np.roll(self._ring, -k, axis=1)
            self._ring[:, -k:] = rows
        self._n += k
        # right now: loudness on a -48..0 dB scale, the onset against the recent peak
        self.energy = min(1.0, max(0.0, (float(rows[2, -1]) + 48) / 48))
        # the voice (lip sync): the top 20 dB under its recent peak, which falls 5 dB a
        # second (the dip between syllables then shuts his mouth, at any loudness)
        lv = []
        for v in rows[3, -VOICE_KEEP:].tolist():
            self._vpeak = max(v, self._vpeak - 0.05)
            lv.append(0.0 if v < -65 else min(1.0, max(0.0, (v - self._vpeak + 20) / 20)))
        if heard is not None:
            self._vt = np.concatenate([self._vt, heard[-len(lv):]])[-VOICE_KEEP:]
            self._vv = np.concatenate([self._vv, lv])[-VOICE_KEEP:]
        self.voice = lv[-1]
        hit = float((rows[0] + 2 * rows[1]).max())
        self._peak = max(hit, self._peak * 0.995 ** k)
        self.onset = min(1.0, hit / self._peak) if self._peak > 1e-4 else 0.0
        self.kick = max(self.kick * 0.85 ** k, self.onset if self.onset > 0.45 else 0.0)

    def _bass_hits(self, db: np.ndarray, heard: np.ndarray):
        """The kick and the 808: the bass level jumping BASS_RISE dB over its lowest of
        the last three frames (a new note or a kick; a held 808's wobble doesn't)."""
        gap = HIT_RULES["bass"][0]
        hist, peak, last = self._bass_db, self._hit_peak["bass"], self._hit_last["bass"]
        hits = self.hits["bass"]
        for d, t in zip(db.tolist(), heard.tolist()):
            peak = max(d, peak - 0.03)   # (falls 3 dB a second)
            low = min(hist) if hist else d
            if d - low > BASS_RISE and d > peak - BASS_FLOOR and d > -70 and t - last >= gap:
                hits.append((t, min(1.0, (d - low) / 15)))
                last = t
            hist.append(d)
            if len(hist) > 3:
                del hist[0]
        self._hit_peak["bass"], self._hit_last["bass"] = peak, last
        if hits and hits[0][0] < last - HIT_KEEP:
            self.hits["bass"] = [h for h in hits if h[0] >= last - HIT_KEEP]

    def voice_at(self, now: float) -> float:
        """How loud the voice is (0..1) at `now`, from the frames heard around it."""
        if not len(self._vt):
            return self.voice
        return float(np.interp(now, self._vt, self._vv))

    def _find_hits(self, band: str, env: np.ndarray, heard: np.ndarray):
        """Note each frame where `band` jumps well over its running average (and over
        a share of its recent peak), at most one a refractory gap."""
        gap, over = HIT_RULES[band]
        avg, peak = self._hit_avg[band], self._hit_peak[band]
        last, prev = self._hit_last[band], self._hit_prev[band]
        hits = self.hits[band]
        for e, t in zip(env.tolist(), heard.tolist()):
            peak = max(e, peak * 0.998)
            if e > avg * over + 1e-3 and e > 0.3 * peak and e > prev and t - last >= gap:
                hits.append((t, min(1.0, e / peak)))
                last = t
            avg = avg * 0.96 + e * 0.04
            prev = e
        self._hit_avg[band], self._hit_peak[band] = avg, peak
        self._hit_last[band], self._hit_prev[band] = last, prev
        if hits and hits[0][0] < last - HIT_KEEP:
            self.hits[band] = [h for h in hits if h[0] >= last - HIT_KEEP]

    def last_hit(self, band: str, now: float) -> tuple[float, float]:
        """(seconds since, strength) of `band`'s latest hit heard by `now`; (inf, 0) if
        none (it knows a little of what's coming: `next_hit`)."""
        for t, s in reversed(self.hits[band]):
            if t <= now:
                return now - t, s
        return float("inf"), 0.0

    def next_hit(self, band: str, now: float) -> tuple[float, float]:
        """(seconds until, strength) of `band`'s next hit, if it's read that far yet."""
        nxt = (float("inf"), 0.0)
        for t, s in reversed(self.hits[band]):
            if t <= now:
                break
            nxt = (t - now, s)
        return nxt

    def gap(self, band: str) -> float:
        """The usual time between `band`'s hits lately (0: not enough of them)."""
        h = self.hits[band][-9:]
        if len(h) < 4:
            return 0.0
        return float(np.median(np.diff([t for t, _s in h])))

    # ------------------------------------------------------------------ beat
    def _env(self, frames: int) -> np.ndarray:
        n = min(frames, self._n, KEEP)
        e = self._ring[0, -n:] + 2 * self._ring[1, -n:]
        return e - np.convolve(e, np.ones(20) / 20, "same")

    def _tempo(self, now: float):
        """The tempo and where its beats fall (`now`: when the newest frame is heard)."""
        env = np.maximum(0.0, self._env(600))
        n = len(env)
        f = np.fft.rfft(env, 2 * n)
        ac = np.fft.irfft(f * np.conj(f))[:n]
        if ac[0] <= 0:
            return
        lags = np.arange(n, dtype=np.float64)
        lo, hi = int(6000 / BPM_HI), int(6000 / BPM_LO) + 1
        bpm = 6000 / np.maximum(lags[lo:hi], 1)
        prior = np.exp(-0.5 * (np.log2(bpm / 118) / 0.85) ** 2)
        score = ac[lo:hi] / ac[0] * prior
        # averaged over the checks: one odd stretch (a fill, a break) doesn't move it
        self._acc = score if self._acc is None else self._acc * 0.75 + score * 0.25
        score = self._acc
        i = int(np.argmax(score))
        lag = float(lo + i)
        if 0 < i < len(score) - 1:   # between frames
            a, b, c = score[i - 1], score[i], score[i + 1]
            lag += 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) else 0.0
        conf = float(max(0.0, min(1.0, ac[lo + i] / ac[0] * 1.6)))
        new = float(6000 / lag)
        kick = self._ring[1, -n:] - self._ring[1, -n:].mean()
        kf = np.fft.rfft(kick, 2 * n)
        kac = np.fft.irfft(kf * np.conj(kf))[:n]
        li = int(round(lag))
        self._four = float(max(0.0, kac[li] / kac[0])) if kac[0] > 0 and li < n else 0.0
        if self.bpm:
            ratio = new / self.bpm
            if abs(ratio - 1) < 0.04:
                new = self.bpm * 0.8 + new * 0.2   # the same tempo: steady it
                self._doubt = 0
            elif min(abs(ratio - 2), abs(ratio - 0.5) * 2, abs(ratio - 1.5),
                     abs(ratio - 2 / 3) * 1.5) < 0.06:
                new = self.bpm   # double, half or 3:2 of it: the same beat, keep his pace
            else:   # really another tempo? only once it's heard it a few times running
                same = self._other and abs(new / self._other - 1) < 0.04
                self._doubt = self._doubt + 1 if same else 1
                self._other = new
                if self._doubt <= SWITCH_VOTES:
                    new = self.bpm
                else:
                    self._doubt = 0
        self.confidence = self.confidence * 0.5 + conf * 0.5 if self.bpm else conf
        self._conf_slow += (self.confidence - self._conf_slow) * (CONF_SLOW if self.bpm else 1.0)
        # where the beats fall: the offset whose comb lines up with the most kicks (the
        # kick band alone: with the hi-hats in, it locked onto the off-beat)
        kick_env = np.maximum(0.0, kick - np.convolve(kick, np.ones(20) / 20, "same"))
        if kick_env.sum() > 0.05 * env.sum():
            env = kick_env
        late = 0.0
        if self.style == "electronic":   # the kick is the loudest the bass gets (a jump
            amp = 10 ** (self._ring[4, -n:] / 20)   # finds the off-beat bassline's starts)
            rise = amp - np.minimum(np.minimum(np.roll(amp, 1), np.roll(amp, 2)), np.roll(amp, 3))
            rise[:3] = 0.0
            env, late = np.maximum(0.0, rise), KICK_PEAK * 100   # (in frames)
        period = 6000 / new
        p = int(round(period))
        best, off = -1.0, 0
        for o in range(p):
            pts = (n - 1 - o - np.arange(0, n - o, period)).astype(int)
            s = float(env[pts[pts >= 0]].sum())
            if s > best:
                best, off = s, o
        measured = (off + late) / period   # beats since the last one, now
        if not self.bpm:
            self.bpm = new
            self._beat0, self._t0 = measured, now
            return
        b = self.beat(now)
        self._beat0, self._t0, self.bpm = b, now, new
        err = (measured - b + 0.5) % 1.0 - 0.5
        self._beat0 += err * (0.5 if self.confidence > 0.3 else 0.2)

    def beat(self, now: float | None = None) -> float:
        """Beats since it started (whole numbers fall on the beat), at `now`."""
        now = time.monotonic() if now is None else now
        if not self.bpm:
            return 0.0
        return self._beat0 + (now - self._t0) * self.bpm / 60

    def _on_beat(self) -> float:
        """The share of the last ON_BEAT_S seconds' beats with a bass hit right on them:
        most for a kick on every beat (house, techno), half or less for hip-hop's 808."""
        if not self.bpm:
            return 0.0
        end, spb = self._t_last, 60 / self.bpm
        b = self.beat(end)
        beats = end - (b - np.arange(np.ceil(b - ON_BEAT_S / spb), np.floor(b) + 1)) * spb
        hits = np.array([t for t, _s in self.hits["bass"] if t > end - ON_BEAT_S - 1])
        if not len(beats) or not len(hits):
            return 0.0
        return float(np.mean(np.abs(beats[:, None] - hits[None, :]).min(axis=1) < ON_BEAT_NEAR))

    # ------------------------------------------------------------------ style
    @property
    def music(self) -> bool | None:
        """Whether a song is playing: False for a soundbite (shorter than CLIP_S) or
        someone talking, None while it's too soon to tell (the radio's first seconds).
        Before the style is settled a sound goes by what its first seconds sounded like
        when they were read ahead."""
        if self._clip:
            return False
        style = self.style or self._peeked
        return (style != "speech") if style else None

    def features(self) -> dict:
        """The last few seconds, summed up: what guess() goes by."""
        n = min(self._n, KEEP)
        r = self._ring[:, -n:]
        db = r[2]
        live = db > db.max() - 45
        med = float(np.median(db[live])) if live.any() else float(db.max())
        rel = lambda row: float(np.mean((row - db)[live])) if live.any() else -99.0  # noqa: E731
        sm = np.convolve(db, np.ones(25) / 25, "valid")   # 1/4 s steps: phrasing, not hits
        # talking: the voice range keeps dropping 20 dB under its peak (the gaps between
        # words), and many frames are quiet next to the second round them. Music under
        # the words fills the gaps; a beat with no singer fills the quiet.
        pw = 10 ** (db / 10)
        near = np.convolve(pw, np.ones(100) / 100, "same")
        v = r[3]
        top = np.max(np.lib.stride_tricks.sliding_window_view(
            np.pad(v, 50, mode="edge"), 101), axis=1)[:len(v)] if len(v) else v
        return {"bpm": self.bpm, "conf": self._conf_slow, "four": self._four,
                "on_beat": self._on_beat(),
                "gaps": float(np.mean(db < med - 15)),
                "bass": rel(r[4]), "voice": rel(r[3]), "high": rel(r[5]),
                "flat": float(np.mean(r[6][live])) if live.any() else 0.0,
                "cent": float(np.mean(r[7][live])) if live.any() else 0.0,
                "dyn": float(np.std(sm)) if len(sm) else 0.0,
                "onsets": float(np.mean(r[0] > np.percentile(r[0], 90) * 0.6)),
                "loud": med,
                "dips": float(np.mean(v < top - 20)) if len(v) else 0.0,
                "quiet": float(np.mean(pw < 0.5 * near)) if len(pw) else 0.0}

    def guess(self) -> str:
        """The style the last few seconds sound like (one of STYLES). Rules of thumb
        measured on real songs, speech and narration (a wrong guess only changes how he
        dances): speech stops and starts (gaps, big swings in loudness, few hits); metal
        is a bright wall of noise; hip-hop is dark and bassy; electronic music is a steady
        beat at club tempo; calm music has little bass or top end.

        The beat's sureness and the kicks on the beat wobble from bar to bar, so while
        they're within CONF_STICK / ON_BEAT_STICK of a rule's line, the style he's dancing
        to stays (a pop chorus wobbling over the line flipped him into headbanging and
        back every few seconds, a techno track between hip-hop and electronic), and a
        techno track's breakdown, the kick gone but the beat as sure, stays electronic."""
        f = self.features()
        style = self._rules(f)
        if self.style == "electronic" and style == "hiphop" and f["conf"] >= BREAK_CONF:
            return self.style   # a breakdown with the kick out, the beat as sure as ever
        if self.style and style != self.style:
            for dc in (-CONF_STICK, 0.0, CONF_STICK):
                for do in (-ON_BEAT_STICK, 0.0, ON_BEAT_STICK):
                    if self._rules({**f, "conf": f["conf"] + dc,
                                    "on_beat": f["on_beat"] + do}) == self.style:
                        return self.style
        return style

    @staticmethod
    def _rules(f: dict) -> str:
        bpm, conf = f["bpm"], f["conf"]
        if f["gaps"] > 0.25 and f["dyn"] > 9 and f["onsets"] < 0.45 and conf < 0.5:
            return "speech"
        if f.get("dips", 0.0) > DIPS and f.get("quiet", 0.0) > QUIET and conf < TALK_CONF:
            return "speech"   # (a talk video: music under it, so the first rule misses it)
        if f["loud"] < -22:
            return "chill"
        if (f["flat"] > 0.37 and f["high"] > -15) or (
                f["onsets"] > 0.85 and conf < 0.5 and f["bass"] > -8 and f["cent"] > -0.6):
            return "rock"
        if (f["high"] < -28 and f["bass"] < -9) or (f["bass"] < -14 and conf < 0.5):
            return "chill"
        if ((f["on_beat"] >= 0.6 or f["four"] >= 0.35) and conf >= 0.55
                and 116 <= bpm <= 150 and f["bass"] > -10):   # a kick on (nearly) every
            return "electronic"   # beat: dark techno, not hip-hop (its 808 lands on half
                                  # the beats or less)
        if f["cent"] < -1.1 and f["high"] < -17 and not 115 <= bpm <= 140:   # (club tempo:
            return "hiphop"                                                # dark house)
        if 116 <= bpm <= 145 and conf >= 0.5 and f["bass"] > -10:
            return "electronic"
        return "pop"

    def _vote(self, style: str):
        last, n = self._votes
        n = n + 1 if style == last else 1
        self._votes = (style, n)
        # the first guess needs two checks in a row to agree (a dance that changed style
        # a second in looked wrong); a change after that, SWITCH_VOTES
        if style != self.style and n >= (2 if not self.style else SWITCH_VOTES):
            self.style = style
