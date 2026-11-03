"""An AI voice's Edit voice: the voice changer's Edit voice window (VoiceFxPanel), with
the AI voice's pitch on top of Main, editing that AI voice's own effects. They run on
the AI voice's audio before the voice changer's (VoiceChain.source_fx), so an AI voice
can be made deeper, given a choir, and so on, with the voice changer on top as well.

Each AI voice keeps its own: the Voice tab saves them in the speech settings under
"ai_fx" ({voice id: {type: {"on": True, ...}}}), beside "ai" (which an older version
cleans down to the fields it knows) so an older version keeps them as they are.

Only the window is used: the panel itself (its voice cards) is never shown."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from soundboard import voicefx
from soundboard.i18n import _
from soundboard.mic import savedvoices
from soundboard.ui.kit import icons
from soundboard.ui.voice.effectrow import EffectRow
from soundboard.ui.voice.voicefxpanel import DLG_ART, VoiceFxPanel
from soundboard.ui.voice.voicetiles import CUSTOM


def clean_all(raw) -> dict[str, dict]:
    """Saved "ai_fx" ({voice id: effects}) with each voice's effects cleaned
    (voicefx.clean_spec) and the ones switched off left out; damaged entries dropped."""
    out = {}
    for vid, effects in (raw.items() if isinstance(raw, dict) else ()):
        if isinstance(vid, str) and vid and isinstance(effects, dict):
            on = only_on(voicefx.clean_spec({"effects": effects})["effects"])
            if on:
                out[vid] = on
    return out


def only_on(effects: dict) -> dict:
    """The effects that are on, without the ones on top of the voice (the Background
    and the Effects pop-up's: the voice changer's, for every voice)."""
    return {t: dict(c) for t, c in effects.items()
            if isinstance(c, dict) and c.get("on") and not voicefx.on_top(t)}


def chain_spec(effects: dict) -> dict:
    """A VoiceChain spec for an AI voice's own effects ({} when it has none)."""
    return {"enabled": True, "effects": effects} if effects else {}


class AiVoiceFx(VoiceFxPanel):
    """Edit voice for the AI voice that's picked (`bind`). `effects_changed(id,
    effects)`: that voice's own effects (only_on), after each change."""
    effects_changed = Signal(str, dict)
    voice_saved = Signal()   # Save as a voice: the voice changer's cards show it

    def __init__(self, parent: QWidget, pitch_box: QWidget, store: savedvoices.Store):
        self._vid = ""
        self._name = ""
        self._pic: QIcon | None = None
        self._ai_latency_ms = 0.0
        self._binding = False   # bind() loading a voice's effects: nothing changed
        super().__init__({"enabled": True, "preset": CUSTOM}, store)
        self.setParent(parent)   # (its window then belongs to the app's)
        self.hide()
        self.main_hint.setText(_("Switch effects on and drag their sliders to change how this "
                                 "AI voice sounds. Each AI voice keeps its own."))
        # the AI voice's own pitch, first on Main, in a card like the effects' (headed
        # AI voice: it isn't the Pitch & voice effect under it)
        box = QFrame()
        box.setObjectName("fxcard")
        bv = QVBoxLayout(box)
        bv.setContentsMargins(14, 12, 14, 12)
        bv.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(8)
        icon = QLabel()
        icons.set_label_icon(icon, "wave", "accent_hi", size=16)
        icon.setObjectName("fxicon")
        head.addWidget(icon)
        title = QLabel(_("AI voice"))
        title.setObjectName("fxname")
        head.addWidget(title)
        head.addStretch(1)
        bv.addLayout(head)
        bv.addWidget(pitch_box)
        pitch_box.show()
        self.hero_box.insertWidget(0, box)

    def bind(self, vid: str, name: str, pic: QIcon | None, effects: dict):
        """Show this AI voice's own effects: Reset goes back to the voice with none."""
        self._vid, self._name, self._pic = vid, name, pic
        self._preset, self._own, self._based_on, self._custom = CUSTOM, True, "", {}
        self._clear_fresh()
        self._restoring = self._binding = True
        try:
            for r in self.rows.values():
                r.load(None)
            self._mark_start()
            for t, r in self.rows.items():
                r.load(effects.get(t))
        finally:
            self._restoring = self._binding = False
        self._record()
        self._refresh()

    @property
    def voice_id(self) -> str:
        return self._vid

    def set_ai_latency(self, seconds: float):
        """The AI voice's own delay, counted in the window's delay."""
        self._ai_latency_ms = max(0.0, seconds * 1000.0)
        self._show_delay()

    def effects_delay(self) -> float:
        return super().effects_delay() + self._ai_latency_ms

    def _ordered_cards(self) -> list[tuple[str, list[EffectRow]]]:
        # what's on top of the voice (the Background) is the voice changer's, for every
        # voice: not here
        top = {r for t, r in self.rows.items() if voicefx.on_top(t)}
        for r in top:
            if r.parentWidget() is None:
                r.setParent(self)   # (never a window of its own)
            r.hide()
        return [(title, [c for c in cards if c not in top])
                for title, cards in super()._ordered_cards()]

    def _show_edit_state(self):
        super()._show_edit_state()
        if not hasattr(self, "_start") or not self._name:
            return
        edited = self.edited_since_start()
        self.dlg_name.setText(_("{voice}, changed", voice=self._name) if edited
                              else self._name)
        if self._pic is not None:
            self.dlg_pic.setPixmap(self._pic.pixmap(DLG_ART, DLG_ART))
        tip = _("Back to “{voice}” as it was when you picked it", voice=self._name)
        self.btn_reset.setToolTip(tip)
        self.btn_reset.setAccessibleName(tip)

    def _emit(self):
        super()._emit()
        if self._vid and not self._binding:
            self.effects_changed.emit(self._vid, only_on(self.spec()["effects"]))

    def save_voice(self):
        super().save_voice()
        self.voice_saved.emit()
