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
from soundboard.audio import appaudio
from soundboard.audio import engine as eng
from soundboard.audio.engine import Engine
from soundboard.audio.engineparts import LITE_BLOCK_S, DeviceWorker
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


def test_a_device_pulled_out_after_a_rescan_is_still_noticed(monkeypatch, gate):
    opened = []
    hanging_driver(monkeypatch, gate, opened)
    gate.set()
    e = Engine()
    e.set_mon_device("Headphones")
    e.close_streams()                               # a re-scan closes them all...
    e.set_mon_device("Headphones")                  # ...and opens them again
    e._last_cb["mon"] = time.monotonic() - 10       # then the headset is pulled out
    e.check_streams()
    assert e.devices.wait(5)
    assert e.check_streams() == ["mon"]             # noticed: the status says so
    assert e.stalls == 1 and len(opened) == 3
    e.shutdown()                                    # quitting: never reopened again
    e._last_try["mon"] = 0.0
    assert e.check_streams() == [] and not e.devices.busy


def test_the_app_s_rescans_keep_the_device_watchdog_on(default_window, monkeypatch,  # noqa: F811
                                                       qapp):
    w = default_window
    monkeypatch.setattr(eng, "rescan", lambda: True)
    w.devctl.refresh_devices()                      # the Re-scan button
    assert not w.engine._shut
    done = []
    w.devctl._when_devices_free(lambda: w.devctl._refresh_off_ui(done.append))   # its own
    process_events(qapp, lambda: done and not w.engine.devices.busy, timeout=5)
    assert done and not w.engine._shut


def test_a_missing_device_is_retried_off_the_ui_thread(monkeypatch, gate):
    opened = []
    hanging_driver(monkeypatch, gate, opened)
    e = Engine()
    e.names["mic"] = "Microphone (USB Mic)"
    e.tap_name = "CABLE Input"                      # straight into the mic, and the cable
    e.copy_names = ("Speakers",)                    # Also play on
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
    quick(w.devctl._recover_devices)
    quick(w.devctl._recover_devices)                       # the first is still asking Windows
    gate.set()
    process_events(qapp, lambda: scans and not e.devices.busy, timeout=5)
    assert asked == ["input"] and len(scans) == 1
    assert scans[0] is not threading.main_thread()
    assert w.devctl._recover_n == 1


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
    quick(w.devctl._on_default_found, "Speakers (Realtek Audio)")
    gate.set()
    process_events(qapp, lambda: w.cfg.mon_device == OUTS[1] and not w.engine.devices.busy,
                   timeout=5)
    assert w.cfg.mon_device == OUTS[1] and w.opened[-1] == OUTS[1]
    assert w.cb_mon.currentData() == OUTS[1]


class held_elsewhere:
    """DEVICES held by another thread (a recovery stuck on a hung driver) until the
    block ends."""
    def __enter__(self):
        self.go, self.held = threading.Event(), threading.Event()

        def hold():
            with eng.DEVICES:
                self.held.set()
                self.go.wait(10)
        self.t = threading.Thread(target=hold, daemon=True)
        self.t.start()
        assert self.held.wait(5)
        return self

    def __exit__(self, *exc):
        self.go.set()
        self.t.join(5)


def recording(calls, key):
    """An engine device method that, like the real ones, opens under DEVICES."""
    def opener(self, *a):
        with eng.DEVICES:
            calls.append((key, *a))
    return opener


def test_latency_and_stream_output_changes_never_wait_on_the_ui_thread(
        main_window, monkeypatch, qapp):  # noqa: F811
    """Audio buffering and lite mode's block (each reopens every stream) and Also play
    on's stream output were opened on the UI thread: a recovery holding the devices
    froze the window."""
    from conftest import devices_done
    w = main_window
    devices_done(w)
    calls = []
    for name in ("set_mic_device", "set_main_device", "set_tap_device", "set_mon_device",
                 "set_obs_device", "set_copy_devices"):
        monkeypatch.setattr(eng.Engine, name, recording(calls, name))
    with held_elsewhere():
        quick(w.devctl.set_latency, "high" if w.cfg.latency != "high" else "low")
        quick(w.routectl.set_obs_device, "Speakers")
        quick(w.devctl.set_lite_block, True)     # lite mode's audio block
        assert calls == []                       # waiting their turn, off the UI thread
        assert w.engine.block_s == 0.0
    devices_done(w)
    assert [c[0] for c in calls].count("set_obs_device") == 3   # reopened, picked, reopened
    assert w.engine.block_s == LITE_BLOCK_S
    assert ("set_obs_device", w.routectl._obs_name("Speakers")) in calls


def test_default_output_switch_and_reopening_all_never_wait_on_the_ui_thread(
        main_window, monkeypatch, qapp):  # noqa: F811
    """Following Windows' default output and reopening every device (the setup guide
    closing) opened their streams on the UI thread: a recovery holding the devices
    froze the window."""
    from conftest import devices_done
    w = main_window
    devices_done(w)
    calls = []
    for name in ("set_mic_device", "set_main_device", "set_tap_device", "set_mon_device",
                 "set_obs_device", "set_copy_devices"):
        monkeypatch.setattr(eng.Engine, name, recording(calls, name))
    w.cfg.mon_follows_default = True
    with held_elsewhere():
        quick(w.devctl._use_default_output, "Speakers")
        quick(w.devctl._reopen_devices)
        assert calls == []                       # waiting their turn, off the UI thread
        assert w.cfg.mon_device == "Speakers"    # the window shows it straight away
    devices_done(w)
    assert ("set_mon_device", "Speakers") in calls
    assert [c[0] for c in calls].count("set_mon_device") == 2   # switched, then all reopened
    assert "set_mic_device" in [c[0] for c in calls]


def test_the_device_thread_is_started_once_not_on_every_check():
    """Starting a thread waits for it to run, and the checks start work from the UI
    thread: on a busy PC short of memory a new thread per check held the window for
    seconds. One thread does every step, however long it sat idle in between."""
    w = DeviceWorker(name="devices-test")
    seen = []
    for _ in range(3):
        done = threading.Event()
        assert w.claim()
        w.run(threading.get_ident, lambda t, done=done: (seen.append(t), w.release(), done.set()))
        assert done.wait(5)
        assert w.wait(5)
    assert len(set(seen)) == 1
    assert w._thread is not None and w._thread.is_alive()


def hanging_portaudio(monkeypatch, gate, names):
    """PortAudio whose device queries hang until `gate` is set, then list `names`."""
    def query_devices(idx=None):
        gate.wait(10)
        devs = [{"name": n, "hostapi": 0, "max_output_channels": 2,
                 "max_input_channels": 0} for n in names]
        return devs if idx is None else devs[idx]

    def query_hostapis(idx=None):
        gate.wait(10)
        api = {"name": "Windows WASAPI", "default_output_device": 0,
               "default_input_device": -1}
        return [api] if idx is None else api

    monkeypatch.setattr(eng.sd, "query_devices", query_devices)
    monkeypatch.setattr(eng.sd, "query_hostapis", query_hostapis)


def answered():
    """Until the device-list thread has nothing left to answer."""
    q = eng.devicelist._asker._open
    assert q is None or q.wait(5)


def test_a_hanging_device_query_gives_the_last_list_not_a_frozen_window(monkeypatch, gate):
    gate.set()
    hanging_portaudio(monkeypatch, gate, ["Speakers"])
    assert [d["name"] for d in eng.list_devices("output")] == ["Speakers"]
    assert eng.default_device_name("output") == "Speakers"
    gate.clear()                                   # a driver stops answering
    hanging_portaudio(monkeypatch, gate, ["Speakers", "Headset"])
    assert [d["name"] for d in quick(eng.list_devices, "output")] == ["Speakers"]
    for _ in range(20):                            # the next asks don't wait at all
        assert [d["name"] for d in quick(eng.list_devices, "output")] == ["Speakers"]
    assert quick(eng.default_device_name, "output") == "Speakers"
    assert quick(eng.list_name, 0) == "Speakers"
    assert quick(eng.virtual_outputs) == []
    gate.set()                                     # it answers after all
    answered()
    assert [d["name"] for d in eng.list_devices("output")] == ["Speakers", "Headset"]


def test_a_device_query_that_fails_still_raises(monkeypatch):
    def broken(idx=None):
        raise eng.sd.PortAudioError("Invalid device")
    monkeypatch.setattr(eng.sd, "query_devices", broken)
    with pytest.raises(eng.sd.PortAudioError):
        eng.list_name(5)
    answered()


def test_the_engine_finds_its_device_while_it_holds_the_device_lock(monkeypatch):
    """The engine opens a stream holding DEVICES on its device thread: the lookup must
    see PortAudio's list then, not the last one (empty on start-up: "not found")."""
    def query_devices(idx=None):
        devs = [{"name": "Microphone (Headset)", "hostapi": 0, "max_output_channels": 0,
                 "max_input_channels": 1}]
        return devs if idx is None else devs[idx]
    monkeypatch.setattr(eng.sd, "query_devices", query_devices)
    monkeypatch.setattr(eng.sd, "query_hostapis", lambda idx=None: [{"name": "Windows WASAPI"}])
    monkeypatch.setattr(eng.devicelist, "_seen", {})
    found = []

    def engine_thread():
        with eng.DEVICES:   # as @_holding_devices does
            found.append(eng.devicelist.find_device("input", "Microphone (Headset)"))
    t = threading.Thread(target=engine_thread)
    t.start()
    t.join(5)
    assert found == [0]
