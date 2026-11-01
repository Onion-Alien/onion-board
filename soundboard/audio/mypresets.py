"""Your own presets: what Live controls or Edit sound → Effects has on now, saved under
a name, so one click puts it all back. Live controls' show as chips after its built-in
ones (livefx.PRESETS) and in Edit sound's Preset box too (soundfx.from_live); a sound's
only in the Preset box (soundfx.PRESETS). Edit sound saves a "live" one when Live
controls can play it (soundfx.to_live), so it shows in both.

They live in %APPDATA%\\OnionBoard\\my-presets.json, a file older versions never open:

    {"version": 1,
     "live": [{"name": "Party", "speed": 1.2, "pitch": 0, "keep": 1, "bass": 6, ...}],
     "sound": [{"name": "Radio demon", "fx": {...soundfx settings...}}]}

A live one holds the speed, pitch and keep pitch with the effect knobs (livefx.clean:
only those off 0) and the volume; a sound's holds soundfx's settings without the trim,
the voice and Live controls' effects (those belong to the sound, not the preset).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from soundboard.audio import livefx, soundfx
from soundboard.sounds import library

log = logging.getLogger(__name__)

FILE_NAME = "my-presets.json"
VERSION = 1
MAX_NAME = 32
MAX_PRESETS = 200    # of each kind (a list, so a long one only scrolls)
KINDS = ("live", "sound")


def path() -> Path:
    return library.APP_DIR / FILE_NAME


def clean_name(name) -> str:
    return " ".join(str(name or "").split())[:MAX_NAME].strip()


def clean_live(raw) -> dict:
    """A live preset: {"speed", "pitch", "keep", <knobs off 0>, "volume"?}."""
    if not isinstance(raw, dict):
        return {}
    try:
        speed = min(max(float(raw.get("speed", 1.0)), 0.05), 20.0)
        pitch = min(max(float(raw.get("pitch", 0.0)), -48.0), 48.0)
    except (TypeError, ValueError):
        return {}
    return {"speed": round(speed, 3), "pitch": round(pitch, 2),
            "keep": 1 if raw.get("keep", 1) else 0, **livefx.clean(raw)}


def clean_sound(raw) -> dict:
    """A sound's preset: soundfx's settings with no trim or voice (Live controls' knobs
    stay: Edit sound's Advanced view has them)."""
    f = soundfx.clean(raw if isinstance(raw, dict) else {})
    f["start"] = f["end"] = 0.0
    f["splices"], f["parts"], f["joined"] = [], [], False
    f["voice"] = {}
    return f


def _clean(kind: str, raw) -> dict:
    return clean_live(raw) if kind == "live" else clean_sound(raw)


def _read() -> dict[str, dict[str, dict]] | None:
    """Every preset by kind, None if the file is there but couldn't be read."""
    out: dict[str, dict[str, dict]] = {k: {} for k in KINDS}
    try:
        raw = json.loads(path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return out
    except (OSError, ValueError):
        log.warning("couldn't read %s", path(), exc_info=True)
        return None
    for kind in KINDS:
        items = raw.get(kind) if isinstance(raw, dict) else None
        for d in items if isinstance(items, list) else ():
            if not isinstance(d, dict):
                continue
            name = clean_name(d.get("name"))
            if not name or any(n.casefold() == name.casefold() for n in out[kind]):
                continue
            body = d.get("fx") if kind == "sound" else d
            p = _clean(kind, body)
            if p and len(out[kind]) < MAX_PRESETS:
                out[kind][name] = p
    return out


def load(kind: str) -> dict[str, dict]:
    """{name: preset} of one kind ("live" or "sound"), in the order they were saved."""
    got = _read()
    return dict(got[kind]) if got else {}


def _write(data: dict[str, dict[str, dict]]) -> bool:
    out = {"version": VERSION,
           "live": [{"name": n, **p} for n, p in data["live"].items()],
           "sound": [{"name": n, "fx": p} for n, p in data["sound"].items()]}
    tmp = path().with_name(f"{FILE_NAME}.{os.getpid()}.tmp")
    try:
        path().parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path())
        return True
    except OSError:
        log.warning("couldn't save %s", path(), exc_info=True)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def find(kind: str, name: str) -> str | None:
    """The saved name `name` matches whatever its case, or None."""
    name = clean_name(name).casefold()
    return next((n for n in load(kind) if n.casefold() == name), None)


def full(kind: str) -> bool:
    return len(load(kind)) >= MAX_PRESETS


def put(kind: str, name: str, preset: dict, at: int = -1) -> str:
    """Save (or replace, in its place) a preset; its name, or "" if it couldn't be.
    `at`: where a new one goes (Undo puts one back where it was), -1 = last."""
    name = clean_name(name)
    data = _read()
    if not name or data is None:
        return ""
    have = data[kind]
    same = next((n for n in have if n.casefold() == name.casefold()), None)
    if same is None and len(have) >= MAX_PRESETS:
        return ""
    p = _clean(kind, preset)
    if same is not None:
        data[kind] = {(name if n == same else n): (p if n == same else v)
                      for n, v in have.items()}
    else:
        items = list(have.items())
        items.insert(len(items) if at < 0 else min(at, len(items)), (name, p))
        data[kind] = dict(items)
    return name if _write(data) else ""


def remove(kind: str, name: str) -> tuple[int, dict] | None:
    """Take a preset out; (where it was, it) so Undo can put it back."""
    data = _read()
    if data is None or name not in data[kind]:
        return None
    at = list(data[kind]).index(name)
    p = data[kind].pop(name)
    return (at, p) if _write(data) else None


def rename(kind: str, old: str, new: str) -> str:
    """The new name, or "" (empty, another preset's name, not saved)."""
    new = clean_name(new)
    data = _read()
    if data is None or old not in data[kind] or not new:
        return ""
    if any(n.casefold() == new.casefold() and n != old for n in data[kind]):
        return ""
    data[kind] = {(new if n == old else n): v for n, v in data[kind].items()}
    return new if _write(data) else ""
