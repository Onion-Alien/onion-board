"""Dialogs grow to fit their text instead of clipping it.

Qt only enforces a dialog's *minimum* size: word-wrapped labels (rich text, long
hints) get taller as the window gets narrower or as their text changes, but the
dialog doesn't grow with them, so the text ends up squashed under the buttons,
especially with Windows display scaling. An event filter on each of our dialogs
(fit.watch in its __init__) steps in when the dialog is shown, when its layout
changes (a label's text was set) and when it's resized: it asks the layout how
tall it needs to be at the current width (heightForWidth, which accounts for
wrapping) and grows the window to that, moving it up if it would run off the
bottom of the screen. A dialog already as tall as the screen gets wider instead,
so its text wraps less; still too tall (a small screen, a big display scale), what's
in it scrolls and a last row of buttons stays in view.

It never shrinks a dialog: whatever the code sized it to is kept. The user can't
drag a watched dialog's edges (on Windows its border is the fixed-size kind), so a
dialog never ends up stretched around a big empty gap; the code can still resize it.
Message boxes and file dialogs size themselves and aren't watched.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, QMargins, QObject, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QScreen
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QLayout, QScrollArea, QVBoxLayout,
                               QWidget)
from shiboken6 import isValid as qt_valid

WIDEN_STEP = 80
LIFTED = "fit_lifted"   # (how far fit() moved a window up, the y it left it at)
MARGIN = "fit_margin"   # a card inside a window: the room it keeps around itself (px)
SCROLLS = "fit_scrolls"   # its content scrolls: widened only when that makes it fit
INSIDE = "fit_inside"     # what scroll_inside moved its content to
OWNER_ROOM = "fit_owner_room"   # a card window: (left, top, right, bottom) of see-through
                                # room round its panel; it stays inside the window it opens
                                # from (that window's inside, not its title bar), not just
                                # on the screen


def room(w: QWidget) -> QRect:
    """Where window `w` may be: its screen's free room, or, for a card window
    (OWNER_ROOM), the inside of the window it opens from, on that screen. Its shadow's
    see-through room may reach past that window's edge; its panel doesn't."""
    screen = w.screen() or QApplication.primaryScreen()
    avail = screen.availableGeometry()
    pad = w.property(OWNER_ROOM)
    above = w.parentWidget()
    if pad is None or above is None:
        return avail
    inside = above.window().geometry().marginsAdded(QMargins(*pad)).intersected(avail)
    return inside if inside.isValid() else avail
WATCHED = (QEvent.Type.Show, QEvent.Type.LayoutRequest, QEvent.Type.Resize)


def needed_height(w: QWidget, width: int) -> int:
    """How tall `w`'s layout wants to be at `width` (window content, no frame)."""
    lay = w.layout()
    if lay is None:
        return 0
    lay.activate()
    inside = w.property(INSIDE)
    if inside is not None:   # all of it, scrolling or not (the page may be short now)
        return needed_height(inside, width) + lay.totalMinimumSize().height()
    if lay.hasHeightForWidth():
        return max(lay.totalHeightForWidth(width), lay.totalMinimumSize().height())
    return lay.totalMinimumSize().height()


def scroll_inside(w: QWidget, lay: QLayout):
    """Put a window's content in a scroll area, all but a last row of buttons, for when
    no width makes it fit on the screen: it can't get shorter than its layout allows,
    which left its bottom under the task bar. `lay`: its layout."""
    margins = lay.contentsMargins()
    last = lay.itemAt(lay.count() - 1)
    footer = last.layout() if last is not None else None
    if footer is not None:
        lay.takeAt(lay.count() - 1)
    inside = QWidget()
    inside.setLayout(lay)   # (takes it off the window, with everything in it)
    area = QScrollArea()
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(inside)
    if w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground):   # a card window:
        area.setObjectName("fitscroll")       # its see-through room round the panel
        inside.setObjectName("fitscrollpage")   # stays see-through (themesheet.py)
    area.setMinimumWidth(lay.totalMinimumSize().width()
                         + area.verticalScrollBar().sizeHint().width())
    outer = QVBoxLayout(w)
    outer.setContentsMargins(0, 0, 0, margins.bottom() if footer is not None else 0)
    outer.setSpacing(lay.spacing())
    outer.addWidget(area, 1)
    if footer is not None:
        footer.setContentsMargins(margins.left(), 0, margins.right(), 0)
        outer.addLayout(footer)
    w.setProperty(INSIDE, inside)


def fit(w: QWidget) -> bool:
    """Grow `w` so its content fits; returns whether it changed size."""
    if not qt_valid(w) or not w.isVisible() or w.isMaximized() or w.isFullScreen():
        return False
    avail = room(w)   # (the screen's, or a card window's owner's inside)
    frame = w.frameGeometry()
    extra_h = frame.height() - w.height()    # title bar and borders
    extra_w = frame.width() - w.width()
    max_h = avail.height() - extra_h
    max_w = avail.width() - extra_w
    if not w.isWindow():   # a card inside a window: as big as the window is or can grow
        top = w.window()   # to (its owner grows it), less the room kept around the card
        margin = int(w.property(MARGIN) or 0)
        tf = top.frameGeometry()
        max_h = max(top.height(), avail.height() - (tf.height() - top.height())) - margin
        max_w = max(top.width(), avail.width() - (tf.width() - top.width())) - margin
    width = w.width()
    lay = w.layout()
    if lay is not None:   # a row of buttons (longer in other languages) is never cut
        lay.activate()
        width = min(max(width, lay.totalMinimumSize().width()), max(max_w, width))
    need = needed_height(w, width)
    narrow, narrow_need = width, need
    while need > max_h and width + WIDEN_STEP <= max_w:   # too tall for the screen: widen
        width += WIDEN_STEP
        need = needed_height(w, width)
    if need > max_h and w.property(SCROLLS):   # wider didn't make it fit: it scrolls,
        width, need = narrow, narrow_need       # at its own width (not stretched empty)
    elif need > max_h and w.isWindow() and lay is not None and w.property(INSIDE) is None:
        scroll_inside(w, lay)
    height = min(max(need, w.height()), max_h)
    if (width, height) == (w.width(), w.height()):
        return False
    w.resize(width, height)
    if not w.isWindow():   # a card inside a window: its owner places it
        return True
    # keep it in its room: move up / left just enough, or down / right when it's above
    # or left of it (a card window placed while taller than its room went to the
    # screen's top, then shrank to fit here, and stayed over the window's title bar)
    g = w.frameGeometry()
    x = max(min(g.x(), avail.right() - g.width() + 1), avail.x())
    y = max(min(g.y(), avail.bottom() - g.height() + 1), avail.y())
    if (x, y) != (g.x(), g.y()):
        w.move(x, y)
        if y < g.y():
            # remember how far up it went (and where it landed), so shrinking can put it
            # back: a fold opened and shut near the bottom walked the window up the screen
            lifted = (w.property(LIFTED) or (0, 0))[0] + g.y() - w.frameGeometry().y()
            w.setProperty(LIFTED, (lifted, w.frameGeometry().y()))
    return True


def resize_on_screen(w: QWidget, size: QSize, screen: QScreen | None = None):
    """Give a window that isn't showing yet `size`, or what `screen` has room for with
    its title bar and borders: only limiting its inside to the screen's room left its
    bottom row under the task bar."""
    # made: its frame's real size is known from here on. Never w.winId(): on a window not
    # made yet, that makes every other child of its parent a native window too (Qt's
    # "native siblings"). The main window's page would then lie over its toasts, which it
    # paints but Windows gives their mouse to the page
    w.create()
    avail = (screen or w.screen() or QApplication.primaryScreen()).availableGeometry()
    frame = w.frameGeometry().size() - w.size()
    w.resize(min(size.width(), avail.width() - frame.width()),
             min(size.height(), avail.height() - frame.height()))


def move_on_screen(w: QWidget):
    """Move a window back inside its screen's room, if it's past an edge of it."""
    avail = (w.screen() or QApplication.primaryScreen()).availableGeometry()
    g = w.frameGeometry()
    x = max(min(g.x(), avail.right() - g.width() + 1), avail.x())
    y = max(min(g.y(), avail.bottom() - g.height() + 1), avail.y())
    if (x, y) != (g.x(), g.y()):
        w.move(x, y)


def shrink(w: QWidget, height: int):
    """Make `w` `height` tall, and move it back down by what fit() lifted it to keep
    a taller step on screen (only while it's still where fit() left it: a window the
    user dragged stays put)."""
    w.resize(w.width(), height)
    if not w.isWindow():   # (a card inside a window: its owner places it)
        return
    lifted, at = w.property(LIFTED) or (0, 0)
    w.setProperty(LIFTED, None)
    g = w.frameGeometry()
    if lifted <= 0 or g.y() != at:
        return
    screen = w.screen() or QApplication.primaryScreen()
    y = min(g.y() + lifted, screen.availableGeometry().bottom() - g.height() + 1)
    if y > g.y():
        w.move(g.x(), y)


class _Fitter(QObject):
    """Event filter on one dialog (only its own events: cheap)."""

    def __init__(self, dialog: QDialog):
        super().__init__(dialog)
        self._pending = False
        dialog.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() in WATCHED and not self._pending:
            self._pending = True
            # after Qt has finished laying the dialog out for this change
            QTimer.singleShot(0, self, self._run)   # dropped if the dialog is freed first
        return False

    def _run(self):
        self._pending = False
        dialog = self.parent()
        assert isinstance(dialog, QWidget)   # made on it
        fit(dialog)


def watch(dialog: QDialog) -> QDialog:
    """Make `dialog` grow to fit its text from now on. Call it in every dialog's
    __init__ (message boxes and file dialogs size themselves already). It also stops
    the user dragging its edges: it's sized to its content, so a drag only made gaps."""
    if sys.platform == "win32":   # a thin border: no resize by dragging; resize() works
        dialog.setWindowFlag(Qt.WindowType.MSWindowsFixedSizeDialogHint, True)
    _Fitter(dialog)
    return dialog
