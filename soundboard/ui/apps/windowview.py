"""The Apps tab's window view: a small live picture of what a program shows, under
its card's buttons, opened with the card's eye button (soundboard.ui.apps.appspanel).

A worker thread finds the program's window and copies it (soundboard.win.winshot)
about four times a second; the UI thread only turns the pixels into a picture.
It runs while the view is open and on screen, including while another app has
focus. Minimized sources keep their last picture with a paused message.
"""
from __future__ import annotations

import logging
import threading
import time

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from soundboard.win import winshot
from soundboard.i18n import _

log = logging.getLogger(__name__)

FRAME_S = 0.25        # a new picture this often
FIND_S = 2.0          # the window is looked up again this often (it may have changed)
VIEW_H = 320          # the picture's tallest, in pixels

MESSAGES = {
    winshot.MINIMISED: _("Minimised: restore for live updates"),
    winshot.GONE: _("No window to show"),
    winshot.BLACK: _("This program doesn't share its picture"),
}


class _Grabber(QObject):
    """The worker: one thread per open view, asleep while there's nothing to do."""
    shot = Signal(object)    # winshot.Shot

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pids: tuple[int, ...] = ()
        self.limit: tuple[int, int] = (560, VIEW_H)   # the picture's largest, device pixels
        self._run = False                  # set by the UI thread: grab now
        self._stopped = False
        self._wake = threading.Event()
        self._hand_over = threading.Lock()  # held while emitting; stop() takes it
        self._thread: threading.Thread | None = None
        self._restore = threading.Event()
        self._restore_pids: tuple[int, ...] = ()

    def restore(self):
        self._restore_pids = self.pids
        self._restore.set()
        self._wake.set()

    def resume(self):
        self._run = True
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, name="windowview", daemon=True)
            self._thread.start()
        self._wake.set()

    def pause(self):
        self._run = False

    def stop(self):
        with self._hand_over:
            self._stopped = True
        self._wake.set()

    def _loop(self):
        hwnd, found_at = 0, -FIND_S
        found_pids = ()
        while not self._stopped:
            if not self._run:
                self._wake.wait()
                self._wake.clear()
                hwnd, found_at = 0, -FIND_S   # back from a pause: look it up again
                continue
            started = time.monotonic()
            pids = self.pids
            try:
                if self._restore.is_set():
                    self._restore.clear()
                    if pids == self._restore_pids:
                        winshot.restore_window(pids)
                    hwnd = 0
                if not hwnd or pids != found_pids or started - found_at >= FIND_S:
                    hwnd, found_at = winshot.find_window(pids), started
                    found_pids = pids
                w, h = self.limit
                shot = winshot.grab(hwnd, w, h)
                if shot.status == winshot.GONE:
                    hwnd = 0
            except Exception:  # noqa: BLE001
                log.debug("window view failed", exc_info=True)
                shot = winshot.Shot(winshot.GONE)
            with self._hand_over:
                if self._stopped:
                    return
                self.shot.emit((pids, shot))
            self._wake.wait(max(0.0, FRAME_S - (time.monotonic() - started)))
            self._wake.clear()


class WindowView(QWidget):
    """The picture (or a line saying why there isn't one). `set_pids` says whose
    window; `set_open` starts and stops it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.picture = QLabel()
        self.picture.setObjectName("windowview")
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.picture.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.message = QLabel()
        self.message.setObjectName("hint")
        self.message.setWordWrap(True)
        v.addWidget(self.picture)
        v.addWidget(self.message)
        self.restore = QPushButton(_("Restore"))
        self.restore.setObjectName("small")
        self.restore.clicked.connect(self._restore_window)
        v.addWidget(self.restore, 0, Qt.AlignmentFlag.AlignLeft)
        self.restore.hide()
        self.max_h = VIEW_H
        self.status = ""
        self._open = False
        self._grabber: _Grabber | None = None
        self._pids: tuple[int, ...] = ()
        self.picture.hide()
        self.message.setText(_("Looking for its window…"))
        self.hide()

    @property
    def is_open(self) -> bool:
        return self._open

    def set_pids(self, pids):
        pids = tuple(pids)
        if pids != self._pids:
            self.picture.clear()
            self.picture.hide()
        self._pids = pids
        if self._grabber is not None:
            self._grabber.pids = self._pids

    def set_open(self, on: bool):
        if on == self._open:
            return
        self._open = on
        self.setVisible(on)
        if on:
            self._grabber = _Grabber(self)
            self._grabber.pids = self._pids
            self._grabber.shot.connect(self._received)
            self._resize_grab()
            self._wake()
        else:
            self._end()
            self.status = ""
            self.picture.clear()
            self.picture.hide()
            self.restore.hide()
            self.message.setText(_("Looking for its window…"))
            self.message.show()

    def _end(self):
        if self._grabber is not None:
            self._grabber.stop()
            self._grabber.shot.disconnect(self._received)
            self._grabber.deleteLater()
            self._grabber = None

    def _wake(self):
        if (self._grabber is not None and self.isVisible()
                and not self.window().isMinimized()):
            self._grabber.resume()

    def _restore_window(self):
        if self._grabber is not None and self.status == winshot.MINIMISED:
            self._grabber.restore()

    def _sleep(self):
        if self._grabber is not None:
            self._grabber.pause()

    def showEvent(self, e):
        super().showEvent(e)
        self.window().installEventFilter(self)
        self._wake()

    def eventFilter(self, obj, e):
        if obj is self.window() and e.type() == QEvent.Type.WindowStateChange:
            if obj.isMinimized():
                self._sleep()
            else:
                self._wake()
        return super().eventFilter(obj, e)

    def hideEvent(self, e):
        super().hideEvent(e)
        self._sleep()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._resize_grab()

    def _resize_grab(self):
        if self._grabber is not None:
            dpr = self.devicePixelRatioF()
            self._grabber.limit = (max(32, round(self.width() * dpr)),
                                  max(32, round(self.max_h * dpr)))

    def _received(self, result):
        pids, shot = result
        if self.sender() is self._grabber and pids == self._pids:
            self._show(shot)

    def _show(self, shot: winshot.Shot):
        if not self._open:
            return
        self.status = shot.status
        self.restore.setVisible(shot.status == winshot.MINIMISED)
        if shot.status != winshot.OK:
            cached = shot.status == winshot.MINIMISED and not self.picture.pixmap().isNull()
            self.picture.setVisible(cached)
            if not cached:
                self.picture.clear()
            self.message.setText(_("Minimised: last picture") if cached else
                                 MESSAGES.get(shot.status, MESSAGES[winshot.GONE]))
            self.message.show()
            return
        img = QImage(shot.data, shot.width, shot.height, shot.width * 4,
                     QImage.Format.Format_RGB32).copy()
        pm = QPixmap.fromImage(img)
        pm.setDevicePixelRatio(self.devicePixelRatioF())
        self.picture.setPixmap(pm)
        size = pm.deviceIndependentSize().toSize()
        self.picture.setFixedHeight(max(1, size.height()))
        self.message.hide()
        self.picture.show()

    def sizeHint(self):
        return QSize(0, super().sizeHint().height())

    def closeEvent(self, e):
        self._end()
        super().closeEvent(e)
