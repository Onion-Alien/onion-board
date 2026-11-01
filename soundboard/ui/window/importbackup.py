"""Backups in the main window: exporting the board, a category or some sounds to a backup
(soundboard/core/backup.py), and importing one: its sounds, settings and hotkeys.
A mixin of ImportControl (importcontrol.py), which owns the window's bridge signals."""
from __future__ import annotations

import copy
import html
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QFileDialog, QMessageBox

from soundboard.core import (
    achievements,
    backup,
    errors,
)
from soundboard.sounds import (
    library,
)
from soundboard.i18n import _, ngettext
from soundboard.sounds.library import (
    PAD_COLORS,
    SoundMeta,
    clean_tags,
)
from soundboard.ui.kit.hotkeypick import HOTKEY_ACTIONS, pretty_key
from soundboard.ui.kit import worker
from soundboard.ui.sounds import importreport
from soundboard.ui.window import taboff
from soundboard.ui.window.controller import Controller
from soundboard.ui.kit.crashdialog import free_dialog

log = logging.getLogger("soundboard.ui.window.importcontrol")

# a plain, empty class at run time (ImportControl itself is the Controller)
_Ctl = Controller if TYPE_CHECKING else object


class BackupImport(_Ctl):
    """ImportControl's backups: export and import (a mixin)."""

    if TYPE_CHECKING:   # ImportControl's own, for the type checker
        from soundboard import otherboards
        def import_files(self, files,
                         extras: dict[str, otherboards.Entry] | None = ...) -> None: ...
        def _on_worker(self, work, then, name: str) -> None: ...
        def _show_skipped(self, skipped) -> None: ...
        _pack_early: dict[str, dict[str, str]]
        # (PackImport's)
        def _pack_name(self, pkg) -> str: ...
        def _pack_tab(self, pkg) -> str: ...
        def _pack_spot(self, m: SoundMeta, order: list[str]) -> int: ...

    # Export / import: see soundboard/core/backup.py and docs/BACKUP-FORMAT.md. The file
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
        achievements.at_least("backup", 1)   # (Backup Plan)
        msg = (ngettext("Exported {n} sound to {name}.",
                        "Exported {n} sounds to {name}.",
                        n, name=html.escape(Path(path).name)))
        if skipped:
            msg += " " + ngettext("{n} sound couldn't be read and was left out.",
                                  "{n} sounds couldn't be read and were left out.", skipped)
        mw.toast(msg, "warn" if skipped else "ok")

    def import_dialog(self):
        mw = self.mw
        files, __ = QFileDialog.getOpenFileNames(
            mw, _("Import a backup, sound pack or zip of sounds"), str(Path.home()),
            _("Zip file (*.zip)"))
        if files:
            self.import_files(files)   # a plain zip of sounds is imported too

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
        if Path(path).parent.resolve() == backup.packs_dir().resolve():
            # a free pack's download: its sounds that went on the board as they came
            pkg.came_first = self._pack_early.pop(Path(path).stem, {})
        start = len(mw.cfg.sounds)
        mw.toast(ngettext("Importing {n} sound…", "Importing {n} sounds…", len(pkg.sounds)))

        def run():
            new = ""
            if pkg.is_pack:   # kept, so it can be reset or removed in one go later
                before = set(backup.packs())
                new = backup.keep_pack(pkg)
                new = "" if new in before else new
                have.update((pkg.pack_id, f) for f in pkg.came_first.values())
            try:
                res = backup.install(
                    pkg, known, lambda i: PAD_COLORS[(start + i) % len(PAD_COLORS)], have)
            except BaseException:
                if new:   # refused (too big, no room): not kept, nor listed as kept
                    backup.forget_pack(new)
                raise
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
        from soundboard.sounds.library import merge_tags
        cats = pkg.categories
        if pkg.is_pack and len({library.split_tag(t)[0].lower() for ps in pkg.sounds
                                for t in clean_tags(ps.entry.get("tags"))}) > 1:
            # one tab for the pack, its categories inside it as subcategories
            tab = self._pack_tab(pkg)
            if library.group_pack_tags(res.sounds + pkg.restored, tab):
                # its list of categories too, or each one comes back as an empty tab
                cats = [tab] + [library.sub_tag(tab, c) for c in cats
                                if not library.split_tag(c)[1]
                                and c.lower() != tab.lower()]
        order = [ps.folder for ps in pkg.sounds]
        for m in pkg.restored + res.sounds:
            # "memes" goes into the "Memes" already here (and a new one gets a tab)
            m.tags = merge_tags(m.tags, mw.cfg.categories, mw.cfg.subcategories)
        for m in res.sounds:
            mw.cfg.sounds.insert(self._pack_spot(m, order), m)
        merge_tags(cats, mw.cfg.categories,   # a full backup's empty ones too
                   mw.cfg.subcategories)
        for m in pkg.restored:
            mw.engine.set_gain(m.id, mw.gain_for(m))
        early = pkg.came_first
        if early and pkg.pack_id:   # on the board already: the pack's own now
            for m in mw.cfg.sounds:
                if m.id in early and not m.pack:
                    m.pack, m.pack_item = pkg.pack_id, early[m.id]
        mw._save_now()
        mw._rebuild_pads()
        mw.catctl._fill_categories()
        mw.soundctl._load_all()
        mw.hkctl.register_hotkeys()
        n = len(res.sounds) + len(pkg.came_first)
        skipped_n = max(len(res.skipped) - len(pkg.came_first), 0)
        if pkg.restored:   # Backup → My sound packs → Reset to how it came
            msg = _("“{name}” is back how it came", name=self._pack_name(pkg))
            if n:
                msg += ngettext(" ({n} removed sound put back)",
                                " ({n} removed sounds put back)", n)
        elif skipped_n:
            msg = ngettext("Imported {n} sound ({skipped} already in your library)",
                           "Imported {n} sounds ({skipped} already in your library)", n,
                           skipped=skipped_n)
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
