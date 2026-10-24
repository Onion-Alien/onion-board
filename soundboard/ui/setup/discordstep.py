"""The setup guide's last step: telling Discord (or a game, Steam, OBS) to use the
mic the sounds go into, read back from Discord's own settings. Mixed into
SetupWizard."""
from __future__ import annotations

import html
import logging
import re

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from soundboard.mic import directmic, discordcfg
from soundboard.audio import engine as eng
from soundboard.core.pollthread import PollThread
from soundboard.ui.kit import busy, icons
from soundboard.ui.bun.bunnywidget import BunnyWidget
from soundboard.ui.kit.choicetile import FoldPill
from soundboard.i18n import _
from soundboard.ui.setup.wizardkit import (BUN_H, BUN_PAD, HEADER_GAP, SECTION_GAP,
                                           SETTLE_MS, TITLE_CSS, _bad, _card, _header,
                                           _label, _ok, WizardStep)

log = logging.getLogger(__name__)


# ...on one kept thread for every guide: a new thread each time made the window wait in
# Thread.start (2.2.2's freeze at _read_discord, pollthread.py)
_DISCORD_POLL = PollThread("setup-discord-read")


class DiscordStep(WizardStep):
    """SetupWizard's Discord step."""

    def _page_discord(self) -> QWidget:
        p = QWidget()
        v = QVBoxLayout(p)
        v.setSpacing(8)
        self.discord_text = _label("")
        self.discord_title = _label(self._discord_heading(), TITLE_CSS)
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
        nomic.clicked.connect(self.win.micctl.open_windows_mic)
        row.addWidget(nomic)
        row.addStretch(1)
        v.addSpacing(HEADER_GAP - 8)
        v.addWidget(self.helper_row)
        # straight into the mic, Discord needs nothing picked, but its own noise filter
        # (on by default) wipes sounds out: the tip's card starts open under its pill,
        # with Discord's settings read live (a tip shut by default was missed, and
        # people from Discord thought the app was broken)
        self.discord_fold = FoldPill(_("Discord: one setting worth changing"), "speech")
        self.discord_fold.toggled.connect(self._fold_discord)
        fold_row = QHBoxLayout()
        fold_row.addWidget(self.discord_fold)
        fold_row.addStretch(1)
        v.addLayout(fold_row)
        self._discord_open = True
        self.discord_body, body = _card(14, 8, roomy=False)
        # what Discord's own files say (chatguide.settings_html): ✓, or what to switch
        self.discord_live = _label("", "font-size:10pt;")
        self.discord_live.hide()
        body.addWidget(self.discord_live)
        self.discord_tip = _label("", "font-size:10pt;")
        body.addWidget(self.discord_tip)
        self.btn_discord = QPushButton(_("Discord: make my sounds come through clean"))
        icons.set_icon(self.btn_discord, "speech", "on_accent")
        self.btn_discord.setObjectName("primary")
        self.btn_discord.setToolTip(_("The Discord settings that stop it chopping up your "
                                      "sounds, and a check that listens to what Discord does"))
        self.btn_discord.clicked.connect(self._set_up_discord)
        body.addWidget(self.btn_discord, 0, Qt.AlignmentFlag.AlignLeft)
        v.addSpacing(8)
        v.addWidget(self.discord_body)
        # games and calls: their guides, in a card of their own
        self.help_card, cl = _card(14, 8, roomy=False)
        self._fold_discord(True)
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
        self.closing = _label("", "font-size:10pt;")   # (_fill_discord)
        v.addWidget(self.closing)
        return p

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
        # nothing in it (not on the mic yet, sounds only for me, no cable): no empty box
        # between the words and the closing line
        filled = tip or bool(self.discord_live.text()) or not self.btn_discord.isHidden()
        self.discord_body.setVisible(filled and (self._discord_open or not tip))

    def _fill_discord(self):
        self.discord_tip.setText("")
        self._live_kept: bool | None = None   # (_fill_discord_text: Discord's settings count)
        self._fill_discord_text()
        self._show_live()
        self.closing.setText(
            _("That's it. Add sounds by dragging files onto the window, then click one "
              "to play it. You can open this guide again any time from the <b>Setup</b> "
              "tab (<b>Step-by-step guide</b>)."))
        games = not self.btn_steam.isHidden()
        self.games_label.setVisible(games)
        streamer = self.win.cfg.use_mode == "streamer"
        self.btn_streamer.setVisible(streamer)
        self.help_card.setVisible(games or streamer)
        self.helper_row.setVisible(not (self.btn_copy.isHidden() and self.btn_nomic.isHidden()))

    def _fill_discord_text(self):
        cfg = self.win.cfg
        dev = self.win.routectl._main_name()
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
            and not name else self._discord_heading())
        if cfg.route == "off":
            self.discord_text.setText(
                _("Your sounds play only for you: in your headphones, where OBS's <b>Desktop "
                  "Audio</b> picks them up, and on a device set to <b>Clean, for streaming</b> "
                  "(Setup → Devices → Also play on).<br><br>Nothing to change in Discord or "
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
                _("<span style='color:{colour}'>Only you will hear your sounds for now.</span> "
                  "Go <b>Back</b> and click <b>Put my sounds straight into my mic</b>, or finish "
                  "now and this guide opens again next time.", colour=_bad()))
            self.btn_copy.hide()
            self.btn_discord.hide()
            return
        self.btn_copy.show()
        self.btn_discord.show()
        self._live_kept = False   # on the cable: Studio is the clean choice there
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
            self.discord_title.setText(self._discord_heading())
            self.discord_text.setText(
                _("<span style='color:{colour}'>Onion Board isn't on your mic yet, so only "
                  "you will hear your sounds.</span> Go <b>Back</b> and press <b>Put my sounds "
                  "in my mic</b> (or use the virtual cable), or finish now and this guide will "
                  "open again next time.", colour=_bad()))
            self.btn_discord.hide()
            return
        # nothing to pick, but Discord's own noise filter (on by default) wipes sounds
        # out: the step says so, with Discord's settings checked live under it
        self.discord_title.setText(_("Last step: check Discord"))
        self.btn_discord.show()
        self._live_kept = True
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
        self.discord_text.setText(
            _("Your sounds are in <b style='color:{colour}'>{mic}</b> now, so there's nothing "
              "to pick in Discord or your games. One thing can still stop them: Discord's own "
              "noise filter, which is on by default.", colour=_ok(), mic=mic))
        if sep:
            # its bold lead-in ("One thing worth doing in Discord:") is the pill's words
            self.discord_tip.setText(re.sub(r"^\s*<b>[^<]*</b>\s*", "", tip) or tip)

    # Discord's own settings, read from its files (discordcfg) while the last step is
    # up: a ✓, or what to switch, ticking itself off as they change it in Discord
    def _read_discord(self):
        if self._discord_reading:
            return
        self._discord_reading = True
        last = self._discord_sig
        _DISCORD_POLL.run(lambda: self._discord_worker(last))

    def _discord_worker(self, last):
        try:
            sig = discordcfg.signature()
            found = None if sig == last else discordcfg.read()
        except Exception:  # noqa: BLE001 - never leave _discord_reading stuck
            log.debug("reading Discord's settings failed", exc_info=True)
            sig, found = last, None
        busy.emit(self._discord_read, sig, found)

    def _discord_in(self, sig, found):
        self._discord_reading = False
        if found is None:   # unchanged since the last read (or it failed): as it is
            return
        self._discord_sig, self._discord_found = sig, found
        self._show_live()

    def _show_live(self):
        """Discord's settings as read, in the tip's card: when there's an answer, it
        takes the place of the general tip (it says what to switch, or ✓)."""
        from soundboard.ui.setup import chatguide
        found = self._discord_found
        text = (chatguide.settings_html(found, self._live_kept)
                if found and self._live_kept is not None else "")
        if text != self.discord_live.text():
            self.discord_live.setText(text)
        self.discord_live.setVisible(bool(text))
        self.discord_tip.setVisible(bool(self.discord_tip.text()) and not text)
        self._show_discord_body()

    def _set_up_discord(self):
        """The Discord step's button: Bun sets it (as every Discord button does); this
        step's own words say what's left to pick on the cable."""
        from soundboard.ui.setup.chatguide import set_up_discord
        set_up_discord(self.win, self, then=lambda: None)

    def show_steam_guide(self):
        self.show_guide("steam")

    def show_streamer_guide(self):
        from soundboard.ui.kit.crashdialog import free_dialog
        from soundboard.ui.setup.streamguide import StreamerGuide
        g = StreamerGuide(self, self.win)
        g.exec()
        free_dialog(g)

    def show_guide(self, which: str):
        from soundboard.ui.setup.chatguide import show_guide
        show_guide(which, self, self.win, self._vm)

    def copy_name(self):
        QApplication.clipboard().setText(self._vm)
        busy.flash(self.btn_copy, _("✓  Copied"))
