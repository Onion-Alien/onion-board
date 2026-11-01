"""Real-time audio engine.

Three WASAPI streams, each opened at its device's *native* rate (Windows'
built-in resampler, auto_convert, audibly garbles audio — measured ~70% junk on
VB-Cable — so all rate conversion is done here with soxr instead):

  mic  (input)  -> streaming resampler -> ring buffers -> main / monitor
  radio   (48 kHz, pushed from the UI thread) -> resampler -> ring buffers -> main / monitor
  aux     (48 kHz, pushed from a capture thread: one per captured program, Apps tab)
          -> the same path again, each with its own rings, volume and switches
  main (output) = sounds + radio / programs (when live) + mic -> the send device: a virtual
                  cable or any other output you picked (what others hear)
  mon  (output) = sounds + radio / programs [+ mic in test mode] -> your headphones
  obs  (output, optional) = sounds + radio / programs (when live) [+ mic] -> a device
       OBS captures: what others get, without the voice chat shaping, as its own track

Sounds are stored at SR and resampled (cached) to each output's rate. Every
playing Voice keeps its own position per output, so the two output devices
run on independent clocks without drift or glitches.

Live speed / pitch (the ⏩ controls): sounds play at `sound_speed` by reading
their data at a fractional rate (like a tape), and a pitch shifter on the sounds
bus corrects the pitch back (`sound_keep_pitch`) and adds `sound_pitch`. The
app's own playback (test recording, cue beeps, the setup tune, previews) is
`fixed`: played at speed 1 and mixed in after the pitch shifter. The live
effects (`sound_fx`: bass, reverb, echo… soundboard.audio.livefx) come after the pitch.
Per-sound effects are baked in ahead of time instead (soundboard.audio.soundfx).
"""
from __future__ import annotations

import collections
import logging
import sys
import threading
import time
import types
import weakref
from typing import Any

import numpy as np

from soundboard.mic import destination, directmic
from soundboard.audio import livefx, mapped
from soundboard.audio.howl import HowlGuard
from soundboard.audio.eq import EQ
from soundboard.audio.sendfx import Limiter, VoiceLeveler
from soundboard.audio.enginedevices import EngineDevices
from soundboard.audio.enginetakes import EngineTakes
from soundboard.audio.soundcache import SoundCache
# moved with the cache, still imported from here elsewhere
from soundboard.audio.soundcache import CACHE_BUDGET, resample  # noqa: F401
from soundboard.audio.engineparts import (
    SR,
    CH,
    is_fixed,
    DeviceWorker,
    START_FADE_S,
    _hard_start,
    Ring,
    DirectFifo,
    StreamResampler,
    peak,
    LivePitch,
    AuxSource,
    Voice,
)
# not used here any more, still imported from here elsewhere
from soundboard.audio.engineparts import (  # noqa: F401
    STALL_S, RETRY_S, BUFFER, _holding_devices, close_quietly, FIXED_SIDS, LOOP_XF_S, AA_DB,
    soft_limit,
    _AA_CACHE,
)

# its parts; all they have is reached through this module too (engine.find_device,
# engine.CableTap, ...): see _Parts
from soundboard.audio import devicelist, enginebus, enginerender
from soundboard.audio.devicelist import *  # noqa: F403
from soundboard.audio.enginerender import *  # noqa: F403
from soundboard.audio.enginebus import *  # noqa: F403
from soundboard.audio.devicelist import CableTap
from soundboard.audio.enginebus import EngineBus
from soundboard.audio.enginerender import EngineRender

log = logging.getLogger(__name__)

SWAP_FADE_S = 0.04   # swap(): the crossfade from a playing sound to it with new effects
# a sound on disk longer than this is never copied at another device's rate: it plays
# read at that rate (Voice.step). A 2-hour song's copy took 17 s, 1.2 GB of RAM and
# held the GIL for seconds at a time (the app froze, the audio cut out)
NO_COPY_S = 20 * 60
CALM_S = 3.0      # nothing played this long, mic quiet: the effect's cushion goes
CALM_MIC = 0.02   # the clean mic's peak under this counts as quiet (no word cut)
READ_AHEAD_EVERY_S = 1.0               # how often the minutes ahead of a long sound are asked for

# --------------------------------------------------------------------------- engine

class Engine(EngineBus, EngineRender, EngineTakes, EngineDevices, SoundCache):
    def __init__(self):
        # `voices` is an immutable tuple that is *replaced* (never mutated) under
        # `lock`. The audio callbacks read the current tuple without locking, so they
        # can never block on the UI thread (which would be a priority inversion: the
        # audio thread stalls while a lower-priority thread holds the lock).
        self.lock = threading.Lock()
        self.voices: tuple[Voice, ...] = ()
        self._init_cache()
        self._ahead_lock = threading.Lock()
        self._ahead_on = False   # the read-ahead thread is running (_read_ahead)

        self.latency = "low"      # sounddevice latency: 'low' or 'high' (safer)
        self.block_s = 0.0        # every stream's block (set_block); 0: the driver's own
        keys: list[str] = ["main", "mon", "mic", "obs"]
        self.names = dict.fromkeys(keys)          # device names for reopening
        self._last_cb = dict.fromkeys(keys, 0.0)  # monotonic time of last callback
        self._last_try = dict.fromkeys(keys, 0.0)   # last (re)open attempt
        self.xruns = dict.fromkeys(keys, 0)       # drop-outs reported by PortAudio
        self.cb_errors = dict.fromkeys(keys, 0)   # exceptions inside a callback
        self._cb_err_base = dict.fromkeys(keys, 0)   # cb_errors when the stream opened
        self._cb_err_seen = dict.fromkeys(keys, 0)   # cb_errors at the last check_streams
        self.stalls = 0                                       # streams reopened by the watchdog

        # live settings (read by audio callbacks; plain attribute writes are atomic)
        self.sound_vol = 1.0      # sounds -> others
        self.mic_vol = 1.0        # mic    -> others
        self.mon_vol = 0.7        # everything -> your headphones
        self.obs_vol = 1.0        # everything -> the stream output (OBS)
        self.obs_voice = True     # your mic goes to the stream output too (when sent)
        self.mic_enabled = True   # pass your mic through to the send device
        self.sending = True       # master switch: False sends silence to others
        self.mic_muted = False
        self.monitor_sounds = True
        self.eq_gains: list[float] | None = None   # None = EQ off
        self.eq_target = "voice"                   # 'voice' | 'sounds' | 'all'
        self.dest = None                           # destination.Dest shaping the sounds bus
        self._dests: dict[str, destination.Processor] = {}
        self._eqs: dict[tuple[str, str], EQ] = {}
        self.mic_check = False    # headphones also get your mic (= exactly what others hear)
        self.mon_voice_only = False   # ...but only your (changed) voice: the Voice tab's
        self._howl: HowlGuard | None = None   # listens for a squeal while mic_check is on
        self.howl_stopped = False  # it squealed: mic_check was switched off (the UI tells)
        self.voice_chain = None   # voicefx.VoiceChain: voice changer / live speech tap on the mic
        # the send stage (soundboard.audio.sendfx): what makes the mix survive voice chat
        self.send_mono = True     # phase-aware mono into the send device (every voice chat is mono)
        self.duck_db = 0.0        # lower the sounds this much while you talk (0 = off)
        self.mic_gate = False     # mute your mic while a sound plays (only the sounds go out)
        self.voice_level = False  # keep your voice at one volume (sendfx.VoiceLeveler)
        self._leveler: VoiceLeveler | None = None   # made for the mic's rate, on first use
        self._gate: dict[str, float] = {}   # output -> the mic's current gate gain
        self.limiter_on = True    # hold the send device's peaks at sendfx.CEILING_DB
        self._send: dict[tuple[str, str], Any] = {}   # (out, kind) -> its sendfx stage
        self._quiet: dict[str, int] = {}   # out -> frames of silence on its sounds bus
        self._idle_n: dict[str, int] = {}  # out -> frames its sounds bus skipped (_bus_idle)
        self._glides: dict = {}   # (out, what) -> the volume its last block ended at (_vol)
        self.sound_speed = 1.0        # live playback speed of every sound (0.25..4)
        self.sound_pitch = 0.0        # live pitch of every sound, semitones
        self.sound_keep_pitch = True  # speed changes leave the pitch alone
        self.sound_fx: dict = {}      # live effects on every sound (livefx), {} = none
        self.sound_live: dict[str, tuple] = {}   # sid -> its own livefx.Stage (set_sound_live)
        self._spitch: dict[str, LivePitch] = {}
        self._sfx: dict = {}          # out or (out, bus) -> livefx.LiveFx
        self._fx_gen: dict[str, int] = {}   # bus -> flushes asked for (stop_all, stop_radio)
        # the same live pitch / effects on the radio and on the Apps tab's programs
        # (one setting for all of them): no speed, they're live streams
        self.radio_pitch = 0.0
        self.radio_fx: dict = {}
        self.apps_pitch = 0.0
        self.apps_fx: dict = {}
        self._lpitch: dict[tuple[str, str], LivePitch] = {}
        # a voice setup from Live controls (soundboard.mic.livesetup): its voice changer
        # live on the sounds (one chain per output), the whole setup where the radio and
        # each captured program come in (one StreamVoice each)
        self.sound_voice: dict = {}   # a VoiceChain spec, {} = none
        self._sound_voice_gen = 0
        self._svoice: dict[str, Any] = {}   # out -> (VoiceChain, gen it was set up for)
        self.radio_voice: Any = None   # livesetup.StreamVoice, or None
        self._apps_setup: tuple = (None, None, None, None)   # (setup, AI module, on_event, lang)
        self._aux_voice: dict = {}   # aux key -> livesetup.StreamVoice

        self.main_stream = self.mon_stream = self.mic_stream = self.obs_stream = None
        # "straight into my mic" (soundboard.mic.directmic): what others hear goes into the
        # real mic inside Windows. The board's mic is then the clean mic the effect hands
        # over (never its own sounds coming back), and the send mix runs on its clock.
        self.main_direct = False
        self.direct_mode = directmic.MODE_REPLACE   # the send mix replaces the mic
        self.direct_lead_s = directmic.LEAD_S
        self._cushioned = False   # the mic effect reads CUSHION_S behind (cushion)
        self._calm_since = 0.0    # since when nothing plays and the mic is quiet
        self.fifo_direct = DirectFifo()
        # ...and the cable gets the same, for a voice app still set to it (CableTap)
        self.tap: CableTap | None = None
        # Setup -> Devices -> Also play on: a copy of what others hear into each of these
        # (set_copy_devices). A new tuple each change: the audio thread reads it once.
        self.copies: tuple[CableTap, ...] = ()
        self.copy_names: tuple[str, ...] = ()
        self._copy_try: dict[str, float] = {}
        self.tap_name: str | None = None
        self._tap_try = 0.0
        # cable / copy devices already logged as failing to open: retried every RETRY_S,
        # but warned about once until they open again (a log line every 5 s, on the UI
        # thread, for hours while a cable is missing)
        self._open_warned: set[str] = set()
        self.rates = {"main": SR, "mon": SR, "mic": SR, "obs": SR}
        # the mic device's own rate: rates["mic"] is the mic effect's while its clean
        # mic feeds the board, and goes back to this when that stops
        self._mic_dev_rate = SR
        self.errors: dict[str, str] = {}
        # the watchdog's reopens run here (check_streams), and so do the window's
        # re-scans: one at a time, never on the UI thread
        self.devices = DeviceWorker()
        self._touched: list[str] = []   # keys the device thread's last reopens touched
        self._touched_lock = threading.Lock()
        self._shut = False   # shutdown() ran: the watchdog never reopens a device again

        # the mic's clock is its own device's: drift tracking switches itself on if it
        # turns out to wander from the output's (see Ring.auto_drift)
        self.ring_main = Ring(auto_drift=True)
        self.ring_mon = Ring(auto_drift=True)
        self.ring_obs = Ring(auto_drift=True)
        self._rs_main = StreamResampler(SR, SR)
        self._rs_mon = StreamResampler(SR, SR)
        self._rs_obs = StreamResampler(SR, SR)

        # internet radio (Radio tab): decoded by Qt Multimedia on the system clock,
        # which isn't the output devices' clock (up to ~1.5% apart), so these rings
        # track drift instead of glitching every few seconds. It arrives in bursty
        # chunks from the UI thread, so it gets a bigger cushion than the mic, and the
        # cushion grows when it runs dry. Its own volume and switches.
        self.radio_vol = 1.0
        self.radio_live = False       # radio -> others
        self.radio_monitor = True     # radio -> your headphones
        self.ring_rmain = Ring(prefill_s=0.1, max_s=0.6, track_drift=True, grow_to_s=0.3)
        self.ring_rmon = Ring(prefill_s=0.1, max_s=0.6, track_drift=True, grow_to_s=0.3)
        self.ring_robs = Ring(prefill_s=0.1, max_s=0.6, track_drift=True, grow_to_s=0.3)
        self._rs_rmain = StreamResampler(SR, SR)
        self._rs_rmon = StreamResampler(SR, SR)
        self._rs_robs = StreamResampler(SR, SR)
        self._radio_heard = 0.0
        self.aux: tuple[AuxSource, ...] = ()   # captured programs (Apps tab), see AuxSource

        self.level_main = 0.0
        self.level_mic = 0.0
        self.level_mon = 0.0
        self.level_obs = 0.0
        self.level_radio = 0.0
        # what the radio played lately, chunk by chunk, while the UI wants it (a dancing
        # mascot: TickControl sets a deque here and empties it each tick)
        self.radio_tap: collections.deque | None = None
        # anything playing — sounds, the radio, captured programs — wherever it goes
        # (to others or only to your headphones), without your mic: the logo's cue
        self.level_play = 0.0

        self._rec_buf: list[np.ndarray] | None = None
        self._rec_frames_left = 0
        self._rec_done: tuple[list | np.ndarray, int] | None = None   # see rec_done
        self._mic_pow = [0.0, 0.0]   # each mic channel's recent power (_mic_channels)
        self._mic_dead: int | None = None   # the mic channel found dead, if one is
        self._mon_fed = False        # the mic wrote to ring_mon last block (mic check)
        self._mon_path = (False, False, False)   # what _mon played last block (see there)
        self._mon_ramp = False       # _mon's send stage starts from silence next block
        self._obs_fed = False        # ...and to ring_obs (your voice on the stream output)
        self._mic_rec: list[np.ndarray] | None = None          # mic during a test (see _mic)
        # Record a sound: the mic's blocks while set to a list (start_mic_take); the UI
        # thread moves them to disk as they come. Separate from the test's _mic_rec
        self._take: list[np.ndarray] | None = None
        self._take_fx = False        # the take is the mic after the voice changer
        # Record a sound from what's playing: the sounds bus plus the radio, before your
        # mic is added, at the main output's rate (start_play_take)
        self._play_take: list[np.ndarray] | None = None
        self.play_take_out = "main"   # ...taken from this output ("mon": no send device)
        # a copy of every block sent to the send device while set to a list (the voice chat
        # check compares it with what Discord plays back); None = off
        self.main_tap: list[np.ndarray] | None = None

    # ----------------------------------------------------------------- direct mic
    # (called on the direct-mic stream every block: opening it is in enginedevices.py)
    def _direct_voice_delay(self) -> float:
        """Frames (at the send rate) the newest frame of the send mix is behind the newest
        clean mic, in your voice: what the resampler holds back, what waits in the fifo,
        the limiter's lookahead. (The mic effect fills in for a late block with the mic
        from the same moment; a voice changer's own delay doesn't count: the effect
        doesn't fill in with your real voice then, see _direct_mic_gain.)"""
        d = self._rs_main.held() + self.fifo_direct.count
        if self.limiter_on:
            d += self._stage("main", Limiter).la
        return d

    def direct_stream(self):
        s = self.main_stream
        return s if self.main_direct and isinstance(s, directmic.DirectMicStream) else None

    def _mic_direct(self, x: np.ndarray, rate: int):
        """A block of the clean mic, from the mic effect (its stream's thread). Guarded
        like the device mic's callback (_cb_mic): a failing block is counted and logged
        once, and the feed goes on."""
        try:
            if rate != self.rates["mic"]:
                log.info("mic rate %d -> %d (the mic effect's)", self.rates["mic"], rate)
                self.rates["mic"] = rate
                self._reconfigure_mic_resamplers()
            self._last_cb["mic"] = time.monotonic()
            self._mic(x, direct=True)
        except Exception as e:  # noqa: BLE001
            self._guard("mic", e)

    def _mic_direct_stopped(self):
        """The mic effect's clean mic stopped (its stream's thread, under its lock):
        the mic device's blocks come at the device's rate again. Left at the effect's,
        mic check, voice effects and recordings played them at the wrong pitch."""
        rate = self._mic_dev_rate
        if rate != self.rates["mic"]:
            log.info("mic rate %d -> %d (the mic's own)", self.rates["mic"], rate)
            self.rates["mic"] = rate
            self._reconfigure_mic_resamplers()

    def _reconfigure_mic_resamplers(self):
        r = self.rates
        self._rs_main = StreamResampler(r["mic"], r["main"])
        self._rs_mon = StreamResampler(r["mic"], r["mon"])
        self._rs_obs = StreamResampler(r["mic"], r["obs"])

    # ----------------------------------------------------------------- radio input
    def feed_radio(self, x: np.ndarray):
        """Push a chunk of radio audio ((n, 2) float32 at SR). Called from one thread at
        a time (the radio's decoding thread), like feed_aux."""
        lvl = peak(x)
        self.level_radio = max(lvl * self.radio_vol, self.level_radio)
        sv = self.radio_voice
        if sv is not None:
            x = sv.process(x, SR)
        tap = self.radio_tap
        if tap is not None:
            tap.append(np.array(x, np.float32))   # (a copy: the decoder may reuse x)
        if lvl > 0.003:
            self._radio_heard = time.monotonic()
        if self.main_stream is not None:
            self.ring_rmain.write(self._rs_rmain(x))
        if self.mon_stream is not None:
            self.ring_rmon.write(self._rs_rmon(x))
        if self.obs_stream is not None:
            self.ring_robs.write(self._rs_robs(x))

    def radio_on_air(self) -> bool:
        """True while the radio is audibly going out to others (drives auto push-to-talk)."""
        return (self.radio_live and self.radio_vol > 0
                and time.monotonic() - self._radio_heard < 0.5)

    # ----------------------------------------------------------------- cushion
    def cushion(self, on: bool = True):
        """Straight into the mic: while something plays, the effect reads CUSHION_S
        behind the board instead of LEAD_S. The board renders on Python threads, which
        wait whenever the UI thread is in one long Qt call (a window or tab shown the
        first time, an add-on installed: 60-200 ms), and with only LEAD_S queued the
        sound skipped each time. The effect plays your plain mic while it falls back."""
        s = self.direct_stream()
        if s is None or on == self._cushioned:
            return
        self._cushioned = on
        self._calm_since = 0.0
        s.set_lead(directmic.CUSHION_S if on else self.direct_lead_s)
        log.info("mic effect lead %.0f ms", s.latency * 1000)

    def _check_cushion(self, now: float):
        """check_streams, once a second: cushion while anything plays (radio and
        captured programs too); back to LEAD_S once nothing has for CALM_S and your mic
        is quiet, so the bit the effect jumps over is silence, not a word."""
        if not self.quiet():
            self.cushion(True)
            self._calm_since = 0.0
        elif self._cushioned:
            if self.level_mic > CALM_MIC:
                self._calm_since = 0.0
            elif not self._calm_since:
                self._calm_since = now
            elif now - self._calm_since >= CALM_S:
                self.cushion(False)

    # ----------------------------------------------------------------- aux sources
    def add_aux(self, key) -> AuxSource:
        """A new pushed source (a captured program). Feed it with feed_aux from any
        one thread; remove_aux when done."""
        src = AuxSource(key, self.rates)
        with self.lock:
            self.aux = tuple(a for a in self.aux if a.key != key) + (src,)
        self._aux_setup(key)
        return src

    def remove_aux(self, key):
        with self.lock:
            self.aux = tuple(a for a in self.aux if a.key != key)
        sv = self._aux_voice.pop(key, None)
        if sv is not None:
            sv.shutdown()

    def set_sound_voice(self, spec: dict):
        """(UI thread) A voice changer spec live on every sound ({} = none)."""
        self.sound_voice = dict(spec or {})
        self._sound_voice_gen += 1

    def set_apps_setup(self, setup: dict | None, module=None, on_event=None, lang=None):
        """(UI thread) A voice setup on every captured program, now and from now on
        (`lang`: its language, livesetup.Lang). Raises RuntimeError when an AI voice's
        or a language's helper can't start."""
        self._apps_setup = (setup, module, on_event, lang)
        for a in self.aux:
            self._aux_setup(a.key)

    def apps_starting(self) -> str:
        """What a captured program waits for: "ai", "lang" (StreamVoice.starting) or ""."""
        return next((w for sv in list(self._aux_voice.values()) if (w := sv.starting)), "")

    def _aux_setup(self, key):
        setup, module, on_event, lang = self._apps_setup
        sv = self._aux_voice.get(key)
        if not setup:
            if sv is not None:
                sv.stop()
            return
        if sv is None:
            from soundboard.mic.livesetup import StreamVoice
            sv = self._aux_voice[key] = StreamVoice(on_event)
        sv.set_setup(setup, module, lang)

    def _sound_voice_fx(self, out: str, x: np.ndarray) -> np.ndarray:
        """The Live controls setup's voice changer on `out`'s sounds."""
        spec, gen = self.sound_voice, self._sound_voice_gen
        got = self._svoice.get(out)
        if got is None or got[1] != gen:
            chain = got[0] if got is not None else None
            if chain is None:
                from soundboard import voicefx
                chain = voicefx.VoiceChain()
            chain.configure(spec)
            self._svoice[out] = got = (chain, gen)
        return got[0].process(x, self.rates[out])

    def feed_aux(self, src: AuxSource, x: np.ndarray):
        """Push a chunk ((n, 2) float32 at SR) of a captured program's audio."""
        sv = self._aux_voice.get(src.key)
        if sv is not None:
            x = sv.process(x, SR)
        src.feed(x, self.main_stream is not None, self.mon_stream is not None,
                 self.obs_stream is not None)

    def aux_on_air(self) -> bool:
        """True while any captured program is audibly going out to others."""
        return any(a.on_air() for a in self.aux)

    # ----------------------------------------------------------------- playback
    def play(self, sid: str, data: np.ndarray, gain: float, loop=False, mode="restart",
             preview=False, src_rate: int = SR, start: float = 0.0,
             fade_in: float = 0.0, fade_out: float = 0.0,
             only: str | tuple[str, ...] | None = None) -> Voice | None:
        """mode: 'restart' (stop previous instance), 'overlap', 'toggle' (stop if playing),
        'solo' (stop every other sound, then restart this one).
        fade_in / fade_out (seconds): a rise from silence at the start; a fall to silence
        when it's stopped and, for a one-shot, over its last fade_out seconds.
        only: 'main' or 'mon' plays on that output alone (the voice chat check); a tuple
        of outputs plays on those ('main', 'obs': others hear it, you don't)."""
        if data.ndim == 1:   # mono (the mic check's probe): the mix is CH channels wide
            data = np.repeat(data[:, None], CH, axis=1)
        outs = self.active_outputs()
        if only is not None:
            outs &= {only} if isinstance(only, str) else set(only)
        if preview:
            # previews are for your ears only; with no headphone device open they must
            # not fall through to the send device (everyone in the call would hear them)
            outs = {"mon"} if "mon" in outs else set()
        if not outs:
            return None
        with self.lock:
            existing = [v for v in self.voices if v.sid == sid and not v.stopping]
            if mode in ("restart", "toggle", "solo"):
                for v in existing:
                    v.stopping = True
                if mode == "toggle" and existing:
                    return None
            if mode == "solo":   # other pads only: not previews, cues, TTS or checks
                for v in self.voices:
                    if (v.sid != sid and not v.preview and not v.sid.startswith("__")
                            and not is_fixed(v.sid)):
                        v.stopping = True
        rates_used = {o: self.rates[o] for o in outs}
        # this runs on the UI thread (or a hotkey's): resampling a song for a 44.1 kHz
        # device takes up to a second, so a copy that isn't ready yet is made on a
        # thread for next time and this press reads the source at the output's rate
        per_out, step = {}, {}
        for o in outs:
            d = self._cached(sid, data, rates_used[o], src_rate)
            if d is None:
                if not (mapped.is_mapped(data) and len(data) > NO_COPY_S * src_rate):
                    self._resample_soon(sid, data, rates_used[o], src_rate)
                d, step[o] = data, src_rate / rates_used[o]
            per_out[o] = d
        for d in {id(d): d for d in per_out.values()}.values():
            mapped.warm(d, int(start * len(d)))   # a long sound on disk: read it in first
        if fade_in <= 0 and (start > 0 or _hard_start(data)):
            fade_in = START_FADE_S   # starts mid-waveform: a tiny rise instead of a pop
        v = Voice(sid, per_out, gain, loop, preview=preview, rates=rates_used,
                  fade_in=max(0.0, float(fade_in)), fade_out=max(0.0, float(fade_out)),
                  fixed=is_fixed(sid), cut_share=self.cut_shares(sid, data, src_rate),
                  step=step, live=None if preview else self.sound_live.get(sid))
        if start > 0:
            v.seek(start)
            for o in v.data:     # not shared yet: apply it now, so progress() is right
                v._apply_seek(o)
        with self.lock:
            # an output closed or reopened at another rate while we resampled: its
            # data is useless, and a voice waiting on it would never finish
            live = self.active_outputs()
            for o in v.data:
                if o not in live or self.rates[o] != rates_used[o]:
                    v.done.add(o)
            if v.finished:
                return None
            self.voices = self.voices + (v,)
        if "main" in v.data:
            self.cushion(True)
        if any(mapped.is_mapped(d) for d in v.data.values()):
            self._follow()
        return v

    def _follow(self):
        """Start the read-ahead thread if it isn't running."""
        with self._ahead_lock:
            if self._ahead_on:
                return
            self._ahead_on = True
        threading.Thread(target=Engine._read_ahead, args=(weakref.ref(self),),
                         daemon=True, name="read-ahead").start()

    @staticmethod
    def _read_ahead(ref: weakref.ref):
        """While sounds on disk play, keep the next mapped.AHEAD_S of each asked for
        (play and seek warm only that much, so a long song's later minutes would
        otherwise be read by the audio thread itself: a cut-out on a slow drive).
        Holds neither the engine nor any audio between rounds."""
        asked: dict[tuple[int, int], tuple[int, int]] = {}   # (voice, data) -> frames asked for
        span = int(mapped.AHEAD_S * SR)
        while True:
            eng = ref()
            if eng is None:
                return
            with eng._ahead_lock:
                live = [v for v in eng.voices if not v.finished and not eng._shut
                        and any(mapped.is_mapped(d) for d in v.data.values())]
                if not live:
                    eng._ahead_on = False
                    return
            keys = set()
            for v in live:
                for o, d in list(v.data.items()):
                    key = (id(v), id(d))
                    if key in keys or not len(d) or not mapped.is_mapped(d):
                        continue
                    keys.add(key)
                    p = int(v.pos.get(o, 0)) % len(d)
                    lo, hi = asked.get(key, (-1, -1))
                    if not (lo <= p and hi - p > span // 2):   # behind, past half, or a seek
                        mapped.prefetch(d, p, wrap=v.loop)
                        asked[key] = (p, p + span)
            asked = {k: asked[k] for k in keys}
            eng = live = v = d = None   # (let go of them while it sleeps)
            try:
                time.sleep(READ_AHEAD_EVERY_S)
            except OSError:   # Windows' high-resolution timer can fail: a coarser wait
                threading.Event().wait(READ_AHEAD_EVERY_S)

    def stop(self, sid: str):
        with self.lock:
            for v in self.voices:
                if v.sid == sid:
                    v.stopping = True

    def swap(self, sid: str, data: np.ndarray, at=None) -> bool:
        """The sound playing as `sid` goes on with `data` (it with other effects) from
        the same share of the way through, on the same outputs, paused or not: a quick
        crossfade, not a restart. `at(frac)`: where in `data` to go on from instead,
        for how far through the old one is (a trim moved). False: it isn't playing."""
        with self.lock:
            v = self._current(sid)
            if v is None or v.preview:
                return False
            frac, paused, outs = v.progress(), v.paused, tuple(v.data)
            if at is not None:
                frac = at(frac)
            gain, loop, fade_out = v.gain, v.loop, v.fade_out
            for old in self.voices:
                if old.sid == sid and not old.stopping:
                    old.fade_out = SWAP_FADE_S   # not the sound's own (long) fade-out
        new = self.play(sid, data, gain, loop=loop, only=outs, start=min(frac, 0.999),
                        fade_in=SWAP_FADE_S, fade_out=fade_out)
        if new is None:
            return False
        with self.lock:
            new.paused = paused
        return True

    def set_sound_live(self, sid: str, stage: tuple | None, now: bool = True):
        """`sid` plays with its own live stage (livefx.Stage: Edit sound's speed, pitch,
        Live controls stages and boost, heard at once instead of baked in first), None
        for none. It's kept for its next press too. `now`: the copies playing take it
        at once (one taken off fades out: NO_STAGE); else only the next ones, so a
        render that bakes it in can swap in under the old one (Save)."""
        if stage is None:
            self.sound_live.pop(sid, None)
        else:
            self.sound_live[sid] = stage
        if not now:
            return
        with self.lock:
            for v in self.voices:
                if v.sid == sid and not v.preview and not v.stopping:
                    v.live = stage if stage is not None else (
                        livefx.NO_STAGE if v.live is not None else None)

    def stop_all(self):
        """Stop everything now: the panic button skips the sounds' own fade-outs, and
        the live echo / reverb tails fade out at once too (livefx FADE)."""
        with self.lock:
            for v in self.voices:
                v.fade_out = 0.0
                v.stopping = True
            self._flush_fx("sounds")

    def stop_radio(self):
        """The radio stopped: what's still queued for it fades out over a few ms
        instead of playing on, and so do its live effects' tails."""
        for ring in (self.ring_rmain, self.ring_rmon, self.ring_robs):
            ring.fade_out()
        self._flush_fx("radio")

    def _flush_fx(self, bus: str):
        # a count the audio thread compares (_fx): it alone touches the LiveFx
        self._fx_gen[bus] = self._fx_gen.get(bus, 0) + 1

    def _current(self, sid: str) -> Voice | None:
        cur = [v for v in self.voices if v.sid == sid and not v.stopping and not v.finished]
        return cur[-1] if cur else None

    def set_paused(self, sid: str, paused: bool):
        with self.lock:
            for v in self.voices:
                if v.sid == sid and not v.stopping:
                    v.paused = paused

    def seek(self, sid: str, frac: float) -> bool:
        with self.lock:
            v = self._current(sid)
        if v is None:
            return False
        for d in {id(d): d for d in v.data.values()}.values():
            mapped.warm(d, int(frac * len(d)))   # before the audio thread jumps there
        with self.lock:
            v.seek(frac)
        return True

    def state(self, sid: str) -> tuple[float, bool] | None:
        """(progress 0..1, paused) of the newest live voice for sid, or None."""
        with self.lock:
            v = self._current(sid)
            return (v.progress(), v.paused) if v else None

    def pause_all(self, on: bool | None = None) -> bool:
        """Pause everything playing, or resume if everything is already paused.
        on=True / False pauses / resumes everything instead of flipping. Returns whether
        anything is paused now: with nothing playing, nothing is."""
        with self.lock:
            live = [v for v in self.voices if not v.stopping and not v.finished and not v.preview]
            resume = (bool(live) and all(v.paused for v in live)) if on is None else not on
            for v in live:
                v.paused = not resume
            return bool(live) and not resume

    def set_gain(self, sid: str, gain: float):
        with self.lock:
            for v in self.voices:
                if v.sid == sid:
                    v.gain = gain

    def playing(self) -> dict[str, tuple[float, bool]]:
        """sid -> (progress 0..1, paused) of the newest voice for that sound."""
        res = {}
        self._sweep()   # the UI polls this: a finished preview's audio goes here
        with self.lock:
            self.voices = tuple(v for v in self.voices if not v.finished)
            for v in self.voices:
                if not v.stopping:
                    res[v.sid] = (v.progress(), v.paused)
        return res

    def any_playing(self) -> bool:
        """True while a sound is going out to others (drives auto push-to-talk)."""
        with self.lock:
            # a stopped sound still fading out is still being heard
            return any(not v.silent and not v.preview and not v.paused
                       and not (v.stopping and not any(v.gate.values()))
                       for v in self.voices)

    def quiet(self) -> bool:
        """Nothing is playing: no sound or sample, no captured program, no radio heard
        in the last second (when uigc's deep sweep can pause the UI thread unheard)."""
        return (not any(not v.silent for v in self.voices) and not self.aux
                and time.monotonic() - self._radio_heard > 1.0)


# ---------------------------------------------------------------------- one module

# engine was one module, and the app, the tests and the scripts still use it as one:
# what a part has is read here (engine.<name>, the private names too), and a name set
# here (a test's monkeypatch) is set in every part that has the same thing, so it
# reaches the code that uses it wherever that code now lives.
_PARTS = (devicelist, enginerender, enginebus)
_UNSET = object()


def __getattr__(name: str) -> Any:
    for part in _PARTS:
        if name in vars(part):
            return vars(part)[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class _Parts(types.ModuleType):
    def __setattr__(self, name: str, value):
        old = getattr(self, name, _UNSET)
        if old is not _UNSET:
            for part in _PARTS:
                if vars(part).get(name, _UNSET) is old:
                    setattr(part, name, value)
        if name in vars(self) or not any(name in vars(part) for part in _PARTS):
            super().__setattr__(name, value)


sys.modules[__name__].__class__ = _Parts
