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
