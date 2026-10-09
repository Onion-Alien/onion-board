"""Make the mouse wheel scroll the page instead of changing a value.

Scrolling over a dropdown, slider or number box would otherwise change it (and
stop the page scrolling), which is a classic way to nudge a volume by accident.

The filter is installed on the individual widgets that need it, not on the
application: an application-wide filter runs a Python call for *every* event of
every object (mouse moves, paints, timers, the web view's stream), which was a
measurable idle cost.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (QAbstractScrollArea, QAbstractSlider, QAbstractSpinBox,
                               QApplication, QComboBox, QProxyStyle,
                               QScrollBar, QStyle)

_guard: _Guard | None = None


class AppStyle(QProxyStyle):
    """Fusion, with two app-wide changes that reach every window, the add-ons'
    included (Onion Watch's Triggers / Log strip), at no per-event cost:

    - the wheel never changes a dropdown or flips a tab strip. Rolling past the
      Radio filters changed them; rolling over Triggers / Log switched pages. An
      open dropdown's list still scrolls (that's its own view).
    - a click anywhere on a slider's bar moves it there, not a page step towards it.
    """

    def styleHint(self, hint, opt=None, widget=None, ret=None):
        if hint in (QStyle.SH_ComboBox_AllowWheelScrolling,
                    QStyle.SH_TabBar_AllowWheelScrolling):
            return 0
        if hint == QStyle.SH_Slider_AbsoluteSetButtons:
            return Qt.LeftButton.value
        return super().styleHint(hint, opt, widget, ret)


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
        w.setProperty("noWheel", True)   # lets a test find any control left unguarded
