"""The sound devices PortAudio lists: finding one by its saved name, which are
virtual cables (and each one's mic side), opening an output at its native rate,
and CableTap, the copy of what others hear played into the cable.

Part of soundboard.audio.engine, which re-exports all of it (tests swap these
names there, and a swap reaches the code here).
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any

import numpy as np
import sounddevice as sd

from soundboard.i18n import _
from soundboard.audio.engineparts import SR, CH, DEVICES, start_or_close, Ring, StreamResampler

log = logging.getLogger("soundboard.audio.engine")


# --------------------------------------------------------------------------- devices

_seen: dict = {}   # the last answers of list_devices / default_device_name


def _wasapi_index() -> int | None:
    for i, api in enumerate(sd.query_hostapis()):
        if "WASAPI" in api["name"]:
            return i
    return None


def rescan() -> bool:
    """Re-enumerate devices (picks up newly plugged ones). Kills open streams — reopen after.

    sounddevice has no public API for this; _terminate/_initialize are what its own
    tests use. If a future version drops them, the app keeps its current device list."""
    with DEVICES:
        try:
            sd._terminate()
            sd._initialize()
            return True
        except Exception:  # noqa: BLE001
            log.exception("device rescan failed")
            try:
                sd._initialize()
            except Exception:  # noqa: BLE001
                pass
            return False


ASK_WAIT_S = 0.25  # how long a caller waits for PortAudio before using the last answer
SLOW_S = 5.0       # after a late answer: how long callers use the last one at once


class _Asker:
    """The one thread that asks PortAudio for its devices. Its answers are usually
    instant, but while a driver is slow or a device is being added or removed one can
    take minutes, and the device lists are read on the UI thread: the window froze
    with it (freeze reports in list_devices, `query_devices` / `query_hostapis`).
    Now a caller waits at most ASK_WAIT_S and then uses the last answer (_seen); the
    late answer still lands in _seen. While a question is unanswered the next ones
    use _seen at once, so nothing piles up behind a stuck driver. The thread stays
    for good once started (starting one waits for it to run, see DeviceWorker)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._q: queue.SimpleQueue = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._open: threading.Event | None = None   # the question being answered
        # PortAudio slow but answering (a busy or paging PC): each new question waited
        # ASK_WAIT_S again, and a check asking a few times in a row held the window
        # for 10-30 s (freeze reports at ask()'s wait). After one late answer, callers
        # don't wait for SLOW_S: the question still goes out and lands in _seen.
        self._slow_until = 0.0

    def ask(self, fn) -> tuple[bool, Any]:
        """(True, fn()'s result), or (False, None) when PortAudio hasn't answered in
        time. fn's exception is raised here."""
        if self._thread is not None and threading.get_ident() == self._thread.ident:
            return True, fn()
        with self._lock:
            if self._open is not None and not self._open.is_set():
                return False, None
            done, box = threading.Event(), []
            self._open = done
            self._q.put((fn, done, box))
            if self._thread is None:
                self._thread = threading.Thread(target=self._loop, daemon=True,
                                                name="device-list")
                self._thread.start()
        slow = time.monotonic() < self._slow_until
        if not done.wait(0 if slow else ASK_WAIT_S):
            if not slow:
                log.warning("the device list took over %.2fs: using the last one",
                            ASK_WAIT_S)
                self._slow_until = time.monotonic() + SLOW_S
            return False, None
        ok, val = box[0]
        if not ok:
            raise val
        return True, val

    def _loop(self):
        while True:
            fn, done, box = self._q.get()
            try:
                box.append((True, fn()))
            except BaseException as e:  # noqa: BLE001 - handed to the caller
                box.append((False, e))
            done.set()


_asker = _Asker()


def _ask(fn) -> tuple[bool, Any]:
    """(True, fn()) holding DEVICES; (False, None) when PortAudio is being re-scanned
    (its list is being freed) or, on the UI thread, slow to answer: the caller then
    uses its last answer. Only the UI thread goes through the query thread: the
    engine opens its streams holding DEVICES (on its device thread), and the query
    thread could never take it from there, so the engine got the last list, or none
    at all on start-up ("device not found", retried every few seconds)."""
    def held():
        if not DEVICES.acquire(blocking=False):
            return False, None
        try:
            return True, fn()
        finally:
            DEVICES.release()
    if threading.current_thread() is not threading.main_thread():
        return held()
    ok, val = _asker.ask(held)
    return val if ok else (False, None)


def _query_list(kind: str) -> list[dict]:
    api = _wasapi_index()
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    out = []
    for i, d in enumerate(sd.query_devices()):
        if (api is None or d["hostapi"] == api) and d[key] > 0:
            out.append({"index": i, "name": d["name"]})
    _seen[kind] = out
    return out


def list_devices(kind: str) -> list[dict]:
    """WASAPI devices of kind 'input' or 'output' as [{index, name}]."""
    ok, out = _ask(lambda: _query_list(kind))
    return out if ok else list(_seen.get(kind, ()))   # or the last list


def _query_default(kind: str) -> str | None:
    api = _wasapi_index()
    if api is None:
        return None
    info = sd.query_hostapis(api)
    idx = info["default_input_device" if kind == "input" else "default_output_device"]
    name = None if idx is None or idx < 0 else sd.query_devices(idx)["name"]
    _seen[("default", kind)] = name
    return name


def default_device_name(kind: str) -> str | None:
    ok, name = _ask(lambda: _query_default(kind))
    return name if ok else _seen.get(("default", kind))


def list_name(index: int) -> str:
    """A device's name as the device lists show it."""
    ok, name = _ask(lambda: sd.query_devices(index)["name"])
    if ok:
        return name
    for kind in ("output", "input"):
        for d in _seen.get(kind, ()):
            if d["index"] == index:
                return d["name"]
    raise LookupError(index)


def find_device(kind: str, name: str | None) -> int | None:
    if not name:
        return None
    devs = list_devices(kind)
    for d in devs:
        if d["name"] == name:
            return d["index"]
    squash = " ".join(name.split()).lower()   # Windows' own name may space it differently
    for d in devs:
        if " ".join(d["name"].split()).lower() == squash:
            return d["index"]
    for d in devs:  # loose match (device renamed / number changed)
        if name.lower() in d["name"].lower() or d["name"].lower() in name.lower():
            return d["index"]
    return None


# Virtual audio cables (VB-Cable, VB-Cable A/B, Hi-Fi Cable, Voicemeeter, …) show up
# as a playback device ("... Input") paired with a recording device ("... Output").
# Audio played into the first comes out of the second, which apps use as a mic.
# Not plain "virtual": real USB headsets are called e.g. "Speakers (HyperX Virtual
# Surround Sound)", and matching that hid a tester's headset from every device list.
VIRTUAL_HINTS = ("cable", "vb-audio", "voicemeeter", "virtual audio cable")


def is_virtual(name: str | None) -> bool:
    n = (name or "").lower()
    return any(k in n for k in VIRTUAL_HINTS)


def virtual_mic_for(render_name: str | None, ins: list[str] | None = None) -> str | None:
    """The recording device that carries what's played into `render_name`. `ins`: the
    recording devices' names, when the caller already has them (virtual_pairs)."""
    if not render_name or not is_virtual(render_name):
        return None
    if ins is None:
        ins = [d["name"] for d in list_devices("input")]
    for a, b in (("Input", "Output"), ("In ", "Out "), ("Input", "Out")):
        cand = render_name.replace(a, b, 1)
        if cand != render_name and cand in ins:
            return cand
    head = render_name.split("(")[0].replace("Input", "Output").strip().lower()
    for n in ins:
        if is_virtual(n) and n.lower().startswith(head):
            return n
    return None


def same_cable(a: str | None, b: str | None) -> bool:
    """Are `a` and `b` playback ends of one virtual cable? VB-Cable lists "CABLE Input"
    and "CABLE In 16ch" (both "(VB-Audio Virtual Cable)"), and both come out of the
    same "CABLE Output": the product name in brackets tells cables apart."""
    if not (a and b and is_virtual(a) and is_virtual(b)):
        return False
    if a == b:
        return True
    pa, pb = (n[n.rfind("("):].lower() if "(" in n else None for n in (a, b))
    return pa is not None and pa == pb


def virtual_pairs() -> list[tuple[str, str | None]]:
    """(playback device, its mic end or None) of every virtual cable, best (has a mic
    side) first. The device lists are read once: Voicemeeter adds ~18 virtual devices,
    and a list per device froze the window for seconds while Windows was busy."""
    outs = [d["name"] for d in list_devices("output") if is_virtual(d["name"])]
    if not outs:
        return []
    ins = [d["name"] for d in list_devices("input")]
    pairs = [(n, virtual_mic_for(n, ins)) for n in outs]
    return sorted(pairs, key=lambda p: p[1] is None)


def virtual_outputs() -> list[str]:
    """Playback devices that are virtual cables, best (has a mic side) first."""
    return [n for n, _mic in virtual_pairs()]


def output_stream(idx: int, rate: int, **kw) -> sd.OutputStream:
    """A stereo (CH) output stream on device `idx` at its native `rate`. Some devices only
    take their own channel count in WASAPI's shared mode: SteelSeries Sonar's Gaming
    device is 7.1 (8 channels), and a stereo open of it fails with "Invalid number of
    channels", so Sonar users heard nothing in their headphones. Those are opened again
    with Windows mapping the stereo onto their channels (auto_convert); the rate is the
    device's own, so Windows' resampler (see the module) isn't used."""
    try:
        return sd.OutputStream(device=idx, samplerate=rate, channels=CH, dtype="float32", **kw)
    except sd.PortAudioError as e:
        if "Invalid number of channels" not in str(e):
            raise
    log.info("device %s won't take %d channels: Windows maps them onto its own", idx, CH)
    return sd.OutputStream(device=idx, samplerate=rate, channels=CH, dtype="float32",
                           extra_settings=sd.WasapiSettings(auto_convert=True), **kw)


class CableTap:
    """Straight into my mic, and the virtual cable too: a copy of what others hear is
    played into the cable, so a voice app still set to the cable's far end keeps
    hearing everything. The send mix is made on the mic's clock and the cable plays on
    its own, so it goes through a Ring that tracks the drift between them."""

    def __init__(self, name: str, latency: float | str = "low"):
        idx = find_device("output", name)
        if idx is None:
            raise RuntimeError(_("device not found: {device}", device=name))
        self.name = name
        self.rate = int(sd.query_devices(idx)["default_samplerate"])
        self.ring = Ring(self.rate, prefill_s=0.03, max_s=0.2, auto_drift=True)
        self._rs = StreamResampler(SR, self.rate)
        self.last_cb = time.monotonic()
        self.stream = output_stream(idx, self.rate, latency=latency, callback=self._cb)
        start_or_close(self.stream, f"cable tap {name}")

    def write(self, mix: np.ndarray):
        self.ring.write(self._rs(mix))

    def _cb(self, outdata, frames, t, status):
        self.last_cb = time.monotonic()
        x = self.ring.read(frames)
        if x is None:
            outdata.fill(0)
        else:
            outdata[:] = x

    def close(self):
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:  # noqa: BLE001 - a device that's gone
            log.debug("closing the cable tap raised", exc_info=True)

