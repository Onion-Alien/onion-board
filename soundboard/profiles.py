"""The simple sound modes over Who's listening: Game, Voice chat, Clean and Advanced.

Each simple mode is a family of destination modes (soundboard.destination) and picks
the one that suits from what the app can see (soundboard.voicesdk): the voice engine
of the game in front, the program listening to the virtual cable. Advanced is the
full list, picked by hand, as before.

Config: `cfg.dest["simple"]` holds the simple mode's key next to `cfg.dest["mode"]`,
the destination mode it picked. Older versions only read "mode", so they keep the
same sound; a "simple" whose family doesn't hold "mode" (an older version changed it)
is ignored and the simple mode is read from "mode" again.

Extending it: a detector is anything that turns what's running into Hints (a
destination mode key, optionally the simple mode it belongs to, and why). A later
"this program -> this mode" list in Settings is one more detector placed first in
the list; choose() and the UI need nothing new for it.
"""
from __future__ import annotations

from dataclasses import dataclass

from soundboard import destination


@dataclass(frozen=True)
class Profile:
    key: str
    label: str
    summary: str               # one line: who it's for (tooltips, the dropdown)
    details: str               # what it does, in plain words (the "What do these do?" box)
    engines: tuple[str, ...]   # destination modes it picks from; () = any (Advanced)
    fallback: str = "off"      # when nothing is detected and the current mode isn't one


GAME = Profile(
    "game", "Game",
    "Voice chat inside a game.",
    "Shapes your sounds for voice chat inside games: mono, the deep bass the chat "
    "throws away turned into harmonics that get through, and each sound's level given "
    "back. When it recognises the game's voice chat (Vivox, or Unity's Photon and "
    "Dissonance) it switches to that by itself; otherwise it keeps the last one it "
    "used (Vivox at first, the most common). Steam voice, Epic and older 8 kHz games: "
    "pick them in Advanced.",
    ("game", "eos", "steam", "unity", "game_lo"), "game")
VOICE = Profile(
    "voice", "Voice chat",
    "Discord, calls in a browser, Zoom, Teams, TeamSpeak.",
    "Shapes your sounds for a voice chat app: Discord, or a call in a browser, Zoom "
    "or Teams, picked by which one is listening to the virtual cable. Mono, the "
    "deep bass turned into harmonics that get through, each sound's level given "
    "back. If it can't tell, it keeps the last one it used (Discord at first).",
    ("discord", "webrtc", "game"), "discord")
CLEAN = Profile(
    "clean", "Clean",
    "Streaming, recording, Voicemeeter or a mixer.",
    "No shaping at all: your sounds go out exactly as mixed, full range. For OBS, "
    "recording, Voicemeeter, a mixer, or anything that isn't a voice chat.",
    ("off",), "off")
ADVANCED = Profile(
    "advanced", "Advanced",
    "Pick the exact voice chat yourself, or make your own.",
    "Every built-in mode by name, your custom modes, and the option to let the app "
    "switch between all of them by itself. Nothing is picked for you unless you tick "
    "that.",
    (), "off")

PROFILES: tuple[Profile, ...] = (GAME, VOICE, CLEAN, ADVANCED)
BY_KEY = {p.key: p for p in PROFILES}

# the shared settings no mode changes, for the "What do these do?" box
SHARED = ("Send in mono, lowering your sounds while you talk and muting your mic "
          "during sounds are your own settings: changing mode leaves them as they are.")


@dataclass(frozen=True)
class Hint:
    """One thing a detector saw: `mode` (a destination mode key) suits it."""
    mode: str
    why: str
    simple: str | None = None   # the simple mode it calls for, when it knows better


def family(mode_key: str) -> Profile:
    """The simple mode a destination mode belongs to (custom ones: Advanced)."""
    for p in (CLEAN, GAME, VOICE):   # "game" (Vivox) sits in Game first, then Voice chat
        if mode_key in p.engines:
            return p
    return ADVANCED


def current(cfg_dest: dict | None) -> Profile:
    """The simple mode a config's `dest` dict is in."""
    d = cfg_dest if isinstance(cfg_dest, dict) else {}
    mode = destination.resolve(d).key
    p = BY_KEY.get(d.get("simple")) if isinstance(d.get("simple"), str) else None
    if p is ADVANCED or (p is not None and mode in p.engines):
        return p
    if d.get("auto"):   # an older config switching between everything: keep doing that
        return ADVANCED
    return family(mode)


def auto_picks(p: Profile) -> bool:
    return p is not ADVANCED and len(p.engines) > 1


def choose(p: Profile, hints, now: str) -> tuple[str, str]:
    """(destination mode, why) for simple mode `p`: the first hint in its family,
    else the mode in use if it's one of them, else its fallback. Advanced keeps
    `now`."""
    if p is ADVANCED:
        return now, ""
    for h in hints or ():
        if h.mode in p.engines and (h.simple or family(h.mode).key) == p.key:
            return h.mode, h.why
    return (now if now in p.engines else p.fallback), ""


def better(p: Profile, hints) -> Hint | None:
    """A hint that calls for another simple mode than `p` (Discord is listening while
    in Game, say): shown as a suggestion, never switched to by itself."""
    if p is ADVANCED:
        return None
    hints = [h if h.simple else Hint(h.mode, h.why, family(h.mode).key) for h in hints or ()]
    if any(h.simple == p.key for h in hints):
        return None   # something seen suits the mode picked: leave it be
    return next((h for h in hints if h.simple in (GAME.key, VOICE.key)), None)


def pick(cfg_dest: dict, key: str, hints=()) -> str:
    """Switch `cfg_dest` (a config's dest dict, changed in place) to simple mode
    `key`; returns why its destination mode was picked ("" when nothing told)."""
    p = BY_KEY[key]
    mode, why = choose(p, hints, destination.resolve(cfg_dest).key)
    cfg_dest["simple"] = p.key
    cfg_dest["mode"] = mode
    if p is not ADVANCED:
        cfg_dest["auto"] = False   # Advanced's own switching; the simple modes pick within
    return why


def explain(cfg_dest: dict | None, why: str = "") -> str:
    """What the current mode does right now, in one or two plain lines."""
    d = cfg_dest if isinstance(cfg_dest, dict) else {}
    p = current(d)
    m = destination.resolve(d)
    if p is CLEAN:
        return "Clean: your sounds go out exactly as mixed."
    using = "Off (no shaping)" if m is destination.OFF else m.label
    line = f"{p.label}: shaping for {using}"
    if why:
        line += f", because {why[0].lower()}{why[1:]}"
    elif auto_picks(p):
        line += " (nothing detected yet, so the last one used)"
    return line + "."
