"""The in-game overlay's settings and where it goes (ui/sounds/overlay.py): its keys, modes and
positions, `OverlaySettings`, picking the monitor (the game's, the main one or a named one) and
placing it on that screen. `overlay` re-exports it all."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from PySide6.QtCore import QPoint, QRect, QSize

from soundboard.i18n import _, ngettext


SLOTS = 9
# key per tile, tiles in reading order (top-left first). The numpad's + and − go by
# their aliases: "num +" can't be written in a combo, where + joins the keys.
KEYSETS = {
    "digits": dict(slots=[str(i) for i in range(1, 10)],
                   prev="q", next="e", stop="0", pause=".", cat="r"),
    "numpad": dict(slots=[f"num {i}" for i in (7, 8, 9, 4, 5, 6, 1, 2, 3)],
                   prev="subtract", next="add", stop="num 0", pause="num .", cat="multiply"),
}
MODES = [("toggle", _("Tap to open, tap again to close")),
         ("hold", _("Hold to show, let go to hide"))]
KEY_CHOICES = [("digits", _("Number row 1–9  (Q / E flip pages, R category)")),
               ("numpad", _("Numpad  (− / + flip pages, * category)"))]
POSITIONS = [("top-left", _("Top left")), ("top", _("Top middle")),
             ("top-right", _("Top right")), ("left", _("Middle left")),
             ("center", _("Middle")), ("right", _("Middle right")),
             ("bottom-left", _("Bottom left")), ("bottom", _("Bottom middle")),
             ("bottom-right", _("Bottom right")), ("custom", _("Where I dragged it"))]
# which monitor: the one the game is on, the main one, or one screen's screen_key()
MONITOR_GAME, MONITOR_PRIMARY = "game", "primary"
DRAG_START_PX = 4       # how far a press has to move before it's a drag
AUTOHIDE = [(0, _("Never"))] + [(s, ngettext("{n} second", "{n} seconds", s))
                                 for s in (3, 4, 6, 10)]
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
    out = [(MONITOR_GAME, _("The one the game is on")), (MONITOR_PRIMARY, _("Main monitor"))]
    for i, sc in enumerate(screens, 1):
        g, k = sc.geometry(), sc.devicePixelRatio()
        size = f"{round(g.width() * k)}×{round(g.height() * k)}"
        out.append((screen_key(sc),
                    _("Screen {n}: {name}  {size}  (main)", n=i, name=sc.name(), size=size)
                    if sc is primary else
                    _("Screen {n}: {name}  {size}", n=i, name=sc.name(), size=size)))
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
