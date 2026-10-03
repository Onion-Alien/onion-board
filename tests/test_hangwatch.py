"""A frozen UI thread gets its stack logged, once per freeze."""
import logging
import time

from soundboard.hangwatch import HangWatch


def frozen_in_a_long_wait(seconds):
    time.sleep(seconds)


def test_a_frozen_window_logs_what_it_was_doing_once(qapp, caplog, tmp_path, monkeypatch):
    from soundboard import applog
    monkeypatch.setitem(applog._state, "log_path", tmp_path / "onionboard.log")
    caplog.set_level(logging.WARNING, logger="soundboard.hangwatch")
    hw = HangWatch(hang_s=0.4)
    try:
        frozen_in_a_long_wait(1.5)                 # the UI thread blocks: no beats
        assert hw.reports == 1
        assert "frozen_in_a_long_wait" in caplog.text
        assert hw.saved.parent == tmp_path / applog.REPORTS_DIR
        assert "froze for" in hw.saved.read_text(encoding="utf-8")
        assert "frozen_in_a_long_wait" in hw.saved.read_text(encoding="utf-8")
        end = time.monotonic() + 1.0                # beating again: no new report
        while time.monotonic() < end:
            qapp.processEvents()
            time.sleep(0.05)
        assert hw.reports == 1
    finally:
        hw.stop()


def test_a_responsive_window_logs_nothing(qapp, caplog):
    caplog.set_level(logging.WARNING, logger="soundboard.hangwatch")
    hw = HangWatch(hang_s=0.4)
    try:
        end = time.monotonic() + 1.2
        while time.monotonic() < end:
            qapp.processEvents()
            time.sleep(0.05)
        assert hw.reports == 0 and not caplog.text
    finally:
        hw.stop()
