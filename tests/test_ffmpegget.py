"""Checking and getting FFmpeg from the app (soundboard.ffmpegget): the start-up check,
its bar's Fix it, and Settings > Data & quality. The installer offers FFmpeg once;
someone who skipped it (or whose copy broke) had no way to fix it later. No test runs the
real ffmpeg or winget."""
import subprocess

import pytest

from soundboard import ffmpegget, library, net


def test_get_runs_winget_and_returns_the_new_ffmpeg(monkeypatch):
    net.configure_features([], offline=False)
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
    net.configure_features([], offline=False)
    monkeypatch.setattr(ffmpegget, "winget", lambda: "winget.exe")
    monkeypatch.setattr(library, "_ffmpeg", lambda: None)   # still missing afterwards
    monkeypatch.setattr(ffmpegget.subprocess, "run",
                        lambda *a, **kw: subprocess.CompletedProcess(
                            a, 1, b"", b"No package found matching input criteria."))
    with pytest.raises(ffmpegget.GetError) as e:
        ffmpegget.get()
    assert "No package found matching input criteria." in str(e.value)


def test_get_is_refused_in_offline_mode(monkeypatch):
    net.configure_features([], offline=True)
    monkeypatch.setattr(ffmpegget, "winget", lambda: "winget.exe")
    with pytest.raises(ffmpegget.GetError, match="Offline"):
        ffmpegget.get()
    net.configure_features([], offline=False)


def test_get_is_refused_when_its_switch_is_off(monkeypatch):
    net.configure_features(["ffmpeg_download"], offline=False)
    monkeypatch.setattr(ffmpegget, "winget", lambda: "winget.exe")
    with pytest.raises(ffmpegget.GetError, match="switched off"):
        ffmpegget.get()
    net.configure_features()


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


def test_version_words(monkeypatch):
    assert ffmpegget._version("ffmpeg version n7.0.2 Copyright") == "7.0.2"
    assert ffmpegget._version("ffmpeg version 2024-10-01-git-abc Copyright") == "2024"
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


def test_why_cant_fix(monkeypatch):
    net.configure_features([], offline=False)
    monkeypatch.setattr(ffmpegget, "_has_winget", True)
    assert ffmpegget.why_cant_fix() == ""
    monkeypatch.setattr(ffmpegget, "_has_winget", False)
    assert "ffmpeg.org" in ffmpegget.why_cant_fix()
    monkeypatch.setattr(ffmpegget, "_has_winget", True)
    net.configure_features(["ffmpeg_download"], offline=False)
    assert "switched off" in ffmpegget.why_cant_fix()
    net.configure_features([], offline=True)
    assert "Offline" in ffmpegget.why_cant_fix()
    net.configure_features([], offline=False)


def _states(monkeypatch, *states):
    """check() answers these in turn (the last one again after that)."""
    seq = [ffmpegget.Health(s, "7.1" if s == ffmpegget.OK else "", why="x") for s in states]

    def check():
        h = seq.pop(0) if len(seq) > 1 else seq[0]
        monkeypatch.setattr(ffmpegget, "_last", h)
        return h
    monkeypatch.setattr(ffmpegget, "check", check)


def _winget_calls(monkeypatch):
    net.configure_features([], offline=False)
    monkeypatch.setattr(ffmpegget, "winget", lambda: "winget.exe")
    monkeypatch.setattr(library, "_ffmpeg", lambda: "ffmpeg.exe")
    calls = []

    def run(args, **kw):
        calls.append(args[1:])
        return subprocess.CompletedProcess(args, 0, b"", b"")
    monkeypatch.setattr(ffmpegget.subprocess, "run", run)
    return calls


def test_fix_reinstalls_a_broken_one_with_force(monkeypatch):
    calls = _winget_calls(monkeypatch)
    _states(monkeypatch, ffmpegget.BROKEN, ffmpegget.OK)
    assert ffmpegget.fix().state == ffmpegget.OK
    assert len(calls) == 1 and calls[0][0] == "install" and "--force" in calls[0]


def test_fix_takes_it_off_first_when_force_did_not_help(monkeypatch):
    calls = _winget_calls(monkeypatch)
    _states(monkeypatch, ffmpegget.BROKEN, ffmpegget.BROKEN, ffmpegget.OK)
    assert ffmpegget.fix().state == ffmpegget.OK
    assert [c[0] for c in calls] == ["install", "uninstall", "install"]


def test_fix_says_plainly_when_it_still_wont_start(monkeypatch):
    _winget_calls(monkeypatch)
    _states(monkeypatch, ffmpegget.BROKEN)
    with pytest.raises(ffmpegget.GetError, match="still won't start"):
        ffmpegget.fix()


def test_fix_does_nothing_when_it_works_unless_asked_to_reinstall(monkeypatch):
    calls = _winget_calls(monkeypatch)
    _states(monkeypatch, ffmpegget.OK)
    assert ffmpegget.fix().state == ffmpegget.OK and calls == []
    assert ffmpegget.fix(force=True).state == ffmpegget.OK
    assert calls and "--force" in calls[0]


def test_fix_is_refused_when_offline_or_switched_off(monkeypatch):
    calls = _winget_calls(monkeypatch)
    _states(monkeypatch, ffmpegget.MISSING)
    net.configure_features(["ffmpeg_download"], offline=False)
    with pytest.raises(ffmpegget.GetError, match="switched off"):
        ffmpegget.fix()
    net.configure_features([], offline=True)
    with pytest.raises(ffmpegget.GetError, match="Offline"):
        ffmpegget.fix()
    net.configure_features([], offline=False)
    assert calls == []
