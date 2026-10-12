"""The Apps tab's window view: a small live picture of what a program shows, under
its card's buttons, opened with the card's eye button (soundboard.ui.appspanel).

A worker thread finds the program's window and copies it (soundboard.winshot)
about four times a second; the UI thread only turns the pixels into a picture.
It runs only while the view is open, on screen and the app is in front: hidden
tab, closed view or a game in front, and the worker sleeps.
"""
from __future__ import annotations

import logging
import threading
import time

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from soundboard import winshot
from soundboard.i18n import _
from soundboard.ui import appstate

log = logging.getLogger(__name__)

FRAME_S = 0.25        # a new picture this often
FIND_S = 2.0          # the window is looked up again this often (it may have changed)
VIEW_H = 180          # the picture's tallest, in pixels

MESSAGES = {
    winshot.MINIMISED: _("Minimised: nothing to show"),
    winshot.GONE: _("No window to show"),
    winshot.BLACK: _("This program doesn't share its picture"),
}


class _Grabber(QObject):
    """The worker: one thread per open view, asleep while there's nothing to do."""
    shot = Signal(object)    # winshot.Shot

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pids: tuple[int, ...] = ()
        self.limit: tuple[int, int] = (320, VIEW_H)   # the picture's largest, device pixels
        self._run = False                  # set by the UI thread: grab now
        self._stopped = False
        self._wake = threading.Event()
        self._hand_over = threading.Lock()  # held while emitting; stop() takes it
        self._thread: threading.Thread | None = None

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
        while not self._stopped:
            if not self._run:
                self._wake.wait()
                self._wake.clear()
                hwnd, found_at = 0, -FIND_S   # back from a pause: look it up again
                continue
            started = time.monotonic()
            try:
                if not hwnd or started - found_at >= FIND_S:
                    hwnd, found_at = winshot.find_window(self.pids), started
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
                self.shot.emit(shot)
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
        self.max_h = VIEW_H
        self.status = ""
        self._open = False
        self._grabber: _Grabber | None = None
        self._pids: tuple[int, ...] = ()
        self.picture.hide()
        self.message.setText(_("Looking for its window…"))
        self.hide()
        appstate.pause_in_background(self, self._wake, self._sleep)

    @property
    def is_open(self) -> bool:
        return self._open

    def set_pids(self, pids):
        self._pids = tuple(pids)
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
            self._grabber.shot.connect(self._show)
            self._resize_grab()
            self._wake()
        else:
            self._end()
            self.status = ""
            self.picture.clear()
            self.picture.hide()
            self.message.setText(_("Looking for its window…"))
            self.message.show()

    def _end(self):
        if self._grabber is not None:
            self._grabber.stop()
            self._grabber.shot.disconnect(self._show)
            self._grabber.deleteLater()
            self._grabber = None

    def _wake(self):
        if self._grabber is not None and self.isVisible() and appstate.active():
            self._grabber.resume()

    def _sleep(self):
        if self._grabber is not None:
            self._grabber.pause()

    def showEvent(self, e):
        super().showEvent(e)
        self._wake()

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

    def _show(self, shot: winshot.Shot):
        if not self._open:
            return
        self.status = shot.status
        if shot.status != winshot.OK:
            self.picture.hide()
            self.message.setText(MESSAGES.get(shot.status, MESSAGES[winshot.GONE]))
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
