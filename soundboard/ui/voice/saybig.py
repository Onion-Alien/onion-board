"""Two more ways to give the computer voice its words, beside the Say bar's one line:

- `SayBigPopup`: the bar's ⤢ opens a real text box in a pop-up card under the bar (the
  tab doesn't grow). Each line is said in turn; Say selection says just the marked
  words. What's typed stays for the next time it's opened.
- `QuickSayBox`: the "Quick-type box" hotkey's small box on top of everything. Type,
  Enter, and it's said; the box goes and the program you were in (the game, a browser)
  gets the keyboard back. Escape or clicking elsewhere closes it without saying."""
from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QMargins, QPoint, Qt, QTimer
from PySide6.QtGui import QCursor, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QLineEdit, QPlainTextEdit, QPushButton,
                               QVBoxLayout, QWidget)
from shiboken6 import isValid as qt_valid

from soundboard.i18n import _
from soundboard.ui.kit.modalframe import SHADOW, InfoCard
from soundboard.ui.kit import busy, panel

log = logging.getLogger(__name__)

BIG_W, BIG_ROWS = 560, 8      # the long-text card, and how many lines its box shows
QUICK_W = 520


def lines_of(text: str) -> list[str]:
    """The lines to say, one after another: blank ones and spaces at the ends dropped."""
    return [" ".join(ln.split()) for ln in text.splitlines() if ln.strip()]


class SayBigPopup(InfoCard):
    """The long-text card. `say(line)` says one line (the panel's say_line)."""

    def __init__(self, parent: QWidget, say: Callable[[str], object],
                 stop: Callable[[], object]):
        # the shared pop-up card (no mascot: a small tool by its button)
        super().__init__(_("Long text"), mascot="", button="", width=BIG_W, parent=parent)
        self._say, self._stop = say, stop
        self._anchor: QWidget | None = None
        v = self.frame.body
        self.box = QPlainTextEdit()
        self.box.setObjectName("saybox")
        self.box.setPlaceholderText(_("Type or paste as much as you like. Each line is said "
                                      "in turn."))
        fm = self.box.fontMetrics()
        self.box.setFixedHeight(BIG_ROWS * fm.lineSpacing() + self.box.frameWidth() * 2 + 16)
        v.addWidget(self.box)
        self.b_all = self.frame.add_button(_("Say all"), primary=True)
        self.b_all.setDefault(False)   # (Enter is a new line in the box)
        self.b_all.setToolTip(_("Says every line, one after another (Ctrl+Enter)"))
        self.b_all.clicked.connect(self.say_all)
        self.b_sel = self.frame.add_button(_("Say selection"))
        self.b_sel.setToolTip(_("Says only the words you marked"))
        self.b_sel.clicked.connect(self.say_selection)
        b_stop = self.frame.add_button(_("Stop"))
        b_stop.clicked.connect(lambda: (self._stop(), busy.flash(b_stop, _("✓ Stopped"), 1200)))
        for keys in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(keys), self.box, self.say_all)

    def say_all(self):
        self._say_lines(self.box.toPlainText(), self.b_all)

    def say_selection(self):
        self._say_lines(self.box.textCursor().selectedText().replace(" ", "\n"),
                        self.b_sel, _("Mark some words first"))

    def _say_lines(self, text: str, btn: QPushButton, empty: str = ""):
        lines = lines_of(text)
        if not lines:
            busy.flash(btn, empty or _("Type a line first"), 1600)
            self.box.setFocus()
            return
        for ln in lines:
            self._say(ln)

    def open_at(self, anchor: QWidget, text: str = ""):
        """Open under `anchor` (the bar's ⤢); `text`: the bar's line, carried over."""
        self._anchor = anchor
        if text:
            self.box.setPlainText(text if not self.box.toPlainText().strip()
                                  else self.box.toPlainText().rstrip("\n") + "\n" + text)
        a = anchor.window().width()
        self.setFixedWidth(max(300, min(BIG_W, a - 16)) + 2 * SHADOW)
        self.adjustSize()
        self.show()
        self._place()
        self.box.setFocus()
        self.box.moveCursor(self.box.textCursor().MoveOperation.End)

    def _place(self):
        a = self._anchor
        if a is None or not qt_valid(a) or not a.isVisible():
            return
        rtl = a.layoutDirection() == Qt.LayoutDirection.RightToLeft
        lay = self.layout()   # (the shadow's room round the panel)
        m = lay.contentsMargins() if lay is not None else QMargins()
        corner = a.mapToGlobal(QPoint(0 if rtl else a.width(), a.height() + 6))
        x = corner.x() - m.left() if rtl else corner.x() - self.width() + m.right()
        scr = a.screen().availableGeometry()
        win = a.window().geometry()
        left = max(scr.left(), win.left()) - m.left()
        right = min(scr.right(), win.right()) + m.right()
        y = corner.y() - m.top()
        if y + self.height() > scr.bottom():
            y = max(scr.top(), a.mapToGlobal(QPoint(0, 0)).y() - self.height() + m.bottom() - 6)
        self.move(max(left, min(x, right - self.width())), y)


class QuickSayBox(QWidget):
    """The hotkey's box: one line on top of everything, near the mouse. `say(text)`
    says it; `to_front(hwnd)` / `front()` give the keyboard to a window / name the one
    that has it (winkeys, swapped out in tests)."""

    def __init__(self, say: Callable[[str], object], to_front: Callable[[int], object],
                 front: Callable[[], int]):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(_("Say a line"))
        self._say, self._to_front, self._front = say, to_front, front
        self._was = 0   # the window that had the keyboard before the box
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card, v = panel.card(_("Say a line"), icon="speech")
        card.setProperty("popup", True)
        outer.addWidget(card)
        self.ed = QLineEdit()
        self.ed.setPlaceholderText(_("Type, then Enter. Esc closes."))
        self.ed.returnPressed.connect(self._enter)
        v.addWidget(self.ed)
        self.setFixedWidth(QUICK_W)

    def pop(self):
        """Show it near the mouse with the keyboard in it (the hotkey)."""
        if self.isVisible():
            self.ed.setFocus()
            return
        self._was = self._front() or 0
        scr = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        g = scr.availableGeometry()
        self.adjustSize()
        self.move(g.left() + (g.width() - self.width()) // 2, g.top() + g.height() // 4)
        self.show()
        self.raise_()
        self.activateWindow()
        self._to_front(int(self.winId()))
        self.ed.setFocus()

    def _enter(self):
        text = " ".join(self.ed.text().split())
        if text:
            self._say(text)
        self.ed.clear()
        self.done()

    def done(self):
        """Away, and the keyboard back to where it was."""
        self.ed.clear()
        # before hide(): that can say the box lost the keyboard, which forgets the window
        was, self._was = self._was, 0
        self.hide()
        if was:
            QTimer.singleShot(0, lambda: self._to_front(was))

    def keyPressEvent(self, e):   # noqa: N802 - Qt
        if e.key() == Qt.Key.Key_Escape:
            self.done()
            return
        super().keyPressEvent(e)

    def changeEvent(self, e):   # noqa: N802 - Qt
        super().changeEvent(e)
        try:
            if (e.type() == e.Type.ActivationChange and self.isVisible()
                    and not self.isActiveWindow()):
                self.ed.clear()
                self.hide()   # clicked elsewhere: that window has the keyboard now
                self._was = 0
        except Exception:  # noqa: BLE001 - never raise from a Qt override (AGENT-RULES)
            log.exception("quick say box: focus change")
