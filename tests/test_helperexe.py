"""soundboard.core.helperexe: which program each of the app's helpers starts as, and
scripts/buildtools/helper_exes.py: how the build cuts the small named launchers."""
import struct
import sys

import pytest

from scripts.buildtools import helper_exes
from soundboard.core import helperexe


def test_source_run_starts_main_py():
    cmd = helperexe.command("--ytdl-worker")
    assert cmd[0] == sys.executable and cmd[1].endswith("main.py") and cmd[2] == "--ytdl-worker"


def test_build_starts_the_named_helper(tmp_path, monkeypatch):
    exe = tmp_path / "OnionBoard.exe"
    exe.write_bytes(b"")
    (tmp_path / "OnionBoardDownloads.exe").write_bytes(b"")
    (tmp_path / "OnionBoardDownloads.pkg").write_bytes(b"")
    (tmp_path / "OnionBoardSounds.exe").write_bytes(b"")   # its .pkg is missing
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert helperexe.command("--ytdl-worker") == [
        str(tmp_path / "OnionBoardDownloads.exe"), "--ytdl-worker"]
    # a helper without its program file, or none at all, still works: the app's own exe
    assert helperexe.command("--render-worker") == [str(exe), "--render-worker"]
    assert helperexe.command("--line-helper") == [str(exe), "--line-helper"]


def test_every_helper_has_its_own_name():
    stems = [s for s, _ in helperexe.HELPERS.values()]
    names = [n for _, n in helperexe.HELPERS.values()]
    assert len(set(stems)) == len(stems) and len(set(names)) == len(names)
    assert all(n.startswith("Onion Board ") for n in names)


def _fake_exe(front: bytes, archive_body: bytes) -> bytes:
    archive_len = len(archive_body) + helper_exes.COOKIE.size
    cookie = helper_exes.COOKIE.pack(helper_exes.MAGIC, archive_len, 0, 0, 313, b"python313.dll")
    return front + archive_body + cookie


def test_launcher_is_the_front_before_the_archive():
    front = b"MZ" + b"\0" * 98
    assert helper_exes.launcher(_fake_exe(front, b"x" * 500)) == front


def test_launcher_refuses_an_exe_without_an_archive():
    with pytest.raises(SystemExit):
        helper_exes.launcher(b"MZ" + b"\0" * 200)
    bad = b"MZ" + b"\0" * 10 + helper_exes.COOKIE.pack(helper_exes.MAGIC, 10**6, 0, 0, 313, b"")
    with pytest.raises(SystemExit):
        helper_exes.launcher(bad)


def test_sideload_mark_is_pyinstallers():
    assert len(helper_exes.SIDELOAD) == 8
    assert struct.calcsize("!8sIIii64s") == helper_exes.COOKIE.size
