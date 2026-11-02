"""Each tab's quick how-to, the first time it's opened: the window dims, the thing to use
sits in the yellow ring, and one card (coach.py) says what to do. It stays until they've
done it (played a station on the globe, sent a program, picked a voice…) or pressed
its "OK", or something went wrong (a station that
won't play: it ends at once, coach.py); either way it never comes back
(Config.tips_seen). One
step each, a few seconds long.

Radio, Apps, Voice and Store have one (Triggers has none: its page says it all);
Sounds has the first-run tour (firsttour.py) and Setup its own guide. None with
tutorials switched off (Config.tutorials_on, Settings > General), none during the
first-run tour or the setup guide (and "OK" twice inside QUIT_S switches them off:
they're clicking around, not learning), and none for tabs an older version already had
(library.Config.from_raw marks those seen: they've been there).
"""
from __future__ import annotations

import html
import logging
import time
from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QRect, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from soundboard.core import usage
from soundboard.sounds.library import TOUR_TABS
from soundboard.i18n import _
from soundboard.ui.kit import busy
from soundboard.ui.setup import coach

log = logging.getLogger(__name__)

TABS = TOUR_TABS
START_MS = 450   # after the tab opens: it lays itself out first
QUIT_S = 60      # "OK" twice this close together: no more tours
EMPTY_S = 6      # Apps with no program making sound this long: the tour says so
SETTLE_S = 1.2   # a voice picked: on this long without a problem before it's "done"

_current: TabTour | None = None


def key(tab: str) -> str:
    """The tab's tour in Config.tips_seen once done or put off."""
    return f"tour-{tab}"


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


class _Clicks(QObject):
    """A click on the window while a tab's tour waits to start (START_MS): that tab is in
    use, so its tour waits for the next visit (the tour switched the Voice tab back to
    Voice changer under a click on Clean mic's switch, and that click was lost). Watches
    the app's input only during that wait, never all the time."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.clicked = False
        self._on = False

    def watch(self):
        self.clicked = False
        if not self._on:
            QApplication.instance().installEventFilter(self)
            self._on = True

    def unwatch(self):
        if self._on:
            QApplication.instance().removeEventFilter(self)
            self._on = False

    def eventFilter(self, obj, ev):   # noqa: N802 - Qt
        if (ev.type() == QEvent.Type.MouseButtonPress and isinstance(obj, QWidget)
                and obj.window() is self.win):
            self.clicked = True
        return False


def hook(win):
    """Watch the window's tab changes: a tab opened for the first time gets its tour."""
    clicks = win._tour_clicks = _Clicks(win)

    def opened(_i):
        # (deferred: the click that switched the tab is still being handled)
        QTimer.singleShot(0, win, clicks.watch)
        QTimer.singleShot(START_MS, win, lambda: maybe_start(win))
    win.tabs.currentChanged.connect(opened)


def _clicked_meanwhile(win) -> bool:
    """A click on the window since its tab opened (not the one that opened it)."""
    clicks = getattr(win, "_tour_clicks", None)
    if clicks is None:
        return False
    clicks.unwatch()
    return clicks.clicked


def hold(win, tab: str):
    """`tab` is about to open on one thing (Open Clean mic, from a setup box): no tour
    on this visit, it comes the next time the tab opens."""
    win.tour_held = tab


def maybe_start(win) -> TabTour | None:
    """Start the open tab's tour, if it hasn't had one and nothing's in the way."""
    global _current
    from soundboard.ui.setup import firsttour
    clicked = _clicked_meanwhile(win)   # (stops watching, whatever happens next)
    try:
        tab = _tab_of(win, win.tabs.currentWidget())
        if tab and tab == getattr(win, "tour_held", ""):
            return None
        if tab and clicked:   # busy on it already: its tour comes next time
            return None
        win.tour_held = ""   # (left the held tab: its tour can come next time)
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
        "voice": lambda: _voice(win, w), "store": lambda: _store(win, w)}
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
        target=globe, done=tab.is_active, skip=_("OK"),
        failed=lambda: bool(getattr(tab, "_globe_error", "")),   # no stations to pick
        oops=lambda: getattr(tab, "_globe_error", "") or _("The stations couldn't load."),
        oops_title=_("The radio couldn't connect"), retry=getattr(tab, "_reload", None),
        page_oops=lambda: getattr(getattr(tab, "flat", None), "oops", None),
        allow=_inside(getattr(tab, "station_panel", None), getattr(tab, "btn_play", None)))]


def _apps(win, tab) -> list[coach.Step]:
    def area() -> list[QRect]:
        """The first program's Send button, else the list (it says to start something)."""
        rows = sorted((r for r in tab.rows.values() if r.isVisible()),
                      key=lambda r: r.mapTo(win, r.rect().topLeft()).y())
        if rows:
            return coach.rect_of(win, rows[0].btn_send)
        return coach.rect_of(win, tab.empty) or coach.rect_of(win, tab.scroll_area)
    since = {"at": time.monotonic()}

    def nothing() -> bool:
        """No program making sound, EMPTY_S after the step showed (or Try again)."""
        if any(r.isVisible() for r in tab.rows.values()):
            since["at"] = time.monotonic()
            return False
        return time.monotonic() - since["at"] > EMPTY_S
    return [coach.Step(
        _("Send a program's sound"),
        _("Start some music or a game, then press Send on it. Everyone in your call hears "
          "it."),
        target=area, done=tab.is_active, skip=_("OK"), allow=_inside(tab.scroll_area),
        failed=nothing, retry=lambda: since.__setitem__("at", time.monotonic()),
        oops_title=_("Nothing to share yet"),
        oops=_("No program is making sound right now. Start some music or a game, then "
               "press Try again."), extra={"calm": True})]


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
    def problem() -> str:
        return getattr(panel, "problem", lambda: "")()
    on_since: dict[str, float | None] = {"at": None}

    def working() -> bool:
        """Picked and on for SETTLE_S without a problem (the mic opening, an effect
        breaking can take a moment to show)."""
        if not (picked["on"] or panel.is_active()) or problem():
            on_since["at"] = None
            return False
        if on_since["at"] is None:
            on_since["at"] = time.monotonic()
        return time.monotonic() - on_since["at"] >= SETTLE_S
    return [coach.Step(
        _("Pick a voice"),
        _("Click one, then talk: you hear yourself in your headphones."),
        target=first_row, done=working, skip=_("OK"), enter=show_fx,
        allow=_inside(fx, getattr(panel, "oops", None)),
        failed=lambda: bool(problem()), oops=lambda: html.unescape(problem()),
        oops_title=_("Your voice couldn't be switched on"),
        retry=getattr(panel, "try_again", None),
        page_oops=lambda: getattr(panel, "oops", None))]


def _store(win, tab) -> list[coach.Step]:
    # Play or Add pressed here, not the board growing: a sound arriving from anywhere
    # else (a download, an import finishing) ended it the moment it showed
    count = getattr(tab, "used", 0)

    def first() -> list[QRect]:
        rows = [r for r in getattr(tab, "_rows", []) if r.isVisible()]
        return coach.rect_of(win, rows[0]) if rows else coach.rect_of(win, tab.list_area)
    return [coach.Step(
        _("Hear one, then add it"),
        _("Press play to hear a sound. Add puts it on your board."),
        target=first, done=lambda: getattr(tab, "used", 0) > count, skip=_("OK"),
        allow=_inside(tab.list_area, getattr(tab, "oops_page", None)),
        failed=lambda: bool(getattr(tab, "failed", False)),
        oops_title=_("The store couldn't load"),
        oops=_("The community sounds couldn't be listed."),
        retry=getattr(tab, "reload", None), page_oops=lambda: getattr(tab, "oops", None))]


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
        elif how == "skipped":
            self._skipped()

    def _skipped(self):
        """Put off twice inside QUIT_S (hopping through the tabs): switch the rest off,
        as Settings > General > Show tutorials does, which also brings them back."""
        w = self.win
        now = time.monotonic()
        last = getattr(w, "_tour_skipped_at", None)
        w._tour_skipped_at = now
        if last is None or now - last > QUIT_S:
            return
        w.tipctl.set_tutorials_on(False)
        usage.used("tours-quit")
        busy.toast(w, _("Tutorials are off now. Settings → General turns them back on."), ms=6000)
