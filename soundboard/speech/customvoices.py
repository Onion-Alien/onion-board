"""Custom voices: a TTS server on your PC, a TTS program, or a Piper voice pack.

They live in `%APPDATA%\\OnionBoard\\voices\\` (Voice tab → More options → Open
voices folder; `README.txt` there says the same as this):

- `<anything>.json` — one voice. With `"url"` it's a server:
  - an OpenAI-style `/v1/audio/speech` endpoint (Kokoro-FastAPI, AllTalk,
    openedai-speech, LocalAI…): POSTed `{"model", "input", "voice", "speed",
    "response_format": "wav"}`, with `"api_key"` sent as a Bearer token if given;
  - or any URL with `{text}` in it (and optionally `{voice}`), fetched with GET.
  With `"command"` it's a program: a list like `["piper.exe", "--model", "x.onnx",
  "--output_file", "{out}"]`, given the line on stdin (or as `{text}`), which
  writes a WAV to `{out}`. Optional everywhere: `"voice"`, `"model"`, `"language"`
  (like "de" or "de-DE", so *Speak in* can pick it).
- `<voice>.onnx` (+ its `<voice>.onnx.json`) — a Piper voice pack, used as is when
  `piper.exe` is in the folder (or a `piper\\` folder in it) or on PATH.

A custom voice's name in the voice list (and in the saved settings) is
`custom:<name>`. `VoiceSet` puts them next to the Windows voices behind the same
`voices` / `synth` interface the Speaker uses.
"""
from __future__ import annotations

import io
import json
import logging
import os
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

from soundboard import library
from soundboard.speech.tts import TTS_RATE, SapiTTS

log = logging.getLogger(__name__)

PREFIX = "custom:"
TIMEOUT_S = 60.0        # a big model on the CPU can take a while for one sentence
MAX_BYTES = 50_000_000  # one spoken line; anything bigger isn't speech

README = """Custom voices for Onion Board
=============================

Put voices here, then press "Reload voices" on the Voice tab (or restart the app).
They show up in the Voice list marked (custom).

1. A TTS server running on your PC - make a file like kokoro.json:

   {"name": "Kokoro", "url": "http://127.0.0.1:8880/v1/audio/speech",
    "voice": "af_bella", "model": "kokoro"}

   Any OpenAI-style /v1/audio/speech server works (Kokoro-FastAPI, AllTalk,
   openedai-speech, LocalAI...). Add "api_key": "..." if yours needs one.
   For a server that takes the text in the address, put {text} (and {voice})
   in the url instead:  "url": "http://127.0.0.1:5002/api/tts?text={text}"

2. A TTS program - a file like mytts.json:

   {"name": "My voice", "command": ["C:/tools/tts.exe", "--out", "{out}"]}

   The line to say is sent on its input (or put {text} in the command), and the
   program writes a WAV file to {out}.

3. A Piper voice pack - copy the .onnx and .onnx.json files here, and piper.exe
   (from github.com/rhasspy/piper releases) into a "piper" folder here.

Optional in any .json: "language": "de" so "Speak in" picks it for German.
Programs here run with your permissions: only add ones you trust.
"""


def folder() -> Path:
    return library.APP_DIR / "voices"


def ensure_folder() -> Path:
    d = folder()
    d.mkdir(parents=True, exist_ok=True)
    readme = d / "README.txt"
    if not readme.exists():
        readme.write_text(README, encoding="utf-8")
    return d


@dataclass
class CustomVoice:
    name: str
    url: str = ""
    command: list[str] = field(default_factory=list)
    voice: str = ""
    model: str = ""
    api_key: str = ""
    language: str = ""
    cwd: Path | None = None

    @property
    def id(self) -> str:
        return PREFIX + self.name

    def synth(self, text: str, rate: int = 0) -> tuple[np.ndarray, int]:
        """`text` spoken: (float32 mono, sample rate). `rate` is -10..10 like Windows'."""
        speed = 2 ** (max(-10, min(10, rate)) / 10)
        data = self._fetch(text, speed) if self.url else self._run(text, speed)
        return decode(data)

    def _fetch(self, text: str, speed: float) -> bytes:
        if "{text}" in self.url:
            url = (self.url.replace("{text}", urllib.parse.quote(text))
                   .replace("{voice}", urllib.parse.quote(self.voice)))
            req = urllib.request.Request(url)
        else:
            body = {"model": self.model or "tts-1", "input": text,
                    "voice": self.voice or "alloy", "response_format": "wav",
                    "speed": round(speed, 3)}
            req = urllib.request.Request(self.url, json.dumps(body).encode("utf-8"),
                                         {"Content-Type": "application/json"})
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:  # noqa: S310 - http(s) only
                return r.read(MAX_BYTES + 1)[:MAX_BYTES]
        except urllib.error.HTTPError as e:
            detail = e.read(300).decode("utf-8", "replace").strip()
            raise RuntimeError(f"{self.name}: the server said {e.code} {detail}".strip()) from None
        except (urllib.error.URLError, OSError) as e:
            why = getattr(e, "reason", e)
            raise RuntimeError(f"{self.name}: couldn't reach {self.url} ({why}). "
                               "Is the server running?") from None

    def _run(self, text: str, speed: float) -> bytes:
        fd, out = tempfile.mkstemp(prefix="sb-tts-", suffix=".wav")
        os.close(fd)
        try:
            subs = {"{out}": out, "{text}": text, "{voice}": self.voice,
                    "{model}": self.model, "{speed}": f"{speed:.3f}",
                    "{length_scale}": f"{1 / speed:.3f}"}
            args = []
            for a in self.command:
                for k, v in subs.items():
                    a = a.replace(k, v)
                args.append(a)
            try:
                r = subprocess.run(args, input=text.encode("utf-8"), capture_output=True,
                                   timeout=TIMEOUT_S, cwd=self.cwd,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except subprocess.TimeoutExpired:
                raise RuntimeError(f"{self.name}: the program took too long") from None
            except OSError as e:
                raise RuntimeError(f"{self.name}: couldn't start {self.command[0]} ({e})") from None
            data = Path(out).read_bytes()
            if r.returncode or not data:
                err = r.stderr.decode("utf-8", "replace").strip().splitlines()
                raise RuntimeError(f"{self.name}: the program failed"
                                   + (f": {err[-1]}" if err else f" (code {r.returncode})"))
            return data
        finally:
            Path(out).unlink(missing_ok=True)


def decode(data: bytes) -> tuple[np.ndarray, int]:
    """Audio file bytes (WAV, FLAC, OGG, MP3) to float32 mono."""
    if not data:
        raise RuntimeError("the voice sent back no audio")
    try:
        x, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    except (sf.LibsndfileError, RuntimeError, TypeError) as e:
        head = data[:80].decode("utf-8", "replace").strip()
        raise RuntimeError(f"the voice didn't send audio ({head or e})") from None
    return np.ascontiguousarray(x.mean(axis=1), np.float32), int(sr)


def _piper_exe(d: Path) -> str:
    for p in (d / "piper.exe", d / "piper" / "piper.exe", d / "piper"):
        if p.is_file():
            return str(p)
    return shutil.which("piper") or ""


def _lang(code) -> str:
    return str(code or "").replace("_", "-").strip()


def load(d: Path | None = None) -> tuple[list[CustomVoice], list[str]]:
    """The voices in the folder, and a line per file that couldn't be used."""
    d = d or folder()
    voices: list[CustomVoice] = []
    problems: list[str] = []
    if not d.is_dir():
        return voices, problems
    for f in sorted(d.glob("*.json")):
        if f.name.endswith(".onnx.json"):
            continue        # a Piper voice's own settings
        try:
            raw = json.loads(f.read_text(encoding="utf-8-sig"))
            if not isinstance(raw, dict):
                raise ValueError("not a {...} object")
            url, cmd = str(raw.get("url", "")).strip(), raw.get("command", [])
            if isinstance(cmd, str):
                cmd = [cmd]
            if not isinstance(cmd, list) or not all(isinstance(a, str) for a in cmd):
                raise ValueError('"command" must be a list of strings')
            if url and urllib.parse.urlsplit(url).scheme not in ("http", "https"):
                raise ValueError('"url" must start with http:// or https://')
            if not url and not cmd:
                raise ValueError('needs a "url" or a "command"')
            voices.append(CustomVoice(
                name=str(raw.get("name") or f.stem).strip(), url=url, command=cmd,
                voice=str(raw.get("voice", "")), model=str(raw.get("model", "")),
                api_key=str(raw.get("api_key", "")), language=_lang(raw.get("language")),
                cwd=d))
        except (OSError, ValueError) as e:
            problems.append(f"{f.name}: {e}")
    onnx = sorted(d.glob("*.onnx"))
    if onnx:
        exe = _piper_exe(d)
        if not exe:
            problems.append("Piper voices found, but no piper.exe (put it in a 'piper' "
                            "folder there)")
        for m in onnx if exe else ():
            lang = ""
            try:
                cfg = json.loads(Path(f"{m}.json").read_text(encoding="utf-8"))
                lang = _lang((cfg.get("language") or {}).get("code") or cfg.get("espeak", {})
                             .get("voice"))
            except (OSError, ValueError, AttributeError):
                pass
            voices.append(CustomVoice(
                name=m.stem, command=[exe, "--model", str(m), "--length_scale",
                                      "{length_scale}", "--output_file", "{out}"],
                language=lang, cwd=d))
    seen: set[str] = set()
    unique = []
    for v in voices:
        if v.name and v.name not in seen:
            seen.add(v.name)
            unique.append(v)
    return unique, problems


def save_server(name: str, url: str, voice: str = "", model: str = "",
                api_key: str = "") -> Path:
    """Write a server voice's .json (the "Add a voice server" box)."""
    d = ensure_folder()
    stem = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip() or "voice"
    raw = {"name": name, "url": url}
    raw.update({k: v for k, v in (("voice", voice), ("model", model),
                                  ("api_key", api_key)) if v})
    path = d / f"{stem}.json"
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return path


def label(name: str) -> str:
    """How a voice (Windows or custom) reads in the UI."""
    if name.startswith(PREFIX):
        return f"{name[len(PREFIX):]} (custom)"
    return name.replace("Microsoft ", "").replace(" Desktop", "")


class VoiceSet(SapiTTS):
    """The Windows voices plus the custom ones, as one TTS for the Speaker: the
    custom ones are added to `voices` / `voice_langs` as `custom:<name>`."""

    def __init__(self):
        super().__init__()
        self.custom: dict[str, CustomVoice] = {}
        self.problems: list[str] = []

    def _merge(self):
        win = [v for v in self.voices if not v.startswith(PREFIX)]
        self.voices = win + list(self.custom)
        self.voice_langs = {k: v for k, v in self.voice_langs.items()
                            if not k.startswith(PREFIX)}
        self.voice_langs.update({k: v.language for k, v in self.custom.items()})
        if self.custom:
            self.error = ""     # Windows speech failing doesn't stop the custom voices

    def _load_custom(self):
        voices, problems = load()
        self.custom = {v.id: v for v in voices}
        self.problems = problems
        for p in problems:
            log.warning("custom voice: %s", p)

    def _start(self):
        super()._start()        # a restarted Windows engine relists only its own voices
        self._merge()

    def warm_up(self) -> list[str]:
        self._load_custom()
        self.voices = list(super().warm_up())
        self._merge()
        return self.voices

    def refresh(self) -> list[str]:
        self._load_custom()
        self.voices = list(super().refresh())
        self._merge()
        return self.voices

    def synth(self, text: str, voice: str = "", rate: int = 0) -> tuple[np.ndarray, int]:
        if not voice.startswith(PREFIX):
            return super().synth(text, voice, rate)
        cv = self.custom.get(voice)
        if cv is None:
            raise RuntimeError(f"the custom voice {voice[len(PREFIX):]} isn't in the "
                               "voices folder any more")
        text = " ".join(text.split())
        if not text:
            return np.zeros(0, np.float32), TTS_RATE
        return cv.synth(text, rate)
