"""Screen-reader names for controls that have none.

Qt reads a button's text and a widget's tooltip, but an icon-only button (■, ⚙, ✕…),
a slider or a box without a label has no *name*, so a screen reader says only
"button" / "slider". This gives each such control a name from its tooltip (or a
line edit's placeholder), as a short first phrase. Names set by hand always win: the
ones made here are marked, so only those are replaced when the tooltip changes.

It runs over a window when it's built and whenever the keyboard focus lands in a
window (that's how dialogs and rows added later get covered), at most twice a second
per window, instead of filtering every event the app sees. Focus inside a tab only
goes over that tab (the rest of the window is gone over once focus is there): the
whole main window is ~1300 widgets with a big board.

The sound pads name themselves (widgets.Pad: a QAbstractButton whose accessible
name is the sound's name and whose description is its state and hotkey)."""
from __future__ import annotations

import html
import re
import time

from PySide6.QtWidgets import (QAbstractButton, QAbstractSlider, QAbstractSpinBox, QApplication,
                               QComboBox, QLineEdit, QProgressBar, QStackedWidget, QTabWidget,
                               QWidget)

AUTO = "_a11y_auto"      # dynamic property: this name was made here
KINDS = (QAbstractButton, QAbstractSlider, QComboBox, QAbstractSpinBox, QLineEdit,
         QProgressBar)
MAX_NAME = 80
_TAG = re.compile(r"<[^>]+>")
_last: dict[int, float] = {}   # window or tab page id -> when it was last gone over


def plain(text: str) -> str:
    """A tooltip as plain text (they may hold rich text)."""
    return " ".join(html.unescape(_TAG.sub(" ", text or "")).split())


def short(text: str) -> str:
    """The first phrase: "Stop — stops every sound" -> "Stop"."""
    for sep in (" — ", " – ", ". ", "\n", ": "):
        head = text.split(sep, 1)[0]
        if 0 < len(head) < len(text):
            text = head
    text = text.strip().rstrip(".")
    return text if len(text) <= MAX_NAME else text[:MAX_NAME - 1].rstrip() + "…"


def has_words(text: str) -> bool:
    return any(ch.isalnum() for ch in text or "")


def name_for(w: QWidget) -> str:
    """The name `w` should get, or "" if it has one already (e.g. a button's text)."""
    if isinstance(w, QAbstractButton) and has_words(w.text()):
        return ""   # Qt reads the text
    tip = plain(w.toolTip())
    if not tip and isinstance(w, QLineEdit):
        tip = w.placeholderText()
    return short(tip) if tip else ""


def label(w: QWidget):
    made = bool(w.property(AUTO))
    if w.accessibleName() and not made:
        return   # named by hand
    n = name_for(w)
    if n and n != w.accessibleName():
        w.setAccessibleName(n)
        w.setProperty(AUTO, True)


def scope(w: QWidget) -> QWidget:
    """What a focus change on `w` goes over: the outermost tab page it's on (a page of
    a QTabWidget, in its window), or its whole window if it isn't on one."""
    win = w.window()
    page, cur = win, w
    while cur is not None and cur is not win:
        up = cur.parentWidget()
        if isinstance(up, QStackedWidget) and isinstance(up.parentWidget(), QTabWidget):
            page = cur
        cur = up
    return page


def label_tree(root: QWidget, force: bool = False):
    """Name every unnamed control in `root`'s window (throttled unless `force`); a
    focus change (not `force`) goes over only scope(root)."""
    if root is None:
        return
    top = root.window() if force else scope(root)
    now = time.monotonic()
    if not force and now - _last.get(id(top), -1.0) < 0.5:
        return
    _last[id(top)] = now
    for w in (top, *top.findChildren(QWidget)):
        if isinstance(w, KINDS):
            label(w)


def install(app: QApplication):
    """Keep naming controls as the focus moves (call once, after the app exists)."""
    app.focusChanged.connect(lambda _old, new: label_tree(new) if new is not None else None)
