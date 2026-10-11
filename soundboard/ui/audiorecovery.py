"""Discoverable recovery for Onion Board's Windows microphone effect.

The card in Settings > Audio shows where the mic effect stands as a pill. The one fix
it needs (update, or repair when Windows took it off the mic) is the card's main
button; the rare actions (repair, clean reinstall, remove) sit behind its ⋯ menu.
While a fix runs, the setup guide's show plays under it (ui/setupshow.py: Bun
builds a speaker, then it thumps and he cheers, or it goes BOOM).

The mic it works on is picked on the card itself ("Mic to fix"), by the mic's Windows
endpoint, not its name: two mics can share a name, and one can be unplugged. The
effect sits on one mic at a time (they'd share one ring), so the list shows each mic
with its own state, and a fix on another mic says it moves there."""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout)
from shiboken6 import isValid as qt_valid

from soundboard import directmic, errors, theme
from soundboard.i18n import _
from soundboard.ui import busy, fit, icons
from soundboard.ui.panel import Flow
from soundboard.ui.setupshow import SetupShow
from soundboard.ui.widgets import DropdownMenu
from soundboard.wheelguard import no_wheel, snug_combo

log = logging.getLogger(__name__)


def look(state):
    """What the card shows for a directmic.status(): (pill text, pill tone ("muted" =
    neutral, still outlined so it reads as a pill), the one fix
    offered as the main button, or None)."""
    off = (_("Off"), "warn", "repair")
    return {
        "ready": (_("Ready"), "ok", None),
        "outdated": (_("Update available"), "warn", "update"),
        "wiped": off,      # Windows took it off the mic
        "other": off,      # it's on another mic, not the one picked
        "missing": (_("Off"), "muted", None),
    }.get(state, ("", "", None))


def action_text(action):
    return {"repair": _("Repair mic effect"), "update": _("Update mic effect"),
            "reinstall": _("Clean reinstall"),
            "remove": _("Remove mic effect")}[action]


def explanation(action, mic=None):
    """What the action does, naming the mic it acts on (`mic`: its name)."""
    if action == "update":
        action = "repair"
    if mic is None:
        return {
            "repair": _("Reinstall Onion Board's mic effect on your selected microphone."),
            "reinstall": _("Restore your microphones, remove the old mic effect, then "
                           "install a fresh copy on your selected microphone."),
            "remove": _("Restore your microphones and remove Onion Board's mic effect. "
                        "Sounds will stop going straight into your mic."),
        }[action]
    return {
        "repair": _("Reinstall Onion Board's mic effect on {mic}.", mic=mic),
        "reinstall": _("Restore {mic}, remove the old mic effect, then install a fresh "
                       "copy on it.", mic=mic),
        "remove": _("Restore {mic} and remove Onion Board's mic effect from it. Sounds "
                    "will stop going straight into it.", mic=mic),
    }[action]


def labels(mics):
    """The list's words for each mic: its name, numbered when two share one, marked
    when unplugged."""
    seen, out = {}, []
    for m in mics:
        n = seen[m["name"]] = seen.get(m["name"], 0) + 1
        name = m["name"] if n == 1 else _("{mic} ({number})", mic=m["name"], number=n)
        out.append(name if m["active"] else _("{mic} (unplugged)", mic=name))
    return out


def has_effect(state):
    return state not in ("missing", "other", "unknown", "")


class Recovery(QObject):
    """Lives with the main window, so closing Settings cannot abandon a repair."""
    finished = Signal(str, str, str)

    def __init__(self, mw):
        super().__init__(mw)
        self.mw = mw
        self.running = False
        self.finished.connect(self._finished)

    def start(self, action, target=None):
        """Run `action` on the mic `target` (a directmic.mics() entry), or, without
        one, on the app's mic (remove: off every mic)."""
        if self.running or self.mw._attaching:
            return False
        mic = self.mw.cfg.mic_device
        if action != "remove" and target is None and not mic:
            self.mw.toast(_("Pick your mic first (Setup tab → Devices)."), "warn")
            return False
        if action != "remove" and target is not None and not target["active"]:
            self.mw.toast(_("Plug this mic in to repair it."), "warn")
            return False
        self.running = True
        self.target = target
        self.mw._attaching = True
        threading.Thread(target=self._work, args=(action, mic, target), daemon=True,
                         name="audio-recovery").start()
        return True

    def _work(self, action, mic, target=None):
        err, state = "", ""
        guid = target["guid"] if target else None
        try:
            if action == "remove":
                err = directmic.uninstall(guid) if guid else directmic.uninstall()
            elif guid:
                err = directmic.install_on(guid, clean=action == "reinstall")
            else:
                err = directmic.install(mic, clean=action == "reinstall")
            err = err or ""
            directmic.forget_status()
            state = directmic.status_on(guid) if guid else directmic.status(mic)
            if not err and action == "remove" and (
                    has_effect(state) if guid else directmic.anything_installed()):
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
        target, self.target = getattr(self, "target", None), None
        pa = target and target.get("pa")
        cb = getattr(self.mw, "cb_mic", None)
        if not err and action != "remove" and pa and pa != self.mw.cfg.mic_device \
                and cb is not None and cb.findData(pa) >= 0:
            # the effect is on that mic now: the app sends into it (as picking it would)
            cb.setCurrentIndex(cb.findData(pa))
            self.mw.on_device(cb, "mic_device")
        else:
            self.mw._when_devices_free(lambda: self.mw._refresh_off_ui())
        if err:
            self.mw.toast(_("{error}", error=err), "warn")


class RecoveryCard(QFrame):
    checked = Signal(str, str)
    listed = Signal(list, str)

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
        title.setProperty("head", True)   # no top padding: it shares a line with the pill
        self.heading = title
        head.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        self.pill = QLabel()
        self.pill.setObjectName("pill")
        self.pill.hide()
        head.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addStretch(1)
        self.more = QPushButton()
        self.more.setObjectName("iconbutton")
        self.more.setProperty("quiet", True)
        self.more.setFixedSize(28, 28)
        icons.set_icon(self.more, "more")
        self.more.setToolTip(_("More options"))
        self.more.setAccessibleName(_("More options"))
        self.menu = DropdownMenu(self.more)
        self.menu_actions = {}
        for action, icon in (("repair", "reload"), ("reinstall", "reload"),
                             ("remove", "trash")):
            if action == "remove":
                self.menu.addSeparator()
            act = self.menu.addAction(icons.icon(icon), action_text(action))
            act.triggered.connect(lambda checked=False, a=action: self.confirm(a))
            self.menu_actions[action] = act
        self.more.clicked.connect(
            lambda: self.menu.popup(self.more.mapToGlobal(self.more.rect().bottomLeft())))
        head.addWidget(self.more, 0, Qt.AlignmentFlag.AlignVCenter)
        v.addLayout(head)
        hint = QLabel(_("Fix problems sending sounds into your mic after an update."))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        v.addWidget(hint)
        row = Flow(gap=8)
        self.mics = []   # directmic.mics(): what the list shows
        pick = QLabel(_("Mic to fix"))
        pick.setProperty("keepline", True)   # one line beside its list, in every language
        self.target_box = QComboBox()
        self.target_box.setAccessibleName(_("Mic to fix"))
        pick.setBuddy(self.target_box)
        no_wheel(self.target_box)
        self.target_box.activated.connect(lambda _i: self._picked())
        row.addWidget(pick)
        row.addWidget(self.target_box)
        self.fix = QPushButton()
        self.fix.setObjectName("primary")
        self.fix.hide()
        self.fix.clicked.connect(lambda: self.confirm(self.fix.property("action")))
        row.addWidget(self.fix)
        v.addLayout(row)
        # the same job as the setup guide's mic step, so the same show (hides itself)
        self.show_ = SetupShow()
        v.addWidget(self.show_)
        # where the effect is when that's not the picked mic, or why it can't be fixed
        self.where = QLabel()
        self.where.setWordWrap(True)
        self.where.setObjectName("hint")
        self.where.hide()
        v.addWidget(self.where)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setObjectName("hint")
        self.note.hide()
        v.addWidget(self.note)
        self.checked.connect(self._checked)
        self.listed.connect(self._listed)
        self.recovery.finished.connect(self._done)
        self._checking = False
        self._sync_busy()
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
        cb = getattr(self.mw, "cb_mic", None)
        names = [cb.itemData(i) for i in range(cb.count())] if cb is not None else []
        names = [n for n in names if n]

        def work():
            try:
                found = directmic.mics(names)
            except Exception:  # noqa: BLE001 - keep settings usable if Windows refuses
                log.exception("couldn't list the mics")
                found = []
            try:
                state = directmic.status(mic)
            except Exception:  # noqa: BLE001 - keep settings usable if Windows refuses
                log.exception("couldn't check mic effect")
                state = "unknown"
            busy.emit(self.listed, found, mic or "")
            busy.emit(self.checked, state, mic or "")
        threading.Thread(target=work, daemon=True, name="recovery-status").start()

    def target(self):
        """The picked mic (a directmic.mics() entry), or None when Windows lists none."""
        guid = self.target_box.currentData()
        return next((m for m in self.mics if m["guid"] == guid), None)

    def _listed(self, found, mic):
        """Fill the list, keeping the picked mic (by endpoint) or else the app's mic."""
        if mic != (self.mw.cfg.mic_device or ""):
            return
        keep = self.target_box.currentData()
        self.mics = found
        box = self.target_box
        box.blockSignals(True)
        box.clear()
        for m, text in zip(found, labels(found)):
            box.addItem(text, m["guid"])
            box.setItemData(box.count() - 1, m["name"], Qt.ItemDataRole.ToolTipRole)
        ours = next((m["guid"] for m in found if mic and m["pa"] == mic), None)
        i = box.findData(keep) if keep else -1
        box.setCurrentIndex(i if i >= 0 else max(0, box.findData(ours)))
        box.blockSignals(False)
        box.setEnabled(bool(found) and not self.recovery.running)
        snug_combo(box)
        box.view().setMinimumWidth(box.view().sizeHintForColumn(0) + 32)   # whole names

    def _picked(self):
        t = self.target()
        if t is not None:
            self.note.hide()
            self._checked(t["state"])

    def _checked(self, state, mic=None):
        self._checking = False
        if mic is not None and mic != (self.mw.cfg.mic_device or ""):
            return
        t = self.target()
        if t is not None and mic is not None:
            state = t["state"]   # the picked mic's own state, not the app's mic's
        self._state = state
        if self.recovery.running:
            return   # the pill says Working… until the fix is done
        pill, tone, fix = look(state)
        self.pill.setText(pill)
        self.pill.setVisible(bool(pill))
        theme.set_tone(self.pill, tone)
        unplugged = t is not None and not t["active"]
        self.fix.setVisible(fix is not None and not unplugged)
        if fix:
            self.fix.setText(action_text(fix))
            self.fix.setProperty("action", fix)
        for a in ("repair", "reinstall"):
            self.menu_actions[a].setEnabled(not unplugged)
        self.menu_actions["remove"].setEnabled(
            state != "missing" if t is None else has_effect(state))
        on = [i for i, m in enumerate(self.mics) if has_effect(m["state"]) and m is not t]
        if unplugged:
            self.where.setText(_("Plug this mic in to repair it."))
        elif t is not None and state == "other" and on:
            self.where.setText(_("The mic effect is on {mic}. It works on one mic at a "
                                 "time.", mic=labels(self.mics)[on[0]]))
        else:
            self.where.setText("")
        self.where.setVisible(bool(self.where.text()))

    def confirm(self, action):
        if self.recovery.running or self.mw._attaching:
            return
        t = self.target()
        name = labels(self.mics)[self.mics.index(t)] if t is not None else None
        if getattr(self, "dialog", None) and qt_valid(self.dialog) and self.dialog.isVisible():
            self.dialog.raise_()
            return
        d = QDialog(self.window())
        self.dialog = d
        d.setWindowTitle(action_text(action))
        d.setMaximumWidth(620)
        v = QVBoxLayout(d)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(12)
        title = QLabel(action_text(action))
        title.setObjectName("helptitle")
        v.addWidget(title)
        lines = [explanation(action, name)]
        if t is not None and action != "remove":
            moved = [labels(self.mics)[i] for i, m in enumerate(self.mics)
                     if has_effect(m["state"]) and m is not t]
            if moved:
                lines.append(_("It comes off {mic}: the mic effect works on one mic at a "
                               "time.", mic=moved[0]))
            if t["pa"] and t["pa"] != self.mw.cfg.mic_device:
                lines.append(_("Onion Board will send your sounds into {mic} from now on.",
                               mic=name))
            elif not t["pa"] and self.mw.cfg.mic_device:
                # its name is shared or unknown: the app can't switch to it by itself
                lines.append(_("Your sounds go into {mic}. To use this mic instead, pick "
                               "it under Devices too.", mic=self.mw.cfg.mic_device))
        lines.append(_("Windows will ask for permission. Audio will briefly stop, "
                       "including calls and games."))
        for text in lines:
            label = QLabel(text)
            label.setWordWrap(True)
            v.addWidget(label)
        kept = QLabel(_("Your sounds and settings are kept."))
        kept.setObjectName("hint")
        kept.setWordWrap(True)
        v.addWidget(kept)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        go = QPushButton(action_text(action))
        go.setObjectName("danger" if action == "remove" else "primary")
        go.setDefault(True)
        go.clicked.connect(lambda: self._start(action, d, t))
        cancel = QPushButton(_("Cancel"))
        cancel.clicked.connect(d.reject)
        row.addWidget(go)
        row.addWidget(cancel)
        v.addLayout(row)
        fit.watch(d)
        d.finished.connect(d.deleteLater)
        d.open()

    def _start(self, action, dialog, target=None):
        self._target_name = (labels(self.mics)[self.mics.index(target)]
                             if target in self.mics else None)
        if self.recovery.start(action, target):
            dialog.accept()
            self.note.hide()
            self._sync_busy()

    def _sync_busy(self):
        running = self.recovery.running
        busy.set_busy(self.fix, running)
        busy.set_busy(self.more, running)
        self.target_box.setEnabled(not running and bool(self.mics))
        if running:
            self.pill.setText(_("Working…"))
            self.pill.show()
            theme.set_tone(self.pill, "muted")
            self.show_.start()

    def _done(self, action, err, state):
        self._sync_busy()
        self.show_.finish(not err)
        name = getattr(self, "_target_name", None)
        t = self.target()
        if t is not None:   # the picked mic's state now, until the next check
            t["state"] = state
        self._checked(state)
        if err:
            text = err
        elif name is None:
            text = (_("Mic effect removed") if action == "remove" else
                    _("Mic effect reinstalled. Test it in your voice chat."))
        else:
            text = (_("Mic effect removed from {mic}", mic=name) if action == "remove" else
                    _("Mic effect reinstalled on {mic}. Test it in your voice chat.",
                      mic=name))
        self.note.setText(text)
        QTimer.singleShot(0, self, self.check)   # every mic's state, fresh
        theme.set_tone(self.note, "warn" if err else "ok")
        self.note.show()
