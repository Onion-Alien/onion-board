"""The AI voices to pick from: the built-in ones and the ones you make yourself.

A voice is a blend of speakers from the add-on's voice model plus a formant and a
pitch (see modules/ai-voices/voices.json). The model holds a fixed set of speakers,
so new blends of them need no new download: the app carries the built-in list
(BUILT_IN, the same as the add-on's voices.json) and writes it, with your own voices,
into the installed add-on's voices.json (sync), which its helper reads. An add-on
downloaded before a voice was added gets that voice too.

Your own voices live in %APPDATA%\\OnionBoard\\ai-voices.json, not in config.json
(an older version rewrites the AI voice settings without fields it doesn't know) and
not only in the add-on's folder (updating or removing the add-on replaces that):

    {"version": 1, "voices": [voice, ...], "deleted": [{"id", "name", "when", "voice"}]}
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

from soundboard import library, trash

log = logging.getLogger(__name__)

FILE_NAME = "ai-voices.json"
VERSION = 1
MAX_NAME = 24
MAX_TEXT = 200
MAX_VOICES = 50
KEEP_DAYS = trash.KEEP_DAYS
KIND = "ai-voice"           # the bin's kind (ui.deleted.DeletedDialog lists one kind)
MY_PREFIX = "my-"           # your own voices' ids
FORMANT = (-2.0, 2.0)
PITCH_HZ = (60, 400)

_FIELDS = ("id", "name", "emoji", "description", "about", "tags", "mix", "formant",
           "pitch_hz")


def _v(vid, name, emoji, description, about, tags, mix, formant, pitch_hz) -> dict:
    return dict(zip(_FIELDS, (vid, name, emoji, description, about, tags, mix,
                              formant, pitch_hz)))


# the same voices, in the same order, as modules/ai-voices/voices.json (a test checks)
BUILT_IN = [
    _v("bear", "Bear", "🐻", "A big, deep voice.",
       "A big man with a deep, heavy voice. Good for a tough guy, a boss or a gentle giant.",
       ["Man"], [[171, 0.5], [60, 0.25], [85, 0.25]], -1.0, 88),
    _v("duke", "Duke", "🎩", "Older and gravelly.",
       "An older man with a low, gravelly voice. Good for a grandad, a wizard or a "
       "grumpy shopkeeper.",
       ["Man"], [[151, 0.5], [85, 0.25], [80, 0.25]], -1.5, 96),
    _v("brick", "Brick", "🧱", "Gruff and grounded.",
       "A rough, hard-edged man's voice with some grit in it. Good for soldiers, bouncers "
       "and grumpy characters.",
       ["Man"], [[156, 0.5], [80, 0.25], [151, 0.25]], -0.5, 100),
    _v("max", "Max", "🧢", "An everyday guy.",
       "An ordinary grown man. The safest pick if you just want to sound like somebody "
       "else.",
       ["Man"], [[188, 0.5], [80, 0.25], [5, 0.25]], 0.0, 118),
    _v("riley", "Riley", "🎮", "A young guy.",
       "A lighter, younger man's voice, like someone in their late teens or early "
       "twenties.",
       ["Man"], [[5, 0.5], [80, 0.25], [188, 0.25]], 0.5, 140),
    _v("river", "River", "🌊", "Somewhere in between.",
       "Sits between a man's and a woman's voice, so it's hard to tell which. Good if "
       "you'd rather not be either.",
       ["Either"], [[80, 0.5], [29, 0.5]], 0.5, 160),
    _v("ivy", "Ivy", "🍂", "A husky woman's voice.",
       "A woman with a low, slightly husky voice. Sounds older and cooler than Sage.",
       ["Woman"], [[108, 0.5], [141, 0.25], [27, 0.25]], -0.5, 160),
    _v("sage", "Sage", "🌿", "A calm, low woman's voice.",
       "A grown woman with a calm, steady, low voice. Sounds relaxed and sure of herself.",
       ["Woman"], [[127, 0.5], [29, 0.25], [108, 0.25]], 0.0, 180),
    _v("nova", "Nova", "✨", "A clear, soft woman's voice.",
       "A woman with a clear, soft voice. The everyday pick if you want to sound like a "
       "woman.",
       ["Woman"], [[27, 0.5], [136, 0.25], [53, 0.25]], 0.0, 215),
    _v("pixie", "Pixie", "🧚", "Light and young-sounding.",
       "A light, high, young-sounding voice. Good for cheerful or cartoon-like characters.",
       ["Woman"], [[18, 0.5], [110, 0.25], [141, 0.25]], 1.0, 265),
    _v("squeak", "Squeak", "🐿️", "A tiny cartoon voice.",
       "Very high and squeaky, like a chipmunk or a cartoon sidekick. Just for fun: "
       "nobody will think it's real.",
       ["Cartoon"], [[18, 0.5], [110, 0.5]], 2.0, 360),
    _v("titan", "Titan", "🗿", "A huge, rumbling voice.",
       "Deeper than anyone really talks: a giant, an ogre or a monster. Best for laughs "
       "and villains, not for passing as a real person.",
       ["Monster"], [[60, 0.5], [85, 0.25], [171, 0.25]], -2.0, 72),
]
BUILT_IN_IDS = frozenset(v["id"] for v in BUILT_IN)

PITCH_WORDS = ((80, "Rumbling"), (95, "Very deep"), (125, "Low"), (150, "Medium-low"),
               (175, "Medium"), (200, "Medium-high"), (240, "Fairly high"), (300, "High"),
               (10 ** 6, "Very high"))


def pitch_word(hz) -> str:
    """How high a voice sits, in a word, from its pitch_hz."""
    try:
        hz = float(hz)
    except (TypeError, ValueError):
        return ""
    if hz <= 0:
        return ""
    return next(w for top, w in PITCH_WORDS if hz < top)


def tag_line(voice: dict) -> str:
    """'Man · Low' / 'Woman · Higher' / 'Your voice · Middle'."""
    tags = [str(t) for t in voice.get("tags", []) if isinstance(t, str)][:3]
    if is_mine(voice):
        tags = ["Your voice"] + tags
    word = pitch_word(voice.get("pitch_hz"))
    return " · ".join(tags + ([word] if word else []))


def is_mine(voice: dict) -> bool:
    return str(voice.get("id", "")).startswith(MY_PREFIX)


def clean_name(name) -> str:
    return " ".join(str(name or "").split())[:MAX_NAME].strip()


def clean_text(text, limit: int = MAX_TEXT) -> str:
    return " ".join(str(text or "").split())[:limit].strip()


def clean_voice(raw, speakers: set[int] | None = None) -> dict | None:
    """A voice from a file or the editor, every field the right type and in range,
    or None if it can't be one (no name, no usable speakers). `speakers`: the
    speakers the model has (others are dropped from the mix)."""
    if not isinstance(raw, dict):
        return None
    vid = raw.get("id")
    name = clean_name(raw.get("name"))
    if not isinstance(vid, str) or not vid or len(vid) > 40 or not name:
        return None
    mix = []
    for pair in raw.get("mix", []) if isinstance(raw.get("mix"), list) else ():
        try:
            s, w = int(pair[0]), float(pair[1])
        except (TypeError, ValueError, IndexError, OverflowError):
            continue
        if w > 0 and w == w and (speakers is None or s in speakers):
            mix.append([s, round(min(w, 1.0), 4)])
    if not mix:
        return None
    try:
        formant = float(raw.get("formant", 0.0))
        hz = float(raw.get("pitch_hz", 150))
    except (TypeError, ValueError):
        formant, hz = 0.0, 150.0
    formant = formant if formant == formant else 0.0
    hz = hz if hz == hz else 150.0
    emoji = str(raw.get("emoji") or "")[:4]
    tags = [clean_text(t, 16) for t in raw.get("tags", [])
            if isinstance(t, str) and clean_text(t, 16)][:3] \
        if isinstance(raw.get("tags"), list) else []
    out = {"id": vid, "name": name, "emoji": emoji,
           "description": clean_text(raw.get("description")),
           "about": clean_text(raw.get("about"), 400), "tags": tags, "mix": mix,
           "formant": round(min(max(formant, FORMANT[0]), FORMANT[1]) * 2) / 2,
           "pitch_hz": int(round(min(max(hz, PITCH_HZ[0]), PITCH_HZ[1])))}
    r = raw.get("recipe")      # your own voice: what the editor made it from
    if isinstance(r, dict) and isinstance(r.get("base"), str):
        try:
            amount = min(max(float(r.get("amount", 0.0)), 0.0), 0.5)
        except (TypeError, ValueError):
            amount = 0.0
        out["recipe"] = {"base": r["base"][:40],
                         "other": str(r.get("other") or "")[:40], "amount": amount}
    return out


def blend(base: dict, other: dict | None = None, amount: float = 0.0) -> list[list]:
    """`base`'s speaker mix with `amount` (0..1) of `other`'s mixed in."""
    a = min(max(float(amount), 0.0), 1.0) if other else 0.0
    out: dict[int, float] = {}
    for voice, share in ((base, 1.0 - a), (other or {}, a)):
        total = sum(float(w) for _s, w in voice.get("mix", [])) or 1.0
        for s, w in voice.get("mix", []):
            out[int(s)] = out.get(int(s), 0.0) + share * float(w) / total
    return [[s, round(w, 4)] for s, w in sorted(out.items(), key=lambda sw: -sw[1])
            if w > 0.0005]


def new_id() -> str:
    return f"{MY_PREFIX}{uuid.uuid4().hex[:10]}"


# ---------------------------------------------------------------- the add-on's list

def model_speakers(folder: Path) -> set[int] | None:
    """The speakers the installed model has (its voices.npz), None if unreadable."""
    try:
        import numpy as np
        with np.load(folder / "model" / "voices.npz") as tab:
            return {int(s) for s in tab["ids"]}
    except Exception:  # noqa: BLE001 - missing, damaged, or not a model at all
        return None


def sync(folder: Path, mine: list[dict], write: bool = True) -> list[dict]:
    """Write the built-in voices and `mine` into the add-on's voices.json (its own
    voices that aren't either are kept, after them), leaving out any voice whose
    speakers the installed model doesn't have. Returns the list now there; the
    file as it was (or []) if it can't be read or written, or `write` is False (a
    copy that isn't the installed one, such as the source tree's)."""
    path = folder / "voices.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("voices"), list):
            raise ValueError("no voices list")
    except (OSError, ValueError):
        return []
    have = [v for v in data["voices"] if isinstance(v, dict) and isinstance(v.get("id"), str)
            and v.get("name")]
    if not write:
        return have
    speakers = model_speakers(folder)
    if speakers is None:     # can't look inside the model: only speakers it's known to have
        speakers = {int(s) for v in have for s, _w in v.get("mix", [])
                    if isinstance(s, (int, float))}
    want, seen = [], set()
    for raw in BUILT_IN + list(mine):
        v = clean_voice(raw, speakers)
        if v is not None and v["id"] not in seen and \
                len(v["mix"]) == len(raw.get("mix", [])):   # every speaker it needs
            seen.add(v["id"])
            want.append(v)
    want += [v for v in have if v["id"] not in seen and not is_mine(v)]
    if want != have:
        data["voices"] = want
        try:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
            tmp.replace(path)
        except OSError:
            log.warning("couldn't update %s", path, exc_info=True)
            return have
    return want


# ---------------------------------------------------------------- your own voices

def path() -> Path:
    return library.APP_DIR / FILE_NAME


class Store:
    """Your own AI voices and the bin. Every change is written straight away. If the
    file couldn't be read (locked by an antivirus or OneDrive) nothing is written over
    it this run."""

    KEEP_DAYS = KEEP_DAYS   # for ui.deleted.DeletedDialog, like trash's

    def __init__(self):
        self.voices: list[dict] = []
        self.deleted: list[trash.Item] = []
        self.writable = True
        self.reload()

    def reload(self):
        self.voices, self.deleted, self.writable = [], [], True
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
        seen = set()
        for d in raw.get("voices", []) if isinstance(raw.get("voices"), list) else ():
            v = clean_voice(d)
            if v is not None and is_mine(v) and v["id"] not in seen:
                seen.add(v["id"])
                self.voices.append(v)
        self.voices = self.voices[:MAX_VOICES]
        for d in raw.get("deleted", []) if isinstance(raw.get("deleted"), list) else ():
            v = clean_voice(d.get("voice")) if isinstance(d, dict) else None
            if v is None:
                continue
            try:
                self.deleted.append(trash.Item(str(d["id"]), KIND, v["name"],
                                               float(d.get("when", 0)), {"voice": v}))
            except (KeyError, TypeError, ValueError):
                continue
        self._prune()

    def save(self) -> bool:
        if not self.writable:
            log.warning("not saving %s: it couldn't be read at startup", path())
            return False
        self._prune()
        data = {"version": VERSION, "voices": self.voices,
                "deleted": [{"id": i.id, "name": i.name, "when": i.when,
                             "voice": i.data.get("voice", {})} for i in self.deleted]}
        try:
            path().parent.mkdir(parents=True, exist_ok=True)
            tmp = path().with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path())
            return True
        except OSError:
            log.exception("couldn't save %s", path())
            return False

    def _prune(self):
        cutoff = time.time() - KEEP_DAYS * 86400
        self.deleted = [i for i in self.deleted if i.when >= cutoff][-trash.MAX_ITEMS:]

    def full(self) -> bool:
        return len(self.voices) >= MAX_VOICES

    def get(self, vid: str) -> dict | None:
        return next((v for v in self.voices if v["id"] == vid), None)

    def put(self, voice: dict) -> dict | None:
        """Add or replace (keeping its place) one of your voices. Returns it as kept."""
        v = clean_voice(voice)
        if v is None or not is_mine(v):
            return None
        i = next((k for k, o in enumerate(self.voices) if o["id"] == v["id"]), None)
        if i is None:
            if self.full():
                return None
            self.voices.append(v)
        else:
            self.voices[i] = v
        self.save()
        return v

    def remove(self, vid: str) -> trash.Item | None:
        """Into the bin. Returns its bin entry, for Undo."""
        v = self.get(vid)
        if v is None:
            return None
        index = self.voices.index(v)
        self.voices.remove(v)
        item = trash.Item(uuid.uuid4().hex[:12], KIND, v["name"], time.time(),
                          {"voice": v}, index)
        self.deleted.append(item)
        self.save()
        return item

    def restore(self, item: trash.Item) -> dict | None:
        """Put a taken-out bin entry back where it was. Returns the voice."""
        v = clean_voice(item.data.get("voice"))
        if v is None or not is_mine(v):
            return None
        if self.get(v["id"]) is not None:
            v["id"] = new_id()
        at = min(max(item.index if item.index is not None else len(self.voices), 0),
                 len(self.voices))
        self.voices.insert(at, v)
        self.save()
        return v

    # (shaped like soundboard.trash, for ui.deleted.DeletedDialog)
    def items(self, kind: str | None = None) -> list[trash.Item]:
        return [i for i in reversed(self.deleted) if kind in (None, KIND)]

    def take(self, item_id: str) -> trash.Item | None:
        item = next((i for i in self.deleted if i.id == item_id), None)
        if item is not None:
            self.deleted.remove(item)
            self.save()
        return item

    def forget(self, item_id: str) -> None:
        self.take(item_id)
