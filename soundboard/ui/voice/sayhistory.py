"""The Say bar's history: every line the computer voice was asked to say (typed, from
the long-text box, a hotkey, the control API, chat), newest first, in a pop-up card
under the bar, so the bar itself stays one line.

Each row has a tick (pick several, then Say picked says them in the order they were
said), its time, its words (click: back in the box to change), where it came from when
it wasn't typed, and ▶ (say it again), copy and + (save it as a sound). The list is kept
in the speech settings (`HISTORY_KEY`), so it's still there after a restart."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)
from shiboken6 import isValid as qt_valid

from soundboard.i18n import _
from soundboard.ui.kit import busy, icons, panel
from soundboard.ui.kit.panel import icon_button
from soundboard.ui.window.upnext import LIST_GAP, _Name

HISTORY_KEY = "say_history"   # in the speech settings: [{"t": epoch, "text", "src"}]
HISTORY_MAX = 200
POPUP_W = 520
POPUP_ROWS = 8      # rows shown before the list scrolls

# where a line came from (its chip; "typed" has none)
SOURCES = ("typed", "api", "clipboard", "quick", "chat")


def source_name(src: str) -> str:
    return {"api": _("Control API"), "clipboard": _("Copied text"),
            "quick": _("Quick box"), "chat": _("Chat")}.get(src, "")


def clean_history(raw) -> list[dict]:
    """Saved history with anything malformed dropped, oldest first, at most HISTORY_MAX."""
    out = []
    for e in raw if isinstance(raw, list) else []:
        if not isinstance(e, dict) or not isinstance(e.get("text"), str) or not e["text"]:
            continue
        t = e.get("t")
        out.append({"t": float(t) if isinstance(t, (int, float)) and not isinstance(t, bool)
                    else 0.0,
                    "text": e["text"],
                    "src": e["src"] if e.get("src") in SOURCES else "typed"})
    return out[-HISTORY_MAX:]


def add_line(history: list[dict], text: str, src: str = "typed") -> list[dict]:
    history.append({"t": time.time(), "text": text, "src": src})
    del history[:-HISTORY_MAX]
    return history


@dataclass
class Actions:
    """What a row's parts do, given the line's words."""
    say: Callable[[str], object]
    edit: Callable[[str], object]
    copy: Callable[[str], object]
    save: Callable[[str], object]
    clear: Callable[[], object]


class SayHistoryPopup(QWidget):
    """The history card. Escape or a click outside closes it; it stays open while
    lines are said from it, so a few can be said one after another."""

    def __init__(self, parent: QWidget, acts: Actions):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.acts = acts
        self._lines: list[dict] = []
        self._picked: set[int] = set()   # indexes into _lines
        self._anchor: QWidget | None = None
        outer = self._outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.count = QLabel()
        self.count.setObjectName("muted")
        self.b_picked = QPushButton(_("Say picked"))
        self.b_picked.setObjectName("small")
        self.b_picked.setToolTip(_("Says the ticked lines again, in the order they were said"))
        self.b_picked.clicked.connect(self._say_picked)
        self.b_clear = QPushButton(_("Clear"))
        self.b_clear.setObjectName("small")
        self.b_clear.setToolTip(_("Forget every line in the list"))
        self.b_clear.clicked.connect(self._clear)
        close = icon_button("fold_open", _("Close"), size=14)
        close.clicked.connect(self.close)
        card, v = panel.card(_("Said lines"), icon="history", beside=self.count,
                             end=(self.b_picked, self.b_clear, close))
        card.setProperty("popup", True)
        outer.addWidget(card)
        self.card = card
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Search what was said"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self._fill())
        v.addWidget(self.search)
        self.empty = panel.hint_label("")
        v.addWidget(self.empty)
        self.rows = QWidget()
        self.rows_v = QVBoxLayout(self.rows)
        self.rows_v.setContentsMargins(0, 0, LIST_GAP, 0)
        self.rows_v.setSpacing(4)
        self.list_area = QScrollArea()
        self.list_area.setWidgetResizable(True)
        self.list_area.setFrameShape(QFrame.Shape.NoFrame)
        self.list_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_area.setWidget(self.rows)
        v.addWidget(self.list_area)
        self.setFixedWidth(POPUP_W)

    # ---- filling
    def open_at(self, anchor: QWidget, lines: list[dict]):
        self._anchor = anchor
        self._picked.clear()
        self.search.clear()
        self.show_lines(lines)
        self.show()
        self._place()
        self.search.setFocus()

    def show_lines(self, lines: list[dict]):
        """The list (again), keeping what's ticked when the same lines are still there."""
        if len(lines) < len(self._lines):
            self._picked.clear()
        self._lines = list(lines)
        self._fill()

    def _fill(self):
        while self.rows_v.count():
            item = self.rows_v.takeAt(0)
            w = item.widget() if item else None
            if w:
                # hidden, never setParent(None): a shown row without a parent becomes a
                # window of its own, and any window opening closes this pop-up (it did
                # after Say picked, which refills the list once per line said)
                w.hide()
                w.deleteLater()
        want = self.search.text().strip().casefold()
        shown = [i for i in range(len(self._lines) - 1, -1, -1)   # newest first
                 if not want or want in self._lines[i]["text"].casefold()]
        self.count.setText(str(len(self._lines)))
        self.b_clear.setVisible(bool(self._lines))
        self.b_picked.setVisible(bool(self._lines))
        self.search.setVisible(bool(self._lines))
        self.empty.setText(_("Nothing said yet. Lines you say show up here.")
                           if not self._lines else
                           _("No line has those words.") if not shown else "")
        self.empty.setVisible(not shown)
        a = self._anchor
        win = a.window().width() if a is not None and qt_valid(a) else POPUP_W + 16
        self.setFixedWidth(max(280, min(POPUP_W, win - 16)))
        rows = [self._row(i) for i in shown]
        for r in rows:
            self.rows_v.addWidget(r)
        self.rows_v.addStretch(1)
        some = rows[:POPUP_ROWS]
        self.list_area.setVisible(bool(rows))
        self.list_area.setFixedHeight(sum(r.sizeHint().height() for r in some)
                                      + self.rows_v.spacing() * max(len(some) - 1, 0))
        self._sync_picked()
        self.card.updateGeometry()
        self._outer.activate()
        self.resize(self.width(), self.sizeHint().height())
        self._place()

    def _row(self, i: int) -> QFrame:
        e = self._lines[i]
        text = e["text"]
        row = QFrame()
        row.setObjectName("chip")
        h = QHBoxLayout(row)
        h.setContentsMargins(6, 2, 2, 2)
        h.setSpacing(6)
        tick = QCheckBox()
        tick.setToolTip(_("Pick it, to say several with Say picked"))
        tick.setAccessibleName(_("Pick it"))
        tick.setChecked(i in self._picked)
        tick.toggled.connect(lambda on, i=i: self._pick(i, on))
        when = QLabel(time.strftime("%H:%M", time.localtime(e["t"])) if e["t"] else "")
        when.setObjectName("muted")
        # every row's words start at the same place ("03:21" is narrower than "03:22")
        when.setMinimumWidth(when.fontMetrics().horizontalAdvance("00:00") + 2)
        name = _Name(text)
        name.setToolTip(name.toolTip() + "\n" + _("Click to put it back in the box"))
        name.clicked.connect(lambda _c=False, t=text: (self.acts.edit(t), self.close()))
        h.addWidget(tick)
        h.addWidget(when)
        h.addWidget(name, 1)
        src = source_name(e["src"])
        if src:
            chip = QLabel(src)
            chip.setObjectName("muted")
            h.addWidget(chip)
        for icon, tip, act in (("play", _("Say it again"), self.acts.say),
                               ("copy", _("Copy it"), self.acts.copy),
                               ("plus", _("Save as sound"), self.acts.save)):
            b = QPushButton()
            b.setObjectName("chipstop")
            b.setToolTip(tip)
            b.setAccessibleName(tip)
            icons.set_icon(b, icon, "accent" if icon == "play" else "muted", size=14)
            b.setFixedSize(24, 24)
            b.clicked.connect(lambda _c=False, t=text, act=act, b=b: self._act(act, t, b))
            h.addWidget(b)
        return row

    # ---- doing
    def _act(self, act, text: str, btn: QPushButton):
        act(text)
        if act is self.acts.copy:
            busy.flash(btn, "✓", 1000)

    def _pick(self, i: int, on: bool):
        (self._picked.add if on else self._picked.discard)(i)
        self._sync_picked()

    def _sync_picked(self):
        n = len(self._picked)
        self.b_picked.setText(_("Say picked ({n})", n=n) if n else _("Say picked"))

    def _say_picked(self):
        if not self._picked:
            busy.flash(self.b_picked, _("Tick some lines first"), 1600)
            return
        for i in sorted(self._picked):   # in the order they were said
            self.acts.say(self._lines[i]["text"])
        self._picked.clear()
        self._fill()

    def _clear(self):
        self.acts.clear()
        self.close()

    def _place(self):
        """Under the bar, right edges lined up with the button that opened it (left
        edges in a right-to-left language), kept on the window and its screen."""
        a = self._anchor
        if a is None or not qt_valid(a) or not a.isVisible():
            return
        rtl = a.layoutDirection() == Qt.LayoutDirection.RightToLeft
        corner = a.mapToGlobal(QPoint(0 if rtl else a.width(), a.height() + 6))
        x = corner.x() if rtl else corner.x() - self.width()
        y = corner.y()
        scr = a.screen().availableGeometry()
        if y + self.height() > scr.bottom():
            y = max(scr.top(), a.mapToGlobal(QPoint(0, 0)).y() - self.height() - 6)
        win = a.window().geometry()
        left, right = max(scr.left(), win.left()), min(scr.right(), win.right())
        self.move(max(left, min(x, right - self.width())), y)
