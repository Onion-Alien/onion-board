"""The watchdog straight into the mic: a stopped feed is reopened after DIRECT_STALL_S
(not STALL_S), checked every tick, never right after the whole app was held up, and
each stall leaves one thread dump next to the log."""
import logging
import threading
import time

import numpy as np

from soundboard.audio import enginedevices
from soundboard.audio.engine import Engine
from soundboard.audio.engineparts import DIRECT_STALL_S, STALL_DUMP_MAX, STALL_S
from soundboard.core import bootmark


class FakeStream:
    closed = False

    def stop(self):
        pass

    def close(self):
        self.closed = True


def direct_engine():
    """An engine sending straight into the mic, with a stand-in stream; reopening it
    only records the call."""
    e = Engine()
    e.main_stream, e.names["main"], e.main_direct = FakeStream(), "Your mic (no cable)", True
    e.reopened = []
    e.set_main_device = e.reopened.append
    e._direct_seen = time.monotonic()   # the tick before ran on time
    return e


def test_a_stopped_feed_is_reopened_after_half_a_second(tmp_path, monkeypatch):
    monkeypatch.setattr(bootmark, "app_dir", lambda: tmp_path)
    e = direct_engine()
    e._last_cb["main"] = time.monotonic() - DIRECT_STALL_S + 0.2
    e.check_direct()
    assert e.devices.wait(5) and e.reopened == []        # a healthy wait: left alone
    e._last_cb["main"] = time.monotonic() - DIRECT_STALL_S - 0.1
    e._direct_seen = time.monotonic()
    e.check_direct()
    assert e.devices.wait(5)
    assert e.reopened == ["Your mic (no cable)"] and e.stalls == 1


def test_a_late_check_gives_the_feed_a_fresh_wait():
    """The whole app was held up (this check ran late too): the feed runs again as soon
    as the app does, so it isn't reopened for a gap that wasn't its own."""
    e = direct_engine()
    e._last_cb["main"] = time.monotonic() - 2.0
    e._direct_seen = time.monotonic() - 2.0             # the last tick was long ago
    e.check_direct()
    assert e.devices.wait(5) and e.reopened == []
    e.check_direct()                                     # the next tick, on time
    assert e.devices.wait(5) and e.reopened == []
    e._direct_grace -= DIRECT_STALL_S + 0.1               # ...and still nothing, later
    e._direct_seen = time.monotonic()
    e.check_direct()
    assert e.devices.wait(5) and e.reopened == ["Your mic (no cable)"]


def test_other_streams_keep_the_long_limit():
    """A device stream (a driver can pause a moment: a rate change, a busy USB hub) is
    reopened only after STALL_S, and check_direct leaves it to check_streams."""
    e = Engine()
    e.main_stream, e.names["main"] = FakeStream(), "Speakers"
    e.reopened = []
    e.set_main_device = e.reopened.append
    e._last_cb["main"] = time.monotonic() - DIRECT_STALL_S - 0.3
    e._direct_seen = time.monotonic()
    e.check_direct()
    e.check_streams()
    assert e.devices.wait(5) and e.reopened == []
    e._last_cb["main"] = time.monotonic() - STALL_S - 0.1
    e.check_streams()
    assert e.devices.wait(5) and e.reopened == ["Speakers"]


def test_a_stall_writes_one_thread_dump(tmp_path, monkeypatch):
    monkeypatch.setattr(bootmark, "app_dir", lambda: tmp_path)
    (tmp_path / enginedevices.STALL_DUMP_NAME).write_text("an older run's\n")
    stuck = threading.Event()
    t = threading.Thread(target=stuck.wait, name="direct-mic", daemon=True)
    t.start()
    try:
        e = direct_engine()
        for _i in range(STALL_DUMP_MAX + 2):
            e._last_cb["main"] = time.monotonic() - 1.0
            e._direct_seen = time.monotonic()
            e.check_direct()
            assert e.devices.wait(5)
    finally:
        stuck.set()
    assert len(e.reopened) == STALL_DUMP_MAX + 2       # every stall is reopened...
    text = (tmp_path / enginedevices.STALL_DUMP_NAME).read_text(encoding="utf-8")
    assert "an older run's" not in text
    assert text.count("main stream:") == STALL_DUMP_MAX   # ...but the dumps stop
    assert "(direct-mic)" in text and "(MainThread)" in text
    assert "s without a callback ===" in text


def test_a_dump_that_cant_be_written_still_reopens(tmp_path, monkeypatch):
    monkeypatch.setattr(bootmark, "app_dir", lambda: tmp_path / "missing" / "dir")
    e = direct_engine()
    e._last_cb["main"] = time.monotonic() - 1.0
    e.check_direct()
    assert e.devices.wait(5) and e.reopened == ["Your mic (no cable)"]


def test_long_waits_between_callbacks_are_noted(caplog):
    e = Engine()
    out = np.zeros((480, 2), np.float32)
    e._last_cb["main"] = time.monotonic() - 0.25
    e._cb_main(out, 480, None, None)
    e._cb_main(out, 480, None, None)
    assert 0.25 <= e.cb_gap_max["main"] < 1.0           # the longest, not the last
    e._gaps_noted -= 61
    with caplog.at_level(logging.INFO, logger="soundboard.audio.engine"):
        e._note_gaps(time.monotonic())
        e._note_gaps(time.monotonic() + 61)              # nothing long since: quiet
    notes = [r.getMessage() for r in caplog.records if "longest wait" in r.getMessage()]
    assert len(notes) == 1 and "main 2" in notes[0] and e.cb_gap_max["main"] == 0.0


def test_a_new_feed_gets_the_long_limit_until_its_first_block():
    """A feed just opened can take ~0.4 s to its first block on a slower PC: it's only
    held to DIRECT_STALL_S once it has called back."""
    e = direct_engine()
    e._fresh.add("main")
    e._last_cb["main"] = time.monotonic() - DIRECT_STALL_S - 0.3
    e.check_direct()
    assert e.devices.wait(5) and e.reopened == []
    out = np.zeros((480, 2), np.float32)
    e._cb_main(out, 480, None, None)                     # its first block...
    assert "main" not in e._fresh and e.cb_gap_max["main"] == 0.0   # ...isn't a gap
    e._last_cb["main"] = time.monotonic() - DIRECT_STALL_S - 0.1
    e._direct_seen = time.monotonic()
    e.check_direct()
    assert e.devices.wait(5) and e.reopened == ["Your mic (no cable)"]
