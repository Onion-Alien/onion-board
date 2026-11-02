"""Set up for the app you're using (appsetup.py), in the main window: noticing the voice app
or game in front and the device it hears, the bar that offers to set the board up for it
(Yes / Not now / x, with Undo), what it checks once it's done, and picking where sounds go
by itself.

MainWindow makes one ``AppSetupControl`` (``MainWindow.appsetctl``); everything here runs
on the UI thread except the looks it hands to a worker."""
from __future__ import annotations

import copy
import html
import logging
import os
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer

from soundboard.mic import appsetup, destination, profiles, voicesdk
from soundboard import i18n
from soundboard.audio import engine as eng
from soundboard.i18n import _
from soundboard.ui.window.alertcontrol import clean_mic_note
from soundboard.ui.window.controller import Controller

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

log = logging.getLogger(__name__)

SETUP_SWITCHED_MS = 8000   # how long "Voice chat mode for Discord. Undo" stays
SETUP_DONE_MS = 15000      # the set-up card with nothing left to do
VOICE_POLL_IDLE_S = 15   # ...while nobody sees the hint and nothing switches by itself


class AppSetupControl(Controller):
    """Set up for the app in use, for one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self._setup_hide = QTimer(mw, singleShot=True)
        self._setup_hide.timeout.connect(self._hide_setup)
        # set up for the app you're using (appsetup): the bar's app and what it shows.
        # Before the Discord check below: on a slow start its answer (_on_discord) comes
        # in while the splash pumps events, before the end of __init__
        self._setup_tracker = appsetup.Tracker()
        self._setup_app: appsetup.Seen | None = None
        self._setup_state = ""        # "offer", "done" or "" (hidden)
        self._setup_skipped: set[str] = set()   # answered Not now, this run
        self._setup_undo: dict | None = None    # the dest settings before a switch
        self._voice_at = 0.0   # when _poll_voice last ran (see _voice_tick)

    def _voice_tick(self):
        """The timer's _poll_voice: every VOICE_POLL_MS while the window is on screen
        (the hint shows) or *Pick the mode by itself* is ticked (it switches), else only
        every VOICE_POLL_IDLE_S: snapshotting the programs and recording sessions is
        wasted work while nobody sees the answer."""
        mw = self.mw
        d = mw.cfg.dest if isinstance(mw.cfg.dest, dict) else {}
        now = time.monotonic()
        if (not mw._ui_live and not d.get("auto")
                and not profiles.auto_picks(profiles.current(d))
                and not appsetup.settings(mw.cfg)["apps"]   # a remembered app switches
                and now - self._voice_at < VOICE_POLL_IDLE_S):
            return
        self._voice_at = now
        self._poll_voice()

    def _heard_device(self):
        """The recording device(s) whose listeners are the voice chat: the cable's far
        end, or with straight into my mic, the mic itself (Discord and games record it)
        and, if there's a cable, its far end too (a voice app still set to the cable)."""
        mw = self.mw
        if mw.cfg.route == "mic":
            if mw.engine.direct_stream() is None:
                return None
            cables = [mic for _out, mic in eng.virtual_pairs()]
            return tuple(dict.fromkeys(d for d in (mw.cfg.mic_device, *cables) if d))
        return eng.virtual_mic_for(mw.routectl._main_name())

    def _poll_voice(self):
        """Which Who's listening mode suits: the program recording the cable's far end
        (voicesdk.Listeners), else the voice engine of the game in front. The simple
        modes (soundboard.mic.profiles) pick within their family from all of it; in
        Advanced, *Pick the mode by itself* switches to the one suggested."""
        mw = self.mw
        key = mw.voice_watch.poll() if mw.voice_watch is not None else None
        why = i18n.keep_english(lambda: _("The game you have open uses {engine} for voice chat",
                                          engine=voicesdk.NAMES.get(key, key))) if key else ""
        heard = ()
        if mw.listeners is not None:
            heard = mw.listeners.poll(self._heard_device())
        # for the simple modes, in order: voice chat apps on the cable, the game in
        # front, games on the cable (a per-program list would go first)
        apps = set(voicesdk.VOICE_APPS.values())
        def listening(name: str) -> str:
            return i18n.keep_english(lambda: _("{name} is listening to your mic", name=name)
                                     if mw.cfg.route == "mic" else
                                     _("{name} is listening to the virtual cable", name=name))
        hints = [profiles.Hint(h[0], listening(h[1]),
                               profiles.VOICE.key) for h in heard if h in apps]
        if key:
            hints.append(profiles.Hint(key, why, profiles.GAME.key))
        hints += [profiles.Hint(h[0], listening(h[1]),
                                profiles.GAME.key) for h in heard if h not in apps]
        if heard:   # the game in front, if it's one of them; else the first
            key, name = next((h for h in heard if h[0] == key), heard[0])
            why = listening(name)
        if (key != mw.voice_suggestion or why != mw.voice_why
                or hints != mw.voice_hints):
            mw.voice_suggestion, mw.voice_why, mw.voice_hints = key, why, hints
            self._auto_dest()
            mw.voice_engine.emit(key)
        self._app_setup(self._apps_seen())

    def _apps_seen(self) -> list[appsetup.Seen]:
        """The apps using your sounds now, ranked as _poll_voice ranks its hints: voice
        chat apps listening, the game in front, games listening."""
        mw = self.mw
        heard = getattr(mw.listeners, "apps", ())   # (a stand-in may not have them)
        voice = [appsetup.Seen(exe, name, profiles.VOICE.key) for exe, _k, name in heard
                 if exe in voicesdk.VOICE_APPS]
        games = [appsetup.Seen(exe, name, profiles.GAME.key) for exe, _k, name in heard
                 if exe not in voicesdk.VOICE_APPS]
        w = mw.voice_watch
        path = getattr(w, "path", "")
        if path and getattr(w, "suggestion", None):
            base = os.path.basename(path)
            games.insert(0, appsetup.Seen(base.lower(), os.path.splitext(base)[0],
                                          profiles.GAME.key))
        out: dict[str, appsetup.Seen] = {}
        for app in voice + games:
            out.setdefault(app.exe, app)
        return list(out.values())

    def _app_setup(self, seen, now: float | None = None):
        """An app that just started using your sounds: switch to its remembered mode,
        or offer to set up for it (appsetup.decide). Nothing before the setup guide is
        done: that one picks the mode."""
        mw = self.mw
        now = time.monotonic() if now is None else now
        new = self._setup_tracker.update(seen, now)
        app = self._setup_app
        if (self._setup_state == "offer" and app is not None
                and not self._setup_tracker.here(app.exe, now)):
            self._hide_setup()   # it closed: nothing to set up any more
        if not new or not mw.cfg.setup_done:
            return
        d = mw.cfg.dest if isinstance(mw.cfg.dest, dict) else {}
        act = appsetup.decide(mw.cfg, new, profiles.current(d).key, self._setup_skipped)
        if act is None:
            return
        what, app = act
        if what == "switch":
            from soundboard.ui.setup.destpanel import set_simple
            self._setup_undo = copy.deepcopy(d)
            set_simple(mw, app.simple)
            log.info("app setup: %s -> %s mode (remembered)", app.exe, app.simple)
            self._hide_setup()   # (what it said was about before the switch)
            mw.toast(_("{mode} mode for <b>{name}</b>.", mode=profiles.BY_KEY[app.simple].name,
                         name=html.escape(app.name)), "ok", SETUP_SWITCHED_MS,
                       key="app-switch", action=(_("Undo"), self._undo_app_switch),
                       on_close=self._forget_app_switch)
            return
        self._show_setup("offer", app)

    def _undo_app_switch(self):
        """Undo on "Game mode for X": the mode goes back to how it was."""
        mw = self.mw
        if self._setup_undo is not None:
            from soundboard.ui.setup.destpanel import _refresh_views
            mw.cfg.dest = self._setup_undo
            self._setup_undo = None
            mw.mode_why = ""
            destination.apply(mw.cfg, mw.engine)
            mw._save_later()
            _refresh_views(mw)

    def _forget_app_switch(self):
        self._setup_undo = None

    def _show_setup(self, state: str, app: appsetup.Seen):
        mw = self.mw
        if state == "offer" and not mw.urgent_bar.isHidden():
            # The urgent bar (a Discord warning, a fix...) is already saying its piece:
            # never two bars at once. The offer waits; the warning wins (_show_urgent).
            self._setup_app, self._setup_state = None, ""
            return
        self._setup_app, self._setup_state = app, state
        self._setup_hide.stop()
        name = html.escape(app.name)
        mw.setup_x.setAccessibleName(_("Hide"))
        mw.setup_no.setVisible(state == "offer")
        if state == "offer":
            mw.setup_bar.set_tone("info", "chat")
            mw.setup_bar.set_message(_("Looks like you're using <b>{name}</b>. Set up for it?",
                                       name=name), rich=True)
            mw.setup_yes.setText(_("Set up"))
            mw.setup_x.setToolTip(_("Don't ask about {name} again", name=app.name))
            mw.setup_x.setAccessibleName(mw.setup_x.toolTip())
        else:
            lines, button = self._setup_checks(app)
            warn = any("⚠" in line for line in lines)
            mw.setup_bar.set_tone("warn" if warn else "ok", "warn" if warn else "check")
            mw.setup_bar.set_message("<br>".join(lines), rich=True)
            mw.setup_yes.setText(button)
            if not button:
                self._setup_hide.start(SETUP_DONE_MS)
        mw.setup_yes.setVisible(bool(mw.setup_yes.text()))
        mw.setup_bar.show()

    def _setup_checks(self, app: appsetup.Seen) -> tuple[list[str], str]:
        """The "done" card: what was set, what the app's own settings say, and the
        button for what's left ("" for none). Discord's problems already have the
        urgent bar, so they aren't said twice here."""
        mw = self.mw
        ok = "<span style='color:#3fb950'>✓</span>"
        warn = "<span style='color:#d29922'>⚠</span>"
        mode = profiles.BY_KEY[app.simple].name
        # (its ✓ is the bar's own icon)
        lines = [_("{ok} {mode} mode on for <b>{name}</b>. Next time it switches by itself.",
                   ok="", mode=mode, name=html.escape(app.name)).strip()]
        guide = app.guide
        if guide == "discord":
            if mw.alertctl.discord_problems():
                return lines, ""   # the urgent bar above says which, with Fix Discord
            if mw.alertctl.discord_found:
                lines.append(_("{ok} Discord's voice settings let your sounds through.",
                               ok=ok))
                return lines, ""
            return lines, _("Check Discord")
        if guide == "meeting":
            lines.append(" ".join(filter(None, (
                _("{warn} Its noise removal can wipe out music: set it to keep the original "
                  "sound.", warn=warn), clean_mic_note()))))
            return lines, _("Show me how")
        return lines, ""

    def _setup_yes_clicked(self):
        mw = self.mw
        app, state = self._setup_app, self._setup_state
        if app is None:
            return
        if state == "offer":
            from soundboard.ui.setup.destpanel import set_simple
            appsetup.remember(mw.cfg, app.exe, app.simple)
            set_simple(mw, app.simple)
            log.info("app setup: %s -> %s mode (set up)", app.exe, app.simple)
            self._show_setup("done", app)
            mw.app_setup_changed.emit()
        elif app.guide:
            mw.statusctl.show_chat_guide(app.guide)
            if self._setup_state == "done":
                self._show_setup("done", app)   # the ticks, as they are now

    def _setup_not_now(self):
        if self._setup_app is not None:
            self._setup_skipped.add(self._setup_app.exe)
        self._hide_setup()

    def _setup_x_clicked(self):
        mw = self.mw
        if self._setup_state == "offer" and self._setup_app is not None:
            appsetup.never(mw.cfg, self._setup_app.exe)
            mw._save_later()
            mw.app_setup_changed.emit()
            mw.toast(_("Won't ask about {name} again. Settings → General can change that.",
                         name=html.escape(self._setup_app.name)))
        self._hide_setup()

    def _hide_setup(self):
        mw = self.mw
        self._setup_hide.stop()
        self._setup_state = ""
        mw.setup_bar.hide()

    def _auto_dest(self):
        """Game and Voice chat: the shaping that suits what's seen, as soon as it's
        seen. Advanced with *Pick the mode by itself*: the suggested mode. Nothing seen
        keeps the mode it has."""
        mw = self.mw
        d = mw.cfg.dest if isinstance(mw.cfg.dest, dict) else {}
        mw.cfg.dest = d
        p = profiles.current(d)
        if profiles.auto_picks(p):
            was = destination.resolve(d).key
            key, mw.mode_why = profiles.choose(p, mw.voice_hints, was)
            if key == was:
                return
            d["simple"], d["mode"] = p.key, key
            mode = destination.apply(mw.cfg, mw.engine)
            mw._save_later()
            log.info("who's listening: %s mode switched to %s (%s)", p.key, key,
                     mw.mode_why)
            mw.toast(_("{mode} mode: shaping for {target}. {mode_why}.",
                         mode=p.name, target=mode.name, mode_why=mw.mode_why))
            return
        key = mw.voice_suggestion
        if not d.get("auto") or key not in destination.BUILTIN_BY_KEY:
            return
        if destination.resolve(d).key == key:
            return
        d["mode"] = key
        mode = destination.apply(mw.cfg, mw.engine)
        mw._save_later()
        log.info("who's listening: switched to %s (%s)", key, mw.voice_why)
        mw.toast(_("Who's listening: {label}. {voice_why}.",
                     label=mode.name, voice_why=mw.voice_why))
