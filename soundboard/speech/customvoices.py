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
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

from soundboard.sounds import library
from soundboard.online import net, netlog
from soundboard.speech import piper
from soundboard.speech.tts import TTS_RATE, SapiTTS
from soundboard.core import errors

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

   The line to say is sent on its input (or put {text_file} in the command: a
   UTF-8 text file with it), and the program writes a WAV file to {out}.
   {text} (the line itself in the command) works only for a program, never for
   a .bat / .cmd / .ps1 script or a shell: lines can come from Twitch chat.

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
    file: Path | None = None     # its .json (none for a Piper voice pack)
    picture: str = ""            # one of the app's pictures ("voice-robot") or a file here

    @property
    def id(self) -> str:
        return PREFIX + self.name

    def synth(self, text: str, rate: int = 0) -> tuple[np.ndarray, int]:
        """`text` spoken: (float32 mono, sample rate). `rate` is -10..10 like Windows'."""
        speed = 2 ** (max(-10, min(10, rate)) / 10)
        netlog.cause("voice_servers", f"Speaking with your custom voice "
                                      f"{netlog.quoted(label(self.name))}")
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
            # this PC's servers stay direct, and work with the switch off too
            with net.urlopen(req, timeout=TIMEOUT_S, feature="voice_servers") as r:
                return r.read(MAX_BYTES + 1)[:MAX_BYTES]
        except urllib.error.HTTPError as e:
            detail = e.read(300).decode("utf-8", "replace").strip()
            raise RuntimeError(f"{self.name}: the server said {e.code} {detail}".strip()) from None
        except net.FeatureOff as e:
            raise RuntimeError(f"{self.name}: {errors.plain(e)}") from None
        except (urllib.error.URLError, OSError) as e:
            why = getattr(e, "reason", e)
            raise RuntimeError(f"{self.name}: couldn't reach {self.url} ({why}). "
                               "Is the server running?") from None

    def _run(self, text: str, speed: float) -> bytes:
        if any("{text}" in a for a in self.command) and _through_a_shell(self.command):
            # the line can be anyone's in Twitch chat: in a script's or a shell's command
            # line, `x" & calc & "` runs calc (cmd.exe reads its own quoting, not
            # Windows'), and %VAR% gives away names and folders
            raise RuntimeError(f"{self.name}: {{text}} can't go to a script or a shell. "
                               "Put {text_file} in the command instead (or read the line "
                               "from the input).")
        fd, out = tempfile.mkstemp(prefix="sb-tts-", suffix=".wav")
        os.close(fd)
        fd, text_file = tempfile.mkstemp(prefix="sb-tts-", suffix=".txt")
        with os.fdopen(fd, "wb") as f:
            f.write(text.encode("utf-8"))
        try:
            subs = {"{out}": out, "{text_file}": text_file, "{voice}": self.voice,
                    "{model}": self.model, "{speed}": f"{speed:.3f}",
                    "{length_scale}": f"{1 / speed:.3f}",
                    # last: nothing in the line is read as another placeholder. A line
                    # that is a whole argument never starts like an option (!say -x)
                    "{text}": text}
            args = []
            for a in self.command:
                whole = a == "{text}"
                for k, v in subs.items():
                    a = a.replace(k, v)
                args.append(a.lstrip("-/ ") or " " if whole else a)
            try:
                # a program that goes online by the proxy variables goes through the
                # relay as a voice server (one that ignores them can't be stopped)
                r = subprocess.run(args, input=text.encode("utf-8"), capture_output=True,
                                   timeout=TIMEOUT_S, cwd=self.cwd,
                                   env=net.child_env("voice_servers"),
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except subprocess.TimeoutExpired:
                raise RuntimeError(f"{self.name}: the program took too long") from None
            except OSError as e:
                raise RuntimeError(f"{self.name}: couldn't start {self.command[0]} "
                                   f"({errors.plain(e)})") from None
            data = Path(out).read_bytes()
            if r.returncode or not data:
                err = r.stderr.decode("utf-8", "replace").strip().splitlines()
                raise RuntimeError(f"{self.name}: the program failed"
                                   + (f": {err[-1]}" if err else f" (code {r.returncode})"))
            return data
        finally:
            Path(out).unlink(missing_ok=True)
            Path(text_file).unlink(missing_ok=True)


# what runs its command line as code: Windows runs .bat / .cmd through cmd.exe, whose
# quoting isn't the one subprocess writes
_SHELLS = {"cmd", "powershell", "pwsh", "wscript", "cscript", "bash", "sh", "wsl", "mshta"}
_SCRIPTS = {".bat", ".cmd", ".ps1", ".vbs", ".vbe", ".wsf", ".sh"}


def _through_a_shell(command: list[str]) -> bool:
    """The program `command` starts reads its arguments as code (a script, a shell),
    or might (Windows looks up a bare name that could be a .bat: checked too)."""
    first = command[0] if command else ""
    found = shutil.which(first) or first
    for p in {Path(first), Path(found)}:
        name, ext = p.stem.lower(), p.suffix.lower()
        if ext in _SCRIPTS or name in _SHELLS:
            return True
    return False


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
                cwd=d, file=f, picture=str(raw.get("picture", "")).strip()))
        except (OSError, ValueError) as e:
            problems.append(f"{f.name}: {errors.plain(e)}")
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


def server_path(name: str) -> Path:
    """Where the server voice called ``name`` is saved."""
    stem = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip() or "voice"
    return folder() / f"{stem}.json"


def save_server(name: str, url: str, voice: str = "", model: str = "",
                api_key: str = "") -> Path:
    """Write a server voice's .json (the "Add a voice server" box)."""
    ensure_folder()
    raw = {"name": name, "url": url}
    raw.update({k: v for k, v in (("voice", voice), ("model", model),
                                  ("api_key", api_key)) if v})
    path = server_path(name)
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return path


def update_server(path: Path, url: str, voice: str = "", model: str = "",
                  api_key: str = "") -> None:
    """Change a server voice's .json, keeping what else is in it (its name, "language")."""
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError("not a {...} object")
    raw["url"] = url
    for k, v in (("voice", voice), ("model", model), ("api_key", api_key)):
        if v:
            raw[k] = v
        else:
            raw.pop(k, None)
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")


def picture_file(cv: CustomVoice) -> Path | None:
    """A server's own picture file (one from a link), or None when it has none or uses
    one of the app's pictures. Only a plain file name in the voices folder counts."""
    name = cv.picture
    if not name or Path(name).name != name or not Path(name).suffix:
        return None
    return (cv.cwd or folder()) / name


def set_picture(path: Path, picture: str) -> None:
    """A server's picture in its .json: an app picture's key, a file name here, or ""."""
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError("not a {...} object")
    old = str(raw.get("picture", "")).strip()
    if picture:
        raw["picture"] = picture
    else:
        raw.pop("picture", None)
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    if old and old != picture and Path(old).name == old and Path(old).suffix:
        (path.parent / old).unlink(missing_ok=True)   # its old picture from a link


def answers(url: str, timeout: float = 2.0) -> bool:
    """Something answers at a server voice's address: any HTTP answer counts (most say
    404 or 405 to a plain GET of their root). Blocks: call it off the UI thread."""
    parts = urllib.parse.urlsplit(url.replace("{text}", "").replace("{voice}", ""))
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    req = urllib.request.Request(f"{parts.scheme}://{parts.netloc}/")
    try:
        with net.urlopen(req, timeout=timeout, feature="voice_servers"):
            return True
    except urllib.error.HTTPError:
        return True
    except (urllib.error.URLError, OSError, ValueError, net.FeatureOff):
        return False


_language_voices: dict[str, str] = {}   # "piper:xx" -> its name, as label() shows it


def label(name: str) -> str:
    """How a voice (Windows, custom or a language's) reads in the UI."""
    if name.startswith(PREFIX):
        return f"{name[len(PREFIX):]} (custom)"
    if name.startswith(piper.PREFIX):
        return _language_voices.get(name, name[len(piper.PREFIX):])
    return name.replace("Microsoft ", "").replace(" Desktop", "")


def language_voices() -> dict[str, tuple[Path, str, str]]:
    """The downloaded languages' voices: {"piper:xx": (voice.onnx, language, name)},
    found in the translation folder (translation/xx/voice/), named from the voice's
    own settings file ("huayan" -> "Huayan"). Reads the disk: off the UI thread."""
    from soundboard.core import langnames
    from soundboard.speech import translation
    found = {}
    try:
        folders = sorted(d for d in translation.base_dir().iterdir() if d.is_dir())
    except OSError:
        return found
    for d in folders:
        f = d / "voice" / translation.VOICE_FILE
        try:
            cfg = json.loads(f.with_name(f.name + ".json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not f.is_file() or not isinstance(cfg, dict):
            continue
        lang = d.name
        name = str(cfg.get("dataset") or lang).replace("_", " ").title()
        found[piper.voice_id(lang)] = (f, lang, f"{name} ({langnames.name(lang, lang)})")
    return found


class VoiceSet(SapiTTS):
    """The Windows voices plus the custom ones and the languages' own voices, as one
    TTS for the Speaker: the custom ones are added to `voices` / `voice_langs` as
    `custom:<name>`, the language voices as `piper:<language>`."""

    def __init__(self):
        super().__init__()
        self.custom: dict[str, CustomVoice] = {}
        self.problems: list[str] = []
        self.languages: dict[str, tuple[Path, str, str]] = {}
        self.reader = piper.PiperReader()

    def _merge(self):
        win = [v for v in self.voices if not v.startswith((PREFIX, piper.PREFIX))]
        self.voices = win + list(self.custom) + list(self.languages)
        self.voice_langs = {k: v for k, v in self.voice_langs.items()
                            if not k.startswith((PREFIX, piper.PREFIX))}
        self.voice_langs.update({k: v.language for k, v in self.custom.items()})
        self.voice_langs.update({k: v[1] for k, v in self.languages.items()})
        if self.custom or self.languages:
            self.error = ""     # Windows speech failing doesn't stop the others

    def _load_custom(self):
        voices, problems = load()
        self.custom = {v.id: v for v in voices}
        self.problems = problems
        for p in problems:
            log.warning("custom voice: %s", p)
        try:
            self.languages = language_voices()
        except Exception:  # noqa: BLE001 - a bad add-on folder must not cost the others
            log.exception("couldn't list the language voices")
            self.languages = {}
        _language_voices.clear()
        _language_voices.update({k: v[2] for k, v in self.languages.items()})

    def voice_for(self, lang: str, prefer: str = "") -> str:
        """The voice translated lines in `lang` ("de", "zh-TW"…) are read with: that
        language's own voice, once it's downloaded. Only a language that comes without
        one (its add-on lists no "voice") falls back to a Windows voice that speaks it."""
        want = lang.lower()
        for vid, (_f, code, _n) in self.languages.items():
            if code.lower() == want:
                return vid
        base = want.split("-")[0]
        return next((vid for vid, (_f, code, _n) in self.languages.items()
                     if code.lower().split("-")[0] == base), "") \
            or super().voice_for(lang, prefer)

    def warm_language(self, voice: str) -> None:
        """Load a language's voice now (a few seconds the first time), so the first
        translated line isn't late by that much too. Blocks: call it off the UI thread."""
        if voice.startswith(piper.PREFIX):
            try:
                self.synth(".", voice)
            except RuntimeError as e:   # the line itself will say why
                log.info("couldn't load the language voice yet: %s", e)

    def close(self):
        super().close()
        self.reader.close()

    def _start(self):
        super()._start()        # a restarted Windows engine relists only its own voices
        self._merge()

    def warm_up(self) -> list[str]:
        self._load_custom()
        self.voices = list(super().warm_up())
        self._merge()
        return self.voices

    def use_listing(self, names: list[str], langs: dict[str, str]) -> list[str]:
        self._load_custom()
        self.voices = list(super().use_listing(names, langs))
        self._merge()
        return self.voices

    def refresh(self) -> list[str]:
        self._load_custom()
        self.voices = list(super().refresh())
        self._merge()
        return self.voices

    def synth(self, text: str, voice: str = "", rate: int = 0) -> tuple[np.ndarray, int]:
        if voice.startswith(piper.PREFIX):
            lv = self.languages.get(voice)
            if lv is None:   # downloaded since the list was made (this is a worker)
                self.languages.update(language_voices())
                lv = self.languages.get(voice)
            if lv is None:
                raise RuntimeError("that language's voice isn't downloaded")
            return self.reader.synth(text, lv[0], rate)
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
