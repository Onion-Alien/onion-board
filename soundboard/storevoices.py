"""Community voices in the Store tab: voice changer voices, AI voices and voice setups
people share, as settings (never a recording).

The store's server rebuilds every voice from fields it checked (server/store/src/voices.js),
and this side checks every one again before showing or keeping it: a voice from the
store is only ever numbers put into their sliders' ranges and short lines of plain text
(no control or format characters, no piles of combining marks), the same cleaning a
voice saved on this PC gets (savedvoices, aivoicelist, voicesetups). Nothing in a voice
is ever run, opened or used as a path.

    share:  {"kind": "fx" | "ai" | "setup", "name", "about", "emoji", "tags", "data"}
    data:   fx    {"e": {effect: {setting: number}}}
            ai    {"mix": [[speaker, weight]], "formant", "pitch_hz"}
            setup {"e"?, "fx"?, "ai"? {"id", "name", "pitch", + a blend if it's your
                   own AI voice}, "lang"?}
"""
from __future__ import annotations

import json
import logging
import math
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass, field

import numpy as np

from soundboard import netlog, savedvoices, store, voicefx, voicesetups
from soundboard.i18n import _
from soundboard.speech import aivoicelist as avl

log = logging.getLogger(__name__)

KINDS = ("fx", "ai", "setup")
MAX_NAME = 32
MAX_ABOUT = 140
REASONS = ("offensive", "broken", "other")
_LANG = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?$")
_AI_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_GONE = {"Cc", "Cf", "Co", "Cs", "Cn", "Zl", "Zp"}
_MARKUP = set("<>`{}\\")   # never in a name (as the store's sound names)


def plain(text, limit: int) -> str:
    """One line of plain text: normalised, no control / format (bidi overrides, zero
    width) / private-use characters, none of <>`{}\\, at most two combining marks in a
    row, runs of spaces made one, at most `limit` characters."""
    out, marks = [], 0
    for ch in unicodedata.normalize("NFKC", str(text or "")):
        cat = unicodedata.category(ch)
        if cat in _GONE or ch in _MARKUP:
            ch, cat = " ", "Zs"
        if cat.startswith("M"):
            marks += 1
            if marks > 2:
                continue
        else:
            marks = 0
        out.append(ch)
    return "".join(" ".join("".join(out).split())[:limit]).strip()


def one_emoji(text) -> str:
    """`text` if it's one emoji (a pictograph, maybe with a variation selector or skin
    tone), else ""."""
    t = str(text or "")
    if not t or len(t) > 3 or any(unicodedata.category(c) in _GONE for c in t):
        return ""
    first = t[0]
    rest_ok = all(c == "️" or 0x1F3FB <= ord(c) <= 0x1F3FF for c in t[1:])
    return t if rest_ok and (ord(first) >= 0x2190 and unicodedata.category(first) == "So") else ""


def _blend(raw) -> dict | None:
    """An AI voice's {"mix", "formant", "pitch_hz"}, in range, or None."""
    if not isinstance(raw, dict):
        return None
    v = avl.clean_voice({"id": "store", "name": "x", "mix": raw.get("mix"),
                         "formant": raw.get("formant", 0.0), "pitch_hz": raw.get("pitch_hz")})
    if v is None or len(v["mix"]) > 4:
        return None
    return {"mix": v["mix"], "formant": v["formant"], "pitch_hz": v["pitch_hz"]}


@dataclass
class Voice:
    """A community voice, every part checked."""
    id: str
    kind: str
    name: str
    about: str = ""
    emoji: str = ""
    tags: list[str] = field(default_factory=list)
    effects: dict = field(default_factory=dict)   # fx, setup: {type: {"on", param...}}
    fx: str = ""                                  # setup: the voice changer voice's name
    ai: dict = field(default_factory=dict)        # ai: the blend; setup: {"id", "name",
    #                                               "pitch"} + a blend when it isn't built in
    language: str = ""
    unknown: list[str] = field(default_factory=list)   # effects this version doesn't have
    up: int = 0
    down: int = 0
    mine: int = 0
    created: int = 0

    @property
    def score(self) -> int:
        return self.up - self.down

    def needs_ai(self) -> bool:
        return bool(self.ai)


def _num(v, default=0) -> int:
    return int(v) if isinstance(v, int) and not isinstance(v, bool) else default


def voice_from(d) -> Voice | None:
    """One voice from the store's list, checked as if it came from anyone (it did), or
    None if it can't be one."""
    if not isinstance(d, dict):
        return None
    vid, kind, data = d.get("id"), d.get("kind"), d.get("data")
    name = plain(d.get("name"), MAX_NAME)
    if (not isinstance(vid, str) or len(vid) != store.ID_LEN
            or not all(c in "0123456789abcdef" for c in vid)
            or kind not in KINDS or not name or not isinstance(data, dict)):
        return None
    tags = [plain(t, 24) for t in d.get("tags") or () if isinstance(t, str)] \
        if isinstance(d.get("tags"), list) else []
    v = Voice(id=vid, kind=kind, name=name, about=plain(d.get("about"), MAX_ABOUT),
              emoji=one_emoji(d.get("emoji")), tags=[t for t in tags if t][:8],
              up=max(0, _num(d.get("up"))), down=max(0, _num(d.get("down"))),
              mine=_num(d.get("mine")) if d.get("mine") in (-1, 0, 1) else 0,
              created=max(0, _num(d.get("created"))))
    try:
        if kind in ("fx", "setup") and "e" in data:
            if not isinstance(data["e"], dict) or len(data["e"]) > 32:
                return None
            v.effects, v.unknown = savedvoices.from_shared(data["e"])
    except savedvoices.CodeError:
        return None
    if kind == "fx":
        return v if v.effects else None
    if kind == "ai":
        b = _blend(data)
        if b is None:
            return None
        v.ai = b
        return v
    # a setup: what of it this version can use
    if v.effects:
        v.fx = plain(data.get("fx"), MAX_NAME)
    ai = data.get("ai")
    if isinstance(ai, dict) and isinstance(ai.get("id"), str) and _AI_ID.match(ai["id"]):
        pitch = ai.get("pitch", 0.0)
        pitch = float(pitch) if isinstance(pitch, (int, float)) and not isinstance(pitch, bool) \
            and math.isfinite(pitch) else 0.0
        part = {"id": ai["id"], "name": plain(ai.get("name"), MAX_NAME) or ai["id"],
                "pitch": min(max(pitch, -12.0), 12.0)}
        b = _blend(ai) if "mix" in ai else None
        if b is not None:
            part.update(b)
        if b is not None or ai["id"] in avl.BUILT_IN_IDS:   # else: one only its maker has
            v.ai = part
    lang = data.get("lang")
    if isinstance(lang, str) and _LANG.match(lang):
        v.language = lang
    return v if (v.effects or v.ai or v.language) else None


def parse(raw) -> tuple[list[Voice], bool]:
    items = raw.get("voices") if isinstance(raw, dict) else None
    out = [v for v in map(voice_from, items if isinstance(items, list) else []) if v]
    return out, bool(isinstance(raw, dict) and raw.get("more"))


# ---------------------------------------------------------------- sharing yours

def _payload(kind: str, name: str, about: str, emoji: str, data: dict) -> dict:
    return {"kind": kind, "name": plain(name, MAX_NAME), "about": plain(about, MAX_ABOUT),
            "emoji": one_emoji(emoji), "data": data}


def pack_fx(name: str, effects: dict, about: str = "") -> dict:
    """One of your voice changer voices, ready to share."""
    return _payload("fx", name, about, "", {"e": savedvoices.shared_effects(effects)})


def pack_ai(voice: dict, about: str = "") -> dict:
    """One of your AI voices, ready to share."""
    b = _blend(voice) or {}
    return _payload("ai", str(voice.get("name") or ""),
                    about or str(voice.get("about") or voice.get("description") or ""),
                    str(voice.get("emoji") or ""), b)


def pack_setup(name: str, setup: dict, ai_voice: dict | None = None, about: str = "") -> dict:
    """One of your setups, ready to share. `ai_voice`: its AI voice when it's one of
    yours (its blend goes along, as nobody else has it)."""
    data: dict = {}
    e = savedvoices.shared_effects(setup.get("effects") or {})
    if e:
        data["e"] = e
        if setup.get("fx"):
            data["fx"] = plain(setup["fx"], MAX_NAME)
    ai = setup.get("ai")
    if isinstance(ai, dict) and ai.get("id"):
        part = {"id": str(ai["id"]), "name": plain(ai.get("name"), MAX_NAME),
                "pitch": float(ai.get("pitch") or 0.0)}
        if avl.is_mine(ai):
            b = _blend(ai_voice) if ai_voice else None
            if b is None:
                part = {}
            else:
                part.update(b)
        if part:
            data["ai"] = part
    lang = setup.get("language") or ""
    if lang and _LANG.match(lang):
        data["lang"] = lang
    return _payload("setup", name, about, "", data)


def can_share(payload: dict) -> bool:
    d = payload.get("data") or {}
    return bool(payload.get("name")) and (
        bool(d.get("e")) if payload["kind"] == "fx"
        else bool(d.get("mix")) if payload["kind"] == "ai" else bool(d))


# ---------------------------------------------------------------- the store's calls

def _why(code: int, err: str) -> str:
    if err == "duplicate" or code == 409:
        return _("That voice is already in the store.")
    if err == "not allowed":
        return _("The store doesn't take that name or description. Try other words "
                 "(and no links).")
    if err == "not a voice" or code == 422:
        return _("That voice has nothing the store can share. Turn on an effect first.")
    if err == "slow down" or code == 429:
        return _("That's a lot for one day. Try again tomorrow.")
    if code == 404:
        return _("That voice isn't in the store any more.")
    return _("The sound store had a problem. Try again in a bit.")


def _call(method: str, path: str, install: str, body: dict | None = None) -> dict:
    data = store._request(method, path, install,   # noqa: SLF001 - the store's one client
                          json.dumps(body).encode() if body is not None else None,
                          "application/json" if body is not None else "", why=_why)
    try:
        got = json.loads(data.decode("utf-8"))
    except ValueError:
        raise store.StoreError(_("The sound store had a problem. Try again in a bit.")) from None
    if not isinstance(got, dict):
        raise store.StoreError(_("The sound store had a problem. Try again in a bit."))
    return got


def browse(install: str, kind: str = "", sort: str = "top", query: str = "",
           offset: int = 0) -> tuple[list[Voice], bool]:
    """A page of community voices. Call off the UI thread."""
    netlog.cause(store.FEATURE, "You opened Voices in the Store tab: reading the list")
    q = urllib.parse.urlencode({"sort": sort if sort in ("new", "trending") else "top",
                                **({"kind": kind} if kind in KINDS else {}),
                                **({"q": query[:60]} if query.strip() else {}),
                                **({"offset": offset} if offset else {})})
    return parse(_call("GET", f"/v1/voices?{q}", install))


def share(install: str, payload: dict) -> str:
    """Put one of your voices on the store; its id. Call off the UI thread."""
    netlog.cause(store.FEATURE, f"You shared {netlog.quoted(payload.get('name', ''))} "
                                "to the store's voices")
    got = _call("POST", "/v1/voices", install, payload)
    vid = got.get("id")
    if not isinstance(vid, str):
        raise store.StoreError(_("The sound store had a problem. Try again in a bit."))
    return vid


def vote(install: str, voice_id: str, value: int) -> tuple[int, int, int]:
    netlog.cause(store.FEATURE, "You voted on a voice in the store")
    d = _call("POST", f"/v1/voices/{voice_id}/vote", install, {"value": value})
    try:
        return int(d["up"]), int(d["down"]), int(d["mine"])
    except (KeyError, TypeError, ValueError):
        raise store.StoreError(_("The sound store had a problem. Try again in a bit.")) from None


def report(install: str, voice_id: str, reason: str) -> None:
    netlog.cause(store.FEATURE, "You reported a voice in the store")
    _call("POST", f"/v1/voices/{voice_id}/report", install,
          {"reason": reason if reason in REASONS else "other"})


# ---------------------------------------------------------------- taking one

def _free(name: str, taken) -> str:
    """`name`, or "name (2)", "name (3)"... while `taken(name)`."""
    if not taken(name):
        return name
    n = 2
    while taken(f"{name[:MAX_NAME - 5]} ({n})"):
        n += 1
    return f"{name[:MAX_NAME - 5]} ({n})"


def take_fx(v: Voice, saved: savedvoices.Store) -> str:
    """A voice changer voice from the store, saved as one of yours. Its name ("" if you
    have the most voices there can be)."""
    if saved.full():
        return ""
    builtin = {n.casefold() for n in voicefx.PRESETS}
    name = v.name if v.name.casefold() not in builtin else f"{v.name[:MAX_NAME - 9]} (shared)"
    return saved.put(saved.free_name(name), v.effects)


def take_ai(v: Voice, ai_store: avl.Store, name: str = "") -> dict | None:
    """An AI voice (or a setup's own AI voice) from the store, kept as one of yours."""
    if ai_store.full():
        return None
    return ai_store.put({"id": avl.new_id(), "name": plain(name or v.name, avl.MAX_NAME),
                         "emoji": v.emoji, "about": v.about, "description": v.about,
                         "tags": [], **{k: v.ai[k] for k in ("mix", "formant", "pitch_hz")}})


def take_setup(v: Voice, setups: voicesetups.Store, ai_store: avl.Store) -> str:
    """A setup from the store, kept as one of yours (its own AI voice too, when it
    brings one). Its name ("" if it couldn't be kept)."""
    setup: dict = {"effects": dict(v.effects), "fx": v.fx, "language": v.language}
    if v.ai:
        ai = {"id": v.ai["id"], "name": v.ai["name"], "pitch": v.ai["pitch"]}
        if "mix" in v.ai:   # someone's own: it's yours now, under a new id
            mine = ai_store.put({"id": avl.new_id(), "name": plain(v.ai["name"], avl.MAX_NAME),
                                 "emoji": v.emoji, "tags": [],
                                 **{k: v.ai[k] for k in ("mix", "formant", "pitch_hz")}})
            if mine is None:
                return ""
            ai["id"] = mine["id"]
        setup["ai"] = ai
    name = _free(v.name, setups.taken)
    return setups.put(name, setup)


# ---------------------------------------------------------------- hearing one

BLOCK = 480   # samples per block through the effects, as the mic sends them (10 ms)


def preview(v: Voice, ai_module=None) -> tuple[np.ndarray, bool]:
    """The sample line said in `v`, ready for engine.play (float32 stereo, 48 kHz, peak
    0.8 at most), and whether its AI voice was left out (no AI voices add-on).
    Raises aipreview.PreviewError. Call off the UI thread: it takes a moment."""
    from soundboard.engine import SR, resample
    from soundboard.speech import aipreview
    line = aipreview.sample()                         # 16 kHz mono
    blend = {k: v.ai[k] for k in ("mix", "formant", "pitch_hz") if k in v.ai}
    if not blend and v.ai.get("id"):
        blend = next((b for b in avl.BUILT_IN if b["id"] == v.ai["id"]), {})
    left_out = False
    if blend and ai_module is not None:
        voice = dict(blend)
        if "pitch" in v.ai:
            voice["pitch"] = v.ai["pitch"]
        y = resample(aipreview.render(ai_module, voice, line), aipreview.OUT_RATE, SR)
    else:
        left_out = bool(blend)
        y = resample(line, aipreview.IN_RATE, SR)
    x = np.ascontiguousarray(np.stack([y, y], axis=1), np.float32)
    if v.effects:
        chain = voicefx.VoiceChain()
        chain.configure({"enabled": True, "effects": v.effects})
        tail = np.zeros((SR, 2), np.float32)          # a second for echoes to ring out
        x = np.concatenate([x, tail])
        x = np.concatenate([chain.process(x[i:i + BLOCK], SR)
                            for i in range(0, len(x) - BLOCK + 1, BLOCK)])
    x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    if peak > 0.8:
        x = x * (0.8 / peak)
    return np.ascontiguousarray(x, np.float32), left_out
