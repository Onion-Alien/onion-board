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
