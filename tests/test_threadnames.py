"""Python threads carry their names in Windows too (soundboard.threadnames)."""
import ctypes
import sys
import threading

import pytest

from soundboard import threadnames


def _windows_name(native_id: int) -> str:
    k32 = ctypes.WinDLL("kernel32")
    k32.OpenThread.restype = ctypes.c_void_p
    k32.OpenThread.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
    k32.GetThreadDescription.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p))
    k32.CloseHandle.argtypes = (ctypes.c_void_p,)
    k32.LocalFree.argtypes = (ctypes.c_void_p,)
    h = k32.OpenThread(0x0800, False, native_id)   # THREAD_QUERY_LIMITED_INFORMATION
    assert h
    try:
        out = ctypes.c_wchar_p()
        assert k32.GetThreadDescription(h, ctypes.byref(out)) >= 0
        name = out.value or ""
        k32.LocalFree(ctypes.cast(out, ctypes.c_void_p))
        return name
    finally:
        k32.CloseHandle(h)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_a_thread_started_after_install_has_its_name_in_windows(monkeypatch):
    monkeypatch.setattr(threading.Thread, "start", threading.Thread.start)  # undone after
    threadnames.install()
    threadnames.install()                       # twice: still wrapped once
    assert getattr(threading.Thread.start, "_names_native", False)
    seen, go = {}, threading.Event()

    def work():
        seen["name"] = _windows_name(threading.get_native_id())
        go.wait(5)

    class Sub(threading.Thread):                # a subclass with its own run(), too
        def run(self):
            seen["sub"] = _windows_name(threading.get_native_id())
    t = threading.Thread(target=work, name="voicesdk-listeners", daemon=True)
    t.start()
    s = Sub(name="tts-speaker", daemon=True)
    s.start()
    s.join(5)
    go.set()
    t.join(5)
    assert seen == {"name": "voicesdk-listeners", "sub": "tts-speaker"}


def test_naming_never_fails_a_thread(monkeypatch):
    monkeypatch.setattr(threading.Thread, "start", threading.Thread.start)
    monkeypatch.setattr(threadnames, "_api", False)    # no such call on this Windows
    threadnames.install()
    ran = []
    t = threading.Thread(target=lambda: ran.append(1))
    t.start()
    t.join(5)
    assert ran == [1]
    assert not threadnames.name_native(None, "x") and not threadnames.name_native(1, "")
