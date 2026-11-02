"""The main window's tick: the timer that moves its meters, the now-playing time and the
pads' progress, how fast it runs (24 a second while something moves and the window is
seen, slower when quiet, hidden or behind a game), waking it, and what it updates.

MainWindow makes one ``TickControl`` (``MainWindow.tickctl``); everything here runs on the
UI thread."""
from __future__ import annotations

import collections
import time
from typing import TYPE_CHECKING

import numpy as np
from shiboken6 import isValid

from soundboard.core import achievements, memtrim
from soundboard.sounds import thumbs
from soundboard.control import winkeys
from soundboard.audio.groove import Groove
from soundboard.audio.sendfx import CEILING_DB
from soundboard.i18n import _
from soundboard.ui.settings import lite
from soundboard.style.owl import OwlWidget
from soundboard.ui.bun.bunnywidget import BunnyWidget
from soundboard.ui.window.controller import Controller
from soundboard.ui.sounds.linkbar import PLAY_ID as LINK_ID
from soundboard.ui.window.livedot import set_tab_live
from soundboard.ui.kit.widgets import loudness, spectrum

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

TICK_MS = 1000 // 24  # the UI timer while the window is on screen (meters, visualisers)
TICK_QUIET_MS = 100  # on screen with nothing moving: no sound, radio, recording or level
TICK_IDLE_MS = 250   # ...and while it's in the tray or minimised (push-to-talk, watchdog)
TICK_LITE_MS = 1000 // 15   # lite mode (ui/settings/lite.py): on screen and busy...
TICK_LITE_QUIET_MS = 200    # ...and quiet (the mic meters still follow, 5 times a second)
LEVEL_FALL = 0.88     # what the levels keep a tick (at 24 a second: as fast a fall as 0.9 at 30)
LEVEL_QUIET = 0.003  # a level below this (-50 dB) shows as nothing on the meters
LEVEL_VOICE = 0.02   # the mic above this (-34 dB) is a voice, not the room: full pace
RADIO_LAG = 0.1      # seconds between the radio's audio arriving and it being heard


class TickControl(Controller):
    """The tick of one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self._tick_n = 0                  # ticks since start (the watchdog runs ~once a second)
        self._tick_busy = True            # something moves with the tick (see _busy)
        self._pads_lit: set[str] = set()  # pads showing a sound (see _tick_visuals)
        self._sounds_live = False         # the Sounds tab's live dot is shown
        self._talk_until = 0.0            # "hearing you" indicator holds until this time
        self._talk_shown: bool | None = None
        self.groove = Groove()            # what plays, for the mascots on screen (_dance)
        self._tray_since: float | None = None   # hidden or minimised then (_give_back)
        self._given_back = False          # ...and memory was given back since

    def _tick_pace(self) -> int:
        mw = self.mw
        if not mw._ui_live and not mw.overlay.is_open and not mw.bunctl.bun_up():
            return TICK_IDLE_MS
        if not self._tick_busy:   # nothing moves: 10 ticks a second instead of 24
            return TICK_LITE_QUIET_MS if lite.on() else TICK_QUIET_MS
        # Visible and busy: meters stay smooth even when a game has focus.
        return TICK_LITE_MS if lite.on() else TICK_MS

    def _wake(self):
        """A sound started or resumed: full pace now, not after a quiet tick (auto
        push-to-talk presses its key from the tick)."""
        mw = self.mw
        if not self._tick_busy:
            self._tick_busy = True
            pace = self._tick_pace()
            if mw.timer.interval() != pace and not mw._shut_down:
                mw.timer.start(pace)
        # the PTT key goes down with the sound, not on the next tick: minimised, that's up
        # to TICK_IDLE_MS later, and a game that only sends while it's held cut the start
        if not mw._shut_down:
            self._sync_ptt()

    def _busy(self, playing) -> bool:
        """Something on screen moves with the tick: a sound playing (not paused), the
        radio, a meter or the mic level still showing. The mic only counts while it
        hears a voice (LEVEL_VOICE): most mics hear the room above LEVEL_QUIET, which
        kept the tick at full pace for as long as the window was open; the room's
        meters follow at the quiet pace. In lite mode the mic doesn't count at all."""
        mw = self.mw
        e = mw.engine
        if (any(not paused for _p, paused in playing.values())
                or mw.radio.is_active() or bool(e.aux)):
            return True
        if e.level_play > LEVEL_QUIET:
            return True
        if lite.on():   # (what others hear is the mic too, with nothing playing)
            return False
        return max(e.level_main, e.level_mic if e.mic_stream is not None else 0.0) > LEVEL_VOICE

    def _set_tick_rate(self, *__):
        mw = self.mw
        live = mw.isVisible() and not mw.isMinimized()
        was, mw._ui_live = mw._ui_live, live
        if live:
            self._tray_since, self._given_back = None, False
        elif self._tray_since is None and not self._given_back:
            self._tray_since = time.monotonic()
        pace = self._tick_pace()
        if (live == was and mw.timer.interval() == pace) or getattr(mw, "_shut_down", False):
            return
        mw.timer.start(pace)
        if not live:   # a level frozen mid-flight would show as stuck on the next show
            mw.out_meter.set_level(0.0)
            mw.mic_meter.set_level(0.0)
            if not mw.isVisible():   # to the tray: the pads' pictures are made again
                thumbs.trim()          # from their small files when it's back

    def tick(self):
        mw = self.mw
        if mw._shut_down:   # a tick already queued when the window shut down
            return
        e = mw.engine
        now = time.monotonic()
        self._tick_n += 1
        if self._tick_n % max(1, 1000 // mw.timer.interval()) == 0:   # about once a second
            if mw.cfg.route == "mic":
                mw.micctl._follow_mic_effect()
            mw.micctl.keep_sonar()
            if e.check_streams() or sum(e.xruns.values()) != mw.statusctl._xruns_shown:
                mw.statusctl._update_status()
            elif mw.cfg.route == "mic" and mw.micctl._direct_health() != mw._direct_shown:
                mw.statusctl._update_flow()
            mw.voice.poll()
        if e.howl_stopped:   # the mic squealed through the speakers (soundboard.audio.howl)
            e.howl_stopped = False
            mw._howl_stopped()
        playing = e.playing()
        if mw.playctl._queue and LINK_ID not in playing and not any(sid in mw._meta
                                                              for sid in playing):
            mw.playctl._next_in_queue()   # it waits for a web search's song too
            playing = e.playing()
        if (LINK_ID not in playing and mw.linkbar.up_next()
                and not mw.playctl._board_song_playing(playing) and mw.linkbar.play_next()):
            playing = e.playing()   # the web search song ended: the next one waiting
        live = any((sid in mw._meta or sid == LINK_ID) and not paused   # a web search's
                   for sid, (_p, paused) in playing.items())                # Play too
        if live != self._sounds_live:   # the Sounds tab glows while a sound plays
            self._sounds_live = live
            set_tab_live(mw.tabs, mw.tabs.indexOf(mw.sounds_page), live,
                         _("● ON: a sound is playing"), "sounds")
        # the taskbar preview's Pause button turns into Play while all of it is paused
        # (a station Pause stopped counts as paused, until anything plays again)
        if live or mw.radio.is_active():
            mw._radio_paused = None
        mw.thumbbar.set_paused(not live and not mw.radio.is_active() and (
            mw._radio_paused is not None or any(
                paused for sid, (_p, paused) in playing.items()
                if sid in mw._meta or sid == LINK_ID)))
        self._tick_busy = self._busy(playing)
        if self._tray_since is not None and now - self._tray_since > memtrim.AFTER_S:
            self._give_back(playing)
        pace = self._tick_pace()
        if mw.timer.interval() != pace:
            mw.timer.start(pace)
        if mw._ui_live:
            self._tick_visuals(playing, now)
        mw.overlay.tick(playing)
        achievements.heard({sid: prog for sid, (prog, _p) in playing.items()
                            if prog is not None and (m := mw._meta.get(sid)) is not None
                            and not m.loop and m.duration >= achievements.HOUR})
        self._dance(playing, now)
        if mw.bunctl.bun_mode is not None and mw.bunctl.bun_mode.isVisible():
            bar = mw.download_bar
            song = next(((mw.audio.get(sid), prog) for sid, (prog, paused) in playing.items()
                         if (sid in mw._meta or sid == LINK_ID) and not paused
                         and prog is not None), None)   # (what he dances to)
            mw.bunctl.bun_mode.tick(song=song,
                live=live, level=e.level_play, sending=e.sending, mic=mw.cfg.mic_enabled,
                paused=any(paused for sid, (_p, paused) in playing.items()
                           if sid in mw._meta or sid == LINK_ID),
                downloading=bar.running(), failed=bar.failed_count())
        e.level_play *= LEVEL_FALL
        e.level_main *= LEVEL_FALL
        e.level_mic *= LEVEL_FALL

        self._sync_ptt()

    def _give_back(self, playing):
        """In the tray or minimised a while: memory back to Windows (memtrim), once
        each time, when nothing plays (the audio thread would read the pages back)."""
        mw = self.mw
        if (any(not paused for _p, paused in playing.values()) or mw.radio.is_active()
                or mw.engine.aux):
            return   # try again on a later tick
        self._tray_since, self._given_back = None, True
        memtrim.release()

    def _dance(self, playing, now: float):
        """The mascots on screen (Bun on an empty page, Hoot) dance to what plays: the
        sound playing, else the radio."""
        mw, e = self.mw, self.mw.engine
        dancers = [w for w in (*BunnyWidget.dancers, *OwlWidget.dancers)
                   if isValid(w) and w.isVisible()]   # (Qt may have deleted one)
        on_radio = bool(dancers) and mw.radio.is_active()
        if on_radio and e.radio_tap is None:
            e.radio_tap = collections.deque(maxlen=200)
        elif not on_radio:
            e.radio_tap = None
        if not dancers:
            return
        song = next(((mw.audio.get(sid), prog) for sid, (prog, paused) in playing.items()
                     if (sid in mw._meta or sid == LINK_ID) and not paused
                     and prog is not None and mw.audio.get(sid) is not None), None)
        g: Groove | None = self.groove
        if song is not None:
            self.groove.feed(song[0], song[1], now)
        elif on_radio and e.radio_tap:
            tap = e.radio_tap
            chunks = [tap.popleft() for _i in range(len(tap))]
            # (it goes out through a short buffer: heard about RADIO_LAG after it's read)
            self.groove.feed_live(np.concatenate(chunks), now, RADIO_LAG)
        elif not on_radio:
            g = None
        for w in dancers:
            w.set_groove(g)

    def _sync_ptt(self):
        """Auto push-to-talk: hold the game's PTT key only while a sound (or live
        radio / a program) goes out. _ptt_held remembers exactly which key we pressed, so it's
        always released even if the setting changes mid-sound."""
        mw = self.mw
        e = mw.engine
        on_air = e.sending and (e.any_playing() or e.radio_on_air()
                                or e.aux_on_air())
        want = mw.cfg.ptt_key if (mw.cfg.ptt_key and on_air) else None
        if mw._ptt_held:
            if winkeys.ptt_held() != mw._ptt_held:
                mw._ptt_held = None   # let go while this thread was stuck: pressed again
            else:
                winkeys.ptt_alive()
        if want != mw._ptt_held:
            if not mw.hkctl._release_ptt():
                return   # still held: try the key-up again next tick
            if want and winkeys.ptt_down(want):
                mw._ptt_held = want

    def _heard_level(self) -> float:
        """The "What others hear" meter. Sending into the mic but not in it yet (no mic
        effect): voice apps still take the real mic as it is, so others hear your voice
        even with nothing sent (the meter showed nothing while you talked), and none of
        the sounds (it moved with them, as if they went out)."""
        mw = self.mw
        e = mw.engine
        if mw.cfg.route == "mic" and not e.main_direct and e.mic_stream is not None:
            return e.level_mic
        return e.level_main

    def _tick_visuals(self, playing, now: float):
        """The part of tick() that only matters while the window is on screen."""
        mw = self.mw
        e = mw.engine
        mw.transctl._update_playing_background(playing)
        on_board = mw.tabs.currentWidget() is mw.sounds_page   # no visualiser off-screen
        shown = mw.isVisible()
        # only the pads playing now and the ones still showing a sound (cleared on the
        # tick after it stops): going over all of them, 30 times a second, cost more
        # than the rest of the tick on a big board with nothing playing
        pads, lit = mw.pads, set()
        for sid in self._pads_lit.union(playing):
            p = pads.get(sid)
            if p is None:   # not a pad (a preview, the test recording) or gone
                continue
            prog, paused = playing.get(sid, (None, False))
            if prog is not None and not paused and on_board and not p.isHidden():
                # scrolled out of view: skip the FFT (the next tick after it scrolls
                # back in catches up)
                if not (shown and p.visibleRegion().isEmpty()):
                    data = mw.audio.get(sid)
                    p.set_levels(spectrum(data, prog, p.n_bands))
                    p.set_meter(loudness(data, prog, mw.gain_for(p.meta)))
            elif prog is None and p.bands is not None:
                p.set_levels(None)
                p.set_meter(None)
            if prog != p.progress or paused != p.paused:
                p.progress, p.paused = prog, paused
                p.update()
            if p.progress is not None or p.bands is not None:
                lit.add(sid)
        self._pads_lit = lit
        mw.transctl._update_transport(playing)
        mw.transctl._show_transport(playing)
        if not mw.ytresults.isHidden():   # the result in the player says so
            prog, paused = playing.get(LINK_ID, (None, False))
            mw.ytresults.show_now(mw.searchctl._link_url, "" if prog is None else
                                    "paused" if paused else "playing")
        mw.playctl._update_chips(playing)
        # held at the limiter's ceiling, it never reached the red zone
        mw.out_meter.top_db = CEILING_DB if e.limiter_on else 0.0
        mw.out_meter.set_level(self._heard_level())
        mw.logo.set_level(e.level_play)   # anything playing, not your voice
        mw.mic_meter.set_level(e.level_mic if e.mic_stream else 0.0)
        if mw.card_meter.isVisible():
            mw.card_meter.set_level(e.level_mic if e.mic_stream else 0.0)
        if mw.voice_meter.isVisible():
            mw.voice_meter.set_level(e.level_mic if e.mic_stream else 0.0)
        talking = e.mic_stream is not None and e.level_mic > 0.05
        if talking:
            self._talk_until = now + 0.8
        talking = now < self._talk_until
        if talking != self._talk_shown:
            self._talk_shown = talking
            mw.statusctl._update_flow(talking)
