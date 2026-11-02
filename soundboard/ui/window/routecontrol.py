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

ROUTE_CHOICES = ((_("My mic (normal)"), "mic"),
                 (_("Nobody: only I hear them"), "off"))
ROUTE_DEVICE = "device:"


class RouteControl(Controller):
    """The route and send outputs of one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)

    def _fill_combo(self, cb, names, current):
        cb.blockSignals(True)
        cb.clear()
        cb.addItem(_("(none)"), None)
        for n in names:
            cb.addItem(n, n)
        i = cb.findData(current) if current else 0
        cb.setCurrentIndex(i if i >= 0 else 0)
        cb.view().setMinimumWidth(cb.view().sizeHintForColumn(0) + 32)   # whole names
        cb.blockSignals(False)

    def on_device(self, cb, attr):
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
        if attr == "mon_device":
            self._show_route()   # the headphones aren't offered as where sounds go
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
            if attr == "mic_device" and mw.cfg.route == "mic" \
                    and directmic.status(name) == "other":
                mw.micctl.attach_mic()   # it follows you to the new mic
            mw.statusctl._update_status()
            self._prepare_all()
        mw.devctl._device_job(plan, opened)

    def set_route(self, route: str, device: str | None = None, by_hand: bool = False,
                  attached: bool = False):
        """Setup -> Devices -> Send my sounds to: your mic, the virtual cable, another
        device (Voicemeeter, a mixer, a device OBS captures) or nobody (only you, and the
        stream output). `device`: send into that one too (the picker and the setup guide
        pick both at once). Otherwise the picked device is kept, so switching back
        restores it. `by_hand`: picked in the box, so the streams open on the device
        thread (_device_job) and the window never waits on a slow driver."""
        mw = self.mw
        c = mw.cfg
        if route not in library.ROUTES or (route == c.route and device is None):
            self._show_route()
            return
        # an older copy of the effect ('outdated') still works: picking the mic never
        # asks for admin for it (the update stays optional). `attached`: it was just
        # put on, and Windows may still be loading it; asking again would loop prompts.
        if route == "mic" and not attached and not directmic.works(directmic.status(c.mic_device)):
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

    def _show_route(self):
        """The Setup tab follows the route: "Send my sounds to" lists your mic, nobody
        and every output but the headphones, with the current one picked."""
        mw = self.mw
        c, cb = mw.cfg, mw.cb_route
        route = c.route
        cb.blockSignals(True)
        cb.clear()
        for text, key in ROUTE_CHOICES:
            cb.addItem(text, key)
        names = [d["name"] for d in eng.list_devices("output")]
        target = c.main_device if route in ("cable", "device") else None
        if route in ("cable", "device") and target not in names:
            names.append(target)   # unplugged, or no cable yet: still shown as picked
        for n in names:
            if n is None:
                cb.addItem(_("A virtual cable (not installed yet)"), ROUTE_DEVICE)
            elif n != c.mon_device or n == target:
                cb.addItem(n, ROUTE_DEVICE + n)
        key = route if route in ("mic", "off") else ROUTE_DEVICE + (target or "")
        cb.setCurrentIndex(max(0, cb.findData(key)))
        cb.view().setMinimumWidth(cb.view().sizeHintForColumn(0) + 32)   # whole names
        cb.blockSignals(False)
        for v in list(getattr(mw, "also_views", ())):   # (not built yet at start)
            v.rebuild()
        # (not "Your virtual mic": a name for a thing a new user doesn't have yet)
        mw.how_title.setText(_("Send your sounds") if route == "cable" else
                               _("Your mic") if route == "mic" else _("Where your sounds go"))

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
