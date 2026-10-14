"""Taking sounds off the board in the main window: asking first when it's many, removing one
or several, the Undo bar that puts them back as they were, the files going to the
Recently deleted bin once Undo is gone (trash.py), and restoring from the bin.

MainWindow makes one ``RemoveControl`` (``MainWindow.rmctl``); everything here runs on
the UI thread."""
from __future__ import annotations

import html
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from soundboard import backup, library, trash
from soundboard.i18n import _, ngettext
from soundboard.library import SoundMeta
from soundboard.ui import toast as toastmod
from soundboard.ui import worker
from soundboard.ui.controller import Controller
from soundboard.ui.crashdialog import free_dialog

if TYPE_CHECKING:
    from soundboard.ui.mainwindow import MainWindow

UNDO_S = 10          # how long "Removed … · Undo" stays up
UNDO_KEY = "undo-sounds"   # its card (toast key)


class RemoveControl(Controller):
    """Removing, Undo and the Recently deleted bin for one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self._removed: list[tuple[SoundMeta, int, np.ndarray | None]] = []   # undo-able
        self._bin_thread: threading.Thread | None = None   # the newest _finish_removals work

    def ask_remove(self, sids: list[str]) -> bool:
        """Remove from the menu / picked pads: ask first. They go to Recently deleted."""
        mw = self.mw
        gone = [m for m in (mw.meta(s) for s in sids) if m]
        if not gone:
            return False
        if len(gone) == 1:
            ask = _("Remove “{name}”?\n\nRemoved sounds go to Recently deleted, where you "
                    "can bring them back for {keep_days} days.",
                    name=gone[0].name, keep_days=trash.KEEP_DAYS)
        else:
            ask = ngettext("Remove this {n} sound?\n\nRemoved sounds go to Recently deleted, "
                           "where you can bring them back for {keep_days} days.",
                           "Remove these {n} sounds?\n\nRemoved sounds go to Recently "
                           "deleted, where you can bring them back for {keep_days} days.",
                           len(gone), keep_days=trash.KEEP_DAYS)
        box = QMessageBox(QMessageBox.Icon.Question, _("Remove sound") if len(gone) == 1
                          else _("Remove sounds"), ask,
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, mw)
        box.button(QMessageBox.StandardButton.Yes).setText(_("Remove"))
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        answer = box.exec()
        free_dialog(box)
        if answer != QMessageBox.StandardButton.Yes:
            return False
        self.remove_sounds([m.id for m in gone])
        return True

    def remove_sound(self, sid: str):
        """Take a sound off the board. Its files stay until the Undo bar goes away
        (or the app closes); then the audio file goes to the Recycle Bin."""
        self.remove_sounds([sid])

    def remove_sounds(self, sids: list[str]):
        """Take several sounds off the board at once; one Undo brings them all back."""
        mw = self.mw
        gone = [m for m in (mw.meta(s) for s in sids) if m]
        if not gone:
            return
        mw.editctl._close_editors([m.id for m in gone])
        self._finish_removals()   # only the latest removal can be undone
        for m in gone:
            mw.engine.stop(m.id)
            mw.engine.stop(f"{m.id}:preview")
            index = mw.cfg.sounds.index(m)
            mw.cfg.sounds.remove(m)
            self._removed.append((m, index, mw.audio.pop(m.id, None)))
            mw.engine.forget(m.id)
            if mw.current == m.id:
                mw.current = None
                mw._set_np_name(_("Pick a sound"))
                mw.np_name.setToolTip(_("Select a sound pad to use these playback controls."))
        # written down first: a crash before the Undo bar goes still bins them next start
        trash.hold([(m, i) for m, i, _d in self._removed])
        mw._save_now()
        mw._rebuild_pads()
        mw.catctl._fill_categories()
        mw.hkctl.register_hotkeys()
        # "Removed X · Undo" for a while; after that they're in Recently deleted
        if len(gone) == 1:
            name = mw.fontMetrics().elidedText(gone[0].name, Qt.TextElideMode.ElideRight, 260)
            text = _("Removed “{name}”", name=name)
        else:
            text = _("Removed {n} sounds", n=len(gone))
        t = mw.toast(html.escape(text), "", UNDO_S * 1000, key=UNDO_KEY,
                       action=(_("Undo"), self.undo_remove), on_close=self._finish_removals)
        if t is not None:
            t.card.action.setToolTip(_("Put the sound back, exactly as it was. Later: Backup "
                                       "→ Recently deleted sounds"))

    def undo_remove(self):
        """Put the last removed sound(s) back where they were, with everything they had."""
        mw = self.mw
        if not self._removed:
            return
        done, self._removed = self._removed, []
        self._put_back(done)
        trash.release([m.id for m, *_rest in done])   # after the save: back on the board
        # Ctrl+Z, not its button: its card goes too (after the sounds are back, so its
        # on_close finds their pack still in use)
        toastmod.close(mw, UNDO_KEY)

    def _put_back(self, entries: list[tuple[SoundMeta, int, np.ndarray | None]]):
        """Put removed sounds back on the board: (meta, the index it had, its audio or
        None to load it). The last one goes in first, so each lands where it was."""
        mw = self.mw
        entries = list(entries)
        while entries:
            m, index, data = entries.pop()
            if any(o.id == m.id for o in mw.cfg.sounds):
                continue   # already back
            if m.hotkey and mw.hkctl._hotkey_taken(m.hotkey):
                m.hotkey = ""   # given to something else in the meantime
            mw.cfg.sounds.insert(min(index, len(mw.cfg.sounds)), m)
            m.tags = library.merge_tags(m.tags, mw.cfg.categories, mw.cfg.subcategories)
            if data is not None:
                mw.audio[m.id] = data
                worker.run(lambda m=m, data=data: mw.engine.prepare(m.id, data),
                           name="prepare")
        mw._save_now()
        mw._rebuild_pads()
        mw.catctl._fill_categories()
        if any(m.id not in mw.audio for m in mw.cfg.sounds):
            mw._load_all()
        mw.hkctl.register_hotkeys()

    def _finish_removals(self):
        """The undo window is over: the removed sounds go to Recently deleted
        (soundboard.trash), where they can still be brought back for a while."""
        # let go of their audio first: Windows won't delete a mapped cache file
        # (soundboard.mapped) while an array still points into it
        mw = self.mw
        done, self._removed = [(m, i) for m, i, _d in self._removed], []
        toastmod.close(mw, UNDO_KEY)   # (its on_close comes back here: nothing left)
        # not undone: the pack is no longer kept
        packs = [p for p in mw.impctl._packs_removed
                 if not any(m.pack == p for m in mw.cfg.sounds)]
        mw.impctl._packs_removed.clear()
        if not done and not packs:
            return
        prev = self._bin_thread

        def work():   # file moves, the bin's list (retried while locked): off the UI thread
            if prev is not None:
                prev.join()   # an earlier removal's sounds go in first
            n = trash.put_sounds(done) if done else None
            trash.release([m.id for m, _i in done])   # in the bin: crash-safe now
            for pid in packs:
                backup.forget_pack(pid)
            return worker.SKIP if n is None else n
        # (nothing waits on it: the bin's count shows next time)
        self._bin_thread = worker.run(work, mw.bin_filled, "to-bin", error=worker.SKIP,
                                      owner=mw)

    def _wait_bin(self):
        """Let removed sounds finish going into the bin (before the bin is listed,
        and on quitting)."""
        if self._bin_thread is not None:
            self._bin_thread.join()
            self._bin_thread = None

    def _label_bin(self, n: int | None = None):
        """Keep the compatibility button's count; Library holds the visible action.
        `n`: the sounds in the bin, if known (None reads it)."""
        mw = self.mw
        if n is None:
            n = len(trash.items(trash.SOUND))
        mw.btn_bin.setText(_("Recently deleted ({n})", n=n))
        mw.btn_bin.hide()   # Recently deleted is in the Library menu

    def show_deleted(self):
        """Library → Recently deleted sounds"""
        mw = self.mw
        from soundboard.ui.deleted import DeletedDialog
        self._finish_removals()   # the ones on the Undo bar are listed too
        self._wait_bin()
        d = DeletedDialog(trash.SOUND, "sounds", self._restore_deleted, mw)
        d.exec()
        free_dialog(d)
        self._label_bin()

    def _restore_deleted(self, item: trash.Item) -> bool:
        m = trash.meta_of(item)
        if m is None or not Path(m.file).exists():
            return False
        self._put_back([(m, item.index, None)])
        return True
