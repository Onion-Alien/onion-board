"""Restarting the PC (what the virtual cable may need after it's installed): Windows'
shutdown tool, started off the window's thread. Starting a program waits on Windows,
and on whatever checks a new program before it runs; on a PC short of memory that held
the window for up to two minutes ("Not responding") right after the Restart click. The
button says it's restarting at once; a start that fails comes back to the window."""
from __future__ import annotations

import subprocess
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from soundboard.core import errors
from soundboard.ui.kit import worker

COMMAND = ["shutdown", "/r", "/t", "5"]


class _Answer(QObject):
    failed = Signal(str)   # why it couldn't start (errors.plain)


def _run():
    subprocess.Popen(COMMAND, creationflags=subprocess.CREATE_NO_WINDOW)
    return worker.SKIP   # started: the PC restarts, nobody waits on an answer


def start(parent: QObject, on_fail: Callable[[str], None]) -> None:
    """Start the restart on a thread; `on_fail(why)` on the UI thread if it can't."""
    answer = _Answer(parent)

    def failed(why: str):
        answer.deleteLater()
        on_fail(why)
    answer.failed.connect(failed)
    worker.start(_run, answer.failed, "pc-restart", owner=answer,
                 error=lambda e: errors.plain(e) or type(e).__name__)
