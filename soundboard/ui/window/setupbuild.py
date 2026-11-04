"""Building the main window's Setup page (ui/window/windowbuild.py): its cards (your
virtual mic, Set up your voice apps, Devices, Who's listening, the equalizer) and the
step-by-step guide.

A mixin WindowBuilder inherits, so every `self.` lookup is the same as before; it runs
once, on the UI thread, while the window is made."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from soundboard.core import usage
from soundboard.mic import cableremove, destination
from soundboard.i18n import _
from soundboard.ui.kit import a11y, busy, icons
from soundboard.ui.setup import alsosend
from soundboard.ui.window.fitcontrol import BODY_SIDE
from soundboard.ui.kit.panel import (
    EqPanel,
    Flow,
    capped,
    card,
    hint_label,
    icon_label,
    info_button,
)
from soundboard.ui.setup.setupshow import SetupShow
from soundboard.ui.window.sidebar import SHUT_W
from soundboard.ui.setup import cableconfirm
from soundboard.ui.kit.failreport import FailReport
from soundboard.ui.kit.glow import Glow
from soundboard.ui.kit.widgets import Meter
from soundboard.ui.kit.wheelguard import AppStyle, no_wheel

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow


def _set_up_discord(mw):
    """The Setup tab's Discord button: Bun sets Discord up (chatguide.set_up_discord)."""
    from soundboard.ui.setup.chatguide import set_up_discord
    set_up_discord(mw)


class WidthScroll(QScrollArea):
    """While it's the page showing, it needs its content's width, so a narrow window
    shuts the rail before the page gets a sideways scroll bar (that only worked while
    the levels strip happened to shut the rail first). Only when shutting it would be
    enough (`room()`: the page's width with the rail shut): wider content scrolls
    sideways rather than turn the window into the mini player."""

    def __init__(self, room, narrowest=None):
        super().__init__()
        self._room = room
        # the content's width in its narrowest arrangement (Setup: one column). What it
        # needs, not what it has now: two columns side by side mustn't shut the rail
        self._narrowest = narrowest

    def minimumSizeHint(self) -> QSize:
        m = super().minimumSizeHint()
        page = self.widget()
        if page is None or not self.isVisible():   # a page not showing
            return m
        content = (self._narrowest() if self._narrowest is not None
                   else page.minimumSizeHint().width())
        need = content + self.verticalScrollBar().sizeHint().width()
        return QSize(max(m.width(), need), m.height()) if need <= self._room() else m


class SetupPageBuild:
    """The Setup page of WindowBuilder's window (``mw``)."""

    if TYPE_CHECKING:   # WindowBuilder's (Controller)
        mw: MainWindow

    def _build_setup_page(self) -> WidthScroll:
        """One-time setup and the rarely-touched stuff: where the audio goes,
        devices, the recorded test, EQ, levelling."""
        mw = self.mw
        c = mw.cfg
        page = WidthScroll(lambda: mw._pages.width() - SHUT_W - 2 * BODY_SIDE,
                           lambda: mw.fitctl._setup_one_col())
        page.setWidgetResizable(True)
        page.setFrameShape(QFrame.Shape.NoFrame)
        a11y.scroll_stop(page, _("Setup"))
        body = QWidget()
        inner = capped(body, margins=(0, 12, 12, 12))   # not a 900 px wide card at full screen; the
        # cards' left edge lines up with the other tabs
        sections = QVBoxLayout(body)
        sections.setContentsMargins(0, 0, 0, 0)
        sections.setSpacing(16)
        # a grid: cards side by side share a row, so they're always the same height and
        # the ones under them line up (fitctl._stack_setup places them)
        cols = mw._setup_cols = QGridLayout()
        sections.addLayout(cols)
        sections.addStretch(1)
        cols.setContentsMargins(0, 0, 0, 0)
        cols.setSpacing(16)
        page.setWidget(inner)

        # ---- how it works + the one thing to set in Discord
        # straight into the mic: what to do if a voice app chops the sounds up sits
        # behind an ⓘ (DESIGN section 4), not as a paragraph under "Nothing to set"
        mw.btn_mictips = info_button(_("Sounds chopped up?"))
        mw.btn_mictips.clicked.connect(mw.tipctl._show_mic_tips)
        # (its room stays: the card moved 3 px each time the switch changed sides)
        tips_size = mw.btn_mictips.sizePolicy()
        tips_size.setRetainSizeWhenHidden(True)
        mw.btn_mictips.setSizePolicy(tips_size)
        mw.btn_mictips.hide()
        # the heading: a mic, the title, its ⓘ, then the status pill at the end, all on
        # the title's cap height (DESIGN section 4, *Card headings*)
        mw.mic_pill = QLabel(_("Not set up"))   # (its height: the text changes later)
        mw.mic_pill.setObjectName("pill")
        mw.mic_pill.hide()
        howcard, cv = card(_("Your mic"), roomy=True, icon="mic",
                           beside=mw.btn_mictips, end=(mw.mic_pill,))
        assert howcard.heading_title is not None   # (titled)
        mw.how_title = howcard.heading_title
        # the mic, the only place it's picked on this tab, and its live level
        pick = QHBoxLayout()
        pick.setSpacing(10)
        mw.cb_mic = QComboBox()
        mw.cb_mic.setAccessibleName(_("Your mic"))
        self._device_box(mw.cb_mic)
        pick.addWidget(mw.cb_mic)
        mw.card_meter = Meter()
        mw.card_meter.setFixedWidth(90)
        mw.card_meter.setToolTip(_("Your mic"))
        pick.addWidget(mw.card_meter, 0, Qt.AlignmentFlag.AlignVCenter)
        pick.addStretch(1)
        cv.addLayout(pick)
        # under the box, when the level alone doesn't say it (beside it, it got cut off
        # in a narrow window)
        mw.mic_sub = hint_label("")
        mw.mic_sub.hide()
        cv.addWidget(mw.mic_sub)
        # how the sounds get in: one track, the picked side lit, the way the sound
        # editor's Simple | Advanced looks. Never Windows' prompt from here: the box under
        # it says what's missing and has the button
        how = Flow(gap=10)
        how_label = QLabel(_("How your sounds get in"))
        sw = mw.route_switch = QWidget()
        sw.setObjectName("modeswitch")
        sw.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        sh = QHBoxLayout(sw)
        sh.setContentsMargins(3, 3, 3, 3)
        sh.setSpacing(2)
        group = QButtonGroup(sw)
        mw.seg_mic = QPushButton(_("Driver"))
        mw.seg_mic.setToolTip(_("Onion Board puts your sounds into your real mic, so "
                                  "Discord and games need no virtual cable and nothing picked"))
        mw.seg_cable = QPushButton(_("Virtual cable"))
        mw.seg_cable.setToolTip(_("Use a free virtual cable instead: you pick it as the "
                                    "mic in Discord and games"))
        mw.seg_off = QPushButton(_("Nobody"))
        mw.seg_off.setToolTip(_("Nothing goes out as a mic: only you hear your sounds"))
        # someone sending to a device by hand (Voicemeeter, a mixer): only while they are,
        # so their setting stays what it is and says so
        mw.seg_device = QPushButton(_("Other device"))
        mw.seg_device.setToolTip(_("Your sounds go to a device you picked by hand"))
        mw.seg_device.hide()
        for b in (mw.seg_mic, mw.seg_cable, mw.seg_off, mw.seg_device):   # the default way first
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            group.addButton(b)
            sh.addWidget(b)
        mw.seg_mic.clicked.connect(mw.routectl.use_mic)
        mw.seg_cable.clicked.connect(mw.routectl.use_cable)
        mw.seg_off.clicked.connect(mw.routectl.use_nobody)
        mw.seg_device.clicked.connect(mw.routectl._show_route)   # (it's on already)
        mw.mic_found.connect(mw.routectl._mic_found)
        sw.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        how_label.setMinimumHeight(sw.sizeHint().height())   # (level with the track's middle)
        how_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        # when the cable is the better pick, behind an ⓘ beside the switch
        mw.btn_cableinfo = info_button(_("When to use the cable"))
        mw.btn_cableinfo.clicked.connect(mw.tipctl._show_cable_tips)
        # (the switch and its ⓘ wrap together: alone on a line, the ⓘ looked lost)
        sw_row = QWidget()
        sr = QHBoxLayout(sw_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.setSpacing(10)
        sr.addWidget(sw)
        sr.addWidget(mw.btn_cableinfo)
        how.addWidget(how_label)
        how.addWidget(sw_row)
        cv.addLayout(how)
        # two or more cables (or a device by hand): which one
        mw.route_pick = QWidget()
        rp = QHBoxLayout(mw.route_pick)
        rp.setContentsMargins(0, 0, 0, 0)
        rp.setSpacing(10)
        mw.cb_route = QComboBox()
        self._device_box(mw.cb_route)
        rp_label = QLabel(_("Send to"))
        rp_label.setBuddy(mw.cb_route)   # a screen reader reads the label as the box's name
        rp.addWidget(rp_label)
        rp.addWidget(mw.cb_route)
        rp.addStretch(1)
        mw.route_pick.hide()
        cv.addWidget(mw.route_pick)
        # one status box on every route: a big icon, what's happening, why and what to do
        box = mw.mic_status = QFrame()
        box.setObjectName("micstatus")
        bh = QHBoxLayout(box)
        bh.setContentsMargins(12, 10, 12, 10)
        bh.setSpacing(10)
        mw.mic_state_icon = QLabel()
        mw.mic_state_icon.setFixedSize(20, 20)
        from soundboard.ui.setup.audiorecovery import explanation
        mw.btn_michange = QPushButton(_("Pick my mic"))   # no mic picked: the one thing to do
        mw.btn_michange.setObjectName("primary")
        mw.btn_michange.clicked.connect(mw.micctl._pick_mic)
        mw.btn_micredo = QPushButton(_("Reinstall"))
        mw.btn_micredo.setProperty("quiet", True)
        mw.btn_micredo.setToolTip(explanation("reinstall"))
        mw.btn_micredo.clicked.connect(lambda: mw.micctl._ask_mic_effect("reinstall"))
        mw.btn_micoff = QPushButton(_("Remove"))
        mw.btn_micoff.setObjectName("danger")
        mw.btn_micoff.setProperty("quiet", True)
        mw.btn_micoff.setToolTip(explanation("remove"))
        mw.btn_micoff.clicked.connect(lambda: mw.micctl._ask_mic_effect("remove"))
        # the headline's row is as tall as the buttons beside it: the icon level with its
        # middle (_show_mic_status sets both, once the theme has sized the buttons)
        icon_col = mw.mic_icon_col = QVBoxLayout()
        icon_col.setSpacing(0)
        icon_col.addWidget(mw.mic_state_icon)
        icon_col.addStretch(1)
        bh.addLayout(icon_col)
        lines = QVBoxLayout()
        lines.setSpacing(8)
        bh.addLayout(lines, 1)
        # line 1: what's happening, then Reinstall and Remove beside it (they wrap under
        # it when narrow)
        top = Flow(gap=10)
        mw.mic_line = QLabel()
        mw.mic_line.setObjectName("micline")
        mw.mic_line.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(mw.mic_line)
        fix = mw.mic_fix = QWidget()   # (they wrap together, never Remove on its own)
        fh = QHBoxLayout(fix)
        fh.setContentsMargins(0, 0, 0, 0)
        fh.setSpacing(8)
        for b in (mw.btn_micredo, mw.btn_micoff):
            fh.addWidget(b)
        # on the cable: its Remove, like the driver's
        mw.btn_rmcable_on = QPushButton(_("Remove"))
        mw.btn_rmcable_on.setObjectName("danger")
        mw.btn_rmcable_on.setProperty("quiet", True)
        mw.btn_rmcable_on.setAccessibleName(_("Remove the virtual cable"))
        mw.btn_rmcable_on.setToolTip(_("Uninstalls VB-Cable. Your sounds go into your mic "
                                       "after that."))
        mw.btn_rmcable_on.clicked.connect(lambda: mw.micctl.remove_cable(mw.btn_rmcable_on))
        mw.btn_rmcable_on.hide()
        fh.addWidget(mw.btn_rmcable_on)
        fix.hide()
        top.addWidget(fix)
        lines.addLayout(top)
        # line 2, when there's something to say or do: why, then the buttons
        mw.mic_reason = QLabel()
        mw.mic_reason.setWordWrap(True)
        mw.mic_reason.setTextFormat(Qt.TextFormat.RichText)
        mw.mic_reason.hide()
        lines.addWidget(mw.mic_reason)
        # putting it on the mic failed: tell us, before giving up
        mw.mic_report = FailReport(lambda: {"mic": mw.cfg.mic_device or "", "mode": "direct",
                                            "err": mw.micctl.fail_code})
        lines.addWidget(mw.mic_report)
        mw.mic_ways = Flow(gap=8)
        lines.addLayout(mw.mic_ways)
        mw.btn_michange.hide()
        mw.mic_ways.addWidget(mw.btn_michange)
        mw._mic_icon = None
        mw._mic_tone = None   # the mic box's last tone (a flash when it turns "ok")
        cv.addWidget(box)
        mw.helper_checked.connect(mw.micctl._helper_known)
        # an old mic part: one amber banner with its one button, in the step's place
        mw.mic_update_note = QFrame()
        mw.mic_update_note.setObjectName("micupdatebar")
        nh = QHBoxLayout(mw.mic_update_note)
        nh.setContentsMargins(14, 10, 10, 10)
        nh.setSpacing(12)
        mw.mic_update_icon = icon_label("warn", color="warn_text")
        nh.addWidget(mw.mic_update_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        mw.mic_update_text = QLabel()
        mw.mic_update_text.setTextFormat(Qt.TextFormat.RichText)
        mw.mic_update_text.setWordWrap(True)
        nh.addWidget(mw.mic_update_text, 1)
        mw.btn_micupdate = QPushButton(_("Update now"))
        mw.btn_micupdate.setObjectName("primary")
        from soundboard.ui.setup.micupdate import _shield
        _shield(mw.btn_micupdate)
        mw.btn_micupdate.clicked.connect(mw.micctl._accept_mic_update)
        nh.addWidget(mw.btn_micupdate, 0, Qt.AlignmentFlag.AlignVCenter)
        mw.mic_update_note.hide()
        cv.addWidget(mw.mic_update_note)
        mw.setup_show = SetupShow(height=96)   # Bun builds it, centred under the boxes
        mw.setup_show.done.connect(mw.statusctl._update_flow)   # (the button's back, if needed)
        cv.addWidget(mw.setup_show)
        mw.btn_install = QPushButton(_("Install the free virtual cable"))
        mw.btn_install.setObjectName("primary")
        mw._cable_started = False   # (I've installed it: check again waits for this)
        def install_clicked():
            if mw.cfg.route == "mic":
                mw.micctl.attach_mic()
                return

            def install():
                mw._cable_started = True
                mw.micctl.install_cable()
            cableconfirm.ask(mw, install, mw.micctl.attach_mic)   # (only if they need it)
        mw.btn_install.clicked.connect(install_clicked)
        # what set_icon last put on it (only set when it changes)
        mw._install_icon = None
        # on the mic route it's the main button (put my sounds into my mic): it glows then
        mw.install_glow = Glow(mw.btn_install)
        mw.install_glow.set_on(False)
        mw.mic_attached.connect(mw.micctl._mic_attached)
        mw.mic_probed.connect(mw.micctl._mic_probed)
        mw._attaching = False
        mw._attach_release = None   # busy.hold on btn_install while it's being set up
        mw._settle_until = 0.0      # just set up: Windows is still loading it
        mw._settle_more = False     # ...and the one longer wait after that has begun
        mw._done_toast = None   # "done" / "updated": said once it works
        icons.set_icon(mw.btn_install, "cable", "on_accent")
        mw.mic_ways.addWidget(mw.btn_install)
        # the cable removed, and picked again: what it's waiting for
        mw.btn_restart_pc = QPushButton(_("⟲  Restart my PC now"))
        mw.btn_restart_pc.setObjectName("primary")
        mw.btn_restart_pc.clicked.connect(mw.micctl.restart_pc)
        mw.btn_restart_pc.hide()
        mw.mic_ways.addWidget(mw.btn_restart_pc)
        mw.cable_removed.connect(mw.micctl._cable_removed)
        # removed, and the PC hasn't restarted since (Windows lists it till then)
        mw._cable_gone = cableremove.removed_pending()
        # is VB-Cable's setup program there to remove it with: looked up on a thread (a
        # file check in Program Files, on every redraw, could stall on a slow disk) and
        # asked again when the devices are re-scanned. None = not known yet
        mw._vb_setup = None
        mw._vb_setup_asking = False
        mw.cable_setup_found.connect(mw.micctl._cable_setup_found)
        mw.btn_rescan = QPushButton(_("I've installed it: check again"))
        mw.btn_rescan.clicked.connect(lambda: mw.devctl.rescan_with_feedback(mw.btn_rescan))
        icons.set_icon(mw.btn_rescan, "reload")
        mw.mic_ways.addWidget(mw.btn_rescan)   # with the other ways, not a row of its own
        # what's being sent and any trouble with it (a cable on the wrong rate, a device
        # that won't open), with the cable's one fix
        mw.setup_hint = hint_label("")
        mw.setup_hint.setTextFormat(Qt.TextFormat.RichText)
        cv.addWidget(mw.setup_hint)
        mw.btn_cablefix = QPushButton(_("Fix the cable: both ends to 48 kHz"))
        mw.btn_cablefix.setToolTip(_("Sets the cable's playback and recording side to 48 kHz, "
                                       "so it passes your sound through without converting it"))
        mw.btn_cablefix.clicked.connect(lambda: busy.run_busy(
            mw.btn_cablefix, _("Switching the cable to 48 kHz…"), mw.micctl.fix_cable_format,
            lambda ok: _("✓ Done") if ok and not mw.micctl.cable_bad
            else _("Couldn't, see below")))
        mw.btn_cablefix.hide()
        cv.addWidget(mw.btn_cablefix, 0, Qt.AlignmentFlag.AlignLeft)
        helpcard, hv = card(_("Set up your voice apps"), roomy=True, icon="speech")
        mw.chat_hint = hint_label(_("Choose your app for the recommended microphone settings."))
        hv.addWidget(mw.chat_hint)
        chat = Flow(gap=8)   # at their own size, wrapping, not five full-width bars
        mw.btn_chat = QPushButton(_("Make it sound clean in Discord"))
        mw.btn_chat.setToolTip(_("Bun saves how Discord is set now, then switches off what "
                                 "chops up your sounds. Settings → Audio → Mic effect puts it "
                                 "back."))
        icons.set_icon(mw.btn_chat, "headphones")
        mw.btn_chat.clicked.connect(lambda: _set_up_discord(mw))   # Bun does it
        chat.addWidget(mw.btn_chat)
        mw.btn_game = QPushButton(_("Set up game voice chat"))
        mw.btn_game.clicked.connect(lambda: mw.statusctl.show_chat_guide("game"))
        chat.addWidget(mw.btn_game)
        mw.btn_meeting = QPushButton(_("Zoom, Teams or a browser call"))
        mw.btn_meeting.setToolTip(_("The settings in Zoom, Microsoft Teams and calls in a web "
                                      "page that stop them treating your sounds as noise"))
        mw.btn_meeting.clicked.connect(lambda: mw.statusctl.show_chat_guide("meeting"))
        chat.addWidget(mw.btn_meeting)
        mw.btn_nomic = QPushButton(_("Game has no microphone setting?"))
        mw.btn_nomic.clicked.connect(mw.micctl.open_windows_mic)
        chat.addWidget(mw.btn_nomic)
        mw.btn_guide = self._guide_button()   # the tab's one: the card is always there for it
        chat.addWidget(mw.btn_guide)
        hv.addLayout(chat)
        mw.helpcard = helpcard


        # ---- devices
        # the ⓘ's size: bigger, the heading grew and its title sat 4 px under Who's
        # listening's beside it
        ref = info_button(_("Re-scan devices"))
        icons.set_icon(ref, "reload", size=16)
        ref.clicked.connect(lambda: mw.devctl.rescan_with_feedback(ref))
        devcard, av = card(_("Speakers and headphones"), roomy=True, icon="headphones", end=(ref,))
        mw.dev_card = devcard
        av.addWidget(hint_label(_("Already set up for you, only change these if "
                                  "something's wrong.")))
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(12)
        # cb_main isn't shown: it keeps the device list the picked device is checked against
        mw.cb_main, mw.cb_mon = QComboBox(), QComboBox()
        row = (icon_label("headphones"), QLabel(_("Play on")), mw.cb_mon)
        row[1].setBuddy(mw.cb_mon)   # a screen reader reads the label as the box's name
        for col, w in enumerate(row):
            grid.addWidget(w, 0, col)
        self._device_box(mw.cb_mon)
        grid.setColumnStretch(3, 1)   # the room past the boxes, not the boxes' column
        av.addLayout(grid)
        mw.cb_main.setParent(devcard)   # never a window of its own
        mw.cb_main.hide()
        # more places at once (streamers): a row per extra device, + and − (alsosend)
        mw.also_views = []
        mw.also_rows = alsosend.build(mw, grid, 1, icons_col=True)
        # a device here that won't open (unplugged)
        mw.dev_hint = hint_label("")
        mw.dev_hint.setTextFormat(Qt.TextFormat.RichText)
        mw.dev_hint.hide()
        av.addWidget(mw.dev_hint)
        no_wheel(mw.cb_main, mw.cb_mon, mw.cb_mic, mw.cb_route)
        for cb, attr in ((mw.cb_main, "main_device"), (mw.cb_mon, "mon_device"),
                         (mw.cb_mic, "mic_device"), (mw.cb_route, "route")):
            cb.activated.connect(lambda _i, cb=cb, attr=attr: mw.routectl.on_device(cb, attr))

        # ---- who's listening: shape the sounds for the voice chat on the other end
        from soundboard.ui.setup.destpanel import DestPanel
        mw.dest_panel = DestPanel(mw)
        destcard, dv = card(_("Who's listening"), _("Where people hear you: a game, a voice "
                                                    "chat app, or a stream. Your sounds are "
                                                    "shaped to come through clearly."),
                            roomy=True, icon="ear",
                            beside=mw.dest_panel.help_btn)   # What do these do?
        dv.addWidget(mw.dest_panel)
        dv.addStretch(1)   # as tall as your mic beside it: the room goes at the bottom

        # ---- sound shaping
        eqcard, ev = card(_("Equalizer and volume"), roomy=True, icon="sliders")
        mw.eq_card = eqcard
        mw.eq = EqPanel(c.eq_enabled, c.eq_target, c.eq_preset, c.eq_gains, fold=True)
        mw.eq.changed.connect(mw.on_eq)
        ev.addWidget(mw.eq)
        mw.chk_level = QCheckBox(_("Level volumes (all sounds equally loud)"))
        mw.chk_level.setChecked(c.level_volumes)
        mw.chk_level.toggled.connect(mw.on_level_toggle)
        ev.addWidget(mw.chk_level)
        for lay in (cv, av, ev, hv):   # as tall as the card beside it: the room goes at the bottom
            lay.addStretch(1)
        # your mic on top, across the whole width; under it pairs that share a grid row
        # (the same height, so their tops and bottoms line up). All open: they fit the
        # screen, so nothing folds away. One column when narrow, in the same order
        # (your mic's home here: Settings > Audio borrows it while it's on screen)
        from soundboard.ui.setup.cardhome import CardHome
        howcard = mw.how_home = CardHome(howcard)
        mw._setup_cards = (howcard, devcard, helpcard, destcard, eqcard)
        # Onion Pocket, once it's installed: beside the EQ, in Set up your voice apps's place
        # (that goes across the whole width under them). fitctl._place_pocket
        from soundboard.ui.setup.pocketcard import PocketCard
        mw.pocket_card = PocketCard(mw)
        mw._setup_stacked = None
        mw.fitctl._place_pocket(False)
        mw.on_eq(*mw.eq.state())   # push the saved EQ into the engine
        destination.apply(mw.cfg, mw.engine)   # ...and the destination mode (Who's listening)
        from soundboard.ui.setup.destpanel import apply_send
        apply_send(mw.cfg, mw.engine)          # ...and mono / ducking
        return page

    @staticmethod
    def _device_box(cb: QComboBox):
        """A device box: a short floor, so a long device name ("Headphones (2- Arctis Nova
        Pro Wireless Game)") can't give the Setup tab a sideways scroll bar; the list opens
        wide enough for whole names."""
        cb.setMinimumWidth(120)
        cb.setProperty("snug", False)   # (wheelguard.snug_combo: sized here)
        cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        cb.setMaximumWidth(AppStyle.COMBO_CAP)

    def _guide_button(self) -> QPushButton:
        mw = self.mw
        guide = QPushButton(_("Step-by-step guide"))
        guide.setToolTip(_("Walks you through mic, headphones, where your sounds go (your mic, "
                           "the cable, another device or nowhere) and Discord"))
        icons.set_icon(guide, "check")
        guide.clicked.connect(lambda: (usage.used("setup-guide-opened"), mw.run_setup()))
        return guide
