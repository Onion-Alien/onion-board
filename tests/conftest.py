"""Test setup: run from the repo root so the flat modules import, never touch the
real %APPDATA%\\Soundboard folder, and keep Qt on the offscreen platform (no
window ever appears; the web engine still runs)."""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SOUNDBOARD_INSTANCE", "pytest")

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


# SOUNDBOARD_TEST_REAL_AUDIO=1 opts back in to real output devices.
if os.environ.get("SOUNDBOARD_TEST_REAL_AUDIO") != "1":
    import sounddevice
    sounddevice.OutputStream = _SilentOutputStream


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
    monkeypatch.setattr(library, "CONFIG_PATH", tmp_path / "config.json")
    return tmp_path


@pytest.fixture(autouse=True)
def _never_touch_real_appdata(monkeypatch, tmp_path):
    """Any test that forgets `app_dir` still can't write into %APPDATA%\\Soundboard."""
    from soundboard import library
    for name in ("APP_DIR", "SOUNDS_DIR", "CACHE_DIR", "CONFIG_PATH"):
        if getattr(library, name).is_relative_to(library.APP_DIR.parent):
            monkeypatch.setattr(library, name, tmp_path / "guard" / name.lower())
