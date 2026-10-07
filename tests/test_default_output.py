"""The headphones output follows Windows' default output: switch Windows from the
headset to the speakers with the app open and the sounds come out of the speakers,
unless another device was picked for the headphones by hand."""
import threading
import time

import pytest

from soundboard import appaudio
from soundboard import engine as eng
from conftest import devices_done
from test_mainwindow import window as main_window  # noqa: F401 - the real window, offscreen

OUTS = ["Headphones  (Gaming Headset)", "Speakers (Realtek Audio)",
        "CABLE Input (VB-Audio Virtual Cable)"]


@pytest.fixture
def window(main_window, monkeypatch):  # noqa: F811
    devs = [{"index": i, "name": n} for i, n in enumerate(OUTS)]
    monkeypatch.setattr(eng, "list_devices", lambda kind: devs if kind == "output" else [])
    monkeypatch.setattr(eng, "list_name", lambda i: OUTS[i])
    opened = []
    monkeypatch.setattr(eng.Engine, "set_mon_device", lambda self, n: opened.append(n))
    main_window.opened = opened
    main_window._default_timer.stop()
    return main_window


def windows_default(monkeypatch, name):
    monkeypatch.setattr(appaudio, "default_output_name", lambda: name)


def test_the_headphones_follow_windows_default_output(window, monkeypatch):
    windows_default(monkeypatch, "Headphones (Gaming Headset)")   # spaced its own way
    window._follow_default_output()
    assert window.cfg.mon_device == OUTS[0]
    windows_default(monkeypatch, "Speakers (Realtek Audio)")
    window._follow_default_output()
    assert window.cfg.mon_device == OUTS[1] and window.opened[-1] == OUTS[1]
    assert window.cb_mon.currentData() == OUTS[1]
    assert "Speakers" in window.status.text()


def test_a_device_picked_by_hand_stays(window, monkeypatch):
    windows_default(monkeypatch, "Speakers (Realtek Audio)")
    window._follow_default_output()
    window.cb_mon.setCurrentIndex(window.cb_mon.findData(OUTS[0]))
    window.on_device(window.cb_mon, "mon_device")      # the headset, by hand
    assert not window.cfg.mon_follows_default
    windows_default(monkeypatch, "Headphones (Gaming Headset)")
    window._follow_default_output()
    windows_default(monkeypatch, "Speakers (Realtek Audio)")
    window._follow_default_output()
    assert window.cfg.mon_device == OUTS[0]
    window.cb_mon.setCurrentIndex(window.cb_mon.findData(OUTS[1]))
    window.on_device(window.cb_mon, "mon_device")      # Windows' default: follows again
    assert window.cfg.mon_follows_default


def test_the_cable_as_windows_default_isnt_followed(window, monkeypatch):
    windows_default(monkeypatch, "Speakers (Realtek Audio)")
    window._follow_default_output()
    windows_default(monkeypatch, "CABLE Input (VB-Audio Virtual Cable)")
    window._follow_default_output()
    assert window.cfg.mon_device == OUTS[1]


def test_the_default_when_the_app_starts(window, monkeypatch):
    window.cfg.mon_device = OUTS[0]
    window._default_out = "Speakers (Realtek Audio)"   # changed while the app was closed
    window._init_devices()
    assert window.cfg.mon_device == OUTS[1]


def test_a_listed_device_that_wont_open_gets_a_rescan_with_backoff(window, monkeypatch, qapp):
    """Plugged in after the app started, or its format changed in Windows: PortAudio's
    old list can't open it, however often the engine retries."""
    from soundboard.ui import mainwindow
    from test_idle_cpu import recover
    scans = []
    monkeypatch.setattr(window, "_refresh_off_ui",
                        lambda: scans.append(1) or window.engine.devices.release())
    e = window.engine
    monkeypatch.setitem(e.names, "mic", "Microphone (USB Mic)")
    monkeypatch.setitem(e.errors, "mic", "device not found")
    e.mic_stream = None
    windows = {"input": set()}
    monkeypatch.setattr(appaudio, "endpoint_names", lambda kind: windows.get(kind, set()))
    recover(window, qapp)
    assert not scans                                   # unplugged: nothing to re-scan for
    windows["input"] = {"Microphone  (USB Mic)"}       # Windows lists it now
    recover(window, qapp)
    assert len(scans) == 1
    recover(window, qapp)
    assert len(scans) == 1                             # waits before the next try
    window._recover_at = 0.0                           # the wait is over
    recover(window, qapp)
    assert len(scans) == 2
    assert window._recover_at - time.monotonic() == pytest.approx(
        mainwindow.RECOVER_WAIT_S[1], abs=5)
    e.errors.pop("mic")                                # it opened: the wait starts over
    recover(window, qapp)
    assert window._recover_n == 0


def test_picking_a_bluetooth_hands_free_mic_warns_about_call_quality(window, monkeypatch):
    from soundboard.ui import mainwindow
    monkeypatch.setattr(eng.Engine, "set_mic_device", lambda self, n: None)
    assert mainwindow.is_hands_free("Headset (WH-1000XM4 Hands-Free AG Audio)")
    assert not mainwindow.is_hands_free("Microphone (USB Mic)")
    cb = window.cb_mic
    cb.addItem("Headset (WH-1000XM4 Hands-Free AG Audio)",
               "Headset (WH-1000XM4 Hands-Free AG Audio)")
    cb.setCurrentIndex(cb.count() - 1)
    window.on_device(cb, "mic_device")
    devices_done(window)
    assert "phone-call mic" in window.status.text()


def test_a_pick_waits_its_turn_while_a_driver_is_stuck(window, monkeypatch, qapp):
    """A recovery stuck in a dead driver on the device thread: picking a device by hand
    doesn't freeze the window waiting for it. The picks run after it, in order."""
    from conftest import process_events
    windows_default(monkeypatch, "Speakers (Realtek Audio)")
    window._fill_combo(window.cb_mon, OUTS, OUTS[2])
    devices_done(window)
    e, stuck = window.engine, threading.Event()
    assert e.devices.claim()
    e.devices.run(lambda: stuck.wait(10), lambda _r: e.devices.release())
    for name in (OUTS[1], OUTS[0]):
        window.cb_mon.setCurrentIndex(window.cb_mon.findData(name))
        t0 = time.monotonic()
        window.on_device(window.cb_mon, "mon_device")
        assert time.monotonic() - t0 < 0.5             # the window didn't wait
    process_events(qapp, lambda: False, timeout=0.3)
    assert window.opened[-2:] != [OUTS[1], OUTS[0]]    # still waiting their turn
    assert window.cfg.mon_device == OUTS[0]            # ...but the pick is taken
    stuck.set()
    devices_done(window)
    assert window.opened[-2:] == [OUTS[1], OUTS[0]]


def test_rescan_runs_on_the_device_thread(window, monkeypatch, qapp):
    from PySide6.QtWidgets import QPushButton

    from conftest import process_events
    from soundboard.ui import busy
    devices_done(window)
    stuck, threads = threading.Event(), []

    def rescan():
        threads.append(threading.current_thread())
        stuck.wait(10)
        return True
    monkeypatch.setattr(eng, "rescan", rescan)
    btn = QPushButton("Re-scan devices")
    window.rescan_with_feedback(btn)
    assert process_events(qapp, lambda: threads, timeout=5)
    assert threads[0] is not threading.main_thread()
    assert btn.text() == "Scanning…" and busy.is_busy(btn)   # the window is free meanwhile
    window.rescan_with_feedback(btn)                         # a double click: ignored
    assert not window._dev_waiting
    stuck.set()
    devices_done(window)
    assert len(threads) == 1 and not busy.is_busy(btn)
    assert btn.text() == "✓ Found 3 devices"
