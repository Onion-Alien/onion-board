"""The Voice tab's My voice combos side: what's on as a setup, turning one back on, its
share code, picture and words. Mixed into VoicePanel (voicepanel.py)."""
from __future__ import annotations

import html
from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import QWidget

from soundboard.core import langnames, usage
from soundboard.mic import savedvoices, voicesetups
from soundboard import voicefx
from soundboard.ui.kit import busy, icons
from soundboard.ui.voice import art
from soundboard.ui.voice.voicefxpanel import CUSTOM, on_top
from soundboard.i18n import _

if TYPE_CHECKING:
    class _Panel(QWidget):
        # what VoicePanel itself provides, for the type checker only
        def __getattr__(self, name: str) -> Any: ...
else:
    _Panel = object


class VoiceCombos(_Panel):
    """VoicePanel's voice combos (voicesetups)."""

    # ---- My voice combos (voicesetups)
    def current_setup(self) -> dict:
        """What's on now as a setup: the voice changer's voice, the AI voice, the
        language spoken; {} when none of them is on. Its "name" is a suggestion."""
        out: dict = {}
        names = []
        if self.fx.btn_power.isChecked():
            effects = {t: c for t, c in self.fx.spec()["effects"].items()
                       if c.get("on") and not on_top(t)}
            if effects:
                name = self.fx.preset
                out["fx"] = "" if name == CUSTOM else name
                out["effects"] = effects
                names.append(_("My own mix") if name == CUSTOM else voicefx.shown(name))
        if self.ai.is_on():
            vid = self.ai.s.get("voice", "")
            vo = next((v for v in self.ai.voices if v.get("id") == vid), None)
            if vo is not None:
                out["ai"] = {"id": vid, "name": vo.get("name", vid),
                             "pitch": float(self.ai.s.get("pitch", 0.0) or 0.0)}
                names.append(out["ai"]["name"])
        lang = self.speech.cb_lang.currentData() or ""
        if lang:
            out["language"] = lang
            m = next((m for m in self.speech.langs if m.language == lang), None)
            names.append(langnames.of(m) if m is not None else lang)
        if out:
            out["name"] = " + ".join(names)[:voicesetups.MAX_NAME]
        return out

    def use_setup(self, setup: dict):
        """Turn a setup's whole mix on for your mic (what it hasn't got goes off)."""
        effects = setup.get("effects") or {}
        name = setup.get("fx") or ""
        saved = self.fx.store.voices.get(name)
        if not effects:
            self.fx.btn_power.setChecked(False)
        elif name in voicefx.PRESETS or (saved is not None and savedvoices.shared_effects(
                saved) == savedvoices.shared_effects(effects)):
            self.fx.pick(name)
        else:   # its own mix, or a voice of that name here that isn't the same one

            self.fx.use_mix(effects)
        ai = setup.get("ai")
        if ai and self.ai.module is not None and any(
                v.get("id") == ai["id"] for v in self.ai.voices):
            self.ai.use(ai["id"])
        else:
            self.ai.stop()
        i = self.speech.cb_lang.findData(setup.get("language") or "")
        self.speech.cb_lang.setCurrentIndex(max(0, i))
        self._update_heads()

    def copy_setup_code(self, name: str) -> bool:
        """A setup as a share code, onto the clipboard (its own AI voice's blend goes
        too, as nobody else has it). False if there's nothing in it to share."""
        from PySide6.QtGui import QGuiApplication

        from soundboard.online import storevoices
        setup = self.setups.setups.get(name)
        if setup is None:
            return False
        ai = setup.get("ai") or {}
        payload = storevoices.pack_setup(name, setup,
                                         self.ai.store.get(ai["id"]) if ai.get("id") else None)
        if not storevoices.can_share(payload):
            return False
        QGuiApplication.clipboard().setText(storevoices.share_code(payload))
        usage.used("setup-code-shared")
        return True

    def take_code(self, v, notes: list[str]) -> str:
        """An AI voice or setup from a share code (storevoices.Voice): asked about, then
        added to yours as a Store voice is. The name it got, "" if none."""
        from PySide6.QtWidgets import QMessageBox

        from soundboard.ui.store.storevoices import VoiceHooks, meta_line
        title = _("Import a voice code")
        ask = (_("Add “{name}”?", name=html.escape(v.name))
               + f"<br><br>{html.escape(meta_line(v))}"
               + "".join(f"<br><br>{html.escape(n)}" for n in notes))
        if QMessageBox.question(self, title, ask) != QMessageBox.StandardButton.Yes:
            return ""
        # self is the VoicePanel this mixin is part of
        hooks = VoiceHooks(lambda: self)  # pyright: ignore[reportArgumentType]
        said = hooks.take(v)
        if hooks.last:
            usage.used("voice-code-imported")
        busy.toast(self, html.escape(said), "ok" if hooks.last else "warn")
        return hooks.last

    def setup_icon(self, setup: dict):
        """A setup's picture: its AI voice's emoji, else its voice changer voice's."""
        ai = setup.get("ai")
        vo = next((v for v in self.ai.voices if ai and v.get("id") == ai["id"]), None)
        if vo is not None:
            from soundboard.ui.voice.aivoicepanel import voice_icon
            return voice_icon(vo)
        pic = art.icon(art.voice_key(setup["fx"])) if setup.get("fx") else None
        return pic or icons.icon("sliders" if setup.get("effects") else "browser", "muted")

    def setup_words(self, setup: dict) -> str:
        """What's in a setup, in words."""
        parts = []
        if setup.get("effects"):
            fx = setup.get("fx") or ""
            parts.append(_("Voice changer: {voice}", voice=voicefx.shown(fx) if fx
                           else _("My own mix")))
        if setup.get("ai"):
            parts.append(_("AI voice: {voice}", voice=setup["ai"].get("name", "")))
        lang = setup.get("language")
        if lang:
            m = next((m for m in self.speech.langs if m.language == lang), None)
            parts.append(_("Speaks {language}", language=langnames.of(m) if m else lang))
        return " · ".join(parts)
