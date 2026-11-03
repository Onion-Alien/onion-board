"""The Languages card's text-to-speech: saying a typed line, saving it as a sound, the
computer voices and their settings. Mixed into SpeechPanel (speechpanel.py)."""
from __future__ import annotations

import html
import threading
import time
from typing import TYPE_CHECKING, Any

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QDialog, QToolButton, QWidget)

from soundboard.core import langnames, usage
from soundboard.speech import customvoices, tts
from soundboard.ui.kit import busy
from soundboard.ui.voice import saybig, sayhistory
from soundboard.ui.kit.widgets import widget_at
from soundboard.core import errors
from soundboard.i18n import _, ngettext

if TYPE_CHECKING:
    class _Panel(QWidget):
        # what SpeechPanel itself provides, for the type checker only
        def __getattr__(self, name: str) -> Any: ...
else:
    _Panel = object

SAY_CLIP_MAX = 5000   # characters of copied text said at once (a whole page is minutes)


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

    def say_line(self, text: str, src: str = "typed", remember: bool = True):
        """Speak `text` (the Say button, the long-text box, a hotkey, or the control
        API's /api/say; `src` says which, for the history). While a language is on
        and talking, it's said in that language and its voice, as what you say out
        loud is. A line said again from the history (`remember` False) is already
        in it, so it gets no second row."""
        usage.used("text-to-speech")   # the name only (usage.py)
        if self.translating() is None or not self.ctl.say_translated(text):
            self.ctl.say(text)
        self._log_said(text)
        self._last_said = text
        self._recall = -1
        if not remember:
            return
        sayhistory.add_line(self.history, text, src)
        self.s[sayhistory.HISTORY_KEY] = list(self.history)
        self.changed.emit(dict(self.s))
        pop = self._history_pop
        if pop is not None and pop.isVisible():
            pop.show_lines(self.history)

    def say_clipboard(self, src: str = "clipboard") -> str:
        """Say what's on the clipboard (the "Say what I copied" hotkey, /api/say?
        clipboard=1). Long text is said a line at a time. "" when there's no text."""
        lines = saybig.lines_of(QGuiApplication.clipboard().text()[:SAY_CLIP_MAX])
        for ln in lines:
            self.say_line(ln, src)
        return "\n".join(lines)

    def say_again(self, src: str = "api") -> str:
        """The last line said, said again ("" when nothing was)."""
        if not self.history:
            return ""
        text = self.history[-1]["text"]
        self.say_line(text, src, remember=False)
        return text

    # ---- the history, the long-text box and the quick box
    def open_history(self):
        if self._history_pop is None:
            self._history_pop = sayhistory.SayHistoryPopup(self.window(), sayhistory.Actions(
                say=self._say_again_from_history, edit=self._edit_line, copy=self._copy_line,
                save=self._save_line, clear=self._clear_history))
        self._history_pop.open_at(self.ed, self.history)

    def open_big(self):
        if self._big_pop is None:
            self._big_pop = saybig.SayBigPopup(self.window(), self.say_line,
                                               self.ctl.stop_speaking)
        self._big_pop.open_at(self.ed, self.ed.text().strip())
        self.ed.clear()

    def open_quick(self):
        """The Quick-type box hotkey: a small box on top of whatever's in front."""
        if self._quick is None:
            from soundboard.control import winkeys
            self._quick = saybig.QuickSayBox(lambda t: self.say_line(t, "quick"),
                                             winkeys.to_front, winkeys.front_window)
        self._quick.pop()

    def _say_again_from_history(self, text: str):
        self.say_line(text, remember=False)

    def _edit_line(self, text: str):
        self.ed.setText(text)
        self.ed.setFocus()

    def _copy_line(self, text: str):
        QGuiApplication.clipboard().setText(text)

    def _clear_history(self):
        self.history.clear()
        self.s[sayhistory.HISTORY_KEY] = []
        self.changed.emit(dict(self.s))

    def _recall_line(self, step: int) -> bool:
        """Up / Down in the bar's box: the lines said before, as in a chat box. Down
        past the newest gives an empty box. False when there's nothing to go to."""
        if not self.history:
            return False
        n = len(self.history)
        i = (n if self._recall < 0 else self._recall) - step
        if i >= n:
            self._recall = -1
            self.ed.clear()
            return True
        i = max(0, i)
        self._recall = i
        self.ed.setText(self.history[i]["text"])
        return True

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
        # ...and the box's own icons at its end (history, long text)
        need += sum(t.sizeHint().width() for t in ed.findChildren(QToolButton))
        want = word if room >= need else ""
        b.setText(shown)
        if b.text() != want:   # changed only when it must (no resize loop)
            b.setText(want)

    def _save_line(self, text: str = ""):
        """Save as sound: `text` (a history row's), else the typed line, else the last
        one said, spoken into a pad."""
        text = text or self.ed.text().strip() or self._last_said
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
        for name in voices:   # custom and language voices only, never Windows' own
            if name.startswith((customvoices.PREFIX, customvoices.piper.PREFIX)):
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
        self.lang_changed.emit()   # the AI voices' Languages cards follow the voices

    def show_custom_voices(self):
        """Open custom voices (VoicePanel's dialog, from AI voices)."""
        self.custom_wanted.emit()

    def _add_voice_server(self):
        """Add a voice server: its voices, found and ticked (voiceaddserver), each saved
        as a .json in the voices folder, so each is a card on AI voices."""
        from soundboard.ui.voice.voiceaddserver import AddServerDialog
        dlg = AddServerDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.saved:
            busy.toast(self, _("✓ Added: loading the voices…"), "ok")
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
