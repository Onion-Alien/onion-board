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
            hint = _("Sending to others is off: your sounds play in your "
                     "headphones and on a device set to Clean, for streaming "
                     "(Also play on) only.")
        elif c.route == "device" and c.main_device and c.main_device == c.mon_device:
            hint = _("<span style='color:{status}'>That's your headphones too, "
                     "so nothing is sent (you'd hear everything twice). Pick "
                     "another device, or pick <b>Nobody</b>: your sounds "
                     "already play in your headphones, where OBS's Desktop "
                     "Audio picks them up.</span>", status=theme.status('warn'))
        elif c.route == "mic":
            hint = _("Your sounds go straight into <b>My mic</b>, so Discord "
                     "and games hear them through the mic they already use.")
        elif self.virtual_mic:
            hint = (_("A virtual cable is a pipe: audio goes in at <b>{main}</b> and comes out "
                      "at <b>{virtual_mic}</b>, which Discord / the game uses as your mic.",
                      main=main, virtual_mic=self.virtual_mic))
            if mw.micctl.cable_bad:
                rates = [f"{x.rate / 1000:g} kHz" for x in mw.micctl.cable_bad]
                if len(rates) > 1:
                    rates = [_("{first} and {second}", first=", ".join(rates[:-1]),
                               second=rates[-1])]
                hint += _("<br><span style='color:{colour}'>One end of the cable is on "
                          "{rates}, so it converts your sound on the way through. Fix it for "
                          "the cleanest sound.</span>", colour=theme.status('warn'),
                          rates=rates[0])
        elif main and c.route == "device":
            hint = _("Whatever listens to <b>{main}</b> gets your sounds (and "
                     "your voice, if you send it): OBS, Voicemeeter, a mixer or "
                     "a capture card.", main=html.escape(main))
        elif main:
            hint = _("<span style='color:{status}'>That's a normal "
                     "speaker/headphone device, so only you will hear the "
                     "sounds. Set <b>Send my sounds to</b> back to <b>My "
                     "mic</b>, unless that's on purpose.</span>",
                     status=theme.status('warn'))
        elif c.route == "cable":
            # the cable is picked, just not installed yet: the line above it and Your
            # virtual mic already say so ("Nothing picked" was wrong, and said it twice)
            hint = ""
        else:
            hint = _("<span style='color:{status}'>Nothing picked: only you "
                     "will hear sounds.</span>", status=theme.status('warn'))
        down = [n for n in mw.engine.copies_down() if n in mw.routectl._copy_names()]
        if down:
            devices = ", ".join(f"<b>{html.escape(n)}</b>" for n in down)
            hint += _("<br><span style='color:{status}'>Can't open {devices} (under Also play on). "
                      "Plugged in? It's tried again by itself.</span>",
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
                hint += unplugged["mon"]
            if dev := gone("mic"):
                unplugged["mic"] = _(
                    "<br><span style='color:{status}'>Can't open {devices} (My mic). "
                    "Plugged in? It's tried again by itself.</span>",
                    status=theme.status('warn'), devices=dev)
                hint += unplugged["mic"]
        hint = hint.removeprefix("<br>")   # only the lines above: no blank first line
        mw.setup_hint.setText(hint)
        mw.setup_hint.setVisible(bool(hint))   # (no empty gap)
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

    def _update_flow(self, talking=False):
        mw = self.mw
        e = mw.engine
        ok, bad = theme.status("ok"), theme.status("error")
        if not mw.cfg.mic_enabled:
            mic = _("Your mic  <b style='color:{colour}'>not sent (sounds only)</b>",
                    colour=theme.status('warn'))
        elif e.mic_stream is None:
            mic = _("Your mic  <b style='color:{colour}'>✗ off</b>", colour=bad)
        elif talking:
            mic = _("Your mic  <b style='color:{colour}'>✓ hearing you</b>", colour=ok)
        else:
            mic = _("Your mic  <b style='color:{colour}'>✓</b>", colour=ok)
        vm = self.virtual_mic
        route = mw.cfg.route
        dev = mw.routectl._main_name()
        any_cable = not mw._cable_gone and bool(eng.virtual_outputs())
        direct = directmic.status(mw.cfg.mic_device) if route == "mic" else ""
        warn = theme.status("warn")
        # just set up: until Windows has it running, say so (not "Repair" straight away)
        settling = (route == "mic" and not mw._attaching
                    and time.monotonic() < mw._settle_until)
        if route == "mic" and mw._attaching:
            state = "missing"
            out = _("Into your mic  <b>setting up…</b>")
            step = ("" if mw.micctl._autofixing else
                    _("Click <b>Yes</b> when Windows asks for permission. Your PC's sound "
                      "drops out for a second while Windows reloads it.")
                    if michelper.will_ask() else
                    _("Your PC's sound drops out for a second while Windows reloads it."))
        elif settling and not (e.main_stream is not None and directmic.works(direct)
                               and e.effect_alive()):
            state = "missing"
            out = _("Into your mic  <b>starting…</b>")
            step = _("Windows is reloading your sound with Onion Board on your mic. This "
                     "takes a few seconds.")
        elif route == "mic" and directmic.needs_repair(direct):
            state = "missing"
            out = _("Into your mic  <b style='color:{colour}'>✗ needs a quick repair</b>",
                    colour=bad)
            step = _("<b style='color:{colour}'>One click:</b> Windows took Onion Board off "
                     "your mic (a driver or Windows update does that). Windows asks for "
                     "permission once, and your sounds are back in your mic.", colour=warn)
        elif route == "mic" and not directmic.works(direct):
            state = "missing"
            out = (_("Into your mic  <b style='color:{colour}'>one click to go</b>",
                     colour=warn) if direct == "missing" else
                   _("Into your mic  <b style='color:{colour}'>set up on another mic</b>",
                     colour=warn))
            step = _("<b style='color:{colour}'>One click:</b> put your sounds straight into "
                     "your mic. Windows asks for permission once; after that Discord and "
                     "games hear them through your normal mic, with nothing to set there.",
                     colour=warn)
        elif route == "mic" and e.main_stream is not None and mw.micctl._direct_not_running():
            state = "unrouted"
            out = _("Into your mic  <b style='color:{colour}'>✗ not running</b>", colour=bad)
            step = _("Another app may have your mic to itself (an <b>exclusive mode</b> "
                     "setting), or Windows hasn't loaded Onion Board on it. Repair it below, "
                     "or send through the virtual cable instead.")
        elif route == "mic" and e.main_stream is not None:
            state = "ok"
            name = html.escape(mw.cfg.mic_device or _("your mic"))
            apps = e.direct_apps()
            out = (_("<b style='color:{colour}'>{name}</b>, your sounds are in it "
                     "<b style='color:{colour}'>✓</b>", colour=ok, name=name)
                   + ("  " + _("<b style='color:{colour}'>(live)</b>", colour=ok)
                      if apps else ""))
            step = _("<b>Nothing to set.</b> Discord and games keep your normal mic, and "
                     "your sounds are in it.").replace("</b>", "</b><br>", 1)
            if direct == "outdated":   # works, but an old part: the banner below says so
                out = _("<b style='color:{colour}'>{name}</b>, with an old version of "
                        "Onion Board's mic part", colour=warn, name=name)
                step = ""
        elif route == "mic":
            state = "unrouted"
            out = _("Into your mic  <b style='color:{colour}'>✗ can't reach it</b>",
                    colour=bad)
            err = html.escape(e.errors_snapshot().get("main", ""))
            step = (_("{error}. Repair it below, or send through the virtual cable instead.",
                      error=err) if err else
                    _("Something went wrong sending into your mic. Repair it below, or send "
                      "through the virtual cable instead."))
        elif route == "off":
            state = "off"
            out = _("Sent to others  <b>nowhere (your choice)</b>")
            step = _("<b>Nothing goes out as a mic</b>, so Discord and games don't hear your "
                     "sounds. They play in your headphones (OBS's <b>Desktop Audio</b> picks "
                     "them up there) and on the <b>stream output</b> if you set one "
                     "(Settings → Audio). To send them out, set <b>Send my sounds to</b> "
                     "back to <b>My mic</b> under Devices.")
        elif route == "device" and dev and e.main_stream is not None and not vm:
            state = "ok"
            name = html.escape(dev)
            out = _("<b style='color:{colour}'>{name}</b>, sending "
                    "<b style='color:{colour}'>✓</b>", colour=ok, name=name)
            step = _("<b>Your sounds go to {name}.</b> Whatever listens there gets them. "
                     "In OBS: Sources → + → <b>Audio Output Capture</b> → "
                     "<b>{name}</b>. In Voicemeeter or a mixer, send that input on "
                     "to wherever it should go. Not going on to a voice chat? Untick "
                     "<b>Send in mono</b> under Who's listening to keep it stereo.", name=name)
        elif route == "device" and not (dev and e.main_stream is not None):
            state = "unrouted"
            if mw.cfg.main_device and dev is None:
                out = _("Sending  <b style='color:{colour}'>✗ same device as your "
                        "headphones</b>", colour=bad)
            elif dev:
                out = _("Sending  <b style='color:{colour}'>✗ can't open {device}</b>",
                        colour=bad, device=html.escape(dev))
            else:
                out = _("Sending  <b style='color:{colour}'>✗ no device picked</b>", colour=bad)
            step = (_("<b style='color:{colour}'>Almost:</b> under <b>Devices</b>, set <b>Send "
                      "my sounds to</b> to another device than your headphones, or to <b>My "
                      "mic</b>.", colour=warn)
                    if mw.cfg.main_device and dev is None else
                    _("<b style='color:{colour}'>Almost:</b> under <b>Devices</b>, set <b>Send "
                      "my sounds to</b> to the device that should get your sounds (and check "
                      "it's plugged in), or to <b>My mic</b>.", colour=warn))
        elif route == "device":   # another virtual cable: its other end is the mic
            state = "ok"
            out = _("<b style='color:{colour}'>{device}</b>, your new mic "
                    "<b style='color:{colour}'>✓ working</b>", colour=ok, device=vm)
            step = _("<b>The only thing you set:</b> in Discord, your game or OBS, pick "
                     "<b style='color:{colour}'>{device}</b> as the <b>microphone</b> / audio "
                     "input.", colour=ok, device=vm)
        elif not any_cable:
            state = "missing"
            # not wrong, just not done yet: orange like the step below, not a red cross
            out = _("Virtual mic  <b style='color:{colour}'>not installed yet</b>",
                    colour=warn)
            step = (_("<b style='color:{colour}'>One-time setup:</b> put your sounds straight "
                      "into your mic, so Discord and games hear them (nothing to install). The "
                      "virtual cable is a download, and Offline mode is on. Voicemeeter, a "
                      "mixer or OBS? Pick that device under <b>Send my sounds to</b>.",
                      colour=warn) if net.offline() else
                    _("<b style='color:{colour}'>One step left:</b> click <b>Put my sounds "
                      "into my mic</b> and Discord and games hear them. Nothing to install.",
                      colour=warn))
        elif vm and e.main_stream is not None:
            state = "ok"
            out = _("<b style='color:{colour}'>{device}</b>, your new mic "
                    "<b style='color:{colour}'>✓ working</b>", colour=ok, device=vm)
            step = _("<b>The only thing you set:</b> in Discord or your game, pick "
                     "<b style='color:{colour}'>{device}</b> as your <b>microphone</b>, and "
                     "switch off its noise suppression (Discord: <b>Input Profile → "
                     "Studio</b>), or it chops your sounds up.", colour=ok, device=vm)
            step = " ".join(filter(None, (step, clean_mic_note())))
        else:
            state = "unrouted"
            out = _("Virtual mic  <b style='color:{colour}'>✗ not connected</b>", colour=bad)
            step = _("<b style='color:{colour}'>Almost:</b> under <b>Devices</b>, set "
                     "<b>Send my sounds to</b> to your virtual cable, or to <b>My mic</b>.",
                     colour=warn)
        if state == "missing" and mw.cfg.mic_enabled and e.mic_stream is None:
            # nothing is set up yet: the mic being closed is part of that, not a second
            # fault (the card showed two red crosses and the header a warning over
            # one thing to do)
            mic = _("Your mic  <b style='color:{colour}'>after the setup below</b>",
                    colour=warn)
        # the app's own painted tick and cross, not the font's ✓ / ✗ (a brushy x)
        # level with the words in the theme's font, whatever its shape
        dpr = mw.flow_out.devicePixelRatioF() or 1.0
        mw.flow_out.ensurePolished()
        font = mw.flow_out.font()

        def marks(text: str) -> str:
            return (text.replace("✗", icons.inline("cross", bad, dpr=dpr, font=font))
                    .replace("✓", icons.inline("check", ok, dpr=dpr, font=font)))
        mw.flow_mic.setText(marks(mic))
        mw.flow_out.setText(marks(out))
        mic_route = route == "mic"
        button = None   # straight into the mic: the one button, when it needs a click
        self._place_ways(mic_route)
        if mic_route:
            reason, button = mw.micctl._show_mic_status(direct, state, settling, step)
            mw.mic_reason.setText(reason)
            reveal.set_shown(mw.mic_reason, bool(reason))
            step = ""   # (said in the box)
        # a card asking for a click after a failed set-up: the report button under it
        mw.mic_report.set_failed(mic_route and button is not None and not mw._attaching
                                 and bool(mw.micctl.fail_code))
        mw.mic_flow.setVisible(not mic_route)
        if not mic_route:
            reveal.set_shown(mw.mic_voice, False)   # (_show_mic_status says when, on the mic)
        mw.mic_status.setVisible(mic_route)
        mw.mic_pill.setVisible(mic_route)
        mw.step_lbl.setText(step)
        mw.btn_mictips.setVisible(route == "mic")
        update = route == "mic" and state == "ok" and direct == "outdated"
        mw.step_lbl.setVisible(bool(step))   # (the update banner says it instead)
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
        mic_busy = route == "mic" and (mw._attaching or (settling and state != "ok"))
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
        mw.btn_michange.setVisible(effect_on)
        mw.btn_micredo.setVisible(effect_on)
        mw.btn_micoff.setVisible(effect_on)
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
            # white only while it's the filled main button: on the cable route it's a
            # plain one, and white vanished on Light's grey
            look = (("shield" if michelper.will_ask() else "mic") if mic_route else "cable",
                    "muted" if update else "on_accent" if route == "mic" else None)
            if look != mw._install_icon:
                mw._install_icon = look
                if look[0] == "shield":
                    from soundboard.ui.setup.micupdate import _shield
                    _shield(mw.btn_install)
                else:
                    icons.set_icon(mw.btn_install, *look)
        # the mic is the main way: on the cable route the cable's button comes second
        self._set_primary(mw.btn_install, route == "mic" and not update)   # (optional)
        mw.install_glow.set_on(route == "mic" and not update)   # the main one glows
        self._set_primary(mw.btn_attach, route == "cable")
        # its mic in the fill's colour while it's the main button (text colour on the
        # accent was 1.0:1 on Hacker's green)
        icons.recolor(mw.btn_attach, "on_accent" if route == "cable" else None)
        # the other ways sit beside the main button as plain words, every time
        reveal.set_shown(mw.mic_alt, route == "mic" and not mic_busy)   # also when it works
        mw.alt_cable.setVisible(not mw._cable_gone)   # (back after a restart)
        mw.btn_usecable.setVisible(route == "mic" and not mic_busy and not mw._cable_gone)
        mw.btn_cableinfo.setVisible(mw.btn_usecable.isVisibleTo(mw.alt_cable))
        spare = route == "mic" and state == "ok" and mw.micctl._spare_cable()
        mw.btn_rmcable.setVisible(spare)
        # installed and spare: say why there's a Use and a Remove, not two puzzles
        mw.alt_cable_words.setText(
            _("It's installed, but your sounds go into your mic now. Use it if a game skips "
              "your mic, or remove it if nothing else needs it.") if spare else
            _("No mic, or you'd rather Onion Board didn't touch yours? Use a free virtual "
              "cable instead: you pick it as the mic in Discord and games."))
        mw.rmcable_note.hide()   # (its tooltip says it)
        if route == "mic":
            mw._direct_shown = mw.micctl._direct_health()
        mw.netctl._cable_follow_switch()
        # "check again" only once they've started a cable install: before, it was a
        # fourth button about a thing they hadn't done
        mw.btn_rescan.setVisible(state == "missing" and route != "mic"
                                 and getattr(mw, "_cable_started", False))
        # the cable isn't a mic the mic part goes on: no "into my mic" button there; the
        # switch on top changes the way instead, once the cable is installed
        mw.btn_attach.setVisible(route == "cable" and not mw._attaching and not any_cable)
        mw.route_switch.setVisible(any_cable and route in ("cable", "mic"))
        (mw.seg_mic if route == "mic" else mw.seg_cable).setChecked(True)
        mw.route_switch.setEnabled(not mic_busy)
        mw.ways_or.setVisible(not mw.btn_attach.isHidden() and not mw.btn_install.isHidden())
        if route == "mic":
            mw.micctl._cable_tip()
        # Discord / the game picks a mic, or keeps its own one: help with its settings
        mic_side = state == "ok" and (bool(vm) or route == "mic")
        mw.btn_nomic.setVisible(mic_side and route != "mic")   # (no mic to switch to)
        mw.btn_chat.setVisible(mic_side)
        mw.btn_game.setVisible(mic_side)
        mw.btn_meeting.setVisible(mic_side)
        # one rule: Connect your chat shows when there's a chat to connect; until then
        # its one button (the guide) sits in the mic card
        mw.helpcard.setVisible(mic_side)
        mw.btn_guide.setVisible(not mic_side)   # (Connect your chat has it then)
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
        mw.setup_connection.setText(pill)
        mw.setup_connection.setVisible(route != "mic")   # (the mic card's pill says it)
        # into the mic, not in it yet: "What others hear" moves with your voice alone
        mw.voice_only.setVisible(route == "mic" and state not in ("ok", "off") and not mic_busy
                                 and mw.engine.mic_stream is not None and mw.cfg.mic_enabled)
        mw.setup_connection.setProperty("tone", "ok" if state in ("ok", "off") else "warn")
        mw.setup_connection.style().unpolish(mw.setup_connection)
        mw.setup_connection.style().polish(mw.setup_connection)
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
            sidebar.put(mw.pill, pill_short, pill,
                        _("Where your sounds go, click for setup and testing"))
            mw.pill.setIcon(icons.icon("headphones", "live_text") if state == "off" else
                              icons.icon("check", "live_text") if good else
                              icons.icon("warn", "warn_text"))
            mw.pill.setProperty("state", "ok" if good else "warn")
            mw.pill.style().unpolish(mw.pill)
            mw.pill.style().polish(mw.pill)
            mw.set_sending(mw.btn_air.isChecked())   # its tooltip carries the pill's text

    def _place_ways(self, mic: bool):
        """The set-up buttons sit in the status box on the mic route (one place for
        the state and what to do about it), in their row under the picture otherwise."""
        mw = self.mw
        if mw._ways_in == mic:
            return
        mw._ways_in = mic
        src, dst = (mw._ways, mw.mic_ways) if mic else (mw.mic_ways, mw._ways)
        # (check again too: it stays last, after them)
        for b in (mw.btn_install, mw.btn_guide, mw.btn_rescan):
            src.removeWidget(b)
            dst.addWidget(b)
        mw.mic_ways.invalidate()
        mw._ways.invalidate()

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
