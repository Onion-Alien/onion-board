"""Voice chat guides: the settings in Discord / a game that decide whether your
sounds come through clean, and the Discord check that listens to what Discord
really does to them (soundboard.sim.chatcheck).

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

from soundboard.sim import chatcheck
from soundboard.mic import directmic, discordcfg
from soundboard.ui.kit import theme
from soundboard.core.pollthread import PollThread
from soundboard.ui.kit import busy, fit, icons, panel
from soundboard.ui.bun.bunnywidget import BunnyWidget
from soundboard.ui.kit.crashdialog import free_dialog
from soundboard.core import errors
from soundboard.i18n import _

log = logging.getLogger(__name__)
# Discord's settings, re-read every 2 s while the guide shows: one kept thread for every
# guide (a new thread each time made the window wait in Thread.start, pollthread.py)
_READ_POLL = PollThread("discord-guide-read")

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
    lbl.setTextFormat(Qt.TextFormat.RichText)
    lbl.setStyleSheet(css)
    return lbl


def _steps(*items: str) -> str:
    """A numbered list of guide steps (each one translated whole)."""
    lis = [f"<li style='margin-bottom:8px'>{t}</li>" for t in items[:-1]]
    return f"<ol style='margin-left:-20px'>{''.join(lis)}<li>{items[-1]}</li></ol>"


def _header(title: str, body: QLabel, bun: BunnyWidget) -> QHBoxLayout:
    from soundboard.ui.setup.setupwizard import _header as header
    return header(title, body, bun)


def _bun(prop: str) -> BunnyWidget:
    """Bun beside a guide's intro, the setup guide's size: no taller than the words,
    so the steps start right under them."""
    from soundboard.ui.setup.setupwizard import BUN_H, BUN_PAD
    return BunnyWidget(prop, height=BUN_H, pad=BUN_PAD)


# --------------------------------------------------------------------------- the check

def find_discord():
    """The running Discord program with an audio session (soundboard.audio.appaudio.App),
    or None."""
    from soundboard.audio import appaudio
    try:
        apps = appaudio.list_apps()
    except Exception:  # noqa: BLE001 - the check just can't run
        log.debug("listing programs failed", exc_info=True)
        return None
    found = [a for a in apps if a.exe.lower() in DISCORD_EXES]
    found.sort(key=lambda a: (not a.active, a.exe.lower() != "discord.exe"))
    return found[0] if found else None


def on_mic(mw) -> bool:
    """Straight into my mic, and it's on the mic: voice apps keep the mic they have."""
    cfg = mw.cfg
    return cfg.route == "mic" and directmic.works(directmic.status(cfg.mic_device))


def raw_skips(mw) -> bool:
    """On the mic, and an app opening it raw (Discord's Studio or Bypass) skips Onion
    Board: an older copy in the stream effect. In the endpoint effect raw gets it too."""
    return on_mic(mw) and not directmic.endpoint_wide()


# each discordcfg problem: what it does and what to switch, in one sentence. Straight
# into my mic, Discord's Studio profile (and "Bypass System Audio Input Processing")
# opens the mic around every Windows audio effect, so nothing of the board's reaches
# Discord: the clean setting there is Custom with the cleanup off.
SETTING_FIXES = {
    discordcfg.STUDIO: _(
        "Input Profile is <b>Studio</b>: Discord skips Onion Board, so none of your "
        "sounds get through: set <b>Input Profile</b> to <b>Custom</b>."),
    discordcfg.BYPASS: _(
        "<b>Bypass System Audio Input Processing</b> is on: Discord skips Onion Board: "
        "turn it off (Show Advanced Voice Settings)."),
    discordcfg.VAD: _(
        "<b>Advanced Voice Activity</b> is on: in a call it only sends your voice, and "
        "cuts most of a song: turn it off (Show Advanced Voice Settings), or use Push "
        "to Talk."),
    discordcfg.AUTO: _(
        "<b>Automatically determine input sensitivity</b> is on: in a call it keeps "
        "taking your sounds for silence and cuts them out: turn it off (Input "
        "Sensitivity) and leave the slider low, or use Push to Talk."),
    discordcfg.ISOLATION: _(
        "Input Profile is <b>Voice Isolation</b>: Krisp wipes out music after a second: "
        "set <b>Input Profile</b> to <b>Custom</b>, then Noise Suppression to <b>None</b>."),
    discordcfg.KRISP: _(
        "Noise Suppression is <b>Krisp</b>: it wipes out music after a second: set "
        "<b>Noise Suppression</b> to <b>None</b>."),
    discordcfg.SUPPRESSION: _(
        "Noise Suppression is <b>Standard</b>: it eats steady sounds: set <b>Noise "
        "Suppression</b> to <b>None</b>."),
    discordcfg.ECHO: _(
        "<b>Echo Cancellation</b> is on: your sounds dip and pump: turn it off."),
    discordcfg.AGC: _(
        "<b>Automatic Gain Control</b> is on: the volume jumps around: turn it off (Show "
        "Advanced Voice Settings)."),
}


def settings_html(found: list, kept: bool) -> str:
    """Discord's own settings as read from its files (soundboard.mic.discordcfg): a ✓, or
    each one that's hurting your sounds and what to switch. '' when none was found."""
    if not found:
        return ""
    ok, warn = _ok(), _warn()
    s = found[0]   # the client changed most recently
    name = html.escape(s.client)
    probs = s.problems(kept and not directmic.endpoint_wide())
    if not probs:
        return _("<b style='color:{colour}'>✓ {name}'s settings are right for your "
                 "sounds.</b>", colour=ok, name=name)
    items = "".join(f"<li style='margin-bottom:4px'>{SETTING_FIXES[p]}</li>" for p in probs)
    return (_("<b style='color:{colour}'>{name}'s settings are changing your sounds:</b>",
              colour=warn, name=name)
            + f"<ul style='margin-left:-20px'>{items}</ul><span style='font-size:9pt'>"
            + _("Discord saves a change after a few seconds, up to a minute: this updates "
                "by itself.") + "</span>")


def _profile_name(p: str) -> str:
    return {"CUSTOM": _("Custom"), "STUDIO": _("Studio"),
            "VOICE_ISOLATION": _("Voice Isolation")}.get(p.upper(),
                                                         p.replace("_", " ").title())


def _noise_name(s: discordcfg.Settings) -> str:
    return "Krisp" if s.krisp else _("Standard") if s.suppression else _("None")


def setting_changes(before: discordcfg.Settings,
                    after: discordcfg.Settings) -> list[tuple[str, str, str]]:
    """Each Discord voice setting that differs between two reads, in the order Voice &
    Video lists them: (setting, was, now)."""
    def on(v: bool) -> str:
        return _("On") if v else _("Off")

    def mode(s) -> str:
        return _("Push to Talk") if s.ptt else _("Voice Activity")
    rows = []
    if before.profile and after.profile:   # older Discord: no Input Profile
        rows.append((_("Input Profile"), _profile_name(before.profile),
                     _profile_name(after.profile)))
    rows += [(_("Noise Suppression"), _noise_name(before), _noise_name(after)),
             (_("Echo Cancellation"), on(before.echo), on(after.echo)),
             (_("Input Mode"), mode(before), mode(after))]
    if not before.ptt and not after.ptt:   # these two only exist on Voice Activity
        rows += [(_("Automatically determine input sensitivity"), on(before.auto),
                  on(after.auto)),
                 (_("Advanced Voice Activity"), on(before.vad), on(after.vad))]
    rows += [(_("Automatic Gain Control"), on(before.agc), on(after.agc)),
             (_("Bypass System Audio Input Processing"), on(before.bypass),
              on(after.bypass))]
    return [r for r in rows if r[1] != r[2]]


def changes_html(changes: list[tuple[str, str, str]]) -> str:
    """The changed settings as a table: setting, what it was (struck out), what it is."""
    ok = _ok()
    rows = "".join(
        f"<tr><td style='padding:3px 18px 3px 0'><b>{html.escape(name)}</b></td>"
        f"<td style='padding:3px 8px 3px 0' nowrap><s>{html.escape(was)}</s></td>"
        f"<td style='padding:3px 8px 3px 0'>→</td>"
        f"<td style='padding:3px 0' nowrap><b style='color:{ok}'>{html.escape(now)}</b></td></tr>"
        for name, was, now in changes)
    return f"<table cellspacing='0'>{rows}</table>"


class DiscordFixed(QDialog):
    """Discord's settings came right while its guide was open: Bun celebrates, and the
    table says exactly which settings changed, from what to what. Audio recovery's Put
    Discord back is under it, and works here too."""
    discord_back = Signal(list, list)   # (Discord folders to put back, still open)

    def __init__(self, parent, client: str, changes: list[tuple[str, str, str]],
                 restore: bool, show_me=None, mw=None):
        super().__init__(parent)
        self.mw = mw if hasattr(mw, "alertctl") else None   # the main window: its toasts
        title = _("{name} is set up for your sounds", name=client)
        self.setWindowTitle(title)
        self.setMinimumWidth(480)   # the table on one line a row, not a narrow column
        self.setMaximumWidth(620)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(12)
        head = QHBoxLayout()
        head.setSpacing(16)
        col = QVBoxLayout()
        col.setSpacing(6)
        top = QLabel(title)
        top.setObjectName("helptitle")
        top.setWordWrap(True)
        col.addWidget(top)
        col.addWidget(panel.hint_label(_(
            "Your sounds reach your friends clean now, not muffled or cut off.")))
        col.addStretch(1)
        head.addLayout(col, 1)
        self.bun = BunnyWidget("star", celebrate=True, height=74, pad=5)
        head.addWidget(self.bun, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(head)
        sec = QLabel(_("What changed in {name}", name=client))
        sec.setObjectName("section")
        v.addWidget(sec)
        self.table = _label(changes_html(changes), "")
        self.table.setObjectName("resultbox")
        v.addWidget(self.table)
        if restore:
            lbl = panel.hint_label(_(
                "When Onion Board closes, it turns Discord's noise suppression, echo "
                "cancellation and automatic volume back on for talking. Don't want that? "
                "Untick <b>Put Discord back for talking on close</b> on the Setup tab."))
            lbl.setTextFormat(Qt.TextFormat.RichText)
            v.addWidget(lbl)
        # where to undo it, and the very button, working (not a picture of it)
        back = panel.hint_label(_(
            "Changed your mind? <b>Put Discord back</b> turns its talking clean-up back on. "
            "It's in <b>Settings → Audio → Audio recovery</b>:"))
        back.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(back)
        from soundboard.ui.setup.audiorecovery import DiscordRow
        self.back = DiscordRow(self)
        self.back.button.clicked.connect(self.put_back)
        self.back.button.setVisible(self.mw is not None)
        self.discord_back.connect(self._put_back_done)
        v.addWidget(self.back)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        ok = QPushButton(_("Nice!"))
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        if show_me is not None:
            where = QPushButton(_("Show me"))
            where.clicked.connect(lambda: (self.accept(), show_me()))
            row.addWidget(where)
        v.addLayout(row)
        fit.watch(self)

    def put_back(self):
        from soundboard.ui.setup.audiorecovery import put_discord_back
        put_discord_back(self.mw, self.back.button, self.discord_back)

    def _put_back_done(self, todo, left):
        """Put back (or waiting for Discord to close): this window's news is old now."""
        from soundboard.ui.setup.audiorecovery import said_discord_back
        busy.set_busy(self.back.button, False)
        said_discord_back(self.mw, todo, left)
        if left != ["?"]:
            self.accept()

    def showEvent(self, ev):
        # its first size is the labels' narrow guess (tall): as tall as the words at
        # this width, not a gap under the title
        super().showEvent(ev)
        self.resize(self.width(), fit.needed_height(self, self.width()))


def result_html(res: dict, vm: str, kept: bool = False) -> str:
    """What the check found, and what to switch in Discord for each finding."""
    ok, warn = _ok(), _warn()
    issues = res.get("issues", [])
    vm = html.escape(vm)   # names and error text are plain, not markup
    if res.get("error"):
        return f"<span style='color:{warn}'>{html.escape(str(res['error']))}</span>"
    if not issues:
        return _("<b style='color:{color}'>✓ Discord passes your sounds through clean.</b> "
                 "Nothing in its settings is changing them.", color=ok)
    device = (_("your normal mic, <b>{mic}</b>", mic=vm) if kept
              else f"<b>{vm}</b>")
    fixes = {
        "not_heard": _(
            "Discord didn't play the test back. In Discord → <b>Voice &amp; Video</b>, set "
            "<b>Input Device</b> to {device}, click <b>Let's Check</b> (the bar should "
            "move when you play a sound here), then check again. If that's all set, Discord "
            "is skipping Onion Board or wiping your sounds out: set <b>Input Profile</b> to "
            "<b>Custom</b> (not Studio: Studio skips Onion Board), <b>Noise Suppression</b> "
            "to <b>None</b>, turn off <b>Echo Cancellation</b>, and turn off <b>Bypass "
            "System Audio Input Processing</b> (Show Advanced Voice Settings).",
            device=device) if kept else _(
            "Discord didn't play the test back. In Discord → <b>Voice &amp; Video</b>, set "
            "<b>Input Device</b> to {device}, click <b>Let's Check</b> (the bar should "
            "move when you play a sound here), then check again. If that's all set, noise "
            "suppression is removing your sounds completely: set <b>Input Profile</b> to "
            "<b>Studio</b>.", device=device),
        "suppression": _(
            "<b>Noise suppression is removing your sounds.</b> In Discord, set <b>Input "
            "Profile</b> to <b>Custom</b> (not Studio: Studio skips Onion Board), <b>Noise "
            "Suppression</b> to <b>None</b>, and turn off <b>Echo Cancellation</b>.")
        if kept else _(
            "<b>Noise suppression is removing your sounds.</b> Set <b>Input Profile</b> to "
            "<b>Studio</b> (or <b>Noise Suppression</b> to <b>None</b>)."),
        "gate": _(
            "<b>Quiet parts of your sounds are cut off</b> (fades, quiet intros). Switch "
            "<b>Input Mode</b> to <b>Push to Talk</b> and turn on <b>Auto push-to-talk</b> "
            "(Settings → Hotkeys), or turn off <b>Automatically determine input "
            "sensitivity</b> and drag the slider almost all the way left."),
        "agc": _(
            "<b>Automatic gain control is pumping your volume.</b> Turn off <b>Automatic "
            "Gain Control</b> and <b>Echo Cancellation</b> (Input Profile <b>Custom</b>, not "
            "Studio).") if kept else _(
            "<b>Automatic gain control is pumping your volume.</b> Set <b>Input Profile</b> "
            "to <b>Studio</b> (or turn off <b>Automatic Gain Control</b>)."),
    }
    items = "".join(f"<li style='margin-bottom:6px'>{fixes[i]}</li>" for i in issues
                    if i in fixes)
    return _("<b style='color:{color}'>Discord is changing your sounds:</b>"
             "<ul style='margin-left:-20px'>{fixes}</ul>Fix it, then check again.",
             color=warn, fixes=items)


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
            self.done.emit({"issues": [], "error": _("Pick where your sounds go first "
                                                     "(Setup tab → Step-by-step guide).")})
            return
        from soundboard.audio import appaudio
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
        making the test sound takes a moment too. Anything raising here ends the
        check with its error: left alone, the check stayed 'running' for good."""
        try:
            app = find_discord()
            sig = chatcheck.test_signal() if app is not None else None
        except Exception as ex:  # noqa: BLE001
            log.exception("discord check couldn't start")
            self._emit(self._analyzed, {"issues": [], "error": _(
                "The check couldn't start: {error}", error=errors.plain(ex))}, run)
            return
        self._emit(self._found, app, sig, run)

    def _emit(self, signal, *args):
        busy.emit(signal, *args)   # (on the UI thread: the dialog may close meanwhile)

    def _on_found(self, app, sig, run: int):
        if run != self._run or not self.running:
            return
        self._sig = sig
        if app is None:
            self.running = False
            self.done.emit({"issues": [], "error": _(
                "Couldn't find Discord playing anything. Open Discord → ⚙ User Settings → "
                "Voice & Video, click Let's Check, then check again.")})
            return
        from soundboard.audio import appaudio
        self._heard = []
        cap = appaudio.AppCapture(app.pid, self._heard.append, name=app.name)
        if not cap.start(wait=False):
            self.running = False
            self.done.emit({"issues": [], "error": cap.error or _("Couldn't listen to Discord.")})
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
            err = cap.error or _("Windows didn't answer in time. Check again to retry.")
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
            self.done.emit({"issues": [], "error": _("The check couldn't start: {error}",
                                                     error=errors.plain(ex))})
            return
        self._t0 = time.monotonic()
        self.progress.emit(_("Listening to Discord…"))
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
            res = {"issues": [], "error": _("The check failed: {error}", error=errors.plain(ex))}
        self._emit(self._analyzed, res, run)

    def _on_analyzed(self, res: dict, run: int):
        if run != self._run or not self.running:
            return
        self.running = False
        self.done.emit(res)


# --------------------------------------------------------------------------- dialogs

class DiscordSetUp(QObject):
    """Bun sets Discord up for your sounds (discordtalk.set_up), every Discord button's
    one way to do it: the setup guide's last step, the Setup tab, the Fix Discord bar
    and the Discord guide. How you talk there is saved first: it goes back by itself
    when Onion Board closes (if that's on), and Settings → Audio → Audio recovery's Put
    Discord back does it any time. Discord's settings can only be written while it's
    closed: open, it's asked first, closed, and opened again on its voice settings."""
    _done = Signal(object)

    def __init__(self, mw, parent=None, then=None):
        """`then`: called once it's over (set up, already right, or left), on the UI
        thread: what comes next (the cable still has to be picked in Discord)."""
        super().__init__(mw)
        self.mw, self.parent_w, self.then = mw, parent or mw, then
        self._on_mic = raw_skips(mw)
        self._closed: list[str] = []   # the Discords closed here: opened again after
        self._done.connect(self._finished)

    def start(self):
        if getattr(self.mw, "_discord_setup", None) is not None:
            return   # one at a time (a double click)
        self.mw._discord_setup = self
        busy.toast(self.parent_w, _("Bun is setting up Discord…"), "busy", 4000,
                   key="discord-setup")
        self._go([])

    def _go(self, close: list[str]):
        saved = dict(self.mw.cfg.discord_talk)
        threading.Thread(target=self._run, args=(saved, close), daemon=True,
                         name="discord-setup").start()

    def _run(self, saved: dict, close: list[str]):
        """On a thread: Discord's files and processes."""
        from soundboard.mic import discordtalk
        from soundboard.sounds.library import APP_DIR
        try:
            if close and not discordtalk.close_clients(close):
                res: dict = {"stuck": True}
            else:
                res = discordtalk.set_up(saved, APP_DIR / "discord-backup", self._on_mic)
                res["installed"] = discordtalk.installed()
        except Exception as e:  # noqa: BLE001 - said, never a stuck "setting up"
            log.exception("setting up Discord failed")
            res = {"error": errors.plain(e)}
        busy.emit(self._done, res)

    def _finished(self, res: dict):
        mw = self.mw
        if res.get("running") and not self._closed:
            if not self._ask_to_close():
                return self._end()
            self._closed = list(res["running"])
            self._go(self._closed)
            return
        talk = res.get("talk") or {}
        if talk:   # how they talk, from before: what goes back (discordtalk.restore)
            mw.cfg.discord_talk = {**mw.cfg.discord_talk, **talk}
            mw.cfg.save()
        done = res.get("done") or []
        if res.get("error") or res.get("stuck") or res.get("failed") or res.get("running"):
            busy.toast(self.parent_w, _(
                "Bun couldn't change Discord's settings, so here's how to do it yourself."),
                "warn", 6000, key="discord-setup")
            self.then = None   # the guide is what comes next
            self._end()
            show_guide("discord", self.parent_w, mw, self._vm())
            return
        if not res.get("installed"):
            busy.toast(self.parent_w, _("Discord isn't installed on this PC."), "warn", 5000,
                       key="discord-setup")
            return self._end()
        if self._closed or done:   # back on its voice settings, as they'd left it
            busy.open_url(DISCORD_VOICE_URL, None, self.parent_w,
                          failed=_("Couldn't open Discord. The link was"))
        if not done:
            busy.toast(self.parent_w, _("Discord is already set up for your sounds."), "ok",
                       4000, key="discord-setup")
            return self._end()
        name, before, after = done[0]
        cfg, setctl = mw.cfg, getattr(mw, "setctl", None)
        box = DiscordFixed(self.parent_w, name, setting_changes(before, after),
                           bool(cfg.discord_restore),
                           (lambda: setctl.open_settings("audio")) if setctl else None,
                           mw=mw)
        box.exec()
        free_dialog(box)
        self._end()

    def close_box(self):
        """The question before Discord is closed: (the box, its yes button)."""
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox(QMessageBox.Icon.Question, _("Close Discord for a moment?"), _(
            "Discord has to close for a few seconds while Bun changes its settings. It "
            "drops any call you're in. Bun opens it again right after."), parent=self.parent_w)
        yes = box.addButton(_("Close Discord and set it up"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(_("Not now"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(yes)
        return box, yes

    def _ask_to_close(self) -> bool:
        box, yes = self.close_box()
        box.exec()
        box.deleteLater()
        return box.clickedButton() is yes

    def _vm(self) -> str:
        statusctl = getattr(self.mw, "statusctl", None)
        return getattr(statusctl, "virtual_mic", None) or "CABLE Output"

    def _end(self):
        self.mw._discord_setup = None
        then, self.then = self.then, None
        if then is not None:
            then()
        self.deleteLater()


def set_up_discord(mw, parent=None, then=None):
    """Set Discord up for sounds (DiscordSetUp). On the cable or a virtual mic, Discord
    still has to be told which mic: its guide follows, saying which."""
    if then is None and not on_mic(mw):
        statusctl = getattr(mw, "statusctl", None)
        vm = getattr(statusctl, "virtual_mic", None)
        if vm:
            then = lambda: show_guide("discord", parent or mw, mw, vm)  # noqa: E731
    DiscordSetUp(mw, parent, then).start()


class DiscordGuide(QDialog):
    """The Discord settings that matter for sounds, with the check built in."""
    _settings_read = Signal(object, object)   # (signature, [Settings] or None = unchanged)

    def __init__(self, parent, mw, vm: str, kept: bool = False):
        super().__init__(parent)
        fit.watch(self)
        self.mw, self.vm, self.kept = mw, vm, kept
        self.setWindowTitle(_("Discord: make your sounds come through clean"))
        self.setMinimumWidth(640)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 18)
        v.setSpacing(12)
        v.addLayout(_header(_("Discord: sound clean"), _label(_(
            "Discord cleans up your mic for <b>talking</b>. Left on, that cleanup treats "
            "music and sound effects as background noise and chops them up, so your "
            "sounds reach your friends muffled and cut off. Two minutes, once:")),
            _bun("headphones")))
        mic = f"<b style='color:{_ok()}'>{html.escape(vm)}</b>"
        v.addWidget(_label(_steps(
            _("In Discord, click the ⚙ gear next to your name (<b>User Settings</b>) → "
              "<b>Voice &amp; Video</b>."),
            _("<b>Input Device</b>: keep your normal mic ({mic}). Your sounds are already "
              "in it.", mic=mic) if kept else
            _("<b>Input Device</b>: choose {mic}.", mic=mic),
            _("<b>Input Profile</b>: choose <b>Custom</b>. <b>Not Studio</b>: Studio makes "
              "Discord skip Onion Board, and none of your sounds get through. Then set "
              "<b>Noise Suppression</b> to <b>None</b> and turn off <b>Echo "
              "Cancellation</b>. Under <b>Show Advanced Voice Settings</b>, turn off "
              "<b>Automatic Gain Control</b> and keep <b>Bypass System Audio Input "
              "Processing</b> off.") if kept else
            _("<b>Input Profile</b>: choose <b>Studio</b>. That switches off noise "
              "suppression, echo cancellation and automatic gain control in one go."
              "<br><span style='font-size:9pt'>No Input Profile in your Discord? Set "
              "<b>Noise Suppression</b> to <b>None</b> and turn off <b>Echo "
              "Cancellation</b> and <b>Automatic Gain Control</b>.</span>"),
            _("<b>Input Mode</b>: <b>Push to Talk</b> works best (set the same key under "
              "Settings → Hotkeys → Auto push-to-talk and Onion Board holds it for you "
              "while a sound plays). On <b>Voice Activity</b>, turn off <b>Automatically "
              "determine input sensitivity</b> and drag the slider almost all the way "
              "left, or Discord keeps cutting your sounds out, loud ones too."),
            _("Click <b>Let's Check</b> in Discord, then <b>Check Discord</b> below. Onion "
              "Board plays a short test into your mic and listens to what Discord does "
              "with it."))))
        # Discord's settings as its files have them, kept up to date while open
        self.settings = _label("", "font-size:10.5pt;")
        self.settings.setObjectName("resultbox")
        self.settings.hide()
        v.addWidget(self.settings)
        self._sig = None
        self._broken = None     # Discord's settings when first seen hurting your sounds
        self._cheered = False   # the "fixed" window has shown
        self.fixed: DiscordFixed | None = None
        self._reading = False   # a worker is reading them (files in Discord's folder)
        self._settings_read.connect(self._settings_in)
        self._watch = QTimer(self)
        self._watch.setInterval(2000)
        self._watch.timeout.connect(self._read_settings)
        self._watch.start()
        self._read_settings()
        self.result_box = _label("", "font-size:10.5pt;")
        self.result_box.setObjectName("resultbox")
        self.result_box.hide()
        v.addWidget(self.result_box)
        row = QHBoxLayout()
        copy = QPushButton(_("Copy the mic name"), self)   # parent: see test_no_flash_windows
        icons.set_icon(copy, "copy")
        copy.clicked.connect(lambda: (QApplication.clipboard().setText(vm),
                                      busy.flash(copy, _("✓  Copied"))))
        copy.setVisible(not kept)   # straight into the mic: nothing to pick
        row.addWidget(copy)
        opn = QPushButton(_("Open Discord"))
        opn.setToolTip(_("Opens Discord's Voice & Video settings"))
        opn.clicked.connect(lambda: busy.open_url(
            DISCORD_VOICE_URL, opn, self, opened=_("✓ Opened Discord"),
            failed=_("Couldn't open Discord: is it installed? Open it yourself: ⚙ User "
                     "Settings → Voice & Video. The link was")))
        row.addWidget(opn)
        ptt = QPushButton(_("Auto push-to-talk"))
        ptt.clicked.connect(lambda: mw.setctl.open_settings("hotkeys"))
        row.addWidget(ptt)
        row.addStretch(1)
        # Bun does it all: the same as every other Discord button (DiscordSetUp)
        auto = self.btn_auto = QPushButton(_("Set it up for me"))
        icons.set_icon(auto, "star")
        auto.setToolTip(_("Bun saves how Discord is set now, then switches off what chops "
                          "up your sounds. Settings → Audio recovery puts it back."))
        # (the guide stays: on the cable its Input Device step is still to do, and its
        # live list ticks the settings off as Bun changes them)
        auto.clicked.connect(lambda: set_up_discord(mw, self, then=lambda: None))
        row.addWidget(auto)
        self.btn_check = QPushButton(_("Check Discord"))
        self.btn_check.setObjectName("primary")
        self.btn_check.clicked.connect(self.check)
        row.addWidget(self.btn_check)
        done = QPushButton(_("Done"))
        done.clicked.connect(self.accept)
        row.addWidget(done)
        v.addLayout(row)
        self._check = ChatCheck(mw.engine, self)
        self._check.done.connect(self._checked)
        self._check.progress.connect(self._progress)

    def _read_settings(self):
        """Re-read Discord's settings when its files changed (~10 kB), on a worker: a
        few ms usually, but the window froze while a slow or waking disk answered."""
        if self._reading:
            return
        self._reading = True
        last = self._sig
        _READ_POLL.run(lambda: self._read_worker(last))

    def _read_worker(self, last):
        try:
            sig = discordcfg.signature()
            found = None if sig == last else discordcfg.read()
        except Exception:  # noqa: BLE001 - never leave _reading stuck
            log.debug("reading Discord's settings failed", exc_info=True)
            sig, found = last, None
        busy.emit(self._settings_read, sig, found)

    def _settings_in(self, sig, found):
        self._reading = False
        if found is None:
            return
        self._sig = sig
        self._watch_fixed(found)
        text = settings_html(found, self.kept)
        if text == self.settings.text():
            return
        self.settings.setText(text)
        self.settings.setVisible(bool(text))
        if self.isVisible():   # a shorter list: shrink, not a gap under the header
            QTimer.singleShot(0, self, self.adjustSize)

    def _watch_fixed(self, found: list):
        """Settings that hurt your sounds, then came right while this is open: the
        "fixed" window, once, with exactly what changed."""
        if not found or self._cheered:
            return
        s = found[0]
        if s.problems(self.kept and not directmic.endpoint_wide()):
            if self._broken is None or self._broken.client != s.client:
                self._broken = s
        elif self._broken is not None and self._broken.client == s.client:
            self._cheered = True
            changes = setting_changes(self._broken, s)
            if changes:   # (not just Straight into my mic switched off meanwhile)
                QTimer.singleShot(0, self, lambda: self._show_fixed(s.client, changes))

    def _show_fixed(self, client: str, changes: list):
        cfg = getattr(self.mw, "cfg", None)
        setctl = getattr(self.mw, "setctl", None)
        self.fixed = DiscordFixed(
            self, client, changes, bool(getattr(cfg, "discord_restore", False)),
            (lambda: setctl.open_settings("audio")) if setctl is not None else None,
            mw=self.mw)
        self.fixed.finished.connect(self.accept)   # nothing left to do in the guide
        self.fixed.open()

    def check(self):
        if busy.is_busy(self.btn_check):
            return
        busy.set_busy(self.btn_check, True)   # not setEnabled: that moves the focus away
        self.btn_check.setText(_("Checking…"))
        self.result_box.setText(_("Starting…"))
        self.result_box.show()
        QTimer.singleShot(0, self, self._start_check)   # paint "Starting…" first

    def _start_check(self):
        try:
            self._check.start()
        except Exception as e:  # noqa: BLE001 - never leave the button stuck on "Checking…"
            log.exception("discord check couldn't start")
            self._checked({"issues": [], "error": _("The check couldn't start: {error}",
                                                     error=errors.plain(e))})

    def _progress(self, text: str):
        self.result_box.setText(_("{text} (about {n} seconds; stay quiet for a moment)",
                              text=text, n=round(chatcheck.LENGTH_S + TAIL_S)))

    def _checked(self, res: dict):
        busy.set_busy(self.btn_check, False)
        self.btn_check.setText(_("Check again"))
        self.result_box.setText(result_html(res, self.vm, self.kept))
        self.result_box.show()

    def done(self, r):   # noqa: A003 - QDialog.done
        self._check.cancel()
        super().done(r)


class GameGuide(QDialog):
    """In-game voice chat (Valorant, Fortnite, Apex, Rust, … and consoles' party chat
    through a PC game): the same idea, in words that fit most games' menus."""

    def __init__(self, parent, mw, vm: str, kept: bool = False):
        super().__init__(parent)
        fit.watch(self)
        self.setWindowTitle(_("Game voice chat: make your sounds come through clean"))
        self.setMinimumWidth(600)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 18)
        v.setSpacing(12)
        v.addLayout(_header(_("Game voice chat"), _label(_(
            "Games squeeze voice chat harder than Discord, and many clean up the mic the "
            "same way. In the game's <b>Audio</b> or <b>Voice chat</b> settings:")),
            _bun("headphones")))
        mic = f"<b style='color:{_ok()}'>{html.escape(vm)}</b>"
        v.addWidget(_label(_steps(
            _("<b>Microphone / Input device</b>: keep your normal mic ({mic}). Your sounds "
              "are already in it.", mic=mic) if kept else
            _("<b>Microphone / Input device</b>: {mic}. No such setting? Use <b>Game has no "
              "microphone setting?</b> on the Setup tab.", mic=mic),
            _("Turn <b>off</b> anything called <b>noise suppression</b>, <b>noise "
              "cancellation</b>, <b>denoiser</b>, <b>background sound removal</b>, <b>voice "
              "clarity</b> or <b>automatic gain</b>. The AI denoisers (VRChat, Minecraft's "
              "Simple Voice Chat) wipe out music almost completely."),
            _("<b>Push to talk</b> instead of open mic or voice activation, with the same key "
              "under <b>Settings → Hotkeys → Auto push-to-talk</b>: voice activation cuts the "
              "quiet parts of sounds, and some games send only speech on it, never music. "
              "Some games' anti-cheat ignores keys other programs press: if your mic doesn't "
              "open for a sound, <b>hold your push-to-talk key yourself</b> while it plays."),
            _("On the Setup tab, set <b>Who's listening</b> to <b>Game</b>. While the game is "
              "open it recognises Vivox and Unity voice chat and shapes your sounds for it by "
              "itself. For <b>Steam voice</b> (CS2, Dota 2), <b>Epic Online Services</b> "
              "(Fortnite) or <b>Low bandwidth</b> (older and console titles), choose "
              "<b>Advanced</b> and pick it."))))
        row = QHBoxLayout()
        copy = QPushButton(_("Copy the mic name"), self)   # parent: see test_no_flash_windows
        icons.set_icon(copy, "copy")
        copy.clicked.connect(lambda: (QApplication.clipboard().setText(vm),
                                      busy.flash(copy, _("✓  Copied"))))
        copy.setVisible(not kept)   # straight into the mic: nothing to pick
        row.addWidget(copy)
        ptt = QPushButton(_("Auto push-to-talk"))
        ptt.clicked.connect(lambda: mw.setctl.open_settings("hotkeys"))
        row.addWidget(ptt)
        row.addStretch(1)
        done = QPushButton(_("Done"))
        done.setObjectName("primary")
        done.clicked.connect(self.accept)
        row.addWidget(done)
        v.addLayout(row)


class MeetingGuide(QDialog):
    """Calls in other apps: Zoom, Microsoft Teams, and calls in a web page (Google
    Meet, Discord in a browser). Their menus differ, so each gets its own few lines."""

    def __init__(self, parent, mw, vm: str, kept: bool = False):
        super().__init__(parent)
        fit.watch(self)
        self.setWindowTitle(_("Zoom, Teams and browser calls: make your sounds come through "
                              "clean"))
        self.setMinimumWidth(600)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 18)
        v.setSpacing(12)
        v.addLayout(_header(_("Zoom, Teams and browser calls"), _label(
            _("Meeting apps clean up the mic for speech and treat music as background "
              "noise. Your sounds are already in your mic: keep it, and turn that cleanup "
              "down:") if kept else
            _("Meeting apps clean up the mic for speech and treat music as background "
              "noise. Pick the mic below and turn that cleanup down:")),
            _bun("headphones")))
        mic = f"<b style='color:{_ok()}'>{html.escape(vm)}</b>"
        v.addWidget(_label(_steps(
            _("<b>Zoom</b>: Settings → Audio → Microphone: {mic}. Untick <b>Automatically "
              "adjust microphone volume</b>, set <b>Background noise suppression</b> to "
              "<b>Low</b>, or pick <b>Original sound for musicians</b> (then turn it on in "
              "the meeting, top left).", mic=mic),
            _("<b>Microsoft Teams</b>: Settings → Devices → Microphone: {mic}. Set <b>Noise "
              "suppression</b> to <b>Off</b> or <b>Low</b>, or switch on <b>Music mode</b> / "
              "<b>High fidelity music mode</b> if it's there.", mic=mic),
            _("<b>In a browser</b> (Google Meet, Discord or Guilded in a web page): the "
              "call's own settings → Microphone: {mic}, and turn off <b>Noise "
              "cancellation</b> / <b>noise suppression</b> where the site has it.", mic=mic),
            _("On the Setup tab, set <b>Who's listening</b> to <b>Voice chat</b>. It picks "
              "the browser shaping by itself once the call is listening."))))
        row = QHBoxLayout()
        copy = QPushButton(_("Copy the mic name"), self)   # parent: see test_no_flash_windows
        icons.set_icon(copy, "copy")
        copy.clicked.connect(lambda: (QApplication.clipboard().setText(vm),
                                      busy.flash(copy, _("✓  Copied"))))
        copy.setVisible(not kept)   # straight into the mic: nothing to pick
        row.addWidget(copy)
        row.addStretch(1)
        done = QPushButton(_("Done"))
        done.setObjectName("primary")
        done.clicked.connect(self.accept)
        row.addWidget(done)
        v.addLayout(row)


def show_guide(which: str, parent, mw, vm: str):
    """Open one guide modally: 'discord', 'game', 'meeting' or 'steam'. Straight into
    the mic, the guides name the user's own mic (there's nothing to switch to)."""
    kept = on_mic(mw)
    if kept:
        vm = mw.cfg.mic_device or _("your mic")
    if which == "steam":
        from soundboard.ui.setup.setupwizard import SteamGuide
        g = SteamGuide(parent, vm)
    elif which == "game":
        g = GameGuide(parent, mw, vm, kept)
    elif which == "meeting":
        g = MeetingGuide(parent, mw, vm, kept)
    else:
        g = DiscordGuide(parent, mw, vm, kept)
    g.exec()
    free_dialog(g)
