"""The tests on Linux or macOS: Onion Board only runs on Windows, but most of its code
(mixing, effects, config, the windows on Qt's offscreen platform) doesn't care. Off
Windows, `install()` stands in for what's missing so `soundboard` imports:

- `winreg`: every key is missing (FileNotFoundError, as for a key that isn't there);
- `subprocess`' Windows flags (CREATE_NO_WINDOW, …): they exist, and Popen drops
  `creationflags` (only Windows takes them; they hide a console window);
- ctypes' Windows parts (`windll`, `WinDLL`, `WINFUNCTYPE`, `WinError`, …): a DLL's
  functions can be set up (argtypes, restype) but calling one raises OSError, as a
  failed Windows call does. Nothing pretends to succeed: a COM call "succeeding"
  would hand back a null pointer and crash the test worker. The one exception is a
  thread's message queue (`_Queues`), which every main window's hotkey thread waits
  on; RegisterHotKey still always fails there.

Tests that need the real thing are marked `@pytest.mark.windows` (or a file's
`pytestmark`) and are skipped off Windows. On Windows this does nothing."""
from __future__ import annotations

import ctypes
import queue
import subprocess
import sys
import threading
import types


class NotWindows(OSError):
    """A Windows call made off Windows."""


def _fail(name: str):
    def call(*_a, **_k):
        raise NotWindows(f"{name}: not on Windows")
    return call


class _Queues:
    """user32's thread message queues, enough for winkeys.Hotkeys' thread: it posts
    and waits as on Windows, but no hotkey can be registered (as if another program
    held every one)."""
    WM_QUIT = 0x0012

    def __init__(self):
        self._lock = threading.Lock()
        self._queues: dict[int, queue.Queue] = {}

    def _mine(self) -> queue.Queue:
        with self._lock:
            return self._queues.setdefault(threading.get_ident(), queue.Queue())

    def peek(self, msg, *_a):
        self._mine()   # creates the queue, as PeekMessage does
        return 0

    def get(self, msg, *_a):
        message, wparam, lparam = self._mine().get()
        m = msg._obj   # byref(msg)
        m.message, m.wParam, m.lParam = message, wparam, lparam
        if message == self.WM_QUIT:
            with self._lock:
                self._queues.pop(threading.get_ident(), None)
            return 0
        return 1

    def post(self, tid, message, wparam, lparam):
        with self._lock:
            q = self._queues.get(tid)
        if q is None:
            return 0
        q.put((message, wparam, lparam))
        return 1


_QUEUES = _Queues()
_WORKING = {   # the few calls that work off Windows: (dll, function) -> what it does
    ("kernel32", "GetCurrentThreadId"): lambda: threading.get_ident(),
    ("user32", "PeekMessageW"): _QUEUES.peek,
    ("user32", "GetMessageW"): _QUEUES.get,
    ("user32", "PostThreadMessageW"): _QUEUES.post,
    ("user32", "RegisterHotKey"): lambda *_a: 0,
    ("user32", "UnregisterHotKey"): lambda *_a: 0,
}


class _Function:
    """A DLL function: argtypes / restype / errcheck can be set, calling it fails."""

    def __init__(self, dll: str, name: str):
        self.__name__ = name
        self._call = _WORKING.get((dll, name)) or _fail(f"{dll}.{name}")

    def __call__(self, *a, **k):
        return self._call(*a, **k)


class _Dll:
    def __init__(self, name: str = "", *_a, **_k):
        self._name = str(name).lower().removesuffix(".dll")

    def __getattr__(self, attr):
        if attr.startswith("__"):
            raise AttributeError(attr)
        fn = _Function(self._name, attr)
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
        return _Dll(name)


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


class _Popen(subprocess.Popen):
    def __init__(self, *args, creationflags=0, **kwargs):
        super().__init__(*args, **kwargs)


_FLAGS = {"CREATE_NEW_CONSOLE": 0x10, "CREATE_NEW_PROCESS_GROUP": 0x200,
          "CREATE_NO_WINDOW": 0x08000000, "DETACHED_PROCESS": 0x8,
          "BELOW_NORMAL_PRIORITY_CLASS": 0x4000, "IDLE_PRIORITY_CLASS": 0x40}


def install() -> None:
    if sys.platform == "win32":
        return
    # mimetypes reads Windows' file types from the registry whenever it can import
    # winreg: imported first, it never sees the stand-in
    import mimetypes  # noqa: F401
    sys.modules.setdefault("winreg", _winreg())
    for name, value in _FLAGS.items():
        if not hasattr(subprocess, name):
            setattr(subprocess, name, value)
    subprocess.Popen = _Popen
    ctypes.WINFUNCTYPE = ctypes.CFUNCTYPE
    ctypes.windll = ctypes.oledll = _Loader()
    ctypes.WinDLL = ctypes.OleDLL = _Dll
    ctypes.HRESULT = ctypes.c_long
    ctypes.get_last_error = lambda: 0
    ctypes.set_last_error = lambda _v: 0
    ctypes.FormatError = lambda code=0: f"Windows error {code}"
    ctypes.WinError = lambda code=None, descr=None: NotWindows(code, descr or "not on Windows")
