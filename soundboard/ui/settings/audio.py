"""Settings → Audio: devices, the mic, the voices and who's listening."""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from soundboard.i18n import _, ngettext
from soundboard.ui.kit import busy, icons
from soundboard.ui.settings import Page, _button_row
from soundboard.ui.kit.wheelguard import no_wheel
from soundboard.ui.window.responsive import settled


class _DeviceBox(QComboBox):
    """A device box: as wide as `want` while there's room (whole names, one width for the
    column), narrower when there isn't, so the page never goes wider than the window."""
    want = 0

    def sizeHint(self):
        hint = super().sizeHint()
        if self.want:
            hint.setWidth(self.want)
        return hint

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(120)
        return hint


class AudioTabs(QWidget):
    """The Audio page's tabs: a row of chips (the look box's on Appearance) over one group
    of cards at a time. All on one page it was too much for a new user to take in. A tab
    with no card to show has no chip (Sound driver off the mic route, Voices without the
    Voice tab). A search shows every card it finds, whichever tab it's on, without the row."""

    def __init__(self):
        super().__init__()
        from soundboard.ui.kit.panel import Flow   # (it imports this module)
        self._v = QVBoxLayout(self)
        self._v.setContentsMargins(0, 0, 0, 0)
        self._v.setSpacing(12)
        self.bar = QWidget()
        self._flow = Flow(self.bar, gap=8)
        self._v.addWidget(self.bar)
        self.group = QButtonGroup(self)
        self.group.idClicked.connect(self.show_tab)
        self.keys: list[str] = []
        self.chips: list[QPushButton] = []
        self.pages: list[QWidget] = []
        self.shown = 0
        self.searching = False

    def add(self, key: str, name: str) -> QVBoxLayout:
        """A new tab; its cards go in the layout this returns."""
        chip = QPushButton(name)
        chip.setObjectName("voicetab")   # the same tabs as Appearance's
        chip.setCheckable(True)
        chip.setAutoDefault(False)
        chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.group.addButton(chip, len(self.chips))
        self._flow.addWidget(chip)
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self._v.addWidget(page)
        self.keys.append(key)
        self.chips.append(chip)
        self.pages.append(page)
        return lay

    def done(self):
        """Every card is in: follow them as they come and go (Show advanced, the route,
        the Voice tab) and show the first tab."""
        for page in self.pages:
            for card in page.findChildren(QFrame, "setcard"):
                card.installEventFilter(self)
        self.show_tab(0)
        self.sync()

    def eventFilter(self, obj, e):
        if e.type() in (QEvent.Type.ShowToParent, QEvent.Type.HideToParent) \
                and not self.searching:
            self.sync()
        return super().eventFilter(obj, e)

    @staticmethod
    def _has_cards(page: QWidget) -> bool:
        return any(not c.isHidden() for c in page.findChildren(QFrame, "setcard"))

    def sync(self):
        """Searching: only the tabs with a card found take room. Otherwise: chips for the
        tabs with a card, and the one showing has to be one of them."""
        if self.searching:
            for page in self.pages:
                page.setVisible(self._has_cards(page))
            return
        for chip, page in zip(self.chips, self.pages):
            chip.setVisible(self._has_cards(page))
        self.show_tab(self.shown if not self.chips[self.shown].isHidden() else 0)

    def show_tab(self, i: int):
        self.shown = i
        self.chips[i].setChecked(True)
        if not self.searching:
            for j, page in enumerate(self.pages):
                page.setVisible(j == i)

    def open_tab(self, key: str):
        """Go to the tab `key`, when it has anything to show."""
        i = self.keys.index(key)
        if not self.chips[i].isHidden():
            self.show_tab(i)

    def search(self, on: bool):
        """Before a search goes through the cards (`on`: it has words): every tab open for
        it to look through. Its cards come and go next: nothing follows them until `searched`."""
        self.searching = True
        self.bar.setVisible(not on)
        if on:
            for page in self.pages:
                page.show()

    def searched(self, on: bool):
        """After it: the tabs it found something on, or (no words) the tab that was showing."""
        self.searching = on
        self.sync()


class AudioPage(Page):
    """Settings → Audio: devices, the mic, the voices and who's listening, a tab each."""

    def _audio(self):
        w, v = self._page()
        tabs = self.dlg.audio_tabs = AudioTabs()
        v.addWidget(tabs)
        v.addStretch(1)
        mic = tabs.add("mic", _("Mic and speakers"))
        listening = tabs.add("listening", _("Who's listening"))
        voices = tabs.add("voices", _("Voices"))
        driver = tabs.add("driver", _("Sound driver"))
        # Setup's Your mic card on top, the same live card (CardVisit)
        from soundboard.ui.setup.cardhome import CardVisit
        mic.addWidget(CardVisit(self.mw.how_home))
        mic.addWidget(self._devices_card())
        from soundboard.ui.setup.audiorecovery import RecoveryCard
        adv = self.dlg._advanced_only   # (Show advanced: the expert cards)
        driver.addWidget(RecoveryCard(self.mw))   # (stays: it fixes the default, mic route)
        card, cv = self._card(_("Send my mic"),
                              _("Normally others hear your voice and your sounds together. "
                                "Untick this for sounds only: they hear the sounds but not your "
                                "mic. (Same as the “Others hear it” box under My mic.)"),
                              icon="mic")
        send = QCheckBox(_("Send my mic to others"))
        send.setChecked(self.mw.cfg.mic_enabled)
        send.toggled.connect(self.mw.chk_mic.setChecked)   # the window applies it
        # and back: the bottom strip, the mini player, a hotkey or the remote changed it
        self.mw.chk_mic.toggled.connect(send.setChecked)
        self.mw.mini_mic.toggled.connect(send.setChecked)   # (it sets chk_mic silently)
        cv.addWidget(send)
        mic.addWidget(adv(card))   # (the footer's Others hear it is the everyday one)
        voices.addWidget(self._clean_card())
        voices.addWidget(adv(self._voices_card(), also=lambda: self.mw.tabctl.tab_on("voice")))
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
        listening.addWidget(card)
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
        # its words whole (the page's boxes are sized for six letters): the theme's padding, arrow
        lat.setMinimumWidth(max(lat.fontMetrics().horizontalAdvance(lat.itemText(i))
                                for i in range(lat.count())) + 60)
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
        mic.addWidget(adv(card))
        more = QPushButton(_("More audio settings"))
        more.setToolTip(_("Speech voices, buffering and your mic switch (Show advanced)"))
        icons.set_icon(more, "sliders")
        more.clicked.connect(lambda: self.dlg._set_advanced(True))
        mic.addWidget(adv(more, show_when_basic=True), 0, Qt.AlignmentFlag.AlignLeft)
        tabs.done()
        return w

    def _clean_card(self):
        """Clean mic on with every voice (VoicePanel._clean_with_voice), on by default.
        Only with the Voice tab, where Clean mic and the voices are."""
        card, cv = self._card(_("Clean mic"),
                              _("When you turn on a voice, Clean mic goes on too, so the voice "
                                "comes out without your background noise. It goes off again "
                                "with the voice, unless you turned it on yourself."),
                              icon="mic")
        chk = QCheckBox(_("Turn on Clean mic with a voice"))
        chk.setChecked(self.mw.cfg.clean_with_voice)
        chk.toggled.connect(lambda on: self.mw.set_option("clean_with_voice", on))
        cv.addWidget(chk)
        if not self.mw.tabctl.tab_on("voice"):
            card.hide()   # (never show() it here: not in its page yet)
        self.dlg.clean_card = card
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
        """The output picker: the Setup tab's Devices box, mirrored here so people find
        it where they look first (the mic's is on Your mic, above). Picking goes through
        the window."""
        from soundboard.ui.kit.panel import icon_button   # (it imports this module)
        mw = self.mw
        ref = icon_button("reload", _("Re-scan devices"))
        ref.clicked.connect(lambda: mw.devctl.rescan_with_feedback(ref, self._sync_devices))
        card, cv = self._card(_("Speakers and headphones"), icon="headphones", end=(ref,))
        # what people searched for before it had this name
        card.setProperty("search_words", f'{_("Devices")} {_("Output")}')
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        self.dlg.dev_combos = []
        for r, text, src, attr in (
                (0, _("Play on"), mw.cb_mon, "mon_device"),):
            cb = _DeviceBox()
            cb.setAccessibleName(text)   # its label beside it, for a screen reader
            cb.setMinimumWidth(120)
            # sized for a short name, the list opens wide enough for whole ones (long
            # device names made the page scroll sideways)
            cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(16)
            no_wheel(cb)
            cb.activated.connect(lambda i, src=src, attr=attr: self._pick_device(src, attr, i))
            label = QLabel(text)
            label.setProperty("keepline", True)   # (wrapped with room to spare)
            grid.addWidget(label, r, 0)
            grid.addWidget(cb, r, 1)
            self.dlg.dev_combos.append((cb, src))
        grid.setColumnStretch(2, 1)   # the room past the boxes, not the boxes' column
        cv.addLayout(grid)
        from soundboard.ui.setup import alsosend  # (it imports this module)
        # once the grid is in the card: a row added before would be its own window
        alsosend.build(mw, grid, 1, icons_col=False)   # kept up to date by mw
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
        # its widest name's width
        wide = max(max((cb.fontMetrics().horizontalAdvance(cb.itemText(i))
                        for i in range(cb.count())), default=0)
                   for cb, _src in self.dlg.dev_combos) + 60   # (the theme's padding and arrow)
        for cb, _src in self.dlg.dev_combos:
            if cb.want != wide:
                cb.want = wide
                cb.updateGeometry()

    def _pick_device(self, src, attr, i):
        with settled(self.dlg):   # the boxes and the rows a new device changes: at once
            src.setCurrentIndex(i)
            self.mw.routectl.on_device(src, attr)
            self._sync_devices()
