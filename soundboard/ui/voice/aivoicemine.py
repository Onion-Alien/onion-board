"""The AI voices card's own voices and voice settings: making, editing and deleting your
voices (with Undo), pitch, the backup voice. Mixed into AiVoicePanel (aivoicepanel.py)."""
from __future__ import annotations

import html
from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import QDialog, QWidget

from soundboard.core import usage
from soundboard.i18n import _, ngettext
from soundboard.speech import aivoicelist as avl
from soundboard.ui.kit import busy
from soundboard.ui.voice.aivoicebrowser import AiVoiceEditor

if TYPE_CHECKING:
    class _Panel(QWidget):
        # what AiVoicePanel itself provides, for the type checker only
        def __getattr__(self, name: str) -> Any: ...
else:
    _Panel = object


class AiVoiceMine(_Panel):
    """AiVoicePanel's own voices, pitch and backup voice."""

    # ------------------------------------------------------------ your own voices
    def can_make(self) -> bool:
        """Any copy of the add-on: the one you downloaded gets your voices written into
        its voices.json, one shipped with the app reads them from your file."""
        return self.module is not None

    def _play_sample(self, data):
        assert self.engine is not None   # only offered with one
        self.engine.play("__ai_voice_sample", data, 1.0, preview=True)

    def edit(self, vid: str | None):
        """Make one of your own voices (None) or change one."""
        if not self.can_make():
            return
        if vid is None and self.store.full():
            busy.toast(self, html.escape(ngettext(
                "⚠ You have {n} voice of your own already: delete it to make another.",
                "⚠ You have {n} voices of your own already: delete one to make another.",
                avl.MAX_VOICES).removeprefix("⚠ ")), "warn")
            return
        built = [vo for vo in self.voices if not avl.is_mine(vo)]
        # on the window, not this card: the card's styles would reach into the dialog
        d = AiVoiceEditor(built, self.store.get(vid) if vid else None, self.previewer,
                          self.window())
        if d.exec() == QDialog.DialogCode.Accepted and self.store.put(d.result_voice()) is not None:
            self._resync()
            if vid is None:
                usage.used("ai-voice-made")
                self.pick(d.result_voice()["id"])

    def delete(self, vid: str):
        item = self.store.remove(vid)
        if item is None:
            return
        self._resync()
        self.undo_bar.show_for(_("Deleted “{name}”", name=item.name),
                               lambda: self._undo(item.id))

    def _undo(self, item_id: str):
        it = self.store.take(item_id)
        if it is not None and self.store.restore(it) is not None:
            self._resync()

    def show_deleted(self):
        from soundboard.ui.sounds.deleted import DeletedDialog
        self.undo_bar.finish()

        def back(item) -> bool:
            return self.store.restore(item) is not None
        DeletedDialog(avl.KIND, "voices", back, self, source=self.store).exec()
        self._resync()

    def _auto_toggled(self, on: bool):
        self.s["auto_pitch"] = on
        self.ctl.set_auto_pitch(on)
        self._emit()

    def _show_pitch(self):
        st = self.sl_pitch.value() / 2
        self.lbl_pitch.setText("0" if st == 0 else f"{st:+g}")

    def _pitch_moved(self, _v):
        self._show_pitch()
        if not self.sl_pitch.isSliderDown():
            self._pitch_released()

    def _pitch_released(self):
        st = self.sl_pitch.value() / 2
        if st != self.s["pitch"]:
            self.s["pitch"] = st
            if self.ctl.running:
                self.ctl.set_voice(self.s["voice"], st)
            self._emit()

    def _backup_picked(self, *_):
        self.s["backup"] = self.cb_backup.currentData() or "voice"
        self.ctl.set_backup(self.s["backup"])
        if self.status() == "failed":
            self._state(self.failure_text(getattr(self, "_failure_error", "")))
        elif self.status() == "starting":
            self._state(self._starting_text())
        self._emit()
