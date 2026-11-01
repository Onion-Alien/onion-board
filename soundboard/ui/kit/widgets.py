"""Small shared widgets (the placeholder fitter, the inline name box, the window's
painted root, click focus, steady tabs), and the one place to import the hand-painted
ones from: the meters (meters.py), the seek row (seek.py), a sound's pad (pad.py), the
board's grid (padgrid.py) and the layout helpers (layouts.py) all come through here."""
from __future__ import annotations

from PySide6.QtCore import (QEvent, QObject, QPointF, Qt, Signal)
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (QAbstractButton, QAbstractSlider, QApplication, QComboBox, QLineEdit,
                               QMenu, QTabBar, QStackedWidget, QStyle, QStyleOptionFrame,
                               QTabWidget, QWidget)
from shiboken6 import isValid as qt_valid

from soundboard.sounds import library
from soundboard.ui.kit import theme
from soundboard.ui.kit.layouts import (take_out, widget_at)  # noqa: F401
from soundboard.ui.kit.meters import (EqCurve, FFT_N, LoadingBar, Meter, loudness,  # noqa: F401
                                      paint_now_playing, spectrum)
from soundboard.ui.kit.seek import (CrispSlider, EdgeMatch, NameAndSeek, SeekSlider,  # noqa: F401
                                    fmt_pos, fmt_time)
from soundboard.ui.kit.padgrid import (PadGrid, expand_dropped)  # noqa: F401
from soundboard.ui.kit.pad import (HOVER_LIFT, HOVER_MS, LINK_PX, LIST_ROW_H,  # noqa: F401
                                   LIST_ROW_W, MINI_PAD_MIN_W, PAD_MIME, PAD_RADIUS, PAD_SHRINK,
                                   PIC_SHADE, PIC_SHADE_HOVER, Pad, ROW_MAX_H, SLIM_PAD_H,
                                   STOP_HIT_PX, STOP_PX, pad_colours, pad_height)


class _PlaceholderFit(QObject):
    """fit_placeholder's resize watcher (one for the app)."""

    def eventFilter(self, obj, e):   # noqa: N802 - Qt
        try:
            # Show too: a box resized while hidden (the mini player) kept its old hint
            if e.type() in (QEvent.Type.Resize, QEvent.Type.FontChange,
                            QEvent.Type.StyleChange, QEvent.Type.Show):
                _refit_placeholder(obj)
        except Exception:  # noqa: BLE001 - never raise from a Qt override (AGENT-RULES)
            pass
        return False


_placeholder_fit: _PlaceholderFit | None = None


def fit_placeholder(edit: QLineEdit, *hints: str):
    """The box's grey hint: the first of `hints` (longest first) that fits, else the
    last ("Search"). Qt cut a long one to its first letters ("Sea…") in a narrow
    window. Call it again to change the words."""
    global _placeholder_fit
    if _placeholder_fit is None:
        _placeholder_fit = _PlaceholderFit(QApplication.instance())
    if edit.property("placeholders") is None:
        edit.installEventFilter(_placeholder_fit)
    edit.setProperty("placeholders", list(hints))
    _refit_placeholder(edit)


def _refit_placeholder(edit: QLineEdit):
    hints = edit.property("placeholders") or []
    if not hints:
        return
    # the room for text: its contents less the icon buttons inside it (search, clear:
    # the clear one keeps its place while the box is empty) and Qt's own 2 px a side
    opt = QStyleOptionFrame()
    edit.initStyleOption(opt)
    room = edit.style().subElementRect(QStyle.SubElement.SE_LineEditContents, opt,
                                       edit).width()
    m = edit.textMargins()
    room -= m.left() + m.right() + 8 + sum(
        c.width() for c in edit.children()
        if isinstance(c, QWidget) and c.metaObject().className() == "QLineEditIconButton")
    fm = edit.fontMetrics()
    text = next((h for h in hints if fm.horizontalAdvance(h) <= room), hints[-1])
    if edit.placeholderText() != text:
        edit.setPlaceholderText(text)


class InlineNameBox(QLineEdit):
    """A name box that takes a "+" button's place when it's clicked, so a new
    category is named right where it will show (no pop-up). Enter, or clicking away
    with something typed, sends `named`; Esc or an empty box puts the button back.
    Add it to the layout just before `button`."""

    named = Signal(str)

    def __init__(self, button: QAbstractButton, placeholder: str, width: int = 170,
                 max_len: int = library.CATEGORY_MAX, parent: QWidget | None = None):
        super().__init__(parent)
        self.button = button
        self.setAccessibleName(placeholder)
        self.setPlaceholderText(placeholder)
        self.setMaxLength(max_len)
        self.setFixedWidth(width)
        self.hide()
        button.clicked.connect(self.start)

    def start(self):
        self.clear()
        self.button.hide()
        self.show()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def _finish(self, text: str | None):
        if not self.isVisible():   # already closed (hiding it moves the focus out)
            return
        self.hide()
        self.button.show()
        if text is not None and text.strip():
            self.named.emit(text)

    def event(self, e):
        # Esc and Enter belong to the box while it's open, not to the window's shortcuts
        if e.type() == QEvent.Type.ShortcutOverride and e.key() in (
                Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            e.accept()
            return True
        return super().event(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self._finish(None)
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._finish(self.text())
        else:
            super().keyPressEvent(e)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        if e.reason() != Qt.FocusReason.PopupFocusReason:   # its own right-click menu
            self._finish(self.text())


class DropdownMenu(QMenu):
    """A button's dropdown menu. Like every dropdown it opens a short gap from its
    button, not stuck to it: the app style does that (wheelguard.drop_gap)."""


class WindowRoot(QWidget):
    """The main window's page: it paints the theme's window background itself (flat, or
    the Textured accent glow), the same picture opaque widgets copy (PadGrid)."""

    def paintEvent(self, e):
        p = QPainter(self)
        theme.paint_window_bg(p, e.rect(), QPointF(0, 0), self.width(), self.height())
        p.end()


def _clicked_kind(w) -> bool:
    """A control a click works (a button, a drop-down, a slider, a tab): no text to type."""
    if isinstance(w, QComboBox):
        return not w.isEditable()
    return isinstance(w, (QAbstractButton, QAbstractSlider, QTabBar))


def click_focus(w) -> None:
    """The focus ring is for the keyboard: a click, a drag or a pick from a drop-down
    left the control it touched ringed until something else was clicked. Those
    controls take the focus from the Tab key only, so a click never rings them (and
    never moves the focus off whatever had it)."""
    if _clicked_kind(w):
        policy = w.focusPolicy()
        if policy in (Qt.FocusPolicy.StrongFocus, Qt.FocusPolicy.WheelFocus):
            w.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        elif policy == Qt.FocusPolicy.ClickFocus:
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)


KEY_FOCUS = "keyfocus"   # dynamic property: the focus came from the keyboard (ringed)


def _set_key_focus(w, on: bool) -> None:
    if bool(w.property(KEY_FOCUS)) != on:
        w.setProperty(KEY_FOCUS, on)
        w.style().unpolish(w)   # the style sheet's [keyfocus="true"]:focus rules
        w.style().polish(w)
        w.update()


def key_focus_rings(old, new) -> None:
    """A dialog that opens hands its first button the focus by itself, and the theme's
    :focus rule ringed it before anyone pressed Tab: it looked picked while the mouse
    was elsewhere, and hovering it barely showed. A button's ring follows the keyboard
    only: Qt marks a window whose focus moved by Tab or the arrows
    (WA_KeyboardFocusChange), and theme.key_focus_only() makes the rings need it."""
    if isinstance(old, QAbstractButton):
        _set_key_focus(old, False)
    if isinstance(new, QAbstractButton):
        _set_key_focus(new, new.window().testAttribute(Qt.WidgetAttribute.WA_KeyboardFocusChange))


def install_click_focus(app: QApplication) -> None:
    """click_focus() on every widget the app shows from now on, as the app style
    polishes it (wheelguard.on_polish: no application-wide event filter), and a
    button's ring for the keyboard's focus only (key_focus_rings)."""
    from soundboard.ui.kit import wheelguard
    wheelguard.on_polish(click_focus)
    app.focusChanged.connect(key_focus_rings)


class SteadyTabs(QObject):
    """Keeps a QTabWidget from repainting all of itself when nothing it lays out
    changed. It answers every layout request from inside (a label's new text, a
    chip in the now-playing row, a tab's new icon) by laying out its tab bar and page
    area again and repainting everything under it: every pad on the board, 2-3
    times a pad press. Only its own size, the tab bar's and corner's size hints and
    the pages' minimum size matter to that layout; while those stay the same the
    request is dropped (the page inside still lays itself out)."""

    def __init__(self, tabs: QTabWidget):
        super().__init__(tabs)
        self._tabs = tabs
        self._stack = tabs.findChild(QStackedWidget, "qt_tabwidget_stackedwidget",
                                     Qt.FindChildOption.FindDirectChildrenOnly)
        self._last = None
        tabs.installEventFilter(self)

    def _state(self):
        t, bar = self._tabs, self._tabs.tabBar()
        if self._stack is not None and not qt_valid(self._stack):   # (seen once: find it again)
            self._stack = t.findChild(QStackedWidget, "qt_tabwidget_stackedwidget",
                                      Qt.FindChildOption.FindDirectChildrenOnly)
        corners = tuple(w.sizeHint() if w is not None and w.isVisible() else None
                        for w in (t.cornerWidget(Qt.Corner.TopLeftCorner),
                                  t.cornerWidget(Qt.Corner.TopRightCorner)))
        return (t.size(), t.isVisible(), t.count(), t.currentIndex(), bar.sizeHint(),
                bar.minimumSizeHint(), corners,
                self._stack.minimumSizeHint() if self._stack is not None else None)

    def eventFilter(self, obj, ev):
        if obj is self._tabs and ev.type() == QEvent.Type.LayoutRequest:
            state = self._state()
            if state == self._last:
                return True
            self._last = state
        return False


