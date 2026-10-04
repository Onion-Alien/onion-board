"""Virtual cable format check: are both ends of the cable at 48 kHz?

A virtual cable has two ends: the playback device we send into ("CABLE Input")
and the recording device Discord / the game listens to ("CABLE Output"). Each has
its own Windows format (Sound settings -> the device -> Advanced), and the cable
has an internal rate (48 kHz by default). VB-Audio's manual: when both ends run
at the internal rate, audio passes through "without conversion, so with the best
audio quality"; any other rate is converted inside the driver. Windows sometimes
sets an end to 44.1 kHz on its own (after a driver update, or another app asked
for it), so the app checks and offers to put both back on 48 kHz.

This reads and writes the device formats the same way the Sound control panel
does (IPolicyConfig: no admin needed). Everything is best-effort: on failure a
check returns no ends and a fix returns False, and the app plays on as before.
"""
from __future__ import annotations

import logging
import sys
from ctypes import POINTER, byref, c_int, c_uint, c_ulong, c_void_p, c_wchar_p, cast
from dataclasses import dataclass

log = logging.getLogger(__name__)

RATE = 48000        # the cable's default internal rate: both ends should match it
E_RENDER, E_CAPTURE = 0, 1

_win = sys.platform == "win32"


@dataclass(frozen=True)
class CableEnd:
    name: str
    flow: str        # 'render' (we play into it) or 'capture' (Discord records it)
    dev_id: str
    rate: int
    bits: int
    channels: int

    @property
    def ok(self) -> bool:
        return self.rate == RATE


def _policy():
    from soundboard.appaudio import GUID, CLSCTX_ALL, ComError, Com, _ole32
    clsid = GUID.of("870AF99C-171D-4F9E-AF0D-E63DF40C2BC9")   # CPolicyConfigClient
    iid = GUID.of("F8679F50-850A-41CF-9C72-430F290290C8")     # IPolicyConfig (Win 7+)
    out = c_void_p()
    hr = _ole32.CoCreateInstance(byref(clsid), None, CLSCTX_ALL, byref(iid), byref(out))
    if hr < 0:
        raise ComError(hr, "CoCreateInstance(PolicyConfig)")
    return Com(out.value)


def _devices(flow: int) -> list[tuple[str, str]]:
    """(id, friendly name) of the active endpoints of one flow."""
    from soundboard.appaudio import (DEVICE_STATE_ACTIVE, Com, _cotaskmem_str, _device_name,
                                     _enumerator)
    out = []
    with _enumerator() as en:
        coll = c_void_p()
        en.call(3, (c_int, c_ulong, POINTER(c_void_p)), flow, DEVICE_STATE_ACTIVE,
                byref(coll), what="EnumAudioEndpoints")
        with Com(coll.value) as c:
            n = c_uint()
            c.call(3, (POINTER(c_uint),), byref(n), what="GetCount")
            for i in range(n.value):
                d = c_void_p()
                c.call(4, (c_uint, POINTER(c_void_p)), i, byref(d), what="Item")
                with Com(d.value) as dev:
                    p = c_void_p()
                    dev.call(5, (POINTER(c_void_p),), byref(p), what="GetId")
                    out.append((_cotaskmem_str(p), _device_name(dev)))
    return out


def _get_format(pc, dev_id: str, mix: bool):
    """(WAVEFORMATEX copy, raw bytes) of the device (or its mix) format."""
    from ctypes import string_at

    from soundboard.appaudio import WAVEFORMATEX, _ole32
    p = c_void_p()
    if mix:
        pc.call(3, (c_wchar_p, POINTER(c_void_p)), dev_id, byref(p), what="GetMixFormat")
    else:
        pc.call(4, (c_wchar_p, c_int, POINTER(c_void_p)), dev_id, 0, byref(p),
                what="GetDeviceFormat")
    try:
        wf = cast(p.value, POINTER(WAVEFORMATEX)).contents
        size = 18 + (wf.cbSize if wf.wFormatTag == 0xFFFE else 0)
        return bytearray(string_at(p.value, size))
    finally:
        _ole32.CoTaskMemFree(p.value)


def _parse(raw: bytearray) -> tuple[int, int, int]:
    """(rate, bits, channels) of a WAVEFORMATEX(TENSIBLE) blob."""
    from soundboard.appaudio import WAVEFORMATEX
    wf = WAVEFORMATEX.from_buffer_copy(bytes(raw[:18]))
    return int(wf.nSamplesPerSec), int(wf.wBitsPerSample), int(wf.nChannels)


def _with_rate(raw: bytearray, rate: int) -> bytearray:
    from soundboard.appaudio import WAVEFORMATEX
    out = bytearray(raw)
    wf = WAVEFORMATEX.from_buffer(out)
    wf.nSamplesPerSec = rate
    wf.nAvgBytesPerSec = rate * wf.nBlockAlign
    return out


def cable_ends(names_hint=None) -> list[CableEnd]:
    """Every virtual-cable endpoint with its current format ([] when it can't tell)."""
    if not _win:
        return []
    from soundboard.appaudio import ComError, _co_init, _ole32
    from soundboard.engine import is_virtual
    owned = False
    try:
        owned = _co_init()
        ends = []
        with _policy() as pc:
            for flow, label in ((E_RENDER, "render"), (E_CAPTURE, "capture")):
                for dev_id, name in _devices(flow):
                    if not is_virtual(name):
                        continue
                    if names_hint is not None and name not in names_hint:
                        continue
                    try:
                        rate, bits, ch = _parse(_get_format(pc, dev_id, mix=False))
                    except ComError:
                        continue
                    ends.append(CableEnd(name, label, dev_id, rate, bits, ch))
        return ends
    except (OSError, ValueError):
        log.debug("cable format check failed", exc_info=True)
        return []
    finally:
        if owned:
            _ole32.CoUninitialize()


def pair(ends: list[CableEnd], render_name: str | None,
         capture_name: str | None) -> list[CableEnd]:
    """The two ends of the cable in use (render first), from cable_ends()."""
    return ([e for e in ends if e.flow == "render" and e.name == render_name]
            + [e for e in ends if e.flow == "capture" and e.name == capture_name])


def set_rate(end: CableEnd, rate: int = RATE) -> bool:
    """Put one end of the cable on `rate` (keeping its bit depth and channels)."""
    if not _win:
        return False
    from soundboard.appaudio import ComError, _co_init, _ole32
    owned = False
    try:
        owned = _co_init()
        with _policy() as pc:
            dev = _with_rate(_get_format(pc, end.dev_id, mix=False), rate)
            mix = _with_rate(_get_format(pc, end.dev_id, mix=True), rate)
            pc.call(6, (c_wchar_p, c_void_p, c_void_p), end.dev_id,
                    _addr(dev), _addr(mix), what="SetDeviceFormat")
        log.info("set %s (%s) to %d Hz", end.name, end.flow, rate)
        return True
    except (ComError, OSError, ValueError):
        log.warning("couldn't set %s to %d Hz", end.name, rate, exc_info=True)
        return False
    finally:
        if owned:
            _ole32.CoUninitialize()


def _addr(buf: bytearray) -> int:
    from ctypes import addressof, c_char
    return addressof((c_char * len(buf)).from_buffer(buf))


def fix(ends: list[CableEnd]) -> bool:
    """Set every end that isn't at RATE; True if all of them are now."""
    results = [set_rate(e) for e in ends if not e.ok]   # try every end, then combine
    return all(results)


__all__ = ["RATE", "CableEnd", "cable_ends", "fix", "pair", "set_rate"]
