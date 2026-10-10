"""Pick programs for *Show this when a program is in front…* (a category tab's menu):
the programs with a window open now, with their icons, plus *Browse for a program…*.
The listing runs on a thread (catswitch.windowed_programs)."""
from __future__ import annotations

import threading

from PySide6.QtCore import QFileInfo, QObject, QSize, Qt, Signal, Slot
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDialog, QFileDialog,
                               QFileIconProvider, QHBoxLayout, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout)

from soundboard import catswitch
from soundboard.ui import fit, icons
from soundboard.ui.panel import hint_label
from soundboard.i18n import _


class _Lists(QObject):
    """Brings a listing from its thread to the picker that asked (by its id). Not a
    signal of the picker itself: closed and freed while the thread emitted on it, that
    was a native access violation. This one lives as long as the app, and a freed
    picker's connection to it is simply gone."""
    listed = Signal(object, object)   # (picker id, programs): an id is past a C int


_lists: _Lists | None = None


def _carrier() -> _Lists:
    global _lists
    if _lists is None:   # made on the UI thread, by the first picker
        _lists = _Lists(QApplication.instance())
    return _lists


class ProgramPicker(QDialog):
    """`picked` after OK: the exe names chosen (lower case). `taken`: {exe: category}
    already set, shown on their rows."""

    def __init__(self, category: str, taken: dict[str, str], parent=None, lister=None):
        super().__init__(parent)
        fit.watch(self)
        self.category, self.taken = category, taken
        self.picked: list[str] = []
        self._lister = lister or catswitch.windowed_programs
        self.setWindowTitle(_("Show “{category}” when a program is in front", category=category))
        lay = QVBoxLayout(self)
        lay.addWidget(hint_label(
            _("When one of these programs comes to the front, the board shows “{category}” by "
              "itself. When it closes, the board goes back to what it showed before.",
              category=category)))
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setIconSize(QSize(20, 20))
        self.list.setMinimumSize(380, 260)
        self.list.itemSelectionChanged.connect(self._update)
        self.list.itemDoubleClicked.connect(lambda _i: self._ok())
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        browse = QPushButton(_("Browse for a program…"))
        icons.set_icon(browse, "folder")
        browse.clicked.connect(self.browse)
        row.addWidget(browse)
        row.addStretch(1)
        self.btn_ok = QPushButton(_("Add"))
        self.btn_ok.setObjectName("primary")
        icons.set_icon(self.btn_ok, "plus", "on_accent")
        self.btn_ok.clicked.connect(self._ok)
        row.addWidget(self.btn_ok)
        cancel = QPushButton(_("Cancel"))
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        lay.addLayout(row)
        self._icons = QFileIconProvider()
        self._wait = QListWidgetItem(_("Looking for open programs…"))
        self._wait.setFlags(Qt.NoItemFlags)
        self.list.addItem(self._wait)
        carrier, me, lister = _carrier(), id(self), self._lister
        carrier.listed.connect(self._on_listed)
        # the thread never touches the picker: it may be closed and freed meanwhile
        threading.Thread(target=lambda: carrier.listed.emit(me, lister()), daemon=True,
                         name="programs").start()
        self._update()

    @Slot(object, object)
    def _on_listed(self, who: int, programs):
        if who == id(self):
            self.fill(programs)

    def fill(self, programs):
        self.list.clear()
        for exe, path, title in programs:
            self._add(exe, path, title)
        if not self.list.count():
            li = QListWidgetItem(_("No open programs found. Use Browse for a program…."))
            li.setFlags(Qt.NoItemFlags)
            self.list.addItem(li)
        self._update()

    def _add(self, exe: str, path: str, title: str = "") -> QListWidgetItem:
        text = exe if not title else f"{exe}    ·    {title[:60]}"
        cat = self.taken.get(exe)
        if cat == self.category:
            text = _("{program}    (already set)", program=text)
        elif cat:
            text = _("{program}    (now shows “{category}”)", program=text, category=cat)
        li = QListWidgetItem(text)
        li.setData(Qt.UserRole, exe)
        li.setToolTip(path or exe)
        if path:
            try:
                li.setIcon(self._icons.icon(QFileInfo(path)))
            except Exception:  # noqa: BLE001
                pass
        self.list.addItem(li)
        return li

    def browse(self):
        path, __ = QFileDialog.getOpenFileName(self, _("Pick a program"), "",
                                              _("Programs (*.exe);;All files (*)"))
        self.add_path(path)

    def add_path(self, path: str):
        exe = catswitch.exe_name(path)
        if not exe:
            return
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == exe:
                self.list.setCurrentRow(i)
                return
        if self.list.count() == 1 and not self.list.item(0).data(Qt.UserRole):
            self.list.clear()   # the "Looking…" / "none found" line
        self.list.setCurrentItem(self._add(exe, path))

    def _chosen(self) -> list[str]:
        return [li.data(Qt.UserRole) for li in self.list.selectedItems()
                if li.data(Qt.UserRole)]

    def _update(self):
        self.btn_ok.setEnabled(bool(self._chosen()))

    def _ok(self):
        self.picked = self._chosen()
        if self.picked:
            self.accept()
