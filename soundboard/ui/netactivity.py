"""Settings > Connection > Network activity: the list soundboard.netlog keeps of every
connection the app makes, to check for yourself where it goes.

Simple: one row per server (what it was for, how often, how much). Detailed: one row
per connection (route, result, bytes each way) and, for the picked one, its request
lines, answer and encryption. It redraws once a second while it's on screen, and
only when something changed."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFontDatabase
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


def _item(text: str, tip: str = "", align=None) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
    if tip:
        it.setToolTip(tip)
    if align is not None:
        it.setTextAlignment(align)
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
        self.simple.setToolTip("One row per server: what it was for and how often")
        self.detailed = QRadioButton("Detailed")
        self.detailed.setToolTip("One row per connection: route, result, bytes, and the "
                                 "requests the app could read")
        group = QButtonGroup(self)
        for b in (self.simple, self.detailed):
            group.addButton(b)
            row.addWidget(b)
        self.simple.setChecked(True)
        row.addStretch(1)
        self.copy = QPushButton("Copy")
        self.copy.setToolTip("Copy the detailed list as text. It shows the sites you used: "
                             "read it before sharing it")
        self.clear = QPushButton("Clear")
        self.clear.setToolTip("Forget the list so far")
        row.addWidget(self.copy)
        row.addWidget(self.clear)
        v.addLayout(row)

        self.summary = QLabel()
        self.summary.setObjectName("hint")
        self.summary.setWordWrap(True)
        v.addWidget(self.summary)

        self.servers = _table(["Server", "Used for", "Connections", "Data", "Last"], 1)
        self.conns = _table(["Time", "Server", "For", "Route", "Result", "Sent",
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
        self._fill_servers(servers)
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
            cells = [_item(s.host), _item(", ".join(s.features), "\n".join(s.features)),
                     _item(count, align=right),
                     _item(f"↑ {netlog.size(s.sent)}  ↓ {netlog.size(s.received)}",
                           "Sent / received", right),
                     _item(_when(s.last))]
            for c, it in enumerate(cells):
                if s.blocked == s.connections:
                    it.setForeground(QColor(theme.status("warn")))
                t.setItem(r, c, it)

    def _fill_conns(self):
        t = self.conns
        picked = self._picked_n()
        t.blockSignals(True)
        t.setRowCount(len(self._entries))
        right = Qt.AlignRight | Qt.AlignVCenter
        tone = {netlog.BLOCKED: "warn", netlog.FAILED: "error"}
        for r, e in enumerate(self._entries):
            result = netlog.outcome(e)
            label = netlog.feature_label(e.feature)
            cells = [_item(_when(e.started)), _item(netlog.where(e)), _item(label, label),
                     _item(e.route or "—"), _item(result, e.reason),
                     _item(netlog.size(e.sent), align=right),
                     _item(netlog.size(e.received), align=right)]
            cells[0].setData(Qt.UserRole, e.n)
            for c, it in enumerate(cells):
                if e.state in tone:
                    it.setForeground(QColor(theme.status(tone[e.state])))
                t.setItem(r, c, it)
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
