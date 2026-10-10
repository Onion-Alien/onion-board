"""Onion Board as the host of the Onion Watch add-on's Triggers tab: the one
interface the add-on talks to (onionwatch.host.Host, version TRIGGERS_API). It
hands the add-on the board's sounds, plays them through the board, keeps the
triggers in Config.screen and their pictures in %APPDATA%\\OnionBoard\\triggers
(as the built-in Triggers tab did, so nothing moves), and gives it the theme's
colours.

A trigger's sound plays like pressing its pad (into what others hear, whichever way
it's sent, with the pad's volume and mode). A ringing trigger ("Ring until stopped") loops its sound
until it's stopped, under its own voice id (`<sound>:ring:<trigger>`), in your
headphones when they're open (an alarm left ringing while you're away shouldn't
go out to everyone in the call), else wherever the board plays.

Every sound is played with a tag, and stop_tag(tag) stops it again: a ring, a
sound clicked on a trigger's card to check it (tags starting "hear:", played to
you alone like a pad's preview, as `<sound>:hear:<tag>`), or a pad-like one-shot
(the pads it pressed are remembered by tag). Removing a sound from a trigger, or
the trigger, then stops what it was playing.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from soundboard import library, theme
from soundboard.i18n import _
from soundboard.modules import TRIGGERS_API

log = logging.getLogger(__name__)

RING = ":ring:"
HEAR = ":hear:"


class BoardHost:
    api_version = TRIGGERS_API[1]
    name = "Onion Board"
    default_sound = ""          # the board has no built-in alerts: pick one of yours
    audio_exts = frozenset(library.AUDIO_EXTS)

    def __init__(self, win):
        """`win` is the MainWindow: cfg, audio, engine, play(), import_files(),
        gain_for(), meta(), tray and _save_later()."""
        self.win = win
        if not isinstance(win.cfg.screen, dict):
            win.cfg.screen = {}
        self._adding: list[tuple[str, Callable[[str | None], None]]] = []   # (fingerprint, done)
        self._pressed: dict[str, set[str]] = {}     # tag -> pads its one-shots pressed

    def count(self, key: str):
        """The add-on's feature `key` was used or is set up (onionwatch/usage.py
        FEATURES): `used/triggers-<key>` with the next daily usage count, when Count me
        in is on. Names outside usage.FEATURES are dropped (usage.used)."""
        from soundboard import usage
        usage.used(f"triggers-{key}")

    def tab_info(self, title: str, text: str):
        """Onion Watch's explanation goes behind the ⓘ by the tabs, not a banner."""
        self.win.tab_info["triggers"] = (title, text)

    # ------------------------------------------------------------------ settings
    @property
    def screen(self) -> dict:
        return self.win.cfg.screen

    @property
    def data_dir(self) -> Path:
        return library.APP_DIR

    def save(self):
        self.win._save_later()

    # ------------------------------------------------------------------ sounds
    def sound_details(self, sid: str) -> str:
        """Optional detail for newer trigger cards; keeps the existing host API."""
        meta = self.win.meta(sid)
        if meta is None:
            return _("Sound unavailable")
        volume = f"{meta.volume:.0%}"
        if meta.hotkey:
            return _("{name}: {volume} · Hotkey: {hotkey}", name=meta.name, volume=volume,
                     hotkey=meta.hotkey)
        return _("{name}: {volume} · Hotkey: none", name=meta.name, volume=volume)

    def sounds(self) -> list[tuple[str, str]]:
        return [(m.id, m.name) for m in self.win.cfg.sounds]

    def add_sound(self, path: str, done: Callable[[str | None], None]) -> None:
        """Add a file to the board (the board's own import, in the background), or
        use the pad it's already on."""
        fp = library.fingerprint(path)
        known = next((m.id for m in self.win.cfg.sounds if fp and m.fingerprint == fp), None)
        if known is not None:
            done(known)
            return
        self._adding.append((fp, done))
        self.win.import_files([path])

    def sounds_changed(self):
        """The board's sounds changed: hand over the ones being added that are in."""
        by_fp = {m.fingerprint: m.id for m in self.win.cfg.sounds if m.fingerprint}
        waiting, self._adding = self._adding, []
        for fp, done in waiting:
            if fp and fp in by_fp:
                done(by_fp[fp])
            else:
                self._adding.append((fp, done))

    def import_done(self):
        """The board has finished importing: a file still not on it failed."""
        self.sounds_changed()
        failed, self._adding = self._adding, []
        for _fp, done in failed:
            done(None)

    # ------------------------------------------------------------------ playing
    def play(self, sid: str, loop: bool = False, tag: str = "") -> bool:
        win = self.win
        m, data = win.meta(sid), win.audio.get(sid)
        if m is None or data is None:
            return False
        eng = win.engine
        if tag.startswith("hear:"):  # checking it on the card: like a pad's preview, to
            # your headphones only (none open: nothing, never into the call or stream)
            v = eng.play(f"{sid}{HEAR}{tag}", data, win.gain_for(m), mode="restart",
                         preview=True)
            return v is not None
        if not loop:
            win.play(sid)            # like pressing its pad
            if tag:
                self._pressed.setdefault(tag, set()).add(sid)
            return True
        voice = f"{sid}{RING}{tag}"
        v = eng.play(voice, data, win.gain_for(m), loop=True, preview=True)
        if v is None:                # no headphones open: where the board plays
            v = eng.play(voice, data, win.gain_for(m), loop=True)
        return v is not None

    def _ring_voices(self) -> list[str]:
        return [sid for sid in self.win.engine.playing() if RING in sid]

    def stop_tag(self, tag: str):
        eng = self.win.engine
        for sid in eng.playing():
            if sid.endswith(RING + tag) or sid.endswith(HEAR + tag):
                eng.stop(sid)
        # the pads its one-shots pressed (pressed by hand meanwhile, they stop too),
        # and a press still waiting out the pad's wait or in the queue never starts
        for sid in self._pressed.pop(tag, ()):
            eng.stop(sid)
            self.win.drop_pending(sid)

    def ringing(self) -> list[str]:
        return [sid.split(RING, 1)[1] for sid in self._ring_voices()]

    def playing(self) -> list[str]:
        """The tags of every trigger sound playing now (Onion Watch's Playing now
        bar; optional in the add-on API): rings, card previews, and the pads its
        one-shots pressed while they still play."""
        now = set(self.win.engine.playing())
        tags = [sid.split(RING, 1)[1] for sid in now if RING in sid]
        tags += [sid.split(HEAR, 1)[1] for sid in now if HEAR in sid]
        tags += [tag for tag, sids in self._pressed.items() if now & set(sids)]
        return tags

    # ------------------------------------------------------------------ the rest
    def palette(self) -> dict[str, str]:
        return dict(theme.T)

    def language(self) -> str:
        """The board's language ("en", "de", "pt-BR", the pseudo-language "xx"…), so the
        add-on can show in it too. Optional: an add-on asks with getattr (older boards
        don't have it), so the api version stays the same."""
        from soundboard import i18n
        return i18n.current()

    def notify(self, title: str, body: str):
        """A tray notification, only while the board isn't in front (hidden in the
        tray, or behind the game)."""
        tray = getattr(self.win, "tray", None)
        if tray is None or not tray.isVisible() or self.win.isActiveWindow():
            return
        from PySide6.QtWidgets import QSystemTrayIcon
        tray.showMessage(title, body, QSystemTrayIcon.Information, 8000)
