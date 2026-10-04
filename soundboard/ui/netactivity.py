"""Settings > Connection > Network activity: the list soundboard.netlog keeps of every
connection the app makes, to check for yourself where it goes.

Simple: one row per server (what it was for, why, how often, how much). Detailed: one
row per connection (why: what you did that made it, route, result, bytes each way)
and, for the picked one, its request lines, answer and encryption. It redraws once a
second while it's on screen, and only when something changed."""
from __future__ import annotations

import html
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFontDatabase
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QHBoxLayout,
                               QHeaderView, QLabel, QPlainTextEdit, QPushButton,
                               QRadioButton, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from soundboard import netlog, theme

REFRESH_MS = 1000
NOTE = ("Every connection the app makes while it's open, and every one a switch "
        "turned away. Kept in memory only: nothing here is saved, logged or sent, and "
        "closing the app forgets it. Tor's own connections to the Tor network aren't "
        "listed one by one: with Tor, everything here leaves through it.")


def _when(t: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(t))


_TONE = Qt.UserRole + 1   # the status colour a cell is drawn in (None: the default)


def _tip(text: str) -> str:
    """A tooltip shown as plain text: a reason can quote a server, and Qt renders "<b>"
    in a tooltip."""
    return f"<p style='white-space:pre-wrap'>{html.escape(text)}</p>" if text else ""


def _put(t: QTableWidget, r: int, c: int, text: str, tip: str = "", align=None,
         tone: str | None = None) -> QTableWidgetItem:
    """Cell (r, c) says `text`. The item already there is reused and only what changed
    is set: while a radio stream counts its bytes, building new items would mean a
    thousand new rows every second."""
    it = t.item(r, c)
    if it is None:
        it = QTableWidgetItem(text)
        it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        t.setItem(r, c, it)
    elif it.text() != text:
        it.setText(text)
    tip = _tip(tip)
    if it.toolTip() != tip:
        it.setToolTip(tip)
    if align is not None and it.textAlignment() != align:
        it.setTextAlignment(align)
    if it.data(_TONE) != tone:
        it.setData(_TONE, tone)
        it.setForeground(QColor(theme.status(tone)) if tone else QBrush())
    return it


def _table(headers: list[str], stretch: int) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setWordWrap(False)
    t.setMinimumHeight(220)
    h = t.horizontalHeader()
    for i in range(len(headers)):
        h.setSectionResizeMode(i, QHeaderView.Stretch if i == stretch
                               else QHeaderView.ResizeToContents)
    return t


class NetActivity(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._shown = -1        # netlog.version() last drawn
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        note = QLabel(NOTE)
        note.setObjectName("hint")
        note.setWordWrap(True)
        v.addWidget(note)

        row = QHBoxLayout()
        self.simple = QRadioButton("Simple")
        self.simple.setToolTip("One row per server: what it was for, why, and how often")
        self.detailed = QRadioButton("Detailed")
        self.detailed.setToolTip("One row per connection: what you did that made it, "
                                 "route, result, bytes, and the requests the app could "
                                 "read")
        group = QButtonGroup(self)
        for b in (self.simple, self.detailed):
            group.addButton(b)
            row.addWidget(b)
        self.simple.setChecked(True)
        row.addStretch(1)
        v.addLayout(row)

        # Copy and Clear beside the summary (it wraps), not after the view buttons: all
        # four in a row made the Connection page wider than a small Settings window
        row = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setObjectName("hint")
        self.summary.setWordWrap(True)
        row.addWidget(self.summary, 1)
        self.copy = QPushButton("Copy")
        self.copy.setToolTip("Copy the detailed list as text. It shows the sites you used: "
                             "read it before sharing it")
        self.clear = QPushButton("Clear")
        self.clear.setToolTip("Forget the list so far")
        row.addWidget(self.copy)
        row.addWidget(self.clear)
        v.addLayout(row)

        self.servers = _table(["Server", "Why", "Used for", "Connections", "Data",
                               "Last"], 1)
        self.conns = _table(["Time", "Server", "Why", "For", "Route", "Result", "Sent",
                             "Received"], 2)
        self.info = QPlainTextEdit()
        self.info.setReadOnly(True)
        self.info.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.info.setPlaceholderText("Pick a connection to see everything about it.")
        self.info.setMinimumHeight(120)
        self.info.setMaximumHeight(180)
        detail = QWidget()
        dv = QVBoxLayout(detail)
        dv.setContentsMargins(0, 0, 0, 0)
        dv.addWidget(self.conns)
        dv.addWidget(self.info)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.servers)
        self.stack.addWidget(detail)
        v.addWidget(self.stack)

        self.simple.toggled.connect(self._mode)
        self.conns.itemSelectionChanged.connect(self._pick)
        self.copy.clicked.connect(self._copy)
        self.clear.clicked.connect(self._clear)
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        self._entries: list[netlog.Entry] = []
        self.refresh()

    # only while it's on screen
    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()
        self._timer.start()

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    def _mode(self, _on=None):
        self.stack.setCurrentIndex(0 if self.simple.isChecked() else 1)
        self.refresh(force=True)   # only the table on show is kept up to date

    def refresh(self, force: bool = False):
        ver = netlog.version()
        if ver == self._shown and not force:
            return
        self._shown = ver
        self._entries = list(reversed(netlog.entries()))   # newest first
        servers = netlog.servers(self._entries)
        blocked = sum(e.state == netlog.BLOCKED for e in self._entries)
        if not self._entries:
            self.summary.setText("Nothing has gone online since the app started.")
        else:
            self.summary.setText(
                f"{len(self._entries)} connection(s) to {len(servers)} server(s)"
                + (f", {blocked} blocked by a switch" if blocked else "") + ".")
        self.copy.setEnabled(bool(self._entries))
        self.clear.setEnabled(bool(self._entries))
        if self.simple.isChecked():
            self._fill_servers(servers)
        else:
            self._fill_conns()

    def _fill_servers(self, servers: list[netlog.Server]):
        t = self.servers
        t.setRowCount(len(servers))
        right = Qt.AlignRight | Qt.AlignVCenter
        for r, s in enumerate(servers):
            count = str(s.connections)
            extra = [f"{k} {what}" for k, what in ((s.blocked, "blocked"),
                                                   (s.failed, "failed")) if k]
            if extra:
                count += f" ({', '.join(extra)})"
            tone = "warn" if s.blocked == s.connections else None
            why = s.causes[0] if s.causes else "—"
            if len(s.causes) > 1:
                why += f" (+{len(s.causes) - 1} more)"
            _put(t, r, 0, s.host, tone=tone)
            _put(t, r, 1, why, "\n".join(s.causes), tone=tone)
            _put(t, r, 2, ", ".join(s.features), "\n".join(s.features), tone=tone)
            _put(t, r, 3, count, align=right, tone=tone)
            _put(t, r, 4, f"↑ {netlog.size(s.sent)}  ↓ {netlog.size(s.received)}",
                 "Sent / received", right, tone)
            _put(t, r, 5, _when(s.last), tone=tone)

    def _fill_conns(self):
        t = self.conns
        picked = self._picked_n()
        t.blockSignals(True)
        t.setRowCount(len(self._entries))
        right = Qt.AlignRight | Qt.AlignVCenter
        tone = {netlog.BLOCKED: "warn", netlog.FAILED: "error"}
        t.clearSelection()   # new rows push the others down: pick it again by number
        for r, e in enumerate(self._entries):
            label = netlog.feature_label(e.feature)
            color = tone.get(e.state)
            _put(t, r, 0, _when(e.started), tone=color).setData(Qt.UserRole, e.n)
            _put(t, r, 1, netlog.where(e), tone=color)
            _put(t, r, 2, e.cause or "—", e.cause, tone=color)
            _put(t, r, 3, label, label, tone=color)
            _put(t, r, 4, e.route or "—", tone=color)
            _put(t, r, 5, netlog.outcome(e), e.reason, tone=color)
            _put(t, r, 6, netlog.size(e.sent), align=right, tone=color)
            _put(t, r, 7, netlog.size(e.received), align=right, tone=color)
            if e.n == picked:
                t.selectRow(r)
        t.blockSignals(False)
        self._pick()

    def _picked_n(self) -> int | None:
        rows = self.conns.selectionModel().selectedRows()
        if not rows:
            return None
        it = self.conns.item(rows[0].row(), 0)
        return it.data(Qt.UserRole) if it is not None else None

    def _pick(self):
        n = self._picked_n()
        e = next((e for e in self._entries if e.n == n), None)
        text = netlog.details(e) if e is not None else ""
        if self.info.toPlainText() != text:
            self.info.setPlainText(text)

    def _copy(self):
        QApplication.clipboard().setText(netlog.as_text(list(reversed(self._entries))))
        self.copy.setText("✓ Copied")
        QTimer.singleShot(1500, self.copy, lambda: self.copy.setText("Copy"))

    def _clear(self):
        netlog.clear()
        self.info.clear()
        self.refresh(force=True)
