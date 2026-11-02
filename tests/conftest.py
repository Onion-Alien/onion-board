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

# Off Windows (Linux, macOS) Windows' registry and DLLs are stood in for, so the app
# imports, and tests marked `windows` are skipped (tests/offwindows.py).
import offwindows  # noqa: E402

offwindows.install()

# Garbage collection on the main thread only, as in the app (soundboard.core.uigc): a
# collection on a test server's or the relay's thread freed a leftover Qt object with
# a running timer there, and its next tick crashed the worker (access violation).
# The same for what a finished thread lets go of (its target, often a tab's method).
import gc  # noqa: E402

from soundboard.core import uigc  # noqa: E402

gc.disable()
uigc.hand_threads_to_ui()

# A test worker (pytest-xdist) dies with the run that started it. Killing pytest (an
# editor's or agent's timeout, a closed terminal) used to leave its workers running,
# each holding ~500 MB, until someone noticed. The run's PID is handed down in the
# environment; each worker waits on that process and exits the moment it's gone.
_RUN_PID = "ONIONBOARD_TEST_RUN_PID"
if "PYTEST_XDIST_WORKER" not in os.environ:
    os.environ[_RUN_PID] = str(os.getpid())
elif sys.platform == "win32" and os.environ.get(_RUN_PID, "").isdigit():
    import ctypes
    import threading

    def _exit_with_the_run(pid: int):
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = ctypes.c_void_p
        handle = k32.OpenProcess(0x00100000, False, pid)   # SYNCHRONIZE
        if handle:
            k32.WaitForSingleObject(ctypes.c_void_p(handle), 0xFFFFFFFF)   # INFINITE
        os._exit(1)

    threading.Thread(target=_exit_with_the_run, args=(int(os.environ[_RUN_PID]),),
                     name="exit-with-the-run", daemon=True).start()


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


_HELD: list = []   # closed_port()'s sockets: bound, never listening, kept to the end


def closed_port() -> int:
    """A port nothing listens on, refused at once. Its socket stays bound (not
    listening) for the rest of the run: closed, the system handed the same number to a
    later test's server (Linux reuses them soon), and every connection to that server
    was "refused" here."""
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    _HELD.append(s)
    port = s.getsockname()[1]
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
# Hover state (underMouse) follows the real cursor: QTest.mouseMove moves it on a PC,
# but a hosted runner's desktop has no cursor to move, so hover never starts there.
real_pc_mouse = pytest.mark.skipif(bool(os.environ.get("CI")),
                                   reason="needs a real cursor: hosted runners have none")


def pytest_configure(config):
    config.addinivalue_line("markers", "real_this_pc: the relay refuses radio 127.x "
                            "(net.NEVER_THIS_PC) as in the app")
    config.addinivalue_line("markers", "windows: needs Windows itself (its registry, "
                            "DLLs or processes); skipped on Linux and macOS")
    config.addinivalue_line("markers", "fonts: loads Windows' own fonts into Qt, which "
                            "changes every later test's text in that process: run last")
    config.addinivalue_line("markers", "real_network_kind: asks Windows what kind of "
                            "network an address is on (others get a Private one)")
    config.addinivalue_line("markers", "host: runs the real mic effect in its test or fuzz "
                            "host (CI's mic-effect job builds them and runs these, one at a "
                            "time: side by side they miss real time)")


def pytest_collection_modifyitems(config, items):
    """The `fonts` tests go last: a font they load stays in Qt's caches for the rest of
    the process (taking it out again doesn't undo it), so the tests after them
    measured other text (a tick 2 px off level, a window too tall for 800x600) and
    failed only in some orders. Off Windows the `windows` tests are skipped.
    `-m windows` / `-m "not windows"` picks either set on any system (on Windows,
    `-m "not windows"` is what runs elsewhere)."""
    items.sort(key=lambda item: item.get_closest_marker("fonts") is not None)   # stable
    if sys.platform == "win32":
        return
    skip = pytest.mark.skip(reason="needs Windows")
    for item in items:
        if item.get_closest_marker("windows") is not None:
            item.add_marker(skip)


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


def pytest_sessionfinish(session, exitstatus):
    """Empty the clipboard before Python exits: on the offscreen platform a QMimeData
    still on it (a test copied a clip) crashed the process at exit, after every test
    had passed. The real Windows platform doesn't."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is not None:
        QApplication.clipboard().clear()


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from soundboard.ui.kit import wheelguard
    app.setStyle(wheelguard.AppStyle("Fusion"))   # as the app sets it (app.main)
    wheelguard.TIP_DELAY = 0   # tests ask for tooltips at once; test_tooltip_wait checks it
    if not app.styleSheet():   # the app's theme and font, as the window applies them:
        from soundboard.ui.kit import theme  # without it a worker's first tests measured
        from soundboard.sounds.library import Config  # text in Qt's plain font, and the
        theme.apply(app, Config().theme)   # ones after a window in the app's
    if not hasattr(app, "_collector"):   # collects while a test spins the event loop
        from soundboard.core.uigc import UiCollector
        app._collector = UiCollector(parent=app, freeze=False)
    return app


@pytest.fixture(autouse=True)
def _limited_themes_on_offer(monkeypatch):
    """Today is pinned inside every limited-edition theme's offer, so the tests that
    go through every theme still find them once the real offer has ended."""
    from soundboard.ui.kit import theme
    if theme.LIMITED:
        day = min(theme.LIMITED.values())
        monkeypatch.setattr(theme, "_today", lambda: day)


@pytest.fixture(autouse=True)
def _memory_never_full(monkeypatch):
    """The usage count waits while the PC is short of memory: a test runner that is
    would quietly send nothing, so no load counts as full here (test_usage sets it)."""
    from soundboard.core import usage
    monkeypatch.setattr(usage, "MEMORY_FULL", 101)


@pytest.fixture(autouse=True)
def _a_private_network(request, monkeypatch):
    """Onion Pocket's server refuses a network Windows can't name, and 127.0.0.1 (where
    the tests run it) is on none: a Private one, unless a test says otherwise."""
    if request.node.get_closest_marker("real_network_kind"):
        return
    from soundboard.online import netcategory
    monkeypatch.setattr(netcategory, "category", lambda ip: netcategory.PRIVATE)


@pytest.fixture(autouse=True)
def _no_ptt_key_left_held():
    """A test that held auto push-to-talk's key (with press / release stood in for)
    leaves nothing for winkeys' watch to let go of later with the real SendInput."""
    yield
    winkeys = sys.modules.get("soundboard.control.winkeys")
    if winkeys is not None:
        winkeys._ptt["combo"] = None


@pytest.fixture(autouse=True)
def _splash_act_back_after():
    """splash.show() picks this launch's act at random, now and then a rare one with a
    taller card: a test that showed the splash puts the act before back, or the splash
    tests after it in the same worker drew a rare launch's card."""
    splash = sys.modules.get("soundboard.ui.bun.splash")
    before = None if splash is None else splash._show
    yield
    splash = sys.modules.get("soundboard.ui.bun.splash")
    if splash is not None:   # (first imported in the test: the module's own default)
        splash._show = before if before is not None else splash.splashacts.Show()


@pytest.fixture(autouse=True)
def _theme_back_after():
    """A test that switched the app's theme (Comic Sans, a highlight colour, textures)
    puts the one before back: the theme is the whole process's, and the tests after it
    that read it without a window of their own (theme.stylesheet(), T) drew in it."""
    theme = sys.modules.get("soundboard.ui.kit.theme")
    before = None if theme is None else (theme.current_name, theme.live_override,
                                         theme.textures_on)
    yield
    theme = sys.modules.get("soundboard.ui.kit.theme")
    if theme is None or before is None:
        return
    if (theme.current_name, theme.live_override, theme.textures_on) == before:
        return
    from PySide6.QtWidgets import QApplication
    name, theme.live_override, theme.textures_on = before
    app = QApplication.instance()
    if app is None:
        theme.set_current(name)
    else:
        theme.apply(app, name)


@pytest.fixture(autouse=True)
def _collect_on_the_main_thread():
    """What a test left in reference cycles is collected here, on the main thread
    (automatic collection is off: see the top of this file)."""
    yield
    uigc.let_go()
    uigc.collect_due()


def said(w) -> str:
    """What the toasts up on window ``w`` say, oldest first, one a line."""
    from soundboard.ui.kit import toast
    return "\n".join(t.text() for t in toast.shown(w))


def unsay(w):
    """Take every toast on window ``w`` down at once."""
    from soundboard.ui.kit import toast
    for t in toast.shown(w):
        t.dismiss()


def process_events(app, until, timeout=8.0, step=0.02):
    """Spin the Qt event loop until `until()` is true (or the timeout passes)."""
    import time
    from PySide6.QtCore import QEventLoop
    end = time.monotonic() + timeout
    while not until() and time.monotonic() < end:
        app.processEvents(QEventLoop.AllEvents, int(step * 1000))
        time.sleep(step / 4)
    return until()


def devices_done(win, timeout=8.0):
    """Until the window's device changes (picks, Re-scan) ran on the device thread
    and came back to the UI thread."""
    from PySide6.QtWidgets import QApplication
    assert process_events(QApplication.instance(), lambda: not win.devctl._dev_waiting
                          and not win.engine.devices.busy, timeout)


def loose_look(win, timeout=8.0):
    """One look at the sounds folder's loose files (ImportControl._take_loose), back
    from the thread that lists the folder. Its timer is stopped first, so it's this
    look and not one the timer starts."""
    from PySide6.QtWidgets import QApplication
    ctl, app = win.impctl, QApplication.instance()
    ctl._loose_timer.stop()
    assert process_events(app, lambda: not ctl._loose_looking, timeout)   # one going
    ctl._take_loose()
    assert process_events(app, lambda: not ctl._loose_looking, timeout)


@pytest.fixture
def app_dir(tmp_path, monkeypatch):
    """Point library's config/sounds paths at a temp folder."""
    from soundboard.sounds import library
    monkeypatch.setattr(library, "APP_DIR", tmp_path)
    monkeypatch.setattr(library, "SOUNDS_DIR", tmp_path / "sounds")
    monkeypatch.setattr(library, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(library, "THUMBS_DIR", tmp_path / "thumbs")
    monkeypatch.setattr(library, "CONFIG_PATH", tmp_path / "config.json")
    return tmp_path


@pytest.fixture(autouse=True)
def _temp_files_in_the_tests_folder(monkeypatch, tmp_path):
    """Downloads (ytdl's sb-ytdl-* folders), recordings and the like go in the test's
    own folder, which pytest clears: the tests that download from a stand-in site
    left hundreds of them in the real %TEMP%."""
    import tempfile
    d = tmp_path.with_name(tmp_path.name + "-temp")   # beside it: tests look inside tmp_path
    d.mkdir(exist_ok=True)
    monkeypatch.setattr(tempfile, "tempdir", str(d))


@pytest.fixture(autouse=True)
def _never_touch_real_appdata(monkeypatch, tmp_path):
    """Any test that forgets `app_dir` still can't write into %APPDATA%\\OnionBoard."""
    from soundboard.sounds import library
    monkeypatch.setattr(library, "USE_RECYCLE_BIN", False)   # removed test files: just deleted
    real = library.APP_DIR.parent   # read once: the loop re-points APP_DIR itself
    for name in ("APP_DIR", "OLD_APP_DIR", "SOUNDS_DIR", "CACHE_DIR", "THUMBS_DIR",
                 "CONFIG_PATH"):
        if getattr(library, name).is_relative_to(real):
            monkeypatch.setattr(library, name, tmp_path / "guard" / name.lower())
    # modules that took their own copy of APP_DIR at import: app.py's commands set up
    # the log there, and a test of one sent every later test's log lines (and crash
    # reports) into the developer's real onionboard.log
    for mod in ("soundboard.core.app", "soundboard.core.updates"):
        m = sys.modules.get(mod)
        if m is not None and Path(m.APP_DIR).is_relative_to(real):
            monkeypatch.setattr(m, "APP_DIR", tmp_path / "guard" / "app_dir")
    # ...and a test that first imports soundboard.core.app in its own body gets the real
    # folder (the loop above ran before): applog.setup itself never takes it in a test
    from soundboard.core import applog
    real_setup = applog.setup

    def setup(app_dir, *a, **k):
        if Path(app_dir).is_relative_to(real):
            app_dir = tmp_path / "guard" / "app_dir"
        return real_setup(Path(app_dir), *a, **k)
    monkeypatch.setattr(applog, "setup", setup)


@pytest.fixture(autouse=True)
def _keep_the_test_logging():
    """applog.setup() (an app command under test) swaps the root logger's handlers:
    put pytest's back afterwards and close the ones it made (the log's writer thread)."""
    import logging
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    for h in list(root.handlers):
        if h not in handlers:
            root.removeHandler(h)
            h.close()
    for h in handlers:
        if h not in root.handlers:
            root.addHandler(h)
    root.setLevel(level)


@pytest.fixture(autouse=True)
def _never_touch_the_real_mic(monkeypatch, tmp_path):
    """Straight into my mic (soundboard.mic.directmic): no test writes the real shared file
    the mic effect reads, runs the admin step, or sees this PC's own install or mics."""
    from soundboard.mic import directmic

    def no_admin(*_a, **_k):
        raise AssertionError("a test tried to run the mic effect's admin step")
    monkeypatch.setattr(directmic, "data_dir", lambda: tmp_path / "guard" / "OnionBoard" / "Mic")
    monkeypatch.setattr(directmic, "ring_path", lambda: tmp_path / "guard" / "ring2.bin")
    monkeypatch.setattr(directmic, "_elevated", no_admin)
    monkeypatch.setattr(directmic, "installed_on", lambda: [])
    monkeypatch.setattr(directmic, "capture_endpoints", lambda: [])   # nor this PC's mics
    monkeypatch.setattr(directmic, "_mic_is_silent", lambda guid: None)   # nor listens to one
    # nor opens one, or waits for the effect to start on one, or asks SteelSeries Sonar
    # about its devices, or reads or edits what Windows removes at its restart
    monkeypatch.setattr(directmic, "_mics_open", lambda guids: set())
    monkeypatch.setattr(directmic, "_effect_runs", lambda guids, mark: True)
    monkeypatch.setattr(directmic, "_processes", lambda exe: [])
    monkeypatch.setattr(directmic, "GG_PROPS", tmp_path / "guard" / "coreProps.json")
    monkeypatch.setattr(directmic, "_unmark", lambda paths: None)
    monkeypatch.setattr(directmic, "_marked", lambda path: False)
    # nor its mic helper (soundboard.mic.michelper): no real Program Files, task or queue
    from soundboard.mic import michelper

    def no_task(*_a, **_k):
        raise AssertionError("a test tried to use Windows' Task Scheduler")
    monkeypatch.setattr(michelper, "helper_dir", lambda: tmp_path / "guard" / "Helper")
    # "will Windows ask": known, no helper (like CI), so no check runs on a thread
    monkeypatch.setattr(michelper, "state",
                        michelper.HelperState({True: False, False: False}, "test"))
    monkeypatch.setattr(michelper, "queue_dir", lambda: tmp_path / "guard" / "MicHelper")
    monkeypatch.setattr(michelper, "_schtasks", no_task)
    monkeypatch.setattr(directmic, "helper_on", True)   # (Settings switches it: set_helper)
    directmic.forget_status()


@pytest.fixture(autouse=True)
def _never_watch_the_real_front_window(monkeypatch):
    """No test looks at this PC's window in front for games run as admin
    (soundboard.control.adminfront): a full-screen admin program here would put a notice in it.
    tests/test_adminfront.py drives the check with fakes."""
    from soundboard.control import adminfront
    monkeypatch.setattr(adminfront.Watcher, "start", lambda self: False)


@pytest.fixture(autouse=True)
def _never_read_the_real_discord(monkeypatch, tmp_path):
    """Discord's voice settings (soundboard.mic.discordcfg) come from an empty folder: the
    developer's own Discord must not put a banner in a test or a screenshot. Tests
    write a fake store under discordcfg._appdata() when they need one. Nor is it ever
    written to (discordtalk), and no Discord helper process is started."""
    from soundboard.mic import discordcfg, discordtalk
    root = tmp_path / "guard" / "discord-appdata"
    monkeypatch.setattr(discordcfg, "_appdata", lambda: root)
    monkeypatch.setattr(discordtalk, "start_helper", lambda *a, **k: False)


@pytest.fixture(autouse=True)
def _pictures_load_at_once(monkeypatch):
    """Pad pictures are read on a worker thread in the app (thumbs.LOAD_ASYNC); tests
    that check pictures and their caches get them at once, so a grab shows them. The
    tests of the worker itself turn it back on."""
    from soundboard.sounds import thumbs
    monkeypatch.setattr(thumbs, "LOAD_ASYNC", False, raising=False)


@pytest.fixture(autouse=True)
def _not_a_dev_pc(monkeypatch):
    """The developer's PCs set ONIONBOARD_NO_STATS (no usage count from them): the
    tests run as on anyone's PC, so the usage count tests see it sent."""
    monkeypatch.delenv("ONIONBOARD_NO_STATS", raising=False)


@pytest.fixture(autouse=True)
def _never_count_for_real(monkeypatch):
    """No test ever reaches the real GoatCounter: the usage count (and the problem
    events riding on it) would land in the project's real stats. Tests that send one
    point usage.ENDPOINT at their own stand-in server; anything else that slips
    through (a test faking sys.frozen that builds a window) hits a closed local port."""
    from soundboard.core import usage
    monkeypatch.setattr(usage, "ENDPOINT", f"http://127.0.0.1:{closed_port()}/api/v0/count")


@pytest.fixture(autouse=True)
def _never_touch_real_shortcuts(monkeypatch):
    """The theme re-icons the app's Desktop / Start menu shortcuts: never the
    developer's real ones (offscreen already skips it; this is the second lock)."""
    from soundboard.win import shellicon
    monkeypatch.setattr(shellicon, "shortcut_folders", lambda: [])


@pytest.fixture(autouse=True)
def _never_update_for_real(monkeypatch, tmp_path):
    """The update check is on by default: no test asks GitHub, downloads an installer
    into %APPDATA% or runs one. Tests fake the parts they exercise."""
    from soundboard.core import updates

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
def _never_use_the_real_store(monkeypatch):
    """No test reaches the real sound store (it has a daily allowance, and whether it was
    up decided some tests): a call to it gets an empty store at once, never the network.
    Tests that need other answers fake store._request or net.urlopen themselves."""
    import io

    from soundboard.online import net, store
    real = net.urlopen

    class Empty(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    def urlopen(req, *a, **k):
        if str(getattr(req, "full_url", req)).startswith(store.BASE):
            return Empty(b'{"sounds": [], "voices": [], "categories": [], "links": [], '
                         b'"more": false, "total": 0}')
        return real(req, *a, **k)
    monkeypatch.setattr(net, "urlopen", urlopen)


@pytest.fixture(autouse=True)
def _no_animal_call_downloads(monkeypatch):
    """Picking Cat or Dog downloads their recorded calls (voicefx.critters): never in a
    test, which hands it the calls it wants instead."""
    from soundboard.voicefx import critters
    monkeypatch.setattr(critters, "fetch", lambda kind: None)
    monkeypatch.setattr(critters, "_calls", {})


@pytest.fixture(autouse=True)
def _test_servers_stand_in_for_the_internet(monkeypatch, request):
    """The tests' radio stations and Radio Browser run on 127.0.0.x, standing in for
    internet hosts, so the relay's NEVER_THIS_PC refusal is off unless a test asks for
    it with @pytest.mark.real_this_pc."""
    if request.node.get_closest_marker("real_this_pc") is None:
        from soundboard.online import net
        monkeypatch.setattr(net, "NEVER_THIS_PC", frozenset())


@pytest.fixture(autouse=True)
def _switches_back_on():
    """Settings > Privacy & security's switches (soundboard.online.net) are process-wide: a
    test that switches something off doesn't leave it off for the next one."""
    yield
    from soundboard.online import net
    net.configure_features()


@pytest.fixture(autouse=True)
def _data_prefs_back_to_default(monkeypatch):
    """Settings > Data & quality (soundboard.online.quality.current) is process-wide too: a
    test that turns on Low data mode doesn't leave the next one without thumbnails."""
    quality = sys.modules.get("soundboard.online.quality")
    if quality is not None:
        monkeypatch.setattr(quality, "current", quality.Prefs())


class NoMidi:
    """soundboard.control.midi's winmm backend with no devices: tests never open the
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
    """The main window asks which game is in front (soundboard.mic.voicesdk) to suggest a
    Who's listening mode: in tests nothing is, whatever the developer is playing.
    For the whole session: test windows outlive their test, timers and all."""
    from soundboard.audio import appaudio
    from soundboard.mic import voicesdk
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(voicesdk, "foreground_process", lambda: (0, ""))
        # ...nor whether it fills the screen (no tip during a game, soundboard.core.tips)
        from soundboard.core import tips
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
    from soundboard.control import midi
    monkeypatch.setattr(midi, "WinMM", NoMidi)


@pytest.fixture(autouse=True)
def _never_touch_real_autostart(monkeypatch):
    """Building a MainWindow re-points an existing "start with Windows" entry at this
    copy of the app; in tests that would rewrite the developer's real Run key. Tests
    that exercise autostart put their own fake winreg in."""
    from soundboard.core import autostart
    monkeypatch.setattr(autostart, "winreg", None)


@pytest.fixture(autouse=True)
def _never_touch_real_mictest(monkeypatch):
    """The setup guide saves its mic test's result in the real HKCU on closing."""
    from soundboard.mic import mictest
    monkeypatch.setattr(mictest, "winreg", None)


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
    from soundboard.control import winkeys
    us = {winkeys.VK[k]: k for k in (";", "=", ",", "-", ".", "/", "`", "[", "\\", "]", "'")}
    return us.get(vk) or (chr(vk) if 0x30 <= vk <= 0x5A else "")


@pytest.fixture(autouse=True)
def _us_keyboard_layout(monkeypatch):
    """Key labels and the overlay key's layout check read the PC's keyboard layout;
    tests see a US one wherever they run."""
    from soundboard.control import winkeys
    monkeypatch.setattr(winkeys, "key_char", us_key_char)


@pytest.fixture(autouse=True)
def _fail_on_swallowed_exceptions(monkeypatch):
    """An exception in a Qt slot, a worker thread or the crash reporter never reaches
    pytest: PySide hands it to sys.excepthook and carries on, so the test passes while
    the user would get the crash dialog. Collect them and fail the test instead."""
    import threading

    from soundboard.core import applog
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
    from soundboard.mic import cableformat
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
_STOP_AFTER_TEST = (("soundboard.online.radio", "RadioPlayer", "shutdown"),
                    ("soundboard.ui.apps.approw", "_Lister", "stop"))


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
def _let_go_of_the_mouse():
    """Release any mouse button a test left held. QTest keeps the buttons it pressed
    for the whole process (Qt 6's mouseDClick ends on a press), and with one held
    every later test's mouseMove is a drag: no widget gets entered or hovered."""
    yield
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QWidget
    app = QApplication.instance()
    if app is None or app.mouseButtons() == Qt.NoButton:
        return
    from PySide6.QtTest import QTest
    spot = QWidget()
    spot.show()
    for button in (Qt.LeftButton, Qt.RightButton, Qt.MiddleButton):
        if app.mouseButtons() & button:
            QTest.mouseRelease(spot, button)
    spot.close()
    spot.deleteLater()


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


@pytest.fixture(autouse=True)
def _ffmpeg_works(monkeypatch):
    """The FFmpeg check (start-up and Settings' FFmpeg row) never runs the PC's real
    ffmpeg: it works, version 7.1. And no test ever runs the real winget or downloads
    FFmpeg: both steps of ffmpegget.fix fail at once unless a test fakes them. Tests of
    a missing or broken one patch ``ffmpegget.check`` / ``ffmpegget._check`` themselves."""
    from soundboard.online import ffmpegget
    works = ffmpegget.Health(ffmpegget.OK, "7.1", "ffmpeg.exe")

    def check():
        monkeypatch.setattr(ffmpegget, "_last", works)
        return works

    def no(*a, **k):
        raise ffmpegget.GetError("(tests never install or download FFmpeg)")
    monkeypatch.setattr(ffmpegget, "_last", None)
    monkeypatch.setattr(ffmpegget, "_early", None)
    monkeypatch.setattr(ffmpegget, "_has_winget", True)
    monkeypatch.setattr(ffmpegget, "check", check)
    monkeypatch.setattr(ffmpegget, "_with_winget", no)
    monkeypatch.setattr(ffmpegget, "_own_copy", no)
    monkeypatch.setattr(ffmpegget, "_winget", no)
    monkeypatch.setattr(ffmpegget, "_download_once", no)


@pytest.fixture(autouse=True)
def _no_tab_tours(monkeypatch, request):
    """A tab's first-visit how-to (ui/setup/tabtours.py) dims the window and holds its clicks:
    only the tests that set TAB_TOURS = True in their module get them."""
    if getattr(request.module, "TAB_TOURS", False):
        return
    from soundboard.ui.setup import tabtours
    monkeypatch.setattr(tabtours, "maybe_start", lambda win: None)
