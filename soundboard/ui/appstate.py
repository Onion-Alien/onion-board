"""Stopping decoration while the app is in the background.

A window left open behind a game is still "visible" to Qt, so show / hide events
alone keep every animation going at full speed. Widgets that only decorate (the logo,
the mascots, the live dot) use `pause_in_background` to also stop while another
program is in front.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Qt
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

    def on_state(self, state):
        if state != Qt.ApplicationActive:
            self._stop()
        elif self._widget.isVisible():
            self._start()


def pause_in_background(widget: QWidget, start: Callable[[], None],
                        stop: Callable[[], None]) -> None:
    """Call `stop` when the app goes to the background and `start` when it's back in
    front with `widget` showing. The widget still starts / stops itself on show / hide
    (checking `active()` before it starts)."""
    app = QGuiApplication.instance()
    if app is not None:
        app.applicationStateChanged.connect(_Pauser(widget, start, stop).on_state)
