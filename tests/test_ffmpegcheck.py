"""The start-up FFmpeg check (MainWindow.check_ffmpeg) and its bar: what stops working
without FFmpeg, one Fix it, Don't ask again. Never the real ffmpeg or winget."""
import threading

import pytest
from conftest import process_events, said
from PySide6.QtGui import QDesktopServices

from soundboard import ffmpegget, net, quality
from soundboard.library import SoundMeta
from soundboard.ui import mainwindow
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)


@pytest.fixture(autouse=True)
def _online():
    net.configure_features([], offline=False)
    quality.load({})
    yield
    net.configure_features()
    quality.load({})


def _found(w, state, why="it stops with an error"):
    h = ffmpegget.Health(state, "7.1" if state == ffmpegget.OK else "", why=why)
    w._on_ffmpeg(h, None)
    return h


def _needs_it(w):
    w.cfg.sounds.append(SoundMeta(id="m4a", name="Song", file="song.m4a"))


def test_the_check_runs_on_a_worker(window, qapp, monkeypatch):  # noqa: F811
    threads = []

    def check():
        threads.append(threading.current_thread())
        return ffmpegget.Health(ffmpegget.BROKEN, why="Windows won't start it")
    monkeypatch.setattr(ffmpegget, "check", check)
    window.check_ffmpeg()
    process_events(qapp, lambda: window.ffmpeg is not None)
    assert threads and threads[0] is not threading.main_thread()
    assert window.ffmpeg.state == ffmpegget.BROKEN and window.ff_bar.isVisibleTo(window)


def test_working_ffmpeg_shows_nothing(window):  # noqa: F811
    _needs_it(window)
    _found(window, ffmpegget.OK)
    assert not window.ff_bar.isVisibleTo(window)


def test_missing_ffmpeg_asks_only_when_something_needs_it(window):  # noqa: F811
    _found(window, ffmpegget.MISSING)
    assert not window.ff_bar.isVisibleTo(window)   # WAVs and MP3s only: no nagging
    quality.change(save_video=True)
    _found(window, ffmpegget.MISSING)
    assert window.ff_bar.isVisibleTo(window)
    quality.change(save_video=False)
    _needs_it(window)
    _found(window, ffmpegget.MISSING)
    assert window.ff_bar.isVisibleTo(window)
    assert "missing" in window.ff_lbl.text() and "video" in window.ff_lbl.text()
    assert window.ff_fix.text() == "Fix it"


def test_broken_ffmpeg_always_asks_and_says_why(window):  # noqa: F811
    _found(window, ffmpegget.BROKEN, "Windows won't start it")
    assert window.ff_bar.isVisibleTo(window)
    assert "Windows won't start it" in window.ff_lbl.text()


def test_fix_it_works_then_the_bar_goes(window, qapp, monkeypatch):  # noqa: F811
    _found(window, ffmpegget.BROKEN)
    asked = []

    def fix(force=False, progress=None):
        asked.append(force)
        h = ffmpegget.Health(ffmpegget.OK, "7.1", "ffmpeg.exe")
        monkeypatch.setattr(ffmpegget, "_last", h)
        return h
    monkeypatch.setattr(ffmpegget, "fix", fix)
    window.ff_fix.click()
    process_events(qapp, lambda: not window.ff_bar.isVisibleTo(window))
    assert asked == [False] and not window.ff_bar.isVisibleTo(window)
    assert "FFmpeg works now (version 7.1)" in said(window)


def test_fix_it_failing_says_so_on_the_bar(window, qapp, monkeypatch):  # noqa: F811
    _found(window, ffmpegget.BROKEN)

    def fix(force=False, progress=None):
        raise ffmpegget.GetError("winget couldn't install FFmpeg (it said: no network).")
    monkeypatch.setattr(ffmpegget, "fix", fix)
    window.ff_fix.click()
    process_events(qapp, lambda: "no network" in window.ff_lbl.text())
    assert window.ff_bar.isVisibleTo(window) and "no network" in window.ff_lbl.text()
    assert "no network" in said(window)
    process_events(qapp, lambda: window.ff_fix.text() == "Fix it", timeout=4)
    assert window.ff_fix.text() == "Fix it"     # ready to try again


@pytest.mark.parametrize("off", ["switch", "offline", "no-winget"])
def test_fix_it_links_to_ffmpeg_org_when_the_app_cant_install_it(window, monkeypatch, off):  # noqa: F811,E501
    if off == "switch":
        net.configure_features(["ffmpeg_download"], offline=False)
    elif off == "offline":
        net.configure_features([], offline=True)
    else:
        monkeypatch.setattr(ffmpegget, "_has_winget", False)
    opened, fixed = [], []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda u: opened.append(u.toString()) or True)
    monkeypatch.setattr(ffmpegget, "fix", lambda *a, **k: fixed.append(True))
    _found(window, ffmpegget.BROKEN)
    words = {"switch": "switched off", "offline": "Offline", "no-winget": "winget"}[off]
    assert words in window.ff_lbl.text()
    assert window.ff_fix.text() == "Open ffmpeg.org"
    window.ff_fix.click()
    assert opened == [ffmpegget.SITE] and fixed == []


def test_dont_ask_again_is_remembered(window):  # noqa: F811
    _found(window, ffmpegget.BROKEN)
    window.ff_never.click()
    assert not window.ff_bar.isVisibleTo(window)
    assert mainwindow.FF_ASK_OFF in window.cfg.tips_seen
    _found(window, ffmpegget.BROKEN)   # the next start's check
    assert not window.ff_bar.isVisibleTo(window)


def test_hide_is_until_the_next_start_only(window):  # noqa: F811
    _found(window, ffmpegget.BROKEN)
    window.ff_hide.click()
    _found(window, ffmpegget.BROKEN)
    assert not window.ff_bar.isVisibleTo(window)
    assert mainwindow.FF_ASK_OFF not in window.cfg.tips_seen


def test_icon_button_has_words(window):  # noqa: F811
    assert window.ff_hide.toolTip() and window.ff_hide.accessibleName()
