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
effects (`sound_fx`: bass, reverb, echo… soundboard.livefx) come after the pitch.
Per-sound effects are baked in ahead of time instead (soundboard.soundfx).
"""
from __future__ import annotations

import collections
import logging
import threading
import time
import weakref
from typing import Any

import numpy as np
import sounddevice as sd

from soundboard.mic import destination, directmic
from soundboard import livefx, mapped
from soundboard.howl import HowlGuard
from soundboard.dsp import hermite
from soundboard.eq import EQ
from soundboard.sendfx import (CEILING_DB, SAFETY_DB, Ducker, Limiter, SafetyLimiter, SmartMono,
                               VoiceLeveler)
from soundboard.core import errors
from soundboard.i18n import _
from soundboard.enginedevices import EngineDevices
from soundboard.enginetakes import EngineTakes
from soundboard.soundcache import SoundCache
# moved with the cache, still imported from here elsewhere
from soundboard.soundcache import CACHE_BUDGET, resample  # noqa: F401
from soundboard.engineparts import (
    SR, CH, I16_SCALE, DEVICES, start_or_close, is_fixed, DeviceWorker, loop_xf,
    loop_wrap, span, _aa_taps, START_FADE_S, _hard_start, Ring, DirectFifo,
    StreamResampler, loud_boost, peak, finite, finite_peak, limit_peak, is_xrun, _add, LivePitch,
    AuxSource, Voice,
)
# not used here any more, still imported from here elsewhere
from soundboard.engineparts import (  # noqa: F401
    STALL_S, RETRY_S, BUFFER, _holding_devices, close_quietly, FIXED_SIDS, LOOP_XF_S, AA_DB,
    soft_limit,
    _AA_CACHE,
)

log = logging.getLogger(__name__)

FADE_S = 0.010  # fade when a sound is stopped early (no clicks)
# where Sounds over 100 % round their peaks to: the limiter that follows them
LOUD_SEND = 10 ** (CEILING_DB / 20)
LOUD_SAFE = 10 ** (SAFETY_DB / 20)
# a sound on disk longer than this is never copied at another device's rate: it plays
# read at that rate (Voice.step). A 2-hour song's copy took 17 s, 1.2 GB of RAM and
# held the GIL for seconds at a time (the app froze, the audio cut out)
NO_COPY_S = 20 * 60
CALM_S = 3.0      # nothing played this long, mic quiet: the effect's cushion goes
CALM_MIC = 0.02   # the clean mic's peak under this counts as quiet (no word cut)
READ_AHEAD_EVERY_S = 1.0               # how often the minutes ahead of a long sound are asked for
# --------------------------------------------------------------------------- devices

_seen: dict = {}   # the last answers of list_devices / default_device_name


def _wasapi_index() -> int | None:
    for i, api in enumerate(sd.query_hostapis()):
        if "WASAPI" in api["name"]:
            return i
    return None


def rescan() -> bool:
    """Re-enumerate devices (picks up newly plugged ones). Kills open streams — reopen after.

    sounddevice has no public API for this; _terminate/_initialize are what its own
    tests use. If a future version drops them, the app keeps its current device list."""
    with DEVICES:
        try:
            sd._terminate()
            sd._initialize()
            return True
        except Exception:  # noqa: BLE001
            log.exception("device rescan failed")
            try:
                sd._initialize()
            except Exception:  # noqa: BLE001
                pass
            return False


def list_devices(kind: str) -> list[dict]:
    """WASAPI devices of kind 'input' or 'output' as [{index, name}]."""
    if not DEVICES.acquire(blocking=False):   # being re-scanned: the last list
        return list(_seen.get(kind, ()))
    try:
        api = _wasapi_index()
        key = "max_input_channels" if kind == "input" else "max_output_channels"
        out = []
        for i, d in enumerate(sd.query_devices()):
            if (api is None or d["hostapi"] == api) and d[key] > 0:
                out.append({"index": i, "name": d["name"]})
        _seen[kind] = out
        return out
    finally:
        DEVICES.release()


def default_device_name(kind: str) -> str | None:
    if not DEVICES.acquire(blocking=False):
        return _seen.get(("default", kind))
    try:
        api = _wasapi_index()
        if api is None:
            return None
        info = sd.query_hostapis(api)
        idx = info["default_input_device" if kind == "input" else "default_output_device"]
        name = None if idx is None or idx < 0 else sd.query_devices(idx)["name"]
        _seen[("default", kind)] = name
        return name
    finally:
        DEVICES.release()


def list_name(index: int) -> str:
    """A device's name as the device lists show it."""
    if not DEVICES.acquire(blocking=False):
        for kind in ("output", "input"):
            for d in _seen.get(kind, ()):
                if d["index"] == index:
                    return d["name"]
        raise LookupError(index)
    try:
        return sd.query_devices(index)["name"]
    finally:
        DEVICES.release()


def find_device(kind: str, name: str | None) -> int | None:
    if not name:
        return None
    devs = list_devices(kind)
    for d in devs:
        if d["name"] == name:
            return d["index"]
    squash = " ".join(name.split()).lower()   # Windows' own name may space it differently
    for d in devs:
        if " ".join(d["name"].split()).lower() == squash:
            return d["index"]
    for d in devs:  # loose match (device renamed / number changed)
        if name.lower() in d["name"].lower() or d["name"].lower() in name.lower():
            return d["index"]
    return None


# Virtual audio cables (VB-Cable, VB-Cable A/B, Hi-Fi Cable, Voicemeeter, …) show up
# as a playback device ("... Input") paired with a recording device ("... Output").
# Audio played into the first comes out of the second, which apps use as a mic.
# Not plain "virtual": real USB headsets are called e.g. "Speakers (HyperX Virtual
# Surround Sound)", and matching that hid a tester's headset from every device list.
VIRTUAL_HINTS = ("cable", "vb-audio", "voicemeeter", "virtual audio cable")


def is_virtual(name: str | None) -> bool:
    n = (name or "").lower()
    return any(k in n for k in VIRTUAL_HINTS)


def virtual_mic_for(render_name: str | None) -> str | None:
    """The recording device that carries what's played into `render_name`."""
    if not render_name or not is_virtual(render_name):
        return None
    ins = [d["name"] for d in list_devices("input")]
    for a, b in (("Input", "Output"), ("In ", "Out "), ("Input", "Out")):
        cand = render_name.replace(a, b, 1)
        if cand != render_name and cand in ins:
            return cand
    head = render_name.split("(")[0].replace("Input", "Output").strip().lower()
    for n in ins:
        if is_virtual(n) and n.lower().startswith(head):
            return n
    return None


def same_cable(a: str | None, b: str | None) -> bool:
    """Are `a` and `b` playback ends of one virtual cable? VB-Cable lists "CABLE Input"
    and "CABLE In 16ch" (both "(VB-Audio Virtual Cable)"), and both come out of the
    same "CABLE Output": the product name in brackets tells cables apart."""
    if not (a and b and is_virtual(a) and is_virtual(b)):
        return False
    if a == b:
        return True
    pa, pb = (n[n.rfind("("):].lower() if "(" in n else None for n in (a, b))
    return pa is not None and pa == pb


def virtual_outputs() -> list[str]:
    """Playback devices that are virtual cables, best (has a mic side) first."""
    outs = [d["name"] for d in list_devices("output") if is_virtual(d["name"])]
    return sorted(outs, key=lambda n: virtual_mic_for(n) is None)


class CableTap:
    """Straight into my mic, and the virtual cable too: a copy of what others hear is
    played into the cable, so a voice app still set to the cable's far end keeps
    hearing everything. The send mix is made on the mic's clock and the cable plays on
    its own, so it goes through a Ring that tracks the drift between them."""

    def __init__(self, name: str, latency: float | str = "low"):
        idx = find_device("output", name)
        if idx is None:
            raise RuntimeError(_("device not found: {device}", device=name))
        self.name = name
        self.rate = int(sd.query_devices(idx)["default_samplerate"])
        self.ring = Ring(self.rate, prefill_s=0.03, max_s=0.2, auto_drift=True)
        self._rs = StreamResampler(SR, self.rate)
        self.last_cb = time.monotonic()
        self.stream = sd.OutputStream(device=idx, samplerate=self.rate, channels=CH,
                                      dtype="float32", latency=latency, callback=self._cb)
        start_or_close(self.stream, f"cable tap {name}")

    def write(self, mix: np.ndarray):
        self.ring.write(self._rs(mix))

    def _cb(self, outdata, frames, t, status):
        self.last_cb = time.monotonic()
        x = self.ring.read(frames)
        if x is None:
            outdata.fill(0)
        else:
            outdata[:] = x

    def close(self):
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:  # noqa: BLE001 - a device that's gone
            log.debug("closing the cable tap raised", exc_info=True)


# --------------------------------------------------------------------------- engine

class Engine(EngineTakes, EngineDevices, SoundCache):
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
        # the send stage (soundboard.sendfx): what makes the mix survive voice chat
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

    def apps_waiting(self) -> bool:
        """A captured program is held back while its AI voice or language gets ready."""
        return bool(self.apps_starting())

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
                  step=step)
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
            time.sleep(READ_AHEAD_EVERY_S)

    def stop(self, sid: str):
        with self.lock:
            for v in self.voices:
                if v.sid == sid:
                    v.stopping = True

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
            # int16 library audio is scaled here (one multiply that already happens
            # for the gain); float32 is used by cues, previews of test recordings…
            g = np.float32(v.gain) * (I16_SCALE if data.dtype == np.int16 else np.float32(1))
            dest = self.dest
            if makeup and dest is not None and dest.lowcut:
                g = g * np.float32(v.makeup(dest.lowcut))
            g0 = v.gate[out]
            rate = self.rates[out]
            st = v.step.get(out, 1.0)
            vspeed = speed * st   # source frames per output frame
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
            shaped = g0 != target or near_end or glide
            if shaped:
                dst_final = dst
                dst = np.zeros((frames, CH), np.float32)
            xf = loop_xf(n, rate) if v.loop else 0
            if abs(vspeed - 1.0) < 1e-4:
                p = int(p)
                if v.loop:
                    dst += span(data, p, p + frames, True, xf) * g
                    p = loop_wrap(p + frames, n, xf)
                elif p < n:
                    take = min(frames, n - p)
                    dst[:take] += data[p:p + take] * g
                    p += take
            else:
                p = self._render_speed(dst, data, float(p), vspeed, g, v.loop, xf)
            v.pos[out] = p
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
            if p >= n and not v.loop:
                v.done.add(out)
        return buf

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

    # Each PortAudio callback is a thin guard around the real work: an exception that
    # escapes a callback makes PortAudio abort the stream for good, silently. Here it
    # is logged (once per opened stream, so the audio thread never does repeated file
    # I/O), counted, and the block is left silent. check_streams() reports the key.
    def _guard(self, key: str, exc: BaseException):
        self.cb_errors[key] += 1
        if self.cb_errors[key] - self._cb_err_base[key] == 1:
            log.error("exception in %s audio callback", key, exc_info=exc)
            self.errors[key] = f"audio callback failed: {errors.plain(exc)}"

    def _cb_main(self, outdata, frames, t, status):
        self._last_cb["main"] = time.monotonic()
        if is_xrun(status):
            self.xruns["main"] += 1
        try:
            self._main(outdata, frames)
        except Exception as e:  # noqa: BLE001
            outdata.fill(0)
            self._guard("main", e)

    def _cb_mon(self, outdata, frames, t, status):
        self._last_cb["mon"] = time.monotonic()
        if is_xrun(status):
            self.xruns["mon"] += 1
        try:
            self._mon(outdata, frames)
        except Exception as e:  # noqa: BLE001
            outdata.fill(0)
            self._guard("mon", e)

    def _cb_obs(self, outdata, frames, t, status):
        self._last_cb["obs"] = time.monotonic()
        if is_xrun(status):
            self.xruns["obs"] += 1
        try:
            self._obs(outdata, frames)
        except Exception as e:  # noqa: BLE001
            outdata.fill(0)
            self._guard("obs", e)

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
            return float(mic.latency) + float(out.latency) + 0.015   # pyright: ignore[reportArgumentType]
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
        playing = self.mic_gate and any(
            out in v.data and not v.preview and not v.paused and not v.silent
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
        enough the loop squeals (soundboard.howl). Once it does, mic_check goes off
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
