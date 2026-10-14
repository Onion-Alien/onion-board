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

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from soundboard import directmic, errors, michelper, net, theme, usage, voicesdk
from soundboard import engine as eng
from soundboard.i18n import _
from soundboard.library import RESOURCE_DIR
from soundboard.ui import busy, icons, worker
from soundboard.ui.controller import Controller
from soundboard.ui.routecontrol import is_hands_free

if TYPE_CHECKING:
    from soundboard.ui.mainwindow import MainWindow

log = logging.getLogger(__name__)

HELPER_RETRY_S = 60.0   # a mic helper check that failed is tried again after this long
MIC_OFFER_MS = 1000   # an older mic part's update is offered this long after the window shows


class MicControl(Controller):
    """The mic effect and the virtual cable of one MainWindow (``mw``)."""

    _mic_offer = None       # the open MicUpdateOffer
    _mic_updating = False   # attach_mic was started from it (its own result messages)
    _autofixing = False     # attach_mic(auto=True): the app's own repair, nobody clicked
    _autofix_err = ""       # that repair failed: the card asks for a click until it works
    _mic_fail_kind = ""     # the last set-up's directmic.FAIL_KINDS word, for the count
    _autofix_tried = False  # it ran since the mic last worked (once per time it's off)
    _declined = False       # the last set-up's Windows prompt got a No
    _helper_checking = False
    _helper_failed = False  # the last check raised: the next waits HELPER_RETRY_S
    _helper_check_at = 0.0  # when the last check started (time.monotonic())
    _mic_offered = False    # shown this start (it comes back next start until updated)
    _silent_said = False    # the "your mic sends no sound" toast came this run
    _following_effect = False

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self.cable_bad = []               # cable ends not at 48 kHz (_check_cable_format)

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
        from soundboard.ui.micupdate import MicUpdateOffer
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
        from soundboard import cableformat
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
        from soundboard import cableformat
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
        needed_no = _("You clicked <b>No</b>, so nothing changed. Try again and click "
                      "<b>Yes</b> when Windows asks.")

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
            look = ("warn", "mic",
                    _("Not in your mic yet") if direct == "missing" else _("On another mic"),
                    _("Not set up"), needed(
                        _("One click puts your sounds straight into your mic, so Discord and "
                          "games hear them. Windows asks once: click <b>Yes</b>.") if ask else
                        _("One click puts your sounds straight into your mic, so Discord and "
                          "games hear them.")), _("Put my sounds straight into my mic"))
        elif state == "ok" and self._mic_sends_nothing():
            # the mic itself sends nothing (stuck after an audio restart, or its own mute):
            # Repair restarts the audio and listens to it again
            if not self._silent_said:
                self._silent_said = True
                mw.toast(_("Your mic sends no sound: see the Setup tab."), "warn")
            look = ("warn", "warn", _("Your mic sends no sound"), _("No sound"), needed(
                _("Discord and games hear nothing from your mic. Is your headset switched "
                  "off, or its mic muted? Turn it on or unmute it. If not, click "
                  "<b>Repair</b>, then <b>Yes</b> when Windows asks.")
                if ask else
                _("Discord and games hear nothing from your mic. Is your headset switched "
                  "off, or its mic muted? Turn it on or unmute it. If not, click "
                  "<b>Repair</b>: your sound drops out for a few seconds.")),
                _("Repair (one click)"))
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
        return reason or "", button

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
        mw._update_flow()

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
                mw.toast(_("Pick your mic first (Setup tab → Devices)."), "warn")
            return
        mw._attaching = True
        self._autofixing = auto
        self._declined = False   # (whatever happens now is what the card says)
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
        mw._update_flow()
        log.info("attaching the mic effect to %s%s", mic, " (by itself)" if auto else "")

        def failed(e):
            self._mic_fail_kind = ""
            return mic, errors.plain(e) or type(e).__name__
        # the admin prompt can outlast the window (closed and freed meanwhile): then
        # there's nobody to tell (owner)
        worker.run(self._attach_mic_work, mw.mic_attached, "mic-attach", error=failed,
                   owner=mw, args=(mic, clean, auto))

    def _attach_mic_work(self, mic: str, clean: bool = False, auto: bool = False):
        err = directmic.install(mic, clean=clean, ask_windows=not auto) or ""
        # its reason word, kept here: the signal hands _mic_attached a plain str
        self._mic_fail_kind = directmic.fail_kind(err) if err else ""
        return mic, err

    def _mic_attached(self, mic: str, err: str):
        mw = self.mw
        mw._attaching = False
        mw._done_toast = None
        updating, self._mic_updating = self._mic_updating, False
        auto, self._autofixing = self._autofixing, False
        directmic.forget_status()
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
            if auto:
                # the card turns into its one button with the reason (_mic_view)
                self._autofix_err = err
                mw.toast(_("Couldn't fix your mic by itself: see the Setup tab."), "warn")
            elif err == directmic.declined() and not updating:
                self._declined = True   # the card says so, with its button to try again
            elif updating and err == directmic.declined():
                # No to the optional update: the old part keeps working, no box needed
                mw.toast(_("Update cancelled. Your mic part is still the old one: "
                             "update it from the Setup tab."), "warn")
            elif err == directmic.mic_silent():
                # it's on the mic, but the mic came back from the audio restart dead
                mw.tell(_("Your mic sends no sound"), err, "error")
            else:
                # the route stays on the mic: until it's set up, the cable carries the
                # sounds meanwhile (_main_name), and the one-click stays on offer
                err = _("{error}\n\nTry again any time from the Setup tab.", error=err)
                mw.tell(_("Couldn't put Onion Board on your mic"), err, "error")
        else:
            log.info("on the mic now: %s", mic)
            usage.used("mic-effect-updated" if updating else
                       "mic-effect-fixed" if auto else "mic-effect-on")
            # Windows takes a few seconds to load it: "starting…" meanwhile, then a
            # redraw when the wait is over (it works by then, or Repair comes back)
            mw._settle_until = time.monotonic() + mw.SETTLE_S
            QTimer.singleShot(int(mw.SETTLE_S * 1000) + 200, mw._update_status)
            mw.cfg.route = "cable"   # so set_route() applies "mic" in full
            mw.routectl.set_route("mic", attached=True)
            from soundboard.ui.setupwizard import SetupWizard
            modal = QApplication.activeModalWidget()
            # said once it works (_update_flow), with the card turning green and Bun
            # cheering: said now, it came while the card still read "starting…" and Bun
            # was still hammering, and Windows can still fail to load it
            mw._done_toast = ("updated" if updating else "fixed" if auto else
                                None if isinstance(modal, SetupWizard) else "done")
            if is_hands_free(mic):
                mw.toast(_("That's a Bluetooth headset's call mic: some of them skip Windows' "
                             "sound effects. If nobody hears your sounds, use the headset's USB "
                             "dongle or the virtual cable."), "warn")
        mw.routectl._show_route()
        mw._update_status()

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
        from soundboard.ui import audiorecovery
        recovery = audiorecovery.recovery_of(mw)
        if recovery.running or mw._attaching:
            return

        def go_on(dialog):
            if recovery.start(action, None, say_done=True):
                dialog.accept()
                mw._update_flow()
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
            mw._update_status()
            self.install_cable()

    def _direct_health(self):
        """What the Setup tab shows about straight into my mic, to redraw it when that
        changes (checked about once a second)."""
        mw = self.mw
        e = mw.engine
        h = (directmic.status(mw.cfg.mic_device), e.main_stream is not None,
             self._direct_not_running(), bool(e.direct_apps()),
             time.monotonic() < mw._settle_until and e.effect_alive(),   # "starting…" ends
             self._mic_sends_nothing())
        return h

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
            mw._update_status()
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
        from soundboard import cableremove
        mw._vb_setup_asking = True
        worker.run(lambda: cableremove.setup_exe() is not None, mw.cable_setup_found,
                   "cable-setup", error=False, owner=mw)

    def _cable_setup_found(self, found: bool):
        mw = self.mw
        mw._vb_setup_asking = False
        if found != mw._vb_setup:
            mw._vb_setup = found
            mw._update_flow()

    def remove_cable(self):
        """Setup tab → Remove the virtual cable: VB-Audio's uninstaller, as admin (it
        waits for Windows' prompt, so it runs on a thread)."""
        mw = self.mw
        if busy.is_busy(mw.btn_rmcable):
            return
        from soundboard import cableremove
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
        mw._update_status()

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
        vm = mw.virtual_mic or _("your virtual cable")
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
