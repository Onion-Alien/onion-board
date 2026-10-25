"""Part of the saved clips list (ui/apps/clipshelf.py `ClipShelf`): what you do with a clip
(play it, send it through the mic, rename, add to Sounds, copy, delete, its menu) and the
clean-up that keeps the shelf in size, with its undo."""
from __future__ import annotations

import logging
import html
import threading
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QMenu, QTreeWidgetItem, QWidget

from soundboard.core import errors, usage
from soundboard.i18n import _, ngettext
from soundboard.sounds.clipshelf import Clip
from soundboard.sounds.library import level_gain
from soundboard.ui.apps import clipeditor
from soundboard.ui.apps.cliprows import ID
from soundboard.ui.kit import busy, icons

log = logging.getLogger("soundboard.ui.apps.clipshelf")

if TYPE_CHECKING:
    from typing import Any

    _Base = QWidget
else:
    _Base = object


class ClipShelfActions(_Base):
    if TYPE_CHECKING:   # what ClipShelf has that these use
        _closed: Any
        _items: Any
        _picked: Any
        _place_actions: Any
        _preview_sid: Any
        _send_sid: Any
        _tick: Any
        add_to_sounds: Any
        cfg: Any
        cleanup_finished: Any
        engine: Any
        list: Any
        reload: Any
        restore_finished: Any
        shelf: Any
        undo_bar: Any
        voice: Any

    # ------------------------------------------------------------------ actions
    def _audio(self, c: Clip) -> np.ndarray | None:
        try:
            return c.audio()
        except Exception as e:  # noqa: BLE001 - the file went missing or is damaged
            log.warning("can't read clip %s: %s", c.file, e)
            errors.warn(self, _("Couldn't open that clip"), e)
            return None

    def _count(self, what: str):
        """For the usage count: the Voice tab's recordings or the Apps tab's saved clips,
        and what was done to one (the action's name only)."""
        usage.used(f"{'voice-rec' if self.voice else 'saved-clip'}-{what}")

    def _gain(self, data) -> float:
        return level_gain(data) if getattr(self.cfg, "level_volumes", True) else 1.0

    def toggle_play(self, it: QTreeWidgetItem | None = None, send: bool = False):
        it = it or self.list.currentItem()
        cid = it.data(0, ID) if it is not None else None
        sid = self._send_sid if send else self._preview_sid
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
        self._count("mic" if send else "play")
        self._playing = (sid, cid)
        self._progress = 0.0
        self.shelf.touch(cid)
        self._tick.start()
        self._repaint(cid)

    def _tick_play(self):
        playing = self._playing
        if playing is None or self._closed:
            self._tick.stop()
            return
        state = self.engine.state(playing[0])
        if state is None:   # it finished
            self._playing = None
            self._tick.stop()
        else:
            self._progress = float(state[0])
        self._repaint(playing[1])

    def _repaint(self, cid: str | None):
        it = self._items.get(cid) if cid else None
        if it is not None:
            self.list.viewport().update(self.list.visualItemRect(it))
        self._place_actions()

    def stop(self):
        if self._playing is not None:
            cid = self._playing[1]
            self.engine.stop(self._playing[0])
            self._playing = None
            self._tick.stop()
            self._repaint(cid)

    def _renamed(self, it: QTreeWidgetItem, col: int):
        if col != 0:
            return
        cid = it.data(0, ID)
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
            self._count("add")
            self.undo_bar.finish()
            busy.toast(self, ngettext("Added {n} clip to your Sounds",
                                      "Added {n} clips to your Sounds", added), "ok")

    def copy_picked(self):
        picked = self._picked()
        if not picked:
            return
        data = self._audio(picked[0])
        if data is not None:
            self._count("copy")
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
        self._count("delete")

        def undo():
            self.shelf.restore_many(gone)
            self.reload(pick=gone[0][1].id)
        what = (_("Deleted “{name}”", name=gone[0][1].name) if len(gone) == 1
                else ngettext("Deleted {n} clip", "Deleted {n} clips", len(gone)))
        self.undo_bar.show_for(what, undo)
        self.reload()

    def _menu(self, pos, it: QTreeWidgetItem | None = None, at: QPoint | None = None):
        if it is None:
            it = self.list.itemAt(pos)
        if it is None or not it.data(0, ID):
            return
        if not it.isSelected():
            self.list.setCurrentItem(it)
        m = QMenu(self)
        cid = it.data(0, ID)
        playing_sid = (self._playing[0] if self._playing is not None and self._playing[1] == cid
                       else None)

        def act(text, slot, icon=None, keys=None):
            a = m.addAction(text)
            if icon:
                a.setIcon(icons.icon(icon))
            if keys:
                a.setShortcut(QKeySequence(keys))   # shown only: the list's own keys do it
            a.triggered.connect(slot)
            return a
        act(_("Stop") if playing_sid == self._preview_sid else _("Play for me"),
            lambda: self.toggle_play(it), "headphones", Qt.Key.Key_Space)
        act(_("Stop sending") if playing_sid == self._send_sid else _("Play through mic"),
            lambda: self.toggle_play(it, send=True), "live", Qt.Key.Key_Return)
        m.addSeparator()
        act(_("Add to Sounds"), self.add_picked, "sounds")
        act(_("Rename"), lambda: self.rename(it), "edit", Qt.Key.Key_F2)
        act(_("Copy"), self.copy_picked, "copy", QKeySequence.StandardKey.Copy)
        m.addSeparator()
        act(_("Delete"), self.delete_picked, "trash", Qt.Key.Key_Delete)
        m.exec(at if at is not None else self.list.viewport().mapToGlobal(pos))

    def _maintain(self):
        # the Voice tab's recordings never expire: nothing to tidy, no worker thread
        if self.voice or self._closed or (self._worker is not None
                                          and self._worker.is_alive()):
            return
        keep = self.voice or self.cfg.app_clips_keep_forever or self.undo_bar.active()
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
        if self._closed:
            return
        if self.shelf.pruned:
            self.shelf.pruned = False
            if not gone:
                self.reload()
        if not gone:
            return
        def undo():
            self._restore_background(gone)
        if self.voice or self.cfg.app_clips_keep_forever or self.undo_bar.active():
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
