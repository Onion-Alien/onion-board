"""Glue for text-to-speech and live voice-to-speech (no Qt here; the panel adds that).

    typed text ─────────────────────────────┐
    mic ─ VoiceChain.tap ─ ServiceHost ─ "final" text ─┴─ Speaker ─ VoiceSet ─ Engine.play

When live voice translates (a translation add-on), its lines come back already in
that language and are spoken with `live_voice`, a voice that speaks it.

Spoken lines are played like a sound (sid "tts"), so they go to the cable, your
headphones and auto push-to-talk exactly as a pad would. While live voice is on,
the chain can also mute your real voice (`replace`), so others only hear the TTS.
"""
from __future__ import annotations

import logging
import math
from collections.abc import Callable

import numpy as np

from soundboard import library
from soundboard.modules import ModuleInfo
from soundboard.speech.customvoices import VoiceSet
from soundboard.speech.service import ServiceHost
from soundboard.speech.tts import Speaker
from soundboard.voicefx import VoiceChain

log = logging.getLogger(__name__)

TTS_SID = "tts"
NO_OUTPUT = "No audio device is open — pick one in Setup"
MAX_GAIN = 4.0          # the voice volume box goes to 400 %


def clean_settings(raw) -> dict:
    """Saved speech settings (config or an imported backup) with every known field
    of the wrong type dropped, so the panel falls back to its default for it instead
    of failing to open. Numbers are brought into range; unknown keys are kept."""
    out = dict(raw) if isinstance(raw, dict) else {}
    for k in ("voice", "model", "language", "translate"):
        if k in out and not isinstance(out[k], str):
            del out[k]
    if "mute_real_voice" in out and not isinstance(out["mute_real_voice"], bool):
        del out["mute_real_voice"]
    for k, lo, hi in (("rate", -10, 10), ("gain", 0.0, MAX_GAIN)):
        if k not in out:
            continue
        v = out[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            del out[k]
        else:
            out[k] = min(max(round(v) if k == "rate" else float(v), lo), hi)
    return out


class SpeechController:
    def __init__(self, engine, chain: VoiceChain, on_event: Callable[[dict], None]):
        """`on_event(dict)` gets every module event plus {"type": "tts_error"} —
        from background threads, so the UI must hop to its own thread."""
        self.engine, self.chain, self.on_event = engine, chain, on_event
        self.tts = VoiceSet()     # Windows voices + custom ones
        self.gain = 1.0
        self.speaker = Speaker(self.tts, self._play,
                               lambda m: self.on_event({"type": "tts_error", "text": m}))
        self.host: ServiceHost | None = None
        self.mute_real_voice = True
        self.live_voice: str | None = None   # voice for live lines (None: the chosen one)
        self._ready = False     # the module said "ready": an error after that isn't fatal

    # ------------------------------------------------------------ text-to-speech
    def say(self, text: str):
        self.speaker.say(text)

    def stop_speaking(self):
        self.speaker.stop()
        self.engine.stop(TTS_SID)

    def _play(self, stereo: np.ndarray, rate: int):
        # "overlap": the Speaker already spaces lines out; this never cuts one short
        if self.engine.play(TTS_SID, stereo, self.gain, mode="overlap", src_rate=rate) is None:
            # nothing open to play it on: say so rather than "speak" to nobody
            raise RuntimeError(NO_OUTPUT)

    # ------------------------------------------------------------ live voice
    @property
    def live(self) -> bool:
        return self.host is not None

    def start_live(self, module: ModuleInfo, args: list[str] = ()):
        self.stop_live()
        holder: list[ServiceHost] = []
        host = ServiceHost(module.resolved_command(list(args)),
                           lambda ev: self._event(ev, holder[0] if holder else None),
                           cwd=module.path, log_path=library.APP_DIR / f"module-{module.id}.log",
                           name=module.id)
        holder.append(host)
        self._ready = False
        self.host = host        # before start(): its first events must not look stale
        try:
            host.start()
        except RuntimeError:
            self.host = None
            raise
        self.chain.tap = host.feed
        self.chain.replace = self.mute_real_voice

    def stop_live(self):
        h, self.host = self.host, None
        self.chain.tap = None
        self.chain.replace = False
        if h is not None:
            h.stop()
            # "Stop" means stop talking: drop lines still queued from a long ramble
            self.stop_speaking()

    def set_mute_real_voice(self, on: bool):
        self.mute_real_voice = on
        if self.live:
            self.chain.replace = on

    def _event(self, ev: dict, host: ServiceHost | None):
        if host is None or host is not self.host:
            return          # a module we already stopped, still saying goodbye
        t = ev.get("type")
        if t == "final" and ev.get("text"):
            self.speaker.say(str(ev["text"]), self.live_voice)
        elif t == "ready":
            self._ready = True
        elif t == "stopped":
            # the module died: give the real mic back straight away
            self._detach()
        elif t == "error" and not self._ready:
            # it couldn't load (no model, no translation): it will never speak, so don't
            # leave the real mic muted behind a voice that isn't coming
            self._detach()
            self.on_event(ev)
            host.stop()         # doesn't block: safe here, on its own reader thread
            self.on_event({"type": "stopped", "text": str(ev.get("text", ""))})
            return
        self.on_event(ev)

    def _detach(self):
        self.host = None
        self.chain.tap = None
        self.chain.replace = False

    def shutdown(self):
        self.stop_live()
        self.speaker.stop()
        self.tts.close()
