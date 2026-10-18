"""Voice setups: what the Voice tab has on (a voice changer voice, an AI voice, a
language to speak), saved under a name. One click on the Voice tab's My setups row
turns the whole mix on for your mic, and Edit sound → Effects → Voice puts it on a
sound (ui.voicepicker).

They live in %APPDATA%\\OnionBoard\\voice-setups.json, a file older versions never
open, so going back a version loses none of them:

    {"version": 1, "setups": [{"name": "Deep girl", "fx": "Deep voice",
                               "effects": {...}, "ai": {"id", "name", "pitch"},
                               "language": "zh"}]}

"fx" is the voice changer voice's name (its effects are kept too, in case it's
deleted later); "language" is a translation add-on's language code ("" = none).
"""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from pathlib import Path

from soundboard.sounds import library
from soundboard.audio import soundfx

log = logging.getLogger(__name__)

FILE_NAME = "voice-setups.json"
VERSION = 1
MAX_NAME = 32
MAX_SETUPS = 100


def path() -> Path:
    return library.APP_DIR / FILE_NAME


def clean_name(name) -> str:
    return " ".join(str(name or "").split())[:MAX_NAME].strip()


def clean_setup(raw, name: str = "") -> dict:
    """A setup as stored: {"name", "fx", "effects", "ai"?, "language"}, or {} if it has
    nothing on (no voice, no AI voice, no language)."""
    if not isinstance(raw, dict):
        return {}
    voice = soundfx.clean_voice(raw)
    lang = str(raw.get("language") or "").strip()[:16]
    if not voice and not lang:
        return {}
    out = {"name": clean_name(name or raw.get("name")),
           "fx": str(voice.get("fx") or "")[:soundfx.MAX_VOICE_NAME],
           "effects": voice.get("effects", {}), "language": lang}
    if voice.get("ai"):
        out["ai"] = voice["ai"]
    return out


def sound_voice(setup: dict) -> dict:
    """The part of a setup a sound can be said in (soundfx's voice), named after it."""
    return soundfx.clean_voice({**setup, "name": setup.get("name", "")})


def clean_list(raw) -> list[tuple[str, dict]]:
    """[(name, setup), ...]: damaged entries dropped, a name used twice keeps its first."""
    out, seen = [], set()
    for d in raw if isinstance(raw, list) else ():
        if not isinstance(d, dict):
            continue
        name = clean_name(d.get("name"))
        setup = clean_setup(d, name)
        if name and setup and name.casefold() not in seen:
            seen.add(name.casefold())
            out.append((name, setup))
    return out[:MAX_SETUPS]


class Store:
    """The saved setups, read once; every change is written straight away and told to
    `listeners` (the Voice tab's row and an open sound picker share one Store). A file
    that couldn't be read is never written over this run."""

    def __init__(self):
        self.setups: dict[str, dict] = {}
        self.writable = True
        self.listeners: list[Callable[[], None]] = []
        try:
            raw = json.loads(path().read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            log.warning("couldn't read %s; not writing it this run", path(), exc_info=True)
            self.writable = False
            return
        self.setups = dict(clean_list(raw.get("setups") if isinstance(raw, dict) else None))

    def put(self, name: str, setup: dict) -> str:
        """Save (or replace) a setup; its cleaned name, or "" if it can't be saved."""
        name = clean_name(name)
        setup = clean_setup(setup, name)
        if not name or not setup or not self.writable:
            return ""
        same = next((n for n in self.setups if n.casefold() == name.casefold()), None)
        if same is None and len(self.setups) >= MAX_SETUPS:
            return ""
        if same is not None:
            del self.setups[same]
        self.setups[name] = setup
        return name if self.save() else ""

    def rename(self, old: str, new: str) -> str:
        """Give a setup another name, in the same place in the row; the new name, or ""
        if it can't be (empty, another setup's name, not saved)."""
        new = clean_name(new)
        if old not in self.setups or not new or not self.writable:
            return ""
        if any(n.casefold() == new.casefold() and n != old for n in self.setups):
            return ""
        self.setups = {(new if n == old else n): ({**v, "name": new} if n == old else v)
                       for n, v in self.setups.items()}
        return new if self.save() else ""

    def taken(self, name: str, but: str = "") -> bool:
        """Another setup (not `but`) already has this name, whatever its case."""
        name = clean_name(name).casefold()
        return any(n.casefold() == name and n != but for n in self.setups)

    def remove(self, name: str) -> dict | None:
        """Take a setup out; it's given back so it can be put back (Undo)."""
        setup = self.setups.pop(name, None)
        if setup is not None:
            self.save()
        return setup

    def save(self) -> bool:
        data = {"version": VERSION, "setups": list(self.setups.values())}
        tmp = path().with_name(f"{FILE_NAME}.{os.getpid()}.tmp")
        try:
            path().parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(path())
        except OSError:
            log.warning("couldn't save %s", path(), exc_info=True)
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return False
        for f in list(self.listeners):
            try:
                f()
            except Exception:  # noqa: BLE001 - one listener mustn't stop the others
                log.exception("voice setups listener failed")
        return True
