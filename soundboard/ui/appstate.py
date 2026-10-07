"""Stopping decoration while the app is in the background.

A window left open behind a game is still "visible" to Qt, so show / hide events
alone keep every animation going at full speed. Widgets that only decorate (the logo,
the mascots, the live dot) use `pause_in_background` to also stop while another
program is in front.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget


def active() -> bool:
    """Is the app in front (one of its windows has focus)?"""
    app = QGuiApplication.instance()
    return app is None or app.applicationState() == Qt.ApplicationActive


class _Pauser(QObject):
    # a child of the widget, so the connection goes with it when the widget is deleted
    def __init__(self, widget: QWidget, start: Callable[[], None], stop: Callable[[], None]):
        super().__init__(widget)
        self._widget, self._start, self._stop = widget, start, stop
        self._watching = None   # the minimised window we wait on to be restored

    def on_state(self, state):
        if state != Qt.ApplicationActive:
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
        if obj is self._watching and e.type() == QEvent.WindowStateChange \
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
    if app is not None:
        app.applicationStateChanged.connect(_Pauser(widget, start, stop).on_state)


BG_METER_MS = 250   # a meter's pace while another program (a game) is in front


def interval(front_ms: int, back_ms: int = BG_METER_MS) -> int:
    """`front_ms` while the app is in front, else `back_ms`."""
    return front_ms if active() else back_ms


class _Pacer(QObject):
    def __init__(self, widget: QWidget, timer, front_ms: int, back_ms: int):
        super().__init__(widget)
        self._timer, self._front, self._back = timer, front_ms, back_ms

    def on_state(self, _state):
        if self._timer.isActive():
            self._timer.setInterval(interval(self._front, self._back))


def slow_in_background(widget: QWidget, timer, front_ms: int,
                       back_ms: int = BG_METER_MS) -> None:
    """A running `timer` ticks every `back_ms` while another program is in front and
    every `front_ms` again once the app is back. For timers that must keep going
    behind a game (a recording's length cap), just less often; start them with
    interval(front_ms, back_ms)."""
    app = QGuiApplication.instance()
    if app is not None:
        app.applicationStateChanged.connect(_Pacer(widget, timer, front_ms, back_ms).on_state)
