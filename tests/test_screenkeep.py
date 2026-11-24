"""win/screenkeep: Windows without any monitor for a moment mustn't take Qt's screens
(the next window made then ended the app: "Cannot create window: no screens available")."""
import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# A hidden app (nothing is ever shown): Windows' list of monitors is made empty for this
# process, and the message Windows sends at a monitor change goes to Qt's window.
APP = r'''
import ctypes, sys, time
from ctypes import wintypes as wt
from PySide6.QtWidgets import QApplication, QWidget
app = QApplication([])
from soundboard.win import screenkeep
if "keep" in sys.argv:
    assert screenkeep.install()
before = [s.name() for s in app.screens()]
assert before
w = QWidget(); w.winId()
u, k = ctypes.WinDLL("user32"), ctypes.WinDLL("kernel32")
k.VirtualProtect.argtypes = (ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, ctypes.c_void_p)
addr = ctypes.cast(u.EnumDisplayMonitors, ctypes.c_void_p).value
old = wt.DWORD()
assert k.VirtualProtect(addr, 8, 0x40, ctypes.byref(old))
real = ctypes.string_at(addr, 6)
hwnd = screenkeep._observer(screenkeep._user32())
assert hwnd
def change():
    for msg in (0x7E, 0x1A):
        u.SendMessageW(wt.HWND(hwnd), msg, 32, 0)
    app.processEvents()
ctypes.memmove(addr, b"\xb8\x01\x00\x00\x00\xc3", 6)   # mov eax, 1; ret
change()
print("screens", len(app.screens()), flush=True)
x = QWidget(); x.winId()
print("made", flush=True)
assert w.screen() is not None and [s.name() for s in app.screens()] == before
ctypes.memmove(addr, real, 6)
assert screenkeep._kept["timer"].isActive()
end = time.monotonic() + 10
while screenkeep._kept["timer"].isActive() and time.monotonic() < end:
    app.processEvents()
    time.sleep(0.02)
assert not screenkeep._kept["timer"].isActive()          # it saw the monitor come back
change()
assert [s.name() for s in app.screens()] == before
screenkeep.uninstall()
assert not screenkeep._kept
change()
assert [s.name() for s in app.screens()] == before       # Qt's own again
print("done", flush=True)
'''


def run(*args):
    env = {**os.environ, "QT_QPA_PLATFORM": "windows", "PYTHONPATH": str(ROOT)}
    return subprocess.run([sys.executable, "-c", APP, *args], env=env, cwd=ROOT, timeout=60,
                          capture_output=True, text=True, creationflags=0x08000000)


windows_only = pytest.mark.skipif(
    sys.platform != "win32" or platform.machine().upper() != "AMD64", reason="Windows x64 only")


@windows_only
def test_no_monitor_for_a_moment_keeps_qts_screens():
    r = run("keep")
    assert "done" in r.stdout and r.returncode == 0, r.stdout + r.stderr[-2000:]


@windows_only
def test_without_it_qt_loses_them():
    """What the test above is for: Qt on its own drops every screen and dies at the
    next window. (Doesn't one day? Then screenkeep can go.)"""
    r = run()
    assert "screens 0" in r.stdout and "made" not in r.stdout, r.stdout + r.stderr[-2000:]


def test_offscreen_it_does_nothing(qapp):
    from soundboard.win import screenkeep
    assert screenkeep.install() is False
