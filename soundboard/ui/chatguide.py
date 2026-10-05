"""Voice chat guides: the settings in Discord / a game that decide whether your
sounds come through clean, and the Discord check that listens to what Discord
really does to them (soundboard.chatcheck).

Discord and game voice chats run the mic through noise suppression, a gain
control and a voice-activity gate that are built for speech: they treat music as
noise. Our own processing can't undo that, so these dialogs tell people the few
switches to flip, and the check tells them which ones are still on.
"""
from __future__ import annotations

import html
import logging
import threading
import time

import numpy as np
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout)

from soundboard import chatcheck, theme
from soundboard.ui import busy, fit, icons
from soundboard.ui.bunnywidget import BunnyWidget
from soundboard.ui.crashdialog import free_dialog
from soundboard import errors

log = logging.getLogger(__name__)

DISCORD_EXES = ("discord.exe", "discordptb.exe", "discordcanary.exe", "discorddevelopment.exe")
DISCORD_VOICE_URL = "discord://-/settings/voice"
CHECK_SID = "__check__"
TAIL_S = chatcheck.MAX_LAG_S + 0.8     # keep listening this long after the test ends
CONNECT_S = 6.0                         # how long Windows gets to open the capture


def _ok() -> str:
    return theme.status("ok")


def _warn() -> str:
    return theme.status("warn")


def _label(text: str, css: str = "font-size:11pt;") -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setTextFormat(Qt.RichText)
    lbl.setStyleSheet(css)
    return lbl


def _header(title: str, body: QLabel, bun: BunnyWidget) -> QHBoxLayout:
    from soundboard.ui.setupwizard import _header as header
    return header(title, body, bun)


# --------------------------------------------------------------------------- the check

def find_discord():
    """The running Discord program with an audio session (soundboard.appaudio.App),
    or None."""
    from soundboard import appaudio
    try:
        apps = appaudio.list_apps()
    except Exception:  # noqa: BLE001 - the check just can't run
        log.debug("listing programs failed", exc_info=True)
        return None
    found = [a for a in apps if a.exe.lower() in DISCORD_EXES]
    found.sort(key=lambda a: (not a.active, a.exe.lower() != "discord.exe"))
    return found[0] if found else None


def result_html(res: dict, vm: str) -> str:
    """What the check found, and what to switch in Discord for each finding."""
    ok, warn = _ok(), _warn()
    issues = res.get("issues", [])
    vm = html.escape(vm)   # names and error text are plain, not markup
    if res.get("error"):
        return f"<span style='color:{warn}'>{html.escape(str(res['error']))}</span>"
    if not issues:
        return (f"<b style='color:{ok}'>✓ Discord passes your sounds through clean.</b> "
                "Nothing in its settings is changing them.")
    fixes = {
        "not_heard": (
            "Discord didn't play the test back. In Discord → <b>Voice &amp; Video</b>, set "
            f"<b>Input Device</b> to <b>{vm}</b>, click <b>Let's Check</b> (the bar should "
            "move when you play a sound here), then check again. If that's all set, noise "
            "suppression is removing your sounds completely: set <b>Input Profile</b> to "
            "<b>Studio</b>."),
        "suppression": (
            "<b>Noise suppression is removing your sounds.</b> Set <b>Input Profile</b> to "
            "<b>Studio</b> (or <b>Noise Suppression</b> to <b>None</b>)."),
        "gate": (
            "<b>Quiet parts of your sounds are cut off</b> (fades, quiet intros). Switch "
            "<b>Input Mode</b> to <b>Push to Talk</b> and turn on <b>Auto push-to-talk</b> "
            "(Settings → Hotkeys), or turn off <b>Automatically determine input "
            "sensitivity</b> and drag the slider almost all the way left."),
        "agc": (
            "<b>Automatic gain control is pumping your volume.</b> Set <b>Input Profile</b> "
            "to <b>Studio</b> (or turn off <b>Automatic Gain Control</b>)."),
    }
    items = "".join(f"<li style='margin-bottom:6px'>{fixes[i]}</li>" for i in issues
                    if i in fixes)
    return (f"<b style='color:{warn}'>Discord is changing your sounds:</b>"
            f"<ul style='margin-left:-20px'>{items}</ul>Fix it, then check again.")


class ChatCheck(QObject):
    """Runs one Discord check: captures Discord's playback, plays the test signal into
    the cable only, taps what we really sent, then compares the two. `done` carries
    the chatcheck.analyze() result (with 'error' set when it couldn't run).

    Nothing slow runs on the window's thread: finding Discord and the comparison run
    on a worker, and Windows opening the capture (up to seconds) is polled."""

    done = Signal(dict)
    progress = Signal(str)
    _found = Signal(object, object, int)   # (App or None, test signal, run): from the worker
    _analyzed = Signal(dict, int)     # (result, run): from the worker

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._cap = None
        self._heard: list[np.ndarray] = []
        self._sig = None   # the test sound (made on the worker: 0.2 s of numpy)
        self._run = 0   # which check: a worker's late answer to a cancelled one is dropped
        self._deadline = 0.0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._finish)
        self._poll = QTimer(self)   # Windows opening the capture (start(wait=False))
        self._poll.setInterval(50)
        self._poll.timeout.connect(self._poll_ready)
        self._found.connect(self._on_found)
        self._analyzed.connect(self._on_analyzed)
        self.running = False

    def start(self):
        if self.running:
            return
        e = self.engine
        if e.main_stream is None:
            self.done.emit({"issues": [], "error": "Pick where your sounds go first "
                                                   "(Setup tab → Step-by-step guide)."})
            return
        from soundboard import appaudio
        can, why = appaudio.supported()
        if not can:
            self.done.emit({"issues": [], "error": why})
            return
        self.running = True
        self._run += 1
        threading.Thread(target=self._find, args=(self._run,), name="chatcheck-find",
                         daemon=True).start()

    def _find(self, run: int):
        """On the worker: listing the programs walks every process and window, and
        making the test sound takes a moment too."""
        app = find_discord()
        self._emit(self._found, app, chatcheck.test_signal() if app is not None else None, run)

    def _emit(self, signal, *args):
        try:
            signal.emit(*args)
        except RuntimeError:   # the dialog closed meanwhile
            pass

    def _on_found(self, app, sig, run: int):
        if run != self._run or not self.running:
            return
        self._sig = sig
        if app is None:
            self.running = False
            self.done.emit({"issues": [], "error": (
                "Couldn't find Discord playing anything. Open Discord → ⚙ User Settings → "
                "Voice & Video, click Let's Check, then check again.")})
            return
        from soundboard import appaudio
        self._heard = []
        cap = appaudio.AppCapture(app.pid, self._heard.append, name=app.name)
        if not cap.start(wait=False):
            self.running = False
            self.done.emit({"issues": [], "error": cap.error or "Couldn't listen to Discord."})
            return
        self._cap = cap
        self._deadline = time.monotonic() + CONNECT_S
        self._poll.start()

    def _poll_ready(self):
        """Windows has opened the capture (or failed to): play the test."""
        cap = self._cap
        if cap is None:
            self._poll.stop()
            return
        if not cap.error and not cap.ready and time.monotonic() < self._deadline:
            return
        self._poll.stop()
        if not cap.ready:
            err = cap.error or "Windows didn't answer in time. Check again to retry."
            self._stop()
            self.done.emit({"issues": [], "error": err})
            return
        e = self.engine
        e.main_tap = []
        try:
            e.play(CHECK_SID, self._sig, 1.0, mode="restart", src_rate=chatcheck.SR, only="main")
        except Exception as ex:  # noqa: BLE001 - no capture or tap left running
            log.exception("discord check couldn't start")
            self._stop()
            self.done.emit({"issues": [], "error": f"The check couldn't start: "
                                                   f"{errors.plain(ex)}"})
            return
        self._t0 = time.monotonic()
        self.progress.emit("Listening to Discord…")
        self._timer.start(int((chatcheck.LENGTH_S + TAIL_S) * 1000))

    def cancel(self):
        if not self.running:
            return
        self._run += 1
        self._timer.stop()
        self._poll.stop()
        self._stop()

    def _stop(self):
        self.running = False
        self.engine.stop(CHECK_SID)
        cap, self._cap = self._cap, None
        if cap is not None:
            cap.stop(wait=False)   # it may still be inside Windows' capture request
        tap, self.engine.main_tap = self.engine.main_tap, None
        return tap

    def _finish(self):
        tap = self._stop()
        self.running = True   # until the comparison is back
        heard, rate, run = list(self._heard), self.engine.rates["main"], self._run
        threading.Thread(target=self._analyze, args=(tap, heard, rate, run),
                         name="chatcheck-analyze", daemon=True).start()

    def _analyze(self, tap, heard, rate, run: int):
        """On the worker: the comparison takes tens of ms."""
        try:
            sent = np.concatenate(tap) if tap else np.zeros((0, 2), np.float32)
            heard = np.concatenate(heard) if heard else np.zeros((0, 2), np.float32)
            if rate != chatcheck.SR and len(sent):
                import soxr
                sent = soxr.resample(sent, rate, chatcheck.SR).astype(np.float32)
            res = chatcheck.analyze(sent, heard, chatcheck.SR)
            log.info("discord check: %s", {k: v for k, v in res.items()})
        except Exception as ex:  # noqa: BLE001
            log.exception("discord check failed")
            res = {"issues": [], "error": f"The check failed: {errors.plain(ex)}"}
        self._emit(self._analyzed, res, run)

    def _on_analyzed(self, res: dict, run: int):
        if run != self._run or not self.running:
            return
        self.running = False
        self.done.emit(res)


# --------------------------------------------------------------------------- dialogs

class DiscordGuide(QDialog):
    """The Discord settings that matter for sounds, with the check built in."""

    def __init__(self, parent, mw, vm: str):
        super().__init__(parent)
        fit.watch(self)
        self.mw, self.vm = mw, vm
        self.setWindowTitle("Discord — make your sounds come through clean")
        self.setMinimumWidth(640)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 18)
        v.setSpacing(12)
        v.addLayout(_header("Discord: sound clean", _label(
            "Discord cleans up your mic for <b>talking</b>. Left on, that cleanup treats "
            "music and sound effects as background noise and chops them up, so your "
            "sounds reach your friends muffled and cut off. Two minutes, once:"),
            BunnyWidget("headphones")))
        v.addWidget(_label(
            "<ol style='margin-left:-20px'>"
            "<li style='margin-bottom:8px'>In Discord, click the ⚙ gear next to your name "
            "(<b>User Settings</b>) → <b>Voice &amp; Video</b>.</li>"
            "<li style='margin-bottom:8px'><b>Input Device</b>: choose "
            f"<b style='color:{_ok()}'>{html.escape(vm)}</b>.</li>"
            "<li style='margin-bottom:8px'><b>Input Profile</b>: choose <b>Studio</b>. That "
            "switches off noise suppression, echo cancellation and automatic gain "
            "control in one go.<br><span style='font-size:9pt'>No Input Profile in your "
            "Discord? Set <b>Noise Suppression</b> to <b>None</b> and turn off <b>Echo "
            "Cancellation</b> and <b>Automatic Gain Control</b>.</span></li>"
            "<li style='margin-bottom:8px'><b>Input Mode</b>: <b>Push to Talk</b> works best "
            "(set the same key under Settings → Hotkeys → Auto push-to-talk and Onion "
            "Board holds it for you while a sound plays). On <b>Voice Activity</b>, turn off "
            "<b>Automatically determine input sensitivity</b> and drag the slider almost "
            "all the way left, or quiet parts of your sounds get cut.</li>"
            "<li>Click <b>Let's Check</b> in Discord, then <b>Check Discord</b> below. "
            "Onion Board plays a short test into your mic and listens to what Discord "
            "does with it.</li></ol>"))
        self.result = _label("", "font-size:10.5pt;")
        self.result.setObjectName("resultbox")
        self.result.hide()
        v.addWidget(self.result)
        row = QHBoxLayout()
        copy = QPushButton("Copy the mic name")
        icons.set_icon(copy, "copy")
        copy.clicked.connect(lambda: (QApplication.clipboard().setText(vm),
                                      busy.flash(copy, "✓  Copied")))
        row.addWidget(copy)
        opn = QPushButton("Open Discord")
        opn.setToolTip("Opens Discord's Voice & Video settings")
        opn.clicked.connect(lambda: busy.open_url(
            DISCORD_VOICE_URL, opn, self, opened="✓ Opened Discord",
            failed="Couldn't open Discord — is it installed? Open it yourself: ⚙ User "
                   "Settings → Voice & Video. The link was"))
        row.addWidget(opn)
        ptt = QPushButton("Auto push-to-talk…")
        ptt.clicked.connect(lambda: mw.open_settings("hotkeys"))
        row.addWidget(ptt)
        row.addStretch(1)
        self.btn_check = QPushButton("Check Discord")
        self.btn_check.setObjectName("primary")
        self.btn_check.clicked.connect(self.check)
        row.addWidget(self.btn_check)
        done = QPushButton("Done")
        done.clicked.connect(self.accept)
        row.addWidget(done)
        v.addLayout(row)
        self._check = ChatCheck(mw.engine, self)
        self._check.done.connect(self._checked)
        self._check.progress.connect(self._progress)

    def check(self):
        if busy.is_busy(self.btn_check):
            return
        busy.set_busy(self.btn_check, True)   # not setEnabled: that moves the focus away
        self.btn_check.setText("Checking…")
        self.result.setText("Starting…")
        self.result.show()
        QTimer.singleShot(0, self, self._start_check)   # paint "Starting…" first

    def _start_check(self):
        try:
            self._check.start()
        except Exception as e:  # noqa: BLE001 - never leave the button stuck on "Checking…"
            log.exception("discord check couldn't start")
            self._checked({"issues": [], "error": f"The check couldn't start: {errors.plain(e)}"})

    def _progress(self, text: str):
        self.result.setText(f"{text} (about {round(chatcheck.LENGTH_S + TAIL_S)} seconds; "
                            "stay quiet for a moment)")

    def _checked(self, res: dict):
        busy.set_busy(self.btn_check, False)
        self.btn_check.setText("Check again")
        self.result.setText(result_html(res, self.vm))
        self.result.show()

    def done(self, r):   # noqa: A003 - QDialog.done
        self._check.cancel()
        super().done(r)


class GameGuide(QDialog):
    """In-game voice chat (Valorant, Fortnite, Apex, Rust, … and consoles' party chat
    through a PC game): the same idea, in words that fit most games' menus."""

    def __init__(self, parent, mw, vm: str):
        super().__init__(parent)
        fit.watch(self)
        self.setWindowTitle("Game voice chat — make your sounds come through clean")
        self.setMinimumWidth(600)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 18)
        v.setSpacing(12)
        v.addLayout(_header("Game voice chat", _label(
            "Games squeeze voice chat harder than Discord, and many clean up the mic the "
            "same way. In the game's <b>Audio</b> or <b>Voice chat</b> settings:"),
            BunnyWidget("headphones")))
        v.addWidget(_label(
            "<ol style='margin-left:-20px'>"
            f"<li style='margin-bottom:8px'><b>Microphone / Input device</b>: "
            f"<b style='color:{_ok()}'>{html.escape(vm)}</b>. No such setting? Use "
            "<b>Game has no microphone setting?</b> on the Setup tab.</li>"
            "<li style='margin-bottom:8px'>Turn <b>off</b> anything called <b>noise "
            "suppression</b>, <b>noise cancellation</b>, <b>denoiser</b>, <b>background "
            "sound removal</b>, <b>voice clarity</b> or <b>automatic gain</b>. The AI "
            "denoisers (VRChat, Minecraft's Simple Voice Chat) wipe out music almost "
            "completely.</li>"
            "<li style='margin-bottom:8px'><b>Push to talk</b> instead of open mic or voice "
            "activation, with the same key under <b>Settings → Hotkeys → Auto "
            "push-to-talk</b>: voice activation cuts the quiet parts of sounds, and some "
            "games send only speech on it, never music. Some games' anti-cheat ignores "
            "keys other programs press: if your mic doesn't open for a sound, "
            "<b>hold your push-to-talk key yourself</b> while it plays.</li>"
            "<li>On the Setup tab, set <b>Who's listening</b> to the voice chat your game "
            "is built on, so your sounds are shaped for it: <b>Vivox</b> (Valorant, "
            "League of Legends, Rainbow Six Siege, Overwatch 2), <b>Epic Online "
            "Services</b> (Fortnite), <b>Steam voice</b> (CS2, Dota 2), <b>Unity "
            "voice</b> (Phasmophobia, Lethal Company) or <b>Low bandwidth</b> for older "
            "and console titles. Not sure? Start the game and switch back: the picker "
            "names the engine when it can tell. Otherwise <b>Vivox</b> suits most "
            "games.</li></ol>"))
        row = QHBoxLayout()
        copy = QPushButton("Copy the mic name")
        icons.set_icon(copy, "copy")
        copy.clicked.connect(lambda: (QApplication.clipboard().setText(vm),
                                      busy.flash(copy, "✓  Copied")))
        row.addWidget(copy)
        ptt = QPushButton("Auto push-to-talk…")
        ptt.clicked.connect(lambda: mw.open_settings("hotkeys"))
        row.addWidget(ptt)
        row.addStretch(1)
        done = QPushButton("Done")
        done.setObjectName("primary")
        done.clicked.connect(self.accept)
        row.addWidget(done)
        v.addLayout(row)


class MeetingGuide(QDialog):
    """Calls in other apps: Zoom, Microsoft Teams, and calls in a web page (Google
    Meet, Discord in a browser). Their menus differ, so each gets its own few lines."""

    def __init__(self, parent, mw, vm: str):
        super().__init__(parent)
        fit.watch(self)
        self.setWindowTitle("Zoom, Teams and browser calls — make your sounds come through "
                            "clean")
        self.setMinimumWidth(600)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 18)
        v.setSpacing(12)
        v.addLayout(_header("Zoom, Teams and browser calls", _label(
            "Meeting apps clean up the mic for speech and treat music as background "
            "noise. Pick the cable as the mic and turn that cleanup down:"),
            BunnyWidget("headphones")))
        mic = f"<b style='color:{_ok()}'>{html.escape(vm)}</b>"
        v.addWidget(_label(
            "<ol style='margin-left:-20px'>"
            f"<li style='margin-bottom:8px'><b>Zoom</b>: Settings → Audio → Microphone: "
            f"{mic}. Untick <b>Automatically adjust microphone volume</b>, set "
            "<b>Background noise suppression</b> to <b>Low</b>, or pick <b>Original sound "
            "for musicians</b> (then turn it on in the meeting, top left).</li>"
            f"<li style='margin-bottom:8px'><b>Microsoft Teams</b>: Settings → Devices → "
            f"Microphone: {mic}. Set <b>Noise suppression</b> to <b>Off</b> or <b>Low</b>, "
            "or switch on <b>Music mode</b> / <b>High fidelity music mode</b> if it's "
            "there.</li>"
            f"<li style='margin-bottom:8px'><b>In a browser</b> (Google Meet, Discord or "
            f"Guilded in a web page): the call's own settings → Microphone: {mic}, and "
            "turn off <b>Noise cancellation</b> / <b>noise suppression</b> where the site "
            "has it.</li>"
            "<li>On the Setup tab, set <b>Who's listening</b> to <b>Browser, Zoom, "
            "Teams</b>. With <b>Pick the mode by "
            "itself</b> ticked it switches when the call starts.</li></ol>"))
        row = QHBoxLayout()
        copy = QPushButton("Copy the mic name")
        icons.set_icon(copy, "copy")
        copy.clicked.connect(lambda: (QApplication.clipboard().setText(vm),
                                      busy.flash(copy, "✓  Copied")))
        row.addWidget(copy)
        row.addStretch(1)
        done = QPushButton("Done")
        done.setObjectName("primary")
        done.clicked.connect(self.accept)
        row.addWidget(done)
        v.addLayout(row)


def show_guide(which: str, parent, mw, vm: str):
    """Open one guide modally: 'discord', 'game', 'meeting' or 'steam'."""
    if which == "steam":
        from soundboard.ui.setupwizard import SteamGuide
        g = SteamGuide(parent, vm)
    elif which == "game":
        g = GameGuide(parent, mw, vm)
    elif which == "meeting":
        g = MeetingGuide(parent, mw, vm)
    else:
        g = DiscordGuide(parent, mw, vm)
    g.exec()
    free_dialog(g)
