"""The sound devices PortAudio lists: finding one by its saved name, which are
virtual cables (and each one's mic side), opening an output at its native rate,
and CableTap, the copy of what others hear played into the cable.

Part of soundboard.audio.engine, which re-exports all of it (tests swap these
names there, and a swap reaches the code here).
"""
from __future__ import annotations

import logging
import time

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


def list_devices(kind: str) -> list[dict]:
    """WASAPI devices of kind 'input' or 'output' as [{index, name}]."""
    if not DEVICES.acquire(blocking=False):   # being re-scanned: the last list
        return list(_seen.get(kind, ()))
    try:
        api = _wasapi_index()
        key = "max_input_channels" if kind == "input" else "max_output_channels"
        out = []
        for i, d in enumerate(sd.query_devices()):
            if (api is None or d["hostapi"] == api) and d[key] > 0:
                out.append({"index": i, "name": d["name"]})
        _seen[kind] = out
        return out
    finally:
        DEVICES.release()


def default_device_name(kind: str) -> str | None:
    if not DEVICES.acquire(blocking=False):
        return _seen.get(("default", kind))
    try:
        api = _wasapi_index()
        if api is None:
            return None
        info = sd.query_hostapis(api)
        idx = info["default_input_device" if kind == "input" else "default_output_device"]
        name = None if idx is None or idx < 0 else sd.query_devices(idx)["name"]
        _seen[("default", kind)] = name
        return name
    finally:
        DEVICES.release()


def list_name(index: int) -> str:
    """A device's name as the device lists show it."""
    if not DEVICES.acquire(blocking=False):
        for kind in ("output", "input"):
            for d in _seen.get(kind, ()):
                if d["index"] == index:
                    return d["name"]
        raise LookupError(index)
    try:
        return sd.query_devices(index)["name"]
    finally:
        DEVICES.release()


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


def virtual_mic_for(render_name: str | None) -> str | None:
    """The recording device that carries what's played into `render_name`."""
    if not render_name or not is_virtual(render_name):
        return None
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


def virtual_outputs() -> list[str]:
    """Playback devices that are virtual cables, best (has a mic side) first."""
    outs = [d["name"] for d in list_devices("output") if is_virtual(d["name"])]
    return sorted(outs, key=lambda n: virtual_mic_for(n) is None)


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

