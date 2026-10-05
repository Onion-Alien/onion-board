"""Per-program capture (soundboard.appaudio). The COM parts only exist on Windows;
the real capture test needs a virtual cable to play a tone into (silent to you)
and is opt-in (SOUNDBOARD_TEST_APP_CAPTURE=1), since it does put a very quiet
tone into the cable for a couple of seconds."""
import os
import subprocess
import sys
import time

import numpy as np
import pytest

from soundboard import appaudio
from soundboard.appaudio import GUID, WAVEFORMATEX, App, to_stereo_f32

WIN = sys.platform == "win32"
SR = appaudio.SR


def test_guid_bytes_keep_zero_bytes():
    # IUnknown's last 8 bytes start with C0 00 ...: a c_char array would stop at the 0
    assert bytes(appaudio.IID_IUnknown).hex() == "0000000000000000c000000000000046"
    assert GUID.of("{BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D}") == appaudio.IID_IAudioSessionControl2
    assert GUID.of("00000000-0000-0000-C000-000000000046") == appaudio.IID_IUnknown
    assert not (appaudio.IID_IUnknown == appaudio.IID_IAudioClient)


def test_struct_sizes_match_the_windows_layouts():
    from ctypes import sizeof
    assert sizeof(GUID) == 16
    assert sizeof(appaudio.PROPVARIANT) == 24
    assert sizeof(appaudio.ACTIVATION_PARAMS) == 12
    assert sizeof(WAVEFORMATEX) == 18
    assert sizeof(appaudio.WAVEFORMATEXTENSIBLE) == 40


def test_to_stereo_f32_handles_widths_and_channel_counts():
    f32 = WAVEFORMATEX(3, 2, 48000, 48000 * 8, 8, 32, 0)
    x = np.array([[0.5, -0.5], [0.25, 0.0]], np.float32)
    out = to_stereo_f32(x.tobytes(), f32, True)
    assert out.shape == (2, 2) and np.allclose(out, x)
    i16 = WAVEFORMATEX(1, 1, 48000, 48000 * 2, 2, 16, 0)     # mono int16 -> both channels
    out = to_stereo_f32(np.array([16384, -32768], np.int16).tobytes(), i16, False)
    assert out.shape == (2, 2)
    assert np.allclose(out[:, 0], [0.5, -1.0]) and np.allclose(out[:, 0], out[:, 1])
    six = WAVEFORMATEX(3, 6, 48000, 48000 * 24, 24, 32, 0)   # 5.1 -> front left / right
    frame = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6], np.float32)
    out = to_stereo_f32(frame.tobytes(), six, True)
    assert out.shape == (1, 2) and np.allclose(out[0], [0.1, 0.2])
    i24 = WAVEFORMATEX(1, 2, 48000, 48000 * 6, 6, 24, 0)
    out = to_stereo_f32(bytes([0, 0, 0x40, 0, 0, 0xC0]), i24, False)   # +0.5, -0.5
    assert np.allclose(out[0], [0.5, -0.5])


def test_app_display_name():
    assert App(1, "spotify.exe").name == "Spotify"
    assert App(7, "").name == "pid 7"


def test_supported_reports_windows_and_build():
    ok, why = appaudio.supported()
    if not WIN:
        assert not ok and "Windows" in why
    else:
        assert ok == (sys.getwindowsversion().build >= appaudio.MIN_BUILD)


def test_root_pid_walks_up_same_exe_only():
    table = {10: (1, "chrome.exe"), 11: (10, "chrome.exe"), 12: (11, "chrome.exe"),
             20: (10, "helper.exe"), 1: (0, "explorer.exe")}
    assert appaudio.root_pid(12, table) == 10
    assert appaudio.root_pid(20, table) == 20
    assert appaudio.root_pid(999, table) == 999
    loop = {5: (6, "a.exe"), 6: (5, "a.exe")}
    assert appaudio.root_pid(5, loop) in (5, 6)


def test_a_shared_helper_is_folded_into_the_program_that_started_it():
    table = {1: (0, "explorer.exe"), 30: (1, "ms-teams.exe"),
             31: (30, "msedgewebview2.exe"), 32: (31, "msedgewebview2.exe"),
             40: (1, "steam.exe"), 41: (40, "steamwebhelper.exe"),
             50: (1, "msedgewebview2.exe"), 51: (50, "msedgewebview2.exe")}
    assert appaudio.root_pid(32, table) == 30      # its sound is the new Teams'
    assert appaudio.root_pid(41, table) == 40
    assert appaudio.root_pid(51, table) == 50      # started by Windows: stays itself


@pytest.mark.skipif(not WIN, reason="Windows only")
def test_list_apps_runs_and_never_lists_this_process():
    apps = appaudio.list_apps()
    assert isinstance(apps, list)
    me = os.getpid()
    for a in apps:
        assert isinstance(a, App)
        assert me not in a.session_pids
        assert a.exe.lower() not in appaudio.SYSTEM_EXES


class _FakeMeter:
    def __init__(self, v):
        self.v, self.released = v, False

    def call(self, slot, argtypes, ptr, what=""):
        ptr._obj.value = self.v

    def release(self):
        self.released = True


@pytest.mark.skipif(not WIN, reason="Windows only")
def test_peak_watcher_reads_meters_between_scans_and_releases_them(monkeypatch):
    made = []

    def fake_list(meters=None):
        ms = [_FakeMeter(0.25), _FakeMeter(0.5)]   # two sessions of one program: the louder
        made.extend(ms)
        meters[42] = ms
        return []

    monkeypatch.setattr(appaudio, "_list_apps", fake_list)
    w = appaudio.PeakWatcher(interval=0.01, rescan=60)
    assert w.peak(42) is None
    w.start()
    deadline = time.monotonic() + 2
    while w.peak(42) is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert w.peak(42) == pytest.approx(0.5)
    for m in made:                                  # it keeps reading without rescanning
        m.v = 0.0
    time.sleep(0.3)
    assert w.peak(42) < 0.05 and len(made) == 2
    t = w._thread
    w.stop()
    t.join(2)
    assert all(m.released for m in made) and w.peak(42) is None


@pytest.mark.skipif(not WIN, reason="Windows only")
@pytest.mark.skipif(not WIN, reason="Windows processes")
def test_a_reused_pid_is_not_taken_for_the_program_it_used_to_be(monkeypatch):
    me = os.getpid()
    real = appaudio.process_path(me)
    assert real and os.path.basename(real).lower().startswith("python")
    # pretend this pid used to be Spotify's: a fresh process list says otherwise
    monkeypatch.setitem(appaudio._names, me, r"C:\Apps\Spotify.exe")
    assert appaudio.process_path(me, os.path.basename(real).lower()) == real
    # and a pid gone from the process list is forgotten, not kept forever
    monkeypatch.setitem(appaudio._names, 4_000_000_001, r"C:\Apps\Spotify.exe")
    appaudio.forget_dead_pids({me: (0, "python.exe")})
    assert 4_000_000_001 not in appaudio._names


@pytest.mark.skipif(not WIN, reason="Windows processes")
def test_is_running_tells_a_newer_process_on_the_same_pid_apart():
    me = os.getpid()
    started = appaudio.process_started(me)
    assert started
    assert appaudio.is_running(me) and appaudio.is_running(me, started)
    assert not appaudio.is_running(me, started - 1)   # "the old one" exited
    assert not appaudio.is_running(4_000_000_001)     # no such process


@pytest.mark.skipif(not WIN, reason="Windows events")
def test_a_quiet_program_is_handed_over_as_silence():
    """A program with nothing to play sends no packets at all: the engine's cushion
    for it ran dry, grew by half each time, and kept the extra delay for good."""
    import threading

    class NoPackets:
        def call(self, i, types, *args, what=""):
            if i == 5:                                 # GetNextPacketSize: nothing
                args[0]._obj.value = 0

    got = []
    cap = appaudio.AppCapture(os.getpid(), got.append, name="quiet")
    evt = appaudio._k32.CreateEventW(None, False, False, None)
    fmt = appaudio._format("f32")
    th = threading.Thread(target=cap._loop, args=(NoPackets(), fmt, True, evt), daemon=True)
    t0 = time.monotonic()
    th.start()
    time.sleep(0.4)
    cap._stop.set()
    th.join(2)
    took = time.monotonic() - t0
    appaudio._k32.CloseHandle(evt)
    n = sum(len(x) for x in got)
    assert not th.is_alive() and cap.error is None
    assert took * SR - 0.1 * SR < n <= took * SR   # the gap, in real time
    assert not any(x.any() for x in got)


def test_capture_of_a_missing_process_fails_politely():
    got = []
    cap = appaudio.AppCapture(4_000_000_000 - 1, got.append, name="nobody")
    assert cap.start() is False
    assert cap.error and "running" in cap.error
    assert not cap.running and cap.ended
    cap.stop()


@pytest.mark.skipif(not WIN, reason="Windows only")
def test_completion_handlers_outlive_a_timeout_until_windows_lets_go():
    from ctypes import c_void_p
    appaudio._Handler._live = []
    h = appaudio._Handler()
    obj = appaudio.Com(h.ptr)
    add_ref = obj._fn(1, (), c_void_p)
    assert add_ref(h.ptr) == 2                   # Windows takes a reference ...
    h.abandon()                                  # ... and we time out
    appaudio._Handler()
    appaudio._Handler()
    assert h in appaudio._Handler._live          # still referenced: must not be freed
    h.done.set()                                 # the late callback fired
    obj.release()                                # and Windows let go
    appaudio._Handler()
    assert h in appaudio._Handler._live          # freed only on the pass after that
    appaudio._Handler()
    assert h not in appaudio._Handler._live
    appaudio._Handler._live = []


HELPER = """
import numpy as np, sounddevice as sd
dev = next(i for i, d in enumerate(sd.query_devices())
           if "CABLE Input" in d["name"] and d["max_output_channels"] > 0
           and "WASAPI" in sd.query_hostapis(d["hostapi"])["name"])
rate = int(sd.query_devices(dev)["default_samplerate"])
t = np.arange(int(4 * rate)) / rate
x = (np.sin(2 * np.pi * 440 * t) * 0.004).astype(np.float32)   # -48 dB: a whisper into the cable
sd.play(np.stack([x, x], 1), rate, device=dev)
sd.wait()
"""


@pytest.mark.skipif(os.environ.get("SOUNDBOARD_TEST_APP_CAPTURE") != "1",
                    reason="opt-in: plays a very quiet tone into the virtual cable")
def test_capture_hears_a_helper_process_tone():
    import sounddevice as sd
    if not any("CABLE Input" in d["name"] and d["max_output_channels"] > 0
               for d in sd.query_devices()):
        pytest.skip("no virtual cable")
    p = subprocess.Popen([sys.executable, "-c", HELPER])
    try:
        for _ in range(12):   # the helper's session appears once its stream is open
            time.sleep(0.5)
            apps = {a.exe.lower() for a in appaudio.list_apps()}
            if apps & {"python.exe", "pythonw.exe"}:
                break
        else:
            pytest.fail(f"the helper never showed up in {sorted(apps)}")
        chunks = []
        cap = appaudio.AppCapture(p.pid, chunks.append, name="helper")
        assert cap.start(), cap.error
        time.sleep(1.5)
        cap.stop()
    finally:
        p.terminate()
        p.wait(5)
    x = np.concatenate(chunks)
    assert len(x) > 48000 // 2 and x.shape[1] == 2
    seg = x[-24000:, 0] * np.hanning(24000)
    freqs = np.fft.rfftfreq(len(seg), 1 / appaudio.SR)
    assert abs(freqs[np.argmax(np.abs(np.fft.rfft(seg)))] - 440) < 5
    assert 0.002 < np.abs(x).max() < 0.01


def test_device_list_releases_what_it_got_when_an_item_fails(monkeypatch):
    released = []

    class FakeCom:
        def __init__(self, ptr):
            self.ptr = ptr

        def call(self, slot, argtypes, *args, what=""):
            out = args[-1]._obj
            if what == "Item" and args[0] == 2:
                raise appaudio.ComError(-1, what)
            out.value = 3 if what == "GetCount" else 100 + (args[0] if what == "Item" else 0)
            return 0

        def release(self):
            released.append(self.ptr)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.release()

    monkeypatch.setattr(appaudio, "Com", FakeCom)
    with pytest.raises(appaudio.ComError):
        appaudio._render_devices(FakeCom(1))
    assert sorted(released) == [100, 100, 101]   # the list (ptr 100) and both devices
