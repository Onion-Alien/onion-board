"""The Voice tab's on / off: the voice changer, AI voice and computer voice switched one
at a time or all together (with Undo), and the voice that's on saying the translated
lines. Mixed into VoicePanel (voicepanel.py)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import QWidget

from soundboard.core import usage
from soundboard import voicefx
from soundboard.speech import spoken
from soundboard.ui.voice.voicefxpanel import CUSTOM
from soundboard.i18n import _
from soundboard.ui.voice.voicecards import ORDER

if TYPE_CHECKING:
    class _Panel(QWidget):
        # what VoicePanel itself provides, for the type checker only
        def __getattr__(self, name: str) -> Any: ...
else:
    _Panel = object


class VoiceSwitch(_Panel):
    """VoicePanel's voices on and off."""

    def _fx_changed(self, spec: dict):
        if self.chain.errors:              # give a bypassed effect another go after an edit
            self.chain.errors.clear()      # (configure rebuilds; clear_errors() would twice)
        self.chain.configure(spec)
        self._update_backdrop(spec)
        self._ai_effects_text()
        self.fx.show_errors({})
        self.fx_changed.emit(spec)
        self._emit_active()

    def _update_backdrop(self, spec: dict):
        """Have the Background's loops made for these settings (a worker reads the board
        sounds from disk and renders them; nothing when it's off). They play on the AI
        voice too, with the voice changer off."""
        on = (spec.get("enabled") or self.ai.is_on()
              or self.speech.livevoice.b_live.isChecked())
        cfg = (spec.get("effects") or {}).get("backdrop") if on else None
        if cfg and cfg.get("on") and cfg.get("sounds"):
            metas = {m.id: m for m in self.board_sounds()}   # read here, on the UI thread
        else:
            metas = {}

        def load(sid: str):
            from soundboard.sounds import library
            m = metas.get(sid)
            return library.load_sound(m) if m is not None else None
        self.backdrop.update(cfg, load)

    def _ai_effects_text(self):
        """The other bars' Effects say what the voice changer's does (one list)."""
        text = self.fx.btn_effects.accessibleName() or _("Effects")
        for bar in (self.ai, self.speak_bar):
            b = bar.btn_effects
            if b.text() != text:
                b.setText(text)
                b.setAccessibleName(text)
                bar._fit_picked()

    def board_changed(self):
        """Sounds were added, renamed or deleted: the Background's names and loops again."""
        refresh = getattr(self.fx.rows.get("backdrop"), "refresh_names", None)
        if refresh is not None:
            refresh()
        self._update_backdrop(self.fx.spec())

    def _clean_changed(self, s: dict):
        self.speech.s["clean"] = s         # kept with the speech settings
        self.speech_changed.emit(dict(self.speech.s))

    def _ai_changed(self, s: dict):
        self.speech.s["ai"] = s            # kept with the speech settings
        self.speech_changed.emit(dict(self.speech.s))

    def _ai_live(self, on: bool):
        if on:                             # one replacement for your voice at a time
            self.speech.livevoice.b_live.setChecked(False)
        self._update_backdrop(self.fx.spec())   # the Background plays on it too
        self._emit_active()

    def _speech_live(self, on: bool):
        if on:
            self.ai.stop()
        self.controller.on_top = on       # the Effects play on the computer voice's lines
        self._update_backdrop(self.fx.spec())

    def stop_all(self):
        """The window's Stop all: the typed line stops and every voice goes off (the
        voice changer, the AI voice, the computer voice and translating). What was on
        is remembered: Voices ON brings it back."""
        self.controller.stop_speaking()
        self.set_voices(False)
        self.speech.stop_translating()   # a language picked but not ready yet goes too

    def on_keys(self) -> list[str]:
        """What's changing your mic now, in the bar's order: "fx", "ai", "speak",
        "lang"."""
        keys = []
        if self.fx.btn_power.isChecked():
            keys.append("fx")
        if self.ai.is_on():
            keys.append("ai")
        if self.speech.livevoice.b_live.isChecked():
            keys.append("speak")
        if spoken.heard() and self.speech.translating() is not None:   # else no Languages tab
            keys.append("lang")
        return keys

    def voices_on(self) -> bool:
        """The Voices switch's state: something here is changing your mic."""
        return bool(self.on_keys())

    def back_keys(self) -> list[str]:
        """What Voices ON would turn on: what it turned off, else the voice changer
        with the voice picked on it (none after Reset: the voice changer is empty, or
        after its chip's ✕)."""
        return list(self._back) or ([] if self.fx.is_blank() or self._fx_forgot
                                    else ["fx"])

    def set_voices(self, on: bool):
        """The Voices switch. Off: every voice goes off, remembered with the grey ones
        already waiting. On: exactly those come back (nothing remembered: the voice
        changer with its picked voice)."""
        self._switching = True
        try:
            if not on:
                keys = self.on_keys()
                if keys:                 # already all off: keep what's remembered
                    # the grey ones stay too (they were shown as coming back), except
                    # a replacement for your voice the one that's on would push off
                    other = {"ai": "speak", "speak": "ai"}
                    self._back = [k for k in ORDER if k in keys or (
                        k in self._back and other.get(k) not in keys)]
                    if "lang" in keys:
                        self._back_lang = self.speech.cb_lang.currentData() or ""
                for k in keys:
                    self.stop_one(k)
            elif not self.voices_on():
                keys = self.back_keys()
                self._back = []
                for k in keys:
                    self._turn_on(k)
        finally:
            self._switching = False
        self._update_heads()

    def toggle_voices(self) -> bool:
        """The Voices hotkey: flips the switch. True when voices are on now."""
        self.set_voices(not self.voices_on())
        return self.voices_on()

    def _master_flipped(self, on: bool):
        usage.used("voices-master")
        self.set_voices(on)

    def _turn_on(self, key: str):
        if key == "fx":
            self.fx.btn_power.setChecked(True)   # its toggled handler applies it
        elif key == "ai":
            self.ai.b_start.setChecked(True)
        elif key == "speak":
            self.speech.livevoice.b_live.setChecked(True)
        elif key == "lang" and self._back_lang:
            i = self.speech.cb_lang.findData(self._back_lang)
            if i > 0:                    # (its language may have been removed since)
                self.speech.cb_lang.setCurrentIndex(i)

    def toggle_one(self, key: str):
        """A status bar chip clicked: that one goes off (remembered, its chip stays
        grey), or a grey one comes back on."""
        usage.used("voice-chip-toggle")
        if key == "clean":   # not a voice: just off (its chip goes, as with ✕)
            self.clean.set_on(False)
            self._update_heads()
            return
        before = self.on_keys()
        self._switching = True
        try:
            if key in before:
                if key == "lang":
                    self._back_lang = self.speech.cb_lang.currentData() or ""
                self._back = [k for k in ORDER if k == key or k in self._back]
                self.stop_one(key)
            else:
                self._back = [k for k in self._back if k != key]
                self._turn_on(key)
                # one replacement for your voice at a time: the one it pushed off goes grey
                pushed = [k for k in before if k not in self.on_keys()]
                self._back = [k for k in ORDER if k in self._back or k in pushed]
        finally:
            self._switching = False
        self._update_heads()

    def forget_one(self, key: str):
        """A chip's ✕: that one goes off, and Voices ON won't bring it back."""
        if key == "clean":
            self.clean.set_on(False)
        # (else its chip came straight back as the voice ON turns on: a dead ✕)
        self._fx_forgot = self._fx_forgot or key == "fx"
        self._back = [k for k in self._back if k != key]
        if key in self.on_keys():
            self.stop_one(key)
        self._update_heads()

    def reset_voices(self):
        """The bar's Reset: a fresh start. Every voice goes off and is forgotten (Voices
        ON won't bring any back) and the voice changer's effects are cleared; Undo puts
        it all back."""
        was = {"on": self.on_keys(), "back": list(self._back), "back_lang": self._back_lang,
               "lang": self.speech.cb_lang.currentData() or "", "fx": self.fx.snapshot()}
        self._switching = True
        try:
            self.controller.stop_speaking()
            for k in was["on"]:
                self.stop_one(k)
            self.speech.stop_translating()
            self._back, self._back_lang = [], ""
            self.fx.clear_mix()
        finally:
            self._switching = False
        self._update_heads()
        self.reset_undo.show_for(_("Voices reset"), lambda: self._unreset(was))

    def _unreset(self, was: dict):
        self._switching = True
        try:
            self.fx.restore(was["fx"])
            for k in was["on"]:
                if k == "lang":
                    self._back_lang = was["lang"]
                if k != "fx":            # restore() turned the voice changer back on
                    self._turn_on(k)
            self._back, self._back_lang = was["back"], was["back_lang"]
        finally:
            self._switching = False
        self._update_heads()

    def stop_one(self, key: str):
        """Just that one goes off, the others stay on."""
        if key == "fx":
            self.fx.btn_power.setChecked(False)   # its toggled handler applies it
        elif key == "ai":
            self.ai.stop()
        elif key == "speak":
            self.controller.stop_speaking()
            self.speech.livevoice.b_live.setChecked(False)
        elif key == "lang":
            self.speech.stop_translating()

    def is_active(self) -> bool:
        """Something here is changing what others hear from your mic."""
        return (self.fx.btn_power.isChecked() or self.speech.livevoice.b_live.isChecked()
                or self.ai.is_on())

    def _emit_active(self):
        self._sync_translate()
        self._update_heads()
        # only when it flips: every slider step lands here, and each send redraws the tab
        on = self.is_active()
        if on != self._active:
            self._active = on
            self.active_changed.emit(on)

    # ---- Speak in: the voice that's on says the translated lines
    def _sync_translate(self):
        sp = self.speech
        lv = sp.livevoice
        m = sp.translating()
        fg = lv.b_live.isChecked()   # text-to-speech's own Start translates by itself
        who = ""
        if m is not None and not fg:
            if self.ai.is_on():
                who = "ai"
            elif self.fx.btn_power.isChecked():
                who = "fx"
        self.ai_controller.set_dub(who == "ai")
        sp.ctl.dub = self.ai_controller if who == "ai" else None   # (typed in live.py)
        sp.ctl.fx_always = who == "fx"
        if who and not lv.bg_for:
            lv._bg_note("")               # "turn on a voice": one is on now
        lv.translate_for(who)
        if not lv.bg_for and not lv._bg_warning:
            lv._bg_note("")               # Said by says who speaks (or that Start does)
        fx = self.fx.preset
        if self.ai.is_on():
            on = ("ai", self.ai.voice_title())
        elif self.fx.btn_power.isChecked():
            on = ("fx", _("My own mix") if fx == CUSTOM else voicefx.shown(fx))
        else:
            on = ("", "")
        sp.said_by(*on)
