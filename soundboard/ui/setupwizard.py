"""Quick setup: the four steps a first-time user goes through, one per page,
in plain words. Shown on the very first launch (and from the Setup tab's
Step-by-step guide button any time after).

  1. Which microphone do you talk into?   (live level bar: "talk, it should move")
  2. Where do you listen?                 (test sound)
  3. Where your sounds go                 (the virtual cable: checks it's there, installs
                                           it if not; or another device / nowhere instead)
  4. Tell Discord / your game / OBS       (the one setting outside the app)

Every choice is applied to the engine as it's made, so the level bar and the test
sound use the real devices. The window's own device boxes are refreshed at the end.
"""
from __future__ import annotations

import ctypes
import html
import subprocess
import time

import numpy as np
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QDialog, QFrame,
                               QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton,
                               QRadioButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from soundboard import directmic
from soundboard import engine as eng
from soundboard import theme
from soundboard.engine import SR
from soundboard import library, net, otherboards
from soundboard.library import RESOURCE_DIR
from soundboard.ui import busy, fit, icons
from soundboard.ui.bunnywidget import TALK, BunnyWidget
from soundboard.ui.setupshow import SetupShow
from soundboard.ui.widgets import Meter
from soundboard import errors
from soundboard.i18n import _

# step 3's "I don't use the cable" list: this choice sends nowhere (Config.route "off")
NOWHERE = _("Nobody: only I hear them")
RESTART_NEEDED = 3010   # install-vbcable.ps1: installed, but Windows must restart first
TICK_MS = 40            # the mic page's meter
SLOW_TICK_MS = 250      # the other pages: only the cable installer to keep up with

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
    return f'"{exe}" "{Path(__file__).resolve().parents[2] / "main.py"}"'


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


TUNE_NOTES = (98.0, 123.47, 146.83, 196.0)   # G2 B2 D3 G3: a G-major arpeggio, down low
TUNE_BASS = 49.0                              # G1 under it
TUNE_PEAK = 0.2


def _pulse(f: float, t: np.ndarray, duty: float = 0.25, top: float = 5000) -> np.ndarray:
    """An 8-bit style pulse wave, built from its harmonics up to `top` Hz so it's
    gritty without the fizzy aliasing a raw square has."""
    out = np.zeros_like(t)
    for k in range(1, int(top / f) + 1):
        out += np.sin(np.pi * k * duty) / k * np.cos(2 * np.pi * k * f * t - np.pi * k * duty)
    return out * (4 / np.pi)


def _steps(env: np.ndarray, levels: int = 15) -> np.ndarray:
    """Old consoles faded in 1/15ths, not smoothly: that stepped decay is half the sound."""
    return np.round(env * levels) / levels


def test_tune() -> np.ndarray:
    """The test sound (stereo float32): a quick G-major arpeggio in an 8-bit pulse
    wave over a deep, stepped triangle-wave bass, like an old console's fanfare."""
    step, note_len, bass_len = 0.1, 0.42, 1.25
    n = int(max(step * (len(TUNE_NOTES) - 1) + note_len, bass_len) * SR)
    out = np.zeros((n, 2))
    # the arpeggio: 25% pulse, stepped decay, low notes a touch left, high a touch right
    t = np.arange(int(note_len * SR)) / SR
    env = _steps(np.minimum(1.0, t / 0.004) * np.exp(-t * 6))
    for i, f in enumerate(TUNE_NOTES):
        tone = _pulse(f, t) * env * (0.55 if i < len(TUNE_NOTES) - 1 else 0.7)
        pan = (i / (len(TUNE_NOTES) - 1) - 0.5) * 0.4
        at = int(i * step * SR)
        out[at:at + len(t), 0] += tone * (1 - pan)
        out[at:at + len(t), 1] += tone * (1 + pan)
    # the bass: a 4-bit triangle (16 levels, like the NES bass channel), held long
    t = np.arange(int(bass_len * SR)) / SR
    tri = np.round((2 * np.abs(2 * ((TUNE_BASS * t) % 1) - 1) - 1) * 7.5) / 7.5
    bass = tri * _steps(np.minimum(1.0, t / 0.01) * np.exp(-t * 1.8))
    out[:len(t)] += bass[:, None]
    fade = int(0.03 * SR)
    out[-fade:] *= np.linspace(1, 0, fade)[:, None]
    out[:int(0.002 * SR)] *= np.linspace(0, 1, int(0.002 * SR))[:, None]
    return (out * (TUNE_PEAK / np.abs(out).max())).astype(np.float32)


TITLE_CSS = "font-size:17pt; font-weight:800;"
BODY_CSS = "font-size:11pt;"


def _ok() -> str:    # status colours readable on the current theme (theme.status)
    return theme.status("ok")


def _bad() -> str:
    return theme.status("warn")


def _cable_text(text: str) -> str:
    """A cable button's words without their ⬇ (the button has the cable picture)."""
    return text.replace("⬇", "").strip()


def _test_title() -> str:
    return _("Play a test sound")


def _choice_icon(name: str, kind: str) -> str:
    """A device's picture in the pick lists: a mic, headphones or a speaker."""
    if kind == "input":
        return "mic"
    low = name.lower()
    return "headphones" if any(w in low for w in ("headphone", "headset", "earbud",
                                                 "airpods", "buds")) else "volume"


def _card(margins: int = 16, spacing: int = 12,
          roomy: bool = True) -> tuple[QFrame, QVBoxLayout]:
    """A rounded panel (the theme's card) to group a page's buttons; `roomy` gives
    them the theme's bigger padding."""
    card = QFrame()
    card.setObjectName("card")
    card.setProperty("roomy", roomy)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(margins, margins, margins, margins)
    lay.setSpacing(spacing)
    return card, lay


def _label(text: str, css: str = BODY_CSS) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setTextFormat(Qt.RichText)
    lbl.setStyleSheet(css)
    return lbl


def _header(title: str, body: QLabel, bun: BunnyWidget) -> QHBoxLayout:
    """A page's title and intro, with Bun (holding something that fits the page)
    beside both. He sits in the same top-right spot on every page, and his widget
    carries its own padding, so he has even room all round instead of sitting on top
    of the text."""
    row = QHBoxLayout()
    row.setSpacing(16)
    col = QVBoxLayout()
    col.setSpacing(10)
    col.addWidget(_label(title, TITLE_CSS))
    col.addWidget(body)
    col.addStretch(1)
    row.addLayout(col, 1)
    row.addWidget(bun, 0, Qt.AlignTop)
    return row


class _RoundButton(QPushButton):
    """A round accent button showing just its icon (the test sound's speaker). Painted
    by hand: the theme's button rules square off a style-sheet circle."""

    def __init__(self, size: int):
        super().__init__()
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = theme.T
        col = QColor(t["accent_hover"] if self.underMouse() or self.isDown() else t["accent"])
        if self.isDown():
            col = col.darker(115)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(t["text"]), 2) if self.hasFocus() else Qt.NoPen)
        p.setBrush(col)
        p.drawEllipse(r)
        s = self.iconSize()
        pm = self.icon().pixmap(s, self.devicePixelRatioF())
        p.drawPixmap(round((self.width() - s.width()) / 2),
                     round((self.height() - s.height()) / 2), pm)


class SetupWizard(QDialog):
    PAGES = 4

    def __init__(self, win, resumed: bool = False):
        """`resumed`: opened by itself after the restart the cable asked for, so it
        starts on the cable step and welcomes them back."""
        super().__init__(win)
        self._resumed = resumed
        fit.watch(self)   # grows to fit its text (ui/fit.py)
        self.win = win
        self.setWindowTitle(_("Onion Board: quick setup"))
        self.setMinimumSize(620, 520)
        # the cable installer, while it runs (one a closed guide left running included)
        self._proc: subprocess.Popen | None = \
            _installer if _installer is not None and _installer.poll() is None else None
        self._cable_tries = 0
        self._needs_restart = False   # the installer said Windows must restart first
        self._cable_step = ""         # the installer's current step (CABLE_STEPS)
        self._steps_seen: list[str] = []
        # the devices from before the guide: a page that stands in the first one it
        # finds for a missing (unplugged) device must not overwrite them on Cancel
        self._saved_devices = {"mic_device": win.cfg.mic_device,
                               "mon_device": win.cfg.mon_device}
        self._user_picked: set[str] = set()   # the ones they actually clicked

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
        # fill the last page's text now, so the window sizes itself for the tallest
        # page when it opens and stays the same size through every step
        self._fill_discord()

        nav = QHBoxLayout()
        self.btn_back = QPushButton(_("←  Back"))
        self.btn_back.clicked.connect(self.back_clicked)
        nav.addWidget(self.btn_back)
        nav.addStretch(1)
        self.btn_next = QPushButton(_("Next  →"))
        self.btn_next.setObjectName("primary")
        self.btn_next.clicked.connect(self.next_clicked)
        self.btn_next.setDefault(True)   # Enter moves on (not "Play a test sound")
        nav.addWidget(self.btn_next)
        v.addLayout(nav)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(TICK_MS)
        if self._proc is not None:   # still installing from a guide closed mid-way
            self.bun_cable.build()
        if win._attaching:
            self.setup_show.start()
        self.go(2 if resumed or self._proc is not None or win._attaching else 0)

    # ------------------------------------------------------------------ pages
    def _choice_list(self, names: list[str], current: str | None,
                     on_pick, kind: str = "output") -> tuple[QWidget, QButtonGroup]:
        """The devices as big tiles, each with its picture; the picked one is outlined."""
        box = QWidget()
        t = theme.T
        box.setStyleSheet(
            f"QRadioButton#choice {{ font-size:12pt; padding:11px 14px; spacing:12px; "
            f"background:{t['panel']}; border:1px solid transparent; border-radius:10px; }}"
            f"QRadioButton#choice:hover {{ background:{t['card_hi']}; "
            f"border-color:{t['border_hi']}; }}"
            f"QRadioButton#choice:checked {{ background:{t['card_hi']}; "
            f"border:2px solid {t['accent']}; padding:10px 13px; }}")
        bv = QVBoxLayout(box)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(8)
        group = QButtonGroup(box)
        for n in names:
            rb = QRadioButton(n.replace("&", "&&"))   # a lone & is a shortcut marker
            rb.setObjectName("choice")
            icons.set_icon(rb, "stop" if n == NOWHERE else _choice_icon(n, kind), size=20)
            rb.setProperty("device", n)
            group.addButton(rb)
            bv.addWidget(rb)
            if n == current:
                rb.setChecked(True)
        if not names:
            bv.addWidget(_label(_("<span style='color:{colour}'>None found. Plug it in, close "
                                  "this, then press <b>Step-by-step guide</b> on the Setup "
                                  "tab.</span>", colour=_bad())))
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
        self.bun_mic = BunnyWidget("mic")
        v.addLayout(_header(_("Which microphone do you talk into?"),
                            _label(_("Pick the mic you use for gaming (your headset or desk "
                                     "mic). <b>Say something</b>, the bar below should move "
                                     "(and Bun talks along) when you talk.")),
                            self.bun_mic))
        mics = [d["name"] for d in eng.list_devices("input") if not eng.is_virtual(d["name"])]
        self._no_mics = not mics
        cur = self.win.cfg.mic_device if self.win.cfg.mic_device in mics else \
            (mics[0] if mics else None)
        if cur and cur != self.win.cfg.mic_device:   # the saved one is missing
            self._pick_mic(cur)
        lst, self.mic_group = self._choice_list(
            mics, cur, lambda n: self._pick_mic(n, by_user=True), "input")
        v.addSpacing(6)
        v.addWidget(lst)
        v.addSpacing(10)
        card, cl = _card(16, 10, roomy=False)
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(_label(_("Your voice:")))
        self.mic_meter = Meter()
        self.mic_meter.setFixedHeight(16)
        row.addWidget(self.mic_meter, 1)
        cl.addLayout(row)
        self.mic_heard = _label("")
        cl.addWidget(self.mic_heard)
        self.chk_send = QCheckBox(_("Send my voice too (untick if you only want your sounds to "
                                    "go out, not your mic)"))
        self.chk_send.setChecked(self.win.cfg.mic_enabled)
        cl.addWidget(self.chk_send)
        v.addWidget(card)
        v.addStretch(1)
        self._mic_peak_seen = False
        return p

    def _page_headphones(self) -> QWidget:
        p = QWidget()
        v = QVBoxLayout(p)
        self.bun_phones = BunnyWidget("headphones")
        v.addLayout(_header(_("Where do you listen?"),
                            _label(_("Pick your headphones or speakers, then press the "
                                     "<b>speaker button</b>. Only you hear this.")),
                            self.bun_phones))
        outs = [d["name"] for d in eng.list_devices("output") if not eng.is_virtual(d["name"])]
        cur = self.win.cfg.mon_device if self.win.cfg.mon_device in outs else \
            (outs[0] if outs else None)
        if cur and cur != self.win.cfg.mon_device:   # the saved one is missing
            self._pick_headphones(cur)
        lst, __ = self._choice_list(outs, cur,
                                   lambda n: self._pick_headphones(n, by_user=True))
        v.addSpacing(6)
        v.addWidget(lst)
        v.addSpacing(10)
        # a round speaker button in a card, with what to do next to it
        card, cl = _card(14, roomy=False)
        row = QHBoxLayout()
        row.setSpacing(16)
        play = self.btn_test = _RoundButton(56)
        icons.set_icon(play, "volume", "on_accent", size=26)
        play.setToolTip(_test_title())
        play.setAccessibleName(_test_title())
        play.clicked.connect(self.test_sound)
        row.addWidget(play)
        words = QVBoxLayout()
        words.setSpacing(2)
        words.addStretch(1)
        self.test_hint = _label(f"<b>{_test_title()}</b>", "font-size:12pt;")
        words.addWidget(self.test_hint)
        hint = _label(_("Only you hear it. Didn't hear it? Pick another one and try again."),
                      "font-size:10pt;")
        hint.setObjectName("muted")
        words.addWidget(hint)
        words.addStretch(1)
        row.addLayout(words, 1)
        cl.addLayout(row)
        v.addWidget(card)
        v.addStretch(1)
        return p

    def _page_cable(self) -> QWidget:
        p = QWidget()
        v = QVBoxLayout(p)
        self.bun_cable = BunnyWidget("plug")
        v.addLayout(_header(_("Where do your sounds go?"),
                            _label(_("Straight into <b>your mic</b>: one click, and Discord "
                                     "and games hear your sounds through the mic they already "
                                     "use. Nothing to install from the internet, nothing to "
                                     "pick in Discord. (Or use a free <b>virtual cable</b> "
                                     "instead.)")),
                            self.bun_cable))
        self.btn_attach = QPushButton(_("Put my sounds straight into my mic"))
        icons.set_icon(self.btn_attach, "mic", "on_accent")
        self.btn_attach.setObjectName("primary")
        self.btn_attach.clicked.connect(self.attach_mic)
        v.addWidget(self.btn_attach, 0, Qt.AlignLeft)
        self.setup_show = SetupShow(height=96)
        self.setup_show.done.connect(lambda: self.recheck_cable(rescan=False))
        v.addWidget(self.setup_show)
        # a bound method, not a lambda: Qt drops the link when the guide is freed, so a
        # set-up finishing after it closed can't poke its deleted buttons
        self.win.mic_attached.connect(self._mic_attached)
        self.cable_status = _label("")
        self.cable_status.setStyleSheet("font-size:12pt; padding:4px 0;")
        v.addWidget(self.cable_status)
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
        self.btn_cable = QPushButton(_cable_text(_("⬇  Install it now (free)")))
        icons.set_icon(self.btn_cable, "cable")
        self.btn_cable.clicked.connect(self.install_cable)
        buttons = QHBoxLayout()   # each button only as wide as its words
        buttons.setSpacing(10)
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
        v.addWidget(self.btn_restart, 0, Qt.AlignLeft)
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
        v.addWidget(self.btn_use_cable, 0, Qt.AlignLeft)
        v.addStretch(1)
        return p

    def _show_other(self, on: bool):
        """The list of other places to send to: every output but your headphones (you'd
        hear everything twice), and nowhere. Filled when shown, after step 2's pick."""
        while self.other_lay.count():
            w = self.other_lay.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.other_box.setVisible(on)
        self.btn_other.setVisible(not on and self._proc is None)
        if not on:
            return
        cfg = self.win.cfg
        self.other_lay.addWidget(_label(_(
            "Pick where your sounds go instead. Onion Board plays them (and your voice, if "
            "you send it) into that device, and whatever listens to it gets them: OBS "
            "(<b>Audio Output Capture</b>), Voicemeeter, a mixer or a capture card."),
            "font-size:10pt;"))
        outs = [d["name"] for d in eng.list_devices("output") if d["name"] != cfg.mon_device]
        cur = (NOWHERE if cfg.route == "off" else
               cfg.main_device if cfg.route == "device" else None)
        lst, __ = self._choice_list(outs + [NOWHERE], cur, self._pick_route)
        self.other_lay.addWidget(lst, 1)

    def _pick_route(self, choice: str):
        """Step 3: the cable ("cable"), nowhere (NOWHERE) or another device (its name).
        Applied at once, and kept even if the guide is closed (like a picked mic)."""
        if self.setup_show.on:
            self.setup_show._stop()
        if choice == "cable":
            self.win.set_route("cable")
            self._show_other(False)
        elif choice == NOWHERE:
            self.win.set_route("off")
        else:
            self.win.set_route("device", choice)
        self.recheck_cable(rescan=False)

    def _page_discord(self) -> QWidget:
        p = QWidget()
        v = QVBoxLayout(p)
        self.discord_text = _label("")
        head = _header(_("Last step: tell Discord or your game"), self.discord_text,
                       BunnyWidget("star", celebrate=True))
        self.discord_title = head.itemAt(0).layout().itemAt(0).widget()
        v.addLayout(head)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.btn_copy = QPushButton(_("Copy the name"))
        icons.set_icon(self.btn_copy, "copy")
        self.btn_copy.clicked.connect(self.copy_name)
        row.addWidget(self.btn_copy)
        nomic = self.btn_nomic = QPushButton(_("Game has no microphone setting?"))
        icons.set_icon(nomic, "mic")
        nomic.clicked.connect(self.win.open_windows_mic)
        row.addWidget(nomic)
        # coming from another soundboard: their board in one click (only offered for
        # ones whose board is here; nothing is read until they click)
        self.import_buttons = []
        for src in otherboards.found():
            btn = QPushButton(_("Bring my {name} sounds over", name=src.name))
            icons.set_icon(btn, "folder")
            btn.setToolTip(_("Copies the sounds on your {name} board into Onion Board, with "
                             "their names, categories and hotkeys. {name} keeps its own.",
                             name=src.name))
            btn.clicked.connect(lambda __=False, src=src: self.win.import_other(src))
            row.addWidget(btn)
            self.import_buttons.append(btn)
        row.addStretch(1)
        v.addLayout(row)
        # the helpers, grouped in one card: Discord first, then games and calls
        self.help_card, cl = _card(14, 10)
        self.discord_tip = _label("", "font-size:10.5pt;")
        cl.addWidget(self.discord_tip)
        self.btn_discord = QPushButton(_("Discord: make my sounds come through clean"))
        icons.set_icon(self.btn_discord, "speech", "on_accent")
        self.btn_discord.setObjectName("primary")
        self.btn_discord.setToolTip(_("The Discord settings that stop it chopping up your "
                                      "sounds, and a check that listens to what Discord does"))
        self.btn_discord.clicked.connect(lambda: self.show_guide("discord"))
        cl.addWidget(self.btn_discord, 0, Qt.AlignLeft)
        self.games_label = _label(_("Playing a game or on a call?"), "font-size:10pt;")
        self.games_label.setObjectName("muted")
        cl.addWidget(self.games_label)
        games = QHBoxLayout()
        games.setSpacing(10)
        self.btn_steam = QPushButton(_("Steam games"))
        icons.set_icon(self.btn_steam, "gamepad")
        self.btn_steam.setToolTip(_("CS2, Dota 2, Deadlock… games that use Steam voice chat "
                                    "take the mic from Steam's own settings"))
        self.btn_steam.clicked.connect(self.show_steam_guide)
        games.addWidget(self.btn_steam)
        self.btn_game = QPushButton(_("Other games"))
        icons.set_icon(self.btn_game, "gamepad")
        self.btn_game.setToolTip(_("Valorant, Fortnite, Apex, Rust… the voice chat settings that "
                                   "matter"))
        self.btn_game.clicked.connect(lambda: self.show_guide("game"))
        games.addWidget(self.btn_game)
        self.btn_meeting = QPushButton(_("Zoom, Teams, browser"))
        icons.set_icon(self.btn_meeting, "browser")
        self.btn_meeting.setToolTip(_("Calls in Zoom, Microsoft Teams or a web page (Google "
                                      "Meet): the settings that matter"))
        self.btn_meeting.clicked.connect(lambda: self.show_guide("meeting"))
        games.addWidget(self.btn_meeting)
        games.addStretch(1)
        cl.addLayout(games)
        v.addWidget(self.help_card)
        v.addStretch(1)
        v.addWidget(_label(_("That's it. Add sounds by dragging files onto the window, then "
                             "click one to play it. You can open this guide again any time "
                             "from the <b>Setup</b> tab (<b>Step-by-step guide</b>)."),
                           "font-size:10pt;"))
        return p

    # ------------------------------------------------------------------ navigation
    def go(self, i: int):
        i = max(0, min(self.PAGES - 1, i))
        if i != 2 and self.setup_show.on:
            self.setup_show._stop()
        self.stack.setCurrentIndex(i)
        self.progress.setText(_("Step {step} of {pages}", step=i + 1, pages=self.PAGES))
        self.btn_back.setVisible(i > 0)
        self.timer.setInterval(TICK_MS if i == 0 else SLOW_TICK_MS)
        if i == 2:
            self.cable_status.setText(_("Checking…"))
            self.cable_status.repaint()   # the check can take a moment (it may reopen devices)
            self.recheck_cable(rescan=False)
        elif i == 3:
            self._fill_discord()
        self._update_next()

    def _update_next(self):
        i = self.stack.currentIndex()
        # while the cable installs, stay on its page: leaving it (or finishing) would
        # lose track of the installer (a mic set-up is the main window's: it reports
        # back through mic_attached wherever the guide is)
        # (greyed out with set_busy, not setEnabled: that would throw the keyboard focus
        # to another control; the click handlers check too, for Enter on the dialog)
        installing = self._proc is not None
        busy.set_busy(self.btn_next, installing)
        busy.set_busy(self.btn_back, installing)
        if i == self.PAGES - 1:
            self.btn_next.setText(_("Finish  ✓"))
        elif i == 2 and not self.route_ok():
            self.btn_next.setText(_("Skip for now  →"))
        else:
            self.btn_next.setText(_("Next  →"))

    def back_clicked(self):
        if self._proc is None:
            self.go(self.stack.currentIndex() - 1)

    def next_clicked(self):
        if self._proc is not None:
            return   # the cable is installing: stay on its page
        i = self.stack.currentIndex()
        if i == self.PAGES - 1:
            self.finish()
        else:
            self.go(i + 1)

    def finish(self):
        cfg = self.win.cfg
        cfg.setup_done = self.route_ok()   # without the cable, offer the guide again next time
        cfg.mic_enabled = self.chk_send.isChecked()
        self.win.chk_mic.setChecked(cfg.mic_enabled)
        cfg.save()
        self.win._init_devices()   # refresh the window's device boxes from the choices
        self.accept()

    def reject(self):
        """Esc / the window's X. Mid-install, check first: the install carries on
        either way, and reopening the guide picks it back up."""
        if self._proc is not None and self._proc.poll() is None and QMessageBox.question(
                self, _("Still installing"),
                _("Bun is still installing the virtual cable.\n\nClose the guide anyway? The "
                  "install carries on by itself; open the guide again from the Setup tab "
                  "(Step-by-step guide) to see how it went.")) \
                != QMessageBox.StandardButton.Yes:
            return
        super().reject()

    def done(self, r):
        self.timer.stop()
        if self.setup_show.on:
            self.setup_show._stop()
        if r != QDialog.Accepted:
            for k, v in self._saved_devices.items():   # keep what they had, unless
                if k not in self._user_picked:         # they picked another one here
                    setattr(self.win.cfg, k, v)
            # closed on purpose: don't open it again every launch (the Setup tab's
            # Step-by-step guide still opens it)
            self.win.cfg.setup_done = True
            self.win.cfg.save()
            self.win._init_devices()
        super().done(r)

    # ------------------------------------------------------------------ actions
    def _pick_mic(self, name: str, by_user: bool = False):
        if by_user:
            self._user_picked.add("mic_device")
        self.win.cfg.mic_device = name
        self.win.engine.set_mic_device(name)
        self._mic_peak_seen = False

    def _pick_headphones(self, name: str, by_user: bool = False):
        if by_user:
            self._user_picked.add("mon_device")
        self.win.cfg.mon_device = name
        self.win.engine.set_mon_device(name)

    def _flash_hint(self, text: str, ms: int):
        self.test_hint.setText(text)
        self._hint_serial = getattr(self, "_hint_serial", 0) + 1
        serial = self._hint_serial
        QTimer.singleShot(ms, lambda: serial == self._hint_serial
                          and self.test_hint.setText(f"<b>{_test_title()}</b>"))

    def test_sound(self):
        if self.win.engine.mon_stream is None:
            self._flash_hint(_("<b>No headphones open</b>, pick another above."), 3500)
            return
        self.win.engine.play("__setup__", test_tune(), 1.0, preview=True)
        self.bun_phones.burst()
        self._flash_hint(_("<b>Playing… hear it?</b>"), 1500)

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
            return (self.win._main_name() is not None
                    and "main" not in self.win.engine.errors_snapshot())
        return self.cable_ok()

    def _mic_attached(self, mic: str, err: str):
        if self.setup_show.on:
            self.setup_show.finish(not bool(err))
        self.recheck_cable(rescan=False)

    def recheck_cable(self, rescan: bool = True):
        if rescan:
            self.win.refresh_devices()   # picks up a driver installed while we're open
        self.btn_restart.hide()
        busy = self._proc is not None
        self.cable_bar.setVisible(busy)
        self.cable_steps.setVisible(busy)
        if not busy and self.bun_cable.building:
            self.bun_cable.stop_building(self.cable_ok())
        route = self.win.cfg.route
        # (straight into the mic has its own "...instead" button, below)
        self.btn_use_cable.setVisible(not busy and route not in ("cable", "mic"))
        self.btn_cable.setToolTip(_("Use a free virtual cable instead: you pick it as the mic "
                                    "in Discord and games") if route == "mic" else "")
        self.btn_other.setVisible(not busy and self.other_box.isHidden())
        attaching = self.win._attaching
        self.btn_attach.setVisible(not busy and not (route == "mic" and self.route_ok())
                                   and not self.setup_show.on)
        self.btn_attach.setEnabled(not attaching)
        state = directmic.status(self.win.cfg.mic_device)
        # another way already works (the cable, a device): the mic is then an option in
        # the row below, not the big button that looked like it had to be set up again
        other_works = route != "mic" and not attaching and self.route_ok()
        if other_works:
            self.btn_attach.hide()
        self.btn_mic_instead.setVisible(other_works and not busy and not self.setup_show.on)
        self.btn_attach.setText(_("Setting up… click Yes when Windows asks") if attaching
                                else _("Repair (one click)") if directmic.needs_repair(state)
                                else _("Put my sounds straight into my mic"))
        if self.setup_show.on and not attaching:
            # the show is the mic's: a working cable doesn't make a failed mic set-up a win
            self.setup_show.finish(route == "mic" and self.route_ok())
        if route == "mic" and not busy and not self._cable_tries and not self._needs_restart:
            self.other_box.hide()
            if self.setup_show.on:
                self.cable_status.setText(
                    _("<b style='color:{colour}'>✓ On your mic.</b> Discord and games hear "
                      "your sounds through it, press Next.", colour=_ok()) if self.route_ok()
                    else _("Setting up… click Yes when Windows asks") if attaching
                    else _("Setting up…"))
                self.btn_cable.hide()
                self.btn_recheck.hide()
                self.btn_other.hide()
                self._update_next()
                return
            if self.route_ok():
                self.cable_status.setText(_("<b style='color:{colour}'>✓ On your mic.</b> "
                                            "Discord and games hear your sounds through it, "
                                            "press Next.", colour=_ok()))
            elif directmic.needs_repair(state):
                self.cable_status.setText(_("Onion Board was on your mic but needs a quick "
                                            "repair: <b>one click</b>, and Windows asks for "
                                            "permission once."))
            else:
                self.cable_status.setText(_("Windows asks for permission once, and your PC's "
                                            "sound drops out for a second."))
            self.btn_cable.setText(_("Virtual cable instead"))
            self.btn_cable.show()
            self.btn_recheck.hide()
            self._update_next()
            return
        if busy:
            self.cable_status.setText(_("<b>Bun is setting it up for you…</b>"))
            self.cable_steps.setText(self._steps_html())
            self.btn_cable.hide()
            self.btn_recheck.hide()
            self.other_box.hide()
        elif route != "cable":
            if self.other_box.isHidden():
                self._show_other(True)
            dev = self.win._main_name()
            if route == "off":
                self.cable_status.setText(_("<b style='color:{colour}'>✓ Sending nowhere.</b> "
                                            "Only you hear your sounds (and a device set to "
                                            "Clean, for streaming under Also send to).",
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
            self.win.engine.set_main_device(self.win._main_name())
            # both ends of the cable on 48 kHz: it then passes the sound through as is
            self.win._check_cable_format()
            if self.win.cable_bad:
                self.win.fix_cable_format(quiet=True)
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
            self.cable_status.setText(_("<b style='color:{colour}'>✓ Installed.</b> Windows "
                                        "needs a <b>restart</b> to finish setting it up. Restart "
                                        "whenever suits you: Onion Board will open by itself "
                                        "afterwards and pick up right here.", colour=_ok()))
            self.btn_cable.setText(_("Try once more without restarting"))
            self.btn_cable.setVisible(not self._needs_restart)   # it just tried that
            self.btn_recheck.show()
            self.btn_restart.show()
        elif self._cable_tries:
            self.cable_status.setText(_("<b style='color:{colour}'>That didn't work.</b> If "
                                        "Windows asked for permission, click <b>Yes</b> this "
                                        "time. If it still won't install, restarting your PC "
                                        "often helps.", colour=_bad()))
            self.btn_cable.setText(_cable_text(_("⬇  Try installing again")))
            self.btn_cable.show()
            self.btn_recheck.show()
        elif self._resumed:   # back from the restart, and it still isn't there
            self.cable_status.setText(_("<b style='color:{colour}'>It still isn't showing up after "
                                        "the restart.</b> Install it again below; if Windows "
                                        "asks for permission, click <b>Yes</b>.", colour=_bad()))
            self.btn_cable.setText(_cable_text(_("⬇  Try installing again")))
            self.btn_cable.show()
            self.btn_recheck.show()
        else:
            self.cable_status.setText(_("<b style='color:{colour}'>Not installed yet.</b> Without "
                                        "it, only you can hear your sounds. Or put them straight "
                                        "into your mic: nothing to install.", colour=_bad()))
            self.btn_cable.setText(_cable_text(_("⬇  Install it now (free)")))
            self.btn_cable.show()
            self.btn_recheck.hide()
        # switched off in Settings > Privacy & security: the installer's download
        # (PowerShell, from vb-audio.com) can't go through the app's connection
        allowed = net.allowed("setup_downloads")
        self.btn_cable.setEnabled(allowed)
        self.btn_cable.setToolTip("" if allowed else net.off_message("setup_downloads"))
        if not allowed and not self.btn_cable.isHidden():
            self.btn_recheck.show()   # for after installing it by hand
            if net.offline():   # Offline mode: no dead button, and the way that works
                self.btn_cable.hide()
                self.cable_status.setText(_(
                    "<b style='color:{colour}'>Not installed.</b> Offline mode is on, so it "
                    "can't be downloaded here. Put your sounds straight into your mic "
                    "instead: nothing to install.", colour=_bad()))
        self._update_next()

    def attach_mic(self):
        self.setup_show.start()
        self.win.attach_mic()
        self.recheck_cable(rescan=False)

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
            self.win.set_route("cable")
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

    def _fill_discord(self):
        self.discord_tip.setText("")
        self._fill_discord_text()
        self.discord_tip.setVisible(bool(self.discord_tip.text()))
        games = not self.btn_steam.isHidden()
        self.games_label.setVisible(games)
        self.help_card.setVisible(games or not self.btn_discord.isHidden())

    def _fill_discord_text(self):
        cfg = self.win.cfg
        dev = self.win._main_name()
        name = eng.virtual_mic_for(dev)
        self._vm = name or dev or "CABLE Output"
        for b in (self.btn_steam, self.btn_game, self.btn_meeting,   # mic settings: not
                  self.btn_nomic):
            b.setVisible(bool(name) or cfg.route == "cable")      # without a mic end to pick
        if cfg.route == "mic":
            self._fill_direct()
            return
        self.discord_title.setText(
            _("Last step: nothing to tell") if cfg.route == "off" else
            _("Last step: pick it up where it arrives") if cfg.route == "device" and dev
            and not name else _("Last step: tell Discord or your game"))
        if cfg.route == "off":
            self.discord_text.setText(
                _("Your sounds play only for you: in your headphones, where OBS's <b>Desktop "
                  "Audio</b> picks them up, and on a device set to <b>Clean, for streaming</b> "
                  "(Setup → Devices → Also send to).<br><br>Nothing to change in Discord or "
                  "your game. To send your sounds to them later, go to the Setup tab → Devices → "
                  "<b>Send my sounds to</b> → <b>My mic</b>."))
            self.btn_copy.hide()
            self.btn_discord.hide()
            return
        if cfg.route == "device" and dev and not name:
            self.btn_copy.show()
            self.btn_discord.hide()
            self.discord_text.setText(
                _("Onion Board sends your sounds (and your voice, if you send it) to:<p "
                  "style='font-size:15pt; font-weight:800; color:{colour}'>{device}</p><b>In "
                  "OBS:</b> Sources → + → <b>Audio Output Capture</b> → pick it. <b>In "
                  "Voicemeeter or a mixer:</b> send that input on to wherever it should go "
                  "(Discord, your stream, a recording).", colour=_ok(), device=html.escape(dev)))
            return
        if not name:
            self.discord_text.setText(
                _("<span style='color:{colour}'>The virtual cable isn't set up yet, so only you "
                  "will hear your sounds.</span> Go <b>Back</b> to install it (or pick another "
                  "device there), or finish now and this guide will open again next time.",
                  colour=_bad()))
            self.btn_copy.hide()
            self.btn_discord.hide()
            return
        self.btn_copy.show()
        self.btn_discord.show()
        esc = html.escape(name)
        self.discord_text.setText(
            _("Onion Board now sends your voice and sounds into a new microphone called:<p "
              "style='font-size:15pt; font-weight:800; color:{colour}'>{device}</p><b>In "
              "Discord:</b> click the ⚙ gear (User Settings) → <b>Voice &amp; Video</b> → "
              "<b>Input Device</b> → choose <b>{device}</b>, and set <b>Input Profile</b> to "
              "<b>Studio</b>. Left on, Discord's noise suppression treats your sounds as "
              "background noise and chops them up.<br><br><b>In a game:</b> open its audio / "
              "voice chat settings, set the microphone to <b>{device}</b> and turn off its "
              "noise suppression.", colour=_ok(), device=esc))

    def _fill_direct(self):
        """Straight into my mic: Discord and games keep the mic they have."""
        cfg = self.win.cfg
        self.btn_copy.hide()
        if not directmic.works(directmic.status(cfg.mic_device)):
            self.discord_title.setText(_("Last step: tell Discord or your game"))
            self.discord_text.setText(
                _("<span style='color:{colour}'>Onion Board isn't on your mic yet, so only "
                  "you will hear your sounds.</span> Go <b>Back</b> and click <b>Put my sounds "
                  "straight into my mic</b> (or use the virtual cable), or finish now and this "
                  "guide will open again next time.", colour=_bad()))
            self.btn_discord.hide()
            return
        self.discord_title.setText(_("Last step: nothing to pick"))
        self.btn_discord.show()
        mic = html.escape(cfg.mic_device or _("your mic"))
        self.discord_text.setText(
            _("Discord and your games keep using the mic they already have:<p "
              "style='font-size:15pt; font-weight:800; color:{colour}'>{mic}</p>Your sounds "
              "are in it now, so there's nothing to pick anywhere.<br><br><b>One thing worth "
              "doing in Discord:</b> ⚙ User Settings → <b>Voice &amp; Video</b> → <b>Input "
              "Profile</b> → <b>Custom</b>, <b>Noise Suppression</b> → <b>None</b>, and "
              "<b>Echo Cancellation</b> off (not Studio: Studio skips Onion Board). Left on, "
              "its noise suppression treats your sounds as background noise and wipes them "
              "out. <b>In a game:</b> turn off its noise suppression if your sounds cut out.",
              colour=_ok(), mic=mic))
        # the Discord part sits in the card with its button (split after translating)
        intro, sep, tip = self.discord_text.text().partition("<br><br>")
        if sep:
            self.discord_text.setText(intro)
            self.discord_tip.setText(tip)

    def show_steam_guide(self):
        self.show_guide("steam")

    def show_guide(self, which: str):
        from soundboard.ui.chatguide import show_guide
        show_guide(which, self, self.win, self._vm)

    def copy_name(self):
        QApplication.clipboard().setText(self._vm)
        busy.flash(self.btn_copy, _("✓  Copied"))

    def _tick(self):
        if self.stack.currentIndex() == 0:   # the mic page: its meter and Bun
            e = self.win.engine
            lvl = e.level_mic if e.mic_stream is not None else 0.0
            self.mic_meter.set_level(lvl)
            self.bun_mic.set_level(lvl)
            if lvl > TALK:
                self._mic_peak_seen = True
            if e.mic_stream is None and self._no_mics:
                self.mic_heard.setText(_("<span style='color:{colour}'>No microphone was "
                                         "found.</span> Plug one in, then open this guide again "
                                         "from the Setup tab, or press Next to carry on without "
                                         "one.", colour=_bad()))
            elif e.mic_stream is None:
                self.mic_heard.setText(_("<span style='color:{colour}'>Couldn't open that "
                                         "mic, try another one.</span>", colour=_bad()))
            elif self._mic_peak_seen:
                self.mic_heard.setText(_("<b style='color:{colour}'>✓ Hearing you!</b>",
                                         colour=_ok()))
            else:
                self.mic_heard.setText(_("Waiting to hear you… if the bar doesn't move, pick "
                                         "another mic."))
        if self._proc is not None:
            self._read_cable_step()
            if (rc := self._proc.poll()) is not None:
                global _installer
                if _installer is self._proc:
                    _installer = None
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
        fit.watch(self)   # grows to fit its text (ui/fit.py)
        self.setWindowTitle(_("Steam games: set your mic"))
        self.setMinimumWidth(600)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 18)
        v.setSpacing(12)
        v.addLayout(_header(_("Steam games"), _label(_(
            "Games that use <b>Steam's voice chat</b> (like <b>Counter-Strike 2</b>, "
            "<b>Dota 2</b> and <b>Deadlock</b>) don't have their own mic setting. "
            "They use the mic you pick <b>in Steam</b>. Do this once:")),
            BunnyWidget("headphones")))
        small = "<br><span style='font-size:9pt'>{}</span>"
        items = [
            _("Open <b>Steam</b>. Click <b>Steam</b> in the top-left corner, then "
              "<b>Settings</b>.")
            + small.format(_("(In a game? Press <b>Shift + Tab</b> and click the ⚙ gear.)")),
            _("On the left, click <b>Voice</b>."),
            _("Click the <b>Voice Input Device</b> box and choose <b style='color:{colour}'>"
              "{mic}</b>.", colour=_ok(), mic=html.escape(mic_name))
            + small.format(_("Not in the list? Close Steam completely (right-click its icon "
                             "by the clock → Exit) and open it again.")),
            _("Under <b>Advanced options</b>, turn <b>OFF</b>: <b>Noise cancellation</b>, "
              "<b>Echo cancellation</b> and <b>Automatic volume/gain control</b>.")
            + small.format(_("They think music is background noise and cut your sounds up. "
                             "Onion Board already cleans up your voice.")),
            _("Click <b>Start microphone test</b> and play a sound in Onion Board. You should "
              "hear it back."),
            _("On the Setup tab, set <b>Who's listening</b> to <b>Advanced</b>, then <b>Steam "
              "voice</b>."),
        ]
        v.addWidget(_label(
            "<ol style='margin-left:-20px'>"
            + "".join(f"<li style='margin-bottom:8px'>{t}</li>" for t in items)
            + "<li>" + _("Restart the game if it was already open.") + "</li></ol>"))
        v.addWidget(_label(_(
            "<b>Push-to-talk tip:</b> if you use push-to-talk in Steam or the game, set "
            "the same key in Onion Board (⚙ Settings → <b>Hotkeys</b> → <b>Auto "
            "push-to-talk</b>). Onion Board will then hold it down for you while a sound "
            "plays."),
            "font-size:10pt;"))
        row = QHBoxLayout()
        copy = QPushButton(_("Copy the mic name"))
        icons.set_icon(copy, "copy")
        copy.clicked.connect(lambda: (QApplication.clipboard().setText(mic_name),
                                      busy.flash(copy, _("✓  Copied"))))
        row.addWidget(copy)
        open_steam = QPushButton(_("Open Steam's voice settings"))
        open_steam.clicked.connect(lambda: self.open_steam(open_steam))
        row.addWidget(open_steam)
        row.addStretch(1)
        ok = QPushButton(_("Done"))
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        v.addLayout(row)

    def open_steam(self, btn=None):
        """steam://settings/voice opens the Voice page when Steam is installed; if it
        isn't, Windows says so and the written steps still apply."""
        busy.open_url("steam://settings/voice", btn, self, opened=_("✓ Opened Steam"),
                      failed=_("Couldn't open Steam: is it installed? Follow the steps "
                               "above instead. The link was"))
