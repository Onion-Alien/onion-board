"""The engine's stream callbacks and the buses they fill: what goes out on the
send (main), the headphones (mon) and OBS's device, the mic block and what
it feeds, the send's limiter, gate and howl guard. Each callback is a thin
guard around the work (an exception that escaped one would end its stream).
Part of soundboard.audio.engine.
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

import numpy as np

from soundboard.mic import directmic
from soundboard.audio.howl import HowlGuard
from soundboard.audio.sendfx import (
    CEILING_DB,
    SAFETY_DB,
    Ducker,
    Limiter,
    SafetyLimiter,
    SmartMono,
    VoiceLeveler,
)
from soundboard.core import errors
from soundboard.audio.engineparts import (
    SR,
    CH,
    loud_boost,
    peak,
    finite,
    finite_peak,
    limit_peak,
    is_xrun,
    _add,
    AuxSource,
)

if TYPE_CHECKING:
    from soundboard.audio.devicelist import CableTap
    from soundboard.audio.engineparts import DirectFifo, LivePitch, Ring, StreamResampler, Voice

log = logging.getLogger("soundboard.audio.engine")


# where Sounds over 100 % round their peaks to: the limiter that follows them
LOUD_SEND = 10 ** (CEILING_DB / 20)
LOUD_SAFE = 10 ** (SAFETY_DB / 20)


class EngineBus:
    """The engine's stream callbacks and the buses each one sends. A mixin Engine
    inherits, so every `self.` lookup is the same as before."""

    if TYPE_CHECKING:   # the engine's own (Engine.__init__, its devices), used here
        voices: tuple[Voice, ...]
        aux: tuple[AuxSource, ...]
        rates: dict[str, int]
        errors: dict[str, str]
        cb_errors: dict[str, int]
        _cb_err_base: dict[str, int]
        _last_cb: dict[str, float]
        xruns: dict[str, int]
        main_stream: Any
        mon_stream: Any
        mic_stream: Any
        obs_stream: Any
        main_direct: bool
        direct_mode: int
        fifo_direct: DirectFifo
        tap: CableTap | None
        copies: tuple[CableTap, ...]
        main_tap: list[np.ndarray] | None
        ring_main: Ring
        ring_mon: Ring
        ring_obs: Ring
        ring_rmain: Ring
        ring_rmon: Ring
        ring_robs: Ring
        _rs_main: StreamResampler
        _rs_mon: StreamResampler
        _rs_obs: StreamResampler
        sending: bool
        limiter_on: bool
        send_mono: bool
        duck_db: float
        sound_vol: float
        sound_fx: dict
        mic_enabled: bool
        mic_muted: bool
        mic_gate: bool
        mic_vol: float
        mon_vol: float
        mon_voice_only: bool
        monitor_sounds: bool
        obs_voice: bool
        obs_vol: float
        radio_live: bool
        radio_monitor: bool
        radio_vol: float
        voice_chain: Any
        voice_level: bool
        dest: Any
        _gate: dict[str, float]
        _glides: dict
        _idle_n: dict[str, int]
        _quiet: dict[str, int]
        _mic_pow: list[float]
        _mic_rec: list[np.ndarray] | None
        _take: list[np.ndarray] | None
        _take_fx: bool
        _play_take: list[np.ndarray] | None
        play_take_out: str
        _send: dict[tuple[str, str], Any]
        _sfx: dict
        _spitch: dict[str, LivePitch]

        def direct_stream(self) -> Any: ...
        def _sounds(self, out: str, frames: int, previews_only=False,
                    makeup=True) -> np.ndarray: ...
        def _sound_st(self) -> float: ...
        def _live(self, out: str, bus: str, x: np.ndarray) -> np.ndarray: ...
        def _eq(self, out: str, part: str, x: np.ndarray) -> np.ndarray: ...
        def _stage[T](self, out: str, kind: type[T]) -> T: ...
        def _lowcut(self) -> int: ...
        def _dest(self, out: str, x: np.ndarray) -> np.ndarray: ...

    # Each PortAudio callback is a thin guard around the real work: an exception that
    # escapes a callback makes PortAudio abort the stream for good, silently. Here it
    # is logged (once per opened stream, so the audio thread never does repeated file
    # I/O), counted, and the block is left silent. check_streams() reports the key.
    def _guard(self, key: str, exc: BaseException):
        self.cb_errors[key] += 1
        if self.cb_errors[key] - self._cb_err_base[key] == 1:
            log.error("exception in %s audio callback", key, exc_info=exc)
            self.errors[key] = f"audio callback failed: {errors.plain(exc)}"

    def _cb_out(self, key, work, outdata, frames, status):
        self._last_cb[key] = time.monotonic()
        if is_xrun(status):
            self.xruns[key] += 1
        try:
            work(outdata, frames)
        except Exception as e:  # noqa: BLE001
            outdata.fill(0)
            self._guard(key, e)

    def _cb_main(self, outdata, frames, t, status):
        self._cb_out("main", self._main, outdata, frames, status)

    def _cb_mon(self, outdata, frames, t, status):
        self._cb_out("mon", self._mon, outdata, frames, status)

    def _cb_obs(self, outdata, frames, t, status):
        self._cb_out("obs", self._obs, outdata, frames, status)

    DIRECT_LOCK_S = 0.02   # longest the mic callback waits on the mic effect's feed

    def _cb_mic(self, indata, frames, t, status):
        self._last_cb["mic"] = time.monotonic()
        if is_xrun(status):
            self.xruns["mic"] += 1
        try:
            d = self.direct_stream()
            if d is None:
                self._mic(indata)
                return
            if not d.mic_live:
                # under the stream's lock: its thread can go live on the clean mic (and
                # switch the mic's rate) mid-block, and _mic must not run on both
                if not d.lock.acquire(timeout=self.DIRECT_LOCK_S):
                    return   # its thread is stuck: the watchdog sees to that
                try:
                    live = d.mic_live
                    if not live:
                        self._mic(indata)
                finally:
                    d.lock.release()
                if not live:
                    return
            # this block went through the mic effect, sounds and all: the clean one
            # came from the effect already; take it now rather than at the next poll
            d.pump()
        except Exception as e:  # noqa: BLE001
            self._guard("mic", e)

    def _main(self, outdata, frames):
        mix, idle, play = self._bus("main", frames, self.sound_vol)
        self.level_play = max(play, self.level_play * 0.85)
        # off with only your voice going out (mic_only): the sounds, radio and programs
        # fade out here, before the mic goes in; the send stage below stays open
        voice = self.mic_only()
        if idle:
            self._glides[("main", "bus")] = 0.0 if voice else 1.0
        else:
            finite(mix)
            mix = self._vol("main", "bus", mix, 0.0 if voice else 1.0)
        if self.main_direct:
            m = self.fifo_direct.read(frames)
            add = self.direct_mode == directmic.MODE_REPLACE
            mix = self._send_bus("main", mix, m, add_mic=add, silent=idle,
                                 sounds_vol=self.sound_vol)
            self._direct_mic_gain()
        else:
            m, add = self.ring_main.read(frames), True
            mix = self._send_bus("main", mix, m, silent=idle, sounds_vol=self.sound_vol)
        # still silence unless the mic went in: every stage below would only pass zeros
        silent = idle and not (add and m is not None and self.mic_enabled and not self.mic_muted)
        # muted: others get silence (faded, not cut), nothing else changes
        send = 1.0 if self.sending or voice else 0.0
        if silent:
            self._glides[("main", "send")] = send
        else:
            mix = self._vol("main", "send", mix, send)
        if self.limiter_on:
            lim = self._stage("main", Limiter)
            if not silent:
                mix = lim.process(mix)
            else:
                y = lim.silence(frames)   # None: at rest, zeros out
                if y is not None:
                    mix, silent = y, False
        if silent:
            outdata.fill(0)
            self.level_main *= 0.85
        else:
            pk = limit_peak(mix)   # (soft_limit, and the peak it leaves)
            outdata[:] = mix
            self.level_main = max(pk, self.level_main * 0.85)
        cable = self.tap
        if cable is not None and self.main_direct:
            cable.write(mix)
        for c in self.copies:   # Also play on
            c.write(mix)
        tap = self.main_tap
        if tap is not None:
            tap.append(mix.copy())
        rec = self._rec_buf   # read once: cancel_test_record may clear it meanwhile
        if rec is not None:
            rec.append(mix.copy())
            self._rec_frames_left -= frames
            if self._rec_frames_left <= 0 and self._rec_buf is rec:   # not cancelled
                self._rec_buf = None
                # joined by whoever reads rec_done: seconds of audio is too much
                # to copy in an audio callback
                self._rec_done = (rec, self.rates["main"])

    def _mon(self, outdata, frames):
        # muted only changes what others hear: your sounds keep playing for you as
        # usual. With only your voice going out (mic_only) you still hear your mic, and
        # your sounds as with mic check off (they were cut here once: muting went silent)
        voice = self.mic_check and self.mic_only()
        check = self.mic_check and self.sending or voice
        path = (check, voice, check and self.mon_voice_only)
        # Switching what the headphones hear (Hear what they hear on or off): this block
        # still plays the old way, faded out, and the new way fades in from silence
        # next block. Jumping straight from one to the other (stereo to the mono send,
        # in and out of the limiter's delay) clicked, and clicking the button over and
        # over while a sound played made a buzz.
        fade = path != self._mon_path
        if fade:
            check, voice, _ = self._mon_path
            if path[0] and not check:   # the limiter's delay still holds the end of
                self._send.pop(("mon", "Limiter"), None)   # last time: start it empty
                self._mon_ramp = True   # ...and what goes in from silence (below)
            path, self._mon_path = self._mon_path, path
        out_vol = 0.0 if fade else self.mon_vol
        if path[2]:
            self._mon_voice(outdata, frames, out_vol)
            return
        # in mic check you hear the real output mix: sounds at their outgoing
        # level plus your mic, so you can judge the balance while a song plays
        hear = check and not voice
        # Who's listening shapes only what's sent: your own playback stays as mixed,
        # unless you hear what they hear
        mix, idle, play = self._bus("mon", frames, self.sound_vol if hear else 1.0, hear=hear,
                                    can_idle=not check,
                                    previews_only=not (hear or self.monitor_sounds),
                                    makeup=hear)
        m = self.ring_mon.read(frames)
        # the main output sees the rest; this one counts with no send device too
        self.level_play = max(play, self.level_play)   # _main decays it; no main: the UI does
        if idle:   # silence all the way: only the volume's glide and the limiter to keep
            self._bus_quiet("mon", mix, silent=True)
            self._glides[("mon", "out")] = float(out_vol)
            y = self._stage("mon", SafetyLimiter).silence(frames)
            if y is None:
                outdata.fill(0)
                self.level_mon *= 0.85
                return
            mix = y
        else:
            finite(mix)
            if check:   # you hear what others get: the same send stage, your mic in it
                mix = self._send_bus("mon", mix, m, sounds_vol=self.sound_vol if hear else 1.0,
                                     shape=hear)
                if self._mon_ramp:   # an empty limiter starts with its delay of silence
                    self._mon_ramp = False
                    mix = mix * np.linspace(0.0, 1.0, len(mix), dtype=np.float32)[:, None]
                if self.limiter_on:
                    mix = self._stage("mon", Limiter).process(mix)
            elif not self._bus_quiet("mon", mix):
                mix = self._eq("mon", "sounds", mix)
            mix = self._vol("mon", "out", mix, out_vol)
            mix = self._stage("mon", SafetyLimiter).process(loud_boost(mix, out_vol))
        outdata[:] = mix
        self.level_mon = max(peak(mix), self.level_mon * 0.85)

    def _mon_voice(self, outdata, frames, out_vol: float | None = None):
        """Hear my voice: your changed voice alone in your headphones (previews still
        play), to tune a voice without your sounds over it."""
        mix = self._sounds("mon", frames, previews_only=True, makeup=False)   # no _dest here
        self.ring_rmon.read(frames)        # keep the others' rings drained meanwhile
        for a in self.aux:
            a.ring_mon.read(frames)
        m = self.ring_mon.read(frames)
        if m is not None:
            on = self.mic_enabled and not self.mic_muted
            mix += self._vol("mon", "mic", m, self.mic_vol if on else 0.0)
        v = self.mon_vol if out_vol is None else out_vol
        mix = self._vol("mon", "out", finite(mix), v)
        mix = self._stage("mon", SafetyLimiter).process(loud_boost(mix, v))
        outdata[:] = mix
        self.level_mon = max(peak(mix), self.level_mon * 0.85)

    def device_delay(self) -> float | None:
        """Seconds your mic and send device add on their own (what the drivers report,
        plus the mic ring's cushion), or None while they aren't open."""
        try:
            mic, out = self.mic_stream, self.main_stream
            if mic is None or out is None:
                return None
            # one-way streams: a float each (a tuple is for duplex ones)
            return (float(mic.latency) + float(out.latency)   # pyright: ignore[reportArgumentType]
                    + self.ring_main.prefill_s)
        except Exception:  # noqa: BLE001 - a stream closing meanwhile
            return None

    def _obs(self, outdata, frames):
        """The stream output: what others get (sounds, the live radio and programs,
        your mic if obs_voice), clean: no voice chat shaping, no mono, its own volume."""
        # clean: no _dest, so no makeup
        mix, idle, _ = self._bus("obs", frames, self.sound_vol, makeup=False)
        if not idle:
            finite(mix)
        if not self._bus_quiet("obs", mix, silent=idle):   # else its EQ has rung out
            mix = self._eq("obs", "sounds", mix)
        m = self.ring_obs.read(frames)
        if m is None:
            self._glides[("obs", "mic")] = 0.0   # nothing coming: it fades in when it does
        else:
            on = self.obs_voice and self.mic_enabled and not self.mic_muted
            if on or self._glides.get(("obs", "mic"), 0.0):   # on, or still fading out
                m = self._vol("obs", "mic", self._gated("obs", m), self.mic_vol if on else 0.0)
                mix += self._eq("obs", "voice", m)
                idle = False
        # muted: the stream gets silence too (faded, not cut)
        out_vol = self.obs_vol if self.sending else 0.0
        if idle:   # silence all the way: only the volume's glide and the limiters to keep
            self._glides[("obs", "out")] = float(out_vol)
            y = self._stage("obs", Limiter).silence(frames) if self.limiter_on else None
            safety = self._stage("obs", SafetyLimiter)
            y = safety.silence(frames) if y is None else safety.process(y)
            if y is None:
                outdata.fill(0)
                self.level_obs *= 0.85
                return
            mix = y
        else:
            mix = self._vol("obs", "out", mix, out_vol)
            if self.limiter_on:
                mix = self._stage("obs", Limiter).process(mix)
            mix = self._stage("obs", SafetyLimiter).process(mix)
        outdata[:] = mix
        self.level_obs = max(peak(mix), self.level_obs * 0.85)

    def _bus(self, out: str, frames: int, sounds_vol: float, hear: bool = False,
             can_idle: bool = True, previews_only: bool = False,
             makeup: bool = True) -> tuple[np.ndarray, bool, float]:
        """How _main, _mon and _obs all start: the block of `out`'s sounds bus, with
        the sounds at `sounds_vol` and the live radio and captured programs at the
        volumes `out` gives them (_radio_on, _aux_gain). With nothing to mix
        (_bus_idle, when `can_idle`) the mixer is skipped and the bus is zeros.
        Returns the bus, whether it is that silence, and the loudest of what's playing
        (level_play). `hear`: the headphones hear what others get (mic check). The
        play take is recorded here too, on the output it's taken from."""
        idle = can_idle and self._bus_idle(out, frames)
        if idle:
            mix = np.zeros((frames, CH), np.float32)
            self._glides[(out, "sounds")] = float(sounds_vol)
            play = 0.0
        else:
            self._wake_bus(out)
            mix = self._vol(out, "sounds",
                            self._sounds(out, frames, previews_only, makeup=makeup), sounds_vol)
            if sounds_vol > 1.0 and out == "obs":
                # over 100 %: louder by rounding the peaks to where the limiter after
                # it holds them (Limiter at CEILING_DB, or the SafetyLimiter / end clip).
                # main and mon round theirs in _send_bus, after the voice chat shaping:
                # its filters built the rounded peaks back up, and the limiter turned
                # 1000 % down to 300 % again
                mix = loud_boost(mix, sounds_vol, self._loud_ceiling())
            play = peak(mix)
        take = self._play_take   # read once: the UI may end it meanwhile
        took = mix.copy() if take is not None and self.play_take_out == out else None
        ring = (self.ring_rmain if out == "main" else
                self.ring_rmon if out == "mon" else self.ring_robs)
        r = ring.read(frames)
        if r is not None:
            r = self._live(out, "radio", r)
            idle = False
            play = max(play, peak(r) * self.radio_vol)
            on = self._radio_on(out, hear)
            mix += self._vol(out, "radio", r, self.radio_vol if on else 0.0)
            if took is not None:   # the radio as you hear it, sent out or not
                took += r * np.float32(self.radio_vol)
        if took is not None and take is not None:
            take.append(took)
        # the low cut's make-up goes only where the mode's shaping does: what's sent,
        # and the headphones while they hear it (the stream output is clean)
        lowcut = self._lowcut() if makeup else 0
        apps = None
        for a in self.aux:
            ring = a.ring_main if out == "main" else a.ring_mon if out == "mon" else a.ring_obs
            x = ring.read(frames)
            if x is not None:
                idle = False
                play = max(play, peak(x) * a.vol)
                apps = _add(apps, self._vol(out, ("aux", a.key), x,
                                            self._aux_gain(out, a, lowcut, hear)))
        if apps is not None:
            mix += self._live(out, "apps", apps)
        return mix, idle, play

    def _radio_on(self, out: str, hear: bool) -> bool:
        """The radio is heard on `out`: others and the stream output get it while it's
        live; the headphones when you listen to it, or hear what's sent while it's live."""
        if out == "mon":
            return self.radio_monitor or (hear and self.radio_live)
        return self.radio_live

    @staticmethod
    def _aux_gain(out: str, a: AuxSource, lowcut: int, hear: bool) -> float:
        """A captured program's volume on `out` (0: not on it), with the make-up for
        the mode's low cut when `lowcut` (AuxSource.gain: what's sent, and the
        headphones while they hear it); the stream output gets it clean."""
        if out == "obs":
            return a.vol if a.stream else 0.0
        on = a.live if out == "main" else (a.monitor or (hear and a.live))
        return a.gain(out, lowcut) if on else 0.0

    def _loud_ceiling(self) -> float:
        """Where loud_boost rounds the peaks to: the ceiling of the limiter after it."""
        return LOUD_SEND if self.limiter_on else LOUD_SAFE

    def _send_bus(self, out: str, mix: np.ndarray, m: np.ndarray | None,
                  add_mic: bool = True, silent: bool = False,
                  sounds_vol: float = 1.0, shape: bool = True) -> np.ndarray:
        """The sounds bus shaped for voice chat (EQ, destination mode, ducking under
        your voice, phase-aware mono), with the mic block `m` added on top (unless not
        `add_mic`: the mic effect's add mode, where Windows keeps the mic itself).
        `silent`: the bus is known to be zeros (_bus_idle), so there's nothing to shape.
        `sounds_vol` over 100 %: the shaped bus has its peaks rounded (loud_boost).
        Not `shape`: the sounds aren't sent (only your voice goes out), so they keep
        the EQ alone, as your own playback does."""
        mic_on = m is not None and self.mic_enabled and not self.mic_muted
        quiet = self._bus_quiet(out, mix, silent)
        if not quiet:
            mix = self._eq(out, "sounds", mix)
            if shape:
                mix = self._dest(out, mix)
        if shape and (self.duck_db < 0 or (out, "Ducker") in self._send):
            g = self._stage(out, Ducker).process(m if mic_on else None, len(mix), self.duck_db,
                                                 ramp=not silent)
            if not isinstance(g, float) and not silent:
                mix = mix * g
        # a mode that already made the bus mono (every built-in one) needs no second pass
        if shape and self.send_mono and not quiet and not (self.dest is not None
                                                           and self.dest.mono):
            mix = self._stage(out, SmartMono).process(mix)
        if sounds_vol > 1.0 and not quiet:   # last, so nothing after it rebuilds the peaks
            mix = loud_boost(mix, sounds_vol, self._loud_ceiling())
        if mic_on and add_mic and m is not None:   # (mic_on: m is not None)
            m = self._gated(out, m)
            mix += self._eq(out, "voice", self._vol(out, "mic", m, self.mic_vol))
        elif mic_on and m is not None:
            self._gated(out, m)   # (keeps the gate's level current for _direct_mic_gain)
        return mix

    def mic_only(self) -> bool:
        """"Others hear" is off, but your own voice still goes out: your mic is sent
        (Send my mic) and no voice changer is on, so only your sounds, the radio and
        programs are cut. With a changed voice, off is silence, as before."""
        if self.sending or not self.mic_enabled or self.mic_muted:
            return False
        chain = self.voice_chain
        return not (chain is not None and chain.changes_voice)

    def _direct_mic_gain(self):
        """The real mic's level, applied by the mic effect (mute, mic volume, the gate
        while a sound plays, and nothing at all while sending is off). Add mode: always
        heard. Replace mode: only when the effect fills in for a block the board was
        late with; a changed voice then stays quiet rather than let the real one out.
        Off with mic_only: your plain voice still goes."""
        d = self.direct_stream()
        if d is None:
            return
        on = self.mic_enabled and not self.mic_muted and (self.sending or self.mic_only())
        if self.direct_mode == directmic.MODE_REPLACE:
            chain = self.voice_chain
            on = on and not (chain is not None and getattr(chain, "changes_voice", True))
        d.set_mic_gain(self.mic_vol * self._gate.get("main", 1.0) if on else 0.0)

    def _vol(self, out: str, what, x: np.ndarray, v: float) -> np.ndarray:
        """x times the volume v, gliding over the block from where the last block of
        (out, what) ended. A slider moved, a mute or a switch thrown would otherwise
        step the level in one sample: a crackle while dragging, a click on mute."""
        key = (out, what)
        v = float(v)
        g0 = self._glides.get(key, v)
        self._glides[key] = v
        if g0 == v:
            return x if v == 1.0 else x * np.float32(v)
        env = np.linspace(g0, v, len(x) + 1, dtype=np.float32)[1:]
        return x * (env[:, None] if x.ndim == 2 else env)

    QUIET_S = 0.5   # this long with nothing on a sounds bus: its filters have rung out

    def _bus_quiet(self, out: str, mix: np.ndarray, silent: bool = False) -> bool:
        """True once the sounds bus of `out` has carried only zeros for QUIET_S. Its EQ,
        mode shaping and mono downmix would only be filtering silence then (~1 ms of
        every 10 ms block in a voice chat mode, with nothing playing), so they're
        skipped; their state has long decayed, and the next sound picks them up.
        `silent`: mix is known to be zeros, so there's no need to look."""
        if not silent and mix.any():
            self._quiet[out] = 0
            return False
        n = self._quiet.get(out, 0) + len(mix)
        self._quiet[out] = n
        return n > self.QUIET_S * self.rates[out]

    IDLE_FAST = True   # _bus_idle may skip the mixer (False: every block mixes, as before)

    def _bus_idle(self, out: str, frames: int) -> bool:
        """True when this block of out's sounds bus is sure to be silence that changes
        nothing: no sound live on it, no live effect or pitch at work, and its filters
        long rung out (_bus_quiet). The callback then skips the mixer, which with
        nothing playing was most of the engine's CPU. _wake_bus catches up after."""
        if not self.IDLE_FAST or self._quiet.get(out, 0) <= self.QUIET_S * self.rates[out]:
            return False
        if self.sound_fx or out in self._sfx or abs(self._sound_st()) >= 0.01:
            return False
        f = self._spitch.get(out)
        if f is not None and f.shift.running:   # still fading out
            return False
        for v in self.voices:
            if out in v.data and out not in v.done:
                return False
        self._idle_n[out] = self._idle_n.get(out, 0) + frames
        return True

    def _wake_bus(self, out: str):
        """Before the mixer runs again after idle blocks: the live pitch gets the
        silence it would have kept meanwhile, so switching it on starts as before."""
        n = self._idle_n.pop(out, 0)
        if n:
            f = self._spitch.get(out)
            if f is not None:
                f.skip_silence(n)

    GATE_S = 0.04    # how fast the mic fades out / back in around a sound

    def _gated(self, out: str, m: np.ndarray) -> np.ndarray:
        """The mic block, faded out while a sound is going out on `out` (mic_gate)."""
        g0 = self._gate.get(out, 1.0)
        if not self.mic_gate and g0 >= 1.0:
            return m
        # done on `out` is enough: a sound still held on another output (headphones
        # that stalled, a stream being reopened) kept the mic shut after it ended here
        playing = self.mic_gate and any(
            out in v.data and out not in v.done and not v.preview and not v.paused
            for v in self.voices)
        target = 0.0 if playing else 1.0
        step = len(m) / (self.GATE_S * max(self.rates.get(out, SR), 1))
        g1 = max(g0 - step, target) if target < g0 else min(g0 + step, target)
        self._gate[out] = g1
        if g0 >= 1.0 and g1 >= 1.0:
            return m
        return m * np.linspace(g0, g1, len(m), dtype=np.float32)[:, None]

    MIC_DEAD = 0.01   # a mic channel under this share of the other's power (-20 dB) is dead
    MIC_ALIVE = 0.05  # ...and alive again above this (-13 dB): no flapping in between

    def _mic_channels(self, x: np.ndarray) -> np.ndarray:
        """A two-channel mic with one live input (an audio interface's input 1, a
        headset adapter): the live channel is copied over the dead one. Otherwise
        voice chat's mono mix would halve it (-6 dB), and mic check is one-sided."""
        p = np.einsum("ij,ij->j", x, x)   # each channel's power, in one go
        a = self._mic_pow
        a[0] += (float(p[0]) - a[0]) * 0.05   # ~0.2 s at 10 ms blocks
        a[1] += (float(p[1]) - a[1]) * 0.05
        if a[0] + a[1] > 1e-6 * len(x):   # the mic hears something (about -60 dBFS)
            d = self._mic_dead
            if d is not None and a[d] > a[1 - d] * self.MIC_ALIVE:
                d = None
            if d is None:
                d = 0 if a[0] < a[1] * self.MIC_DEAD else 1 if a[1] < a[0] * self.MIC_DEAD else None
            self._mic_dead = d
        d = self._mic_dead
        if d is not None:
            x[:, d] = x[:, 1 - d]
        return x

    def _howling(self, heard) -> bool:
        """Hear what they hear on speakers: the mic picks the speakers up, and loud
        enough the loop squeals (soundboard.audio.howl). Once it does, mic_check goes off
        here, at once; the UI sees howl_stopped, unticks the switch and says why."""
        g = self._howl
        if g is None or g.rate != self.rates["mic"]:
            g = self._howl = HowlGuard(self.rates["mic"])
        if not g.feed(heard):
            return False
        g.reset()
        self.mic_check = False
        self.howl_stopped = True
        return True

    def _mic(self, indata, direct: bool = False):
        x = indata
        two = x.shape[1] >= 2
        x = np.concatenate((x, x), axis=1) if x.shape[1] == 1 else x[:, :2]   # (np.repeat's 3x)
        x = np.ascontiguousarray(x, dtype=np.float32)
        if two and np.shares_memory(x, indata):   # a copy: it's written to below
            x = x.copy()   # (it may still be a view of PortAudio's buffer)
        # a NaN / Inf from the mic (a driver's effect, or the clean mic in the ring
        # file, which anyone signed in can write) broke voice effects for the session
        # (bypassed: the real voice went out), and stuck in what's sent and in the
        # dead-channel check's averages
        if two:   # (the dead-channel fix can change the peak: measured after it)
            x = self._mic_channels(finite(x))
            pk = peak(x)
        else:
            pk = finite_peak(x)
        self.level_mic = max(pk, self.level_mic * 0.85)
        rec = self._mic_rec
        raw = x[:, 0].copy() if rec is not None and self._rec_buf is not None else None
        take = self._take   # Record a sound: one copy and one append, nothing more
        if take is not None and not self._take_fx:
            take.append(x.copy())
        heard = x[:, 0].copy() if self.mic_check else None   # the real mic, for the howl check
        chain = self.voice_chain
        if chain is not None:   # after the meter: that judges the real mic
            x = chain.process(x, self.rates["mic"])
        if self.voice_level:   # after the voice changer: it levels what's sent
            lv = self._leveler
            if lv is None or lv.rate != self.rates["mic"]:
                lv = self._leveler = VoiceLeveler(self.rates["mic"])
            x = lv.process(x)
        if raw is not None and rec is not None:   # a test: the real mic and what's sent
            rec.append(np.stack([raw, x[:, 0]], 1))
        if take is not None and self._take_fx:
            take.append(x.copy())
        if self.main_stream is not None:
            if not self.main_direct:
                self.ring_main.write(self._rs_main(x))
            elif direct:   # straight into the mic: the same stretch goes out right after
                self.fifo_direct.write(self._rs_main(x))
        fed = self.mic_check and self.mon_stream is not None
        if fed and heard is not None and self._howling(heard):
            fed = False   # the mic hears its own playback (speakers): stop feeding it
        if fed:
            self.ring_mon.write(self._rs_mon(x))
        elif self._mon_fed:   # mic check stopped: an emptied ring isn't clock drift
            self.ring_mon.clear()
            if self._howl is not None:
                self._howl.reset()
        self._mon_fed = fed
        fed = self.obs_voice and self.obs_stream is not None
        if fed:
            self.ring_obs.write(self._rs_obs(x))
        elif self._obs_fed:
            self.ring_obs.clear()
        self._obs_fed = fed

