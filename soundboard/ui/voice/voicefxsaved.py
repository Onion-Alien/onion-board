"""Part of the voice changer (ui/voice/voicefxpanel.py `VoiceFxPanel`): your saved voices:
naming, saving, renaming and deleting them (with undo and Recently deleted), a tile's menu, and
sharing them as codes."""
from __future__ import annotations

import html
import uuid
from typing import TYPE_CHECKING

from PySide6.QtGui import QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import QMenu, QWidget

from soundboard import voicefx
from soundboard.core import usage
from soundboard.i18n import _, ngettext
from soundboard.mic import savedvoices
from soundboard.online import net
from soundboard.ui.kit import busy, icons, modalframe
from soundboard.ui.voice import art, voicepics
from soundboard.ui.voice.aivoicebrowser import HEAR
from soundboard.ui.voice.voicetiles import CUSTOM

if TYPE_CHECKING:
    from typing import Any

    _Base = QWidget
else:
    _Base = object


class VoiceFxSaved(_Base):
    if TYPE_CHECKING:   # what VoiceFxPanel has that these use
        _based_on: Any
        _custom: Any
        _emit: Any
        _favs: Any
        _fill_saved: Any
        _mark_start: Any
        _mine: Any
        _own: Any
        _preset: Any
        _show_edit_state: Any
        _start: Any
        _show_picked: Any
        _tile: Any
        btn_import: Any
        btn_save: Any
        btn_share: Any
        dlg: Any
        edit_voice: Any
        hear: Any
        hotkey_asked: Any
        hotkey_cleared: Any
        keys: Any
        pick: Any
        play_sample: Any
        renamed: Any
        rows: Any
        share_asked: Any
        store: Any
        take_code: Any
        undo_bar: Any

    def _ask_name(self, title: str, text: str, keep: str = "") -> str:
        """A name for a saved voice, or "" if cancelled. Built-in voices' names are
        taken; so is another saved voice's, unless you agree to replace it (`keep` is
        the voice being renamed, whose own name is fine)."""
        builtin = self._builtin_names()
        while True:
            name = savedvoices.clean_name(modalframe.ask_text(
                self._parent(), title, _("Name"), text, max_len=savedvoices.MAX_NAME) or "")
            if not name:
                return ""
            if name.casefold() in builtin:
                modalframe.notice(self._parent(), title,
                                  _("“{name}” is a built-in voice's name. "
                                    "Pick another one.", name=name))
                text = name
                continue
            other = self.store.find(name)
            if other is None or other == keep:
                return name
            if modalframe.confirm(self._parent(), title,   # (a name from a backup too)
                                  _("You already have a voice called “{name}”. "
                                    "Replace it?", name=other),
                                  _("Replace"), danger=True):
                return other
            text = name

    def save_voice(self):
        """Fine-tune's "Save as a voice": what's in Fine-tune now, under a name, as a
        tile of its own (picked straight away)."""
        suggestion = self._based_on or self.store.free_name(_("My voice"))
        if self.store.full() and self.store.find(suggestion) is None:
            busy.toast(self._parent(), html.escape(self._full_text()), "warn", 8000)
            return
        name = self._ask_name(_("Save as a voice"), suggestion)
        if not name:
            return
        effects = {t: r.state() for t, r in self.rows.items()}
        if self._mine():
            self._custom = effects   # "My own mix" stays what it was too
        name = self.store.put(name, effects)
        usage.used("voice-saved")   # the name only (usage.py), never the voice's
        self._preset, self._own, self._based_on = name, False, name
        self._make_back = None   # saved: it stays on when Edit voice closes
        self._fill_saved()
        self._mark_start()   # Reset now goes back to the voice as saved
        self._emit()
        busy.flash(self.btn_save, _("✓ Saved"))
        # the flash is gone in a second: the card says it stuck, and under what name
        busy.toast(self._parent(), html.escape(_("Saved “{name}”.", name=name)), "ok")

    def saved_icon(self, name: str) -> QIcon | None:
        """A saved voice's card picture: the one you picked, else My own mix's."""
        pic = self.store.picture(name)
        return (art.file_icon(pic) if pic else None) or art.icon(art.voice_key(CUSTOM))

    def saved_pixmap(self, name: str, size: int) -> QPixmap | None:
        pic = self.store.picture(name)
        return (art.file_pixmap(pic, size) if pic else None) or \
            art.pixmap(art.voice_key(CUSTOM), size)

    def change_picture(self, name: str):
        """Pick a picture for a saved voice (one of the app's, a file or a pasted one)."""
        if name not in self.store.voices:
            return
        ok, img = voicepics.ask(self._parent())
        if not ok:
            return
        pic = ""
        if img is not None:
            pic = uuid.uuid4().hex[:12]   # a new file each time: the bin's copy keeps its own
            if not voicepics.write(img, savedvoices.picture_path(pic)):
                busy.toast(self._parent(), html.escape(_("Couldn't save that picture.")),
                           "warn")
                return
        self.store.set_picture(name, pic)
        self._fill_saved()
        self._show_edit_state()
        self._show_picked()

    def _dlg_pic_clicked(self):
        """Edit voice's picture: change it, for a saved voice."""
        base = getattr(self, "_start", {}).get("preset", "")
        if base in self.store.voices:
            self.change_picture(base)

    def voice_names(self) -> set[str]:
        """The voices a hotkey can pick: the ready ones and your saved ones."""
        return {n for n in self._tile if n != CUSTOM}

    def saved_names(self) -> list[str]:
        return list(self.store.voices)

    def title_of(self, name: str) -> str:
        """What a voice's card calls it."""
        return voicefx.shown(name) if name in voicefx.PRESETS else name

    def _tile_menu(self, name: str, at):
        """A voice card's right-click menu: Hear it, Edit voice, its hotkey, and for a
        saved voice rename, share and delete."""
        from soundboard.ui.kit.hotkeypick import pretty_key
        m = QMenu(self)
        if self.play_sample is not None:
            m.addAction(icons.icon("headphones"), HEAR, lambda: self.hear(name))
            m.addSeparator()
        m.addAction(icons.icon("sliders"), _("Edit voice…"), lambda: self.edit_voice(name))
        key = self.keys.get(name, "")
        m.addAction(icons.icon("keyboard"),
                    _("Hotkey: {key}…", key=pretty_key(key)) if key else _("Set a hotkey…"),
                    lambda: self.hotkey_asked.emit(name))
        if key:
            m.addAction(icons.icon("close"), _("Clear hotkey"),
                        lambda: self.hotkey_cleared.emit(name))
        if name in self.store.voices:
            m.addSeparator()
            m.addAction(icons.icon("edit"), _("Rename"), lambda: self.rename_voice(name))
            m.addAction(icons.icon("image"), _("Change picture…"),
                        lambda: self.change_picture(name))
            m.addAction(icons.icon("copy"), _("Copy share code"), lambda: self.copy_code(name))
            if not net.offline():
                m.addAction(icons.icon("upload"), _("Share to the store…"),
                            lambda: self.share_asked.emit(name))
            m.addAction(icons.icon("trash", "danger_text"), _("Delete"),
                        lambda: self.delete_voice(name))
        m.exec(at)

    @staticmethod
    def _full_text() -> str:
        return ngettext("You have {n} saved voice, the most there can be. Delete one "
                        "(right-click it) first.",
                        "You have {n} saved voices, the most there can be. Delete one "
                        "(right-click it) first.", savedvoices.MAX_VOICES)

    def _parent(self) -> QWidget:
        """Where a question goes: over Edit voice while it's open."""
        return self.dlg if self.dlg.isVisible() else self

    def copy_code(self, name: str) -> str:
        """A saved voice as a share code, onto the clipboard. Returns the code."""
        effects = self.store.voices.get(name)
        if effects is None:
            return ""
        code = savedvoices.share_code(name, effects)
        QGuiApplication.clipboard().setText(code)
        usage.used("voice-code-shared")
        if self.dlg.isVisible() and name == self._preset:
            busy.flash(self.btn_share, _("✓ Copied"))
        else:
            self.undo_bar.finish()
            self._note(_("Copied “{name}” as a share code", name=name))
        return code

    def _note(self, text: str):
        """A short result, as a corner card."""
        busy.toast(self._parent(), html.escape(text), "ok")

    def import_code(self, text: str | None = None) -> str:
        """Add a voice from a share code (asked for if not given) as a new saved voice,
        renamed if the name's taken, and turn it on; a code holding an AI voice or a
        setup goes to `take_code`. Returns the name it got ("" if none)."""
        title = _("Import a voice code")
        if text is None:
            text = modalframe.ask_text(self._parent(), title,
                                       _("Paste the code someone sent you:"),
                                       verb=_("Import"))
            if text is None:
                return ""
        from soundboard.online import storevoices
        try:
            v, notes = storevoices.read_code(text)
        except savedvoices.CodeError as e:
            busy.toast(self._parent(), html.escape(str(e)), "warn")
            return ""
        if v.kind != "fx":
            return self.take_code(v, notes) if self.take_code is not None else ""
        name, effects = v.name, v.effects
        if self.store.full():
            busy.toast(self._parent(), html.escape(self._full_text()), "warn", 8000)
            return ""
        if name.casefold() in self._builtin_names():
            name = f"{name[:savedvoices.MAX_NAME - 9]} (shared)"
        name = self.store.free_name(name)
        on = [voicefx.shown(voicefx.REGISTRY[t].name) for t in effects]
        ask = (_("Add the voice “{name}”?<br><br>Effects: {effects}", name=html.escape(name),
                 effects=(html.escape(", ".join(on)) if on
                          else _("none (your normal voice)")))
               + "".join(f"<br><br>{html.escape(n)}" for n in notes))
        if not modalframe.confirm(self._parent(), title, ask, _("Add"), rich=True):
            return ""
        name = self.store.put(name, effects)
        usage.used("voice-code-imported")
        self._fill_saved()
        self.pick(name)
        if self.dlg.isVisible():
            busy.flash(self.btn_import, _("✓ Added"))
        else:   # nothing else would say it worked
            busy.toast(self._parent(), _("Added the voice “{name}”", name=html.escape(name)),
                       "ok")
        return name

    @staticmethod
    def _builtin_names() -> set[str]:
        return savedvoices.builtin_names()

    def rename_voice(self, old: str):
        new = self._ask_name(_("Rename voice"), old, keep=old)
        if not new or new == old:
            return
        if self.store.find(new) not in (None, old):
            self.store.remove(new)   # agreed to replace it (it goes to the bin)
            if self._preset == new:
                self._preset = CUSTOM
        new = self.store.rename(old, new)
        if not new:
            return
        if self._preset == old:
            self._preset = new
        if self._based_on == old:
            self._based_on = new
        self._favs = [new if n == old else n for n in self._favs]
        self._fill_saved()
        self.renamed.emit(old, new)
        self._emit()

    def delete_voice(self, name: str):
        """Into the bin (Undo for a few seconds, "Recently deleted" for a month).
        If it was on, the voice you hear doesn't change: it shows as "My own mix"."""
        item = self.store.remove(name)
        if item is None:
            return
        was_on = self._preset == name
        if was_on:
            self._preset = CUSTOM
        if self._based_on == name:
            self._based_on = ""
        self._fill_saved()
        self._emit()
        self.undo_bar.show_for(_("Deleted the voice “{name}”", name=name),
                               lambda: self._undelete(item.id, was_on))

    def _undelete(self, item_id: str, was_on: bool = False) -> str:
        item = self.store.take(item_id)
        if item is None:
            return ""
        name = self.store.restore(item, item.index)
        # still sounding just like it (nothing touched since): it's the one that's on
        if was_on and self._preset == CUSTOM and \
                {t: r.state() for t, r in self.rows.items()} == self.store.voices[name]:
            self._preset = name
        self._fill_saved()
        self._emit()
        return name

    def show_deleted(self):
        from soundboard.ui.sounds.deleted import DeletedDialog
        self.undo_bar.finish()

        def back(item) -> bool:   # DeletedDialog has taken it out of the bin already
            self.store.restore(item, item.index)   # in its old place, as Undo does
            self._fill_saved()
            self._emit()
            return True
        DeletedDialog(savedvoices.VOICE, "voices", back, self, source=self.store).exec()
        self._fill_saved()

    def merge_saved(self, raw) -> int:
        """Add a backup's saved voices (the ones not here by name). Returns how many."""
        added = self.store.merge(raw)
        if added:
            self._fill_saved()
        return added
