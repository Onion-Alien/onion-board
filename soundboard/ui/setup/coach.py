"""Short guided tours ("tutorials"): the window dims, what to use next sits in a yellow
ring, and one card beside it (Bun, a title, a line, the step dots and its buttons) says
what to do. The first-run tour of the empty board (firsttour.py) and each tab's first
visit (tabtours.py) are built from it.

A tour is a few `Step`s. A plain step has one button ("Let's go"). An action step waits
until the person has done the thing (`done()` turns true: searched, played a station);
it's the one place the tour can be put off, with a quiet "Not now" that shows up after
SKIP_MS, so clicking through without reading doesn't skip it.

Until then the tour keeps the window to itself: a click outside the ring and the card
does nothing (the card gives a little shake and the ring flashes), and so does a key
outside them. The overlay never takes a click itself (WA_TransparentForMouseEvents): it
watches the app's input (eventFilter) and lets through what lands in a ring, the card,
or another window (a menu, a file picker, a dialog the ring's button opened).

Something going wrong stops it at once, so nobody is held on a thing that doesn't
work (a station that won't play, a search that can't get through): an "error" or
"warn" card (toast.PROBLEM_HOOKS), an error logged anywhere in the app, or a step's own
`failed()`. The card then turns red, Bun goes sad, and it says what didn't work (the
step's `oops`) and what to do (oops.py): Try again (the step once more; its `retry()`
redoes what failed), close and reopen the app, or Report a problem. The window isn't
held meanwhile (no dimming, clicks go through); Close ends the tour ("failed").
When the page shows its own red card (the step's `page_oops`: the search results', the
store's), that one speaks and the tour's card steps aside; its Try again carries the
tour on.

While the window isn't showing the tour's page (minimised, mini mode, Settings, a
dialog in front) the tour hides and waits; `leave()` says when it's gone for good.
"""
from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QFrame, QGraphicsDropShadowEffect, QHBoxLayout,
                               QLabel, QPushButton, QVBoxLayout, QWidget)

from soundboard.ui.kit import theme
from soundboard.i18n import _
from soundboard.ui.kit import oops, toast
from soundboard.ui.bunnywidget import BunnyWidget

log = logging.getLogger(__name__)

TICK_MS = 120        # follows the window (sizes, results, tab) this often
ARM_MS = 600         # a step's button ignores clicks this long after it shows
SKIP_MS = 2500       # "Not now" shows this long after an action step starts
SHAKE_MS = 420       # the card's shake when a click lands outside
FLASH_MS = 700       # ... and the ring's flash
# the ring round what to use next: a fixed yellow, drawn on the dimmed window (so the
# same in every theme), as asked for: "a yellow border around the search bar"
RING = QColor("#ffd23f")
DIM = 150            # how dark the rest of the window gets (of 255)
PAD = 6              # the ring this far outside what it rings
CARD_W = 360         # the card's width at most (less in a small window)
CARD_W_RED = 440     # ... red: three buttons (Report a problem, Close, Try again)
EDGE = 12            # the card keeps this far in from the window's edges
GAP = 16             # between the card and what it points at (its arrow spans it)
ARROW = 9            # the arrow's half width at the card's edge
RETRY_MS = 1500      # after Try again, a step's own failed() isn't asked this long

_running: list[Tour] = []


def abort(_kind: str = ""):
    """Something went wrong: every tour that's up ends now."""
    for t in list(_running):
        t.end("failed")


toast.PROBLEM_HOOKS.append(abort)


class _Errors(logging.Handler):
    """An error logged anywhere while a tour is up (any thread): the tour's next tick
    ends it. Only a flag here: Qt isn't touched off the UI thread."""

    def __init__(self):
        super().__init__(logging.ERROR)
        self.seen = False

    def emit(self, record):
        if not record.name.startswith(__name__):   # (its own log lines aren't news)
            self.seen = True


_errors = _Errors()


CARD_STYLE = """
QFrame#coachcard {{ background:{panel}; border:1px solid {border};
    border-radius:14px; }}
QFrame#coachcard QLabel {{ background:transparent; }}
QFrame#coachcard QLabel#coachtitle {{ font-size:13pt; font-weight:700; color:{text_hi}; }}
QFrame#coachcard QLabel#coachbody {{ color:{text}; }}
QFrame#coachcard[problem="true"] {{ border:2px solid {error_text}; }}
QFrame#coachcard[problem="true"] QLabel#coachtitle {{ color:{error_text}; }}
"""


@dataclass
class Step:
    """One step of a tour. `target()`: the rects to ring, in the window's coordinates
    (the first one is what the card points at; empty = nothing to point at, the card
    sits in the middle). `done()`: an action step's test, polled; true = on to the next
    step. `button`: a plain step's button (the step moves on when it's pressed). `allow`:
    a widget a click may also reach (the search box's own site menu…)."""
    title: str
    body: str
    target: Callable[[], list[QRect]] = lambda: []
    done: Callable[[], bool] | None = None
    button: str = ""
    skip: str = ""
    failed: Callable[[], bool] | None = None   # polled; true = it can't work: the red card
    oops: Callable[[], str] | str = ""   # the red card's line: what didn't work
    oops_title: str = ""    # ... and its title ("" = That didn't work)
    retry: Callable[[], None] | None = None   # Try again: redo what failed (reload the list)
    page_oops: Callable[[], QWidget | None] | None = None   # the page's own red card
    enter: Callable[[], None] | None = None
    allow: Callable[[QWidget], bool] | None = None
    bun: str | None = "star"
    blocks: bool = True     # False: a click anywhere ends the step (a last "Nice!" card)
    ring: bool = True       # False: the target's only lit up, no yellow ring (Bun himself)
    extra: dict = field(default_factory=dict)


def rect_of(win: QWidget, *widgets: QWidget | None) -> list[QRect]:
    """The visible ones of `widgets` as rects in `win`'s coordinates (one each)."""
    out = []
    for w in widgets:
        try:
            if w is None or not w.isVisible() or w.width() <= 0 or w.height() <= 0:
                continue
            seen = w.visibleRegion().boundingRect()   # (a row half scrolled away)
            if seen.isEmpty():
                continue
            out.append(seen.translated(w.mapTo(win, QPoint(0, 0))))
        except RuntimeError:   # freed meanwhile
            continue
    return out


def united(win: QWidget, widgets) -> list[QRect]:
    """One rect round all the visible `widgets` (e.g. the first row of voice tiles)."""
    rs = rect_of(win, *widgets)
    if not rs:
        return []
    r = rs[0]
    for o in rs[1:]:
        r = r.united(o)
    return [r]


class _Dots(QWidget):
    """The step dots: the one you're on long and in the accent."""

    def __init__(self, total: int, parent=None):
        super().__init__(parent)
        self.total, self.at = total, 0
        self.setFixedSize(max(0, total * 12 + 8), 10)
        self.setVisible(total > 1)

    def paintEvent(self, ev):   # noqa: N802 - Qt
        try:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            x = 0.0
            for i in range(self.total):
                on = i == self.at
                w = 18.0 if on else 6.0
                p.setBrush(QColor(theme.T["accent"] if on else theme.T["faint"]))
                p.drawRoundedRect(QRectF(x, 2, w, 6), 3, 3)
                x += w + 6
            p.end()
        except Exception:  # noqa: BLE001 - never raise from a Qt override (AGENT-RULES)
            log.exception("tour: dots")


class Card(QFrame):
    """The tour's one card: Bun on the left, then the dots, the title, the line and
    the buttons. A child of the window, above the dimmed layer."""

    def __init__(self, win: QWidget, total: int):
        super().__init__(win)
        self.setObjectName("coachcard")
        self.setStyleSheet(CARD_STYLE.format(**theme.T))
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.setGraphicsEffect(shadow)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 14, 16, 14)
        row.setSpacing(12)
        self.bun = BunnyWidget("star", height=64, pad=4, parent=self)
        self.bun.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(self.bun, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(6)
        self.dots = _Dots(total, self)
        col.addWidget(self.dots)
        self.title = QLabel()
        self.title.setObjectName("coachtitle")
        self.title.setWordWrap(True)
        col.addWidget(self.title)
        self.body = QLabel()
        self.body.setObjectName("coachbody")
        self.body.setWordWrap(True)
        col.addWidget(self.body)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 6, 0, 0)
        buttons.setSpacing(8)
        buttons.addStretch(1)
        self.btn_report = QPushButton(_("Report a problem"))
        self.btn_report.setProperty("quiet", True)
        self.btn_report.setObjectName("coachreport")
        self.btn_report.hide()   # the red card's
        buttons.addWidget(self.btn_report)
        self.btn_skip = QPushButton()
        self.btn_skip.setProperty("quiet", True)
        self.btn_skip.setObjectName("coachskip")
        buttons.addWidget(self.btn_skip)
        self.btn_go = QPushButton()
        self.btn_go.setObjectName("primary")
        buttons.addWidget(self.btn_go)
        col.addLayout(buttons)
        row.addLayout(col, 1)
        self._fit_for: tuple = ()
        self.failing = False   # the red card (wider: three buttons)

    def _problem(self, on: bool):
        if bool(self.property("problem")) != on:
            self.setProperty("problem", on)
            for w in (self, self.title):
                w.style().unpolish(w)
                w.style().polish(w)
        self.bun.sad = 1.0 if on else 0.0
        self.bun.sulk = on
        self.bun.prop = self.bun._home_prop = None if on else "star"   # (no star when sad)
        self.btn_report.setVisible(on)

    def fail(self, step: Step, own: bool = True):
        """The red card: sad Bun, what didn't work and what to do about it (`own`: the
        step's own failed() said so, so its own words; else something elsewhere)."""
        self._problem(not step.extra.get("calm"))   # calm: nothing broke, no red
        self.bun.sad, self.bun.sulk = 1.0, True
        self.bun.prop = self.bun._home_prop = None
        self.failing = True
        self.btn_report.setVisible(not step.extra.get("calm"))
        self.dots.hide()
        line = (step.oops() if callable(step.oops) else step.oops) if own else ""
        self.title.setText((step.oops_title if own else "") or _("That didn't work"))
        line = line or _("Something went wrong.")
        self.body.setText(line if step.extra.get("calm") else oops.with_hint(line))
        self.body.show()
        self.btn_go.setText(_("Try again"))
        self.btn_go.show()
        self.btn_skip.setText(_("Close"))
        self.btn_skip.show()
        self.bun.show()

    def fill(self, step: Step, at: int):
        self._problem(False)
        self.failing = False
        self.dots.at = at
        self.dots.setVisible(self.dots.total > 1 and step.blocks)
        self.dots.update()
        self.title.setText(step.title)
        self.body.setText(step.body)
        self.body.setVisible(bool(step.body))
        self.btn_go.setText(step.button)
        self.btn_go.setVisible(bool(step.button))
        self.btn_skip.setText(step.skip)
        self.btn_skip.hide()   # an action step shows it after SKIP_MS
        self.bun.setVisible(step.bun is not None)

    def fit(self, max_w: int):
        """As wide as CARD_W (less in a small window), as tall as the words need."""
        w = max(220, min(CARD_W_RED if self.failing else CARD_W, max_w))
        key = (w, self.title.text(), self.body.text(), self.btn_skip.isVisible(),
               self.btn_report.isVisible())
        if self.width() != w or self._fit_for != key:
            self._fit_for = key
            self.setFixedWidth(w)
            lay = self.layout()
            if lay is not None:
                lay.invalidate()   # (the words just changed)
                lay.activate()
            h = (lay.totalHeightForWidth(w) if lay is not None and lay.hasHeightForWidth()
                 else self.sizeHint().height())
            self.setFixedHeight(max(h, self.minimumSizeHint().height()))


class Tour(QWidget):
    """The dimmed layer over the window and its rings, plus the card. Subclasses (or
    callers) give the steps and what "showing" means (`showing()`), and hear when it's
    over (`finished(how)`: "done", "skipped" or "left")."""

    def __init__(self, win: QWidget, steps: list[Step]):
        super().__init__(win)
        self.win: Any = win   # the MainWindow (its parts: cfg, tabs, search…)
        self.steps = steps
        self.at = -1
        self.step: Step | None = None
        self._ended = False
        self._hidden = False
        self._step_at = 0.0
        self._shake_at = -1e9
        self.failing = False     # the red card's up (something didn't work)
        self._retry_at = -1e9
        self._page_said = False  # the page's own red card was up (step.page_oops)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setGeometry(win.rect())
        self.card = Card(win, sum(1 for s in steps if s.blocks))
        self.card.btn_go.clicked.connect(self._pressed_go)
        self.card.btn_skip.clicked.connect(self._pressed_skip)
        self.card.btn_report.clicked.connect(self._report)
        if not _running:
            _errors.seen = False
            logging.getLogger().addHandler(_errors)
        _running.append(self)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(TICK_MS)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self.show()
        self.card.show()
        self.go(0)

    # ------------------------------------------------------------------ for callers
    def showing(self) -> bool:
        """The window shows the tour's page right now (else the tour hides and waits)."""
        w = self.win
        return w.isVisible() and not w.isMinimized() \
            and QApplication.activeModalWidget() is None

    def leave(self) -> bool:
        """The tour should end now without being done (its page is gone)."""
        return False

    def finished(self, how: str):
        """Over: "done", "skipped", "failed" (something went wrong) or "left"."""

    def entered(self, step: Step):
        """A step just showed."""

    # ------------------------------------------------------------------ steps
    def go(self, i: int):
        if self._ended:
            return
        if i >= len(self.steps):
            self.end("done")
            return
        self.at = i
        self.step = s = self.steps[i]
        self._step_at = time.monotonic()
        dot = sum(1 for st in self.steps[:i] if st.blocks)
        self.card.fill(s, min(dot, max(0, self.card.dots.total - 1)))
        if s.done is not None and s.skip:
            QTimer.singleShot(SKIP_MS, self, lambda st=s: self._show_skip(st))
        if s.enter is not None:
            s.enter()
        self.entered(s)
        self._place()

    def go_to(self, name: str):
        """To the step whose extra["name"] is `name`."""
        for i, s in enumerate(self.steps):
            if s.extra.get("name") == name:
                self.go(i)
                return

    def _show_skip(self, step: Step):
        if not self._ended and self.step is step:
            self.card.btn_skip.show()
            self._place()

    def _pressed_go(self):
        if time.monotonic() - self._step_at < ARM_MS / 1000:
            return   # a click meant for what was there before
        if self.failing:
            self.try_again()
            return
        self.go(self.at + 1)

    def _pressed_skip(self):
        self.end("failed" if self.failing else "skipped")

    # ------------------------------------------------------------------ the red card
    def fail(self, own: bool = False):
        """Something didn't work: the red card, until Try again or Close (`own`: the
        step's own failed() said so)."""
        if self._ended or self.failing:
            return
        if self.step is None:
            self._broke()
            return
        self.failing = True
        self._page_said = False
        self._step_at = time.monotonic()   # (arms its buttons, as a new step's)
        self.card.fail(self.step, own)
        self._sync_card()
        self._place()

    def _page_card(self) -> bool:
        """The page shows its own red card for this step (it speaks, not the tour)."""
        s = self.step
        if s is None or s.page_oops is None:
            return False
        try:
            w = s.page_oops()
            return w is not None and w.isVisible()
        except RuntimeError:
            return False

    def _sync_card(self):
        """The card shows unless hidden, or a red card whose page says it already."""
        on = not self._hidden and not (self.failing and self._page_card())
        if self.card.isVisible() != on:
            self.card.setVisible(on)

    def try_again(self, done_by_page: bool = False):
        """The failed step once more (its retry() redoes what failed, unless the page's
        own Try again just did)."""
        s = self.step
        self.failing = False
        _errors.seen = False
        self._retry_at = time.monotonic()
        if s is not None and s.retry is not None and not done_by_page:
            try:
                s.retry()
            except Exception:  # noqa: BLE001 - its own log line, not a new failure
                log.warning("tour: retry", exc_info=True)
        self._sync_card()
        back = s.extra.get("retry_to") if s is not None else None
        if back:   # (a search's results step: back to the search box)
            self.go_to(back)
        else:
            self.go(self.at)

    def _report(self):
        oops.report(self.win)
        self.end("failed")

    def _broke(self):
        """The tour itself broke (a bad step, a paint error): gone at once, no card."""
        self.failing = True
        self.end("failed")

    def end(self, how: str = "done"):
        if self._ended:
            return
        if how == "failed" and not self.failing:
            self.fail()   # the red card first; its Close ends it
            return
        self._ended = True
        if self in _running:
            _running.remove(self)
        if not _running:
            logging.getLogger().removeHandler(_errors)
        self.timer.stop()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        for w in (self.card, self):
            try:
                w.hide()
                w.deleteLater()
            except RuntimeError:
                pass
        try:
            self.finished(how)
        except Exception:  # noqa: BLE001 - the tour's gone either way
            log.exception("tour: finished")

    @property
    def ended(self) -> bool:
        return self._ended

    def _tick(self):
        try:
            if self._ended:
                return
            if self.leave():
                self.end("left")
                return
            s = self.step
            if not self.failing and (_errors.seen or (
                    s is not None and s.failed is not None
                    and time.monotonic() - self._retry_at > RETRY_MS / 1000 and s.failed())):
                self.fail(own=not _errors.seen)
            show = self.showing()
            if show == self._hidden:   # flipped
                self._hidden = not show
                self.setVisible(show)
            if self.failing and s is not None and s.page_oops is not None:
                page = self._page_card()
                if page:
                    self._page_said = True
                elif self._page_said and show:   # its Try again (or it went): carry on
                    self.try_again(done_by_page=True)
                    return
            self._sync_card()
            if not show:
                return
            s = self.step
            if not self.failing and s is not None and s.done is not None and s.done():
                self.go(self.at + 1)
                return
            self._place()
        except RuntimeError:   # the window or a part of it was freed meanwhile
            self.end("left")
        except Exception:  # noqa: BLE001 - a bad step never traps anyone
            log.exception("tour: tick")
            self._broke()

    # ------------------------------------------------------------------ input
    def eventFilter(self, obj, ev):   # noqa: N802 - Qt
        # (never raises: PySide keeps an exception from an override for later, and
        # it can free another class's override meanwhile, AGENT-RULES)
        try:
            return self._input(obj, ev)
        except Exception:  # noqa: BLE001 - a broken tour lets go at once
            log.exception("tour: input")
            QTimer.singleShot(0, self, self._broke)
            return False

    _MOUSE = (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
              QEvent.Type.MouseButtonDblClick)

    def _input(self, obj, ev) -> bool:
        t = ev.type()
        if self._ended or self._hidden or (t not in self._MOUSE
                                           and t != QEvent.Type.KeyPress):
            return False
        if self.failing:   # the window's theirs again; Esc closes the red card
            if (t == QEvent.Type.KeyPress and ev.key() == Qt.Key.Key_Escape
                    and isinstance(obj, QWidget) and obj.window() is self.win):
                self.end("failed")
                return True
            return False
        if not isinstance(obj, QWidget) or obj.window() is not self.win:
            return False   # another window (a menu, a file picker): not the tour's
        if obj is self.card or self.card.isAncestorOf(obj):
            if t == QEvent.Type.KeyPress and ev.key() == Qt.Key.Key_Escape:
                return self._escape()
            return False
        s = self.step
        if s is None:
            return False
        if t in self._MOUSE:
            if not s.blocks:
                if t == QEvent.Type.MouseButtonPress:
                    self.end("done")
                return False   # (the click goes on)
            pos = self.win.mapFromGlobal(ev.globalPosition().toPoint())
            if self._in_ring(pos) or (s.allow is not None and s.allow(obj)):
                return False
            if t == QEvent.Type.MouseButtonPress:
                self._nudge()
            return True
        # a key
        if ev.key() == Qt.Key.Key_Escape:
            return self._escape()
        if not s.blocks:
            self.end("done")
            return False
        if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and s.done is None \
                and self.card.btn_go.isVisible():
            self._pressed_go()
            return True
        return not self._in_ring_widget(obj)   # (typing in the search box goes in)

    def _escape(self) -> bool:
        """Esc: only where "Not now" is showing (or a last card)."""
        s = self.step
        if s is not None and not s.blocks:
            self.end("done")
        elif self.card.btn_skip.isVisible():
            self.end("skipped")
        else:
            self._nudge()
        return True

    def _in_ring(self, pos: QPoint) -> bool:
        return any(r.adjusted(-PAD, -PAD, PAD, PAD).contains(pos) for r in self._targets())

    def _in_ring_widget(self, obj: QWidget) -> bool:
        tl = obj.mapTo(self.win, QPoint(0, 0))
        c = QRect(tl, obj.size()).center()
        return self._in_ring(c)

    def _nudge(self):
        """A click outside: the card shakes and the ring flashes."""
        self._shake_at = time.monotonic()
        for ms in range(0, SHAKE_MS + 1, 30):
            QTimer.singleShot(ms, self, self._place)
        QTimer.singleShot(FLASH_MS, self, self.update)

    def _targets(self) -> list[QRect]:
        s = self.step
        if s is None:
            return []
        try:
            return [r for r in s.target() if r.isValid() and not r.isEmpty()]
        except RuntimeError:
            return []

    # ------------------------------------------------------------------ placing
    def _place(self):
        """The layer over the window, the card beside the first ring."""
        if self._ended:
            return
        w = self.win
        if self.geometry() != w.rect():
            self.setGeometry(w.rect())
        self.raise_()
        card = self.card
        card.fit(self.width() - 2 * EDGE)
        cw, ch = card.width(), card.height()
        rings = self._targets()
        side, x, y = self._spot(rings, cw, ch)
        self._side = side
        since = time.monotonic() - self._shake_at
        if since < SHAKE_MS / 1000:   # a little side-to-side, dying away
            k = 1 - since / (SHAKE_MS / 1000)
            x += round(math.sin(since * 60) * 9 * k)
        card.move(x, y)
        card.raise_()
        self.update()

    def _spot(self, rings: list[QRect], cw: int, ch: int) -> tuple[str, int, int]:
        W, H = self.width(), self.height()
        if not rings:
            return "", (W - cw) // 2, (H - ch) // 2
        t = QRectF(rings[0]).adjusted(-PAD, -PAD, PAD, PAD)
        rtl = QApplication.isRightToLeft()
        room = {"below": H - EDGE - t.bottom() - GAP, "above": t.top() - GAP - EDGE,
                "right": W - EDGE - t.right() - GAP, "left": t.left() - GAP - EDGE}
        order = ["below", "above", "left" if rtl else "right", "right" if rtl else "left"]
        if t.width() > W * 0.5 and t.height() > H * 0.45:
            # a big area (a list, a page): the card sits inside it, at its foot
            x = t.center().x() - cw / 2
            y = t.bottom() - ch - 16
            return "", self._clamp_x(x, cw), self._clamp_y(y, ch)
        if t.height() > H * 0.45:   # tall: beside it first
            order = order[2:] + order[:2]
        side = next((s for s in order if room[s] >= (ch if s in ("below", "above") else cw)),
                    "")
        if side == "below":
            x = t.center().x() - cw / 2 if t.width() < cw else t.left()
            y = t.bottom() + GAP
        elif side == "above":
            x = t.center().x() - cw / 2 if t.width() < cw else t.left()
            y = t.top() - GAP - ch
        elif side == "right":
            x, y = t.right() + GAP, t.center().y() - ch / 2
        elif side == "left":
            x, y = t.left() - GAP - cw, t.center().y() - ch / 2
        else:   # no room anywhere: in the middle, over the dimmed window
            return "", (W - cw) // 2, (H - ch) // 2
        return side, self._clamp_x(x, cw), self._clamp_y(y, ch)

    def _clamp_x(self, x: float, cw: int) -> int:
        return round(max(EDGE, min(x, self.width() - EDGE - cw)))

    def _clamp_y(self, y: float, ch: int) -> int:
        return round(max(EDGE, min(y, self.height() - EDGE - ch)))

    # ------------------------------------------------------------------ drawing
    def paintEvent(self, ev):   # noqa: N802 - Qt
        try:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            rings = [QRectF(r).adjusted(-PAD, -PAD, PAD, PAD) for r in self._targets()]
            if self.failing:   # no dimming, no ring: only the card's arrow
                if self.card.isVisible():
                    self._arrow(p, rings[0] if rings else None)
                p.end()
                return
            path = QPainterPath()
            path.addRect(QRectF(self.rect()))
            for r in rings:
                hole = QPainterPath()
                hole.addRoundedRect(r, 12, 12)
                path = path.subtracted(hole)
            p.fillPath(path, QColor(0, 0, 0, DIM))
            flash = time.monotonic() - self._shake_at < FLASH_MS / 1000
            # a slow breath on the ring, so the eye finds it
            breath = 0.5 + 0.5 * math.sin(time.monotonic() * 3.2)
            for r in rings[:1] if self.step is not None and self.step.ring else ():
                self._ring(p, r, breath, flash)
            for r in rings[1:]:
                self._ring(p, r, 0.0, False, QColor(theme.T["accent"]), 2)
            self._arrow(p, rings[0] if rings else None)
            p.end()
        except Exception:  # noqa: BLE001 - see eventFilter
            log.exception("tour: paint")
            QTimer.singleShot(0, self, self._broke)

    def _ring(self, p: QPainter, r: QRectF, breath: float, flash: bool,
              colour: QColor = RING, width: float = 3):
        p.setBrush(Qt.BrushStyle.NoBrush)
        glow = QColor(colour)
        for extra, alpha in ((14, 30 + 30 * breath), (7, 60 + 40 * breath)):
            glow.setAlpha(int(min(255, alpha * (2 if flash else 1))))
            p.setPen(QPen(glow, width + extra))
            p.drawRoundedRect(r, 12, 12)
        p.setPen(QPen(colour, width + (2 if flash else 0)))
        p.drawRoundedRect(r, 12, 12)

    def _arrow(self, p: QPainter, t: QRectF | None):
        """The card's little arrow towards the ring, in the card's colour."""
        side = getattr(self, "_side", "")
        if t is None or not side or not self.card.isVisible():
            return
        c = QRectF(self.card.geometry())
        if side in ("below", "above"):
            ex = max(c.left() + 24, min(t.center().x(), c.right() - 24))
            ey = c.top() if side == "below" else c.bottom()
            tip = QPointF(ex, ey - (GAP - 4) if side == "below" else ey + (GAP - 4))
            a, b = QPointF(ex - ARROW, ey), QPointF(ex + ARROW, ey)
        else:
            ey = max(c.top() + 24, min(t.center().y(), c.bottom() - 24))
            ex = c.left() if side == "right" else c.right()
            tip = QPointF(ex - (GAP - 4) if side == "right" else ex + (GAP - 4), ey)
            a, b = QPointF(ex, ey - ARROW), QPointF(ex, ey + ARROW)
        tri = QPainterPath(a)
        tri.lineTo(tip)
        tri.lineTo(b)
        tri.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.T["panel"]))
        p.drawPath(tri)
        p.setPen(QPen(QColor(theme.T["border"]), 1))   # the card's edge, round the tip
        p.drawPolyline([a, tip, b])
