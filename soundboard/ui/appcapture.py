"""The Apps tab's capture, recording and clip editor half (ui/appspanel.py): one
capture per program card, open while it's sent, recorded or its Clip editor listens;
Record's waiting, length cap and saving to Saved clips; the Clip editor opening,
closing and saving.

``AppsTab`` makes one ``AppCapture`` (``AppsTab.capctl``), a QObject it owns, so the
meter timer and the editors' signals aimed at it stop with the tab. Everything here
runs on the UI thread except ``_sink`` (the capture thread)."""
from __future__ import annotations

import html
import logging
import re
import time
import zlib
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject

from soundboard import appaudio, errors, usage
from soundboard.sounds import library
from soundboard.sounds.clipedit import LiveBuffer
from soundboard.engine import SR
from soundboard.i18n import _
from soundboard.sounds.library import MAX_SECONDS, trim_silence
from soundboard.recorder import ArmedRecorder
from soundboard.ui import appstate, busy
from soundboard.ui.approw import AppRow, _route, is_path_key
from soundboard.ui.clipeditor import ClipEditor

if TYPE_CHECKING:
    from soundboard.ui.appspanel import AppsTab

log = logging.getLogger(__name__)

METER_MS = 60
CONNECTING = _("Connecting…")   # a card's status while its capture is starting


class AppCapture(QObject):
    """Capturing, recording and clip editing for one AppsTab (``tab``)."""

    def __init__(self, tab: AppsTab):
        super().__init__(tab)
        self.tab = tab
        self._stopping: list[appaudio.AppCapture] = []   # stopped, maybe not ended yet

    def _poll_capture(self, row: AppRow) -> bool:
        """A capture started without waiting (start(wait=False)): clears *Connecting…*
        once it's up, or stops it and says why. True if it failed."""
        cap = row.capture
        if cap is None:
            return False
        if cap.error:
            row.remember_pending = False
            self._stop_capture(row)
            row.set_sending(False)
            row.set_status(cap.error, error=True)
            log.warning("capturing %s stopped: %s", row.exe, cap.error)
            self.tab._report_active()
            return True
        if cap.ready:
            if row.status_text == CONNECTING:
                row.set_status("")
            if row.remember_pending:
                row.remember_pending = False
                self.tab._remember(row)
        return False

    def _meters(self):
        for row in list(self.tab.rows.values()):
            if row.capture is not None and (row.remember_pending or row.status_text == CONNECTING
                                            or row.capture.error):
                self._poll_capture(row)
        if not self.tab.isVisible() and not any(r.rec for r in self.tab.rows.values()):
            self.tab.meter_timer.stop()   # hidden, nothing to cap: showEvent restarts it
            return
        for row in list(self.tab.rows.values()):
            if row.app is not None:
                live = self.tab.peaks.peak(row.app.pid)
                if live is not None and live > 0:
                    row.last_sound_at = time.monotonic()
            rec = row.rec
            if row.app is not None:
                live = self.tab.peaks.peak(row.app.pid)
                if live is not None and live > 0:
                    row.last_sound_at = time.monotonic()
            if rec is not None:
                secs = rec.seconds
                if secs >= MAX_SECONDS:
                    self._finish_rec(row)
                elif rec.triggered:
                    row.btn_rec.setText(_("Stop  {time}",
                                          time=f"{int(secs // 60)}:{int(secs % 60):02d}"))
                else:
                    row.btn_rec.setText(_("Waiting for sound…"))
            if row.src is not None:
                row.meter.set_level(row.src.level)
                row.src.level *= 0.8
            elif row.app is None:
                row.meter.set_level(0.0)
            else:
                live = self.tab.peaks.peak(row.app.pid)
                row.meter.set_level(row.app.peak if live is None else live)

    # ------------------------------------------------------------------ capture
    # One capture per program, open while it's being sent, recorded, or both.
    def _sink(self, row: AppRow, x):
        """A chunk of the program's audio (on the capture thread)."""
        src = row.src
        if src is not None:
            self.tab.engine.feed_aux(src, x)
        rec = row.rec
        if rec is not None:
            rec.push(x)
        listen = row.listen
        if listen is not None:
            listen.push(x)

    def _open_capture(self, row: AppRow) -> bool:
        if row.capture is not None:
            return True
        if row.app is None:
            return False
        cap = appaudio.AppCapture(row.app.pid, lambda x, r=row: self._sink(r, x),
                                  name=row.app.name)
        if not cap.start(wait=False):   # opening it can take seconds: see _poll_capture
            row.set_status(cap.error or _("Couldn't capture it."), error=True)
            log.warning("capturing %s failed: %s", row.exe, cap.error)
            return False
        row.capture = cap
        log.info("capturing %s (pid %d)", row.exe, row.app.pid)
        return True

    def _close_capture(self, row: AppRow):
        cap, row.capture = row.capture, None
        if cap is not None:
            # without waiting: a capture Windows is still opening takes up to 5 s to
            # notice (that froze the window); shutdown() waits for the stragglers
            cap.stop(wait=False)
            self._stopping = [c for c in self._stopping if c.running] + [cap]
        row.meter.set_level(0.0)

    def _start_capture(self, row: AppRow):
        """Send on: the program's audio goes into the mix."""
        if row.app is None or row.src is not None:
            return
        row.set_status(CONNECTING)   # opening its audio can take a moment (_poll_capture)
        key = ("app", row.key)
        src = self.tab.engine.add_aux(key)
        src.vol = row.vol.value()
        src.monitor = row.chk_hear.isChecked()
        _route(src, row.to)
        row.src = src
        if not self._open_capture(row):
            row.src = None
            self.tab.engine.remove_aux(key)
            row.set_sending(False)
            return
        row.set_sending(True)
        self._poll_capture(row)

    def _stop_send(self, row: AppRow):
        """Send off; the capture stays open while Record is on."""
        src, row.src = row.src, None
        if src is not None:
            self.tab.engine.remove_aux(src.key)
        if row.rec is None and row.listen is None:
            self._close_capture(row)

    def _stop_capture(self, row: AppRow, save: bool = True):
        """Stop everything on this row: sending, and recording (kept if `save`)."""
        self._finish_rec(row, save)
        src, row.src = row.src, None
        if src is not None:
            self.tab.engine.remove_aux(src.key)
        self._close_capture(row)

    # ------------------------------------------------------------------ record
    def _spool_path(self, row: AppRow):
        name = re.sub(r'[^A-Za-z0-9._-]', '_', row.exe)
        if is_path_key(row.key):   # another program of the same name: its own file
            name += f"-{zlib.crc32(row.key.encode()):08x}"
        return library.APP_DIR / f"app-recording-{name}.tmp.wav"

    def _on_rec(self, row: AppRow, on: bool):
        if not on:
            self._finish_rec(row)
            return
        if row.app is None or row.rec is not None:
            row.set_recording(row.rec is not None)
            return
        row.rec = ArmedRecorder(self._spool_path(row))
        if not self._open_capture(row):
            row.rec = None
            row.set_recording(False)
            return
        row.btn_rec.setText(_("Waiting for sound…"))
        # also enforces the length cap while hidden
        self.tab.meter_timer.start(appstate.interval(METER_MS))

    def _finish_rec(self, row: AppRow, save: bool = True):
        rec, row.rec = row.rec, None
        if rec is None:
            return
        row.set_recording(False)
        if save:
            row.set_status(_("Saving the clip…"))
            row.sub.repaint()
        heard = rec.triggered
        data = rec.stop()
        if row.src is None and row.listen is None:
            self._close_capture(row)
        if not save:
            return
        data = trim_silence(data)
        row.set_status("")   # "Saving the clip…" is over: the result is a corner card
        if len(data) < int(0.2 * SR):
            busy.toast(self.tab, html.escape(_("Too short to keep.") if heard else
                                         _("Nothing was recorded: it didn't make a sound.")),
                       "warn")
            return
        error = self._add_clip(row, data)
        if error:   # the window couldn't save it
            busy.toast(self.tab, html.escape(_("Couldn't save the clip: {error}", error=error)),
                       "error")
            return
        self._kept_clip(data)

    def _add_clip(self, row: AppRow, data) -> str:
        """Keep a recording in Saved clips; why it couldn't, or ""."""
        name = (row.app.name if row.app else row.name.text())[:30] or _("App")
        try:
            self.tab.shelf.add(data, f"{name} {time.strftime('%H.%M.%S')}", name)
        except Exception as e:  # noqa: BLE001 - failed audio encoding or disk writes
            log.exception("can't keep recording")
            return errors.plain(e)
        return ""

    # ------------------------------------------------------------------ clip editor
    # Opt-in per card: nothing is built, kept or drawn until its Clip editor is
    # opened, and closing it stops listening (an edited take stays for next time).
    def _has_take(self, row: AppRow) -> bool:
        return row.editor is not None and row.editor.take is not None

    def _on_clip(self, row: AppRow, on: bool):
        if not on:
            self._close_clip(row)
            return
        if row.listen is not None:
            return
        if row.app is None and not self._has_take(row):
            row.set_clip_open(False)
            return
        usage.used("clip-editor")   # the name only (usage.py)
        if row.editor is None:
            row.editor = ClipEditor(self.tab.engine, self.tab.cfg, row)
            row.editor.save_clip.connect(lambda data, whole, r=row: self._save_edit(r, data, whole))
            row.editor.big_toggled.connect(lambda on, r=row: self.tab._set_big(r, on))
            lay = row.layout()
            assert lay is not None   # made in AppRow.__init__
            lay.addWidget(row.editor)
        row.set_clip_open(True)
        row.editor.show()
        if row.app is not None:
            row.listen = LiveBuffer()
            if not self._open_capture(row):
                row.listen = None
        row.editor.set_buffer(row.listen)
        row.btn_forget.setVisible(False)
        self._poll_capture(row)
        self.tab._set_big(row, True)

    def _close_clip(self, row: AppRow):
        if self.tab.big is row:
            self.tab._set_big(row, False)
        row.set_clip_open(False)
        listen, row.listen = row.listen, None
        if row.editor is not None:
            row.editor.set_buffer(None)   # stops playing; an unedited take is let go
            row.editor.hide()
        if listen is not None and row.src is None and row.rec is None:
            self._close_capture(row)
        row.set_sending(row.sending)      # the ✕ comes back

    def _save_edit(self, row: AppRow, data, whole: bool):
        if whole:   # nothing picked out: the dead air at its ends goes
            data = trim_silence(data)
        if len(data) < int(0.05 * SR):
            busy.toast(self.tab, html.escape(_("Nothing but silence there.")), "warn")
            return
        src = (row.app.name if row.app else row.name.text())[:30] or _("App")
        try:
            self.tab.shelf.add(data, f"{src} {time.strftime('%H.%M.%S')}", src)
        except Exception as e:  # noqa: BLE001 - the disk is full, the folder is locked
            log.exception("can't keep the clip")
            busy.toast(self.tab, html.escape(_("Couldn't save it: {error}", error=errors.plain(e))),
                       "error")
            return
        if row.editor is not None:
            row.editor.go_live()
        self._kept_clip(data)

    def _kept_clip(self, data):
        busy.toast(self.tab, _("✓ Kept {seconds}s in Saved clips below: double-click plays it, "
                           "right-click adds it to your Sounds.",
                           seconds=f"{len(data) / SR:.2f}"), "ok",
                   action=(_("Show clips"), self._show_clips))

    def _show_clips(self):
        self.tab.shelf.title.setChecked(True)
        self.tab.list_layout.activate()
        self.tab.scroll_area.ensureWidgetVisible(self.tab.shelf)
        self.tab.shelf.list.setFocus()

    def _shelf_to_sounds(self, data, name: str):
        self.tab.clip_error = ""
        self.tab.clip_ready.emit(data, name)
        self.tab.shelf.error = self.tab.clip_error
