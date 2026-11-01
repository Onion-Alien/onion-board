"""The Languages card's live voice (`SpeechPanel.livevoice`).

Translating in the background for the AI voice, the voice changer or the language's
own voice (`translate_for`, VoicePanel decides who). Its old Start (a computer voice
saying what you say) is kept but never shown. A
QObject the panel owns, like ui/window/controller.py's: the helper's events stop with the
panel. It builds the Start row and the translation note; the panel places them.
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from soundboard.core import langnames
from soundboard.speech import live, piper, spoken, translation
from soundboard.ui.kit import icons
from soundboard.ui.kit.panel import hint_label
from soundboard.ui.voice.voicefxpanel import _enable
from soundboard.core import achievements, errors
from soundboard.i18n import _

if TYPE_CHECKING:
    from soundboard.ui.voice.speechpanel import SpeechPanel

IDLE_HINT = ""   # nothing to say while it's off: the language cards say the rest
MODELS = [(_("Fast (base.en)"), "base.en"), (_("Fastest (tiny.en)"), "tiny.en"),
          (_("Accurate (small.en)"), "small.en"), (_("Any language (base)"), "base"),
          (_("Any language, accurate (small)"), "small")]


def download_bar() -> QProgressBar:
    """A thin download bar (the theme's `downloadprogress`), hidden until there's one."""
    bar = QProgressBar()
    bar.setObjectName("downloadprogress")
    bar.setRange(0, 1000)
    bar.setTextVisible(False)
    bar.setFixedSize(320, 6)
    bar.setAccessibleName(_("Speech model download"))
    bar.hide()
    return bar


class _StateLabel(QLabel):
    """The Start row's state: tells `fit` when its words change (empty takes no room)."""

    def __init__(self, fit):
        super().__init__(IDLE_HINT)
        self._fit = fit

    def setText(self, text: str):
        super().setText(text)
        self._fit()


class LiveVoice(QObject):
    """Speech recognition (+ translation) running live for one SpeechPanel (``p``)."""
    _event = Signal(dict)          # the helper's / TTS events, hopped onto the UI thread

    def __init__(self, panel: SpeechPanel):
        super().__init__(panel)
        self.p = panel
        self.bg_for = ""             # translating for the "ai" voice, the "fx" changer or
        # the language's own voice ("read")
        self._bg_key: tuple = ()     # (who, language) the running helper was started for
        self._bg_failed: tuple = ()  # the key it last stopped with an error for
        self._said = ""              # the helper's own last error: "stopped" keeps it
        self._bg_warning = False     # lbl_bg shows a ⚠ problem (not a hint)
        panel.ctl.on_event = self._event.emit
        self._event.connect(self._on_event)

        # ---- Start and its state (shown once speech recognition is installed)
        self._installed = False        # speech recognition is in (set_installed)
        self.start_box = QWidget()
        sv = QVBoxLayout(self.start_box)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(8)
        action = QHBoxLayout()
        sv.addLayout(action)
        action.setSpacing(14)
        # the computer voice's own Start: a language card starts it by itself, so the
        # button lives under More options (SpeechPanel puts it there) for talking as the
        # computer voice in your own language
        self.b_live = QPushButton(_("Start the computer voice"))
        icons.set_icon(self.b_live, "mic", "on_accent", "on_accent")
        self.b_live.setCheckable(True)
        self.b_live.setMinimumHeight(40)
        self.b_live.setObjectName("primary")
        self.b_live.toggled.connect(self._toggle_live)
        self.lbl_state = _StateLabel(self._fit_start_box)
        self.lbl_state.setTextFormat(Qt.TextFormat.PlainText)   # shows the module's error text
        self.lbl_state.setObjectName("muted")
        self.lbl_state.setWordWrap(True)
        self.lbl_state.setMinimumWidth(0)
        action.addWidget(self.lbl_state, 1)
        # the speech model's first download (the helper's "download" events)
        self.dl_bar = download_bar()
        sv.addWidget(self.dl_bar, 0, Qt.AlignmentFlag.AlignLeft)

        # ---- translating for another voice: its note and download bar, under Speak in
        self.lbl_bg = hint_label("")
        self.lbl_bg.setTextFormat(Qt.TextFormat.PlainText)     # shows the helper's error text
        self.lbl_bg.hide()
        self.bg_bar = download_bar()   # the same, while translating for another voice

    def set_installed(self, ok: bool):
        """Speech recognition is in (or not): its state row can show."""
        self._installed = ok
        self._fit_start_box()

    def _fit_start_box(self):
        """The state row takes room only while it says something: an empty one left a
        gap between the card's intro and its language cards. (Never shown parentless.)"""
        if self.start_box.parent() is not None:
            self.start_box.setVisible(self._installed and bool(self.lbl_state.text()))

    def _live_args(self) -> list[str]:
        """The live-voice helper's arguments; sets the voice translated lines use."""
        p = self.p
        # only our own models: any other name makes the helper download that repo
        model = p.s["model"] if p.s["model"] in {d for _n, d in MODELS} else MODELS[0][1]
        lang = spoken.spoken(p.s)
        # an English-only model can't hear another language: its "Any language" one
        args = ["--model", spoken.model_for(model, lang), "--language", lang]
        args += live.lighter_args(args[1])   # Use less CPU: a smaller one, if it's there
        m = p._lang_on()
        p.ctl.live_voice = None
        if m is not None and m.installed:
            if not spoken.same(m.language, lang):   # said in it already: just spoken
                if lang != "en":   # the translations go from English: Whisper's first
                    args += ["--task", "translate"]
                args += ["--translate", str(translation.model_dir(m))]
            # its own voice (or a Windows one while it can't be read), never the Say
            # voice: an English one read Chinese out
            p.ctl.live_voice = p._voice_for(m) or None
        return args

    def _toggle_live(self, on: bool):
        p = self.p
        if on and self.bg_for:           # Start takes over from translating for a voice
            self._stop_bg()
        if on and not p.ctl.live:
            m = p._lang_on()
            if m is not None and not m.installed:
                self._set_live_ui(False, _("Download {language} first (above).",
                                           language=langnames.of(m)))
                return
            module = p.module
            assert module is not None   # start_live needs it (it failed on None before too)
            try:
                p.ctl.start_live(module, self._live_args())
            except RuntimeError as e:
                self._set_live_ui(False, f"⚠ {errors.plain(e)}")
                return
            p._warm_for_a_line()   # its first line would otherwise wait for speech
            self._set_live_ui(True, _("starting…"))
        elif not on and p.ctl.live:
            p.ctl.stop_live()
            self._set_live_ui(False, IDLE_HINT)

    # ---- translating for the AI voice or the voice changer (VoicePanel decides)
    def translate_for(self, who: str):
        """Run speech recognition + translation in the background so the voice that's
        on ("ai", "fx", or "read": the language's own voice) speaks the language picked
        under Speak in; "" stops it.
        Text-to-speech's own Start, when on, already does this and wins."""
        p = self.p
        if self.b_live.isChecked():
            who = ""
        m = p.translating() if who else None
        key = (who, m.language) if m is not None else ()
        if not key:
            self._bg_failed = ()      # switched off: the next switch-on tries again
        if key == self._bg_key and (not key or p.ctl.live):
            return
        if key and key == self._bg_failed:
            return        # it stopped with an error: not again on every slider step
        if key and self.bg_for and p.ctl.live and key[1] == self._bg_key[1]:
            # the other voice took over: same helper, only the real-mic mute changes
            self.bg_for, self._bg_key = who, key
            p.ctl.set_replace(who in ("fx", "read"))
            return
        if self.bg_for:
            self._stop_bg()
        if not key:
            p._refresh_translation()
            return
        module = p.module
        assert module is not None   # start_live needs it (it failed on None before too)
        try:
            # the voice changer or the language's own voice: your real voice is muted
            p.ctl.start_live(module, self._live_args(), replace=who in ("fx", "read"))
        except RuntimeError as e:
            self._bg_note(_("⚠ Couldn't start translating: {error}", error=errors.plain(e)),
                          warning=True)
            return
        self.bg_for, self._bg_key = who, key
        voice, tts = p.ctl.live_voice or "", p.ctl.tts
        if voice.startswith(piper.PREFIX) and hasattr(tts, "warm_language"):
            threading.Thread(target=tts.warm_language, args=(voice,),
                             name="language-voice-warmup", daemon=True).start()
        self._bg_note(_("Starting the translation…"))
        p._refresh_translation()

    def _stop_bg(self):
        self.bg_for, self._bg_key, self._bg_failed = "", (), ()
        self.p.ctl.stop_live()
        self._bg_note("")
        self.bg_bar.hide()

    def _bg_note(self, text: str, warning: bool = False):
        self.lbl_bg.setText(text)
        self._bg_warning = warning and bool(text)
        self.lbl_bg.setVisible(bool(text))

    def _set_live_ui(self, on: bool, state: str):
        p = self.p
        self.b_live.blockSignals(True)
        self.b_live.setChecked(on)
        self.b_live.blockSignals(False)
        p.live_changed.emit(on)
        # talking in another language: its time counts (Lost in Translation)
        achievements.live("translate", on and bool(p.cb_lang.currentData()))
        for w in (p.cb_model, p.ed_lang, p.cb_lang):
            _enable(w, not on, _("Stop the computer voice to change this"))
        _enable(p.installs.b_update, not on,
                _("Stop the computer voice to change this") if on
                else _("Waiting for the install to finish"))
        _enable(p.installs.b_remove, not on, _("Stop the computer voice to change this"))
        self.lbl_state.setText(state)
        if not on:
            self.dl_bar.hide()
        p._refresh_translation()

    def show_button(self, language: str, other_on: bool):
        """Start's words follow Speak in: the language it speaks, or the computer voice
        taking over from the AI voice or the voice changer (`other_on`)."""
        if self.b_live.isChecked():
            text = (_("Stop speaking {language}", language=language) if language
                    else _("Stop the computer voice"))
        elif other_on:
            text = _("Use the computer voice instead")
        else:
            text = (_("Start speaking {language}", language=language) if language
                    else _("Start the computer voice"))
        self.b_live.setText(text)
        self.b_live.setAccessibleName(text)
        # taking over from a voice that's on is a side choice, not the next step
        main = "" if other_on and not self.b_live.isChecked() else "primary"
        if self.b_live.objectName() != main:
            self.b_live.setObjectName(main)
            icons.set_icon(self.b_live, "mic", "on_accent" if main else "text",
                           "on_accent" if main else "text")
            self.b_live.style().unpolish(self.b_live)
            self.b_live.style().polish(self.b_live)
        if not self.b_live.isChecked() and self.lbl_state.text() in ("", IDLE_HINT):
            self.lbl_state.setText("" if other_on else IDLE_HINT)

    def _download_note(self, ev: dict) -> str:
        """A "download" event: its bar filled, the words that go with it."""
        done, total = int(ev.get("done") or 0), int(ev.get("total") or 0)
        bar = self.bg_bar if self.bg_for else self.dl_bar
        bar.setValue(min(1000, done * 1000 // total) if total > 0 else 0)
        bar.show()
        return _("Downloading the speech model (one time only)… {done} of {total} MB",
                 done=done // 1_000_000, total=total // 1_000_000)

    def _on_event(self, ev: dict):
        p = self.p
        t = ev.get("type")
        text = str(ev.get("text", ""))
        if t != "download":
            (self.bg_bar if self.bg_for else self.dl_bar).hide()
        if t == "error":
            self._said = text
        elif t == "ready":
            self._said = ""
        elif t == "stopped":
            text, self._said = text or self._said, ""   # its reason, if it gave one
        if self.bg_for and t != "tts_error":
            self._on_bg_event(t, text, ev)
            return
        if t == "download":
            self.lbl_state.setText(self._download_note(ev))
        elif t == "tts_error":
            p._tts_error(_("Couldn't speak that line: {error}", error=text))
        elif t == "status":
            self.lbl_state.setText(text)
        elif t == "ready":
            self.lbl_state.setText(_("● listening"))
        elif t == "vad":
            self.lbl_state.setText(_("● hearing you…") if ev.get("speaking")
                                   else _("● listening"))
        elif t == "final" and text:
            orig = str(ev.get("original", ""))
            p._log_said(_("{text}   (you said: {original})", text=text, original=orig)
                        if orig else text)
        elif t == "error":
            self.lbl_state.setText(f"⚠ {text}")
        elif t == "stopped":
            self._set_live_ui(False, _("⚠ stopped: {error}", error=text) if text
                              else _("stopped"))

    def _on_bg_event(self, t, text: str, ev: dict):
        p = self.p
        name = self._bg_key[1] if self._bg_key else ""
        m = p._lang()
        name = langnames.of(m) if m is not None else name
        if t == "download":
            self._bg_note(self._download_note(ev))
        elif t == "ready" or (t == "vad" and not ev.get("speaking")):
            self._bg_note(_("● Listening: say it in your language, it comes out in {language}.",
                            language=name))
        elif t == "vad":
            self._bg_note(_("● Hearing you…"))
        elif t == "status":
            self._bg_note(text)
        elif t == "final" and text:
            orig = str(ev.get("original", ""))
            p._log_said(_("{text}   (you said: {original})", text=text, original=orig)
                        if orig else text)
        elif t == "error":
            self._bg_note(f"⚠ {text}", warning=True)
        elif t == "stopped":
            self._bg_failed = self._bg_key
            self.bg_for, self._bg_key = "", ()
            self._bg_note(_("⚠ Translating stopped: {error}", error=text) if text
                          else _("Translating stopped."), warning=bool(text))
            p._refresh_translation()
