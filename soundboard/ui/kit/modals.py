"""Two app-wide fixes for dialogs, installed once (install(app)).

No white flash: Windows puts a new window on screen before Qt has drawn anything in it,
so a dialog (Qt's own small ones most of all: a name to type, a yes/no question) showed
as a white box for a moment. Every dialog now starts see-through and turns solid once
its first frame is painted.

A click outside closes it: a modal dialog blocks the rest of the app, and clicking there
only got Windows' error sound. Now a left click anywhere else in the app closes the
dialog in front, the same as Cancel. Dialogs where that would throw work away (editing
a sound, the setup guide, a recording, text typed in a form) say so with
keep_open(dlg) or a class attribute KEEP_OPEN = True, and keep the old behaviour.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QWidget
from shiboken6 import isValid as qt_valid

SHOW_AFTER_PAINT_MS = 30   # one more frame after the first paint, for the compositor
SHOW_ANYWAY_MS = 250       # never left invisible if no paint comes

WM_SETCURSOR = 0x0020
WM_LBUTTONDOWN = 0x0201
WM_NCLBUTTONDOWN = 0x00A1
HTERROR = 0xFFFE   # (-2) a click on a window a modal dialog blocks


def keep_open(dlg: QDialog) -> QDialog:
    """`dlg` doesn't close on a click outside it (closing it would lose work)."""
    dlg.setProperty("keep_open", True)
    return dlg


def closes_on_click_outside(dlg: QWidget) -> bool:
    return (isinstance(dlg, QDialog) and not getattr(dlg, "KEEP_OPEN", False)
            and not dlg.property("keep_open"))


class _NoFlash(QObject):
    """On each dialog only (an application filter is called for every event of every
    object): hides it (opacity 0) from its Show until its first paint is on screen."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hidden: set[QWidget] = set()   # shown, not painted yet

    def eventFilter(self, obj, ev):   # noqa: N802 - Qt API
        t = ev.type()
        if t == QEvent.Type.Paint:
            if obj in self._hidden:
                QTimer.singleShot(SHOW_AFTER_PAINT_MS, obj, lambda o=obj: self._reveal(o))
        elif t == QEvent.Type.Show:
            if (obj.isWindow() and obj not in self._hidden
                    and not obj.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
                    and obj.windowOpacity() == 1.0):
                self._hidden.add(obj)
                obj.setWindowOpacity(0.0)   # before Windows puts it on screen
                # (timed on self: still runs, and forgets it, if the dialog is freed)
                QTimer.singleShot(SHOW_ANYWAY_MS, self, lambda o=obj: self._reveal(o))
        elif t == QEvent.Type.Hide and obj in self._hidden:
            self._reveal(obj)   # shown again later: hidden again until painted
        return False

    def _reveal(self, dlg: QWidget) -> None:
        if dlg in self._hidden:
            self._hidden.discard(dlg)
            if qt_valid(dlg):
                dlg.setWindowOpacity(1.0)


_no_flash: _NoFlash | None = None


def _polished(w) -> None:
    """Every widget as the app style polishes it (wheelguard.on_polish), before it's
    first shown: each dialog gets watched."""
    global _no_flash
    if isinstance(w, QDialog):
        if _no_flash is None:
            _no_flash = _NoFlash()
        w.installEventFilter(_no_flash)   # once: Qt doesn't add it twice


class _MSG(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD), ("pt", wintypes.POINT)]


def _outside_click(msg: _MSG) -> bool:
    """A left click on one of our windows that a modal dialog blocks."""
    if msg.message == WM_SETCURSOR:   # how Windows reports a click on a blocked window
        lp = msg.lParam or 0
        return (lp & 0xFFFF) == HTERROR and (lp >> 16) & 0xFFFF in (WM_LBUTTONDOWN,
                                                                    WM_NCLBUTTONDOWN)
    return False


def close_front_dialog() -> bool:
    """Close the modal dialog in front, if it may be closed that way. True if it was."""
    dlg = QApplication.activeModalWidget()
    if not isinstance(dlg, QDialog) or not closes_on_click_outside(dlg):
        return False
    QTimer.singleShot(0, dlg, dlg.reject)   # after Windows is done with this click
    return True


class _ClickOutside(QAbstractNativeEventFilter):
    def nativeEventFilter(self, event_type, message):   # noqa: N802 - Qt API
        try:
            if bytes(event_type) == b"windows_generic_MSG" and _outside_click(
                    _MSG.from_address(int(message))) and close_front_dialog():
                return True, 1   # handled: no error sound
        except Exception:  # noqa: BLE001 - never break the app's input over this
            pass
        return False, 0


_click_outside: _ClickOutside | None = None


def install(app: QApplication) -> None:
    from soundboard.ui.kit import wheelguard
    wheelguard.on_polish(_polished)
    if sys.platform == "win32":
        global _click_outside
        _click_outside = _ClickOutside()   # kept alive while the app runs
        app.installNativeEventFilter(_click_outside)
