"""The main window's settings changes: set_option and saving, the light voice switch, the
EQ, always on top, pad width, single click, and the master switch (set_sending)."""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt

from soundboard import voicefx
from soundboard.ui.window import sidebar
from soundboard.ui.kit.widgets import Pad
from soundboard.i18n import _

from soundboard.ui.window.windowparts import WindowParts
log = logging.getLogger("soundboard.ui.window.mainwindow")


class WindowOptions(WindowParts):
    """MainWindow's option setters and saving (a mixin)."""

    def on_eq(self, gains, enabled, target, preset):
        c = self.cfg
        c.eq_enabled, c.eq_target, c.eq_preset, c.eq_gains = enabled, target, preset, list(gains)
        self.engine.eq_target = target
        self.engine.eq_gains = list(gains) if enabled else None
        self._save_later()

    # ------------------------------------------------------------------ settings
    def set_option(self, attr: str, v):
        """Change one config value (mirrored onto the engine when it has the same
        attribute) and save shortly after. The small public surface the Settings
        window and dialogs use."""
        setattr(self.cfg, attr, v)
        if attr in ("playing_background", "playing_background_opacity"):
            self.transctl._update_playing_background(self.engine.playing())
        if hasattr(self.engine, attr):
            setattr(self.engine, attr, v)
        self._save_later()

    def light_voice_on(self) -> bool:
        """Use less CPU for the voice features: the switch's choice, or lite mode's."""
        c = self.cfg.light_voice
        return c == "on" or (c == "auto" and self.cfg.lite_mode)

    def apply_light_voice(self):
        """The effects (next mic block) and the Voice tab's switch follow
        light_voice_on(); the speech helpers take it at their next start."""
        on = self.light_voice_on()
        voicefx.set_light(on)
        v = getattr(self, "voice", None)   # (the tab can be off)
        if v is not None and hasattr(v, "set_light"):
            v.set_light(on)

    def set_light_voice(self, on: bool):
        """The Voice tab's Use less CPU switch: the user's own choice from now
        on, whatever lite mode says."""
        self.set_option("light_voice", "on" if on else "off")
        self.apply_light_voice()

    def _save_later(self):
        self._save_timer.start(100)   # short: a crash loses at most this much

    def _save_now(self, then=None):
        """The debounced save: the settings are copied now and written on the saver's
        thread (library.Saver), then _on_saved says how it went. `then(ok)` is called on
        the UI thread once this copy (or a newer one) is written, or failed to be."""
        self._saver.cfg = self.cfg
        self._saver.save(then)

    def _on_saved(self, ok: bool):
        """A failure (disk full, antivirus lock) is logged by the writer; here it's
        shown once so the user knows settings aren't sticking."""
        for then, was_ok in self._saver.finished():   # _save_now(then)s now on disk (or not)
            try:
                then(was_ok)
            except Exception:  # noqa: BLE001 - one mustn't stop the report
                log.exception("after saving settings")
        if ok:
            self._save_failed_shown = False
        elif not self._save_failed_shown:
            self._save_failed_shown = True
            self.toast(_("Couldn't save your settings, see the log in %APPDATA%\\OnionBoard."),
                       "error")

    def on_level_toggle(self, b):
        self.set_option("level_volumes", b)
        for m in self.cfg.sounds:
            self.engine.set_gain(m.id, self.gain_for(m))

    def on_top_toggle(self, b):
        self.set_option("always_on_top", b)
        handle = self.windowHandle()
        if handle is None or not self.isVisible():
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, b)
            self.show()
            return
        # on the window as it is: setWindowFlag makes a new native window, and the
        # window went white for a frame (and lost its place in the taskbar) while it did
        flags = self.windowFlags()
        flags = (flags | Qt.WindowType.WindowStaysOnTopHint) if b \
            else (flags & ~Qt.WindowType.WindowStaysOnTopHint)
        self.overrideWindowFlags(flags)   # what Qt thinks the widget has...
        handle.setFlags(flags)            # ...and the window itself, changed in place

    def set_pad_width(self, w):
        self._pad_size_wait.stop()
        self.cfg.pad_width = w
        self.grid.set_pad_width(w)
        self._save_later()

    # ------------------------------------------------------------------ hotkeys
    def set_single_click(self, on: bool):
        """Settings -> General: one click on a pad plays it."""
        self.set_option("single_click", on)
        Pad.single_click = on

    def set_sending(self, on: bool):
        """The master switch, "Others hear": on (others hear your mic and whatever is
        live) or off (they hear nothing at all, or only your plain voice while your mic is
        sent and no voice changer is on: engine.mic_only). Everything keeps playing for
        you. Not saved: the app always opens live, so nobody's left wondering why they're
        silent."""
        self.engine.sending = on
        self.playctl.sending_changed(on)
        if self.btn_air.isChecked() != on:
            self.btn_air.setChecked(on)   # comes back here
            return
        # sending nowhere (or the send device is the headphones): Live doesn't claim
        # others hear you; muting still silences the stream output, if there is one
        others = self.routectl._main_name() is not None
        stream = bool(self.engine.names["obs"])
        voice = not on and others and self.engine.mic_only()
        self.btn_air.setProperty("voiceonly", voice)   # the rail's word: sidebar.names
        if voice:
            text = (_("Others hear only your mic"), _("Only your mic"), "")
        elif not on:
            text = (_("Muted: others hear nothing"), _("Muted"), "")
        elif others:
            text = (_("On: others hear you and your sounds"), _("On"), "")
        elif stream:
            text = (_("On: only the stream hears your sounds"), _("On"), "")
        else:
            text = (_("Only you hear sounds"), _("Only you"), "")
        # one short word ("On") on the open rail; the whole sentence leads its tooltip and
        # is what a screen reader says
        if voice:
            tip = _("Click to send your sounds again: right now others hear only your mic")
        elif not on:
            tip = _("Click so others hear you and your sounds again")
        elif others:
            tip = (_("Click to mute your sounds for others (Discord, the game, OBS…). Your "
                     "mic still goes out unless a voice changer is on. You still hear "
                     "everything"))
        elif stream:
            tip = (_("Nothing goes out to others, only to the stream output. Click to mute that "
                     "too (you still hear everything)"))
        else:
            tip = (_("Nothing goes out to others: pick where to send on the Setup tab (Send my "
                     "sounds to)"))
        if self._pill_good and self._pill_long:   # the hidden pill's "In your mic…"
            tip = f"{self._pill_long}\n{tip}"
        sidebar.put(self.btn_air, text[1], text[0], tip)
        if hasattr(self, "thumbbar"):
            self.thumbbar.set_live(on)
        if hasattr(self, "mini_air"):
            self.mini_air.setChecked(on)
            self.mini_air.setToolTip(self.btn_air.toolTip())
