"""soundboard.core.helperexe: which program each of the app's helpers starts as."""
import sys

from soundboard.core import helperexe


def test_source_run_starts_main_py():
    cmd = helperexe.command("--ytdl-worker")
    assert cmd[0] == sys.executable and cmd[1].endswith("main.py") and cmd[2] == "--ytdl-worker"


def test_build_starts_the_named_copy(tmp_path, monkeypatch):
    exe = tmp_path / "OnionBoard.exe"
    exe.write_bytes(b"")
    (tmp_path / "OnionBoardDownloads.exe").write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert helperexe.command("--ytdl-worker") == [
        str(tmp_path / "OnionBoardDownloads.exe"), "--ytdl-worker"]
    # a build without the copy (or one deleted) still works: the app's own exe
    assert helperexe.command("--render-worker") == [str(exe), "--render-worker"]


def test_every_helper_has_its_own_name():
    stems = list(helperexe.HELPERS.values())
    assert len(set(stems)) == len(stems)
    assert all(s.startswith("OnionBoard") and s != "OnionBoard" for s in stems)
