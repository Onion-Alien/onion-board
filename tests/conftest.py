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
    # Chromium (the Radio tab's globe) must never reach the default device either.
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if "--mute-audio" not in flags:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = f"{flags} --mute-audio".strip()


def pytest_xdist_auto_num_workers(config):
    """`-n auto` (pyproject's addopts): the whole suite runs on 4 workers, about a
    quarter of the time; a file or two runs in this process, where starting workers
    would cost more than it saves. `-n 2` / `-n 0` on the command line override it."""
    picked = [a for a in config.args if Path(a.split("::")[0]).suffix == ".py"]
    if picked and len(picked) == len(config.args) and len(picked) <= 2:
        return 0
    return min(4, os.cpu_count() or 1)


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    return app


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
def _switches_back_on():
    """Settings > Privacy & security's switches (soundboard.net) are process-wide: a
    test that switches something off doesn't leave it off for the next one."""
    yield
    from soundboard import net
    net.configure_features()


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
        # ...nor which output Windows has as its default (the headphones follow it)
        mp.setattr(appaudio, "default_output_name", lambda: None)
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
def _no_result_stats_lookups(monkeypatch):
    """Web search cards look up each YouTube hit's likes and comments on a thread
    (ytsearch.SearchResults): never the real site from a test."""
    from soundboard import ytdl

    def offline(r):
        raise ytdl.FetchError("offline in tests")
    monkeypatch.setattr(ytdl, "stats", offline)
