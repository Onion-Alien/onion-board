"""The AI voices card's start and stop: the settings it emits, turning the helper on and
off, what the card says while it starts, runs or fails, and the helper's events. Mixed
into AiVoicePanel (aivoicepanel.py)."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import QWidget

from soundboard.core import errors, usage
from soundboard.ui.kit import theme
from soundboard.i18n import _
from soundboard.speech import aivoice
from soundboard.speech import aivoicelist as avl
from soundboard.ui.voice import art
from soundboard.ui.voice.aivoicebrowser import mine_pixmap
from soundboard.ui.voice.voicefxpanel import PICKED_ART
from soundboard.ui.voice.aivoicecards import art_key, emoji_icon

if TYPE_CHECKING:
    class _Panel(QWidget):
        # what AiVoicePanel itself provides, for the type checker only
        def __getattr__(self, name: str) -> Any: ...
else:
    _Panel = object

log = logging.getLogger("soundboard.ui.voice.aivoicepanel")   # the card's own logger, as before


# what others hear once the AI voice has stopped, by backup key ("Others now hear …")
BACKUP_HEARD = {"voice": _("a built-in voice (still hides yours)"),
                "mic": _("your real voice"), "mute": _("silence")}

# the helper loads in about a second; one still loading after this is stuck (it once
# sat for half a minute, the backup voice on, while the cards seemed to switch)
LOAD_TIMEOUT_MS = 20_000


class AiVoiceRun(_Panel):
    """AiVoicePanel's settings, start / stop and the helper's events."""

    # ------------------------------------------------------------ settings
    def _emit(self):
        self.changed.emit({**self.s, **({"favorites": list(self._favs)} if self._favs
                                        else {})})

    def current_voice(self) -> str:
        """The picked voice's id: the saved one if the add-on has it, else its first."""
        ids = [vo["id"] for vo in self.voices]
        return self.s["voice"] if self.s["voice"] in ids else (ids[0] if ids else "")

    def _voice(self) -> dict:
        vid = self.current_voice()
        return next((vo for vo in self.voices if vo["id"] == vid), {})

    def _show_about(self):
        """The bar under the cards: the picked voice, who it sounds like and about it."""
        vo = self._voice()
        tags = avl.tag_line(vo) if vo else ""
        text = str(vo.get("about") or vo.get("description") or "")
        self.picked_name.setText(str(vo.get("name", "")))
        about = f"{tags}. {text}" if tags and text else tags or text
        self.picked_name.setToolTip(about)
        self.picked_pic.setToolTip(about)
        key = art_key(vo) if vo else ""
        pm = mine_pixmap(vo, PICKED_ART) if avl.is_mine(vo) else \
            art.pixmap(key, PICKED_ART) if key else None
        self.picked_pic.setPixmap(pm or emoji_icon(str(vo.get("emoji") or ""), PICKED_ART)
                                  .pixmap(PICKED_ART, PICKED_ART))
        n = len(self.store.deleted)
        self.b_bin.setText(_("Recently deleted ({n})", n=n))
        self.b_bin.setVisible(n > 0)
        self._mark_tile()
        self._fit_picked()

    def _say(self, text: str):
        self.lbl_sample.setText(text)
        self.lbl_sample.setVisible(bool(text))

    # ------------------------------------------------------------ start / stop
    def is_on(self) -> bool:
        return self.b_start.isChecked()

    def stop(self):
        if self.b_start.isChecked():
            self.b_start.setChecked(False)

    def _toggle(self, on: bool):
        if on and not self.ctl.running:
            if self.module is None:
                self._set_ui(False, "")
                return
            self._retried = False
            if not self._start_helper():
                return
            self._voice_name = self._voice().get("name", "")
            usage.used("ai-voice")   # switched on (never which voice)
            self._set_ui(True, self._starting_text())
        elif not on:
            self._load_timer.stop()
            if self.ctl.running:
                self.ctl.stop()
            self._set_ui(False, "")   # (also when it had already stopped by itself)
        self._mark_tile()

    def _start_helper(self) -> bool:
        self._connected = False      # the helper said hello (it can still fail to load)
        module = self.module
        assert module is not None   # both callers checked
        try:
            self.ctl.start(module, self.current_voice(),
                           self.s["auto_pitch"], self.s["pitch"])
        except RuntimeError as e:
            self._set_ui(False, f"⚠ {errors.plain(e)}")
            return False
        self._load_timer.start()
        return True

    def status(self) -> str:
        """"off", "starting", "on" (others hear the AI voice) or "failed" (the backup
        covers you): for the Voice tab's status bar."""
        return self._status if self.is_on() else "off"

    def voice_title(self) -> str:
        """The running voice's name (the status bar's chip)."""
        return self._voice_name or self._voice().get("name", "")

    def backup_heard(self) -> str:
        return BACKUP_HEARD.get(self.cb_backup.currentData() or "voice", BACKUP_HEARD["voice"])

    def _starting_text(self, retry: bool = False) -> str:
        return (_("starting again…") if retry else _("starting…")) + " " + _(
            "Others now hear {backup}.", backup=self.backup_heard())

    def failure_text(self, error: str = "") -> str:
        error = error.strip().rstrip(".。")   # the sentence adds its own full stop
        return (_("⚠ The AI voice stopped: {error}. Others now hear {backup}. Switch it "
                  "off and on again to try again.", error=error, backup=self.backup_heard())
                if error else
                _("⚠ The AI voice stopped. Others now hear {backup}. Switch it off and on "
                  "again to try again.", backup=self.backup_heard()))

    def _state(self, text: str):
        """The line under the card's words: how it's doing while it's on."""
        self.lbl_state.setText(text)
        self.lbl_state.setVisible(bool(text))
        theme.set_tone(self.lbl_state, "warn" if text.startswith("⚠") else "")

    def _set_ui(self, on: bool, state: str):
        self._status = "starting" if on else "off"
        self.b_start.blockSignals(True)
        self.b_start.setChecked(on)
        self.b_start.blockSignals(False)
        self.b_start.setText(_("On") if on else _("Off"))
        self._mark_tile()
        self.b_update.setEnabled(not on)
        self._state(state)
        self.show_picked_row()
        self._refresh()   # (the switch: usable again once off)
        self.live_changed.emit(on)

    def _on_event(self, ev: dict):
        t = ev.get("type")
        text = str(ev.get("text", ""))
        if t == "hello":
            self._connected = True
        elif t == "status":
            self._state(text)
        elif t == "ready":
            self._load_timer.stop()
            self._status = "on"
            msg = (_("● you sound like {voice}", voice=self._voice_name) if self._voice_name
                   else _("● you sound like the voice"))
            if ev.get("slow"):
                msg += " " + _("⚠ This PC is slow for AI voices: games may stutter. A voice "
                               "changer preset (left) is much lighter.")
            self._state(msg)
        elif t == "stats":
            cpu = f"{float(ev.get('cpu', 0)):.0f}"
            ms = f"{float(ev.get('latency_s', aivoice.LATENCY_S)) * 1000:.0f}"
            self._state(
                _("● you sound like {voice} · CPU {cpu}% · about {ms} ms behind you",
                  voice=self._voice_name, cpu=cpu, ms=ms) if self._voice_name else
                _("● you sound like the voice · CPU {cpu}% · about {ms} ms behind you",
                  cpu=cpu, ms=ms))
        elif t == "timeout":
            if not self.ctl.running or self._status != "starting":
                return
            if not self._retried:            # one more go by itself, as for no call back
                self._retried = True
                log.warning("AI voice helper still loading after %d s; trying once more",
                            LOAD_TIMEOUT_MS // 1000)
                if self._start_helper():
                    self._state(self._starting_text(retry=True))
                return
            log.warning("AI voice helper still loading after %d s; giving up",
                        LOAD_TIMEOUT_MS // 1000)
            self._status = "failed"
            self._failure_error = _("can't load")
            self._state(self.failure_text(self._failure_error))
            self.ctl.give_up()
        elif t == "error":
            self._load_timer.stop()
            self._status = "failed"
            self._failure_error = text
            self._state(self.failure_text(text))
        elif (t == "stopped" and self.ctl.running and not self._connected
              and not self._retried and self.module is not None):
            # the helper never called back (once it sat silent for 30 s, then started
            # fine the next time): one more go by itself before asking you to
            self._retried = True
            log.warning("AI voice helper didn't connect (%s); trying once more", text)
            if self._start_helper():
                self._status = "starting"
                self._state(self._starting_text(retry=True))
        elif t == "stopped" and self.ctl.running:
            self._load_timer.stop()
            if text or self._status != "failed":   # keep the helper's own reason
                self._failure_error = text
            self._status = "failed"
            self._state(self.failure_text(self._failure_error))
