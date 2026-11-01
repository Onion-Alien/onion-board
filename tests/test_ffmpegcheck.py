"""The FFmpeg check (ui/window/ffmpegcontrol.py) and its bar: FFmpeg missing or broken is
got by itself once the window is up, with progress and Stop; when it can't be (Offline,
its switch, Low data mode) or it failed, the bar says what stops working, with Fix it.
Never the real ffmpeg, winget or a download."""
import threading
import time

import pytest
from conftest import process_events, said

from soundboard.online import ffmpegget, net
from soundboard.online import quality
from soundboard.core import usage
from soundboard.ui.window import ffmpegcontrol, mainwindow
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)

OK = ffmpegget.Health(ffmpegget.OK, "9.0.1", "ffmpeg.exe")


@pytest.fixture(autouse=True)
def _online():
    net.configure_features([], offline=False)
    quality.load({})
    yield
    net.configure_features()
    quality.load({})


def _up(widget) -> bool:
    """Shown in its bar (the page around it may be the test window's mini player)."""
    return not widget.isHidden()


def _found(w, state, why="it stops with an error"):
    h = OK if state == ffmpegget.OK else ffmpegget.Health(state, why=why)
    w.ffctl.on_answer(h, None)
    return h


def _fix(monkeypatch, err=None, wait: threading.Event | None = None, pct=None):
    """ffmpegget.fix: works (or raises ``err``); waits for ``wait``; reports ``pct``."""
    calls = []

    def fix(force=False, progress=None, stop=None):
        calls.append(force)
        if pct is not None and progress:
            progress(pct, 100)
        if wait is not None:
            while not wait.is_set():
                if stop is not None and stop.is_set():
                    raise ffmpegget.Stopped("Stopped.")
                time.sleep(0.01)
        if err:
            raise ffmpegget.GetError(err)
        monkeypatch.setattr(ffmpegget, "_last", OK)
        return OK
    monkeypatch.setattr(ffmpegget, "fix", fix)
    return calls


def test_the_check_is_answered_on_a_worker(window, qapp, monkeypatch):  # noqa: F811
    threads = []

    def answer():
        threads.append(threading.current_thread())
        return OK
    monkeypatch.setattr(ffmpegget, "answer", answer)
    window.check_ffmpeg()
    process_events(qapp, lambda: window.ffmpeg is not None)
    assert threads and threads[0] is not threading.main_thread()
    assert window.ffmpeg == OK and not _up(window.ff_bar)


@pytest.mark.parametrize("state", [ffmpegget.MISSING, ffmpegget.BROKEN])
def test_missing_or_broken_ffmpeg_is_got_by_itself(window, qapp, monkeypatch, state):  # noqa: F811
    go = threading.Event()
    calls = _fix(monkeypatch, wait=go, pct=42)
    _found(window, state)
    assert calls == [False]
    process_events(qapp, lambda: "42%" in window.ffctl.lbl.text())
    assert _up(window.ff_bar) and "Getting FFmpeg" in window.ffctl.lbl.text()
    assert _up(window.ffctl.stop_btn) and not _up(window.ffctl.fix_btn)
    go.set()
    process_events(qapp, lambda: not _up(window.ff_bar))
    assert not _up(window.ff_bar)
    assert "FFmpeg works now (version 9.0.1)" in said(window)
    _found(window, state)                     # broken again later this start: not again
    assert calls == [False] and _up(window.ffctl.fix_btn)


@pytest.mark.parametrize("why", ["offline", "switch", "low-data", "dont-ask"])
def test_not_got_by_itself_when_the_user_said_no(window, monkeypatch, why):  # noqa: F811
    calls = _fix(monkeypatch)
    if why == "offline":
        net.configure_features([], offline=True)
    elif why == "switch":
        net.configure_features(["ffmpeg_download"], offline=False)
    elif why == "low-data":
        quality.change(**quality.LOW)
    else:
        window.cfg.tips_seen.append(ffmpegcontrol.ASK_OFF)
    _found(window, ffmpegget.MISSING)
    assert calls == []
    if why == "dont-ask":
        assert not _up(window.ff_bar)
        return
    assert _up(window.ff_bar) and window.ffctl.fix_btn.text() == "Fix it"
    words = {"offline": "Offline", "switch": "switched off", "low-data": "Low data"}[why]
    assert words in window.ffctl.lbl.text()


def test_fix_it_switches_a_switched_off_download_back_on(window, qapp, monkeypatch):  # noqa: F811
    net.configure_features(["ffmpeg_download"], offline=False)
    window.cfg.net_off = ["ffmpeg_download"]
    calls = _fix(monkeypatch)
    _found(window, ffmpegget.MISSING)
    window.ffctl.fix_btn.click()
    assert "ffmpeg_download" not in window.cfg.net_off and net.allowed("ffmpeg_download")
    process_events(qapp, lambda: not _up(window.ff_bar))
    assert calls == [False] and "switched on again" in said(window)


def test_fix_it_offline_says_so_and_downloads_nothing(window, monkeypatch):  # noqa: F811
    net.configure_features([], offline=True)
    calls = _fix(monkeypatch)
    _found(window, ffmpegget.MISSING)
    window.ffctl.fix_btn.click()
    assert calls == [] and "Offline" in said(window)


def test_a_failed_fix_says_why_and_fix_it_tries_again(window, qapp, monkeypatch):  # noqa: F811
    calls = _fix(monkeypatch, err="Couldn't reach github.com (timed out).")
    _found(window, ffmpegget.BROKEN)
    process_events(qapp, lambda: "github.com" in window.ffctl.lbl.text())
    assert _up(window.ffctl.fix_btn) and "github.com" in said(window)
    calls = _fix(monkeypatch)
    window.ffctl.fix_btn.click()
    process_events(qapp, lambda: not _up(window.ff_bar))
    assert calls == [False]


def test_stop(window, qapp, monkeypatch):  # noqa: F811
    _fix(monkeypatch, wait=threading.Event())
    _found(window, ffmpegget.MISSING)
    window.ffctl.stop_btn.click()
    process_events(qapp, lambda: _up(window.ffctl.fix_btn))
    assert _up(window.ffctl.fix_btn) and not _up(window.ffctl.stop_btn)
    assert "missing" in window.ffctl.lbl.text() and "Stopped" not in said(window)


def test_dont_ask_again_is_remembered(window, monkeypatch):  # noqa: F811
    net.configure_features([], offline=True)   # (not got by itself)
    _found(window, ffmpegget.BROKEN)
    window.ffctl.never_btn.click()
    assert not _up(window.ff_bar)
    assert ffmpegcontrol.ASK_OFF in window.cfg.tips_seen
    _found(window, ffmpegget.BROKEN)   # the next start's check
    assert not _up(window.ff_bar)


def test_hide_is_until_the_next_start_only(window):  # noqa: F811
    net.configure_features([], offline=True)
    _found(window, ffmpegget.BROKEN)
    window.ffctl.hide_btn.click()
    _found(window, ffmpegget.BROKEN)
    assert not _up(window.ff_bar)
    assert ffmpegcontrol.ASK_OFF not in window.cfg.tips_seen


def test_icon_button_has_words(window):  # noqa: F811
    assert window.ffctl.hide_btn.toolTip() and window.ffctl.hide_btn.accessibleName()



def test_failed_get_then_retry_counts_recovery(window, qapp, monkeypatch):  # noqa: F811
    monkeypatch.setattr(usage, "enabled", lambda: True)
    monkeypatch.setattr(usage, "_used", set())
    _fix(monkeypatch, err="network unavailable")
    _found(window, ffmpegget.MISSING)
    process_events(qapp, lambda: not window.ffctl.getting)
    assert window.cfg.stats_ffmpeg_failed
    assert "get-ffmpeg-auto-failed" in window.cfg.stats_used
    assert "ffmpeg-recovered" not in window.cfg.stats_used
    _fix(monkeypatch)
    window.ffctl.fix_btn.click()
    process_events(qapp, lambda: not window.ffctl.getting)
    assert not window.cfg.stats_ffmpeg_failed
    assert "ffmpeg-recovered" in window.cfg.stats_used


def test_startup_broken_then_working_check_counts_recovery(window, monkeypatch):  # noqa: F811
    monkeypatch.setattr(usage, "enabled", lambda: True)
    monkeypatch.setattr(usage, "_used", set())
    window.ffctl.auto_tried = True   # test checks, without starting a download
    _found(window, ffmpegget.BROKEN)
    assert window.cfg.stats_ffmpeg_failed and "ffmpeg-broken" in window.cfg.stats_used
    _found(window, ffmpegget.OK)
    assert not window.cfg.stats_ffmpeg_failed
    assert "ffmpeg-recovered" in window.cfg.stats_used


def test_startup_check_that_timed_out_isnt_counted_broken(window, monkeypatch):  # noqa: F811
    """A check that only didn't answer in time (a new install's first run behind a virus
    scan) still gets FFmpeg by itself, but isn't counted as broken."""
    monkeypatch.setattr(usage, "enabled", lambda: True)
    monkeypatch.setattr(usage, "_used", set())
    window.ffctl.auto_tried = True   # test checks, without starting a download
    window.ffctl.on_answer(ffmpegget.Health(ffmpegget.BROKEN, path="ffmpeg.exe",
                                            why="it didn't answer", slow=True), None)
    assert not window.cfg.stats_ffmpeg_failed and "ffmpeg-broken" not in window.cfg.stats_used
    _found(window, ffmpegget.OK)
    assert "ffmpeg-recovered" not in window.cfg.stats_used


@pytest.mark.parametrize("err", [ffmpegget.Stopped("Stopped."), ffmpegget.GetError("failed")])
def test_failed_or_stopped_fix_cannot_recover_from_stale_health(window, monkeypatch, err):  # noqa: F811
    monkeypatch.setattr(usage, "enabled", lambda: True)
    monkeypatch.setattr(usage, "_used", set())
    window.cfg.stats_ffmpeg_failed = True
    window.ffctl.on_answer(OK, err)
    assert window.cfg.stats_ffmpeg_failed
    assert "ffmpeg-recovered" not in window.cfg.stats_used
    failed = not isinstance(err, ffmpegget.Stopped)
    assert ("get-ffmpeg-failed" in window.cfg.stats_used) == failed


def test_ffmpeg_lives_in_its_own_controller(window):  # noqa: F811
    """The FFmpeg check, fix and bar are one FfmpegControl the window owns, not ~200
    lines of MainWindow: the window only keeps its bar among the top bars and the two
    calls Settings makes."""
    assert isinstance(window.ffctl, ffmpegcontrol.FfmpegControl)
    assert window.ff_bar is window.ffctl.bar
    assert not [n for n in vars(window) if n.startswith("_ff_")]
    for gone in ("_on_ffmpeg", "_ffmpeg_news", "_show_ffmpeg_bar", "fix_ffmpeg",
                 "_may_get_ffmpeg", "_ffmpeg_never"):
        assert not hasattr(mainwindow.MainWindow, gone), gone
    assert window.ffmpeg is window.ffctl.health


def _flaky(monkeypatch, faults: list[str]):
    """ffmpegget.fix: fails with each of ``faults`` in turn (a GetError's fault), then works."""
    calls = []

    def fix(force=False, progress=None, stop=None):
        calls.append(force)
        if len(calls) <= len(faults):
            raise ffmpegget.GetError("Couldn't reach github.com (timed out).",
                                     faults[len(calls) - 1])
        monkeypatch.setattr(ffmpegget, "_last", OK)
        return OK
    monkeypatch.setattr(ffmpegget, "fix", fix)
    return calls


@pytest.fixture
def quick_retries(monkeypatch):
    monkeypatch.setattr(ffmpegcontrol, "RETRY_WAITS_S", (0.05, 0.05, 0.05))
    monkeypatch.setattr(ffmpegget, "connected", lambda: True)


def test_a_dropped_connection_is_tried_again_quietly(window, qapp, monkeypatch,  # noqa: F811
                                                     quick_retries):
    calls = _flaky(monkeypatch, ["own-URLError", "winget-exit-1 own-err-10054"])
    shown = []
    monkeypatch.setattr(window.ffctl.bar, "show", lambda: shown.append(1))
    _found(window, ffmpegget.MISSING)
    process_events(qapp, lambda: len(calls) == 3 and not window.ffctl.getting)
    assert len(calls) == 3 and shown == [1]   # the first try's progress only: none after
    assert "github.com" not in said(window) and "FFmpeg works now" in said(window)


def test_the_bar_shows_once_the_tries_again_are_used_up(window, qapp, monkeypatch,  # noqa: F811
                                                        quick_retries):
    calls = _flaky(monkeypatch, ["own-URLError"] * 9)
    _found(window, ffmpegget.MISSING)
    process_events(qapp, lambda: _up(window.ffctl.fix_btn))
    assert len(calls) == 1 + len(ffmpegcontrol.RETRY_WAITS_S)
    assert _up(window.ff_bar) and "github.com" in window.ffctl.lbl.text()
    assert said(window).count("github.com") == 1          # one toast, at the end


@pytest.mark.parametrize("fault", ["own-err-112", "own-still-err-193", "off",
                                   "own-http-404", "own-too-big"])
def test_what_waiting_cant_fix_isnt_tried_again(window, qapp, monkeypatch,  # noqa: F811
                                                quick_retries, fault):
    calls = _flaky(monkeypatch, [fault] * 9)
    _found(window, ffmpegget.MISSING)
    process_events(qapp, lambda: _up(window.ffctl.fix_btn))
    assert calls == [False] and _up(window.ff_bar)


def test_back_online_tries_again_at_once(window, qapp, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ffmpegcontrol, "RETRY_WAITS_S", (600,))
    monkeypatch.setattr(ffmpegcontrol, "ONLINE_POLL_MS", 20)
    window.ffctl.online_timer.setInterval(20)
    online = [False]
    monkeypatch.setattr(ffmpegget, "connected", lambda: online[0])
    calls = _flaky(monkeypatch, ["own-err-11001"])
    _found(window, ffmpegget.MISSING)
    process_events(qapp, lambda: window.ffctl.retry_timer.isActive())
    assert len(calls) == 1 and window.ffctl.retrying() and not _up(window.ff_bar)
    online[0] = True                                       # the Wi-Fi came back
    process_events(qapp, lambda: len(calls) == 2 and not window.ffctl.getting)
    assert len(calls) == 2 and "FFmpeg works now" in said(window)


def test_fix_it_during_a_wait_goes_at_once(window, qapp, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ffmpegcontrol, "RETRY_WAITS_S", (600,))
    monkeypatch.setattr(ffmpegget, "connected", lambda: True)
    calls = _flaky(monkeypatch, ["own-URLError"])
    _found(window, ffmpegget.MISSING)
    process_events(qapp, lambda: window.ffctl.retry_timer.isActive())
    window.click_ffmpeg_fix(window.ffctl.fix_btn) if hasattr(window, "click_ffmpeg_fix") \
        else window.ffctl.fix_clicked(window.ffctl.fix_btn)
    process_events(qapp, lambda: len(calls) == 2 and not window.ffctl.getting)
    assert len(calls) == 2 and not window.ffctl.retry_timer.isActive()


@pytest.mark.parametrize("fault, again", [
    ("own-URLError", True), ("own-err-10060", True), ("own-checksum", True),
    ("own-http-503", True), ("own-http-429", True), ("own-proxy", True),
    ("winget-exit-5 own-TimeoutError", True),
    ("off", False), ("own-err-112", False), ("own-err-28", False), ("own-err-5", False),
    ("own-http-404", False), ("own-too-big", False), ("own-still-err-193", False),
    ("own-unpack-err-5", False), ("", False)])
def test_worth_retrying(fault, again):
    assert ffmpegget.worth_retrying(ffmpegget.GetError("x", fault)) is again
    assert not ffmpegget.worth_retrying(ffmpegget.Stopped("x", fault))
