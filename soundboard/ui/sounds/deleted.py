"""The "Recently deleted" window: what's in the bin (soundboard.core.trash, or another bin
shaped like it, such as the saved voices' in soundboard.mic.savedvoices), newest first,
with Bring back and Delete for good."""
from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout,
                               QLabel, QListWidgetItem, QMessageBox, QPushButton,
                               QVBoxLayout)

from soundboard.core import achievements, trash
from soundboard.ui.bun import bunacts
from soundboard.ui.kit import busy, fit, icons, toast, worker
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


FAILED_NAMES = 10   # sounds named on the "couldn't bring it back" card, at most


class Source(Protocol):
    """What DeletedDialog lists: the trash module, or a store of voices with its own bin."""
    @property
    def KEEP_DAYS(self) -> int: ...   # noqa: N802 - trash's name
    def items(self, kind: str | None = None) -> list[trash.Item]: ...
    def take(self, item_id: str) -> trash.Item | None: ...
    def forget(self, item_id: str) -> None: ...


class DeletedDialog(QDialog):
    """`restore(item)` puts a taken-out entry back and returns whether it could.
    `source` has trash's items(kind) / take(id) / forget(id) and KEEP_DAYS.
    `restore_many(items)` (sounds: a whole board can be in here) puts many back in one
    go and returns the ones it couldn't; `source` then has trash's take_many(ids) and
    forget_many(ids)."""
    _worked = Signal(object)   # the disk work for many entries is over: its result

    def __init__(self, kind: str, what: str, restore: Callable[[trash.Item], bool],
                 parent=None, source: Source = trash,
                 restore_many: Callable[[list[trash.Item]], list[trash.Item]] | None = None):
        super().__init__(parent)
        fit.watch(self)
        self.kind, self.what, self.restore, self.source = kind, what, restore, source
        self.restore_many = restore_many
        self._then: Callable[[object], None] | None = None   # set: disk work is running
        self._worked.connect(self._work_over)
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

    def _off_ui(self, btn, text: str, work: Callable[[], object],
                then: Callable[[object], None]):
        """Run a selection's disk work off the UI thread. The window stays until it's
        over (see reject): `then` still has to put the sounds on the board."""
        self._then = then
        self._release = busy.hold(btn, text)
        for b in (self.btn_back, self.btn_forget):
            busy.set_busy(b, True)
        worker.run(lambda: (work(),), self._worked, "deleted-dialog", error=(None,),
                   owner=self)

    def _work_over(self, result):
        then, self._then = self._then, None
        self._release()
        for b in (self.btn_back, self.btn_forget):
            busy.set_busy(b, False)
        if then is not None:
            then(result)

    def reject(self):
        if self._then is None:   # (Esc, Close, the window's X)
            super().reject()

    def bring_back(self):
        if self._then is not None:
            return
        ids = self._picked()
        if self.restore_many is None:
            failed, back = [], 0
            for iid in ids:
                it = self.source.take(iid)
                if it is None or not self.restore(it):
                    failed.append(it.name if it else _("One of them"))
                else:
                    back += 1
            self._brought_back(back, failed)
        elif ids:
            self._off_ui(self.btn_back, _("Working…"),
                         lambda: self.source.take_many(ids),   # pyright: ignore[reportAttributeAccessIssue]
                         lambda result: self._taken(result, len(ids)))

    def _taken(self, result, asked: int):
        taken, stuck = result or ([], [])
        lost = self.restore_many(taken) if taken and self.restore_many else []
        failed = [it.name for it in stuck + lost]
        if len(taken) + len(stuck) < asked:
            failed.append(_("One of them"))
        self._brought_back(len(taken) - len(lost), failed)

    def _brought_back(self, back: int, failed: list[str]):
        if back:
            achievements.bump("restored", back)
            self.bun.play(bunacts.BRING_BACK)
        self.fill()
        if failed:
            names = failed[:FAILED_NAMES] + ["…"] * (len(failed) > FAILED_NAMES)
            busy.toast(self, toast.titled(_("Couldn't bring it back"), _(
                "{names}\n\ncouldn't be brought back: its files are gone from the bin.",
                names="\n".join(names))), "warn", 10000)

    def delete_for_good(self):
        ids = self._picked()
        if not ids or self._then is not None:
            return
        n = len(ids)
        if QMessageBox.question(
                self, _("Delete for good"),
                ngettext("Delete {n} item for good? This can't be undone.",
                         "Delete {n} items for good? This can't be undone.", n)
            ) != QMessageBox.StandardButton.Yes:
            return
        if self.restore_many is not None:   # (a whole board: the Recycle Bin takes a while)
            self._off_ui(self.btn_forget, _("Deleting…"),
                         lambda: self.source.forget_many(ids),   # pyright: ignore[reportAttributeAccessIssue]
                         lambda _result: self._forgotten())
            return
        for iid in ids:
            self.source.forget(iid)
        self._forgotten()

    def _forgotten(self):
        self.bun.play(bunacts.BYE)
        self.fill()
