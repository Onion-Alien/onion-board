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
from dataclasses import asdict, dataclass

from PySide6.QtCore import (QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRect, QRectF,
                            QEvent, QObject, QSize, Qt, QTimer)
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath,
                           QPen, QPixmap, QPolygonF)
from PySide6.QtWidgets import QApplication, QWidget

from soundboard import theme, winkeys

log = logging.getLogger(__name__)

SLOTS = 9
# key per tile, tiles in reading order (top-left first). The numpad's + and − go by
# their aliases: "num +" can't be written in a combo, where + joins the keys.
KEYSETS = {
    "digits": dict(slots=[str(i) for i in range(1, 10)],
                   prev="q", next="e", stop="0", pause=".", cat="r"),
    "numpad": dict(slots=[f"num {i}" for i in (7, 8, 9, 4, 5, 6, 1, 2, 3)],
                   prev="subtract", next="add", stop="num 0", pause="num .", cat="multiply"),
}
MODES = [("toggle", "Tap to open, tap again to close"),
         ("hold", "Hold to show, let go to hide")]
KEY_CHOICES = [("digits", "Number row 1–9  (Q / E flip pages, R category)"),
               ("numpad", "Numpad  (− / + flip pages, * category)")]
POSITIONS = [("top-left", "Top left"), ("top", "Top middle"), ("top-right", "Top right"),
             ("left", "Middle left"), ("center", "Middle"), ("right", "Middle right"),
             ("bottom-left", "Bottom left"), ("bottom", "Bottom middle"),
             ("bottom-right", "Bottom right"), ("custom", "Where I dragged it")]
# which monitor: the one the game is on, the main one, or one screen's screen_key()
MONITOR_GAME, MONITOR_PRIMARY = "game", "primary"
DRAG_START_PX = 4       # how far a press has to move before it's a drag
AUTOHIDE = [(0, "Never"), (3, "3 seconds"), (4, "4 seconds"), (6, "6 seconds"),
            (10, "10 seconds")]
CLOSE_DELAY_MS = 220    # after a pick, long enough to see the tile light up
FLASH_S = 0.25
HOLD_POLL_MS = 30


def key_label(key: str) -> str:
    k = key.replace("num ", "")
    return {"subtract": "−", "add": "+", "multiply": "*", "esc": "Esc"}.get(k, k.upper())


def pick_screen(screens, device_name: str, native_rect):
    """The QScreen for the monitor Windows describes as `device_name` (GDI, like
    '\\\\.\\DISPLAY2') at `native_rect` (left, top, width, height in physical pixels),
    or None.

    Qt 5 named screens by device, so the name matches. Qt 6 uses the monitor's
    friendly name, so the screen is found by its native geometry instead: Qt keeps
    each screen's native top-left as its logical position and scales only the size
    by devicePixelRatio. An exact position + size match wins; failing that, a size
    nobody else has is enough."""
    if device_name:
        for sc in screens:
            if sc.name() == device_name:
                return sc
    if not native_rect:
        return None
    x, y, w, h = native_rect
    same_size = []
    for sc in screens:
        g, k = sc.geometry(), sc.devicePixelRatio()
        if (round(g.width() * k), round(g.height() * k)) != (w, h):
            continue
        if (g.left(), g.top()) == (x, y):
            return sc
        same_size.append(sc)
    return same_size[0] if len(same_size) == 1 else None


def screen_key(sc) -> str:
    """How a monitor is remembered: its name plus its top-left, so two identical
    monitors (same name) are still told apart."""
    g = sc.geometry()
    return f"{sc.name()}@{g.left()},{g.top()}"


def find_screen(screens, key: str):
    """The screen saved as `key` (screen_key), or None. If the monitors were
    rearranged, a screen with the same name still counts, as long as only one has it."""
    for sc in screens:
        if screen_key(sc) == key:
            return sc
    name = key.rpartition("@")[0]
    named = [sc for sc in screens if sc.name() == name]
    return named[0] if len(named) == 1 else None


def monitor_choices(screens, primary) -> list[tuple[str, str]]:
    """(value, label) for the Settings window's monitor list."""
    out = [(MONITOR_GAME, "The one the game is on"), (MONITOR_PRIMARY, "Main monitor")]
    for i, sc in enumerate(screens, 1):
        g, k = sc.geometry(), sc.devicePixelRatio()
        main = "  (main)" if sc is primary else ""
        out.append((screen_key(sc), f"Screen {i}: {sc.name()}  "
                                    f"{round(g.width() * k)}×{round(g.height() * k)}{main}"))
    return out


def place(geo: QRect, size: QSize, s: OverlaySettings, margin: int) -> QPoint:
    """Top-left for a window of `size` on a monitor at `geo`, per the settings."""
    w, h = size.width(), size.height()
    if s.position == "custom":
        return QPoint(geo.left() + round(s.x * max(0, geo.width() - w)),
                      geo.top() + round(s.y * max(0, geo.height() - h)))
    pos = s.position
    col = "left" if pos.endswith("left") else "right" if pos.endswith("right") else ""
    row = "top" if pos.startswith("top") else "bottom" if pos.startswith("bottom") else ""
    x = {"left": geo.left() + margin, "right": geo.left() + geo.width() - margin - w}.get(
        col, geo.left() + (geo.width() - w) // 2)
    y = {"top": geo.top() + margin, "bottom": geo.top() + geo.height() - margin - h}.get(
        row, geo.top() + (geo.height() - h) // 2)
    return QPoint(x, y)


@dataclass
class OverlaySettings:
    mode: str = "toggle"            # toggle | hold
    keys: str = "digits"            # digits | numpad
    close_after_play: bool = True   # toggle mode: hide as soon as a sound is picked
    autohide: int = 4               # toggle mode: seconds untouched before it hides; 0 = never
    position: str = "top"           # one of POSITIONS; "custom" = at x, y
    monitor: str = MONITOR_GAME     # "game" | "primary" | a screen_key()
    x: float = 0.5                  # custom spot, as a fraction of the room the
    y: float = 0.0                  # monitor has around the window (0 = left / top)
    scale: int = 100                # tile size, %
    opacity: int = 85               # background, %

    @classmethod
    def from_dict(cls, d: dict | None) -> OverlaySettings:
        d, s = d or {}, cls()
        if d.get("mode") in dict(MODES):
            s.mode = d["mode"]
        if d.get("keys") in KEYSETS:
            s.keys = d["keys"]
        if isinstance(d.get("close_after_play"), bool):
            s.close_after_play = d["close_after_play"]
        if d.get("position") in dict(POSITIONS):
            s.position = d["position"]
        if isinstance(d.get("monitor"), str) and 0 < len(d["monitor"]) <= 300:
            s.monitor = d["monitor"]
        for name in ("x", "y"):
            v = d.get(name)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
                setattr(s, name, min(max(float(v), 0.0), 1.0))
        for name, lo, hi in (("autohide", 0, 60), ("scale", 60, 160), ("opacity", 30, 100)):
            v = d.get(name)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                setattr(s, name, int(min(max(v, lo), hi)))
        return s

    def to_dict(self) -> dict:
        return asdict(self)


class Overlay:
    """What the overlay does; `OverlayWindow` only draws it.

    `host` is the main window. Used: host.cfg (sounds, categories, category,
    overlay_hotkey), host.audio, host.play(sid), host.on_hotkey('__stop__' /
    '__pause__'), host.register_hotkeys() (which asks `layer()` for the extra keys),
    host.cue(kind or notes) and host.set_category(name) (the category key)."""
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
        key = (cfg.category, id(cfg.sounds), len(cfg.sounds))
        if self._sounds is None or self._sounds[0] != key:
            cat = cfg.category
            self._sounds = (key, [m for m in cfg.sounds if not cat or cat in m.tags])
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
            self.host.on_hotkey("__stop__")
            self._touch()
        elif what == "pause":
            self.host.on_hotkey("__pause__")
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
        self.host.register_hotkeys()      # claims layer()
        if self.blind:
            log.info("overlay opened without a window: a game is in exclusive fullscreen")
            self.host.cue("start")
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
        self.host.register_hotkeys()      # the keys go back to the game
        if self.blind:
            self.host.cue("stop")
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
        self.host.play(sounds[tile].id)
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
            self.host.cue(tuple(f for _ in range(min(self.page + 1, 6)) for f in (1175, 0)))
        if self._window is not None:
            self._window.update()
        self._touch()

    def next_category(self):
        """All → the first category → … → the last → All again."""
        cats = ["", *self.host.cfg.categories]
        cur = self.host.cfg.category
        i = cats.index(cur) if cur in cats else 0
        self.host.set_category(cats[(i + 1) % len(cats)])
        self.page = 0
        self.flash = None
        if self.blind:
            self.host.cue("saved")
        if self._window is not None:
            self._window.update()
        self._touch()

    # ------------------------------------------------------------------ host hooks
    def apply(self, settings: dict):
        """New settings from the Settings window."""
        self.s = OverlaySettings.from_dict(settings)
        if self.is_open:
            self.host.register_hotkeys()
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


class _AnyInput(QObject):
    """Calls `done` on the first click or key press anywhere in the app."""

    def __init__(self, done):
        super().__init__()
        self._done = done

    def eventFilter(self, obj, e):
        if e.type() in (QEvent.MouseButtonPress, QEvent.KeyPress):
            QTimer.singleShot(0, self._done)   # not from inside the event's delivery
        return False


class OverlayWindow(QWidget):
    """The HUD itself: frameless, see-through, always on top and never focused. It
    takes clicks (a tile plays, the footer buttons pause / stop), but clicking it
    never activates it, so the game keeps the keyboard."""
    TILE_W, TILE_H, GAP, PAD, HEAD, FOOT = 138, 70, 8, 14, 30, 34
    BTN_W, BTN_H = 100, 22
    MARGIN = 36   # from the screen edge

    def __init__(self, ov: Overlay):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowDoesNotAcceptFocus | Qt.NoDropShadowWindowHint)
        self.ov = ov
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle("Onion Board overlay")
        self.playing: dict = {}
        self._hover: str | None = None     # "slot:N" / "pause" / "stop" under the mouse
        self.setMouseTracking(True)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.finished.connect(self._faded)
        self._styled = False
        self._press: QPoint | None = None     # where a press on an empty part was
        self._grab: QPoint | None = None      # while dragging: that point − window pos
        self._placed_on = None                # the screen present() put it on
        self._cache_key: tuple | None = None  # what the cached layers were drawn from
        self._layers: tuple[QPixmap, QPixmap] | None = None

    # ------------------------------------------------------------------ geometry
    def _k(self) -> float:
        return self.ov.s.scale / 100

    def sizeHint(self):
        k = self._k()
        w = 2 * self.PAD + 3 * self.TILE_W + 2 * self.GAP
        h = 2 * self.PAD + self.HEAD + 3 * self.TILE_H + 2 * self.GAP + self.FOOT
        return QSize(round(w * k), round(h * k))

    def _tile_rect(self, i: int) -> QRectF:
        return QRectF(self.PAD + (i % 3) * (self.TILE_W + self.GAP),
                      self.PAD + self.HEAD + (i // 3) * (self.TILE_H + self.GAP),
                      self.TILE_W, self.TILE_H)

    def _buttons(self) -> dict[str, QRectF]:
        """The footer buttons, in the unscaled coordinates everything is painted in."""
        top = self.sizeHint().height() / self._k() - self.PAD - self.FOOT + 8
        return {"pause": QRectF(self.PAD, top, self.BTN_W, self.BTN_H),
                "stop": QRectF(self.PAD + self.BTN_W + 6, top, self.BTN_W, self.BTN_H)}

    def _hit(self, pos) -> str | None:
        k = self._k()
        pt = QPointF(pos.x() / k, pos.y() / k)
        if self.ov.sounds():
            for name, r in self._buttons().items():
                if r.contains(pt):
                    return name
        for i in range(len(self.ov.page_sounds())):
            if self._tile_rect(i).contains(pt):
                return f"slot:{i}"
        return None

    def _all_paused(self) -> bool:
        return bool(self.playing) and all(paused for _, paused in self.playing.values())

    # ------------------------------------------------------------------ mouse
    def mouseMoveEvent(self, e):
        self.ov.keep_preview()
        self.ov._touch()   # the mouse is on it: don't auto-hide from under it
        if self._press is not None and e.buttons() & Qt.LeftButton:
            at = e.globalPosition().toPoint()
            if self._grab is None and (at - self._press).manhattanLength() >= DRAG_START_PX:
                self._grab = self._press - self.pos()
                self.setCursor(Qt.ClosedHandCursor)
            if self._grab is not None:
                self.move(self._clamped(at - self._grab, at))
                self.ov._touch()
            return
        hit = self._hit(e.position())
        if hit != self._hover:
            self._hover = hit
            self.setCursor(Qt.PointingHandCursor if hit else Qt.OpenHandCursor)
            self.update()

    def _clamped(self, top_left: QPoint, cursor: QPoint) -> QPoint:
        """Keep the whole window on the monitor under the mouse."""
        sc = QGuiApplication.screenAt(cursor) or self.screen()
        if sc is None:
            return top_left
        g = sc.geometry()
        return QPoint(min(max(top_left.x(), g.left()), g.left() + g.width() - self.width()),
                      min(max(top_left.y(), g.top()), g.top() + g.height() - self.height()))

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        dragged, self._grab, self._press = self._grab is not None, None, None
        self.setCursor(Qt.PointingHandCursor if self._hover else Qt.OpenHandCursor)
        if dragged:
            geo = self.geometry()
            sc = QGuiApplication.screenAt(geo.center()) or self.screen()
            if sc is not None:
                self.ov.dropped(geo, sc, self._placed_on)

    def leaveEvent(self, e):
        if self._hover is not None:
            self._hover = None
            self.unsetCursor()
            self.update()

    def mousePressEvent(self, e):
        hit = self._hit(e.position()) if e.button() == Qt.LeftButton else None
        if hit:
            self.ov.click(hit)
            self.update()
        elif e.button() == Qt.LeftButton:     # anywhere else grabs it, to move it
            self._press = e.globalPosition().toPoint()

    def _screen(self, follow_game: bool):
        monitor = self.ov.s.monitor
        if monitor == MONITOR_GAME:
            if follow_game and QGuiApplication.platformName() == "windows":
                name, rect = winkeys.foreground_monitor_info()
                sc = pick_screen(QGuiApplication.screens(), name, rect)
                if sc is not None:
                    return sc
            return self.screen() if self.isVisible() else QGuiApplication.primaryScreen()
        if monitor != MONITOR_PRIMARY:
            sc = find_screen(QGuiApplication.screens(), monitor)
            if sc is not None:
                return sc
        return QGuiApplication.primaryScreen()   # also when that monitor is unplugged

    def _place(self, follow_game: bool):
        size = self.sizeHint()
        self.resize(size)
        sc = self._screen(follow_game)
        if sc is None:
            return
        self._placed_on = sc
        self.move(place(sc.geometry(), size, self.ov.s, round(self.MARGIN * self._k())))

    # ------------------------------------------------------------------ show / hide
    def present(self, follow_game: bool = True):
        self._place(follow_game)
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
            if not self._styled and QGuiApplication.platformName() == "windows":
                winkeys.make_overlay(int(self.winId()))
                self._styled = True
        if QGuiApplication.platformName() == "windows":
            winkeys.raise_topmost(int(self.winId()))
        self._animate(1.0, 120)
        self.update()

    def dismiss(self):
        if self.isVisible():
            self._animate(0.0, 140)

    def _animate(self, to: float, ms: int):
        self._fade.stop()
        self._fade.setDuration(ms)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(to)
        self._fade.start()

    def _faded(self):
        if self._fade.endValue() == 0.0:
            self.hide()

    def set_playing(self, playing: dict):
        """Called ~30x/s while open. Repaints only what changed: a tile whose bar moved
        a pixel or more, or that started, stopped or was paused, and the footer when
        its buttons light up or flip to Resume. A paused sound's bar doesn't move, so it
        costs nothing. (Repainting all of it every tick took ~2 ms a frame.)"""
        if not (playing or self.playing or self.ov.flash):
            return
        old, self.playing = self.playing, dict(playing)
        if self.ov.flash or self._static_key() != self._cache_key:
            self.update()   # a pick's flash, the footer, a page flip, a sound loaded …
            return
        px = self.TILE_W * self._k()
        for i, meta in enumerate(self.ov.page_sounds()[:SLOTS]):
            was, now = old.get(meta.id), self.playing.get(meta.id)
            if was == now:
                continue
            if was is not None and now is not None and was[1] == now[1] \
                    and abs(was[0] - now[0]) * px < 1:
                self.playing[meta.id] = was   # under a pixel: keep what's drawn
                continue
            self.update(self._scaled(self._tile_rect(i)))

    def _scaled(self, r: QRectF) -> QRect:
        """A rect in painted (unscaled) units → widget pixels, with room for the border."""
        k = self._k()
        return QRectF(r.left() * k, r.top() * k, r.width() * k,
                      r.height() * k).toAlignedRect().adjusted(-2, -2, 2, 2)

    # ------------------------------------------------------------------ paint
    # The parts that don't move are drawn once into two cached layers: `under` (panel,
    # header, footer, tile cards) and `over` (each tile's strip, key and name). A
    # paint just stacks under → progress bars → over → tile borders.
    THEMED = ("bg", "border", "text_hi", "muted", "card", "card_hi", "accent", "badge",
              "badge_text")

    def _flash(self) -> int | None:
        ov = self.ov
        return ov.flash[0] if ov.flash and ov.flash[1] > time.monotonic() else None

    def _static_key(self) -> tuple:
        """Everything the cached layers are drawn from."""
        ov = self.ov
        cfg, T = ov.host.cfg, theme.T
        return (self.width(), self.height(), self.devicePixelRatioF(), self.font().key(),
                ov.s.scale, ov.s.opacity, ov.s.mode, ov.s.keys, ov.page, ov.pages(),
                cfg.category, bool(cfg.categories), bool(ov.sounds()),
                tuple(T.get(t) for t in self.THEMED),
                tuple((m.id, m.name, m.color, m.id in ov.host.audio)
                      for m in ov.page_sounds()),
                self._hover, self._flash(), bool(self.playing), self._all_paused())

    def _layer(self, draw) -> QPixmap:
        dpr = self.devicePixelRatioF()
        pm = QPixmap(max(1, round(self.width() * dpr)), max(1, round(self.height() * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(self._k(), self._k())
        draw(p)
        p.end()
        return pm

    def paintEvent(self, e):
        ov, k = self.ov, self._k()
        now = time.monotonic()
        flash = self._flash()
        if flash is None:
            ov.flash = None   # over: set_playing needn't repaint for it any more
        key = self._static_key()
        if key != self._cache_key:
            self._layers = (self._layer(lambda p: self._paint_under(p, flash)),
                            self._layer(self._paint_over))
            self._cache_key = key
        under, over = self._layers
        dirty = e.rect()
        tiles = [(i, self._tile_rect(i), m) for i, m in enumerate(ov.page_sounds()[:SLOTS])]
        tiles = [t for t in tiles if dirty.intersects(self._scaled(t[1]))]
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.drawPixmap(0, 0, under)
        p.scale(k, k)
        for _, r, meta in tiles:
            self._tile_bar(p, r, meta)
        p.resetTransform()
        p.drawPixmap(0, 0, over)
        p.scale(k, k)
        for i, r, meta in tiles:
            self._tile_edge(p, r, i, meta, flash == i)
        p.end()
        if flash is not None:
            QTimer.singleShot(int((ov.flash[1] - now) * 1000) + 20, self.update)

    def _paint_under(self, p: QPainter, flash: int | None):
        ov, T = self.ov, theme.T
        W, H = self.width() / self._k(), self.height() / self._k()
        panel = QPainterPath()
        panel.addRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), 14, 14)
        bg = QColor(T["bg"])
        bg.setAlpha(round(255 * ov.s.opacity / 100))
        p.fillPath(panel, bg)
        p.setPen(QPen(QColor(T["border"]), 1))
        p.drawPath(panel)

        f = QFont(self.font())
        f.setPointSizeF(10)
        f.setBold(True)
        ks = ov.keyset
        sounds = ov.page_sounds()
        n = ov.pages()

        # header: page, and how to flip
        head = QRectF(self.PAD + 2, self.PAD - 2, W - 2 * self.PAD - 4, self.HEAD - 6)
        p.setFont(f)
        p.setPen(QColor(T["text_hi"]))
        cat = ov.host.cfg.category
        title = f"Page {ov.page + 1} of {n}" if n > 1 else "Sounds"
        if cat:
            title = f"{cat}  ·  {title}" if n > 1 else cat
        hint = f"{key_label(ks['prev'])}  ‹  ›  {key_label(ks['next'])}" if n > 1 else ""
        small = QFont(f)
        small.setBold(False)
        small.setPointSizeF(8.5)
        # a long category name ran into the page keys: it's cut with "…" before them
        room = head.width() - (QFontMetrics(small).horizontalAdvance(hint) + 12 if hint else 0)
        p.drawText(head, Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(title, Qt.ElideRight, max(0, int(room))))
        f.setBold(False)
        f.setPointSizeF(8.5)
        p.setFont(f)
        p.setPen(QColor(T["muted"]))
        if hint:
            p.drawText(head, Qt.AlignRight | Qt.AlignVCenter, hint)

        # tiles: an empty slot whole, a sound's card (the bar and the rest go on top)
        for i in range(SLOTS):
            self._tile_under(p, f, self._tile_rect(i), i,
                             sounds[i] if i < len(sounds) else None, flash == i)

        # footer: the other keys
        foot = QRectF(self.PAD + 2, H - self.PAD - self.FOOT + 6, W - 2 * self.PAD - 4,
                      self.FOOT - 6)
        f.setPointSizeF(8.5)
        p.setFont(f)
        p.setPen(QColor(T["muted"]))
        cat_key = (f"     {key_label(ks['cat'])}  category"
                   if ov.host.cfg.categories else "")
        if not ov.sounds():
            p.drawText(foot, Qt.AlignCenter,
                       f"Nothing in this category{cat_key}" if cat
                       else "No sounds yet: add some in the Sounds tab")
        else:
            btns, paused, live = self._buttons(), self._all_paused(), bool(self.playing)
            self._button(p, f, "pause", "play" if paused else "pause",
                         "Resume" if paused else "Pause", key_label(ks["pause"]), live)
            self._button(p, f, "stop", "stop", "Stop all", key_label(ks["stop"]), live)
            f.setBold(False)
            f.setPointSizeF(8.5)
            p.setFont(f)
            p.setPen(QColor(T["muted"]))
            left = btns["stop"].right() + 10
            rest = QRectF(left, btns["stop"].top(), W - self.PAD - 2 - left, self.BTN_H)
            close = "let go to close" if ov.s.mode == "hold" else "Esc  close"
            p.drawText(rest, Qt.AlignLeft | Qt.AlignVCenter, cat_key.strip())
            p.drawText(rest, Qt.AlignRight | Qt.AlignVCenter, close)

    def _paint_over(self, p: QPainter):
        f = QFont(self.font())
        for i, meta in enumerate(self.ov.page_sounds()[:SLOTS]):
            self._tile_over(p, f, self._tile_rect(i), i, meta)

    def _button(self, p: QPainter, f: QFont, name: str, icon: str, text: str, key: str,
                live: bool):
        """A footer button: icon, name, key. Dimmed while nothing is playing."""
        T = theme.T
        r = self._buttons()[name]
        hover = self._hover == name
        path = QPainterPath()
        path.addRoundedRect(r, 7, 7)
        card = QColor(T["card_hi"] if hover else T["card"])
        card.setAlpha(240)
        p.fillPath(path, card)
        p.setPen(QPen(QColor(T["accent"] if hover else T["border"]), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        ink = QColor(T["text_hi"] if live else T["muted"])
        # the icon is drawn, not a glyph: not every font has ⏸ / ⏹
        cx, cy, s = r.left() + 14, r.center().y(), 4.5
        p.setPen(Qt.NoPen)
        p.setBrush(ink)
        if icon == "pause":
            p.drawRect(QRectF(cx - s, cy - s, 3.2, 2 * s))
            p.drawRect(QRectF(cx + s - 3.2, cy - s, 3.2, 2 * s))
        elif icon == "play":
            p.drawPolygon(QPolygonF([QPointF(cx - s + 1, cy - s), QPointF(cx + s + 1, cy),
                                     QPointF(cx - s + 1, cy + s)]))
        else:
            p.drawRoundedRect(QRectF(cx - s, cy - s, 2 * s, 2 * s), 1.5, 1.5)
        body = r.adjusted(26, 0, -8, 0)
        f.setBold(True)
        f.setPointSizeF(8.5)
        p.setFont(f)
        p.setPen(ink)
        p.drawText(body, Qt.AlignLeft | Qt.AlignVCenter, text)
        if key:   # the key on a little keycap, like a pad's hotkey badge
            f.setBold(False)
            p.setFont(f)
            fm = p.fontMetrics()
            w = fm.horizontalAdvance(key) + 10
            cap = QRectF(body.right() - w, cy - fm.height() / 2 - 1, w, fm.height() + 2)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(T["badge"]))
            p.drawRoundedRect(cap, 4, 4)
            p.setPen(QColor(T["badge_text"]))
            p.drawText(cap, Qt.AlignCenter, key)

    @staticmethod
    def _path(r: QRectF) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(r, 9, 9)
        return path

    def _tile_under(self, p: QPainter, f: QFont, r: QRectF, i: int, meta, flash: bool):
        T = theme.T
        path = self._path(r)
        if meta is None:
            p.setPen(QPen(QColor(T["border"]), 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            p.setPen(QColor(T["muted"]))   # faint was unreadable (2.6:1) in some themes
            f.setBold(False)
            f.setPointSizeF(8.5)
            p.setFont(f)
            p.drawText(r.adjusted(10, 6, -8, -6), Qt.AlignLeft | Qt.AlignTop,
                       key_label(self.ov.keyset["slots"][i]))
            return
        card = QColor(T["card_hi"] if flash else T["card"])
        card.setAlpha(240)
        p.fillPath(path, card)

    def _tile_bar(self, p: QPainter, r: QRectF, meta):
        """How far the sound has got, over the card and under its name."""
        prog, paused = self.playing.get(meta.id, (None, False))
        if prog is None:
            return
        fill = QColor(meta.color)
        fill.setAlpha(45 if paused else 85)
        p.save()
        p.setClipPath(self._path(r))
        p.fillRect(QRectF(r.left(), r.top(), r.width() * max(prog, 0.02), r.height()), fill)
        p.restore()

    def _tile_over(self, p: QPainter, f: QFont, r: QRectF, i: int, meta):
        T = theme.T
        # colour strip down the left edge
        p.save()
        p.setClipPath(self._path(r))
        p.fillRect(QRectF(r.left(), r.top(), 4, r.height()), QColor(meta.color))
        p.restore()
        # key badge
        key = key_label(self.ov.keyset["slots"][i])
        f.setBold(True)
        f.setPointSizeF(8.5)
        p.setFont(f)
        badge = QRectF(r.left() + 11, r.top() + 7, max(18, p.fontMetrics().horizontalAdvance(key)
                                                       + 10), 17)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(T["badge"]))
        p.drawRoundedRect(badge, 5, 5)
        p.setPen(QColor(T["badge_text"]))
        p.drawText(badge, Qt.AlignCenter, key)
        # name
        ready = meta.id in self.ov.host.audio
        f.setPointSizeF(9.5)
        p.setFont(f)
        p.setPen(QColor(T["text_hi"] if ready else T["muted"]))
        p.drawText(r.adjusted(11, 27, -8, -5), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
                   meta.name if ready else f"{meta.name} (loading)")

    def _tile_edge(self, p: QPainter, r: QRectF, i: int, meta, flash: bool):
        T = theme.T
        prog, paused = self.playing.get(meta.id, (None, False))
        if flash:
            p.setPen(QPen(QColor(T["text_hi"]), 2.2))
        elif self._hover == f"slot:{i}":
            p.setPen(QPen(QColor(T["accent"]), 1.6))
        elif prog is not None:
            p.setPen(QPen(QColor(meta.color), 2, Qt.DashLine if paused else Qt.SolidLine))
        else:
            p.setPen(QPen(QColor(T["border"]), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(self._path(r))
