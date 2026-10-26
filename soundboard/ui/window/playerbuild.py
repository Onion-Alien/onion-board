"""Building the main window's mini player and its mixer strip (ui/window/windowbuild.py).

A mixin WindowBuilder inherits, so every `self.` lookup is the same as before; it runs
once, on the UI thread, while the window is made."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOptionButton,
    QStylePainter,
    QVBoxLayout,
    QWidget,
)

from soundboard.core import usage
from soundboard.i18n import _
from soundboard.ui.kit import icons
from soundboard.ui.apps.appspanel import ElidedLabel
from soundboard.ui.window.buncontrol import BUN_TIP
from soundboard.ui.window.downloadbar import DownloadBar
from soundboard.ui.kit.iconrow import CapIcon
from soundboard.ui.kit.panel import (
    BAR_H,
    VolumeControl,
    steady_number,
    vsep,
)
from soundboard.ui.kit.playbutton import PlayButton
from soundboard.ui.kit.widgets import (
    EdgeMatch,
    Meter,
    SeekSlider,
    widget_at,
)
from soundboard.ui.kit.wheelguard import no_wheel

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow


class CutPill(QPushButton):
    """A button that never cuts its words off on both sides when it's squeezed: it
    drops its icon first, then ends the words in "…". A plain button showed "ic: Conne"
    and "■ A" in the mini player's narrowest sizes (and fonts)."""

    def shown(self) -> QStyleOptionButton:
        """What it paints at its width: its icon only when the words still fit."""
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        room = self.style().subElementRect(QStyle.SubElement.SE_PushButtonContents,
                                           opt, self).width()
        words = self.fontMetrics().horizontalAdvance(opt.text)
        if not opt.icon.isNull() and opt.iconSize.width() + words > room:
            opt.icon = QIcon()
        if opt.icon.isNull() and opt.text:
            opt.text = self.fontMetrics().elidedText(opt.text, Qt.TextElideMode.ElideRight,
                                                     max(0, room))
        return opt

    def paintEvent(self, _e):
        QStylePainter(self).drawControl(QStyle.ControlElement.CE_PushButton, self.shown())


class PlayerBuild:
    """The mini player and the mixer strip of WindowBuilder's window (``mw``)."""

    if TYPE_CHECKING:   # WindowBuilder's (Controller)
        mw: MainWindow

    def _build_mini(self) -> QWidget:
        """The mini player: what's playing, play / stop, where it's at, Live and Stop
        all, and the pads above them if there's room. The pads are the real ones,
        moved in and out of the Sounds tab (_set_mini)."""
        mw = self.mw
        page = QWidget()
        v = mw._mini_v = QVBoxLayout(page)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)
        mw.mini_download_bar = DownloadBar(mw)
        mw.mini_download_bar.set_mini(True)
        v.addWidget(mw.mini_download_bar)
        v.addStretch(0)   # keeps the player at the bottom when the pads don't fit
        card = mw._mini_card = QFrame()
        card.setObjectName("transport")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(8, 6, 8, 6)
        cv.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(6)
        mw.mini_pp = PlayButton()
        mw.mini_pp.setObjectName("transport_play")
        mw.mini_pp.setProperty("mini", True)
        mw.mini_pp.setAccessibleName(_("Play / pause"))
        mw.mini_pp.clicked.connect(mw.playctl.toggle_play_pause)
        mw.mini_st = QPushButton()
        mw.mini_st.setObjectName("transport_stop")
        mw.mini_st.setAccessibleName(_("Stop"))
        mw.mini_st.clicked.connect(mw.playctl.stop_current)
        icons.set_icon(mw.mini_st, "stop", size=16)
        mw.mini_skip = QPushButton()
        mw.mini_skip.setObjectName("transport_stop")
        mw.mini_skip.setAccessibleName(_("Skip to the next sound in Up next"))
        mw.mini_skip.clicked.connect(mw.playctl.skip_next)
        icons.set_icon(mw.mini_skip, "next", size=16)
        for b in (mw.mini_pp, mw.mini_st, mw.mini_skip):
            b.setFixedSize(34, 30)
            top.addWidget(b)
        mw.mini_name = ElidedLabel(mw.np_name.text(), hide_overflow=True)
        mw.mini_name.setTextFormat(Qt.TextFormat.PlainText)   # sound names are user / web text
        mw.mini_name.setStyleSheet("font-weight:600;")
        mw.mini_name.setMinimumWidth(0)   # it hides when it doesn't fit: its room goes to "■ All"
        mw.mini_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        top.addWidget(mw.mini_name, 1)
        mw.mini_air = QPushButton()
        mw.mini_air.setObjectName("onair")
        mw.mini_air.setCheckable(True)
        mw.mini_air.setChecked(mw.btn_air.isChecked())
        mw.mini_air.setToolTip(mw.btn_air.toolTip())
        mw.mini_air.toggled.connect(mw.set_sending)
        mw.mini_air.clicked.connect(
            lambda on: usage.used("on-air-on" if on else "on-air-off"))
        icons.set_icon(mw.mini_air, "live", "danger_text", "on_live")
        # "All" in words: an icon-only ■ here looked just like the one-sound ■ on
        # the left, and stopped everything
        mw.mini_stop = CutPill(_("All"))   # squeezed: the word stays, the ■ goes
        mw.mini_stop.setObjectName("danger")
        mw.mini_stop.setProperty("mini", True)   # slim padding: never squeezed to "■ A"
        mw.mini_stop.setToolTip(mw.stop_btn.toolTip())
        mw.mini_stop.setAccessibleName(_("Stop all"))   # read out whole, not just "All"
        mw.mini_stop.clicked.connect(mw.playctl.stop_all)
        icons.set_icon(mw.mini_stop, "stop", "danger_text", size=14)
        mw.mini_air.setFixedSize(38, 30)
        mw.mini_stop.setFixedHeight(30)
        mw.mini_stop.setMinimumWidth(38)
        for b in (mw.mini_air, mw.mini_stop):
            top.addWidget(b)
        cv.addLayout(top)
        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        mw.mini_seek = SeekSlider(Qt.Orientation.Horizontal)
        mw.mini_seek.setRange(0, 1000)
        mw.mini_seek.setObjectName("seek")
        mw.mini_seek.setFixedHeight(24)
        mw.mini_seek.sliderPressed.connect(lambda: setattr(mw.playctl, "_seeking", True))
        mw.mini_seek.sliderReleased.connect(lambda: mw.playctl.do_seek(mw.mini_seek))
        mw.mini_seek.valueChanged.connect(mw.playctl._seek_preview)
        no_wheel(mw.mini_seek)
        bottom.addWidget(mw.mini_seek, 1)
        mw.mini_time = QLabel(mw.np_time.text())
        mw.mini_time.setObjectName("muted")
        steady_number(mw.mini_time, "00:00 / 00:00")
        bottom.addWidget(mw.mini_time)
        cv.addLayout(bottom)
        connection = QHBoxLayout()
        mw.mini_connection = CutPill()
        mw.mini_connection.setObjectName("pill")
        mw.mini_connection.setMinimumWidth(0)
        mw.mini_connection.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        mw.mini_connection.clicked.connect(mw._mini_setup)
        connection.addWidget(mw.mini_connection, 1)
        mw.mini_mic = QPushButton()
        mw.mini_mic.setCheckable(True)
        mw.mini_mic.setFixedHeight(28)
        mw.mini_mic.setToolTip(_("Mute or unmute your mic for others. Your sounds still "
                                   "play for them."))
        mw.mini_mic.toggled.connect(mw.routectl.on_mic_toggle)
        mw.mini_mic.clicked.connect(lambda: usage.used("mini-mic-mute"))   # clicks only
        mw.mini_mic.clicked.connect(mw.routectl._warn_mute_does_nothing)
        connection.addWidget(mw.mini_mic)
        mw.mini_bun = QPushButton()
        mw.mini_bun.setFixedSize(34, 28)
        mw.mini_bun.setToolTip(BUN_TIP)
        mw.mini_bun.setAccessibleName(_("Turn into Bun"))
        mw.mini_bun.setIconSize(QSize(20, 20))
        self._paint_mini_bun()
        mw.mini_bun.clicked.connect(mw.bunctl.enter_bun_mode)
        connection.addWidget(mw.mini_bun)
        # the way back: dragged too small for the board, the window turned into this by
        # itself, with nothing on it saying so or how to get the board back
        mw.mini_full = QPushButton()
        mw.mini_full.setFixedSize(34, 28)
        mw.mini_full.setToolTip(_("Full board: the window got too small for the board, so "
                                  "it shows this mini player. Click (or drag the window "
                                  "bigger) to get the board back."))
        mw.mini_full.setAccessibleName(_("Full board"))
        icons.set_icon(mw.mini_full, "expand", size=18)
        mw.mini_full.clicked.connect(lambda: (usage.used("mini-full-board"),
                                              mw.fitctl.grow_to_board()))
        connection.addWidget(mw.mini_full)
        cv.addLayout(connection)
        v.addWidget(card)
        mw._sync_mini_mic()
        icons.set_icon(mw.mini_pp, "play", "on_accent", size=16)
        return page

    def _build_mixer(self) -> QFrame:
        """The levels strip along the bottom, the same on every tab: three labelled
        boxes, left to right the way the sound flows — your mic, what others hear,
        your own headphones. (Each tab's own volume sits in that tab's bar.)"""
        mw = self.mw
        c = mw.cfg
        # one slim bar: three groups side by side with a thin line between, each
        # labelled inline (a title row over each box made the strip twice as tall)
        f = QFrame()
        f.setObjectName("deck")
        f.setMinimumHeight(BAR_H)
        h = mw._mixer_layout = QHBoxLayout(f)
        h.setContentsMargins(12, 6, 12, 6)
        h.setSpacing(14)
        mw.mixer = f
        mw._deck_titles = []
        mw._deck_rows = []
        mw._decks = []   # each group, with the line before it
        # too narrow for all three: one group shown whole (what others hear, unless
        # you pick another) and the other two as icon buttons that bring theirs up
        mw._deck_tabs = []
        mw._mixer_one = mw._mixer_tight = False
        mw._mixer_focus = 1

        def group(icon: str, title: str, tip: str) -> tuple[QLabel, QHBoxLayout]:
            sep = vsep() if mw._decks else None
            if sep is not None:
                h.addWidget(sep)
            tab = QPushButton()
            tab.setObjectName("iconbutton")
            tab.setProperty("quiet", True)
            tab.setToolTip(title)
            tab.setAccessibleName(title)
            icons.set_icon(tab, icon, "muted")
            tab.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            tab.clicked.connect(lambda _c=False, i=len(mw._decks): mw._focus_deck(i))
            tab.hide()
            h.addWidget(tab)
            mw._deck_tabs.append(tab)
            deck = QWidget()
            deck.setObjectName("decktop")
            row = QHBoxLayout(deck)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            mw._deck_rows.append(row)
            lbl = QLabel(title)
            lbl.setObjectName("decktitle")
            lbl.setToolTip(tip)
            row.addWidget(CapIcon(lbl, icon, tip=tip))
            row.addWidget(lbl)
            mw._deck_titles.append(lbl)
            mw._decks.append((deck,) if sep is None else (sep, deck))
            h.addWidget(deck)
            return lbl, row

        mw.mic_lbl, row = group("mic", _("My mic"),
                                  _("Your real microphone, and how loud your voice is for others"))
        mw.mic_icon = widget_at(row, 0)   # its CapIcon: struck through while muted (_sync_mini_mic)
        assert mw.mic_icon is not None
        mw.chk_mic = QCheckBox(_("Others hear it"))
        mw.chk_mic.setToolTip(_("Send your voice to others along with the sounds.\nUntick for "
                                  "sounds only: they hear your sounds but not your mic."))
        mw.chk_mic.setChecked(c.mic_enabled)
        mw.chk_mic.toggled.connect(mw.routectl.on_mic_toggle)
        mw.chk_mic.clicked.connect(mw.routectl._warn_mute_does_nothing)   # clicks only
        row.addWidget(mw.chk_mic)
        mw.vol_mic = VolumeControl(c.mic_vol, meter=True,
                                     tip=_("How loud your voice is for others. The dot shows "
                                           "activity when you talk"))
        mic_meter = mw.vol_mic.meter
        assert mic_meter is not None   # meter=True
        mw.mic_meter = mic_meter
        # shown alone (_mixer_one_at_a_time) its slider takes the room, up to its own
        # most (150 px), with what's left after it
        row.addWidget(mw.vol_mic, 1)
        row.addStretch(0)

        send_lbl, row = group("live", _("What others hear"),
                              _("Everything going out to others right now (Discord, a game, "
                                "OBS…): your mic plus whatever is live"))
        mw.out_meter = Meter()
        mw.out_meter.setMinimumWidth(60)
        mw.out_meter.setToolTip(_("Level of what others receive (Discord, the game, OBS…)"))
        row.addWidget(mw.out_meter, 1)
        # straight into the mic, not in it yet: the meter moves with your voice, but the
        # sounds don't reach anyone. Said right by it, until they're in (statuscontrol)
        mw.voice_only = QPushButton(_("Voice only"))
        mw.voice_only.setObjectName("vchip")
        mw.voice_only.setProperty("state", "warn")
        mw.voice_only.setCursor(Qt.CursorShape.PointingHandCursor)
        mw.voice_only.setToolTip(_("Others hear your voice, but not your sounds: they aren't "
                                     "in your mic yet. Click to set it up."))
        mw.voice_only.clicked.connect(lambda: mw.tabs.setCurrentWidget(mw.setup_page))
        mw.voice_only.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        mw.voice_only.hide()
        row.addWidget(mw.voice_only)
        # Only the seek slider trims itself; matching must not resize this row.
        mw._bar_edges = EdgeMatch(mw.seek, mw._name_seek.set_pad_right,
                                  mw.out_meter)
        mw.btn_check = QPushButton(_("Hear what they hear"))
        mw.btn_check.setObjectName("miccheck")
        # its name by hand: a narrow window blanks the words (on_mic_check keeps it)
        mw.btn_check.setAccessibleName(_("Hear what they hear"))
        mw.btn_check.setProperty("short_text", _("Listen"))   # a narrow window's word
        mw.btn_check.setCheckable(True)
        mw.btn_check.setToolTip(_("Plays your mic into your headphones on top of the sounds, "
                                    "exactly what others hear."))
        mw.btn_check.toggled.connect(mw.on_mic_check)
        icons.set_icon(mw.btn_check, "ear", checked_color="#ffffff")
        row.addWidget(mw.btn_check)
        mw.btn_check.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        h.setStretchFactor(mw._decks[1][-1], 1)   # the "what others hear" group takes the room

        mw.hp_lbl, row = group("headphones", _("My headphones"),
                                 _("Only what YOU hear. Doesn't change anything for others."))
        mw.vol_mon = VolumeControl(c.mon_vol, tip=_("Only what YOU hear, doesn't change "
                                                      "anything for others"))
        row.addWidget(mw.vol_mon, 1)
        row.addStretch(0)
        for vol in (mw.vol_mic, mw.vol_mon):   # no gap between the slider and its %
            lay = vol.layout()
            assert lay is not None   # made in VolumeControl.__init__
            vol.setMaximumWidth(lay.maximumSize().width())

        for box, key in ((mw.vol_mic, "mic_vol"), (mw.vol_mon, "mon_vol")):
            box.changed.connect(lambda v, key=key: mw.set_option(key, v))
        return f

    def _paint_mini_bun(self):
        """The mini player's Bun button, in this theme's colours."""
        mw = self.mw
        mw.mini_bun.setIcon(self._bun_icon())
        if getattr(mw, "_tray_bun", None) is not None:   # (the tray's menu: theme changes)
            mw._tray_bun.setIcon(self._bun_icon())

    def _bun_icon(self) -> QIcon:
        """A line-drawn bunny like the other icons (the cartoon Bun looked out of place
        among them)."""
        return icons.icon("bun")
