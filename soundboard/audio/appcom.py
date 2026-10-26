"""The COM plumbing per-program capture and the mic checks share: Windows' audio
constants and interface ids, the ctypes structures, the Com wrapper, the device
enumerator, the playback devices' names and form factors, and capture bytes
turned into stereo float32. Nothing in it works outside Windows.
Part of soundboard.audio.appaudio, which re-exports all of it.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import typing
from ctypes import (POINTER, Structure, Union, byref, c_int, c_long, c_ubyte, c_uint, c_ulong,
                    c_ushort, c_void_p, c_wchar_p, cast)

if typing.TYPE_CHECKING:
    import numpy as np
else:
    try:
        import numpy as np
    except ImportError:   # the mic helper (soundboard/mic/michelper.py) ships without numpy:
        np = None         # it only uses mic_is_silent(), which never needs it

log = logging.getLogger("soundboard.audio.appaudio")


S_OK = 0
E_NOINTERFACE = -2147467262
CLSCTX_ALL = 23
COINIT_MULTITHREADED = 0
RPC_E_CHANGED_MODE = -2147417850
VT_BLOB = 0x41
VT_LPWSTR = 31
VT_UI4 = 19
STGM_READ = 0
E_RENDER, E_CAPTURE, DEVICE_STATE_ACTIVE = 0, 1, 1
E_CONSOLE = 0   # ERole: the default device (not the communications one)
AUDCLNT_SHAREMODE_SHARED = 0
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000
AUDCLNT_BUFFERFLAGS_SILENT = 0x2
AUDCLNT_E_UNSUPPORTED_FORMAT = -2004287480       # 0x88890008
AUDCLNT_E_DEVICE_INVALIDATED = -2004287484       # 0x88890004
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259
WAVE_FORMAT_PCM, WAVE_FORMAT_IEEE_FLOAT, WAVE_FORMAT_EXTENSIBLE = 1, 3, 0xFFFE
PROCESS_LOOPBACK_MODE_INCLUDE_TREE, PROCESS_LOOPBACK_MODE_EXCLUDE_TREE = 0, 1
AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK = 1
VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK = "VAD\\Process_Loopback"
# Windows' own sounds and helpers: never something you'd want to send to a call

_win = sys.platform == "win32"
if _win:
    from ctypes import WINFUNCTYPE, windll
    _ole32, _k32, _user32 = windll.ole32, windll.kernel32, windll.user32

    # handles and pointers are 64-bit: without these, ctypes would pass them as C ints
    for _f, _res, _args in (
        (_k32.OpenProcess, c_void_p, (c_ulong, c_int, c_ulong)),
        (_k32.CloseHandle, c_int, (c_void_p,)),
        (_k32.GetExitCodeProcess, c_int, (c_void_p, c_void_p)),
        (_k32.GetProcessTimes, c_int, (c_void_p, c_void_p, c_void_p, c_void_p, c_void_p)),
        (_k32.QueryFullProcessImageNameW, c_int, (c_void_p, c_ulong, c_void_p, c_void_p)),
        (_k32.CreateToolhelp32Snapshot, c_void_p, (c_ulong, c_ulong)),
        (_k32.Process32FirstW, c_int, (c_void_p, c_void_p)),
        (_k32.Process32NextW, c_int, (c_void_p, c_void_p)),
        (_k32.CreateEventW, c_void_p, (c_void_p, c_int, c_int, c_void_p)),
        (_k32.WaitForSingleObject, c_ulong, (c_void_p, c_ulong)),
        (_user32.IsWindowVisible, c_int, (c_void_p,)),
        (_user32.GetWindow, c_void_p, (c_void_p, c_uint)),
        (_user32.GetWindowThreadProcessId, c_ulong, (c_void_p, c_void_p)),
        (_user32.GetWindowTextLengthW, c_int, (c_void_p,)),
        (_user32.GetWindowTextW, c_int, (c_void_p, c_void_p, c_int)),
        (_user32.EnumWindows, c_int, (c_void_p, c_void_p)),
        (_ole32.CoInitializeEx, c_long, (c_void_p, c_ulong)),
        (_ole32.CoUninitialize, None, ()),
        (_ole32.CoCreateInstance, c_long, (c_void_p, c_void_p, c_ulong, c_void_p, c_void_p)),
        (_ole32.CoTaskMemFree, None, (c_void_p,)),
        (_ole32.PropVariantClear, c_long, (c_void_p,)),
    ):
        _f.restype, _f.argtypes = _res, _args
    # its own copy, so OpenProcess's error code is kept for ctypes.get_last_error()
    _k32le = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32le.OpenProcess.restype = c_void_p
    _k32le.OpenProcess.argtypes = (c_ulong, c_int, c_ulong)
    _ntdll = windll.ntdll
    _ntdll.NtQueryInformationProcess.restype = c_long
    _ntdll.NtQueryInformationProcess.argtypes = (c_void_p, c_int, c_void_p, c_ulong, c_void_p)


# --------------------------------------------------------------------------- COM plumbing

class GUID(Structure):
    _fields_ = [("d1", c_ulong), ("d2", c_ushort), ("d3", c_ushort), ("d4", c_ubyte * 8)]

    @classmethod
    def of(cls, text: str) -> GUID:
        p = text.strip("{}").split("-")
        g = cls()
        g.d1, g.d2, g.d3 = int(p[0], 16), int(p[1], 16), int(p[2], 16)
        g.d4 = (c_ubyte * 8)(*bytes.fromhex(p[3] + p[4]))   # not c_char: it stops at a 0 byte
        return g

    def __eq__(self, other):
        return isinstance(other, GUID) and bytes(self) == bytes(other)

    __hash__ = None   # pyright: ignore[reportAssignmentType]  # unhashable: __eq__ compares bytes


IID_IUnknown = GUID.of("00000000-0000-0000-C000-000000000046")
IID_IAgileObject = GUID.of("94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90")
IID_IAudioClient = GUID.of("1CB9AD4C-DBFA-4C32-B178-C2F568A703B2")
IID_IAudioCaptureClient = GUID.of("C8ADBD64-E71E-48A0-A4DE-185C395CD317")
IID_ICompletionHandler = GUID.of("41D949AB-9862-444A-80F6-C261334DA5EB")
IID_IMMDeviceEnumerator = GUID.of("A95664D2-9614-4F35-A746-DE8DB63617E6")
CLSID_MMDeviceEnumerator = GUID.of("BCDE0395-E52F-467C-8E3D-C4579291692E")
IID_IAudioSessionManager2 = GUID.of("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F")
IID_IAudioSessionControl2 = GUID.of("BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D")
IID_IAudioMeterInformation = GUID.of("C02216F6-8C67-4B5B-9D00-D008E73E0064")
KSDATAFORMAT_SUBTYPE_IEEE_FLOAT = GUID.of("00000003-0000-0010-8000-00AA00389B71")
KSDATAFORMAT_SUBTYPE_PCM = GUID.of("00000001-0000-0010-8000-00AA00389B71")


class PROPERTYKEY(Structure):
    _fields_ = [("fmtid", GUID), ("pid", c_ulong)]


PKEY_Device_FriendlyName = PROPERTYKEY(GUID.of("A45C254E-DF1C-4EFD-8020-67D146A850E0"), 14)
# what Windows thinks the device is (EndpointFormFactor): soundboard.audio.howl reads it
PKEY_AudioEndpoint_FormFactor = PROPERTYKEY(GUID.of("1DA5D803-D492-4EDD-8C23-E0C0FFEE7F0E"), 0)


class BLOB(Structure):
    _fields_ = [("cbSize", c_ulong), ("pBlobData", c_void_p)]


class _PVU(Union):
    _fields_ = [("blob", BLOB), ("pwszVal", c_void_p), ("ulVal", c_ulong)]


class PROPVARIANT(Structure):
    _fields_ = [("vt", c_ushort), ("r1", c_ushort), ("r2", c_ushort), ("r3", c_ushort),
                ("u", _PVU)]


class ACTIVATION_PARAMS(Structure):
    """AUDIOCLIENT_ACTIVATION_PARAMS with its one union member, the process-loopback params."""
    _fields_ = [("ActivationType", c_ulong), ("TargetProcessId", c_ulong),
                ("ProcessLoopbackMode", c_ulong)]


class WAVEFORMATEX(Structure):
    _pack_ = 1
    _fields_ = [("wFormatTag", c_ushort), ("nChannels", c_ushort), ("nSamplesPerSec", c_ulong),
                ("nAvgBytesPerSec", c_ulong), ("nBlockAlign", c_ushort),
                ("wBitsPerSample", c_ushort), ("cbSize", c_ushort)]


class WAVEFORMATEXTENSIBLE(Structure):
    _pack_ = 1
    _fields_ = [("Format", WAVEFORMATEX), ("wValidBitsPerSample", c_ushort),
                ("dwChannelMask", c_ulong), ("SubFormat", GUID)]


class ComError(OSError):
    def __init__(self, hr: int, what: str = ""):
        self.hr = hr & 0xFFFFFFFF
        super().__init__(f"{what or 'COM call'} failed: 0x{self.hr:08X}")


_protos: dict = {}


class Com:
    """A raw COM interface pointer: calls by vtable slot, released once."""

    def __init__(self, ptr: int | None):
        if not ptr:
            raise ComError(-2147467261, "null interface")   # E_POINTER
        self.ptr = ptr

    def _fn(self, slot: int, argtypes: tuple, restype=c_long):
        key = (slot, argtypes, restype)
        proto = _protos.get(key)
        if proto is None:
            proto = _protos[key] = WINFUNCTYPE(restype, c_void_p, *argtypes)
        ptr = self.ptr
        assert ptr, "the interface was released"
        vtbl = cast(ptr, POINTER(c_void_p))[0]
        return proto(cast(vtbl, POINTER(c_void_p))[slot])

    def call(self, slot: int, argtypes: tuple, *args, what: str = "") -> int:
        hr = self._fn(slot, argtypes)(self.ptr, *args)
        if hr < 0:
            raise ComError(hr, what or f"slot {slot}")
        return hr

    def qi(self, iid: GUID) -> Com:
        out = c_void_p()
        self.call(0, (POINTER(GUID), POINTER(c_void_p)), byref(iid), byref(out),
                  what="QueryInterface")
        return Com(out.value)

    def release(self):
        if self.ptr:
            p, self.ptr = self.ptr, None
            try:
                proto = _protos.get((2, (), c_ulong)) or WINFUNCTYPE(c_ulong, c_void_p)
                _protos[(2, (), c_ulong)] = proto
                proto(cast(cast(p, POINTER(c_void_p))[0], POINTER(c_void_p))[2])(p)
            except Exception:  # noqa: BLE001
                log.debug("Release raised", exc_info=True)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.release()


def _co_init() -> bool:
    """CoInitializeEx for this thread. Returns whether we own the uninit."""
    hr = _ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
    if hr == RPC_E_CHANGED_MODE:
        return False   # the thread is already STA (Qt's main thread): calls still work
    if hr < 0:
        raise ComError(hr, "CoInitializeEx")
    return True   # S_OK or S_FALSE (already initialised here): both need a CoUninitialize


def _enumerator() -> Com:
    out = c_void_p()
    hr = _ole32.CoCreateInstance(byref(CLSID_MMDeviceEnumerator), None, CLSCTX_ALL,
                                 byref(IID_IMMDeviceEnumerator), byref(out))
    if hr < 0:
        raise ComError(hr, "CoCreateInstance(MMDeviceEnumerator)")
    return Com(out.value)


def _render_devices(en: Com, flow: int = E_RENDER) -> list[Com]:
    coll = c_void_p()
    en.call(3, (c_int, c_ulong, POINTER(c_void_p)), flow, DEVICE_STATE_ACTIVE, byref(coll),
            what="EnumAudioEndpoints")
    devs = []
    with Com(coll.value) as c:
        try:
            n = c_uint()
            c.call(3, (POINTER(c_uint),), byref(n), what="GetCount")
            for i in range(n.value):
                d = c_void_p()
                c.call(4, (c_uint, POINTER(c_void_p)), i, byref(d), what="Item")
                devs.append(Com(d.value))
        except Exception:   # the ones already got would never be released
            for d in devs:
                d.release()
            raise
    return devs


def _device_name(dev: Com) -> str:
    store = c_void_p()
    try:
        dev.call(4, (c_ulong, POINTER(c_void_p)), STGM_READ, byref(store), what="OpenPropertyStore")
        with Com(store.value) as s:
            pv = PROPVARIANT()
            s.call(5, (POINTER(PROPERTYKEY), POINTER(PROPVARIANT)), byref(PKEY_Device_FriendlyName),
                   byref(pv), what="GetValue")
            try:
                if pv.vt == VT_LPWSTR and pv.u.pwszVal:
                    return cast(pv.u.pwszVal, c_wchar_p).value or ""
            finally:
                _ole32.PropVariantClear(byref(pv))
    except ComError:
        log.debug("device name unavailable", exc_info=True)
    return ""


def _form_factor(dev: Com) -> int | None:
    store = c_void_p()
    try:
        dev.call(4, (c_ulong, POINTER(c_void_p)), STGM_READ, byref(store), what="OpenPropertyStore")
        with Com(store.value) as s:
            pv = PROPVARIANT()
            s.call(5, (POINTER(PROPERTYKEY), POINTER(PROPVARIANT)),
                   byref(PKEY_AudioEndpoint_FormFactor), byref(pv), what="GetValue")
            try:
                return int(pv.u.ulVal) if pv.vt == VT_UI4 else None
            finally:
                _ole32.PropVariantClear(byref(pv))
    except ComError:
        log.debug("form factor unavailable", exc_info=True)
    return None


def output_form_factors() -> dict[str, int]:
    """Each playback device's name -> what Windows thinks it is (EndpointFormFactor:
    1 speakers, 3 headphones, 5 a headset, 9 a screen over HDMI, ...). Asks Windows:
    never on the UI thread. Empty when it can't be asked."""
    if not _win:
        return {}
    out: dict[str, int] = {}
    own = _co_init()
    try:
        with _enumerator() as en:
            for dev in _render_devices(en):
                with dev:
                    name, ff = _device_name(dev), _form_factor(dev)
                    if name and ff is not None:
                        out[name] = ff
    except ComError:
        log.debug("no playback devices", exc_info=True)
    finally:
        if own:
            _ole32.CoUninitialize()
    return out


def _cotaskmem_str(p: c_void_p) -> str:
    if not p.value:
        return ""
    try:
        return cast(p.value, c_wchar_p).value or ""
    finally:
        _ole32.CoTaskMemFree(p.value)


def to_stereo_f32(raw: bytes, fmt: WAVEFORMATEX, is_float: bool) -> np.ndarray:
    """Interleaved capture bytes -> (n, 2) float32 (any channel count / sample width)."""
    ch, bits = fmt.nChannels, fmt.wBitsPerSample
    if is_float and bits == 32:
        x = np.frombuffer(raw, np.float32)
    elif bits == 16:
        x = np.frombuffer(raw, np.int16).astype(np.float32) * np.float32(1 / 32768)
    elif bits == 32:
        x = np.frombuffer(raw, np.int32).astype(np.float32) * np.float32(1 / 2147483648)
    elif bits == 24:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
        x = ((b[:, 0] << 8) | (b[:, 1] << 16) | (b[:, 2] << 24)).astype(np.float32) / 2147483648
    else:
        x = np.frombuffer(raw, np.uint8).astype(np.float32) * np.float32(1 / 128) - 1
    x = x.reshape(-1, max(ch, 1))
    if ch == 1:
        x = np.repeat(x, 2, axis=1)
    elif ch > 2:
        x = x[:, :2]
    return np.ascontiguousarray(x, dtype=np.float32)

