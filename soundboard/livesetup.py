"""A voice setup (soundboard.voicesetups) on what plays, from Live controls: the sounds,
the radio or the programs the Apps tab sends. Nothing here touches Qt.

A setup has up to three parts. Its voice changer voice runs live, so it's on at once.
Its AI voice has to start a helper first (a few seconds, longer the first time):

- the radio and programs are live streams, so `StreamVoice` runs the whole setup where
  the stream comes in (Engine.feed_radio / feed_aux): one chain for every output. Until
  the AI voice is ready the stream is held back (silence), then it carries on in the
  new voice;
- a sound is a file, so the UI renders it once in the AI voice (`sound_fx`, the sound's
  own effects with the AI voice put in) and plays that.

Its language (speaking another language) is the Voice tab's; Live controls leaves it
out for now.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import numpy as np

from soundboard import soundfx, voicefx

log = logging.getLogger(__name__)


def chain_spec(setup: dict | None) -> dict:
    """The setup's voice changer part, as a VoiceChain spec ({} when it has none)."""
    effects = (setup or {}).get("effects") or {}
    return {"enabled": True, "effects": effects} if effects else {}


def ai_of(setup: dict | None) -> dict | None:
    """The setup's AI voice ({"id", "name", "pitch"}), or None."""
    ai = (setup or {}).get("ai")
    return ai if isinstance(ai, dict) and ai.get("id") else None


def sound_fx(fx: dict | None, setup: dict | None) -> dict | None:
    """A sound's own effects with the setup's AI voice put in (its voice changer runs
    live on the sounds instead), or None when the setup has no AI voice."""
    ai = ai_of(setup)
    if ai is None:
        return None
    out = dict(fx or {})
    out["voice"] = soundfx.clean_voice({**(out.get("voice") or {}), "ai": ai})
    return out


def ai_module():
    """The AI voices add-on, ready to run, or None."""
    from soundboard.speech import soundvoice
    return soundvoice.module()


class StreamVoice:
    """A setup on a live stream ((n, 2) float32 at library.SR, pushed from one thread).

    `set_setup(setup, module)` (UI thread) switches it; `process(x)` (the stream's
    thread) gives the stream back in that voice. `on_event(dict)` hears the AI voice's
    helper ({"type": "ready" | "error" | "stopped", ...}, from its own threads)."""

    def __init__(self, on_event: Callable[[dict], None] | None = None):
        from soundboard.speech.aivoice import AiVoiceController
        self.chain = voicefx.VoiceChain()
        self.on_event = on_event or (lambda ev: None)
        self.ai = AiVoiceController(self.chain, self._event)
        self.waiting = False      # an AI voice is starting: the stream is held back
        self._lock = threading.Lock()

    @property
    def active(self) -> bool:
        return self.chain.enabled or self.ai.running

    def set_setup(self, setup: dict | None, module=None):
        """Put a setup on (None: off). Its AI voice needs `module` (ai_module()); without
        one only the voice changer part goes on. Raises RuntimeError when the AI voice's
        helper can't start."""
        with self._lock:
            self.chain.configure(chain_spec(setup))
            ai = ai_of(setup)
            if ai is None or module is None:
                self.ai.stop()
                self.waiting = False
                return
            self.waiting = True
            try:
                self.ai.start(module, ai["id"], pitch=float(ai.get("pitch", 0.0)))
            except RuntimeError:
                self.waiting = False
                raise

    def stop(self):
        self.set_setup(None)

    def _event(self, ev: dict):
        t = ev.get("type")
        if t == "ready":
            self.waiting = False
        elif t in ("error", "stopped"):
            self.waiting = False
            src = self.chain.source
            if src is not None and getattr(src, "dead", False):
                self.ai.stop()   # never the backup voice on a song: the plain stream
        self.on_event(ev)

    def process(self, x: np.ndarray, rate: int) -> np.ndarray:
        if self.waiting:   # the helper is loading its model: nothing comes out yet
            return np.zeros_like(x)
        if not self.chain.enabled and self.chain.source is None:
            return x   # (chain.active is only right once process built its effects)
        return self.chain.process(np.ascontiguousarray(x, dtype=np.float32), rate)

    def shutdown(self):
        self.ai.shutdown()
