"""The headphones output follows Windows' default output: switch Windows from the
headset to the speakers with the app open and the sounds come out of the speakers,
unless another device was picked for the headphones by hand."""
import threading
import time

import pytest

from soundboard.audio import appaudio
from soundboard.audio import engine as eng
from conftest import devices_done, said
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
    window.devctl._follow_default_output()
    assert window.cfg.mon_device == OUTS[0]
    windows_default(monkeypatch, "Speakers (Realtek Audio)")
    window.devctl._follow_default_output()
    devices_done(window)   # opened on the device thread
    assert window.cfg.mon_device == OUTS[1] and window.opened[-1] == OUTS[1]
    assert window.cb_mon.currentData() == OUTS[1]
    assert "Speakers" in said(window)


def test_a_device_picked_by_hand_stays(window, monkeypatch):
    windows_default(monkeypatch, "Speakers (Realtek Audio)")
    window.devctl._follow_default_output()
    window.cb_mon.setCurrentIndex(window.cb_mon.findData(OUTS[0]))
    window.routectl.on_device(window.cb_mon, "mon_device")      # the headset, by hand
    assert not window.cfg.mon_follows_default
    windows_default(monkeypatch, "Headphones (Gaming Headset)")
    window.devctl._follow_default_output()
    windows_default(monkeypatch, "Speakers (Realtek Audio)")
    window.devctl._follow_default_output()
    assert window.cfg.mon_device == OUTS[0]
    window.cb_mon.setCurrentIndex(window.cb_mon.findData(OUTS[1]))
    window.routectl.on_device(window.cb_mon, "mon_device")      # Windows' default: follows again
    assert window.cfg.mon_follows_default


def test_the_cable_as_windows_default_isnt_followed(window, monkeypatch):
    windows_default(monkeypatch, "Speakers (Realtek Audio)")
    window.devctl._follow_default_output()
    windows_default(monkeypatch, "CABLE Input (VB-Audio Virtual Cable)")
    window.devctl._follow_default_output()
    assert window.cfg.mon_device == OUTS[1]


def test_a_pulled_out_headset_leaves_the_headphones_box(window, monkeypatch):
    """Windows' default goes back to the speakers when the headset is pulled out; PortAudio's
    list (from the last scan) still had it, so the box offered a device that's gone."""
    devs = eng.list_devices("output")
    windows_default(monkeypatch, "Headphones (Gaming Headset)")
    window.devctl._follow_default_output()
    devices_done(window)
    scans = []

    def rescan():
        scans.append(1)
        devs[:] = [d for d in devs if d["name"] != OUTS[0]]
        return True
    monkeypatch.setattr(eng, "rescan", rescan)
    monkeypatch.setattr(appaudio, "endpoint_names", lambda kind: set(OUTS[1:]))   # unplugged
    windows_default(monkeypatch, "Speakers (Realtek Audio)")
    window.devctl._follow_default_output()
    devices_done(window)
    assert scans and window.cfg.mon_device == OUTS[1]
    assert window.cb_mon.findData(OUTS[0]) == -1
    # Windows' default switched by hand, the headset still plugged in: no re-scan
    scans.clear()
    devs[:] = [{"index": i, "name": n} for i, n in enumerate(OUTS)]
    monkeypatch.setattr(appaudio, "endpoint_names", lambda kind: set(OUTS))
    windows_default(monkeypatch, "Headphones (Gaming Headset)")
    window.devctl._follow_default_output()
    windows_default(monkeypatch, "Speakers (Realtek Audio)")
    window.devctl._follow_default_output()
    devices_done(window)
    assert not scans


def test_the_default_when_the_app_starts(window, monkeypatch):
    window.cfg.mon_device = OUTS[0]
    window._default_out = "Speakers (Realtek Audio)"   # changed while the app was closed
    window.devctl._init_devices()
    assert window.cfg.mon_device == OUTS[1]


def test_a_listed_device_that_wont_open_gets_a_rescan_with_backoff(window, monkeypatch, qapp):
    """Plugged in after the app started, or its format changed in Windows: PortAudio's
    old list can't open it, however often the engine retries."""
    from soundboard.ui.window import devicecontrol
    from test_idle_cpu import recover
    scans = []
    monkeypatch.setattr(window.devctl, "_refresh_off_ui",
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
    window.devctl._recover_at = 0.0                           # the wait is over
    recover(window, qapp)
    assert len(scans) == 2
    assert window.devctl._recover_at - time.monotonic() == pytest.approx(
        devicecontrol.RECOVER_WAIT_S[1], abs=5)
    e.errors.pop("mic")                                # it opened: the wait starts over
    recover(window, qapp)
    assert window.devctl._recover_n == 0


def test_picking_a_bluetooth_hands_free_mic_just_uses_it(window, monkeypatch):
    """Earbuds picked as the mic are used like any mic: no warning about call quality
    (people with earbuds know) or about Windows' effects."""
    monkeypatch.setattr(eng.Engine, "set_mic_device", lambda self, n: None)
    cb = window.cb_mic
    cb.addItem("Headset (WH-1000XM4 Hands-Free AG Audio)",
               "Headset (WH-1000XM4 Hands-Free AG Audio)")
    cb.setCurrentIndex(cb.count() - 1)
    window.routectl.on_device(cb, "mic_device")
    devices_done(window)
    assert "phone-call" not in said(window) and "Bluetooth" not in said(window)


def test_a_pick_waits_its_turn_while_a_driver_is_stuck(window, monkeypatch, qapp):
    """A recovery stuck in a dead driver on the device thread: picking a device by hand
    doesn't freeze the window waiting for it. The picks run after it, in order."""
    from conftest import process_events
    windows_default(monkeypatch, "Speakers (Realtek Audio)")
    window.routectl._fill_combo(window.cb_mon, OUTS, OUTS[2])
    devices_done(window)
    e, stuck = window.engine, threading.Event()
    assert e.devices.claim()
    e.devices.run(lambda: stuck.wait(10), lambda _r: e.devices.release())
    for name in (OUTS[1], OUTS[0]):
        window.cb_mon.setCurrentIndex(window.cb_mon.findData(name))
        t0 = time.monotonic()
        window.routectl.on_device(window.cb_mon, "mon_device")
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
    from soundboard.ui.kit import busy
    devices_done(window)
    stuck, threads = threading.Event(), []

    def rescan():
        threads.append(threading.current_thread())
        stuck.wait(10)
        return True
    monkeypatch.setattr(eng, "rescan", rescan)
    btn = QPushButton("Re-scan devices")
    window.devctl.rescan_with_feedback(btn)
    assert process_events(qapp, lambda: threads, timeout=5)
    assert threads[0] is not threading.main_thread()
    assert btn.text() == "Scanning…" and busy.is_busy(btn)   # the window is free meanwhile
    window.devctl.rescan_with_feedback(btn)                         # a double click: ignored
    assert not window.devctl._dev_waiting
    stuck.set()
    devices_done(window)
    assert len(threads) == 1 and not busy.is_busy(btn)
    assert btn.text() == "✓ Found 3 devices"
    # spam clicks while it shows what it found: each re-scan reopened every device
    window.devctl.rescan_with_feedback(btn)
    assert not window.devctl._dev_waiting and len(threads) == 1
    btn.setProperty("scanned_until", 0.0)   # (the result has been shown)
    window.devctl.rescan_with_feedback(btn)
    assert process_events(qapp, lambda: len(threads) == 2, timeout=5)
    devices_done(window)


def test_a_rescan_finding_the_same_devices_keeps_the_rows(window):
    """Also play on's rows were made again on every re-scan and route redraw: the new
    boxes showed for a moment before the layout placed them (device names flashed
    over the Devices card)."""
    devices_done(window)
    window.cfg.also_send = [OUTS[1]]
    window.routectl._show_route()
    rows = window.also_rows
    boxes = list(rows.boxes)
    assert boxes
    for _ in range(3):
        window.routectl._show_route()
    assert rows.boxes == boxes
    window.cfg.also_send = []   # a real change: made again
    window.routectl._show_route()
    assert rows.boxes == []


CABLE = "CABLE Input (VB-Audio Virtual Cable)"


@pytest.fixture
def on_cable(window, monkeypatch):
    """The sounds go into VB-Cable; Windows' default output is recorded, not changed."""
    from soundboard.mic import cableformat
    window.cfg.main_device = CABLE
    window.cfg.mon_device = OUTS[1]
    window._default_out = "Speakers (Realtek Audio)"
    window.set_default = []
    monkeypatch.setattr(cableformat, "set_default_output",
                        lambda n: window.set_default.append(n) or window.set_works)
    window.set_works = True
    return window


def windows_answers(win, qapp, name):
    """Windows' default output came back from the poll as `name`."""
    from conftest import process_events
    win.devctl._on_default_found(name)
    assert process_events(qapp, lambda: not win.devctl._cable_fixing, timeout=5)


def test_windows_switching_to_the_cable_is_put_back(on_cable, qapp):
    """Windows makes CABLE Input its default by itself: the whole PC then goes into the
    cable mic, the call hears it, and closing the app doesn't stop it."""
    windows_answers(on_cable, qapp, CABLE)
    assert on_cable.set_default == ["Speakers (Realtek Audio)"]
    assert "back on Speakers" in said(on_cable)
    assert on_cable.cfg.mon_device == OUTS[1]      # the headphones stay where they were


def test_keep_the_cable(on_cable, qapp):
    from soundboard.ui.kit import toast
    from conftest import process_events
    windows_answers(on_cable, qapp, CABLE)
    toast.shown(on_cable)[-1].card.action.click()
    assert on_cable.cfg.cable_default_ok
    assert process_events(qapp, lambda: on_cable.set_default[-1:] == [CABLE], timeout=5)
    n = len(on_cable.set_default)
    windows_answers(on_cable, qapp, CABLE)          # left alone from now on
    assert len(on_cable.set_default) == n


def test_the_cable_as_default_on_the_mic_route_is_left_alone(on_cable, qapp):
    on_cable.cfg.main_device = None                 # straight into the mic: no cable in use
    windows_answers(on_cable, qapp, CABLE)
    assert on_cable.set_default == []


def test_a_failed_switch_says_how_and_isnt_tried_again(on_cable, qapp):
    on_cable.set_works = False
    windows_answers(on_cable, qapp, CABLE)
    assert "sound settings" in said(on_cable)
    windows_answers(on_cable, qapp, CABLE)
    assert len(on_cable.set_default) == 1


def test_which_devices_are_the_cable():
    from soundboard.mic.cableformat import is_cable_input
    assert is_cable_input(CABLE) and is_cable_input("CABLE In 16ch (VB-Audio Virtual Cable)")
    assert is_cable_input("CABLE-A Input (VB-Audio Cable A)")
    assert not is_cable_input("Voicemeeter Input (VB-Audio Voicemeeter VAIO)")
    assert not is_cable_input("Speakers (Realtek Audio)") and not is_cable_input(None)
