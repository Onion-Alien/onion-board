"""Logging and crash reporting.

The app runs under pythonw.exe, so there is no console: without this, every
traceback, Qt warning and swallowed error simply vanishes. Everything goes to a
small rotating log in the app folder, and an unhandled exception on the UI thread
also shows a dialog pointing at that log.

Set SOUNDBOARD_DEBUG=1 to log at DEBUG level.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path

LOG_NAME = "soundboard.log"
_shown = False   # only one crash dialog per run, so a repeating error can't stack dialogs


def setup(app_dir: Path) -> Path:
    """Send all logging to app_dir/soundboard.log (3 x 1 MB). Returns the log path."""
    app_dir.mkdir(parents=True, exist_ok=True)
    path = app_dir / LOG_NAME
    level = logging.DEBUG if os.environ.get("SOUNDBOARD_DEBUG") else logging.INFO
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    h = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=2,
                                             encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(threadName)s "
                                     "%(name)s: %(message)s"))
    root.addHandler(h)
    if sys.stderr is not None:   # a console is attached (python.exe): mirror there too
        root.addHandler(logging.StreamHandler(sys.stderr))
    return path


def install_hooks(log_path: Path, version: str):
    """Route unhandled exceptions (main thread, worker threads) and Qt's own
    messages into the log; show one dialog for a crash on the UI thread."""
    log = logging.getLogger("crash")
    log.info("Soundboard %s starting (python %s)", version, sys.version.split()[0])

    def excepthook(t, v, tb):
        log.critical("Unhandled exception", exc_info=(t, v, tb))
        _dialog(log_path, f"{t.__name__}: {v}")

    def thread_hook(args):
        log.critical("Unhandled exception in thread %s", args.thread.name if args.thread else "?",
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = excepthook
    threading.excepthook = thread_hook

    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except ImportError:   # tests without Qt
        return
    qlog = logging.getLogger("qt")
    levels = {QtMsgType.QtDebugMsg: logging.DEBUG, QtMsgType.QtInfoMsg: logging.DEBUG,
              QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
              QtMsgType.QtFatalMsg: logging.CRITICAL}

    def qt_handler(kind, _ctx, msg):
        qlog.log(levels.get(kind, logging.WARNING), "%s", msg)

    qInstallMessageHandler(qt_handler)


def _dialog(log_path: Path, what: str):
    global _shown
    if _shown or threading.current_thread() is not threading.main_thread():
        return
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance() is None:
            return
        _shown = True
        QMessageBox.critical(
            None, "Soundboard hit a problem",
            f"{what}\n\nDetails were written to:\n{log_path}\n\n"
            "The app will keep running, but if things look wrong, restart it.")
    except Exception:  # noqa: BLE001 - never let the crash reporter itself crash
        pass
