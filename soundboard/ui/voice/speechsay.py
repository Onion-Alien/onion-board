"""The Languages card's text-to-speech: saying a typed line, saving it as a sound, the
computer voices and their settings. Mixed into SpeechPanel (speechpanel.py)."""
from __future__ import annotations

import html
import threading
import time
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QMessageBox,
                               QScrollArea, QWidget)

from soundboard.core import langnames, usage
from soundboard.ui.kit import theme
from soundboard.speech import customvoices, tts
from soundboard.ui.kit import busy, fit
from soundboard.ui.kit.panel import hint_label
from soundboard.ui.kit.widgets import widget_at
from soundboard.core import errors
from soundboard.i18n import _, ngettext

if TYPE_CHECKING:
    class _Panel(QWidget):
        # what SpeechPanel itself provides, for the type checker only
        def __getattr__(self, name: str) -> Any: ...
else:
    _Panel = object


class SpeechSay(_Panel):
    """SpeechPanel's text to speech."""

    # ---- text to speech
    def _warm_for_a_line(self, *_):
        """A line is being typed (or the live voice starts): start Windows speech now,
        not when the line is said. With the voice list remembered from the last run it
        isn't running yet, and starting it takes ~2 s."""
        t = self.ctl.tts
        if (self._warming or getattr(t, "running", True)
                or self.ctl.speaker.voice.startswith(customvoices.PREFIX)):
            return
        self._warming = True

        def work():
            try:
                busy.emit(self._voices, t.warm_up(), t.error)
            finally:
                self._warming = False
        threading.Thread(target=work, name="tts-warmup", daemon=True).start()

    def _remember_voices(self):
        """Keep the list the speech helper gave (with the Windows voices it was for) in
        the settings, so the next launch needn't start the helper to list them."""
        listed = getattr(self.ctl.tts, "listed", None)
        if not listed or not self._voice_fp:
            return
        names, langs = listed
        entry = tts.remember_voices(names, langs, self._voice_fp)
        if self.s.get(tts.VOICE_CACHE) != entry:
            self.s[tts.VOICE_CACHE] = entry
            self.changed.emit(dict(self.s))

    def _say(self):
        text = self.ed.text().strip()
        if not text:   # as Save as sound says it: the box is where the line goes
            busy.flash(self.b_say, _("Type a line first"), 1600)
            self.ed.setFocus()
            return
        self.say_line(text)
        self.ed.clear()

    def say_line(self, text: str):
        """Speak `text` (the Say button, or the control API's /api/say)."""
        usage.used("text-to-speech")   # the name only (usage.py)
        self.ctl.say(text)
        self._log_said(text)
        self._last_said = text

    def _fit_say_bar(self):
        """Save as sound shows its words while the box beside it still has room for
        "Type here"; narrower, just its + (the tooltip says the rest), so the box isn't
        cut to its first letters."""
        b, ed = self.b_keep, self.ed
        word = _("Save as sound")
        shown = b.text()
        b.setText(word)
        lay = self.say_bar.layout()
        if lay is None:
            return
        m = lay.contentsMargins()
        others = sum(w.sizeHint().width() for w in (widget_at(lay, i) for i in range(lay.count()))
                     if w is not None and w is not ed and not w.isHidden())
        gaps = lay.spacing() * max(lay.count() - 1, 0)
        room = self.say_bar.width() - m.left() - m.right() - others - gaps
        need = ed.fontMetrics().horizontalAdvance(_("Type here")) + 64
        want = word if room >= need else ""
        b.setText(shown)
        if b.text() != want:   # changed only when it must (no resize loop)
            b.setText(want)

    def _save_line(self):
        """Save as sound: the typed line (else the last one said) spoken into a pad."""
        text = self.ed.text().strip() or self._last_said
        if not text:
            busy.flash(self.b_keep, _("Type a line first"), 1600)
            return
        busy.set_busy(self.b_keep, True)
        name = " ".join(text.split())[:40]

        def work():
            try:
                data, err = self.ctl.render_line(text), ""
            except Exception as e:  # noqa: BLE001 - said under the bar
                data, err = None, errors.plain(e)
            busy.emit(self._line_saved, data, name, err)
        threading.Thread(target=work, name="tts-save", daemon=True).start()

    def _line_done(self, data, name: str, err: str):
        busy.set_busy(self.b_keep, False)
        if data is None:
            self._tts_error(_("Couldn't save that line: {error}", error=err))
            return
        self.clip_ready.emit(data, name)
        busy.flash(self.b_keep, _("✓ Added to Sounds"), 1800)

    def _log_said(self, text: str):
        self.said_log.appendPlainText(f"{time.strftime('%H:%M:%S')}  {text}")
        bar_ = self.said_log.verticalScrollBar()
        bar_.setValue(bar_.maximum())

    def _fill_voices(self, voices: list, error: str, quiet: bool = False):
        self.cb_voice.blockSignals(True)
        self.cb_voice.clear()
        self.cb_voice.addItem(_("Windows default"), "")
        for name in voices:
            self.cb_voice.addItem(customvoices.label(name), name)
        found = self.cb_voice.findData(self.s["voice"])
        self._voice_standin = found < 0
        self.cb_voice.setCurrentIndex(max(0, found))
        self.cb_voice.setEnabled(bool(voices))
        self.cb_voice.blockSignals(False)
        # speak in the voice the list shows: a saved voice that's been uninstalled
        # shows as "Windows default", and asking for it would fail every line
        self.ctl.speaker.voice = self.cb_voice.currentData() or ""
        if not error:
            self._remember_voices()
        m = self._lang()
        voice = self._voice_for(m) if m is not None else ""
        self.installs.voices_loaded(len(voices), error, m is None or bool(voice))
        if self.ctl.live and m is not None and voice and self.ctl.live_voice != voice:
            # talking already: switch to the new voice now, no restart needed
            self.ctl.live_voice = voice
            short = customvoices.label(voice)
            self.livevoice.lbl_state.setText(_("✓ {language} voice found: {voice} speaks from the "
                                               "next line on.", language=langnames.of(m),
                                               voice=short))
        self._refresh_translation()
        problems = getattr(self.ctl.tts, "problems", [])
        custom = getattr(self.ctl.tts, "custom", {})
        servers = [v for v in custom.values() if v.url]
        self.servers.set_servers(servers, self.cb_voice.currentData() or "")
        others = len(custom) - len(servers)   # the servers have their own rows
        self.lbl_custom.setText("\n".join(f"⚠ {p}" for p in problems) if problems else
                                ngettext("{n} custom voice loaded.", "{n} custom voices loaded.",
                                         others) if others else "")
        self.lbl_custom.setVisible(bool(self.lbl_custom.text()))
        if error and not quiet:
            self._tts_error(_("Text-to-speech isn't available: {error}",
                              error=errors.plain(error)))

    def show_custom_voices(self):
        """Open the Add-ons tab (VoicePanel shows it) and bring custom voices into view."""
        self.custom_wanted.emit()
        w = self.custom_box.parentWidget()
        while w is not None and not isinstance(w, QScrollArea):
            w = w.parentWidget()
        if w is not None:
            QTimer.singleShot(0, self, lambda a=w: a.ensureWidgetVisible(
                self.custom_title, 0, 40))   # from its heading

    def _add_voice_server(self):
        """A small form for a TTS server's address; saved as a .json in the voices folder."""
        dlg = QDialog(self)
        fit.watch(dlg)
        dlg.setWindowTitle(_("Add a voice server"))
        form = QFormLayout(dlg)
        form.addRow(hint_label(_("A text-to-speech server running on your PC. Most have an "
                                 "OpenAI-style address ending in /v1/audio/speech; one that "
                                 "takes the text in the address can use {text} in it instead.",
                                 text="{text}")))
        ed_name = QLineEdit()
        ed_name.setPlaceholderText("Kokoro")
        ed_url = QLineEdit()
        ed_url.setPlaceholderText("http://127.0.0.1:8880/v1/audio/speech")
        ed_voice = QLineEdit()
        ed_voice.setPlaceholderText(_("the server's voice name, e.g. af_bella (optional)"))
        ed_model = QLineEdit()
        ed_model.setPlaceholderText(_("optional"))
        ed_key = QLineEdit()
        ed_key.setEchoMode(QLineEdit.EchoMode.Password)
        ed_key.setPlaceholderText(_("only if the server asks for one"))
        for lbl, w in ((_("Name"), ed_name), (_("Address"), ed_url), (_("Voice"), ed_voice),
                       (_("Model"), ed_model), (_("API key"), ed_key)):
            form.addRow(lbl, w)
        err = hint_label("")
        theme.set_tone(err, "error")
        err.hide()
        form.addRow(err)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        form.addRow(btns)
        btns.rejected.connect(dlg.reject)

        def ok():
            url = ed_url.text().strip()
            if not url.lower().startswith(("http://", "https://")):
                err.setText(_("The address starts with http:// or https://"))
                err.show()
                return
            name = ed_name.text().strip() or "Voice server"
            try:
                if customvoices.server_path(name).exists() and QMessageBox.question(
                        dlg, _("Add a voice server"),
                        _("There's already a voice server called “{name}”. Replace it?",
                          name=name)
                ) != QMessageBox.StandardButton.Yes:
                    return
                customvoices.save_server(name, url, ed_voice.text().strip(),
                                         ed_model.text().strip(), ed_key.text().strip())
            except OSError as e:
                err.setText(_("Couldn't save it in the voices folder: {error}",
                              error=errors.plain(e)))
                err.show()
                return
            self.s["voice"] = customvoices.PREFIX + name   # pick it once it's loaded
            dlg.accept()
        btns.accepted.connect(ok)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.changed.emit(dict(self.s))
            busy.toast(self, _("✓ Saved “{name}”: loading its voices…",
                               name=html.escape(ed_name.text().strip() or "Voice server")),
                       "ok")
            self.installs._recheck_voices_asked()

    def _tts_error(self, msg: str):
        busy.toast(self, html.escape(msg), "error")

    def _voice_picked(self, *_):
        self._voice_standin = False   # the user chose this one
        self._settings_edited()
        self.servers.sync(self.cb_voice.currentData() or "")

    def _server_switched(self, voice: str, on: bool):
        """A voice server's switch: on, it's the computer voice; off, Windows' is."""
        i = self.cb_voice.findData(voice if on else "")
        if i < 0 or i == self.cb_voice.currentIndex():
            self.servers.sync(self.cb_voice.currentData() or "")
            return
        self.cb_voice.setCurrentIndex(i)   # saves it, and the other switches go off

    def _remove_server(self, cv):
        """Remove: the .json goes now, Undo puts it back (DESIGN: no "Are you sure?")."""
        path = cv.file or customvoices.server_path(cv.name)
        try:
            kept = path.read_bytes()
            path.unlink()
        except OSError as e:
            self._tts_error(_("Couldn't remove it: {error}", error=errors.plain(e)))
            return
        was_on = self.cb_voice.currentData() == cv.id

        def undo():
            try:
                path.write_bytes(kept)
            except OSError as e:
                self._tts_error(_("Couldn't put it back: {error}", error=errors.plain(e)))
                return
            if was_on:
                self.s["voice"] = cv.id   # picked again once it's loaded
            self.installs._recheck_voices_asked()
        if was_on:
            self.cb_voice.setCurrentIndex(0)   # Windows' voice speaks from now on
        busy.toast(self, _("Removed “{name}”", name=html.escape(cv.name)), "ok",
                   action=(_("Undo"), undo))
        self.installs._recheck_voices_asked()

    def _settings_edited(self, *_):
        if not self._voice_standin:
            self.s["voice"] = self.cb_voice.currentData() or ""
            self.ctl.speaker.voice = self.s["voice"]
        self.s.update(rate=self.sl_rate.value(),
                      model=self.cb_model.currentData(),
                      spoken=self.ed_lang.text().strip().lower(),
                      mute_real_voice=self.chk_mute.isChecked(),
                      voice_fx=self.chk_fx.isChecked(),
                      # Don't translate keeps the last language (older versions show
                      # it picked, switched off)
                      translate=self.cb_lang.currentData() or self.s["translate"],
                      translate_on=bool(self.cb_lang.currentData()))
        self.ctl.speaker.rate = self.s["rate"]
        self.ctl.set_mute_real_voice(self.s["mute_real_voice"])
        if self.ctl.live and not self.livevoice.bg_for:
            self.ctl.set_replace(self.s["mute_real_voice"])
        self.ctl.voice_fx = self.s["voice_fx"]
        self.changed.emit(dict(self.s))
