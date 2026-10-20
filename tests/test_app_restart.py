"""app.register_restart: Windows starts the app again after an installer closed it to
update it (Inno Setup's CloseApplications), a crash or a Not Responding close, marked
--restarted so it comes back without taking the focus."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from soundboard.core import app
from soundboard.core.app import restart_cmdline

ROOT = Path(__file__).resolve().parent.parent


def test_frozen_keeps_args_but_drops_the_one_off_ones():
    argv = [r"C:\Apps\OnionBoard.exe", "--tray", "--restart-after", "123",
            "--resume-setup", "--x", "a b"]
    assert restart_cmdline(argv, frozen=True) == '--x "a b" --restarted'


def test_source_run_names_the_script_by_full_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert restart_cmdline(["main.py", "--tray"], frozen=False) == \
        subprocess.list2cmdline([str(tmp_path / "main.py"), "--restarted"])


def test_restarted_twice_is_marked_once():
    assert restart_cmdline(["ob.exe", "--restarted"], frozen=True) == "--restarted"


@pytest.mark.windows   # PowerShell and RegisterApplicationRestart
def test_windows_accepts_the_registration():
    """In a child process: it registers, and Windows hands the same line back."""
    child = textwrap.dedent("""
        import ctypes, sys
        from ctypes import wintypes
        sys.argv = [sys.argv[0], "--tray"]
        from soundboard.core import app
        app.register_restart()
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = wintypes.HANDLE
        k.GetApplicationRestartSettings.argtypes = [
            wintypes.HANDLE, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD)]
        buf = ctypes.create_unicode_buffer(1024)
        size, flags = wintypes.DWORD(1024), wintypes.DWORD()
        hr = k.GetApplicationRestartSettings(k.GetCurrentProcess(), buf,
                                             ctypes.byref(size), ctypes.byref(flags))
        print(hr, flags.value, buf.value, sep="|")
    """)
    out = subprocess.run([sys.executable, "-c", child], cwd=ROOT, capture_output=True,
                         text=True, timeout=60, env={**os.environ, "PYTHONPATH": str(ROOT)})
    hr, flags, line = out.stdout.strip().split("|")
    assert hr == "0", out.stderr
    assert int(flags) == 8   # after a crash, a hang or an update: only not a reboot
    assert "--tray" not in line and line.endswith("--restarted")   # back on screen



def test_audio_tuning_raises_the_process_one_step(monkeypatch):
    """Above normal, never high: a busy PC can't starve the sound, and the app
    doesn't outrank Windows itself."""
    calls = []

    class K32:
        def GetCurrentProcess(self):
            return -1

        def SetPriorityClass(self, handle, cls):
            calls.append((handle, cls))
            return 1

    monkeypatch.setattr(app.sys, "platform", "win32")
    monkeypatch.setattr(app.ctypes, "windll", type("W", (), {"kernel32": K32()})(), raising=False)
    app.raise_process_priority()
    assert calls == [(-1, 0x8000)]   # ABOVE_NORMAL_PRIORITY_CLASS
