"""Quick setup: the four steps a first-time user goes through, one per page,
in plain words. Shown on the very first launch (and from the Setup tab's
Step-by-step guide button any time after).

  1. Which microphone do you talk into?   (live level bar: "talk, it should move")
  2. Where do you listen?                 (test sound)
  3. Where your sounds go                 (the virtual cable: checks it's there, installs
                                           it if not; or another device / nowhere instead)
  4. Tell Discord / your game / OBS       (the one setting outside the app)

On the very first launch only (Config.use_mode is "" just then), a page before them
asks what the app is for (USES) and switches on the tabs that fit.

Every choice is applied to the engine as it's made, so the level bar and the test
sound use the real devices. The window's own device boxes are refreshed at the end.
"""
from __future__ import annotations

import ctypes
import html
import re
import subprocess
import time

import numpy as np
from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QDialog, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from soundboard import directmic, michelper
from soundboard import engine as eng
from soundboard import theme
from soundboard.engine import SR
from soundboard import library, net, usage
from soundboard.library import RESOURCE_DIR
from soundboard.ui import busy, fit, icons, panel
from soundboard.ui.bunnywidget import TALK, BunnyWidget
from soundboard.ui.setupshow import SetupShow
from soundboard.ui.choicetile import ChoiceTile, FoldPill
from soundboard import errors
from soundboard.i18n import _
from soundboard.ui.pixels import snap_to_pixels

# step 3's "I don't use the cable" list: this choice sends nowhere (Config.route "off")
NOWHERE = _("Nobody: only I hear them")
RESTART_NEEDED = 3010   # install-vbcable.ps1: installed, but Windows must restart first
TICK_MS = 40            # the mic page's meter
SETTLE_MS = 60          # after a step change, the window settles to what the steps need
SLOW_TICK_MS = 250      # the other pages: only the cable installer to keep up with
LOCK_MAX_S = 180        # the mic set-up holds the guide shut at most this long

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


TILE_W = 138                  # a device tile; TILE_COLS of them fill the page's width
TILE_MIN_H = 72               # a tile's least height (as tall as its names need: tile_h)
TILE_COLS, TILE_GAP = 4, 12
CONTENT_W = TILE_COLS * TILE_W + (TILE_COLS - 1) * TILE_GAP   # a page's width: one row
MARGIN = 24                   # the dialog's sides: the step bar, pages and Back / Next
HEADER_GAP = 20               # every step: between the title + words and what's below
SECTION_GAP = 16              # between a step's parts (a card, a list, the footer line)
# Bun beside each step's title, top-aligned with it and no taller than the title and
# two lines of words: the header ends where its text does, so the gap under every
# step's words is HEADER_GAP and nothing more (a taller Bun left a band under them)
BUN_H, BUN_PAD = 74, 5
TITLE_CSS = "font-size:17pt; font-weight:800;"   # DESIGN.md Standard kit: Display
BODY_CSS = "font-size:11pt;"                      # ... Large (a full-page guide's body)


class StepBar(QWidget):
    """Where you are in the guide: one short bar per step, the ones done and the
    current one in the accent colour (painted, so it follows the theme)."""
    SEG_W, SEG_H, GAP = 28, 4, 4

    def __init__(self, steps: int):
        super().__init__()
        self.steps, self.current = steps, 0
        self.setFixedSize(steps * self.SEG_W + (steps - 1) * self.GAP, self.SEG_H)

    def set_step(self, i: int):
        self.current = i
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        t = theme.T
        for i in range(self.steps):
            p.setBrush(QColor(t["accent"] if i <= self.current else t["card_hi"]))
            p.drawRoundedRect(QRectF(i * (self.SEG_W + self.GAP), 0, self.SEG_W, self.SEG_H),
                              2, 2)


def uses() -> tuple[tuple[str, str, str, str], ...]:
    """The first page's answers to "What's it for?": (key, icon, title, what it adds).
    A function, not a constant: the words follow the language picked at start-up."""
    return (("normal", "volume", _("Just sounds"),
             _("Play sounds in Discord and games. Nothing else to learn.")),
            ("streamer", "live", _("Streaming"),
             _("Adds the <b>Apps</b> tab (send music or a game to your stream). The last step "
               "links the <b>Streamer guide</b> (Stream Deck keys, chat commands).")),
            ("games", "gamepad", _("Competitive games"),
             _("Adds the <b>Triggers</b> tab: Onion Watch plays a sound when something "
               "shows up on your screen (a kill, \u201cYOU DIED\u201d).")),
            ("all", "star", _("Show me everything"),
             _("Every tab: <b>Radio</b>, <b>Apps</b> and <b>Triggers</b> too.")))


# the tabs each answer switches on (the rest stay as they are: a plain soundboard)
USE_TABS = {"streamer": ("apps",), "games": ("triggers",),
            "all": ("radio", "apps", "triggers")}


def apply_use(win, use: str):
    """Switch on the tabs that fit what the app is for (Settings > Tabs can undo it)."""
    for key in USE_TABS.get(use, ()):
        win.set_tab_on(key, True)


def _ok() -> str:    # status colours readable on the current theme (theme.status)
    return theme.status("ok")


def _bad() -> str:
    return theme.status("warn")


def _nav_words(text: str) -> str:
    """Back / Next's words without their text arrow or tick: the buttons carry painted
    ones (a font's arrow glyph is a hairline next to the bold words)."""
    return re.sub(r"[←→✓]", "", text).strip()


NAV_GAP = " "   # a thin space (U+2009) between Back / Next's words and their arrow


def _cable_text(text: str) -> str:
    """A cable button's words without their ⬇ (the button has the cable picture)."""
    return text.replace("⬇", "").strip()


def _test_title() -> str:
    return _("Play a test sound")


# the generic first words of Windows' device names ("Microphone (Product)"), English
# and a few common Windows languages: only these get split (_split_name)
_KINDS = ("mic", "headphone", "headset", "speaker", "earphone", "line", "cable", "input",
          "output", "digital", "mikrofon", "lautsprecher", "kopfh", "micro", "haut-parleur",
          "casque", "altavoz", "auricular", "altoparlant", "cuffie", "fone")


def _split_name(name: str) -> tuple[str, str]:
    """A tile's words for a device: Windows names most of them "Kind (Product)", so
    "Microphone (Logitech G733 Gaming Headset)" shows the product big and "Microphone"
    small under it. Short brackets ("Headset Mic (USB)") and names whose first part
    isn't a kind ("LG ULTRAGEAR (NVIDIA High Definition Audio)") stay whole."""
    m = re.match(r"^([^()]+?)\s*\((.{6,})\)$", name)
    if m and any(k in m.group(1).lower() for k in _KINDS):
        return m.group(2), m.group(1)
    return "", ""


def _choice_icon(name: str, kind: str) -> str:
    """A device's picture in the pick lists: a mic, headphones or a speaker."""
    if kind == "input":
        return "mic"
    low = name.lower()
    return "headphones" if any(w in low for w in ("headphone", "headset", "earbud",
                                                 "airpods", "buds")) else "volume"


def tile_h(tiles: list[ChoiceTile]) -> int:
    """One height for a list's tiles: what the tallest name needs (at least
    TILE_MIN_H), set on each of them."""
    h = max([TILE_MIN_H, *(t.needed_height() for t in tiles)])
    for t in tiles:
        t.setFixedHeight(h)
    return h


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
    lbl.setTextFormat(Qt.TextFormat.RichText)
    lbl.setStyleSheet(css)
    return lbl


def _header(title: str | QLabel, body: QLabel, bun: BunnyWidget) -> QHBoxLayout:
    """A page's title and intro, with Bun (holding something that fits the page)
    beside both, top-aligned with the title. He's no taller than the words, so the
    header ends where they do (BUN_H)."""
    row = QHBoxLayout()
    row.setSpacing(16)
    col = QVBoxLayout()
    col.setSpacing(10)
    col.addWidget(_label(title, TITLE_CSS) if isinstance(title, str) else title)
    col.addWidget(body)
    col.addStretch(1)
    row.addLayout(col, 1)
    row.addWidget(bun, 0, Qt.AlignmentFlag.AlignTop)
    return row


class _RoundButton(QPushButton):
    """A round accent button showing just its icon (the test sound's speaker). Painted
    by hand: the theme's button rules square off a style-sheet circle."""

    def __init__(self, size: int):
        super().__init__()
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, ev):
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = theme.T
        col = QColor(t["accent_hover"] if self.underMouse() or self.isDown() else t["accent"])
        if self.isDown():
            col = col.darker(115)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(t["text"]), 2) if self.hasFocus() else Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawEllipse(r)
        s = self.iconSize()
        pm = self.icon().pixmap(s, self.devicePixelRatioF())
        p.drawPixmap(round((self.width() - s.width()) / 2),
                     round((self.height() - s.height()) / 2), pm)


class _PageStack(QWidget):
    """The steps, one shown at a time, sized by the one showing: a QStackedWidget
    measures itself by its tallest page (its layout asks every page), so a short step
    sat above an empty band. Here the others are hidden, and a hidden widget takes no
    room (DESIGN.md: a multi-step dialog shrinks to the current page). The calls the
    guide uses are QStackedWidget's."""
    currentChanged = Signal(int)

    def __init__(self):
        super().__init__()
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._pages: list[QWidget] = []
        self._current = -1

    def addWidget(self, page: QWidget) -> int:
        self._pages.append(page)
        self._lay.addWidget(page)
        if self._current < 0:
            self._current = 0
        else:
            page.hide()
        return len(self._pages) - 1

    def count(self) -> int:
        return len(self._pages)

    def widget(self, i: int) -> QWidget | None:
        return self._pages[i] if 0 <= i < len(self._pages) else None

    def currentIndex(self) -> int:
        return self._current

    def currentWidget(self) -> QWidget | None:
        return self.widget(self._current)

    def setCurrentIndex(self, i: int):
        if not 0 <= i < len(self._pages) or i == self._current:
            return
        old, self._current = self.currentWidget(), i
        # the old one goes first: with both shown for a moment, Qt grew the window to
        # fit the two (to the screen's height, moved up) before it shrank back
        if old is not None:
            old.hide()
        self._pages[i].show()
        self.currentChanged.emit(i)


class StatusCard(QFrame):
    """Step 3's answer to "is it working?": a round badge (a tick, a ! or dots), an
    optional bold line, the status words and a pill, on a card tinted with the
    state's colour ("ok", "warn", "busy" or "" for not set up). Before, a green
    "On your mic." at the start of a sentence was all there was."""
    BADGE = 32

    def __init__(self, text: QLabel):
        super().__init__()
        self.tone = ""
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 12, 14, 14)
        h.setSpacing(12)
        self._badge = QWidget()   # painted by the card (paintEvent)
        self._badge.setFixedSize(self.BADGE, self.BADGE)
        self._badge.setStyleSheet("background:transparent;")
        h.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(4)
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-size:11pt; font-weight:700;")   # Standard kit: Large
        col.addWidget(self.title)
        col.addWidget(text)
        self.action_box = QVBoxLayout()   # a button that belongs to the state (Repair...)
        self.action_box.setContentsMargins(0, 4, 0, 0)
        col.addLayout(self.action_box)
        h.addLayout(col, 1)
        self.pill = QLabel()
        h.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignTop)

    def _colour(self) -> QColor:
        t = theme.T
        return QColor({"ok": t["ok_text"], "warn": t["warn_text"],
                       "busy": t["accent"]}.get(self.tone, t["muted"]))

    def set_state(self, tone: str, pill: str, title: str = ""):
        self.tone = tone
        self.title.setText(title)
        self.title.setVisible(bool(title))
        c = self._colour()
        self.pill.setText(pill)
        self.pill.setVisible(bool(pill))
        self.pill.setStyleSheet(
            f"background:rgba({c.red()},{c.green()},{c.blue()},45); color:{c.name()}; "
            "border-radius:10px; padding:3px 10px; font-size:8pt; font-weight:600;")
        self.update()

    def paintEvent(self, ev):
        t = theme.T
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        r = QRectF(self.rect())
        p.setBrush(QColor(t["panel"]))
        p.drawRoundedRect(r, 12, 12)
        c = self._colour()
        tint = QColor(c)
        tint.setAlpha(28 if self.tone else 0)
        p.setBrush(tint)
        p.drawRoundedRect(r, 12, 12)
        b = QRectF(self._badge.geometry())
        p.setBrush(c)
        p.drawEllipse(b)
        pen = QPen(QColor(t["on_accent"] if self.tone == "busy" else t["bg"]), 2.6,
                   Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        cx, cy = b.center().x(), b.center().y()
        if self.tone == "ok":
            p.drawPolyline([QPointF(cx - 6, cy), QPointF(cx - 1.5, cy + 4.5),
                            QPointF(cx + 6.5, cy - 4.5)])
        elif self.tone == "warn":
            p.drawLine(QPointF(cx, cy - 7), QPointF(cx, cy + 2))
            p.drawPoint(QPointF(cx, cy + 6.5))
        else:   # setting up / not yet: three dots
            for dx in (-6, 0, 6):
                p.drawPoint(QPointF(cx + dx, cy))


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
        # as wide as a row of tiles plus the margins: the tiles' right edge lines up
        # with Next's (DESIGN.md: everything on the same edges)
        self.setMinimumWidth(CONTENT_W + 2 * MARGIN)   # (the height follows each step)
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
        self._chose_cable = False   # "Virtual cable instead" clicked here
        # the first launch only: a "What's it for?" page goes before the mic, and the
        # device pages move up one (self.base)
        self._ask_use = win.cfg.use_mode == ""
        self._use = "normal"
        self.base = 1 if self._ask_use else 0
        self.PAGES = SetupWizard.PAGES + self.base

        v = QVBoxLayout(self)
        v.setContentsMargins(MARGIN, 18, MARGIN, 18)
        v.setSpacing(12)
        top = QHBoxLayout()   # the step bar, then "Step 2 of 5"
        top.setSpacing(12)
        self.step_bar = StepBar(self.PAGES)
        top.addWidget(self.step_bar, 0, Qt.AlignmentFlag.AlignVCenter)
        self.progress = QLabel()
        self.progress.setObjectName("hint")
        top.addWidget(self.progress)
        top.addStretch(1)
        v.addLayout(top)
        self.stack = _PageStack()
        v.addWidget(self.stack, 1)
        if self._ask_use:
            self.stack.addWidget(self._page_use())
        self.stack.addWidget(self._page_mic())
        self.stack.addWidget(self._page_headphones())
        self.stack.addWidget(self._page_cable())
        self.stack.addWidget(self._page_discord())
        for i in range(self.stack.count()):   # the pages' edges are the dialog's: their
            page = self.stack.widget(i)          # cards line up with Back / Next
            if page is not None and (lay := page.layout()) is not None:
                lay.setContentsMargins(0, 0, 0, 0)
        # fill the last page's text now (its pill and card show from the start)
        self._fill_discord()

        nav = QHBoxLayout()
        self.btn_back = QPushButton(NAV_GAP + _nav_words(_("←  Back")))
        rtl = QApplication.isRightToLeft()
        icons.set_icon(self.btn_back, "nav_next" if rtl else "nav_back")   # painted: bolder
        self.btn_back.clicked.connect(self.back_clicked)
        nav.addWidget(self.btn_back)
        nav.addStretch(1)
        self.btn_next = QPushButton(_nav_words(_("Next  →")))
        self.btn_next.setObjectName("primary")
        # the arrow after the words, on the reading side's end
        self.btn_next.setLayoutDirection(Qt.LayoutDirection.LeftToRight if rtl
                                         else Qt.LayoutDirection.RightToLeft)
        self.btn_next.clicked.connect(self.next_clicked)
        self.btn_next.setDefault(True)   # Enter moves on (not "Play a test sound")
        nav.addWidget(self.btn_next)
        for b in (self.btn_back, self.btn_next):   # a full-page guide's way through
            b.setProperty("guide", True)
            b.setIconSize(QSize(20, 20))
        v.addLayout(nav)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(TICK_MS)
        if self._proc is not None:   # still installing from a guide closed mid-way
            self.bun_cable.build()
        if win._attaching:
            self.setup_show.start()
        self.go(self.base + 2 if resumed or self._proc is not None or win._attaching else 0)

    # ------------------------------------------------------------------ pages
    def _choice_list(self, names: list[str], current: str | None,
                     on_pick, kind: str = "output") -> tuple[QWidget, QButtonGroup]:
        """The devices as tiles in a grid (TILE_COLS across), each with its picture;
        the picked one is filled, ringed and ticked. Every tile is as tall as the
        longest name needs (tile_h), so short names don't float in a tall tile. More
        than two rows scroll."""
        box = QWidget()
        grid = QGridLayout(box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(TILE_GAP)
        group = QButtonGroup(box)
        tiles = []
        for i, n in enumerate(names):
            title, sub = _split_name(n)
            tile = ChoiceTile(n, "stop" if n == NOWHERE else _choice_icon(n, kind),
                              TILE_W, TILE_MIN_H, title=title, sub=sub)
            tile.meter = kind == "input"   # the picked mic shows your voice's level
            tiles.append(tile)
            tile.setToolTip(n)
            tile.setProperty("device", n)
            group.addButton(tile)
            grid.addWidget(tile, i // TILE_COLS, i % TILE_COLS)
            if n == current:
                tile.setChecked(True)
        if not names:
            grid.addWidget(_label(_("<span style='color:{colour}'>None found. Plug it in, close "
                                    "this, then press <b>Step-by-step guide</b> on the Setup "
                                    "tab.</span>", colour=_bad())), 0, 0, 1, TILE_COLS)
        h = tile_h(tiles)
        grid.setColumnStretch(TILE_COLS, 1)   # tiles keep their size; room goes to the end
        group.buttonClicked.connect(lambda b: on_pick(b.property("device")))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(box)
        rows = min(2, max(1, -(-len(names) // TILE_COLS)))
        scroll.setFixedHeight(rows * h + (rows - 1) * TILE_GAP if names else h)
        return scroll, group

    def _page_use(self) -> QWidget:
        """First launch only: what the app is for. Each answer switches on the tabs
        that fit (USE_TABS) when they press Next; the words under the tiles say what."""
        p = QWidget()
        v = QVBoxLayout(p)
        v.addLayout(_header(_("What will you use Onion Board for?"),
                            _label(_("Pick the closest one. It only decides which tabs you "
                                     "start with: change it any time in <b>Settings</b> "
                                     "→ <b>Tabs</b>.")),
                            BunnyWidget("star", height=BUN_H, pad=BUN_PAD)))
        box = QWidget()
        grid = QGridLayout(box)   # one row, like the device tiles
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(TILE_GAP)
        self.use_group = QButtonGroup(box)
        self.use_buttons: dict[str, ChoiceTile] = {}
        self._use_words: dict[str, str] = {}
        for i, (key, icon, title, words) in enumerate(uses()):
            rb = ChoiceTile(title, icon, TILE_W, TILE_MIN_H)
            rb.setProperty("use", key)
            rb.setChecked(key == self._use)
            self.use_group.addButton(rb)
            grid.addWidget(rb, 0, i)
            self.use_buttons[key] = rb
            self._use_words[key] = words
        tile_h(list(self.use_buttons.values()))
        grid.setColumnStretch(len(uses()), 1)
        v.addSpacing(HEADER_GAP)
        v.addWidget(box)
        v.addSpacing(12)
        card, cl = _card(14, 8, roomy=False)
        # every answer's words sit hidden in the same spot, keeping their room: the
        # card is always as tall as the longest, so clicking between the tiles
        # doesn't grow and shrink the window (it jumped around when spammed)
        words = QGridLayout()
        words.setContentsMargins(0, 0, 0, 0)
        for text in self._use_words.values():
            ghost = _label(text)
            keep = ghost.sizePolicy()
            keep.setRetainSizeWhenHidden(True)
            ghost.setSizePolicy(keep)
            ghost.hide()
            words.addWidget(ghost, 0, 0)
        self.use_hint = _label("")   # fills that room, its words at the top: a pick
        self.use_hint.setAlignment(Qt.AlignmentFlag.AlignLeading   # never re-lays it out
                                   | Qt.AlignmentFlag.AlignTop)
        words.addWidget(self.use_hint, 0, 0)
        cl.addLayout(words)
        v.addWidget(card)
        v.addStretch(1)
        self.use_group.buttonClicked.connect(lambda b: self._pick_use(b.property("use")))
        self._pick_use(self._use)
        return p

    def _pick_use(self, key: str):
        self._use = key
        self.use_hint.setText(self._use_words[key])

    def _save_use(self):
        """Leaving the "What's it for?" page: remember the answer (so it's never asked
        again, even if the guide is closed later) and add the tabs that fit."""
        cfg = self.win.cfg
        if cfg.use_mode == self._use:
            return
        usage.used(f"use-{self._use}")   # the answer's name only (usage.py)
        cfg.use_mode = self._use
        apply_use(self.win, self._use)
        cfg.save()
        self._fill_discord()   # the streamer guide's button on the last page

    def _page_mic(self) -> QWidget:
        p = QWidget()
        v = QVBoxLayout(p)
        self.bun_mic = BunnyWidget("mic", height=BUN_H, pad=BUN_PAD)
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
        v.addSpacing(HEADER_GAP)
        v.addWidget(lst)   # the picked mic's tile shows your voice's level along its foot
        v.addSpacing(12)
        self.mic_heard = _label("")
        v.addWidget(self.mic_heard)
        self.chk_send = QCheckBox(_("Send my voice too"))
        self.chk_send.setToolTip(_("Send my voice too (untick if you only want your sounds to "
                                   "go out, not your mic)"))
        self.chk_send.setChecked(self.win.cfg.mic_enabled)
        v.addWidget(self.chk_send, 0, Qt.AlignmentFlag.AlignLeft)
        v.addStretch(1)
        self._mic_peak_seen = False
        return p

    def _page_headphones(self) -> QWidget:
        p = QWidget()
        v = QVBoxLayout(p)
        self.bun_phones = BunnyWidget("headphones", height=BUN_H, pad=BUN_PAD)
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
        v.addSpacing(HEADER_GAP)
        v.addWidget(lst)
        v.addSpacing(SECTION_GAP)
        # a round speaker button in a card, with what to do next to it: the page's
        # width, so its edges are the tiles' and Next's (a card as wide as its words
        # ended at a spot nothing else lines up with)
        card, cl = _card(16, roomy=False)
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
        self.test_hint = _label(f"<b>{_test_title()}</b>")
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
        v.insertSpacing(1, HEADER_GAP - SECTION_GAP)
        v.insertWidget(2, self.status_card)
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
        v.addWidget(self._alt_card())
        v.addStretch(1)
        return p

    def _alt_card(self) -> QFrame:
        """Sending into the mic: the other ways, in their own card under it, side by
        side as small tiles (icon, name, why you'd want it, then its button on the
        same edge). Before, their buttons sat right under the green "On your mic" and
        read like a step still to do."""
        self.alt_card, cl = _card(14, 12, roomy=False)
        head = QLabel(_("Optional: other ways to send your sounds"))
        head.setObjectName("section")
        head.setProperty("head", True)
        cl.addWidget(head)
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
            _("If you'd rather not add Onion Board's audio driver to your mic, or a game "
              "skips it: a free virtual cable you pick as the mic in Discord and games."),
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
        v.setSpacing(8)
        self.discord_text = _label("")
        self.discord_title = _label(_("Last step: tell Discord or your game"), TITLE_CSS)
        head = _header(self.discord_title, self.discord_text,
                       BunnyWidget("star", celebrate=True, height=BUN_H, pad=BUN_PAD))
        v.addLayout(head)
        self.helper_row = QWidget()   # (takes no room when both buttons are hidden)
        row = QHBoxLayout(self.helper_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.btn_copy = QPushButton(_("Copy the name"))
        icons.set_icon(self.btn_copy, "copy")
        self.btn_copy.clicked.connect(self.copy_name)
        row.addWidget(self.btn_copy)
        nomic = self.btn_nomic = QPushButton(_("Game has no microphone setting?"))
        icons.set_icon(nomic, "mic")
        nomic.clicked.connect(self.win.open_windows_mic)
        row.addWidget(nomic)
        row.addStretch(1)
        v.addSpacing(HEADER_GAP - 8)
        v.addWidget(self.helper_row)
        # straight into the mic, Discord needs nothing to work: its one tip is a small
        # pill (shut until clicked) that opens a card under it, not a paragraph
        self.discord_fold = FoldPill(_("Discord: one setting worth changing"), "speech")
        self.discord_fold.toggled.connect(self._fold_discord)
        fold_row = QHBoxLayout()
        fold_row.addWidget(self.discord_fold)
        fold_row.addStretch(1)
        v.addLayout(fold_row)
        self._discord_open = False
        self.discord_body, body = _card(14, 8, roomy=False)
        self.discord_tip = _label("", "font-size:10pt;")
        body.addWidget(self.discord_tip)
        self.btn_discord = QPushButton(_("Discord: make my sounds come through clean"))
        icons.set_icon(self.btn_discord, "speech", "on_accent")
        self.btn_discord.setObjectName("primary")
        self.btn_discord.setToolTip(_("The Discord settings that stop it chopping up your "
                                      "sounds, and a check that listens to what Discord does"))
        self.btn_discord.clicked.connect(lambda: self.show_guide("discord"))
        body.addWidget(self.btn_discord, 0, Qt.AlignmentFlag.AlignLeft)
        v.addSpacing(8)
        v.addWidget(self.discord_body)
        # games and calls: their guides, in a card of their own
        self.help_card, cl = _card(14, 8, roomy=False)
        self._fold_discord(False)
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
        # said "Streaming" on the first page: the remote-control guide, right here
        self.btn_streamer = QPushButton(_("Streamer guide"))
        icons.set_icon(self.btn_streamer, "live")
        self.btn_streamer.setToolTip(_("Play sounds from your Stream Deck, channel points and "
                                       "chat commands"))
        self.btn_streamer.clicked.connect(self.show_streamer_guide)
        self.btn_streamer.hide()
        games.addWidget(self.btn_streamer)
        games.addStretch(1)
        cl.addLayout(games)
        v.addWidget(self.help_card)
        v.addStretch(1)
        v.addSpacing(SECTION_GAP - 8)   # the closing words: apart from the cards above
        v.addWidget(_label(_("That's it. Add sounds by dragging files onto the window, then "
                             "click one to play it. You can open this guide again any time "
                             "from the <b>Setup</b> tab (<b>Step-by-step guide</b>)."),
                           "font-size:10pt;"))
        return p

    # ------------------------------------------------------------------ navigation
    def go(self, i: int):
        i = max(0, min(self.PAGES - 1, i))
        if self._ask_use and self.stack.currentIndex() == 0 and i > 0:
            self._save_use()   # leaving "What's it for?"
        page = i - self.base   # 0 mic, 1 headphones, 2 cable, 3 Discord; -1 what it's for
        if page != 2 and self.setup_show.on:
            self.setup_show._stop()
        self.stack.setCurrentIndex(i)
        self.progress.setText(_("Step {step} of {pages}", step=i + 1, pages=self.PAGES))
        self.step_bar.set_step(i)
        self.btn_back.setVisible(i > 0)
        self.timer.setInterval(TICK_MS if page == 0 else SLOW_TICK_MS)
        if page == 2:
            self.cable_status.setText(_("Checking…"))
            self.cable_status.repaint()   # the check can take a moment (it may reopen devices)
            self.recheck_cable(rescan=False)
        elif page == 3:
            self._fill_discord()
        self._update_next()
        # to the new step's size now, before it's drawn: drawn first at the old size,
        # a taller step showed squeezed for a moment
        fit.fit(self)
        self._settle_size()
        QTimer.singleShot(SETTLE_MS, self, self._settle_size)

    def showEvent(self, ev):
        super().showEvent(ev)
        QTimer.singleShot(SETTLE_MS, self, self._settle_size)   # the first step's height

    _settle_due = False

    def event(self, ev):
        # any change to what's shown (a state, a card opening): fit to it again, once
        # things have settled (fit.watch grows the window; this also shrinks it)
        if ev.type() == QEvent.Type.LayoutRequest and not self._settle_due:
            self._settle_due = True
            QTimer.singleShot(SETTLE_MS, self, self._settle_size)
        return super().event(ev)

    def _settle_size(self):
        """To the height this step needs (_PageStack), shrinking too: fit.watch only
        grows the window, so a short step after a tall one kept an empty band, and
        while a step switches Qt can briefly ask for far more room than it needs."""
        self._settle_due = False
        if not self.isVisible():
            return
        need = max(fit.needed_height(self, self.width()), self.minimumHeight())
        if self.height() > need:
            fit.shrink(self, need)

    def _update_next(self):
        i = self.stack.currentIndex()
        # while the cable installs, stay on its page: leaving it (or finishing) would
        # lose track of the installer (a mic set-up is the main window's: it reports
        # back through mic_attached wherever the guide is)
        # (greyed out with set_busy, not setEnabled: that would throw the keyboard focus
        # to another control; the click handlers check too, for Enter on the dialog)
        self._was_locked = self._locked()   # (_tick updates these when that changes)
        installing = self._proc is not None or self._was_locked
        busy.set_busy(self.btn_next, installing)
        busy.set_busy(self.btn_back, installing)
        if i == self.PAGES - 1:
            text, icon = _("Finish  ✓"), "check"
        elif i == self.base + 2 and not self.route_ok():
            text, icon = _("Skip for now  →"), "nav_next"
        else:
            text, icon = _("Next  →"), "nav_next"
        if QApplication.isRightToLeft() and icon == "nav_next":
            icon = "nav_back"   # right to left: on is to the left
        self.btn_next.setText(_nav_words(text) + NAV_GAP)
        icons.set_icon(self.btn_next, icon, "on_accent")

    _lock_since: float | None = None
    _was_locked = False
    _route_was_ok: bool | None = None   # step 3's last answer (_tick)

    def _locked(self) -> bool:
        """Bun is putting the sounds into the mic: the guide stays open on its page
        until it's done (closed or moved on mid-way, they couldn't tell how it went).
        At most LOCK_MAX_S: a set-up that never answers can't trap them."""
        if not self.win._attaching:
            self._lock_since = None
            return False
        if self._lock_since is None:
            self._lock_since = time.monotonic()
        return time.monotonic() - self._lock_since < LOCK_MAX_S

    def _busy(self) -> bool:
        """Back / Next wait: the cable is installing or the mic is being set up."""
        return self._proc is not None or self._locked()

    def back_clicked(self):
        if not self._busy():
            self.go(self.stack.currentIndex() - 1)

    def next_clicked(self):
        if self._busy():
            return   # the cable is installing / the mic is set up: stay on its page
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
        either way, and reopening the guide picks it back up. While the mic is set up,
        they do nothing (_locked)."""
        if self._locked():
            return
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
        if not self.win.cfg.use_mode:   # closed on "What's it for?": asked once is enough
            usage.used("use-skipped")
            self.win.cfg.use_mode = "normal"
            self.win.cfg.save()
        if r != QDialog.DialogCode.Accepted:
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
        self._update_next()

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
        # on the cable, but the mic effect is already on the mic and working: use the mic
        # (the page leads with it) instead of offering to set it up all over again
        if (route == "cable" and not busy and not self._chose_cable
                and not self.win._attaching and not self.setup_show.on
                and directmic.works(directmic.status(self.win.cfg.mic_device))):
            self.win.set_route("mic")
            route = self.win.cfg.route
        # (straight into the mic has its own "...instead" button, below)
        self.btn_use_cable.setVisible(not busy and route not in ("cable", "mic"))
        self.btn_cable.setToolTip(_("Use a free virtual cable instead: you pick it as the mic "
                                    "in Discord and games") if route == "mic" else "")
        self.btn_other.setVisible(not busy and self.other_box.isHidden())
        self.alt_card.hide()   # the mic's other ways: shown below once it's the mic's page
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
                self.btn_cable.hide()
                self.btn_recheck.hide()
                self.btn_other.hide()
                self._update_next()
                return
            if self.route_ok():
                self._show_working()
            elif directmic.needs_repair(state):
                self.status_card.set_state("warn", _("Needs a repair"),
                                           _("Your mic needs a quick repair"))
                self.cable_status.setText(_("Onion Board was on your mic but needs a quick "
                                            "repair: <b>one click</b>, and Windows asks for "
                                            "permission once.") if ask else
                                          _("Onion Board was on your mic but needs a quick "
                                            "repair: <b>one click</b>."))
            else:
                self.status_card.set_state("", _("Not set up"), _("Not set up yet"))
                self.cable_status.setText(_("Windows asks for permission once, and your PC's "
                                            "sound drops out for a second.") if ask else
                                          _("Your PC's sound drops out for a second while "
                                            "Windows reloads it."))
            # the other ways sit in their own card, not as buttons under the status
            self.btn_cable.hide()
            self.btn_other.hide()
            self.btn_recheck.hide()
            self.alt_card.show()
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
            dev = self.win._main_name()
            self.status_card.set_state(
                "ok" if self.route_ok() else "warn" if dev else "",
                _("Working") if self.route_ok() else _("Not working") if dev else "")
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
            self.status_card.set_state("ok", _("Installed"))
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
        QTimer.singleShot(SETTLE_MS, self, self._settle_size)   # a shorter state: no band

    def _show_working(self):
        """On the mic and working: said in plain words, a green card and a pill."""
        mic = self.win.cfg.mic_device or _("your mic")
        self.status_card.set_state("ok", _("Installed"),
                                   _("Working: your sounds go into your mic"))
        self.cable_status.setText(_("Onion Board's audio driver is on <b>{mic}</b>. Discord "
                                    "and games hear your sounds through it: press Next.",
                                    mic=html.escape(mic)))

    def _alt_cable(self):
        """Use the cable, from the optional card. With the driver working on the mic,
        ask first (CableConfirm): it's a step back for most people."""
        if not (self.win.cfg.route == "mic" and self.route_ok()):
            self.install_cable()
            return
        dlg = self._cable_confirm = CableConfirm(self, self.win.cfg.mic_device or "")
        dlg.btn_tell.clicked.connect(lambda: (dlg.reject(), self._tell_us()))
        dlg.accepted.connect(self.install_cable)
        dlg.open()   # modal over the guide; answered through its signals

    def _tell_us(self):
        """The driver let them down: the feedback box, over the guide."""
        from soundboard.ui import feedbackdialog
        self._feedback = feedbackdialog.ask(self.win.cfg, self)

    def attach_mic(self):
        self._chose_cable = False
        if self.win.cfg.route != "mic" and directmic.works(
                directmic.status(self.win.cfg.mic_device)):
            self.win.set_route("mic")   # already on the mic: no admin prompt, no reinstall
            self.recheck_cable(rescan=False)
            return
        self.setup_show.start()
        self.win.attach_mic()
        self.recheck_cable(rescan=False)
        self._update_next()   # Back / Next wait for it

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

    def _fold_discord(self, open_: bool):
        """Open or shut the Discord tip under its pill (the chevron says which)."""
        self._discord_open = open_
        if self.discord_fold.isChecked() != open_:
            self.discord_fold.setChecked(open_)
        self.discord_fold.setToolTip(_("Hide") if open_ else _("Show"))
        self.discord_fold.setAccessibleDescription(self.discord_fold.toolTip())
        self._show_discord_body()
        # shut again: no empty band, not even for a moment (the layouts first hear
        # the tip went away, or it's measured as still there: the news goes up one
        # layout per pass, the tip -> the page -> the steps -> the guide)
        for _pass in range(4):
            QApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
        self._settle_size()
        QTimer.singleShot(SETTLE_MS, self, self._settle_size)

    def _show_discord_body(self):
        # one rule: a Discord tip folds under its heading; without one (on the cable,
        # where Discord's steps are on the page) the Discord button shows as it is
        tip = bool(self.discord_tip.text())
        self.discord_fold.setVisible(tip)
        self.discord_body.setVisible(self._discord_open or not tip)

    def _fill_discord(self):
        self.discord_tip.setText("")
        self._fill_discord_text()
        self.discord_tip.setVisible(bool(self.discord_tip.text()))
        self._show_discord_body()
        games = not self.btn_steam.isHidden()
        self.games_label.setVisible(games)
        streamer = self.win.cfg.use_mode == "streamer"
        self.btn_streamer.setVisible(streamer)
        self.help_card.setVisible(games or streamer)
        self.helper_row.setVisible(not (self.btn_copy.isHidden() and self.btn_nomic.isHidden()))

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
        text = (
            _("Discord and your games keep using the mic they already have:<p "
              "style='font-size:15pt; font-weight:800; color:{colour}'>{mic}</p>Your sounds "
              "are in it now, so there's nothing to pick anywhere.<br><br><b>One thing worth "
              "doing in Discord:</b> ⚙ User Settings → <b>Voice &amp; Video</b> → <b>Input "
              "Profile</b> → <b>Custom</b>, <b>Noise Suppression</b> → <b>None</b>, and "
              "<b>Echo Cancellation</b> off (not Studio: Studio skips Onion Board). Left on, "
              "its noise suppression treats your sounds as background noise and wipes them "
              "out. <b>In a game:</b> turn off its noise suppression if your sounds cut out.",
              colour=_ok(), mic=mic))
        # the Discord part sits in the card under its pill (split after translating, and
        # before it's shown: the whole text for a moment grew the window for good)
        intro, sep, tip = text.partition("<br><br>")
        self.discord_text.setText(intro if sep else text)
        if sep:
            # its bold lead-in ("One thing worth doing in Discord:") is the pill's words
            self.discord_tip.setText(re.sub(r"^\s*<b>[^<]*</b>\s*", "", tip) or tip)

    def show_steam_guide(self):
        self.show_guide("steam")

    def show_streamer_guide(self):
        from soundboard.ui.crashdialog import free_dialog
        from soundboard.ui.streamguide import StreamerGuide
        g = StreamerGuide(self, self.win)
        g.exec()
        free_dialog(g)

    def show_guide(self, which: str):
        from soundboard.ui.chatguide import show_guide
        show_guide(which, self, self.win, self._vm)

    def copy_name(self):
        QApplication.clipboard().setText(self._vm)
        busy.flash(self.btn_copy, _("✓  Copied"))

    def _tick(self):
        if (locked := self._locked()) != self._was_locked:   # the mic set-up began / ended
            self._was_locked = locked
            self._update_next()
        if self.stack.currentIndex() == self.base:   # the mic page: its meter and Bun
            e = self.win.engine
            lvl = e.level_mic if e.mic_stream is not None else 0.0
            for tile in self.mic_group.buttons():   # the level on the picked mic's tile
                if isinstance(tile, ChoiceTile):
                    tile.set_level(lvl if tile.isChecked() else None)
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
        if (self.stack.currentIndex() == self.base + 2 and self._proc is None
                and not self._was_locked):
            # the step's card follows the mic effect when it changes from outside the
            # guide (a Windows update takes it off, a repair or Remove elsewhere): it
            # kept saying "Working" after the effect was gone
            if (ok := self.route_ok()) != self._route_was_ok:
                if self._route_was_ok is not None:
                    self.recheck_cable(rescan=False)
                self._route_was_ok = ok
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
            BunnyWidget("headphones", height=BUN_H, pad=BUN_PAD)))
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
