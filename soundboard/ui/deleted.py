"""The "Recently deleted" window: what's in the bin (soundboard.trash, or another bin
shaped like it, such as the saved voices' in soundboard.savedvoices), newest first,
with Bring back and Delete for good."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                               QVBoxLayout)

from soundboard import trash
from soundboard.ui import fit, icons
from soundboard.ui.panel import hint_label


class DeletedDialog(QDialog):
    """`restore(item)` puts a taken-out entry back and returns whether it could.
    `source` has trash's items(kind) / take(id) / forget(id) and KEEP_DAYS."""

    def __init__(self, kind: str, what: str, restore: Callable[[trash.Item], bool],
                 parent=None, source=trash):
        super().__init__(parent)
        fit.watch(self)
        self.kind, self.what, self.restore, self.source = kind, what, restore, source
        self.setWindowTitle(f"Recently deleted {what}")
        lay = QVBoxLayout(self)
        self.hint = hint_label(f"{what.capitalize()} you delete are kept here for "
                               f"{source.KEEP_DAYS} days, so you can bring them back.")
        lay.addWidget(self.hint)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setMinimumSize(360, 240)
        self.list.itemSelectionChanged.connect(self._update)
        self.list.itemDoubleClicked.connect(lambda _i: self.bring_back())
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.btn_back = QPushButton("Bring back")
        self.btn_back.setObjectName("primary")
        icons.set_icon(self.btn_back, "plus", "on_accent")
        self.btn_back.clicked.connect(self.bring_back)
        row.addWidget(self.btn_back)
        self.btn_forget = QPushButton("Delete for good")
        icons.set_icon(self.btn_forget, "trash", "danger_text")
        self.btn_forget.clicked.connect(self.delete_for_good)
        row.addWidget(self.btn_forget)
        row.addStretch(1)
        lay.addLayout(row)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.reject)
        row.addWidget(box)
        self.fill()

    def fill(self):
        self.list.clear()
        for it in self.source.items(self.kind):
            li = QListWidgetItem(f"{it.name}    ·    deleted {trash.ago(it.when)}")
            li.setData(Qt.UserRole, it.id)
            self.list.addItem(li)
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            li = QListWidgetItem(f"Nothing here. Deleted {self.what} show up here.")
            li.setFlags(Qt.NoItemFlags)
            self.list.addItem(li)
        self._update()

    def _picked(self) -> list[str]:
        return [li.data(Qt.UserRole) for li in self.list.selectedItems()
                if li.data(Qt.UserRole)]

    def _update(self):
        on = bool(self._picked())
        self.btn_back.setEnabled(on)
        self.btn_forget.setEnabled(on)

    def bring_back(self):
        failed = []
        for iid in self._picked():
            it = self.source.take(iid)
            if it is None or not self.restore(it):
                failed.append(it.name if it else "One of them")
        self.fill()
        if failed:
            QMessageBox.warning(self, "Couldn't bring it back",
                                "\n".join(failed) + "\n\ncouldn't be brought back: its "
                                "files are gone from the bin.")

    def delete_for_good(self):
        ids = self._picked()
        if not ids:
            return
        n = len(ids)
        if QMessageBox.question(
                self, "Delete for good",
                f"Delete {'this' if n == 1 else f'these {n}'} for good? "
                "This can't be undone.") != QMessageBox.Yes:
            return
        for iid in ids:
            self.source.forget(iid)
        self.fill()
