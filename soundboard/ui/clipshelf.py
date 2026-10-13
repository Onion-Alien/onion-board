"""Saved clips: the list under the Apps tab's cards where the clip editor's Save
puts what you cut out (stored by soundboard.clipshelf). Double-click (or Enter)
plays one in your headphones, F2 or a slow second click renames it, and a
right-click adds it to your Sounds, sends it, copies it or deletes it (the Undo
bar brings it back)."""
from __future__ import annotations

import html
import logging

import numpy as np
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QMenu,
                               QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from soundboard import errors, theme
from soundboard.clipshelf import Clip, Shelf
from soundboard.i18n import _, ngettext
from soundboard.ui import busy, clipeditor, icons
from soundboard.ui.clipeditor import fmt
from soundboard.ui.panel import CONTROL_H, Flow, UndoBar
from soundboard.engine import SR
from soundboard.library import level_gain

log = logging.getLogger(__name__)

ROWS_SHOWN = 5           # the list's height, in rows, before it scrolls
PREVIEW = "clipshelf:preview"   # ":preview": headphones only
SEND = "clipshelf-send"


class ClipResizeHandle(QWidget):
    """A mouse and keyboard grip for the saved clips, inside the scrolling page."""

    def __init__(self, shelf):
        super().__init__(shelf)
        self.shelf = shelf
        self.setFixedHeight(28)
        self.setCursor(Qt.CursorShape.SplitVCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        tip = _("Drag to resize saved clips. Double-click to fit the clips.")
        self.setToolTip(tip)
        self.setAccessibleName(tip)
        self._drag = None

    def paintEvent(self, event):
        p = QPainter(self)
        p.setPen(QPen(QColor(theme.T["accent"] if self.hasFocus() else theme.T["muted"]), 2))
        mid = self.width() // 2
        for y in (12, 16):
            p.drawLine(mid - 20, y, mid + 20, y)
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self._drag = (event.globalPosition().y(), self.shelf.list.height())
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag is not None:
            y, height = self._drag
            self.shelf.resize_clips(height + event.globalPosition().y() - y)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag = None

    def mouseDoubleClickEvent(self, event):
        self._drag = None
        self.shelf.resize_clips(0)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.shelf.resize_clips(self.shelf.list.height()
                                    + (36 if event.key() == Qt.Key.Key_Down else -36))
        elif event.key() == Qt.Key.Key_Home:
            self.shelf.resize_clips(0)
        else:
            super().keyPressEvent(event)


class ClipShelf(QWidget):
    """The saved clips list. `add_to_sounds(audio, name)` asks the window to make
    one a sound (AppsTab passes it on as clip_ready)."""
    add_to_sounds = Signal(object, str)
    layout_changed = Signal()
    size_changed = Signal()
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
        hint.setWordWrap(True)
        head.addWidget(hint, 1)
        v.addLayout(head)
        actions = Flow(gap=8)
        self.btn_add = QPushButton(_("Add to Sounds"))
        self.btn_add.setObjectName("primary")
        self.btn_add.setMinimumHeight(CONTROL_H)
        icons.set_icon(self.btn_add, "sounds", size=18)
        self.btn_add.clicked.connect(self.add_picked)
        actions.addWidget(self.btn_add)
        self.clip_buttons = []
        for text, icon, slot in ((_("Preview"), "play", self.toggle_play),
                                 (_("Rename"), "edit", self.rename),
                                 (_("Delete"), "trash", self.delete_picked)):
            b = QPushButton(text)
            b.setMinimumHeight(CONTROL_H)
            b.setAccessibleName(text)
            icons.set_icon(b, icon, size=18)
            b.clicked.connect(lambda _checked=False, fn=slot: fn())
            actions.addWidget(b)
            self.clip_buttons.append(b)
        v.addLayout(actions)
        self.list = QTreeWidget()
        self.list.setAccessibleName(_("Saved clips"))
        self.list.setHeaderLabels([_("Name"), _("Length"), _("From")])
        self.list.setRootIsDecorated(False)
        self.list.setUniformRowHeights(True)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed
                                  | QAbstractItemView.EditTrigger.SelectedClicked)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.list.itemDoubleClicked.connect(lambda it, _col: self.toggle_play(it))
        self.list.itemChanged.connect(self._renamed)
        self.list.itemSelectionChanged.connect(self._sync)
        h = self.list.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        v.addWidget(self.list)
        self.resize_handle = ClipResizeHandle(self)
        v.addWidget(self.resize_handle)
        self.undo_bar = UndoBar(_("Put the clip back in the list"))
        v.addWidget(self.undo_bar)
        for keys, slot in ((Qt.Key.Key_Delete, self.delete_picked),
                           (QKeySequence.StandardKey.Copy, self.copy_picked)):
            a = QAction(self.list)
            a.setShortcut(QKeySequence(keys))
            a.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
            a.triggered.connect(slot)
            self.list.addAction(a)
        self.reload()

    # ------------------------------------------------------------------ list
    def reload(self, pick: str = ""):
        self.list.blockSignals(True)
        self.list.clear()
        for c in self.shelf.clips:
            it = QTreeWidgetItem([c.name, fmt(c.seconds * SR), c.src])
            it.setData(0, Qt.ItemDataRole.UserRole, c.id)
            it.setSizeHint(0, QSize(0, CONTROL_H))
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable)
            it.setToolTip(0, _("{name}\nDouble-click plays it, F2 renames it, right-click "
                               "adds it to your Sounds.", name=c.name))
            it.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.list.addTopLevelItem(it)
            if c.id == pick:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        rows = min(max(len(self.shelf.clips), 1), ROWS_SHOWN)
        row_h = self.list.sizeHintForRow(0) if self.shelf.clips else 22
        self._fit_height = (self.list.header().sizeHint().height() + rows * max(row_h, 36)
                            + 2 * self.list.frameWidth() + 2)
        self._apply_height()
        self.setVisible(bool(self.shelf.clips) or self.undo_bar.active())
        self._sync()
        self.layout_changed.emit()

    def _apply_height(self):
        height = self.cfg.app_clip_height
        self.list.setFixedHeight(min(max(int(height), 72), 600) if height else self._fit_height)

    def resize_clips(self, height):
        self.cfg.app_clip_height = min(max(int(height), 72), 600) if height else 0
        self._apply_height()
        self.layout_changed.emit()
        self.size_changed.emit()

    def _sync(self):
        n = len(self.shelf.clips)
        self.title.setText(_("Saved clips ({n})", n=n))
        picked = bool(self._picked())
        self.btn_add.setEnabled(picked)
        for b in self.clip_buttons:
            b.setEnabled(picked)

    def _picked(self) -> list[Clip]:
        out = []
        cur = self.list.currentItem()
        for it in self.list.selectedItems() or ([cur] if cur else []):
            c = self.shelf.get(it.data(0, Qt.ItemDataRole.UserRole))
            if c is not None:
                out.append(c)
        return out

    def _item(self, cid: str) -> QTreeWidgetItem | None:
        for i in range(self.list.topLevelItemCount()):
            it = self.list.topLevelItem(i)
            if it is not None and it.data(0, Qt.ItemDataRole.UserRole) == cid:
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
        cid = it.data(0, Qt.ItemDataRole.UserRole) if it is not None else None
        sid = SEND if send else PREVIEW
        again = self._playing == (sid, cid) and self.engine.state(sid) is not None
        self.stop()
        c = self.shelf.get(cid) if cid else None
        if again or c is None or not cid:
            return
        data = self._audio(c)
        if data is None or not len(data):
            return
        if self.engine.play(sid, data, self._gain(data), mode="restart",
                            preview=not send) is None:
            busy.toast(self, html.escape(
                _("Nowhere to send it: pick where your sounds go on the Setup tab.") if send
                else _("No headphones to play it in: pick them on the Setup tab.")), "error")
            return
        self._playing = (sid, cid)

    def stop(self):
        if self._playing is not None:
            self.engine.stop(self._playing[0])
            self._playing = None

    def _renamed(self, it: QTreeWidgetItem, col: int):
        if col != 0:
            return
        cid = it.data(0, Qt.ItemDataRole.UserRole)
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
            self.undo_bar.finish()
            busy.toast(self, ngettext("Added {n} clip to your Sounds",
                                      "Added {n} clips to your Sounds", added), "ok")

    def copy_picked(self):
        picked = self._picked()
        if not picked:
            return
        data = self._audio(picked[0])
        if data is not None:
            clipeditor.set_clipboard(data)
            busy.toast(self, _("Copied “{name}”: Ctrl+V pastes it in an editor or on the "
                               "Sounds tab", name=html.escape(picked[0].name)), "ok")

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
        cid = it.data(0, Qt.ItemDataRole.UserRole)
        playing_sid = (self._playing[0] if self._playing is not None and self._playing[1] == cid
                       else None)

        def act(text, slot, icon=None):
            a = m.addAction(text)
            if icon:
                a.setIcon(icons.icon(icon))
            a.triggered.connect(slot)
            return a
        act(_("Stop") if playing_sid == PREVIEW else _("Play (headphones)"),
            lambda: self.toggle_play(it), "play")
        act(_("Stop sending") if playing_sid == SEND
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
