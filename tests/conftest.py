"""Test setup: run from the repo root so the flat modules import, never touch the
real %APPDATA%\\OnionBoard folder, and keep Qt on the offscreen platform (no
window ever appears; the web engine still runs)."""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("ONIONBOARD_INSTANCE", "pytest")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Garbage collection on the main thread only, as in the app (soundboard.uigc): a
# collection on a test server's or the relay's thread freed a leftover Qt object with
# a running timer there, and its next tick crashed the worker (access violation).
import gc  # noqa: E402

gc.disable()


class _SilentOutputStream:
    """Stands in for sounddevice.OutputStream: the callback runs on a thread at the
    device's pace, but what it writes goes nowhere. Tests that open the engine's
    outputs (main window, setup wizard) would otherwise play through the developer's
    real speakers or headphones."""

    def __init__(self, *, samplerate, channels, callback, blocksize=0, **_):
        import sounddevice as sd
        self._rate, self._chans, self._cb = int(samplerate), int(channels), callback
        self._frames = blocksize or max(1, self._rate // 100)   # 10 ms blocks
        self._flags = sd.CallbackFlags
        self._stop = None
        self._thread = None

    def _run(self):
        import numpy as np
        buf = np.zeros((self._frames, self._chans), dtype="float32")
        period = self._frames / self._rate
        while not self._stop.wait(period):
            try:
                self._cb(buf, self._frames, None, self._flags())
            except Exception:  # noqa: BLE001 - a real stream would swallow it too
                return

    def start(self):
        import threading
        if self._thread is None:
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self):
        if self._thread is not None:
            self._stop.set()
            self._thread.join(1)
            self._thread = None

    close = stop
    abort = stop


# ONIONBOARD_TEST_REAL_AUDIO=1 opts back in to real output devices.
if os.environ.get("ONIONBOARD_TEST_REAL_AUDIO") != "1":
    import sounddevice
    sounddevice.OutputStream = _SilentOutputStream



# Windows takes ~2 s to refuse a connection to a closed port, even on 127.0.0.1 (it
# retries the SYN twice). A test that wants "nothing is listening there" takes a port
# from closed_port(): connecting to it is refused at once, with the same error. A
# server listening on 127.0.0.1 only calls ipv4_only(port), so "localhost" (::1
# first) is refused there at once too, not after the same ~2 s.
_CLOSED_PORTS: set[int] = set()
_V4_ONLY_PORTS: set[int] = set()


def closed_port() -> int:
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    _CLOSED_PORTS.add(port)
    return port


def ipv4_only(port: int) -> int:
    _V4_ONLY_PORTS.add(port)
    return port


def _refuse_closed_ports_at_once():
    import socket
    connect, connect_ex = socket.socket.connect, socket.socket.connect_ex

    def closed(addr):
        if not (isinstance(addr, tuple) and len(addr) >= 2):
            return False
        return ((addr[1] in _CLOSED_PORTS and addr[0] in ("127.0.0.1", "::1", "localhost"))
                or (addr[1] in _V4_ONLY_PORTS and addr[0] == "::1"))

    def refusal():
        return OSError(0, "No connection could be made because the target machine "
                       "actively refused it", None, 10061)   # ConnectionRefusedError

    def fast_connect(self, addr):
        if closed(addr):
            raise refusal()
        return connect(self, addr)

    def fast_connect_ex(self, addr):
        return 10061 if closed(addr) else connect_ex(self, addr)

    socket.socket.connect = fast_connect
    socket.socket.connect_ex = fast_connect_ex


_refuse_closed_ports_at_once()

# Hosted CI runners (shared cores, other test workers beside it) stall a thread
# 10-30 ms on their own, as much as the hitches the wall-clock audio timing tests
# measure: there they fail on unchanged code. They run on a real PC, where a hitch is
# the only stall.
real_pc_timing = pytest.mark.skipif(bool(os.environ.get("CI")),
                                    reason="wall-clock audio timing: too noisy on CI")


def pytest_configure(config):
    config.addinivalue_line("markers", "real_this_pc: the relay refuses radio 127.x "
                            "(net.NEVER_THIS_PC) as in the app")


def pytest_xdist_auto_num_workers(config):
    """`-n auto` (pyproject's addopts): the whole suite runs on 4 workers, about a
    quarter of the time; a file or two runs in this process, where starting workers
    would cost more than it saves. `-n 2` / `-n 0` on the command line override it, and
    so does PYTEST_XDIST_AUTO_NUM_WORKERS (xdist's own setting) for the whole suite."""
    picked = [a for a in config.args if Path(a.split("::")[0]).suffix == ".py"]
    if picked and len(picked) == len(config.args) and len(picked) <= 2:
        return 0
    if (n := os.environ.get("PYTEST_XDIST_AUTO_NUM_WORKERS", "")).isdigit():
        return int(n)
    return min(4, os.cpu_count() or 1)


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    if not hasattr(app, "_collector"):   # collects while a test spins the event loop
        from soundboard.uigc import UiCollector
        app._collector = UiCollector(parent=app)
    return app


@pytest.fixture(autouse=True)
def _collect_on_the_main_thread():
    """What a test left in reference cycles is collected here, on the main thread
    (automatic collection is off: see the top of this file)."""
    yield
    from soundboard.uigc import collect_due
    collect_due()


def process_events(app, until, timeout=8.0, step=0.02):
    """Spin the Qt event loop until `until()` is true (or the timeout passes)."""
    import time
    from PySide6.QtCore import QEventLoop
    end = time.monotonic() + timeout
    while not until() and time.monotonic() < end:
        app.processEvents(QEventLoop.AllEvents, int(step * 1000))
        time.sleep(step / 4)
    return until()


@pytest.fixture
def app_dir(tmp_path, monkeypatch):
    """Point library's config/sounds paths at a temp folder."""
    from soundboard import library
    monkeypatch.setattr(library, "APP_DIR", tmp_path)
    monkeypatch.setattr(library, "SOUNDS_DIR", tmp_path / "sounds")
    monkeypatch.setattr(library, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(library, "THUMBS_DIR", tmp_path / "thumbs")
    monkeypatch.setattr(library, "CONFIG_PATH", tmp_path / "config.json")
    return tmp_path


@pytest.fixture(autouse=True)
def _never_touch_real_appdata(monkeypatch, tmp_path):
    """Any test that forgets `app_dir` still can't write into %APPDATA%\\OnionBoard."""
    from soundboard import library
    monkeypatch.setattr(library, "USE_RECYCLE_BIN", False)   # removed test files: just deleted
    real = library.APP_DIR.parent   # read once: the loop re-points APP_DIR itself
    for name in ("APP_DIR", "OLD_APP_DIR", "SOUNDS_DIR", "CACHE_DIR", "THUMBS_DIR",
                 "CONFIG_PATH"):
        if getattr(library, name).is_relative_to(real):
            monkeypatch.setattr(library, name, tmp_path / "guard" / name.lower())


@pytest.fixture(autouse=True)
def _never_touch_the_real_mic(monkeypatch, tmp_path):
    """Straight into my mic (soundboard.directmic): no test writes the real shared file
    the mic effect reads, runs the admin step, or sees this PC's own install."""
    from soundboard import directmic

    def no_admin(*_a, **_k):
        raise AssertionError("a test tried to run the mic effect's admin step")
    monkeypatch.setattr(directmic, "data_dir", lambda: tmp_path / "guard" / "OnionBoard" / "Mic")
    monkeypatch.setattr(directmic, "ring_path", lambda: tmp_path / "guard" / "ring2.bin")
    monkeypatch.setattr(directmic, "_elevated", no_admin)
    monkeypatch.setattr(directmic, "installed_on", lambda: [])
    directmic.forget_status()


@pytest.fixture(autouse=True)
def _never_read_the_real_discord(monkeypatch, tmp_path):
    """Discord's voice settings (soundboard.discordcfg) come from an empty folder: the
    developer's own Discord must not put a banner in a test or a screenshot. Tests
    write a fake store under discordcfg._appdata() when they need one."""
    from soundboard import discordcfg
    root = tmp_path / "guard" / "discord-appdata"
    monkeypatch.setattr(discordcfg, "_appdata", lambda: root)


@pytest.fixture(autouse=True)
def _not_a_dev_pc(monkeypatch):
    """The developer's PCs set ONIONBOARD_NO_STATS (no usage count from them): the
    tests run as on anyone's PC, so the usage count tests see it sent."""
    monkeypatch.delenv("ONIONBOARD_NO_STATS", raising=False)


@pytest.fixture(autouse=True)
def _never_touch_real_shortcuts(monkeypatch):
    """The theme re-icons the app's Desktop / Start menu shortcuts: never the
    developer's real ones (offscreen already skips it; this is the second lock)."""
    from soundboard import shellicon
    monkeypatch.setattr(shellicon, "shortcut_folders", lambda: [])


@pytest.fixture(autouse=True)
def _never_update_for_real(monkeypatch, tmp_path):
    """The update check is on by default: no test asks GitHub, downloads an installer
    into %APPDATA% or runs one. Tests fake the parts they exercise."""
    from soundboard import updates

    def offline(*_a, **_k):
        raise OSError("tests don't go online")

    def no_installer(*_a, **_k):
        raise AssertionError("a test tried to run the update installer")
    monkeypatch.setattr(updates, "UPDATES_DIR", tmp_path / "guard" / "updates")
    monkeypatch.setattr(updates, "INSTALL_LOG", tmp_path / "guard" / "updates" / "install.log")
    monkeypatch.setattr(updates, "_get", offline)
    monkeypatch.setattr(updates, "_open", offline)
    monkeypatch.setattr(updates, "start_install", no_installer)


@pytest.fixture(autouse=True)
def _test_servers_stand_in_for_the_internet(monkeypatch, request):
    """The tests' radio stations and Radio Browser run on 127.0.0.x, standing in for
    internet hosts, so the relay's NEVER_THIS_PC refusal is off unless a test asks for
    it with @pytest.mark.real_this_pc."""
    if request.node.get_closest_marker("real_this_pc") is None:
        from soundboard import net
        monkeypatch.setattr(net, "NEVER_THIS_PC", frozenset())


@pytest.fixture(autouse=True)
def _switches_back_on():
    """Settings > Privacy & security's switches (soundboard.net) are process-wide: a
    test that switches something off doesn't leave it off for the next one."""
    yield
    from soundboard import net
    net.configure_features()


@pytest.fixture(autouse=True)
def _data_prefs_back_to_default(monkeypatch):
    """Settings > Data & quality (soundboard.quality.current) is process-wide too: a
    test that turns on Low data mode doesn't leave the next one without thumbnails."""
    quality = sys.modules.get("soundboard.quality")
    if quality is not None:
        monkeypatch.setattr(quality, "current", quality.Prefs())


class NoMidi:
    """soundboard.midi's winmm backend with no devices: tests never open the
    developer's real MIDI controllers (a DAW may be using them)."""
    def __init__(self):
        self.on_message = self.on_closed = lambda *_: None

    def devices(self):
        return []

    def open(self, index, key):
        raise OSError("no MIDI in tests")

    def close(self, handle):
        pass


@pytest.fixture(autouse=True, scope="session")
def _never_look_at_the_real_foreground():
    """The main window asks which game is in front (soundboard.voicesdk) to suggest a
    Who's listening mode: in tests nothing is, whatever the developer is playing.
    For the whole session: test windows outlive their test, timers and all."""
    from soundboard import appaudio, voicesdk
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(voicesdk, "foreground_process", lambda: (0, ""))
        # ...nor whether it fills the screen (no tip during a game, soundboard.tips)
        from soundboard import tips
        mp.setattr(tips, "fullscreen_in_front", lambda: False)
        # ...nor which output Windows has as its default (the headphones follow it)
        mp.setattr(appaudio, "default_output_name", lambda: None)
        # ...nor which devices it has (a failing device is re-scanned when it's listed)
        mp.setattr(appaudio, "endpoint_names", lambda kind: None)
        # ...nor who records the cable (Who's listening suggests a mode from it)
        mp.setattr(appaudio, "recording_apps", lambda device: [])
        yield


@pytest.fixture(autouse=True)
def _never_touch_real_midi(monkeypatch):
    from soundboard import midi
    monkeypatch.setattr(midi, "WinMM", NoMidi)


@pytest.fixture(autouse=True)
def _never_touch_real_autostart(monkeypatch):
    """Building a MainWindow re-points an existing "start with Windows" entry at this
    copy of the app; in tests that would rewrite the developer's real Run key. Tests
    that exercise autostart put their own fake winreg in."""
    from soundboard import autostart
    monkeypatch.setattr(autostart, "winreg", None)


def own_module(monkeypatch, module, name: str, **fakes):
    """Give `module` its own copy of the module it imported as `name` (time, threading,
    ...) with `fakes` in it. Patching time.sleep or threading.Thread itself changes it
    for every thread in the process: the threads earlier tests left running then spun
    flat out (a 1 s test took 44 s, and a window's loader beside it missed its 15 s),
    or a thread of something else was never started."""
    import types
    real = getattr(module, name)
    copy = types.ModuleType(real.__name__)
    copy.__dict__.update(vars(real))
    copy.__dict__.update(fakes)
    monkeypatch.setattr(module, name, copy)
    return copy


def own_time(monkeypatch, module, **fakes):
    """own_module for `time`: sleep=..., monotonic=... for `module` alone."""
    return own_module(monkeypatch, module, "time", **fakes)


def us_key_char(vk: int) -> str:
    """winkeys.key_char on a US keyboard layout, whatever layout this PC has."""
    from soundboard import winkeys
    us = {winkeys.VK[k]: k for k in (";", "=", ",", "-", ".", "/", "`", "[", "\\", "]", "'")}
    return us.get(vk) or (chr(vk) if 0x30 <= vk <= 0x5A else "")


@pytest.fixture(autouse=True)
def _us_keyboard_layout(monkeypatch):
    """Key labels and the overlay key's layout check read the PC's keyboard layout;
    tests see a US one wherever they run."""
    from soundboard import winkeys
    monkeypatch.setattr(winkeys, "key_char", us_key_char)


@pytest.fixture(autouse=True)
def _fail_on_swallowed_exceptions(monkeypatch):
    """An exception in a Qt slot, a worker thread or the crash reporter never reaches
    pytest: PySide hands it to sys.excepthook and carries on, so the test passes while
    the user would get the crash dialog. Collect them and fail the test instead."""
    import threading

    from soundboard import applog
    seen = []
    monkeypatch.setattr(sys, "excepthook", lambda t, v, tb: seen.append((t, v, tb)))
    monkeypatch.setattr(threading, "excepthook",
                        lambda a: seen.append((a.exc_type, a.exc_value, a.exc_traceback)))
    real_report = applog.report

    def report(exc_info=None, where="", fatal=False):
        if exc_info is None:
            exc_info = sys.exc_info()
        elif isinstance(exc_info, BaseException):
            exc_info = (type(exc_info), exc_info, exc_info.__traceback__)
        if exc_info[0] is not None:
            seen.append(exc_info)
        return None
    monkeypatch.setattr(applog, "report", report)
    monkeypatch.setattr(applog, "_real_report", real_report, raising=False)
    yield seen
    if seen:
        import traceback
        text = "\n".join("".join(traceback.format_exception(*e)) for e in seen)
        pytest.fail(f"{len(seen)} exception(s) escaped to the crash reporter:\n{text}",
                    pytrace=False)


@pytest.fixture(autouse=True)
def _no_blocking_message_boxes(monkeypatch):
    """A QMessageBox.question / warning / … nobody expected would wait forever for a
    click on the offscreen platform and hang the whole run. Answer them with Cancel
    (or OK) instead; tests that care patch them with their own answer."""
    try:
        from PySide6.QtWidgets import QMessageBox
    except ImportError:
        return
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Cancel)
    for name in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, name, lambda *a, **k: QMessageBox.Ok)


@pytest.fixture(autouse=True)
def _never_change_real_device_formats(monkeypatch):
    """The cable check reads and sets Windows device formats. Tests see a cable that's
    already fine and can never change a real device's format."""
    from soundboard import cableformat
    monkeypatch.setattr(cableformat, "cable_ends", lambda names_hint=None: [])
    monkeypatch.setattr(cableformat, "set_rate", lambda end, rate=cableformat.RATE: False)


def pytest_runtest_logreport(report):
    """Name a failing test the moment it fails, not only in the summary at the end:
    a long run that's stopped early still says what broke, and `pytest --lf` then
    reruns just those."""
    if report.failed:
        import sys
        sys.stderr.write(f"\nFAILED {report.nodeid} ({report.when})\n")
        sys.stderr.flush()


@pytest.fixture(autouse=True)
def _no_windows_speech(request, monkeypatch):
    """Every main window warms up Windows speech: a PowerShell process that loads the
    speech engine. Across the hundred-odd tests that build one, that's what made the
    whole suite crawl. Only the speech tests talk to it (or their own fake)."""
    if request.node.module.__name__.rsplit(".", 1)[-1] == "test_speech":
        return
    from soundboard.speech import tts
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])


# What a test made and left running with a thread of Qt's or its own behind it, stopped
# after the test as the app stops it when the tab goes: freed while that thread was
# still handing it something, it crashed the test worker a few tests later (access
# violation / abort, about 1 run in 100). (module, class, method that stops it)
_STOP_AFTER_TEST = (("soundboard.radio", "RadioPlayer", "shutdown"),
                    ("soundboard.ui.appspanel", "_Lister", "stop"))


@pytest.fixture(autouse=True)
def _stop_what_tests_left_running(monkeypatch):
    import weakref
    made = []
    for mod_name, cls_name, stop in _STOP_AFTER_TEST:
        mod = sys.modules.get(mod_name)
        if mod is None:   # this test's module never imported it: none made here
            continue
        cls = getattr(mod, cls_name)

        def tracked(self, *a, _init=cls.__init__, _stop=stop, **k):
            _init(self, *a, **k)
            made.append((weakref.ref(self), _stop))
        monkeypatch.setattr(cls, "__init__", tracked)
    yield
    for ref, stop in made:
        obj = ref()
        if obj is not None:
            try:
                getattr(obj, stop)()
            except RuntimeError:   # its C++ side is already gone (its tab was freed)
                pass


@pytest.fixture(autouse=True)
def _free_test_windows():
    """Close and free the windows a test leaves behind. Qt keeps a closed top-level
    window alive, and every theme change restyles all of them: with a few hundred
    left over from earlier tests, one theme-switching test took 50 s, not 1 s."""
    from PySide6.QtWidgets import QApplication
    from shiboken6 import getCppPointer

    def key(w):
        return getCppPointer(w)[0]   # the C++ object: a wrapper's id() can change

    app = QApplication.instance()
    before = set(map(key, app.topLevelWidgets())) if app is not None else set()
    yield
    app = QApplication.instance()
    if app is None:
        return
    from PySide6.QtCore import QEvent
    for w in app.topLevelWidgets():
        if key(w) not in before:
            try:
                w.close()
                w.deleteLater()
            except RuntimeError:   # already gone on the C++ side
                pass
    app.sendPostedEvents(None, QEvent.DeferredDelete)
