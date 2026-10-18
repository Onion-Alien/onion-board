"""Make the mouse wheel scroll the page instead of changing a value.

Scrolling over a dropdown, slider or number box would otherwise change it (and
stop the page scrolling), which is a classic way to nudge a volume by accident.

The filter is installed on the individual widgets that need it, not on the
application: an application-wide filter runs a Python call for *every* event of
every object (mouse moves, paints, timers, the web view's stream), which was a
measurable idle cost.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QCursor, QHelpEvent, QHoverEvent, QMouseEvent, QPalette
from PySide6.QtWidgets import (QAbstractButton, QAbstractScrollArea, QAbstractSlider,
                               QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QFormLayout,
                               QGridLayout, QLayout, QMenu, QProxyStyle, QPushButton,
                               QScrollBar, QSizePolicy, QSlider, QTabBar, QToolButton,
                               QWidget)

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
    - a dropdown's list and a button's menu open DROP_GAP below (or above) their
      button, never stuck to its edge (drop_gap, also from _SubmenuEdge).
    - popups clear hover on the controls behind their mouse grab, so moving away
      while a menu is open never leaves its opener highlighted.
    - tick boxes take keyboard focus from Tab, so mouse clicks do not leave a
      focus ring behind. Keyboard users can still reach and toggle them.
    - a button's, pad's, dropdown's or tab's tooltip waits until the mouse has been
      on it TIP_DELAY seconds (_hold_tip), every time. Qt's own wait is 0.7 s, and
      for 2 s after one tooltip every other shows at once, so sweeping across the
      pads or the toolbar popped one up under the mouse at each step.
    """

    COMBO_CAP = 360

    def polish(self, arg):
        if not isinstance(arg, (QWidget, QApplication, QPalette)):
            # a dead layout item's wrapper still listed at the new widget's address
            # (ui/kit/widgets.py widget_at): Qt's own call must never raise from here
            return
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
        if isinstance(arg, (QAbstractButton, QComboBox)):
            arg.installEventFilter(_popup_click_guard())



TIP_DELAY = 1.0   # seconds on a control before its tooltip shows
_TIP_EVENTS = (QEvent.Type.Enter, QEvent.Type.Leave, QEvent.Type.ToolTip,
               QEvent.Type.MouseButtonPress, QEvent.Type.Wheel)


def _hold_tip(obj, ev) -> bool:
    """Hold a tooltip back until the mouse has rested on `obj` for TIP_DELAY,
    then show it where the mouse is. True = the event was held (eaten).

    Called from the filters already on buttons, dropdowns and tab strips (no new
    per-event filter). A click, a wheel turn or leaving starts the wait over.
    """
    t = ev.type()
    if t != QEvent.Type.ToolTip:
        obj.setProperty("tipFrom", None if t == QEvent.Type.Leave else time.monotonic())
        obj.setProperty("tipPending", None)
        return False
    start = obj.property("tipFrom")
    if start is None:   # hovered before it was polished: count from now
        start = time.monotonic()
        obj.setProperty("tipFrom", start)
    wait = TIP_DELAY - (time.monotonic() - start)
    if wait <= 0:
        return False
    if obj.property("tipPending") != start:
        obj.setProperty("tipPending", start)

        def show():
            if obj.property("tipPending") != start or not obj.underMouse():
                return
            obj.setProperty("tipPending", None)
            g = QCursor.pos()
            QApplication.sendEvent(obj, QHelpEvent(QEvent.Type.ToolTip, obj.mapFromGlobal(g), g))

        QTimer.singleShot(int(wait * 1000) + 1, obj, show)
    return True


class _AppFilter(QObject):
    """AppStyle's wheel and slider changes, on each dropdown, tab strip and slider,
    plus the tooltip wait on tab strips and sliders (dropdowns get it from
    _PopupClickGuard)."""
    WHEEL, PRESS = QEvent.Type.Wheel, QEvent.Type.MouseButtonPress

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t in _TIP_EVENTS and not isinstance(obj, QComboBox) and _hold_tip(obj, ev):
            return True
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
        if obj.windowType() == Qt.WindowType.Popup:
            if ev.type() == QEvent.Type.Show:
                opener = getattr(obj, "_opener", None)
                parent = obj.parentWidget()
                while opener is None and parent is not None:
                    if isinstance(parent, QMenu):
                        break
                    if isinstance(parent, (QAbstractButton, QComboBox)):
                        opener = parent
                    elif isinstance(obj, QMenu):
                        # setMenu() does not require the button to own the menu. Only
                        # Qt's own setMenu() buttons: other buttons' `menu` is theirs
                        # (a sound pad's is a signal, and calling it raised TypeError).
                        opener = next((button for button in parent.findChildren(QAbstractButton)
                                       if isinstance(button, (QPushButton, QToolButton))
                                       and button.menu() is obj), None)
                    parent = parent.parentWidget()
                # Submenus and context menus have no dropdown opener.
                # Qt's Python wrappers allow per-instance bookkeeping attributes.
                obj._click_opener = opener  # pyright: ignore[reportAttributeAccessIssue]
                if opener is not None and (isinstance(obj, QMenu)
                                           or isinstance(obj.parentWidget(), QComboBox)):
                    drop_gap(obj, opener)
            elif ev.type() == QEvent.Type.Hide:
                opener = getattr(obj, "_click_opener", None)
                if opener is not None:
                    opener.setProperty("popupClosedAt", time.monotonic())
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


DROP_GAP = 8   # px between a dropdown's list or menu and the button it opened from


def drop_gap(popup: QWidget, opener: QWidget):
    """Leave DROP_GAP between a dropdown's list (or a button's menu) and its button,
    instead of stuck to its edge: below it, or above it when it opened upwards. One
    already placed away from the button (its own gap, beside it) is left alone."""
    g = popup.geometry()
    top = opener.mapToGlobal(QPoint(0, 0)).y()
    bottom = top + opener.height()
    if bottom - 2 <= g.top() <= bottom + 1:          # under it, touching
        y = bottom + DROP_GAP
    elif top - 2 <= g.bottom() + 1 <= top + 1:      # over it, touching
        y = top - DROP_GAP - g.height()
    else:
        return
    screen = opener.screen()
    if screen is not None:
        room = screen.availableGeometry()
        y = max(room.top(), min(y, room.bottom() + 1 - g.height()))
    popup.move(g.x(), y)


_edge: _SubmenuEdge | None = None


def _submenu_edge() -> _SubmenuEdge:
    global _edge
    if _edge is None:
        _edge = _SubmenuEdge()
    return _edge


class _PopupClickGuard(QObject):
    """On every button and dropdown: the tooltip wait (_hold_tip), and:

    Require a short pause before reopening a dismissed dropdown with the mouse.

    Qt can replay the outside click that dismissed a popup onto its opener. That
    must not immediately reopen it. Repeated presses extend the pause, so a burst
    of clicks settles closed rather than flashing a new popup every few clicks.
    Keyboard input, menu choices and the first click remain immediate.
    """
    PAUSE = 0.25

    def eventFilter(self, obj, ev):
        kind = ev.type()
        if kind in _TIP_EVENTS and _hold_tip(obj, ev):   # the tooltip wait, see AppStyle
            return True
        if kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick) \
                and ev.button() == Qt.MouseButton.LeftButton:
            closed = obj.property("popupClosedAt")
            now = time.monotonic()
            blocked = closed is not None and now - closed < self.PAUSE
            obj.setProperty("popupClickBlocked", blocked)
            if blocked:
                obj.setProperty("popupClosedAt", now)
                ev.accept()
                return True
        elif kind == QEvent.Type.MouseButtonRelease \
                and ev.button() == Qt.MouseButton.LeftButton \
                and obj.property("popupClickBlocked"):
            obj.setProperty("popupClickBlocked", False)
            ev.accept()
            return True
        return False


_click_guard: _PopupClickGuard | None = None


def _popup_click_guard() -> _PopupClickGuard:
    global _click_guard
    if _click_guard is None:
        _click_guard = _PopupClickGuard()
    return _click_guard


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
    each fitting its own device name). Just cb when it isn't in one.

    Found by indexOf / getItemPosition only, never itemAt(): an item's Python wrapper
    outlives the item when Qt deletes it, and a widget made later at its address
    reached polish() as that stale item."""
    parent = cb.parentWidget()
    top = parent.layout() if parent is not None else None
    if parent is None or top is None:
        return [cb]
    for lay in [top, *top.findChildren(QLayout)]:
        i = lay.indexOf(cb)
        if i < 0:
            continue
        if not isinstance(lay, (QGridLayout, QFormLayout)):
            return [cb]
        # grid: (row, column, ...); form: (row, role)
        col = lay.getItemPosition(i)[1]  # pyright: ignore[reportIndexIssue]  (a tuple)
        mates = []
        for w in parent.findChildren(QComboBox):
            j = lay.indexOf(w)
            if j >= 0 and lay.getItemPosition(j)[1] == col:  # pyright: ignore[reportIndexIssue]
                mates.append(w)
        return [w for w in mates if w.property("snug") is True and not w.isHidden()] or [cb]
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
