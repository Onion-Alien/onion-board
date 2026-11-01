"""Discoverable recovery for Onion Board's Windows microphone effect.

The card in Settings > Audio lists every mic (by its Windows endpoint, not its name:
two mics can share a name, and one can be unplugged) as a row of its own: the mic's
name, where the mic effect stands on it, and each action it can take as a button,
with nothing behind a menu. A mic with the effect gets its fix (update, or repair
when Windows took it off), a clean reinstall and remove; a mic without it gets install
and a clean-up of anything a cut-off set-up left. The effect sits on one mic at a time
(they'd share one ring), so installing it on another mic says it moves there. While a
fix runs, the setup guide's show plays under the list (ui/setup/setupshow.py: Bun builds a
speaker, then it thumps and he cheers, or it goes BOOM)."""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, QSignalBlocker, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout)
from shiboken6 import isValid as qt_valid

from soundboard.mic import directmic, michelper
from soundboard.ui.kit import theme
from soundboard.core import errors, usage
from soundboard.core.pollthread import PollThread
from soundboard.i18n import _
from soundboard.ui.kit import busy, fit, icons
from soundboard.ui.kit.glow import Glow
from soundboard.ui.kit.panel import Flow
from soundboard.ui.setup.setupshow import SetupShow

log = logging.getLogger(__name__)
# the status look every 5 s while the page shows: one kept thread for every copy of the
# page (a new thread each time made the window wait in Thread.start, pollthread.py)
_STATUS_POLL = PollThread("recovery-status")
INSTALLS = ("install", "repair", "update", "reinstall")   # these leave the effect on


def look(state):
    """What the card shows for a directmic.status(): (pill text, pill tone ("muted" =
    neutral, still outlined so it reads as a pill), the one fix
    offered as the main button, or None)."""
    # not on this mic at all: nothing to repair, it's installed (and then it's on this one)
    absent = (_("Not installed"), "muted", "install")
    return {
        "ready": (_("Ready"), "ok", None),
        "outdated": (_("Update available"), "warn", "update"),
        "wiped": (_("Off"), "warn", "repair"),   # Windows took it off the mic
        "other": absent,     # it's on another mic, not this one
        "missing": absent,   # on no mic
    }.get(state, ("", "", None))


def action_text(action):
    return {"install": _("Install mic effect"),
            "repair": _("Repair mic effect"), "update": _("Update mic effect"),
            "reinstall": _("Clean reinstall"), "cleanup": _("Clean up leftovers"),
            "remove": _("Remove mic effect")}[action]


def explanation(action, mic=None):
    """What the action does, naming the mic it acts on (`mic`: its name)."""
    if action == "update":
        action = "repair"
    if mic is None:
        return {
            "install": _("Put Onion Board's mic effect on your selected microphone, so "
                         "your sounds can go straight into it."),
            "repair": _("Reinstall Onion Board's mic effect on your selected microphone."),
            "reinstall": _("Restore your microphones, remove the old mic effect, then "
                           "install a fresh copy on your selected microphone."),
            "remove": _("Restore your microphones and remove Onion Board's mic effect. "
                        "Sounds will stop going straight into your mic."),
        }[action]
    return {
        "install": _("Put Onion Board's mic effect on {mic}, so your sounds can go "
                     "straight into it.", mic=mic),
        "repair": _("Reinstall Onion Board's mic effect on {mic}.", mic=mic),
        "reinstall": _("Restore {mic}, remove the old mic effect, then install a fresh "
                       "copy on it.", mic=mic),
        "remove": _("Restore {mic} and remove Onion Board's mic effect from it. Sounds "
                    "will stop going straight into it.", mic=mic),
        "cleanup": _("Look for anything Onion Board left on {mic} and take it out. Only "
                     "Onion Board's own parts go: the mic's other settings stay.", mic=mic),
    }[action]


def labels(mics):
    """The list's words for each mic: its name, every one numbered when two share it
    (in front, so a narrow list that cuts the end off still tells them apart), marked
    when unplugged."""
    names = [m["name"] for m in mics]
    seen, out = {}, []
    for m in mics:
        n = seen[m["name"]] = seen.get(m["name"], 0) + 1
        name = m["name"] if names.count(m["name"]) == 1 else \
            _("#{number} {mic}", mic=m["name"], number=n)
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

    def start(self, action, target=None, say_done=False):
        """Run `action` on the mic `target` (a directmic.mics() entry), or, without
        one, on the app's mic (remove: off every mic). `say_done`: a toast when it
        worked too (the Setup tab has no line of its own for it)."""
        if self.running or self.mw._attaching:
            return False
        mic = self.mw.cfg.mic_device
        if action != "remove" and target is None and not mic:
            self.mw.toast(_("Pick your mic first (Setup tab → Devices)."), "warn")
            return False
        if action in INSTALLS and target is not None and not target["active"]:
            self.mw.toast(_("Plug this mic in to repair it."), "warn")
            return False
        self.running = True
        self.target = target
        self.say_done = say_done
        self.mw._attaching = True
        threading.Thread(target=self._work, args=(action, mic, target), daemon=True,
                         name="audio-recovery").start()
        return True

    def _work(self, action, mic, target=None):
        err, state, why = "", "", ""
        guid = target["guid"] if target else None
        try:
            if action == "cleanup" and target is not None and guid:   # on a picked mic
                if not directmic.leftovers(guid):
                    action = "cleanup-none"   # nothing there: no admin prompt at all
                else:
                    err = directmic.cleanup(guid)
                    if not err and directmic.leftovers(guid):
                        why = "leftovers"
                        err = _("Some leftovers couldn't be removed from {mic}.",
                                mic=target["name"])
            elif action == "remove":
                err = directmic.uninstall(guid) if guid else directmic.uninstall()
            elif guid:
                err = directmic.install_on(guid, clean=action in ("reinstall", "update"))
            else:
                err = directmic.install(mic, clean=action in ("reinstall", "update"))
            if err and not why:   # its reason word, while err is still install's Failure
                why = "said-no" if err == directmic.declined() else directmic.fail_kind(err)
            err = err or ""
            directmic.forget_status()
            state = directmic.status_on(guid) if guid else directmic.status(mic)
            if not err and action == "remove" and (
                    has_effect(state) if guid else directmic.anything_installed()):
                why = "not-removed"
                err = _("Repair failed")
            elif not err and action in INSTALLS and state != "ready":
                why = "unverified"
                err = _("The mic effect could not be verified. Restart your PC, then try "
                        "Repair mic effect again.")
        except Exception as exc:  # noqa: BLE001 - report unexpected device failures
            log.exception("audio recovery failed")
            err, why = errors.plain(exc), "error"
        self._why = why   # read by _finished (one run at a time; the signal carries str)
        busy.emit(self.finished, action, err, state)

    def _finished(self, action, err, state):
        self.running = False
        done = "cleanup" if action == "cleanup-none" else action
        if done in usage.RECOVERY:
            usage.used(f"recovery-{done}")
        why, self._why = getattr(self, "_why", ""), ""
        if why == "said-no":   # No to Windows' prompt: nothing failed
            usage.used("recovery-said-no")
        elif err:   # why, as a fixed word (never err)
            usage.used("recovery-failed")
            usage.used(f"recovery-failed-{why or 'code-other'}")
        self.mw._attaching = False
        target, self.target = getattr(self, "target", None), None
        pa = target and target.get("pa")
        cb = getattr(self.mw, "cb_mic", None)
        if not err and action in INSTALLS and pa and pa != self.mw.cfg.mic_device \
                and cb is not None and cb.findData(pa) >= 0:
            # the effect is on that mic now: the app sends into it (as picking it would)
            cb.setCurrentIndex(cb.findData(pa))
            self.mw.routectl.on_device(cb, "mic_device")
        else:
            self.mw.devctl._when_devices_free(lambda: self.mw.devctl._refresh_off_ui())
        if err:
            self.mw.toast(_("{error}", error=err), "warn")
        elif getattr(self, "say_done", False):
            self.mw.toast(_("Mic effect removed") if action == "remove" else
                          _("Mic effect reinstalled. Test it in your voice chat."), "ok")


def recovery_of(mw):
    """The main window's one Recovery (Settings' card and the Setup tab share it)."""
    if not hasattr(mw, "audio_recovery"):
        mw.audio_recovery = Recovery(mw)
    return mw.audio_recovery


def ask(parent, action, lines, go_on):
    """The are-you-sure box for `action`: `lines` say what it does, then what Windows
    and the audio will do. `go_on(dialog)` runs on its button. Returns the box (open)."""
    d = QDialog(parent)
    d.setWindowTitle(action_text(action))
    d.setMaximumWidth(620)
    v = QVBoxLayout(d)
    v.setContentsMargins(18, 18, 18, 18)
    v.setSpacing(12)
    title = QLabel(action_text(action))
    title.setObjectName("helptitle")
    v.addWidget(title)
    lines = list(lines)
    # the mic helper does it without Windows' prompt (setting up: only with this
    # app's own mic effect in it)
    prompts = michelper.will_ask(action in INSTALLS)
    lines.append(
        (_("If anything is found, Windows will ask for permission and audio will "
           "briefly stop.") if prompts else
         _("If anything is found, audio will briefly stop.")) if action == "cleanup" else
        directmic.with_helper_note(_("Windows will ask for permission. Audio will briefly "
                                     "stop, including calls and games."))
        if prompts and action in INSTALLS else
        _("Windows will ask for permission. Audio will briefly stop, "
          "including calls and games.") if prompts else
        _("Audio will briefly stop, including calls and games."))
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
    go.clicked.connect(lambda: go_on(d))
    cancel = QPushButton(_("Cancel"))
    cancel.clicked.connect(d.reject)
    row.addWidget(go)
    row.addWidget(cancel)
    v.addLayout(row)
    fit.watch(d)
    d.finished.connect(d.deleteLater)
    d.open()
    return d


class MicName(QLabel):
    """The mic's name: asks for its whole name on one line, and wraps only when the
    row is too narrow for it (a plain wrapping label asks for about half that)."""

    def sizeHint(self):
        h = super().sizeHint()
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 2, h.height())


class MicRow(QFrame):
    """One mic on the card: its name, where the mic effect stands on it, and every
    action that mic can take, as buttons (nothing hidden in a menu)."""

    def __init__(self, card, mic, label, in_use):
        super().__init__(card)   # inside the card from the start: never a window
        self.mic = mic
        self.setObjectName("tabcard")   # a box inside the card
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(8)
        # each layout joins the row before anything goes in it: a widget added to a
        # layout that has no widget yet is a window of its own for a moment, and a new
        # window takes the keyboard focus away from Settings
        top = QHBoxLayout()
        top.setSpacing(8)
        v.addLayout(top)
        self.name = MicName(label, self)
        self.name.setToolTip(mic["name"])
        self.name.setWordWrap(True)
        top.addWidget(self.name)
        # the pills sit right after the name, not out at the far edge of the row
        pill, tone, _fix = look(mic["state"])
        self.pill = QLabel(pill, self)
        self.pill.setObjectName("pill")
        self.pill.setVisible(bool(pill))
        theme.set_tone(self.pill, tone)
        top.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignVCenter)
        self.in_use = QLabel(_("In use"), self)
        self.in_use.setObjectName("pill")
        theme.set_tone(self.in_use, "muted")
        self.in_use.setVisible(in_use)
        top.addWidget(self.in_use, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addStretch(1)
        self.buttons = {}
        row = Flow(gap=8)
        v.addLayout(row)
        for action in actions_for(mic):
            b = QPushButton(action_text(action), self)
            if action in ("repair", "update"):
                b.setObjectName("primary")   # the fix this mic needs
            elif action == "remove":
                b.setObjectName("danger")
                b.setProperty("quiet", True)
            b.clicked.connect(lambda _c=False, a=action: card.confirm(a, self.mic))
            row.addWidget(b)
            self.buttons[action] = b
        if in_use and "install" in self.buttons:
            # the mic in use has no mic effect yet: the one button to press here
            self.glow = Glow(self.buttons["install"], tone="warn")
        self.hint = QLabel(_("Plug this mic in to repair it."), self)
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        self.hint.setVisible(not mic["active"])
        v.addWidget(self.hint)


class DiscordRow(QFrame):
    """Put Discord back: its voice clean-up (noise suppression, echo cancellation,
    automatic volume) back on the way you had it before you set it up for sounds, or
    Discord's own settings. For talking without Onion Board."""

    def __init__(self, parent=None):
        super().__init__(parent)   # inside its card (or the picture of it): never a window
        self.setObjectName("tabcard")
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(8)
        v.addLayout(top)
        icon = QLabel(self)
        icon.setPixmap(icons.icon("speech").pixmap(18, 18))
        top.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(QLabel("Discord", self), 1)
        hint = QLabel(_("Turns Discord's noise suppression, echo cancellation and automatic "
                        "volume back on, the way you had them before you set it up for "
                        "sounds. For talking without Onion Board: your sounds may get cut "
                        "off in calls again."), self)
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        v.addWidget(hint)
        row = Flow(gap=8)
        v.addLayout(row)
        self.button = QPushButton(_("Put Discord back"), self)
        icons.set_icon(self.button, "history")
        row.addWidget(self.button)


def put_discord_back(mw, button, done):
    """Discord back the way you talk, on a worker (its files); `done` (a Signal) gets
    (what needed putting back, what's still open). A Discord that's open won't take
    it, so that one's done the moment it closes (AlertControl)."""
    if busy.is_busy(button):
        return
    busy.set_busy(button, True)
    saved = dict(mw.cfg.discord_talk)

    def work():
        todo, left = [], []
        try:
            from soundboard.mic import discordtalk
            from soundboard.sounds.library import APP_DIR
            todo = discordtalk.to_restore(saved)
            if todo:
                left = discordtalk.restore(saved, APP_DIR / "discord-backup",
                                           only=set(todo), always=True)
        except Exception:  # noqa: BLE001 - say it, don't leave the button stuck
            log.exception("putting Discord back failed")
            todo, left = ["?"], ["?"]
        busy.emit(done, todo, left)
    threading.Thread(target=work, daemon=True, name="discord-back").start()


def said_discord_back(mw, todo, left):
    """put_discord_back's answer, as a toast on the window."""
    if left == ["?"]:
        mw.toast(_("Couldn't put Discord back. Turn on Noise Suppression, Echo "
                   "Cancellation and Automatic Gain Control in its Voice & Video "
                   "settings."), "warn")
    elif not todo:
        mw.toast(_("Discord is already set up for talking."), "ok")
    elif left:
        mw.alertctl.discord_pending |= set(left)
        mw.toast(_("Close Discord and it's put back right away: Discord doesn't take "
                   "changes while it's open."), "warn")
    else:
        mw.toast(_("Discord is back the way you talk: its noise suppression, echo "
                   "cancellation and automatic volume are on again."), "ok")


def actions_for(mic):
    """The buttons a mic gets: on it, its fix (if it needs one), a clean reinstall and
    remove; not on it, install and a clean-up of anything left behind. Unplugged: only
    remove. Without an endpoint (Windows listed no mics), no clean-up."""
    state = mic["state"]
    if not has_effect(state):
        if state not in ("other", "missing") or not mic["active"]:
            return []
        return ["install"] + (["cleanup"] if mic["guid"] else [])
    if not mic["active"]:
        return ["remove"]
    fix = look(state)[2]
    return ([fix] if fix else []) + ["reinstall", "remove"]


class RecoveryCard(QFrame):
    checked = Signal(str, str)
    listed = Signal(list, str)
    discord_back = Signal(list, list)   # (Discord folders to put back, still open)

    def __init__(self, mw, parent=None):
        super().__init__(parent)
        self.mw = mw
        self.recovery = recovery_of(mw)
        self.mics = []      # directmic.mics(): one row each
        self._state = ""    # the app's mic, for when Windows lists no mics
        self._shown = None  # what the rows show, so a check that changed nothing keeps them
        self.rows = {}      # endpoint GUID (None: the app's mic, unlisted) -> MicRow
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
        title = QLabel(_("Mic effect"))
        title.setObjectName("section")
        title.setProperty("keepline", True)
        title.setProperty("head", True)   # no top padding: it shares a line with the pill
        self.heading = title
        head.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        self.pill = QLabel()   # Working… while a fix runs
        self.pill.setObjectName("pill")
        self.pill.hide()
        head.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addStretch(1)
        v.addLayout(head)
        hint = QLabel(_("Puts your sounds into your mic. Fix it here after an update, or put "
                       "Discord back for talking."))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        v.addWidget(hint)
        # the mic effect sits on one mic: say so where it's installed
        self.new_mic = QLabel(_("🎧 <b>New mic or headset?</b> The mic effect goes on one mic "
                                "at a time. Each time you switch to a new one, pick it under "
                                "Devices, then press <b>Install mic effect</b> here, or others "
                                "won't hear your sounds."))
        self.new_mic.setWordWrap(True)
        v.addWidget(self.new_mic)
        # sent elsewhere (the cable): no mic row, so say how to send into the mic instead
        self.not_mic = QLabel(_("Your sounds don't go into your mic now. To send them into "
                                "it, set <b>{field}</b> to <b>{choice}</b> above.",
                                field=_("Send my sounds to"), choice=_("My mic (normal)")))
        self.not_mic.setWordWrap(True)
        self.not_mic.hide()
        v.addWidget(self.not_mic)
        self.list = QVBoxLayout()
        self.list.setSpacing(6)
        v.addLayout(self.list)
        self.discord = DiscordRow(self)
        self.discord.button.clicked.connect(self.put_discord_back)
        v.addWidget(self.discord)
        from soundboard.mic import discordtalk
        self.discord.setVisible(discordtalk.installed())   # no Discord: nothing to put back
        self.discord_back.connect(self._discord_back)
        # the mic helper (soundboard/mic/michelper.py): said plainly, and switched off here
        self.helper = QCheckBox(_("Don't ask for admin each time"), self)
        self.helper.setToolTip(_("Onion Board adds a small helper to Windows (a task that "
                                 "runs as SYSTEM), so it can set up and repair the mic "
                                 "effect without Windows asking for permission each time. "
                                 "Untick this to remove it."))
        self.helper.setChecked(mw.cfg.mic_helper)
        self.helper.toggled.connect(self._switch_helper)
        mw.micctl.helper_switched.connect(self._helper_switched)
        v.addWidget(self.helper)
        self.helper_hint = QLabel(_("Off: Windows asks for permission every time the mic "
                                    "effect is set up or repaired."), self)
        self.helper_hint.setObjectName("hint")
        self.helper_hint.setWordWrap(True)
        v.addWidget(self.helper_hint)
        # the same job as the setup guide's mic step, so the same show (hides itself)
        self.show_ = SetupShow()
        v.addWidget(self.show_)
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
        # what the last look found (kept on the window): a new copy of the card shows
        # those rows at once, then looks again. Built empty, its rows came in after it
        # was on screen and pushed the rest of the page down.
        last = getattr(mw, "_recovery_last", None)
        if last and last["mic"] == (mw.cfg.mic_device or ""):
            self._state, self.mics = last["state"], last["mics"]
            self._rebuild()
        # the first look even before it shows: Settings is built behind the loading
        # screen, so the rows are there when it's first opened
        QTimer.singleShot(0, self, lambda: self.check(first=True))

    def check(self, first: bool = False):
        if self._checking or not (first or self.isVisible()):
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
            # the app's mic first, then the list: one rebuild of the rows, not two
            busy.emit(self.checked, state, mic or "")
            busy.emit(self.listed, found, mic or "")
        _STATUS_POLL.run(work)

    def put_discord_back(self):
        put_discord_back(self.mw, self.discord.button, self.discord_back)

    def _switch_helper(self, on: bool):
        if on == self.mw.cfg.mic_helper:
            return
        if not self.mw.micctl.switch_helper(on):   # a mic step is running: try after it
            self.mw.toast(_("Wait until the mic effect is done, then try again."), "warn")
            self._helper_switched(not on)
            return
        busy.set_busy(self.helper, not on)   # (Windows asks: the answer moves it)

    def _helper_switched(self, on: bool):
        if not qt_valid(self):
            return
        busy.set_busy(self.helper, False)
        if self.helper.isChecked() != on:
            with QSignalBlocker(self.helper):
                self.helper.setChecked(on)

    def _discord_back(self, todo, left):
        if not qt_valid(self):
            return
        busy.set_busy(self.discord.button, False)
        said_discord_back(self.mw, todo, left)

    def shown(self):
        """The mics the card lists: Windows' list, or, when it lists none, the app's
        mic on its own (worked on by name)."""
        if self.mics:
            return self.mics
        mic = self.mw.cfg.mic_device
        return [{"guid": None, "name": mic or _("Your mic"), "active": True,
                 "state": self._state, "pa": mic}]

    def _listed(self, found, mic):
        self._checking = False
        if mic != (self.mw.cfg.mic_device or ""):
            return
        self.mics = found
        self._remember()
        self._rebuild()

    def _checked(self, state, mic=None):
        self._checking = False
        if mic is not None and mic != (self.mw.cfg.mic_device or ""):
            return
        self._state = state
        self._remember()
        self._rebuild()

    def _remember(self):
        self.mw._recovery_last = {"mic": self.mw.cfg.mic_device or "", "state": self._state,
                                  "mics": self.mics}

    def _rebuild(self):
        mics = self.shown()
        if self.mw.cfg.route != "mic" and not any(has_effect(m["state"]) for m in mics):
            mics = []   # sent elsewhere (the cable) and on no mic: no mic to talk about
        self.new_mic.setVisible(bool(mics))
        self.not_mic.setVisible(not mics)
        sig = (tuple((m["guid"], m["name"], m["active"], m["state"], m["pa"]) for m in mics),
               self.mw.cfg.mic_device)
        if sig == self._shown:
            return   # the same: keep the rows (and the keyboard focus in them)
        self._shown = sig
        # a button with the keyboard focus goes with its row: the same one on the new
        # row takes it, or focus would be lost (Tab goes nowhere)
        focus = QApplication.focusWidget()
        keep = next(((g, a) for g, r in self.rows.items() for a, b in r.buttons.items()
                     if b is focus), None)
        for r in self.rows.values():
            r.hide()
            self.list.removeWidget(r)
            r.deleteLater()
        self.rows = {}
        def in_use(m):
            return bool(m["pa"]) and m["pa"] == self.mw.cfg.mic_device
        # the mic in use first: its row is the one to act on (twins keep their numbers)
        for m, text in sorted(zip(mics, labels(mics)), key=lambda p: not in_use(p[0])):
            r = MicRow(self, m, text, in_use(m))
            self.list.addWidget(r)
            self.rows[m["guid"]] = r
        if keep is not None:
            row = self.rows.get(keep[0])
            b = row.buttons.get(keep[1]) if row else None
            b = b or next((b for r in self.rows.values() for b in r.buttons.values()), None)
            (b or self).setFocus(Qt.FocusReason.OtherFocusReason)
        self._sync_busy()

    def name_of(self, mic):
        mics = self.shown()
        return labels(mics)[mics.index(mic)] if mic in mics else mic["name"]

    def confirm(self, action, mic):
        if self.recovery.running or self.mw._attaching:
            return
        if getattr(self, "dialog", None) and qt_valid(self.dialog) and self.dialog.isVisible():
            self.dialog.raise_()
            return
        name = self.name_of(mic)
        target = mic if mic["guid"] else None   # unlisted: the app's mic, by name
        lines = [explanation(action, name)]
        if target is not None and action in INSTALLS:
            moved = [self.name_of(m) for m in self.mics
                     if has_effect(m["state"]) and m is not mic]
            if moved:
                lines.append(_("It comes off {mic}: the mic effect works on one mic at a "
                               "time.", mic=moved[0]))
            if mic["pa"] and mic["pa"] != self.mw.cfg.mic_device:
                lines.append(_("Onion Board will send your sounds into {mic} from now on.",
                               mic=name))
            elif not mic["pa"] and self.mw.cfg.mic_device:
                # its name is shared or unknown: the app can't switch to it by itself
                lines.append(_("Your sounds go into {mic}. To use this mic instead, pick "
                               "it under Devices too.", mic=self.mw.cfg.mic_device))
        self.dialog = ask(self.window(), action, lines,
                          lambda d: self._start(action, d, target, name))

    def _start(self, action, dialog, target, name):
        self._target_name = name
        if self.recovery.start(action, target):
            dialog.accept()
            self.note.hide()
            self._sync_busy()

    def _sync_busy(self):
        running = self.recovery.running
        for r in self.rows.values():
            for b in r.buttons.values():
                busy.set_busy(b, running)
        if running:
            self.pill.setText(_("Working…"))
            self.pill.show()
            theme.set_tone(self.pill, "muted")
            if not self.show_.on:
                self.show_.start()
        else:
            self.pill.hide()

    def _done(self, action, err, state):
        self._sync_busy()
        self.show_.finish(not err)
        name = getattr(self, "_target_name", None)
        if err:
            text = err
        elif action == "cleanup":
            text = _("Leftovers removed from {mic}.", mic=name)
        elif action == "cleanup-none":
            text = _("Nothing of Onion Board's was left on {mic}.", mic=name)
        elif name is None:
            text = (_("Mic effect removed") if action == "remove" else
                    _("Mic effect installed. Test it in your voice chat.")
                    if action == "install" else
                    _("Mic effect reinstalled. Test it in your voice chat."))
        else:
            text = (_("Mic effect removed from {mic}", mic=name) if action == "remove" else
                    _("Mic effect installed on {mic}. Test it in your voice chat.",
                      mic=name) if action == "install" else
                    _("Mic effect reinstalled on {mic}. Test it in your voice chat.",
                      mic=name))
        self.note.setText(text)
        theme.set_tone(self.note, "warn" if err else "ok")
        self.note.show()
        self.check()   # every mic's state, fresh
