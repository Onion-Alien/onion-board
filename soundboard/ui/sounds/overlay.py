"""In-game overlay: a small HUD of sound tiles that pops up over a game on a hotkey.

The overlay never takes focus, so the game keeps its keyboard and mouse the whole
time. Its keys are global hotkeys (RegisterHotKey, see winkeys) claimed only while
it's up: the number keys play a tile, Q / E flip pages, R switches category, 0 stops
everything, . pauses, Esc closes. When it closes, the keys go straight back to the game.
It takes clicks too (a tile plays, the Pause / Stop buttons along the bottom) without
ever taking focus, for games that give you a mouse cursor.

Pages are the Sounds tab's pads in order, nine at a time, so dragging pads around
there rearranges the overlay too. It shows the category the Sounds tab shows;
switching category here switches it there too.

It opens on the game's monitor, or on a monitor picked in Settings, at one of nine
spots or wherever it was last dragged to: drag it by any empty part (the title, the
edges) and it stays there, kept as a fraction of the monitor so it survives a change
of resolution or overlay size.

In exclusive fullscreen nothing can be drawn over the game, so the overlay opens
"blind": the keys still work, and short beeps in your headphones confirm it.
"""
from __future__ import annotations

import logging
import math
import time

from PySide6.QtCore import (QRect, QTimer)
from PySide6.QtGui import (QGuiApplication)
from PySide6.QtWidgets import QApplication

from soundboard.sounds import library
from soundboard.control import winkeys
from soundboard.ui.sounds.overlaysettings import (  # noqa: F401
    AUTOHIDE,
    CLOSE_DELAY_MS,
    DRAG_START_PX,
    find_screen,
    FLASH_S,
    HOLD_POLL_MS,
    KEY_CHOICES,
    key_label,
    KEYSETS,
    MODES,
    monitor_choices,
    MONITOR_GAME,
    MONITOR_PRIMARY,
    OverlaySettings,
    pick_screen,
    place,
    POSITIONS,
    screen_key,
    SLOTS,
)
from soundboard.ui.sounds.overlaywindow import _AnyInput, OverlayWindow  # noqa: F401

log = logging.getLogger(__name__)


class Overlay:
    """What the overlay does; `OverlayWindow` only draws it.

    `host` is the main window. Used: host.cfg (sounds, categories, category,
    overlay_hotkey), host.audio, host.playctl.play(sid), host.hkctl.on_hotkey('__stop__' /
    '__pause__'), host.hkctl.register_hotkeys() (which asks `layer()` for the extra keys),
    host.playctl.cue(kind or notes) and host.catctl.set_category(name) (the category key)."""
    ACTION = "__overlay__"
    PREFIX = "__ov:"

    def __init__(self, host, settings: dict | None = None):
        self.host = host
        self.s = OverlaySettings.from_dict(settings)
        self.page = 0
        self._sounds: tuple | None = None   # (key, sounds()) cached
        self.is_open = False
        self.blind = False            # open without a window (exclusive fullscreen)
        self.by_click = False         # opened from Settings: no key is held, acts like toggle
        self.flash: tuple[int, float] | None = None   # (tile, until) just picked
        self._window: OverlayWindow | None = None
        self._hold_vk: int | None = None
        self._autohide = QTimer()
        self._autohide.setSingleShot(True)
        self._autohide.timeout.connect(self.close)
        self._close_soon = QTimer()
        self._close_soon.setSingleShot(True)
        self._close_soon.timeout.connect(self.close)
        self._hold = QTimer()
        self._hold.timeout.connect(self._poll_hold)
        self._preview_end = QTimer()
        self._preview_end.setSingleShot(True)
        self._preview_end.timeout.connect(self._end_preview)
        self._previewing = False
        self._preview_watch = _AnyInput(self._end_preview)
        self.listeners: list = []     # called (no args) after a drag changed the settings

    @property
    def keyset(self) -> dict:
        return KEYSETS[self.s.keys]

    @property
    def window(self) -> OverlayWindow:
        if self._window is None:
            self._window = OverlayWindow(self)
        return self._window

    # ------------------------------------------------------------------ pages
    def sounds(self) -> list:
        """The sounds of the category the Sounds tab shows (all of them for ""). Kept
        until sounds_changed() or the category / sound list changes: a paint asks
        several times, and a big library made each ask a full pass."""
        cfg = self.host.cfg
        key = (cfg.category, cfg.subcategory, id(cfg.sounds), len(cfg.sounds),
               tuple(cfg.hidden_from_all))
        if self._sounds is None or self._sounds[0] != key:
            self._sounds = (key, [m for m in cfg.sounds
                                  if library.in_view(m.tags, cfg.category, cfg.subcategory,
                                                  cfg.hidden_from_all)])
        return self._sounds[1]

    def sounds_changed(self):
        """A sound was added, removed, moved or put in / out of a category."""
        self._sounds = None

    def pages(self) -> int:
        return max(1, math.ceil(len(self.sounds()) / SLOTS))

    def page_sounds(self) -> list:
        self.page = min(self.page, self.pages() - 1)
        return self.sounds()[self.page * SLOTS:(self.page + 1) * SLOTS]

    # ------------------------------------------------------------------ keys
    def layer(self) -> dict[str, str]:
        """The keys to claim while open: combo -> action. They win over the app's
        other hotkeys for as long as the overlay is up."""
        if not self.is_open:
            return {}
        ks = self.keyset
        keys = {k: f"{self.PREFIX}slot:{i}" for i, k in enumerate(ks["slots"])}
        keys.update({ks["prev"]: f"{self.PREFIX}prev", ks["next"]: f"{self.PREFIX}next",
                     ks["stop"]: f"{self.PREFIX}stop", ks["pause"]: f"{self.PREFIX}pause",
                     "esc": f"{self.PREFIX}close"})
        if self.host.cfg.categories:   # only claimed when there's something to switch to
            keys[ks["cat"]] = f"{self.PREFIX}cat"
        out = dict(keys)
        if self.s.mode == "hold":
            # while ctrl+alt+O is held, "1" arrives as ctrl+alt+1: claim that too
            parsed = winkeys.parse(self.host.cfg.overlay_hotkey or "")
            if parsed and parsed[0]:
                mods = winkeys.combo_name(parsed[0], ord("A"))[:-1]   # "ctrl+alt+"
                for k, act in keys.items():
                    out.setdefault(mods + k, act)
        # the overlay's own hotkey (say Num 0 with the numpad keys) keeps closing it
        out.pop(self.host.cfg.overlay_hotkey, None)
        return out

    def handle(self, action: str) -> bool:
        """Take a fired hotkey action if it's ours. True if it was."""
        if action == self.ACTION:
            self.trigger()
            return True
        if not action.startswith(self.PREFIX):
            return False
        if not self.is_open:
            return True           # a key press that raced the close: drop it
        what = action[len(self.PREFIX):]
        if what.startswith("slot:"):
            self.pick(int(what[5:]))
        elif what in ("prev", "next"):
            self.flip(-1 if what == "prev" else 1)
        elif what == "cat":
            self.next_category()
        elif what == "stop":
            self.host.hkctl.on_hotkey("__stop__")
            self._touch()
        elif what == "pause":
            self.host.hkctl.on_hotkey("__pause__")
            self._touch()
        elif what == "close":
            self.close()
        return True

    def click(self, what: str):
        """A click on the window: "slot:N", "pause" or "stop". Same as its key."""
        self.handle(self.PREFIX + what)

    # ------------------------------------------------------------------ open / close
    @property
    def toggling(self) -> bool:
        """Open until closed (tap again, Esc, auto-hide), not until a key is let go."""
        return self.s.mode == "toggle" or self.by_click

    def trigger(self):
        if not self.is_open:
            self.open()
        elif self.toggling:
            self.close()
        # hold mode: letting go closes it, a repeat press does nothing

    def open_by_click(self):
        """The Open overlay button: the same as the hotkey, minus the key to hold."""
        if self.is_open:
            self.close()
        else:
            self.open(by_click=True)

    def open(self, by_click: bool = False):
        if self.is_open:
            return
        self._preview_end.stop()
        self._set_previewing(False)
        self.is_open = True
        self.by_click = by_click
        self.flash = None
        self.blind = winkeys.exclusive_fullscreen()
        self.host.hkctl.register_hotkeys()      # claims layer()
        if self.blind:
            log.info("overlay opened without a window: a game is in exclusive fullscreen")
            self.host.playctl.cue("start")
            if self._window is not None:
                self._window.dismiss()
        else:
            self.window.present()
            log.info("overlay opened at %s on %s", self.window.geometry().getRect(),
                     self.window.screen().name() if self.window.screen() else "?")
        self._hold_vk = None
        if not self.toggling:
            parsed = winkeys.parse(self.host.cfg.overlay_hotkey or "")
            if parsed:
                self._hold_vk = parsed[1]
                self._hold.start(HOLD_POLL_MS)
        self._touch()

    def close(self):
        if not self.is_open:
            return
        self.is_open = False
        for t in (self._autohide, self._close_soon, self._hold):
            t.stop()
        self.host.hkctl.register_hotkeys()      # the keys go back to the game
        if self.blind:
            self.host.playctl.cue("stop")
        if self._window is not None:
            self._window.dismiss()

    def _poll_hold(self):
        if self._hold_vk is not None and not winkeys.is_down(self._hold_vk):
            self.close()

    def _touch(self):
        """Something happened: push the auto-hide back."""
        if self.is_open and self.toggling and self.s.autohide \
                and not self._close_soon.isActive():
            self._autohide.start(self.s.autohide * 1000)

    # ------------------------------------------------------------------ actions
    def pick(self, tile: int):
        sounds = self.page_sounds()
        if not 0 <= tile < len(sounds):
            self._touch()
            return
        self.host.playctl.play(sounds[tile].id)
        self.flash = (tile, time.monotonic() + FLASH_S)
        if self._window is not None:
            self._window.update()
        if self.toggling and self.s.close_after_play:
            self._autohide.stop()
            self._close_soon.start(CLOSE_DELAY_MS)
        else:
            self._touch()

    def flip(self, step: int):
        n = self.pages()
        self.page = (self.page + step) % n
        self.flash = None
        if self.blind and n > 1:     # 1 beep for page 1, 2 for page 2, …
            beeps = min(self.page + 1, 6)
            self.host.playctl.cue(tuple(f for __ in range(beeps) for f in (1175, 0)))
        if self._window is not None:
            self._window.update()
        self._touch()

    def next_category(self):
        """All → the first category → … → the last → All again."""
        cats = ["", *self.host.cfg.categories]
        cur = self.host.cfg.category
        i = cats.index(cur) if cur in cats else 0
        self.host.catctl.set_category(cats[(i + 1) % len(cats)])
        self.page = 0
        self.flash = None
        if self.blind:
            self.host.playctl.cue("saved")
        if self._window is not None:
            self._window.update()
        self._touch()

    # ------------------------------------------------------------------ host hooks
    def apply(self, settings: dict):
        """New settings from the Settings window."""
        self.s = OverlaySettings.from_dict(settings)
        if self.is_open:
            self.host.hkctl.register_hotkeys()
        if self._window is not None and self._window.isVisible():
            self._window.present()        # new size / position

    def preview(self, seconds: float = 3.0):
        """Show the overlay (without claiming any keys) so its look can be judged. Only
        to look at: clicks pass through it, and any click or key in the app ends it
        (Settings is modal, so a click on the overlay itself only made Windows ding).
        Open the real overlay to try it or drag it."""
        if self.is_open:
            return
        self.window.present(follow_game=False)
        self._set_previewing(True)
        self._preview_end.start(int(seconds * 1000))

    def _set_previewing(self, on: bool):
        if on == self._previewing:
            return
        self._previewing = on
        app = QApplication.instance()
        if app is not None:
            (app.installEventFilter if on else app.removeEventFilter)(self._preview_watch)
        w = self._window
        if w is not None and QGuiApplication.platformName() == "windows":
            winkeys.set_click_through(int(w.winId()), on)

    def keep_preview(self):
        """The mouse is on the preview (say, dragging it into place): keep it up."""
        if not self.is_open and self._preview_end.isActive():
            self._preview_end.start(3000)

    def dropped(self, rect: QRect, screen, placed_on):
        """The window was dragged to `rect` on `screen` (it had opened on `placed_on`):
        remember the spot, and save it. Set to follow the game, it keeps doing so
        unless it was dragged onto another monitor, which then becomes its monitor."""
        g = screen.geometry()
        room_w, room_h = g.width() - rect.width(), g.height() - rect.height()
        self.s.position = "custom"
        self.s.x = min(max((rect.left() - g.left()) / room_w, 0.0), 1.0) if room_w > 0 else 0.5
        self.s.y = min(max((rect.top() - g.top()) / room_h, 0.0), 1.0) if room_h > 0 else 0.0
        if self.s.monitor != MONITOR_GAME or screen is not placed_on:
            self.s.monitor = screen_key(screen)
        save = getattr(self.host, "set_option", None)
        if save is not None:
            save("overlay", self.s.to_dict())
        for cb in list(self.listeners):
            cb()
        self.keep_preview()
        self._touch()

    def _end_preview(self):
        self._preview_end.stop()
        self._set_previewing(False)
        if not self.is_open and self._window is not None:
            self._window.dismiss()

    def tick(self, playing: dict):
        """Called by the main window's UI timer. Repaints only while visible."""
        w = self._window
        if w is not None and w.isVisible():
            w.set_playing(playing)

    def shutdown(self):
        for t in (self._autohide, self._close_soon, self._hold, self._preview_end):
            t.stop()
        self._set_previewing(False)
        self.is_open = False
        if self._window is not None:
            self._window.close()
            self._window.deleteLater()
            self._window = None
