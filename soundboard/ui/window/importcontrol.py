"""Getting sounds in and out of the board, in the main window: Add sounds / a folder /
a link, files dropped on the window, the sounds folder's loose files, backups and
sound packs (import, export, tidy, reset, remove), other soundboards' sounds, and the
Free packs window.

MainWindow makes one ``ImportControl`` (``MainWindow.impctl``) and sends it the
bridge's ``imported`` / ``exported`` / ``worked`` signals. The file work runs on
workers (library.py, backup.py, otherboards.py); everything here runs on the UI thread."""
from __future__ import annotations

import html
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QFileSystemWatcher, Qt, QTimer, QUrl, QVariantAnimation, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QFileDialog

from soundboard.core import (
    backup,
    errors,
    usage,
)
from soundboard.ui.bun import bunny
from soundboard import otherboards
from soundboard.sounds import (
    library,
    thumbs,
    videos,
)
from soundboard.online import ytdl
from soundboard.win import winpath
from soundboard.i18n import _, ngettext
from soundboard.sounds.library import (
    AUDIO_EXTS,
    PAD_COLORS,
    clean_tags,
    fingerprint,
    import_file,
    loose_sounds,
)
from soundboard.ui.kit import busy, worker
from soundboard.ui.sounds import importreport
from soundboard.ui.kit import toast as toastmod
from soundboard.ui.window.controller import Controller
from soundboard.ui.window.importbackup import BackupImport
from soundboard.ui.window.importpacks import (
    PACK_SAMPLE, PackImport, pack_tab_name)  # noqa: F401  (moved there)
from soundboard.ui.kit.widgets import expand_dropped

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

log = logging.getLogger(__name__)

SHORT_SOUND_S = 0.3   # an added sound shorter than this gets a "very short" note
LOOSE_WAIT_MS = 1500   # a file dragged into the sounds folder is looked at again (ms)
LOOSE_EMPTY_LOOKS = 20   # an empty file that long (~30 s) waits for the folder to change


class ImportControl(BackupImport, PackImport, Controller):
    """Importing, exporting and sound packs for one MainWindow (``mw``)."""
    _loose_checked = Signal(object)   # _take_loose's look on a thread: [(Path, sig)] | None
    # a links pack asked for again later (PackImport): pack, (path, skipped, later) | None,
    # what it raised | None
    _pack_refetched = Signal(object, object, object)
    # some of a links pack's sounds, as they came (PackImport): then, [SoundMeta]
    _pack_came = Signal(object, object)

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self._loose_checked.connect(self._loose_found)
        self._pack_refetched.connect(self._pack_retried)
        self._pack_retries: set[str] = set()   # links packs waiting to be asked for again
        self._pack_came.connect(lambda then, got: then(got))
        # free pack id -> {sound id: its pack folder}: put on the board as they came, made
        # the pack's own once it all lands (_package_read)
        self._pack_early: dict[str, dict[str, str]] = {}
        self._packs_removed: set[str] = set()   # sound packs to stop keeping after Undo
        self._packs_page = None   # the Free packs page, while it's in the tabs' place
        self._imported_short = False      # a sound added in this batch is under SHORT_SOUND_S
        self._pending_imports = 0
        self._imported_ok = 0
        # other soundboards on their way in: each has its own category, named on the card
        self._boards: list[str] = []
        self._exporting = False
        self._import_errors: list[importreport.Skipped] = []
        self._import_total = 0      # this batch, for the toast's "3 of 12"
        self._import_card_shut = False   # its card closed with ✕: the import goes on
        self._import_stop = threading.Event()   # its Stop: the files not started are skipped
        # the sounds in, or on their way in, by fingerprint: shared by every import
        # running at once, so the same board imported twice together isn't added twice
        self._known: dict[str, str] = {}
        self._known_lock = threading.Lock()
        self._import_ids: list[str] = []   # added in this batch: Undo takes them off
        # sound id -> the hotkey it had in another soundboard (Import from Soundpad),
        # given to it once it's in if nothing here has that key
        self._import_keys: dict[str, str] = {}
        # the pads come in a few at a time while a big import runs, each playable at once
        # (the first one at once, as the card says; the ones landing right after it
        # wait for this, so a big import doesn't rebuild the board for every sound)
        self._import_pads = QTimer(mw, singleShot=True, interval=300,
                                   timeout=self._owed_pads)   # pyright: ignore[reportCallIssue]
        self._pads_owed = False

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
        self._loose_looking = False   # the folder is being listed on a thread
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
        same size on two looks in a row). The folder is listed on a thread (it can be
        big, or on OneDrive): _loose_found does the rest."""
        mw = self.mw
        if self._loose_looking:   # one look at a time: this one looks again after it
            self._loose_timer.start()
            return
        self._loose_looking = True
        cfg = library.Config(sounds=list(mw.cfg.sounds))   # (the board changes meanwhile)

        def look():
            found = []
            for p in loose_sounds(cfg):
                try:
                    st = p.stat()
                except OSError:
                    continue
                found.append((p, (st.st_size, st.st_mtime_ns)))
            return (found,)
        worker.run(look, self._loose_checked, "loose-sounds", error=(None,), owner=mw)

    def _loose_found(self, found):
        mw = self.mw
        self._loose_looking = False
        if found is None or mw._shut_down:   # (the failure is logged)
            return
        seen, ready, empty = {}, [], {}
        # a sound on the Undo bar is off the board but its file is still here: not a
        # new one (it came back as a copy, without its hotkey, and its bin entry broke)
        undoable = {os.path.normcase(m.file) for m, *_rest in mw.rmctl._removed}
        for p, sig in found:
            if p in self._loose_taken or os.path.normcase(str(p)) in undoable:
                continue
            if not sig[0]:   # empty: never "ready", so not looked at every 1.5 s forever
                was = self._loose_empty.get(p)
                looks = was[1] + 1 if was and was[0] == sig else 0
                empty[p] = (sig, looks)
                if looks >= LOOSE_EMPTY_LOOKS:
                    continue   # the folder changing (it's written to) looks again
            if sig[0] and self._loose_sizes.get(p) == sig:
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
        """A link already copied goes straight into the search box (its card shows),
        and so do several (their cards, with Add all); otherwise the box is focused for
        one to be pasted."""
        mw = self.mw
        copied = QApplication.clipboard().text().strip()
        many = ytdl.as_links(copied)
        if ytdl.as_link(copied) or many:
            mw.search.setText(" ".join(many) if many else copied)
            mw.searchctl.flush_search()   # (the link bar has them now)
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
        if not self._pending_imports:   # nothing else running: start from the library
            self._known = {m.fingerprint: m.name for m in mw.cfg.sounds if m.fingerprint}
        self._pending_imports += count
        start = len(mw.cfg.sounds)
        known, lock = self._known, self._known_lock
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
                    with lock:   # taken here, before it's read in: the other import skips it
                        had = known.get(fp) if fp else None
                        if fp and had is None:
                            known[fp] = Path(shown).stem
                    if had is not None:
                        if shown in extras:
                            emit(None, None, None)   # already moved over
                            continue
                        raise importreport.AlreadyAdded(had)
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
        if self._boards:   # another soundboard: say where they're coming from
            text = (_("Bringing your sounds over from {name}: {done} of {total}…",
                      name=self._boards[0], done=done, total=total)
                    if len(self._boards) == 1 else
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

    def _owed_pads(self):
        """The import's pad timer: the sounds that landed since the last rebuild."""
        if self._pads_owed:
            self._pads_owed = False
            self.mw._rebuild_pads()
            self._import_pads.start()   # and the ones still coming wait again

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
            if not set(meta.tags) & set(self._boards):   # a board's: in its own category
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
            if meta is not None:
                if self._import_pads.isActive():
                    self._pads_owed = True   # with the next few, in a moment
                else:
                    mw._rebuild_pads()   # on the board now, playable at once
                    self._import_pads.start()
            self._import_progress()
            return
        self._import_pads.stop()
        self._pads_owed = False
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
        boards = list(self._boards)
        self._drop_empty_boards()
        if not n and not skipped:
            mw.toast(_("Nothing new to add"), key="import")
            return
        text, kind = importreport.summary(n, skipped)
        if len(boards) == 1 and not skipped:   # another soundboard's: say where they went
            text = _("✓ Added {count} to {name}", count=ngettext("{n} sound", "{n} sounds", n),
                     name=html.escape(boards[0]))
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

    def _show_board(self, name: str):
        """Another soundboard's sounds are on their way in: its category is made and
        shown now, so each sound is seen landing in it (not in All)."""
        mw = self.mw
        if name not in self._boards:
            self._boards.append(name)
        cat = library.merge_tags([name], mw.cfg.categories)[0]
        mw.catctl._fill_categories()
        mw.catctl.set_category(cat)

    def _drop_empty_boards(self):
        """The import's done: a board's category that got nothing (all already here)
        goes again."""
        mw = self.mw
        boards, self._boards = self._boards, []
        empty = [c for c in mw.cfg.categories if c in boards
                 and not any(c in m.tags for m in mw.cfg.sounds)]
        if not empty:
            return
        for c in empty:
            mw.cfg.categories.remove(c)
        if mw.cfg.category in empty:
            mw.catctl.set_category("")
        mw.catctl._fill_categories()
        mw._save_now()

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
                self.import_other(src, ask=False)

    def import_other(self, src: otherboards.Source, path: str = "", ask: bool = True):
        """Bring another soundboard's board over: its sound files (copied, it keeps its
        own), names, categories and the hotkeys nothing here uses yet. Never asks
        "are you sure?": picking it was the yes. `ask`: False for the installer's box
        (no file picker or pop-ups, only toasts)."""
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
        """import_other's read is back: the import, here on the UI
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
        # picking "Import from …" was their yes: no "are you sure?" box, it just imports
        if bad and ask:
            mw.toast(ngettext(
                "{n} more can't be brought over (the file was moved or deleted, or isn't "
                "a sound): {names}", "{n} more can't be brought over (the file was moved "
                "or deleted, or isn't a sound): {names}", len(bad),
                names=html.escape(", ".join(e.name for e in bad[:5]))
                + ("…" if len(bad) > 5 else "")), "warn")
        self._show_board(src.name)
        self.import_files([e.path for e in ok], {e.path: e for e in ok})

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

