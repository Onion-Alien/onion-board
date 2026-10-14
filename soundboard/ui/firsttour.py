"""Bun's first-run tour of the empty board: ten seconds on where sounds come from.

Right after the very first setup guide (setupwizard.SetupWizard.done), on a board with
no sounds yet, the window dims and Bun, in a spotlight, says there are none:

  "bun"      Bun and his bubble. Any click or key moves on; Esc ends it.
  "search"   The search box in a yellow ring: type a song, press Enter. Optional: a
             click anywhere else (or Esc) ends it.
  "wait"     They searched: nothing drawn while the results load.
  "results"  The results are up: Bun comes back beside the first one ("pick one"), the
             Add button ringed for their own files. Any click, key or scroll ends it
             and goes on to whatever was clicked.

Never in Offline mode or with every search site switched off (there'd be nothing to
find), never in the mini player, and once only (Config.tips_seen). It ends by itself
when sounds arrive (an import), the Sounds tab is left, a dialog opens, or the window
goes away.
"""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget

from soundboard import net, theme, tips, usage
from soundboard.i18n import _
from soundboard.ui.bunnywidget import BUBBLE, INK, BunnyWidget
from soundboard.ui.ytsearch import SearchResults

log = logging.getLogger(__name__)

KEY = "first-run-tour"   # in Config.tips_seen once shown
START_MS = 700           # after the setup guide closes: the window settles first
TICK_MS = 150            # follows the window (sizes, results, tab) this often
WAIT_MAX_S = 30.0        # a search that never answers ends the tour
# the ring round what to use next: a fixed yellow, drawn on the dimmed window (so the
# same in every theme), as asked for: "a yellow border around the search bar"
RING = QColor("#ffd23f")
DIM = {"bun": 165, "search": 135, "results": 105}   # how dark the rest of the window gets
BUBBLE_W = 340           # a bubble's width at most (less in a small window)
EDGE = 12                # bubbles keep this far in from the window's edges
GAP = 18                 # between a bubble and what it points at (its tail spans it)

_current: Tour | None = None


def will_run(win) -> bool:
    """Would the tour run once the setup guide closes: not seen yet, no sounds yet,
    and searching possible (not Offline mode, not every site switched off)."""
    cfg = win.cfg
    return (KEY not in cfg.tips_seen and not cfg.sounds and not net.offline()
            and SearchResults.available())


def start(win) -> Tour | None:
    """Start the tour over `win` (the main window), if it should run now."""
    global _current
    try:
        if (_current is not None or not will_run(win) or not win.isVisible()
                or win.isMinimized() or win.is_mini()
                or win.tabs.currentWidget() is not win.sounds_page
                or QApplication.activeModalWidget() is not None):
            return None
    except RuntimeError:   # the window went meanwhile
        return None
    cfg = win.cfg
    cfg.tips_seen = [*cfg.tips_seen, KEY, "search"]   # (the search tip says the same)
    cfg.tip_day = tips.today()   # this is today's tip: no "Did you know?" bar on top
    win._save_later()
    usage.used("tour-shown")
    _current = Tour(win)
    return _current


def _font(size_pt: float, bold: bool = False) -> QFont:
    f = QFont(QApplication.font())
    f.setPointSizeF(size_pt)
    f.setBold(bold)
    return f


class Tour(QWidget):
    """The dimmed layer over the window, its bubbles and rings. A child of the
    window that covers it; it takes clicks only on its first step, and watches the
    app's input (eventFilter) for the rest."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.step = ""
        self._wait_since = 0.0
        self._ended = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setGeometry(win.rect())
        # Bun on the board: his own small bubble waits while the tour's speaks for him
        self.bun = win.grid.bun
        self._bun_lines = (self.bun.lines, self.bun.hope_lines)
        # Bun again beside the results: a little one, drawn over the dimmed window
        self.result_bun = BunnyWidget("star", height=96, pad=8, parent=self)
        self.result_bun.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.result_bun.hide()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(TICK_MS)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self._go("bun")
        self.show()
        self.raise_()

    # ------------------------------------------------------------------ steps
    def _go(self, step: str):
        self.step = step
        if step == "bun":
            self.bun.lines, self.bun.hope_lines = (), ()
            self.bun.say = ""
            self.bun.hope(True)   # happy to see them
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            self.setFocus()
        else:
            self._bun_back()
            # the window works as usual underneath from here: the search box takes the
            # typing, a result's Play / Add take their clicks
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        if step == "search":
            self.win.search.setFocus(Qt.FocusReason.OtherFocusReason)
        elif step == "wait":
            self._wait_since = time.monotonic()
        elif step == "results":
            usage.used("tour-searched")
        self.result_bun.setVisible(step == "results")
        self._place_result_bun()
        self.update()

    def _bun_back(self):
        """The board's Bun back to his own lines and mood."""
        if self.bun.lines == () and self._bun_lines is not None:
            self.bun.lines, self.bun.hope_lines = self._bun_lines
            self.bun.hope(False)

    def end(self, skipped: bool = False):
        """Gone for good (it never comes back: Config.tips_seen)."""
        global _current
        if self._ended:
            return
        self._ended = True
        if skipped:
            usage.used("tour-skipped")
        self.timer.stop()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        try:
            self._bun_back()
        except RuntimeError:   # the board went first (the window closing)
            pass
        self.hide()
        self.deleteLater()
        if _current is self:
            _current = None

    def _tick(self):
        """Follow the window: its size, its search results; stop when it's no
        longer the empty Sounds tab in front of them."""
        try:
            w = self.win
            if (not w.isVisible() or w.isMinimized() or w.is_mini()
                    or w.tabs.currentWidget() is not w.sounds_page
                    or QApplication.activeModalWidget() is not None
                    or (self.step in ("bun", "search") and w.cfg.sounds)):
                self.end()
                return
            if self.geometry() != w.rect():
                self.setGeometry(w.rect())
            res = w.ytresults
            if self.step in ("search", "wait") and not res.isHidden():
                if res._rows:
                    self._go("results")
                elif self.step == "search":
                    self._go("wait")
            if self.step == "wait" and (time.monotonic() - self._wait_since > WAIT_MAX_S
                                        or res.isHidden()):
                self.end()   # no results came (an error, nothing found, closed)
                return
            if self.step == "results" and (res.isHidden() or not res._rows):
                self.end()
                return
            self.raise_()
            self._place_result_bun()
            self.update()
        except RuntimeError:   # the window or a part of it was freed meanwhile
            self.end()

    # ------------------------------------------------------------------ input
    def eventFilter(self, obj, ev):   # noqa: N802 - Qt
        # (never raises: PySide keeps an exception from an override for later, and
        # it can free another class's override meanwhile, AGENT-RULES)
        try:
            return self._input(obj, ev)
        except Exception:  # noqa: BLE001
            log.exception("first-run tour: input")
            return False

    def _input(self, obj, ev) -> bool:
        t = ev.type()
        if self._ended or t not in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress,
                                    QEvent.Type.Wheel):
            return False
        if not isinstance(obj, QWidget) or obj.window() is not self.win:
            return False   # another window (a menu, a dialog): not the tour's
        if t == QEvent.Type.KeyPress and ev.key() == Qt.Key.Key_Escape:
            self.end(skipped=self.step in ("bun", "search"))
            return self.step == "bun"   # (in the search box, Esc does its own thing too)
        if self.step == "bun":
            if t == QEvent.Type.Wheel:
                return True   # the board stays put under the spotlight
            self._go("search")
            if t == QEvent.Type.KeyPress and ev.text().strip():
                self.win.search.insert(ev.text())   # typing at once: it goes in the box
            return True   # the click or key that moved on does nothing else
        if self.step == "search":
            if t == QEvent.Type.MouseButtonPress and not self._in_search(obj):
                self.end(skipped=True)   # not now: the click goes on to what was under it
            return False
        if self.step == "results":
            self.end()   # they got it: the click goes on (Play, Add, …)
        return False

    def _in_search(self, obj) -> bool:
        """The search box, its clear button, or the site button next to it."""
        w = self.win
        return any(obj is b or (isinstance(obj, QWidget) and b.isAncestorOf(obj))
                   for b in (w.search, w.btn_yt))

    def mousePressEvent(self, ev):   # noqa: N802 - Qt (the first step only)
        ev.accept()

    def keyPressEvent(self, ev):   # noqa: N802 - Qt (eventFilter moves it on)
        ev.accept()

    # ------------------------------------------------------------------ drawing
    def _rect(self, widget: QWidget, pad: float) -> QRectF:
        tl = widget.mapTo(self.win, QPoint(0, 0))
        return QRectF(tl.x() - pad, tl.y() - pad, widget.width() + 2 * pad,
                      widget.height() + 2 * pad)

    def _bun_hole(self) -> QRectF:
        r = self._rect(self.bun, 0)
        half = min(r.width() / 2, 95.0)
        return QRectF(r.center().x() - half, r.top() - 10, 2 * half, r.height() + 20)

    def _first_result(self) -> QRectF | None:
        rows = [r for r in self.win.ytresults._rows if r.isVisible()]
        return self._rect(rows[0], 6) if rows else None

    def _place_result_bun(self):
        if self.step != "results":
            return
        first = self._first_result()
        bw, bh = self.result_bun.width(), self.result_bun.height()
        room = self.width() - EDGE - (first.right() if first else 0)
        if first is None or room < bw + GAP + 200:
            self.result_bun.hide()   # no room beside it: the bubble goes under, alone
            return
        self.result_bun.move(round(first.right() + GAP), round(first.top() + 8))
        self.result_bun.resize(bw, bh)
        self.result_bun.show()

    def paintEvent(self, ev):   # noqa: N802 - Qt
        try:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            if self.step == "bun":
                hole = self._bun_hole()
                self._dim(p, [hole])
                self._bubble(p, hole, _("No sounds here yet!"),
                             _("How about your favourite song? I'll show you where to look."),
                             _("Click anywhere to keep going · Esc to skip"))
            elif self.step == "search":
                box = self._rect(self.win.search, 6)
                self._dim(p, [box])
                self._ring(p, box)
                self._bubble(p, box, _("Type a song you love, then press Enter"),
                             _("Try anything: a song, a meme, a game sound."),
                             _("Not now? Click anywhere else."), prefer="below")
            elif self.step == "results":
                first = self._first_result()
                add = self._rect(self.win.btn_add, 5)
                self._dim(p, [r for r in (first, add) if r is not None])
                if first is not None:
                    self._ring(p, first)
                self._ring(p, add, QColor(theme.T["accent"]), 2)
                target = first if first is not None else add
                if not self.result_bun.isHidden():   # beside Bun, who's beside the result
                    g = self.result_bun.geometry()
                    target = QRectF(g.x(), g.y(), g.width(), 60)
                self._bubble(p, target, _("Pick one, you'll love it!"),
                             _("Play to hear it, Add to keep it on your board."),
                             _("Got your own songs? The Add button, ringed up top, brings "
                               "them in."))
            p.end()
        except Exception:  # noqa: BLE001 - see eventFilter
            log.exception("first-run tour: paint")

    def _dim(self, p: QPainter, holes: list[QRectF]):
        path = QPainterPath()
        path.addRect(QRectF(self.rect()))
        for h in holes:
            hp = QPainterPath()
            hp.addRoundedRect(h, 14, 14)
            path = path.subtracted(hp)
        p.fillPath(path, QColor(0, 0, 0, DIM.get(self.step, 120)))

    def _ring(self, p: QPainter, r: QRectF, colour: QColor = RING, width: float = 3):
        p.setBrush(Qt.BrushStyle.NoBrush)
        for extra, alpha in ((10, 40), (6, 70)):   # a soft glow, then the line
            glow = QColor(colour)
            glow.setAlpha(alpha)
            p.setPen(QPen(glow, width + extra))
            p.drawRoundedRect(r, 12, 12)
        p.setPen(QPen(colour, width))
        p.drawRoundedRect(r, 12, 12)

    def _bubble(self, p: QPainter, target: QRectF, title: str, body: str, hint: str,
                prefer: str = "right"):
        """A speech bubble in Bun's style (BUBBLE, INK) pointing at `target`: beside it
        when there's room, else under it, else over it; always inside the window."""
        bw = min(BUBBLE_W, self.width() - 2 * EDGE)
        inner = bw - 32
        parts = ((title, _font(13, True), INK), (body, _font(10), INK),
                 (hint, _font(8.5), QColor("#6b6778")))
        sizes = [QFontMetrics(f).boundingRect(0, 0, inner, 2000, Qt.TextFlag.TextWordWrap,
                                              text).height() for text, f, _c in parts]
        bh = 16 + sizes[0] + 6 + sizes[1] + 10 + sizes[2] + 16
        rtl = QApplication.isRightToLeft()
        right_room = self.width() - EDGE - target.right() - GAP
        left_room = target.left() - GAP - EDGE
        below_room = self.height() - EDGE - target.bottom() - GAP
        side = prefer
        if side == "right" and rtl and left_room >= bw:
            side = "left"   # right to left: beside it on the reading side's end
        if side == "right" and right_room < bw:
            side = "left" if left_room >= bw else "below" if below_room >= bh else "above"
        elif side == "below" and below_room < bh:
            side = "above"
        if side == "right":
            x, y = target.right() + GAP, target.top() + 6
        elif side == "left":
            x, y = target.left() - GAP - bw, target.top() + 6
        elif side == "below":
            x, y = target.left() + 10, target.bottom() + GAP
        else:
            x, y = target.left() + 10, target.top() - GAP - bh
        x = max(EDGE, min(x, self.width() - EDGE - bw))
        y = max(EDGE, min(y, self.height() - EDGE - bh))
        box = QRectF(x, y, bw, bh)
        shape = QPainterPath()
        shape.addRoundedRect(box, 16, 16)
        # the tail: from the bubble's near edge towards the target
        if side in ("right", "left"):
            ty = max(box.top() + 18, min(target.center().y(), box.bottom() - 18, box.top() + 40))
            ex = box.left() if side == "right" else box.right()
            tip = QPointF(ex - (GAP - 2) if side == "right" else ex + (GAP - 2), ty)
            base = (QPointF(ex, ty - 10), QPointF(ex, ty + 10))
        else:
            tx = max(box.left() + 24, min(target.left() + 40, box.right() - 24))
            ey = box.top() if side == "below" else box.bottom()
            tip = QPointF(tx, ey - (GAP - 2) if side == "below" else ey + (GAP - 2))
            base = (QPointF(tx - 10, ey), QPointF(tx + 10, ey))
        tail = QPainterPath(base[0])
        tail.lineTo(tip)
        tail.lineTo(base[1])
        tail.closeSubpath()
        shape = shape.united(tail)
        p.setPen(QPen(INK, 1.6))
        p.setBrush(BUBBLE)
        p.drawPath(shape)
        cy = box.top() + 16
        for (text, f, colour), h, gap in zip(parts, sizes, (6, 10, 0)):
            p.setFont(f)
            p.setPen(colour)
            p.drawText(QRectF(box.left() + 16, cy, inner, h),
                       Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeading, text)
            cy += h + gap
