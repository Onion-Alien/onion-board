"""Make the mouse wheel scroll the page instead of changing a value.

Scrolling over a dropdown, slider or number box would otherwise change it (and
stop the page scrolling), which is a classic way to nudge a volume by accident.

The filter is installed on the individual widgets that need it, not on the
application: an application-wide filter runs a Python call for *every* event of
every object (mouse moves, paints, timers, the web view's stream), which was a
measurable idle cost.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import (QAbstractScrollArea, QAbstractSlider, QAbstractSpinBox,
                               QApplication, QComboBox, QScrollBar)

_guard: _Guard | None = None


class _Guard(QObject):
    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Wheel and isinstance(
                obj, (QComboBox, QAbstractSpinBox, QAbstractSlider)) \
                and not isinstance(obj, QScrollBar):
            w = obj.parentWidget()
            while w is not None and not isinstance(w, QAbstractScrollArea):
                w = w.parentWidget()
            if w is not None:
                QApplication.sendEvent(w.verticalScrollBar(), ev)
            return True
        return False


def no_wheel(*widgets):
    """Install the guard on these widgets (dropdowns, sliders, spin boxes)."""
    global _guard
    if _guard is None:
        _guard = _Guard()
    for w in widgets:
        w.installEventFilter(_guard)
