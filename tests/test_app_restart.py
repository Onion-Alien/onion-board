"""app.register_restart: an installer that closes the app to update it (Inno Setup's
CloseApplications) starts it again, instead of leaving it closed like a crash."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from soundboard.app import restart_cmdline

ROOT = Path(__file__).resolve().parent.parent


def test_frozen_keeps_args_but_drops_the_one_off_ones():
    argv = [r"C:\Apps\OnionBoard.exe", "--tray", "--restart-after", "123",
            "--resume-setup", "--x", "a b"]
    assert restart_cmdline(argv, frozen=True) == '--x "a b"'


def test_source_run_names_the_script_by_full_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert restart_cmdline(["main.py", "--tray"], frozen=False) == \
        subprocess.list2cmdline([str(tmp_path / "main.py")])


@pytest.mark.windows   # PowerShell and RegisterApplicationRestart
def test_windows_accepts_the_registration():
    """In a child process: it registers, and Windows hands the same line back."""
    child = textwrap.dedent("""
        import ctypes, sys
        from ctypes import wintypes
        sys.argv = [sys.argv[0], "--tray"]
        from soundboard import app
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
    assert int(flags) == 1 | 2 | 8   # only for updates: not after a crash, hang or reboot
    assert "--tray" not in line   # comes back on screen

