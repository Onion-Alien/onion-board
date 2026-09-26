"""Quick setup: the four questions a first-time user has to answer, one per page,
in plain words. Shown on the very first launch (and from the Setup tab's
Step-by-step guide button any time after).

  1. Which microphone do you talk into?   (live level bar: "talk, it should move")
  2. Where do you listen?                 (test beep)
  3. The virtual cable                    (checks it's there; installs it if not)
  4. Tell Discord / your game             (the one setting outside the app)

Every choice is applied to the engine as it's made, so the level bar and the test
beep use the real devices. The window's own device boxes are refreshed at the end.
"""
from __future__ import annotations

import ctypes
import subprocess
import time

import numpy as np
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QDialog, QFrame,
                               QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QRadioButton, QScrollArea, QStackedWidget,
                               QVBoxLayout, QWidget)

from soundboard import engine as eng
from soundboard.bunny import bunny_pixmap
from soundboard.engine import SR
from soundboard import library
from soundboard.library import RESOURCE_DIR
from soundboard.ui.widgets import Meter

RESTART_NEEDED = 3010   # install-vbcable.ps1: installed, but Windows must restart first


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

TITLE_CSS = "font-size:17pt; font-weight:800;"
BODY_CSS = "font-size:11pt;"
OK, BAD = "#13ce66", "#ffb020"


def _label(text: str, css: str = BODY_CSS) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setTextFormat(Qt.RichText)
    lbl.setStyleSheet(css)
    return lbl


def _header(title: str, prop: str | None) -> QHBoxLayout:
    """A page title with Bun beside it, holding something that fits the page."""
    row = QHBoxLayout()
    row.addWidget(_label(title, TITLE_CSS), 1)
    pic = QLabel()
    dpr = QApplication.instance().devicePixelRatio() if QApplication.instance() else 1.0
    pic.setPixmap(bunny_pixmap(110, prop, dpr))
    row.addWidget(pic, 0, Qt.AlignTop)
    return row


class SetupWizard(QDialog):
    PAGES = 4

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Soundboard — quick setup")
        self.setMinimumSize(620, 520)
        self._proc: subprocess.Popen | None = None   # the cable installer, while it runs
        self._cable_tries = 0
        self._needs_restart = False   # the installer said Windows must restart first

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 18)
        v.setSpacing(12)
        self.progress = QLabel()
        self.progress.setObjectName("muted")
        v.addWidget(self.progress)
        self.stack = QStackedWidget()
        v.addWidget(self.stack, 1)
        self.stack.addWidget(self._page_mic())
        self.stack.addWidget(self._page_headphones())
        self.stack.addWidget(self._page_cable())
        self.stack.addWidget(self._page_discord())

        nav = QHBoxLayout()
        self.btn_back = QPushButton("←  Back")
        self.btn_back.clicked.connect(lambda: self.go(self.stack.currentIndex() - 1))
        nav.addWidget(self.btn_back)
        nav.addStretch(1)
        self.btn_next = QPushButton("Next  →")
        self.btn_next.setObjectName("primary")
        self.btn_next.setMinimumWidth(160)
        self.btn_next.setStyleSheet("padding:10px 18px; font-size:11pt;")
        self.btn_next.clicked.connect(self.next_clicked)
        nav.addWidget(self.btn_next)
        v.addLayout(nav)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(40)
        self.go(0)

    # ------------------------------------------------------------------ pages
    def _choice_list(self, names: list[str], current: str | None,
                     on_pick) -> tuple[QWidget, QButtonGroup]:
        box = QWidget()
        bv = QVBoxLayout(box)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(6)
        group = QButtonGroup(box)
        for n in names:
            rb = QRadioButton(n)
            rb.setStyleSheet("font-size:11pt; padding:6px;")
            rb.setProperty("device", n)
            group.addButton(rb)
            bv.addWidget(rb)
            if n == current:
                rb.setChecked(True)
        if not names:
            bv.addWidget(_label(f"<span style='color:{BAD}'>None found. Plug it in, close "
                                "this, then press <b>Step-by-step guide</b> on the Setup "
                                "tab.</span>"))
        bv.addStretch(1)
        group.buttonClicked.connect(lambda b: on_pick(b.property("device")))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(box)
        return scroll, group

    def _page_mic(self) -> QWidget:
        p = QWidget()
        v = QVBoxLayout(p)
        v.addLayout(_header("🎤  Which microphone do you talk into?", "mic"))
        v.addWidget(_label("Pick the mic you use for gaming (your headset or desk mic). "
                           "<b>Say something</b> — the bar below should move when you talk."))
        mics = [d["name"] for d in eng.list_devices("input") if not eng.is_virtual(d["name"])]
        cur = self.win.cfg.mic_device if self.win.cfg.mic_device in mics else \
            (mics[0] if mics else None)
        if cur:
            self._pick_mic(cur)
        lst, self.mic_group = self._choice_list(mics, cur, self._pick_mic)
        v.addWidget(lst, 1)
        row = QHBoxLayout()
        row.addWidget(_label("Your voice:"))
        self.mic_meter = Meter()
        self.mic_meter.setFixedHeight(16)
        row.addWidget(self.mic_meter, 1)
        v.addLayout(row)
        self.mic_heard = _label("")
        v.addWidget(self.mic_heard)
        self.chk_send = QCheckBox("Send my voice too (untick if you only want your sounds "
                                  "to go out, not your mic)")
        self.chk_send.setChecked(self.win.cfg.mic_enabled)
        v.addWidget(self.chk_send)
        self._mic_peak_seen = False
        return p

    def _page_headphones(self) -> QWidget:
        p = QWidget()
        v = QVBoxLayout(p)
        v.addLayout(_header("🎧  Where do you listen?", "headphones"))
        v.addWidget(_label("Pick your headphones or speakers, then press <b>Play a test "
                           "beep</b>. Only you hear this."))
        outs = [d["name"] for d in eng.list_devices("output") if not eng.is_virtual(d["name"])]
        cur = self.win.cfg.mon_device if self.win.cfg.mon_device in outs else \
            (outs[0] if outs else None)
        if cur:
            self._pick_headphones(cur)
        lst, _ = self._choice_list(outs, cur, self._pick_headphones)
        v.addWidget(lst, 1)
        beep = QPushButton("🔊  Play a test beep")
        beep.setStyleSheet("padding:10px; font-size:11pt;")
        beep.clicked.connect(self.test_beep)
        v.addWidget(beep)
        v.addWidget(_label("Didn't hear it? Pick another one and try again.",
                           "font-size:9pt;"))
        return p

    def _page_cable(self) -> QWidget:
        p = QWidget()
        v = QVBoxLayout(p)
        v.addLayout(_header("🔌  The virtual cable", "plug"))
        v.addWidget(_label("This is a free add-on that works like an invisible microphone. "
                           "Soundboard puts <b>your sounds</b> (and your voice, if you send "
                           "it) into it, and Discord or your game listens to it."))
        self.cable_status = _label("")
        self.cable_status.setStyleSheet("font-size:12pt; padding:12px;")
        v.addWidget(self.cable_status)
        self.btn_cable = QPushButton("⬇  Install it now (free)")
        self.btn_cable.setObjectName("primary")
        self.btn_cable.setStyleSheet("padding:12px; font-size:12pt;")
        self.btn_cable.clicked.connect(self.install_cable)
        v.addWidget(self.btn_cable)
        self.btn_recheck = QPushButton("⟳  Check again")
        self.btn_recheck.clicked.connect(self.recheck_cable)
        v.addWidget(self.btn_recheck)
        self.btn_restart = QPushButton("⟲  Restart my PC now")
        self.btn_restart.setObjectName("primary")
        self.btn_restart.setStyleSheet("padding:12px; font-size:12pt;")
        self.btn_restart.clicked.connect(self.restart_pc)
        self.btn_restart.hide()
        v.addWidget(self.btn_restart)
        v.addStretch(1)
        return p

    def _page_discord(self) -> QWidget:
        p = QWidget()
        v = QVBoxLayout(p)
        v.addLayout(_header("🎮  Last step: tell Discord or your game", "star"))
        self.discord_text = _label("")
        v.addWidget(self.discord_text)
        row = QHBoxLayout()
        self.btn_copy = QPushButton("📋  Copy the name")
        self.btn_copy.clicked.connect(self.copy_name)
        row.addWidget(self.btn_copy)
        nomic = QPushButton("My game has no microphone setting")
        nomic.clicked.connect(self.win.open_windows_mic)
        row.addWidget(nomic)
        row.addStretch(1)
        v.addLayout(row)
        self.btn_steam = QPushButton("🎮  Playing a Steam game (CS2, Dota 2, Deadlock…)? "
                                     "Show me how")
        self.btn_steam.setToolTip("Games that use Steam voice chat take the mic from "
                                  "Steam's own settings")
        self.btn_steam.clicked.connect(lambda: SteamGuide(self, self._vm).exec())
        v.addWidget(self.btn_steam)
        v.addStretch(1)
        v.addWidget(_label("That's it. Add sounds by dragging files onto the window, then "
                           "click one to play it. You can open this guide again any time "
                           "from the <b>Setup</b> tab (<b>Step-by-step guide</b>).",
                           "font-size:10pt;"))
        return p

    # ------------------------------------------------------------------ navigation
    def go(self, i: int):
        i = max(0, min(self.PAGES - 1, i))
        self.stack.setCurrentIndex(i)
        self.progress.setText(f"Step {i + 1} of {self.PAGES}")
        self.btn_back.setVisible(i > 0)
        if i == 2:
            self.recheck_cable(rescan=False)
        elif i == 3:
            self._fill_discord()
        self._update_next()

    def _update_next(self):
        i = self.stack.currentIndex()
        if i == self.PAGES - 1:
            self.btn_next.setText("Finish  ✓")
        elif i == 2 and not self.cable_ok():
            self.btn_next.setText("Skip for now  →")
        else:
            self.btn_next.setText("Next  →")

    def next_clicked(self):
        i = self.stack.currentIndex()
        if i == self.PAGES - 1:
            self.finish()
        else:
            self.go(i + 1)

    def finish(self):
        cfg = self.win.cfg
        cfg.setup_done = self.cable_ok()   # without the cable, offer the guide again next time
        cfg.mic_enabled = self.chk_send.isChecked()
        self.win.chk_mic.setChecked(cfg.mic_enabled)
        cfg.save()
        self.win._init_devices()   # refresh the window's device boxes from the choices
        self.accept()

    def done(self, r):
        self.timer.stop()
        if r != QDialog.Accepted:
            self.win.cfg.save()
            self.win._init_devices()
        super().done(r)

    # ------------------------------------------------------------------ actions
    def _pick_mic(self, name: str):
        self.win.cfg.mic_device = name
        self.win.engine.set_mic_device(name)
        self._mic_peak_seen = False

    def _pick_headphones(self, name: str):
        self.win.cfg.mon_device = name
        self.win.engine.set_mon_device(name)

    def test_beep(self):
        n = int(0.18 * SR)
        t = np.arange(n) / SR
        env = np.minimum(1.0, np.minimum(t, t[::-1]) / 0.01)
        tone = np.concatenate([np.sin(2 * np.pi * f * t) * env for f in (660, 880)]) * 0.25
        self.win.engine.play("__setup__", np.stack([tone, tone], 1).astype(np.float32), 1.0,
                             preview=True)

    def cable_ok(self) -> bool:
        return bool(eng.virtual_outputs())

    def recheck_cable(self, rescan: bool = True):
        if rescan:
            self.win.refresh_devices()   # picks up a driver installed while we're open
        self.btn_restart.hide()
        if self.cable_ok():
            if not eng.is_virtual(self.win.cfg.main_device):
                self.win.cfg.main_device = eng.virtual_outputs()[0]
            self.win.engine.set_main_device(self.win.cfg.main_device)
            self.cable_status.setText(f"<b style='color:{OK}'>✓ Installed and connected.</b> "
                                      "Nothing to do here — press Next.")
            self.btn_cable.hide()
            self.btn_recheck.hide()
        elif self._proc is not None:
            self.cable_status.setText("⏳  Installing… <b>click Yes</b> when Windows asks for "
                                      "permission.")
            self.btn_cable.hide()
            self.btn_recheck.hide()
        elif self._needs_restart or cable_restart_pending():
            # installed, but Windows has to restart before it works; installing it again
            # before then is what VB-Audio says not to do
            self.cable_status.setText(f"<b style='color:{OK}'>✓ Installed.</b> Windows needs "
                                      "a <b>restart</b> to finish setting it up. Restart your "
                                      "PC and open Soundboard again — this guide will pick up "
                                      "where you left off.")
            self.btn_cable.hide()
            self.btn_recheck.show()
            self.btn_restart.show()
        elif self._cable_tries:
            self.cable_status.setText(f"<b style='color:{BAD}'>That didn't work.</b> If Windows "
                                      "asked for permission, click <b>Yes</b> this time. If it "
                                      "still won't install, restarting your PC often helps.")
            self.btn_cable.setText("⬇  Try installing again")
            self.btn_cable.show()
            self.btn_recheck.show()
        else:
            self.cable_status.setText(f"<b style='color:{BAD}'>Not installed yet.</b> "
                                      "Without it, only you can hear your sounds.")
            self.btn_cable.show()
            self.btn_recheck.hide()
        self._update_next()

    def install_cable(self):
        script = RESOURCE_DIR / "install-vbcable.ps1"
        if not script.exists():
            self.cable_status.setText(f"<span style='color:{BAD}'>The cable installer is "
                                      "missing. Get it from vb-audio.com/Cable.</span>")
            return
        self._cable_tries += 1
        self._proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
             "-Silent"], creationflags=subprocess.CREATE_NO_WINDOW)
        self.recheck_cable(rescan=False)

    def restart_pc(self):
        if QMessageBox.question(
                self, "Restart now?",
                "Your PC will restart in a few seconds. Save anything you have open first.\n\n"
                "After the restart, open Soundboard again to finish setting up.") \
                != QMessageBox.StandardButton.Yes:
            return
        self.win.cfg.save()
        subprocess.Popen(["shutdown", "/r", "/t", "5"], creationflags=subprocess.CREATE_NO_WINDOW)

    def _fill_discord(self):
        name = eng.virtual_mic_for(self.win.cfg.main_device)
        self._vm = name or "CABLE Output"
        if not name:
            self.discord_text.setText(
                f"<span style='color:{BAD}'>The virtual cable isn't set up yet, so only you "
                "will hear your sounds.</span> Go <b>Back</b> to install it, or finish now and "
                "this guide will open again next time.")
            self.btn_copy.hide()
            return
        self.btn_copy.show()
        self.discord_text.setText(
            "Soundboard now sends your voice and sounds into a new microphone called:"
            f"<p style='font-size:15pt; font-weight:800; color:{OK}'>{name}</p>"
            "<b>In Discord:</b> click the ⚙ gear (User Settings) → <b>Voice &amp; Video</b> → "
            f"<b>Input Device</b> → choose <b>{name}</b>.<br><br>"
            f"<b>In a game:</b> open its audio / voice chat settings and set the microphone to "
            f"<b>{name}</b>.")

    def copy_name(self):
        QApplication.clipboard().setText(self._vm)
        self.btn_copy.setText("✓  Copied")

    def _tick(self):
        e = self.win.engine
        lvl = e.level_mic if e.mic_stream is not None else 0.0
        self.mic_meter.set_level(lvl)
        if lvl > 0.05:
            self._mic_peak_seen = True
        if self.stack.currentIndex() == 0:
            if e.mic_stream is None:
                self.mic_heard.setText(f"<span style='color:{BAD}'>Couldn't open that mic — "
                                       "try another one.</span>")
            elif self._mic_peak_seen:
                self.mic_heard.setText(f"<b style='color:{OK}'>✓ Hearing you!</b>")
            else:
                self.mic_heard.setText("Waiting to hear you… if the bar doesn't move, pick "
                                       "another mic.")
        if self._proc is not None and (rc := self._proc.poll()) is not None:
            self._proc = None
            self._needs_restart = rc == RESTART_NEEDED
            self.recheck_cable()


class SteamGuide(QDialog):
    """Steam games with Steam voice chat (CS2, Dota 2, Deadlock, …) ignore Windows'
    mic and have no mic picker of their own: the microphone is chosen in the Steam
    client's Voice settings. And Steam's noise cancellation treats music as noise, so
    left on it chops up the sounds; this walks through all of it."""

    def __init__(self, parent, mic_name: str):
        super().__init__(parent)
        self.setWindowTitle("Steam games — set your mic")
        self.setMinimumWidth(600)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 18)
        v.setSpacing(12)
        v.addLayout(_header("🎮  Steam games", "headphones"))
        v.addWidget(_label(
            "Games that use <b>Steam's voice chat</b> (like <b>Counter-Strike 2</b>, "
            "<b>Dota 2</b> and <b>Deadlock</b>) don't have their own mic setting. "
            "They use the mic you pick <b>in Steam</b>. Do this once:"))
        v.addWidget(_label(
            "<ol style='margin-left:-20px'>"
            "<li style='margin-bottom:8px'>Open <b>Steam</b>. Click <b>Steam</b> in the "
            "top-left corner, then <b>Settings</b>.<br>"
            "<span style='font-size:9pt'>(In a game? Press <b>Shift + Tab</b> and click "
            "the ⚙ gear.)</span></li>"
            "<li style='margin-bottom:8px'>On the left, click <b>Voice</b>.</li>"
            "<li style='margin-bottom:8px'>Click the <b>Voice Input Device</b> box and "
            f"choose <b style='color:{OK}'>{mic_name}</b>.<br>"
            "<span style='font-size:9pt'>Not in the list? Close Steam completely "
            "(right-click its icon by the clock → Exit) and open it again.</span></li>"
            "<li style='margin-bottom:8px'>Under <b>Advanced options</b>, turn "
            "<b>OFF</b>: <b>Noise cancellation</b>, <b>Echo cancellation</b> and "
            "<b>Automatic volume/gain control</b>.<br>"
            "<span style='font-size:9pt'>They think music is background noise and cut "
            "your sounds up. Soundboard already cleans up your voice.</span></li>"
            "<li style='margin-bottom:8px'>Click <b>Start microphone test</b> and play a "
            "sound in Soundboard. You should hear it back.</li>"
            "<li>Restart the game if it was already open.</li>"
            "</ol>"))
        v.addWidget(_label(
            "<b>Push-to-talk tip:</b> if you use push-to-talk in Steam or the game, set "
            "the same key in Soundboard (⚙ Settings → <b>Hotkeys</b> → <b>Game push-to-talk</b>). "
            "Soundboard will then hold it down for you while a sound plays.",
            "font-size:10pt;"))
        row = QHBoxLayout()
        copy = QPushButton("📋  Copy the mic name")
        copy.clicked.connect(lambda: (QApplication.clipboard().setText(mic_name),
                                      copy.setText("✓  Copied")))
        row.addWidget(copy)
        open_steam = QPushButton("Open Steam's voice settings")
        open_steam.clicked.connect(self.open_steam)
        row.addWidget(open_steam)
        row.addStretch(1)
        ok = QPushButton("Done")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        v.addLayout(row)

    def open_steam(self):
        """steam://settings/voice opens the Voice page when Steam is installed; if it
        isn't, Windows says so and the written steps still apply."""
        QDesktopServices.openUrl(QUrl("steam://settings/voice"))
