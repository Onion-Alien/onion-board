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


class InstanceServer(QLocalServer):
    show_requested = False   # launched again before the window existed


def comes_to_front(argv: list[str], show_requested: bool) -> bool:
    """Whether the main window takes the focus once it first shows. Yes on a normal
    start (the installer's "Open Onion Board now", a shortcut): the splash never takes
    the focus, so without this the window lands behind the browser. Not when started
    with Windows (--tray) or started again by Windows after a crash or an update
    (--restarted), where a game may be in front, unless someone launched it again
    meanwhile (that copy already let us take the focus)."""
    from soundboard.autostart import TRAY_ARG
    return not ({TRAY_ARG, "--restarted"} & set(argv)) or show_requested


def bring_to_front(w):
    """raise_ + activateWindow, and on Windows past the foreground lock: the launcher
    (the installer) has usually exited by now, so Windows keeps whatever is next in
    front and only flashes the taskbar button. Joining the input of the window in front
    for a moment lets SetForegroundWindow work."""
    w.raise_()
    w.activateWindow()
    try:
        from ctypes import wintypes
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        u32.GetForegroundWindow.restype = wintypes.HWND
        u32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.c_void_p)
        u32.GetWindowThreadProcessId.restype = wintypes.DWORD
        u32.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
        u32.BringWindowToTop.argtypes = (wintypes.HWND,)
        u32.SetForegroundWindow.argtypes = (wintypes.HWND,)
        hwnd = int(w.winId())
        front = u32.GetForegroundWindow()
        if not hwnd or front == hwnd:
            return
        theirs = u32.GetWindowThreadProcessId(front, None) if front else 0
        mine = k32.GetCurrentThreadId()
        joined = bool(theirs and theirs != mine and u32.AttachThreadInput(mine, theirs, True))
        try:
            u32.BringWindowToTop(hwnd)
            u32.SetForegroundWindow(hwnd)
        finally:
            if joined:
                u32.AttachThreadInput(mine, theirs, False)
    except Exception:  # noqa: BLE001 - raise_ + activateWindow already ran
        log.debug("couldn't bring the window to the front", exc_info=True)


def listen_for_second_launch(app, get_window) -> InstanceServer:
    """Bring the window to the front when someone launches Onion Board again."""
    QLocalServer.removeServer(INSTANCE_NAME)
    server = InstanceServer(app)

    def on_connect():
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.disconnected.connect(conn.deleteLater)
        w = get_window()
        if w is None:   # still starting up: app.main() shows it once it exists
            server.show_requested = True
        else:
            w.setWindowState((w.windowState() & ~Qt.WindowState.WindowMinimized)
                             | Qt.WindowState.WindowActive)
            w.show()
            w.raise_()
            w.activateWindow()

    server.newConnection.connect(on_connect)
    if not server.listen(INSTANCE_NAME):
        log.warning("single-instance server couldn't listen: %s", server.errorString())
    return server
