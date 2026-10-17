"""Each tab's quick how-to, the first time it's opened: the window dims, the thing to use
sits in the yellow ring, and one card (coach.py) says what to do. It stays until they've
done it (played a station on the globe, sent a program, picked a voice…) or pressed
its "Not now", which shows after a moment, or something went wrong (a station that
won't play: it ends at once, coach.py); either way it never comes back
(Config.tips_seen). One
step each, a few seconds long.

Radio, Apps, Triggers, Voice and Store have one; Sounds has the first-run tour
(firsttour.py) and Setup its own guide. None with tutorials switched off
(Config.tutorials_on, Settings > General), none during the first-run tour or the setup
guide, and none for tabs an older version already had (library.Config.from_raw marks
those seen: they've been there).
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QRect, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from soundboard import usage
from soundboard.library import TOUR_TABS
from soundboard.i18n import _
from soundboard.ui import busy, coach

log = logging.getLogger(__name__)

TABS = TOUR_TABS
START_MS = 450   # after the tab opens: it lays itself out first

_current: TabTour | None = None


def key(tab: str) -> str:
    """The tab's tour in Config.tips_seen once done or put off."""
    return f"tour-{tab}"


def seen_all(cfg):
    """Mark every tab's tour seen (an update from a version without them)."""
    cfg.tips_seen = [*cfg.tips_seen, *(key(t) for t in TABS if key(t) not in cfg.tips_seen)]


def _widget(win, tab: str) -> QWidget | None:
    return getattr(win, tab, None)


def _tab_of(win, page: QWidget | None) -> str:
    """Which of TABS `page` (the tab widget's current page) is, or ""."""
    if page is None:
        return ""
    for t in TABS:
        w = _widget(win, t)
        if w is not None and (w is page or page.isAncestorOf(w)):
            return t
    return ""


def would_run(win, tab: str) -> bool:
    cfg = win.cfg
    if tab not in TABS or not getattr(cfg, "tutorials_on", True) or not cfg.setup_done \
            or key(tab) in cfg.tips_seen:
        return False
    w = _widget(win, tab)
    # a tab switched off is a stand-in (taboff), with nothing to show
    return w is not None and type(w).__name__ not in ("TabOff", "VoiceOff", "RadioOff")


def hook(win):
    """Watch the window's tab changes: a tab opened for the first time gets its tour."""
    win.tabs.currentChanged.connect(lambda _i, w=win: QTimer.singleShot(
        START_MS, w, lambda: maybe_start(w)))


def maybe_start(win) -> TabTour | None:
    """Start the open tab's tour, if it hasn't had one and nothing's in the way."""
    global _current
    from soundboard.ui import firsttour
    try:
        tab = _tab_of(win, win.tabs.currentWidget())
        if (not tab or _current is not None or firsttour._current is not None
                or not would_run(win, tab) or _blocked(win)):
            return None
        steps = _steps(win, tab)
    except RuntimeError:   # the window went meanwhile
        return None
    if not steps:
        return None
    usage.used(f"tour-{tab}-shown")
    _current = TabTour(win, tab, steps)
    return _current


def stop(win=None):
    """End the running tab tour (tutorials switched off, the first-run tour starting):
    it'll come again next time unless tutorials are off."""
    if _current is not None and (win is None or _current.win is win):
        _current.end("left")


def _blocked(win) -> bool:
    return (not win.isVisible() or win.isMinimized() or win.fitctl.is_mini()
            or win.setctl.settings_open() or QApplication.activeModalWidget() is not None
            or QApplication.activePopupWidget() is not None)


# ---------------------------------------------------------------------- the steps
def _steps(win, tab: str) -> list[coach.Step]:
    w = _widget(win, tab)
    make: dict[str, Callable[[], list[coach.Step]]] = {
        "radio": lambda: _radio(win, w), "apps": lambda: _apps(win, w),
        "triggers": lambda: _triggers(win, w), "voice": lambda: _voice(win, w),
        "store": lambda: _store(win, w)}
    return make[tab]()


def _inside(*parents) -> Callable[[QWidget], bool]:
    """A click may land anywhere in these too (another row, a scroll bar)."""
    def allow(obj: QWidget) -> bool:
        return any(p is not None and (obj is p or p.isAncestorOf(obj)) for p in parents)
    return allow


def _radio(win, tab) -> list[coach.Step]:
    def globe() -> list[QRect]:
        """The globe (the map of stations), else the station list beside it."""
        return (coach.rect_of(win, getattr(tab, "flat", None))
                or coach.rect_of(win, getattr(tab, "station_panel", None)))
    return [coach.Step(
        _("Pick a station on the globe"),
        _("Click any dot to play that station. Press Send to others and your call hears it too."),
        target=globe, done=tab.is_active, skip=_("Not now"),
        failed=lambda: bool(getattr(tab, "_globe_error", "")),   # no stations to pick
        allow=_inside(getattr(tab, "station_panel", None), getattr(tab, "btn_play", None)))]


def _apps(win, tab) -> list[coach.Step]:
    def area() -> list[QRect]:
        """The first program's Send button, else the list (it says to start something)."""
        rows = sorted((r for r in tab.rows.values() if r.isVisible()),
                      key=lambda r: r.mapTo(win, r.rect().topLeft()).y())
        if rows:
            return coach.rect_of(win, rows[0].btn_send)
        return coach.rect_of(win, tab.empty) or coach.rect_of(win, tab.scroll_area)
    return [coach.Step(
        _("Send a program's sound"),
        _("Start some music or a game, then press Send on it. Everyone in your call hears "
          "it."),
        target=area, done=tab.is_active, skip=_("Not now"), allow=_inside(tab.scroll_area))]


def _triggers(win, tab) -> list[coach.Step]:
    got = {"get": False}
    btn = getattr(tab, "btn_get", None)
    if getattr(tab, "panel", None) is None and btn is not None:   # not installed yet
        btn.clicked.connect(lambda: got.__setitem__("get", True))
        return [coach.Step(
            _("Get the free Onion Watch add-on"),
            _("It watches your game and plays a sound when something shows up, like "
              "“YOU DIED”."),
            target=lambda: coach.rect_of(win, btn),
            done=lambda: got["get"] or getattr(tab, "panel", None) is not None,
            skip=_("Not now"))]
    return [coach.Step(
        _("Turn on a trigger"),
        _("Pick what to watch for on your screen, then switch it on."),
        target=lambda: coach.rect_of(win, tab),
        done=lambda: bool(getattr(tab, "is_active", lambda: False)()), skip=_("Not now"))]


def _voice(win, panel) -> list[coach.Step]:
    picked = {"on": False}
    fx = getattr(panel, "fx", None)
    if fx is None:
        return []
    fx.tiles.buttonClicked.connect(lambda _b: picked.__setitem__("on", True))

    def first_row() -> list[QRect]:
        tiles = [t for t in fx._tile.values() if t.isVisible()]
        if not tiles:
            return coach.rect_of(win, fx)
        top = min(t.mapTo(win, t.rect().topLeft()).y() for t in tiles)
        return coach.united(win, [t for t in tiles
                                  if t.mapTo(win, t.rect().topLeft()).y() == top])

    def show_fx():
        if getattr(panel, "current_tab", lambda: "fx")() != "fx":
            panel.show_tab("fx")
    return [coach.Step(
        _("Pick a voice"),
        _("Click one, then talk: you hear yourself in your headphones."),
        target=first_row, done=lambda: picked["on"] or panel.is_active(),
        skip=_("Not now"), enter=show_fx, allow=_inside(fx))]


def _store(win, tab) -> list[coach.Step]:
    count = len(win.cfg.sounds)

    def first() -> list[QRect]:
        rows = [r for r in getattr(tab, "_rows", []) if r.isVisible()]
        return coach.rect_of(win, rows[0]) if rows else coach.rect_of(win, tab.list_area)
    return [coach.Step(
        _("Hear one, then add it"),
        _("Press play to hear a sound. Add puts it on your board."),
        target=first, done=lambda: len(win.cfg.sounds) > count, skip=_("Not now"),
        allow=_inside(tab.list_area))]


class TabTour(coach.Tour):
    """One tab's tour on the real window."""

    def __init__(self, win, tab: str, steps: list[coach.Step]):
        self.tab = tab
        self.page = _widget(win, tab)
        super().__init__(win, steps)

    def showing(self) -> bool:
        w = self.win
        return (w.isVisible() and not w.isMinimized() and not w.fitctl.is_mini()
                and not w.setctl.settings_open()
                and QApplication.activeModalWidget() is None)

    def leave(self) -> bool:
        """Another tab's in front (it only gets there by a key or the app itself):
        this one comes back next time."""
        return _tab_of(self.win, self.win.tabs.currentWidget()) != self.tab

    def finished(self, how: str):
        global _current
        if _current is self:
            _current = None
        if how == "left":
            return   # not seen: next time
        # (failed: something went wrong, a station that won't play: it doesn't come back
        # to hold them on it again)
        cfg = self.win.cfg
        if key(self.tab) not in cfg.tips_seen:
            cfg.tips_seen = [*cfg.tips_seen, key(self.tab)]
            self.win._save_later()
        usage.used(f"tour-{self.tab}-{how}")
        if how == "done":
            busy.toast(self.win, _("Nice, you've got it!"), "ok")
