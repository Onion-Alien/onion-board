"""Every number box (QSpinBox / QDoubleSpinBox) takes what you type without Enter.

Most boxes only count a typed value on Enter or once the keyboard focus moves on
(`setKeyboardTracking(False)`: "150" mustn't go 1 %, 15 %, 150 %). But clicking empty
space or a slider doesn't move the focus, so "2" sat in the speed box doing nothing,
and Enter went on to the window too: in the Live controls popup it pressed Reset all,
snapping "2" straight back to 1.00x. So, for the box the focus is in:

- a pause in typing (PAUSE_MS) sets the value, keeping the text as typed
  ("2", not "2.00x" under the cursor) until Enter or leaving tidies it;
- a click anywhere else in its window sets it;
- Enter sets it and stops there, never pressing one of the window's buttons.

The app-wide filter is only on while a number box has the focus: filtering every
event the app sees for this would cost on every mouse move."""
from __future__ import annotations

import shiboken6
from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QWidget

PAUSE_MS = 700
_ENTER = (Qt.Key.Key_Return, Qt.Key.Key_Enter)


def box_of(w) -> QAbstractSpinBox | None:
    """The editable number box `w` is (or is the text part of), else None."""
    for cand in (w, w.parentWidget() if isinstance(w, QWidget) else None):
        if isinstance(cand, QAbstractSpinBox) and not cand.isReadOnly():
            return cand
    return None


class _Commit(QObject):
    def __init__(self, app: QApplication):
        super().__init__(app)
        self.app = app
        self.box: QAbstractSpinBox | None = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(PAUSE_MS)
        self.timer.timeout.connect(self._pause)
        app.focusChanged.connect(self._focus)

    def _live(self) -> QAbstractSpinBox | None:
        """The box the focus is in, unless it has been deleted meanwhile."""
        return self.box if self.box is not None and shiboken6.isValid(self.box) else None

    def _focus(self, _old, new):
        box = box_of(new) if new is not None else None
        if box is self.box:
            return
        self.timer.stop()
        old = self._live()
        if old is not None:
            try:
                old.lineEdit().textEdited.disconnect(self._edited)
            except (RuntimeError, TypeError):
                pass
        if self.box is not None:
            self.app.removeEventFilter(self)
        self.box = box
        if box is not None:
            box.lineEdit().textEdited.connect(self._edited)
            self.app.installEventFilter(self)

    def _edited(self, _text):
        box = self._live()
        if box is not None and not box.keyboardTracking():   # tracking: it's live already
            self.timer.start()

    def _pause(self):
        """Set the typed value, but leave the text and cursor as the user has them."""
        box = self._live()
        if box is None or not box.hasFocus():
            return
        le = box.lineEdit()
        text, pos = le.text(), le.cursorPosition()
        if box.validate(text, pos)[0] != QValidator.State.Acceptable:
            return   # "-", "1." : not a number yet
        box.interpretText()
        if shiboken6.isValid(le) and le.text() != text:
            le.setText(text)
            le.setCursorPosition(pos)

    def commit(self):
        self.timer.stop()
        box = self._live()
        if box is not None:
            box.interpretText()

    def eventFilter(self, obj, e):
        box = self._live()
        if box is None or not isinstance(obj, QWidget):
            return False
        t = e.type()
        if t == QEvent.Type.MouseButtonPress:
            if obj is not box and not box.isAncestorOf(obj) and obj.window() is box.window():
                self.commit()
        elif (t == QEvent.Type.KeyPress and e.key() in _ENTER and obj is not box
              and obj.isAncestorOf(box)):
            # the box has set its value and passed Enter up: it goes no further
            self.timer.stop()
            return True
        return False


def install(app: QApplication) -> None:
    if getattr(app, "_numberbox", None) is None:
        app._numberbox = _Commit(app)   # pyright: ignore[reportAttributeAccessIssue]  # kept alive on the app
