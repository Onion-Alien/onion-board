"""The Steam voice chat help: where Steam picks the mic, and its noise cancellation."""
from __future__ import annotations

import html

from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QPushButton, QVBoxLayout

from soundboard.ui.kit import busy, fit, icons
from soundboard.ui.bun.bunnywidget import BunnyWidget
from soundboard.i18n import _
from soundboard.ui.setup.chatguide import clean_mic_tip
from soundboard.ui.setup.wizardkit import BUN_H, BUN_PAD, _header, _label, _ok


class SteamGuide(QDialog):
    """Steam games with Steam voice chat (CS2, Dota 2, Deadlock, …) ignore Windows'
    mic and have no mic picker of their own: the microphone is chosen in the Steam
    client's Voice settings. And Steam's noise cancellation treats music as noise, so
    left on it chops up the sounds; this walks through all of it."""

    def __init__(self, parent, mic_name: str, mw=None):
        super().__init__(parent)
        fit.watch(self)   # grows to fit its text (ui/kit/fit.py)
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
            + small.format(_("They think music is background noise and cut your sounds "
                             "up.")),
            clean_mic_tip(mw),
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
