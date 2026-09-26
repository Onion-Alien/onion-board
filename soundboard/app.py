"""Application entry point: logging, runtime tuning, single instance, the window."""
from __future__ import annotations

import ctypes
import gc
import logging
import os
import sys

# Render the window through the GPU from the start. The browser tab needs a GPU
# surface; without this, opening it the first time makes Qt destroy and rebuild the
# whole native window, which looks like the app closing and reopening.
# (Must be set before the QApplication exists. QT_WIDGETS_RHI=0 is the escape hatch
# on a machine whose GPU driver or remote-desktop session can't do it.)
os.environ.setdefault("QT_WIDGETS_RHI", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402

from soundboard import __version__, applog  # noqa: E402
from soundboard.library import APP_DIR  # noqa: E402
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


def main():
    log_path = applog.setup(APP_DIR)
    applog.install_hooks(log_path, __version__)
    tune_runtime_for_audio()
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Soundboard.App")
    except Exception:  # noqa: BLE001
        log.debug("SetCurrentProcessExplicitAppUserModelID failed", exc_info=True)
    app = QApplication(sys.argv)
    if not claim_single_instance():
        log.info("another Soundboard is running; asked it to come to the front")
        sys.exit(0)
    app.setStyle("Fusion")

    from soundboard.ui.mainwindow import MainWindow   # after the QApplication exists
    holder = {}
    app.instance_server = listen_for_second_launch(app, lambda: holder.get("w"))  # kept alive
    w = holder["w"] = MainWindow()
    w.show()
    from PySide6.QtCore import QTimer
    if not w.cfg.setup_done:   # first launch: walk them through mic, headphones, cable
        QTimer.singleShot(400, w.run_setup)
    QTimer.singleShot(30_000, lambda: start_ytdlp_check(w.cfg))
    sys.exit(app.exec())
