"""Asked on leaving Settings when "Send my sounds to" was just set to a device that
isn't a mic or a virtual cable (speakers, a headset, a monitor's audio): Discord and
games don't hear what plays there, so most people picked it by mistake. Offers the
two ways that do reach voice chat (straight into the mic, or the virtual cable) and
keeping it as it is."""
from __future__ import annotations

import html

from PySide6.QtWidgets import (QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout)

from soundboard.i18n import _
from soundboard.ui.kit import fit
from soundboard.ui.kit.panel import hint_label

MIC, CABLE = 1, 2   # finished() codes past Rejected (0, = keep it)


def needs_warning(route: str, device: str | None, headphones: str | None) -> bool:
    """A device that isn't a virtual cable gets the question; the cable never does.
    The headphones have their own hint in Setup (nothing is sent there at all)."""
    from soundboard.audio.engine import is_virtual
    return route == "device" and bool(device) and not is_virtual(device) \
        and device != headphones


class RouteWarning(QDialog):
    """[Use my mic] / [Use the virtual cable] or [Install a virtual cable] / [Keep it]:
    finishes with MIC, CABLE or Rejected (Esc and Keep leave it as it is)."""

    def __init__(self, device: str, cable_installed: bool, parent=None):
        super().__init__(parent)
        title_text = _("Discord and games won't hear your sounds")
        self.setWindowTitle(title_text)
        self.setMaximumWidth(620)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(12)
        title = QLabel(title_text)
        title.setObjectName("helptitle")
        v.addWidget(title)
        name = html.escape(device)
        v.addWidget(hint_label(_(
            "They now go to <b>{device}</b>, a normal speaker or headset, so only you hear "
            "them. Pick a way that reaches voice chat:", device=name)))
        # the two ways in, each with what it means beside it
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        self.to_mic = QPushButton(_("Use my mic"))
        self.to_mic.setObjectName("primary")
        self.to_mic.setDefault(True)
        self.to_mic.clicked.connect(lambda: self.done(MIC))
        self.to_cable = QPushButton(_("Use the virtual cable") if cable_installed
                                    else _("Install a virtual cable"))
        self.to_cable.clicked.connect(lambda: self.done(CABLE))
        rows = ((self.to_mic, _("Straight into the mic you already use. Nothing to "
                                "install.")),
                (self.to_cable, _("A second mic to pick in Discord or the game.")
                 if cable_installed else
                 _("Free. Opens Setup and installs it, then you pick it as the mic in "
                   "Discord or the game.")))
        for i, (btn, text) in enumerate(rows):
            grid.addWidget(btn, i, 0)
            grid.addWidget(hint_label(text), i, 1)
        grid.setColumnStretch(1, 1)
        v.addLayout(grid)
        v.addWidget(hint_label(_("Meant for OBS, Voicemeeter or a mixer? Keep it.")))
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        self.keep = QPushButton(_("Keep it"))
        self.keep.clicked.connect(self.reject)
        row.addWidget(self.keep)
        v.addLayout(row)
        fit.watch(self)
