"""Glue for text-to-speech and live voice-to-speech (no Qt here; the panel adds that).

    typed text ─────────────────────────────┐
    mic ─ VoiceChain.tap ─ ServiceHost ─ "final" text ─┴─ Speaker ─ SapiTTS ─ Engine.play

When live voice translates (a translation add-on), its lines come back already in
that language and are spoken with `live_voice`, a voice that speaks it.

Spoken lines are played like a sound (sid "tts"), so they go to the cable, your
headphones and auto push-to-talk exactly as a pad would. While live voice is on,
the chain can also mute your real voice (`replace`), so others only hear the TTS.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

import numpy as np

from soundboard import library
from soundboard.modules import ModuleInfo
from soundboard.speech.service import ServiceHost
from soundboard.speech.tts import SapiTTS, Speaker
from soundboard.voicefx import VoiceChain

log = logging.getLogger(__name__)

TTS_SID = "tts"


class SpeechController:
    def __init__(self, engine, chain: VoiceChain, on_event: Callable[[dict], None]):
        """`on_event(dict)` gets every module event plus {"type": "tts_error"} —
        from background threads, so the UI must hop to its own thread."""
        self.engine, self.chain, self.on_event = engine, chain, on_event
        self.tts = SapiTTS()
        self.gain = 1.0
        self.speaker = Speaker(self.tts, self._play,
                               lambda m: self.on_event({"type": "tts_error", "text": m}))
        self.host: ServiceHost | None = None
        self.mute_real_voice = True
        self.live_voice: str | None = None   # voice for live lines (None: the chosen one)

    # ------------------------------------------------------------ text-to-speech
    def say(self, text: str):
        self.speaker.say(text)

    def stop_speaking(self):
        self.speaker.stop()
        self.engine.stop(TTS_SID)

    def _play(self, stereo: np.ndarray, rate: int):
        # "overlap": the Speaker already spaces lines out; this never cuts one short
        self.engine.play(TTS_SID, stereo, self.gain, mode="overlap", src_rate=rate)

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
        if ev.get("type") == "final" and ev.get("text"):
            self.speaker.say(str(ev["text"]), self.live_voice)
        elif ev.get("type") == "stopped":
            # the module died: give the real mic back straight away
            self.host = None
            self.chain.tap = None
            self.chain.replace = False
        self.on_event(ev)

    def shutdown(self):
        self.stop_live()
        self.speaker.stop()
        self.tts.close()
