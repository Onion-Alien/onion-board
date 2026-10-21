"""The audio devices of the main window: opening them (on a worker, one job at a time), a
rescan when they change or on request, the latency, and following Windows' default output
when it changes; getting them back when one goes away.

MainWindow makes one ``DeviceControl`` (``MainWindow.devctl``); everything here runs on the
UI thread except the device jobs it hands to its worker."""
from __future__ import annotations

import html
import logging
import sys
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer

from soundboard.audio import appaudio
from soundboard.ui.kit import theme
from soundboard.mic import directmic
from soundboard.audio import engine as eng
from soundboard.audio.engine import is_virtual as is_virtual_cable
from soundboard.audio.engineparts import LITE_BLOCK_S
from soundboard.i18n import _, ngettext
from soundboard.core.pollthread import PollThread
from soundboard.ui.kit import busy
from soundboard.ui.window.controller import Controller

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

log = logging.getLogger(__name__)

DEFAULT_POLL_IDLE_S = 5  # ...while the window is in the tray or minimised (seconds)
# a device that won't open while Windows lists it: re-scan, then wait this long
# (seconds) before the next re-scan, so one that really won't open isn't re-scanned
# over and over (each re-scan reopens every stream)
RECOVER_WAIT_S = (20, 40, 80, 160, 300)
# ...and one Windows doesn't list (unplugged): looked for at the timer's pace for a
# few checks (a quick re-plug), then only this often (seconds)
GONE_CHECKS, GONE_WAIT_S = 4, 6


def _listed(name: str, names) -> bool:
    """`name` (as the app saved it) is one of `names` (Windows' own), spacing aside."""
    squash = " ".join(name.split()).lower()
    return any(" ".join(n.split()).lower() == squash for n in names)


class DeviceControl(Controller):
    """The audio devices of one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        # (PySide takes properties and signals as keywords; the stubs don't know)
        self._dev_retry = QTimer(mw, singleShot=True, interval=100, timeout=self._dev_pump)   # pyright: ignore[reportCallIssue]
        self._recover_n, self._recover_at = 0, 0.0   # see _recover_devices
        self._default_at = 0.0   # when Windows' default was last looked at (_default_tick)
        self._default_asking = False   # ...and a thread is asking it now
        self._default_poll = PollThread("default-output")
        self._dev_waiting: list = []   # device changes waiting their turn (_when_devices_free)
        self._gone_n = 0   # checks in a row that found the failing device unplugged

    def refresh_devices(self) -> str:
        """Re-scan the sound devices and reopen the streams. Returns a short result
        for the button that asked ("✓ Found 7 devices", "No cable yet", …).
        Runs on the UI thread: the app's own recoveries use _refresh_off_ui."""
        mw = self.mw
        mw.engine.close_streams()
        rescanned = eng.rescan()
        mw._vb_setup = None     # installed or removed since: look again
        self._init_devices()
        return self._rescanned(rescanned)

    def _off_ui(self, work, then):
        """work() on the engine's device thread, then then(its result) back on the UI
        thread. The caller holds the device thread's claim (engine.devices.claim())."""
        mw = self.mw
        def done(result):
            def step():
                try:
                    then(result)
                except Exception:
                    mw.engine.devices.release()   # the next recovery can still run
                    raise
            try:
                mw.device_step.emit(step)
            except RuntimeError:   # the window is gone (quitting)
                mw.engine.devices.release()
        mw.engine.devices.run(work, done)

    def _refresh_off_ui(self, then=None, quiet: bool = False):
        """refresh_devices without the slow part on the UI thread: closing every
        stream, the re-scan, opening them again and the cable's format (asked of
        Windows) run on the device thread. The caller holds its claim; it's released
        when this is done, then then() runs. quiet: a re-scan nobody asked for (a
        headset plugged in or pulled out) doesn't say the cable is still missing."""
        mw = self.mw
        e = mw.engine

        def scanned(rescanned):
            if rescanned is None:   # it raised (logged): leave the streams to the watchdog
                rescanned = False
            self._pick_devices()
            plan = self._device_plan()
            self._off_ui(lambda: self._open_devices(plan), lambda ends: opened(ends, rescanned))

        def opened(ends, rescanned):
            self._devices_opened(ends or [])
            msg = self._rescanned(rescanned, quiet)
            e.devices.release()
            if then is not None:
                then(msg)

        self._off_ui(lambda: (e.close_streams(), eng.rescan())[1], scanned)

    def _when_devices_free(self, start):
        """start() on the UI thread once it holds the device thread's claim: a
        recovery (or an earlier click) still running there finishes first, and clicks
        take their turns in order. start() hands the claim on to its _off_ui steps,
        and the last of them releases it."""
        self._dev_waiting.append(start)
        self._dev_pump()

    def _dev_pump(self):
        mw = self.mw
        if not self._dev_waiting or getattr(mw, "_shut_down", False):
            return
        if not mw.engine.devices.claim():
            self._dev_retry.start()   # busy: look again in a moment
            return
        start = self._dev_waiting.pop(0)
        try:
            start()
        except Exception:
            mw.engine.devices.release()
            raise
        finally:
            if self._dev_waiting:
                self._dev_retry.start()

    def _device_job(self, plan, then=None):
        """A device change asked for by hand, without the UI thread waiting on a slow
        driver (one stuck after a headset was pulled can take seconds, or hang): once
        the device thread is free, plan() on the UI thread returns the work, work() opens
        and closes streams on the device thread, then then(its result) back here."""
        mw = self.mw
        e = mw.engine

        def start():
            work = plan()

            def guarded():
                with eng.DEVICES:   # not after the app quit meanwhile
                    return None if getattr(mw, "_shut_down", False) else work()

            def finish(result):
                e.devices.release()
                if then is not None and not getattr(mw, "_shut_down", False):
                    then(result)
            self._off_ui(guarded, finish)
        self._when_devices_free(start)

    def _rescanned(self, rescanned: bool, quiet: bool = False) -> str:
        """After a re-scan: the sounds are prepared for the new rates, and the result."""
        mw = self.mw
        mw.routectl._prepare_all()
        outs = eng.list_devices("output")
        if not rescanned:   # after _init_devices, whose status update would hide it
            mw.say(_("<span style='color:{status}'>Couldn't re-scan devices, "
                       "restart the app to pick up new ones.</span>",
                       status=theme.status('warn')), "warn")
            return _("Couldn't re-scan")
        if mw.cfg.route == "cable" and not any(is_virtual_cable(d["name"]) for d in outs):
            if quiet:
                return _("No cable found yet")
            mw.say(_("<span style='color:{status}'>Still no virtual cable. If you "
                       "just installed it, restart your PC, Windows often only shows "
                       "it after a restart.</span>", status=theme.status('warn')), "warn")
            return _("No cable found yet")
        n = len({d["name"] for d in outs} | {d["name"] for d in eng.list_devices("input")})
        return ngettext("✓ Found {n} device", "✓ Found {n} devices", n)

    def rescan_with_feedback(self, btn, after=None):
        """A Re-scan button: "Scanning…" while it runs (on the device thread: the
        window stays usable even if a driver is stuck), then what it found."""
        mw = self.mw
        if busy.is_busy(btn) or time.monotonic() < (btn.property("scanned_until") or 0):
            # already scanning, or still showing what it found: a re-scan closes and
            # reopens every device, so spam clicks restarted them all over and over
            return
        release = busy.hold(btn, _("Scanning…"))

        def done(msg):
            if after:
                try:
                    after()
                except RuntimeError:   # its dialog was closed while it scanned
                    pass
            try:
                btn.setProperty("scanned_until", time.monotonic() + mw.RESCAN_SHOWN_S)
            except RuntimeError:   # (its dialog was closed)
                pass
            release(msg, int(mw.RESCAN_SHOWN_S * 1000))
        self._when_devices_free(lambda: self._refresh_off_ui(done))

    def set_latency(self, mode: str):
        """'low' (default) or 'high' (bigger buffers: more delay, fewer drop-outs)."""
        mw = self.mw
        if mode not in ("low", "high") or mode == mw.cfg.latency:
            return
        mw.cfg.latency = mode
        mw.engine.latency = mode
        mw._save_now()
        e = mw.engine

        def reopened(_):
            mw.statusctl._update_status()
            self._say_back_on_mic()
        self._device_job(lambda: e.reopen_all, reopened)   # (on the device thread)

    def set_lite_block(self, on: bool):
        """Lite mode's bigger audio block (engineparts.LITE_BLOCK_S) on or off: every
        stream reopens with it, as after an audio buffering change."""
        e = self.mw.engine
        seconds = LITE_BLOCK_S if on else 0.0
        if seconds == e.block_s:
            return

        def plan():
            def work():
                e.set_block(seconds)
                e.reopen_all()
            return work
        self._device_job(plan, lambda _: self.mw.statusctl._update_status())

    def _say_back_on_mic(self):
        """After a restart or an audio buffering change: tell them the board is on the
        mic again (the only other sign is the status strip)."""
        mw = self.mw
        if mw.cfg.route == "mic" and directmic.works(directmic.status()):
            mw.toast(_("Your sounds are back on your mic."), "ok")

    def _init_devices(self):
        self._pick_devices()
        self._devices_opened(self._open_devices(self._device_plan()))

    def _reopen_devices(self):
        """_init_devices for a click (the setup guide closing): the boxes now, the
        streams on the device thread (_device_job), so the window never waits on them."""
        self._pick_devices()

        def plan():   # the config as it is when its turn comes
            devices = self._device_plan()
            return lambda: self._open_devices(devices)
        self._device_job(plan, lambda ends: self._devices_opened(ends or []))

    def _pick_devices(self):
        """_init_devices' quick part (UI thread): the devices to use, from the lists."""
        mw = self.mw
        outs = [d["name"] for d in eng.list_devices("output")]
        # a virtual cable as the *mic* would record our own output and feed it back
        # into itself (a loud feedback screech), so cables never appear here
        ins = [d["name"] for d in eng.list_devices("input") if not is_virtual_cable(d["name"])]
        c = mw.cfg
        if c.mic_device and is_virtual_cable(c.mic_device):
            c.mic_device = None   # was set to the cable: fall back to the real mic
        # only the cable route picks the cable for you: another device stays the one
        # picked by hand, even while it's unplugged (it's retried until it's back)
        if c.route == "cable" and (not c.main_device
                                   or eng.find_device("output", c.main_device) is None):
            c.main_device = next(iter(eng.virtual_outputs()), None) or c.main_device
        if c.mon_follows_default:   # Windows' default now, not when PortAudio started
            c.mon_device = self._default_output() or c.mon_device
        if not c.mon_device:
            dflt = eng.default_device_name("output")
            c.mon_device = dflt if dflt and not is_virtual_cable(dflt) else \
                next((n for n in outs if not is_virtual_cable(n)), None)
        if not c.mic_device:
            dflt = eng.default_device_name("input")
            c.mic_device = dflt if dflt and not is_virtual_cable(dflt) else \
                next(iter(ins), None)
        mw.routectl._fill_combo(mw.cb_main, outs, c.main_device)
        mw.routectl._fill_combo(mw.cb_mon, outs, c.mon_device)
        mw.routectl._fill_combo(mw.cb_mic, ins, c.mic_device)
        mw.routectl._show_route()

        e = mw.engine
        e.sound_vol, e.mic_vol, e.mon_vol = c.sound_vol, c.mic_vol, c.mon_vol
        e.mic_enabled, e.monitor_sounds = c.mic_enabled, c.monitor_sounds
        e.obs_vol, e.obs_voice = c.obs_vol, c.obs_voice

    def _device_plan(self) -> dict:
        """What _open_devices opens, worked out on the UI thread (it reads the config)."""
        mw = self.mw
        c = mw.cfg
        main = mw.routectl._main_name()
        return {"mic": c.mic_device, "main": main, "tap": mw.routectl._tap_name(),
                "mon": c.mon_device, "obs": mw.routectl._obs_name(c.obs_device),
                "copies": mw.routectl._copy_names(), "vm": eng.virtual_mic_for(main)}

    def _open_devices(self, plan: dict) -> list:
        """_init_devices' slow part (any thread; the app's recoveries run it on the
        device thread): open the streams and ask Windows for the cable's format.
        Returns the ends of the cable in use (cableformat.CableEnd)."""
        mw = self.mw
        e = mw.engine
        with eng.DEVICES:   # all of them, or none if the app quit meanwhile
            if getattr(mw, "_shut_down", False):   # (not set yet while starting)
                return []
            e.set_mic_device(plan["mic"])
            e.set_main_device(plan["main"])
            e.set_tap_device(plan["tap"])
            e.set_mon_device(plan["mon"])
            e.set_obs_device(plan["obs"])
            e.set_copy_devices(plan["copies"])
        return mw.micctl._cable_ends(plan["main"], plan["vm"])

    def _devices_opened(self, ends: list):
        """_init_devices' last part (UI thread): what the cable check found, the status."""
        mw = self.mw
        mw.micctl._set_cable_bad(ends)
        mw.statusctl._update_status()
        if "--restart-after" in sys.argv:   # started again by the app (Settings > Reset)
            self._say_back_on_mic()

    def _default_output(self) -> str | None:
        """Windows' default output as the device lists name it (None: unknown, or the
        cable, which is never the headphones)."""
        mw = self.mw
        idx = eng.find_device("output", mw._default_out)
        name = eng.list_name(idx) if idx is not None else None
        return None if name is None or is_virtual_cable(name) else name

    def _recover_devices(self):
        """A device the app uses won't open, but Windows lists it: PortAudio's device
        list is out of date (it was plugged in after the last scan, or its format was
        changed in Windows' sound settings), and the engine's retries can't fix that.
        Re-scan, waiting longer each time it doesn't help (RECOVER_WAIT_S)."""
        mw = self.mw
        e = mw.engine
        failing: list[tuple[str, str]] = [
            (k, name) for k in ("main", "mon", "mic", "obs")
            if (name := e.names.get(k)) and getattr(e, f"{k}_stream") is None
            and k in e.errors_snapshot()]
        if not failing:
            self._recover_n = self._gone_n = 0
            return
        if time.monotonic() < self._recover_at or not e.devices.claim():
            return   # waiting, or the device thread is busy: the next check looks again

        def ask():   # Windows' device lists (COM): on the device thread
            listed: dict[str, set[str] | None] = {}
            for key, name in failing:
                kind = "input" if key == "mic" else "output"
                if kind not in listed:
                    listed[kind] = appaudio.endpoint_names(kind)
                if _listed(name, listed[kind] or ()):
                    return key, name
            return None

        self._off_ui(ask, self._recover_found)

    def _recover_found(self, found: tuple[str, str] | None):
        """_recover_devices' answer from Windows (UI thread, holding the device thread)."""
        mw = self.mw
        now = time.monotonic()
        if found is None:
            # really gone (unplugged): the engine's retries pick it up again. Asking
            # Windows for its device list every check while it stays unplugged is
            # wasted work, so after a few checks look less often
            self._gone_n += 1
            if self._gone_n >= GONE_CHECKS:
                self._recover_at = now + GONE_WAIT_S
            mw.engine.devices.release()
            return
        key, name = found
        self._gone_n = 0
        self._recover_at = now + RECOVER_WAIT_S[min(self._recover_n, len(RECOVER_WAIT_S) - 1)]
        self._recover_n += 1
        log.info("%s device %r is listed by Windows but won't open: re-scanning", key, name)
        self._refresh_off_ui()

    def _default_tick(self):
        """The timer's look at Windows' default output (a COM call): only while the
        headphones follow it, as nothing else uses the answer (picking a device by hand
        looks again), and every few seconds rather than constantly while the window is
        in the tray or minimised. Asked on a thread (it took ~5 ms of the UI thread every
        1.5 s); the answer comes back through default_found."""
        mw = self.mw
        if not mw.cfg.mon_follows_default or self._default_asking:
            return
        now = time.monotonic()
        if not mw._ui_live and now - self._default_at < DEFAULT_POLL_IDLE_S:
            return
        self._default_at = now
        self._default_asking = True
        self._default_poll.run(self._ask_default)

    def _ask_default(self):
        mw = self.mw
        try:
            name = appaudio.default_output_name()
        except Exception:  # noqa: BLE001 - never let the poll's thread die loudly
            log.debug("asking for Windows' default output failed", exc_info=True)
            name = None
        busy.emit(mw.default_found, name)

    def _on_default_found(self, name):
        mw = self.mw
        self._default_asking = False
        if mw.cfg.mon_follows_default:   # not picked by hand meanwhile
            self._follow_default_output(name)

    def _follow_default_output(self, *found: str | None):
        """Windows' default output changed (headphones → speakers): the headphones
        output moves with it, unless another device was picked for it by hand.
        `found`: its name, already asked (on a thread); asked now if not given."""
        mw = self.mw
        now = found[0] if found else appaudio.default_output_name()
        if not now or now == mw._default_out:
            return
        was, mw._default_out = mw._default_out, now
        c = mw.cfg
        if not c.mon_follows_default:
            return
        name = self._default_output()
        if name is None and not is_virtual_cable(now):
            # plugged in since the app started: not listed yet. Re-scanned on the device
            # thread; if it's busy, the next poll sees the change again
            if not mw.engine.devices.claim():
                mw._default_out = was
                return
            self._refresh_off_ui(lambda _msg: self._use_default_output(self._default_output()),
                                 quiet=True)
            return
        self._use_default_output(name)
        self._drop_if_gone(was)

    def _drop_if_gone(self, was: str | None):
        """Windows' default moved off `was`. If it was pulled out (a headset unplugged),
        PortAudio's list, from the last scan, still has it, so the device boxes offered
        a device that's gone. Windows is asked on the device thread; a re-scan drops it."""
        if not was or eng.find_device("output", was) is None:
            return

        def start():
            def gone():
                have = appaudio.endpoint_names("output")
                return have is not None and not _listed(was, have)

            def checked(stale):
                if stale:
                    log.info("output %r was pulled out: re-scanning", was)
                    self._refresh_off_ui(quiet=True)
                else:
                    self.mw.engine.devices.release()
            self._off_ui(gone, checked)
        self._when_devices_free(start)

    def _use_default_output(self, name: str | None):
        """The headphones move to Windows' default output, `name` (as listed)."""
        mw = self.mw
        c = mw.cfg
        if name is None or name == c.mon_device or not c.mon_follows_default:
            return
        log.info("Windows' default output changed: headphones %r -> %r", c.mon_device, name)
        c.mon_device = name
        mw.routectl._fill_combo(mw.cb_mon, [d["name"] for d in eng.list_devices("output")], name)
        mw._save_now()
        e = mw.engine

        def plan():   # the streams are opened on the device thread (_device_job)
            mon, send = c.mon_device, mw.routectl._send_plan()   # where it ended up by then

            def work():
                e.set_mon_device(mon)
                return mw.routectl._open_send(send)
            return work

        def opened(ends):
            if ends is not None:
                mw.micctl._set_cable_bad(ends)
            mw.statusctl._update_status()
            mw.toast(_("You hear your sounds on {name} now: it's Windows' default output.",
                         name=html.escape(name)), "ok")
        self._device_job(plan, opened)
