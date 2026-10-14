"""Editing sounds from the main window: the Edit sound windows (one per sound, a spare one
kept built), what happens when one closes (saved, or a copy saved), closing them when their
sound goes, Duplicate, Open file location, and rendering a sound again after its effects
change.

MainWindow makes one ``EditControl`` (``MainWindow.editctl``); everything here runs on
the UI thread."""
from __future__ import annotations

import html
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from shiboken6 import isValid as qt_valid

from soundboard import errors, library, soundfx, videos
from soundboard.i18n import _
from soundboard.library import SoundMeta, cache_keep, duplicate, load_sound, prune_cache
from soundboard.ui import worker
from soundboard.ui.crashdialog import free_dialog, rehome_crash_reports
from soundboard.ui.dialogs import EditDialog

if TYPE_CHECKING:
    from soundboard.ui.mainwindow import MainWindow


class EditControl:
    """The Edit sound windows of one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        self.mw = mw
        self._editors: dict[str, EditDialog] = {}
        self._render_gen: dict[str, int] = {}   # sid -> newest effects render (_rerender)

    def edit(self, sid, tab: str = "sound"):
        """Edit sound beside the board, not over it: sounds, hotkeys and the other
        pads keep working. It's still a draft: nothing changes until Save, and Cancel
        (or Escape, or closing it) drops it. One window per sound: editing the same
        sound again raises the open one."""
        mw = self.mw
        d = self._editors.get(sid)
        if d is not None and qt_valid(d):
            if tab == "effects":
                d.tabs.setCurrentIndex(1)
            d.showNormal() if d.isMinimized() else d.show()
            d.raise_()
            d.activateWindow()
            return d
        m = mw.meta(sid)
        if m is None:
            return None
        # a closed one shows this sound instead: building one took ~200 ms every time
        d, mw.setctl._spare_editor = mw.setctl._spare_editor, None
        if d is not None and qt_valid(d):
            d.load(m, tab)
        else:
            d = self._new_editor(m, tab)
        self._editors[sid] = d
        d.show()
        return d

    def _edit_done(self, sid: str, d: EditDialog, ok: int):
        """An Edit sound window closed: Save puts its draft on the sound (or a copy).
        It's kept for the next sound edited (the first one closed; any more are freed)."""
        mw = self.mw
        if self._editors.get(sid) is d:
            del self._editors[sid]
        mw.drop_preview()                        # a preview still rendering
        mw.engine.stop(f"{sid}:preview")         # and the one playing, either kind
        mw.engine.stop(f"{sid}~fx:preview")
        # the sound as it is now: gone (removed while the window was open: nothing to
        # save it onto), or the same sound in a new object (Undo put it back)
        m = mw.meta(sid)
        try:
            if ok and m is not None and d.as_copy:
                self._save_copy(m, d)
            elif ok and m is not None:
                old_key = soundfx.key(m.fx)
                d.apply(m)
                mw._clear_dupe_hotkey(m)
                mw.engine.set_gain(sid, mw.gain_for(m))
                if soundfx.key(m.fx) != old_key:
                    self._rerender(m)
                mw._save_now()
                mw.pads[sid].update()
                mw.apply_filter(mw.search.text())
        finally:
            if mw.setctl._spare_editor is None and d not in self._editors.values():
                rehome_crash_reports(d)
                mw.setctl._spare_editor = d
            else:   # freed once its finished signal is over (deleting it inside crashed)
                QTimer.singleShot(0, lambda: free_dialog(d))
        mw.register_hotkeys()

    def _new_editor(self, m: SoundMeta, tab: str) -> EditDialog:
        mw = self.mw
        d = EditDialog(m, mw.hotkeys, mw.preview, mw, tab=tab,
                       others=lambda: list(mw._meta.values()))
        d.hotkeys_changed.connect(mw.register_hotkeys)
        d.source_forgotten.connect(mw._save_now)
        d.finished.connect(lambda ok, d=d: self._edit_done(d.meta.id, d, ok))
        return d

    def _close_editors(self, sids):
        """The sounds are going: their open Edit sound windows close, unsaved (the
        Undo bar brings the sound back as it was)."""
        for sid in sids:
            d = self._editors.get(sid)
            if d is not None and qt_valid(d):
                d.reject()

    def duplicate_sound(self, sid: str) -> SoundMeta | None:
        """The pad menu's Duplicate: a copy right after the original, with its own
        file, so each can get its own effects, hotkey or category."""
        mw = self.mw
        m = mw.meta(sid)
        if m is None:
            return None
        try:
            new = duplicate(m, _("{name} (copy)", name=m.name)[:40])
        except OSError as e:
            errors.warn(mw, _("Couldn't copy the sound"), e)
            return None
        videos.copy_link(m.id, new.id)
        mw.catctl._tag_new(new)   # stays in sight in the category showing
        mw.cfg.sounds.insert(mw.cfg.sounds.index(m) + 1, new)
        mw._index()
        mw._save_now()
        mw._rebuild_pads()
        self._rerender(new)
        mw.toast(_("✓ Added “{name}”", name=html.escape(new.name)), "ok")
        return new

    def show_sound_file(self, sid: str):
        """The pad menu's Open file location: Explorer with the file picked
        (elsewhere, the folder it's in)."""
        mw = self.mw
        m = mw.meta(sid)
        if m is None:
            return
        path = Path(m.file)
        if not path.is_file():
            mw.toast(_("The file for “{name}” isn't there any more", name=html.escape(m.name)),
                       "warn")
            return
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def _save_copy(self, m: SoundMeta, d: EditDialog):
        """'Save a copy': the edits go onto a copy placed after the original."""
        mw = self.mw
        name = d.name.text().strip() or m.name
        try:
            new = duplicate(m, name if name != m.name else f"{name} (edit)")
        except OSError as e:
            errors.warn(mw, _("Couldn't copy the sound"), e)
            return
        videos.copy_link(m.id, new.id)
        d.apply(new)
        if new.name == m.name:
            new.name = f"{m.name} (edit)"[:40]
        if new.hotkey == m.hotkey:
            new.hotkey = ""   # the original keeps its hotkey
        mw._clear_dupe_hotkey(new)
        mw.catctl._tag_new(new)   # stays in sight in the category showing
        mw.cfg.sounds.insert(mw.cfg.sounds.index(m) + 1, new)
        mw._index()
        mw._save_now()
        mw._rebuild_pads()
        self._rerender(new)

    def _rerender(self, m: SoundMeta):
        """Load a sound again after its effects changed. They're rendered in the
        background; the pad says 'applying effects…' until it's ready."""
        mw = self.mw
        mw.engine.stop(m.id)
        mw.audio.pop(m.id, None)
        mw.engine.forget(m.id)
        p = mw.pads.get(m.id)
        if p:
            p.state = "rendering"
            p.update()
        gen = self._render_gen[m.id] = self._render_gen.get(m.id, 0) + 1

        def run():
            try:
                data = load_sound(m, cancel=lambda: self._render_gen.get(m.id) != gen)
            except library.Cancelled:
                return worker.SKIP   # (it stopped partway for a newer one)
            if self._render_gen.get(m.id) != gen:
                return worker.SKIP   # edited again meanwhile: a newer render is on its way
            mw.engine.prepare(m.id, data)
            prune()
            return m.id, data, ""

        def prune():
            worker.run(lambda: prune_cache(cache_keep(mw._live_metas())), name="prune")

        def failed(e):
            prune()
            return m.id, None, errors.plain(e)
        worker.run(run, mw.bridge.loaded, "fx-render", error=failed, owner=mw)
