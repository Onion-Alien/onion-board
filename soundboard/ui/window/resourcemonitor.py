"""Live resource readings and manual cleanup, shared by the toolbar and Bun's menu."""
from __future__ import annotations

import ctypes
import shutil
import sys
from functools import lru_cache
from typing import TYPE_CHECKING

from PySide6.QtCore import QLocale, QTimer, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QGridLayout, QLabel, QProgressBar, QSizePolicy,
                               QWidget)

from soundboard.core import hangwatch
from soundboard.i18n import _, ngettext
from soundboard.online import ytworker
from soundboard.sounds.paths import SOUNDS_DIR
from soundboard.ui.kit import busy, worker
from soundboard.ui.kit.modalframe import ModalDialog
from soundboard.ui.kit.panel import steady_number
from soundboard.ui.kit.wheelguard import no_wheel, snug_combo
from soundboard.ui.window.controller import Controller

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

RELEASE_INTERVALS = (0, 30, 60, 120, 300, 600, 900)
RETRY_MS = 5000


@lru_cache(maxsize=1)
def _system_times():
    if sys.platform == "win32":
        return ctypes.WinDLL("kernel32").GetSystemTimes
    return None


def _cpu_times() -> tuple[int, int] | None:
    get = _system_times()
    if get is None:
        return None
    idle, kernel, user = (ctypes.c_ulonglong() for _ in range(3))
    if get(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        return idle.value, kernel.value + user.value
    return None


class ResourceControl(Controller):
    """One cleanup worker and schedule for the window, even with the monitor closed."""

    started = Signal()
    released = Signal(bool)

    def __init__(self, window: MainWindow):
        super().__init__(window)
        self._monitor = None
        self.releasing = False
        self._timer = QTimer(self, singleShot=True)
        self._timer.timeout.connect(self._auto_release)
        self.released.connect(self._finished)

    def show_monitor(self):
        if self._monitor is None:
            self._monitor = ResourceMonitor(self)
        self._monitor.sync_interval()
        self._monitor.open()

    @property
    def interval(self) -> int:
        seconds = self.mw.cfg.ram_release_interval
        return seconds if type(seconds) is int and seconds in RELEASE_INTERVALS else 0

    def set_interval(self, seconds: int):
        self.mw.set_option("ram_release_interval", seconds)
        self.schedule()

    def schedule(self):
        self._timer.stop()
        if self.interval:
            self._timer.start(self.interval * 1000)

    def stop(self):
        self._timer.stop()

    def _auto_release(self):
        mw = self.mw
        if not self.interval or mw._shut_down:
            return
        speech = getattr(mw.voice, "controller", None)
        radio_recorder = getattr(mw.radio, "recorder", None)
        if (not mw.engine.quiet() or getattr(mw.soundctl, "_record_dlg", None) is not None
                or (radio_recorder is not None and radio_recorder.recording)
                or (speech is not None and speech.speaker.busy)):
            self._timer.start(RETRY_MS)
            return
        self.release_ram()

    def release_ram(self):
        mw = self.mw
        if mw._shut_down or self.releasing:
            return
        self._timer.stop()
        self.releasing = True
        self.started.emit()
        engine = mw.engine
        speech = getattr(mw.voice, "controller", None)

        def run():
            engine.release_cached_audio()
            ytworker.drop_all()
            if speech is not None:
                speech.release_idle_helpers()
            return True

        worker.start(run, self.released, "release-ram", error=False, owner=self)

    def _finished(self, _ok: bool):
        self.releasing = False
        if not self.mw._shut_down:
            self.schedule()


class ResourceMonitor(ModalDialog):
    sampled = Signal(object, object, object, object)

    def __init__(self, control: ResourceControl):
        super().__init__(control.mw, _("Resource monitor"), icon="wave", width=376)
        self._control = control
        self._previous = None
        self._sampling = False
        self._rows = []
        grid_box = QWidget()
        grid_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        grid = QGridLayout(grid_box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)
        for row, name in enumerate((_("CPU"), _("RAM"), _("Library drive"))):
            grid.addWidget(QLabel(name), row, 0)
            bar = QProgressBar()
            bar.setObjectName("downloadprogress")
            bar.setAccessibleName(name)
            bar.setTextVisible(False)
            bar.setFixedHeight(6)
            bar.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            bar.setMinimumWidth(36)
            grid.addWidget(bar, row, 1)
            value = QLabel("—")
            steady_number(value, QLocale().toString(100) + QLocale().percent())
            grid.addWidget(value, row, 2, Qt.AlignmentFlag.AlignTrailing)
            self._rows.append((bar, value))
        grid.addWidget(QLabel(_("Onion Board RAM")), 3, 0)
        self._app_ram = QLabel("—")
        grid.addWidget(self._app_ram, 3, 1, 1, 2, Qt.AlignmentFlag.AlignTrailing)
        self.frame.add_widget(grid_box)

        interval_label = QLabel(_("Auto-release RAM"))
        self._interval = QComboBox()
        self._interval.setAccessibleName(interval_label.text())
        interval_label.setBuddy(self._interval)
        self._interval.addItem(_("Off"), 0)
        self._interval.addItem(_("{n} s", n=30), 30)
        for seconds in RELEASE_INTERVALS[2:]:
            self._interval.addItem(ngettext("{n} min", "{n} min", seconds // 60), seconds)
        snug_combo(self._interval)
        no_wheel(self._interval)
        grid.addWidget(interval_label, 4, 0)
        grid.addWidget(self._interval, 4, 1, 1, 2, Qt.AlignmentFlag.AlignTrailing)
        self._interval.activated.connect(lambda i: control.set_interval(self._interval.itemData(i)))

        self._release = self.frame.add_button(_("Release RAM"), primary=True)
        self._release.clicked.connect(control.release_ram)
        self.frame.close_btn.setAutoDefault(False)
        self._release.setAutoDefault(False)
        self.focus_first(self.frame.close_btn)
        self.sampled.connect(self._show_sample)
        control.started.connect(self._release_started)
        control.released.connect(self._release_done)
        if control.releasing:
            self._release_started()
        self._timer = QTimer(self, interval=1000)
        self._timer.timeout.connect(self._sample)

    def sync_interval(self):
        self._interval.setCurrentIndex(self._interval.findData(self._control.interval))

    def showEvent(self, event):  # noqa: N802 - Qt API
        super().showEvent(event)
        self._timer.start()
        self._sample()

    def hideEvent(self, event):  # noqa: N802 - Qt API
        self._timer.stop()
        self._previous = None
        super().hideEvent(event)

    def _sample(self):
        if self._sampling:
            return
        self._sampling = True

        def run():
            try:
                times = _cpu_times()
            except (OSError, AttributeError):
                times = None
            ram = hangwatch.memory_load()
            app_ram = hangwatch.working_set()
            try:
                disk = shutil.disk_usage(SOUNDS_DIR)
                used = round(100 * disk.used / disk.total) if disk.total else None
            except OSError:
                used = None
            return times, ram, used, app_ram

        worker.start(run, self.sampled, "resource-sample", error=(None,) * 4, owner=self)

    def _show_sample(self, times, ram, disk, app_ram):
        self._sampling = False
        if not self.isVisible():
            return
        cpu = None
        previous, self._previous = self._previous, times
        if previous is not None and times is not None:
            idle, total = (new - old for new, old in zip(times, previous))
            if total > 0:
                cpu = round(100 * (1 - idle / total))
        locale = QLocale()
        for (bar, label), percent in zip(self._rows, (cpu, ram, disk)):
            if percent is None:
                bar.setValue(0)
                label.setText("—")
            else:
                percent = min(100, max(0, percent))
                bar.setValue(percent)
                label.setText(locale.toString(percent) + locale.percent())
        self._app_ram.setText(locale.formattedDataSize(app_ram) if app_ram is not None
                              else "—")

    def _release_started(self):
        self._finish_release = busy.hold(self._release, _("Releasing RAM…"))

    def _release_done(self, ok):
        self._finish_release(_("Done") if ok else _("Didn't work, try again"))
        if self.isVisible():
            self._sample()
