"""Straight into the mic and the virtual cable, in the main window: the mic effect's status
on the Setup tab, putting it on the mic (and back on by itself when Windows takes it
off), the mic helper, noticing when it stops working and falling back to the cable;
the cable's install, removal and sample-rate fix; opening Windows' mic settings.

MainWindow makes one ``MicControl`` (``MainWindow.micctl``); everything here runs on the
UI thread except the jobs it hands to workers."""
from __future__ import annotations

import html
import logging
import subprocess
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from soundboard.mic import directmic, michelper, micprobe, sonarkeep, voicesdk
from soundboard.ui.kit import theme
from soundboard.core import errors, usage
from soundboard.core.pollthread import PollThread
from soundboard.online import net
from soundboard.audio import engine as eng
from soundboard.i18n import _
from soundboard.sounds.library import RESOURCE_DIR
from soundboard.ui.kit import busy, icons, reveal, worker
from soundboard.ui.window.controller import Controller

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

log = logging.getLogger(__name__)

HELPER_RETRY_S = 60.0   # a mic helper check that failed is tried again after this long
MIC_OFFER_MS = 1000   # an older mic part's update is offered this long after the window shows
# The mic check after a set-up (probe_mic) is only counted for now: how often the probe
# goes missing on mics nobody here could test (a headset brand's own effect on the mic)
# decides whether the card's Repair and the cut-off app's toast are switched on.
PROBE_SHOWS = False


class MicControl(Controller):
    """The mic effect and the virtual cable of one MainWindow (``mw``)."""

    _mic_offer = None       # the open MicUpdateOffer
    _mic_updating = False   # attach_mic was started from it (its own result messages)
    _autofixing = False     # attach_mic(auto=True): the app's own repair, nobody clicked
    _autofix_err = ""       # that repair failed: the card asks for a click until it works
    fail_code = ""          # the last set-up failed: its short code, for the report button
    _mic_fail_kind = ""     # the last set-up's directmic.FAIL_KINDS word, for the count
    _autofix_tried = False  # it ran since the mic last worked (once per time it's off)
    _declined = False       # the last set-up's Windows prompt got a No
    _raised = None          # exit code 1: directmic.raised_why() of that set-up
    _fallback = None        # directmic.helper_fallback() of that set-up
    _stuck = ""             # exit code 6: directmic.stuck_why() of that set-up
    _unstarted = ""         # exit code 8: directmic.unstarted_why() of that set-up
    _helper_checking = False
    _helper_failed = False  # the last check raised: the next waits HELPER_RETRY_S
    _helper_check_at = 0.0  # when the last check started (time.monotonic())
    _helper_switching = False   # switch_helper(False) is removing it
    helper_removed = Signal(bool)    # (that job's answer: it's gone)
    helper_switched = Signal(bool)   # the helper's switch ended up on (True) or off
    _mic_offered = False    # shown this start (it comes back next start until updated)
    _following_effect = False
    _alive_before: frozenset = frozenset()   # other mics with sound before the set-up
    _probe_due = False      # a set-up worked: probe_mic once it's running
    _probing = False
    _probe_missing = False  # the probe didn't come out of the mic: the card says so

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self.cable_bad = []               # cable ends not at 48 kHz (_check_cable_format)
        # SteelSeries Sonar's devices, set back after Windows' audio restarts (keep_sonar)
        self.sonar = sonarkeep.SonarKeep(directmic.sonar_devices, directmic.sonar_set_back)
        self.sonar_poll = PollThread("sonar-keep")
        self.helper_removed.connect(self._helper_removed)

    def keep_sonar(self):
        """About once a second: while the mic is SteelSeries Sonar's, its devices are
        noted, and set back when an audio restart moved them (soundboard.mic.sonarkeep).
        Not during the mic effect's own steps: they set Sonar back themselves."""
        mw = self.mw
        mic = mw.cfg.mic_device or ""
        on = mic.startswith(directmic.SONAR_MIC) and not mw._attaching
        do = self.sonar.tick(time.monotonic(), on, mw.engine.mic_live())
        if do == "note":
            self.sonar_poll.run(lambda: self.sonar.note(time.monotonic()))
        elif do == "back":
            self.sonar_poll.run(lambda: self.sonar.back(time.sleep, time.monotonic))

    def _mic_update_due(self) -> bool:
        mw = self.mw
        cfg = mw.cfg
        return (cfg.route == "mic" and bool(cfg.mic_device) and not mw._attaching
                and directmic.status(cfg.mic_device) == "outdated")

    def _offer_mic_update(self):
        """An older mic part (1.9.20 and before sat where raw streams skip it: Discord's
        Studio, Chrome, Edge) is offered an update a second after the window opens, not
        left to a button nobody looks for. Windows' admin prompt only comes after
        *Install update*: never by itself, and never from the tray (showEvent asks again
        once the window is open). Offered again each start until it's updated: an old
        part may not reach every app. Setup keeps the button meanwhile."""
        mw = self.mw
        if mw._shut_down or self._mic_offer is not None or self._mic_offered:
            return
        if not mw.isVisible():
            return
        if mw.isMinimized() or QApplication.activeModalWidget() is not None:
            QTimer.singleShot(MIC_OFFER_MS, mw, self._offer_mic_update)   # once it's free
            return
        if not self._mic_update_due():
            return
        self._mic_offered = True
        log.info("offering the newer mic part")
        from soundboard.ui.setup.micupdate import MicUpdateOffer
        offer = self._mic_offer = MicUpdateOffer(mw)
        offer.accepted.connect(self._accept_mic_update)
        offer.finished.connect(self._mic_offer_closed)
        offer.popup()

    def _mic_offer_closed(self):
        self._mic_offer = None

    def _accept_mic_update(self):
        """Install update: the mic, the route or the part may have changed while the
        offer was up, so check again before Windows is asked."""
        mw = self.mw
        if not self._mic_update_due():
            cfg = mw.cfg
            if cfg.route == "mic" and directmic.works(directmic.status(cfg.mic_device)):
                mw.toast(_("Your mic is already up to date."), "ok")
            else:
                mw.toast(_("Nothing to update now: your mic settings changed."))
            return
        log.info("updating the mic part (asked)")
        self._mic_updating = True
        mw.toast(_("Updating Onion Board's part of your mic so every app hears your "
                     "sounds: click Yes when Windows asks.") if michelper.will_ask() else
                   _("Updating Onion Board's part of your mic so every app hears your sounds."))
        self.attach_mic(clean=True)

    def _check_cable_format(self):
        """Note which ends of the cable in use aren't at 48 kHz (shown on the Setup tab)."""
        mw = self.mw
        main = mw.routectl._main_name()
        self._set_cable_bad(self._cable_ends(main, eng.virtual_mic_for(main)))

    @staticmethod
    def _cable_ends(main: str | None, vm: str | None) -> list:
        """The ends of the cable `main` -> `vm` with their formats (a COM call: any thread)."""
        from soundboard.mic import cableformat
        try:
            return cableformat.pair(cableformat.cable_ends(), main, vm) if vm else []
        except Exception:  # noqa: BLE001 - only a hint
            log.debug("cable format check failed", exc_info=True)
            return []

    def _set_cable_bad(self, ends: list):
        self.cable_bad = [x for x in ends if not x.ok]
        if self.cable_bad:
            log.info("cable not at 48 kHz: %s",
                     ", ".join(f"{x.name} @ {x.rate}" for x in self.cable_bad))

    def fix_cable_format(self, quiet: bool = False) -> bool:
        """Put both ends of the cable on 48 kHz, then reopen the streams at the new rate."""
        mw = self.mw
        from soundboard.mic import cableformat
        self._check_cable_format()
        if not self.cable_bad:
            return True
        ok = cableformat.fix(self.cable_bad)
        mw.devctl.refresh_devices()   # the rates changed: rescan and reopen (re-checks too)
        if not quiet:
            if ok and not self.cable_bad:
                msg, kind = _("✓ The cable is on 48 kHz both ends now. If Discord goes "
                              "quiet, rejoin the voice channel."), "ok"
            else:
                msg, kind = _("Couldn't change the cable's format. Set it by hand: Sound "
                              "settings → the cable → Advanced → 48000 Hz."), "warn"
            mw.toast(msg, kind)
        return ok

    @staticmethod
    def declined_text() -> str:
        """The set-up's Windows prompt got a No: said in the card, whatever the route."""
        return _("You clicked <b>No</b>, so nothing changed. Try again and click "
                 "<b>Yes</b> when Windows asks.")

    def _show_mic_status(self, direct: str, state: str, settling: bool,
                         step: str) -> tuple[str, str | None]:
        """Straight into the mic, on the Setup tab: fills the status box and the pill,
        and gives (the reason the user is needed or "", the one button's words or
        None). One rule: the card asks for a click only when the app can't go on
        without one (the first set-up, a No, no usable mic helper, a repair that
        failed); otherwise it's the status box, and Windows taking it off the mic is
        fixed by itself. `step`: what the old card said for this state."""
        mw = self.mw
        e = mw.engine
        ask = michelper.will_ask()
        if michelper.known() is None:
            self._check_helper()   # once, at start: the texts follow its answer
        name = mw.cfg.mic_device or _("your mic")
        needed_no = self.declined_text()

        def needed(reason):   # a No beats every other reason: it's what just happened
            return needed_no if self._declined else reason

        if directmic.works(direct):
            self._autofix_tried = False   # working: the next time it's off is fixed again
        # (tone, icon, headline, pill, reason, button)
        if mw._attaching and self._autofixing:
            look = ("warn", "reload", _("Fixing your mic…"), _("Fixing…"),
                    _("Windows took Onion Board off your mic. It's going back on: your "
                      "sound drops out for a second."), None)
        elif mw._attaching:
            look = ("warn", "reload", _("Setting up…"), _("Setting up…"), step, None)
        elif state == "missing" and settling:
            look = ("warn", "reload", _("Starting…"), _("Setting up…"), step, None)
        elif self.mic_unplugged() and (headset := directmic.sound_only(mw.cfg.mic_device)):
            # a Bluetooth headset still playing with its mic half dropped (AirPods): "is
            # it plugged in?" read as the app being wrong, it was connected
            usage.used("mic-unplugged")
            look = ("warn", "mic", _("Your headset's mic is off"), _("Mic off"), _(
                "The mic on <b>{headset}</b> disconnected. Reconnect it and your sounds go "
                "out again.", headset=html.escape(headset)), None)
        elif self.mic_unplugged():
            # Windows still knows it, it's just not there: nothing to repair or set up
            usage.used("mic-unplugged")   # the card said so (never which mic)
            look = ("warn", "mic", _("Is your headset plugged in?"), _("Unplugged"), _(
                "Windows can't find <b>{mic}</b> right now. Plug it in, or switch it on if "
                "it's wireless. No mic at all? Use the <b>virtual cable</b> below: it works "
                "without one.", mic=html.escape(name)), None)
        elif directmic.needs_repair(direct):
            known = michelper.known()
            if known and self._autofix_tried and not self._autofix_err:
                # fixed, and Windows took it off again: no loop of audio restarts
                self._autofix_err = _("Windows took it off again")
            if known and not self._autofix_err:
                QTimer.singleShot(0, mw, lambda: self._auto_fix(direct))
                look = ("warn", "reload", _("Fixing your mic…"), _("Fixing…"),
                        _("Windows took Onion Board off your mic. It's going back on: "
                          "your sound drops out for a second."), None)
            elif known is None:
                look = ("", "reload", _("Checking your mic…"), _("Setting up…"), "", None)
            elif self._autofix_err:
                look = ("error", "warn", _("Windows took Onion Board off your mic"),
                        _("Repair needed"), needed(_(
                            "Onion Board couldn't fix it by itself: {error}. Click <b>Try "
                            "again</b>, and if Windows asks for permission, click <b>Yes</b>.",
                            error=html.escape(self._autofix_err.rstrip(".")))),
                        _("Try again"))
            else:
                look = ("error", "warn", _("Windows took Onion Board off your mic"),
                        _("Repair needed"), needed(_(
                            "A driver or Windows update does that. Click <b>Repair</b>, then "
                            "<b>Yes</b> when Windows asks.")), _("Repair (one click)"))
        elif not directmic.works(direct):
            # named for what's missing (the sounds), never "your mic": the mic works, its
            # level moves, and "Your mic: Not set up" read as a broken mic
            look = ("warn", "mic",
                    _("Your sounds aren't in your mic yet") if direct == "missing"
                    else _("Your sounds are on another mic"),
                    _("1 step left"), needed(directmic.with_helper_note(
                        _("Others hear your voice, but not your sounds. One click adds Onion "
                          "Board's audio driver to this mic, so Discord and games hear your "
                          "sounds too. Windows asks once: click <b>Yes</b>.")) if ask else
                        _("Others hear your voice, but not your sounds. One click adds Onion "
                          "Board's audio driver to this mic, so Discord and games hear your "
                          "sounds too.")), _("Put my sounds straight into my mic"))
        elif state == "ok" and self._probe_missing:
            # set up and running, but the probe didn't come out of the mic (probe_mic):
            # a voice chat wouldn't hear the sounds either
            look = ("error", "warn", _("Your sounds aren't in your mic yet"),
                    _("Not working"), needed(_(
                        "Onion Board is on your mic, but a test sound didn't come through "
                        "it. Click <b>Repair</b> to put it on again.")),
                    _("Repair (one click)"))
        elif state == "ok" and self._mic_sends_nothing():
            # the mic itself sends exact zeros: a wireless headset switched off (its
            # dongle stays plugged in), the mic's own mute or its boom mic pulled out.
            # The effect still sends the sounds on that silence, so nothing is broken:
            # others hear just the sounds (a mic stuck after an audio restart: Reinstall)
            usage.used("mic-silent")
            look = ("ok", "check", _("Your sounds go into your mic"), _("Connected"), _(
                "Your mic sends no sound right now (switched off, muted or no mic plugged "
                "in), so others hear only your sounds. Want them to hear you too? Turn it "
                "on or unmute it."), None)
        elif state == "ok":
            look = ("ok", "check", _("Your sounds go into your mic"), _("Connected"), "", None)
        else:   # set up, but Windows isn't running it or it won't open: the step says why
            look = ("error", "warn",
                    _("Not running") if state == "unrouted" and e.main_stream is not None
                    else _("Can't reach it"), _("Not working"), needed(step),
                    _("Repair (one click)"))
        tone, icon, headline, pill, reason, button = look
        if state == "ok" and not mw.cfg.mic_enabled:
            sub = _("{mic} · not sent, sounds only", mic=name)
        elif state == "ok" and e.mic_stream is None:
            sub = _("{mic} · off", mic=name)
        else:
            sub = name
        # the mic itself works (it's open and not unplugged) while the sounds aren't in
        # it yet: said in its own green row, with its level, above what's missing
        voice = (tone != "ok" and e.mic_stream is not None and not self.mic_unplugged())
        reveal.set_shown(mw.mic_voice, voice)   # (folds away once the sounds are in)
        if voice:
            mw.mic_voice_sub.setText(name)
            mw.mic_voice_sub.setToolTip(name)
            sub = ""   # (named in the row above)
        mw.mic_sub.setToolTip(sub)
        mw.mic_line.setText(headline)
        theme.set_tone(mw.mic_line, tone)
        mw.mic_sub.setText(sub)
        mw.card_meter.setVisible(state == "ok" and e.mic_stream is not None)
        colour = {"ok": "ok_text", "warn": "warn_text", "error": "error_text"}.get(tone, "muted")
        if (icon, colour) != mw._mic_icon:
            mw._mic_icon = (icon, colour)
            icons.set_label_icon(mw.mic_state_icon, icon, colour, size=20)
        mw.mic_pill.setText(pill)
        theme.set_tone(mw.mic_pill, tone)
        if tone == "ok" and mw._mic_tone not in (None, "ok"):
            # it just started working (set up, repaired, back on): say so with a flash,
            # not only with boxes going away
            reveal.flash(mw.mic_status, mw.mic_state_icon)
        mw._mic_tone = tone
        return reason or "", button

    def _other_mics_alive(self, mic: str) -> frozenset:
        """Before a set-up (on its thread): the other mics with sound now. One of them
        sending only zeros after it was cut off by it (an app between the mic and a
        voice chat, with a virtual mic of its own). A check: never fails the set-up."""
        try:
            target = (directmic.endpoint_for(mic) or "").lower()
            return frozenset(micprobe.alive(
                [e["guid"] for e in directmic.capture_endpoints()
                 if e["active"] and e["guid"] != target]))
        except Exception:  # noqa: BLE001
            log.info("couldn't listen to the other mics", exc_info=True)
            return frozenset()

    def probe_mic(self):
        """Once a set-up works (statuscontrol, the card turned green): the board plays
        micprobe's probe into the mic only (never into your own headphones) and listens
        to the mic and the other mics that had sound before (micprobe.check). Not when
        the sounds aren't sent at all (muted, voice only): nothing to find then."""
        mw = self.mw
        e = mw.engine
        if not self._probe_due or self._probing or mw._attaching:
            return
        self._probe_due = False
        guid = directmic.endpoint_for(mw.cfg.mic_device)
        if (not guid or mw.cfg.route != "mic" or e.main_stream is None or not e.sending
                or e.mic_only() or e.sound_vol <= 0.05):
            log.info("mic probe skipped (nothing sent to others now)")
            return
        self._probing = True
        data = micprobe.probe()
        gain = min(1.0 / e.sound_vol, 10.0)   # the sounds' volume to others: undone
        before = self._alive_before

        def play():
            e.play("__probe__", data, gain, mode="restart", src_rate=micprobe.SR,
                   only="main")

        def work():
            res = micprobe.check(play, guid, before)
            if res.real is False:   # once more: a word said right then can hide it
                res = micprobe.check(play, guid, before)
            return res
        worker.run(work, mw.mic_probed, "mic-probe", error=lambda err: None, owner=mw)

    def _mic_probed(self, res):
        mw = self.mw
        self._probing = False
        if res is None or mw._shut_down:
            return
        usage.used("mic-probe-heard" if res.real else
                   "mic-probe-missing" if res.real is False else "mic-probe-unsure")
        if res.real is False:
            log.warning("the probe didn't come out of the mic: %s", res.scores)
        for _g in res.dead:
            usage.used("mic-probe-app-cut-off")
        if res.dead:
            log.warning("cut off by the set-up (only zeros now): %s", res.dead)
        if not PROBE_SHOWS:
            return
        if res.real is False:
            self._probe_missing = True
            mw.statusctl._update_status()
        # the name Windows' Sound settings shows first ("SteelSeries Sonar - Microphone"),
        # without the device part in brackets that made it two lines
        names = {e["guid"]: e["name"].removesuffix(f" ({e['device']})") if e.get("device")
                 else e["name"] for e in directmic.capture_endpoints()}
        for g in res.dead:
            mw.toast(_("<b>{mic}</b> stopped sending sound after the set-up. Restart the "
                       "app it belongs to and it works again.",
                       mic=html.escape(names.get(g, g))), "warn", ms=12000, aside=True)

    def _auto_fix(self, direct: str):
        """Windows took the effect off the mic (a driver or Windows update): put it back
        through the mic helper, no click and no prompt (a toast says what's happening).
        Once per time it's found off: if it fails, the card asks for the click."""
        mw = self.mw
        if (mw._shut_down or mw._attaching or self._autofix_err
                or mw.cfg.route != "mic" or not michelper.known()):
            return
        if not directmic.needs_repair(directmic.status(mw.cfg.mic_device)):
            return
        log.info("the mic effect was taken off the mic (%s): fixing it by itself", direct)
        usage.used("mic-effect-taken-off")
        self._autofix_tried = True
        self.attach_mic(auto=True)

    def _app_state(self, state):
        """Back in front after a while (behind a game for an hour, say): the mic
        helper's answer may be stale (another account removed or set it up), so check
        it again; the card's "click Yes" and the fix-by-itself follow the new answer."""
        mw = self.mw
        if (state != Qt.ApplicationState.ApplicationActive or mw._shut_down
                or mw.cfg.route != "mic"):
            return
        ago = michelper.checked_ago()
        if ago is not None and ago > michelper.RECHECK_S:
            self._check_helper("window back")

    def _check_helper(self, via: str = "card"):
        """Is the mic helper usable (michelper.ready runs a process: on a thread)? The
        card redraws with the answer."""
        mw = self.mw
        if self._helper_checking:
            return
        # (a check that failed leaves known() None, which every card redraw asks about:
        # one schtasks call a minute at most, not one per redraw)
        if (self._helper_failed
                and time.monotonic() - self._helper_check_at < HELPER_RETRY_S):
            return
        self._helper_checking, self._helper_check_at = True, time.monotonic()

        def work():
            self._helper_failed = not directmic._helper_check(via)
            return ()

        def failed(_e):
            self._helper_failed = True
            return ()
        worker.run(work, mw.helper_checked, "mic-helper-check", error=failed, owner=mw)

    def _helper_known(self):
        mw = self.mw
        self._helper_checking = False
        mw.statusctl._update_flow()

    def switch_helper(self, on: bool) -> bool:
        """Settings -> Audio -> Mic effect: "Don't ask for admin each time". On: saved,
        and the next step Windows asks for anyway sets the helper up again. Off: the
        helper is removed first (Windows asks once, if it's there), then every step
        asks; a No leaves it on. helper_switched says how it ended. False (nothing
        done) while a mic step runs."""
        mw = self.mw
        if mw._attaching or self._helper_switching:
            return False
        if on:
            self._helper_set(True)
            michelper.state.forget()   # (a look again: it may still be there)
            self._helper_failed = False
            self._check_helper("switched on")
            return True
        self._helper_switching = True
        log.info("switching the mic helper off")

        def work():
            if michelper.installed() or michelper.leftover():
                directmic.remove_helper()
            return not michelper.installed()

        worker.run(work, self.helper_removed, "mic-helper-remove", error=False, owner=mw)
        return True

    def _helper_removed(self, gone: bool):
        mw = self.mw
        self._helper_switching = False
        if gone:
            self._helper_set(False)
            mw.toast(_("The helper is removed. Windows asks for permission each time now."),
                     "ok")
        else:
            log.info("the mic helper is still there: left on")
            mw.toast(_("The helper is still there, so nothing changed. Try again and click "
                       "<b>Yes</b> when Windows asks."), "warn")
            self.helper_switched.emit(True)

    def _helper_set(self, on: bool):
        mw = self.mw
        mw.cfg.mic_helper = on
        directmic.set_helper(on)
        mw._save_now()
        self.helper_switched.emit(on)
        mw.statusctl._update_flow()   # the texts' "click Yes" follow it

    def attach_mic(self, clean: bool = False, auto: bool = False):
        """Put the mic effect on the mic in use (Windows asks for admin once; with the
        mic helper set up, not at all), then send what others hear into it. The admin
        step waits, so it runs on a thread. `clean` (the update offer): the old part
        comes off completely first, then the new one goes on, under the same one prompt.
        `auto`: the app's own repair when Windows took it off (_mic_view), through the
        helper only: Windows' prompt never comes up for a click nobody made."""
        mw = self.mw
        if mw._attaching:
            return
        mic = mw.cfg.mic_device
        if not mic:
            if not auto:
                mw.toast(_("Pick your mic first (Setup tab → Devices)."), "warn", aside=True)
            return
        mw._attaching = True
        self._autofixing = auto
        self._probe_missing = False   # (checked again once this one works)
        self._declined = False   # (whatever happens now is what the card says)
        self.fail_code = ""
        if auto:
            mw.toast(_("Fixing your mic… (your sound drops for a second)"))
        else:
            self._autofix_err = ""
            # Bun's show explains the first set-up's wait and Yes; a repair or an
            # update says it in the card instead
            mw._show_bun = directmic.status(mic) in ("missing", "other")
            if mw._attach_release is None:   # released by _update_flow once it works
                mw._attach_release = busy.hold(mw.btn_install, _("Setting up…"))
            if mw._show_bun:
                mw.setup_show.start()
        mw.statusctl._update_flow()
        log.info("attaching the mic effect to %s%s", mic, " (by itself)" if auto else "")

        def failed(e):
            self._mic_fail_kind = ""
            return mic, errors.plain(e) or type(e).__name__
        # the admin prompt can outlast the window (closed and freed meanwhile): then
        # there's nobody to tell (owner)
        worker.run(self._attach_mic_work, mw.mic_attached, "mic-attach", error=failed,
                   owner=mw, args=(mic, clean, auto))

    def _attach_mic_work(self, mic: str, clean: bool = False, auto: bool = False):
        self._alive_before = self._other_mics_alive(mic)
        err = directmic.install(mic, clean=clean, ask_windows=not auto) or ""
        if err and not auto and directmic.fail_kind(err) == "no-mic-gone":
            # Windows doesn't know the picked mic any more (an old headset, renamed):
            # the default mic, which the board records meanwhile, is set up instead of
            # a dead end (_mic_attached switches to it)
            other = directmic.fallback_mic(mic)
            if other:
                log.info("the picked mic is gone: setting up Windows' default mic instead")
                mic, err = other, directmic.install(other, clean=clean) or ""
        # its reason word, kept here: the signal hands _mic_attached a plain str
        self._mic_fail_kind = directmic.fail_kind(err) if err else ""
        # the admin step raised: where, what and Windows' error number; or the audio
        # wouldn't stop: which service. From its log (read here, off the UI thread)
        self._raised = directmic.raised_why() if self._mic_fail_kind == "code-1" else None
        self._stuck = directmic.stuck_why() if self._mic_fail_kind == "code-6" else ""
        self._unstarted = directmic.unstarted_why() if self._mic_fail_kind == "code-8" else ""
        # the helper's run raised and Windows' prompt ran it instead: where the helper's
        # failed, which the prompt's own result doesn't tell
        self._fallback = directmic.helper_fallback()
        return mic, err

    def _mic_attached(self, mic: str, err: str):
        mw = self.mw
        mw._attaching = False
        mw._done_toast = None
        updating, self._mic_updating = self._mic_updating, False
        auto, self._autofixing = self._autofixing, False
        directmic.forget_status()
        # on the mic, but the mic itself came back from the audio restart sending
        # nothing: the effect still sends the sounds on that silence (the card says
        # the mic is silent), so it's set up, not failed
        silent = err == directmic.mic_silent()
        fallback, self._fallback = self._fallback, None
        if fallback:
            where, what, num = fallback
            usage.used("mic-effect-helper-fallback")
            usage.used(f"mic-effect-helper-code-1-at-{where}")
            usage.used(f"mic-effect-helper-code-1-{what}")
            usage.used(f"mic-effect-helper-code-1-{num}")
        if silent:
            err, self._mic_fail_kind = "", ""
        if err:
            if mw._attach_release is not None:
                release, mw._attach_release = mw._attach_release, None
                release(_("✗ Didn't work"))
            log.warning("not put on the mic: %s", err)
            # an older mic part can still be working (the optional update failed): the
            # status then reads fine, but this attempt didn't work, so Bun mustn't cheer
            mw.setup_show.finish(False)
            usage.used("mic-effect-fix-failed" if auto else
                       "mic-effect-said-no" if err == directmic.declined() else
                       "mic-effect-failed")
            kind, self._mic_fail_kind = self._mic_fail_kind or "code-other", ""
            if auto or err != directmic.declined():   # why, as a fixed word (never err)
                usage.used(f"mic-effect-{'fix-' if auto else ''}failed-{kind}")
                self.fail_code = f"attach-{kind}"   # (a No isn't the app failing)
            raised, self._raised = self._raised, None
            stuck, self._stuck = self._stuck, ""
            unstarted, self._unstarted = self._unstarted, ""
            if kind == "code-1" and raised:
                where, what, num = raised
                usage.used(f"mic-effect-code-1-at-{where}")
                usage.used(f"mic-effect-code-1-{what}")
                usage.used(f"mic-effect-code-1-{num}")
            elif kind == "code-6" and stuck:
                usage.used(f"mic-effect-code-6-{stuck}")
            elif kind == "code-8" and unstarted:
                usage.used(f"mic-effect-code-8-{unstarted}")
            if auto:
                # the card turns into its one button with the reason (_mic_view)
                self._autofix_err = err
                mw.toast(_("Couldn't fix your mic by itself: see the Setup tab."), "warn",
                         aside=True)
            elif err == directmic.declined() and not updating:
                self._declined = True   # the card says so, with its button to try again
            elif updating and err == directmic.declined():
                # No to the optional update: the old part keeps working, no box needed
                mw.toast(_("Update cancelled. Your mic part is still the old one: "
                             "update it from the Setup tab."), "warn", aside=True)
            else:
                # the route stays on the mic: until it's set up, the cable carries the
                # sounds meanwhile (_main_name), and the one-click stays on offer
                # with the way that works on every PC one click away: new users who only
                # got "Try again" tried again (the same failure) and uninstalled
                err = _("{error}\n\nTry again any time from the Setup tab.", error=err)
                mw.tell(_("Couldn't put Onion Board on your mic"), err, "error",
                        action=(_("Use the cable"), mw.btn_usecable.click), aside=True)
        else:
            log.info("on the mic now: %s", mic)
            usage.used("mic-effect-updated" if updating else
                       "mic-effect-fixed" if auto else "mic-effect-on")
            if mic != mw.cfg.mic_device:
                # the picked mic was gone: set up on Windows' default one instead
                mw.cfg.mic_device = mic
                mw._save_now()
                mw.devctl._reopen_devices()
                mw.toast(_("Windows doesn't know your picked mic any more, so Onion Board "
                           "went on {mic} (Windows' default mic) instead.",
                           mic=html.escape(mic)), "warn", aside=True)
            if silent:
                usage.used("mic-silent-after-setup")
                mw.toast(_("Your sounds are in your mic, but your mic sends no sound itself "
                           "right now. Is your headset switched off or muted?"), "warn",
                         aside=True)
            # Windows takes a few seconds to load it: "starting…" meanwhile, then a
            # redraw when the wait is over (it works by then, or Repair comes back)
            mw._settle_until = time.monotonic() + mw.SETTLE_S
            mw._settle_more = False
            QTimer.singleShot(int(mw.SETTLE_S * 1000) + 200, mw.statusctl._update_status)
            mw.cfg.route = "cable"   # so set_route() applies "mic" in full
            mw.routectl.set_route("mic", attached=True)
            from soundboard.ui.setup.setupwizard import SetupWizard
            modal = QApplication.activeModalWidget()
            # said once it works (_update_flow), with the card turning green and Bun
            # cheering: said now, it came while the card still read "starting…" and Bun
            # was still hammering, and Windows can still fail to load it
            mw._done_toast = ("updated" if updating else "fixed" if auto else
                                None if isinstance(modal, SetupWizard) else "done")
            self._probe_due = True   # once it's running (statuscontrol: probe_mic)
        mw.routectl._show_route()
        mw.statusctl._update_status()

    def _cable_tip(self):
        """Once: straight into the mic works, and a voice app is still set to the
        cable's far end. It still hears you (the cable gets the same), but its normal
        mic is the simpler setting."""
        mw = self.mw
        c = mw.cfg
        watch = getattr(mw, "_cable_watch", None)   # (not made yet while starting up)
        if c.cable_tip_done or mw.engine.tap is None or watch is None:
            return
        far = eng.virtual_mic_for(mw.engine.tap_name)
        apps = set(voicesdk.VOICE_APPS.values())
        heard = [h for h in watch.poll(far) if h in apps]
        if heard:
            c.cable_tip_done = True
            mw._save_now()
            mw.toast(_("{value} still uses the virtual cable as its mic. It still hears you, "
                         "but you can set its input back to your normal mic: your sounds are in "
                         "it now.", value=heard[0][1]))

    def _ask_mic_effect(self, action: str):
        """The status box's Reinstall / Remove: Settings' audio recovery, on this mic,
        after the same are-you-sure box."""
        mw = self.mw
        from soundboard.ui.setup import audiorecovery
        recovery = audiorecovery.recovery_of(mw)
        if recovery.running or mw._attaching:
            return

        def go_on(dialog):
            if recovery.start(action, None, say_done=True):
                dialog.accept()
                mw.statusctl._update_flow()
        audiorecovery.ask(mw, action, [audiorecovery.explanation(
            action, mw.cfg.mic_device or None)], go_on)

    def _pick_send_device(self):
        """Setup tab -> Another device: Devices' "Send my sounds to", opened."""
        mw = self.mw
        mw.setup_page.ensureWidgetVisible(mw.cb_route)
        mw.cb_route.setFocus()
        mw.cb_route.showPopup()

    def _pick_mic(self):
        """Your mic -> Change mic: Devices' "My mic", opened (the effect follows the mic
        picked there)."""
        mw = self.mw
        mw.setup_page.ensureWidgetVisible(mw.cb_mic)
        mw.cb_mic.setFocus()
        mw.cb_mic.showPopup()

    def use_cable_instead(self):
        """Straight into my mic isn't working here: send through the virtual cable (set
        it up first if it isn't installed)."""
        mw = self.mw
        if mw._cable_gone:
            # removed this session: Windows still lists it until a restart, but it won't
            # open (sending into it lost the mic until it was set up again)
            mw.toast(_("The virtual cable was removed. Restart your PC before you "
                         "install it again."), "warn")
            return
        if eng.virtual_outputs():
            mw.routectl.set_route("cable")
            mw.toast(_("Sending through the virtual cable. Pick it as the mic in Discord and "
                         "games (Setup tab)."), "ok")
        else:
            mw.cfg.route = "cable"
            mw.routectl._show_route()
            mw.statusctl._update_status()
            self.install_cable()

    def _direct_health(self):
        """What the Setup tab shows about straight into my mic, to redraw it when that
        changes (checked about once a second)."""
        mw = self.mw
        e = mw.engine
        h = (directmic.status(mw.cfg.mic_device), e.main_stream is not None,
             self._direct_not_running(), bool(e.direct_apps()),
             time.monotonic() < mw._settle_until and e.effect_alive(),   # "starting…" ends
             self._mic_sends_nothing(), self.mic_unplugged(),
             directmic.sound_only(mw.cfg.mic_device))
        return h

    def mic_unplugged(self) -> bool:
        """The picked mic isn't there (directmic.unplugged), and no sound comes in from
        it either: Windows' list can lag behind (or a name match miss) while the mic
        works, and "plugged in?" over a moving level read as the app being broken."""
        return directmic.unplugged(self.mw.cfg.mic_device) and not self.mw.engine.mic_live()

    def _mic_sends_nothing(self) -> bool:
        """The mic, with the effect on it, has sent only exact zeros for MIC_SILENT_S."""
        mw = self.mw
        return mw.engine.direct_mic_silent_s() >= mw.MIC_SILENT_S

    def _follow_mic_effect(self):
        """Sending into the mic, and the mic effect started (or stopped) working since
        what others hear was opened: switch to it (or back to the cable) now. Before,
        sounds stayed on the cable until the app restarted, e.g. when Windows loaded the
        effect a while after the app started. Checked about once a second; the streams
        open on the device thread."""
        mw = self.mw
        if mw._attaching or self._following_effect:
            return
        if mw.engine.names["main"] == mw.routectl._main_name():
            return
        self._following_effect = True
        log.info("the mic effect %s: what others hear follows",
                 "works now" if mw.routectl._main_name() == directmic.DEVICE
                 else "stopped working")

        def opened(ends):
            self._following_effect = False
            if ends is not None:
                self._set_cable_bad(ends)
            mw.statusctl._update_status()
            mw.routectl._prepare_all()

        def plan():   # worked out when its turn comes
            send = mw.routectl._send_plan()
            return lambda: mw.routectl._open_send(send)
        mw.devctl._device_job(plan, opened)

    def _spare_cable(self) -> bool:
        """Straight into the mic, and VB-Cable still installed: it's only the fallback
        now, so the Setup tab offers to remove it."""
        mw = self.mw
        if mw._cable_gone or not eng.virtual_outputs():
            return False
        if mw._vb_setup is None:      # shown once it's known (_cable_setup_found)
            self._ask_cable_setup()
            return False
        return mw._vb_setup

    def _ask_cable_setup(self):
        mw = self.mw
        if mw._vb_setup_asking:
            return
        from soundboard.mic import cableremove
        mw._vb_setup_asking = True
        worker.run(lambda: cableremove.setup_exe() is not None, mw.cable_setup_found,
                   "cable-setup", error=False, owner=mw)

    def _cable_setup_found(self, found: bool):
        mw = self.mw
        mw._vb_setup_asking = False
        if found != mw._vb_setup:
            mw._vb_setup = found
            mw.statusctl._update_flow()

    def remove_cable(self):
        """Setup tab → Remove the virtual cable: VB-Audio's uninstaller, as admin (it
        waits for Windows' prompt, so it runs on a thread)."""
        mw = self.mw
        if busy.is_busy(mw.btn_rmcable):
            return
        from soundboard.mic import cableremove
        self._rmcable_release = busy.hold(mw.btn_rmcable,
                                          _("Removing… click Yes when Windows asks"))
        worker.run(lambda: cableremove.remove() or "", mw.cable_removed, "cable-remove",
                   error=lambda e: errors.plain(e) or type(e).__name__, owner=mw)

    def _cable_removed(self, err: str):
        mw = self.mw
        if err:
            log.warning("virtual cable not removed: %s", err)
            self._rmcable_release(_("✗ Not removed"))
            mw.toast(_("The virtual cable wasn't removed: {err}", err=html.escape(err)), "warn")
            return
        self._rmcable_release()
        mw._cable_gone = True   # stop sending into it now (Windows lists it till a restart)
        mw.routectl._apply_send_outputs()
        mw.toast(_("✓ The virtual cable is removed. Restart your PC to finish: until then "
                     "Windows still lists “CABLE Input” / “CABLE Output”."), "ok")
        mw.statusctl._update_status()

    def _direct_not_running(self) -> bool:
        """Set up on the mic, the board's own mic stream open on it for a while, and the
        effect still never ran: Windows isn't running it (exclusive mode, a driver that
        skips effects, a failed load)."""
        mw = self.mw
        e = mw.engine
        if e.mic_stream is None or e.effect_alive():
            self._direct_dead_since = None
            return False
        # the cached status, not endpoint_for / installed_on: those walk the registry,
        # and this runs every second on the UI thread
        if not mw.cfg.mic_device or directmic.status(mw.cfg.mic_device) in ("missing",
                                                                                "other"):
            return False
        now = time.monotonic()
        since = getattr(self, "_direct_dead_since", None) or now
        self._direct_dead_since = since
        return now - since > mw.DIRECT_GRACE_S

    def install_cable(self):
        mw = self.mw
        if not net.allowed("setup_downloads"):   # its download can't go through the app
            mw.toast(html.escape(net.off_message("setup_downloads")), "warn")
            return
        script = RESOURCE_DIR / "install-vbcable.ps1"
        if not script.exists():
            mw.tell(_("Installer missing"), _("Can't find {name}.", name=script.name),
                      "error")
            return
        try:
            subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                              "-File", str(script)],
                             creationflags=subprocess.CREATE_NEW_CONSOLE)
        except OSError as e:
            log.warning("couldn't start the cable installer", exc_info=True)
            mw.tell(
                _("Couldn't start the installer"),
                _("Windows wouldn't run PowerShell ({e}).\n\nYou can install VB-Cable by hand: "
                  "download it from vb-audio.com, unzip it, right-click VBCABLE_Setup_x64.exe → "
                  "Run as administrator → Install Driver.", e=errors.plain(e)), "error")
            return
        QMessageBox.information(
            mw, _("Installing the virtual cable"),
            _("A window opened that downloads VB-Cable (free) from the official VB-Audio "
              "site.\n\nWindows will ask for permission, click Yes, then click “Install "
              "Driver”.\n\nWhen it's done, click “I've installed it, check again”. If it "
              "doesn't show up, restart your PC."))

    def open_windows_mic(self):
        mw = self.mw
        vm = mw.statusctl.virtual_mic or _("your virtual cable")
        try:
            subprocess.Popen(["control", "mmsys.cpl,,1"], creationflags=0x08000000)
        except OSError:
            log.warning("couldn't open the Sound control panel", exc_info=True)
            mw.tell(_("Couldn't open the Sound settings"),
                      _("Open it yourself: press Win+R, type  mmsys.cpl  and press "
                        "Enter, then go to the Recording tab."), "warn", 15000)
            return
        QMessageBox.information(
            mw, _("Game with no mic setting"),
            _("Some games just use Windows' main mic. A sound window just opened:\n\n1.  "
              "Right-click  {vm}  →  Set as Default Device\n2.  Right-click it again  →  Set as "
              "Default Communication Device\n     (voice chat in many games asks Windows for "
              "that one)\n3.  Restart the game.\n\nHeads-up: voice typing will then also hear "
              "your sounds.\nTo undo, do the same on your normal mic.", vm=vm))
