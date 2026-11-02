"""Bun's first-run tour of the empty board: half a minute to get a first sound on it.

Right after the very first setup guide (setupwizard.SetupWizard.done: a new install's
first start, never an update, a reset or a restored backup), on a board with no sounds
yet, the window dims and one card (coach.py) walks them through it:

  "welcome"  Bun on the board, lit up, the card under him: no sounds yet. Show me.
  "search"   The search box in the yellow ring: type a sound, press Enter.
  "results"  The results are up, the first one ringed: press Add on one.
  "add"      Offline mode (or every search site switched off): instead of the search
             box, the Add button, for a sound from their own files.
  "nice"     A sound arrived: one last card, any click closes it.

It can't be clicked away: a click outside the ring and the card does nothing until the
search (or Add) step, which has a quiet "OK" to put it off. Once
only (Config.tips_seen); never with tutorials switched off (Config.tutorials_on).

Anything going wrong (a search that can't get through, an error card, an error logged)
ends it at once (coach.py): it never holds anyone on something that doesn't work.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QWidget

from soundboard.online import net
from soundboard.core import usage
from soundboard.i18n import _
from soundboard.ui.setup import coach
from soundboard.ui.sounds.ytsearch import SearchResults

log = logging.getLogger(__name__)

KEY = "first-run-tour"   # in Config.tips_seen once shown
START_MS = 700           # after the setup guide closes: the window settles first

_current: Tour | None = None


def will_run(win) -> bool:
    """Would the tour run once the setup guide closes: not seen yet, no sounds yet,
    tutorials on."""
    cfg = win.cfg
    return KEY not in cfg.tips_seen and not cfg.sounds and getattr(cfg, "tutorials_on", True)


def can_search() -> bool:
    """Searching online works (not Offline mode, not every site switched off): the
    tour shows the search box, else the Add button."""
    return not net.offline() and SearchResults.available()


def _elsewhere(win) -> bool:
    """The window isn't the Sounds tab in front of them right now."""
    return (not win.isVisible() or win.isMinimized() or win.fitctl.is_mini()
            or win.tabs.currentWidget() is not win.sounds_page
            or win.setctl.settings_open()
            or QApplication.activeModalWidget() is not None)


def start(win) -> Tour | None:
    """Start the tour over `win` (the main window), if it should run now."""
    global _current
    try:
        if (_current is not None or not will_run(win) or _elsewhere(win)
                or QApplication.activePopupWidget() is not None):
            return None
    except RuntimeError:   # the window went meanwhile
        return None
    from soundboard.ui.setup import tabtours
    tabtours.stop(win)   # (one tour at a time)
    cfg = win.cfg
    cfg.tips_seen = [*cfg.tips_seen, KEY, "search"]   # (the search tip says the same)
    win._save_later()
    usage.used("tour-shown")
    _current = Tour(win)
    return _current


def stop(win=None):
    """End the tour now (tutorials switched off): put off, as with OK."""
    if _current is not None and (win is None or _current.win is win):
        _current.end("skipped")


class Tour(coach.Tour):
    """The first-run tour's steps on the real window."""

    def __init__(self, win):
        self.online = can_search()   # the search box, or (offline) the Add button
        self.bun = win.grid.bun      # Bun on the board: quiet while the card speaks
        self._bun_lines = (self.bun.lines, self.bun.hope_lines)
        self.added = False
        w = win
        welcome = coach.Step(
            _("No sounds here yet!"),
            _("Let's find your first sound. I'll show you where to look.") if self.online
            else _("Got a sound on your PC? I'll show you where it goes."),
            target=self._bun_hole, button=_("Show me"), bun=None, ring=False,
            enter=self._quiet_bun, extra={"name": "welcome"})
        if self.online:
            middle = [
                coach.Step(
                    _("Type a sound you want, then press Enter"),
                    _("Try airhorn, applause or vine boom."),
                    target=lambda: coach.rect_of(w, w.search),
                    done=lambda: bool(w.cfg.sounds) or self._results_up(),
                    skip=_("OK"), enter=self._focus_search,
                    failed=lambda: w.ytresults.failed, oops=self._oops,
                    retry=self._retry_search, page_oops=lambda: w.ytresults.oops,
                    allow=self._in_search, extra={"name": "search"}),
                coach.Step(
                    _("Pick one, you'll love it!"),
                    _("Play to hear it, Add to keep it on your board."),
                    target=self._first_result, done=lambda: bool(w.cfg.sounds),
                    skip=_("OK"), allow=self._in_results,
                    failed=lambda: w.ytresults.failed, oops=self._oops,
                    retry=self._retry_search, page_oops=lambda: w.ytresults.oops,
                    enter=self._searched,
                    extra={"name": "results", "retry_to": "search"}),
            ]
        else:
            middle = [coach.Step(
                _("Add a sound from your PC"),
                _("Click Add, then Sound files, and pick a sound file you have."),
                target=lambda: coach.rect_of(w, w.btn_add), done=lambda: bool(w.cfg.sounds),
                skip=_("OK"), extra={"name": "add"})]
        nice = coach.Step(
            _("Nice, that's your first sound!"),
            _("Click it to play it. Each tab shows you a quick how-to like this the first "
              "time you open it."),
            target=lambda: coach.rect_of(w, w.grid), button=_("Done"), blocks=False,
            bun="star", enter=self._got_one, extra={"name": "nice"})
        super().__init__(win, [welcome, *middle, nice])

    # ------------------------------------------------------------------ the window
    def showing(self) -> bool:
        return not _elsewhere(self.win)

    def _tick(self):
        super()._tick()
        if self.ended or self.step is None:
            return
        try:   # the results closed without a pick: back to the search box
            if self.step.extra.get("name") == "results" and not self._results_up() \
                    and not self.win.cfg.sounds:
                self.go_to("search")
        except RuntimeError:
            self.end("left")

    def finished(self, how: str):
        global _current
        if _current is self:
            _current = None
        try:
            self._bun_back()
        except RuntimeError:   # the board went first (the window closing)
            pass
        if how == "skipped" and not self.added:
            usage.used("tour-skipped")
        elif how == "failed" and not self.added:
            usage.used("tour-failed")

    # ------------------------------------------------------------------ steps' parts
    def _quiet_bun(self):
        self.bun.lines, self.bun.hope_lines = (), ()
        self.bun.say = ""   # (calm: hope() would keep him hopping the whole tour)

    def _bun_back(self):
        """The board's Bun back to his own lines and mood."""
        if self.bun.lines == () and self._bun_lines is not None:
            self.bun.lines, self.bun.hope_lines = self._bun_lines

    def _searched(self):
        if self._results_up():
            usage.used("tour-searched")

    def _oops(self) -> str:
        return _("The search couldn't get through.")

    def _retry_search(self):
        """Try again: the search box again, ready for Enter (the same words)."""
        self.win.ytresults.failed = False

    def _focus_search(self):
        self.win.search.setFocus()

    def _got_one(self):
        self.added = True
        usage.used("tour-files" if not self.online else "tour-added")

    def _bun_hole(self) -> list[QRect]:
        """The board's Bun, lit up: the card speaks for him."""
        r = coach.rect_of(self.win, self.bun)
        if not r:
            return []
        b = r[0]
        half = min(b.width() // 2, 90)
        return [QRect(b.center().x() - half, b.top(), 2 * half, b.height())]

    def _results_up(self) -> bool:
        res = self.win.ytresults
        return not res.isHidden() and bool(res._rows)

    def _first_result(self) -> list[QRect]:
        res = self.win.ytresults
        rows = [r for r in res._rows if r.isVisible()] if not res.isHidden() else []
        return coach.rect_of(self.win, rows[0]) if rows else []

    def _in_results(self, obj: QWidget) -> bool:
        """Anything in the results panel (another result, its scroll bar, Close)."""
        res = self.win.ytresults
        return obj is res or res.isAncestorOf(obj) or self._in_search(obj)

    def _in_search(self, obj: QWidget) -> bool:
        """The search box, its clear button, or the site button next to it."""
        w = self.win
        return any(obj is b or b.isAncestorOf(obj) for b in (w.search, w.btn_yt))
