"""Getting FFmpeg from the app (soundboard.ffmpegget): Settings > Data & quality.
The installer offers FFmpeg once; someone who skipped it had no way to add it later."""
import subprocess

import pytest

from soundboard import ffmpegget, library, net


def test_can_offer_only_when_it_is_missing_and_winget_is_here(monkeypatch):
    monkeypatch.setattr(library, "_ffmpeg", lambda: "ffmpeg.exe")
    assert not ffmpegget.can_offer()          # already have it
    monkeypatch.setattr(library, "_ffmpeg", lambda: None)
    monkeypatch.setattr(ffmpegget, "winget", lambda: None)
    assert not ffmpegget.can_offer()          # no winget to get it with
    monkeypatch.setattr(ffmpegget, "winget", lambda: "winget.exe")
    assert ffmpegget.can_offer()


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
