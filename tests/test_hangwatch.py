"""A frozen UI thread gets its stack logged, once per freeze."""
import logging
import time

from PySide6.QtCore import QCoreApplication, QEvent

from soundboard.hangwatch import HangWatch

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
    from soundboard import applog
    monkeypatch.setitem(applog._state, "log_path", tmp_path / "onionboard.log")
    caplog.set_level(logging.WARNING, logger="soundboard.hangwatch")
    settle(qapp)
    hw = HangWatch(hang_s=HANG_S)
    try:
        frozen_in_a_long_wait(hw, HANG_S * 2)      # the UI thread blocks: no beats
        assert hw.reports == 1
        assert "frozen_in_a_long_wait" in caplog.text
        assert hw.saved.parent == tmp_path / applog.REPORTS_DIR
        assert "froze for" in hw.saved.read_text(encoding="utf-8")
        assert "frozen_in_a_long_wait" in hw.saved.read_text(encoding="utf-8")
        beat_for(qapp, HANG_S)                     # beating again: no new report
        assert hw.reports == 1
    finally:
        hw.stop()


def test_a_responsive_window_logs_nothing(qapp, caplog):
    caplog.set_level(logging.WARNING, logger="soundboard.hangwatch")
    settle(qapp)
    hw = HangWatch(hang_s=HANG_S)
    try:
        beat_for(qapp, HANG_S * 1.5)
        assert hw.reports == 0 and not caplog.text
    finally:
        hw.stop()
