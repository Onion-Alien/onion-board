"""Discoverable recovery for Onion Board's Windows microphone effect."""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QGraphicsDropShadowEffect)
from shiboken6 import isValid as qt_valid

from soundboard import directmic, errors, theme
from soundboard.i18n import _
from soundboard.ui import busy, fit, icons
from soundboard.ui.panel import Flow

log = logging.getLogger(__name__)


def action_text(action):
    return {"repair": _("Repair mic effect"), "update": _("Update mic effect"),
            "reinstall": _("Clean reinstall"),
            "remove": _("Remove mic effect")}[action]


def explanation(action):
    if action == "update":
        action = "repair"
    return {
        "repair": _("Reinstall Onion Board's mic effect on your selected microphone."),
        "reinstall": _("Restore your microphones, remove the old mic effect, then install "
                       "a fresh copy on your selected microphone."),
        "remove": _("Restore your microphones and remove Onion Board's mic effect. "
                    "Sounds will stop going straight into your mic."),
    }[action]


class Recovery(QObject):
    """Lives with the main window, so closing Settings cannot abandon a repair."""
    finished = Signal(str, str, str)

    def __init__(self, mw):
        super().__init__(mw)
        self.mw = mw
        self.running = False
        self.finished.connect(self._finished)

    def start(self, action):
        if self.running or self.mw._attaching:
            return False
        mic = self.mw.cfg.mic_device
        if action != "remove" and not mic:
            self.mw.toast(_("Pick your mic first (Setup tab → Devices)."), "warn")
            return False
        self.running = True
        self.mw._attaching = True
        threading.Thread(target=self._work, args=(action, mic), daemon=True,
                         name="audio-recovery").start()
        return True

    def _work(self, action, mic):
        err, state = "", ""
        try:
            err = (directmic.uninstall() if action == "remove" else
                   directmic.install(mic, clean=action == "reinstall")) or ""
            directmic.forget_status()
            state = directmic.status(mic)
            if not err and action == "remove" and directmic.anything_installed():
                err = _("Repair failed")
            elif not err and action != "remove" and state != "ready":
                err = _("The mic effect could not be verified. Restart your PC, then try "
                        "Repair mic effect again.")
        except Exception as exc:  # noqa: BLE001 - report unexpected device failures
            log.exception("audio recovery failed")
            err = errors.plain(exc)
        busy.emit(self.finished, action, err, state)

    def _finished(self, action, err, state):
        self.running = False
        self.mw._attaching = False
        self.mw._when_devices_free(lambda: self.mw._refresh_off_ui())
        if err:
            self.mw.toast(_("{error}", error=err), "warn")


class RecoveryCard(QFrame):
    checked = Signal(str, str)

    def __init__(self, mw, parent=None):
        super().__init__(parent)
        self.mw = mw
        if not hasattr(mw, "audio_recovery"):
            mw.audio_recovery = Recovery(mw)
        self.recovery = mw.audio_recovery
        self._state = ""
        self.setObjectName("setcard")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 14)
        v.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(8)
        icon = QLabel()
        pixmap = icons.icon("mic").pixmap(24, 24)
        pixels = pixmap.toImage()
        occupied = [x for x in range(pixels.width())
                    if any(pixels.pixelColor(x, y).alpha() for y in range(pixels.height()))]
        if occupied:
            pixmap = pixmap.copy(min(occupied), 0, max(occupied) - min(occupied) + 1,
                                 pixmap.height())
        icon.setPixmap(pixmap)
        icon.setFixedSize(pixmap.size())
        head.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)
        title = QLabel(_("Audio recovery"))
        title.setObjectName("section")
        title.setProperty("keepline", True)
        self.heading = title
        head.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addStretch(1)
        v.addLayout(head)
        hint = QLabel(_("Fix problems sending sounds into your mic after an update."))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        v.addWidget(hint)
        row = Flow(gap=8)
        self.repair = QPushButton(_("Update to new version"))
        self.repair.setObjectName("primary")
        self.repair.hide()
        self.repair.clicked.connect(lambda: self.confirm("update"))
        row.addWidget(self.repair)
        self.actions = {"repair": self.repair}
        for action in ("reinstall", "remove"):
            button = QPushButton(action_text(action))
            icons.set_icon(button, "reload" if action == "reinstall" else "trash")
            if action == "remove":
                button.setObjectName("danger")
                button.setProperty("small", True)
            else:
                button.setObjectName("small")
            button.clicked.connect(lambda checked=False, a=action: self.confirm(a))
            self.actions[action] = button
            row.addWidget(button)
        v.addLayout(row)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setObjectName("hint")
        self.note.hide()
        v.addWidget(self.note)
        self.checked.connect(self._checked)
        self.recovery.finished.connect(self._done)
        self._sync_busy()
        self._checking = False
        self.timer = QTimer(self)
        self.timer.setInterval(5000)
        self.timer.timeout.connect(self.check)
        self.timer.start()
        QTimer.singleShot(0, self, self.check)

    def check(self):
        if self._checking or not self.isVisible():
            return
        self._checking = True
        mic = self.mw.cfg.mic_device

        def work():
            try:
                state = directmic.status(mic)
            except Exception:  # noqa: BLE001 - keep settings usable if Windows refuses
                log.exception("couldn't check mic effect")
                state = "unknown"
            busy.emit(self.checked, state, mic or "")
        threading.Thread(target=work, daemon=True, name="recovery-status").start()

    def _checked(self, state, mic=None):
        self._checking = False
        if mic is not None and mic != (self.mw.cfg.mic_device or ""):
            return
        self._state = state
        self.repair.setText(_("Update to new version"))
        self.repair.setVisible(state == "outdated")
        self.repair.setProperty("recoveryUpdate", state == "outdated")
        self.repair.style().unpolish(self.repair)
        self.repair.style().polish(self.repair)
        if state == "outdated":
            glow = QGraphicsDropShadowEffect(self.repair)
            glow.setColor(QColor(theme.T["warn_text"]))
            glow.setBlurRadius(12)
            glow.setOffset(0, 0)
            self.repair.setGraphicsEffect(glow)
        else:
            self.repair.setGraphicsEffect(None)

    def confirm(self, action):
        if self.recovery.running or self.mw._attaching:
            return
        if getattr(self, "dialog", None) and qt_valid(self.dialog) and self.dialog.isVisible():
            self.dialog.raise_()
            return
        d = QDialog(self.window())
        self.dialog = d
        d.setWindowTitle(action_text(action))
        d.setMaximumWidth(620)
        d.resize(500, 200)
        v = QVBoxLayout(d)
        v.setContentsMargins(18, 18, 18, 18)
        title = QLabel(action_text(action))
        title.setObjectName("section")
        v.addWidget(title)
        for text in (explanation(action),
                     _("Windows will ask for permission. Audio will briefly stop, "
                       "including calls and games."),
                     _("Your sounds and settings are kept.")):
            label = QLabel(text)
            label.setWordWrap(True)
            v.addWidget(label)
        row = QHBoxLayout()
        go = QPushButton(action_text(action))
        go.setObjectName("danger" if action == "remove" else "primary")
        go.clicked.connect(lambda: self._start(action, d))
        cancel = QPushButton(_("Cancel"))
        cancel.clicked.connect(d.reject)
        row.addStretch(1)
        row.addWidget(go)
        row.addWidget(cancel)
        v.addLayout(row)
        width = max(go.sizeHint().width(), cancel.sizeHint().width())
        height = max(go.sizeHint().height(), cancel.sizeHint().height())
        go.setFixedSize(width, height)
        cancel.setFixedSize(width, height)
        fit.watch(d)
        d.finished.connect(d.deleteLater)
        d.show()

    def _start(self, action, dialog):
        if self.recovery.start(action):
            dialog.accept()
            self.note.setText(_("Working…"))
            self.note.show()
            self._sync_busy()

    def _sync_busy(self):
        for button in self.actions.values():
            busy.set_busy(button, self.recovery.running)
        if self.recovery.running:
            self.note.setText(_("Working…"))
            self.note.show()

    def _done(self, action, err, state):
        self._sync_busy()
        self._checked(state)
        self.note.show()
        self.note.setText(err or (_("Mic effect removed") if action == "remove" else
                                  _("Mic effect reinstalled. Test it in your voice chat.")))
        theme.set_tone(self.note, "warn" if err else "ok")
