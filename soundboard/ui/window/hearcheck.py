"""Hear what they hear (the mic check): the switch, the speakers warning and the squeal stop
(soundboard.audio.howl)."""
from __future__ import annotations

import html
import logging
import threading


from soundboard.ui.kit import theme
from soundboard.audio import appaudio, howl
from soundboard.ui.kit import busy
from soundboard.i18n import _

from soundboard.ui.window.windowparts import WindowParts
log = logging.getLogger("soundboard.ui.window.mainwindow")


class HearCheck(WindowParts):
    """MainWindow's Hear what they hear (a mixin)."""

    # ------------------------------------------------------------------ test mode
    def on_mic_check(self, on):
        self.engine.ring_mon.clear()
        self.engine.mic_check = on
        text = _("Stop hearing it") if on else _("Hear what they hear")
        short = _("Stop") if on else _("Listen")
        self.btn_check.setProperty("full_text", text)   # what a compact window restores
        self.btn_check.setProperty("short_text", short)   # ...and what it shows meanwhile
        self.btn_check.setAccessibleName(text)
        self.btn_check.setText(short if self.btn_check.property("compact") else text)
        self.mic_lbl.setStyleSheet(f"color:{theme.status('error')};" if on else "")
        self.mic_meter.hot = on
        if on and not self.cfg.mic_enabled:
            self.say(_("<span style='color:{status}'>Sounds only: your mic isn't "
                       "sent, so nobody (including you) hears it.</span>",
                       status=theme.status('warn')), "warn", key="sounds-only")
        if on and self.engine.names.get("mon"):   # (no answer off Windows)
            self._check_speakers(self.engine.names["mon"])
        if not on:
            self.unsay("speakers")

    def _check_speakers(self, name: str):
        """Hear what they hear on speakers: the mic hears them, and loud enough it
        squeals. Windows is asked on a thread what the headphones output really is."""
        def work():
            try:
                ffs = appaudio.output_form_factors()
            except Exception:  # noqa: BLE001 - only a warning: never fail loudly
                log.debug("asking for the outputs' form factors failed", exc_info=True)
                return
            if howl.is_speaker(name, ffs):
                busy.emit(self.device_step, lambda: self._warn_speakers(name))
        threading.Thread(target=work, name="speaker-check", daemon=True).start()

    def _warn_speakers(self, name: str):
        if not self.engine.mic_check or self.engine.names.get("mon") != name:
            return   # switched off, or moved to other headphones, meanwhile
        self.say(_("<b>{device}</b> looks like speakers, so your mic hears itself. Keep "
                   "them quiet or use headphones. If it starts to squeal, this switches "
                   "off by itself.", device=html.escape(name)), "warn", ms=10000,
                 key="speakers")

    def _howl_stopped(self):
        """The engine heard the mic squeal through the speakers and stopped playing
        it back (soundboard.audio.howl): untick the switch to match and say why."""
        self.unsay("speakers")
        self.btn_check.setChecked(False)   # -> on_mic_check
        self.say(_("Stopped <b>Hear what they hear</b>: your mic was picking up your "
                   "speakers and started to squeal. Use headphones, or turn the speakers "
                   "down."), "warn", ms=12000, key="howl")
