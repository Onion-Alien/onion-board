"""Application entry point: logging, runtime tuning, single instance, the window."""
from __future__ import annotations

import ctypes
import gc
import logging
import os
import sys

# Render the window through the GPU from the start. The Radio tab's globe needs a GPU
# surface; without this, opening it the first time makes Qt destroy and rebuild the
# whole native window, which looks like the app closing and reopening.
# (Must be set before the QApplication exists. QT_WIDGETS_RHI=0 is the escape hatch
# on a machine whose GPU driver or remote-desktop session can't do it.)
os.environ.setdefault("QT_WIDGETS_RHI", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402

from soundboard import __version__, applog  # noqa: E402
from soundboard.library import APP_DIR, migrate_from_soundboard  # noqa: E402
from soundboard.singleinstance import claim_single_instance, listen_for_second_launch  # noqa: E402

log = logging.getLogger(__name__)


def tune_runtime_for_audio():
    """Two cheap knobs that keep the audio callbacks from waiting on the UI thread.

    The interpreter lets a thread hold the GIL for 5 ms before forcing a switch; a
    WASAPI callback at low latency has about 10 ms to produce its block, so a 5 ms
    wait is half its budget. 1 ms leaves the UI slightly less efficient and the
    audio thread almost never waiting.

    The garbage collector's gen-0 threshold is 700 allocations; numpy blocks in
    the callbacks are Python objects, so every few blocks a collection ran *on the
    audio thread*. Raising the threshold makes collections rarer (and they still
    run mostly on the UI thread, where a pause costs nothing).
    """
    sys.setswitchinterval(0.001)
    gc.set_threshold(50_000, 20, 20)


def start_ytdlp_check(cfg):
    """The daily "is there a newer yt-dlp?" check, off the UI thread (see ytdl.py)."""
    import threading

    from soundboard import ytdl
    threading.Thread(target=ytdl.auto_update, args=(cfg.ytdlp_auto_optin,), daemon=True,
                     name="ytdlp-update").start()


def selftest() -> int:
    """`OnionBoard.exe --selftest`: prove a (pruned) build can load everything it
    ships, without a window, a device, a hotkey or a network request. build.ps1
    runs it after trimming Qt (scripts/prune_build.py), so a missing DLL fails the
    build instead of a user's first launch. Prints OK and returns 0."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--mute-audio --disable-gpu")
    for mod in ("numpy", "scipy.signal", "sounddevice", "soundfile", "soxr", "yt_dlp"):
        __import__(mod)
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtMultimedia import QMediaPlayer
    from PySide6.QtWebEngineWidgets import QWebEngineView
    _app = QApplication(sys.argv)   # kept until the loop below has run
    from soundboard.ui import mainwindow, setupwizard, crashdialog  # noqa: F401
    from soundboard import engine, radio, theme  # noqa: F401
    theme.app_icon()
    QMediaPlayer()   # loads the FFmpeg multimedia plugin
    view = QWebEngineView()   # starts Chromium: resources, locale, the helper exe
    loop = QEventLoop()
    result = {}
    view.loadFinished.connect(lambda ok: (result.__setitem__("ok", ok), loop.quit()))
    QTimer.singleShot(30_000, loop.quit)
    view.setHtml("<html><body><script>document.title='ready'</script></body></html>")
    loop.exec()
    if not result.get("ok"):
        print("FAIL: the web engine didn't load a page", file=sys.stderr)
        return 1
    print(f"OK: Onion Board {__version__} self-test passed")
    return 0


def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    migrate_from_soundboard()
    log_path = applog.setup(APP_DIR)
    applog.install_hooks(log_path, __version__)
    from soundboard.library import MIGRATION_ERRORS
    for msg in MIGRATION_ERRORS:
        log.error("%s", msg)
    tune_runtime_for_audio()
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OnionBoard.App")
    except Exception:  # noqa: BLE001
        log.debug("SetCurrentProcessExplicitAppUserModelID failed", exc_info=True)
    app = QApplication(sys.argv)
    applog.ui_ready()
    if not claim_single_instance():
        log.info("another Onion Board is running; asked it to come to the front")
        sys.exit(0)
    app.setStyle("Fusion")
    from soundboard.ui import a11y
    a11y.install(app)   # screen-reader names for icon-only controls, as focus moves
    from soundboard import theme
    app.setWindowIcon(theme.app_icon())   # every window, and the taskbar button

    from soundboard.ui.mainwindow import MainWindow   # after the QApplication exists
    holder = {}
    app.instance_server = listen_for_second_launch(app, lambda: holder.get("w"))  # kept alive
    try:
        w = holder["w"] = MainWindow()
    except Exception:  # noqa: BLE001 - tell the user why nothing appeared, then quit
        applog.report(where="starting up", fatal=True)
        sys.exit(1)
    # Windows logging off / shutting down while the window is hidden in the tray never
    # calls closeEvent: still let go of push-to-talk and save the settings
    app.aboutToQuit.connect(w.shutdown)
    from soundboard.autostart import TRAY_ARG
    if not (TRAY_ARG in sys.argv and w.can_hide()):   # started with Windows: tray only
        w.show()
    from PySide6.QtCore import QTimer
    if "--resume-setup" in sys.argv:   # back after the restart the cable asked for
        QTimer.singleShot(400, lambda: w.run_setup(resumed=True))
    elif not w.cfg.setup_done:   # first launch: walk them through mic, headphones, cable
        QTimer.singleShot(400, w.run_setup)
    QTimer.singleShot(30_000, lambda: start_ytdlp_check(w.cfg))
    QTimer.singleShot(45_000, w.check_updates)   # only if opted in (updates.py)
    sys.exit(app.exec())
