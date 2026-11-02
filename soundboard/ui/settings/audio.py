"""Settings → Audio: devices, the mic, the voices and who's listening."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QLabel, QPushButton

from soundboard.i18n import _, ngettext
from soundboard.ui.kit import busy, icons
from soundboard.ui.settings import Page, _button_row
from soundboard.ui.kit.wheelguard import no_wheel
from soundboard.ui.window.responsive import settled


class AudioPage(Page):
    """Settings → Audio: devices, the mic, the voices and who's listening."""

    def _audio(self):
        w, v = self._page()
        v.addWidget(self._devices_card())
        from soundboard.ui.setup.audiorecovery import RecoveryCard
        adv = self.dlg._advanced_only   # (Show advanced: the expert cards)
        v.addWidget(RecoveryCard(self.mw))   # (stays: it fixes the default, mic route)
        card, cv = self._card(_("Your mic"),
                              _("Normally others hear your voice and your sounds together. "
                                "Untick this for sounds only: they hear the sounds but not your "
                                "mic. (Same as the “Others hear it” box under My mic.)"),
                              icon="mic")
        send = QCheckBox(_("Send my mic to others"))
        send.setChecked(self.mw.cfg.mic_enabled)
        send.toggled.connect(self.mw.chk_mic.setChecked)   # the window applies it
        cv.addWidget(send)
        v.addWidget(adv(card))   # (the footer's Others hear it is the everyday one)
        v.addWidget(self._clean_card())
        v.addWidget(adv(self._voices_card(), also=lambda: self.mw.tabctl.tab_on("voice")))
        card, cv = self._card(_("Who's listening"),
                              _("Voice chat squashes your sounds: mono, no deep bass, and in "
                                "some games nothing above 8-12 kHz. Pick where people hear you "
                                "and they're shaped to get through it. Game and Voice chat work "
                                "out the exact voice chat by themselves; Clean sends them "
                                "exactly as mixed; Advanced lets you pick it yourself."),
                              icon="ear")
        from soundboard.ui.setup.destpanel import DestPanel
        dest = DestPanel(self.mw)
        dest.chk_gate.setText(_("Mute mic during sounds"))
        cv.addWidget(dest)
        v.addWidget(card)
        card, cv = self._card(_("Audio buffering"),
                              _("Low keeps your voice and sounds as immediate as possible. If "
                                "the status line reports drop-outs (crackles, stutters), Safer "
                                "uses bigger buffers: a little more delay, far fewer drop-outs."),
                              icon="sliders")
        lat = QComboBox()
        lat.setAccessibleName(_("Audio buffering"))
        lat.addItem(_("Low (default)"), "low")
        lat.addItem(_("Safer: bigger buffers"), "high")
        lat.setCurrentIndex(max(0, lat.findData(self.mw.cfg.latency)))
        lat.currentIndexChanged.connect(lambda i: self.mw.devctl.set_latency(lat.itemData(i)))
        no_wheel(lat)
        cv.addWidget(lat)
        e = self.mw.engine
        xr = sum(e.xruns.values())
        stat = QLabel(_("Since start: {dropouts}, {reconnects}.",
                        dropouts=ngettext("{n} drop-out", "{n} drop-outs", xr),
                        reconnects=ngettext("{n} device reconnect", "{n} device reconnects",
                                            e.stalls)))
        stat.setObjectName("hint")
        cv.addWidget(stat)
        v.addWidget(adv(card))
        more = QPushButton(_("More audio settings"))
        more.setToolTip(_("Speech voices, buffering and your mic switch (Show advanced)"))
        icons.set_icon(more, "sliders")
        more.clicked.connect(lambda: self.dlg._set_advanced(True))
        v.addWidget(adv(more, show_when_basic=True), 0, Qt.AlignmentFlag.AlignLeft)
        v.addStretch(1)
        return w

    def _clean_card(self):
        """Clean mic on with every voice (VoicePanel._clean_with_voice), on by default.
        Only with the Voice tab, where Clean mic and the voices are."""
        card, cv = self._card(_("Clean mic"),
                              _("When you turn on a voice, Clean mic goes on too, so the voice "
                                "comes out without your background noise. Turning the voice "
                                "off leaves Clean mic as it is."),
                              icon="mic")
        chk = QCheckBox(_("Turn on Clean mic with a voice"))
        chk.setChecked(self.mw.cfg.clean_with_voice)
        chk.toggled.connect(lambda on: self.mw.set_option("clean_with_voice", on))
        cv.addWidget(chk)
        if not self.mw.tabctl.tab_on("voice"):
            card.hide()   # (never show() it here: not in its page yet)
        return card

    def _voices_card(self):
        """Custom text-to-speech voices live on the Voice tab (behind Add voices); this
        card is where people look for them first. Hidden while the tab is switched off
        (Settings > Tabs), and its buttons reach the Voice tab there now: switched off
        and on again while Settings is open, that's a new one."""
        from soundboard.speech import customvoices
        mw = self.mw
        card, cv = self._card(
            _("Custom voices (text-to-speech)"),
            _("Your own voices for typed lines and the text-to-speech voice: a TTS server "
              "running on your PC (Kokoro, AllTalk, any OpenAI-style one), a TTS program, or "
              "Piper voice packs dropped into the voices folder. They join the Voice list on the "
              "Voice tab."), icon="speech")
        row = _button_row()   # one line, wrapping only when the window is narrow
        add = QPushButton(_("Add a voice server"))
        icons.set_icon(add, "plus")
        add.clicked.connect(
            lambda: mw.tabctl.tab_on("voice") and mw.voice.speech._add_voice_server())
        row.addWidget(add)
        folder = QPushButton(_("Open voices folder"))
        folder.setToolTip(_("Voice packs and voice settings go here; README.txt in it says how"))
        folder.clicked.connect(lambda: busy.open_folder(customvoices.ensure_folder, folder))
        row.addWidget(folder)
        show = QPushButton(_("Show on the Voice tab"))

        def go():
            if not mw.tabctl.tab_on("voice"):
                return
            self.dlg.accept()
            mw.tabs.setCurrentWidget(mw.voice)
            mw.voice.speech.show_custom_voices()
        show.clicked.connect(go)
        row.addWidget(show)
        cv.addLayout(row)
        self.dlg.voices_card, self.dlg.voices_show = card, show
        if not mw.tabctl.tab_on("voice"):   # (never show() it here: not in its page yet, it'd
            card.hide()              # flash up as a little window of its own)
        return card

    def _devices_card(self):
        """Input / output pickers: the Setup tab's Devices combos, mirrored here so
        people find them where they look first. Picking goes through the window."""
        mw = self.mw
        card, cv = self._card(_("Devices"),
                              _("Your mic (input) and where you listen (output). Your sounds go "
                                "into your mic unless you pick somewhere else to send them. "
                                "Plugged something in? Press Re-scan."), icon="headphones")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        self.dlg.dev_combos = []
        for r, (text, src, attr) in enumerate((
                (_("Input: my mic"), mw.cb_mic, "mic_device"),
                (_("Output: my headphones"), mw.cb_mon, "mon_device"),
                (_("Send my sounds to"), mw.cb_route, "route"))):
            cb = QComboBox()
            cb.setAccessibleName(text)   # its label beside it, for a screen reader
            cb.setMinimumWidth(120)
            # sized for a short name, the list opens wide enough for whole ones (device
            # names in "Send my sounds to" made the page scroll sideways)
            cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(16)
            no_wheel(cb)
            cb.activated.connect(lambda i, src=src, attr=attr: self._pick_device(src, attr, i))
            label = QLabel(text)
            grid.addWidget(label, r, 0)
            grid.addWidget(cb, r, 1)
            self.dlg.dev_combos.append((cb, src))
        grid.setColumnStretch(2, 1)   # the room past the boxes, not the boxes' column
        cv.addLayout(grid)
        from soundboard.ui.setup import alsosend  # (its panel import imports this module)
        # once the grid is in the card: a row added before would be its own window
        alsosend.build(mw, grid, grid.rowCount(), icons_col=False)   # kept up to date by mw
        ref = QPushButton(_("Re-scan devices"))
        icons.set_icon(ref, "reload")
        ref.clicked.connect(lambda: mw.devctl.rescan_with_feedback(ref, self._sync_devices))
        cv.addWidget(ref, 0, Qt.AlignmentFlag.AlignLeft)
        self._sync_devices()
        return card

    def _sync_devices(self):
        for cb, src in self.dlg.dev_combos:
            items = [(src.itemText(i), src.itemData(i)) for i in range(src.count())]
            # the same devices: left as they are (emptied and filled again, each box
            # shrank for a frame and the row beside it slid across and back)
            if items != [(cb.itemText(i), cb.itemData(i)) for i in range(cb.count())]:
                cb.clear()
                for text, data in items:
                    cb.addItem(text, data)
                cb.view().setMinimumWidth(cb.view().sizeHintForColumn(0) + 32)   # whole names
            if cb.currentIndex() != src.currentIndex():
                cb.setCurrentIndex(src.currentIndex())

    def _pick_device(self, src, attr, i):
        with settled(self.dlg):   # the boxes and the rows a new device changes: at once
            src.setCurrentIndex(i)
            self.mw.routectl.on_device(src, attr)
            self._sync_devices()   # "Send my sounds to" never offers the headphones
