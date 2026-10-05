"""Settings > Connection > Network activity: the list soundboard.netlog keeps of every
connection the app makes, to check for yourself where it goes.

Simple: one row per server (what it was for, why, how often, how much). Detailed: one
row per connection (why: what you did that made it, route, result, bytes each way)
and, for the picked one, its request lines, answer and encryption. It redraws once a
second while it's on screen, and only when something changed.

Totals opens a window adding it all up per site (or per server): with a kept history,
over the whole saved file, not just the last 1000 the list shows. Open log opens that
file."""
from __future__ import annotations

import html
import subprocess
import sys
import time

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFontDatabase
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCheckBox,
                               QDialog, QHBoxLayout, QHeaderView, QLabel,
                               QPlainTextEdit, QPushButton,
                               QRadioButton, QSizePolicy, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from soundboard import netlog, theme
from soundboard.ui import fit
from soundboard.ui.panel import Flow

REFRESH_MS = 1000
_TOR = ("Tor's own connections to the Tor network aren't listed one by one: with Tor, "
        "everything here leaves through it.")
NOTE = ("Every connection the app makes while it's open, and every one a switch "
        "turned away. Kept in memory only: nothing here is saved, logged or sent, and "
        "closing the app forgets it. " + _TOR)
NOTE_KEPT = ("Every connection the app makes while it's open, and every one a switch "
             "turned away. Kept on this PC between starts (Keep a history, below), "
             "never logged or sent. " + _TOR)


def _when(t: float) -> str:
    """The time, and the day too when it wasn't today (a kept history spans days)."""
    lt = time.localtime(t)
    if lt[:3] == time.localtime()[:3]:
        return time.strftime("%H:%M:%S", lt)
    return time.strftime("%d %b %H:%M", lt)


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
    tip = _tip(tip or text)
    if it.toolTip() != tip:
        it.setToolTip(tip)
    if align is not None and it.textAlignment() != align:
        it.setTextAlignment(align)
    colour = QColor(theme.status(tone)) if tone else None
    # the colour is checked too, not just the tone: a theme switch changes it
    if it.data(_TONE) != tone or (colour is not None and it.foreground().color() != colour):
        it.setData(_TONE, tone)
        it.setForeground(colour if colour is not None else QBrush())
    return it


class ActivityTable(QTableWidget):
    """Bounded columns: long server names cannot displace every later column."""

    def __init__(self, headers, stretch):
        super().__init__(0, len(headers))
        self._widths = ([150, 180, 125, 100, 130, 80] if stretch == 1 else
                        [80, 150, 180, 120, 85, 100, 80, 90])
        # how far each column may shrink when the table is narrower than all of them
        # (Settings' default width): cut text ends in "…" and is whole in the cell's
        # tooltip, while a column pushed out behind a scroll bar was just missing
        self._mins = ([70, 64, 64, 72, 110, 72] if stretch == 1 else
                      [64] * len(self._widths))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for i, width in enumerate(self.fitted_widths(self.viewport().width())):
            self.setColumnWidth(i, width)

    def fitted_widths(self, room: int) -> list[int]:
        """The columns' widths in `room` px: they share any spare room; short of it,
        each gives up the same share of what it has above its minimum, and only below
        all the minimums does the table scroll."""
        total = sum(self._widths)
        if room >= total:
            return [int(w * room / total) for w in self._widths]
        least = sum(self._mins)
        f = max(0.0, (room - least) / (total - least))
        return [int(m + (w - m) * f) for w, m in zip(self._widths, self._mins)]


def _table(headers: list[str], stretch: int) -> QTableWidget:
    t = ActivityTable(headers, stretch)
    t.setObjectName("activitytable")
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setWordWrap(False)
    t.setShowGrid(False)
    t.setAlternatingRowColors(True)
    t.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    t.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    t.setTextElideMode(Qt.ElideRight)
    t.setMinimumHeight(220)
    t.setMaximumHeight(320)
    t.verticalHeader().setDefaultSectionSize(34)
    h = t.horizontalHeader()
    h.setMinimumSectionSize(64)
    h.setSectionResizeMode(QHeaderView.Interactive)
    h.setStretchLastSection(True)
    h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    for i, width in enumerate(t._widths):
        t.setColumnWidth(i, width)
    return t


class _Stack(QStackedWidget):
    """Only as tall as the page on show: a plain QStackedWidget sizes to its tallest
    page, which left the Simple table with the Detailed info box's height of blank
    space under it."""

    def __init__(self):
        super().__init__()
        self.currentChanged.connect(lambda _i: self.updateGeometry())

    def sizeHint(self):
        w = self.currentWidget()
        if w is None:
            return super().sizeHint()
        return w.sizeHint().expandedTo(w.minimumSize()).boundedTo(w.maximumSize())

    def minimumSizeHint(self):
        w = self.currentWidget()
        if w is None:
            return super().minimumSizeHint()
        return w.minimumSizeHint().expandedTo(w.minimumSize()).boundedTo(w.maximumSize())


class NetActivity(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._shown = -1        # netlog.version() last drawn
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        self.note = note = QLabel(NOTE)
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

        self.summary = QLabel()
        self.summary.setObjectName("hint")
        self.summary.setWordWrap(True)
        v.addWidget(self.summary)
        self.copy = QPushButton("Copy")
        self.copy.setToolTip("Copy the detailed list as text. It shows the sites you used: "
                             "read it before sharing it")
        self.clear = QPushButton("Clear")
        self.clear.setToolTip("Forget the list so far (and the saved history, if "
                              "it's kept)")

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
        self.stack = _Stack()
        # no taller than the page on show: a tall Settings window gave the stack its
        # spare height, a blank band between the table and the buttons under it
        self.stack.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.stack.addWidget(self.servers)
        self.stack.addWidget(detail)
        v.addWidget(self.stack)

        # all four under the table, on the left like every other card's buttons, wrapping
        # in a small Settings window (Copy and Clear far right beside the summary looked
        # out of line with Totals and Open log)
        row = Flow(gap=8)
        self.totals = QPushButton("Totals…")
        self.totals.setToolTip("How much data went to each site, added up over the whole "
                               "history")
        self.open_log = QPushButton("Open log")
        for b in (self.copy, self.clear, self.totals, self.open_log):
            row.addWidget(b)
        v.addLayout(row)

        self.simple.toggled.connect(self._mode)
        self.conns.itemSelectionChanged.connect(self._pick)
        self.copy.clicked.connect(self._copy)
        self.clear.clicked.connect(self._clear)
        self.totals.clicked.connect(self._show_totals)
        self.open_log.clicked.connect(self._open_log)
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        self._entries: list[netlog.Entry] = []
        self._conn_ns: list[int] = []     # the Detailed rows' entries (Entry.n), top down
        self._conn_done: set[int] = set()   # ones drawn finished: not looked at again
        self._conn_theme: tuple = ()
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
        kept = netlog.keeping()
        note = NOTE_KEPT if kept else NOTE
        if self.note.text() != note:
            self.note.setText(note)
        if not self._entries:
            self.summary.setText("Nothing has gone online yet." if kept else
                                 "Nothing has gone online since the app started.")
        else:
            self.summary.setText(
                f"{len(self._entries)} connection(s) to {len(servers)} server(s)"
                + (f", {blocked} blocked by a switch" if blocked else "") + ".")
        self.copy.setEnabled(bool(self._entries))
        self.clear.setEnabled(bool(self._entries))
        self.totals.setEnabled(bool(self._entries))
        has_file = netlog.kept_file() is not None
        # without a saved file it shows this run's list in a window instead (nothing
        # written): a greyed-out Open log beside a full list looked broken
        self.open_log.setEnabled(has_file or bool(self._entries))
        tip = (f"Open {netlog.FILE_NAME}, the saved history (one connection per line)"
               if has_file else "Show this run's list as text. Nothing is saved: tick "
               "Keep a history between starts (below) to keep a log on this PC")
        if self.open_log.toolTip() != tip:
            self.open_log.setToolTip(tip)
        if self.simple.isChecked():
            self._fill_servers(servers)
        else:
            self._fill_conns(force)

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

    def _fill_conns(self, force: bool = False):
        """New connections go in as rows at the top; only rows still open (and ones
        not drawn finished yet) are looked at again. Redrawing by position shifted
        every row down one, so each new connection rewrote every cell."""
        t = self.conns
        picked = self._picked_n()
        t.blockSignals(True)
        keep = {e.n for e in self._entries}
        for r in reversed(range(len(self._conn_ns))):   # the oldest fell off, or Clear
            if self._conn_ns[r] not in keep:
                t.removeRow(r)
                del self._conn_ns[r]
        top = self._conn_ns[0] if self._conn_ns else 0
        new = [e.n for e in self._entries if e.n > top]   # newest first, like the list
        for _ in new:
            t.insertRow(0)
        self._conn_ns[:0] = new
        if t.rowCount() != len(self._entries) or self._conn_ns != [e.n for e in self._entries]:
            t.setRowCount(len(self._entries))   # out of step somehow: redraw it all
            self._conn_ns = [e.n for e in self._entries]
            force = True
        theme_key = (theme.status("warn"), theme.status("error"))
        if force or theme_key != self._conn_theme:   # a theme switch recolours them all
            self._conn_theme = theme_key
            self._conn_done.clear()
        right = Qt.AlignRight | Qt.AlignVCenter
        tone = {netlog.BLOCKED: "warn", netlog.FAILED: "error"}
        t.clearSelection()   # new rows push the others down: pick it again by number
        for r, e in enumerate(self._entries):
            if e.n in self._conn_done:
                if e.n == picked:
                    t.selectRow(r)
                continue
            if e.state not in (netlog.CONNECTING, netlog.CONNECTED):
                self._conn_done.add(e.n)   # finished: it won't change again
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

    def _show_totals(self):
        dlg = TotalsDialog(self)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.show()

    def _open_log(self):
        path = netlog.kept_file()
        if path is None:
            if self._entries:
                dlg = LogDialog(netlog.as_text(list(reversed(self._entries))), self)
                dlg.setAttribute(Qt.WA_DeleteOnClose)
                dlg.show()
            return
        # Notepad: a .jsonl file usually has nothing set to open it
        if sys.platform == "win32":
            try:
                subprocess.Popen(["notepad.exe", str(path)])
                return
            except OSError:
                pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _clear(self):
        netlog.clear()
        self.info.clear()
        self.refresh(force=True)


class _Num(QTableWidgetItem):
    """A cell that sorts by the number behind it, not its text ("2 KB" < "10 KB")."""

    def __lt__(self, other):
        return (self.data(Qt.UserRole) or 0) < (other.data(Qt.UserRole) or 0)


class LogDialog(QDialog):
    """This run's network activity as text, for Open log when no history is kept:
    shown, never written to a file."""

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        fit.watch(self)   # grows to fit its text (ui/fit.py)
        self.setWindowTitle("Network activity log (this run, not saved)")
        self.resize(820, 520)
        v = QVBoxLayout(self)
        self.text = QPlainTextEdit(text)
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        v.addWidget(self.text)
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        row.addWidget(close)
        v.addLayout(row)


class TotalsDialog(QDialog):
    """Network activity added up: per site (or per server), the connections and the data
    each way, over the whole kept history (or this run's list when none is kept)."""

    COLUMNS = ["Site", "Connections", "Sent", "Received", "Total", "First", "Last"]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        fit.watch(self)   # grows to fit its text (ui/fit.py)
        self.setWindowTitle("Network activity totals")
        self.resize(820, 520)
        v = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setObjectName("hint")
        self.summary.setWordWrap(True)
        v.addWidget(self.summary)
        self.by_site = QCheckBox("Group servers by site (googlevideo.com, not each "
                                 "r3---sn-abc.googlevideo.com)")
        self.by_site.setChecked(True)
        v.addWidget(self.by_site)
        t = self.table = QTableWidget(0, len(self.COLUMNS))
        t.setObjectName("activitytable")
        t.setHorizontalHeaderLabels(self.COLUMNS)
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setShowGrid(False)
        t.setAlternatingRowColors(True)
        t.setWordWrap(False)
        t.verticalHeader().setDefaultSectionSize(30)
        h = t.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Interactive)
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        h.setSortIndicator(4, Qt.DescendingOrder)   # the most data first
        for i, width in enumerate([0, 130, 90, 90, 90, 110, 110]):
            if width:
                t.setColumnWidth(i, width)
        v.addWidget(t, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.copy = QPushButton("Copy")
        self.copy.setToolTip("Copy the table (pastes into a spreadsheet). It shows the "
                             "sites you used: read it before sharing it")
        close = QPushButton("Close")
        row.addWidget(self.copy)
        row.addWidget(close)
        v.addLayout(row)
        self.by_site.toggled.connect(self.refresh)
        self.copy.clicked.connect(self._copy)
        close.clicked.connect(self.close)
        self._rows: list[netlog.Total] = []
        self._head = ""
        self.refresh()

    def refresh(self, _on=None):
        items = netlog.history()
        by_site = self.by_site.isChecked()
        self._rows = rows = netlog.totals(items, by_site)
        sent = sum(r.sent for r in rows)
        received = sum(r.received for r in rows)
        what = "site(s)" if by_site else "server(s)"
        if not items:
            self._head = "Nothing has gone online yet."
        else:
            since = time.strftime("%d %b %Y %H:%M", time.localtime(items[0].started))
            scope = ("in the saved history" if netlog.keeping() else
                     "since the app started (tick Keep a history to add up across "
                     "starts)")
            self._head = (f"{len(items)} connection(s) to {len(rows)} {what} {scope}, "
                          f"from {since}: ↑ {netlog.size(sent)} sent, "
                          f"↓ {netlog.size(received)} received, "
                          f"{netlog.size(sent + received)} in all.")
        self.summary.setText(self._head)
        t = self.table
        t.horizontalHeaderItem(0).setText("Site" if by_site else "Server")
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        right = Qt.AlignRight | Qt.AlignVCenter
        for r, row in enumerate(rows):
            count = str(row.connections)
            extra = [f"{k} {w}" for k, w in ((row.blocked, "blocked"),
                                             (row.failed, "failed")) if k]
            if extra:
                count += f" ({', '.join(extra)})"
            tone = "warn" if row.blocked == row.connections else None
            cells = [(row.name, None, "\n".join(row.hosts)),
                     (count, row.connections, ""),
                     (netlog.size(row.sent), row.sent, f"{row.sent:,} bytes sent"),
                     (netlog.size(row.received), row.received,
                      f"{row.received:,} bytes received"),
                     (netlog.size(row.data), row.data, f"{row.data:,} bytes in all"),
                     (_when(row.first), row.first, ""), (_when(row.last), row.last, "")]
            for c, (text, num, tip) in enumerate(cells):
                it = QTableWidgetItem(text) if num is None else _Num(text)
                if num is not None:
                    it.setData(Qt.UserRole, num)
                    if c <= 4:
                        it.setTextAlignment(right)
                it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                it.setToolTip(_tip(tip or text))
                if tone:
                    it.setForeground(QColor(theme.status(tone)))
                t.setItem(r, c, it)
        t.setSortingEnabled(True)
        self.copy.setEnabled(bool(rows))

    def _copy(self):
        QApplication.clipboard().setText(netlog.totals_text(self._rows, self._head))
        self.copy.setText("✓ Copied")
        QTimer.singleShot(1500, self.copy, lambda: self.copy.setText("Copy"))
