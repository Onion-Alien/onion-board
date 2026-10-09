"""Make the mouse wheel scroll the page instead of changing a value.

Scrolling over a dropdown, slider or number box would otherwise change it (and
stop the page scrolling), which is a classic way to nudge a volume by accident.

The filter is installed on the individual widgets that need it, not on the
application: an application-wide filter runs a Python call for *every* event of
every object (mouse moves, paints, timers, the web view's stream), which was a
measurable idle cost.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import (QAbstractScrollArea, QAbstractSlider, QAbstractSpinBox,
                               QApplication, QComboBox, QProxyStyle,
                               QScrollBar, QSizePolicy, QStyle)

QWIDGETSIZE_MAX = (1 << 24) - 1

_guard: _Guard | None = None


class AppStyle(QProxyStyle):
    """Fusion, with two app-wide changes that reach every window, the add-ons'
    included (Onion Watch's Triggers / Log strip), at no per-event cost:

    - the wheel never changes a dropdown or flips a tab strip. Rolling past the
      Radio filters changed them; rolling over Triggers / Log switched pages. An
      open dropdown's list still scrolls (that's its own view).
    - a click anywhere on a slider's bar moves it there, not a page step towards it.
    - a dropdown is as wide as its longest choice, capped at COMBO_CAP, and never
      stretches to fill its card (Settings' device boxes were 720 px for a 30-letter
      name). One that set its own size policy, width cap or sizing rule keeps it.
    """

    COMBO_CAP = 360

    def polish(self, arg):
        super().polish(arg)
        if isinstance(arg, QComboBox):
            snug_combo(arg, self.COMBO_CAP)

    def styleHint(self, hint, opt=None, widget=None, ret=None):
        if hint in (QStyle.SH_ComboBox_AllowWheelScrolling,
                    QStyle.SH_TabBar_AllowWheelScrolling):
            return 0
        if hint == QStyle.SH_Slider_AbsoluteSetButtons:
            return Qt.LeftButton.value
        return super().styleHint(hint, opt, widget, ret)


def snug_combo(cb: QComboBox, cap: int = AppStyle.COMBO_CAP):
    """Size a dropdown to its longest choice (up to the cap) instead of the row.

    Many use a short minimum so a long device name can't make a page scroll sideways
    in a narrow window: that minimum stays as a floor, the box just *prefers* its
    words now and never grows past them. One the code gave its own width limit or a
    non-default size policy is left alone. Redone whenever its choices change."""
    managed = cb.property("snug")
    if managed is None:
        if (cb.sizePolicy().horizontalPolicy() != QSizePolicy.Preferred
                or cb.maximumWidth() < QWIDGETSIZE_MAX):
            cb.setProperty("snug", False)
            return
        cb.setProperty("snug", True)
        short = cb.sizeAdjustPolicy() != QComboBox.AdjustToContentsOnFirstShow
        if short and not cb.minimumWidth():
            cb.setMinimumWidth(cb.minimumSizeHint().width())   # keep the short floor
        cb.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        m = cb.model()
        refit = lambda *_a: _refit(cb, cap)  # noqa: E731
        for sig in (m.rowsInserted, m.rowsRemoved, m.modelReset, m.dataChanged):
            sig.connect(refit)
    elif not managed:
        return
    _refit(cb, cap)
    # again once the theme's stylesheet has polished it too (its padding counts)
    QTimer.singleShot(0, cb, lambda: _refit(cb, cap))


def _refit(cb: QComboBox, cap: int):
    try:
        cb.setMaximumWidth(max(cb.minimumWidth(), min(cap, cb.sizeHint().width())))
    except RuntimeError:   # the model outlived its dropdown
        pass


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
