"""Only one Onion Board at a time.

A second copy would fight the first over the audio devices and the hotkeys, and
every extra launch used to leave two more pythonw.exe processes lying around. The
lock is a named mutex, which Windows frees automatically if the app crashes, so
a stale lock can't keep it from starting. The second launch asks the first to
come to the front over a local socket.
"""
from __future__ import annotations

import ctypes
import logging
import os
import time

from PySide6.QtCore import Qt
from PySide6.QtNetwork import QLocalServer, QLocalSocket

log = logging.getLogger(__name__)

# overridable so a test copy never finds (and pops up) the real, running app
INSTANCE_NAME = os.environ.get("ONIONBOARD_INSTANCE", "OnionBoard.App")
CONNECT_SECONDS = 5.0   # how long a second launch waits for the first to answer


def claim_single_instance() -> bool:
    """True if we're the only Onion Board running. Otherwise asks the running one to
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
    # The running copy may still be starting up (its server not listening yet): keep
    # trying for a few seconds before telling the user to go look for it.
    deadline = time.monotonic() + CONNECT_SECONDS
    while True:
        sock.connectToServer(INSTANCE_NAME)
        if sock.waitForConnected(500) or time.monotonic() >= deadline:
            break
        sock.abort()
        time.sleep(0.2)
    if sock.state() == QLocalSocket.LocalSocketState.ConnectedState:
        sock.write(b"show")
        sock.waitForBytesWritten(500)
        sock.disconnectFromServer()
    else:   # the running copy didn't answer: don't just vanish without a word
        log.warning("the running Onion Board didn't answer: %s", sock.errorString())
        try:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                None, "Onion Board is already running",
                "Onion Board is already open. Look for its icon in the taskbar tray "
                "(the ^ arrow by the clock).\n\nIf you can't find it, end “Onion Board” "
                "in Task Manager and start it again.")
        except Exception:  # noqa: BLE001
            log.debug("couldn't show the already-running message", exc_info=True)
    return False


def listen_for_second_launch(app, get_window) -> QLocalServer:
    """Bring the window to the front when someone launches Onion Board again."""
    QLocalServer.removeServer(INSTANCE_NAME)
    server = QLocalServer(app)
    server.show_requested = False

    def on_connect():
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.disconnected.connect(conn.deleteLater)
        w = get_window()
        if w is None:   # still starting up: app.main() shows it once it exists
            server.show_requested = True
        else:
            w.setWindowState((w.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
            w.show()
            w.raise_()
            w.activateWindow()

    server.newConnection.connect(on_connect)
    if not server.listen(INSTANCE_NAME):
        log.warning("single-instance server couldn't listen: %s", server.errorString())
    return server
