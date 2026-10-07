"""Slow device work (closing, opening and re-scanning streams, asking Windows for its
devices) runs on the engine's device thread, never the UI thread: a driver that
hangs when a headset is unplugged, Bluetooth drops or the PC wakes from sleep used to
freeze the window for seconds. Each test makes the driver hang behind an Event and
checks the UI-thread call comes straight back, then lets it go and checks the work
still got done (once: never two recoveries at once)."""
import threading
import time

import pytest

from conftest import process_events
from soundboard import appaudio
from soundboard import engine as eng
from soundboard.engine import Engine
from test_default_output import OUTS
from test_default_output import window as default_window  # noqa: F401
from test_mainwindow import window as main_window  # noqa: F401

QUICK_S = 0.5   # what the UI thread may spend on it


@pytest.fixture
def gate():
    g = threading.Event()
    yield g
    g.set()   # never leave the device thread stuck behind a failed test


def quick(fn, *a):
    t0 = time.monotonic()
    out = fn(*a)
    took = time.monotonic() - t0
    assert took < QUICK_S, f"the UI thread waited {took:.2f}s on a device"
    return out


def hanging_driver(monkeypatch, gate, opened):
    """sounddevice whose streams hang on open and close until `gate` is set."""
    class Stream:
        def __init__(self, **kw):
            gate.wait(10)
            opened.append(self)

        def start(self):
            pass

        def stop(self):
            gate.wait(10)

        def close(self):
            pass

    monkeypatch.setattr(eng, "find_device", lambda kind, name: 3)
    monkeypatch.setattr(eng.sd, "query_devices",
                        lambda idx=None: {"default_samplerate": 48000, "max_output_channels": 2,
                                          "max_input_channels": 1, "name": "x"})
    monkeypatch.setattr(eng.sd, "OutputStream", Stream)
    monkeypatch.setattr(eng.sd, "InputStream", Stream)
    return Stream


def test_a_stalled_stream_is_reopened_off_the_ui_thread(monkeypatch, gate):
    opened = []
    Stream = hanging_driver(monkeypatch, gate, opened)
    e = Engine()
    gate.set()
    e.set_mon_device("Headphones")
    gate.clear()
    old = e.mon_stream
    assert isinstance(old, Stream)
    e._last_cb["mon"] = time.monotonic() - 10       # its callback stopped (unplugged)
    assert quick(e.check_streams) == []
    for _ in range(3):                              # still hung: nothing stacks up
        assert quick(e.check_streams) == []
    gate.set()
    assert e.devices.wait(5)
    assert e.check_streams() == ["mon"]             # the status line is refreshed now
    assert e.stalls == 1 and len(opened) == 2 and e.mon_stream is opened[-1]


def test_a_missing_device_is_retried_off_the_ui_thread(monkeypatch, gate):
    opened = []
    hanging_driver(monkeypatch, gate, opened)
    e = Engine()
    e.names["mic"] = "Microphone (USB Mic)"
    e.tap_name = "CABLE Input"                      # straight into the mic, and the cable
    e.copy_names = ("Speakers",)                    # Also send to
    e.errors["mic"] = "device not found"
    assert quick(e.check_streams) == []
    gate.set()
    assert e.devices.wait(5)
    assert e.check_streams() == ["mic"]             # came back
    assert e.mic_stream is not None and e.tap is not None and len(e.copies) == 1
    assert len(opened) == 3


def test_a_device_thread_job_that_raises_lets_the_next_one_run(monkeypatch):
    e = Engine()
    monkeypatch.setattr(e, "_watch", lambda now: 1 / 0)
    e.names["mon"] = "Headphones"
    e._last_try["mon"] = 0.0
    e.check_streams()
    assert e.devices.wait(5)                        # not stuck "busy" forever
    assert e.devices.claim()
    e.devices.release()


def test_a_listed_device_is_rescanned_off_the_ui_thread(default_window, monkeypatch,  # noqa: F811
                                                        gate, qapp):
    w = default_window
    e = w.engine
    asked, scans = [], []

    def endpoint_names(kind):
        asked.append(kind)
        gate.wait(10)
        return {"Microphone (USB Mic)"}

    def rescan():
        gate.wait(10)
        scans.append(threading.current_thread())
        return True

    monkeypatch.setattr(appaudio, "endpoint_names", endpoint_names)
    monkeypatch.setattr(eng, "rescan", rescan)
    monkeypatch.setitem(e.names, "mic", "Microphone (USB Mic)")
    monkeypatch.setitem(e.errors, "mic", "device not found")
    e.mic_stream = None
    quick(w._recover_devices)
    quick(w._recover_devices)                       # the first is still asking Windows
    gate.set()
    process_events(qapp, lambda: scans and not e.devices.busy, timeout=5)
    assert asked == ["input"] and len(scans) == 1
    assert scans[0] is not threading.main_thread()
    assert w._recover_n == 1


def test_a_new_default_output_is_found_by_a_rescan_off_the_ui_thread(
        default_window, monkeypatch, gate, qapp):  # noqa: F811
    w = default_window
    devs = [{"index": i, "name": n} for i, n in enumerate(OUTS) if "Speakers" not in n]
    monkeypatch.setattr(eng, "list_devices", lambda kind: devs if kind == "output" else [])
    monkeypatch.setattr(eng, "list_name", lambda i: OUTS[i])

    def rescan():                                   # plugged in since the app started
        gate.wait(10)
        devs[:] = [{"index": i, "name": n} for i, n in enumerate(OUTS)]
        return True

    monkeypatch.setattr(eng, "rescan", rescan)
    w.cfg.mon_follows_default = True
    quick(w._on_default_found, "Speakers (Realtek Audio)")
    gate.set()
    process_events(qapp, lambda: w.cfg.mon_device == OUTS[1] and not w.engine.devices.busy,
                   timeout=5)
    assert w.cfg.mon_device == OUTS[1] and w.opened[-1] == OUTS[1]
    assert w.cb_mon.currentData() == OUTS[1]
