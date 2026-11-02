"""The setup guide's "where your sounds go" step: straight into the mic (the mic
effect), the virtual cable (its installer, and the restart it may need) or another
way out. Mixed into SetupWizard."""
from __future__ import annotations

import ctypes
import html
import subprocess
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox,
                               QProgressBar, QPushButton, QVBoxLayout, QWidget)

from soundboard.mic import directmic, michelper
from soundboard.audio import engine as eng
from soundboard.sounds import library
from soundboard.online import net
from soundboard.sounds.library import RESOURCE_DIR
from soundboard.ui.setup import cableconfirm
from soundboard.ui.kit.glow import Glow
from soundboard.ui.kit import busy, fit, icons, panel
from soundboard.ui.bun.bunnywidget import BunnyWidget
from soundboard.ui.setup.setupshow import SetupShow
from soundboard.ui.kit.choicetile import FoldPill
from soundboard.ui.kit.failreport import FailReport
from soundboard.core import errors
from soundboard.i18n import _
from soundboard.ui.setup.wizardkit import (BUN_H, BUN_PAD, HEADER_GAP, NOWHERE,
                                           SECTION_GAP, SETTLE_MS, _bad, _cable_text,
                                           _card, _header, _label, _ok, _working_title,
                                           WizardStep)
from soundboard.ui.setup.wizardparts import StatusCard


RESTART_NEEDED = 3010   # install-vbcable.ps1: installed, but Windows must restart first

# install-vbcable.ps1 -StatusFile writes "<step>|<text>"; these are the steps as the
# guide shows them, in order ("wake" only happens if the cable needs a nudge)
CABLE_STEPS = (("permission", _("Click <b>Yes</b> when Windows asks")),
               ("download", _("Fetching the parts (downloading)")),
               ("install", _("Building your cable (installing)")),
               ("check", _("Checking it works")),
               ("wake", _("Waking it up, so you don't have to restart "
                          "(your sound may blip for a second)")))


def cable_restart_pending() -> bool:
    """install-vbcable.ps1 leaves this marker when the cable needs a restart to start
    working. Once the PC has restarted since it was written, it no longer counts."""
    try:
        written = (library.APP_DIR / "cable-restart-pending").stat().st_mtime
    except OSError:
        return False
    tick = ctypes.windll.kernel32.GetTickCount64
    tick.restype = ctypes.c_uint64
    uptime = tick() / 1000
    return written > time.time() - uptime

# The cable installer while it runs. Kept here, not only on the guide, so a guide
# closed mid-install and opened again picks the same install back up instead of
# starting a second one.
_installer: subprocess.Popen | None = None

RESUME_FLAG = "--resume-setup"
_RUNONCE = r"Software\Microsoft\Windows\CurrentVersion\RunOnce"
_RUNONCE_NAME = "OnionBoardResumeSetup"


def launch_command() -> str:
    """How to start this copy of the app: the exe when frozen, else pythonw + main.py."""
    import sys
    from pathlib import Path
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = Path(sys.executable)
    if (w := exe.with_name("pythonw.exe")).exists():
        exe = w
    return f'"{exe}" "{Path(__file__).resolve().parents[3] / "main.py"}"'


def resume_after_restart(on: bool):
    """Open the guide on the cable step by itself, once, the next time this user logs
    in (a per-user RunOnce entry: no admin, and Windows deletes it as it runs it).
    Set while the cable is waiting on a restart, cleared once it works."""
    import winreg
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUNONCE) as k:
            if on:
                winreg.SetValueEx(k, _RUNONCE_NAME, 0, winreg.REG_SZ,
                                  f"{launch_command()} {RESUME_FLAG}")
            else:
                try:
                    winreg.DeleteValue(k, _RUNONCE_NAME)
                except FileNotFoundError:
                    pass
    except OSError:
        pass   # only a convenience; the marker still makes the guide pick up


class CableConfirm(QDialog):
    """Use the cable, while Onion Board's driver works on the mic: are they sure?
    The driver needs nothing picked anywhere; the cable has to be picked as the mic in
    Discord and every game. And if the driver let them down, a way to tell us."""

    def __init__(self, parent, mic: str):
        super().__init__(parent)
        self.setWindowTitle(_("Switch to the virtual cable?"))
        self.setMinimumWidth(440)
        self.setMaximumWidth(560)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(12)
        title = QLabel(_("Switch to the virtual cable?"))
        title.setObjectName("helptitle")
        v.addWidget(title)
        body = QLabel(_("Onion Board's audio driver is installed on <b>{mic}</b> and "
                        "working: Discord and games already hear your sounds. With the "
                        "cable, you have to pick it as the mic in Discord and in every game "
                        "instead.", mic=html.escape(mic)))
        body.setWordWrap(True)
        v.addWidget(body)
        why = QHBoxLayout()   # a problem with the driver: tell us, so it gets fixed
        why.setSpacing(8)
        why.addWidget(panel.hint_label(_("Something wrong with the driver? Tell us what "
                                         "happened so we can fix it.")), 1)
        self.btn_tell = QPushButton(_("Tell us why"))
        self.btn_tell.setProperty("quiet", True)
        icons.set_icon(self.btn_tell, "speech")
        why.addWidget(self.btn_tell, 0, Qt.AlignmentFlag.AlignVCenter)
        v.addLayout(why)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        self.btn_keep = QPushButton(_("Keep my mic"))
        self.btn_keep.setObjectName("primary")
        self.btn_keep.setDefault(True)
        self.btn_keep.clicked.connect(self.reject)
        row.addWidget(self.btn_keep)
        self.btn_use = QPushButton(_("Use the cable"))
        icons.set_icon(self.btn_use, "cable")
        self.btn_use.clicked.connect(self.accept)
        row.addWidget(self.btn_use)
        v.addLayout(row)
        fit.watch(self)


class CableStep(WizardStep):
    """SetupWizard's "where your sounds go" step."""

    def _page_cable(self) -> QWidget:
        p = QWidget()
        v = QVBoxLayout(p)
        v.setSpacing(SECTION_GAP)   # the same gap between every part of the step
        self.bun_cable = BunnyWidget("plug", height=BUN_H, pad=BUN_PAD)
        v.addLayout(_header(_("Where do your sounds go?"),
                            _label(_("Straight into <b>your mic</b>: one click, and Discord "
                                     "and games hear your sounds through the mic they already "
                                     "use. Nothing to install from the internet, nothing to "
                                     "pick in Discord.")),
                            self.bun_cable))
        self.btn_attach = QPushButton(_("Put my sounds straight into my mic"))
        icons.set_icon(self.btn_attach, "mic", "on_accent")
        self.btn_attach.setObjectName("primary")
        self.btn_attach.clicked.connect(self.attach_mic)
        self.attach_glow = Glow(self.btn_attach)   # the one to press, among the colours
        self.setup_show = SetupShow(height=96)
        self.setup_show.done.connect(lambda: self.recheck_cable(rescan=False))
        v.addWidget(self.setup_show)
        # a bound method, not a lambda: Qt drops the link when the guide is freed, so a
        # set-up finishing after it closed can't poke its deleted buttons
        self.win.mic_attached.connect(self._mic_attached)
        self.cable_status = _label("")
        self.cable_status.setStyleSheet("font-size:10pt;")
        # the answer to "is it working?" right under the intro, in a card of its own
        self.status_card = StatusCard(self.cable_status)
        self.status_card.action_box.addWidget(self.btn_attach, 0, Qt.AlignmentFlag.AlignLeft)
        # putting it on the mic failed: tell us, before giving up
        self.attach_report = FailReport(lambda: {"mic": self.win.cfg.mic_device or "",
                                                 "mode": "direct",
                                                 "err": self.win.micctl.fail_code})
        self.status_card.action_box.addWidget(self.attach_report)
        v.insertSpacing(1, HEADER_GAP - SECTION_GAP)
        v.insertWidget(2, self.status_card)
        # straight into the mic, not in it yet: step 1's mic works, said above what's
        # still to do, so the two don't read as one broken mic
        self.mic_done = _label("")
        self.mic_done.hide()
        v.insertWidget(2, self.mic_done)
        # the mic effect sits on one mic: a new mic or headset needs it put on again
        self.mic_note = _label(_("🎧 <b>Got a new mic or headset later?</b> Put your sounds "
                                 "into that one too: <b>Settings → Audio → Install mic "
                                 "effect</b>. Each mic needs it once."))
        self.mic_note.setObjectName("hint")
        v.insertWidget(4, self.mic_note)
        self.cable_bar = QProgressBar()
        self.cable_bar.setRange(0, 0)   # busy: we can't know how long Windows takes
        self.cable_bar.setTextVisible(False)
        self.cable_bar.setFixedHeight(10)
        self.cable_bar.hide()
        v.addWidget(self.cable_bar)
        self.cable_steps = _label("")
        self.cable_steps.hide()
        v.addWidget(self.cable_steps)
        # the cable is only the backup: a plain button, never the big main one
        self.btn_cable = QPushButton(_("Install the cable"))
        icons.set_icon(self.btn_cable, "cable")
        self.btn_cable.clicked.connect(self._cable_clicked)
        buttons = QHBoxLayout()   # each button only as wide as its words
        buttons.setSpacing(10)
        # "or" in front while the mic button is up: the cable and the other device are
        # for the few who'd rather not, not a second step
        self.cable_or = QLabel(_("or"))
        self.cable_or.setObjectName("hint")
        self.cable_or.hide()
        buttons.addWidget(self.cable_or)
        buttons.addWidget(self.btn_cable)
        self.btn_recheck = QPushButton(_("⟳  Check again"))
        self.btn_recheck.clicked.connect(lambda: busy.run_busy(
            self.btn_recheck, _("Checking…"), self.recheck_cable,
            lambda _r: None if self.route_ok() else _("Still not found: checked just now"),
            ms=3500))
        buttons.addWidget(self.btn_recheck)
        self.btn_restart = QPushButton(_("⟲  Restart my PC now"))
        self.btn_restart.setObjectName("primary")
        self.btn_restart.clicked.connect(self.restart_pc)
        self.btn_restart.hide()
        v.addWidget(self.btn_restart, 0, Qt.AlignmentFlag.AlignLeft)
        # streamers and Voicemeeter / mixer users: send somewhere else instead
        self.btn_other = QPushButton(_("Other device"))
        icons.set_icon(self.btn_other, "sliders")
        self.btn_other.setToolTip(_("Send your sounds to another device instead (Voicemeeter, "
                                    "OBS, a mixer…), or nowhere (only you, and the stream "
                                    "output)"))
        self.btn_other.clicked.connect(lambda: self._show_other(True))
        buttons.addWidget(self.btn_other)
        # the cable (or another device) works: the mic as the other way, not the main one
        self.btn_mic_instead = QPushButton(_("Straight into my mic instead"))
        icons.set_icon(self.btn_mic_instead, "mic")
        self.btn_mic_instead.setToolTip(_("Put your sounds into the mic you already use, "
                                          "so Discord and games need no changes"))
        self.btn_mic_instead.clicked.connect(self.attach_mic)
        self.btn_mic_instead.hide()
        buttons.insertWidget(0, self.btn_mic_instead)
        buttons.addStretch(1)
        v.addLayout(buttons)
        self.other_box = QWidget()
        self.other_lay = QVBoxLayout(self.other_box)
        self.other_lay.setContentsMargins(0, 0, 0, 0)
        self.other_box.hide()
        v.addWidget(self.other_box, 1)
        self.btn_use_cable = QPushButton(_("Use the virtual cable after all"))
        icons.set_icon(self.btn_use_cable, "cable")
        self.btn_use_cable.clicked.connect(lambda: self._pick_route("cable"))
        self.btn_use_cable.hide()
        v.addWidget(self.btn_use_cable, 0, Qt.AlignmentFlag.AlignLeft)
        # the other ways are for a few people (streamers, mixers, a game that skips the
        # mic): a pill that opens their card, not a card that's always there. Open, it
        # read like a second thing to do, with words new users don't need yet
        self.alt_fold = FoldPill(_("Other ways: virtual cable, OBS, a mixer"), "sliders")
        self.alt_fold.toggled.connect(self._fold_alt)
        self.alt_fold_row = QWidget()   # (takes no room while hidden)
        fold_row = QHBoxLayout(self.alt_fold_row)
        fold_row.setContentsMargins(0, 0, 0, 0)
        fold_row.addWidget(self.alt_fold)
        fold_row.addStretch(1)
        self.alt_fold_row.hide()
        v.addWidget(self.alt_fold_row)
        v.addWidget(self._alt_card())
        v.addStretch(1)
        return p

    def _fold_alt(self, open_: bool):
        """Open or shut the other ways' card under its pill."""
        self.alt_fold.setToolTip(_("Hide") if open_ else _("Show"))
        self.alt_fold.setAccessibleDescription(self.alt_fold.toolTip())
        self.alt_card.setVisible(open_ and not self.alt_fold_row.isHidden())
        QTimer.singleShot(SETTLE_MS, self, self._settle_size)   # shut: no band left

    def _alt_card(self) -> QFrame:
        """Sending into the mic: the other ways, in their own card under it, side by
        side as small tiles (icon, name, why you'd want it, then its button on the
        same edge). Before, their buttons sat right under the green "On your mic" and
        read like a step still to do. It opens under its pill (alt_fold), which is
        its heading."""
        self.alt_card, cl = _card(14, 12, roomy=False)
        tiles = QHBoxLayout()   # two halves; one left alone (the other's list is open)
        tiles.setSpacing(12)    # takes the whole row, not half of it beside a hole

        def tile(icon: str, title: str, words: str, button: QPushButton) -> QFrame:
            box = panel.alt_tile(icon, title, words, button)[0]
            tiles.addWidget(box, 1)
            return box

        self.btn_alt_cable = QPushButton(_("Use the cable"))
        icons.set_icon(self.btn_alt_cable, "cable")
        self.btn_alt_cable.setToolTip(_("Use a free virtual cable instead: you pick it as the "
                                        "mic in Discord and games"))
        self.btn_alt_cable.clicked.connect(self._alt_cable)
        self.alt_cable_row = tile(
            "cable", _("Virtual cable"),
            _("No mic, or you'd rather Onion Board didn't touch yours? Use a free virtual "
              "cable instead: you pick it as the mic in Discord and games."),
            self.btn_alt_cable)
        self.btn_alt_other = QPushButton(_("Pick a device"))
        icons.set_icon(self.btn_alt_other, "sliders")
        self.btn_alt_other.clicked.connect(lambda: self._show_other(True))
        self.alt_other_row = tile(
            "sliders", _("Another device"),
            _("For streamers and mixers: send your sounds to Voicemeeter, OBS, a mixer or a "
              "capture card, or to nobody."),
            self.btn_alt_other)
        cl.addLayout(tiles)
        self.alt_card.hide()
        return self.alt_card

    def _sync_or(self):
        """The "or" before the cable's buttons: only between the mic button and them."""
        if hasattr(self, "cable_or"):
            self.cable_or.setVisible(not self.btn_attach.isHidden() and (
                not self.btn_cable.isHidden() or not self.btn_other.isHidden()))

    def _show_other(self, on: bool):
        """The list of other places to send to: every output but your headphones (you'd
        hear everything twice), and nowhere. Filled when shown, after step 2's pick."""
        while self.other_lay.count():
            item = self.other_lay.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.deleteLater()
        self.other_box.setVisible(on)
        self.btn_other.setVisible(not on and self._proc is None)
        self.alt_other_row.setVisible(not on)   # the list is open below the status now
        self._sync_or()
        if not on:
            return
        cfg = self.win.cfg
        self.other_lay.setSpacing(6)
        head = QLabel(_("Another device"))   # what this list is, like the card's head
        head.setObjectName("section")
        head.setProperty("head", True)
        self.other_lay.addWidget(head)
        self.other_lay.addWidget(panel.hint_label(_(
            "Pick where your sounds go instead. Onion Board plays them (and your voice, if "
            "you send it) into that device, and whatever listens to it gets them: OBS "
            "(<b>Audio Output Capture</b>), Voicemeeter, a mixer or a capture card.")))
        outs = [d["name"] for d in eng.list_devices("output") if d["name"] != cfg.mon_device]
        cur = (NOWHERE if cfg.route == "off" else
               cfg.main_device if cfg.route == "device" else None)
        lst, __ = self._choice_list(outs + [NOWHERE], cur, self._pick_route)
        self.other_lay.addSpacing(12 - 6)
        self.other_lay.addWidget(lst, 1)

    def _pick_route(self, choice: str):
        """Step 3: the cable ("cable"), nowhere (NOWHERE) or another device (its name).
        Applied at once, and kept even if the guide is closed (like a picked mic)."""
        if self.setup_show.on:
            self.setup_show._stop()
        if choice == "cable":
            self._chose_cable = True   # picked here: recheck_cable leaves it on the cable
            self.win.routectl.set_route("cable")
            self._show_other(False)
        elif choice == NOWHERE:
            self.win.routectl.set_route("off")
        else:
            self.win.routectl.set_route("device", choice)
        self.recheck_cable(rescan=False)

    def cable_ok(self) -> bool:
        return bool(eng.virtual_outputs())

    def route_ok(self) -> bool:
        """Step 3 is done: the cable is there, the mic effect is on the mic, another
        device is sending, or sending nowhere was picked on purpose."""
        route = self.win.cfg.route
        if route == "off":
            return True
        if route == "mic":
            return directmic.works(directmic.status(self.win.cfg.mic_device))
        if route == "device":   # picked, and it opened
            return (self.win.routectl._main_name() is not None
                    and "main" not in self.win.engine.errors_snapshot())
        return self.cable_ok()

    def _mic_attached(self, mic: str, err: str):
        if self.setup_show.on:
            self.setup_show.finish(not bool(err))
        self.recheck_cable(rescan=False)
        self._update_next()

    def _open_cable(self):
        """What others hear goes into the cable, opened on the device thread (the window
        never waits on a slow driver); then both ends of the cable onto 48 kHz, so it
        passes the sound through as is."""
        win = self.win

        def plan():
            send = win.routectl._send_plan(force_main=True)
            return lambda: win.routectl._open_send(send)

        def opened(ends):
            if ends is not None:
                win.micctl._set_cable_bad(ends)
            if win.micctl.cable_bad:
                win.micctl.fix_cable_format(quiet=True)
        win.devctl._device_job(plan, opened)

    def _say_mic_done(self):
        """The mic itself works (it's open): a green line says so above the status."""
        if self.win.engine.mic_stream is None:
            return
        mic = html.escape(self.win.cfg.mic_device or _("your mic"))
        self.mic_done.setText(_("<b style='color:{colour}'>✓ Your mic works:</b> Onion Board "
                                "hears <b>{mic}</b>. Now your sounds go into it too.",
                                colour=_ok(), mic=mic))
        self.mic_done.show()

    def recheck_cable(self, rescan: bool = True):
        if not self.setup_show.on:
            # (held while the mic sets up and its show plays: on success the pill
            # narrows, the words wrap a line less and the card would shrink)
            for label in (self.status_card.title, self.cable_status):
                label.setMinimumHeight(0)
        if rescan:
            self.win.devctl.refresh_devices()   # picks up a driver installed while we're open
        self.btn_restart.hide()
        busy = self._proc is not None
        self.cable_bar.setVisible(busy)
        self.cable_steps.setVisible(busy)
        if not busy and self.bun_cable.building:
            self.bun_cable.stop_building(self.cable_ok())
        route = self.win.cfg.route
        # on the cable, but the mic effect is already on the mic and working: use the mic
        # (the page leads with it) instead of offering to set it up all over again
        if (route == "cable" and not busy and not self._chose_cable
                and not self.win._attaching and not self.setup_show.on
                and directmic.works(directmic.status(self.win.cfg.mic_device))):
            self.win.routectl.set_route("mic")
            route = self.win.cfg.route
        # (straight into the mic has its own "...instead" button, below)
        self.btn_use_cable.setVisible(not busy and route not in ("cable", "mic"))
        self.btn_other.setVisible(not busy and self.other_box.isHidden())
        self.mic_done.hide()   # (shown below: on the mic, with the sounds not in it)
        self.alt_card.hide()   # the mic's other ways: shown below once it's the mic's page
        self.alt_fold_row.hide()
        attaching = self.win._attaching
        self.btn_attach.setVisible(not busy and not (route == "mic" and self.route_ok())
                                   and not self.setup_show.on)
        self.btn_attach.setEnabled(not attaching)
        state = directmic.status(self.win.cfg.mic_device)
        self.attach_report.set_failed(route == "mic" and not attaching and not busy
                                      and bool(self.win.micctl.fail_code)
                                      and not self.route_ok())
        # another way already works (the cable, a device): the mic is then an option in
        # the row below, not the big button that looked like it had to be set up again
        other_works = route != "mic" and not attaching and self.route_ok()
        if other_works:
            self.btn_attach.hide()
        self.btn_mic_instead.setVisible(other_works and not busy and not self.setup_show.on)
        ask = michelper.will_ask()   # (the mic helper does it without Windows' prompt)
        self.btn_attach.setText((_("Setting up… click Yes when Windows asks") if ask
                                 else _("Setting up…")) if attaching
                                else _("Repair (one click)") if directmic.needs_repair(state)
                                else _("Put my sounds straight into my mic"))
        if self.setup_show.on and not attaching:
            # the show is the mic's: a working cable doesn't make a failed mic set-up a win
            self.setup_show.finish(route == "mic" and self.route_ok())
        if route == "mic" and not busy and not self._cable_tries and not self._needs_restart:
            self.other_box.hide()
            if self.setup_show.on:
                if self.route_ok():
                    self._show_working()
                else:
                    self.status_card.set_state("busy", _("Setting up"), _("Setting up…"))
                    self.cable_status.setText(_("Click Yes when Windows asks.")
                                              if attaching and ask else "")
                    self._hold_working_room()
                self.btn_cable.hide()
                self.btn_recheck.hide()
                self.btn_other.hide()
                self._update_next()
                return
            # the step's one action is the corner button (Next: _mic_action), not a
            # second button in the card saying the same
            self.btn_attach.hide()
            if self.route_ok():
                self._show_working()
            elif directmic.needs_repair(state):
                self._say_mic_done()
                self.status_card.set_state("warn", "", _("Your mic needs a quick repair"))
                self.cable_status.setText(_("Onion Board was on your mic but needs a quick "
                                            "repair: <b>one click</b>, and Windows asks for "
                                            "permission once.") if ask else
                                          _("Onion Board was on your mic but needs a quick "
                                            "repair: <b>one click</b>."))
            else:
                self._say_mic_done()
                self.status_card.set_state("", "", _("Your sounds aren't in your mic yet"))
                self.cable_status.setText(directmic.with_helper_note(
                                          _("Others hear your voice, but not your sounds. Press "
                                            "<b>Put my sounds in my mic</b> below: Onion Board "
                                            "adds its audio driver to your mic. Windows asks "
                                            "once: click <b>Yes</b>. Your sound drops out for a "
                                            "second while it sets up.")) if ask else
                                          _("Others hear your voice, but not your sounds. Press "
                                            "<b>Put my sounds in my mic</b> below: Onion Board "
                                            "adds its audio driver to your mic. Your sound "
                                            "drops out for a second while Windows reloads it."))
            # the other ways sit in their own card, not as buttons under the status
            self.btn_cable.hide()
            self.btn_other.hide()
            self.btn_recheck.hide()
            self.alt_fold_row.show()
            self.alt_card.setVisible(self.alt_fold.isChecked())
            self.alt_other_row.setVisible(self.other_box.isHidden())
            self._update_next()
            return
        if busy:
            self.status_card.set_state("busy", _("Setting up"))
            self.cable_status.setText(_("<b>Bun is setting it up for you…</b>"))
            self.cable_steps.setText(self._steps_html())
            self.btn_cable.hide()
            self.btn_recheck.hide()
            self.other_box.hide()
        elif route != "cable":
            if self.other_box.isHidden():
                self._show_other(True)
            dev = self.win.routectl._main_name()
            self.status_card.set_state(
                "ok" if self.route_ok() else "warn" if dev else "",
                _("Working") if self.route_ok() else _("Not working") if dev else "")
            if route == "off":
                self.cable_status.setText(_("<b style='color:{colour}'>✓ Sending nowhere.</b> "
                                            "Only you hear your sounds (and a device set to "
                                            "Clean, for streaming under Also play on).",
                                            colour=_ok()))
            elif self.route_ok():
                self.cable_status.setText(_("<b style='color:{colour}'>✓ Sending to "
                                            "{device}.</b> Press Next.", colour=_ok(),
                                            device=html.escape(dev)))
            elif dev:
                self.cable_status.setText(_("<b style='color:{colour}'>Couldn't open "
                                            "{device}.</b> Is it plugged in? Pick another one, "
                                            "or press Next to carry on.", colour=_bad(),
                                            device=html.escape(dev)))
            else:
                self.cable_status.setText(_("Pick the device your sounds should go to."))
            self.btn_cable.hide()
            self.btn_recheck.hide()
        elif self.cable_ok():
            if not eng.is_virtual(self.win.cfg.main_device):
                self.win.cfg.main_device = eng.virtual_outputs()[0]
            self._open_cable()
            self.status_card.set_state("ok", _("Installed"))
            resume_after_restart(False)
            if self._resumed:   # back from the restart, and it worked
                self._resumed = False
                self.bun_cable.stop_building(True)
                self.cable_status.setText(_("<b style='color:{colour}'>Welcome back, the cable "
                                            "works now!</b> Press Next for the last step.",
                                            colour=_ok()))
            else:
                self.cable_status.setText(_("<b style='color:{colour}'>✓ Installed and "
                                            "connected.</b> Nothing to do here, press Next.",
                                            colour=_ok()))
            self.btn_cable.hide()
            self.btn_recheck.hide()
        elif self._needs_restart or cable_restart_pending():
            # installed, but Windows wants a restart before it works. Never install it
            # again before then (VB-Audio says not to); the button below only re-runs
            # the installer's wake-up (restart the cable + audio service), no reinstall.
            resume_after_restart(True)
            self.status_card.set_state("warn", _("Restart needed"))
            self.cable_status.setText(_("<b style='color:{colour}'>✓ Installed.</b> Windows "
                                        "needs a <b>restart</b> to finish setting it up. Restart "
                                        "whenever suits you: Onion Board will open by itself "
                                        "afterwards and pick up right here.", colour=_ok()))
            self.btn_cable.setText(_("Try once more without restarting"))
            self.btn_cable.setVisible(not self._needs_restart)   # it just tried that
            self.btn_recheck.show()
            self.btn_restart.show()
        elif self._cable_tries:
            self.status_card.set_state("warn", _("Not working"))
            self.cable_status.setText(_("<b style='color:{colour}'>That didn't work.</b> If "
                                        "Windows asked for permission, click <b>Yes</b> this "
                                        "time. If it still won't install, restarting your PC "
                                        "often helps.", colour=_bad()))
            self.btn_cable.setText(_cable_text(_("⬇  Try installing again")))
            self.btn_cable.show()
            self.btn_recheck.show()
        elif self._resumed:   # back from the restart, and it still isn't there
            self.status_card.set_state("warn", _("Not working"))
            self.cable_status.setText(_("<b style='color:{colour}'>It still isn't showing up after "
                                        "the restart.</b> Install it again below; if Windows "
                                        "asks for permission, click <b>Yes</b>.", colour=_bad()))
            self.btn_cable.setText(_cable_text(_("⬇  Try installing again")))
            self.btn_cable.show()
            self.btn_recheck.show()
        else:
            self.status_card.set_state("warn", _("Not set up"))
            # (said what "it" is: the step's title asks where the sounds go)
            self.cable_status.setText(_("<b style='color:{colour}'>Only you can hear your sounds "
                                        "so far.</b> Put them into your mic (nothing to "
                                        "install), or install the free virtual cable.",
                                        colour=_bad()))
            self.btn_cable.setText(_("Install the cable"))
            self.btn_cable.show()
            self.btn_recheck.hide()
        # switched off in Settings > Privacy & security: the installer's download
        # (PowerShell, from vb-audio.com) can't go through the app's connection
        allowed = net.allowed("setup_downloads")
        self.btn_cable.setEnabled(allowed)
        # what installing means, said calmly: free, about a minute, one Windows prompt
        self.btn_cable.setToolTip(_("A free virtual cable from VB-Audio. It takes about a "
                                    "minute, and Windows asks once if that's OK. Then you "
                                    "pick it as the mic in Discord and games.") if allowed
                                  else net.off_message("setup_downloads"))
        if not allowed and not self.btn_cable.isHidden():
            self.btn_recheck.show()   # for after installing it by hand
            if net.offline():   # Offline mode: no dead button, and the way that works
                self.btn_cable.hide()
                self.cable_status.setText(_(
                    "<b style='color:{colour}'>Not installed.</b> Offline mode is on, so it "
                    "can't be downloaded here. Put your sounds straight into your mic "
                    "instead: nothing to install.", colour=_bad()))
        self._update_next()
        QTimer.singleShot(SETTLE_MS, self, self._settle_size)   # a shorter state: no band

    def _working_words(self) -> str:
        mic = self.win.cfg.mic_device or _("your mic")
        return _("Onion Board's audio driver is on <b>{mic}</b>. Discord and games hear "
                 "your sounds through it: press Next.", mic=html.escape(mic))

    def _hold_working_room(self):
        """While the mic sets up, keep the room the "Working" title and words will take,
        so the card doesn't grow on success and push everything under it down."""
        for label, text in ((self.status_card.title, _working_title()),
                            (self.cable_status, self._working_words())):
            w = label.width()
            if w <= 0:
                continue
            probe = QLabel(text)
            probe.setFont(label.font())
            probe.setStyleSheet(label.styleSheet())
            probe.setWordWrap(True)
            label.setMinimumHeight(probe.heightForWidth(w))
            probe.deleteLater()

    def _show_working(self):
        """On the mic and working: said in plain words, a green card and a pill."""
        self.status_card.set_state("ok", _("Installed"), _working_title())
        self.cable_status.setText(self._working_words())

    def _alt_cable(self):
        """Use the cable, from the optional card. With the driver working on the mic,
        ask first (CableConfirm): it's a step back for most people."""
        if not (self.win.cfg.route == "mic" and self.route_ok()):
            self._cable_clicked()   # not installed: asks first (only for those who need it)
            return
        dlg = self._cable_confirm = CableConfirm(self, self.win.cfg.mic_device or "")
        dlg.btn_tell.clicked.connect(lambda: (dlg.reject(), self._tell_us()))
        dlg.accepted.connect(self.install_cable)
        dlg.open()   # modal over the guide; answered through its signals

    def _tell_us(self):
        """The driver let them down: the feedback box, over the guide."""
        from soundboard.ui.kit import feedbackdialog
        self._feedback = feedbackdialog.ask(self.win.cfg, self)

    def attach_mic(self):
        self._chose_cable = False
        if self.win.cfg.route != "mic" and directmic.works(
                directmic.status(self.win.cfg.mic_device)):
            self.win.routectl.set_route("mic")   # already on the mic: no admin prompt, no reinstall
            self.recheck_cable(rescan=False)
            return
        self.setup_show.start()
        self.win.micctl.attach_mic()
        self.recheck_cable(rescan=False)
        self._update_next()   # Back / Next wait for it

    def _cable_clicked(self):
        """The first install asks first (it's only for those who need it); a retry after a
        failed one, or back from the restart, goes straight on."""
        if self._cable_tries or self._resumed or (
                self.win.cfg.route == "mic" and self.cable_ok()):
            self.install_cable()
        else:
            cableconfirm.ask(self, self.install_cable, self.attach_mic)

    def install_cable(self):
        if self.setup_show.on:
            self.setup_show._stop()
        if self.win.cfg.route == "mic" and self.cable_ok():   # "...instead", and it's there
            self._pick_route("cable")
            return
        script = RESOURCE_DIR / "install-vbcable.ps1"
        if not net.allowed("setup_downloads"):
            self.cable_status.setText(html.escape(net.off_message("setup_downloads")))
            return
        if not script.exists():
            self.cable_status.setText(_("<span style='color:{colour}'>The cable installer is "
                                        "missing. Get it from vb-audio.com/Cable.</span>",
                                        colour=_bad()))
            return
        global _installer
        if self._proc is not None:
            return   # one install at a time
        if self.win.cfg.route == "mic":   # "Use the virtual cable instead"
            self.win.routectl.set_route("cable")
        try:
            status = self._status_file()
            status.unlink(missing_ok=True)
            proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                 str(script), "-Silent", "-StatusFile", str(status)],
                creationflags=subprocess.CREATE_NO_WINDOW)
        except OSError as e:
            self.cable_status.setText(_("<span style='color:{colour}'>Couldn't start the cable "
                                        "installer ({error}).</span> Restart your PC and try "
                                        "again, or install it yourself from vb-audio.com/Cable.",
                                        colour=_bad(), error=errors.plain(e)))
            return
        self._cable_tries += 1
        self._needs_restart = False
        self._resumed = False
        self._cable_step, self._steps_seen = "", []
        self._proc = _installer = proc
        self.bun_cable.build()
        self.recheck_cable(rescan=False)

    _status_dir = None   # the folder made already (not on every tick)

    @classmethod
    def _status_file(cls):
        if cls._status_dir != library.APP_DIR:
            library.APP_DIR.mkdir(parents=True, exist_ok=True)
            cls._status_dir = library.APP_DIR
        return library.APP_DIR / "cable-install-status.txt"

    def _read_cable_step(self):
        """Pick up the installer's current step from its status file."""
        try:
            step = self._status_file().read_text(encoding="utf-8-sig").split("|", 1)[0].strip()
        except OSError:
            return
        if step != self._cable_step and step in dict(CABLE_STEPS):
            self._cable_step = step
            if step not in self._steps_seen:
                self._steps_seen.append(step)
            self.cable_steps.setText(self._steps_html())

    def _steps_html(self) -> str:
        """The install checklist: ✓ done, ▶ now, ○ still to come."""
        rows = []
        for key, text in CABLE_STEPS:
            if key == self._cable_step:
                rows.append(f"<b>▶  {text}…</b>")
            elif key in self._steps_seen:
                rows.append(f"<span style='color:{_ok()}'>✓  {text}</span>")
            elif key != "wake":   # only listed if it actually happens
                rows.append(f"<span style='color:gray'>○  {text}</span>")
        return "<br>".join(rows)

    def restart_pc(self):
        if QMessageBox.question(
                self, _("Restart now?"),
                _("Your PC will restart in a few seconds. Save anything you have open "
                  "first.\n\nOnion Board will open by itself after the restart to finish setting "
                  "up.")) \
                != QMessageBox.StandardButton.Yes:
            return
        self.win.cfg.save()
        try:
            subprocess.Popen(["shutdown", "/r", "/t", "5"],
                             creationflags=subprocess.CREATE_NO_WINDOW)
            busy.hold(self.btn_restart, _("Restarting in a few seconds…"))
        except OSError as e:
            self.cable_status.setText(_("<span style='color:{colour}'>Couldn't restart the PC "
                                        "({error}).</span> Restart it from the Start menu (Power → "
                                        "Restart); Onion Board will pick up here afterwards.",
                                        colour=_bad(), error=errors.plain(e)))
