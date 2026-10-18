"""A frozen UI thread gets its stack logged, once per freeze."""
import logging
import re
import sys
import threading
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from soundboard.core.hangwatch import HangWatch

# Long enough that a busy machine (the full suite on every core) or another test's
# leftover events can't pass for a freeze; the freeze below is twice as long.
HANG_S = 1.0


def frozen_in_a_long_wait(hw, seconds, cap=10.0):
    """Block the UI thread for `seconds`, and on past that until the watch has
    reported (a loaded CI runner can starve its thread well past the freeze)."""
    time.sleep(seconds)
    end = time.monotonic() + cap
    while hw.reports == 0 and time.monotonic() < end:
        time.sleep(0.05)


def settle(qapp):
    """Run what earlier tests left queued (deletes, timers) before the watch starts:
    tearing down a big widget can keep the UI thread busy long enough to count."""
    for _ in range(3):
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        qapp.processEvents()


def beat_for(qapp, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.05)


def test_a_frozen_window_logs_what_it_was_doing_once(qapp, caplog, tmp_path, monkeypatch):
    from soundboard.core import applog
    monkeypatch.setitem(applog._state, "log_path", tmp_path / "onionboard.log")
    caplog.set_level(logging.WARNING, logger="soundboard.core.hangwatch")
    settle(qapp)
    hw = HangWatch(hang_s=HANG_S)
    try:
        frozen_in_a_long_wait(hw, HANG_S * 2)      # the UI thread blocks: no beats
        assert hw.reports == 1
        assert "frozen_in_a_long_wait" in caplog.text
        assert hw.saved.parent == tmp_path / applog.REPORTS_DIR
        assert "froze for" in hw.saved.read_text(encoding="utf-8")
        assert "frozen_in_a_long_wait" in hw.saved.read_text(encoding="utf-8")
        assert "Lasted:   still frozen" in hw.saved.read_text(encoding="utf-8")
        beat_for(qapp, HANG_S)                     # beating again: no new report
        assert hw.reports == 1
        # ...and the report says how long it lasted in all
        assert re.search(r"^Lasted:   \d+ s$", hw.saved.read_text(encoding="utf-8"), re.M)
    finally:
        hw.stop()


@pytest.mark.skipif(sys.platform != "win32", reason="thread CPU times are read on Windows")
def test_a_freeze_report_says_how_busy_each_thread_was(qapp, tmp_path, monkeypatch):
    """A window asleep (waiting) uses no CPU; a thread spinning uses a whole core."""
    from soundboard.core import applog
    monkeypatch.setitem(applog._state, "log_path", tmp_path / "onionboard.log")
    go = threading.Event()

    def spinning_worker():
        while not go.is_set():
            sum(range(1000))
    worker = threading.Thread(target=spinning_worker, name="spinner", daemon=True)
    worker.start()
    settle(qapp)
    hw = HangWatch(hang_s=HANG_S)
    try:
        frozen_in_a_long_wait(hw, HANG_S * 2)
        text = hw.saved.read_text(encoding="utf-8")
        assert int(re.search(r"^Window CPU: (\d+)%", text, re.M).group(1)) < 30
        assert int(re.search(r'^Thread "spinner" \(\d+\), (\d+)% CPU:', text,
                             re.M).group(1)) >= 30
    finally:
        hw.stop()
        go.set()
        worker.join()


def waiting_in_a_worker(go):
    go.wait()


class Dialog:
    """Stands in for a modal dialog: exec() runs native code with no Python frame."""
    exec = staticmethod(time.sleep)


def test_a_freeze_report_shows_the_other_threads_too(qapp, tmp_path, monkeypatch):
    from soundboard.core import applog
    monkeypatch.setitem(applog._state, "log_path", tmp_path / "onionboard.log")
    go = threading.Event()
    worker = threading.Thread(target=waiting_in_a_worker, args=(go,), name="busy-worker",
                              daemon=True)
    worker.start()
    settle(qapp)
    hw = HangWatch(hang_s=HANG_S)
    try:
        frozen_in_a_long_wait(hw, HANG_S * 2)
        text = hw.saved.read_text(encoding="utf-8")
        assert text.index("frozen_in_a_long_wait") < text.index("Other threads")
        assert "busy-worker" in text and "waiting_in_a_worker" in text
        assert 'Thread "hangwatch"' not in text                        # not itself
        assert "window's own event loop" not in text
        assert str(Path.home()).lower() not in text.lower()          # scrubbed throughout
    finally:
        hw.stop()
        go.set()
        worker.join()


def test_a_freeze_inside_a_dialogs_exec_says_so(qapp, tmp_path, monkeypatch):
    from soundboard.core import applog
    monkeypatch.setitem(applog._state, "log_path", tmp_path / "onionboard.log")
    settle(qapp)
    hw = HangWatch(hang_s=HANG_S)
    try:
        Dialog.exec(HANG_S * 2)
        frozen_in_a_long_wait(hw, 0)
        text = hw.saved.read_text(encoding="utf-8")
        assert "it was inside a window's own event loop" in text
    finally:
        hw.stop()


def test_a_responsive_window_logs_nothing(qapp, caplog):
    caplog.set_level(logging.WARNING, logger="soundboard.core.hangwatch")
    settle(qapp)
    hw = HangWatch(hang_s=HANG_S)
    try:
        beat_for(qapp, HANG_S * 1.5)
        assert hw.reports == 0 and not caplog.text
    finally:
        hw.stop()


class SleepingPC:
    """An awake-time clock: it stands still while `asleep` (the PC sleeping with the
    app open: every thread stopped, the window too)."""

    def __init__(self):
        self.asleep, self._held, self._at = False, 0.0, None

    def __call__(self) -> float:
        now = time.monotonic()
        if self.asleep:
            if self._at is None:
                self._at = now
            return self._at - self._held
        if self._at is not None:
            self._held += now - self._at
            self._at = None
        return now - self._held


def test_time_the_pc_slept_is_no_freeze(qapp, tmp_path, monkeypatch):
    """2.0.4 counted every sleep with the app open as a freeze of the whole sleep,
    stuck wherever the window happened to be."""
    from soundboard.core import applog
    monkeypatch.setitem(applog._state, "log_path", tmp_path / "onionboard.log")
    settle(qapp)
    pc = SleepingPC()
    hw = HangWatch(hang_s=HANG_S, clock=pc)
    try:
        pc.asleep = True
        time.sleep(HANG_S * 3)          # asleep: no beats, but no awake time either
        pc.asleep = False
        beat_for(qapp, HANG_S)
        assert hw.reports == 0
        frozen_in_a_long_wait(hw, HANG_S * 2)      # a real freeze still counts
        assert hw.reports == 1
    finally:
        hw.stop()


def test_the_awake_clock_moves_with_time():
    from soundboard.core.hangwatch import awake_clock
    clock = awake_clock()
    a = clock()
    time.sleep(0.2)
    assert 0.1 < clock() - a < 5


@pytest.mark.skipif(sys.platform != "win32", reason="Sleep without letting go of the GIL")
def test_a_freeze_that_held_every_thread_says_so(qapp, tmp_path, monkeypatch):
    """One thread keeping Python's lock while it waits stops the watch too: the report
    tells that apart from the window alone being stuck."""
    import ctypes

    from soundboard.core import applog, hangwatch
    monkeypatch.setitem(applog._state, "log_path", tmp_path / "onionboard.log")
    settle(qapp)
    hw = HangWatch(hang_s=HANG_S)
    try:
        ctypes.PyDLL("kernel32").Sleep(int(HANG_S * 2500))   # holds the GIL throughout
        frozen_in_a_long_wait(hw, 0)
        assert hangwatch.ALL_HELD_NOTE in hw.saved.read_text(encoding="utf-8")
        beat_for(qapp, HANG_S)
        frozen_in_a_long_wait(hw, HANG_S * 2)      # the window alone: no such note
        assert hw.reports == 2
        assert hangwatch.ALL_HELD_NOTE not in hw.saved.read_text(encoding="utf-8")
    finally:
        hw.stop()


def test_a_freeze_report_says_how_full_the_pcs_memory_was(qapp, tmp_path, monkeypatch):
    """An idle window stuck at random lines for 10-30 s, over and over on one PC, looked
    like Windows swapping the app to disk: the report now says how full memory was and
    how fast the app page-faulted while it was stuck."""
    from soundboard.core import applog, hangwatch
    monkeypatch.setitem(applog._state, "log_path", tmp_path / "onionboard.log")
    faults = iter([1000, 1000 + 3000])   # before and after the half-second sample
    monkeypatch.setattr(hangwatch, "memory_load", lambda: 93)
    monkeypatch.setattr(hangwatch, "page_faults", lambda: next(faults))
    settle(qapp)
    hw = HangWatch(hang_s=HANG_S)
    try:
        frozen_in_a_long_wait(hw, HANG_S * 2)
        text = hw.saved.read_text(encoding="utf-8")
        assert re.search(r"^PC memory in use: 93%$", text, re.M)
        assert re.search(r"^Page faults: 6000/s$", text, re.M)
    finally:
        hw.stop()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' own figures")
def test_the_memory_figures_read_on_windows():
    from soundboard.core import hangwatch
    load, faults = hangwatch.memory_load(), hangwatch.page_faults()
    assert 0 <= load <= 100 and faults > 0
