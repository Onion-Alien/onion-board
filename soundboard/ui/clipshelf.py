"""Saved clips: the list under the Apps tab's cards where the clip editor's Save
puts what you cut out (stored by soundboard.clipshelf). Double-click (or Enter)
plays one in your headphones, F2 or a slow second click renames it, and a
right-click adds it to your Sounds, sends it, copies it or deletes it (the Undo
bar brings it back)."""
from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QMenu,
                               QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from soundboard import errors
from soundboard.clipshelf import Clip, Shelf
from soundboard.i18n import _, ngettext
from soundboard.ui import clipeditor, icons
from soundboard.ui.clipeditor import fmt
from soundboard.ui.panel import UndoBar
from soundboard.engine import SR
from soundboard.library import level_gain

log = logging.getLogger(__name__)

ROWS_SHOWN = 5           # the list's height, in rows, before it scrolls
PREVIEW = "clipshelf:preview"   # ":preview": headphones only
SEND = "clipshelf-send"


class ClipShelf(QWidget):
    """The saved clips list. `add_to_sounds(audio, name)` asks the window to make
    one a sound (AppsTab passes it on as clip_ready)."""
    add_to_sounds = Signal(object, str)
    error = ""   # set by whoever adds it to Sounds, when it can't

    def __init__(self, engine, cfg, parent=None):
        super().__init__(parent)
        self.engine, self.cfg = engine, cfg
        self.shelf = Shelf()
        self._playing: tuple[str, str] | None = None   # (engine sid, clip id)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(12)
        self.title = QLabel()
        self.title.setObjectName("section")
        head.addWidget(self.title)
        hint = QLabel(_("Double-click plays · F2 renames · right-click for more"))
        hint.setObjectName("hint")
        head.addWidget(hint, 1)
        self.btn_add = QPushButton(_("Add to Sounds"))
        self.btn_add.setObjectName("small")
        icons.set_icon(self.btn_add, "sounds", size=13)
        self.btn_add.setToolTip(_("Make the picked clips sounds on the Sounds tab"))
        self.btn_add.clicked.connect(self.add_picked)
        head.addWidget(self.btn_add)
        v.addLayout(head)
        self.list = QTreeWidget()
        self.list.setAccessibleName(_("Saved clips"))
        self.list.setHeaderLabels([_("Name"), _("Length"), _("From")])
        self.list.setRootIsDecorated(False)
        self.list.setUniformRowHeights(True)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setEditTriggers(QAbstractItemView.EditKeyPressed
                                  | QAbstractItemView.SelectedClicked)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.list.itemDoubleClicked.connect(lambda it, _col: self.toggle_play(it))
        self.list.itemChanged.connect(self._renamed)
        self.list.itemSelectionChanged.connect(self._sync)
        h = self.list.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        v.addWidget(self.list)
        self.undo_bar = UndoBar(_("Put the clip back in the list"))
        v.addWidget(self.undo_bar)
        for keys, slot in ((Qt.Key_Delete, self.delete_picked),
                           (QKeySequence.Copy, self.copy_picked)):
            a = QAction(self.list)
            a.setShortcut(QKeySequence(keys))
            a.setShortcutContext(Qt.WidgetShortcut)
            a.triggered.connect(slot)
            self.list.addAction(a)
        self.reload()

    # ------------------------------------------------------------------ list
    def reload(self, pick: str = ""):
        self.list.blockSignals(True)
        self.list.clear()
        for c in self.shelf.clips:
            it = QTreeWidgetItem([c.name, fmt(c.seconds * SR), c.src])
            it.setData(0, Qt.UserRole, c.id)
            it.setFlags(it.flags() | Qt.ItemIsEditable)
            it.setToolTip(0, _("{name}\nDouble-click plays it, F2 renames it, right-click "
                               "adds it to your Sounds.", name=c.name))
            it.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            self.list.addTopLevelItem(it)
            if c.id == pick:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        rows = min(max(len(self.shelf.clips), 1), ROWS_SHOWN)
        row_h = self.list.sizeHintForRow(0) if self.shelf.clips else 22
        self.list.setFixedHeight(self.list.header().sizeHint().height() + rows * max(row_h, 18)
                                 + 2 * self.list.frameWidth() + 2)
        self.setVisible(bool(self.shelf.clips) or self.undo_bar.isVisible())
        self._sync()

    def _sync(self):
        n = len(self.shelf.clips)
        self.title.setText(_("Saved clips ({n})", n=n))
        self.btn_add.setEnabled(bool(self._picked()))

    def _picked(self) -> list[Clip]:
        out = []
        for it in self.list.selectedItems() or ([self.list.currentItem()]
                                                if self.list.currentItem() else []):
            c = self.shelf.get(it.data(0, Qt.UserRole))
            if c is not None:
                out.append(c)
        return out

    def _item(self, cid: str) -> QTreeWidgetItem | None:
        for i in range(self.list.topLevelItemCount()):
            it = self.list.topLevelItem(i)
            if it.data(0, Qt.UserRole) == cid:
                return it
        return None

    def add(self, data: np.ndarray, name: str, src: str = "") -> Clip:
        c = self.shelf.add(data, name, src)
        self.reload(pick=c.id)
        self.show()
        return c

    # ------------------------------------------------------------------ actions
    def _audio(self, c: Clip) -> np.ndarray | None:
        try:
            return c.audio()
        except Exception as e:  # noqa: BLE001 - the file went missing or is damaged
            log.warning("can't read clip %s: %s", c.file, e)
            errors.warn(self, _("Couldn't open that clip"), e)
            return None

    def _gain(self, data) -> float:
        return level_gain(data) if getattr(self.cfg, "level_volumes", True) else 1.0

    def toggle_play(self, it: QTreeWidgetItem | None = None, send: bool = False):
        it = it or self.list.currentItem()
        cid = it.data(0, Qt.UserRole) if it is not None else None
        sid = SEND if send else PREVIEW
        again = self._playing == (sid, cid) and self.engine.state(sid) is not None
        self.stop()
        c = self.shelf.get(cid) if cid else None
        if again or c is None:
            return
        data = self._audio(c)
        if data is None or not len(data):
            return
        if self.engine.play(sid, data, self._gain(data), mode="restart",
                            preview=not send) is None:
            n = len(self.shelf.clips)
            self.title.setText(
                _("Saved clips ({n}) · nowhere to send it: pick where your sounds go on the "
                  "Setup tab", n=n) if send else
                _("Saved clips ({n}) · no headphones to play it in: pick them on the Setup "
                  "tab", n=n))
            return
        self._playing = (sid, cid)

    def stop(self):
        if self._playing is not None:
            self.engine.stop(self._playing[0])
            self._playing = None

    def _renamed(self, it: QTreeWidgetItem, col: int):
        if col != 0:
            return
        cid = it.data(0, Qt.UserRole)
        c = self.shelf.get(cid)
        if c is None:
            return
        if not self.shelf.rename(cid, it.text(0)):
            self.list.blockSignals(True)
            it.setText(0, c.name)   # empty: back to what it was
            self.list.blockSignals(False)

    def rename(self, it: QTreeWidgetItem | None = None):
        it = it or self.list.currentItem()
        if it is not None:
            self.list.editItem(it, 0)

    def add_picked(self):
        added = 0
        for c in self._picked():
            data = self._audio(c)
            if data is None:
                continue
            self.error = ""
            self.add_to_sounds.emit(data, c.name)
            if self.error:
                errors.warn(self, _("Couldn't add it to your Sounds"), self.error)
                return
            added += 1
        if added:
            self.undo_bar.hide()
            clips = len(self.shelf.clips)
            self.title.setText(
                ngettext("Saved clips ({clips}) · ✓ added {n} to your Sounds",
                         "Saved clips ({clips}) · ✓ added {n} to your Sounds", added,
                         clips=clips) if added > 1 else
                _("Saved clips ({clips}) · ✓ added to your Sounds", clips=clips))

    def copy_picked(self):
        picked = self._picked()
        if not picked:
            return
        data = self._audio(picked[0])
        if data is not None:
            clipeditor.set_clipboard(data)
            self.title.setText(_("Saved clips ({n}) · copied “{name}” — Ctrl+V pastes it in "
                                 "an editor or on the Sounds tab",
                                 n=len(self.shelf.clips), name=picked[0].name))

    def delete_picked(self):
        gone = []
        for c in self._picked():
            if self._playing is not None and self._playing[1] == c.id:
                self.stop()
            r = self.shelf.remove(c.id)
            if r is not None:
                gone.append(r)
        if not gone:
            return

        def undo():
            for at, c in reversed(gone):
                self.shelf.restore(at, c)
            self.reload(pick=gone[0][1].id)
        what = (_("Deleted “{name}”", name=gone[0][1].name) if len(gone) == 1
                else ngettext("Deleted {n} clip", "Deleted {n} clips", len(gone)))
        self.undo_bar.show_for(what, undo)
        self.reload()
        self.show()

    def _menu(self, pos):
        it = self.list.itemAt(pos)
        if it is None:
            return
        if not it.isSelected():
            self.list.setCurrentItem(it)
        m = QMenu(self)
        cid = it.data(0, Qt.UserRole)
        playing = self._playing is not None and self._playing[1] == cid

        def act(text, slot, icon=None):
            a = m.addAction(text)
            if icon:
                a.setIcon(icons.icon(icon))
            a.triggered.connect(slot)
            return a
        act(_("Stop") if playing and self._playing[0] == PREVIEW else _("Play (headphones)"),
            lambda: self.toggle_play(it), "play")
        act(_("Stop sending") if playing and self._playing[0] == SEND
            else _("Send to whoever's listening"), lambda: self.toggle_play(it, send=True),
            "live")
        m.addSeparator()
        act(_("Add to Sounds"), self.add_picked, "sounds")
        act(_("Rename"), lambda: self.rename(it), "edit")
        act(_("Copy"), self.copy_picked, "copy")
        m.addSeparator()
        act(_("Delete"), self.delete_picked, "trash")

        m.exec(self.list.viewport().mapToGlobal(pos))

    def shutdown(self):
        self.stop()
        self.engine.forget(SEND)
