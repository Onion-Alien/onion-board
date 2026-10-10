"""The tests on Linux or macOS: Onion Board only runs on Windows, but most of its code
(mixing, effects, config, the windows on Qt's offscreen platform) doesn't care. Off
Windows, `install()` stands in for what's missing so `soundboard` imports:

- `winreg`: every key is missing (FileNotFoundError, as for a key that isn't there);
- ctypes' Windows parts (`windll`, `WinDLL`, `WINFUNCTYPE`, `WinError`, …): a DLL's
  functions can be set up (argtypes, restype) but calling one raises OSError, as a
  failed Windows call does. Nothing pretends to succeed: a COM call "succeeding"
  would hand back a null pointer and crash the test worker.

Tests that need the real thing are marked `@pytest.mark.windows` (or a file's
`pytestmark`) and are skipped off Windows. On Windows this does nothing."""
from __future__ import annotations

import ctypes
import subprocess
import sys
import types

_POPEN_FLAGS = ("CREATE_NO_WINDOW", "CREATE_NEW_CONSOLE", "CREATE_NEW_PROCESS_GROUP",
                "DETACHED_PROCESS", "CREATE_BREAKAWAY_FROM_JOB", "CREATE_DEFAULT_ERROR_MODE",
                "BELOW_NORMAL_PRIORITY_CLASS", "ABOVE_NORMAL_PRIORITY_CLASS",
                "IDLE_PRIORITY_CLASS", "NORMAL_PRIORITY_CLASS", "HIGH_PRIORITY_CLASS",
                "REALTIME_PRIORITY_CLASS")


class NotWindows(OSError):
    """A Windows call made off Windows."""


def _fail(name: str):
    def call(*_a, **_k):
        raise NotWindows(f"{name}: not on Windows")
    return call


class _Function:
    """A DLL function: argtypes / restype / errcheck can be set, calling it fails."""

    def __init__(self, name: str):
        self.__name__ = name
        self._call = _fail(name)

    def __call__(self, *a, **k):
        return self._call(*a, **k)


class _Dll:
    def __init__(self, name: str = "", *_a, **_k):
        self._name = name

    def __getattr__(self, attr):
        if attr.startswith("__"):
            raise AttributeError(attr)
        fn = _Function(f"{self._name}.{attr}")
        setattr(self, attr, fn)
        return fn

    __getitem__ = __getattr__


class _Loader:
    def __getattr__(self, attr):
        if attr.startswith("__"):
            raise AttributeError(attr)
        dll = _Dll(attr)
        setattr(self, attr, dll)
        return dll

    def LoadLibrary(self, name, *_a, **_k):   # noqa: N802 - ctypes' own name
        return _Dll(str(name))


def _winreg() -> types.ModuleType:
    reg = types.ModuleType("winreg")
    reg.__doc__ = "Stand-in for the tests off Windows: every key is missing."
    consts = {
        "HKEY_CLASSES_ROOT": 0x80000000, "HKEY_CURRENT_USER": 0x80000001,
        "HKEY_LOCAL_MACHINE": 0x80000002, "HKEY_USERS": 0x80000003,
        "KEY_QUERY_VALUE": 0x1, "KEY_SET_VALUE": 0x2, "KEY_CREATE_SUB_KEY": 0x4,
        "KEY_ENUMERATE_SUB_KEYS": 0x8, "KEY_READ": 0x20019, "KEY_WRITE": 0x20006,
        "KEY_ALL_ACCESS": 0xF003F, "KEY_WOW64_64KEY": 0x100, "KEY_WOW64_32KEY": 0x200,
        "REG_NONE": 0, "REG_SZ": 1, "REG_EXPAND_SZ": 2, "REG_BINARY": 3, "REG_DWORD": 4,
        "REG_MULTI_SZ": 7, "REG_QWORD": 11,
    }
    for k, v in consts.items():
        setattr(reg, k, v)

    def missing(*_a, **_k):
        raise FileNotFoundError(2, "The system cannot find the file specified (not Windows)")

    for fn in ("OpenKey", "OpenKeyEx", "CreateKey", "CreateKeyEx", "DeleteKey", "DeleteKeyEx",
               "DeleteValue", "EnumKey", "EnumValue", "QueryValue", "QueryValueEx",
               "QueryInfoKey", "SetValue", "SetValueEx", "ConnectRegistry", "FlushKey"):
        setattr(reg, fn, missing)
    reg.CloseKey = lambda _key: None
    reg.ExpandEnvironmentStrings = lambda s: s
    reg.error = OSError
    return reg


def install() -> None:
    if sys.platform == "win32":
        return
    sys.modules.setdefault("winreg", _winreg())
    ctypes.WINFUNCTYPE = ctypes.CFUNCTYPE
    ctypes.windll = ctypes.oledll = _Loader()
    ctypes.WinDLL = ctypes.OleDLL = _Dll
    ctypes.HRESULT = ctypes.c_long
    ctypes.get_last_error = lambda: 0
    ctypes.set_last_error = lambda _v: 0
    ctypes.FormatError = lambda code=0: f"Windows error {code}"
    ctypes.WinError = lambda code=None, descr=None: NotWindows(code, descr or "not on Windows")
    # Windows-only Popen flags: 0, because POSIX's Popen refuses any other
    # creationflags (and a child never opens a console window there anyway).
    for flag in _POPEN_FLAGS:
        if not hasattr(subprocess, flag):
            setattr(subprocess, flag, 0)


def quiet_hotkeys() -> None:
    """Off Windows the main window's hotkey thread has no message queue to wait on:
    it ends at once, as if no hotkey were ever registered (none can be)."""
    if sys.platform == "win32":
        return
    from soundboard import winkeys

    def loop(self):
        self._tid = 0
        self._ready.set()

    def register(self, mapping):
        self._midi_map = {}
        self.failed = [c for c in mapping if c]

    winkeys.Hotkeys._loop = loop
    winkeys.Hotkeys.register = register
    winkeys.Hotkeys.stop = lambda self: self.midi.close_all()
