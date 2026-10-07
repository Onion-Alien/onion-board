"""Discord's own voice settings, read from its files: which ones are wiping out sounds.

Discord keeps its voice settings in its web storage (a LevelDB folder under
%APPDATA%\\discord\\Local Storage\\leveldb), as JSON under the key "MediaEngineStore".
Measured on a real Discord (2026-10-07, What Is Love through Straight into my mic,
recorded from Discord's own Mic Test playback):

  Studio profile           Discord opens the mic around every Windows audio effect:
                           Straight into my mic never reaches it (nothing at all).
  Voice Isolation / Krisp  music lasts about a second, then it's wiped out.
  Echo cancellation        the level dips and pumps; 0.62 vs 0.85 on the sound match.
  Custom, all of it off    the song comes through (0.93 of the original, sounds at 100%).

With the virtual cable Studio is the clean choice (the cable has no effects to skip),
so what counts as a problem depends on the route.

read() is a raw scan for the JSON, not a LevelDB reader: Discord writes the store to
the .log file as plain text and only rewrites it into tables now and then. A store
that can't be found or parsed is None ("don't know"), never a guess. Discord writes
the store some seconds to a minute after a change, so a check can lag behind it.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# the desktop clients, each with its own settings: (folder under %APPDATA%, name)
CLIENTS = (("discord", "Discord"), ("discordptb", "Discord PTB"),
           ("discordcanary", "Discord Canary"), ("discorddevelopment", "Discord Development"))
KEY = b"MediaEngineStore"
MAX_JSON = 400_000   # the store is ~10 kB; per-user volumes can grow it

# what's wrong, in the order it matters: the first ones wipe sounds out completely
STUDIO = "studio"            # Studio profile, on the mic: Discord skips Onion Board
BYPASS = "bypass"            # "Bypass System Audio Input Processing", on the mic: same
ISOLATION = "isolation"      # Voice Isolation profile: Krisp is always on
KRISP = "krisp"              # Noise Suppression: Krisp
SUPPRESSION = "suppression"  # Noise Suppression: Standard
ECHO = "echo"                # Echo Cancellation
AGC = "agc"                  # Automatic Gain Control
ORDER = (STUDIO, BYPASS, ISOLATION, KRISP, SUPPRESSION, ECHO, AGC)
WIPES = (STUDIO, BYPASS, ISOLATION, KRISP, SUPPRESSION)   # the ones that remove sounds


@dataclass(frozen=True)
class Settings:
    client: str                # "Discord", "Discord Canary", ...
    profile: str               # "CUSTOM", "STUDIO", "VOICE_ISOLATION", "" (older Discord)
    krisp: bool
    suppression: bool
    echo: bool
    agc: bool
    bypass: bool
    input_device: str          # Windows endpoint id, or "default"
    stamp: float               # when the file it came from was written

    def problems(self, on_mic: bool) -> list[str]:
        """What in these settings changes or removes sounds, ORDER first-worst.
        `on_mic`: Straight into my mic (Studio and Bypass skip it); on the virtual
        cable they're the clean choice."""
        p = self.profile.upper()
        out = []
        if p == "STUDIO":
            return [STUDIO] if on_mic else []
        if self.bypass and on_mic:
            out.append(BYPASS)
        if p and p not in ("CUSTOM", "STUDIO"):   # Voice Isolation, or a newer preset
            out.append(ISOLATION)
            return out
        if self.krisp:
            out.append(KRISP)
        if self.suppression:
            out.append(SUPPRESSION)
        if self.echo:
            out.append(ECHO)
        if self.agc:
            out.append(AGC)
        return out


def _appdata() -> Path | None:
    a = os.environ.get("APPDATA")
    return Path(a) if a else None


def _folder(client_dir: str, appdata: Path | None = None) -> Path | None:
    base = appdata or _appdata()
    return base / client_dir / "Local Storage" / "leveldb" if base else None


def _files(folder: Path) -> list[Path]:
    """The folder's data files, newest first: .log before the tables (it holds the
    latest writes), then by LevelDB's file number."""
    try:
        files = [p for p in folder.iterdir() if p.suffix in (".log", ".ldb")]
    except OSError:
        return []

    def rank(p: Path):
        num = int(re.sub(r"\D", "", p.stem) or 0)
        return (p.suffix == ".log", num)
    return sorted(files, key=rank, reverse=True)


def _latest_store(data: bytes) -> dict | None:
    """The last MediaEngineStore JSON in one file's bytes that parses."""
    dec = json.JSONDecoder()
    pos = len(data)
    while True:
        i = data.rfind(KEY, 0, pos)
        if i < 0:
            return None
        pos = i
        j = data.find(b"{", i + len(KEY), i + len(KEY) + 64)
        if j < 0:
            continue
        try:
            obj, _ = dec.raw_decode(data[j:j + MAX_JSON].decode("utf-8", "replace"))
        except ValueError:   # cut off, or packed into a compressed table block
            continue
        if isinstance(obj, dict) and isinstance(obj.get("default"), dict):
            return obj


def parse(store: dict, client: str = "Discord", stamp: float = 0.0) -> Settings:
    d = store.get("default", {})

    def flag(k: str, default: bool) -> bool:
        v = d.get(k, default)
        return v if isinstance(v, bool) else default
    # Discord's own defaults, for a key it hasn't written yet
    return Settings(client=client, profile=str(d.get("activeInputProfile") or ""),
                    krisp=flag("noiseCancellation", True),
                    suppression=flag("noiseSuppression", False),
                    echo=flag("echoCancellation", True),
                    agc=flag("automaticGainControl", True),
                    bypass=flag("bypassSystemInputProcessing", False),
                    input_device=str(d.get("inputDeviceId") or "default"),
                    stamp=stamp)


def read_client(client_dir: str, name: str, appdata: Path | None = None) -> Settings | None:
    folder = _folder(client_dir, appdata)
    if folder is None or not folder.is_dir():
        return None
    for f in _files(folder):
        try:
            data = f.read_bytes()
            stamp = f.stat().st_mtime
        except OSError:   # Discord holds the LOCK file only; a table can vanish mid-scan
            continue
        store = _latest_store(data)
        if store is not None:
            return parse(store, name, stamp)
    return None


def read(appdata: Path | None = None) -> list[Settings]:
    """Every installed Discord client's voice settings that could be read, the most
    recently changed first."""
    out = []
    for d, name in CLIENTS:
        try:
            s = read_client(d, name, appdata)
        except Exception:  # noqa: BLE001 - never let a strange file break the board
            log.debug("reading %s's settings failed", name, exc_info=True)
            s = None
        if s is not None:
            out.append(s)
    return sorted(out, key=lambda s: -s.stamp)


def signature(appdata: Path | None = None) -> tuple:
    """Cheap: the clients' newest file sizes and times, to re-read only on change."""
    sig = []
    for d, _name in CLIENTS:
        folder = _folder(d, appdata)
        if folder is None or not folder.is_dir():
            continue
        for f in _files(folder)[:2]:
            try:
                st = f.stat()
                sig.append((str(f), st.st_size, st.st_mtime))
            except OSError:
                pass
    return tuple(sig)
