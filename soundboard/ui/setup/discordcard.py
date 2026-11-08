"""Discord's card on the Setup tab, beside Your mic (`MainWindow.discord_card`): everything
about Discord in one place, and only once a Discord's settings can be read and your sounds
have a way out.

**Discord mode** on: Discord's own filters are off, so sounds and voice effects get through
(chatguide.DiscordSetUp). Off: they're back the way you talk (discordtalk.restore).
Discord only takes either while it's closed: open, it's asked first, closed, and opened
again. **Clean mic** is the Voice tab's own switch: with Discord's filters off, it takes the
background noise out of your voice instead. **Headphones or speakers** is what you hear
calls on (config hear_on, the same tiles as Settings → Audio): only headphones turn
Discord's echo cancellation off. The tick is `cfg.discord_restore`: Discord
mode goes off by itself when Onion Board closes (AlertControl.discord_quit).

What the switch shows is read from Discord's own files (discordcfg): someone can change
them in Discord, and it follows.
"""
from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMessageBox, QVBoxLayout

from soundboard.i18n import _
from soundboard.mic import discordcfg
from soundboard.ui.kit import busy, icons, theme
from soundboard.ui.kit.panel import card, hint_label, info_button
from soundboard.ui.kit.wrapbutton import WrapCheck
from soundboard.ui.setup import chatguide
from soundboard.ui.voice.fxcontrols import Switch

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

log = logging.getLogger(__name__)

FIRST_READ_MS = 2500   # Discord's files are read a moment after the window is up


class DiscordCard(QObject):
    # the width each of Setup's two columns needs beside this card: narrower, the words in
    # Your mic and here get cut, so the cards stack instead (FitControl._setup_need)
    MIN_W = 470
    _read = Signal(object)    # [discordcfg.Settings], from a worker
    _asked = Signal(object)   # what needs putting back and what's open, from a worker
    _back = Signal(object, object)   # what needed putting back, what's still open

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self.mw = mw
        self.wanted = False    # your sounds have a way out (the same as the other voice apps)
        self.shown = False
        self.switching = False
        self._target = False   # where the switch is heading while it's switching
        self._reading = 0      # looks at Discord's files still under way
        self._clean_seen = None   # the Clean mic its switch follows
        self.btn_info = info_button(_("How Discord and your sounds work"))
        self.btn_info.clicked.connect(self._show_help)
        self.pill = QLabel()
        self.pill.setObjectName("pill")
        self.frame, v = card("Discord", roomy=True, icon="speech", beside=(self.btn_info,),
                             end=(self.pill,))
        self.mode_row, self.mode_why, self.mode = self._line(v, "speech", _("Discord mode"))
        self.clean_row, self.clean_why, self.clean = self._line(v, "mic", _("Clean mic"))
        self.hear_row, self.hear_why, self.hear = self._hear_line(v, mw.cfg.hear_on)
        self.hear.picked.connect(self._hear_picked)
        self.chk_off = WrapCheck(_("Turn Discord mode off when I close Onion Board"))
        self.chk_off.setToolTip(
            _("Discord's noise suppression, echo cancellation and automatic volume go back "
              "on the way you had them, so your plain voice sounds right without Onion "
              "Board. If Discord is still open, it's done the moment you close it."))
        self.chk_off.setChecked(bool(mw.cfg.discord_restore))
        self.chk_off.toggled.connect(lambda on: mw.set_option("discord_restore", on))
        v.addWidget(self.chk_off)
        v.addStretch(1)
        self.mode.clicked.connect(self._mode_clicked)
        self.clean.clicked.connect(self._clean_clicked)
        self._read.connect(self._on_read)
        self._asked.connect(self._on_asked)
        self._back.connect(self._on_back)
        self.frame.hide()
        QTimer.singleShot(FIRST_READ_MS, self, self.read)

    @staticmethod
    def _line(v: QVBoxLayout, icon: str, name: str) -> tuple[QFrame, QLabel, Switch]:
        """One setting: an icon, its name and what it's doing now, its switch at the end."""
        box = QFrame()
        box.setObjectName("micstatus")
        row = QHBoxLayout(box)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(10)
        pic = QLabel()
        pic.setFixedSize(20, 20)
        icons.set_label_icon(pic, icon, "text", size=20)
        row.addWidget(pic, 0, Qt.AlignmentFlag.AlignTop)
        words = QVBoxLayout()
        words.setSpacing(2)
        title = QLabel(name)
        title.setObjectName("section")
        words.addWidget(title)
        why = hint_label("")
        words.addWidget(why)
        row.addLayout(words, 1)
        switch = Switch(name, hover=False)
        row.addWidget(switch, 0, Qt.AlignmentFlag.AlignVCenter)
        v.addWidget(box)
        return box, why, switch

    @staticmethod
    def _hear_line(v: QVBoxLayout, current: str):
        """Headphones or speakers: its name and what it means now, the two tiles below."""
        from soundboard.ui.setup.audiorecovery import HearOnTiles
        box = QFrame()
        box.setObjectName("micstatus")
        col = QVBoxLayout(box)
        col.setContentsMargins(12, 10, 12, 10)
        col.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(10)
        pic = QLabel()
        pic.setFixedSize(20, 20)
        icons.set_label_icon(pic, "headphones", "text", size=20)
        row.addWidget(pic, 0, Qt.AlignmentFlag.AlignTop)
        words = QVBoxLayout()
        words.setSpacing(2)
        title = QLabel(_("Headphones or speakers?"))
        title.setObjectName("section")
        words.addWidget(title)
        why = hint_label("")
        words.addWidget(why)
        row.addLayout(words, 1)
        col.addLayout(row)
        tiles = HearOnTiles(current, box)
        col.addWidget(tiles)
        v.addWidget(box)
        return box, why, tiles

    # ------------------------------------------------------------------ what it shows
    def set_wanted(self, on: bool):
        """Your sounds have a way out, or not (StatusControl)."""
        self.wanted = on
        self.refresh()

    def read(self):
        """Discord's settings, on a worker: AlertControl only reads them while Discord
        runs, and this card shows them while it's closed too."""
        self._reading += 1

        def work():
            found: list = []
            try:
                found = discordcfg.read()
            except Exception:  # noqa: BLE001 - a look that can't run shows nothing
                log.debug("reading Discord's settings failed", exc_info=True)
            busy.emit(self._read, found)
        threading.Thread(target=work, daemon=True, name="discord-card").start()

    def _on_read(self, found: list):
        self._reading -= 1
        self.mw.alertctl.set_discord_found(found)   # (which refreshes this card)

    def mode_on(self) -> bool:
        """Discord is set so sounds and voice effects get through (what discordtalk.set_up
        leaves it as, whoever set it)."""
        from soundboard.mic import discordtalk
        found = self.mw.alertctl.discord_found
        if not found:
            return False
        headphones = chatguide.on_headphones(self.mw)
        return (not found[0].problems(chatguide.raw_skips(self.mw), headphones)
                and not discordtalk.echo_wrong(found[0], headphones))

    def refresh(self):
        mw = self.mw
        show = self.wanted and bool(mw.alertctl.discord_found)
        if show != self.shown:
            self.shown = show
            mw.fitctl.place_discord(show)
        on = self.mode_on()
        # back on, here or in Discord: the bar can say again (not from what was read before
        # a switch: that still says on, just after it was turned off)
        if on and mw.cfg.discord_off and not self._reading:
            mw.set_option("discord_off", False)
        self._set(self.mode, self._target if self.switching else on)
        if self.switching:
            self.pill.setText(_("Switching…"))
            theme.set_tone(self.pill, "muted")
            self.mode_why.setText(_("Discord closes for a few seconds, then opens again."))
        elif on:
            self.pill.setText(_("Sounds get through"))
            theme.set_tone(self.pill, "ok")
            self.mode_why.setText(_("Your sounds and voice effects get through. Discord's own "
                                    "filters are off."))
        else:
            self.pill.setText(_("Sounds may cut out"))
            theme.set_tone(self.pill, "warn")
            self.mode_why.setText(_("Discord's own filters are on. They can cut your sounds "
                                    "and voice effects."))
        self._refresh_clean(on)
        self._refresh_hear()
        self.chk_off.blockSignals(True)
        self.chk_off.setChecked(bool(mw.cfg.discord_restore))
        self.chk_off.blockSignals(False)

    def _refresh_clean(self, mode_on: bool):
        """Clean mic's row: none without the Voice tab or the cleaner (chatguide.clean_mic)."""
        clean = chatguide.clean_mic(self.mw)
        self.clean_row.setVisible(clean is not None)
        if clean is None:
            return
        if clean is not self._clean_seen:
            self._clean_seen = clean
            clean.live_changed.connect(lambda _on: self.refresh())
        on = clean.is_on()
        self._set(self.clean, on)
        recommend = mode_on and not on
        if on:
            self.clean_why.setText(_("Takes background noise out of your voice, never your "
                                     "sounds."))
        elif recommend:
            self.clean_why.setText(_("Recommended: with Discord mode on, background noise "
                                     "gets through."))
        else:
            self.clean_why.setText(_("Discord's own filter is on, so you can leave this off."))
        theme.set_tone(self.clean_why, "warn" if recommend else "")

    def _refresh_hear(self):
        hear = self.mw.cfg.hear_on
        self.hear.set_current(hear)
        if hear == "headphones":
            self.hear_why.setText(_("Discord's echo cancellation goes off, so your sounds "
                                    "come through clean."))
        elif hear == "speakers":
            self.hear_why.setText(_("Discord's echo cancellation stays on, so what your PC "
                                    "plays doesn't go into your mic."))
        else:
            self.hear_why.setText(_(
                "What do you hear your calls on? On speakers your mic hears them too, so "
                "Discord's echo cancellation stays on to keep your PC's sound out of the "
                "call."))

    @staticmethod
    def _set(switch: Switch, on: bool):
        switch.blockSignals(True)
        switch.setChecked(on)
        switch.blockSignals(False)

    # ------------------------------------------------------------------ the switches
    def _clean_clicked(self, on: bool):
        clean = chatguide.clean_mic(self.mw)
        if clean is not None:
            clean.set_on(on)
        self.refresh()

    def _mode_clicked(self, on: bool):
        if self.switching or on == self.mode_on():   # (never disabled: it holds the focus)
            self.refresh()
            return
        self.switching, self._target = True, on
        self.refresh()
        if on:
            chatguide.set_up_discord(self.mw, quiet=True, after=self._switched)
        else:
            self._turn_off()

    def _hear_picked(self, key: str):
        """Headphones or speakers, picked here: saved, and with Discord mode on, Discord's
        echo cancellation changed to match (as Settings → Audio does it)."""
        mw = self.mw
        if key == mw.cfg.hear_on:
            return
        mw.cfg.hear_on = key
        mw.cfg.save()
        if self.mode_on() or self.switching:
            self.refresh()
            return
        was_on = self._mode_was_on(key)
        if was_on:
            self.switching, self._target = True, True
            self.refresh()
            chatguide.DiscordSetUp(mw, mw, echo_only=True, quiet=True,
                                   after=self._switched).start()
        else:
            self.refresh()

    def _mode_was_on(self, key: str) -> bool:
        """Discord mode was on with the answer before `key`: only echo cancellation is
        wrong now."""
        from soundboard.mic import discordtalk
        found = self.mw.alertctl.discord_found
        if not found:
            return False
        before = key != "headphones"   # the other answer
        return (not found[0].problems(chatguide.raw_skips(self.mw), before)
                and not discordtalk.echo_wrong(found[0], before))

    def _switched(self):
        """Over, however it went: the switch says what Discord is set to now."""
        self.switching = False
        self.read()
        self.refresh()

    def _turn_off(self, close: tuple[str, ...] = ()):
        """Discord's filters back the way you talk, on a worker (its files and processes).
        First what's open is only looked at, and asked about here. `close`: the answer."""
        saved = dict(self.mw.cfg.discord_talk)

        def work():
            from soundboard.mic import discordtalk
            from soundboard.sounds.library import APP_DIR
            todo, left = [], []
            try:
                todo = discordtalk.to_restore(saved)
                open_now = sorted(set(todo) & discordtalk.running_clients())
                if open_now and not close:
                    busy.emit(self._asked, open_now)
                    return
                if close:
                    discordtalk.close_clients(close)
                if todo:
                    left = discordtalk.restore(saved, APP_DIR / "discord-backup",
                                               only=set(todo), always=True)
            except Exception:  # noqa: BLE001 - said, never a stuck "Switching…"
                log.exception("turning Discord mode off failed")
                todo, left = ["?"], ["?"]
            busy.emit(self._back, todo, left)
        self._closed = bool(close)
        threading.Thread(target=work, daemon=True, name="discord-mode-off").start()

    def _on_asked(self, open_now: list[str]):
        box = QMessageBox(QMessageBox.Icon.Question, _("Close Discord for a moment?"), _(
            "Discord has to close for a few seconds while Bun changes its settings. It "
            "drops any call you're in. Bun opens it again right after."),
            parent=self.mw)
        box.setProperty("keep_open", True)   # a click outside isn't an answer
        yes = box.addButton(_("Close Discord and switch"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(_("Not now"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(yes)
        box.exec()
        box.deleteLater()
        if box.clickedButton() is yes:
            self._turn_off(tuple(open_now))
        else:
            self._switched()

    def _on_back(self, todo: list, left: list):
        from soundboard.ui.setup.audiorecovery import said_discord_back
        mw = self.mw
        said_discord_back(mw, todo, left)
        if not left:
            mw.set_option("discord_off", True)   # on purpose: no Fix Discord bar about it
        if self._closed and not left:
            busy.open_url(chatguide.DISCORD_VOICE_URL, None, mw,
                          failed=_("Couldn't open Discord. The link was"))
        self._switched()

    def _show_help(self):
        from PySide6.QtCore import Qt as _Qt

        from soundboard.ui.sounds.dialogs import TabHelpPopup
        box = TabHelpPopup(
            _("How Discord and your sounds work"),
            _("Discord's filters treat your sounds and voice effects as noise and cut them "
              "out. <b>Discord mode</b> turns those filters off for you. Switch it off and "
              "they go back on.<br><br>"
              "With them off, Discord stops cleaning your voice, so a fan or keyboard gets "
              "through. <b>Clean mic</b> does that job instead: it cleans only your voice, "
              "before your sounds are added.<br><br>"
              "Discord only takes these settings while it's closed, so switching closes and "
              "reopens it. Any call you're in drops."),
            parent=self.mw)
        box.body.setTextFormat(_Qt.TextFormat.RichText)   # (the bold)
        self.mw.tipctl._show_help(box, self.btn_info)
