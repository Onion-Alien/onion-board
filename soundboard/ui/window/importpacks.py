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
from PySide6.QtWidgets import QDialog, QMenu
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
from soundboard.ui.kit import busy, modalframe
from soundboard.ui.kit.crashdialog import free_dialog

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
        def import_package(self, path: str, free_id: str = ..., done=...) -> None: ...
        _packs_removed: set[str]
        _packs_page: QDialog | None
        _packs_watch: object
        _pack_came: Signal
        _pack_retries: dict[str, object]
        _pack_tries: dict[str, int]
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
                          try_later=self._pack_try_later, add_some=self._pack_some,
                          board=self)
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

    # the Free packs page's way to the board (packsdialog.PackBoard)
    def pack_on_board(self, p: packs.Pack) -> int:
        """How many of free pack `p`'s sounds are on the board."""
        pid = backup.free_pack_id(p.id)
        return sum(m.pack == pid for m in self.mw.cfg.sounds)

    def pack_adding(self, p: packs.Pack):
        """Add pressed on `p`. No need for its try by itself now, and if it was just removed
        that's final (Undo would bring a second copy back); its kept copy stays in use."""
        self._pack_retries.pop(p.id, None)
        self._pack_tries.pop(p.id, None)
        pid = backup.free_pack_id(p.id)
        if pid in self._packs_removed:
            self._packs_removed.discard(pid)
            self.mw.rmctl._finish_removals()

    def pack_remove(self, p: packs.Pack):
        self.remove_pack(backup.free_pack_id(p.id))

    def pack_import(self, p: packs.Pack, path: Path, done):
        """Free pack `p` came (all or some): onto the board. done() once that has ended."""
        usage.used(f"pack-added-{usage.pack_tag(p.id)}")
        self.import_package(str(path), p.id, done)

    def _packs_refresh(self):
        page = self._packs_page
        if page is not None and qt_valid(page):
            page.refresh()   # pyright: ignore[reportAttributeAccessIssue] - a PacksDialog

    def _pack_some(self, p: packs.Pack, zips: list[Path], done):
        """Some of links pack `p`'s sounds, as they came (a zip of one sound each): on
        the board now, in the pack's tab, not when all of it has come. Quiet: the whole
        pack's import says what came, and makes these its own. done() once they're on."""
        mw = self.mw
        start = len(mw.cfg.sounds)
        pid = backup.free_pack_id(p.id)   # theirs from the start: a crash leaves no orphans
        have = {m.pack_item for m in mw.cfg.sounds if m.pack == pid}

        def run():   # copying them into the library: on its own thread
            got = []
            for z in zips:
                try:
                    pkg = backup.read(z)
                    if pkg.sounds[0].folder in have:   # (came before this try stopped)
                        continue
                    res = backup.install(pkg, set(), lambda _i, n=len(got): PAD_COLORS[
                        (start + n) % len(PAD_COLORS)])
                    for m in res.sounds:
                        m.pack, m.pack_item = pid, pkg.sounds[0].folder
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
                # in the pack's order: after the last of its sounds before it in the
                # list, else before the first after it, else on the end
                came = [(i, o.pack_item) for i, o in enumerate(mw.cfg.sounds)
                        if o.pack == m.pack]
                if any(f == m.pack_item for _i, f in came):
                    continue   # never twice, whatever raced to put it here
                m.tags = merge_tags(m.tags, mw.cfg.categories, mw.cfg.subcategories)
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
        packs.LINK_TRY_LATER after, twice as long each time they keep failing (up to
        packs.LINK_TRY_LATER_MAX), for as long as the app runs. Only what's missing is
        asked for. Add pressed, or the pack removed, calls it off."""
        if p.id in self._pack_retries:
            return
        turn = object()
        self._pack_retries[p.id] = turn
        n = self._pack_tries.get(p.id, 0)
        self._pack_tries[p.id] = n + 1
        wait = min(packs.LINK_TRY_LATER << n, packs.LINK_TRY_LATER_MAX)
        log.info("pack %s: asking for its missing sounds again in %d s", p.id, wait)
        QTimer.singleShot(wait * 1000, self.mw, lambda: self._pack_retry(p, turn))

    def _pack_retry(self, p: packs.Pack, turn: object = None):
        if turn is not None and self._pack_retries.get(p.id) is not turn:
            return   # called off
        self._pack_retries.pop(p.id, None)
        if not net.allowed(packs.FEATURE):   # Offline mode meanwhile: the next time
            self._pack_try_later(p)
            return
        from soundboard.ui.sounds.packsdialog import downloads
        jobs = downloads()
        jobs.board = self   # (the page, which sets it, may never have been open since)
        # the one way onto the board, so it can't cross an Add pressed meanwhile
        if jobs.start(p, self._pack_got, self._pack_try_later, self.mw, self._pack_some,
                      quiet=True):
            self._packs_refresh()

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
        return (packs.name_of(pkg.free_id) or backup.packs().get(pkg.pack_id)
                or Path(pkg.path).name)

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
        p = packs.known(backup.free_id_of(pid) or pid)
        return {c.lower() for c in p.categories} if p else set()

    def _ungrouped_pack_sounds(self, pid: str) -> list[SoundMeta]:
        """Sounds of pack `pid` still in its categories as tabs of their own."""
        mw = self.mw
        name = packs.name_of(backup.free_id_of(pid)) or backup.packs().get(pid, pid)
        # (a category named like the pack's tab is that tab: nothing to put in it)
        own = self._pack_own_categories(pid) - {pack_tab_name(name).lower()}
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
        if not modalframe.confirm(
                mw, _("Put its categories in one tab"),
                _("Make one “{name}” tab, with {n} of its categories inside it as "
                  "subcategories instead of tabs of their own?\n\nNo sound is "
                  "removed or changed.", name=name, n=len(own)), _("Make one tab")):
            return
        mine = [m for m in mw.soundctl._live_metas() if m.pack == pid]
        library.group_pack_tags(mine, pack_tab_name(name), own)
        merge = library.merge_tags
        for m in mine:
            m.tags = merge(m.tags, mw.cfg.categories, mw.cfg.subcategories)
        self._drop_empty_tabs(own)   # the old tabs, once nothing is in them
        mw._save_now()
        mw.catctl._fill_categories()
        mw.searchctl.apply_filter(mw.search.text())
        mw.hkctl.register_hotkeys()
        mw.toast(_("✓ “{name}” is one tab now", name=html.escape(name)), "ok")

    def _drop_empty_tabs(self, names: set[str]):
        """The tabs named in `names` (lower case) that nothing is in, and nothing was set up
        for. The caller saves and redraws."""
        mw = self.mw
        live = mw.soundctl._live_metas()
        for c in list(mw.cfg.categories):
            if c.lower() in names and not any(c in m.tags for m in live) and not (
                    mw.cfg.category_hotkeys.get(c)
                    or catswitch.programs_for(mw.cfg.category_programs, c)):
                mw.cfg.categories.remove(c)
                mw.cfg.category_colors.pop(c, None)
                mw.cfg.subcategories.pop(c, None)
                if c in mw.cfg.hidden_from_all:
                    mw.cfg.hidden_from_all.remove(c)
        if mw.cfg.category not in mw.cfg.categories:
            mw.cfg.category = mw.cfg.subcategory = ""

    def tidy_free_packs(self):
        """Once per board: put right what older versions could leave behind when a free
        pack was added twice or only part of it came. Runs a moment after start-up."""
        mw = self.mw
        if mw.cfg.packs_tidied or mw._shut_down:
            return

        def run():
            try:
                moved = packs.tidy_kept()
            except Exception:  # noqa: BLE001 - tidying up must never hurt the running app
                log.warning("couldn't tidy the free packs", exc_info=True)
                return
            ids = {p.id: backup.free_pack_id(p.id)
                   for p in [*packs.built_in(), *packs._listed.values()]}
            kept = {i for i in ids if backup.kept_free_pack(i) is not None}
            busy.emit(self._pack_came, lambda found: self._tidied(*found), (moved, ids, kept),
                      owner=self)
        threading.Thread(target=run, daemon=True, name="pack-tidy").start()

    def _tidied(self, moved: dict[str, str], ids: dict[str, str], kept: set[str]):
        mw = self.mw
        if mw._shut_down or mw.cfg.packs_tidied:
            return
        mw.cfg.packs_tidied = 1
        sounds = mw.cfg.sounds
        for m in sounds:
            m.pack = moved.get(m.pack, m.pack)
        # sounds that went on the board as they came and were never made the pack's own
        # (the app closed, or the rest of the pack failed): by their place and name
        for free_id, pid in ids.items():
            p = packs.known(free_id)
            names = {packs.link_folder(i): k.name[:40]
                     for i, k in enumerate(p.links)} if p else {}
            for m in sounds:
                if not m.pack and names.get(m.pack_item) == m.name:
                    m.pack = pid
        seen, twice = set(), []
        for m in sounds:
            if m.pack and m.pack_item:
                if (m.pack, m.pack_item) in seen:
                    twice.append(m.id)
                seen.add((m.pack, m.pack_item))
        if twice:   # the first stays: to Recently deleted with these, so nothing's lost
            log.info("free packs: taking off %d sounds that were on the board twice", len(twice))
            mw.rmctl.remove_sounds(twice)
        on = {m.pack for m in sounds if m.pack}
        own: set[str] = set()
        for free_id, pid in ids.items():
            if free_id in kept or pid in on:
                own |= self._pack_own_categories(free_id)
        self._drop_empty_tabs(own)   # (the tabs an Add with nothing new used to leave)
        mw._save_now()
        mw.catctl._fill_categories()
        mw.searchctl.apply_filter(mw.search.text())

    def reset_pack(self, pid: str, ask: bool = True):
        """Put a sound pack back how it came: its sounds' names, hotkeys, volume,
        effects, categories and pictures, and its removed sounds come back.
        The pack is read, and its pictures put back, on a worker; this returns at once."""
        if self._pack_being_added(pid):
            return

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
        if ask and not modalframe.confirm(
                mw, _("Reset sound pack"),
                _("Put the sounds from “{name}” back how they came?\n\nChanges you "
                  "made to them (names, hotkeys, volume, effects, pictures…) are "
                  "undone, and ones you removed come back. Your other sounds aren't "
                  "touched.", name=name), _("Reset")):
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

    def _pack_being_added(self, pid: str) -> bool:
        """Free pack `pid` is on its way onto the board right now: said, and True."""
        from soundboard.ui.sounds.packsdialog import downloads
        if backup.free_id_of(pid) not in downloads().words:
            return False
        self.mw.toast(html.escape(_("Still adding that pack. Try again when it's done.")), "warn")
        return True

    def remove_pack(self, pid: str, ask: bool = True):
        """Take every sound of a sound pack off the board (one Undo brings them back);
        once the Undo bar is gone, the pack is no longer kept."""
        mw = self.mw
        gone = [m.id for m in mw.cfg.sounds if m.pack == pid]
        if not gone:
            return
        if self._pack_being_added(pid):   # it'd come straight back when that lands
            return
        from soundboard.ui.sounds.packsdialog import downloads
        free = backup.free_id_of(pid)
        name = backup.packs().get(pid, pid)
        if ask and not modalframe.confirm(
                mw, ngettext("Remove the {n} sound from “{name}”?",
                             "Remove the {n} sounds from “{name}”?", len(gone), name=name),
                _("You can undo this, or bring them back from Recently deleted."),
                _("Remove")):
            return
        mw.rmctl.remove_sounds(gone)
        self._packs_removed.add(pid)
        self._pack_retries.pop(free, None)   # (it isn't wanted any more)
        self._pack_tries.pop(free, None)
        downloads().failed.discard(free)
        self._packs_refresh()

    def _pack_tabs_gone(self, pids: list[str]) -> set[str]:
        """The tabs a pack brought (lower case), for once it's no longer on the board."""
        names: set[str] = set()
        for pid in pids:
            names |= self._pack_own_categories(pid)
            name = packs.name_of(backup.free_id_of(pid)) or backup.packs().get(pid)
            if name:
                names.add(pack_tab_name(name).lower())
        return names
