"""Getting sounds in and out of the board, in the main window: Add sounds / a folder /
a link, files dropped on the window, the sounds folder's loose files, backups and
sound packs (import, export, tidy, reset, remove), other soundboards' sounds, and the
Free packs window.

MainWindow makes one ``ImportControl`` (``MainWindow.impctl``) and sends it the
bridge's ``imported`` / ``exported`` / ``worked`` signals. The file work runs on
workers (library.py, backup.py, otherboards.py); everything here runs on the UI thread."""
from __future__ import annotations

import copy
import html
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QFileSystemWatcher, Qt, QTimer, QUrl, QVariantAnimation
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QMessageBox

from soundboard import (
    backup,
    bunny,
    catswitch,
    errors,
    library,
    otherboards,
    soundfx,
    thumbs,
    usage,
    videos,
    winpath,
    ytdl,
)
from soundboard.i18n import _, ngettext
from soundboard.library import (
    AUDIO_EXTS,
    PAD_COLORS,
    SoundMeta,
    clean_tags,
    fingerprint,
    import_file,
    loose_sounds,
)
from soundboard.settings import HOTKEY_ACTIONS, pretty_key
from soundboard.ui import busy, importreport, taboff, worker
from soundboard.ui import toast as toastmod
from soundboard.ui.controller import Controller
from soundboard.ui.crashdialog import free_dialog
from soundboard.ui.widgets import expand_dropped

if TYPE_CHECKING:
    from soundboard.ui.mainwindow import MainWindow

log = logging.getLogger(__name__)

SHORT_SOUND_S = 0.3   # an added sound shorter than this gets a "very short" note
PACK_SAMPLE = "__pack_sample"   # Free packs' "hear it first" voice (headphones only)
LOOSE_WAIT_MS = 1500   # a file dragged into the sounds folder is looked at again (ms)
LOOSE_EMPTY_LOOKS = 20   # an empty file that long (~30 s) waits for the folder to change


class ImportControl(Controller):
    """Importing, exporting and sound packs for one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self._packs_removed: set[str] = set()   # sound packs to stop keeping after Undo
        self._imported_short = False      # a sound added in this batch is under SHORT_SOUND_S
        self._pending_imports = 0
        self._imported_ok = 0
        # boards the installer's ticked box brought over: asked once they're in
        self._ask_keep: list[str] = []
        self._exporting = False
        self._import_errors: list[importreport.Skipped] = []
        self._import_total = 0      # this batch, for the toast's "3 of 12"
        self._import_card_shut = False   # its card closed with ✕: the import goes on
        self._import_stop = threading.Event()   # its Stop: the files not started are skipped
        self._import_ids: list[str] = []   # added in this batch: Undo takes them off
        # sound id -> the hotkey it had in another soundboard (Import from Soundpad),
        # given to it once it's in if nothing here has that key
        self._import_keys: dict[str, str] = {}
        # the pads come in a few at a time while a big import runs, each playable at once
        self._import_pads = QTimer(mw, singleShot=True, interval=300,
                                   timeout=mw._rebuild_pads)   # pyright: ignore[reportCallIssue]

    def open_sounds_folder(self):
        mw = self.mw
        try:
            library.SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
            opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(library.SOUNDS_DIR)))
        except OSError as e:
            log.warning("can't make the sounds folder: %s", e)
            opened = False
        if opened:
            mw.toast(_("Opened your sounds folder"), "ok")
        else:
            mw.toast(_("Couldn't open the sounds folder: {sounds_dir}",
                         sounds_dir=html.escape(str(library.SOUNDS_DIR))), "warn")

    def _watch_sounds_folder(self):
        """Sound files dragged into the sounds folder in Explorer join the board,
        even ones put there while the app was closed."""
        mw = self.mw
        self._loose_sizes: dict[Path, tuple[int, int]] = {}
        self._loose_taken: set[Path] = set()   # imported or failed: not tried again
        self._loose_empty: dict[Path, tuple[tuple[int, int], int]] = {}   # sig, looks
        self._loose_timer = QTimer(mw)
        self._loose_timer.setSingleShot(True)
        self._loose_timer.setInterval(LOOSE_WAIT_MS)
        self._loose_timer.timeout.connect(self._take_loose)
        try:
            library.SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        self._folder_watch = QFileSystemWatcher([str(library.SOUNDS_DIR)], mw)
        self._folder_watch.directoryChanged.connect(lambda _p: self._loose_timer.start())
        self._loose_timer.start()

    def _take_loose(self):
        """Import the sounds folder's loose files once they're done copying in (the
        same size on two looks in a row)."""
        mw = self.mw
        seen, ready, empty = {}, [], {}
        # a sound on the Undo bar is off the board but its file is still here: not a
        # new one (it came back as a copy, without its hotkey, and its bin entry broke)
        undoable = {os.path.normcase(m.file) for m, *_rest in mw.rmctl._removed}
        for p in loose_sounds(mw.cfg):
            if p in self._loose_taken or os.path.normcase(str(p)) in undoable:
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            sig = (st.st_size, st.st_mtime_ns)
            if not st.st_size:   # never "ready": don't look again every 1.5 s forever
                was = self._loose_empty.get(p)
                looks = was[1] + 1 if was and was[0] == sig else 0
                empty[p] = (sig, looks)
                if looks >= LOOSE_EMPTY_LOOKS:
                    continue   # the folder changing (it's written to) looks again
            if st.st_size and self._loose_sizes.get(p) == sig:
                ready.append(p)
            else:
                seen[p] = sig
        self._loose_sizes, self._loose_empty = seen, empty
        if seen:
            self._loose_timer.start()   # still copying: look again
        if ready:
            self._loose_taken.update(ready)
            log.info("adding %d sound(s) put in the sounds folder", len(ready))
            self.import_files([str(p) for p in ready])

    def add_dialog(self):
        mw = self.mw
        exts = " ".join(f"*{e}" for e in sorted(AUDIO_EXTS))
        files, __ = QFileDialog.getOpenFileNames(
            mw, _("Add sounds"), str(Path.home()),
            _("Sounds and zips ({exts} *.zip);;Audio ({exts});;Zip of sounds, backup or "
              "sound pack (*.zip);;All files (*)", exts=exts))
        if files:
            self.import_files(files)

    def add_folder_dialog(self):
        """Add every sound in a folder (and its subfolders), as a drop of it would."""
        mw = self.mw
        folder = QFileDialog.getExistingDirectory(mw, _("Add sounds"), str(Path.home()))
        if folder:
            self.import_files(expand_dropped([folder]))

    def add_from_link(self):
        """A link already copied goes straight into the search box (its card shows);
        otherwise the box is focused for one to be pasted."""
        mw = self.mw
        copied = QApplication.clipboard().text().strip()
        if ytdl.as_link(copied):
            mw.search.setText(copied)
            mw.searchctl._show_link()
        else:
            mw.toast(_("Paste a link into the search box"))
        mw.search.setFocus()
        mw.search.selectAll()

    def import_files(self, files, extras: dict[str, otherboards.Entry] | None = None):
        """Add sound files (and zips / backups). `extras`: file -> its name, hotkey and
        categories from another soundboard; those already here are skipped quietly."""
        files = [f for f in files if f]
        extras = extras or {}
        for f in list(files):
            if (src := otherboards.for_file(f)) is not None:
                files.remove(f)   # another soundboard's saved board dropped on the window
                self.import_other(src, f)
        packages = [f for f in files if self._is_package(f)]
        if not packages:
            self._import_now(files, extras, {})
            return
        files = [f for f in files if f not in packages]

        def look():   # opening each zip: on the worker (a big one, or on OneDrive)
            return {f: backup.loose_audio(f) for f in packages}

        def then(found, err):
            if err is not None:
                log.warning("couldn't look into %s: %r", packages, err)
            found = found or {}
            # a plain zip of sound files: unpacked, then imported like the rest; a
            # backup / sound pack (a .zip, or a folder with its JSON) is read instead
            zips = {f: found[f] for f in packages if found.get(f)}
            for f in packages:
                if f not in zips:
                    self.import_package(f)
            self._import_now(files, extras, zips)
        self._on_worker(look, then, "import-look")

    def _import_now(self, files: list[str], extras: dict[str, otherboards.Entry],
                    zips: dict[str, list[str]]):
        """import_files once the zips are sorted: `zips` maps a plain zip to its sounds."""
        mw = self.mw
        count = len(files) + sum(len(n) for n in zips.values())
        if not count:
            return
        self._pending_imports += count
        start = len(mw.cfg.sounds)
        known = {m.fingerprint: m.name for m in mw.cfg.sounds if m.fingerprint}
        copy_local = mw.cfg.copy_local_sounds
        local_files = set(files)   # ZIP extraction adds temporary files later
        stop = self._import_stop
        sent = [0]   # answers so far: on_imported waits for `count` of them

        def emit(meta, data, err):
            sent[0] += 1
            mw.bridge.imported.emit(meta, data, err)

        def failed(e):   # the rest come back as one problem, so the import ends
            first = next(iter(zips), files[0] if files else "")
            for i in range(count - sent[0]):
                emit(None, None, importreport.classify(first, e) if i == 0 else None)
            return worker.SKIP

        def run():
            with tempfile.TemporaryDirectory(prefix="onionboard-zip-") as tmp:
                todo = list(files)
                for k, (z, names) in enumerate(zips.items()):
                    if stop.is_set():   # Stop: not unpacked, only counted down
                        for __ in names:
                            emit(None, None, None)
                        continue
                    try:
                        res = backup.extract_loose(z, names, Path(tmp) / str(k))
                    except Exception as e:  # noqa: BLE001 - too big, no room, damaged
                        log.warning("can't unpack %s: %s", z, e)
                        # one message for the zip; the rest only count down
                        emit(None, None, importreport.classify(z, e))
                        for __ in names[1:]:
                            emit(None, None, None)
                        continue
                    for _n, dest, err in res:
                        if dest is None:
                            sk = importreport.classify(z, err)
                            sk.file = f"{Path(z).name} → {_n}"
                            emit(None, None, sk)
                        else:
                            todo.append(str(dest))
                import_all(todo)

        def import_all(files):
            for i, shown in enumerate(files):
                if stop.is_set():   # Stop: the rest only count down, the ones in stay
                    emit(None, None, None)
                    continue
                f = shown   # read through any folder link Windows won't follow
                try:
                    f = str(winpath.usable(shown))
                    fp = fingerprint(f)
                    if fp and fp in known:
                        if shown in extras:
                            emit(None, None, None)   # already moved over
                            continue
                        raise importreport.AlreadyAdded(known[fp])
                    x = extras.get(shown)   # from another soundboard: named as it was there
                    meta, data = import_file(f, PAD_COLORS[(start + i) % len(PAD_COLORS)],
                                             name=x.name if x is not None else "",
                                             copy=copy_local or shown not in local_files
                                             or library.owns(Path(f)))
                    if x is not None:
                        meta.name = x.name or meta.name
                        meta.tags = clean_tags(x.tags)
                        if x.hotkey:
                            self._import_keys[meta.id] = x.hotkey
                    meta.image = thumbs.extract_art(f, meta.id)   # cover art / first frame
                    videos.link_import(meta.id, f)   # the player can show a video file
                    if fp:
                        known[fp] = meta.name   # the same file twice in one drop
                    mw.engine.prepare(meta.id, data)
                    if Path(f).parent == library.SOUNDS_DIR and Path(meta.file) != Path(f):
                        Path(f).unlink(missing_ok=True)   # dragged into the folder: now
                    emit(meta, data, None)   # it's in there as ours
                except Exception as e:  # noqa: BLE001
                    log.warning("can't import %s: %s", f, e)
                    emit(None, None, importreport.classify(shown, e))
        worker.run(run, mw.bridge.imported, "import", error=failed)
        busy.set_busy(mw.btn_add, True)   # back in on_imported, when they're all in
        self._import_total += count
        self._import_progress()

    def _import_progress(self):
        """The import's toast while it runs: "Adding 3 of 12…", with a bar. Several
        files get a bigger card with Bun; closing it (✕) only hides it: the import goes
        on, its sounds keep showing up, and the finished card still comes."""
        mw = self.mw
        total = self._import_total
        done = total - self._pending_imports
        text = (ngettext("Adding {count} sound…", "Adding {count} sounds…", total, count=total)
                if not done else _("Adding {done} of {total}…", done=done, total=total))
        if total <= 1:
            mw.toast(text, "busy", 0, key="import")   # up until it's in, however slow
            return
        if self._import_card_shut:
            return
        if self._ask_keep:   # the installer's box: say where they're coming from
            text = (_("Bringing your sounds over from {name}: {done} of {total}…",
                      name=self._ask_keep[0], done=done, total=total)
                    if len(self._ask_keep) == 1 else
                    _("Bringing your sounds over from your other soundboards: {done} of "
                      "{total}…", done=done, total=total))
        text = "<b>{}</b><br>{}".format(text, _("Each sound shows up as soon as it's in. "
                                                 "Closing this doesn't stop it."))
        t = mw.toast(text, "busy", 0, key="import", progress=(done, total),
                       action=(_("Stop"), self._stop_import),
                       picture=bunny.bunny_pixmap(44, dpr=mw.devicePixelRatioF()))
        if t is not None and not t.property("import_card"):
            t.setProperty("import_card", True)
            t.card.btn_close.clicked.connect(self._shut_import_card)

    def _shut_import_card(self):
        if self._pending_imports > 0:
            self._import_card_shut = True

    def _stop_import(self):
        """The card's Stop: the file being read finishes, the rest are skipped; the
        sounds already in stay (the finished card's Undo takes them off too)."""
        if self._pending_imports > 0:
            usage.used("import-stopped")
            self._import_stop.set()
            self._import_card_shut = True

    def on_imported(self, meta, data, err):
        mw = self.mw
        self._pending_imports -= 1
        if meta is not None:
            mw.catctl._tag_new(meta)
            meta.tags = library.merge_tags(meta.tags, mw.cfg.categories,
                                           mw.cfg.subcategories)
            key = library.clean_hotkey(self._import_keys.pop(meta.id, ""), meta.name)
            if key and not mw.hkctl._hotkey_taken(key):
                meta.hotkey = key
            mw.cfg.sounds.append(meta)
            mw._index()
            mw.audio[meta.id] = data
            self._imported_ok += 1
            if meta.duration < SHORT_SOUND_S:
                self._imported_short = True
            self._import_ids.append(meta.id)
            usage.used("add-files")
            usage.step(mw.cfg, "added-sound")
        elif err:
            self._import_errors.append(err)
        if self._pending_imports > 0:
            if meta is not None and not self._import_pads.isActive():
                self._import_pads.start()   # on the board soon, with the next few
            self._import_progress()
            return
        self._import_pads.stop()
        self._pending_imports = 0
        self._import_card_shut = False
        self._import_stop.clear()
        mw._save_now()
        mw._rebuild_pads()
        mw.catctl._fill_categories()   # categories and hotkeys from an Import from Soundpad
        mw.hkctl.register_hotkeys()
        n, self._imported_ok = self._imported_ok, 0
        short, self._imported_short = self._imported_short, False
        ids, self._import_ids = self._import_ids, []
        skipped, self._import_errors = self._import_errors, []
        self._import_total = 0
        busy.set_busy(mw.btn_add, False)
        mw.triggers.import_done()   # a trigger's sound that failed to import
        boards, self._ask_keep = self._ask_keep, []
        if boards and ids and not self._keep_imported(boards, ids):
            return
        if not n and not skipped:
            mw.toast(_("Nothing new to add"), key="import")
            return
        text, kind = importreport.summary(n, skipped)
        if skipped:
            usage.used("import-skipped")
            action = (_("See why"), lambda: self._show_skipped(skipped))
        else:
            action = (_("Undo"), lambda: mw.rmctl.remove_sounds(ids))
        mw.toast(text, kind, 8000 if skipped else 6000, key="import", action=action)
        self._flash_new(ids)
        if short:
            mw.toast(_("A sound you added is very short, so it may be barely "
                         "heard."), "warn")

    def _keep_imported(self, boards: list[str], ids: list[str]) -> bool:
        """The installer's box brought another soundboard's sounds over without asking:
        ask now whether to keep them, so nobody has to delete a big board pad by pad.
        False: they're removed (Undo and Recently deleted still have them)."""
        mw = self.mw
        text = (ngettext("We brought over <b>{n}</b> sound from {name}. Keep it?",
                         "We brought over <b>{n}</b> sounds from {name}. Keep them?",
                         len(ids), name=boards[0]) if len(boards) == 1 else
                ngettext("We brought over <b>{n}</b> sound from your other soundboards. "
                         "Keep it?",
                         "We brought over <b>{n}</b> sounds from your other soundboards. "
                         "Keep them?", len(ids)))
        box = QMessageBox(QMessageBox.Icon.Question, _("Keep your imported sounds?"), text,
                          QMessageBox.StandardButton.NoButton, mw)
        # Bun, smug: got your board and its settings in one go
        box.setIconPixmap(bunny.bunny_pixmap(84, dpr=mw.devicePixelRatioF(), smug=True))
        keep = box.addButton(_("Keep"), QMessageBox.ButtonRole.YesRole)
        remove = box.addButton(_("Remove"), QMessageBox.ButtonRole.NoRole)
        box.setInformativeText(_("Removed sounds come back with Undo, or later from Backup "
                                 "→ Recently deleted sounds."))
        box.setDefaultButton(keep)
        box.setEscapeButton(keep)   # closing it never deletes anything
        box.exec()
        kept = box.clickedButton() is not remove   # closed some other way: kept
        free_dialog(box)
        if not kept:
            mw.rmctl.remove_sounds(ids)
        return kept

    def _show_skipped(self, skipped):
        mw = self.mw
        dlg = importreport.SkippedDialog(skipped, mw)
        dlg.show()   # not modal: sounds keep playing

    def _flash_new(self, ids: list[str]):
        """The pads just added light up once (their hover glow), the first scrolled
        into view, so it's clear where they went."""
        mw = self.mw
        pads = [mw.pads[i] for i in ids if i in mw.pads]
        if not pads:
            return
        mw._pad_scroll.ensureWidgetVisible(pads[0])
        if not toastmod.animations_on():
            return
        for pad in pads:
            a = QVariantAnimation(pad)
            a.setDuration(900)
            a.setKeyValueAt(0.0, 0.0)
            a.setKeyValueAt(0.3, 1.0)
            a.setKeyValueAt(1.0, 0.0)
            a.valueChanged.connect(lambda v, pad=pad: pad.hover or pad._on_hover_k(v))
            a.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    # Export / import: see soundboard/backup.py and docs/BACKUP-FORMAT.md. The file
    # work runs on a thread; the result comes back through the bridge.
    @staticmethod
    def _is_package(path: str) -> bool:
        p = Path(path)
        if p.is_dir():
            return (p / backup.MANIFEST).is_file() or (p / backup.SOUND_JSON).is_file()
        return p.suffix.lower() == ".zip"

    def _save_name(self, title: str, name: str) -> str:
        mw = self.mw
        docs = Path.home() / "Documents"
        start = (docs if docs.is_dir() else Path.home()) / name
        f, __ = QFileDialog.getSaveFileName(mw, title, str(start), _("Zip file (*.zip)"))
        if f and not f.lower().endswith(".zip"):
            f += ".zip"
        return f

    def export_board(self):
        """Everything: every sound (with its picture, effects, hotkey, categories) and
        the app's settings, to move to another PC or keep as a backup."""
        mw = self.mw
        if not mw.cfg.sounds and not QMessageBox.question(
                mw, _("Export"), _("There are no sounds yet. Export just your settings?")) \
                == QMessageBox.StandardButton.Yes:
            return
        f = self._save_name(_("Export everything"),
                            f"Onion Board backup {time.strftime('%Y-%m-%d')}.zip")
        if f:
            self._export(f, list(mw.cfg.sounds), with_settings=True)

    def export_category(self):
        mw = self.mw
        if mw.cfg.category:
            self.export_sounds(mw.catctl.category_sounds(), mw.cfg.category)

    def export_sounds(self, sounds: list[SoundMeta], name: str):
        """A sound pack: just these sounds (no settings), e.g. to share with friends."""
        mw = self.mw
        if not sounds:
            mw.toast(_("There are no sounds in it to export."), "warn")
            return
        f = self._save_name(_("Export sounds"), backup._safe(name) + ".zip")
        if f:
            self._export(f, sounds, with_settings=False)

    def _export(self, path: str, sounds: list[SoundMeta], with_settings: bool):
        mw = self.mw
        mw._save_now()
        # snapshot on this thread: the UI keeps editing the live config (and each
        # sound's fx dict) while the export thread would be iterating over them
        cfg = copy.deepcopy(mw.cfg) if with_settings else None
        sounds = copy.deepcopy(sounds)
        cats = list(mw.cfg.categories)
        if self._exporting:
            mw.toast(_("Still exporting the last one, try again when it's done"), "warn")
            return
        self._exporting = True
        mw.toast(ngettext("Exporting {n} sound…", "Exporting {n} sounds…", len(sounds)))

        def run():
            skipped = []   # locked or vanished files: left out, the rest still go
            n = backup.export(path, sounds, cfg, cats, skipped)
            return path, n, "", len(skipped)
        # disk full, no permission…: told, and _exporting goes back
        worker.run(run, mw.bridge.exported, "export",
                   error=lambda e: (path, 0, errors.plain(e), 0), owner=mw)

    def _on_exported(self, path: str, n: int, err: str, skipped: int = 0):
        mw = self.mw
        self._exporting = False
        if err:
            mw.tell(_("Export failed"),   # in place of the "Exporting…" card
                      _("Couldn't write {name}:\n{err}",
                        name=Path(path).name, err=errors.plain(err)), "error")
            return
        msg = (ngettext("Exported {n} sound to {name}.",
                        "Exported {n} sounds to {name}.",
                        n, name=html.escape(Path(path).name)))
        if skipped:
            msg += " " + ngettext("{n} sound couldn't be read and was left out.",
                                  "{n} sounds couldn't be read and were left out.", skipped)
        mw.toast(msg, "warn" if skipped else "ok")

    def show_packs(self):
        """The Free packs window (soundboard.packs): a pack it downloads is imported the
        way dropping its zip on the window is."""
        mw = self.mw
        from soundboard.ui.packsdialog import PacksDialog
        dlg = PacksDialog(lambda path: self.import_files([str(path)]), mw,
                          play=self._pack_sample)
        dlg.exec()
        free_dialog(dlg)

    def _pack_sample(self, data, gain: float) -> bool:
        """Free packs' samples: to your headphones only (None stops it). False: no
        headphones to play them on."""
        mw = self.mw
        if data is None:
            mw.engine.stop(PACK_SAMPLE)
            return True
        return mw.engine.play(PACK_SAMPLE, data, gain, mode="restart",
                                preview=True) is not None

    def import_dialog(self):
        mw = self.mw
        files, __ = QFileDialog.getOpenFileNames(
            mw, _("Import a backup, sound pack or zip of sounds"), str(Path.home()),
            _("Zip file (*.zip)"))
        if files:
            self.import_files(files)   # a plain zip of sounds is imported too

    def import_queued(self):
        """The installer's "Bring my sounds over from …" boxes, ticked: they left a
        note for this start. The tick was their yes, so nothing is asked again."""
        note = library.APP_DIR / otherboards.QUEUED_NAME
        if not note.is_file():
            return
        try:
            keys = note.read_text(encoding="utf-8", errors="replace").split()
        except OSError:
            keys = []
        note.unlink(missing_ok=True)
        for key in dict.fromkeys(keys):
            if (src := otherboards.by_key(key)) is not None:
                self._ask_keep.append(src.name)
                self.import_other(src, ask=False)

    def import_other(self, src: otherboards.Source, path: str = "", ask: bool = True):
        """Bring another soundboard's board over: its sound files (copied, it keeps its
        own), names, categories and the hotkeys nothing here uses yet. `ask`: False
        when they already said yes (the installer's box): no questions or pop-ups."""
        usage.used("import-board")
        self._read_board(src, path, ask)

    def _read_board(self, src: otherboards.Source, path: str, ask: bool):
        # finding and reading the board, and checking every sound file is there, run on
        # a thread: the board file can be tens of MB and its sounds on a network drive
        # that's gone, which takes seconds a file (the window froze, even at start-up)
        mw = self.mw
        where = [path]

        def run():
            if not where[0]:
                try:
                    where[0] = str(src.find() or "")
                except OSError:
                    where[0] = ""
            if not where[0]:
                return src, "", ask, None
            entries = src.read(Path(where[0]))
            return src, where[0], ask, (*otherboards.importable(entries), entries)
        # a board that can't be read (or a bad one) comes back as what it raised
        worker.run(run, mw.board_read, "import-board",
                   error=lambda e: (src, where[0], ask, e), owner=mw)

    def _board_read(self, src: otherboards.Source, path: str, ask: bool, result):
        """import_other's read is back: the question, then the import, here on the UI
        thread (the window may have closed in the meantime)."""
        mw = self.mw
        if mw._shut_down:
            return
        title = _("Import from {name}", name=src.name)
        if not path and not ask:
            return   # its board went away since the install
        if not path:
            path, __ = QFileDialog.getOpenFileName(
                mw, _("{title}: pick a saved board", title=title), str(Path.home()),
                _("{name} board ({patterns})", name=src.name,
                  patterns=" ".join("*" + x for x in src.suffixes)))
            if path:
                self._read_board(src, path, ask)
            return
        if isinstance(result, Exception):
            e = result
            if not ask:
                log.warning("can't read %s's board: %s", src.name, e)
                mw.toast(_("Couldn't bring your {name} sounds over: {e}",
                             name=src.name, e=errors.plain(e)),
                           "warn")
            else:
                errors.warn(mw, _("Couldn't read the {name} board", name=src.name), e)
            return
        ok, bad, entries = result
        if not ok:
            msg = (_("No sounds to bring over: the sound files {name} points at have been moved "
                     "or deleted.", name=src.name) if entries else
                   _("There are no sounds on your {name} board.", name=src.name))
            mw.toast(html.escape(msg), "warn")
            return
        for e in ok:   # all in a category named after it too, so they're easy to find
            e.tags = [src.name, *(t for t in e.tags if t != src.name)]
        if ask:
            keys = sum(1 for e in ok if e.hotkey)
            cats = {t for e in ok for t in e.tags}
            n_cats = ngettext("{n} category", "{n} categories", len(cats))
            n_keys = ngettext("{n} hotkey", "{n} hotkeys", keys)
            if cats and keys:
                found = ngettext("Found <b>{n}</b> sound in {name} with {categories} and "
                                 "{hotkeys}.", "Found <b>{n}</b> sounds in {name} with "
                                 "{categories} and {hotkeys}.", len(ok), name=src.name,
                                 categories=n_cats, hotkeys=n_keys)
            elif cats or keys:
                found = ngettext("Found <b>{n}</b> sound in {name} with {what}.",
                                 "Found <b>{n}</b> sounds in {name} with {what}.", len(ok),
                                 name=src.name, what=n_cats if cats else n_keys)
            else:
                found = ngettext("Found <b>{n}</b> sound in {name}.",
                                 "Found <b>{n}</b> sounds in {name}.", len(ok), name=src.name)
            lines = [found,
                     _("They're copied into Onion Board; {name} keeps its own. Ones "
                       "already here are skipped, and a hotkey something here already "
                       "uses is left off.", name=src.name),
                     _("They go in a category called “{name}”.", name=html.escape(src.name))]
            if bad:
                lines.append(ngettext(
                    "{n} more can't be brought over (the file was moved or deleted, or isn't "
                    "a sound): {names}", "{n} more can't be brought over (the file was moved "
                    "or deleted, or isn't a sound): {names}", len(bad),
                    names=html.escape(", ".join(e.name for e in bad[:5]))
                    + ("…" if len(bad) > 5 else "")))
            if QMessageBox.question(mw, title, "<br><br>".join(lines),
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                                    ) != QMessageBox.StandardButton.Yes:
                return
        self.import_files([e.path for e in ok], {e.path: e for e in ok})

    def import_package(self, path: str):
        """Add the sounds from a backup / sound pack (ones already here are skipped).
        A full backup's settings are only applied if the user says so.
        Reading it (a big zip takes a moment) runs on a worker; this returns at once."""
        self._on_worker(lambda: backup.read(path),
                        lambda pkg, err: self._package_read(path, pkg, err), "import-read")

    def _package_read(self, path: str, pkg, err):
        mw = self.mw
        if isinstance(err, backup.BackupError):
            errors.warn(mw, _("Can't import"), err)
            return
        if err is not None:   # a damaged or odd file, never a crash
            log.warning("couldn't read %s: %r", path, err)
            mw.tell(_("Can't import"),
                      _("{name} is damaged or in a format Onion Board can't read ({e}).",
                        name=Path(path).name, e=errors.plain(err)), "error")
            return
        use_settings = False
        if pkg.settings:
            box = QMessageBox(QMessageBox.Icon.Question, _("Import backup"),
                              ngettext("{name} has {n} sound and the settings they were saved "
                                       "with (theme, hotkeys, overlay, voice effects…).\n\nUse "
                                       "its settings too? Your devices stay as they are.",
                                       "{name} has {n} sounds and the settings they were saved "
                                       "with (theme, hotkeys, overlay, voice effects…).\n\nUse "
                                       "its settings too? Your devices stay as they are.",
                                       len(pkg.sounds), name=Path(path).name),
                              QMessageBox.StandardButton.NoButton, mw)
            yes = box.addButton(_("Sounds and settings"), QMessageBox.ButtonRole.YesRole)
            box.addButton(_("Just the sounds"), QMessageBox.ButtonRole.NoRole)
            cancel = box.addButton(QMessageBox.StandardButton.Cancel)
            box.exec()
            clicked = box.clickedButton()
            free_dialog(box)
            if clicked is cancel:
                return
            use_settings = clicked is yes
        if use_settings and pkg.settings:   # (only asked when there are some)
            self._apply_backup_settings(pkg.settings)
        if not pkg.sounds:
            return
        # only what's on the board: a sound removed a moment ago (still undo-able) must
        # come back from its backup, or deleting all then restoring leaves nothing
        # a backup goes by name too: a removed pad that shared its audio with one still
        # here ("Save as new sound") comes back rather than being "already in your
        # library". A pack's sound is skipped whenever its audio is here, whatever its name
        names: dict[str, set[str]] = {}
        for m in mw.cfg.sounds:
            if m.fingerprint:
                names.setdefault(m.fingerprint, set()).add(m.name.lower())
        known = set(names) if pkg.is_pack else names
        have = {(m.pack, m.pack_item) for m in mw.cfg.sounds if m.pack}
        start = len(mw.cfg.sounds)
        mw.toast(ngettext("Importing {n} sound…", "Importing {n} sounds…", len(pkg.sounds)))

        def run():
            if pkg.is_pack:   # kept, so it can be reset or removed in one go later
                backup.keep_pack(pkg)
            res = backup.install(
                pkg, known, lambda i: PAD_COLORS[(start + i) % len(PAD_COLORS)], have)
            return res, pkg, ""
        worker.run(run, mw.bridge.unpacked, "import-pack",
                   error=lambda e: (None, pkg, errors.plain(e)), owner=mw)

    def _apply_backup_settings(self, raw: dict):
        mw = self.mw
        was_off = list(mw.cfg.tabs_off)
        had_programs = dict(mw.cfg.category_programs)
        changed = backup.apply_settings(mw.cfg, raw)
        if "category_programs" in changed:   # added to the rules here, not in their place
            mw.cfg.category_programs = {**had_programs, **mw.cfg.category_programs}
            mw.catctl.cat_switch.reset()
            mw.catctl._update_cat_timer()
            mw.catctl._fill_categories()
        if "tabs_off" in changed:   # the tabs follow now: a list saying one thing while
            # the window shows another left the Voice tab unreachable, and Settings
            # crashed reaching into a stand-in
            off, mw.cfg.tabs_off = mw.cfg.tabs_off, was_off
            for key in taboff.KEYS:
                mw.tabctl.set_tab_on(key, key not in off)
            mw.set_option("tabs_off", off)   # with a newer version's keys
        if mw.voice.fx.merge_saved(raw.get(backup.SAVED_VOICES)):   # their own file
            changed.append("saved voices")
        if "theme" in changed:
            mw.themectl.apply_theme(mw.cfg.theme)
        mw._save_now()
        mw.hkctl.register_hotkeys()
        if changed:
            mw.tell(_("Settings imported"),
                      _("Done. Hotkeys and the theme apply now; everything else "
                        "the next time Onion Board starts."), "ok")

    def _take_pack_hotkeys(self, clashes: list[tuple[str, SoundMeta, SoundMeta]],
                           name: str) -> bool:
        """Some sounds in a pack use hotkeys sounds here already have: give those keys
        to the pack's sounds? No (the default, and Esc) keeps them on yours."""
        mw = self.mw
        lines = "\n".join(f"{pretty_key(k)}: {old.name} → {new.name}"
                          for k, old, new in clashes[:10])
        if len(clashes) > 10:
            lines += "\n…"
        box = QMessageBox(QMessageBox.Icon.Question, _("Same hotkeys"),
                          ngettext("A sound in “{name}” uses a hotkey one of your sounds "
                                   "already has:\n\n{lines}\n\nGive it to the new sound?",
                                   "{n} sounds in “{name}” use hotkeys your sounds already "
                                   "have:\n\n{lines}\n\nGive them to the new sounds?",
                                   len(clashes), name=name, lines=lines),
                          QMessageBox.StandardButton.NoButton, mw)
        yes = box.addButton(_("Use the new ones"), QMessageBox.ButtonRole.YesRole)
        keep = box.addButton(_("Keep mine"), QMessageBox.ButtonRole.NoRole)
        box.setDefaultButton(keep)
        box.setEscapeButton(keep)   # closing it never deletes anything
        box.setEscapeButton(keep)
        box.exec()
        clicked = box.clickedButton()
        free_dialog(box)
        return clicked is yes

    def _on_unpacked(self, res, pkg, err: str):
        mw = self.mw
        mw.statusctl._update_status()
        if res is None:
            mw.tell(_("Import failed"), err, "error")
            return
        self._settle_hotkeys(res.sounds + pkg.restored, self._pack_name(pkg))
        from soundboard.library import merge_tags
        if pkg.is_pack and len({library.split_tag(t)[0].lower() for ps in pkg.sounds
                                for t in clean_tags(ps.entry.get("tags"))}) > 1:
            # one tab for the pack, its categories inside it as subcategories
            library.group_pack_tags(res.sounds + pkg.restored, self._pack_name(pkg))
        order = [ps.folder for ps in pkg.sounds]
        for m in pkg.restored + res.sounds:
            # "memes" goes into the "Memes" already here (and a new one gets a tab)
            m.tags = merge_tags(m.tags, mw.cfg.categories, mw.cfg.subcategories)
        for m in res.sounds:
            mw.cfg.sounds.insert(self._pack_spot(m, order), m)
        merge_tags(pkg.categories, mw.cfg.categories,   # a full backup's empty ones too
                   mw.cfg.subcategories)
        for m in pkg.restored:
            mw.engine.set_gain(m.id, mw.gain_for(m))
        mw._save_now()
        mw._rebuild_pads()
        mw.catctl._fill_categories()
        mw.soundctl._load_all()
        mw.hkctl.register_hotkeys()
        n = len(res.sounds)
        if pkg.restored:   # Backup → My sound packs → Reset to how it came
            msg = _("“{name}” is back how it came", name=self._pack_name(pkg))
            if n:
                msg += ngettext(" ({n} removed sound put back)",
                                " ({n} removed sounds put back)", n)
        elif res.skipped:
            msg = ngettext("Imported {n} sound ({skipped} already in your library)",
                           "Imported {n} sounds ({skipped} already in your library)", n,
                           skipped=len(res.skipped))
        else:
            msg = ngettext("Imported {n} sound", "Imported {n} sounds", n)
        mw.toast(msg, "ok" if n or pkg.restored else "")
        if res.failed:
            skipped = [importreport.Skipped(line, "", "unreadable") for line in res.failed]
            mw.toast(html.escape(_("Some sounds weren't imported")), "warn", 10000,
                       action=(_("See why"), lambda: self._show_skipped(skipped)))

    def _settle_hotkeys(self, incoming: list[SoundMeta], name: str):
        """Hotkeys coming in with a pack that are already in use. Ones a sound here has:
        ask whether the pack's sounds take them. App-wide keys, category keys and
        push-to-talk always stay where they are. Whatever's still taken is cleared on
        the incoming sound (and a key twice in the pack goes to the first)."""
        mw = self.mw
        taken = {getattr(mw.cfg, a) for a, *__ in HOTKEY_ACTIONS if getattr(mw.cfg, a)}
        taken |= {k for k in mw.cfg.category_hotkeys.values() if k}
        if mw.cfg.ptt_key:   # pressed by us for the game: never a sound's hotkey
            taken.add(mw.cfg.ptt_key)
        ids = {m.id for m in incoming}
        mine = {o.hotkey: o for o in mw.cfg.sounds if o.hotkey and o.id not in ids}
        clashes, seen = [], set(taken)
        for m in incoming:
            if m.hotkey and m.hotkey not in seen and m.hotkey in mine:
                clashes.append((m.hotkey, mine[m.hotkey], m))
            seen.add(m.hotkey)
        if clashes and self._take_pack_hotkeys(clashes, name):
            for _key, old, _new in clashes:
                old.hotkey = ""   # the pack's sound gets it instead
        taken |= {o.hotkey for o in mw.cfg.sounds if o.hotkey and o.id not in ids}
        for m in incoming:
            if m.hotkey in taken:
                m.hotkey = ""   # the sounds already here keep theirs
            taken.add(m.hotkey)

    def _pack_name(self, pkg) -> str:
        return backup.packs().get(pkg.pack_id) or Path(pkg.path).name

    def _pack_spot(self, m: SoundMeta, order: list[str]) -> int:
        """Where a sound coming back into its pack goes: after the pack's sound before it
        (or before the one after it) on the board; anything else goes on the end."""
        mw = self.mw
        if not m.pack or m.pack_item not in order:
            return len(mw.cfg.sounds)
        at = {o.pack_item: i for i, o in enumerate(mw.cfg.sounds) if o.pack == m.pack}
        k = order.index(m.pack_item)
        for f in reversed(order[:k]):
            if f in at:
                return at[f] + 1
        for f in order[k + 1:]:
            if f in at:
                return at[f]
        return len(mw.cfg.sounds)

    def _fill_packs_menu(self, menu: QMenu):
        """Backup → My sound packs: each pack imported, to reset or remove in one go."""
        mw = self.mw
        menu.clear()
        for pid, name in backup.packs().items():
            n = sum(m.pack == pid for m in mw.cfg.sounds)
            sub = menu.addMenu(ngettext("{name} ({n} sound)", "{name} ({n} sounds)", n,
                                        name=name.replace("&", "&&")))   # not a shortcut
            sub.addAction(_("Reset to how it came"), lambda pid=pid: self.reset_pack(pid))
            if self._ungrouped_pack_sounds(pid):
                sub.addAction(_("Put its categories in one tab"),
                              lambda pid=pid: self.tidy_pack(pid))
            act = sub.addAction(_("Remove from the board"), lambda pid=pid: self.remove_pack(pid))
            act.setEnabled(bool(n))

    @staticmethod
    def _pack_own_categories(pid: str) -> set[str]:
        """The categories a free pack comes with (lower case); {} for any other pack."""
        from soundboard import packs
        return {c.lower() for p in packs.built_in() if p.id == pid for c in p.categories}

    def _ungrouped_pack_sounds(self, pid: str) -> list[SoundMeta]:
        """Sounds of pack `pid` still in its categories as tabs of their own."""
        mw = self.mw
        own = self._pack_own_categories(pid)
        return [m for m in mw.cfg.sounds if m.pack == pid and any(
            library.split_tag(t)[0].lower() in own and not library.split_tag(t)[1]
            for t in m.tags)] if own else []

    def tidy_pack(self, pid: str):
        """Backup → My sound packs → Put its categories in one tab: the pack's categories
        (Tavern, Combat…) stop being tabs and become subcategories of one named after
        the pack. Sounds you added to your own categories stay in them."""
        mw = self.mw
        moved = self._ungrouped_pack_sounds(pid)
        name = backup.packs().get(pid, pid)
        own = self._pack_own_categories(pid)
        if not moved:
            return
        if QMessageBox.question(
                mw, _("Put its categories in one tab"),
                _("Make one “{name}” tab, with {n} of its categories inside it as "
                  "subcategories instead of tabs of their own?\n\nNo sound is removed or "
                  "changed.", name=name, n=len(own)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
                ) != QMessageBox.StandardButton.Yes:
            return
        mine = [m for m in mw.soundctl._live_metas() if m.pack == pid]
        library.group_pack_tags(mine, name, own)
        merge = library.merge_tags
        for m in mine:
            m.tags = merge(m.tags, mw.cfg.categories, mw.cfg.subcategories)
        live = mw.soundctl._live_metas()
        for c in list(mw.cfg.categories):   # the old tabs, once nothing is in them
            if c.lower() in own and not any(c in m.tags for m in live) and not (
                    mw.cfg.category_hotkeys.get(c)
                    or catswitch.programs_for(mw.cfg.category_programs, c)):
                mw.cfg.categories.remove(c)
                mw.cfg.category_colors.pop(c, None)
                mw.cfg.subcategories.pop(c, None)
        if mw.cfg.category not in mw.cfg.categories:
            mw.cfg.category = mw.cfg.subcategory = ""
        mw._save_now()
        mw.catctl._fill_categories()
        mw.searchctl.apply_filter(mw.search.text())
        mw.hkctl.register_hotkeys()
        mw.toast(_("✓ “{name}” is one tab now", name=html.escape(name)), "ok")

    def reset_pack(self, pid: str, ask: bool = True):
        """Put a sound pack back how it came: its sounds' names, hotkeys, volume,
        effects, categories and pictures, and its removed sounds come back.
        The pack is read, and its pictures put back, on a worker; this returns at once."""
        def read():
            pkg = backup.read_pack(pid)
            return pkg, self._pack_name(pkg)
        self._on_worker(read, lambda got, err: self._pack_read(pid, got, err, ask),
                        "reset-read")

    def _pack_read(self, pid: str, got, err, ask: bool):
        mw = self.mw
        if err is not None:
            if not isinstance(err, backup.BackupError):
                log.warning("couldn't read the sound pack %s: %r", pid, err)
            errors.warn(mw, _("Can't reset the sound pack"), err)
            return
        pkg, name = got
        if ask and QMessageBox.question(
                mw, _("Reset sound pack"),
                _("Put the sounds from “{name}” back how they came?\n\nChanges you made to "
                  "them (names, hotkeys, volume, effects, pictures…) are undone, and ones you "
                  "removed come back. Your other sounds aren't touched.", name=name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
                ) != QMessageBox.StandardButton.Yes:
            return
        on_board = {}
        for m in mw.cfg.sounds:
            if m.pack == pid:
                on_board.setdefault(m.pack_item, m)
        # put back on copies (the pictures are re-encoded: disk), copied over here
        copies = {k: copy.copy(m) for k, m in on_board.items()}
        missing = [ps for ps in pkg.sounds if ps.folder not in on_board]
        start = len(mw.cfg.sounds)

        def run():
            restored = backup.reset_sounds(pkg, copies)
            if not missing:
                return restored, backup.Imported(), ""
            full = list(pkg.sounds)
            pkg.sounds = missing
            try:
                res = backup.install(
                    pkg, set(), lambda i: PAD_COLORS[(start + i) % len(PAD_COLORS)])
            except Exception as e:  # noqa: BLE001
                log.exception("reset of the sound pack %s failed", pid)
                res, err = None, errors.plain(e)
            else:
                err = ""
            finally:
                pkg.sounds = full   # for _pack_spot's order
            return restored, res, err

        def then(got, err):
            if err is not None:
                if not isinstance(err, (OSError, backup.BackupError)):
                    log.warning("reset of the sound pack %s failed: %r", pid, err)
                errors.warn(mw, _("Can't reset the sound pack"), err)
                return
            restored, res, failed = got
            pkg.restored = []
            for c in restored:
                m = on_board[c.pack_item]
                if m not in mw.cfg.sounds:   # removed while it ran
                    continue
                fx_before = soundfx.key(m.fx)
                for k in (*backup.SOUND_FIELDS, "image"):
                    setattr(m, k, getattr(c, k))
                pkg.restored.append(m)
                if soundfx.key(m.fx) != fx_before:
                    mw.editctl._rerender(m)
                if p := mw.pads.get(m.id):
                    p.update()
            self._on_unpacked(res, pkg, failed)
        self._on_worker(run, then, "reset-pack")

    def _on_worker(self, work, then, name: str):
        """work() (reading a backup or pack: disk) on a worker thread with the busy
        cursor up, then then(its result, None) or then(None, what it raised) back on
        the UI thread."""
        mw = self.mw
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        # what it raised is said by then(); the window gone (quitting): nothing
        worker.run(lambda: (then, work(), None), mw.bridge.worked, name,
                   error=lambda e: (then, None, e), owner=mw)

    def _on_worked(self, then, res, err):
        mw = self.mw
        QApplication.restoreOverrideCursor()
        if mw._shut_down:   # closed while it ran
            return
        then(res, err)

    def remove_pack(self, pid: str, ask: bool = True):
        """Take every sound of a sound pack off the board (one Undo brings them back);
        once the Undo bar is gone, the pack is no longer kept."""
        mw = self.mw
        gone = [m.id for m in mw.cfg.sounds if m.pack == pid]
        if not gone:
            return
        name = backup.packs().get(pid, pid)
        if ask and QMessageBox.question(
                mw, _("Remove sound pack"),
                ngettext("Remove the {n} sound from “{name}”?",
                         "Remove the {n} sounds from “{name}”?", len(gone), name=name)
                + "\n\n" + _("You can undo this, or bring them back from Recently deleted."),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
                ) != QMessageBox.StandardButton.Yes:
            return
        mw.rmctl.remove_sounds(gone)
        self._packs_removed.add(pid)
