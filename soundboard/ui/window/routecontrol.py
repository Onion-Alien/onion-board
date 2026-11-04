"""Where the main window's sounds go: the device pickers, the route (straight into the mic, a
cable, or only your headphones), the extra places sounds are sent (another output, OBS's
device, the kind of send), and what the mic button and mute do on each route.

MainWindow makes one ``RouteControl`` (``MainWindow.routectl``); everything here runs on the
UI thread."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QCheckBox, QMessageBox

from soundboard.audio import appaudio
from soundboard.ui.bun import bunny
from soundboard.mic import directmic
from soundboard.core import usage
from soundboard.sounds import library
from soundboard.audio import engine as eng
from soundboard.audio.engine import is_virtual as is_virtual_cable
from soundboard.i18n import _
from soundboard.ui.kit import worker
from soundboard.ui.window.controller import Controller
from soundboard.ui.kit.crashdialog import free_dialog

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

log = logging.getLogger(__name__)

ROUTE_DEVICE = "device:"
MIC_FAILED = "mic-attach-failed"   # the toast key of "Couldn't put Onion Board on your mic"


class RouteControl(Controller):
    """The route and send outputs of one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self.finding_mic = False   # use_mic: asking which mic Onion Board is on already
        self._find_id = 0          # ...that ask's number: an answer to an older one is dropped

    def _fill_combo(self, cb, names, current):
        cb.blockSignals(True)
        cb.clear()
        if cb is self.mw.cb_mic:
            # no "(none)" to get stuck on: no mic picked, it asks for one (and a saved mic
            # that isn't plugged in shows its name, greyed: the card says what's up)
            cb.setPlaceholderText(current or _("Pick your mic"))
        else:
            cb.addItem(_("(none)"), None)
        for n in names:
            cb.addItem(n, n)
        i = cb.findData(current) if current else 0
        cb.setCurrentIndex(-1 if cb is self.mw.cb_mic and not (current and i >= 0)
                           else max(i, 0))
        cb.view().setMinimumWidth(cb.view().sizeHintForColumn(0) + 32)   # whole names
        cb.blockSignals(False)

    def on_device(self, cb, attr, follow: bool = True):
        """A Devices box was picked. `follow`: a new My mic on the mic route takes the
        mic effect along (Windows asks); not when use_mic picked it (no prompt there)."""
        mw = self.mw
        name = cb.currentData()
        if attr == "route":
            if name and name.startswith(ROUTE_DEVICE):   # a device by name
                dev = name[len(ROUTE_DEVICE):] or None
                self.set_route("cable" if dev is None or is_virtual_cable(dev) else "device",
                               dev, by_hand=True)
            else:
                self.set_route(name, by_hand=True)
            return
        setattr(mw.cfg, attr, name)
        if attr == "mon_device":
            # picking Windows' default keeps following it; anything else stays put
            if not mw.cfg.mon_follows_default:   # not looked at while not following
                mw._default_out = appaudio.default_output_name() or mw._default_out
            mw.cfg.mon_follows_default = name is not None and name == mw.devctl._default_output()
        mw._save_now()
        if attr in ("mon_device", "mic_device"):
            # the headphones aren't offered as where sounds go; the mic comes first
            self._show_route()
        e = mw.engine

        def plan():   # the streams are opened on the device thread (_device_job)
            send = self._send_plan(force_main=attr == "main_device")

            def work():
                if attr == "mon_device":
                    e.set_mon_device(name)
                elif attr == "mic_device":
                    e.set_mic_device(name)
                return self._open_send(send)
            return work

        def opened(ends):
            if ends is not None:
                mw.micctl._set_cable_bad(ends)
            if follow and attr == "mic_device" and mw.cfg.route == "mic" \
                    and directmic.status(name) == "other":
                mw.micctl.attach_mic()   # it follows you to the new mic
            mw.statusctl._update_status()
            self._prepare_all()
        mw.devctl._device_job(plan, opened)

    def set_route(self, route: str, device: str | None = None, by_hand: bool = False,
                  attached: bool = False, unset: bool = False):
        """Setup -> Your mic -> How your sounds get in: your mic, the virtual cable, another
        device (Voicemeeter, a mixer, a device OBS captures) or nobody (only you, and the
        stream output). `device`: send into that one too (Send to and the setup guide
        pick both at once). Otherwise the picked device is kept, so switching back
        restores it. `by_hand`: picked in the box, so the streams open on the device
        thread (_device_job) and the window never waits on a slow driver. `unset` (the My
        mic switch): on the mic even while the mic effect isn't on it; the card says so
        and offers the set-up, and the cable carries the sounds meanwhile (_main_name)."""
        mw = self.mw
        c = mw.cfg
        if route not in library.ROUTES or (route == c.route and device is None):
            self._show_route()
            return
        # an older copy of the effect ('outdated') still works: picking the mic never
        # asks for admin for it (the update stays optional). `attached`: it was just
        # put on, and Windows may still be loading it; asking again would loop prompts.
        if route == "mic" and not attached and not unset \
                and not directmic.works(directmic.status(c.mic_device)):
            self._show_route()   # not attached yet: the picker stays put until it is
            mw.micctl.attach_mic()
            return
        log.info("send to others through: %s -> %s (%s)", c.route, route,
                 device or c.main_device)
        c.route = route
        mw.micctl._declined = False   # (a No said under the old route is over now)
        if device is not None:
            c.main_device = device
        elif route == "cable" and not is_virtual_cable(c.main_device):
            c.main_device = next(iter(eng.virtual_outputs()), None) or c.main_device
        self._fill_combo(mw.cb_main, [d["name"] for d in eng.list_devices("output")],
                         c.main_device)
        self._show_route()
        mw._save_now()
        if by_hand:
            def opened(ends):
                if ends is not None:
                    mw.micctl._set_cable_bad(ends)
                mw.statusctl._update_status()
                self._prepare_all()

            def plan():   # worked out when its turn comes
                send = self._send_plan(force_main=True)
                return lambda: self._open_send(send)
            mw.devctl._device_job(plan, opened)
            return
        self._apply_send_outputs(force_main=True)
        mw.statusctl._update_status()
        self._prepare_all()

    def _show_switch(self):
        """Your mic's switch says the route. On its way to the mic (asking which mic, or
        setting it up) it says Driver already, and goes back when that doesn't happen (no
        mic, a No, a failure). Other device only shows while it's the route."""
        mw = self.mw
        route = mw.cfg.route
        to_mic = route == "mic" or mw._attaching or self.finding_mic
        mw.seg_device.setVisible(route == "device" and not to_mic)
        (mw.seg_mic if to_mic else mw.seg_off if route == "off"
         else mw.seg_device if route == "device" else mw.seg_cable).setChecked(True)

    def _show_route(self):
        """The Setup tab follows the route: the switch says it, and on the cable or a
        device Send to lists where they can go, when there's more than one place: the
        virtual cables by the end Discord picks, and the device picked by hand."""
        mw = self.mw
        c, cb = mw.cfg, mw.cb_route
        route = c.route
        on_mic = route == "mic" or mw._attaching or self.finding_mic
        self._show_switch()
        cb.blockSignals(True)
        cb.clear()
        names = [d["name"] for d in eng.list_devices("output")]
        ins = [d["name"] for d in eng.list_devices("input")]
        target = c.main_device if route in ("cable", "device") else None
        # only what others can hear you through: a virtual cable, one entry each ("CABLE
        # Input" and "CABLE In 16ch" are the same cable). Speakers and screens aren't
        # (Also play on copies sounds there).
        gone = getattr(mw, "_cable_gone", False)   # (Windows lists it till a restart)
        shown = [target] if target and not on_mic and not gone else []
        for n in [] if gone else names:
            if n not in shown and n != c.mon_device and is_virtual_cable(n) \
                    and not any(eng.same_cable(n, s) for s in shown):
                shown.append(n)
        shown.sort(key=lambda n: names.index(n) if n in names else len(names))
        for n in shown:
            cb.addItem(eng.virtual_mic_for(n, ins) or n, ROUTE_DEVICE + n)
        cb.setCurrentIndex(max(0, cb.findData(ROUTE_DEVICE + (target or ""))))
        cb.view().setMinimumWidth(cb.view().sizeHintForColumn(0) + 32)   # whole names
        cb.blockSignals(False)
        mw.route_pick.setVisible(route in ("cable", "device") and not on_mic and cb.count() > 1)
        for v in list(getattr(mw, "also_views", ())):   # (not built yet at start)
            v.rebuild()
        # Settings' copy of the boxes and its Mic effect card follow at once, not on
        # their next look (the switch is on that page too). Only while it's open: a
        # closed one is built again for the new route when it opens (_settings_print),
        # and a hidden page that changed size moved the rest of the window
        setctl = getattr(mw, "setctl", None)
        if setctl is not None and setctl.settings_open():
            from soundboard.ui.setup.audiorecovery import RecoveryCard   # (it imports this)
            dlg = setctl._settings_dlg
            if getattr(dlg, "dev_combos", None):
                dlg.audio._sync_devices()
            for card in dlg.findChildren(RecoveryCard):
                card._rebuild()
    def use_mic(self):
        """The Your mic card's Driver switch: sounds go into the mic, always (it never
        bounces back to the cable), and never with Windows' admin prompt. A mic Onion
        Board is on already is used as it is (the picker moves to it too); otherwise it's
        the picked mic, or Windows' default one, and the card says the sounds aren't in
        it yet, with its button to set it up. Which mic it's on is read from the registry
        on a thread (_mic_found); the switch says Driver meanwhile."""
        mw = self.mw
        if mw.cfg.route == "mic" or mw._attaching or self.finding_mic:
            self._show_route()
            mw.statusctl._update_flow()
            return
        self.finding_mic = True
        self._find_id += 1
        self._show_route()
        mw.statusctl._update_flow()
        ins = [n for n in (mw.cb_mic.itemData(i) for i in range(mw.cb_mic.count())) if n]
        worker.run(self._mic_with_effect, mw.mic_found, "mic-find", error=(self._find_id, None),
                   owner=mw, args=(self._find_id, ins, mw.cfg.mic_device))

    def use_cable(self):
        """The Your mic card's Virtual cable switch. A Driver click still being looked
        up (use_mic) is dropped. Not installed: the card says so and has its Install
        button; the switch itself never starts an install."""
        mw = self.mw
        self.finding_mic = False
        self._find_id += 1
        if mw.cfg.route == "cable":
            self._show_route()
            mw.statusctl._update_flow()
        elif mw._cable_gone or eng.virtual_outputs():
            mw.micctl.use_cable_instead()
        else:
            self.set_route("cable", by_hand=True)

    def use_nobody(self):
        """The Your mic card's Nobody switch: only you hear your sounds. A Driver click
        still being looked up (use_mic) is dropped."""
        self.finding_mic = False
        self._find_id += 1
        self.set_route("off", by_hand=True)

    @staticmethod
    def _mic_with_effect(find_id: int, ins: list[str],
                         picked: str | None) -> tuple[int, str | None]:
        """(a thread) The mic in `ins` Onion Board is on and working: `picked` if it's
        one, else the first. None when it isn't on any of them."""
        on = [m["pa"] for m in directmic.mics(ins)
              if m["active"] and m["pa"] and directmic.works(m["state"])]
        return find_id, picked if picked in on else next(iter(on), None)

    def _mic_found(self, find_id: int, name: str | None):
        mw = self.mw
        if find_id != self._find_id:   # Virtual cable clicked (or asked again) meanwhile
            return
        self.finding_mic = False
        c = mw.cfg
        if c.route == "mic" or mw._attaching:   # (got there another way meanwhile)
            self._show_route()
            mw.statusctl._update_status()
            return
        ins = [n for n in (mw.cb_mic.itemData(i) for i in range(mw.cb_mic.count())) if n]
        dflt = eng.default_device_name("input")
        mic = name or (c.mic_device if c.mic_device in ins else None) \
            or (dflt if dflt in ins else next(iter(ins), None))
        if mic and mic != c.mic_device:
            mw.cb_mic.setCurrentIndex(mw.cb_mic.findData(mic))
            self.on_device(mw.cb_mic, "mic_device", follow=False)
        # never Windows' admin prompt from the switch: not on the mic yet, the card says
        # so and its "Put my sounds straight into my mic" button sets it up
        self.set_route("mic", by_hand=True, unset=True)
        if name:
            log.info("sending into the mic Onion Board is on already")
            mw.unsay(MIC_FAILED)   # (an old "Couldn't put Onion Board on your mic" is over)

    def _main_name(self) -> str | None:
        """The device that gets what others hear: none when sending nowhere, and
        never the headphones (you'd hear everything twice, your own voice included)."""
        mw = self.mw
        c = mw.cfg
        if c.route == "mic":
            if directmic.works(directmic.status()):
                return directmic.DEVICE
            # not on the mic yet (or Windows took it off): the cable meanwhile, so
            # a voice app set to it still hears you
            cable = self._cable_out()
            return cable if cable != c.mon_device else None
        if c.route == "off" or not c.main_device or c.main_device == c.mon_device:
            return None
        return c.main_device

    def _cable_out(self) -> str | None:
        """The virtual cable's input (what plays into it): the one picked, else the
        first one installed. None once removed (Windows lists it till a restart)."""
        mw = self.mw
        c = mw.cfg
        if getattr(mw, "_cable_gone", False):
            return None
        present = eng.virtual_outputs()
        # the picked one only while it's plugged in: a cable saved in the settings but
        # not installed (any more) was opened anyway, and "device not found: CABLE
        # Input" stood where "not in your mic yet" should have been the only news
        if c.main_device and is_virtual_cable(c.main_device) and c.main_device in present:
            return c.main_device
        return next(iter(present), None)

    def _apply_send_outputs(self, force_main: bool = False):
        """(Re)open what others hear and the stream output for the current devices and
        route. Each is reopened only if its device changed (or `force_main`)."""
        mw = self.mw
        ends = self._open_send(self._send_plan(force_main))
        if ends is not None:
            mw.micctl._set_cable_bad(ends)

    def _send_plan(self, force_main: bool = False) -> dict:
        """What _apply_send_outputs reopens, worked out on the UI thread (it reads the
        config): only what changed."""
        mw = self.mw
        e = mw.engine
        plan = {}
        main = self._main_name()
        if force_main or e.names["main"] != main:
            plan["main"], plan["vm"] = main, eng.virtual_mic_for(main)
        tap = self._tap_name()
        if e.tap_name != tap:
            plan["tap"] = tap
        obs = self._obs_name(mw.cfg.obs_device)   # never the cable or headphones too
        if e.names["obs"] != obs:
            plan["obs"] = obs
        copies = self._copy_names()
        if list(e.copy_names) != copies:
            plan["copies"] = copies
        return plan

    def _open_send(self, plan: dict) -> list | None:
        """_apply_send_outputs' slow part (any thread): open what `plan` says. Returns
        the cable's ends if what others hear was reopened (see _cable_ends), else None."""
        mw = self.mw
        e = mw.engine
        if "main" in plan:
            e.set_main_device(plan["main"])
        if "tap" in plan:
            e.set_tap_device(plan["tap"])
        if "obs" in plan:
            e.set_obs_device(plan["obs"])
        if "copies" in plan:
            e.set_copy_devices(plan["copies"])
        return mw.micctl._cable_ends(plan["main"], plan["vm"]) if "main" in plan else None

    def _copy_names(self) -> list[str]:
        """Setup -> Devices -> Also play on: the devices that get a copy of what others
        hear. None while sending to nobody; never the headphones (you'd hear it twice),
        and never a device that gets it already (what others hear, the cable alongside
        the mic, the stream output, or another end of one of those cables)."""
        mw = self.mw
        c = mw.cfg
        if c.route == "off":
            return []
        taken = self.sending_to()
        out = []
        for n in c.also_send:
            if (isinstance(n, str) and n and n != c.mon_device and n not in out
                    and not any(n == t or eng.same_cable(n, t) for t in taken)):
                out.append(n)
        return out

    def sending_to(self) -> list[str]:
        """The devices that get what others hear already: the picked one, the cable
        alongside the mic, and the stream output ("Also play on" can't add them again)."""
        mw = self.mw
        return [t for t in (self._main_name(), self._tap_name(),
                            self._obs_name(mw.cfg.obs_device)) if t]

    def set_also_send_at(self, i: int, name: str | None):
        """Setup -> Devices -> Also play on: row `i` sends to `name` (one past the last
        row adds one; None removes that row)."""
        mw = self.mw
        c = mw.cfg
        lst = list(c.also_send)
        if name is None:
            if i < len(lst):
                del lst[i]
        elif i < len(lst):
            lst[i] = name
        else:
            lst.append(name)
        c.also_send = list(dict.fromkeys(lst))
        log.info("also send to: %s", c.also_send)
        self._apply_send_outputs()
        self._show_route()
        mw._save_now()
        mw.statusctl._update_status()

    def _tap_name(self) -> str | None:
        """Straight into the mic: the cable gets the same (engine.CableTap), for a voice
        app still set to it. None otherwise, or if the cable is the headphones."""
        mw = self.mw
        if self._main_name() != directmic.DEVICE:
            return None
        tap = self._cable_out()
        return None if tap == mw.cfg.mon_device else tap

    def _obs_name(self, name: str | None) -> str | None:
        """The stream output's device, unless it's what others hear (or another end of
        the same cable: everyone in the call would get everything twice) or the
        headphones (you'd hear it twice). Sending nowhere frees the cable for it."""
        mw = self.mw
        main = self._main_name()
        if (name in (None, main, mw.cfg.mon_device)
                or eng.same_cable(name, main) or eng.same_cable(name, self._tap_name())):
            return None
        return name

    def set_obs_device(self, name: str | None):
        """The stream output: Setup -> Devices -> Also play on -> a row set to Clean,
        for streaming. None switches it off."""
        mw = self.mw
        mw.cfg.obs_device = name
        self._show_route()            # the rows
        mw._save_now()
        e = mw.engine

        def plan():   # the streams are opened on the device thread (_device_job)
            obs = self._obs_name(name)
            copies = self._copy_names()   # (a copy row on it may be free to open again)

            def work():
                e.set_obs_device(obs)
                if list(e.copy_names) != copies:
                    e.set_copy_devices(copies)
            return work

        def opened(_):
            mw.statusctl._update_status()
            self._prepare_all()
        mw.devctl._device_job(plan, opened)

    def set_send_kind(self, name: str, stream: bool):
        """Also play on: the row on `name` gets the clean stream mix (`stream`; the
        one that had it before goes back to a copy of the call, in its place) or the
        same as the call."""
        mw = self.mw
        c = mw.cfg
        lst = list(c.also_send)
        if stream:
            if c.obs_device == name:
                return
            i = lst.index(name) if name in lst else len(lst)
            lst = [n for n in lst if n != name]
            if c.obs_device and c.route != "off":
                lst.insert(i, c.obs_device)
            c.also_send = lst
            log.info("also send to: %s, clean: %s", lst, name)
            self.set_obs_device(name)
        elif c.obs_device == name:
            c.also_send = list(dict.fromkeys([*lst, name]))
            log.info("also send to: %s, clean: none", c.also_send)
            self.set_obs_device(None)

    def _prepare_all(self):
        mw = self.mw
        items = list(mw.audio.items())
        worker.run(lambda: [mw.engine.prepare(s, d) for s, d in items], name="prepare")

    def on_mic_toggle(self, b):
        """Send my mic to others, or sounds only. The mic itself stays open either
        way (the meter, the tests and live voice-to-speech still hear it); this only
        decides whether it's mixed into what others get."""
        mw = self.mw
        mw.set_option("mic_enabled", b)
        mw._sync_mini_mic()
        mw.statusctl._update_status()

    def _mute_does_nothing(self) -> bool:
        """Sending into the mic, but the mic effect isn't on it: voice apps take the real
        mic as it is, so unticking "Others hear it" can't keep your voice from them."""
        mw = self.mw
        return (mw.cfg.route == "mic"
                and not directmic.works(directmic.status(mw.cfg.mic_device)))

    def _warn_mute_does_nothing(self, on: bool):
        """Unticked by a click while that's so: say it, and offer the one-click set-up.
        Not on the hotkey: no pop-up mid-game."""
        mw = self.mw
        if on or mw.cfg.mute_warning_off or not self._mute_does_nothing():
            return
        box = QMessageBox(QMessageBox.Icon.Information, _("This won't mute you yet"),
                          _("Hey! This does nothing yet, because Onion Board isn't set "
                            "up in your mic. People still hear you."),
                          QMessageBox.StandardButton.NoButton, mw)
        box.setIconPixmap(bunny.bunny_pixmap(84, dpr=mw.devicePixelRatioF()))
        box.setInformativeText(_("One click sets it up."))
        setup = box.addButton(_("Set it up"), QMessageBox.ButtonRole.AcceptRole)
        setup.setObjectName("primary")
        ok = box.addButton(_("Not now"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(setup)
        box.setEscapeButton(ok)
        # someone who plays on the cable on purpose met this on every untick
        box.setCheckBox(QCheckBox(_("Don't show this again"), box))   # box owns it
        usage.used("mute-warning-shown")
        box.exec()
        chosen = box.clickedButton() is setup
        if box.checkBox().isChecked():
            mw.set_option("mute_warning_off", True)
        free_dialog(box)
        if chosen:
            usage.used("mute-warning-setup")
            mw.micctl.attach_mic()
