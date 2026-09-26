"""Only one Soundboard at a time.

A second copy would fight the first over the virtual cable and the hotkeys, and
every extra launch used to leave two more pythonw.exe processes lying around. The
lock is a named mutex, which Windows frees automatically if the app crashes, so
a stale lock can't keep it from starting. The second launch asks the first to
come to the front over a local socket.
"""
from __future__ import annotations

import ctypes
import logging
import os

from PySide6.QtCore import Qt
from PySide6.QtNetwork import QLocalServer, QLocalSocket

log = logging.getLogger(__name__)

# overridable so a test copy never finds (and pops up) the real, running app
INSTANCE_NAME = os.environ.get("SOUNDBOARD_INSTANCE", "Soundboard.App")


def claim_single_instance() -> bool:
    """True if we're the only Soundboard running. Otherwise asks the running one to
    come to the front and returns False."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    handle = k32.CreateMutexW(None, False, f"Local\\{INSTANCE_NAME}")
    if handle and ctypes.get_last_error() != 183:   # 183 = ERROR_ALREADY_EXISTS
        claim_single_instance.handle = handle        # held until the process exits
        return True
    try:
        ctypes.windll.user32.AllowSetForegroundWindow(-1)   # ASFW_ANY: let it take focus
    except Exception:  # noqa: BLE001
        log.debug("AllowSetForegroundWindow failed", exc_info=True)
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_NAME)
    if sock.waitForConnected(1500):
        sock.write(b"show")
        sock.waitForBytesWritten(500)
        sock.disconnectFromServer()
    return False


def listen_for_second_launch(app, get_window) -> QLocalServer:
    """Bring the window to the front when someone launches Soundboard again."""
    QLocalServer.removeServer(INSTANCE_NAME)
    server = QLocalServer(app)

    def on_connect():
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.disconnected.connect(conn.deleteLater)
        w = get_window()
        if w is not None:
            w.setWindowState((w.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
            w.show()
            w.raise_()
            w.activateWindow()

    server.newConnection.connect(on_connect)
    server.listen(INSTANCE_NAME)
    return server
