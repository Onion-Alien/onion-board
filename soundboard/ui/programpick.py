"""Pick programs for *Show this when a program is in front…* (a category tab's menu):
the programs with a window open now, with their icons, plus *Browse for a program…*.
The listing runs on a thread (catswitch.windowed_programs)."""
from __future__ import annotations

import threading

from PySide6.QtCore import QFileInfo, QSize, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QFileDialog, QFileIconProvider,
                               QHBoxLayout, QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout)

from soundboard import catswitch
from soundboard.ui import fit, icons
from soundboard.ui.panel import hint_label


class ProgramPicker(QDialog):
    """`picked` after OK: the exe names chosen (lower case). `taken`: {exe: category}
    already set, shown on their rows."""
    _listed = Signal(object)

    def __init__(self, category: str, taken: dict[str, str], parent=None, lister=None):
        super().__init__(parent)
        fit.watch(self)
        self.category, self.taken = category, taken
        self.picked: list[str] = []
        self._lister = lister or catswitch.windowed_programs
        self.setWindowTitle(f"Show “{category}” when a program is in front")
        lay = QVBoxLayout(self)
        lay.addWidget(hint_label(
            f"When one of these programs comes to the front, the board shows “{category}”"
            " by itself. When it closes, the board goes back to what it showed before."))
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setIconSize(QSize(20, 20))
        self.list.setMinimumSize(380, 260)
        self.list.itemSelectionChanged.connect(self._update)
        self.list.itemDoubleClicked.connect(lambda _i: self._ok())
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        browse = QPushButton("Browse for a program…")
        icons.set_icon(browse, "folder")
        browse.clicked.connect(self.browse)
        row.addWidget(browse)
        row.addStretch(1)
        self.btn_ok = QPushButton("Add")
        self.btn_ok.setObjectName("primary")
        icons.set_icon(self.btn_ok, "plus", "on_accent")
        self.btn_ok.clicked.connect(self._ok)
        row.addWidget(self.btn_ok)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        lay.addLayout(row)
        self._icons = QFileIconProvider()
        self._wait = QListWidgetItem("Looking for open programs…")
        self._wait.setFlags(Qt.NoItemFlags)
        self.list.addItem(self._wait)
        self._listed.connect(self.fill)
        threading.Thread(target=self._list_bg, daemon=True, name="programs").start()
        self._update()

    def _list_bg(self):
        programs = self._lister()
        try:
            self._listed.emit(programs)
        except RuntimeError:   # closed meanwhile
            pass

    def fill(self, programs):
        self.list.clear()
        for exe, path, title in programs:
            self._add(exe, path, title)
        if not self.list.count():
            li = QListWidgetItem("No open programs found. Use Browse for a program….")
            li.setFlags(Qt.NoItemFlags)
            self.list.addItem(li)
        self._update()

    def _add(self, exe: str, path: str, title: str = "") -> QListWidgetItem:
        text = exe if not title else f"{exe}    ·    {title[:60]}"
        cat = self.taken.get(exe)
        if cat == self.category:
            text += "    (already set)"
        elif cat:
            text += f"    (now shows “{cat}”)"
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
        path, _ = QFileDialog.getOpenFileName(self, "Pick a program", "",
                                              "Programs (*.exe);;All files (*)")
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
