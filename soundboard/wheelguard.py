"""Make the mouse wheel scroll the page instead of changing a value.

Scrolling over a dropdown, slider or number box would otherwise change it (and
stop the page scrolling), which is a classic way to nudge a volume by accident.

The filter is installed on the individual widgets that need it, not on the
application: an application-wide filter runs a Python call for *every* event of
every object (mouse moves, paints, timers, the web view's stream), which was a
measurable idle cost.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPointF, Qt, QTimer
from PySide6.QtGui import QHoverEvent, QMouseEvent
from PySide6.QtWidgets import (QAbstractScrollArea, QAbstractSlider, QAbstractSpinBox,
                               QApplication, QCheckBox, QComboBox, QFormLayout,
                               QGridLayout, QLayout, QMenu, QProxyStyle,
                               QScrollBar, QSizePolicy, QSlider, QTabBar, QWidget)

QWIDGETSIZE_MAX = (1 << 24) - 1

_guard: _Guard | None = None


class AppStyle(QProxyStyle):
    """Fusion, with two app-wide changes that reach every window, the add-ons'
    included (Onion Watch's Triggers / Log strip):

    - the wheel never changes a dropdown or flips a tab strip. Rolling past the
      Radio filters changed them; rolling over Triggers / Log switched pages. An
      open dropdown's list still scrolls (that's its own view).
    - a click anywhere on a slider's bar moves it there, not a page step towards it.
    - a dropdown is as wide as its longest choice, capped at COMBO_CAP, and never
      stretches to fill its card (Settings' device boxes were 720 px for a 30-letter
      name). One that set its own size policy, width cap or sizing rule keeps it.
    - a submenu opens just past its menu's edge, not over it (Fusion put it 7 px
      inside the menu's border and padding, theme.py's QMenu): _SubmenuEdge moves it
      when it shows. Not a pixelMetric override: every Python override here is called
      by Qt from C++ tens of thousands of times per theme switch, and each call waits
      for Python's lock while an audio thread holds it (freezes of 11 s and 36 s).
      The wheel and slider changes are for the same reason _AppFilter on those
      widgets, not a styleHint override (~28k calls per switch).
    - popups clear hover on the controls behind their mouse grab, so moving away
      while a menu is open never leaves its opener highlighted.
    - tick boxes take keyboard focus from Tab, so mouse clicks do not leave a
      focus ring behind. Keyboard users can still reach and toggle them.
    """

    COMBO_CAP = 360

    def polish(self, arg):
        super().polish(arg)
        if isinstance(arg, (QComboBox, QTabBar, QSlider)):
            arg.installEventFilter(_app_filter())   # once: Qt doesn't add it twice
            if isinstance(arg, QComboBox):
                snug_combo(arg, self.COMBO_CAP)
        elif isinstance(arg, QCheckBox) and arg.focusPolicy() == Qt.FocusPolicy.StrongFocus:
            arg.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        elif isinstance(arg, QMenu):
            arg.installEventFilter(_submenu_edge())   # once: Qt doesn't add it twice
        elif isinstance(arg, QWidget) and arg.windowType() == Qt.WindowType.Popup:
            arg.installEventFilter(_submenu_edge())



class _AppFilter(QObject):
    """AppStyle's wheel and slider changes, on each dropdown, tab strip and slider."""
    WHEEL, PRESS = QEvent.Type.Wheel, QEvent.Type.MouseButtonPress

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == self.WHEEL and isinstance(obj, (QComboBox, QTabBar)):
            ev.ignore()   # passed on to the parent, so the page scrolls instead
            return True
        if t == self.PRESS and isinstance(obj, QSlider) \
                and ev.button() == Qt.MouseButton.LeftButton:
            # Qt's own jump-to-the-click is the middle button: hand it that press
            mid = QMouseEvent(QEvent.Type.MouseButtonPress, ev.position(),
                              ev.scenePosition(), ev.globalPosition(),
                              Qt.MouseButton.MiddleButton, Qt.MouseButton.MiddleButton,
                              ev.modifiers())
            QApplication.sendEvent(obj, mid)
            ev.setAccepted(mid.isAccepted())
            return True
        return False


_filter: _AppFilter | None = None


def _app_filter() -> _AppFilter:
    global _filter
    if _filter is None:
        _filter = _AppFilter()
    return _filter


class _SubmenuEdge(QObject):
    """Clear hover behind popups and keep submenus outside their parent menu."""
    GAP = 2

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Show and obj.windowType() == Qt.WindowType.Popup:
            # A popup grabs the mouse before the opener receives Leave. Moving away
            # while it is open can then leave both QSS and custom hover fills stuck.
            # Send the normal leave events, including to hovered cards and parents.
            for window in QApplication.topLevelWidgets():
                if window is obj or window.windowType() == Qt.WindowType.Popup:
                    continue
                for widget in [window, *window.findChildren(QWidget)]:
                    if widget.window() is window and widget.underMouse():
                        widget.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
                        QApplication.sendEvent(widget, QEvent(QEvent.Type.Leave))
                        if widget.testAttribute(Qt.WidgetAttribute.WA_Hover):
                            QApplication.sendEvent(widget, QHoverEvent(
                                QEvent.Type.HoverLeave, QPointF(-1, -1),
                                QPointF(widget.mapToGlobal(widget.rect().center())),
                                QPointF(-1, -1)))
                        widget.update()
        if ev.type() == QEvent.Type.Show and isinstance(obj, QMenu):
            parent = obj.parentWidget()
            if isinstance(parent, QMenu) and parent.isVisible():
                pg, g = parent.geometry(), obj.geometry()
                if g.left() <= pg.right() and g.right() >= pg.left():   # they overlap
                    x = (pg.right() + 1 + self.GAP if g.center().x() >= pg.center().x()
                         else pg.left() - self.GAP - g.width())
                    obj.move(x, g.top())
        return False


_edge: _SubmenuEdge | None = None


def _submenu_edge() -> _SubmenuEdge:
    global _edge
    if _edge is None:
        _edge = _SubmenuEdge()
    return _edge


def snug_combo(cb: QComboBox, cap: int = AppStyle.COMBO_CAP):
    """Size a dropdown to its longest choice (up to the cap) instead of the row.

    Many use a short minimum so a long device name can't make a page scroll sideways
    in a narrow window: that minimum stays as a floor, the box just *prefers* its
    words now and never grows past them. One the code gave its own width limit or a
    non-default size policy is left alone. Redone whenever its choices change."""
    managed = cb.property("snug")
    if managed is None:
        if (cb.sizePolicy().horizontalPolicy() != QSizePolicy.Policy.Preferred
                or cb.maximumWidth() < QWIDGETSIZE_MAX):
            cb.setProperty("snug", False)
            return
        cb.setProperty("snug", True)
        short = cb.sizeAdjustPolicy() != QComboBox.SizeAdjustPolicy.AdjustToContentsOnFirstShow
        if short and not cb.minimumWidth():
            cb.setMinimumWidth(cb.minimumSizeHint().width())   # keep the short floor
        cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        m = cb.model()
        refit = lambda *_a: _refit(cb, cap)  # noqa: E731
        for sig in (m.rowsInserted, m.rowsRemoved, m.modelReset, m.dataChanged):
            sig.connect(refit)
    elif not managed:
        return
    _refit(cb, cap)
    # again once the theme's stylesheet has polished it too (its padding counts)
    QTimer.singleShot(0, cb, lambda: _refit(cb, cap))


def _own_width(cb: QComboBox, cap: int) -> int:
    return max(cb.minimumWidth(), min(cap, cb.sizeHint().width()))


def _column_mates(cb: QComboBox) -> list[QComboBox]:
    """The snug dropdowns stacked in cb's grid / form column, cb included: they share
    the widest one's width (Settings -> Devices' three boxes were 300, 358 and 358 px,
    each fitting its own device name). Just cb when it isn't in one."""
    parent = cb.parentWidget()
    top = parent.layout() if parent is not None else None
    todo: list[QLayout] = [top] if top is not None else []
    while todo:
        lay = todo.pop()
        i = lay.indexOf(cb)
        if i >= 0:
            if isinstance(lay, QGridLayout):
                col = lay.getItemPosition(i)[1]  # pyright: ignore[reportIndexIssue]  (a tuple)
                cells = [lay.itemAtPosition(r, col) for r in range(lay.rowCount())]
            elif isinstance(lay, QFormLayout):
                role = lay.getItemPosition(i)[1]  # pyright: ignore[reportIndexIssue]  (a tuple)
                cells = [lay.itemAt(r, role) for r in range(lay.rowCount())]
            else:
                return [cb]
            mates = [c.widget() for c in cells if c is not None]
            return [w for w in mates if isinstance(w, QComboBox)
                    and w.property("snug") is True and not w.isHidden()] or [cb]
        for j in range(lay.count()):
            item = lay.itemAt(j)
            sub = item.layout() if item is not None else None
            if sub is not None:
                todo.append(sub)
    return [cb]


def _refit(cb: QComboBox, cap: int):
    try:
        mates = _column_mates(cb)
        width = max(_own_width(m, cap) for m in mates)
        for m in mates:
            m.setMaximumWidth(width)
        if cb not in mates:
            cb.setMaximumWidth(_own_width(cb, cap))
    except RuntimeError:   # the model outlived its dropdown
        pass


class _Guard(QObject):
    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Wheel and isinstance(
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
