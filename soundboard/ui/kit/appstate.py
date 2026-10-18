"""Stopping decoration while the app is in the background.

A window left open behind a game is still "visible" to Qt, so show / hide events
alone keep every animation going at full speed. Widgets that only decorate (the logo,
the mascots, the live dot) use `pause_in_background` to also stop while another
program is in front.
"""
from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

# active() and pause_in_background() live in the style kit, which Hoot shares with Onion
# Watch
from soundboard.style.appstate import active, pause_in_background  # noqa: F401


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
    if isinstance(app, QGuiApplication):
        app.applicationStateChanged.connect(_Pacer(widget, timer, front_ms, back_ms).on_state)
