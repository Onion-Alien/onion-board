"""Hotkeys in the main window: registering them (per category when hotkeys follow the
category), what each app-wide key does when pressed or let go, push-to-talk, MIDI pads and
instant replay saying why they can't work, setting a sound's, a category's or an app-wide
key (a combo does one thing: it comes off whatever had it), the Sounds tab's keyboard menu
and turning every hotkey off and on.

MainWindow makes one ``HotkeyControl`` (``MainWindow.hkctl``); everything here runs on the
UI thread."""
from __future__ import annotations

import html
import logging
import threading
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMenu

from soundboard.control import adminfront, midi, winkeys
from soundboard.ui.kit import theme
from soundboard.core import achievements, usage
from soundboard.audio.engine import SR
from soundboard.i18n import _, ngettext
from soundboard.sounds.library import SoundMeta
from soundboard.ui.kit.hotkeypick import HOTKEY_ACTIONS, HotkeyDialog, pretty_key
from soundboard.ui.kit import busy, icons
from soundboard.ui.window.controller import Controller
from soundboard.ui.kit.crashdialog import free_dialog

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

log = logging.getLogger(__name__)

RANDOM = "__random__:"   # hotkey action prefix: a random sound from the category after it
PICK_VOICE = "__pickvoice__:"   # ...: the voice (Voice tab) named after it
PICK_AI = "__pickai__:"         # ...: the AI voice with the id after it
# an AI voice's key sits with the voices' keys under this and its id (older versions
# skip it: no voice has that name)
AI_KEY = "ai:"
# shown when instant replay goes on: it records whoever is talking in a call
REPLAY_NOTE = _("Instant replay is on: your key keeps the last seconds you heard. In some "
                "places recording a call needs everyone's OK, so only keep clips of people "
                "who are fine with it.")


class HotkeyControl(Controller):
    """The hotkeys of one MainWindow (``mw``)."""
    _admin_started = Signal(bool)   # the admin copy was started (True) or not

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self._hotkeys_off = False         # "All hotkeys off": only that key still works
        self._off_remote = False          # ...turned off by the control API, which turns them on
        self._voice_was: bool | None = None   # voice changer state before a held key
        self._admin: adminfront.Watcher | None = None   # looks for games run as admin
        self._admin_started.connect(self._admin_answer)

    def _fit_overlay_key(self):
        """The default overlay key is the one left of 1 on a US keyboard, where it types
        a rarely used `. On most other layouts that key types a letter or everyday
        punctuation (ö, ñ, ù, UK '@), which a bare global hotkey would take away from
        typing everywhere: there it becomes Alt + that key. Checked once, so a key the
        user picks later is left alone."""
        mw = self.mw
        if mw.cfg.overlay_key_checked:
            return
        mw.cfg.overlay_key_checked = True
        if mw.cfg.overlay_hotkey == "`" and winkeys.key_char(winkeys.VK["`"]) not in ("`", ""):
            mw.cfg.overlay_hotkey = "alt+`"
            log.info("overlay hotkey moved to Alt+` for this keyboard layout")
        mw._save_later()

    def register_hotkeys(self):
        mw = self.mw
        mapping = {}
        if self._hotkeys_off and not mw.cfg.hotkeys_off_hotkey and not self._off_remote:
            # the key that turns them back on was cleared or given to something else:
            # nothing could turn them on again until a restart, so they're on now
            self._hotkeys_off = False
            mw.toast(_("Hotkeys are on again."), "ok", key="hotkeys")
        mw.hotkeys.share = mw.cfg.hotkeys_share
        mw.hotkeys.grab = set()
        if self._hotkeys_off:   # only the key that turns them back on
            if mw.cfg.hotkeys_off_hotkey:
                mapping[mw.cfg.hotkeys_off_hotkey] = "__hotkeys__"
            mw.hotkeys.register(mapping)
            mw.replay.set_enabled(bool(mw.cfg.replay_hotkey), mw.cfg.replay_seconds)
            return
        for attr, action, _label, _desc in HOTKEY_ACTIONS:
            combo = getattr(mw.cfg, attr)
            if combo:
                mapping.setdefault(combo, action)
        for m in mw.cfg.sounds:
            if m.hotkey and self._hotkey_live(m):
                mapping.setdefault(m.hotkey, m.id)
        for cat, combo in mw.cfg.category_hotkeys.items():
            if combo and cat in mw.cfg.categories:
                mapping.setdefault(combo, RANDOM + cat)
        fx = self._voice_fx()
        if fx is not None:
            fx.keys = dict(mw.cfg.voice_hotkeys)   # for the voice cards' menus
            known = fx.voice_names()
            for name, combo in mw.cfg.voice_hotkeys.items():
                if combo and name in known:
                    mapping.setdefault(combo, PICK_VOICE + name)
        ai = self._ai_panel()
        if ai is not None:
            ai.keys = {n[len(AI_KEY):]: c for n, c in mw.cfg.voice_hotkeys.items()
                       if n.startswith(AI_KEY) and c}
            ids = {vo["id"] for vo in ai.voices}
            for vid, combo in ai.keys.items():
                if vid in ids:
                    mapping.setdefault(combo, PICK_AI + vid)
        layer = mw.overlay.layer()   # its keys, only while it's open
        mapping.update(layer)
        mw.hotkeys.grab = set(layer)   # ...and they never reach the game
        # the game's push-to-talk key is pressed by us (auto-PTT) and by the player: as a
        # hotkey of ours, Windows would hand those presses to us instead of the game
        mapping.pop(mw.cfg.ptt_key, None)
        mw.hotkeys.register(mapping)
        # instant replay listens only while its hotkey is set
        mw.replay.set_enabled(bool(mw.cfg.replay_hotkey), mw.cfg.replay_seconds)
        if mapping and self._admin is None:
            self._admin = adminfront.Watcher(self)
            self._admin.found.connect(self._admin_in_front)
            self._admin.start()

    def _admin_in_front(self, _exe: str):
        """A game run as admin came to the front (adminfront): Windows keeps its keys
        from us, so say why the hotkeys go quiet there, and offer the way round it.
        Once per game while the board runs; never while every hotkey is off."""
        if self._hotkeys_off:
            return
        usage.used("admin-game")
        self.mw.tell(_("Your hotkeys can't reach this game"),
                     _("The game runs as admin, and Windows doesn't let other programs "
                       "hear the keys you press in it. Start Onion Board as admin too to "
                       "use your hotkeys there."),
                     "warn", 0, key="admin-game",
                     action=(_("Restart as admin"), self.restart_as_admin))

    def restart_as_admin(self):
        """Start the board again as admin (Windows asks first), then quit this copy.
        The prompt waits for an answer, so it's asked from a worker thread."""
        usage.used("admin-restart")
        args = self.mw.restart_args()
        threading.Thread(target=lambda: busy.emit(self._admin_started,
                                                  adminfront.start_elevated(args),
                                                  owner=self),
                         daemon=True, name="restart-admin").start()

    def _admin_answer(self, started: bool):
        if started:
            self.mw.quit_app()   # the admin copy waits for this one to be gone
        else:
            self.mw.toast(_("Onion Board is still running without admin."), key="admin-game")

    def _hotkey_live(self, m: SoundMeta) -> bool:
        """Does m's hotkey work right now? Always, unless hotkeys follow the category
        (scoped_hotkeys): then only while a category it's in is showing (All shows
        every sound; one in no category always keeps its key)."""
        mw = self.mw
        cat = mw.cfg.category
        return not mw.cfg.scoped_hotkeys or not cat or not m.tags or cat in m.tags

    def set_share_hotkeys(self, on: bool):
        """Settings -> Hotkeys: the game still gets a hotkey's key (on), or only we do."""
        mw = self.mw
        mw.cfg.hotkeys_share = on
        mw._save_now()
        self.register_hotkeys()

    def set_scoped_hotkeys(self, on: bool):
        """Settings -> Hotkeys: a set of sound hotkeys per category."""
        mw = self.mw
        mw.cfg.scoped_hotkeys = on
        if not on:   # one key, one sound again: the first sound (in board order) keeps it
            seen = set(self._global_combos())
            for m in mw.cfg.sounds:
                if m.hotkey and m.hotkey in seen:
                    m.hotkey = ""
                    if m.id in mw.pads:
                        mw.pads[m.id].update()
                elif m.hotkey:
                    seen.add(m.hotkey)
        mw._save_now()
        self.register_hotkeys()

    def _global_combos(self) -> list[str]:
        """Combos the app-wide actions, the push-to-talk key and category keys hold."""
        mw = self.mw
        return ([getattr(mw.cfg, a) for a, *__ in HOTKEY_ACTIONS if getattr(mw.cfg, a)]
                + [c for c in (mw.cfg.ptt_key, *mw.cfg.category_hotkeys.values(),
                               *mw.cfg.voice_hotkeys.values()) if c])

    def on_hotkey_released(self, action: str):
        """A hotkey or MIDI pad was let go: a hold-to-play sound stops, and an overlay
        in hold mode opened by a MIDI pad closes (a key's release it watches itself)."""
        mw = self.mw
        m = mw._meta.get(action)
        if action == "__voicehold__":
            if self._voice_was is not None:
                self._set_voice(self._voice_was)
                self._voice_was = None
        elif m is not None and m.hold:
            mw.playctl._cancel_waiting(action)
            mw.engine.stop(action)
        elif (action == "__overlay__" and mw.overlay.s.mode == "hold"
              and midi.is_midi(mw.cfg.overlay_hotkey) and mw.overlay.is_open):
            mw.overlay.close()

    def on_midi_busy(self, busy: list[str]):
        mw = self.mw
        if busy:
            mw.say(_("<span style='color:{status}'>{devices} is open in another "
                       "program (a music app?), so its pads don't work here until "
                       "that program lets go of it.</span>",
                       status=theme.status('warn'),
                       devices=html.escape(", ".join(busy))), "warn")

    def on_replay_state(self):
        mw = self.mw
        if mw.replay.enabled and mw.replay.error:
            mw.say(_("<span style='color:{status}'>Instant replay can't listen: "
                       "{error}</span>", status=theme.status('warn'),
                       error=html.escape(mw.replay.error)), "warn")

    def save_replay(self):
        """The instant-replay hotkey: the last seconds of what you heard become a pad."""
        mw = self.mw
        data = mw.replay.clip()
        if len(data) < int(0.2 * SR):
            mw.playctl.cue("fail")
            why = mw.replay.error or ngettext(
                "nothing has played on this PC in the last {n} second",
                "nothing has played on this PC in the last {n} seconds", mw.replay.seconds)
            mw.say(_("<span style='color:{status}'>Nothing to save: {why}.</span>",
                       status=theme.status('warn'), why=html.escape(why)), "warn")
            return
        mw.soundctl.on_clip(data, _("Replay {time}", time=time.strftime("%H.%M.%S")))
        mw.playctl.cue("saved")

    def on_hotkeys_failed(self, failed: list[str]):
        mw = self.mw
        if not failed:
            return
        log.warning("hotkeys that couldn't be claimed: %s", failed)
        mw.say(_("<span style='color:{status}'>Another program is already "
                   "using {keys}, pick a different hotkey.</span>",
                   status=theme.status('warn'),
                   keys=html.escape(", ".join(pretty_key(c) for c in failed))), "warn",
               key="hotkey")   # (in place of the "✓ … plays" just said for a key set now)

    def _valid_hotkey(self, combo: str, mouse: bool = False) -> str | None:
        """`combo` as it's saved, or None (and a toast saying why) if no keyboard could
        ever send it: such a key used to be saved and shown as working. `mouse`: a mouse
        side button is fine too (auto push-to-talk)."""
        if not combo:
            return combo
        good, why = winkeys.check(combo, mouse)
        if why:
            log.info("refused hotkey %r: %s", combo[:80], why)
            usage.used("hotkey-refused")   # never which key
            self.mw.toast(_("Hotkey not saved: {why}", why=why), "warn", key="hotkey")
            return None
        return good

    def keeps_stop_key(self, combo: str) -> bool:
        """True (and a toast saying why) if `combo` is the Stop everything key: it stays
        on that. Handing it to a sound or another action left no key to stop every sound
        at once."""
        mw = self.mw
        if not combo or combo != mw.cfg.stop_hotkey:
            return False
        mw.toast(_("{key} is your Stop everything key, so it stays on that. Pick another key, "
                   "or give Stop everything a new one in Settings → Hotkeys first.",
                   key=html.escape(pretty_key(combo))), "warn", key="hotkey")
        return True

    def everyday_note(self, combo: str):
        """Ctrl+C, Alt+Tab and the like work as hotkeys, but then they stop doing their
        own job in every other app while the board runs: say so."""
        if combo and winkeys.everyday(combo):
            self.mw.toast(_("Heads up: while Onion Board is open, {key} plays your hotkey "
                            "instead of doing its usual job in other apps.",
                            key=html.escape(pretty_key(combo))), "warn", key="hotkey-everyday")

    def set_global_hotkey(self, attr: str, combo: str):
        """Set one of the app-wide hotkeys (or ptt_key). A combo can only do one thing,
        so it's taken off any other action or sound that had it, and a toast says what
        lost it: a key quietly going off a pad was a surprise the next time it was
        pressed in a game."""
        mw = self.mw
        good = self._valid_hotkey(combo, mouse=attr == "ptt_key")
        if good is None:
            self.register_hotkeys()   # the capture paused them
            return
        combo = good
        if attr != "stop_hotkey" and self.keeps_stop_key(combo):
            self.register_hotkeys()
            return
        lost = []
        if combo:
            lost = self._take_actions(combo, keep=attr) + self._take_sounds(combo)
            lost += [_("a random sound from “{name}”", name=c)
                     for c in self._clear_category_hotkey(combo)]
            lost += [_("the voice “{name}”", name=n) for n in self._clear_voice_hotkey(combo)]
            if attr != "ptt_key":
                lost += self._take_ptt(combo)
        if attr == "replay_hotkey" and combo and not mw.cfg.replay_hotkey:
            mw.toast(REPLAY_NOTE)   # instant replay just went on
        setattr(mw.cfg, attr, combo)
        mw._save_now()
        self.register_hotkeys()
        if lost:
            what = (_("auto push-to-talk") if attr == "ptt_key"
                    else next((label for a, _ac, label, _d in HOTKEY_ACTIONS if a == attr), attr))
            mw.toast(_("{hotkey} is {what} now, it was the key for {lost}",
                         hotkey=html.escape(pretty_key(combo)), what=html.escape(what),
                         lost=html.escape(_(" and ").join(lost))), "warn")
        self.everyday_note(combo)

    def _fill_quick_hotkeys(self, menu: QMenu):
        """The Sounds tab's keyboard button: the common hotkeys with their keys (click
        one to set it), then a way into Settings → Hotkeys for the rest."""
        mw = self.mw
        menu.clear()
        labels = {attr: label for attr, _a, label, _d in HOTKEY_ACTIONS}
        labels["ptt_key"] = _("Auto push-to-talk key")
        for attr in (*mw.QUICK_HOTKEYS, "ptt_key"):
            combo = getattr(mw.cfg, attr)
            key = pretty_key(combo) or (_("Off") if attr == "ptt_key" else _("not set"))
            icons.set_icon(menu.addAction(f"{labels[attr]}	{key}",
                                          lambda a=attr: self._quick_set_hotkey(a)), "keyboard")
        menu.addSeparator()
        icons.set_icon(menu.addAction(_("All hotkeys"),
                                      lambda: mw.setctl.open_settings("hotkeys")),
                       "settings")

    def _quick_set_hotkey(self, attr: str):
        mw = self.mw
        d = HotkeyDialog(mw.hotkeys, mw, pads=attr != "ptt_key", mouse=attr == "ptt_key")
        if d.exec() and d.result_combo:
            self.set_global_hotkey(attr, d.result_combo)
        else:
            self.register_hotkeys()   # the capture paused them
        free_dialog(d)

    def on_hotkey(self, action):
        mw = self.mw
        if action == "__hotkeys__":
            self.toggle_hotkeys()
            return
        if self._hotkeys_off:   # one already on its way when they were turned off
            return
        if mw.overlay.handle(action):
            return
        if action == "__stop__":
            mw.playctl.stop_all()
        elif action == "__last__":
            mw.playctl.play_last()
        elif action in ("__nextcat__", "__prevcat__"):
            self.step_category(1 if action == "__nextcat__" else -1)
        elif action in ("__volup__", "__voldown__"):
            self.step_sound_volume(1 if action == "__volup__" else -1)
        elif action == "__mic__":
            mw.chk_mic.setChecked(not mw.chk_mic.isChecked())   # -> on_mic_toggle
            mw.playctl.cue("start" if mw.cfg.mic_enabled else "stop")
        elif action == "__voice__":
            on = not mw.voice.fx.btn_power.isChecked()
            self._voice_was = None
            self._set_voice(on)
            # the Voice tab switched off: nothing went on, so no "on" beep either
            mw.playctl.cue("fail" if not mw.tabctl.tab_on("voice") else "start" if on else "stop")
        elif action == "__voices__":
            self.toggle_voices()
        elif action == "__voicehold__":
            if self._voice_was is None and mw.tabctl.tab_on("voice"):
                self._voice_was = mw.voice.fx.btn_power.isChecked()
            self._set_voice(True)
        elif action == "__replay__":
            self.save_replay()
        elif action == "__pause__":
            mw.playctl._pause_clicked()
        elif action == "__skip__":
            mw.playctl.skip_next()
        elif action == "__random__":
            mw.playctl.play_random()
        elif action.startswith(RANDOM):
            mw.playctl.play_random(action[len(RANDOM):])
        elif action.startswith(PICK_VOICE):
            self.pick_voice(action[len(PICK_VOICE):])
        elif action.startswith(PICK_AI):
            self.pick_ai_voice(action[len(PICK_AI):])
        elif action == "__voicerandom__":
            self.random_voice()
        else:
            achievements.played_by("hotkey", hidden=not mw.isVisible() or mw.isMinimized())
            mw.playctl.play(action)

    def _voice_fx(self):
        """The Voice tab's voice grid, or None while the tab is switched off."""
        mw = self.mw
        voice = getattr(mw, "voice", None)
        return voice.fx if voice is not None and mw.tabctl.tab_on("voice") else None

    def pick_voice(self, name: str):
        """A voice's own hotkey (or the tray): turns the voice changer on with it."""
        mw = self.mw
        fx = self._voice_fx()
        if fx is None:
            mw.playctl.cue("fail")
            mw.toast(_("The Voice tab is switched off (Settings > Tabs)."), "warn")
            return
        if name not in fx.voice_names():   # deleted since the key was set
            mw.playctl.cue("fail")
            return
        self._voice_was = None
        fx.pick(name)
        mw.playctl.cue("start")

    def _ai_panel(self):
        """The Voice tab's AI voices card, or None while the tab is switched off."""
        mw = self.mw
        voice = getattr(mw, "voice", None)
        return (getattr(voice, "ai", None)
                if voice is not None and mw.tabctl.tab_on("voice") else None)

    def _ai_name(self, vid: str) -> str:
        ai = self._ai_panel()
        vo = next((v for v in ai.voices if v["id"] == vid), None) if ai is not None else None
        return str(vo.get("name") or vid) if vo else vid

    def pick_ai_voice(self, vid: str):
        """An AI voice's own hotkey: that voice, on (as clicking its card)."""
        mw = self.mw
        ai = self._ai_panel()
        if ai is None or vid not in {vo["id"] for vo in ai.voices}:
            mw.playctl.cue("fail")
            return
        self._voice_was = None
        ai.use(vid)
        mw.playctl.cue("start")

    def set_ai_voice_hotkey(self, vid: str, combo: str | None = None):
        """The hotkey that turns the AI voice `vid` on (asks for it unless given; ""
        clears it). Kept with the voices' keys, so a key does one voice either way."""
        mw = self.mw
        if combo is None:
            combo = self._ask_combo()
            if combo is None:
                self.register_hotkeys()   # the capture paused them
                return
        combo = self._valid_hotkey(combo)
        if combo is None or self.keeps_stop_key(combo):
            self.register_hotkeys()
            return
        name = self._ai_name(vid)
        if combo:
            taken_from = self._take_actions(combo) + self._take_sounds(combo)
            taken_from += [_("a random sound from “{name}”", name=c)
                           for c in self._clear_category_hotkey(combo)]
            taken_from += [_("the voice “{name}”", name=n)
                           for n in self._clear_voice_hotkey(combo, keep=AI_KEY + vid)]
            taken_from += self._take_ptt(combo)
            mw.cfg.voice_hotkeys[AI_KEY + vid] = combo
            msg = (_("✓ {combo} picks the voice “{name}”, it was the key for {lost}",
                     combo=html.escape(pretty_key(combo)), name=html.escape(name),
                     lost=html.escape(", ".join(taken_from))) if taken_from
                   else _("✓ {combo} picks the voice “{name}”",
                          combo=html.escape(pretty_key(combo)), name=html.escape(name)))
            mw.toast(msg, "ok")
            self.everyday_note(combo)
        else:
            mw.cfg.voice_hotkeys.pop(AI_KEY + vid, None)
            mw.toast(_("Hotkey for the voice “{name}” cleared", name=html.escape(name)))
        mw._save_now()
        self.register_hotkeys()

    def random_voice(self):
        """The Random voice key: the Voice tab's die, from anywhere."""
        mw = self.mw
        fx = self._voice_fx()
        if fx is None:
            mw.playctl.cue("fail")
            mw.toast(_("The Voice tab is switched off (Settings > Tabs)."), "warn")
            return
        self._voice_was = None
        mw.playctl.cue("start" if fx.roll() else "fail")

    def toggle_voices(self):
        """The All voices key: the Voice tab's Voices switch, from anywhere."""
        mw = self.mw
        if not mw.tabctl.tab_on("voice"):
            mw.playctl.cue("fail")
            mw.toast(_("The Voice tab is switched off (Settings > Tabs)."), "warn")
            return
        self._voice_was = None   # a held voice key lets go of nothing now
        mw.playctl.cue("start" if mw.voice.toggle_voices() else "stop")

    def _set_voice(self, on: bool):
        """The voice changer's big ON / OFF switch, from a hotkey."""
        mw = self.mw
        if not mw.tabctl.tab_on("voice"):
            if on:
                mw.toast(_("The Voice tab is switched off (Settings > Tabs)."), "warn")
            return
        if mw.voice.fx.btn_power.isChecked() != on:
            mw.voice.fx.btn_power.setChecked(on)   # its toggled handler applies it

    def toggle_hotkeys(self):
        """All hotkeys off (they type normally again), or back on. Not saved: the app
        always opens with them on."""
        if not self._hotkeys_off and not self.mw.cfg.hotkeys_off_hotkey:
            return   # no key to turn them back on with
        self.set_hotkeys_on(self._hotkeys_off)

    @property
    def hotkeys_on(self) -> bool:
        return not self._hotkeys_off

    def set_hotkeys_on(self, on: bool, remote: bool = False):
        """All hotkeys on, or off (the key that toggles them, or the control API's
        /api/hotkeys with `remote`, turns them back on)."""
        mw = self.mw
        if on != self._hotkeys_off:
            return   # already so
        self._hotkeys_off = not on
        self._off_remote = remote and not on
        if self._hotkeys_off and self._voice_was is not None:   # a held voice key
            self._set_voice(self._voice_was)
            self._voice_was = None
        self.register_hotkeys()
        mw.playctl.cue("stop" if self._hotkeys_off else "start")
        key = pretty_key(mw.cfg.hotkeys_off_hotkey)
        if self._hotkeys_off and not mw.cfg.hotkeys_off_hotkey:
            pass   # off from the control API, with no key: the button that did it says so
        elif self._hotkeys_off:
            mw.say(_("<span style='color:{status}'>Hotkeys are off: {key} turns them back "
                       "on.</span>", status=theme.status('warn'), key=html.escape(key)),
                     "warn", key="hotkeys")
        else:
            mw.toast(_("Hotkeys are on again."), "ok", key="hotkeys")

    def step_category(self, step: int):
        """Next / previous category (with All at the front), with a beep for each
        place along it, so you can tell where you are without looking."""
        mw = self.mw
        names = ["", *mw.cfg.categories]
        if len(names) < 2:
            mw.playctl.cue("fail")
            return
        i = names.index(mw.cfg.category) if mw.cfg.category in names else 0
        name = names[(i + step) % len(names)]
        mw.catctl.set_category(name)
        n = names.index(name)
        # All: one low beep; the 1st category one high beep, the 2nd two... (up to 5)
        mw.playctl.cue((523,) if n == 0 else ((784, 0) * min(n, 5))[:-1])
        mw.toast(_("Category: {value}", value=html.escape(name or 'All')), key="category")

    def step_sound_volume(self, step: int):
        """The louder / quieter hotkeys: the sounds' volume box by 10 % a press, and the
        "My headphones" slider with it (the sounds' box only shows while one plays, so
        a key press otherwise showed nothing)."""
        mw = self.mw
        new = 0
        for vol in (mw.vol_mon, mw.vol_sound):   # -> mon_vol, sound_vol
            pct = vol.spin.value()
            new = min(max((round(pct / 10) + step) * 10, 0), vol.spin.maximum())
            vol.spin.setValue(new)
        mw.playctl.cue((880, 1175) if step > 0 else (880, 659))
        mw.toast(_("Sounds: {new}%", new=new), key="volume")

    def _hotkey_taken(self, combo: str) -> bool:
        """Does a sound, an app-wide action, the push-to-talk key or a category's
        random-sound key already have `combo`?"""
        mw = self.mw
        return (any(o.hotkey == combo for o in mw.cfg.sounds)
                or any(getattr(mw.cfg, attr) == combo for attr, *__ in HOTKEY_ACTIONS)
                or mw.cfg.ptt_key == combo
                or combo in mw.cfg.category_hotkeys.values()
                or combo in mw.cfg.voice_hotkeys.values())

    def _shares_keys(self, a: SoundMeta, b: SoundMeta) -> bool:
        """Can a and b's hotkeys be live at the same time? With a set of hotkeys per
        category, two sounds with no category in common can share a key."""
        mw = self.mw
        return (not mw.cfg.scoped_hotkeys or not a.tags or not b.tags
                or bool(set(a.tags) & set(b.tags)))

    def _clear_dupe_hotkey(self, m) -> list[str]:
        """A combo does one thing: m's hotkey comes off whatever else had it. Returns
        what lost it ("“Boom”", "Stop everything"...), and says so in the status line,
        so a key taken from another sound or action is never a silent surprise."""
        mw = self.mw
        lost = []
        if not m.hotkey:
            return lost
        lost = (self._take_sounds(m.hotkey, keep=lambda o: o is m or not self._shares_keys(o, m))
                + self._take_actions(m.hotkey))
        lost += [_("a random sound from “{name}”", name=c)
                 for c in self._clear_category_hotkey(m.hotkey)]
        lost += [_("the voice “{name}”", name=n) for n in self._clear_voice_hotkey(m.hotkey)]
        lost += self._take_ptt(m.hotkey)   # as everywhere else a key is set
        if lost:
            mw.say(
                _("<span style='color:{status}'>{hotkey} plays “{name}” now, it was the key for "
                  "{lost}.</span>",
                  status=theme.status('warn'), hotkey=html.escape(pretty_key(m.hotkey)),
                  name=html.escape(m.name), lost=html.escape(_(" and ").join(lost))),
                "warn", 8000, key="hotkey")
        return lost

    def set_sound_hotkey(self, sid: str, combo: str | None = None):
        """The pad menu's hotkey: asks for one unless given ("" removes it)."""
        mw = self.mw
        m = mw.meta(sid)
        if m is None:
            return
        if combo is None:
            combo = self._ask_combo()
        if combo is not None:
            combo = self._valid_hotkey(combo)
        if combo and self.keeps_stop_key(combo):
            combo = None
        if combo is not None and combo != m.hotkey:
            m.hotkey = combo
            lost = self._clear_dupe_hotkey(m)
            mw._save_now()
            if sid in mw.pads:
                mw.pads[sid].update()
            if not lost:   # else its warning already says what the key plays now
                mw.toast(_("✓ {combo} plays “{name}”",
                             combo=html.escape(pretty_key(combo)),
                             name=html.escape(m.name)) if combo
                           else _("Hotkey removed from “{name}”", name=html.escape(m.name)),
                           key="hotkey")
            self.everyday_note(combo)
        self.register_hotkeys()   # the capture paused them

    def _take_actions(self, combo: str, keep: str = "") -> list[str]:
        """A combo does one thing: take it off the app-wide hotkeys (not `keep`'s).
        Returns their labels."""
        mw = self.mw
        lost = []
        for attr, _action, label, _desc in HOTKEY_ACTIONS:
            if attr != keep and getattr(mw.cfg, attr) == combo:
                setattr(mw.cfg, attr, "")
                lost.append(label)
        return lost

    def _take_sounds(self, combo: str, keep=lambda o: False) -> list[str]:
        """...and off the sounds' hotkeys (not those `keep(o)` picks). Returns their names."""
        mw = self.mw
        lost = []
        for o in mw.cfg.sounds:
            if o.hotkey == combo and not keep(o):
                o.hotkey = ""
                lost.append(f"“{o.name}”")
                if o.id in mw.pads:
                    mw.pads[o.id].update()
        return lost

    def _take_ptt(self, combo: str) -> list[str]:
        """...and off auto push-to-talk."""
        mw = self.mw
        if mw.cfg.ptt_key == combo:
            mw.cfg.ptt_key = ""
            return [_("auto push-to-talk")]
        return []

    def _ask_combo(self) -> str | None:
        """The key capture: the combo picked, or None."""
        mw = self.mw
        d = HotkeyDialog(mw.hotkeys, mw)
        combo = d.result_combo if d.exec() and d.result_combo else None
        free_dialog(d)
        return combo

    def _clear_category_hotkey(self, combo: str, keep: str | None = None) -> list[str]:
        """A combo does one thing: take it off any category's random-sound hotkey.
        Returns what lost it."""
        mw = self.mw
        gone = ([c for c, k in mw.cfg.category_hotkeys.items() if k == combo and c != keep]
                if combo else [])
        for cat in gone:
            del mw.cfg.category_hotkeys[cat]
        return gone

    def _clear_voice_hotkey(self, combo: str, keep: str | None = None) -> list[str]:
        """A combo does one thing: take it off any voice's hotkey. Returns what lost it."""
        mw = self.mw
        gone = ([n for n, k in mw.cfg.voice_hotkeys.items() if k == combo and n != keep]
                if combo else [])
        for v in gone:
            del mw.cfg.voice_hotkeys[v]
        return [self._ai_name(n[len(AI_KEY):]) if n.startswith(AI_KEY) else n for n in gone]

    def voice_renamed(self, old: str, new: str):
        """A saved voice got a new name: its key goes with it."""
        mw = self.mw
        if old in mw.cfg.voice_hotkeys:
            mw.cfg.voice_hotkeys[new] = mw.cfg.voice_hotkeys.pop(old)
            mw._save_now()
            self.register_hotkeys()

    def set_voice_hotkey(self, name: str, combo: str | None = None):
        """The hotkey that picks voice `name` and turns the voice changer on (asks for
        it unless given; "" clears it)."""
        mw = self.mw
        fx = self._voice_fx()
        if fx is None or name not in fx.voice_names():
            return
        if combo is None:
            combo = self._ask_combo()
            if combo is None:
                self.register_hotkeys()   # the capture paused them
                return
        combo = self._valid_hotkey(combo)
        if combo is None or self.keeps_stop_key(combo):
            self.register_hotkeys()
            return
        if combo:
            taken_from = self._take_actions(combo) + self._take_sounds(combo)
            taken_from += [_("a random sound from “{name}”", name=c)
                           for c in self._clear_category_hotkey(combo)]
            taken_from += [_("the voice “{name}”", name=n)
                           for n in self._clear_voice_hotkey(combo, keep=name)]
            taken_from += self._take_ptt(combo)
            mw.cfg.voice_hotkeys[name] = combo
            msg = (_("✓ {combo} picks the voice “{name}”, it was the key for {lost}",
                     combo=html.escape(pretty_key(combo)), name=html.escape(name),
                     lost=html.escape(", ".join(taken_from))) if taken_from
                   else _("✓ {combo} picks the voice “{name}”",
                          combo=html.escape(pretty_key(combo)), name=html.escape(name)))
            mw.toast(msg, "ok")
            self.everyday_note(combo)
        else:
            mw.cfg.voice_hotkeys.pop(name, None)
            mw.toast(_("Hotkey for the voice “{name}” cleared", name=html.escape(name)))
        mw._save_now()
        self.register_hotkeys()

    def set_category_hotkey(self, name: str, combo: str | None = None):
        """The hotkey that plays a random sound from category `name` (asks for it
        unless given; "" clears it)."""
        mw = self.mw
        if name not in mw.cfg.categories:
            return
        if combo is None:
            combo = self._ask_combo()
            if combo is None:
                self.register_hotkeys()   # the capture paused them
                return
        combo = self._valid_hotkey(combo)
        if combo is None or self.keeps_stop_key(combo):
            self.register_hotkeys()
            return
        taken_from = []
        if combo:
            taken_from = ([_("another action") for __ in self._take_actions(combo)]
                          + self._take_sounds(combo))
            self._clear_category_hotkey(combo, keep=name)
            taken_from += [_("the voice “{name}”", name=n) for n in self._clear_voice_hotkey(combo)]
            self._take_ptt(combo)   # (its toast doesn't name it)
            mw.cfg.category_hotkeys[name] = combo
            if taken_from:
                msg = _("✓ {combo} plays a random “{name}” sound, it was the key for {lost}",
                        combo=html.escape(pretty_key(combo)), name=html.escape(name),
                        lost=html.escape(", ".join(taken_from)))
            else:
                msg = _("✓ {combo} plays a random “{name}” sound",
                        combo=html.escape(pretty_key(combo)), name=html.escape(name))
            mw.toast(msg, "ok")
            self.everyday_note(combo)
        else:
            mw.cfg.category_hotkeys.pop(name, None)
            mw.toast(_("Random-sound hotkey for “{name}” cleared", name=html.escape(name)))
        mw._save_now()
        mw.catctl._fill_categories()
        self.register_hotkeys()

    def _release_ptt(self) -> bool:
        """Let go of the PTT key we hold. False if Windows refused the key-up (an
        admin window or a UAC prompt in front blocks it): it stays ours to release,
        or the game's push-to-talk would stay stuck down."""
        mw = self.mw
        if mw._ptt_held:
            if not winkeys.ptt_up(mw._ptt_held):
                return False
            mw._ptt_held = None
        return True
