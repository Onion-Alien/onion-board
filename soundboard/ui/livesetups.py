"""My setups in Live controls: a voice setup (soundboard.voicesetups) on every sound, on
the radio or on the programs the Apps tab sends.

Its voice changer part is live, so it's on at once. Its AI voice takes a while:

- the radio and programs are held back (silence) while the AI voice's helper starts,
  then go on in the new voice (soundboard.livesetup.StreamVoice);
- a sound is made again in the AI voice before it plays (its own effects kept, a
  render cached like Edit sound's: renderworker), one sound at a time. A sound that
  was playing pauses meanwhile and goes on from the same place.

A setup with an AI voice asks first ("this may take a while"). Then Live controls (and
a card, when it's shut) shows how far it is with a Cancel, which puts back what was on
before. Nothing here is saved: like the rest of Live controls, it's for now.
"""
from __future__ import annotations

import dataclasses
import html
import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QMessageBox

from soundboard import (errors, library, livesetup, renderworker, soundfx, usage,
                        voicesetups)
from soundboard.i18n import _
from soundboard.ui import worker
from soundboard.ui.controller import Controller

if TYPE_CHECKING:
    from soundboard.ui.mainwindow import MainWindow
    from soundboard.ui.speedpitch import SpeedPitchButton

log = logging.getLogger(__name__)

TABS = ("sounds", "radio", "apps")
POLL_MS = 250   # while a stream's AI voice gets ready: is it yet?
TOAST_KEY = "live-setup-ai"


class LiveSetups(Controller):
    """MainWindow.livesetups: the setup on each of the three Live controls."""

    _event = Signal(str, dict)             # (tab, helper event) from its threads
    _progress = Signal(int, float)         # (job gen, 0..1) from the render thread
    _rendered = Signal(int, str, object, str)   # (gen, sid, data or None, error)

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self.names = {t: "" for t in TABS}   # the setup on each, "" = none
        self._before = dict(self.names)      # what Cancel puts back
        self._ai: dict | None = None         # the sounds' AI voice
        self._ready: dict[tuple[str, str], object] = {}   # (sid, fx key) -> rendered
        self._jobs: list[tuple[str, float | None]] = []   # (sid, resume at) to render
        self._job: tuple[int, str, float | None] | None = None   # (gen, sid, resume at)
        self._gen = 0
        self._ai_playing: set[str] = set()   # sounds playing in the AI voice now
        self._from_pick = False   # the jobs are for a setup just picked (Cancel: undo it)
        self._shown_pct = -1
        self._event.connect(self._on_event)
        self._progress.connect(self._on_progress)
        self._rendered.connect(self._on_rendered)
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self._check_streams)
        for tab in TABS:
            b = self.button(tab)
            if b is None:
                continue
            b.opening.connect(lambda t=tab: self.refresh(t))
            b.setup_picked.connect(lambda name, t=tab: self.pick(t, name))
            b.setup_cancelled.connect(lambda t=tab: self.cancel(t))

    # ------------------------------------------------------------ the list
    def button(self, tab: str) -> SpeedPitchButton | None:
        mw = self.mw
        if tab == "sounds":
            return getattr(mw, "speed_btn", None)
        owner = getattr(mw, "radio" if tab == "radio" else "apps", None)
        return getattr(owner, "fx_btn", None)

    def setups(self) -> dict[str, dict]:
        """The saved setups, read again each time (a new one saved on the Voice tab
        shows, as does one saved by the Voice tab's own copy)."""
        return dict(voicesetups.Store().setups)

    def refresh(self, tab: str):
        b = self.button(tab)
        if b is None:
            return
        voice = self.mw.voice
        icon = getattr(voice, "setup_icon", None)
        words = getattr(voice, "setup_words", None)
        items = []
        for name, setup in self.setups().items():
            try:
                pic = icon(setup) if icon is not None else None
                tip = words(setup) if words is not None else ""
            except Exception:  # noqa: BLE001 - only a picture or a tip
                log.debug("setup %r: no icon / words", name, exc_info=True)
                pic, tip = None, ""
            items.append((name, pic, tip))
        b.set_setups(items, self.names[tab])

    # ------------------------------------------------------------ picking one
    def pick(self, tab: str, name: str, ask: bool = True):
        setup = self.setups().get(name) if name else None
        if name and setup is None:
            self.refresh(tab)   # deleted on the Voice tab meanwhile
            return
        module = None
        if livesetup.ai_of(setup) is not None:
            module = livesetup.ai_module()
            if module is not None and ask and not self.ask(tab, name):
                usage.used("live-setup-ai-no")
                return   # No: what was on stays on
            if module is None:
                self.mw.toast(_("The AI voices add-on isn't installed, so only the voice "
                                "changer part of “{name}” is on.", name=html.escape(name)),
                              "warn")
        self._before[tab] = self.names[tab]
        if name and ask:   # their pick (not a cancel putting the old one back)
            usage.used(f"live-setup-{tab}")
        try:
            self._apply(tab, setup, module)
        except RuntimeError as e:
            self.mw.toast(_("Couldn't start the AI voice: {why}",
                            why=html.escape(errors.plain(e))), "error")
            self._apply(tab, setup, None)
        self.names[tab] = name
        b = self.button(tab)
        if b is not None:
            b.set_setup(name)

    def ask(self, tab: str, name: str) -> bool:
        """A setup with an AI voice takes a while: say so, Yes or No first."""
        return self.ask_box(tab, name).exec() == QMessageBox.StandardButton.Yes

    def ask_box(self, tab: str, name: str) -> QMessageBox:
        text = {
            "sounds": _("“{name}” has an AI voice, so this may take a while. Each sound is "
                        "made in that voice first, in the background, and plays when it's "
                        "ready.", name=name),
            "radio": _("“{name}” has an AI voice, so this may take a while. The radio goes "
                       "quiet until the AI voice is ready, then carries on in it.", name=name),
            "apps": _("“{name}” has an AI voice, so this may take a while. Your programs go "
                      "quiet until the AI voice is ready, then carry on in it.", name=name),
        }[tab]
        box = QMessageBox(QMessageBox.Icon.Question, _("Use “{name}”?", name=name), text,
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                          self.mw)
        box.button(QMessageBox.StandardButton.Yes).setText(_("Use it"))
        box.button(QMessageBox.StandardButton.No).setText(_("Not now"))
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        return box

    def _apply(self, tab: str, setup: dict | None, module):
        eng = self.mw.engine
        if tab == "sounds":
            eng.set_sound_voice(livesetup.chain_spec(setup))
            self._set_sound_ai(livesetup.ai_of(setup) if module is not None else None)
        elif tab == "radio":
            sv = eng.radio_voice
            if sv is None and setup:
                sv = eng.radio_voice = livesetup.StreamVoice(
                    lambda ev: self._event.emit("radio", ev))
            if sv is not None:
                sv.set_setup(setup, module)
        else:
            eng.set_apps_setup(setup, module, lambda ev: self._event.emit("apps", ev))
        self._check_streams()

    def cancel(self, tab: str):
        """Cancel while its AI voice gets ready: what was on before comes back (a sound
        pressed while the setup was already on just doesn't play)."""
        usage.used("live-setup-cancel")
        if tab == "sounds":
            undo = self._from_pick
            self._stop_jobs(resume=True)
            if not undo:
                return
        self.pick(tab, self._before.get(tab, ""), ask=False)
        self._before[tab] = self.names[tab]

    # ------------------------------------------------------------ the radio, programs
    def _waiting(self, tab: str) -> bool:
        eng = self.mw.engine
        if tab == "radio":
            return bool(eng.radio_voice is not None and eng.radio_voice.waiting)
        return tab == "apps" and eng.apps_waiting()

    def _check_streams(self):
        busy = False
        for tab in ("radio", "apps"):
            b = self.button(tab)
            w = self._waiting(tab)
            busy = busy or w
            if b is not None:
                b.set_busy(_("Getting the AI voice ready…") if w else "")
        if busy and not self._poll.isActive():
            self._poll.start()
        elif not busy:
            self._poll.stop()

    def _on_event(self, tab: str, ev: dict):
        if ev.get("type") == "error" and ev.get("text"):
            self.mw.toast(_("Couldn't start the AI voice: {why}",
                            why=html.escape(str(ev["text"]))), "error")
        self._check_streams()

    # ------------------------------------------------------------ sounds
    def _set_sound_ai(self, ai: dict | None):
        if ai == self._ai:
            return
        self._stop_jobs(resume=False)
        self._ai = ai
        self._ready.clear()
        playing = self._board_playing()
        if ai is None:   # the AI voice off: what's playing in it goes back to plain
            for sid, frac in playing:
                if sid in self._ai_playing:
                    self._replay(sid, frac, self.mw.audio.get(sid))
            self._ai_playing.clear()
            return
        for sid, frac in playing:   # each waits, made again in the AI voice
            self.mw.engine.set_paused(sid, True)
            self._jobs.append((sid, frac))
        self._from_pick = bool(self._jobs)
        self._next_job()

    def _board_playing(self) -> list[tuple[str, float]]:
        mw = self.mw
        return [(sid, frac) for sid, (frac, paused) in mw.engine.playing().items()
                if sid in mw._meta and not paused]

    def _fx(self, sid: str) -> dict | None:
        m = self.mw.meta(sid)
        return None if m is None else livesetup.sound_fx(m.fx, {"ai": self._ai})

    def for_play(self, sid: str, data):
        """What PlaybackControl plays for `sid`: its audio, or the AI voice's version.
        None: that's being made first, and it plays when it's ready."""
        if self._ai is None or data is None:
            return data
        fx = self._fx(sid)
        if fx is None:
            return data
        key = (sid, soundfx.key(fx))
        got = self._ready.get(key)
        if got is None:
            got = library.load_cached(sid, key[1])
            if got is not None:
                self._ready[key] = got
        if got is not None:
            self._ai_playing.add(sid)
            return got
        if not any(s == sid for s, _f in self._jobs) and (
                self._job is None or self._job[1] != sid):
            self._jobs.append((sid, None))
            self._next_job()
        return None

    def _next_job(self):
        if self._job is not None or not self._jobs:
            if self._job is None:
                self._show_busy(None)
                self._from_pick = False
            return
        sid, at = self._jobs.pop(0)
        m = self.mw.meta(sid)
        fx = self._fx(sid)
        if m is None or fx is None:
            self._next_job()
            return
        self._gen += 1
        gen = self._gen
        self._job = (gen, sid, at)
        meta = dataclasses.replace(m, fx=fx)
        key = soundfx.key(fx)
        self._show_busy(0.0)

        def cancel():
            return self._gen != gen

        def progress(frac: float):   # (the render thread)
            self._progress.emit(gen, float(frac))

        def run():
            try:
                data = None
                if renderworker.enabled:
                    try:   # out of the app's process: no stutter, no lag
                        renderworker.render(meta, cancel, progress)
                        data = library.load_cached(sid, key)
                    except renderworker.Unavailable as e:
                        log.info("AI voice for %s in the app: %s", sid, e)
                if data is None:
                    data = library.load_sound(meta, cancel=cancel, progress=progress)
            except library.Cancelled:
                return worker.SKIP
            return gen, sid, data, ""

        def failed(e):
            return gen, sid, None, errors.plain(e)
        worker.run(run, self._rendered, "live-setup-ai", error=failed, owner=self.mw)

    def _show_busy(self, frac: float | None):
        b = self.button("sounds")
        if b is None:
            return
        job = self._job
        m = self.mw.meta(job[1]) if job is not None else None
        if frac is None or m is None:
            b.set_busy("")
            if self._shown_pct >= 0:
                self.mw.unsay(TOAST_KEY)
            self._shown_pct = -1
            return
        pct = int(frac * 100)
        text = _("Putting the AI voice on “{name}”… {pct}%", name=m.name, pct=pct)
        b.set_busy(text, frac)
        # the pop-up may be shut: a card says it too, with the same Cancel
        if pct // 5 != self._shown_pct // 5 or self._shown_pct < 0:
            self._shown_pct = pct
            self.mw.toast(html.escape(text), "busy", 0, key=TOAST_KEY,
                          action=(_("Cancel"), lambda: self.cancel("sounds")))

    def _on_progress(self, gen: int, frac: float):
        if self._job is not None and self._job[0] == gen:
            self._show_busy(min(1.0, max(0.0, frac)))

    def _on_rendered(self, gen: int, sid: str, data, err: str):
        job = self._job
        if job is None or job[0] != gen:
            return   # cancelled meanwhile
        self._job = None
        at = job[2]
        if data is None:
            m = self.mw.meta(sid)
            self.mw.toast(_("Couldn't put the AI voice on “{name}”: {why}",
                            name=html.escape(m.name if m else sid),
                            why=html.escape(err or "?")), "error")
            if at is not None:
                self.mw.engine.set_paused(sid, False)   # it goes on as it was
        else:
            fx = self._fx(sid)
            if fx is not None:
                self._ready[(sid, soundfx.key(fx))] = data
            m = self.mw.meta(sid)
            if m is not None:   # the busy card turns into this one
                self.mw.toast(_("✓ “{name}” is ready to play", name=html.escape(m.name)),
                              "ok", key=TOAST_KEY)
                self._shown_pct = -1
            if at is not None:
                self._replay(sid, at, data)
                self._ai_playing.add(sid)
            else:
                self.mw.playctl.play(sid, now=True)
        self._next_job()

    def _replay(self, sid: str, frac: float, data):
        """Play `sid` again from `frac` of the way in, with `data` (same length)."""
        mw = self.mw
        m = mw.meta(sid)
        if m is None or data is None:
            return
        mw.engine.stop(sid)
        mw.engine.play(sid, data, mw.gain_for(m), loop=m.loop, mode="overlap",
                       only=("main", "obs") if m.only_them else None)
        mw.engine.seek(sid, frac)

    def _stop_jobs(self, resume: bool):
        """Stop making AI versions; `resume`: the sounds waiting for them go on."""
        waiting = [(s, a) for s, a in self._jobs if a is not None]
        if self._job is not None and self._job[2] is not None:
            waiting.append((self._job[1], self._job[2]))
        self._jobs.clear()
        self._job = None
        self._gen += 1
        self._show_busy(None)
        if resume:
            for sid, _at in waiting:
                self.mw.engine.set_paused(sid, False)

    def shutdown(self):
        self._stop_jobs(resume=False)
        self._poll.stop()
        eng = self.mw.engine
        if eng.radio_voice is not None:
            eng.radio_voice.shutdown()
        eng.set_apps_setup(None)
