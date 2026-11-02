"""Pitch, Harmony and Monster growl: effects that move the voice's pitch."""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from soundboard.audio.dsp import butter, hermite
from soundboard.voicefx import Effect, Param, register

from soundboard.voicefx.builtin.parts import (F32, _Filter, _PitchTracker, _Stage, _biquad, _glide,
                                              _shift_in, _stft_size)

if TYPE_CHECKING:
    from soundboard.voicefx.builtin.space import Reverb


def _envelope_shift(spec: np.ndarray, factor: float, lifter: int) -> np.ndarray:
    """Move each frame's spectral envelope (the voice's formants: the size and shape
    of the throat and mouth) by `factor` along the frequency axis while keeping its
    fine structure (the pitch's harmonics). The envelope is the low part of the
    cepstrum; each bin is scaled by envelope(f / factor) / envelope(f)."""
    n = 2 * (spec.shape[1] - 1)
    logm = np.log(np.abs(spec) + 1e-7)
    cep = np.fft.irfft(logm, n, axis=1)
    cep[:, lifter:n - lifter + 1] = 0.0
    env = np.fft.rfft(cep, axis=1).real
    k = np.arange(spec.shape[1]) / factor
    i0 = np.minimum(k.astype(np.int64), spec.shape[1] - 1)
    i1 = np.minimum(i0 + 1, spec.shape[1] - 1)
    f = np.minimum(k - i0, 1.0)
    warped = env[:, i0] * (1 - f) + env[:, i1] * f
    return spec * np.exp(np.clip(warped - env, -3.5, 3.5))


@register
class PitchShift(Effect):
    """Time-domain pitch shifter (WSOLA, the SoundTouch approach).

    The voice is first time-stretched by the pitch ratio: it is cut into short
    overlapping sequences, and each one is spliced onto the previous at the
    offset where the two waveforms line up best (a cross-correlation search), so
    the splices fall on the voice's own period and don't beat against it. Then
    the stretched audio is resampled back to the original length, which moves
    the pitch and the formants together (the chipmunk / giant sound people expect
    from a voice changer). Latency is about SEQ + SEEK + one block, ~50 ms.

    Natural sound and Voice size move the formants on their own (_envelope_shift,
    one more ~20 ms frame): Natural 100% puts them back where your own voice has
    them, so a pitch change sounds like another person rather than a cartoon, and
    Voice size makes the throat behind the voice bigger or smaller (below 100% Mix,
    "Voice size on my voice too" reshapes the blended-in own voice as well, in its own
    frame; off for saves from before it). Both at 0 (the default, and what sounds and
    music use) skip that stage entirely.

    Autotune snaps the voice to the nearest note: a pitch tracker on the input picks
    the correction, which glides in (slow: natural tuning) or jumps (100%: the hard
    T-Pain effect). At 100% it snaps to the notes of one key (A minor) instead of
    every note: talking moves in small slides, and only bigger steps between held
    notes make it sound sung. A note is kept until the voice is clearly past the
    halfway point to the next one, so it flips cleanly instead of flickering.

    While bypassed (0 st) it keeps the last HIST_S of input, and switching on
    stretches that first, so the output doesn't go silent for the latency.
    Switching on or off crossfades dry <-> wet over XF_MS (no click).
    """

    type = "pitch"
    name = "Pitch"
    description = ("Higher or lower; a cartoon or a real-sounding person; a bigger or "
                   "smaller throat; autotune.")
    params = (Param("semitones", "Pitch", -12, 24, 0, " st", 0.5, ("lower", "higher")),
              Param("natural", "Natural sound", 0, 1, 0, "", 0, ("cartoon", "real person")),
              Param("size", "Voice size", -12, 12, 0, "", 0.5, ("smaller", "bigger")),
              Param("tune", "Autotune", 0, 1, 0, "", 0, ("off", "robotic")),
              Param("mix", "Mix", 0, 1, 1),
              Param("gap", "Gap between voices", 0, 1, 1, "", 0, ("together", "echo")),
              Param("blur", "Blur on the new voice", 0, 1, 0, "", 0, ("clear", "blurry")),
              Param("under", "Voice size on my voice too", 0, 1, 0, "", 0,
                    ("new voice only", "mine too")))

    SEQ_MS = 30.0       # one sequence of voice, copied to the output
    SEEK_MS = 10.0      # how far the splice point may move to line up
    OVL_MS = 7.0        # crossfade between one sequence and the next
    XF_MS = 10.0        # dry <-> wet crossfade when it switches on or off
    HIST_S = 0.35       # input kept while bypassed (enough to prime it at -24 st)
    FORMANT_S = 0.02    # the formant stage's frame (its added latency)
    LIFTER_S = 0.0011   # cepstrum kept as the envelope: shorter than any voice's period
    GAP_MAX_S = 0.15    # longest the blended-in voice can be held back to line up
    GAP_PER_OCTAVE_S = 0.0073   # the shifted voice's extra delay per octave down
    BLUR_SIZE, BLUR_TONE = 0.0, 9000.0   # the room Blur puts round the shifted voice: small
    BLUR_SCOOP_HZ, BLUR_SCOOP_DB = 500.0, 20.0   # ...minus its middle
    KEY = (0, 2, 3, 5, 7, 8, 10)    # Autotune at 100%: A minor (semitones above A)
    TUNE_HOLD = 0.15    # how far past halfway (semitones) before Autotune changes note

    def __init__(self, rate, values=None, channels: int = 0):
        """channels: 0 for a mono voice ((n,) blocks); 2 for stereo (n, 2) blocks, cut
        and spliced at the same places in both channels (the engine's live pitch on
        music: channels spliced on their own smear the stereo picture, and flange
        once a call folds them to mono)."""
        super().__init__(rate, values)
        self.shape = (channels,) if channels else ()
        self.seq = int(rate * self.SEQ_MS / 1000)
        self.seek = int(rate * self.SEEK_MS / 1000)
        self.ovl = int(rate * self.OVL_MS / 1000)
        self.fade_in = np.linspace(0, 1, self.ovl, endpoint=False, dtype=F32)
        if channels:
            self.fade_in = self.fade_in[:, None]
        self.fade_out = F32(1) - self.fade_in
        self.aa = _Filter()
        self.aa.f.fresh = False     # first switched on mid-voice: fade in from unfiltered
        self.running = False
        self.hist = np.zeros((int(rate * self.HIST_S),) + self.shape, F32)
        self.xf = max(1, int(rate * self.XF_MS / 1000))
        self.wet_g = 0.0        # 0 = dry, 1 = wet
        self.ratio, self.mix = 1.0, 1.0
        self.formant = 1.0      # formant correction applied after the shift (1 = none)
        self.fstage: _Stage | None = None
        self.dstage: _Stage | None = None   # Voice size on the unshifted voice (Mix < 100%)
        self.dhist = np.zeros((int(rate * self.GAP_MAX_S),) + self.shape, F32)   # blended-in
        self.held = None        # ...and how far back it is read (samples) last block
        self.blend = False      # Mix has been under 100%: keep that path going
        self.mix_g = None       # the Mix applied last block
        self.verb: Reverb | None = None     # Blur: a reverb on the shifted voice only
        self.lifter = max(8, int(rate * self.LIFTER_S))
        self.tracker: _PitchTracker | None = None
        self.tune_st = 0.0      # autotune's correction right now, in semitones
        self.tune_note: float | None = None   # the note autotune is holding
        self._reset(1.0)

    def _need(self, tempo: float) -> int:
        """Input the stretcher needs on hand before it can cut the next sequence."""
        return max(self.seek + self.seq, int((self.seq - self.ovl) * tempo) + 2)

    def _reset(self, ratio: float):
        self.inb = np.zeros((0,) + self.shape, F32)   # mic audio waiting to be stretched
        self.mid = np.zeros((self.ovl,) + self.shape, F32)   # the last sequence's tail
        self.skip = 0.0                         # fractional input position carried over
        # The stretcher can only start once it has a sequence's worth of input, so the
        # resampler starts that far behind (the effect's latency); the head start is
        # exactly what keeps it fed afterwards, whatever the mic's block size.
        # (autotune moves the ratio as you talk: a little more head start for that)
        head = self._need(1 / ratio) * ratio * (1.08 if self.p.get("tune", 0) > 0 else 1.0)
        # (its first sample is the one before the resampler's position: _resample)
        self.stretched = np.zeros((int(head) + 5,) + self.shape, F32)
        self.rs_phase = 0.0
        self.pads = 0                           # times the resampler still had to wait
        self.slows = 0                          # ...or read slower to keep up

    def _stretch(self, tempo: float) -> list[np.ndarray]:
        """Consume `inb`, producing (seq - ovl)-sample chunks at 1/tempo the speed."""
        seq, ovl, seek = self.seq, self.ovl, self.seek
        body = seq - ovl
        need = self._need(tempo)
        out = []
        while len(self.inb) >= need:
            cand = self.inb[:seek + ovl]
            if cand.ndim == 1:
                corr = np.correlate(cand, self.mid, "valid")      # seek + 1 candidates
                cs = np.cumsum(cand.astype(np.float64) ** 2)
            else:   # all channels together: one splice point for all of them
                corr = sum(np.correlate(cand[:, c], self.mid[:, c], "valid")
                           for c in range(cand.shape[1]))
                cs = np.cumsum((cand.astype(np.float64) ** 2).sum(1))
            energy = cs[ovl - 1:] - np.concatenate([[0.0], cs[:seek]])
            k = int(np.argmax(corr / np.sqrt(energy + 1e-9)))
            s = self.inb[k:k + seq]
            out.append(self.mid * self.fade_out + s[:ovl] * self.fade_in)
            out.append(s[ovl:body])
            self.mid = s[body:].copy()
            adv = body * tempo + self.skip
            i = int(adv)
            self.skip = adv - i
            self.inb = self.inb[i:]
        return out

    def _resample(self, ratio: float, n: int) -> np.ndarray:
        """n samples read from `stretched` at `ratio` (cubic: linear dulled the top
        and left images). stretched[0] is the sample before position 0."""
        buf, ph = self.stretched, self.rs_phase
        need = int(1 + ph + (n - 1) * ratio) + 3
        if len(buf) < need and n > 1:
            # the stretcher is a little behind: the pitch went up while you talked
            # (a slider, or autotune snapping up a note) and the head start was sized
            # for the old one. Read this block a touch slower so it fits, instead of
            # leaving a hole of silence (a click); that also rebuilds the head start.
            fit = (len(buf) - 4.01 - ph) / (n - 1)
            if fit >= 0.5 * ratio:
                ratio = fit
                need = int(1 + ph + (n - 1) * ratio) + 3
                self.slows += 1
        if len(buf) < need:                      # the stretcher isn't ahead yet: wait
            buf = np.concatenate([buf, np.zeros((need - len(buf),) + buf.shape[1:], F32)])
            self.pads += 1
        pos = 1 + ph + ratio * np.arange(n, dtype=np.float64)
        i = pos.astype(np.int64)
        f = (pos - i).astype(F32)
        if buf.ndim == 2:
            f = f[:, None]
        y = hermite(buf[i - 1], buf[i], buf[i + 1], buf[i + 2], f)
        nph = ph + n * ratio
        cut = int(nph)
        self.stretched, self.rs_phase = buf[cut:], nph - cut
        return y

    def _add_stretched(self, chunks, ratio: float, rate: int):
        new = np.concatenate(chunks)
        # about to read faster: keep aliasing out. The filter fades in and out
        # (dsp.SmoothSos) instead of switching: started cold, or with the memory it had
        # when it last stopped, it clicked as the pitch was dragged up past +0.3 st
        up = ratio > 1.02
        if up or not self.aa.f.idle:
            cut = 0.45 * rate / ratio
            new = self.aa.run(new, round(cut) if up else None, lambda: butter(
                4, cut, btype="low", fs=rate).astype(F32) if up else None)
        self.stretched = np.concatenate([self.stretched, new])

    def _remember(self, x):
        _shift_in(self.hist, x)

    def _prime(self, ratio: float, rate: int):
        """Start at `ratio` with the recent input already stretched, so the
        resampler's head start is real audio instead of zeros."""
        self._reset(ratio)
        # your own voice's held-back copy (Mix under 100%) starts from the recent
        # input too: from silence, the voice dropped out for the hold-back, then jumped in
        self.dhist[:] = self.hist[len(self.hist) - len(self.dhist):]
        head = len(self.stretched)
        k = self._need(1 / ratio) + int((head + self.seq) / ratio)
        self.inb = self.hist[len(self.hist) - min(k, len(self.hist)):].copy()
        chunks = self._stretch(1.0 / ratio)
        if chunks:
            self._add_stretched(chunks, ratio, rate)
        # keep what a fresh start holds after being fed len(inb) samples
        keep = max(head - int(len(self.inb) * ratio), 0)
        self.stretched = self.stretched[len(self.stretched) - keep:]

    def _target(self, x, rate) -> tuple[float, float]:
        """(pitch ratio, formant correction) for this block."""
        p = self.p
        base = 2.0 ** (p["semitones"] / 12.0)
        tune = p.get("tune", 0.0)
        if tune > 0:
            if self.tracker is None:
                self.tracker = _PitchTracker(rate)
            # the shifter plays what you said ~40 ms ago, so measure the pitch there
            tr = self.tracker
            recent = np.concatenate([self.hist, x])
            if recent.ndim == 2:
                recent = recent.mean(1)
            lag = int(self._need(1.0 / max(base, 1e-3))) - tr.window // 2
            end = min(len(recent), max(tr.window, len(recent) - max(lag, 0)))
            f0 = tr.measure(recent[end - tr.window:end])
            if f0 > 0:
                note = 12 * np.log2(f0 * base / 440.0)
                want = self._snap_note(note, tune >= 0.98) - note
                tau = 0.005 + 0.15 * (1 - tune)          # 100%: jumps (T-Pain)
                a = 1.0 if tune >= 0.98 else 1 - np.exp(-len(x) / (rate * tau))
                self.tune_st += (want - self.tune_st) * a
        else:
            self.tune_st, self.tune_note = 0.0, None
        ratio = base * 2.0 ** (self.tune_st / 12.0)
        # where the formants should end up, relative to your own voice: following the
        # pitch (a cartoon) or staying put (a real person), then made bigger/smaller
        want = base ** (1.0 - p.get("natural", 0.0)) * 2.0 ** (-p.get("size", 0.0) / 12.0)
        return ratio, want / ratio

    def _snap_note(self, note: float, key: bool) -> float:
        """The note (semitones from A 440) autotune pulls `note` to: the nearest one,
        or the nearest in KEY, but the one it's holding until clearly past halfway."""
        lo = int(np.floor(note)) - 2
        notes = [k for k in range(lo, lo + 6) if not key or k % 12 in self.KEY]
        best = min(notes, key=lambda k: abs(k - note))
        held = self.tune_note
        if (held is not None and abs(note - held) < abs(note - best) + self.TUNE_HOLD
                and (not key or held % 12 in self.KEY)):
            best = held
        self.tune_note = best
        return float(best)

    def _wants_formants(self) -> bool:
        p = self.p
        base = 2.0 ** (p["semitones"] / 12.0)
        shift = base ** -p.get("natural", 0.0) * 2.0 ** (-p.get("size", 0.0) / 12)
        return abs(np.log2(shift)) > 1e-3

    def latency(self) -> float:
        p = self.p
        if not (self.running or abs(p["semitones"]) >= 0.01 or p.get("size", 0)
                or p.get("tune", 0) > 0):
            return 0.0
        ratio = 2.0 ** (p["semitones"] / 12.0)
        s = self._need(1 / ratio) / self.rate
        if self.fstage is not None or self._wants_formants():
            n = self.fstage.n if self.fstage else _stft_size(self.rate, self.FORMANT_S)
            s += n / self.rate
        return s

    def _hold_back(self, dry, rate):
        """The shifted voice comes out ~40-80 ms after your own: below 100% Mix that
        is a slapback echo under the voice. Gap between voices at 0 holds your own
        voice back by the difference so the two line up; 1 (old saves) leaves it."""
        h, n = self.dhist, len(dry)
        buf = np.concatenate([h, dry])
        self.dhist = buf[-len(h):]
        # (lower pitches come out a little later than latency(), higher ones earlier:
        # each stretched sequence plays slower or faster than it was said, ~7 ms/octave)
        lag = ((self.latency() + self.GAP_PER_OCTAVE_S * np.log2(1.0 / self.ratio)) * rate
               - (self.dstage.n if self.dstage is not None else 0))
        k = max(min(int(round((1.0 - self.p.get("gap", 1.0)) * max(lag, 0.0))), len(h)), 0)
        k0, self.held = (k if self.held is None else self.held), k
        out = buf[len(buf) - n - k:len(buf) - k]
        if k0 != k:   # Gap or Pitch moved: crossfade to the new spot (a jump clicked)
            r = np.linspace(0, 1, n + 1, dtype=F32)[1:]
            old = buf[len(buf) - n - k0:len(buf) - k0]
            out = old + (out - old) * (r[:, None] if out.ndim == 2 else r)
        return out

    def run(self, x, rate):
        p = self.p
        mix = p["mix"]
        on = (abs(p["semitones"]) >= 0.01 or abs(p.get("size", 0)) >= 0.01
              or p.get("tune", 0) > 0) and mix > 0
        if not on and not self.running:
            self._remember(x)
            return x
        if on:
            ratio, formant = self._target(x, rate)
            if not self.running:
                self.running = True
                self._prime(ratio, rate)
            self.ratio, self.mix, self.formant = ratio, mix, formant
        ratio, mix = self.ratio, self.mix       # switching off: fade out at the old ones
        self._remember(x)
        self.inb = np.concatenate([self.inb, x])
        chunks = self._stretch(1.0 / ratio)
        if chunks:
            self._add_stretched(chunks, ratio, rate)
        wet = self._resample(ratio, len(x))
        if self.fstage is None and abs(np.log2(self.formant)) > 1e-3:
            self.fstage = _Stage(_stft_size(rate, self.FORMANT_S), self.xf)
        if self.fstage is not None:   # once on, it stays on: its delay mustn't jump
            c = self.formant
            wet = self.fstage.run(wet, lambda spec: spec if abs(np.log2(c)) <= 1e-3
                                  else _envelope_shift(spec, c, self.lifter))
        blur = p.get("blur", 0.0)
        if self.verb is None and blur > 0:
            # imported here, not at the top: space.py registers Echo and Reverb, which
            # must register (and so run) after the pitch effects
            from soundboard.voicefx.builtin.space import Reverb
            self.verb = Reverb(rate, {"size": self.BLUR_SIZE, "tone": self.BLUR_TONE, "mix": 1})
            self.verb_eq = _Filter()
        if self.verb is not None:     # once on, it stays on: its tail mustn't cut off
            # the room alone (Reverb at full Mix gives 0.4 dry + 0.8 room), with its
            # middle scooped out so the words stay clear and only lows and highs smear
            room = (self.verb.run(wet, rate) - F32(0.4) * wet) * F32(1.25)
            room = self.verb_eq.run(room, "scoop", lambda: _biquad(
                "peak", self.BLUR_SCOOP_HZ, rate, -self.BLUR_SCOOP_DB, 0.7))
            wet = wet + room * F32(blur)
        if mix < 1:
            self.blend = True
        if self.blend:
            # (once your own voice has been blended in, its held-back copy is kept
            # current even at 100% Mix: going back below read a stale one, a click.)
            # "Voice size on my voice too" reshapes the blended-in voice as well, or your
            # own voice stays recognisable under the effect (no key: old saves, as before)
            dry, d = x, 2.0 ** (-p.get("size", 0.0) * p.get("under", 0.0) / 12.0)
            if self.dstage is None and mix < 1 and abs(np.log2(d)) > 1e-3:
                self.dstage = _Stage(_stft_size(rate, self.FORMANT_S), self.xf)
            if self.dstage is not None:
                dry = self.dstage.run(x, lambda spec: spec if abs(np.log2(d)) <= 1e-3
                                      else _envelope_shift(spec, d, self.lifter))
            dry = self._hold_back(dry, rate)
            m0, self.mix_g = (mix if self.mix_g is None else self.mix_g), mix
            if mix < 1 or m0 < 1:     # (glides, like every other level)
                m = _glide(m0, mix, len(x))
                if x.ndim == 2 and np.ndim(m):
                    m = np.asarray(m)[:, None]
                wet = dry * (1 - m) + wet * m
        g0, target = self.wet_g, 1.0 if on else 0.0
        if g0 == target:
            return wet
        step = (1.0 / self.xf) * (1 if target > g0 else -1)
        env = np.clip(g0 + step * np.arange(1, len(x) + 1), 0.0, 1.0).astype(F32)
        self.wet_g = float(env[-1]) if len(x) else g0
        if x.ndim == 2:
            env = env[:, None]
        if not on and self.wet_g <= 0.0:
            self.running = False
            self.fstage = self.dstage = self.verb = None
            self.held = self.mix_g = None
            self.tune_st = 0.0
        return x + (wet - x) * env


# --------------------------------------------------------------------------- growl

@register
class Harmony(Effect):
    """Two more voices at set intervals from yours (a chord of you): two pitch
    shifters on copies of the voice, added back under it. Your own voice waits the
    shifters' delay in a line of its own, so the three land together; the chord
    is a touch wider than that line (a shifter's delay moves a little with its
    interval), which is what a choir does anyway."""

    type = "harmony"
    name = "Harmony"
    description = "Two more voices at intervals from yours: a chord, a choir."
    params = (Param("first", "First voice", -12, 12, 4, " st", 1, ("lower", "higher")),
              Param("second", "Second voice", -12, 12, 7, " st", 1, ("lower", "higher")),
              Param("level", "Volume", 0, 1, 0.7, "", 0, ("behind you", "as loud as you")))

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.a = PitchShift(rate, {"semitones": self.p["first"]})
        self.b = PitchShift(rate, {"semitones": self.p["second"]})
        wait = PitchShift(rate, {"semitones": -12}).latency()
        self.hist = np.zeros(max(1, int(wait * rate)), F32)    # your voice, waiting
        self.level = None

    def latency(self) -> float:
        return len(self.hist) / self.rate

    def set_values(self, values):
        super().set_values(values)
        self.a.set_values({"semitones": self.p["first"]})
        self.b.set_values({"semitones": self.p["second"]})

    def run(self, x, rate):
        n = len(x)
        if n == 0:
            return x
        full = np.concatenate([self.hist, x])
        held, self.hist = full[:n], full[-len(self.hist):]
        chord = self.a.run(x, rate) + self.b.run(x, rate)
        level = 0.5 * self.p["level"]
        g = _glide(level if self.level is None else self.level, level, n)
        self.level = level
        return (held + chord * g).astype(F32, copy=False)


@register
class Growl(Effect):
    """A second voice an octave below yours, the way an octave pedal makes one: a
    square wave that flips at every other cycle of your voice (so it runs at half
    your pitch) multiplied with the voice. No delay, nothing to track: demons and
    monsters."""

    type = "growl"
    name = "Monster growl"
    description = "Adds a rough voice an octave below yours."
    params = (Param("amount", "Growl", 0, 1, 0.5, "", 0, ("subtle", "monster")),
              Param("tone", "Tone", 300, 3000, 1200, " Hz", 50, ("dark", "raspy")))

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.track = _Filter()
        self.tone = _Filter()
        self.sign = 1.0
        self.parity = 0
        self.amount = None

    def run(self, x, rate):
        lo = self.track.run(x, "t", lambda: butter(2, 350, btype="low", fs=rate).astype(F32))
        level = float(np.sqrt(np.mean(lo * lo)) + 1e-9)
        s = np.where(np.abs(lo) > level * 0.3, np.sign(lo), 0.0)
        s[0] = s[0] or self.sign
        idx = np.where(s != 0, np.arange(len(s)), 0)
        s = s[np.maximum.accumulate(idx)]              # hold the last sign (hysteresis)
        rising = np.diff(np.r_[self.sign, s]) > 0
        flips = np.cumsum(rising) + self.parity
        sq = np.where(flips % 2 == 0, 1.0, -1.0).astype(F32)
        self.sign, self.parity = float(s[-1]), int(flips[-1] % 2)
        tone = self.p["tone"]
        sub = self.tone.run(x * sq, round(tone), lambda: butter(
            2, min(tone, rate * 0.45), btype="low", fs=rate).astype(F32))
        amount = 1.6 * self.p["amount"]
        g = _glide(amount if self.amount is None else self.amount, amount, len(x))
        self.amount = amount
        return x + sub * g
