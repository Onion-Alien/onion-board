"""*Did you know?* tips: one short tip per start, about a feature a new user won't find
alone, each with a *Show me* that opens the right place. Shown only after the setup
guide is done, at most once a day, never while a game is up (the overlay open or a
fullscreen program in front), and never again once seen. Settings → General →
*Show tips* turns them off. The window (ui/mainwindow.py) shows the bar and does
the *Show me*; this module only picks."""
from __future__ import annotations

import datetime
import logging
import os
import sys
from dataclasses import dataclass

from soundboard.i18n import _

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tip:
    key: str        # remembered in Config.tips_seen once shown
    text: str
    show: str       # where Show me goes: "tab:<name>", "settings:<page>" or an action name
    needs: str = ""  # a tab (taboff.KEYS) that must be on for the tip to make sense


TIPS: tuple[Tip, ...] = (
    Tip("effects", _("Right-click any pad → Effects… for bass boost, nightcore, slowed + "
        "reverb, trim and more. The original file is never changed."), "tab:sounds"),
    Tip("record", _("Record a sound with your mic: the Record button next to Add sounds."),
        "record"),
    Tip("search", _("Type in the search box and press Enter to find sounds on YouTube, "
        "SoundCloud and Myinstants, then add one with a click."), "search"),
    Tip("link", _("Paste a YouTube or TikTok link into the search box to add its sound "
        "as a pad."), "search"),
    Tip("replay", _("Instant replay: one hotkey turns the last 30 seconds you heard into "
        "a pad. Set its key in Settings → Hotkeys."), "settings:hotkeys"),
    Tip("overlay", _("The in-game overlay shows your pads over the game, played with the "
        "number keys. Set it up in Settings → Overlay."), "settings:overlay"),
    Tip("hold", _("Hold to play: a sound plays only while you hold its key down, like an "
        "air horn. Right-click a pad → Edit… to switch it on."), "tab:sounds"),
    Tip("categories", _("Make categories with the + above your pads, then right-click "
        "one to give it a random-sound hotkey."), "tab:sounds"),
    Tip("scoped", _("Hotkeys per category: one key plays a different sound in each "
        "category. Switch it on in Settings → Hotkeys."), "settings:hotkeys"),
    Tip("programs", _("Right-click a category → Show this when a program is in front, and "
        "the board switches to it by itself when you open your game."), "tab:sounds"),
    Tip("tabs", _("Don't use the Radio or Triggers tabs? Switch them off in Settings → "
        "Tabs and they don't load at all."), "settings:tabs"),
    Tip("phone", _("Play your pads from your phone with Onion Pocket: Settings → Remote."),
        "settings:remote"),
    Tip("triggers", _("Triggers play a sound when something shows up on your screen, "
        "like a victory banner."), "tab:triggers", "triggers"),
    Tip("voice", _("The Voice tab changes your voice live, or talks for you with a "
        "computer voice."), "tab:voice", "voice"),
    Tip("apps", _("The Apps tab sends another program's sound (a music player, a video) "
        "to your friends, and can record it."), "tab:apps", "apps"),
    Tip("radio", _("The Radio tab plays stations from around the world, and can save the "
        "last 15 seconds as a pad."), "tab:radio", "radio"),
    Tip("queue", _("Right-click a pad → Play next to queue it after the sound that's "
        "playing."), "tab:sounds"),
    Tip("deleted", _("Removed a sound by mistake? It waits in Recently deleted for 30 "
        "days."), "deleted"),
    Tip("backup", _("Back up every sound and setting to one file, or share a category as "
        "a sound pack: the Backup button."), "settings:general"),
    Tip("themes", _("Onion Board has over 30 themes: Settings → Appearance."),
        "settings:appearance"),
    Tip("stream", _("Streaming? The stream output gives OBS your sounds on their own "
        "track: Settings → Audio."), "settings:audio"),
    Tip("hotkeys_off", _("One key can switch every other hotkey off while you type in "
        "chat. Set it in Settings → Hotkeys."), "settings:hotkeys"),
)
BY_KEY = {t.key: t for t in TIPS}


def today() -> str:
    return datetime.date.today().isoformat()


def next_tip(seen, tab_on=lambda key: True) -> Tip | None:
    """The first tip not seen yet whose tab is on (None: all seen)."""
    done = set(seen)
    return next((t for t in TIPS if t.key not in done and (not t.needs or tab_on(t.needs))),
                None)


def due(cfg, tab_on=lambda key: True, game_up=lambda: False, day: str | None = None) -> Tip | None:
    """The tip to show now, or None: tips off, the setup guide not done yet, one already
    shown today, a game up, or nothing left."""
    if not cfg.tips_on or not cfg.setup_done or cfg.tip_day == (day or today()):
        return None
    tip = next_tip(cfg.tips_seen, tab_on)
    if tip is None or game_up():
        return None
    return tip


def fullscreen_in_front() -> bool:
    """A program filling a whole monitor is in front (a game, borderless or not, or a
    video): no tip then. The desktop doesn't count."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetShellWindow.restype = wintypes.HWND
        u.GetDesktopWindow.restype = wintypes.HWND
        u.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        u.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
        u.MonitorFromWindow.restype = wintypes.HMONITOR

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
        u.GetMonitorInfoW.argtypes = (wintypes.HMONITOR, ctypes.POINTER(MONITORINFO))
        hwnd = u.GetForegroundWindow()
        if not hwnd or hwnd in (u.GetShellWindow(), u.GetDesktopWindow()):
            return False
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid():   # the board itself, maximised
            return False
        buf = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(hwnd, buf, 64)
        if buf.value in ("WorkerW", "Progman"):   # the desktop
            return False
        r = wintypes.RECT()
        if not u.GetWindowRect(hwnd, ctypes.byref(r)):
            return False
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if not u.GetMonitorInfoW(u.MonitorFromWindow(hwnd, 2), ctypes.byref(mi)):
            return False
        m = mi.rcMonitor
        return r.left <= m.left and r.top <= m.top and r.right >= m.right \
            and r.bottom >= m.bottom
    except Exception:  # noqa: BLE001
        log.debug("fullscreen check failed", exc_info=True)
        return False
