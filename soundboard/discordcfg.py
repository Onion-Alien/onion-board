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
MAX_JSON = 400_000   # the store is ~10 kB; per-user volumes can grow it

# what's wrong, in the order it matters: the first ones wipe sounds out completely
STUDIO = "studio"            # Studio profile, on the mic: Discord skips Onion Board
BYPASS = "bypass"            # "Bypass System Audio Input Processing", on the mic: same
ISOLATION = "isolation"      # Voice Isolation profile: Krisp is always on
KRISP = "krisp"              # Noise Suppression: Krisp
SUPPRESSION = "suppression"  # Noise Suppression: Standard
ECHO = "echo"                # Echo Cancellation
AGC = "agc"                  # Automatic Gain Control
VAD = "vad"                  # Advanced Voice Activity: Krisp decides when you talk
ORDER = (STUDIO, BYPASS, VAD, ISOLATION, KRISP, SUPPRESSION, ECHO, AGC)
WIPES = (STUDIO, BYPASS, VAD, ISOLATION, KRISP, SUPPRESSION)   # the ones that remove sounds


@dataclass(frozen=True)
class Settings:
    client: str                # "Discord", "Discord Canary", ...
    profile: str               # "CUSTOM", "STUDIO", "VOICE_ISOLATION", "" (older Discord)
    krisp: bool
    suppression: bool
    echo: bool
    agc: bool
    bypass: bool
    vad: bool                  # Voice Activity mode with Advanced Voice Activity (Krisp)
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
        if self.vad:   # a real call (not the Mic Test): ~90% of a song cut, measured
            out.append(VAD)
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


def _varint(b: bytes, i: int) -> tuple[int, int]:
    v = shift = 0
    while True:
        c = b[i]
        i += 1
        v |= (c & 0x7F) << shift
        if c < 0x80:
            return v, i
        shift += 7


def unsnappy(b: bytes) -> bytes:
    """Snappy decompression (the format LevelDB packs table blocks with)."""
    n, i = _varint(b, 0)
    out = bytearray()
    while i < len(b):
        tag = b[i]
        i += 1
        kind = tag & 3
        if kind == 0:   # literal
            ln = tag >> 2
            if ln >= 60:
                nb = ln - 59
                ln = int.from_bytes(b[i:i + nb], "little")
                i += nb
            ln += 1
            out += b[i:i + ln]
            i += ln
            continue
        if kind == 1:
            ln, off = ((tag >> 2) & 7) + 4, ((tag >> 5) << 8) | b[i]
            i += 1
        elif kind == 2:
            ln, off = (tag >> 2) + 1, int.from_bytes(b[i:i + 2], "little")
            i += 2
        else:
            ln, off = (tag >> 2) + 1, int.from_bytes(b[i:i + 4], "little")
            i += 4
        if off <= 0 or off > len(out):
            raise ValueError("bad snappy copy")
        start = len(out) - off
        while ln > 0:   # an overlapping copy repeats the last `off` bytes
            chunk = out[start:start + min(ln, off)]
            out += chunk
            start += len(chunk)
            ln -= len(chunk)
    if len(out) != n:
        raise ValueError("bad snappy length")
    return bytes(out)


def _block(data: bytes, off: int, size: int) -> bytes:
    raw = data[off:off + size]
    kind = data[off + size] if off + size < len(data) else 0
    return unsnappy(raw) if kind == 1 else raw


def table_blocks(data: bytes) -> list[bytes]:
    """A LevelDB table (.ldb)'s data blocks, uncompressed: the footer points at the
    index block, whose values point at the data blocks."""
    if len(data) < 48 or data[-8:] != bytes.fromhex("57fb808b247547db"):
        return []
    foot = data[-48:]
    _meta_off, i = _varint(foot, 0)
    _meta_size, i = _varint(foot, i)
    idx_off, i = _varint(foot, i)
    idx_size, i = _varint(foot, i)
    idx = _block(data, idx_off, idx_size)
    nrest = int.from_bytes(idx[-4:], "little")
    end = len(idx) - 4 - 4 * nrest
    out, i = [], 0
    while i < end:
        _shared, i = _varint(idx, i)
        nonshared, i = _varint(idx, i)
        vlen, i = _varint(idx, i)
        i += nonshared
        off, j = _varint(idx, i)
        size, _ = _varint(idx, j)
        i += vlen
        out.append(_block(data, off, size))
    return out


# the parsed store per table file: tables never change once written
_TABLES: dict[tuple, dict | None] = {}


def _table_store(f: Path, data: bytes, st) -> dict | None:
    key = (str(f), st.st_size, st.st_mtime)
    if key not in _TABLES:
        found = None
        try:
            for blk in table_blocks(data):
                found = _latest_store(blk) or found
        except (ValueError, IndexError):
            log.debug("couldn't read %s", f, exc_info=True)
        _TABLES[key] = found
    return _TABLES[key]


VOICE_KEYS = ("echoCancellation", "modeOptions", "activeInputProfile", "noiseCancellation")


def _latest_store(data: bytes) -> dict | None:
    """The last MediaEngineStore JSON in some bytes that parses: found by its value
    ({"default": {... voice settings ...}}), since a table may store the key cut short."""
    dec = json.JSONDecoder()
    pos = len(data)
    while True:
        j = data.rfind(b'{"default":{', 0, pos)
        if j < 0:
            return None
        pos = j
        try:
            obj, _ = dec.raw_decode(data[j:j + MAX_JSON].decode("utf-8", "replace"))
        except ValueError:   # cut off
            continue
        d = obj.get("default") if isinstance(obj, dict) else None
        if isinstance(d, dict) and any(k in d for k in VOICE_KEYS):
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
                    vad=str(d.get("mode", "VOICE_ACTIVITY")) == "VOICE_ACTIVITY"
                    and (d.get("modeOptions") or {}).get("vadUseKrisp", True) is not False,
                    input_device=str(d.get("inputDeviceId") or "default"),
                    stamp=stamp)


def read_client(client_dir: str, name: str, appdata: Path | None = None) -> Settings | None:
    folder = _folder(client_dir, appdata)
    if folder is None or not folder.is_dir():
        return None
    for f in _files(folder):
        try:
            data = f.read_bytes()
            st = f.stat()
        except OSError:   # Discord holds the LOCK file only; a table can vanish mid-scan
            continue
        stamp = st.st_mtime
        store = _latest_store(data) if f.suffix == ".log" else _table_store(f, data, st)
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
