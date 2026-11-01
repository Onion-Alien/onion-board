"""The main window's transport and what plays behind it: the play / pause / stop / seek row,
the playing sound's picture as the board's background (scrolled behind the pads), and a
sound's video: finding it, asking whether to get it, and showing it.

MainWindow makes one ``TransportControl`` (``MainWindow.transctl``); everything here runs
on the UI thread."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, Signal

from soundboard.sounds import videos
from soundboard.audio.engine import SR
from soundboard.i18n import _
from soundboard.ui.kit import worker
from soundboard.ui.window.controller import Controller
from soundboard.ui.sounds.linkbar import PLAY_ID as LINK_ID
from soundboard.ui.kit.widgets import fmt_pos

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

log = logging.getLogger(__name__)


class TransportControl(Controller):
    """The transport, playing background and video of one MainWindow (``mw``)."""
    _video_checked = Signal(int, str, object)   # show_video's look: which click, sid, Path|None

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self._refit_due = False   # a refit for the player bar is on its way
        self._video_ask = 0       # the Video button's latest click: only its answer opens
        self._video_checked.connect(self._open_video)

    def _show_transport(self, playing=None):
        """The player bar: always on the Sounds tab; on the others only while a sound
        plays or is paused, so it can be stopped without going back to the pads (and
        doesn't take the room the rest of the time)."""
        mw = self.mw
        from_tick = playing is not None
        if mw.tabs.currentWidget() is mw.sounds_page and not mw.setctl.settings_open():
            want = True
        else:
            if playing is None:
                playing = mw.engine.playing()
            want = any(sid in mw._meta or sid == LINK_ID for sid in playing)
        if mw.transport.isHidden() == want:
            mw.transport.setVisible(want)
            # fitted again with the bar: on another tab the window gave its room back,
            # and coming to Sounds the bar's name was cut off ("Sound wählen" in 0 px).
            # From the play tick: just after it, not inside it
            if want and hasattr(mw.fitctl, "_fit"):
                if not from_tick:
                    if not mw.fitctl.setup_switching():   # (it fits again next)
                        mw.fitctl._refit()
                elif not self._refit_due:
                    self._refit_due = True

                    def refit():
                        self._refit_due = False
                        mw.fitctl._refit()
                    QTimer.singleShot(0, mw, refit)   # with the window: not after it's gone

    def _scroll_background_board(self, value):
        mw = self.mw
        if not mw.grid.background_image:
            return
        step = getattr(self, "_background_row_step", 0)
        bar = mw._pad_scroll.verticalScrollBar()
        if step:
            snapped = min(round(value / step), bar.maximum() // step) * step
            if snapped != value:
                bar.setValue(snapped)
        mw.grid.update()

    def _update_playing_background(self, playing):
        mw = self.mw
        on = mw.cfg.playing_background
        fitted_height, step = 0, 0
        if on and mw.grid.pads and mw.grid._shape is not None:
            margins = mw.grid.grid.contentsMargins()
            height = mw.grid.natural_pad_h(mw.grid._shape[1])
            spacing = mw.grid.grid.spacing()
            step = height + spacing
            room = mw._pad_scroll.height() - margins.top() - margins.bottom()
            if room >= height:
                rows = max(1, (room + spacing) // step)
                fitted_height = (room - spacing * (rows - 1)) // rows
                step = fitted_height + spacing
        if fitted_height != mw.grid.background_pad_height:
            mw.grid.background_pad_height = fitted_height
            mw.grid.relayout(force=True)
        self._background_row_step = step
        gap = (on, step)
        if getattr(self, "_background_gap", None) != gap:
            self._background_gap = gap
            bar = mw._pad_scroll.verticalScrollBar()
            if not hasattr(self, "_background_scroll_step"):
                self._background_scroll_step = bar.singleStep()
            # The gap belongs outside the viewport, so the backdrop contains
            # every card rather than cutting inside their edges.
            rtl = mw.layoutDirection() == Qt.LayoutDirection.RightToLeft
            mw._pad_scroll.setViewportMargins(12 if on and rtl else 0, 0,
                                               12 if on and not rtl else 0, 0)
            bar.setSingleStep(step or self._background_scroll_step)
        image = ""
        if on:
            # The first active sound owns the backdrop, including while paused.
            # Waiting sounds and a merely selected pad never claim it.
            sid = next((sid for sid in playing if sid in mw._meta), None)
            m = mw.meta(sid) if sid else None
            image = m.image if m else ""
        mw.grid.set_background(image, mw.cfg.playing_background_opacity)
        if image and step and mw._pad_scroll.verticalScrollBar().value() % step:
            self._scroll_background_board(mw._pad_scroll.verticalScrollBar().value())

    def _update_transport(self, playing):
        mw = self.mw
        sid = mw.current
        m = mw.meta(sid) if sid else None
        self._update_video(sid, m, playing)
        enabled = m is not None
        for w in (mw.btn_pp, mw.btn_st, mw.seek, mw.mini_pp, mw.mini_st,
                  mw.mini_seek):
            w.setEnabled(enabled)
        players = mw.editctl.players()
        for p in players:
            p.set_enabled(enabled)
        if not m:
            return
        prog, paused = playing.get(sid, (None, False))
        live = prog is not None
        mw.playctl._set_pp_icon("pause" if live and not paused else "play")
        if not mw.playctl._seeking:
            frac = prog if live else mw.start_frac
            for slider in (mw.seek, mw.mini_seek):
                slider.blockSignals(True)
                slider.setValue(int(frac * 1000))
                slider.blockSignals(False)
            for p in players:
                p.set_seek(int(frac * 1000))
            length = mw.playctl.length(m)
            mw._set_np_time(fmt_pos(frac * length, length))

    def _video_of(self, sid: str | None) -> Path | None:
        """The current sound's video, looked up once per selection, on a thread (it
        reads videos.json and checks the video is there, maybe on a sleeping drive):
        None until it's known."""
        mw = self.mw
        if mw._video_for[0] != sid:
            mw._video_for = (sid, None)
            if sid:
                self._ask_video(sid)
        return mw._video_for[1]

    def _ask_video(self, sid: str):
        mw = self.mw
        if mw._video_asking is not None:   # one at a time: its answer asks for the next
            return
        mw._video_asking = sid

        def look():
            try:
                return sid, videos.get(sid)
            except Exception:  # noqa: BLE001 - never leave _video_asking stuck
                log.debug("video lookup failed", exc_info=True)   # (a sleeping drive)
                return sid, None
        worker.run(look, mw.video_found, "video-lookup", error=(sid, None))

    def _video_found(self, sid: str, path):
        mw = self.mw
        mw._video_asking = None
        now = mw._video_for[0]
        if now != sid:             # another sound was picked meanwhile
            if now:
                self._ask_video(now)
            return
        mw._video_for = (sid, path)
        if mw.btn_video.isHidden() == (path is not None):
            mw.btn_video.setVisible(path is not None)

    def _update_video(self, sid, m, playing):
        mw = self.mw
        path = self._video_of(sid) if m else None
        if mw.btn_video.isHidden() == (path is not None):
            mw.btn_video.setVisible(path is not None)
        w = mw._video_win
        if w is None or not w.isVisible():
            return
        if path is not None and w.sid != sid:   # a newly picked video pad takes it over
            w.show_for(sid, m.name, path)
        shown = mw.meta(w.sid)
        data = mw.audio.get(w.sid)
        if shown is None or data is None:
            w.follow(None, 0.0)
            return
        w.follow(playing.get(w.sid), len(data) / SR, mw.engine.sound_speed)

    def show_video(self):
        """The player's Video button: open the current sound's video (and play the
        sound if it isn't playing). It's looked up again first, on a thread (it reads
        videos.json and checks the video is still there, maybe on a sleeping drive)."""
        mw = self.mw
        sid = mw.current or ""
        self._video_ask += 1
        ask = self._video_ask
        if not sid or mw.meta(sid) is None:
            self._open_video(ask, sid, None)
            return
        worker.run(lambda: (ask, sid, videos.get(sid)), self._video_checked, "video-open",
                   error=(ask, sid, None), owner=mw)

    def _open_video(self, ask: int, sid: str, path):
        mw = self.mw
        if ask != self._video_ask or mw._shut_down:   # clicked again, or the window closed
            return
        if sid != (mw.current or ""):   # another sound was picked meanwhile
            return
        m = mw.meta(sid) if sid else None
        mw._video_for = (mw.current, path)
        if path is None or m is None:
            mw.btn_video.hide()
            mw.toast(_("This sound's video isn't there any more"), "warn")
            return
        if mw._video_win is None:
            try:   # imported here: a build missing QtMultimediaWidgets must still start
                from soundboard.ui.sounds.videowindow import VideoWindow
            except ImportError:
                log.exception("can't show videos")
                mw.btn_video.hide()
                mw.toast(_("Videos can't be shown in this copy of Onion Board"), "warn")
                return
            mw._video_win = VideoWindow(mw)
            mw._video_win.setWindowIcon(mw.windowIcon())
        mw._video_win.show_for(sid, m.name, path)
        if mw.engine.state(sid) is None:
            mw.playctl.toggle_play_pause()
