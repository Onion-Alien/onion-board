"""The engine's mixing, per audio block: the voices playing on an output read
into one block (sounds at the live speed, the app's own playback at speed 1),
then the sounds bus's pitch shift, live effects, EQ and the destination's
processing. Part of soundboard.audio.engine.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from soundboard.mic import destination
from soundboard.audio import livefx
from soundboard.audio.dsp import hermite
from soundboard.audio.eq import EQ
from soundboard.audio.engineparts import (
    CH,
    I16_SCALE,
    loop_xf,
    loop_wrap,
    span,
    _aa_taps,
    LivePitch,
)

if TYPE_CHECKING:
    from soundboard.audio.engineparts import Voice


FADE_S = 0.010  # fade when a sound is stopped early (no clicks)
# a sound's own live stage rings on past its end while louder than this, at most
# TAIL_S (as the bake keeps its echo / reverb tail: soundfx)
RING_FLOOR = 1e-3
TAIL_S = 3.0


class EngineRender:
    """The engine's mixing: the playing voices read into a block (at the live speed),
    then the sounds bus's pitch, live effects, EQ and the destination's processing.
    A mixin Engine inherits, so every `self.` lookup is the same as before."""

    if TYPE_CHECKING:   # the engine's own (Engine.__init__), used here
        voices: tuple[Voice, ...]
        rates: dict[str, int]
        sound_speed: float
        sound_pitch: float
        sound_keep_pitch: bool
        sound_fx: dict
        sound_voice: dict
        radio_fx: dict
        radio_pitch: float
        apps_fx: dict
        apps_pitch: float
        eq_gains: list[float] | None
        eq_target: str
        dest: Any
        _dests: dict[str, destination.Processor]
        _eqs: dict[tuple[str, str], EQ]
        _fx_gen: dict[str, int]
        _lpitch: dict[tuple[str, str], LivePitch]
        _spitch: dict[str, LivePitch]
        _send: dict[tuple[str, str], Any]
        _sfx: dict

        def _sound_voice_fx(self, out: str, x: np.ndarray) -> np.ndarray: ...

    # ----------------------------------------------------------------- callbacks
    def _render(self, out: str, frames: int, previews_only=False,
                fixed=False, makeup=True) -> np.ndarray:
        """Mix the voices playing on `out`: the sounds (at the live speed) or, with
        `fixed`, the app's own playback (always at speed 1). `makeup`: this mix goes
        through _dest, so give back what its low cut takes (paths that skip _dest
        must not get the boost without the cut)."""
        buf = np.zeros((frames, CH), np.float32)
        silent = None   # scratch for voices that must advance but not be heard
        fade = int(FADE_S * self.rates[out])
        speed = 1.0 if fixed else float(self.sound_speed)
        # no lock: `self.voices` is an immutable tuple swapped atomically by the UI side
        voices = [v for v in self.voices
                  if v.fixed == fixed and out in v.data and out not in v.done]
        for v in voices:
            if v.seek_to:
                v._apply_seek(out)
            if not len(v.data[out]):   # nothing to play (even looped): it's over
                v.done.add(out)
                continue
            if previews_only and not v.preview:
                if silent is None:
                    silent = np.zeros((frames, CH), np.float32)
                dst = silent
            else:
                dst = buf
            data = v.data[out]
            n = len(data)
            p = v.pos[out]
            stage = v.live   # (read once: the UI swaps it whole)
            # int16 library audio is scaled here (one multiply that already happens
            # for the gain); float32 is used by cues, previews of test recordings…
            scale = I16_SCALE if data.dtype == np.int16 else np.float32(1)
            g = np.float32(v.gain) * scale
            dest = self.dest
            if makeup and dest is not None and dest.lowcut:
                g = g * np.float32(v.makeup(dest.lowcut))
            g0 = v.gate[out]
            rate = self.rates[out]
            st = v.step.get(out, 1.0)
            vspeed = speed * st   # source frames per output frame
            if stage is not None:
                vspeed *= stage[0]
            if v.stopping:  # fade out (10 ms, or the sound's own fade-out), then done
                if g0 <= 0.0 or v.paused or not n:
                    v.done.add(out)
                    continue
                target, ramp = 0.0, max(fade, int(v.fade_out * rate))
            else:
                target = 0.0 if v.paused else 1.0
                if g0 == 0.0 and target == 0.0:
                    continue  # paused: hold position, output nothing
                # the start's fade-in; pause, resume and seek take 10 ms
                ramp = int(v.fade_in * rate) if out in v.fading and target else fade
            # a one-shot's fade-out before its natural end
            tail = int(v.fade_out * rate * st) if v.fade_out > 0 and not v.loop else 0
            p_start = float(p)
            near_end = tail and n - p_start < tail + frames * max(vspeed, 1.0) + 1
            # a gain change (its slider, or the mode's make-up) glides over the block
            # instead of stepping, which crackles on held notes and bass
            g_was = v.gnow.get(out, g)
            v.gnow[out] = g
            glide = g_was != g
            if glide:
                g_top = np.float32(max(abs(g_was), abs(g)))
                if not g_top:
                    glide = False
                else:
                    g_env = np.linspace(g_was / g_top, g / g_top, frames + 1,
                                        dtype=np.float32)[1:]
                    g = g_top
            # its own live stage runs on the sound as it is (as the bake would), so it's
            # read at unity and given its gain after
            shaped = g0 != target or near_end or glide or stage is not None
            gr = scale if stage is not None else g
            if shaped:
                dst_final = dst
                dst = np.zeros((frames, CH), np.float32)
            xf = loop_xf(n, rate) if v.loop else 0
            if abs(vspeed - 1.0) < 1e-4:
                p = int(p)
                if v.loop:
                    dst += span(data, p, p + frames, True, xf) * gr
                    p = loop_wrap(p + frames, n, xf)
                elif p < n:
                    take = min(frames, n - p)
                    dst[:take] += data[p:p + take] * gr
                    p += take
            else:
                p = self._render_speed(dst, data, float(p), vspeed, gr, v.loop, xf)
            v.pos[out] = p
            rings = False
            if stage is not None:
                dst = self._voice_stage(v, out, dst, stage, p_start == 0)
                if p >= n and not v.loop:   # past its end: its echo / reverb dies away
                    v.ring[out] = v.ring.get(out, 0) + frames
                    rings = (v.ring[out] < TAIL_S * rate
                             and float(np.abs(dst).max()) >= RING_FLOOR)
                dst *= g / scale
            if shaped:
                if g0 != target:   # a straight line from g0 towards target, `ramp` long
                    step = np.float32(1.0 / max(ramp, 1)) * (1 if target > g0 else -1)
                    env = g0 + step * np.arange(1, frames + 1, dtype=np.float32)
                    env = np.clip(env, min(g0, target), max(g0, target))
                    v.gate[out] = float(env[-1])
                    if v.gate[out] == target:
                        v.fading.discard(out)
                else:
                    env = np.full(frames, target, np.float32)
                if glide:
                    env = env * g_env
                if near_end:
                    at = p_start + vspeed * np.arange(frames, dtype=np.float32)
                    env = env * np.clip((n - at) / tail, 0.0, 1.0)
                dst_final += dst * env[:, None]
                if v.stopping and v.gate[out] <= 0.0:
                    v.done.add(out)
            if p >= n and not v.loop and not rings:
                v.done.add(out)
        return buf

    def _voice_stage(self, v, out: str, x: np.ndarray, stage: tuple,
                     start: bool) -> np.ndarray:
        """A sound's own live stage on `out` (Voice.live), made at the output's rate
        (`start`: as the sound starts, else it came on mid-way)."""
        f = v.stage.get(out)
        if f is None or f.rate != self.rates[out]:
            f = v.stage[out] = livefx.SoundStage(self.rates[out], fresh=start)
        return f.process(x, stage)

    @staticmethod
    def _render_speed(dst, data, p: float, speed: float, g, loop: bool, xf: int = 0):
        """Add `data` read from position p at `speed` (cubic interpolation, lowpassed
        first when faster than 1: _aa_taps) into dst; returns the new position
        (len(data) once a one-shot has ended). A loop wraps through its crossfade
        (`xf` frames: span)."""
        n = len(data)
        if n < 2:
            return n
        pos = p + speed * np.arange(len(dst), dtype=np.float64)   # along the sound as played
        if not loop:
            pos = pos[:int(np.searchsorted(pos, n - 1))]   # frames before the end
        if len(pos):
            i = pos.astype(np.int64)
            f = (pos - i).astype(np.float32)[:, None]
            h = _aa_taps(speed) if speed > 1.0 + 1e-4 else None
            pad = 1 + (len(h) // 2 if h is not None else 0)
            lo = int(i[0]) - pad
            # only the few frames this block uses are converted and filtered (four
            # gathers straight from a song's int16 cost ~70 us per sound and output)
            w = span(data, lo, int(i[-1]) + 2 + pad, loop, xf)
            if h is not None:
                for c in range(w.shape[1]):
                    w[:, c] = np.convolve(w[:, c], h, "same")
            i0 = i - lo
            p0, p1, p2, p3 = w[i0 - 1], w[i0], w[i0 + 1], w[i0 + 2]
            if not loop:   # past either end: continue the line (a ramp stays a ramp)
                first, last = i == 0, i + 2 > n - 1
                p0[first] = 2 * p1[first] - p2[first]
                p3[last] = 2 * p2[last] - p1[last]
            dst[:len(pos)] += hermite(p0, p1, p2, p3, f) * g
        p += speed * len(dst)
        if loop:
            return loop_wrap(p, n, xf)
        return p if p < n - 1 else n

    def _sounds(self, out: str, frames: int, previews_only=False,
                makeup=True) -> np.ndarray:
        """The sounds bus: sounds at the live speed through the live pitch, plus the
        app's own playback (fixed voices) as it is. makeup=False where the bus skips
        _dest (the stream output, hear-my-voice)."""
        mix = self._fx(out, self._pitch(out, self._render(out, frames, previews_only,
                                                          makeup=makeup)))
        if self.sound_voice:
            mix = self._sound_voice_fx(out, mix)
        if any(v.fixed for v in self.voices):
            mix += self._render(out, frames, previews_only, fixed=True, makeup=makeup)
        return mix

    def _sound_st(self) -> float:
        """The live pitch's shift in semitones (see _pitch)."""
        st = float(self.sound_pitch)
        if self.sound_keep_pitch and abs(self.sound_speed - 1.0) >= 1e-4:
            st -= 12.0 * float(np.log2(max(self.sound_speed, 1e-3)))
        return st

    def _pitch(self, out: str, x: np.ndarray) -> np.ndarray:
        """Live pitch on the sounds bus: the user's shift, plus the correction that
        undoes the speed's pitch change when keep-pitch is on."""
        st = self._sound_st()
        f = self._spitch.get(out)
        if f is None or f.rate != self.rates[out]:   # made at 0 st too: it needs the history
            f = self._spitch[out] = LivePitch(self.rates[out])
        return f.process(x, st)   # at 0 st it only keeps its history fresh

    def _fx(self, out: str, x: np.ndarray, fx: dict | None = None, key=None) -> np.ndarray:
        """Live effects on the sounds bus (livefx), or on another bus with its own
        `fx` and `key`. Made when a knob comes off 0 and dropped once they're all back
        at 0 and the last change has faded out."""
        if fx is None:
            fx = self.sound_fx
        key = out if key is None else key
        f = self._sfx.get(key)
        gen = self._fx_gen.get("sounds" if key == out else key[1], 0)
        if f is None or f.rate != self.rates[out]:
            if not fx:
                return x
            f = self._sfx[key] = livefx.LiveFx(self.rates[out])
            f.gen = gen
        if f.gen != gen:
            f.gen = gen
            f.flush()
        y = f.process(x, fx)
        if not fx and f.idle:
            self._sfx.pop(key, None)
        return y

    def _live(self, out: str, bus: str, x: np.ndarray) -> np.ndarray:
        """The radio's ('radio') or the programs' ('apps') live pitch and effects.
        The pitch shifter is made the first time it's off 0 and kept from then on
        (at 0 st it only keeps its history fresh), so going back to 0 doesn't click."""
        st, fx = ((self.radio_pitch, self.radio_fx) if bus == "radio"
                  else (self.apps_pitch, self.apps_fx))
        key = (out, bus)
        f = self._lpitch.get(key)
        if f is None or f.rate != self.rates[out]:
            if not st:
                f = None
            else:
                f = self._lpitch[key] = LivePitch(self.rates[out])
        if f is not None:
            x = f.process(x, float(st))
        return self._fx(out, x, fx, key)

    def _eq(self, out: str, part: str, x: np.ndarray) -> np.ndarray:
        """Run x through the EQ if it's on and aimed at `part` ('sounds' / 'voice')."""
        g = self.eq_gains
        key = (out, part)
        f = self._eqs.get(key)
        if g is None or self.eq_target not in (part, "all"):
            # off here: fade back to the dry sound (switching straight to it clicked),
            # then drop the filter, so its old memory can't click when it's back on
            if f is None:
                return x
            y = f.process(x, None) if f.rate == self.rates[out] else x
            if f.idle or y is x:
                self._eqs.pop(key, None)
            return y
        if f is None or f.rate != self.rates[out]:
            # switched on mid-stream: fade in from the dry sound, as it fades out
            f = self._eqs[key] = EQ(self.rates[out], fade_in=f is None)
        return f.process(x, g)

    def _stage[T](self, out: str, kind: type[T]) -> T:
        """This output's Limiter / SmartMono / Ducker, made for its current rate."""
        key = (out, kind.__name__)
        f = self._send.get(key)
        if f is None or f.rate != self.rates[out]:
            f = self._send[key] = kind(self.rates[out])   # pyright: ignore[reportCallIssue]  # a stage takes its rate
        return f

    def _lowcut(self) -> int:
        """The destination mode's low cut (Hz), 0 with none: captured programs get
        the make-up for it (AuxSource.gain), as sounds do (Voice.makeup)."""
        d = self.dest
        return d.lowcut if d is not None else 0

    def _dest(self, out: str, x: np.ndarray) -> np.ndarray:
        """Shape the sounds bus for whoever is listening (soundboard.mic.destination)."""
        d = self.dest
        if d is None:
            self._dests.pop(out, None)   # start fresh when it's turned back on
            return x
        f = self._dests.get(out)
        if f is None or f.rate != self.rates[out]:
            f = self._dests[out] = destination.Processor(self.rates[out])
        return f.process(x, d)
