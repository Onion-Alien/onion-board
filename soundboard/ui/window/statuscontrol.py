"""What the main window says about its audio: the devices' status line and card, and the
Setup tab's flow (what you hear, what others hear, the set-up buttons in the status box
and which of them is the main one), redrawn when anything about the route changes.

MainWindow makes one ``StatusControl`` (``MainWindow.statusctl``); everything here runs on
the UI thread."""
from __future__ import annotations

import html
import re
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer

from soundboard.mic import directmic, michelper
from soundboard.ui.kit import theme
from soundboard.core import usage
from soundboard.online import net
from soundboard.audio import engine as eng
from soundboard.i18n import _, ngettext
from soundboard.ui.kit import busy, icons, reveal
from soundboard.ui.window import sidebar
from soundboard.ui.window.alertcontrol import clean_mic_note
from soundboard.ui.window.controller import Controller

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow


class StatusControl(Controller):
    """The audio status and the Setup tab's flow of one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self._xruns_shown = 0             # drop-out count last told (the "audio" toast)
        self._audio_said = ""             # what that toast says now
        self.virtual_mic: str | None = None
        self.setup_state = ""

    def _update_status(self):
        mw = self.mw
        e = mw.engine
        c = mw.cfg
        main = mw.routectl._main_name() or ""
        self.virtual_mic = eng.virtual_mic_for(main)
        if c.route == "off":
            hint = ""   # (the card's words say it)
        elif c.route == "device" and c.main_device and c.main_device == c.mon_device:
            hint = _("<span style='color:{status}'>That's your headphones too, "
                     "so nothing is sent (you'd hear everything twice). Pick "
                     "another device, or pick <b>Nobody</b>: your sounds "
                     "already play in your headphones, where OBS's Desktop "
                     "Audio picks them up.</span>", status=theme.status('warn'))
        elif c.route == "mic":
            hint = ""   # the status box says it, with its button when one's needed
        elif self.virtual_mic:
            hint = ""   # (the step above says which to pick; only trouble is added)
            if mw.micctl.cable_bad:
                rates = [f"{x.rate / 1000:g} kHz" for x in mw.micctl.cable_bad]
                if len(rates) > 1:
                    rates = [_("{first} and {second}", first=", ".join(rates[:-1]),
                               second=rates[-1])]
                hint += _("<br><span style='color:{colour}'>One end of the cable is on "
                          "{rates}, so it converts your sound on the way through. Fix it for "
                          "the cleanest sound.</span>", colour=theme.status('warn'),
                          rates=rates[0])
        elif main and (c.route == "device" or eng.is_virtual(main)):
            # (a virtual device with no mic end, e.g. Voicemeeter's inputs: a mixer. The
            # step above it says who gets them)
            hint = ""
        elif main:
            hint = _("<span style='color:{status}'>That's a normal "
                     "speaker/headphone device, so only you will hear the "
                     "sounds. Pick <b>Driver</b> above, unless that's on "
                     "purpose.</span>",
                     status=theme.status('warn'))
        elif c.route == "cable":
            # the cable is picked, just not installed yet: the line above it and Your
            # virtual mic already say so ("Nothing picked" was wrong, and said it twice)
            hint = ""
        else:
            hint = _("<span style='color:{status}'>Nothing picked: only you "
                     "will hear sounds.</span>", status=theme.status('warn'))
        dev_hint = ""   # Devices' own trouble, said in that card
        down = [n for n in mw.engine.copies_down() if n in mw.routectl._copy_names()]
        if down:
            devices = ", ".join(f"<b>{html.escape(n)}</b>" for n in down)
            dev_hint += _("<br><span style='color:{status}'>Can't open {devices} (under Also "
                          "play on). Plugged in? It's tried again by itself.</span>",
                          status=theme.status('warn'), devices=devices)
        # the headphones or mic picked here won't open (unplugged): the toast about it
        # fades, so say it where the device is picked until it's back
        unplugged = {}   # ...and the toast says it in the same words, not PortAudio's
        if not (mw._attaching or time.monotonic() < mw._settle_until):
            errs_now = e.errors_snapshot()

            def gone(key):
                name = e.names.get(key)
                if name and key in errs_now and getattr(e, f"{key}_stream", None) is None:
                    return f"<b>{html.escape(name)}</b>"
                return None
            if dev := gone("mon"):
                unplugged["mon"] = _(
                    "<br><span style='color:{status}'>Can't open {devices} (My headphones). "
                    "Plugged in? It's tried again by itself.</span>",
                    status=theme.status('warn'), devices=dev)
                dev_hint += unplugged["mon"]
            if dev := gone("mic"):
                unplugged["mic"] = _(
                    "<br><span style='color:{status}'>Can't open {devices} (My mic). "
                    "Plugged in? It's tried again by itself.</span>",
                    status=theme.status('warn'), devices=dev)
                hint += unplugged["mic"]
        hint = hint.removeprefix("<br>")   # only the lines above: no blank first line
        mw.setup_hint.setText(hint)
        mw.setup_hint.setVisible(bool(hint))   # (no empty gap)
        dev_hint = dev_hint.removeprefix("<br>")
        mw.dev_hint.setText(dev_hint)
        mw.dev_hint.setVisible(bool(dev_hint))
        mw.set_sending(mw.btn_air.isChecked())   # its label follows the route
        self._update_flow()
        where = {"main": _("sending"), "mon": _("headphones"), "mic": _("mic"),
                 "obs": _("stream output")}
        errs = [re.sub(r"<span[^>]*>(.*?)</span>", r"\1", unplugged[k][4:], flags=re.S)
                if k in unplugged else html.escape(f"{where.get(k, k)}: {v}")
                for k, v in e.errors_snapshot().items()]
        if errs and (mw._attaching or time.monotonic() < mw._settle_until):
            # setting up straight into my mic restarts Windows' audio on purpose: every
            # device drops for a few seconds and comes back by itself, so that's no error
            # (still failing once the wait is over, it shows: _mic_attached redraws then)
            errs = []
        if errs:
            self._say_audio(_("<span style='color:{status}'>Audio device problem: "
                              "{problems}</span>", status=theme.status('error'),
                              problems=" · ".join(errs)), "error")
            return
        text = ""
        xr = sum(e.xruns.values())
        self._xruns_shown = xr
        if xr:
            tip = ("" if mw.cfg.latency == "high" else
                   _(", try Settings → Audio → Audio buffering: Safer"))
            text += ("<br>" if text else "") + ngettext(
                "<span style='color:{colour}'>{n} audio drop-out since start{tip}</span>",
                "<span style='color:{colour}'>{n} audio drop-outs since start{tip}</span>",
                xr, colour=theme.status('warn'), tip=tip)
        self._say_audio(text, "warn")

    def _say_audio(self, text: str, kind: str):
        """The audio devices' state as one card: new text updates it, none takes it
        down (called on every status redraw, so the same text again does nothing)."""
        mw = self.mw
        if text == self._audio_said:
            return
        self._audio_said = text
        if text:
            mw.say(re.sub(r"<span style='color:[^']*'>(.*?)</span>", r"\1", text, flags=re.S),
                     kind, 10000, key="audio")
        else:
            mw.unsay("audio")

    def _no_load_why(self, route: str, direct: str) -> str:
        """Why it's still not working when the wait after a set-up ran out, as one of
        usage.MIC_NO_LOAD (never a name): sent elsewhere since, Windows took it off
        again, not on the mic, the board's sending into it not open, or open but the
        effect never ran (another app has the mic to itself, a driver skipping it)."""
        if route != "mic":
            return "off-route"
        if directmic.needs_repair(direct):
            return "wiped"
        if not directmic.works(direct):
            return "not-on"
        return "no-stream" if self.mw.engine.main_stream is None else "not-running"

    def _update_flow(self):
        mw = self.mw
        e = mw.engine
        vm = self.virtual_mic
        route = mw.cfg.route
        dev = mw.routectl._main_name()
        any_cable = not mw._cable_gone and bool(eng.virtual_outputs())
        direct = directmic.status(mw.cfg.mic_device) if route == "mic" else ""
        ok, warn = theme.status("ok"), theme.status("warn")
        # just set up: until Windows has it running, say so (not "Repair" straight away)
        settling = (route == "mic" and not mw._attaching
                    and time.monotonic() < mw._settle_until)
        # a virtual device with no mic end found (Voicemeeter's inputs go through its
        # mixer, not a pipe): like any device sent to, never "Virtual mic not connected"
        mixer = route == "device" or (route == "cable" and bool(dev) and not vm
                                      and eng.is_virtual(dev) and any_cable)
        # setting up straight into the mic from another route (the picker or the
        # button): the route only turns to "mic" once it works, so it's said here too
        if mw._attaching:
            state = "missing"
            step = ("" if mw.micctl._autofixing else
                    _("Click <b>Yes</b> when Windows asks for permission. Your PC's sound "
                      "drops out for a second while Windows reloads it.")
                    if michelper.will_ask() else
                    _("Your PC's sound drops out for a second while Windows reloads it."))
        elif settling and not (e.main_stream is not None and directmic.works(direct)
                               and e.effect_alive()):
            state = "missing"
            step = _("Windows is reloading your sound with Onion Board on your mic. This "
                     "takes a few seconds.")
        elif route == "mic" and directmic.needs_repair(direct):
            state = "missing"
            step = _("<b style='color:{colour}'>One click:</b> Windows took Onion Board off "
                     "your mic (a driver or Windows update does that). Windows asks for "
                     "permission once, and your sounds are back in your mic.", colour=warn)
        elif route == "mic" and not directmic.works(direct):
            state = "missing"
            step = _("<b style='color:{colour}'>One click:</b> put your sounds straight into "
                     "your mic. Windows asks for permission once; after that Discord and "
                     "games hear them through your normal mic, with nothing to set there.",
                     colour=warn)
        elif route == "mic" and e.main_stream is not None and mw.micctl._direct_not_running():
            state = "unrouted"
            step = _("Another app may have your mic to itself (an <b>exclusive mode</b> "
                     "setting), or Windows hasn't loaded Onion Board on it. Repair it below, "
                     "or send through the virtual cable instead.")
        elif route == "mic" and e.main_stream is not None:
            state = "ok"
            step = _("<b>Nothing to set.</b> Discord and games keep your normal mic, and "
                     "your sounds are in it.").replace("</b>", "</b><br>", 1)
            if direct == "outdated":   # works, but an old part: the banner below says so
                step = ""
        elif route == "mic":
            state = "unrouted"
            err = html.escape(e.errors_snapshot().get("main", ""))
            step = (_("{error}. Repair it below, or send through the virtual cable instead.",
                      error=err) if err else
                    _("Something went wrong sending into your mic. Repair it below, or send "
                      "through the virtual cable instead."))
        elif route == "off":
            state = "off"
            step = _("<b>Nothing goes out as a mic</b>, so Discord and games don't hear your "
                     "sounds. They play in your headphones (OBS's <b>Desktop Audio</b> picks "
                     "them up there) and on the <b>stream output</b> if you set one "
                     "(Settings → Audio). To send them out, pick <b>Driver</b> above.")
        elif mixer and dev and e.main_stream is not None and not vm:
            state = "ok"
            name = html.escape(dev)
            step = _("Whatever listens there gets them. "
                     "In OBS: Sources → + → <b>Audio Output Capture</b> → "
                     "<b>{name}</b>. In Voicemeeter or a mixer, send that input on "
                     "to wherever it should go. Not going on to a voice chat? Untick "
                     "<b>Send in mono</b> under Who's listening to keep it stereo.", name=name)
        elif mixer and not (dev and e.main_stream is not None):
            state = "unrouted"
            step = (_("<b style='color:{colour}'>Almost:</b> that's your headphones too. "
                      "Pick <b>Driver</b> or <b>Virtual cable</b> above.", colour=warn)
                    if mw.cfg.main_device and dev is None else
                    _("<b style='color:{colour}'>Almost:</b> check that device is plugged in, "
                      "or pick <b>Driver</b> or <b>Virtual cable</b> above.", colour=warn))
        elif route == "device":   # another virtual cable: its other end is the mic
            state = "ok"
            step = _("<b>The only thing you set:</b> in Discord, your game or OBS, pick "
                     "<b style='color:{colour}'>{device}</b> as the <b>microphone</b> / audio "
                     "input.", colour=ok, device=vm)
        elif not any_cable:
            state = "missing"
            # not wrong, just not done yet: orange like the step below, not a red cross
            step = (_("<b style='color:{colour}'>One-time setup:</b> the virtual cable is a "
                      "download, and Offline mode is on. Pick <b>Driver</b> above: nothing to "
                      "download.", colour=warn) if net.offline() else
                    _("<b style='color:{colour}'>One step left:</b> install the free virtual "
                      "cable, or pick <b>Driver</b> above: nothing to install.", colour=warn))
        elif vm and e.main_stream is not None:
            state = "ok"
            step = _("<b>The only thing you set:</b> in Discord or your game, pick "
                     "<b style='color:{colour}'>{device}</b> as your <b>microphone</b>, and "
                     "switch off its noise suppression (Discord: <b>Input Profile → "
                     "Studio</b>), or it chops your sounds up.", colour=ok, device=vm)
            step = " ".join(filter(None, (step, clean_mic_note())))
        else:
            state = "unrouted"
            step = _("<b style='color:{colour}'>Almost:</b> check your virtual cable is "
                     "plugged in or installed, or pick <b>Driver</b> above.", colour=warn)
        if route != "mic" and mw.micctl._declined and not mw._attaching:
            # a No to the set-up from another route: the route stays, the card says why
            step = mw.micctl.declined_text()
        mic_route = route == "mic"
        button = None   # straight into the mic: the one button, when it needs a click
        # one status box whatever the route: what's happening, why, what to do
        if mic_route:
            reason, button = mw.micctl._show_mic_status(direct, state, settling, step)
        else:
            reason = self._show_route_status(state, bool(vm), dev, step)
        mw.mic_reason.setText(reason)
        reveal.set_shown(mw.mic_reason, bool(reason))
        # a card asking for a click after a failed set-up: the report button under it
        mw.mic_report.set_failed(mic_route and button is not None and not mw._attaching
                                 and bool(mw.micctl.fail_code))
        self._show_mic_level()
        mw.mic_pill.setVisible(True)
        mw.btn_mictips.setVisible(route == "mic")
        update = route == "mic" and state == "ok" and direct == "outdated"
        if update:
            mw.mic_update_text.setText(_(
                "<b style='color:{colour}'>Update your mic part</b><br>It's from an older "
                "version of Onion Board, so some games, calls and browsers may not hear "
                "your sounds. Windows asks once, and your sound drops out for a second.",
                colour=warn) if michelper.will_ask() else _(
                "<b style='color:{colour}'>Update your mic part</b><br>It's from an older "
                "version of Onion Board, so some games, calls and browsers may not hear "
                "your sounds. Your sound drops out for a second.", colour=warn))
        # setting up, or Windows still loading it: the button stays "Setting up…" and
        # takes no clicks (attach_mic holds it) until it works or the wait is over
        mic_busy = mw._attaching or (route == "mic" and settling and state != "ok")
        if (mw._done_toast and not mic_busy and route == "mic" and state != "ok"
                and not mw._settle_more):
            # not working yet when the wait ran out: after Windows' audio restart the
            # board's own streams come back on their next retry, and a slow PC takes
            # longer to load it. One longer wait before it counts as not working
            mw._settle_more = True
            mw._settle_until = time.monotonic() + mw.SETTLE_MORE_S
            QTimer.singleShot(int(mw.SETTLE_MORE_S * 1000) + 200, mw,
                              self._update_status)
            self._update_flow()
            return
        if mw._attach_release is not None and not mic_busy:
            release, mw._attach_release = mw._attach_release, None
            release()
        if mw.setup_show.on and not mic_busy:
            mw.setup_show.finish(route == "mic" and state == "ok")
        elif mic_busy and mw._show_bun and not mw.setup_show.on:
            # still setting up or starting, but Bun's show ended (he left while the tab
            # was hidden): back on, never a Repair button beside "starting…"
            mw.setup_show.start()
        if not mic_busy:
            mw._show_bun = False
        effect_on = (mic_route and not mic_busy and not mw.setup_show.on
                     and directmic.works(direct))
        # no mic picked: nothing to reinstall or remove, only a mic to pick
        no_mic = mic_route and not mic_busy and not mw.cfg.mic_device
        mw.btn_michange.setVisible(no_mic and mw.cb_mic.count() > 0)
        mw.btn_micredo.setVisible(effect_on and not no_mic)
        mw.btn_micoff.setVisible(effect_on and not no_mic)
        said = mw._done_toast
        if said and not mic_busy:
            mw._done_toast = None
            mw._settle_more = False
            if route != "mic" or state != "ok":
                # set up, not working when the wait ran out, and why (one word)
                usage.used("mic-effect-no-load")
                usage.used(f"mic-effect-no-load-{self._no_load_why(route, direct)}")
            if route == "mic" and state == "ok":   # (the wait ran out: no "Done")
                mw.toast(_("Mic updated: games, calls and browsers hear your sounds.")
                           if said == "updated" else
                           _("Done: your sounds are back in your mic.") if said == "fixed" else
                           _("Done: Discord and games hear your sounds through your mic now."),
                           "ok")
        if route == "mic" and state == "ok" and not mic_busy:
            mw.micctl.probe_mic()   # (once after a set-up: does the mic carry the sounds?)
        # an old part: the banner and its button, until Bun's show is over
        mw.mic_update_note.setVisible(update and not mw.setup_show.on)
        mw.btn_install.setVisible((button is not None if mic_route else state == "missing")
                                    and not mw.setup_show.on)   # Bun's show instead
        if not busy.is_busy(mw.btn_install):
            mw.btn_install.setText(button or _("Install the free virtual cable"))
            # Windows' shield when its prompt comes, like Windows' own buttons
            # white only while it's the filled main button (white vanished on Light's grey)
            look = (("shield" if michelper.will_ask() else "mic") if mic_route else "cable",
                    "muted" if update else "on_accent")
            if look != mw._install_icon:
                mw._install_icon = look
                if look[0] == "shield":
                    from soundboard.ui.setup.micupdate import _shield
                    _shield(mw.btn_install)
                else:
                    icons.set_icon(mw.btn_install, *look)
        self._set_primary(mw.btn_install, not update)   # (the update: optional)
        mw.install_glow.set_on(route == "mic" and not update)   # the main one glows
        mw.btn_rmcable_on.setVisible(
            route == "cable" and not mic_busy and mw.micctl._spare_cable()
            and "voicemeeter" not in (mw.cfg.main_device or "").lower())   # (not what it removes)
        mw.mic_fix.setVisible(not (mw.btn_micredo.isHidden() and mw.btn_micoff.isHidden()
                                   and mw.btn_rmcable_on.isHidden()))
        if route == "mic":
            mw._direct_shown = mw.micctl._direct_health()
        mw.netctl._cable_follow_switch()
        # "check again" only once they've started a cable install: before, it was a
        # fourth button about a thing they hadn't done
        mw.btn_rescan.setVisible(state == "missing" and route != "mic"
                                 and getattr(mw, "_cable_started", False))
        mw.routectl._show_switch()
        mw.route_switch.setEnabled(not mic_busy)
        # Discord / the game picks a mic, or keeps its own one: help with its settings
        mic_side = state == "ok" and (bool(vm) or route == "mic")
        mw.btn_nomic.setVisible(mic_side and route != "mic")   # (no mic to switch to)
        mw.btn_chat.setVisible(mic_side)
        mw.btn_game.setVisible(mic_side)
        mw.btn_meeting.setVisible(mic_side)
        # no chat to connect yet: Set up your voice apps holds just the step-by-step guide
        mw.chat_hint.setVisible(mic_side)
        cablefix = state == "ok" and bool(vm) and bool(mw.micctl.cable_bad)
        mw.btn_cablefix.setVisible(cablefix)
        # "off" was picked on purpose: it's set up, as far as the rest of the app goes
        self.setup_state = "ok" if state == "off" else state
        # a device is picked to send to (not the headphones): failing is "Not working",
        # never "Not configured"
        picked = (mw.cfg.main_device if route in ("cable", "device")
                  and mw.cfg.main_device != mw.cfg.mon_device else None)
        pills = []   # (short, whole): the open rail shows the short one
        for short in (True, False):
            if state == "off":
                pill = _("Only you") if short else _("Not sending to others (only you hear sounds)")
            elif route == "mic" and not mic_busy and mw.micctl.mic_unplugged() \
                    and directmic.sound_only(mw.cfg.mic_device):
                # a Bluetooth headset that plays, with its mic half off: not "plugged in?"
                pill = _("Mic off") if short else _("Your headset's mic is off")
            elif route == "mic" and not mic_busy and mw.micctl.mic_unplugged():
                # pulled out or switched off: nothing's broken, it works once it's back
                pill = _("Unplugged") if short else _("Is your headset plugged in?")
            elif state == "ok" and route == "mic":
                pill = (_("Connected") if short
                        else _("In your mic: Discord / games hear your sounds"))
            elif mic_busy and mw.micctl._autofixing:
                pill = _("Fixing your mic…")
            elif mic_busy:
                pill = _("Setting up…") if short else _("Setting up your mic…")
            elif route == "mic" and state != "missing":
                pill = _("Not working") if short else _("Not reaching your mic, click to fix")
            elif route == "mic" and directmic.needs_repair(direct):
                pill = _("Repair needed") if short else _("One click needed: repair your mic")
            elif route == "mic":
                pill = (_("1 step left") if short
                        else _("Your sounds aren't in your mic yet: one click to fix"))
            elif state == "ok" and not vm:
                pill = _("Connected") if short else _("Sending to:  {dev}", dev=dev)
            elif state == "ok":
                pill = _("Connected") if short else _("Your mic in Discord / games:  {vm}", vm=vm)
            elif state == "missing":
                pill = (_("Setup needed") if short
                        else _("One-time setup needed, others can't hear you yet"))
            elif picked:   # set up, but it won't open (or the cable's mic end is gone)
                pill = (_("Not working") if short
                        else _("Can't send to {device}, click to fix", device=picked))
            elif route == "device":
                pill = (_("Not configured") if short
                        else _("Not sending: pick a device on the Setup tab"))
            else:   # (the Setup tab offers straight into the mic first)
                pill = (_("Not configured") if short
                        else _("Not configured: click to fix"))
            pills.append(pill)
        pill_short, pill = pills
        if route != "mic":   # (on the mic, _show_mic_status has said it)
            mw.mic_pill.setText(pill_short)
            theme.set_tone(mw.mic_pill, "" if state == "off" else
                           "ok" if state == "ok" else "warn")
        # into the mic, not in it yet: "What others hear" moves with your voice alone
        voice_only = (route == "mic" and state not in ("ok", "off") and not mic_busy
                      and mw.engine.mic_stream is not None and mw.cfg.mic_enabled)
        if voice_only == mw.voice_only.isHidden():
            mw.voice_only.setVisible(voice_only)
            # it makes the strip wider with no resize to fit it again: squeezed, it read
            # "ice on" and Hear what they hear lost letters too
            QTimer.singleShot(0, mw, mw.fitctl._refit)
        if hasattr(mw, "mini_connection"):
            route_name = (_("My mic") if route == "mic" else
                          _("Only you") if state == "off" else _("Output"))
            mw.mini_connection.setText(_("{route}: {status}",
                                          route=route_name, status=pill_short))
            mw.mini_connection.setToolTip(pill)
            mw.mini_connection.setAccessibleName(pill)
            mw.mini_connection.setProperty("state", "ok" if state in ("ok", "off")
                                              else "warn")
            mw.mini_connection.style().unpolish(mw.mini_connection)
            mw.mini_connection.style().polish(mw.mini_connection)
        good = state in ("ok", "off")
        if good != mw._pill_good:
            # all set: Live says it, so the pill only shows when something needs a click
            mw._pill_good = good
            mw._show_pill()
        if mw._pill_long != pill:
            mw._pill_long = pill
            # (the icon first: the On Air card copies it when `put` refreshes it)
            mw.pill.setIcon(icons.icon("headphones", "live_text") if state == "off" else
                              icons.icon("check", "live_text") if good else
                              icons.icon("warn", "warn_text"))
            sidebar.put(mw.pill, pill_short, pill,
                        _("Where your sounds go, click for setup and testing"))
            mw.pill.setProperty("state", "ok" if good else "warn")
            mw.pill.style().unpolish(mw.pill)
            mw.pill.style().polish(mw.pill)
            mw.set_sending(mw.btn_air.isChecked())   # its tooltip carries the pill's text

    def _show_mic_level(self):
        """Beside the mic's box: its level, and what the level can't say by itself."""
        mw = self.mw
        e = mw.engine
        mic = mw.cfg.mic_device
        mw.card_meter.setVisible(bool(mic) and e.mic_stream is not None)
        if mic:
            # (on the cable two things read as "a mic": this one is where the voice comes from)
            sub = (_("Not sent, sounds only") if not mw.cfg.mic_enabled else
                   _("Your voice comes from here") if mw.cfg.route in ("cable", "device") else "")
        else:
            sub = ""
            if mw.cfg.route in ("cable", "device"):
                sub = (_("Pick your mic so others hear you too") if mw.cb_mic.count()
                       else _("No mic found: others hear only your sounds"))
        mw.mic_sub.setText(sub)
        mw.mic_sub.setToolTip(sub)
        mw.mic_sub.setVisible(bool(sub))

    def _show_route_status(self, state: str, cable_mic: bool, dev: str | None, step: str) -> str:
        """The status box off the mic route (on it: _show_mic_status). Gives its reason."""
        mw = self.mw
        voice = bool(mw.cfg.mic_device) and mw.cfg.mic_enabled
        if mw._attaching:   # on its way to the mic: the route only turns once it works
            look = ("warn", "reload", _("Setting up…"))
        elif state == "off":
            look = ("", "headphones", _("Only you hear your sounds"))
        elif state == "ok" and cable_mic:
            look = ("ok", "check", _("Your sounds and voice go into the virtual cable") if voice
                    else _("Your sounds go into the virtual cable"))
        elif state == "ok":
            look = ("ok", "check", _("Your sounds go to {device}", device=dev))
        elif state == "missing":
            look = ("warn", "cable", _("The virtual cable isn't installed yet"))
        else:
            look = ("error", "warn", _("Not sending"))
        mw.micctl._set_status(*look)
        return step

    @staticmethod
    def _set_primary(btn, on: bool):
        name = "primary" if on else ""
        if btn.objectName() != name:
            btn.setObjectName(name)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def show_chat_guide(self, which: str):
        mw = self.mw
        from soundboard.ui.setup.chatguide import show_guide
        show_guide(which, mw, mw, self.virtual_mic or "CABLE Output")
