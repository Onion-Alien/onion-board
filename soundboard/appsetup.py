"""Set up for the app you're using: when a voice chat app or a game starts listening
to you, a slim bar asks once "Looks like you're using Discord. Set up for it?".
*Set up* switches to the simple mode that suits it (soundboard.profiles) and
remembers the app; the next time it shows up, the board switches by itself (with
Undo). *Not now* asks again next start; ✕ never asks about that app again.

Only apps actually listening (voicesdk.Listeners: recording your mic or the cable)
or a game in front with a known voice engine (voicesdk.Watcher) count, so an app
merely open in the background never asks anything.

Config: `cfg.app_setup` = {"ask": bool, "apps": {exe: simple mode key}, "never":
[exe]}. Older versions don't know the key and keep it as it is (library._raw_extra);
an unknown simple mode in "apps" (a newer version's) is kept and skipped.
"""
from __future__ import annotations

from dataclasses import dataclass

from soundboard import profiles

# an app counts as gone (and is new again when it comes back) after this long unseen:
# Discord and games stop recording for a moment now and then
GONE_S = 30.0
# the simple modes an app can be remembered with (Advanced is picked by hand)
MODES = (profiles.GAME.key, profiles.VOICE.key, profiles.CLEAN.key)

_DISCORD = ("discord.exe", "discordptb.exe", "discordcanary.exe", "discorddevelopment.exe")
_MEETING = ("zoom.exe", "ms-teams.exe", "teams.exe", "chrome.exe", "msedge.exe",
            "firefox.exe", "brave.exe", "opera.exe", "opera_gx.exe", "vivaldi.exe")


@dataclass(frozen=True)
class Seen:
    """One app using your sounds now: `simple` is the simple mode that suits it."""
    exe: str       # lower-case file name: what's remembered
    name: str      # as shown ("Discord", "Your browser", "VALORANT-Win64-Shipping")
    simple: str

    @property
    def guide(self) -> str:
        """The chat guide with that app's own settings to check (chatguide.show_guide):
        "" for none."""
        if self.exe in _DISCORD:
            return "discord"
        if self.exe in _MEETING:
            return "meeting"
        return "game" if self.simple == profiles.GAME.key else ""


def settings(cfg) -> dict:
    """`cfg.app_setup`, with its keys made usable (changed in place, so a setting
    this version doesn't know stays in it)."""
    s = getattr(cfg, "app_setup", None)
    if not isinstance(s, dict):
        s = {}
        cfg.app_setup = s
    if not isinstance(s.get("ask"), bool):
        s["ask"] = True
    apps = s.get("apps")
    s["apps"] = {k.lower(): v for k, v in apps.items()
                 if isinstance(k, str) and isinstance(v, str)} if isinstance(apps, dict) else {}
    never = s.get("never")
    s["never"] = list(dict.fromkeys(x.lower() for x in never if isinstance(x, str))) \
        if isinstance(never, list) else []
    return s


def remember(cfg, exe: str, simple: str):
    s = settings(cfg)
    s["apps"][exe.lower()] = simple
    if exe.lower() in s["never"]:
        s["never"].remove(exe.lower())


def forget(cfg, exe: str):
    """Off the remembered list and the never-ask list both: it may ask again."""
    s = settings(cfg)
    s["apps"].pop(exe.lower(), None)
    s["never"] = [x for x in s["never"] if x != exe.lower()]


def never(cfg, exe: str):
    s = settings(cfg)
    if exe.lower() not in s["never"]:
        s["never"].append(exe.lower())


class Tracker:
    """Which apps are new: one is new when it shows up after GONE_S unseen (or for
    the first time), so a mode picked by hand while it runs is left alone."""

    def __init__(self):
        self._last: dict[str, float] = {}

    def update(self, seen, now: float) -> list[Seen]:
        new = [s for s in seen if now - self._last.get(s.exe, -1e9) > GONE_S]
        for s in seen:
            self._last[s.exe] = now
        return new

    def here(self, exe: str, now: float) -> bool:
        return now - self._last.get(exe, -1e9) <= GONE_S


def decide(cfg, new, current: str, skipped=()) -> tuple[str, Seen] | None:
    """What to do about the apps that just showed up (`new`, in the order the hints
    rank them), in simple mode `current`:
    ("switch", app) for a remembered app whose mode isn't the one in use (its
    `simple` is the remembered mode), ("offer", app) to ask, None for nothing.
    `skipped`: apps answered *Not now* this run."""
    s = settings(cfg)
    for app in new:
        mode = s["apps"].get(app.exe)
        if mode is not None:
            if mode not in MODES:   # a newer version's mode: leave it to that one
                continue
            if mode == current:
                return None
            return "switch", Seen(app.exe, app.name, mode)
        if (not s["ask"] or app.exe in s["never"] or app.exe in skipped
                or current == profiles.ADVANCED.key or app.simple == current):
            continue
        return "offer", app
    return None


__all__ = ["GONE_S", "MODES", "Seen", "Tracker", "decide", "forget", "never", "remember",
           "settings"]
