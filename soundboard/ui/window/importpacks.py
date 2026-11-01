"""Sound packs in the main window: the Free packs window, a pack's category, tidying,
resetting and removing a pack. A mixin of ImportControl (importcontrol.py)."""
from __future__ import annotations

import copy
import html
import logging
import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QMenu, QMessageBox
from shiboken6 import isValid as qt_valid

from soundboard.core import (
    backup,
    errors,
    usage,
)
from soundboard.audio import soundfx
from soundboard.online import net
from soundboard.sounds import (
    catswitch,
    library,
    packs,
)
from soundboard.i18n import _, ngettext
from soundboard.sounds.library import (
    PAD_COLORS,
    SoundMeta,
)
from soundboard.ui.window.controller import Controller
from soundboard.ui.kit import busy
from soundboard.ui.kit.crashdialog import free_dialog
from soundboard.ui.kit.plaintext import plain_tip   # (pack names come from the pack)

log = logging.getLogger("soundboard.ui.window.importcontrol")

PACK_SAMPLE = "__pack_sample"   # Free packs' "hear it first" voice (headphones only)


def pack_tab_name(name: str) -> str:
    """A pack's tab: its name without a trailing "pack" ("Streamer pack" → "Streamer",
    "GM starter pack" → "GM starter"), first letter capital."""
    tab = re.sub(r"(?i)[\s_-]*\bpack\s*$", "", name.strip()).strip() or name.strip()
    return tab[:1].upper() + tab[1:]


# a plain, empty class at run time (ImportControl itself is the Controller)
_Ctl = Controller if TYPE_CHECKING else object


class PackImport(_Ctl):
    """ImportControl's sound packs (a mixin)."""

    if TYPE_CHECKING:   # ImportControl's own, for the type checker
        from PySide6.QtCore import Signal

        from soundboard import otherboards
        def import_files(self, files,
                         extras: dict[str, otherboards.Entry] | None = ...) -> None: ...
        def _on_worker(self, work, then, name: str) -> None: ...
        _packs_removed: set[str]
        _packs_page: QDialog | None
        _packs_watch: object
        _pack_refetched: Signal
        _pack_came: Signal
        _pack_retries: set[str]
        _pack_early: dict[str, dict[str, str]]
        # (BackupImport's)
        def _on_unpacked(self, res, pkg, err: str) -> None: ...

    def show_packs(self):
        """The Free packs page (soundboard.sounds.packs), in the tabs' place as Settings
        is (the rail, player and mixer stay): a pack it downloads is imported the way
        dropping its zip on the window is. [Done], Escape, a tab on the rail or Settings
        go back."""
        mw = self.mw
        from soundboard.ui.sounds.packsdialog import PacksDialog
        if self.packs_open():
            return
        usage.used("packs-opened")
        if mw.bunctl.bun_up():   # the window comes back first (as Settings does)
            mw.bunctl.leave_bun_mode(False)
        mw.setctl.close_settings()
        # it belongs to the Sounds tab (opened from its Backup menu): that tab is the one
        # lit on the rail, and picking it (or any tab) goes back
        mw.tabs.setCurrentWidget(mw.sounds_page)
        dlg = PacksDialog(self._pack_got, mw, play=self._pack_sample,
                          try_later=self._pack_try_later, add_some=self._pack_some)
        dlg.setWindowFlags(Qt.WindowType.Widget)
        self._packs_page = dlg
        dlg.finished.connect(lambda _r, d=dlg: self._packs_closed(d))
        mw._content.addWidget(dlg)
        mw._content.setCurrentWidget(dlg)
        # anything else put in its place (Settings): it closes
        self._packs_watch = mw._content.currentChanged.connect(
            lambda _i, d=dlg: self._packs_left(d))
        mw.fitctl._fit_body_top()
        setctl = mw.setctl
        setctl._opening_settings = True   # (fitcontrol: not closed again for being small)
        try:
            setctl._board_counts(False)
            if mw.fitctl.is_mini():
                setctl._grow_for_settings()
        finally:
            setctl._opening_settings = False
        mw.transctl._show_transport()
        dlg.search.setFocus(Qt.FocusReason.OtherFocusReason)
        return dlg

    def packs_open(self) -> bool:
        dlg = self._packs_page
        return dlg is not None and qt_valid(dlg)

    def close_packs(self):
        """Back from Free packs to the tabs, as [Done] does."""
        dlg = self._packs_page
        if dlg is not None and qt_valid(dlg):
            dlg.accept()

    def _packs_left(self, dlg):
        if qt_valid(dlg) and self.mw._content.currentWidget() is not dlg and not dlg._closed:
            dlg.reject()

    def _packs_closed(self, dlg):
        mw = self.mw
        if self._packs_page is dlg:
            self._packs_page = None
            mw._content.currentChanged.disconnect(self._packs_watch)
        had_focus = dlg.isAncestorOf(mw.focusWidget()) if mw.focusWidget() else False
        if mw._content.currentWidget() is dlg:
            mw._content.setCurrentWidget(mw._tabs_area)
        mw._content.removeWidget(dlg)
        mw.fitctl._fit_body_top()
        if not mw.setctl.settings_open():
            mw.setctl._board_counts(True)
        mw.transctl._show_transport()
        if had_focus and not mw.setctl.settings_open():
            mw._focus_sounds_page(mw.tabs.currentIndex())
        # freed once its finished signal is over (deleting it inside that crashed)
        QTimer.singleShot(0, lambda: free_dialog(dlg))

    def _pack_got(self, path):
        """A free pack downloaded (packs/<its id>.zip): imported like a dropped zip."""
        usage.used(f"pack-added-{usage.pack_tag(Path(path).stem)}")
        self.import_files([str(path)])

    def _pack_some(self, p: packs.Pack, zips: list[Path], done):
        """Some of links pack `p`'s sounds, as they came (a zip of one sound each): on
        the board now, in the pack's tab, not when all of it has come. Quiet: the whole
        pack's import says what came, and makes these its own. done() once they're on."""
        mw = self.mw
        start = len(mw.cfg.sounds)

        def run():   # copying them into the library: on its own thread
            got = []
            for z in zips:
                try:
                    pkg = backup.read(z)
                    res = backup.install(pkg, set(), lambda _i, n=len(got): PAD_COLORS[
                        (start + n) % len(PAD_COLORS)])
                    for m in res.sounds:
                        m.pack_item = pkg.sounds[0].folder
                        got.append(m)
                except Exception:  # noqa: BLE001 - it comes with the whole pack then
                    log.info("pack %s: couldn't put %s on the board yet", p.id, z.name,
                             exc_info=True)
                finally:
                    z.unlink(missing_ok=True)
            busy.emit(self._pack_came, lambda found: self._put_early(p, found, done), got,
                      owner=self)
        threading.Thread(target=run, daemon=True, name="pack-came").start()

    def _put_early(self, p: packs.Pack, got: list[SoundMeta], done):
        mw = self.mw
        try:
            if not got or mw._shut_down:
                return
            from soundboard.sounds.library import merge_tags
            cats = list(dict.fromkeys(k.category for k in p.links if k.category))
            tab = pack_tab_name(p.name)
            # as the whole pack's import does: several categories go in one tab
            if len({library.split_tag(c)[0].lower() for c in cats}) > 1:
                library.group_pack_tags(got, tab)
                cats = [tab] + [library.sub_tag(tab, c) for c in cats
                                if not library.split_tag(c)[1] and c.lower() != tab.lower()]
            early = self._pack_early.setdefault(p.id, {})
            for m in sorted(got, key=lambda m: m.pack_item):
                m.tags = merge_tags(m.tags, mw.cfg.categories, mw.cfg.subcategories)
                # in the pack's order: after the last of its sounds before it in the
                # list, else before the first after it, else on the end
                came = [(i, early[o.id]) for i, o in enumerate(mw.cfg.sounds)
                        if o.id in early]
                before = [i for i, f in came if f < m.pack_item]
                at = (before[-1] + 1 if before else came[0][0] if came
                      else len(mw.cfg.sounds))
                mw.cfg.sounds.insert(at, m)
                early[m.id] = m.pack_item
            merge_tags(cats, mw.cfg.categories, mw.cfg.subcategories)
            mw._save_now()
            mw._rebuild_pads()
            mw.catctl._fill_categories()
            mw.soundctl._load_all()
            mw.statusctl._update_status()
        finally:
            done()

    def _pack_try_later(self, p: packs.Pack):
        """Some (or all) of links pack `p`'s sounds failed for now, after all their tries
        (no connection, Myinstants down or busy): asked for again by themselves
        packs.LINK_TRY_LATER after, and again after that while they keep failing, for as
        long as the app runs. What's on the board already is skipped by the import."""
        if p.id in self._pack_retries:
            return
        self._pack_retries.add(p.id)
        log.info("pack %s: asking for its missing sounds again in %d s", p.id,
                 packs.LINK_TRY_LATER)
        QTimer.singleShot(packs.LINK_TRY_LATER * 1000, self.mw, lambda: self._pack_retry(p))

    def _pack_retry(self, p: packs.Pack):
        self._pack_retries.discard(p.id)
        if not net.allowed(packs.FEATURE):   # Offline mode meanwhile: the next time
            self._pack_try_later(p)
            return

        def run():   # quiet, on its own thread: no busy cursor for minutes
            try:
                got, err = packs.download_links(p, again=True), None
            except Exception as e:  # noqa: BLE001 - said (or tried again) on the UI thread
                got, err = None, e
            busy.emit(self._pack_refetched, p, got, err, owner=self)
        threading.Thread(target=run, daemon=True, name="pack-retry").start()

    def _pack_retried(self, p: packs.Pack, got, err):
        if isinstance(err, packs.TryLater):
            self._pack_try_later(p)
            return
        if err is not None:
            log.info("pack %s: asked again, still failed: %s", p.id, err)
            return
        path, _skipped, later = got
        self._pack_got(path)   # the board's own import says what came
        if later:
            self._pack_try_later(p)

    def _pack_sample(self, data, gain: float) -> bool:
        """Free packs' samples: to your headphones only (None stops it). False: no
        headphones to play them on."""
        mw = self.mw
        if data is None:
            mw.engine.stop(PACK_SAMPLE)
            return True
        usage.used("pack-heard")
        return mw.engine.play(PACK_SAMPLE, data, gain, mode="restart",
                                preview=True) is not None

    def _pack_name(self, pkg) -> str:
        return backup.packs().get(pkg.pack_id) or Path(pkg.path).name

    def _pack_tab(self, pkg) -> str:
        """The one tab a pack goes into: its name without "pack" ("Streamer pack" →
        "Streamer")."""
        return pack_tab_name(self._pack_name(pkg))

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
        from soundboard.sounds import packs
        p = packs.known(pid)
        return {c.lower() for c in p.categories} if p else set()

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
                plain_tip(_("Make one “{name}” tab, with {n} of its categories inside it as "
                            "subcategories instead of tabs of their own?\n\nNo sound is "
                            "removed or changed.", name=name, n=len(own))),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
                ) != QMessageBox.StandardButton.Yes:
            return
        mine = [m for m in mw.soundctl._live_metas() if m.pack == pid]
        library.group_pack_tags(mine, pack_tab_name(name), own)
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
                if c in mw.cfg.hidden_from_all:
                    mw.cfg.hidden_from_all.remove(c)
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
                plain_tip(_("Put the sounds from “{name}” back how they came?\n\nChanges you "
                            "made to them (names, hotkeys, volume, effects, pictures…) are "
                            "undone, and ones you removed come back. Your other sounds aren't "
                            "touched.", name=name)),
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
                plain_tip(ngettext("Remove the {n} sound from “{name}”?",
                                   "Remove the {n} sounds from “{name}”?", len(gone), name=name)
                          + "\n\n"
                          + _("You can undo this, or bring them back from Recently deleted.")),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
                ) != QMessageBox.StandardButton.Yes:
            return
        mw.rmctl.remove_sounds(gone)
        self._packs_removed.add(pid)
