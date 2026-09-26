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
so its text wraps less.

It never shrinks a dialog: whatever the user (or the code) sized it to is kept.
Message boxes and file dialogs size themselves and aren't watched.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QWidget
from shiboken6 import isValid as qt_valid

WIDEN_STEP = 80
WATCHED = (QEvent.Show, QEvent.LayoutRequest, QEvent.Resize)


def needed_height(w: QWidget, width: int) -> int:
    """How tall `w`'s layout wants to be at `width` (window content, no frame)."""
    lay = w.layout()
    if lay is None:
        return 0
    lay.activate()
    if lay.hasHeightForWidth():
        return max(lay.totalHeightForWidth(width), lay.totalMinimumSize().height())
    return lay.totalMinimumSize().height()


def fit(w: QWidget) -> bool:
    """Grow `w` so its content fits; returns whether it changed size."""
    if not qt_valid(w) or not w.isVisible() or w.isMaximized() or w.isFullScreen():
        return False
    screen = w.screen() or QApplication.primaryScreen()
    avail = screen.availableGeometry()
    frame = w.frameGeometry()
    extra_h = frame.height() - w.height()    # title bar and borders
    extra_w = frame.width() - w.width()
    max_h = avail.height() - extra_h
    max_w = avail.width() - extra_w
    width = w.width()
    need = needed_height(w, width)
    while need > max_h and width + WIDEN_STEP <= max_w:   # too tall for the screen: widen
        width += WIDEN_STEP
        need = needed_height(w, width)
    height = min(max(need, w.height()), max_h)
    if (width, height) == (w.width(), w.height()):
        return False
    w.resize(width, height)
    # keep it on screen: move up / left just enough
    g = w.frameGeometry()
    x = min(g.x(), avail.right() - g.width() + 1)
    y = min(g.y(), avail.bottom() - g.height() + 1)
    if (x, y) != (g.x(), g.y()):
        w.move(max(x, avail.x()), max(y, avail.y()))
    return True


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
        fit(self.parent())


def watch(dialog: QDialog) -> QDialog:
    """Make `dialog` grow to fit its text from now on. Call it in every dialog's
    __init__ (message boxes and file dialogs size themselves already)."""
    _Fitter(dialog)
    return dialog
