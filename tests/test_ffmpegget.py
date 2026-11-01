"""Checking, getting and repairing FFmpeg (soundboard.online.ffmpegget): the check behind the
loading screen, getting it by itself, the bar's Fix it and Settings > Data & quality.
No test runs the real ffmpeg or winget, or downloads anything (conftest blocks them)."""
import hashlib
import io
import subprocess
import threading
import zipfile

import pytest

from soundboard.online import ffmpegget, net
from soundboard.sounds import library

# the real steps, before conftest's _ffmpeg_works blocks them for every test
REAL = {name: getattr(ffmpegget, name)
        for name in ("_with_winget", "_own_copy", "_winget", "_download_once")}


@pytest.fixture(autouse=True)
def _online():
    net.configure_features([], offline=False)
    yield
    net.configure_features()


def _real(monkeypatch, *names):
    for name in names:
        monkeypatch.setattr(ffmpegget, name, REAL[name])


# --------------------------------------------------------------------------- winget

def test_get_runs_winget_and_returns_the_new_ffmpeg(monkeypatch):
    _real(monkeypatch, "_winget")
    have = []
    monkeypatch.setattr(ffmpegget, "winget", lambda: "winget.exe")
    monkeypatch.setattr(library, "_ffmpeg", lambda: "ffmpeg.exe" if have else None)
    calls = []

    def run(args, **kw):
        calls.append(args)
        have.append(True)                     # winget installs it
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(ffmpegget.subprocess, "run", run)
    progress = []
    assert ffmpegget.get(progress=lambda: progress.append(True)) == "ffmpeg.exe"
    assert progress == [True]
    assert calls and calls[0][1:4] == ["install", "--id", ffmpegget.PACKAGE]


def test_get_says_winget_could_not_install_it(monkeypatch):
    _real(monkeypatch, "_winget")
    monkeypatch.setattr(ffmpegget, "winget", lambda: "winget.exe")
    monkeypatch.setattr(library, "_ffmpeg", lambda: None)   # still missing afterwards
    monkeypatch.setattr(ffmpegget.subprocess, "run",
                        lambda *a, **kw: subprocess.CompletedProcess(
                            a, 1, b"", b"No package found matching input criteria."))
    with pytest.raises(ffmpegget.GetError) as e:
        ffmpegget.get()
    assert "No package found matching input criteria." in str(e.value)


def test_get_is_refused_offline_or_switched_off(monkeypatch):
    monkeypatch.setattr(ffmpegget, "winget", lambda: "winget.exe")
    net.configure_features([], offline=True)
    with pytest.raises(ffmpegget.GetError, match="Offline"):
        ffmpegget.get()
    net.configure_features(["ffmpeg_download"], offline=False)
    with pytest.raises(ffmpegget.GetError, match="switched off"):
        ffmpegget.get()


def test_winget_reinstalls_then_takes_it_off_first(monkeypatch):
    """--force first (winget can count a broken copy as installed); still broken:
    uninstall, then install fresh."""
    _real(monkeypatch, "_with_winget", "_winget")
    monkeypatch.setattr(ffmpegget, "winget", lambda: "winget.exe")
    monkeypatch.setattr(library, "_ffmpeg", lambda: "ffmpeg.exe")
    calls = []
    monkeypatch.setattr(ffmpegget.subprocess, "run", lambda args, **kw: (
        calls.append(args[1:]), subprocess.CompletedProcess(args, 0, b"", b""))[1])
    _states(monkeypatch, ffmpegget.BROKEN, ffmpegget.OK)
    assert ffmpegget._with_winget().state == ffmpegget.OK
    assert [c[0] for c in calls] == ["install", "uninstall", "install"]
    assert "--force" in calls[0]


# --------------------------------------------------------------------------- check

def _version_says(monkeypatch, rc=0, out=b"ffmpeg version 7.1-essentials_build-www.gyan.dev "
                  b"Copyright (c) 2000-2024", exc=None):
    calls = []

    def run(args, **kw):
        calls.append((args, kw))
        if exc is not None:
            raise exc
        return subprocess.CompletedProcess(args, rc, out, b"bad")
    monkeypatch.setattr(ffmpegget.subprocess, "run", run)
    return calls


def test_check_says_it_works_and_which_version(monkeypatch):
    monkeypatch.setattr(library, "_ffmpeg", lambda: "ffmpeg.exe")
    calls = _version_says(monkeypatch)
    h = ffmpegget._check()
    assert h == ffmpegget.Health(ffmpegget.OK, "7.1", "ffmpeg.exe")
    args, kw = calls[0]
    assert args == ["ffmpeg.exe", "-version"]          # hidden, and never hangs the check
    assert kw["timeout"] == ffmpegget.CHECK_TIMEOUT_S
    assert kw["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)


def test_version_words():
    assert ffmpegget._version("ffmpeg version n7.0.2 Copyright") == "7.0.2"
    assert ffmpegget._version("ffmpeg version 9.0.1-essentials_build-www.gyan.dev") == "9.0.1"
    assert ffmpegget._version("ffmpeg version N-117000-gabc Copyright") == "N-117000-gabc"
    assert ffmpegget._version("something else") == ""


def test_check_says_missing_when_there_is_none(monkeypatch, tmp_path):
    monkeypatch.setattr(library, "_ffmpeg", lambda: None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert ffmpegget._check() == ffmpegget.Health(ffmpegget.MISSING)


def test_check_says_broken_when_winget_left_half_of_it(monkeypatch, tmp_path):
    """The package folder is there without ffmpeg.exe: winget still thinks it's
    installed, so a plain install would skip it."""
    monkeypatch.setattr(library, "_ffmpeg", lambda: None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    (tmp_path / "Microsoft" / "WinGet" / "Packages" / (ffmpegget.PACKAGE + "_Microsoft.Winget"
                                                       ".Source_8wekyb3d8bbwe")).mkdir(parents=True)
    h = ffmpegget._check()
    assert h.state == ffmpegget.BROKEN and h.why


@pytest.mark.parametrize("how", ["oserror", "timeout", "exit-code"])
def test_check_says_broken_when_it_wont_start(monkeypatch, how):
    """Won't start (the wrong kind for this PC, a dead file), hangs, or stops with an
    error: all broken, with words for why."""
    monkeypatch.setattr(library, "_ffmpeg", lambda: "ffmpeg.exe")
    if how == "oserror":
        _version_says(monkeypatch, exc=OSError(193, "%1 is not a valid Win32 application"))
    elif how == "timeout":
        _version_says(monkeypatch, exc=subprocess.TimeoutExpired("ffmpeg", 8))
    else:
        _version_says(monkeypatch, rc=-1073741515, out=b"")
    h = ffmpegget._check()
    assert h.state == ffmpegget.BROKEN and h.path == "ffmpeg.exe" and h.why
    assert h.slow == (how == "timeout")   # only too slow to answer: not proof it's broken


def test_check_waits_out_a_first_run_behind_a_virus_scan():
    """A new install's first ffmpeg.exe run (100 MB) waits for the virus scan, on a PC
    busy with the app's own first start: 8 s could call a fine copy broken and fetch
    another ~100 MB one."""
    assert ffmpegget.CHECK_TIMEOUT_S >= 60


def test_the_check_behind_the_loading_screen_is_the_answer(monkeypatch):
    runs = []

    def check():
        runs.append(threading.current_thread().name)
        h = ffmpegget.Health(ffmpegget.MISSING)
        monkeypatch.setattr(ffmpegget, "_last", h)
        return h
    monkeypatch.setattr(ffmpegget, "check", check)
    monkeypatch.setattr(ffmpegget, "_early", threading.Thread(target=lambda: check()))
    ffmpegget._early.start()
    assert ffmpegget.answer().state == ffmpegget.MISSING
    assert len(runs) == 1                     # not checked twice


def test_library_uses_the_apps_own_copy_first(monkeypatch, tmp_path):
    if library.os.name != "nt":
        pytest.skip("the app's own copy is a Windows build")
    monkeypatch.setattr(library, "APP_DIR", tmp_path)
    own = tmp_path / "ffmpeg" / "bin" / "ffmpeg.exe"
    own.parent.mkdir(parents=True)
    own.write_bytes(b"MZ")
    assert library._ffmpeg() == str(own)


def test_library_finds_wingets_copy_without_a_link(monkeypatch, tmp_path):
    """winget without the right to make links puts the package's bin folder on PATH
    instead of WinGet\\Links: an app started before that (by the installer) must still
    find it, not call it broken."""
    monkeypatch.setattr(library, "APP_DIR", tmp_path / "app")
    monkeypatch.setattr(library.shutil, "which", lambda name: None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ProgramFiles", raising=False)
    pkg = (tmp_path / "Microsoft" / "WinGet" / "Packages"
           / (ffmpegget.PACKAGE + "_Microsoft.Winget.Source_8wekyb3d8bbwe"))
    pkg.mkdir(parents=True)
    assert library._ffmpeg() is None         # half there: check() says broken
    exe = pkg / "ffmpeg-9.0.1-essentials_build" / "bin" / "ffmpeg.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    assert library._ffmpeg() == str(exe)


def test_library_skips_a_winget_link_windows_cant_look_at(monkeypatch, tmp_path):
    """2.2.0: is_file() on a WinGet link Windows couldn't follow raised OSError out of
    the FFmpeg check; it counts as not there."""
    monkeypatch.setattr(library, "APP_DIR", tmp_path / "app")
    monkeypatch.setattr(library.shutil, "which", lambda name: None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ProgramFiles", raising=False)
    real = library.Path.is_file

    def is_file(self):
        if self.name == "ffmpeg.exe" and self.parent.name == "Links":
            raise OSError(22, "The file cannot be accessed by the system")
        return real(self)
    monkeypatch.setattr(library.Path, "is_file", is_file)
    assert library._ffmpeg() is None


def test_why_not(monkeypatch):
    assert ffmpegget.why_not() == ""
    net.configure_features(["ffmpeg_download"], offline=False)
    assert "switched off" in ffmpegget.why_not()
    net.configure_features([], offline=True)
    assert "Offline" in ffmpegget.why_not()


# --------------------------------------------------------------------------- fix

def _states(monkeypatch, *states):
    """check() answers these in turn (the last one again after that)."""
    seq = [ffmpegget.Health(s, "9.0.1" if s == ffmpegget.OK else "", why="x") for s in states]

    def check():
        h = seq.pop(0) if len(seq) > 1 else seq[0]
        monkeypatch.setattr(ffmpegget, "_last", h)
        return h
    monkeypatch.setattr(ffmpegget, "check", check)


def _steps(monkeypatch, winget_ok=True, own_ok=True):
    did = []
    ok = ffmpegget.Health(ffmpegget.OK, "9.0.1")

    def with_winget():
        did.append("winget")
        if not winget_ok:
            raise ffmpegget.GetError("winget couldn't install FFmpeg (it said: nope).")
        ffmpegget._last = ok
        return ok

    def own_copy(progress, stop):
        did.append("own")
        if not own_ok:
            raise ffmpegget.GetError("Couldn't reach github.com (timed out).")
        return ok
    monkeypatch.setattr(ffmpegget, "_with_winget", with_winget)
    monkeypatch.setattr(ffmpegget, "_own_copy", own_copy)
    monkeypatch.setattr(ffmpegget, "winget", lambda: "winget.exe")
    return did


def test_fix_uses_winget_when_it_works(monkeypatch):
    did = _steps(monkeypatch)
    _states(monkeypatch, ffmpegget.BROKEN)
    assert ffmpegget.fix().state == ffmpegget.OK and did == ["winget"]


def test_fix_falls_back_to_the_apps_own_download(monkeypatch):
    did = _steps(monkeypatch, winget_ok=False)
    _states(monkeypatch, ffmpegget.MISSING)
    assert ffmpegget.fix().state == ffmpegget.OK and did == ["winget", "own"]


def test_fix_downloads_it_without_winget(monkeypatch):
    did = _steps(monkeypatch)
    monkeypatch.setattr(ffmpegget, "winget", lambda: None)
    _states(monkeypatch, ffmpegget.MISSING)
    assert ffmpegget.fix().state == ffmpegget.OK and did == ["own"]


def test_fix_never_lets_winget_skip_the_proxy_or_tor(monkeypatch):
    """winget goes direct: with a proxy or Tor set, only the app's own download, which
    follows Connection."""
    did = _steps(monkeypatch)
    monkeypatch.setattr(net, "mode", lambda: net.TOR)
    _states(monkeypatch, ffmpegget.MISSING)
    assert ffmpegget.fix().state == ffmpegget.OK and did == ["own"]


def test_fix_says_so_when_nothing_worked(monkeypatch):
    _steps(monkeypatch, winget_ok=False, own_ok=False)
    _states(monkeypatch, ffmpegget.MISSING)
    with pytest.raises(ffmpegget.GetError, match="github.com"):
        ffmpegget.fix()


def test_fix_does_nothing_when_it_works_unless_asked_to_reinstall(monkeypatch):
    did = _steps(monkeypatch)
    _states(monkeypatch, ffmpegget.OK)
    assert ffmpegget.fix().state == ffmpegget.OK and did == []
    assert ffmpegget.fix(force=True).state == ffmpegget.OK and did == ["winget"]


def test_fix_is_refused_offline_or_switched_off(monkeypatch):
    did = _steps(monkeypatch)
    _states(monkeypatch, ffmpegget.MISSING)
    net.configure_features(["ffmpeg_download"], offline=False)
    with pytest.raises(ffmpegget.GetError, match="switched off"):
        ffmpegget.fix()
    net.configure_features([], offline=True)
    with pytest.raises(ffmpegget.GetError, match="Offline"):
        ffmpegget.fix()
    assert did == []


def test_stop_after_winget_skips_the_download(monkeypatch):
    did = _steps(monkeypatch, winget_ok=False)
    _states(monkeypatch, ffmpegget.MISSING)
    stop = threading.Event()
    stop.set()
    with pytest.raises(ffmpegget.Stopped):
        ffmpegget.fix(stop=stop)
    assert did == ["winget"]


# --------------------------------------------------------------------------- own copy

def test_download_retries_then_tries_the_other_source(monkeypatch, tmp_path):
    monkeypatch.setattr(ffmpegget, "RETRY_WAIT_S", (0.0, 0.0))
    tried = []

    def once(url, to, progress, stop):
        tried.append(url)
        if len(tried) < ffmpegget.TRIES + 1:      # every try on the first source fails
            raise ffmpegget.GetError("Couldn't reach github.com (reset).")
    monkeypatch.setattr(ffmpegget, "_download_once", once)
    ffmpegget.download(tmp_path / "z.zip")
    assert tried == [ffmpegget.URLS[0]] * ffmpegget.TRIES + [ffmpegget.URLS[1]]


def test_download_says_why_each_source_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(ffmpegget, "RETRY_WAIT_S", (0.0, 0.0))

    def once(url, to, progress, stop):
        if "github.com" in url:
            raise ffmpegget.GetError("Couldn't reach github.com (reset)")
        raise ffmpegget.GetError("www.gyan.dev said 404 Not Found.")
    monkeypatch.setattr(ffmpegget, "_download_once", once)
    with pytest.raises(ffmpegget.GetError) as e:
        ffmpegget.download(tmp_path / "z.zip")
    assert str(e.value) == ("Couldn't reach github.com (reset). "
                            "www.gyan.dev said 404 Not Found.")


def test_download_says_a_shared_reason_once(monkeypatch, tmp_path):
    monkeypatch.setattr(ffmpegget, "RETRY_WAIT_S", (0.0, 0.0))

    def once(url, to, progress, stop):
        raise ffmpegget.GetError("Offline mode is on.")
    monkeypatch.setattr(ffmpegget, "_download_once", once)
    with pytest.raises(ffmpegget.GetError) as e:
        ffmpegget.download(tmp_path / "z.zip")
    assert str(e.value) == "Offline mode is on."


def test_download_stops_at_once(monkeypatch, tmp_path):
    tried = []

    def once(url, to, progress, stop):
        tried.append(url)
        raise ffmpegget.Stopped("Stopped.")
    monkeypatch.setattr(ffmpegget, "_download_once", once)
    with pytest.raises(ffmpegget.Stopped):
        ffmpegget.download(tmp_path / "z.zip")
    assert len(tried) == 1


def test_download_switched_off_gives_up_at_once(monkeypatch, tmp_path):
    _real(monkeypatch, "_download_once")
    tried = []

    def urlopen(req, **kw):
        tried.append(req.full_url)
        raise net.FeatureOff("Downloading FFmpeg is switched off.")
    monkeypatch.setattr(ffmpegget.net, "urlopen", urlopen)
    monkeypatch.setattr(ffmpegget, "RETRY_WAIT_S", (30.0, 30.0))   # never waited
    with pytest.raises(ffmpegget.SwitchedOff) as e:
        ffmpegget.download(tmp_path / "z.zip")
    assert len(tried) == 1
    assert "switched off" in str(e.value)


class _Resp(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __exit__(self, *a):
        return False


def test_download_once_checks_the_checksum(monkeypatch, tmp_path):
    _real(monkeypatch, "_download_once")
    data = b"x" * 1000
    monkeypatch.setattr(net, "urlopen", lambda *a, **k: _Resp(data))
    to = tmp_path / "z.zip"
    with pytest.raises(ffmpegget.GetError, match="checksum"):
        ffmpegget._download_once(ffmpegget.URLS[0], to, None, None)
    monkeypatch.setattr(ffmpegget, "SHA256", hashlib.sha256(data).hexdigest())
    seen = []
    ffmpegget._download_once(ffmpegget.URLS[0], to, lambda d, t: seen.append((d, t)), None)
    assert to.read_bytes() == data and seen[-1] == (1000, 1000)


def test_unpack_takes_only_the_named_files(tmp_path):
    z = tmp_path / "z.zip"
    with zipfile.ZipFile(z, "w") as f:
        for name in ffmpegget.KEEP:
            f.writestr(name, b"data:" + name.encode())
        f.writestr("../../evil.exe", b"no")
    dest = ffmpegget.unpack(z, tmp_path / "bin")
    assert sorted(p.name for p in dest.iterdir()) == sorted(ffmpegget.KEEP.values())
    assert not (tmp_path.parent / "evil.exe").exists()


def test_unpack_says_what_is_missing(tmp_path):
    z = tmp_path / "z.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("nothing", b"")
    with pytest.raises(ffmpegget.GetError, match="ffmpeg.exe"):
        ffmpegget.unpack(z, tmp_path / "bin")
    assert not (tmp_path / "bin").exists()


def test_unpack_waits_for_an_antivirus_holding_the_new_files(tmp_path, monkeypatch):
    """Windows denies moving the fresh folder while an antivirus scans its ffmpeg.exe
    (err-5): unpack tries again for a few seconds instead of failing at once."""
    z = tmp_path / "z.zip"
    with zipfile.ZipFile(z, "w") as f:
        for name in ffmpegget.KEEP:
            f.writestr(name, b"x")
    (tmp_path / "bin").mkdir()
    monkeypatch.setattr(ffmpegget, "RENAME_WAIT_S", 0, raising=False)
    real, denied = ffmpegget.Path.rename, [3]

    def rename(self, to):
        if self.name == "bin.partial" and denied[0]:
            denied[0] -= 1
            raise PermissionError(13, "Access is denied")
        return real(self, to)
    monkeypatch.setattr(ffmpegget.Path, "rename", rename)
    dest = ffmpegget.unpack(z, tmp_path / "bin")
    assert sorted(p.name for p in dest.iterdir()) == sorted(ffmpegget.KEEP.values())
    assert not (tmp_path / "bin.old").exists() and not (tmp_path / "bin.partial").exists()


# --------------------------------------------------------------------------- follow the app

def test_the_apps_own_copy_follows_the_app(monkeypatch, tmp_path):
    """An app update naming a newer FFmpeg replaces the app's own older copy; a copy
    from winget (or one already at VERSION) is left alone."""
    monkeypatch.setattr(library, "APP_DIR", tmp_path)
    own = str(ffmpegget.own_dir() / "ffmpeg.exe")
    got = []

    def own_copy(progress, stop):
        got.append(1)
        return ffmpegget.Health(ffmpegget.OK, ffmpegget.VERSION, own)
    monkeypatch.setattr(ffmpegget, "_own_copy", own_copy)
    for path, version, fetched in ((own, "9.0.1", True), (own, ffmpegget.VERSION, False),
                                   (str(tmp_path / "WinGet" / "ffmpeg.exe"), "8.1.1", False)):
        got.clear()
        monkeypatch.setattr(ffmpegget, "check",
                            lambda p=path, v=version: ffmpegget.Health(ffmpegget.OK, v, p))
        h = ffmpegget.update_own()
        assert bool(got) is fetched and (h is not None) is fetched
    monkeypatch.setattr(ffmpegget, "check",
                        lambda: ffmpegget.Health(ffmpegget.OK, "9.0.1", own))
    got.clear()
    net.configure_features(["ffmpeg_download"], offline=False)   # switched off: never
    assert ffmpegget.update_own() is None and not got


# --------------------------------------------------------------------------- fault words

def test_check_says_why_it_is_broken_for_the_count(monkeypatch):
    """The count's ffmpeg-broken couldn't tell an antivirus from a missing DLL: the
    check keeps Windows' error or the exit code (never a path)."""
    monkeypatch.setattr(library, "_ffmpeg", lambda: "ffmpeg.exe")
    e = OSError(22, "%1 is not a valid Win32 application")
    e.winerror = 193
    _version_says(monkeypatch, exc=e)
    assert ffmpegget._check().fault == "err-193"
    _version_says(monkeypatch, rc=-1073741515, out=b"")   # a DLL missing
    assert ffmpegget._check().fault == "exit-3221225781"


def test_get_failed_keeps_each_steps_fault(monkeypatch):
    """winget's exit code and why the app's own download failed, both."""
    _real(monkeypatch, "_winget", "_with_winget")
    monkeypatch.setattr(ffmpegget, "winget", lambda: "winget.exe")
    monkeypatch.setattr(library, "_ffmpeg", lambda: None)
    monkeypatch.setattr(ffmpegget.subprocess, "run",
                        lambda *a, **kw: subprocess.CompletedProcess(a, 1, b"", b"no"))
    with pytest.raises(ffmpegget.GetError) as e:
        ffmpegget.get()
    assert e.value.fault == "winget-exit-1"

    def own_copy(progress, stop):
        raise ffmpegget.GetError("github.com said 403 Forbidden.", "own-http-403")
    monkeypatch.setattr(ffmpegget, "_own_copy", own_copy)
    _states(monkeypatch, ffmpegget.MISSING)
    with pytest.raises(ffmpegget.GetError) as e:
        ffmpegget.fix()
    assert e.value.fault == "winget-exit-1 own-http-403"


def test_download_once_names_the_status(monkeypatch, tmp_path):
    import urllib.error
    _real(monkeypatch, "_download_once")

    def refused(*a, **kw):
        raise urllib.error.HTTPError("https://example.com/f.zip", 403, "Forbidden", {}, None)
    monkeypatch.setattr(net, "urlopen", refused)
    with pytest.raises(ffmpegget.GetError) as e:
        ffmpegget._download_once("https://example.com/f.zip", tmp_path / "f", None, None)
    assert e.value.fault == "own-http-403"


def _aged(path, seconds=ffmpegget.TIDY_AFTER_S + 60):
    import os
    import time
    t = time.time() - seconds
    os.utime(path, (t, t))


def test_start_up_clears_what_a_fix_cut_short_left(app_dir):
    """The app ended mid-download / mid-unpack: the zip part and bin.partial go, even
    when FFmpeg is found elsewhere and no new fix ever replaces them."""
    folder = ffmpegget.own_dir().parent
    (folder / "bin.partial").mkdir(parents=True)
    (folder / "bin.partial" / "ffmpeg.exe").write_bytes(b"half")
    (folder / (ffmpegget.ZIP + ".partial")).write_bytes(b"half a zip")
    _aged(folder / "bin.partial")
    _aged(folder / (ffmpegget.ZIP + ".partial"))
    ffmpegget.tidy()
    assert not any(folder.iterdir())


def test_start_up_puts_back_a_copy_a_cut_short_swap_moved_aside(app_dir):
    folder = ffmpegget.own_dir().parent
    (folder / "bin.old").mkdir(parents=True)
    (folder / "bin.old" / "ffmpeg.exe").write_bytes(b"works")
    _aged(folder / "bin.old")
    ffmpegget.tidy()
    assert (ffmpegget.own_dir() / "ffmpeg.exe").read_bytes() == b"works"
    assert not (folder / "bin.old").exists()


def test_start_up_leaves_a_fix_that_is_still_going_alone(app_dir):
    folder = ffmpegget.own_dir().parent
    (folder / "bin.partial").mkdir(parents=True)
    (folder / (ffmpegget.ZIP + ".partial")).write_bytes(b"arriving")   # fresh: in use
    ffmpegget.tidy()
    assert (folder / "bin.partial").is_dir() and (folder / (ffmpegget.ZIP + ".partial")).is_file()
    _aged(folder / "bin.partial")
    with ffmpegget._fixing:   # a fix is going: nothing is touched
        ffmpegget.tidy()
    assert (folder / "bin.partial").is_dir()
