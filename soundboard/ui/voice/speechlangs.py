"""The Languages card's translation: picking a language, downloading it, the live voice
speaking in it and who says the lines. Mixed into SpeechPanel (speechpanel.py)."""
from __future__ import annotations

import html
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QMessageBox, QWidget

from soundboard.addons import modules as mods
from soundboard.core import langnames, usage
from soundboard.sounds import library
from soundboard.online import net
from soundboard.speech import customvoices, translation
from soundboard.ui.kit import busy
from soundboard.i18n import _

if TYPE_CHECKING:
    class _Panel(QWidget):
        # what SpeechPanel itself provides, for the type checker only
        def __getattr__(self, name: str) -> Any: ...
else:
    _Panel = object


LIVE_MODULE = "live-voice"


def translations(module_list: list[mods.ModuleInfo]) -> list[mods.ModuleInfo]:
    """The languages the live voice can speak in (translation add-ons), A to Z."""
    return sorted((m for m in module_list if m.kind == "translation" and not m.error),
                  key=langnames.sort_key)


class SpeechLangs(_Panel):
    """SpeechPanel's translation and live voice."""

    # ---- live
    def set_modules(self, module_list: list[mods.ModuleInfo]):
        self.module = next((m for m in module_list if m.id == LIVE_MODULE and not m.error),
                           None)
        self.langs = translations(module_list)
        self._fill_langs()
        self.installs._refresh_module()
        # "Refresh" may come right after installing a voice in Windows settings
        self.installs._recheck_voices()

    # ---- translation
    def _lang(self) -> mods.ModuleInfo | None:
        code = self.cb_lang.currentData()
        return next((m for m in self.langs if m.language == code), None)

    def _fill_langs(self):
        self._ready.clear()   # called after every download, removal and module rescan
        self.cb_lang.blockSignals(True)
        self.cb_lang.clear()
        self.cb_lang.addItem(_("Don't translate"), "")
        for m in self.langs:
            name = langnames.of(m)
            self.cb_lang.addItem(name if m.installed
                                 else _("{language}  (download {size} MB)", language=name,
                                        size=translation.size_mb(m)),
                                 m.language)
        self.cb_lang.setIconSize(QSize(20, 20))
        self._fit_lang_list()
        self.cb_lang.setCurrentIndex(max(0, self.cb_lang.findData(self.s["translate"]))
                                     if self.s["translate_on"] else 0)
        self.cb_lang.blockSignals(False)
        self._fill_tiles()
        self.show_lang_box(self.module is not None and self.module.installed
                           and bool(self.langs))
        self._refresh_translation()
        self._sync_switch()
        self.installs.show_remove()   # a language downloaded or deleted

    def show_recognition(self, ok: bool):
        """Speech recognition is in (or not): the options that use it show (or hide)."""
        for w in getattr(self, "_needs_recognition", ()):
            w.setVisible(ok)

    def show_lang_box(self, on: bool):
        """The language cards, once there's speech recognition and languages. Until
        then the ON / OFF switch and "Pick a language" have nothing to pick: hidden,
        the install box says what's needed."""
        self._lang_ready = on
        self.cards.setVisible(on)
        self.b_on.setVisible(on)
        self.lbl_intro.setVisible(on)
        self._show_settings()

    def recognition_ready(self) -> bool:
        """Speech recognition is installed: the card works offline from here on."""
        return self.module is not None and self._is_ready(self.module)

    def _show_settings(self):
        """Who says it and what the language still needs, in their inner area: only
        while a language is on or downloading (an empty box otherwise)."""
        on = self._lang_ready and (self._lang() is not None
                                   or self.installs._dl_busy is not None)
        self.lang_box.setVisible(on)
        self.settings_box.setVisible(on)

    def _module(self, code: str) -> mods.ModuleInfo | None:
        return next((m for m in self.langs if m.language == code), None)

    def _tile_clicked(self, code: str):
        """A language card: a grey one asks to download it; a downloaded one goes on;
        the one that's on goes off (as the voice cards)."""
        self._mark_tiles()   # its own click checked it: the language decides
        m = self._module(code)
        if m is None:
            return
        if code == (self.cb_lang.currentData() or ""):
            self.set_language("")
        elif not m.installed:
            self._offer_download(m)
        else:
            self.set_language(code)

    def set_language(self, code: str):
        """Turn `code` on (the AI voice or the voice changer says it, else the
        language's own voice: VoicePanel decides), or "" every language off."""
        self.cb_lang.setCurrentIndex(max(0, self.cb_lang.findData(code)) if code else 0)
        self._mark_tiles()

    def _switch_clicked(self, on: bool):
        """The card's ON / OFF: the last language back on, or every language off."""
        if not on:
            self.set_language("")
            return
        m = self._module(self.s.get("translate") or "")
        if m is None or not m.installed:
            m = next((x for x in self.langs if x.installed), None)
        if m is None:
            self._sync_switch()
            busy.toast(self, html.escape(_("Pick a language first: click one below.")))
            return
        self.set_language(m.language)

    def _sync_switch(self):
        on = bool(self.cb_lang.currentData())
        if self.b_on.isChecked() != on:
            self.b_on.blockSignals(True)
            self.b_on.setChecked(on)
            self.b_on.blockSignals(False)
        self.b_on.setText(_("On") if on else _("Off"))
        self.b_on.update()

    def _offer_download(self, m: mods.ModuleInfo):
        """A grey card: download it (with its voice) after a Yes."""
        name = langnames.of(m)
        if net.offline():
            busy.toast(self, html.escape(_("Offline mode is on, so {language} can't be "
                                           "downloaded now.", language=name)), "warn")
            return
        if not net.allowed("voices"):
            busy.toast(self, html.escape(net.off_message("voices")), "warn")
            return
        if self.installs._dl_busy is not None:
            busy.toast(self, html.escape(_("Another language is downloading. Wait for it "
                                           "to finish.")))
            return
        if QMessageBox.question(
                self, _("Download {language}?", language=name),
                _("{language} isn't downloaded yet. Download it now? It's a one-time "
                  "{size} MB download, with a voice that speaks {language}.",
                  language=name, size=translation.size_mb(m))
        ) != QMessageBox.StandardButton.Yes:
            return
        self._wanted = m.language
        self.installs._download(m)
        self._show_settings()

    def _after_download(self):
        """A language (and its voice) came in: its voice joins the lists, and a grey
        card's language is on now."""
        self.installs._recheck_voices()
        code, self._wanted = self._wanted, ""
        m = self._module(code) if code else None
        if m is None or not m.installed:
            return
        self.set_language(code)

    def _fit_lang_list(self):
        """The open list shows every name whole, even past the box's own width."""
        view = self.cb_lang.view()
        view.setMinimumWidth(view.sizeHintForColumn(0) + 40)    # + padding, scroll bar

    def _lang_picked(self, *_):
        """A language picked means speaking it; Don't translate is off."""
        if self.cb_lang.currentData():
            usage.used("translate-on")
        self._settings_edited()
        self._refresh_translation()
        self._sync_switch()
        self._mark_tiles()
        self._show_settings()
        self.lang_changed.emit()

    def stop_translating(self):
        """Back to Don't translate (Stop all)."""
        self.cb_lang.setCurrentIndex(0)

    def _lang_on(self) -> mods.ModuleInfo | None:
        """The language picked under Speak in (None: Don't translate)."""
        return self._lang()

    def said_by(self, who: str, name: str = ""):
        """Who's on elsewhere on the tab: "ai" (the AI voice `name`), "fx" (the voice
        changer's voice `name`) or "" (nobody: the computer voice). From VoicePanel."""
        self._who = f"{who}:{name}" if who else ""
        self._show_who()

    def _show_who(self):
        """Said by: who others will hear, and Start's words to match."""
        who, _c, name = self._who.partition(":")
        m = self._lang_on()
        lang = langnames.of(m) if m is not None else ""
        voice = self._voice_for(m) if m is not None else ""
        # the language's own voice by its name ("Huayan"), or the Windows one reading
        # a language that has none of its own
        own = (str(m.voice.get("name") or "") or customvoices.label(voice)
               if m is not None and voice else "")
        if m is not None and not voice:
            text = _("The {language} voice, once {language} is downloaded (below).",
                     language=lang)
        elif who == "ai" and m is not None:
            text = _("Your AI voice, {voice}. It's on: just talk.", voice=name)
        elif who == "fx" and m is not None:
            text = _("{voice} with your {effect} voice changer. It's on: just talk.",
                     voice=own or lang, effect=name)
        elif m is not None:
            text = _("{voice}, the {language} voice. It's on: just talk.",
                     voice=own or lang, language=lang)
        else:
            text = ""
        self.lbl_who.setText(text)
        # its height for its width changed: the layouts around keep the old one until told
        self.settings_box.updateGeometry()
        self.livevoice.show_button(lang, bool(who) and m is not None)

    def translating(self) -> mods.ModuleInfo | None:
        """The language picked under Speak in, switched on, downloaded and ready."""
        m = self._lang_on()
        ok = self.module is not None and self._is_ready(self.module)
        return m if ok and m is not None and self._is_ready(m) else None

    def _is_ready(self, m: mods.ModuleInfo) -> bool:
        """m.installed, remembered until the next install, download or rescan. The
        Voice tab asks on every click (Voices ON / OFF, its chips); while an add-on
        installs, the disk is so busy that one check held the window for seconds,
        and the sounds playing with it."""
        key = id(m)   # the list it's from is kept until the next rescan, which clears this
        if key not in self._ready:
            self._ready[key] = m.installed
        return self._ready[key]

    def _voice_for(self, m: mods.ModuleInfo) -> str:
        return self.ctl.tts.voice_for(m.language, self.s["voice"])

    def _refresh_translation(self):
        # Computing this state temporarily hides its buttons. Restore focus only
        # when the same action is still available in the resulting state.
        focused = self.focusWidget()
        self._refresh_translation_state()
        self._show_who()
        if hasattr(self, "cards"):   # (still being made)
            self._show_settings()
        if (focused is not None and focused in self.installs.tr_buttons()
                and focused.isVisible()):
            focused.setFocus(Qt.FocusReason.OtherFocusReason)

    def _refresh_translation_state(self):
        """The box under "Speak in": download it, get its Windows voice, or all set."""
        i = self.installs
        busy.set_busy(i.b_voice_install, i._voice_installing is not None)
        m = self._lang()
        on = self._lang_on()
        if on is not None:
            name = langnames.of(on)
            self.lbl_delay.setText(_(
                "⏱ Others hear you in {language} a few seconds late: each sentence is "
                "written down, translated, then spoken once you've finished it. It works "
                "with the AI voice and the voice changer too; your real voice is muted "
                "meanwhile.", language=name))
        self.lbl_delay.setVisible(on is not None)
        downloading = i._dl_busy is not None
        self.tr_box.setVisible(m is not None or downloading)
        for b in i.tr_buttons():
            b.hide()
        i._watch_voices(False)
        if downloading:
            i.b_dl.show()
            i.b_dl_cancel.show()
            return
        if m is None:
            return
        name = langnames.of(m)
        live = self.ctl.live
        if not m.installed:
            self.lbl_tr.setText(_("{language} needs a one-time download of its translation "
                                  "model ({size} MB). After that, translating happens on this "
                                  "PC; what you say never leaves it.", language=name,
                                  size=translation.size_mb(m)))
            i.b_dl.setText(_("Download {language}", language=name))
            i.b_dl.setVisible(not net.offline())   # Offline mode: no dead button
            if net.offline():
                self.lbl_tr.setText(_("{language} needs a one-time download of its "
                                      "translation model ({size} MB). Offline mode is on, so "
                                      "it can't be downloaded now.", language=name,
                                      size=translation.size_mb(m)))
            # downloading voices switched off in Settings > Privacy: greyed, saying why
            i.b_dl.setEnabled(not live and net.allowed("voices"))
            i.b_dl.setToolTip(net.off_message("voices") if not net.allowed("voices") else
                              _("Stop the voice to download this") if live else "")
            return
        i.b_dl_remove.setText(_("Delete the {language} download", language=name))
        i.b_dl_remove.setVisible(not live)
        if not self.ctl.tts.voices:        # still loading, or no speech at all
            self.lbl_tr.setText(_("Translation is quick but not perfect with slang."))
            return
        voice = self._voice_for(m)
        if m.voice and self.voices_need:
            # its voice reads through the AI voices add-on: say what's missing
            self.lbl_tr.setText(
                _("The {language} voice needs the AI voices add-on: get it on the AI "
                  "voices tab.", language=name) if self.voices_need == "get" else
                _("The {language} voice needs the newest AI voices: press Update AI voices "
                  "under More options on the AI voices tab.", language=name))
        elif voice:
            # (Said by names the voice)
            self.lbl_tr.setText(_("Translation is quick but not perfect with slang."))
        else:
            i._watch_voices(True)
            for b in (i.b_voice_install, i.b_voices, i.b_voices_check):
                b.show()
            if i._voice_installing is not None:
                self.lbl_tr.setText(_("Installing the {language} voice\u2026 Say Yes to "
                                      "Windows' permission prompt, then it downloads (a minute "
                                      "or two). It's used by itself as soon as it's in.",
                                      language=name))
                i.b_voice_install.setText(_("Installing\u2026"))
                busy.set_busy(i.b_voice_install, True)
                i.b_voices.hide()
                return
            i.b_voice_install.setText(_("Install the {language} voice", language=name))
            i.b_voice_install.setVisible(not net.offline())   # Windows Update: online
            # Windows Update can't go through the app's connection: off means not at all
            i.b_voice_install.setEnabled(net.allowed("voices"))
            i.b_voice_install.setToolTip(
                i._voice_install_tip if net.allowed("voices") else net.off_message("voices"))
            self.lbl_tr.setText(i._voice_note or (_(
                "\u26a0 Windows has no {language} voice yet, so {language} can't be spoken "
                "properly. Offline mode is on, so it can't be installed now.", language=name)
                if net.offline() else _(
                "\u26a0 Windows has no {language} voice yet, so {language} can't be spoken "
                "properly. Press Install (free, one click); it's picked up by itself "
                "once it's in, even mid-sentence.", language=name)))

    @staticmethod
    def _open_folder(module: mods.ModuleInfo | None = None, btn=None):
        """The module's own folder, or the user add-ons folder when it isn't there yet."""
        d = module.path if module is not None else library.APP_DIR / "modules"

        def make():
            d.mkdir(parents=True, exist_ok=True)
            return d
        busy.open_folder(make, btn)
