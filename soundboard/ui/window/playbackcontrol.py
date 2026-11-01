"""Playing sounds in the main window: a pad played (or queued, or waiting its turn), Up next
and its chips, Space, select, play / pause, stop one or all, skip, seek, play the last
one again, a random sound, the headphones-only cue beep, and the effects preview.

MainWindow makes one ``PlaybackControl`` (``MainWindow.playctl``); everything here runs on
the UI thread."""
from __future__ import annotations

import html
import time
from typing import TYPE_CHECKING, Any

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPushButton
from shiboken6 import isValid as qt_valid

from soundboard.sounds import library
from soundboard.audio import soundfx
from soundboard.ui.kit import theme
from soundboard.core import achievements, usage
from soundboard.audio.engine import SR
from soundboard.i18n import _
from soundboard.sounds.library import PRESS_MODE, load_original
from soundboard.audio.shuffle import ShuffleBag
from soundboard.ui.kit import icons, worker
from soundboard.ui.window import sidebar
from soundboard.ui.window.controller import Controller
from soundboard.ui.sounds.linkbar import PLAY_ID as LINK_ID
from soundboard.ui.window.upnext import UpNextChip, UpNextPopup, Waiting
from soundboard.ui.kit.widgets import fmt_pos

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

# an effects preview of a sound longer than this renders only its first PREVIEW_S
# (soundfx.preview_part): a 2-hour song's pitch shift took minutes to start playing
PREVIEW_WHOLE_S = 5 * 60
PREVIEW_S = 30
CHIPS_GAP = 6         # between the now-playing row's chips
CHIPS_ROW_H = 30      # the now-playing row: a chip's 24 px ■ button, its margins and border
WANTED_S = 10.0       # a sound pressed while it loads still plays once loaded within this


def _nothing():
    """Space with nothing to play (PlaybackControl._space_action)."""


class PlaybackControl(Controller):
    """Playing sounds for one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        # play counts and Ctrl+wheel volumes: saved within a few seconds, not on each press
        # (a spammed hotkey wrote the whole config every time); closing saves the rest
        self._count_save = QTimer(mw, singleShot=True, interval=5000)
        self._count_save.timeout.connect(mw._save_now)
        self.shuffle = ShuffleBag()       # the random-sound hotkeys
        self._last_sid: str | None = None   # the last sound played (its replay hotkey)
        self._queue: list[str] = []       # sounds waiting for the ones playing to finish
        self._stopped_at = (0.0, "")       # (when, which) a ■ for one sound last stopped
        self._cool: dict[str, float] = {}   # sid -> time.monotonic() its cooldown ends
        self._waiting: dict[str, list[QTimer]] = {}   # sid -> its delayed starts
        self._wanted: dict[str, float] = {}   # sid -> when it was pressed while still loading
        self._preview_gen = 0            # newest effects preview (older renders are dropped)
        self._preview_done = None         # its done(ok) callback while it renders
        # what each sound's preview plays: (its effects, the share of the whole it starts
        # at and the share it covers: a long sound's is only its first part)
        self.preview_of: dict[str, tuple[dict, float, float]] = {}
        self._preview_info: tuple | None = None   # (gen, preview_of entry, start) of a render
        self._seeking = False
        self._chip_groups: tuple = ()   # the Now playing row's, for a new Edit sound player
        self._zero_vol_said = False   # the "Sounds volume is at 0%" toast, once per time
        self._muted_said = False      # the "you're muted" one, once per mute

    def play(self, sid, now: bool = False):
        """Play a pad's sound as its settings say (by default one at a time: a new
        sound stops the others, PRESS_MODE): its cooldown, a Queue sound waiting
        for the ones playing, its wait before playing. now=True skips all of that (the
        queue and a delayed start, whose press was already checked)."""
        mw = self.mw
        m = mw.meta(sid)
        data = mw.audio.get(sid)
        if m is None:
            return
        if not now and data is not None:
            t = time.monotonic()
            if t < self._cool.get(sid, 0.0):
                return   # in its cooldown: a spammed key does nothing
            if m.cooldown:
                self._cool[sid] = t + m.delay + m.cooldown
            if m.mode == "queue" and (self._pads_playing() or self._queue):
                self.queue_sound(sid)
                return
            if m.delay > 0:
                timer = QTimer(mw)
                timer.setSingleShot(True)
                timer.timeout.connect(lambda s=sid, tm=timer: self._waited(s, tm))
                self._waiting.setdefault(sid, []).append(timer)
                timer.start(int(m.delay * 1000))
                self.select(sid)
                return
        if data is None:   # say why nothing happens instead of silently ignoring the press
            p = mw.pads.get(sid)
            if p is not None and p.state == "error":
                why = f": {html.escape(p.error)}" if p.error else ""
                name = html.escape(m.name)
                mw.say(_("<span style='color:{status}'>Can't play “{name}”{why}. If "
                           "the file was moved or deleted, remove the pad and add the "
                           "sound again.</span>",
                           status=theme.status('error'), name=name, why=why), "error")
            elif p is not None and p.state == "rendering" and mw.editctl.rendering(sid):
                mw.toast(_("“{name}” can't play until its effects are applied ({how})",
                           name=html.escape(m.name), how=mw.editctl.render_words(sid)),
                         "warn", key="render-wait")
            else:   # it plays once it's loaded (loaded()), as a press a moment later would
                self._wanted[sid] = time.monotonic()
                mw.toast(_("“{name}” is still loading…", name=html.escape(m.name)), "warn")
            return
        if sid != LINK_ID and LINK_ID in mw.engine.playing() and (
                (PRESS_MODE.get(m.mode, m.mode) == "solo" and not m.loop)
                or mw.searchctl._pad_for_link(mw.searchctl._link_url) == sid):
            # a sound that stops the others stops the web search's song too (the
            # engine leaves that voice alone): it played over it, two songs at once.
            # Its own pad (the song saved) starts it again from the top instead.
            # Play over it is the pad's Overlap mode; a loop is a background.
            self._stop_sound(LINK_ID)
        live = getattr(mw, "livesetups", None)
        if live is not None:   # a Live controls setup's AI voice: its version of the sound
            data = live.for_play(sid, data)
            if data is None:
                self.select(sid)
                return   # being made in the AI voice first: it plays when it's ready
        self.select(sid)
        self._last_sid = sid
        if sid != LINK_ID:
            m.plays += 1   # Most played
            achievements.played(sid=sid, plays=m.plays, gain=m.volume * mw.cfg.sound_vol)
            if not self._count_save.isActive():
                self._count_save.start()
        v = mw.engine.play(sid, data, mw.gain_for(m), loop=m.loop,
                             mode=PRESS_MODE.get(m.mode, m.mode),
                             fade_in=m.fade_in, fade_out=m.fade_out,
                             only=("main", "obs") if m.only_them else None)
        mw.tickctl._wake()
        if v is not None and sid != LINK_ID:   # Wall of Noise
            achievements.at_once(sum(1 for s in mw.engine.playing() if s in mw._meta))
        if v is not None:   # a new install's first steps (usage.py; once each, if counted)
            usage.step(mw.cfg, "played-sound")
            if mw.cfg.route != "off":
                usage.step(mw.cfg, "sent-to-others")
        if v is None and not mw.engine.active_outputs():
            mw.say(_("<span style='color:{status}'>No audio device is open, pick "
                       "one in Setup.</span>", status=theme.status('warn')), "warn")
        self._say_zero_volume(v is not None)
        self._say_muted(v is not None, m.name)

    def _say_muted(self, played: bool, name: str):
        """A sound started while muted (Live off): a hotkey or the control API plays it
        in your own headphones only, with nothing on screen saying why nobody else hears
        it. Said once, until you go live again (sending_changed)."""
        mw = self.mw
        if (not played or mw.engine.sending or self._muted_said or mw.cfg.route == "off"
                or mw.routectl._main_name() is None):
            return
        self._muted_said = True
        usage.used("muted-note")
        mw.toast(_("You're muted, so only you hear “{name}”.", name=html.escape(name)),
                 "warn", 8000, key="muted-play",
                 action=(_("Go live"), lambda: (usage.used("muted-go-live"),
                                                mw.set_sending(True))))

    def sending_changed(self, on: bool):
        if on:
            self._muted_said = False   # muted again later: say it again
            self.mw.unsay("muted-play")

    def _say_zero_volume(self, played: bool):
        """A sound started with the Sounds volume at 0%: it still plays in your own
        headphones, so it seems to work while nobody else hears it. Said once, until
        the volume goes up again (sound_volume_changed)."""
        mw = self.mw
        if not played or mw.cfg.sound_vol > 0:
            return
        if mw.cfg.route == "off":   # nobody else hears it anyway: no warning, but the
            achievements.event("sound-vol-0")   # badge (Silent But Deadly) still counts
            return
        if self._zero_vol_said:
            return
        self._zero_vol_said = True
        usage.used("sound-vol-0")
        mw.toast(_("Your Sounds volume is at 0%, so nobody else hears your sounds."), "warn",
                 8000, key="sound-vol-0",
                 action=(_("Set to 100%"), lambda: (usage.used("sound-vol-0-fixed"),
                                                     mw.vol_sound.spin.setValue(100))))

    def sound_volume_changed(self, v: float):
        if v > 0:
            self._zero_vol_said = False   # back at 0 later: say it again
            self.mw.unsay("sound-vol-0")

    def _waited(self, sid: str, timer: QTimer):
        """A sound's wait before playing is over."""
        timers = self._waiting.get(sid, [])
        if timer in timers:
            timers.remove(timer)
            if not timers:
                del self._waiting[sid]
            self.play(sid, now=True)
        timer.deleteLater()

    def _cancel_waiting(self, sid: str):
        for timer in self._waiting.pop(sid, []):
            timer.stop()
            timer.deleteLater()

    def _pads_playing(self) -> bool:
        """Is one of the board's sounds playing (not a preview, cue or the radio)?"""
        mw = self.mw
        return any(sid in mw._meta and not paused
                   for sid, (_p, paused) in mw.engine.playing().items())

    def _board_song_playing(self, playing=None) -> bool:
        """Is one of the board's sounds playing or paused? A web search's Play waits
        for it (Up next), as a pad's Play next does. A looping one (rain, a hum) is a
        background: that would never end, so a song doesn't wait for it."""
        mw = self.mw
        playing = mw.engine.playing() if playing is None else playing
        return any(sid in mw._meta and not mw._meta[sid].loop for sid in playing)

    def clicked(self, sid: str):
        """A pad clicked (or Enter on it): played as its settings say."""
        achievements.played_by("click")
        self.play(sid)

    def queue_sound(self, sid: str) -> bool:
        """Play `sid` once the board's sounds playing now have finished (now, if none are:
        True then)."""
        mw = self.mw
        achievements.at_least("queued", 1)   # (Wait Your Turn)
        if (not self._pads_playing() and not self._queue
                and not mw.linkbar.up_next() and LINK_ID not in mw.engine.playing()):
            self.play(sid, now=True)
            return True
        self._queue.append(sid)
        self._say_queue()
        return False

    def queue_category(self, name: str, shuffled: bool):
        """Play every sound in category `name`, one after another."""
        mw = self.mw
        sids = [m.id for m in mw.cfg.sounds if name in m.tags and m.id in mw.audio]
        if not sids:
            self.cue("fail")
            mw.toast(_("No sounds in “{name}” to play yet", name=html.escape(name)), "warn")
            return
        if shuffled:
            self.shuffle.rng.shuffle(sids)
        self._queue = sids
        for sid in mw.engine.playing():   # the board's sounds make way (not the radio)
            if sid in mw._meta:
                mw.engine.stop(sid)
        self._next_in_queue()

    def _next_in_queue(self):
        mw = self.mw
        while self._queue:
            sid = self._queue.pop(0)
            if mw.meta(sid) is not None and sid in mw.audio:
                self.play(sid, now=True)
                self._say_queue()
                return

    def _say_queue(self):
        mw = self.mw
        if self._queue:
            m = mw.meta(self._queue[0])
            name, n = html.escape(m.name if m else "?"), len(self._queue) - 1
            self._queue_said = (
                _("Up next: “{name}” (+{n} more) · Stop all clears the queue", name=name, n=n)
                if n else _("Up next: “{name}” · Stop all clears the queue", name=name))
            mw.toast(self._queue_said, key="queue")
        elif getattr(self, "_queue_said", None):   # ran out / cleared
            self._queue_said = None
            mw.unsay("queue")

    def select(self, sid):
        mw = self.mw
        if mw.current != sid:
            if mw.current in mw.pads:
                mw.pads[mw.current].selected = False
                mw.pads[mw.current].update()
            mw.current = sid
            mw.start_frac = 0.0
            if sid in mw.pads:
                mw.pads[sid].selected = True
                mw.pads[sid].update()
            m = mw.meta(sid)
            mw._set_np_name(m.name if m else "")

    def deselect(self):
        """Nothing in the player: Space and ▶ have no sound to play until a pad is
        picked again."""
        mw = self.mw
        if mw.current in mw.pads:
            mw.pads[mw.current].selected = False
            mw.pads[mw.current].update()
        mw.current = None
        mw.start_frac = 0.0
        mw._set_np_name(_("Pick a sound"))
        mw.np_name.setToolTip(_("Select a sound pad to use these playback controls."))

    def toggle_play_pause(self):
        mw = self.mw
        sid = mw.current
        if not sid:
            return
        st = mw.engine.state(sid)
        if st:
            mw.engine.set_paused(sid, not st[1])
            mw.tickctl._wake()
            return
        m, data = mw.meta(sid), mw.audio.get(sid)
        if m and data is not None:
            frac = 0.0 if mw.start_frac >= 0.995 else mw.start_frac
            mw.engine.play(sid, data, mw.gain_for(m), loop=m.loop, mode="restart", start=frac,
                             fade_in=m.fade_in if frac == 0 else 0.0, fade_out=m.fade_out)
            mw.tickctl._wake()

    def _space_action(self):
        """What Space does on the tab showing (ui/window/spacekey.py): play / pause the
        player's sound on Sounds, play / stop the radio on Radio; None elsewhere.
        Nothing to play on Sounds: nothing, not a press of the button clicked last
        (the mini player's Bun button turned the window back into Bun). Settings open
        over a tab: None, so Space ticks the box you clicked there, as anywhere."""
        mw = self.mw
        if mw.setctl.settings_open():
            return None
        page = mw.tabs.currentWidget()
        if page is mw.sounds_page:
            return self.toggle_play_pause if mw.current else _nothing
        if page is mw.radio_page:
            return getattr(mw.radio, "toggle_play", None)
        return None

    def space_pad(self, sid: str):
        """Space on a pad: pause or resume it while it's playing (or paused), like a
        media player; play it when it isn't."""
        mw = self.mw
        if mw.engine.state(sid):
            self.select(sid)
            st = mw.engine.state(sid)
            mw.engine.set_paused(sid, not (st is not None and st[1]))
            mw.tickctl._wake()
        else:
            self.play(sid)

    def stop_current(self):
        """The player's ■. A second press within a double-click of the first that
        would stop a different sound is a double click (or a bouncy mouse): the queue's
        next sound had already taken the player, and it went too."""
        mw = self.mw
        if mw.current:
            self._stop_one(mw.current)
        mw.start_frac = 0.0

    def skip_next(self):
        """The player's ⏭ (and its hotkey): the next sound in Up next starts now. The
        board's queue waits for every pad sound, so they all make way (as Play all
        does); a web search's Up next waits for its song. Nothing waiting: it stops
        the player's sound, like ■."""
        mw = self.mw
        if self._queue:
            for sid in mw.engine.playing():   # (it waits for a web search's song too)
                if sid in mw._meta or sid == LINK_ID:
                    mw.engine.stop(sid)
            mw.searchctl._drop_link()
            self._next_in_queue()
        elif mw.linkbar.up_next():
            self._make_way()   # it waits for your sounds too
            mw.linkbar.play_next()
        elif mw.current:
            self._stop_sound(mw.current)
            mw.start_frac = 0.0
        else:
            self.cue("fail")
            return
        mw.tickctl._wake()

    def _stop_one(self, sid: str):
        """A ■ for one sound (the player's, or a Now playing chip's). A second press
        within a double-click of one that stopped a different sound does nothing: the
        player had moved to the next sound, or the chips row was remade and the next
        sound's ■ slid in under the mouse, and a double click (or a bouncy mouse)
        stopped that one too, so stopping one sound stopped two or all of them."""
        now, (at, was) = time.monotonic(), self._stopped_at
        if was and sid != was and now - at < QApplication.doubleClickInterval() / 1000:
            return
        self._stopped_at = (now, sid)
        self._stop_sound(sid)

    def _stop_sound(self, sid: str):
        """Stop one sound. If it was the player's and others still play, the player
        moves to the newest of them, so its ⏸ / ■ reach them (stopping the shown pad
        used to leave a web search's sound playing with no way back to it)."""
        mw = self.mw
        mw.engine.stop(sid)
        if sid == LINK_ID:   # a web song isn't on the board: stopped, it leaves the player
            mw.searchctl._drop_link()
        if sid != mw.current and mw.current:
            return
        others = [s for s in mw.engine.playing()
                  if s != sid and (s in mw._meta or s == LINK_ID)]
        if others:
            self.select(others[-1])

    def _seek_preview(self, v):
        mw = self.mw
        if self._seeking:
            m = mw.meta(mw.current) if mw.current else None
            if m:
                length = self.length(m)
                mw._set_np_time(fmt_pos(v / 1000 * length, length))

    def length(self, m) -> float:
        """How long what the sound plays is, in seconds: its audio as it is now, which
        an open Edit sound window's unsaved trim has cut already (m.duration is the
        saved length until Save)."""
        data = self.mw.audio.get(m.id)
        return len(data) / SR if data is not None and len(data) else m.duration

    def do_seek(self, slider=None):
        mw = self.mw
        self._seeking = False
        if not mw.current:
            return
        frac = (slider or mw.seek).value() / 1000
        if not mw.engine.seek(mw.current, frac):
            mw.start_frac = frac   # not playing: ▶ will start from here

    def preview(self, sid, volume=None, fx=None, fades=None, done=None, at: float = 0.0,
                quiet: bool = False) -> str:
        """Play a sound to your headphones only. With `fx` (the Edit dialog's unsaved
        effects) it's rendered with those first, in the background; `fades` is the
        dialog's unsaved (fade in, fade out). Returns "playing", "rendering" (then
        `done(ok)` is called when it plays or fails) or "missing" (not loaded).
        `at`: from that share (0..1) of the way through; `quiet`: no toast while it
        renders (it follows an edit, or a drag on the waveform)."""
        mw = self.mw
        m = mw.meta(sid)
        data = mw.audio.get(sid)
        if not m or data is None:
            return "missing"
        gain = mw.gain_for(m, volume)
        fade_in, fade_out = fades if fades is not None else (m.fade_in, m.fade_out)
        self._preview_fades: dict[str, Any] = {"fade_in": fade_in, "fade_out": fade_out}
        if fx is None or soundfx.key(fx) == soundfx.key(m.fx):
            self.drop_preview()   # an effects render still going mustn't play over it
            self.preview_of[sid] = (m.fx, 0.0, 1.0)
            mw.engine.play(sid + ":preview", data, gain, mode="restart", preview=True,
                           start=min(max(at, 0.0), 0.999), **self._preview_fades)
            return "playing"
        self.drop_preview()
        gen = self._preview_gen
        self._preview_done = done
        if not quiet:
            mw.toast(_("Rendering the preview…"), "busy", key="preview")

        def answer(out):
            return (sid, out, gain, gen) if gen == self._preview_gen else worker.SKIP

        def run():
            try:
                src = load_original(m)
                if len(src) > PREVIEW_WHOLE_S * SR:   # long: only what plays first
                    part, pfx = soundfx.preview_part(src, fx, PREVIEW_S, at)
                    out = soundfx.render(part, pfx)
                    kept = len(soundfx.trim(src, fx)) or 1
                    # (one assignment: read on the UI thread with its answer)
                    self._preview_info = (gen, (fx, at, min(1.0, len(part) / kept)), 0.0)
                else:
                    # into the cache file for these effects: saving them afterwards
                    # finds it rendered
                    out = library.render_cached(m.id, src, fx,
                                                cancel=lambda: gen != self._preview_gen)
                    self._preview_info = (gen, (fx, 0.0, 1.0), at)
            except library.Cancelled:
                return worker.SKIP   # a newer preview (or the dialog closed): nothing to play
            return answer(out)
        worker.run(run, mw.bridge.preview, "fx-preview", error=lambda _e: answer(None),
                   owner=mw)
        return "rendering"

    def drop_preview(self):
        """Forget an effects preview still rendering (a newer preview, or its Edit
        dialog closed): it won't play, and the status stops saying it's rendering.
        Its done() isn't called: the dialog it belongs to may be gone."""
        mw = self.mw
        self._preview_gen += 1
        if self._preview_done is not None:
            self._preview_done = None
            mw.unsay("preview")

    def _on_fx_preview(self, sid, data, gain, gen=None):
        mw = self.mw
        if gen is not None and gen != self._preview_gen:
            return   # dropped while it rendered (checked here too: the signal is queued)
        mw.unsay("preview")
        done, self._preview_done = self._preview_done, None
        if done is not None:
            done(data is not None)
        if data is None:
            mw.toast(_("Couldn't render the preview with these effects (see the log)."), "warn")
            return
        start = 0.0
        info = self._preview_info
        if info is not None and info[0] == gen:
            self.preview_of[sid], start = info[1], info[2]
        # its own id: it mustn't share the pad's resample cache or its preview voice
        mw.engine.stop(sid + ":preview")   # (the saved one, when it moved on from that)
        mw.engine.play(sid + "~fx:preview", data, gain, mode="restart", preview=True,
                       start=min(max(start, 0.0), 0.999), **getattr(self, "_preview_fades", {}))

    def on_live_speed(self, speed: float, pitch: float, keep: bool):
        mw = self.mw
        e = mw.engine
        e.sound_speed, e.sound_pitch, e.sound_keep_pitch = speed, pitch, keep

    def play_random(self, category: str | None = None) -> str | None:
        """Play a random loaded sound from `category` (None = the one showing, "" = all
        of them): each comes up once before any repeats. Returns its id."""
        mw = self.mw
        cat = mw.cfg.category if category is None else category
        if cat and cat not in mw.cfg.categories:
            return None
        pool = [m.id for m in mw.cfg.sounds   # All: not the categories hidden from it
                if library.in_view(m.tags, cat, hidden=mw.cfg.hidden_from_all)
                and m.id in mw.audio]
        sid = self.shuffle.next(cat, pool)
        if sid is None:
            self.cue("fail")
            mw.toast(_("No sounds in “{cat}” to play yet", cat=html.escape(cat)) if cat
                       else _("No sounds to play yet"), "warn")
            return None
        self.play(sid)
        return sid

    def cue(self, kind: str | tuple):
        """A short beep in the headphones only (others never hear it), so a hotkey pressed
        in-game is confirmed without looking at the app. `kind` is a CUES name or the
        notes themselves (Hz; 0 = a gap)."""
        mw = self.mw
        if not mw.cfg.cue_sounds or mw.engine.mon_stream is None:
            return
        notes, n = mw.CUES[kind] if isinstance(kind, str) else kind, int(0.075 * SR)
        t = np.arange(n) / SR
        env = np.minimum(1.0, np.minimum(t, t[::-1]) / 0.008)   # 8 ms fade in/out
        tone = np.concatenate([np.sin(2 * np.pi * f * t) * env for f in notes]) * 0.18
        mw.engine.play("__cue__", np.stack([tone, tone], 1).astype(np.float32), 1.0,
                         mode="restart", preview=True)

    def _stop_all_clicked(self):
        mw = self.mw
        usage.used("stop-all")
        self.stop_all()
        # only an icon on the rail: a tick for a moment says it worked
        icons.set_icon(mw.stop_btn, "check", "live_text", size=sidebar.ICON, gap=False)
        QTimer.singleShot(1200, mw.stop_btn,   # (the button: never after it's gone)
                          lambda: icons.set_icon(mw.stop_btn, "stop", "danger_text",
                                                 size=sidebar.ICON))
        card = mw.rail.output.stop if mw.rail.output else None
        if card is not None:   # the open card's Stop all: the same tick
            icons.set_icon(card, "check", "live_text", gap=False)
            QTimer.singleShot(1200, card, lambda: icons.set_icon(card, "stop", "danger_text",
                                                                 gap=False))

    def play_last(self):
        mw = self.mw
        if self._last_sid is None or mw.meta(self._last_sid) is None:
            self.cue("fail")
        else:
            self.play(self._last_sid)

    def _pause_clicked(self):
        """Pause everything playing (sounds and the radio), or bring it all back. A
        station is live, so pausing it stops it and Play turns the same one back on."""
        mw = self.mw
        usage.used("pause")
        playing = mw.engine.playing()
        radio_on = mw.radio.is_active()
        if radio_on or any(not paused for _p, paused in playing.values()):
            if any(not paused for _p, paused in playing.values()):
                mw.engine.pause_all()   # something still plays: pauses them all
            if radio_on:
                mw._radio_paused = getattr(getattr(mw.radio, "player", None), "station", None)
                mw.radio.stop()
        else:
            if playing:
                mw.engine.pause_all()   # all paused: resumes them
            station, mw._radio_paused = mw._radio_paused, None
            play = getattr(mw.radio, "play", None)   # (the Radio tab switched off: none)
            if station is not None and play is not None:
                play(station)
        mw.tickctl._wake()

    def loaded(self, sid: str):
        """A sound finished loading: play it if it was pressed while it loaded, and
        not too long ago (a press from long before would come as a surprise)."""
        t = self._wanted.pop(sid, None)
        if t is not None and time.monotonic() - t < WANTED_S:
            self.play(sid)

    def stop_all(self):
        mw = self.mw
        self._wanted.clear()
        mw._radio_paused = None
        self._queue.clear()
        self._say_queue()
        mw.linkbar.drop_up_next()
        for sid in list(self._waiting):
            self._cancel_waiting(sid)
        mw.engine.stop_all()
        mw.radio.stop()
        mw.apps.stop_all()
        mw.triggers.cancel_pending()
        mw.voice.stop_all()   # the voice changer and the other voices go off too

    def _update_chips(self, playing, force: bool = False):
        """The row above the pads: every sound playing, each with its own ■, then Up
        next, one chip with how many wait that opens them all in a list (upnext.py). A
        web search / link's Play once counts too: it isn't a pad, but it plays over
        them and needs its own ■. One rule, whatever
        played before: a sound has a chip while it plays. (The row used to show only
        for two or more, so stopping one of two hid the other's chip too and it looked
        like ■ had stopped both.) `force`: remade even when nothing changed (a dragged
        Up next row put back)."""
        mw = self.mw
        if force:
            mw._chip_ids = ("remake",)   # never equal to a real (ids, queue, ..., link)
        ids = tuple(s for s in mw.pads if s in playing)
        if LINK_ID in playing:
            ids += (LINK_ID,)
        # a paused one is under Paused, not Now playing: a song paused before a
        # Community sound played said it was still playing
        paused = tuple(s for s in ids if playing[s][1])
        queue = tuple(self._queue)
        links = tuple(mw.linkbar.up_next())   # web search / link Plays waiting their turn
        # the link's chip says its name: another link (or Community sound) played over
        # it is the same voice, so its name is part of what's compared
        link = m.name if LINK_ID in ids and (m := mw.meta(LINK_ID)) is not None else ""
        if (ids, queue, links, paused, link) != mw._chip_ids:
            mw._chip_ids = (ids, queue, links, paused, link)
            while mw._chips_hl.count():
                item = mw._chips_hl.takeAt(0)
                w = item.widget() if item else None
                if w:
                    w.deleteLater()
            mw._chips = {}
            # Now playing first, then Up next: one line, read the way the app reads
            # (the Flow mirrors it in Arabic)
            groups = ((_("Now playing"), [s for s in ids if s not in paused]),
                      (_("Paused"), list(paused)))
            for title, group in groups:
                if not group:
                    continue
                lbl = QLabel(title)
                lbl.setObjectName("muted")
                mw._chips_hl.addWidget(lbl)
                for sid in group:
                    chip = self._chip(sid)
                    mw._chips_hl.addWidget(chip)
                    mw._chips[sid] = chip
            self._chip_groups = groups
            for p in mw.editctl.players():   # Edit sound's players have them too
                p.set_chips(groups, self._chip)
            # Up next: one chip, "Up next" and how many wait, that opens the whole list
            mw._up_next_chip = None
            waiting = len(queue) + len(links)
            if waiting:
                chip = UpNextChip(waiting)
                chip.clicked.connect(self.open_up_next)
                mw._chips_hl.addWidget(chip)
                mw._up_next_chip = chip
            pop = mw._up_next_popup
            if pop is not None and pop.isVisible():
                if waiting:
                    pop._anchor = mw._up_next_chip
                    pop.show_items(self._up_next_items())
                else:
                    pop.close()
            self._fit_up_next()
            # at least a line high, taller when the chips wrap (the Flow's height for
            # its width); a row that shrank and grew back with every overlapping
            # sound resized and repainted the whole board under it
            mw.playing_row.setMinimumHeight(CHIPS_ROW_H)
            mw.playing_row.setVisible(bool(ids) or bool(queue) or bool(links))
        for p in mw.editctl.players():
            p.mark_chip(mw.current)
        for sid, chip in mw._chips.items():
            sel = "true" if sid == mw.current else "false"
            if chip.property("sel") != sel:
                chip.setProperty("sel", sel)
                chip.style().unpolish(chip)
                chip.style().polish(chip)

    def _chip(self, sid: str) -> QFrame:
        """One sound's chip: its name (into the player) and its own ■."""
        m = self.mw.meta(sid)
        chip = QFrame()
        chip.setObjectName("chip")
        ch = QHBoxLayout(chip)
        ch.setContentsMargins(4, 2, 2, 2)
        ch.setSpacing(2)
        name = QPushButton(chip.fontMetrics().elidedText(   # && : "R&B" not "RB"
            m.name if m else sid, Qt.TextElideMode.ElideRight, 150).replace("&", "&&"))
        name.setObjectName("chipname")
        name.setToolTip(_("Show this sound in the player (keeps playing)"))
        name.clicked.connect(lambda __=False, s=sid: self.select(s))
        stop = QPushButton()
        stop.setObjectName("chipstop")
        stop.setAccessibleName(_("Stop this sound"))
        icons.set_icon(stop, "stop", "danger_text", size=12)
        stop.setFixedSize(24, 24)
        stop.clicked.connect(lambda __=False, s=sid: self._stop_one(s))
        ch.addWidget(name)
        ch.addWidget(stop)
        return chip

    def _up_next_items(self) -> list[Waiting]:
        """Everything waiting to play, in order: web search / link songs, then the
        board's queued sounds; each with what clicking its name and its ✕ do."""
        mw = self.mw
        links = tuple(mw.linkbar.up_next())
        queue = tuple(self._queue)
        waiting: list[Waiting] = [
            Waiting(title,   # its name plays it now, as its ▶ does: never over a sound
                    lambda __=False, i=i, q=links: self._play_link_now(i, q),
                    lambda __=False, i=i, q=links: mw.linkbar.drop_up_next(i, q),
                    lambda __=False, i=i, q=links: self._play_link_now(i, q),
                    lambda to, i=i, q=links: self._move_link(i, to, q), "links")
            for i, title in enumerate(links)]
        for i, sid in enumerate(queue):
            m = mw.meta(sid)
            waiting.append(Waiting(
                m.name if m else sid,
                lambda __=False, s=sid: self.select(s),
                lambda __=False, i=i, q=queue: self._unqueue(i, q),
                lambda __=False, i=i, q=queue: self._play_queued_now(i, q),
                lambda to, i=i, q=queue: self._move_queued(i, to, q), "board"))
        return waiting

    def _make_way(self):
        """What plays makes way for an Up next sound played now (as ⏭ does): the
        board's sounds (a looping one stays) and a web search's song."""
        mw = self.mw
        for sid in mw.engine.playing():
            if sid == LINK_ID or (sid in mw._meta and not mw._meta[sid].loop):
                mw.engine.stop(sid)

    def _play_queued_now(self, i: int, shown: tuple[str, ...]):
        """A queued sound's ▶ in Up next: it plays now, the rest keep waiting after it.
        A list that's out of date does nothing (a double click hit a moved row)."""
        mw = self.mw
        if tuple(self._queue) != shown or not 0 <= i < len(self._queue):
            return
        usage.used("upnext-play-now")
        sid = self._queue.pop(i)
        self._make_way()
        mw.searchctl._drop_link()
        if mw.meta(sid) is not None and sid in mw.audio:
            self.play(sid, now=True)
        self._say_queue()
        self._update_chips(mw.engine.playing())
        mw.tickctl._wake()

    def _play_link_now(self, i: int, shown: tuple[str, ...]):
        """A web search / link song's ▶ in Up next: it plays now."""
        mw = self.mw
        if tuple(mw.linkbar.up_next()) != tuple(shown):
            return
        usage.used("upnext-play-now")
        self._make_way()
        mw.linkbar.play_next(i, shown)
        self._update_chips(mw.engine.playing())
        mw.tickctl._wake()

    def _move_queued(self, i: int, to: int, shown: tuple[str, ...]):
        """A queued sound dragged from place `i` to `to` in Up next."""
        if tuple(self._queue) != shown or not (0 <= i < len(self._queue)
                                               and 0 <= to < len(self._queue)):
            self._update_chips(self.mw.engine.playing(), force=True)   # back as it was
            return
        usage.used("upnext-reordered")
        self._queue.insert(to, self._queue.pop(i))
        self._say_queue()
        self._update_chips(self.mw.engine.playing())

    def _move_link(self, i: int, to: int, shown: tuple[str, ...]):
        """A web search / link song dragged from place `i` to `to` in Up next."""
        mw = self.mw
        if not mw.linkbar.move_up_next(i, to, shown):
            self._update_chips(mw.engine.playing(), force=True)
            return
        usage.used("upnext-reordered")
        self._update_chips(mw.engine.playing())

    def open_up_next(self):
        """The Up next chip: the whole list in a pop-up card above it."""
        mw = self.mw
        chip = mw._up_next_chip
        if chip is None or not qt_valid(chip):
            return
        usage.used("upnext-opened")
        if mw._up_next_popup is None:
            mw._up_next_popup = UpNextPopup(mw, self.clear_up_next)
        mw._up_next_popup.open_at(chip, self._up_next_items())

    def clear_up_next(self):
        """The list's Clear: nothing waits any more; what plays keeps playing."""
        usage.used("upnext-cleared")
        self._queue.clear()
        self._say_queue()
        self.mw.linkbar.drop_up_next()
        self._update_chips(self.mw.engine.playing())

    def _fit_up_next(self):
        """The row moved or changed size: the open Up next list stays on its chip."""
        pop = self.mw._up_next_popup
        if pop is not None and pop.isVisible():
            pop._place()

    def _unqueue(self, i: int, shown: tuple[str, ...] | None = None):
        """The ✕ on the queue's chip `i`, of the queue as its row `shown` it. A row
        that's out of date does nothing: the chips are remade on the next tick, so a
        double click (or a bouncy mouse) hit the same ✕ twice, and the second took out
        the sound that had moved into that place. The row is remade at once."""
        mw = self.mw
        if shown is not None and tuple(self._queue) != shown:
            return
        if 0 <= i < len(self._queue):
            del self._queue[i]
            self._say_queue()
            self._update_chips(mw.engine.playing())

    def drop_pending(self, sid: str):
        """`sid` won't start later after all: off the queue, and not when its wait
        before playing is over (what pressed it is gone, e.g. a deleted trigger)."""
        self._cancel_waiting(sid)
        if sid in self._queue:
            self._queue = [s for s in self._queue if s != sid]
            self._say_queue()

    def _set_pp_icon(self, name: str):
        mw = self.mw
        if name != mw._pp_icon:
            mw._pp_icon = name
            for b in (mw.btn_pp, getattr(mw, "mini_pp", None)):
                if b is not None:
                    icons.set_icon(b, name, "on_accent", size=16)
            for p in mw.editctl.players():
                p.set_icon(name)
