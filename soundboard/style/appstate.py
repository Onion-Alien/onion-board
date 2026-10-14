"""Stopping decoration while the app is in the background, and whole-pixel painting.

A window left open behind a game is still "visible" to Qt, so show / hide events
alone keep every animation going at full speed. Widgets that only decorate (the logo,
the mascots, the live dot) use `pause_in_background` to also stop while another
program is in front.

Part of the style kit (see __init__.py): imports nothing from either app.
"""
from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget


def active() -> bool:
    """Is the app in front (one of its windows has focus)?"""
    app = QGuiApplication.instance()
    return (not isinstance(app, QGuiApplication)
            or app.applicationState() == Qt.ApplicationState.ApplicationActive)


class _Pauser(QObject):
    # a child of the widget, so the connection goes with it when the widget is deleted
    def __init__(self, widget: QWidget, start: Callable[[], None], stop: Callable[[], None]):
        super().__init__(widget)
        self._widget, self._start, self._stop = widget, start, stop
        self._watching = None   # the minimised window we wait on to be restored

    def on_state(self, state):
        if state != Qt.ApplicationState.ApplicationActive:
            self._stop()
        elif self._widget.isVisible():
            win = self._widget.window()
            if not win.isMinimized():
                self._start()   # (a minimised window's widgets are still "visible")
            elif self._watching is None:
                # Restoring from the taskbar makes the app active *before* the window
                # leaves its minimised state, so start once it actually has.
                self._watching = win
                win.installEventFilter(self)

    def eventFilter(self, obj, e):
        if obj is self._watching and e.type() == QEvent.Type.WindowStateChange \
                and not obj.isMinimized():
            obj.removeEventFilter(self)
            self._watching = None
            if active() and self._widget.isVisible():
                self._start()
        return False


def pause_in_background(widget: QWidget, start: Callable[[], None],
                        stop: Callable[[], None]) -> None:
    """Call `stop` when the app goes to the background and `start` when it's back in
    front with `widget` showing. The widget still starts / stops itself on show / hide
    (checking `active()` before it starts)."""
    app = QGuiApplication.instance()
    if isinstance(app, QGuiApplication):
        app.applicationStateChanged.connect(_Pauser(widget, start, stop).on_state)


def snap_to_pixels(p: QPainter):
    """Shift `p` (fresh from QPainter(widget)) so the widget's edge is a whole pixel.
    A no-op at 100 % and 200 %, and on pictures (grab) that start on one already.

    At 125 %, 150 %... a widget often starts between two screen pixels (x = 10 at 125 %
    is pixel 12.5). Qt keeps the widget to the whole pixels from 13, but paints it from
    12.5, so the left or top half pixel of anything drawn to its edge is lost: a round
    button came out flat on its left."""
    t = p.deviceTransform()
    if not t.m11() or not t.m22():
        return
    dx = math.floor(t.dx() + 0.5) - t.dx()   # Qt rounds halves up (qRound), not to even
    dy = math.floor(t.dy() + 0.5) - t.dy()
    if dx or dy:
        p.translate(dx / t.m11(), dy / t.m22())
