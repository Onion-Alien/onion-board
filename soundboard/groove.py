"""What the song playing sounds like, as it plays: its beat and a guess at its style.

Bun mode's Bun dances to it (ui/bunnywidget.py ``set_groove``): on the beat, and in a
way that suits the song: he headbangs to rock, bounces fast to electronic music, nods
to hip-hop, sways to something calm and talks along to someone speaking.

Only what was just played is read (the same stretch as the pads' visualiser, see
widgets.spectrum): a long sound is mapped from disk and what's ahead may not be in yet.
Each call does a few small FFTs (10 ms frames), so it's cheap enough for the UI tick;
the tempo and style are worked out again from the last few seconds now and then.

    g = Groove()
    g.feed(data, frac)          # each tick: the playing sound's samples and position
    g.style, g.bpm, g.beat(now) # "rock", 128.0, 41.27 (beats since it started)
"""
from __future__ import annotations

import time

import numpy as np

from soundboard.engine import SR

HOP = SR // 100          # one frame every 10 ms
WIN = 1024               # FFT size
KEEP = 800               # frames remembered (8 s)
BACKFILL = 400           # frames read at once when a song starts or jumps (4 s)
TEMPO_EVERY = 0.5        # seconds of audio between tempo checks
STYLE_EVERY = 1.0        # ... and style checks
STYLE_MIN = 250          # frames heard before the first guess (2.5 s)
SWITCH_VOTES = 3         # a new style must win this many checks in a row
BPM_LO, BPM_HI = 60.0, 185.0
STYLES = ("pop", "electronic", "rock", "hiphop", "chill", "speech")

_HANN = np.hanning(WIN).astype(np.float32)
_HZ = SR / WIN
_KICK = slice(1, max(2, round(140 / _HZ)) + 1)          # ~47..140 Hz
_VOICE = slice(round(300 / _HZ), round(3000 / _HZ))
_HIGH = slice(round(3000 / _HZ), round(10000 / _HZ))
_FLAT = slice(round(1000 / _HZ), round(6000 / _HZ))     # where distortion fills it in
_TOP = round(10000 / _HZ)
_BINS = np.arange(1, _TOP, dtype=np.float32)


def _db(x):
    return 10 * np.log10(np.maximum(x, 1e-12))


class Groove:
    """The beat and style of one playing sound (`feed` it each tick)."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.style = ""        # "" until it's heard enough to guess
        self.bpm = 0.0
        self.confidence = 0.0  # how sure of the beat (0..1)
        self.energy = 0.0      # how loud right now, 0..1
        self.kick = 0.0        # the latest onset's strength, 0..1 (decays)
        self.voice = 0.0       # how loud the vocal range is right now, 0..1 (lip sync)
        self.onset = 0.0       # 0..1 of the frame just read (a hit or a syllable)
        self._data_id = 0
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

    # ------------------------------------------------------------------ input
    def feed(self, data: np.ndarray | None, frac: float, now: float | None = None):
        """Read what was played since the last call (`frac`: 0..1 through `data`)."""
        now = time.monotonic() if now is None else now
        if data is None or len(data) < WIN:
            return
        if id(data) != self._data_id:   # another sound
            self.reset()
            self._data_id = id(data)
        end = max(0, int(min(max(frac, 0.0), 1.0) * len(data)) - WIN)   # (just played)
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
        mag = np.abs(np.fft.rfft(mono * _HANN, axis=1)).astype(np.float32) * (4.0 / WIN)
        self._frames(mag)
        self._since_tempo += n
        self._since_style += n
        if self._since_tempo >= TEMPO_EVERY * 100 and self._n >= 300:
            self._since_tempo = 0
            self._tempo(now)
        if self._since_style >= STYLE_EVERY * 100 and self._n >= STYLE_MIN:
            self._since_style = 0
            self._vote(self.guess())

    def _frames(self, mag: np.ndarray):
        lm = np.log1p(mag[:, 1:_TOP] * 10000)
        prev = lm[:1] if self._prev is None else self._prev[None, :]
        rise = np.maximum(0.0, np.diff(np.vstack([prev, lm]), axis=0))
        self._prev = lm[-1]
        flux = rise.mean(axis=1)
        kflux = rise[:, _KICK.start - 1:_KICK.stop - 1].mean(axis=1)
        p = mag * mag
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
        vdb = float(rows[3, -1])
        self._vpeak = max(vdb, self._vpeak - 0.05 * k)   # (falls 5 dB a second)
        # (the top 20 dB of it: the dip between syllables then shuts his mouth)
        self.voice = 0.0 if vdb < -65 else min(1.0, max(0.0, (vdb - self._vpeak + 20) / 20))
        hit = float((rows[0] + 2 * rows[1]).max())
        self._peak = max(hit, self._peak * 0.995 ** k)
        self.onset = min(1.0, hit / self._peak) if self._peak > 1e-4 else 0.0
        self.kick = max(self.kick * 0.85 ** k, self.onset if self.onset > 0.45 else 0.0)

    # ------------------------------------------------------------------ beat
    def _env(self, frames: int) -> np.ndarray:
        n = min(frames, self._n, KEEP)
        e = self._ring[0, -n:] + 2 * self._ring[1, -n:]
        return e - np.convolve(e, np.ones(20) / 20, "same")

    def _tempo(self, now: float):
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
            elif min(abs(ratio - 2), abs(ratio - 0.5) * 2) < 0.06:
                new = self.bpm   # double or half of it: the same beat, keep his pace
            else:   # really another tempo? only once it's heard it a few times running
                same = self._other and abs(new / self._other - 1) < 0.04
                self._doubt = self._doubt + 1 if same else 1
                self._other = new
                if self._doubt <= SWITCH_VOTES:
                    new = self.bpm
                else:
                    self._doubt = 0
        self.confidence = self.confidence * 0.5 + conf * 0.5 if self.bpm else conf
        # where the beats fall: the offset whose comb lines up with the most onsets
        period = 6000 / new
        p = int(round(period))
        best, off = -1.0, 0
        for o in range(p):
            pts = (n - 1 - o - np.arange(0, n - o, period)).astype(int)
            s = float(env[pts[pts >= 0]].sum())
            if s > best:
                best, off = s, o
        measured = off / period   # beats since the last one, now
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

    # ------------------------------------------------------------------ style
    def features(self) -> dict:
        """The last few seconds, summed up: what guess() goes by."""
        n = min(self._n, KEEP)
        r = self._ring[:, -n:]
        db = r[2]
        live = db > db.max() - 45
        med = float(np.median(db[live])) if live.any() else float(db.max())
        rel = lambda row: float(np.mean((row - db)[live])) if live.any() else -99.0  # noqa: E731
        sm = np.convolve(db, np.ones(25) / 25, "valid")   # 1/4 s steps: phrasing, not hits
        return {"bpm": self.bpm, "conf": self.confidence, "four": self._four,
                "gaps": float(np.mean(db < med - 15)),
                "bass": rel(r[4]), "voice": rel(r[3]), "high": rel(r[5]),
                "flat": float(np.mean(r[6][live])) if live.any() else 0.0,
                "cent": float(np.mean(r[7][live])) if live.any() else 0.0,
                "dyn": float(np.std(sm)) if len(sm) else 0.0,
                "onsets": float(np.mean(r[0] > np.percentile(r[0], 90) * 0.6)),
                "loud": med}

    def guess(self) -> str:
        """The style the last few seconds sound like (one of STYLES). Rules of thumb
        measured on real songs, speech and narration (a wrong guess only changes how he
        dances): speech stops and starts (gaps, big swings in loudness, few hits); metal
        is a bright wall of noise; hip-hop is dark and bassy; electronic music is a steady
        beat at club tempo; calm music has little bass or top end."""
        f = self.features()
        bpm, conf = f["bpm"], f["conf"]
        if f["gaps"] > 0.25 and f["dyn"] > 9 and f["onsets"] < 0.45 and conf < 0.5:
            return "speech"
        if f["loud"] < -22:
            return "chill"
        if (f["flat"] > 0.37 and f["high"] > -15) or (
                f["onsets"] > 0.85 and conf < 0.5 and f["bass"] > -8 and f["cent"] > -0.6):
            return "rock"
        if (f["high"] < -28 and f["bass"] < -9) or (f["bass"] < -14 and conf < 0.5):
            return "chill"
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
