"""AI voices: your mic turned into a character voice by the ai-voices add-on.

    mic ─ VoiceChain ─ VoiceSource.process ─ talk gate ─ ServiceHost.feed ──(16 kHz)──> helper
                         ^                                                               │
                         └── ring <─ reader thread: soxr 24 kHz -> mic rate <──(b"B")───┘

`VoiceSource.process()` runs on the audio thread: no locks, no I/O. It hands your
mic to the helper only while you talk (a level gate with 200 ms of pre-roll, so
the first sounds aren't clipped), and plays what comes back after a 20 ms jitter
buffer. While you're quiet nothing is sent, the helper sleeps and the output is
silence.

If the helper falls behind, the last 5 ms fade out; if nothing comes back for
300 ms while you talk (it crashed or hung), the backup takes over with a 10 ms
crossfade: a built-in voice preset by default, so your real voice still isn't
heard. "mic" (your own voice) and "mute" are the other backups.
"""
from __future__ import annotations

import logging
import math
from collections import deque
from collections.abc import Callable

import numpy as np

from soundboard import library, net
from soundboard.modules import ModuleInfo
from soundboard.speech import resample
from soundboard.speech.service import ServiceHost

log = logging.getLogger(__name__)

MODULE_ID = "ai-voices"
VOICE_RATE = 24000          # what the helper sends back
JITTER_S = 0.02             # buffered before playing (one helper chunk)
MAX_BUFFER_S = 0.06         # more than this queued: drop the oldest down to TRIM_TO_S
TRIM_TO_S = 0.03            # (the pre-roll comes back in one go when you start talking:
                            # that's the quiet before your first word, and keeping it
                            # would leave you that much further behind for good)
STARVE_S = 0.3              # nothing back for this long while talking: use the backup
FADE_S = 0.005              # fade-out when the buffer runs dry
XFADE_S = 0.01              # crossfade to and from the backup
PREROLL_S = 0.2
HANG_S = 0.3
BACKUP_PRESET = "Masked caller"     # hides your voice if the AI voice stops
BACKUPS = ("voice", "mic", "mute")
LATENCY_S = 0.075           # typical: 20 ms chunks + ~32 ms model look-ahead + buffer


def clean_settings(raw) -> dict:
    """Saved AI voice settings (the speech settings' "ai"), each field of the right
    type and range or its default, so the card always opens."""
    raw = raw if isinstance(raw, dict) else {}
    out = {"voice": "", "auto_pitch": True, "pitch": 0.0, "backup": "voice"}
    if isinstance(raw.get("voice"), str):
        out["voice"] = raw["voice"]
    if isinstance(raw.get("auto_pitch"), bool):
        out["auto_pitch"] = raw["auto_pitch"]
    p = raw.get("pitch")
    if isinstance(p, (int, float)) and not isinstance(p, bool) and math.isfinite(p):
        out["pitch"] = round(min(max(float(p), -12.0), 12.0) * 2) / 2
    if raw.get("backup") in BACKUPS:
        out["backup"] = raw["backup"]
    return out


class TalkGate:
    """Talking or not, from the block level against a slowly tracked noise floor
    (the live-voice helper's Segmenter idea, per block, cheap enough for the audio
    thread)."""

    def __init__(self, hang_s: float = HANG_S, min_level: float = 0.008):
        self.hang_s, self.min_level = hang_s, min_level
        self.floor = 0.0
        self.open = False
        self.quiet_s = 0.0

    def update(self, m: np.ndarray, rate: int) -> bool:
        rms = float(np.sqrt(np.mean(m * m))) if len(m) else 0.0
        th = max(self.min_level, self.floor * 3.0)
        if not self.open:
            a = 0.2 if rms < self.floor else 0.01     # falls fast, rises slowly
            self.floor += (rms - self.floor) * a
            if rms > th:
                self.open, self.quiet_s = True, 0.0
        elif rms > th * 0.7:
            self.quiet_s = 0.0
        else:
            self.quiet_s += len(m) / rate
            if self.quiet_s >= self.hang_s:
                self.open = False
        return self.open


class VoiceSource:
    """The converted voice, for `VoiceChain.source`. `feed` is where the mic goes
    (ServiceHost.feed); `send_quiet` tells the helper you stopped talking."""

    def __init__(self, feed: Callable[[np.ndarray, int], None],
                 send_quiet: Callable[[], None] | None = None, backup: str = "voice"):
        self.feed = feed
        self.send_quiet = send_quiet
        self.backup = backup if backup in BACKUPS else "voice"
        self.gate = TalkGate()
        self.rate = 0                         # the mic's, written by the audio thread
        self.ready = False                    # the helper said "ready"
        self.dead = False                     # the helper is gone: backup only
        self._pre: deque[np.ndarray] = deque()
        self._pre_s = 0.0
        self._ring: deque[np.ndarray] = deque()
        self._ring_n = 0                      # samples queued (approximate across threads)
        self._head = np.zeros(0, np.float32)  # the part of a block already started
        self._playing = False
        self._starved_s = 0.0
        self._last = 0.0                      # last sample played (for the fade-out)
        self._mix = 0.0                       # 0 = AI voice, 1 = backup (crossfade)
        self._rs = None
        self._rs_rate = 0
        self._backup_fx: list = []
        self._backup_rate = 0
        self._was_talking = False
        self.underruns = 0
        self.dropped = 0

    # ------------------------------------------------------------ reader thread
    def push(self, pcm: bytes):
        """Converted audio from the helper (int16, 24 kHz)."""
        rate = self.rate
        if not rate:
            return
        y = np.frombuffer(pcm, "<i2").astype(np.float32) / 32768.0
        if rate != self._rs_rate:
            self._rs = resample.make(VOICE_RATE, rate)    # steady, not in soxr's lumps
            self._rs_rate = rate
        if rate != VOICE_RATE:
            y = self._rs.resample_chunk(y)
        if len(y):
            self._ring.append(y)
            self._ring_n += len(y)

    # ------------------------------------------------------------ audio thread
    def process(self, m: np.ndarray, rate: int) -> np.ndarray:
        """Mono mic block -> mono voice block of the same length."""
        self.rate = rate
        n = len(m)
        dt = n / rate
        talking = self.gate.update(m, rate)
        if self.ready and not self.dead:
            self._send(m, rate, talking)
        if not self.ready or self.dead:
            return self._backup(m, rate)
        # keep the delay short: a burst that piled up is dropped, oldest first
        have = self._ring_n + len(self._head)
        if have > MAX_BUFFER_S * rate:
            self._drop(have - int(TRIM_TO_S * rate))
        if not self._playing and self._ring_n + len(self._head) >= JITTER_S * rate:
            self._playing = True
        y = self._take(n) if self._playing else None
        if y is not None:
            self._starved_s = 0.0
            out = y
        else:
            if self._playing:                 # ran dry: fade, then buffer again
                if talking:                   # (after you stop, that's just the end)
                    self.underruns += 1
                self._playing = False
            if talking:
                self._starved_s += dt
            else:
                self._starved_s = 0.0
            out = self._fade_tail(n, rate)
        # the backup takes over while the helper has been silent too long
        want = 1.0 if self._starved_s >= STARVE_S else 0.0
        if want or self._mix:
            out = self._crossfade(out, m, rate, want)
        if len(out):
            self._last = float(out[-1])
        return out

    def _send(self, m: np.ndarray, rate: int, talking: bool):
        if talking:
            if self._pre:                     # what came just before you started
                for b in self._pre:
                    self.feed(b, rate)
                self._pre.clear()
                self._pre_s = 0.0
            self.feed(m, rate)
            self._was_talking = True
            return
        if self._was_talking:
            self._was_talking = False
            if self.send_quiet is not None:
                self.send_quiet()
        self._pre.append(m.copy())
        self._pre_s += len(m) / rate
        while self._pre_s > PREROLL_S and len(self._pre) > 1:
            self._pre_s -= len(self._pre.popleft()) / rate

    def _drop(self, k: int):
        """Throw away the oldest `k` queued samples."""
        self.dropped += k
        h = min(k, len(self._head))
        self._head = self._head[h:]
        k -= h
        while k > 0 and self._ring:
            b = self._ring.popleft()
            self._ring_n -= len(b)
            if len(b) > k:
                self._head = b[k:]
                k = 0
            else:
                k -= len(b)

    def _take(self, n: int) -> np.ndarray | None:
        have = len(self._head) + self._ring_n
        if have < n:
            return None
        parts = [self._head]
        got = len(self._head)
        while got < n:
            b = self._ring.popleft()
            self._ring_n -= len(b)
            parts.append(b)
            got += len(b)
        buf = np.concatenate(parts)
        self._head = buf[n:]
        return buf[:n]

    def _fade_tail(self, n: int, rate: int) -> np.ndarray:
        out = np.zeros(n, np.float32)
        k = min(n, max(1, int(FADE_S * rate)))
        if self._last:
            out[:k] = self._last * np.linspace(1.0, 0.0, k, endpoint=False, dtype=np.float32)
            self._last = 0.0
        return out

    def _crossfade(self, out: np.ndarray, m: np.ndarray, rate: int, want: float) -> np.ndarray:
        b = self._backup(m, rate)
        step = len(m) / (XFADE_S * rate)
        m0 = self._mix
        m1 = min(want, m0 + step) if want > m0 else max(want, m0 - step)
        self._mix = m1
        g = np.linspace(m0, m1, len(m), dtype=np.float32)
        return out * (1.0 - g) + b * g

    def _backup(self, m: np.ndarray, rate: int) -> np.ndarray:
        if self.backup == "mic":
            return m
        if self.backup == "mute":
            return np.zeros_like(m)
        if rate != self._backup_rate:
            self._backup_fx = backup_effects(rate)
            self._backup_rate = rate
        y = m
        for e in self._backup_fx:
            try:
                z = e.run(y, rate)
                if z.shape == y.shape and np.all(np.isfinite(z)):
                    y = z.astype(np.float32, copy=False)
            except Exception:  # noqa: BLE001 - the backup must never stop the mic
                pass
        return y

    def latency(self) -> float:
        return LATENCY_S


def backup_effects(rate: int) -> list:
    """The built-in preset that stands in when the AI voice can't."""
    from soundboard import voicefx
    out = []
    for etype, cfg in voicefx.PRESETS.get(BACKUP_PRESET, {}).items():
        cls = voicefx.REGISTRY.get(etype)
        if cls is not None:
            try:
                out.append(cls(rate, {**voicefx.defaults(etype), **cfg}))
            except Exception:  # noqa: BLE001
                log.warning("backup voice effect %r couldn't start", etype, exc_info=True)
    return out


class AiVoiceController:
    """Starts and stops the helper and plugs its voice into the chain. `on_event`
    gets the helper's events (from background threads) plus {"type": "stopped"}."""

    def __init__(self, chain, on_event: Callable[[dict], None]):
        self.chain = chain
        self.on_event = on_event
        self.host: ServiceHost | None = None
        self.source: VoiceSource | None = None
        self.backup = "voice"

    @property
    def running(self) -> bool:
        return self.host is not None

    def start(self, module: ModuleInfo, voice: str, auto_pitch: bool = True,
              pitch: float = 0.0, args: list[str] = ()):
        self.stop()
        argv = ["--voice", voice, "--pitch", f"{float(pitch):g}"]
        if not auto_pitch:
            argv.append("--no-auto-pitch")
        holder: list[ServiceHost] = []
        host = ServiceHost(module.resolved_command(argv + list(args)),
                           lambda ev: self._event(ev, holder[0] if holder else None),
                           cwd=module.path,
                           log_path=library.APP_DIR / f"module-{module.id}.log",
                           name=module.id, env=net.child_env("voices"),
                           on_audio=lambda pcm: self._audio(pcm, holder[0] if holder else None),
                           make_resampler=resample.make)
        holder.append(host)
        src = VoiceSource(host.feed, lambda: host.feed_json({"type": "quiet"}), self.backup)
        self.host, self.source = host, src
        try:
            host.start()
        except RuntimeError:
            self.host = self.source = None
            raise
        # on straight away: until the voice is ready the backup covers your mic
        self.chain.source = src

    def set_voice(self, voice: str, pitch: float = 0.0):
        if self.host is not None:
            self.host.send_json({"type": "config", "voice": voice, "pitch": float(pitch)},
                                wait=0.25)

    def set_auto_pitch(self, on: bool):
        if self.host is not None:
            self.host.send_json({"type": "config", "auto_pitch": bool(on)}, wait=0.25)

    def set_backup(self, backup: str):
        self.backup = backup if backup in BACKUPS else "voice"
        if self.source is not None:
            self.source.backup = self.backup

    def stop(self):
        h, self.host = self.host, None
        self.source = None
        self.chain.source = None
        if h is not None:
            h.stop()

    def _audio(self, pcm: bytes, host):
        src = self.source
        if host is self.host and src is not None:
            src.push(pcm)

    def _event(self, ev: dict, host):
        if host is None or host is not self.host:
            return              # one we already stopped, still saying goodbye
        t = ev.get("type")
        src = self.source
        if t == "ready" and src is not None:
            src.ready = True
        elif t in ("stopped", "error") and src is not None and (t == "stopped" or not src.ready):
            # it died or couldn't load: the backup voice keeps covering your mic until
            # you press Stop (falling back to your real voice would give it away)
            src.dead = True
            if t == "error":
                self.on_event(ev)
                host.stop()
                self.on_event({"type": "stopped", "text": str(ev.get("text", ""))})
                return
        self.on_event(ev)

    def shutdown(self):
        self.stop()
