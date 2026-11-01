"""Glue for text-to-speech and live voice-to-speech (no Qt here; the panel adds that).

    typed text ─────────────────────────────┐
    mic ─ VoiceChain.tap ─ ServiceHost ─ "final" text ─┴─ Speaker ─ VoiceSet ─ Engine.play

When live voice translates (a translation add-on), its lines come back already in
that language and are spoken with `live_voice`, a voice that speaks it.

Spoken lines are played like a sound (sid "tts"), so they go to the send device, your
headphones and auto push-to-talk exactly as a pad would. While live voice is on,
the chain can also mute your real voice (`replace`), so others only hear the TTS.

With an AI voice on, translated lines go to it instead (`dub`, the AI voice
controller): the AI voice says them, and the voice changer's effects follow in
the chain as they do for your mic.
"""
from __future__ import annotations

import logging
import math
import os
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from soundboard.sounds import library
from soundboard.online import net
from soundboard.addons.modules import ModuleInfo
from soundboard.speech.customvoices import VoiceSet
from soundboard.speech.service import ServiceHost
from soundboard.speech.tts import Speaker
from soundboard import voicefx
from soundboard.voicefx import VoiceChain

if TYPE_CHECKING:
    from soundboard.speech.aivoice import AiVoiceController

log = logging.getLogger(__name__)


def speech_model_dirs() -> list[Path]:
    """The speech recognition models the live voice downloaded: faster-whisper's own
    (core.backup.SPEECH_MODELS), in the Hugging Face cache. Only those folders, never
    the rest of the cache (other programs share it)."""
    from soundboard.core.backup import SPEECH_MODELS
    hub = os.environ.get("HF_HUB_CACHE") or os.path.join(
        os.environ.get("HF_HOME") or os.path.join(Path.home(), ".cache", "huggingface"),
        "hub")
    dirs = (Path(hub) / f"models--Systran--faster-whisper-{m}" for m in SPEECH_MODELS)
    return [d for d in dirs if d.exists()]


def remove_recognition(module: ModuleInfo | None, langs: Sequence[ModuleInfo]) -> bool:
    """Take speech recognition back off this PC: the live-voice add-on's Python
    environment, its speech models and every downloaded translation. The add-on stays
    (it comes with the app), so Install speech recognition gets it all back. Returns
    whether everything went. Raises ModuleError when the environment can't be moved."""
    from soundboard.addons import modules as mods
    from soundboard.speech import translation
    if module is not None:
        mods.remove_env(module)
    for m in langs:
        translation.remove(m)
    for d in speech_model_dirs():
        shutil.rmtree(d, ignore_errors=True)
    return ((module is None or not (module.path / ".venv").exists())
            and not speech_model_dirs()
            and not any(translation.model_dir(m).exists() for m in langs))

TTS_SID = "tts"
NO_OUTPUT = "No audio device is open, pick one in Setup"
MAX_GAIN = 4.0          # the voice volume box goes to 400 %


def clean_settings(raw) -> dict:
    """Saved speech settings (config or an imported backup) with every known field
    of the wrong type dropped, so the panel falls back to its default for it instead
    of failing to open. Numbers are brought into range; unknown keys are kept."""
    out = dict(raw) if isinstance(raw, dict) else {}
    for k in ("voice", "model", "language", "spoken", "translate"):
        if k in out and not isinstance(out[k], str):
            del out[k]
    for k in ("mute_real_voice", "voice_fx", "translate_on"):
        if k in out and not isinstance(out[k], bool):
            del out[k]
    for k, lo, hi in (("rate", -10, 10), ("gain", 0.0, MAX_GAIN)):
        if k not in out:
            continue
        v = out[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            del out[k]
        else:
            out[k] = min(max(round(v) if k == "rate" else float(v), lo), hi)
    return out


def helper_env(env: dict[str, str]) -> dict[str, str]:
    """The speech helper's maths threads (CTranslate2's OpenMP) sleep as soon as a
    sentence is done instead of spinning for ~200 ms: speech comes in bursts, and the
    spinning was a third of its CPU (on a slower PC 123 -> 86 % of a core, the
    sentences ~0.05 s slower). With Use less CPU, two threads instead of one per core,
    and ONIONBOARD_LESS_CPU=1 (it translates with one guess instead of two; an older
    helper doesn't know it and carries on as before)."""
    env = {**env, "OMP_WAIT_POLICY": "PASSIVE", "KMP_BLOCKTIME": "0"}
    if voicefx.light():
        env["OMP_NUM_THREADS"] = "2"
        env["ONIONBOARD_LESS_CPU"] = "1"
    return env


# Use less CPU: the next smaller recognition model, used only when it's downloaded
# already (the helper looks; --lighter). The Languages card's "small" (any language)
# takes ~1.3 s a line on a CPU, "base" ~0.4 s but hears other languages a little worse.
LIGHTER = {"base.en": "tiny.en", "small": "base"}


def lighter_args(model: str) -> list[str]:
    """["--lighter", <smaller model>] for the helper with Use less CPU on, else []."""
    small = LIGHTER.get(model)
    return ["--lighter", small] if small and voicefx.light() else []


class SpeechController:
    def __init__(self, engine, chain: VoiceChain, on_event: Callable[[dict], None],
                 tts: VoiceSet | None = None):
        """`on_event(dict)` gets every module event plus {"type": "tts_error"} —
        from background threads, so the UI must hop to its own thread. `engine` plays
        the lines (Engine.play / stop: a stream's livesetup.Lines does too); `tts`: the
        voices of another controller to share (it keeps them open)."""
        self.engine, self.chain, self.on_event = engine, chain, on_event
        self._own_tts = tts is None
        self.tts = VoiceSet() if tts is None else tts     # Windows voices + custom ones
        self.gain = 1.0
        self.speaker = Speaker(self.tts, self._play,
                               lambda m: self.on_event({"type": "tts_error", "text": m}))
        self.host: ServiceHost | None = None
        self.mute_real_voice = True
        self.voice_fx = True    # the voice changer's effects go on the computer voice too
        self.live_voice: str | None = None   # voice for live lines (None: the chosen one)
        self.dub: AiVoiceController | None = None   # the AI voice controller saying the lines
        self.fx_always = False  # translating for the voice changer: its effect, always
        self.on_top = False     # the computer voice is on: the Effects play on its lines
        self._ready = False     # the module said "ready": an error after that isn't fatal
        self._replace = False   # live voice mutes your real voice

    # ------------------------------------------------------------ text-to-speech
    def say(self, text: str):
        self.speaker.say(text)

    def render_line(self, text: str) -> np.ndarray:
        """`text` spoken as a sound to keep: (n, 2) float32 at library.SR, in the voice
        and with the voice changer that Say uses (not an AI voice). Blocks: call it off
        the UI thread. Raises when the voice can't say it."""
        mono, rate = self.tts.synth(text, self.speaker.voice, self.speaker.rate)
        if not len(mono):
            raise RuntimeError("this voice can't read that text")
        mono = self._effects(mono, rate)
        from soundboard.audio.engine import resample
        mono = resample(np.asarray(mono, np.float32), rate, library.SR)
        return np.ascontiguousarray(np.repeat(mono[:, None], 2, axis=1), np.float32)

    def _effects(self, mono: np.ndarray, rate: int) -> np.ndarray:
        """A line through the voice changer (when it's on and goes on the computer
        voice) or else just the Effects on top of the voice (while it's on)."""
        full = (self.voice_fx or self.fx_always) and self.chain.enabled
        if not full and not self.on_top:
            return mono
        return self.chain.render(mono, rate, top_only=not full)

    def stop_speaking(self):
        self.speaker.stop()
        self.engine.stop(TTS_SID)
        if self.dub is not None:
            self.dub.clear_dub()

    def _play(self, stereo: np.ndarray, rate: int):
        dub = self.dub
        if dub is not None and dub.dub(stereo[:, 0], rate):
            return              # the AI voice says it (the chain adds the voice changer)
        mono = stereo[:, 0]
        y = self._effects(mono, rate)
        if y is not mono:   # changed: on both sides
            stereo = np.repeat(y[:, None], 2, axis=1)
        # "overlap": the Speaker already spaces lines out; this never cuts one short
        if self.engine.play(TTS_SID, stereo, self.gain, mode="overlap", src_rate=rate) is None:
            # nothing open to play it on: say so rather than "speak" to nobody
            raise RuntimeError(NO_OUTPUT)

    # ------------------------------------------------------------ live voice
    @property
    def live(self) -> bool:
        return self.host is not None

    def start_live(self, module: ModuleInfo, args: Sequence[str] = (),
                   replace: bool | None = None):
        """`replace`: mute your real voice (None: the mute_real_voice setting)."""
        self.stop_live()
        from soundboard.online import netlog
        netlog.cause("voices", f"You started live voice ({module.name}): it may fetch "
                               "its speech model")
        holder: list[ServiceHost] = []
        host = ServiceHost(module.resolved_command(list(args)),
                           lambda ev: self._event(ev, holder[0] if holder else None),
                           cwd=module.path, log_path=library.APP_DIR / f"module-{module.id}.log",
                           name=module.id,
                           # its speech model download goes through the relay as
                           # "voices"; switched off, it uses only the model it has
                           env=helper_env(net.child_env("voices")))
        holder.append(host)
        self._ready = False
        self.host = host        # before start(): its first events must not look stale
        try:
            host.start()
        except RuntimeError:
            self.host = None
            raise
        self.chain.tap = host.feed
        self._replace = self.mute_real_voice if replace is None else bool(replace)
        self.chain.replace = self._replace

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

    def set_replace(self, on: bool):
        """Mute (or give back) your real voice while live voice runs."""
        self._replace = bool(on)
        if self.live:
            self.chain.replace = self._replace

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
        self.speaker.close()
        if self._own_tts:
            self.tts.close()
