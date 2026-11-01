"""Old download and self-test folders in %TEMP% are cleaned at start-up; nothing
else there is touched."""
import os
import sys
import tempfile
import time

import pytest

from soundboard.core import app


def test_only_our_old_temp_folders_are_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    now = time.time()
    old = now - app.TEMP_MAX_AGE_S - 60

    def made(name, folder=True, aged=True):
        p = tmp_path / name
        if folder:
            p.mkdir()
            (p / "a.webm").write_bytes(b"x")
        else:
            p.write_bytes(b"x")
        if aged:
            os.utime(p, (old, old))
        return p
    stale = made("sb-ytdl-abc")
    selftest = made("onionboard-selftest-abc")
    running = made("sb-ytdl-new", aged=False)              # a download going on now
    other = made("someone-elses-folder")
    near = made("xsb-ytdl-abc")                            # not the prefix
    a_file = made("sb-ytdl-note.txt", folder=False)
    assert app.clean_temp_leftovers(now) == 2
    assert not stale.exists() and not selftest.exists()
    assert running.exists() and other.exists() and near.exists() and a_file.exists()


def test_a_missing_temp_folder_is_no_error(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path / "nope"))
    assert app.clean_temp_leftovers() == 0


def test_tests_never_write_into_the_real_temp_folder(tmp_path):
    """Downloads from the tests' stand-in sites (ytdl's sb-ytdl-* folders) left
    hundreds of folders in the real %TEMP%: every test's temp files go in its own."""
    import tempfile as tf
    from pathlib import Path
    mine = tmp_path.parent   # pytest's own folder for this run, which it clears
    assert Path(tf.gettempdir()).is_relative_to(mine)
    assert Path(tf.mkdtemp(prefix="sb-ytdl-")).is_relative_to(mine)


@pytest.mark.skipif(sys.platform != "win32", reason="the app's process is looked up on Windows")
def test_a_download_folder_of_an_app_that_was_closed_goes_at_once(tmp_path, monkeypatch):
    """The app hard-closed mid-download left a big .part in %TEMP%: the next launch
    removes it, not a day later. A running app's (this one's, another's) stays."""
    import subprocess
    from soundboard.online import ytsites
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    done = subprocess.Popen([sys.executable, "-c", "pass"])
    done.wait()
    alive = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        mine = ytsites.temp_folder()
        (mine / "a.m4a.part").write_bytes(b"x")
        closed = tmp_path / f"sb-ytdl-{done.pid}-abc"
        pack = tmp_path / f"sb-linkpack-{done.pid}-abc"
        other = tmp_path / f"sb-ytdl-{alive.pid}-abc"
        for p in (closed, pack, other):
            p.mkdir()
            (p / "a.m4a.part").write_bytes(b"x")
        assert mine.name.startswith(f"sb-ytdl-{os.getpid()}-")
        assert app.clean_temp_leftovers() == 2
        assert not closed.exists() and not pack.exists()
        assert mine.exists() and other.exists()
    finally:
        alive.kill()
        alive.wait()
