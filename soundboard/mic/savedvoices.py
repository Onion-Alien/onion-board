"""Your own voices for the voice changer: mixes saved under a name (Fine-tune ->
"Save as a voice"), and the ones deleted lately so they can be brought back.

They live in %APPDATA%\\OnionBoard\\voices.json, not in config.json: an older version
rewrites the voice changer's settings without the fields it doesn't know, and this is
a file it never opens, so going back a version loses none of them.

    {"version": 1,
     "voices": [{"name": "Squeaky robot", "effects": {type: {"on": bool, ...}}}],
     "deleted": [{"id": "...", "name": "...", "when": time.time(), "effects": {...}}]}

The folder is looked up on every call (library.APP_DIR), so tests that point the
library somewhere else get their own file.
"""
from __future__ import annotations

import base64
import json
import logging
import math
import time
import uuid
import zlib
from pathlib import Path

from soundboard.sounds import library
from soundboard.core import trash
from soundboard import voicefx
from soundboard.i18n import _

log = logging.getLogger(__name__)

FILE_NAME = "voices.json"
VERSION = 1
MAX_NAME = 32
MAX_VOICES = 100
KEEP_DAYS = trash.KEEP_DAYS
VOICE = "voice"     # the bin's kind (ui.deleted.DeletedDialog lists one kind)


def path() -> Path:
    return library.APP_DIR / FILE_NAME


def clean_name(name) -> str:
    """One line, no runs of spaces, at most MAX_NAME characters ("" if nothing's left)."""
    return " ".join(str(name or "").split())[:MAX_NAME].strip()


def clean_effects(raw) -> dict:
    return voicefx.clean_spec({"effects": raw})["effects"]


def builtin_names() -> set[str]:
    """The names a saved voice can't have (casefolded): the ready voices' (the English
    names, what's saved, and how their cards read now) and the panel's own cards."""
    names = (*voicefx.PRESETS, "Custom", "My own mix", "Random voice")
    return {n.casefold() for n in (*names, *map(voicefx.shown, voicefx.PRESETS),
                                   _("My own mix"))}


def clean_list(raw) -> list[tuple[str, dict]]:
    """[{"name", "effects"}, ...] from a file or a backup, as (name, effects) pairs:
    damaged entries are dropped, and a name used twice keeps its first. One named like
    a ready voice (saved before that voice came out, or by hand) comes back as
    "name (2)": under the ready voice's name its card would pick the ready voice."""
    pairs, seen = [], set()
    for d in raw if isinstance(raw, list) else ():
        if not isinstance(d, dict):
            continue
        name = clean_name(d.get("name"))
        if name and name.casefold() not in seen and isinstance(d.get("effects"), dict):
            seen.add(name.casefold())
            pairs.append((name, clean_effects(d["effects"])))
    builtin = builtin_names()
    taken = seen | builtin
    out = []
    for name, effects in pairs[:MAX_VOICES]:
        if name.casefold() in builtin:
            n = 2
            while f"{name[:MAX_NAME - 5]} ({n})".casefold() in taken:
                n += 1
            name = f"{name[:MAX_NAME - 5]} ({n})"
            taken.add(name.casefold())
        out.append((name, effects))
    return out


def saved() -> list[dict]:
    """The saved voices as written, read without changing anything (for a backup)."""
    try:
        raw = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    voices = raw.get("voices") if isinstance(raw, dict) else None
    return [{"name": n, "effects": e} for n, e in clean_list(voices)]


# ---------------------------------------------------------------- share codes
# A saved voice as a line of text to paste to a friend: "OB1-" + base64url (no
# padding) of zlib-compressed compact JSON {"n": name, "e": {type: {"on", param...}}}.
# Only the name and the effects' numbers go in: no paths, nothing about this PC.
# Effects that are off and settings left at their default are left out (they load
# that way anyway), so codes stay short. "OB2-" codes (any of your voices or setups,
# packed the same way) are storevoices.share_code's.
CODE_PREFIX = "OB"
CODE_VERSION = 1
MAX_CODE = 4096        # characters of code (a full 13-effect voice is ~300)
MAX_JSON = 16384       # bytes it may unpack to (a zip bomb stops here)
# your mic clean-up and what's on top of the voice (the Background, the Effects
# pop-up's extras) are yours, not the voice's (ui.voicefxpanel.on_top): never shared
NOT_SHARED = frozenset({"cleanup", "backdrop"})


class CodeError(ValueError):
    """A share code that can't be read; str() says why, in plain words."""


def shared_effects(effects: dict) -> dict:
    """A voice's effects as they're shared (codes, the store): only those that are on,
    only settings that aren't at their default, {type: {param: number}}."""
    out = {}
    for etype, cfg in clean_effects(effects).items():
        cls = voicefx.REGISTRY.get(etype)
        if cls is None or etype in NOT_SHARED or cls.extra or not cfg.get("on"):
            continue
        d = {}
        for q in cls.params:
            if q.key in cfg:
                v = q.clamp(cfg[q.key])
                if v != q.default:
                    d[q.key] = round(v, 4)
        out[etype] = d
    return out


def from_shared(raw: dict) -> tuple[dict, list[str]]:
    """Shared effects ({type: {param: number}}) as a voice's effects, every number put
    inside its slider's range, and the effects this version doesn't have (left out).
    Raises CodeError when an effect's settings aren't a dict."""
    effects, unknown = {}, []
    for etype, cfg in raw.items():
        cls = voicefx.REGISTRY.get(etype) if isinstance(etype, str) else None
        if cls is None:
            unknown.append(str(etype)[:40])
            continue
        if etype in NOT_SHARED or cls.extra:
            continue
        if not isinstance(cfg, dict):
            raise CodeError(_("That code is damaged: an effect's settings are missing."))
        d: dict[str, bool | float] = {"on": True}
        for q in cls.params:
            v = cfg.get(q.key)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                try:
                    v = float(v)
                except OverflowError:   # an integer too big to be a number here
                    continue
                if math.isfinite(v):
                    d[q.key] = q.clamp(v)
        effects[etype] = d
    return effects, unknown


def pack_code(obj: dict, version: int = CODE_VERSION) -> str:
    """`obj` as a code: "OB<version>-" + base64url (no padding) of zlib'd compact JSON."""
    raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    body = base64.urlsafe_b64encode(zlib.compress(raw, 9)).rstrip(b"=").decode("ascii")
    return f"{CODE_PREFIX}{version}-{body}"


def unpack_code(text, newest: int = CODE_VERSION) -> tuple[int, dict]:
    """(version, the JSON object) from a code made by pack_code, or CodeError: one
    pasted over two lines or with spaces around still reads, one that's too long,
    unpacks to too much or was made by a version newer than `newest` doesn't."""
    code = "".join(str(text or "").split())   # pasted over two lines, spaces around
    if not code:
        raise CodeError(_("There's no code there."))
    if len(code) > MAX_CODE:
        raise CodeError(_("That's far too long to be a voice code."))
    head, dash, body = code.partition("-")
    version = head[len(CODE_PREFIX):]
    if not dash or not head.upper().startswith(CODE_PREFIX) \
            or not (version.isascii() and version.isdecimal()) or int(version) < 1:
        raise CodeError(_("That isn't a voice code (they start with “OB”)."))
    if int(version) > newest:
        raise CodeError(_("That code was made by a newer version of the app. Update to "
                          "use it."))
    try:
        packed = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        unzip = zlib.decompressobj()
        raw = unzip.decompress(packed, MAX_JSON)
        if unzip.unconsumed_tail:
            raise CodeError(_("That code unpacks to far too much to be a voice."))
        if not unzip.eof:
            raise ValueError("cut short")
        data = json.loads(raw.decode("utf-8"))
    except CodeError:
        raise
    except (ValueError, zlib.error, RecursionError):
        raise CodeError(_("That code is damaged or cut short. Copy the whole thing "
                          "and try again.")) from None
    if not isinstance(data, dict):
        raise CodeError(_("That code is damaged: it doesn't hold a voice."))
    return int(version), data


def unknown_note(unknown: list[str]) -> list[str]:
    """The note for effects a code or store voice has that this version doesn't."""
    if not unknown:
        return []
    names = ", ".join(unknown[:5]) + ("…" if len(unknown) > 5 else "")
    return [_("Left out effects this version doesn't have: {effects}. "
              "Updating the app may add them.", effects=names)]


def share_code(name: str, effects: dict) -> str:
    return pack_code({"n": clean_name(name) or _("My voice"), "e": shared_effects(effects)},
                     CODE_VERSION)


def read_code(text) -> tuple[str, dict, list[str]]:
    """(name, effects, notes) from a voice changer voice's "OB1-" code, or CodeError.
    Every number is put inside its slider's range; effects this version doesn't have
    are left out and named in `notes`. (Any kind of code: storevoices.read_code.)"""
    _version, data = unpack_code(text, CODE_VERSION)
    if not isinstance(data.get("n"), str) or not isinstance(data.get("e"), dict):
        raise CodeError(_("That code is damaged: it doesn't hold a voice."))
    name = clean_name(data["n"]) or _("Shared voice")
    effects, unknown = from_shared(data["e"])
    return name, effects, unknown_note(unknown)


class Store:
    """The saved voices (name -> effects, in the order they were saved) and the bin.
    Every change is written straight away. If the file couldn't be read (locked by an
    antivirus or OneDrive) nothing is written over it this run."""

    KEEP_DAYS = KEEP_DAYS   # for ui.deleted.DeletedDialog, like trash's

    def __init__(self):
        self.voices: dict[str, dict] = {}
        self.deleted: list[trash.Item] = []
        self.writable = True
        self.reload()

    # ------------------------------------------------------------ the file
    def reload(self):
        self.voices, self.deleted, self.writable = {}, [], True
        try:
            raw = json.loads(path().read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except ValueError:
            log.warning("couldn't read %s; setting it aside", path(), exc_info=True)
            try:
                path().replace(path().with_name(
                    f"{FILE_NAME}.broken-{time.strftime('%Y%m%d-%H%M%S')}"))
            except OSError:
                self.writable = False
            return
        except OSError:
            log.warning("couldn't read %s", path(), exc_info=True)
            self.writable = False
            return
        raw = raw if isinstance(raw, dict) else {}
        self.voices = dict(clean_list(raw.get("voices")))
        for d in raw.get("deleted", []) if isinstance(raw.get("deleted"), list) else ():
            try:
                name = clean_name(d["name"]) or _("Voice")
                self.deleted.append(trash.Item(str(d["id"]), VOICE, name,
                                               float(d.get("when", 0)),
                                               {"effects": clean_effects(d.get("effects"))}))
            except (KeyError, TypeError, ValueError):
                continue
        self._prune()

    def save(self) -> bool:
        if not self.writable:
            log.warning("not saving %s: it couldn't be read at startup", path())
            return False
        self._prune()
        data = {"version": VERSION,
                "voices": self.export(),
                "deleted": [{"id": i.id, "name": i.name, "when": i.when,
                             "effects": i.data.get("effects", {})} for i in self.deleted]}
        try:
            path().parent.mkdir(parents=True, exist_ok=True)
            library.atomic_write_text(path(), json.dumps(data, indent=1))
            return True
        except OSError:
            log.exception("couldn't save %s", path())
            return False

    def export(self) -> list[dict]:
        """The voices as they're written (and exported with a backup's settings)."""
        return [{"name": n, "effects": e} for n, e in self.voices.items()]

    def _prune(self):
        cutoff = time.time() - KEEP_DAYS * 86400
        self.deleted = [i for i in self.deleted if i.when >= cutoff][-trash.MAX_ITEMS:]

    # ------------------------------------------------------------ voices
    def find(self, name: str) -> str | None:
        """The saved voice called `name`, whatever its capitals (None if there's none)."""
        key = clean_name(name).casefold()
        return next((n for n in self.voices if n.casefold() == key), None)

    def free_name(self, name: str) -> str:
        """`name`, or "name (2)", "name (3)"... if that's taken (a ready voice's name
        is taken too)."""
        name = clean_name(name) or _("My voice")
        builtin = builtin_names()

        def taken(n: str) -> bool:
            return self.find(n) is not None or n.casefold() in builtin
        if not taken(name):
            return name
        n = 2
        while taken(f"{name[:MAX_NAME - 5]} ({n})"):
            n += 1
        return f"{name[:MAX_NAME - 5]} ({n})"

    def full(self) -> bool:
        return len(self.voices) >= MAX_VOICES

    def put(self, name: str, effects: dict) -> str:
        """Save (or replace, keeping its place) a voice. Returns the name it got."""
        name = self.find(name) or clean_name(name)
        self.voices[name] = clean_effects(effects)
        self.save()
        return name

    def rename(self, old: str, new: str) -> str:
        """Rename keeping its place. Returns the new name ("" if `old` is gone)."""
        new = clean_name(new)
        if old not in self.voices or not new:
            return ""
        self.voices = {(new if n == old else n): e for n, e in self.voices.items()}
        self.save()
        return new

    def remove(self, name: str) -> trash.Item | None:
        """Into the bin. Returns its bin entry, for Undo."""
        if name not in self.voices:
            return None
        index = list(self.voices).index(name)
        item = trash.Item(uuid.uuid4().hex[:12], VOICE, name, time.time(),
                          {"effects": self.voices.pop(name)}, index)
        self.deleted.append(item)
        self.save()
        return item

    def restore(self, item: trash.Item, index: int | None = None) -> str:
        """Put a taken-out bin entry back (as "name (2)" if the name's been reused).
        Returns the name it came back as."""
        name = self.free_name(item.name)
        pairs = list(self.voices.items())
        at = len(pairs) if index is None else min(max(index, 0), len(pairs))
        pairs.insert(at, (name, clean_effects(item.data.get("effects"))))
        self.voices = dict(pairs)
        self.save()
        return name

    def merge(self, raw) -> int:
        """Add the voices from a backup that aren't here by name. Returns how many."""
        added = 0
        for name, effects in clean_list(raw):
            if self.find(name) is None and not self.full():
                self.voices[name] = effects
                added += 1
        if added:
            self.save()
        return added

    # ------------------------------------------------------------ the bin
    # (shaped like soundboard.core.trash, for ui.deleted.DeletedDialog)
    def items(self, kind: str | None = None) -> list[trash.Item]:
        return [i for i in reversed(self.deleted) if kind in (None, VOICE)]

    def take(self, item_id: str) -> trash.Item | None:
        item = next((i for i in self.deleted if i.id == item_id), None)
        if item is not None:
            self.deleted.remove(item)
            self.save()
        return item

    def forget(self, item_id: str) -> None:
        self.take(item_id)
