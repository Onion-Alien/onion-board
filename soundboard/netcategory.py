"""Whether Windows calls the network an address is on Public, Private or Domain (the
choice in Settings → Network & internet), so the phone remote's server never listens
on a café's or a hotel's Wi-Fi even when Windows Firewall would let it (an "Allow" once
clicked on Windows' own firewall prompt with Public ticked lets a program in on every
Public network).

`category(ip)` asks Windows' Network List Manager (COM, a few ms, no admin, no child
process) for each connection's adapter, finds the adapter holding `ip` in the
TCP/IP settings in the registry, and returns that network's category; None when it
can't tell (not Windows, or anything failed), which callers treat as "don't know"."""
from __future__ import annotations

import logging
import sys

log = logging.getLogger(__name__)

PUBLIC, PRIVATE, DOMAIN = "public", "private", "domain"
_CATEGORIES = {0: PUBLIC, 1: PRIVATE, 2: DOMAIN}   # NLM_NETWORK_CATEGORY
_INTERFACES = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"


def _addresses(adapter: str) -> set[str]:
    """The IPv4 addresses Windows has for adapter `{GUID}`."""
    import winreg
    out: set[str] = set()
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{_INTERFACES}\\{adapter}") as k:
            for name in ("DhcpIPAddress", "IPAddress"):
                try:
                    v = winreg.QueryValueEx(k, name)[0]
                except OSError:
                    continue
                out.update([v] if isinstance(v, str) else list(v or ()))
    except OSError:
        pass
    return out


def category(ip: str) -> str | None:
    """PUBLIC / PRIVATE / DOMAIN for the network `ip` (this PC's address) is on, or None."""
    if sys.platform != "win32":
        return None
    try:
        return _category(ip)
    except Exception:  # noqa: BLE001 - "don't know" is always a fine answer
        log.debug("couldn't read the network category", exc_info=True)
        return None


def _category(ip: str) -> str | None:
    import ctypes
    import uuid
    from ctypes import POINTER, WINFUNCTYPE, byref, c_int, c_ulong, c_void_p

    class GUID(ctypes.Structure):
        _fields_ = [("raw", ctypes.c_ubyte * 16)]

        @classmethod
        def of(cls, text):
            g = cls()
            ctypes.memmove(g.raw, uuid.UUID(text).bytes_le, 16)
            return g

        def text(self):
            return "{" + str(uuid.UUID(bytes_le=bytes(self.raw))).upper() + "}"

    HR = ctypes.HRESULT   # a failing call raises OSError

    def call(obj, index, *argtypes):
        vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]
        return WINFUNCTYPE(HR, c_void_p, *argtypes)(vtbl[index])

    def release(obj):
        if obj:
            vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]
            WINFUNCTYPE(c_ulong, c_void_p)(vtbl[2])(obj)

    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitializeEx.argtypes = [c_void_p, ctypes.c_uint]
    ole32.CoInitializeEx.restype = c_int
    ole32.CoCreateInstance.argtypes = [POINTER(GUID), c_void_p, ctypes.c_uint,
                                       POINTER(GUID), POINTER(c_void_p)]
    ole32.CoCreateInstance.restype = c_int
    # S_OK / S_FALSE: ours to undo. RPC_E_CHANGED_MODE: the thread already has COM (Qt's)
    hr = ole32.CoInitializeEx(None, 0x2)   # COINIT_APARTMENTTHREADED, like Qt's UI thread
    inited = hr in (0, 1)
    manager = c_void_p()
    try:
        hr = ole32.CoCreateInstance(byref(GUID.of("DCB00C01-570F-4A9B-8D69-199FDBA5723B")),
                                    None, 0x17,   # CLSCTX_ALL
                                    byref(GUID.of("DCB00000-570F-4A9B-8D69-199FDBA5723B")),
                                    byref(manager))
        if hr < 0 or not manager:
            return None
        conns = c_void_p()
        call(manager, 9, POINTER(c_void_p))(manager, byref(conns))   # GetNetworkConnections
        try:
            while True:
                conn, got = c_void_p(), c_ulong()
                call(conns, 8, c_ulong, POINTER(c_void_p), POINTER(c_ulong))(
                    conns, 1, byref(conn), byref(got))                   # Next
                if not got.value:
                    return None
                try:
                    adapter = GUID()
                    call(conn, 12, POINTER(GUID))(conn, byref(adapter))   # GetAdapterId
                    if ip not in _addresses(adapter.text()):
                        continue
                    net = c_void_p()
                    call(conn, 7, POINTER(c_void_p))(conn, byref(net))    # GetNetwork
                    try:
                        cat = c_int()
                        call(net, 18, POINTER(c_int))(net, byref(cat))    # GetCategory
                        return _CATEGORIES.get(cat.value)
                    finally:
                        release(net)
                finally:
                    release(conn)
        finally:
            release(conns)
    finally:
        release(manager)
        if inited:
            ole32.CoUninitialize()
