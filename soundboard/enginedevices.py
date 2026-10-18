"""The engine's devices: opening each output and the mic at its native rate, the
straight-into-my-mic stream and its cable copies, and the watchdog that reopens a
stream that stalled or failed to open (on the device thread, DeviceWorker).

A mixin Engine inherits, so every `self.` lookup is the same as before. Nothing here
runs per audio block: the stream callbacks and what they call stay in engine.py.
`find_device` and `CableTap` are looked up in soundboard.engine when called (tests
swap them there).
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import sounddevice as sd

from soundboard import directmic
from soundboard.core import errors
from soundboard.engineparts import (
    BUFFER, CH, MIC_BUFFER, RETRY_S, SR, STALL_S, DEVICES, StreamResampler, _holding_devices,
    close_quietly, start_or_close,
)
from soundboard.i18n import _

if TYPE_CHECKING:
    import threading
    from typing import Any
    import numpy as np
    from soundboard.engineparts import AuxSource, DeviceWorker, DirectFifo, Ring, Voice

# the engine's logger, as before the move (log lines and filters keep their name)
log = logging.getLogger("soundboard.engine")


class EngineDevices:
    """Opening, watching and reopening the streams (see the module)."""

    if TYPE_CHECKING:   # the engine's own (Engine.__init__, the audio path), used here
        lock: threading.Lock
        voices: tuple[Voice, ...]
        latency: str
        names: dict[str, Any]
        rates: dict[str, int]
        errors: dict[str, str]
        devices: DeviceWorker
        cb_errors: dict[str, int]
        _cb_err_base: dict[str, int]
        _cb_err_seen: dict[str, int]
        _cushioned: bool
        _last_cb: dict[str, float]
        _last_try: dict[str, float]
        _copy_try: dict[str, float]
        _open_warned: set[str]
        _touched_lock: threading.Lock
        aux: tuple[AuxSource, ...]
        direct_mode: Any
        direct_lead_s: float
        fifo_direct: DirectFifo
        ring_main: Ring
        ring_mon: Ring
        ring_obs: Ring
        ring_rmain: Ring
        ring_rmon: Ring
        ring_robs: Ring

        def _cb_main(self, outdata, frames, t, status) -> None: ...
        def _cb_mon(self, outdata, frames, t, status) -> None: ...
        def _cb_obs(self, outdata, frames, t, status) -> None: ...
        def _cb_mic(self, indata, frames, t, status) -> None: ...
        def _direct_voice_delay(self) -> float: ...
        def _check_cushion(self, now: float) -> None: ...
        def direct_stream(self) -> Any: ...
        def _mic_direct(self, x: np.ndarray, rate: int) -> None: ...
        def _mic_direct_stopped(self) -> None: ...
        def _reconfigure_mic_resamplers(self) -> None: ...

    KEYS = ("main", "mon", "mic", "obs")

    _close_quietly = staticmethod(close_quietly)

    # ----------------------------------------------------------------- streams
    @staticmethod
    def _native_rate(idx: int) -> int:
        return int(sd.query_devices(idx)["default_samplerate"])

    def _open_out(self, key, name, callback):
        if key == "main" and name == directmic.DEVICE:
            return self._open_direct(callback)
        idx = _eng.find_device("output", name)
        if idx is None:
            raise RuntimeError(_("device not found: {device}", device=name))
        rate = self._native_rate(idx)
        chans = min(CH, sd.query_devices(idx)["max_output_channels"])
        if chans < CH:
            raise RuntimeError(_("mono output devices aren't supported"))
        s = sd.OutputStream(device=idx, samplerate=rate, channels=CH, dtype="float32",
                            latency=BUFFER.get(self.latency, "low"), callback=callback)
        self._last_cb[key] = time.monotonic()
        start_or_close(s, key)
        # committed only now, so a failed open leaves the rate and the rings alone.
        # Nothing plays on or writes to this output until its *_stream attribute is
        # set, so callbacks that run before this line render silence and do no harm.
        self._stream_opened(key)
        if rate != self.rates[key]:
            self.rates[key] = rate
            self._reconfigure_out(key)
        else:   # same rate: only drop what was queued for the old stream
            self._clear_out(key)
        self._resume_voices(key, rate)
        log.info("opened %s output: %s @ %d Hz (latency %s)", key, name, rate, self.latency)
        return s

    def _open_direct(self, callback):
        """What others hear -> straight into the real mic (soundboard.directmic)."""
        try:
            s = directmic.DirectMicStream(callback, mic_callback=self._mic_direct,
                                          mic_stopped=self._mic_direct_stopped,
                                          mode=self.direct_mode, lead_s=self.direct_lead_s,
                                          voice_delay=self._direct_voice_delay)
        except FileNotFoundError:
            raise RuntimeError(_("Onion Board isn't attached to your mic yet")) from None
        self.fifo_direct.clear()
        self._cushioned = False   # a new stream starts at LEAD_S (check_streams re-cushions)
        self._last_cb["main"] = time.monotonic()
        s.start()
        self._stream_opened("main")
        rate = directmic.RATE
        if rate != self.rates["main"]:
            self.rates["main"] = rate
            self._reconfigure_out("main")
        else:
            self._clear_out("main")
        self._resume_voices("main", rate)
        log.info("opened main output: straight into the mic")
        return s

    def effect_alive(self) -> bool:
        """The mic effect is running: a program is recording the mic it's on."""
        s = self.main_stream
        return isinstance(s, directmic.DirectMicStream) and s.effect_alive()

    @_holding_devices
    def set_tap_device(self, name: str | None):
        """Also play what others hear into `name` (the virtual cable) while it goes
        straight into the mic; None = don't."""
        old, self.tap = self.tap, None
        if old is not None:
            old.close()
        self.tap_name = name
        self._tap_try = time.monotonic()
        if name:
            try:
                self.tap = _eng.CableTap(name, BUFFER.get(self.latency, "low"))
            except Exception as e:  # noqa: BLE001 - the mic still works; retried
                self._open_failed(name, e)
            else:
                self._opened(name)

    @_holding_devices
    def set_copy_devices(self, names):
        """Also play what others hear into each of `names` (Setup -> Devices -> Also play
        on: Voicemeeter, OBS, a second cable...). Ones already open stay open; one that
        won't open is retried by check_streams."""
        names = tuple(dict.fromkeys(n for n in names if n))
        keep = {t.name: t for t in self.copies if t.name in names}
        old, self.copies = self.copies, tuple(keep.values())
        self.copy_names = names
        for t in old:
            if t.name not in keep:
                t.close()
        for n in names:
            if n not in keep:
                self._open_copy(n)

    def _open_copy(self, name: str):
        self._copy_try[name] = time.monotonic()
        try:
            t = _eng.CableTap(name, BUFFER.get(self.latency, "low"))
        except Exception as e:  # noqa: BLE001 - the rest still works; retried
            self._open_failed(name, e)
            return
        self._opened(name)
        self.copies = (*self.copies, t)

    def _open_failed(self, name: str, e: Exception):
        self._warn_open(f"copy:{name}", "can't also send into %s: %s", name, e)

    def _opened(self, name: str):
        self._open_warned.discard(f"copy:{name}")
        log.info("also sending into %s", name)

    def _warn_open(self, tag: str, msg: str, *args):
        """A device that won't open: a warning the first time, then debug lines while
        it's retried every RETRY_S, until it opens (the setter discards `tag`)."""
        if tag in self._open_warned:
            log.debug("still: " + msg, *args)
        else:
            self._open_warned.add(tag)
            log.warning(msg + " (trying again every %.0f s)", *args, RETRY_S)

    def copies_down(self) -> list[str]:
        """The "Also play on" devices that aren't open (unplugged, or busy)."""
        up = {t.name for t in self.copies}
        return [n for n in self.copy_names if n not in up]

    def _copies_due(self, now: float) -> bool:
        return (any(now - t.last_cb > STALL_S for t in self.copies)
                or any(now - self._copy_try.get(n, 0.0) >= RETRY_S for n in self.copies_down()))

    @_holding_devices
    def _check_copies(self, now: float):
        """The "Also play on" copies' watchdog (see check_streams)."""
        for t in self.copies:
            if now - t.last_cb > STALL_S:
                log.warning("copy to %s stalled; reopening", t.name)
                self.copies = tuple(c for c in self.copies if c is not t)
                t.close()
                self._open_copy(t.name)
        for n in self.copies_down():
            if now - self._copy_try.get(n, 0.0) >= RETRY_S:
                self._open_copy(n)

    def _tap_due(self, now: float) -> bool:
        tap = self.tap
        if not self.tap_name:
            return False
        if tap is None:
            return now - self._tap_try >= RETRY_S
        return now - tap.last_cb > STALL_S

    @_holding_devices
    def _check_tap(self, now: float):
        """The cable tap's own watchdog (see check_streams)."""
        if not self._tap_due(now):
            return
        if self.tap is not None:
            log.warning("cable tap stalled; reopening %s", self.tap_name)
        self.set_tap_device(self.tap_name)

    def direct_apps(self) -> int:
        """Apps whose mic stream carries the board right now (its own one too)."""
        s = self.direct_stream()
        return s.apps() if s is not None else 0

    def direct_mic_silent_s(self) -> float:
        """How long the mic has sent nothing but exact zeros into the mic effect (see
        DirectMicStream.mic_silent_s); 0 when it hasn't, or nothing to tell."""
        s = self.direct_stream()
        return s.mic_silent_s() if s is not None else 0.0

    def _resume_voices(self, key: str, rate: int):
        """Output `key` was reopened: sounds still playing on another output pick
        up here again, at the same spot (with a short fade in); sounds this output
        was cut from while every output was closed (a device rescan) pick up where
        they were cut. Data made for another rate is useless, so those stay done."""
        with self.lock:
            for v in self.voices:
                if key not in v.done or v.stopping or not len(v.data.get(key, ())):
                    continue
                if v.rates.get(key) != rate:
                    v.cut.discard(key)   # can't resume here: let it finish
                    continue
                other = next((o for o in v.data if o != key and o not in v.done
                              and len(v.data[o])), None)
                if other is None:
                    if key not in v.cut:
                        continue
                    other = key   # nothing else playing it: its own spot
                d = v.data[other]
                frac = v.seek_to.get(other)
                if frac is None:
                    frac = (v.pos[other] % len(d)) / len(d)
                v.cut.discard(key)
                v.seek_to.pop(key, None)
                v.pos[key] = int(frac * len(v.data[key]))
                v.gate[key] = 0.0
                v.fading.discard(key)
                v.done.discard(key)   # last: the callback may render it from here on

    def _stream_opened(self, key):
        # callback errors are counted per stream from here: the first failure on the
        # new stream is logged and reported again (cb_errors stays a running total)
        self._cb_err_base[key] = self.cb_errors[key]

    @_holding_devices
    def set_main_device(self, name: str | None):
        self._close("main_stream")
        self.errors.pop("main", None)
        self.names["main"] = name
        self.main_direct = name == directmic.DEVICE
        self._last_try["main"] = time.monotonic()
        if name:
            try:
                self.main_stream = self._open_out("main", name, self._cb_main)
            except Exception as e:  # noqa: BLE001
                self._warn_open(f"main:{name}", "can't open main output %r: %s", name, e)
                self.errors["main"] = errors.plain(e)
            else:
                self._open_warned.discard(f"main:{name}")

    @_holding_devices
    def set_mon_device(self, name: str | None):
        self._close("mon_stream")
        self.errors.pop("mon", None)
        self.names["mon"] = name
        self._last_try["mon"] = time.monotonic()
        if name:
            try:
                self.mon_stream = self._open_out("mon", name, self._cb_mon)
            except Exception as e:  # noqa: BLE001
                self._warn_open(f"mon:{name}", "can't open headphone output %r: %s", name, e)
                self.errors["mon"] = errors.plain(e)
            else:
                self._open_warned.discard(f"mon:{name}")

    @_holding_devices
    def set_obs_device(self, name: str | None):
        """The stream output: a device OBS captures (None = off)."""
        self._close("obs_stream")
        self.errors.pop("obs", None)
        self.names["obs"] = name
        self._last_try["obs"] = time.monotonic()
        if name:
            try:
                self.obs_stream = self._open_out("obs", name, self._cb_obs)
            except Exception as e:  # noqa: BLE001
                self._warn_open(f"obs:{name}", "can't open stream output %r: %s", name, e)
                self.errors["obs"] = errors.plain(e)
            else:
                self._open_warned.discard(f"obs:{name}")

    @_holding_devices
    def set_mic_device(self, name: str | None):
        self._close("mic_stream")
        self.errors.pop("mic", None)
        self.names["mic"] = name
        self._last_try["mic"] = time.monotonic()
        if name:
            idx = _eng.find_device("input", name)
            old_rate = self.rates["mic"]
            s = None
            try:
                if idx is None:
                    raise RuntimeError(_("device not found: {device}", device=name))
                rate = self._native_rate(idx)
                chans = min(2, sd.query_devices(idx)["max_input_channels"])
                s = sd.InputStream(device=idx, samplerate=rate, channels=chans, dtype="float32",
                                   latency=MIC_BUFFER.get(self.latency, "low"),
                                   callback=self._cb_mic)
                # the mic callback resamples with these from its first block, so they're
                # set before start (cheap: no ring is touched) and undone if it fails
                if rate != old_rate:
                    self.rates["mic"] = rate
                    self._reconfigure_mic_resamplers()
                self._last_cb["mic"] = time.monotonic()
                s.start()
                self._stream_opened("mic")
                self.mic_stream = s
                self._mic_dev_rate = rate
                self._open_warned.discard(f"mic:{name}")
                log.info("opened mic: %s @ %d Hz, %d ch", name, rate, chans)
            except Exception as e:  # noqa: BLE001
                self._warn_open(f"mic:{name}", "can't open mic %r: %s", name, e)
                self.errors["mic"] = errors.plain(e)
                if s is not None:
                    self._close_quietly(s, "mic")
                if self.rates["mic"] != old_rate:
                    self.rates["mic"] = old_rate
                    self._reconfigure_mic_resamplers()

    @_holding_devices
    def reopen_all(self):
        """Close and reopen every stream with the same devices (after a latency change)."""
        self.set_mic_device(self.names["mic"])
        self.set_main_device(self.names["main"])
        self.set_tap_device(self.tap_name)
        copies = self.copy_names
        self.set_copy_devices(())
        self.set_copy_devices(copies)
        self.set_mon_device(self.names["mon"])
        self.set_obs_device(self.names["obs"])

    def _key_due(self, key: str, now: float) -> str | None:
        """'retry' (didn't open, and RETRY_S is up), 'stall' (its callback stopped) or
        None, for stream `key`."""
        if not self.names[key]:
            return None
        if getattr(self, f"{key}_stream") is None:
            return "retry" if now - self._last_try[key] >= RETRY_S else None
        return "stall" if now - self._last_cb[key] > STALL_S else None

    def check_streams(self) -> list[str]:
        """Watchdog (call about once a second from the UI thread).

        A stream whose callback has stopped being called (headset unplugged, Windows
        changed its sample rate, PC came back from sleep) is closed and reopened. A
        device that failed to open is retried every RETRY_S. Both happen on the device
        thread (self.devices: closing a dead device's stream or opening a missing one
        can take the driver seconds), one check at a time. Returns the keys that were
        touched (reopened or came back since the last check, or whose callback raised),
        so the UI can refresh its status from errors_snapshot()."""
        if self._shut:
            return []
        now = time.monotonic()
        self._check_cushion(now)
        with self._touched_lock:
            touched, self._touched = self._touched, []
        for key in self.KEYS:
            n_err = self.cb_errors[key]
            if n_err != self._cb_err_seen[key]:
                self._cb_err_seen[key] = n_err
                touched.append(key)
        due = (self._tap_due(now) or self._copies_due(now)
               or any(self._key_due(k, now) for k in self.KEYS))
        if due and self.devices.claim():
            self.devices.run(lambda: self._watch(time.monotonic()), self._watched)
        return list(dict.fromkeys(touched))

    def _watched(self, keys: list[str] | None):
        with self._touched_lock:
            self._touched += keys or []
        self.devices.release()

    @_holding_devices
    def _watch(self, now: float) -> list[str]:
        """check_streams' reopens, on the device thread. Returns the keys touched."""
        if self._shut:   # queued before shutdown() closed everything
            return []
        touched = []
        self._check_tap(now)
        self._check_copies(now)
        for key in self.KEYS:
            why = self._key_due(key, now)
            if why is None:
                continue
            name = self.names[key]
            setter = getattr(self, f"set_{key}_device")
            if why == "stall":
                log.warning("%s stream stalled (%.1fs without a callback); reopening %s",
                            key, now - self._last_cb[key], name)
                self.stalls += 1
                setter(name)
                touched.append(key)
            else:
                setter(name)
                if key not in self.errors:
                    log.info("%s device came back: %s", key, name)
                    touched.append(key)
        return touched

    def errors_snapshot(self) -> dict[str, str]:
        """A copy of `errors` that is safe to iterate. A failing audio callback adds
        to `errors` from its own thread, so iterating the live dict on the UI thread
        can raise "dictionary changed size during iteration". Copying a str-keyed
        dict never releases the GIL, so the copy itself can't be torn."""
        return dict(self.errors)

    def _reconfigure_out(self, key: str):
        """Rebuild what feeds output `key` for its (new) rate. Only that output's
        rings are reset: the other output plays on without a gap."""
        r = self.rates
        if key == "main":
            self._rs_main = StreamResampler(r["mic"], r["main"])
            self._rs_rmain = StreamResampler(SR, r["main"])
            rings = (self.ring_main, self.ring_rmain)
        elif key == "obs":
            self._rs_obs = StreamResampler(r["mic"], r["obs"])
            self._rs_robs = StreamResampler(SR, r["obs"])
            rings = (self.ring_obs, self.ring_robs)
        else:
            self._rs_mon = StreamResampler(r["mic"], r["mon"])
            self._rs_rmon = StreamResampler(SR, r["mon"])
            rings = (self.ring_mon, self.ring_rmon)
        for ring in rings:
            ring.configure(r[key])
        for a in self.aux:
            a.configure(r, (key,))

    def _clear_out(self, key: str):
        """Drop everything queued for output `key` (its stream was reopened)."""
        if key == "main":
            rings = [self.ring_main, self.ring_rmain]
            rings += [a.ring_main for a in self.aux]
        elif key == "obs":
            rings = [self.ring_obs, self.ring_robs]
            rings += [a.ring_obs for a in self.aux]
        else:
            rings = [self.ring_mon, self.ring_rmon]
            rings += [a.ring_mon for a in self.aux]
        for ring in rings:
            ring.clear()

    def _reconfigure_mic_paths(self):
        """Everything, for the current rates (resets both outputs' rings)."""
        self._reconfigure_mic_resamplers()
        self._reconfigure_out("main")
        self._reconfigure_out("mon")
        self._reconfigure_out("obs")

    def _close(self, attr):
        s = getattr(self, attr)
        setattr(self, attr, None)
        out = {"main_stream": "main", "mon_stream": "mon", "obs_stream": "obs"}.get(attr)
        if out:  # voices can't finish on a device that's gone
            with self.lock:
                for v in self.voices:
                    if out in v.data and out not in v.done:
                        v.cut.add(out)
                        v.cut_at = time.monotonic()
                    v.done.add(out)
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:  # noqa: BLE001
                log.debug("closing %s raised", attr, exc_info=True)

    def shutdown(self, wait_s: float = 5.0):
        """Quitting: close every stream, and the watchdog never reopens one again. Waits
        up to `wait_s` for the device thread's work (quitting mustn't hang on a driver
        that never answers)."""
        self._shut = True
        self.close_streams(wait_s)

    def close_streams(self, wait_s: float = 5.0):
        """Close every stream, for a re-scan that opens them again: unlike shutdown(),
        the watchdog keeps watching them (a re-scan used to switch it off for good, so
        a device pulled out after one was never noticed or brought back)."""
        held = DEVICES.acquire(timeout=wait_s)
        if not held:
            log.warning("the device thread is stuck; closing the streams anyway")
        try:
            for a in ("mic_stream", "main_stream", "mon_stream", "obs_stream"):
                self._close(a)
            # what set_tap_device(None) and set_copy_devices(()) do, without their wait
            taps = (self.tap, *self.copies)
            self.tap, self.tap_name, self.copies, self.copy_names = None, None, (), ()
            for t in taps:
                if t is not None:
                    t.close()
        finally:
            if held:
                DEVICES.release()

    def active_outputs(self) -> set:
        outs = set()
        if self.main_stream is not None:
            outs.add("main")
        if self.mon_stream is not None:
            outs.add("mon")
        if self.obs_stream is not None:
            outs.add("obs")
        return outs


# last, so either module can be imported first: engine imports this one for the
# mixin, this one only needs engine's names when a method runs
from soundboard import engine as _eng  # noqa: E402
