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

Its language (speaking another language, the Voice tab's translation: `Lang`) works
like the Voice tab's on your mic, with the stream in place of the mic:

- on a stream, the live-voice helper hears it (VoiceChain.tap), and each translated
  line is said in the AI voice (its `dub`) or by the language's computer voice, in
  place of the stream (`replace`), a few seconds behind;
- a sound is heard whole by the same helper (`translate_sound`), and each line is
  said where it was said in it, then put in the AI voice when the setup has one.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from soundboard import library, soundfx, voicefx
from soundboard.library import SR

log = logging.getLogger(__name__)

MODELS = ("tiny.en", "base.en", "small.en", "base", "small")   # ui.livevoice.MODELS
READY_S = 600.0     # the helper's first start may download its speech model
QUIET_S = 60.0      # a sound's lines: give up after this long (+ its length) without them


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


def lang_of(setup: dict | None) -> str:
    """The setup's language (a translation add-on's code), or ""."""
    return str((setup or {}).get("language") or "")


@dataclass(frozen=True)
class Lang:
    """A setup's language, ready to run: the live-voice add-on with its arguments
    (it hears any language and translates into `code`), and the computer voice that
    says the lines ("" = the default one), from `tts` (a speech.customvoices.VoiceSet)."""
    code: str
    name: str
    module: Any
    args: tuple[str, ...]
    voice: str = ""
    tts: Any = None


def lang_args(model: str, target) -> list[str]:
    """The live-voice helper's arguments for hearing a stream or a sound (whatever
    language it's in: a multilingual model, into English) and translating it into
    `target` (a translation add-on, downloaded)."""
    from soundboard.speech import spoken, translation
    model = model if model in MODELS else "base.en"
    return ["--model", spoken.model_for(model, "auto"), "--language", "auto",
            "--task", "translate", "--translate", str(translation.model_dir(target))]


def ai_module():
    """The AI voices add-on, ready to run, or None."""
    from soundboard.speech import soundvoice
    return soundvoice.module()


class Lines:
    """The spoken lines on a stream: SpeechController plays them on this (in place of
    the Engine), and the stream's thread mixes them in (`mix`)."""

    def __init__(self):
        self._q: deque[np.ndarray] = deque()
        self._head = np.zeros(0, np.float32)
        self._lock = threading.Lock()

    def play(self, sid: str, data: np.ndarray, gain: float, mode: str = "overlap",
             src_rate: int = SR, **_kw) -> bool:
        from soundboard.engine import resample
        mono = np.asarray(data, np.float32)
        mono = mono[:, 0] if mono.ndim == 2 else mono
        mono = np.asarray(resample(mono * np.float32(gain), src_rate, SR), np.float32)
        with self._lock:
            self._q.append(mono)
        return True

    def stop(self, sid: str = ""):
        with self._lock:
            self._q.clear()
            self._head = np.zeros(0, np.float32)

    def mix(self, y: np.ndarray) -> np.ndarray:
        """`y` ((n, 2)) with the lines' next n samples added."""
        n = len(y)
        with self._lock:
            if not self._q and not len(self._head):
                return y
            out = np.zeros(n, np.float32)
            got = 0
            while got < n:
                if not len(self._head):
                    if not self._q:
                        break
                    self._head = self._q.popleft()
                k = min(n - got, len(self._head))
                out[got:got + k] = self._head[:k]
                self._head = self._head[k:]
                got += k
        return y + out[:, None]


class StreamVoice:
    """A setup on a live stream ((n, 2) float32 at library.SR, pushed from one thread).

    `set_setup(setup, module, lang)` (UI thread) switches it; `process(x)` (the stream's
    thread) gives the stream back in that voice. `on_event(dict)` hears the AI voice's
    helper ({"type": "ready" | "error" | "stopped", ...}, from its own threads) and the
    language's (the same, with "part": "language")."""

    def __init__(self, on_event: Callable[[dict], None] | None = None):
        from soundboard.speech.aivoice import AiVoiceController
        self.chain = voicefx.VoiceChain()
        self.on_event = on_event or (lambda ev: None)
        self.ai = AiVoiceController(self.chain, self._event)
        self.waiting = False        # an AI voice is starting: the stream is held back
        self.lang_waiting = False   # its translation is starting (the stream is muted)
        self.speech: Any = None     # speech.live.SpeechController, once a language is on
        self.lines = Lines()
        self._lang_key: tuple | None = None
        self._lock = threading.Lock()

    @property
    def active(self) -> bool:
        return self.chain.enabled or self.ai.running or self._lang_key is not None

    @property
    def starting(self) -> str:
        """What's getting ready: "ai" (the AI voice), "lang" (the translation) or ""."""
        return "ai" if self.waiting else "lang" if self.lang_waiting else ""

    def set_setup(self, setup: dict | None, module=None, lang: Lang | None = None):
        """Put a setup on (None: off). Its AI voice needs `module` (ai_module()), its
        language `lang`; without one the other parts go on. Raises RuntimeError when
        the AI voice's or the language's helper can't start."""
        with self._lock:
            self.chain.configure(chain_spec(setup))
            ai = ai_of(setup)
            ai_on = ai is not None and module is not None
            if not ai_on:
                self.ai.stop()
                self.waiting = False
            self._set_lang(lang if setup else None, ai_on)
            if ai is None or module is None:
                return
            self.waiting = True
            try:
                self.ai.start(module, ai["id"], pitch=float(ai.get("pitch", 0.0)))
            except RuntimeError:
                self.waiting = False
                raise

    def _set_lang(self, lang: Lang | None, ai_on: bool):
        key = (lang.code, lang.voice, lang.args, ai_on) if lang is not None else None
        if key == self._lang_key:
            return
        self._lang_key = None
        self.ai.set_dub(False)
        if self.speech is not None:
            self.speech.stop_live()
        self.lines.stop()
        self.lang_waiting = False
        if lang is None:
            return
        if self.speech is None:
            from soundboard.speech.live import SpeechController
            self.speech = SpeechController(self.lines, self.chain, self._speech_event,
                                           tts=lang.tts)
        sp = self.speech
        sp.fx_always = True            # the voice changer part is on the lines too
        sp.live_voice = lang.voice or None
        sp.dub = self.ai if ai_on else None
        self.ai.set_dub(ai_on)         # the AI voice says the lines, never the stream
        self.lang_waiting = True
        try:
            # without an AI voice the lines stand in for the stream: it's muted
            sp.start_live(lang.module, list(lang.args), replace=not ai_on)
        except RuntimeError:
            self.lang_waiting = False
            self.ai.set_dub(False)
            raise
        self._lang_key = key

    def _speech_event(self, ev: dict):
        t = ev.get("type")
        if t not in ("ready", "error", "stopped", "tts_error"):
            return    # (what it heard, its downloads: the Voice tab shows those)
        if t != "tts_error":
            self.lang_waiting = False
        if t == "stopped":
            self._lang_key = None      # (SpeechController gave the stream back)
            self.ai.set_dub(False)
        self.on_event({**ev, "part": "language"})

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
                sp = self.speech
                if sp is not None and sp.live:   # its lines go on in the computer voice
                    sp.dub = None
                    sp.set_replace(True)
        self.on_event(ev)

    def process(self, x: np.ndarray, rate: int) -> np.ndarray:
        if self.waiting:   # the helper is loading its model: nothing comes out yet
            return np.zeros_like(x)
        c = self.chain
        if not c.enabled and c.source is None and c.tap is None and not c.replace:
            return x   # (chain.active is only right once process built its effects)
        y = c.process(np.ascontiguousarray(x, dtype=np.float32), rate)
        return self.lines.mix(y) if self.speech is not None else y

    def shutdown(self):
        self.ai.shutdown()
        if self.speech is not None:
            self.speech.shutdown()


# ---------------------------------------------------------------- a sound, in a language
def hear_lines(lang: Lang, mono: np.ndarray, rate: int,
               cancel: Callable[[], bool] = lambda: False,
               progress: Callable[[float], None] | None = None) -> list[tuple[float, str]]:
    """What's said in `mono` (float32 at `rate`), translated into `lang`: (when it
    starts, in seconds; the line), by the live-voice helper. Raises RuntimeError when
    it can't, library.Cancelled once `cancel()`. Slow: off the UI thread."""
    from soundboard import net
    from soundboard.speech.service import QUEUE_BLOCKS, ServiceHost
    events: queue.Queue[dict] = queue.Queue()
    mod = lang.module
    host = ServiceHost(mod.resolved_command(list(lang.args)), events.put, cwd=mod.path,
                       log_path=library.APP_DIR / f"module-{mod.id}.log", name=mod.id,
                       env=net.child_env("voices"))
    host.start()

    def next_event(seconds: float) -> dict:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if cancel():
                raise library.Cancelled
            try:
                ev = events.get(timeout=0.05)
            except queue.Empty:
                continue
            if ev.get("type") in ("error", "stopped"):
                raise RuntimeError(str(ev.get("text") or "speech recognition stopped"))
            return ev
        raise RuntimeError("speech recognition didn't answer")
    lines: list[tuple[float, str]] = []
    try:
        while next_event(READY_S).get("type") != "ready":
            pass   # (its hello, what it's doing, its model's download)
        host.feed_json({"type": "clip", "id": 1})
        step = max(1, rate)   # a second at a time
        for i in range(0, len(mono), step):
            while host._q.qsize() > QUEUE_BLOCKS // 2:   # let the sender catch up
                if cancel():
                    raise library.Cancelled
                time.sleep(0.005)
            host.feed(np.ascontiguousarray(mono[i:i + step], np.float32), rate)
        host.feed_json({"type": "clip_end", "id": 1})
        while True:
            ev = next_event(QUIET_S + len(mono) / rate)
            t = ev.get("type")
            if t == "clip_line" and ev.get("text"):
                lines.append((max(0.0, float(ev.get("at") or 0.0)), str(ev["text"])))
            elif t == "clip_progress" and progress is not None and ev.get("total"):
                progress(min(1.0, int(ev.get("done") or 0) / int(ev["total"])))
            elif t == "clip_done":
                return lines
    finally:
        host.stop()


def translate_sound(audio: np.ndarray, lang: Lang, ai: dict | None = None,
                    cancel: Callable[[], bool] = lambda: False,
                    progress: Callable[[float], None] | None = None) -> np.ndarray:
    """A sound ((n, 2), int16 or float32 at SR) said again in `lang`: each line heard in
    it is translated and said where it was said, by the language's computer voice, then
    put in the AI voice `ai` (when given). (m, 2) float32, at least as long. A sound
    with nothing said in it comes back as it is. Raises RuntimeError or
    library.Cancelled. Slow: off the UI thread."""
    from soundboard.engine import resample
    tell = progress or (lambda f: None)
    x = np.asarray(audio)
    f = x.astype(np.float32) / 32767.0 if x.dtype == np.int16 else x.astype(np.float32)
    f = f if f.ndim == 2 else np.repeat(f[:, None], 2, axis=1)
    mono = f.mean(axis=1)
    hear_to = 0.6 if ai else 0.8      # how much of the progress each step is
    speak_to = 0.7 if ai else 1.0
    lines = hear_lines(lang, mono, SR, cancel, lambda p: tell(p * hear_to))
    if not lines:
        return f
    track = np.zeros(len(mono), np.float32)
    pos = 0
    for i, (at, text) in enumerate(lines):
        if cancel():
            raise library.Cancelled
        y, r = lang.tts.synth(text, lang.voice, 0)
        y = np.asarray(resample(np.asarray(y, np.float32), r, SR), np.float32)
        start = max(int(at * SR), pos)    # never over the line before
        end = start + len(y)
        if end > len(track):
            track = np.concatenate([track, np.zeros(end - len(track), np.float32)])
        track[start:end] += y
        pos = end
        tell(hear_to + (speak_to - hear_to) * (i + 1) / len(lines))
    if ai:
        from soundboard.speech import soundvoice
        try:
            track = soundvoice.render(track, SR, ai["id"], float(ai.get("pitch", 0.0)),
                                      cancel=cancel,
                                      progress=lambda p: tell(speak_to + (1 - speak_to) * p))
        except soundvoice.Unavailable as e:
            if cancel():
                raise library.Cancelled from None
            raise RuntimeError(str(e)) from None
    tell(1.0)
    return np.repeat(track[:, None], 2, axis=1)
