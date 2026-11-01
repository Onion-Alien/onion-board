"""The "Recently deleted" window: what's in the bin (soundboard.core.trash, or another bin
shaped like it, such as the saved voices' in soundboard.mic.savedvoices), newest first,
with Bring back and Delete for good."""
from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout,
                               QLabel, QListWidgetItem, QMessageBox, QPushButton,
                               QVBoxLayout)

from soundboard.core import achievements, trash
from soundboard.ui.bun import bunacts
from soundboard.ui.kit import busy, fit, icons, toast
from soundboard.ui.kit.panel import EmptyList, hint_label
from soundboard.i18n import _, ngettext


def _texts(what: str, keep_days: int) -> tuple[str, str, str]:
    """(title, hint, empty list) for "sounds", "voices" or "programs": whole sentences,
    so each language can word them its own way."""
    if what == "voices":
        return (_("Recently deleted voices"),
                ngettext("Voices you delete are kept here for {n} day, so you can bring "
                         "them back.", "Voices you delete are kept here for {n} days, so "
                         "you can bring them back.", keep_days),
                _("Nothing here. Deleted voices show up here."))
    if what == "programs":
        return (_("Recently deleted programs"),
                ngettext("Programs you delete are kept here for {n} day, so you can bring "
                         "them back.", "Programs you delete are kept here for {n} days, "
                         "so you can bring them back.", keep_days),
                _("Nothing here. Deleted programs show up here."))
    return (_("Recently deleted sounds"),
            ngettext("Sounds you delete are kept here for {n} day, so you can bring them "
                     "back.", "Sounds you delete are kept here for {n} days, so you can "
                     "bring them back.", keep_days),
            _("Nothing here. Deleted sounds show up here."))


class Source(Protocol):
    """What DeletedDialog lists: the trash module, or a store of voices with its own bin."""
    @property
    def KEEP_DAYS(self) -> int: ...   # noqa: N802 - trash's name
    def items(self, kind: str | None = None) -> list[trash.Item]: ...
    def take(self, item_id: str) -> trash.Item | None: ...
    def forget(self, item_id: str) -> None: ...


class DeletedDialog(QDialog):
    """`restore(item)` puts a taken-out entry back and returns whether it could.
    `source` has trash's items(kind) / take(id) / forget(id) and KEEP_DAYS."""

    def __init__(self, kind: str, what: str, restore: Callable[[trash.Item], bool],
                 parent=None, source: Source = trash):
        super().__init__(parent)
        fit.watch(self)
        self.kind, self.what, self.restore, self.source = kind, what, restore, source
        title, hint, self.empty_text = _texts(what, source.KEEP_DAYS)
        self.setWindowTitle(title)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(12)
        head = QHBoxLayout()
        head.setSpacing(2)   # (his widget has room round him already)
        self.bun = bunacts.ActBunny(bunacts.BIN_ACT)   # Bun in the bin, beside the title
        head.addWidget(self.bun)
        heading = QLabel(title)
        heading.setObjectName("helptitle")   # the dialog Title role (DESIGN.md)
        head.addWidget(heading, 1)
        lay.addLayout(head)
        self.hint = hint_label(hint)
        lay.addWidget(self.hint)
        self.list = EmptyList(self.empty_text, "trash")
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setMinimumSize(360, 240)
        self.list.itemSelectionChanged.connect(self._update)
        self.list.itemDoubleClicked.connect(lambda _i: self.bring_back())
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.btn_back = QPushButton(_("Bring back"))
        self.btn_back.setObjectName("primary")
        icons.set_icon(self.btn_back, "plus", "on_accent")
        self.btn_back.clicked.connect(self.bring_back)
        row.addWidget(self.btn_back)
        self.btn_forget = QPushButton(_("Delete for good"))
        icons.set_icon(self.btn_forget, "trash", "danger_text")
        self.btn_forget.clicked.connect(self.delete_for_good)
        row.addWidget(self.btn_forget)
        row.addStretch(1)
        lay.addLayout(row)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        row.addWidget(box)
        self.fill()

    def fill(self):
        self.list.clear()
        for it in self.source.items(self.kind):
            li = QListWidgetItem(_("{name}    ·    deleted {ago}",
                                   name=it.name, ago=trash.ago(it.when)))
            li.setData(Qt.ItemDataRole.UserRole, it.id)
            self.list.addItem(li)
        if self.list.count():
            self.list.setCurrentRow(0)
        self._update()

    def _picked(self) -> list[str]:
        return [li.data(Qt.ItemDataRole.UserRole) for li in self.list.selectedItems()
                if li.data(Qt.ItemDataRole.UserRole)]

    def _update(self):
        on = bool(self._picked())
        self.btn_back.setEnabled(on)
        self.btn_forget.setEnabled(on)

    def bring_back(self):
        failed, back = [], False
        for iid in self._picked():
            it = self.source.take(iid)
            if it is None or not self.restore(it):
                failed.append(it.name if it else _("One of them"))
            else:
                achievements.bump("restored")
                back = True
        if back:
            self.bun.play(bunacts.BRING_BACK)
        self.fill()
        if failed:
            busy.toast(self, toast.titled(_("Couldn't bring it back"), _(
                "{names}\n\ncouldn't be brought back: its files are gone from the bin.",
                names="\n".join(failed))), "warn", 10000)

    def delete_for_good(self):
        ids = self._picked()
        if not ids:
            return
        n = len(ids)
        if QMessageBox.question(
                self, _("Delete for good"),
                ngettext("Delete {n} item for good? This can't be undone.",
                         "Delete {n} items for good? This can't be undone.", n)
            ) != QMessageBox.StandardButton.Yes:
            return
        for iid in ids:
            self.source.forget(iid)
        self.bun.play(bunacts.BYE)
        self.fill()
