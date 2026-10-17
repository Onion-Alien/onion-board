"""Saved clips: the list under the Apps tab's cards where the clip editor's Save
puts what you cut out (stored by soundboard.clipshelf). Double-click (or Enter)
plays one in your headphones, F2 or a slow second click renames it, and a
right-click adds it to your Sounds, sends it, copies it or deletes it (the Undo
bar brings it back)."""
from __future__ import annotations

import html
import logging
import threading
from datetime import datetime

import numpy as np
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMenu,
                               QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from soundboard import errors, theme
from soundboard.clipshelf import Clip, Shelf
from soundboard.i18n import _, ngettext
from soundboard.ui import busy, clipeditor, icons
from soundboard.ui.clipeditor import fmt
from soundboard.ui.panel import CONTROL_H, Flow, UndoBar, fold_button
from soundboard.ui.restyled import on_restyle
from soundboard.engine import SR
from soundboard.library import level_gain
from soundboard.wheelguard import no_wheel

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
    cleanup_finished = Signal(object)
    restore_finished = Signal(str, object)
    error = ""   # set by whoever adds it to Sounds, when it can't

    def __init__(self, engine, cfg, parent=None):
        super().__init__(parent)
        self.engine, self.cfg = engine, cfg
        self.shelf = Shelf()
        self._closed = False
        self._worker = None
        self._items: dict[str, QTreeWidgetItem] = {}
        self._groups: dict[tuple[str, ...], QTreeWidgetItem] = {}
        self._group_counts: dict[tuple[str, ...], int] = {}
        self._purge_workers: list[threading.Thread] = []
        self._pending: list[Clip] = []
        self._pick = ""
        self._visible_count = 0
        self._playing: tuple[str, str] | None = None   # (engine sid, clip id)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(12)
        self.body = QWidget(self)
        self.title = fold_button(_("Saved clips"), self.body)
        self.title.setMinimumHeight(CONTROL_H)
        self.title.setAccessibleName(_("Saved clips"))
        self.title.setChecked(cfg.app_clips_expanded)
        head.addWidget(self.title)
        # a parent from the start: shown with none (its row isn't in the shelf yet), it
        # flashed up as a little window of its own at start-up
        self.hint = QLabel(_("Double-click plays · F2 renames · right-click for more"), self)
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        self.hint.setVisible(cfg.app_clips_expanded)
        head.addWidget(self.hint, 1)
        head.addStretch(1)
        v.addLayout(head)
        v.addWidget(self.body)
        v = QVBoxLayout(self.body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
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
        filters = Flow(gap=8)
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Find clips"))
        self.search.setAccessibleName(_("Find clips"))
        icons.clear_button(self.search)
        self.search.setMinimumHeight(CONTROL_H)
        self.search.setMinimumWidth(180)
        self.search.setMaximumWidth(360)
        filters.addWidget(self.search)
        self.group_by = QComboBox()
        self.group_by.setAccessibleName(_("Group clips"))
        self.group_by.setMinimumHeight(CONTROL_H)
        for text, key in ((_("By app"), "app"), (_("By day"), "day"),
                          (_("Newest first"), "newest")):
            self.group_by.addItem(text, key)
        self.group_by.setCurrentIndex(max(0, self.group_by.findData(cfg.app_clip_group)))
        no_wheel(self.group_by)
        filters.addWidget(self.group_by)
        v.addLayout(filters)
        self.list = QTreeWidget()
        self.list.setAccessibleName(_("Saved clips"))
        on_restyle(self.list, self._fit)   # (measured in the theme's font: see restyled)
        self.list.setHeaderLabels([_("Name"), _("Length"), _("From"), _("Created")])
        self.list.setRootIsDecorated(False)
        self.list.setUniformRowHeights(True)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed
                                  | QAbstractItemView.EditTrigger.SelectedClicked)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.list.itemDoubleClicked.connect(
            lambda it, _col: self.toggle_play(it) if it.data(0, Qt.ItemDataRole.UserRole) else None)
        self.list.itemChanged.connect(self._renamed)
        self.list.itemSelectionChanged.connect(self._sync)
        h = self.list.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        h.setResizeContentsPrecision(100)
        v.addWidget(self.list)
        self.empty = QLabel(_("No matching clips"))
        self.empty.setObjectName("hint")
        v.addWidget(self.empty)
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
        self._fill_timer = QTimer(self)
        self._fill_timer.timeout.connect(self._fill_rows)
        self.search.textChanged.connect(lambda: self.reload())
        self.group_by.currentIndexChanged.connect(self._group_changed)
        self.cleanup_finished.connect(self._cleanup_done)
        self.restore_finished.connect(self._restored)
        self._cleanup_timer = QTimer(self)
        self._cleanup_timer.setInterval(60_000)
        self._cleanup_timer.timeout.connect(self._maintain)
        self._cleanup_timer.start()
        self.title.toggled.connect(self._fold)
        self.reload()
        QTimer.singleShot(0, self._maintain)

    # ------------------------------------------------------------------ list
    def reload(self, pick: str = ""):
        self._fill_timer.stop()
        current = self.list.currentItem()
        pick = pick or (current.data(0, Qt.ItemDataRole.UserRole) if current is not None else "")
        self.resize_handle._drag = None
        self.list.blockSignals(True)
        self.list.clear()
        self._items.clear()
        self._groups.clear()
        self._group_counts.clear()
        self._pick = pick
        self._pending = self.shelf.snapshot()
        self._pending.sort(key=lambda c: c.made, reverse=True)
        self._visible_count = 0
        self.list.setRootIsDecorated(self.group_by.currentData() != "newest")
        self._columns()
        self.list.blockSignals(False)
        self._fill_rows()
        if self._pending:
            self._fill_timer.start(0)

    @staticmethod
    def _created(c: Clip) -> str:
        try:
            return datetime.fromtimestamp(c.made).strftime("%Y-%m-%d")
        except (ValueError, OverflowError, OSError):
            return ""

    def _group_changed(self):
        self.cfg.app_clip_group = self.group_by.currentData()
        self.size_changed.emit()
        self.reload()

    def _fill_rows(self):
        self.list.blockSignals(True)
        batch, self._pending = self._pending[:100], self._pending[100:]
        query = self.search.text().strip().casefold()
        mode = self.group_by.currentData()
        for c in batch:
            created = self._created(c)
            if query and query not in f"{c.name} {c.src} {created}".casefold():
                continue
            self._visible_count += 1
            it = QTreeWidgetItem([c.name, fmt(c.seconds * SR), c.src, created])
            it.setData(0, Qt.ItemDataRole.UserRole, c.id)
            it.setSizeHint(0, QSize(0, CONTROL_H))
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable)
            it.setToolTip(0, _("{name}\nDouble-click plays it, F2 renames it, right-click "
                               "adds it to your Sounds.", name=c.name))
            it.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._items[c.id] = it
            labels = ((c.src or _("Other"), created) if mode == "app"
                      else (created, c.src or _("Other")) if mode == "day" else ())
            parent = None
            for depth, label in enumerate(labels):
                key = labels[:depth + 1]
                group = self._groups.get(key)
                if group is None:
                    group = QTreeWidgetItem([label])
                    group.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    group.setSizeHint(0, QSize(0, CONTROL_H))
                    if parent is None:
                        self.list.addTopLevelItem(group)
                    else:
                        parent.addChild(group)
                    group.setExpanded(bool(query) or len(self.shelf.clips) <= 100 or depth > 0)
                    self._groups[key] = group
                count = self._group_counts.get(key, 0) + 1
                self._group_counts[key] = count
                group.setText(0, f"{label} ({count})")
                parent = group
            if parent is None:
                self.list.addTopLevelItem(it)
            else:
                parent.addChild(it)
            if c.id == self._pick:
                ancestor = it.parent()
                while ancestor is not None:
                    ancestor.setExpanded(True)
                    ancestor = ancestor.parent()
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        if not self._pending:
            self._fill_timer.stop()
        self._fit()
        self.resize_handle.setVisible(self._visible_count > 0)
        self.empty.setVisible(not self._pending and self._visible_count == 0)
        self.setVisible(bool(self.shelf.clips))
        self._sync()
        self.layout_changed.emit()

    def _columns(self):
        grouped = self.group_by.currentData() != "newest"
        self.list.setColumnHidden(2, grouped or self.width() < 600)
        self.list.setColumnHidden(3, grouped and self.width() < 420)

    def _fold(self, expanded):
        self.cfg.app_clips_expanded = expanded
        self.hint.setVisible(expanded)
        self.resize_handle._drag = None
        layout = self.layout()
        assert layout is not None
        layout.activate()
        self.updateGeometry()
        self.size_changed.emit()
        self.layout_changed.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._columns()

    def _fit(self):
        """As tall as the rows it shows (up to ROWS_SHOWN), in the theme's font."""
        rows = min(max(self._visible_count + len(self._groups), 1), ROWS_SHOWN)
        row_h = self.list.sizeHintForRow(0) if self.shelf.clips else 22
        self._fit_height = (self.list.header().sizeHint().height() + rows * max(row_h, 36)
                            + 2 * self.list.frameWidth() + 2)
        self._apply_height()

    def _apply_height(self):
        height = self.cfg.app_clip_height if self._visible_count else 0
        self.list.setFixedHeight(min(max(int(height), 72), 600) if height else self._fit_height)

    def resize_clips(self, height):
        if not self._visible_count or not self.title.isChecked():
            return
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
        clips = {c.id: c for c in self.shelf.snapshot()}
        cur = self.list.currentItem()
        for it in self.list.selectedItems() or ([cur] if cur else []):
            c = clips.get(it.data(0, Qt.ItemDataRole.UserRole))
            if c is not None:
                out.append(c)
        return out

    def _item(self, cid: str) -> QTreeWidgetItem | None:
        return self._items.get(cid)

    def add(self, data: np.ndarray, name: str, src: str = "") -> Clip:
        c = self.shelf.add(data, name, src)
        self.search.clear()
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
        self.shelf.touch(cid)

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
            self.shelf.touch(c.id)
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
            self.shelf.touch(picked[0].id)
            busy.toast(self, _("Copied “{name}”: Ctrl+V pastes it in an editor or on the "
                               "Sounds tab", name=html.escape(picked[0].name)), "ok")

    def delete_picked(self):
        picked = self._picked()
        for c in picked:
            if self._playing is not None and self._playing[1] == c.id:
                self.stop()
        gone = self.shelf.remove_many({c.id for c in picked})
        if not gone:
            return

        def undo():
            self.shelf.restore_many(gone)
            self.reload(pick=gone[0][1].id)
        what = (_("Deleted “{name}”", name=gone[0][1].name) if len(gone) == 1
                else ngettext("Deleted {n} clip", "Deleted {n} clips", len(gone)))
        self.undo_bar.show_for(what, undo)
        self.reload()

    def _menu(self, pos):
        it = self.list.itemAt(pos)
        if it is None or not it.data(0, Qt.ItemDataRole.UserRole):
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

    def _maintain(self):
        if self._closed or (self._worker is not None and self._worker.is_alive()):
            return
        keep = self.cfg.app_clips_keep_forever or self.undo_bar.active()
        playing = self._playing
        active = (playing[1] if playing is not None
                  and self.engine.state(playing[0]) is not None else None)
        def work():
            try:
                gone = self.shelf.maintain(keep, active)
            except OSError:
                log.exception("saved clips maintenance failed")
                return
            busy.emit(self.cleanup_finished, gone)
        self._worker = threading.Thread(target=work, daemon=True, name="saved-clips-cleanup")
        self._worker.start()

    def _cleanup_done(self, gone):
        if self._closed or not gone:
            return
        def undo():
            self._restore_background(gone)
        if self.cfg.app_clips_keep_forever or self.undo_bar.active():
            undo()
            return
        self.reload()
        self.undo_bar.show_for(_("Removed inactive clips: {n}", n=len(gone)), undo,
                              done=lambda: self._discard(gone))

    def _restore_background(self, gone):
        def work():
            error = None
            try:
                self.shelf.restore_many(gone)
            except OSError as e:
                error = e
            busy.emit(self.restore_finished, gone[0][1].id, error)
        self._worker = threading.Thread(target=work, daemon=True, name="saved-clips-restore")
        self._worker.start()

    def _restored(self, pick, error):
        if self._closed:
            return
        self.reload(pick=pick)
        if error is not None:
            busy.toast(self, html.escape(_("Couldn't save it: {error}",
                                          error=errors.plain(error))), "error")

    def _discard(self, gone):
        worker = threading.Thread(target=lambda: self.shelf.discard_files(gone),
                                  daemon=True, name="saved-clips-delete")
        self._purge_workers = [t for t in self._purge_workers if t.is_alive()]
        self._purge_workers.append(worker)
        worker.start()

    def shutdown(self):
        self._closed = True
        self._fill_timer.stop()
        self._cleanup_timer.stop()
        self.undo_bar.finish()
        if self._worker is not None:
            self._worker.join(5)
        for worker in self._purge_workers:
            worker.join(5)
        # Persist the final activity timestamp off the UI thread as well.
        self._worker = threading.Thread(target=lambda: self.shelf.maintain(True),
                                        daemon=True, name="saved-clips-flush")
        self._worker.start()
        self._worker.join(5)
        self.stop()
        self.engine.forget(SEND)
