"""Building the main window's Setup page (ui/window/windowbuild.py): its cards (your
virtual mic, Connect your chat, Devices, Who's listening, the equalizer) and the
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
from soundboard.mic import destination
from soundboard.audio import engine
from soundboard.ui.kit import theme
from soundboard.i18n import _
from soundboard.ui.kit import a11y, busy, icons
from soundboard.ui.setup import alsosend
from soundboard.ui.apps.appspanel import ElidedLabel
from soundboard.ui.window.fitcontrol import BODY_SIDE
from soundboard.ui.kit.panel import (
    EqPanel,
    Flow,
    TileRow,
    alt_tile,
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
from soundboard.ui.kit.iconrow import CapIcon
from soundboard.ui.kit.widgets import Meter
from soundboard.ui.kit.wheelguard import AppStyle, no_wheel

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow


# Setup -> Devices -> Send my sounds to (Config.route, library.ROUTES): the mic, nobody,
# or one of the output devices by name (ROUTE_DEVICE + its name: "cable" for a virtual
# cable, "device" for anything else)
SEND_TO = _("Send my sounds to")


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
        # a grid, not two columns: your mic and who's listening share its first row, so
        # they're always the same height and the cards under them line up
        cols = mw._setup_cols = QGridLayout()
        sections.addLayout(cols)
        sections.addStretch(1)
        cols.setContentsMargins(0, 0, 0, 0)
        cols.setSpacing(16)
        lcol, rcol = mw._setup_lr = QVBoxLayout(), QVBoxLayout()
        for i, col in enumerate((lcol, rcol)):
            col.setSpacing(16)
            cols.addLayout(col, 2, i)   # (rows 0 and 1: the card pairs, when side by side)
        page.setWidget(inner)

        # ---- how it works + the one thing to set in Discord
        # straight into the mic: what to do if a voice app chops the sounds up sits
        # behind an ⓘ (DESIGN section 4), not as a paragraph under "Nothing to set"
        mw.btn_mictips = info_button(_("Sounds chopped up?"))
        mw.btn_mictips.clicked.connect(mw.tipctl._show_mic_tips)
        mw.btn_mictips.hide()
        # the heading: a mic, the title, its ⓘ, then the status pill at the end, all on
        # the title's cap height (DESIGN section 4, *Card headings*)
        mw.mic_pill = QLabel(_("Not set up"))   # (its height: the text changes later)
        mw.mic_pill.setObjectName("pill")
        mw.mic_pill.hide()
        howcard, cv = card(_("Your virtual mic"), roomy=True, icon="mic",
                           beside=mw.btn_mictips, end=(mw.mic_pill,))
        assert howcard.heading_title is not None   # (titled)
        mw.how_title = howcard.heading_title   # renamed for the other routes
        # the cable is installed: Virtual cable | My mic on top, the way the sound
        # editor's Simple | Advanced looks (one track, the picked side lit)
        sw = mw.route_switch = QWidget()
        sw.setObjectName("modeswitch")
        sw.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        sh = QHBoxLayout(sw)
        sh.setContentsMargins(3, 3, 3, 3)
        sh.setSpacing(2)
        group = QButtonGroup(sw)
        mw.seg_cable = QPushButton(_("Virtual cable"))
        mw.seg_cable.setToolTip(_("Use a free virtual cable instead: you pick it as the "
                                    "mic in Discord and games"))
        mw.seg_mic = QPushButton(_("My mic"))
        mw.seg_mic.setToolTip(_("Onion Board puts your sounds into your real mic, so "
                                  "Discord and games need no virtual cable and nothing picked"))
        for b in (mw.seg_cable, mw.seg_mic):
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            group.addButton(b)
            sh.addWidget(b)
        mw.seg_cable.clicked.connect(lambda: mw.cfg.route != "cable"
                                     and mw.micctl.use_cable_instead())
        mw.seg_mic.clicked.connect(lambda: mw.cfg.route != "mic" and mw.micctl.attach_mic())
        sw.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        sw.hide()
        cv.addWidget(sw, 0, Qt.AlignmentFlag.AlignLeft)
        flow = mw.mic_flow = QFrame()
        flow.setObjectName("micflow")
        fv = QVBoxLayout(flow)
        fv.setContentsMargins(14, 14, 14, 14)
        fv.setSpacing(10)
        mw.flow_mic = QLabel()
        mw.flow_snd = QLabel(_("Your sounds, radio and voice effects"))
        arrow = QLabel(_("↓   the app mixes them together"))
        arrow.setObjectName("hint")
        mw.flow_out = QLabel()
        for ic, w in (("mic", mw.flow_mic), ("volume", mw.flow_snd), ("", arrow),
                      ("live", mw.flow_out)):   # mic or cable alike
            w.setTextFormat(Qt.TextFormat.RichText)
            w.setWordWrap(True)
            row = QHBoxLayout()
            row.setSpacing(8)
            if ic:   # on the words' capitals, not the line box (the ticks made it taller)
                row.addWidget(CapIcon(w, ic))
            else:
                row.addSpacing(26)
            row.addWidget(w, 1)
            if w is mw.flow_out:
                output = QFrame()
                output.setObjectName("micoutput")
                ov = QVBoxLayout(output)
                ov.setContentsMargins(12, 12, 12, 12)
                ov.addLayout(row)
                fv.addWidget(output)
            else:
                fv.addLayout(row)
        cv.addWidget(flow)
        # straight into the mic, not in it yet: the mic itself works (its level moves)
        # and the sounds aren't in it, two different things. A box of its own says the
        # first, with a tick and the live level, so "Not set up" under it can't read as
        # "your mic is broken"
        voice = mw.mic_voice = QFrame()
        voice.setObjectName("micstatus")
        vh = QHBoxLayout(voice)
        vh.setContentsMargins(12, 10, 12, 10)
        vh.setSpacing(10)
        tick = QLabel()
        tick.setFixedSize(20, 20)
        icons.set_label_icon(tick, "check", "ok_text", size=20)
        vh.addWidget(tick, 0, Qt.AlignmentFlag.AlignTop)
        vlines = QVBoxLayout()
        vlines.setSpacing(4)
        vh.addLayout(vlines, 1)
        vtop = QHBoxLayout()
        vtop.setSpacing(10)
        works = QLabel(_("Your mic works"))
        works.setObjectName("micline")
        theme.set_tone(works, "ok")
        vtop.addWidget(works, 0, Qt.AlignmentFlag.AlignVCenter)
        mw.mic_voice_sub = ElidedLabel()
        mw.mic_voice_sub.setObjectName("hint")
        mw.mic_voice_sub.setMinimumWidth(40)
        vtop.addWidget(mw.mic_voice_sub, 0, Qt.AlignmentFlag.AlignVCenter)
        mw.voice_meter = Meter()
        mw.voice_meter.setFixedWidth(90)
        mw.voice_meter.setToolTip(_("Your voice"))
        vtop.addWidget(mw.voice_meter, 0, Qt.AlignmentFlag.AlignVCenter)
        vtop.addStretch(1)
        vlines.addLayout(vtop)
        heard = QLabel(_("Onion Board hears you, and Discord and games already hear your "
                         "voice through it."))
        heard.setWordWrap(True)
        vlines.addWidget(heard)
        voice.hide()
        cv.addWidget(voice)
        # straight into the mic: one status box instead of the picture above (it works
        # by itself, and the mic helper puts it back when Windows takes it off): a big
        # icon, what's happening, the mic's name and its live level. The step below
        # only when it needs a click.
        box = mw.mic_status = QFrame()
        box.setObjectName("micstatus")
        bh = QHBoxLayout(box)
        bh.setContentsMargins(12, 10, 12, 10)
        bh.setSpacing(10)
        mw.mic_state_icon = QLabel()
        mw.mic_state_icon.setFixedSize(20, 20)
        bh.addWidget(mw.mic_state_icon, 0, Qt.AlignmentFlag.AlignTop)
        lines = QVBoxLayout()
        lines.setSpacing(8)
        bh.addLayout(lines, 1)
        # line 1: what's happening, the mic, its live level
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addStrut(mw.mic_state_icon.height())   # as tall as the icon: level with it
        mw.mic_line = QLabel()
        mw.mic_line.setObjectName("micline")
        top.addWidget(mw.mic_line, 0, Qt.AlignmentFlag.AlignVCenter)
        mw.mic_sub = ElidedLabel()
        mw.mic_sub.setObjectName("hint")
        mw.mic_sub.setMinimumWidth(40)
        top.addWidget(mw.mic_sub, 0, Qt.AlignmentFlag.AlignVCenter)
        mw.card_meter = Meter()
        mw.card_meter.setFixedWidth(90)
        mw.card_meter.setToolTip(_("Your mic"))
        top.addWidget(mw.card_meter, 0, Qt.AlignmentFlag.AlignVCenter)   # by its name
        top.addStretch(1)
        # working: a fresh copy or off, right here (Settings → Audio has every mic)
        from soundboard.ui.setup.audiorecovery import explanation
        mw.btn_michange = QPushButton(_("Change mic"))
        mw.btn_michange.setProperty("quiet", True)
        mw.btn_michange.setToolTip(_("Put your sounds into another mic instead"))
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
        for b in (mw.btn_michange, mw.btn_micredo, mw.btn_micoff):   # (wraps when narrow)
            b.hide()
            mw.mic_ways.addWidget(b)
        box.hide()
        mw._mic_icon = None
        mw._mic_tone = None   # the mic box's last tone (a flash when it turns "ok")
        mw._ways_in = None   # which row the set-up buttons are in (_place_ways)
        cv.addWidget(box)
        cv.addWidget(box)
        mw.helper_checked.connect(mw.micctl._helper_known)
        mw.step_lbl = QLabel()
        mw.step_lbl.setWordWrap(True)
        mw.step_lbl.setTextFormat(Qt.TextFormat.RichText)
        mw.step_lbl.setObjectName("micguide")
        cv.addWidget(mw.step_lbl)
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
        mw.btn_attach = QPushButton(_("Put my sounds into my mic"))   # (tip: no cable)
        mw.btn_attach.setToolTip(_("Onion Board puts your sounds into your real mic, so "
                                     "Discord and games need no virtual cable and nothing picked"))
        mw.btn_attach.clicked.connect(mw.micctl.attach_mic)
        icons.set_icon(mw.btn_attach, "mic")
        mw.attach_glow = Glow(mw.btn_attach)   # the one to press, among the card's colours
        mw.btn_attach.hide()
        # the ways to set it up, side by side at their own size (wraps when narrow)
        ways = Flow(gap=8)
        # the mic on a row of its own, then "or" and the rest: the cable is the fallback
        # for the few who'd rather not, not the next step
        # (straight in the card, at its own width: a row with a stretch kept a gap of
        # its own while the button was hidden, and the card came up short)
        cv.addWidget(mw.btn_attach, 0, Qt.AlignmentFlag.AlignLeft)
        mw.ways_or = QLabel(_("or"))
        mw.ways_or.setObjectName("hint")
        mw.ways_or.hide()
        ways.addWidget(mw.ways_or)   # first in the row, level with the buttons' middle
        mw.btn_usecable = QPushButton(_("Use the cable"))   # (in its tile, below)
        mw.btn_usecable.setToolTip(_("Use a free virtual cable instead: you pick it as the "
                                       "mic in Discord and games"))
        # not installed yet: asked first (only for those who need it); there already,
        # it just switches
        mw.btn_usecable.clicked.connect(lambda: mw.micctl.use_cable_instead()
                                        if engine.virtual_outputs() else cableconfirm.ask(
            mw, mw.micctl.use_cable_instead, lambda: None, _("Keep using my mic")))
        icons.set_icon(mw.btn_usecable, "cable")
        mw.btn_usecable.hide()
        mw.mic_attached.connect(mw.micctl._mic_attached)
        mw.mic_probed.connect(mw.micctl._mic_probed)
        mw._attaching = False
        mw._attach_release = None   # busy.hold on btn_install while it's being set up
        mw._settle_until = 0.0      # just set up: Windows is still loading it
        mw._settle_more = False     # ...and the one longer wait after that has begun
        mw._done_toast = None   # "done" / "updated": said once it works
        icons.set_icon(mw.btn_install, "cable", "on_accent")
        mw.ways_or.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        mw.ways_or.setMinimumHeight(mw.btn_install.sizeHint().height())   # (the buttons')
        ways.addWidget(mw.btn_install)
        # Connect your chat is hidden until there's a chat to connect: its guide is here
        # meanwhile (that card held nothing else, while nothing was set up or on Nobody)
        mw.btn_guide = self._guide_button()
        mw.btn_guide.hide()
        mw.btn_guide.setProperty("quiet", True)
        ways.addWidget(mw.btn_guide)
        # (the row straight in the card: inside another row its height came up short)
        cv.addLayout(ways)
        mw._ways = ways
        # straight into the mic works: the cable is only a fallback, so offer to remove it
        mw.btn_rmcable = QPushButton(_("Remove"))   # (in the cable's tile: it says which)
        mw.btn_rmcable.setAccessibleName(_("Remove the virtual cable"))
        mw.btn_rmcable.setToolTip(_("Uninstalls VB-Cable. Your sounds go straight into your "
                                      "mic, so Onion Board doesn't need it"))
        icons.set_icon(mw.btn_rmcable, "cable")
        mw.btn_rmcable.clicked.connect(mw.micctl.remove_cable)
        mw.btn_rmcable.hide()
        mw.cable_removed.connect(mw.micctl._cable_removed)
        mw._cable_gone = False   # removed this session (Windows lists it till a restart)
        # is VB-Cable's setup program there to remove it with: looked up on a thread (a
        # file check in Program Files, on every redraw, could stall on a slow disk) and
        # asked again when the devices are re-scanned. None = not known yet
        mw._vb_setup = None
        mw._vb_setup_asking = False
        mw.cable_setup_found.connect(mw.micctl._cable_setup_found)
        mw.rmcable_note = hint_label(
            _("<b>You don't need the virtual cable any more</b>, it was only the backup. Remove "
              "it, or keep it if another program uses it (Voicemeeter, another soundboard)."))
        mw.rmcable_note.setTextFormat(Qt.TextFormat.RichText)
        mw.rmcable_note.hide()
        cv.addWidget(mw.rmcable_note)
        mw.btn_rmcable.setProperty("quiet", True)   # (beside Use the cable, in its tile)
        mw.btn_rescan = QPushButton(_("I've installed it: check again"))
        mw.btn_rescan.clicked.connect(lambda: mw.devctl.rescan_with_feedback(mw.btn_rescan))
        icons.set_icon(mw.btn_rescan, "reload")
        ways.addWidget(mw.btn_rescan)   # with the other ways, not a row of its own
        # straight into the mic: the other ways as two tiles under the status, like the
        # setup guide's (before, two lone buttons said "use the cable" and "remove the
        # cable" side by side with no why, over an empty card)
        alt = mw.mic_alt = QWidget()
        al = QVBoxLayout(alt)
        al.setContentsMargins(0, 4, 0, 0)
        al.setSpacing(10)
        head = QLabel(_("Optional: other ways to send your sounds"))
        head.setObjectName("section")
        head.setProperty("head", True)
        al.addWidget(head)
        tiles = mw.mic_alt_tiles = TileRow()   # stacked when narrow, never clipped
        # when the cable is the better pick, behind an ⓘ beside its button
        mw.btn_cableinfo = info_button(_("When to use the cable"))
        mw.btn_cableinfo.clicked.connect(mw.tipctl._show_cable_tips)
        mw.alt_cable, mw.alt_cable_words = alt_tile(
            "cable", _("Virtual cable"), "", mw.btn_usecable, mw.btn_cableinfo,
            mw.btn_rmcable)
        tiles.addTile(mw.alt_cable)
        mw.btn_pickdev = QPushButton(_("Pick a device"))
        icons.set_icon(mw.btn_pickdev, "sliders")
        mw.btn_pickdev.clicked.connect(mw.micctl._pick_send_device)
        mw.alt_device = alt_tile(
            "sliders", _("Another device"),
            _("For streamers and mixers: send your sounds to Voicemeeter, OBS, a mixer or a "
              "capture card, or to nobody."), mw.btn_pickdev)[0]
        tiles.addTile(mw.alt_device)
        al.addWidget(tiles)
        alt.hide()
        cv.addWidget(alt)
        helpcard, hv = card(_("Connect your chat"), roomy=True, icon="speech")
        hv.addWidget(hint_label(_("Choose your app for the recommended microphone settings.")))
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
        chat.addWidget(self._guide_button())
        hv.addLayout(chat)
        mw.helpcard = helpcard


        # ---- devices
        devcard, av = card(_("Devices"), roomy=True, icon="headphones")
        mw.dev_card = devcard
        av.addWidget(hint_label(_("Already set up for you, only change these if "
                                  "something's wrong.")))
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(12)
        mw.cb_main, mw.cb_mon, mw.cb_mic = QComboBox(), QComboBox(), QComboBox()
        # your mic (the normal way), nobody, or a device by name (set_route). cb_main
        # isn't shown: it keeps the device list the picked device is checked against.
        mw.cb_route = QComboBox()
        mw.cb_route.setToolTip(_("Normally your sounds go into your mic, so everyone who hears "
                                   "your mic hears them. Only pick something else to send them "
                                   "somewhere instead: Voicemeeter, a mixer, a device OBS "
                                   "captures, or a virtual cable."))
        for r, (ic, text, cb) in enumerate((
                ("headphones", _("My headphones"), mw.cb_mon),
                ("mic", _("My mic"), mw.cb_mic),
                ("live", SEND_TO, mw.cb_route))):
            row = (icon_label(ic), QLabel(text), cb)
            row[1].setBuddy(cb)   # a screen reader reads the label as the box's name
            for col, w in enumerate(row):
                grid.addWidget(w, r, col)
            # a short floor, so a long device name ("Headphones (2- Arctis Nova Pro
            # Wireless Game)") can't give the Setup tab a sideways scroll bar; the list
            # opens wide enough for whole names
            cb.setMinimumWidth(120)
            # one column: the three boxes share the widest one's width (up to the cap)
            # instead of each fitting its own names, which left My mic's edge short
            cb.setProperty("snug", False)   # (wheelguard.snug_combo: sized here)
            cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
            cb.setMaximumWidth(AppStyle.COMBO_CAP)
        grid.setColumnStretch(3, 1)   # the room past the boxes, not the boxes' column
        av.addLayout(grid)
        mw.setup_connection = QLabel()
        mw.setup_connection.setObjectName("hint")
        mw.setup_connection.setWordWrap(True)
        av.addWidget(mw.setup_connection)
        mw.cb_main.setParent(devcard)   # never a window of its own
        mw.cb_main.hide()
        # more places at once (streamers): a row per extra device, + and − (alsosend)
        mw.also_views = []
        mw.also_rows = alsosend.build(mw, grid, 3, icons_col=True)
        mw.setup_hint = hint_label("")
        mw.setup_hint.setTextFormat(Qt.TextFormat.RichText)
        av.addWidget(mw.setup_hint)
        mw.btn_cablefix = QPushButton(_("Fix the cable: both ends to 48 kHz"))
        mw.btn_cablefix.setToolTip(_("Sets the cable's playback and recording side to 48 kHz, "
                                       "so it passes your sound through without converting it"))
        mw.btn_cablefix.clicked.connect(lambda: busy.run_busy(
            mw.btn_cablefix, _("Switching the cable to 48 kHz…"), mw.micctl.fix_cable_format,
            lambda ok: _("✓ Done") if ok and not mw.micctl.cable_bad
            else _("Couldn't, see below")))
        mw.btn_cablefix.hide()
        av.addWidget(mw.btn_cablefix, 0, Qt.AlignmentFlag.AlignLeft)
        no_wheel(mw.cb_main, mw.cb_mon, mw.cb_mic, mw.cb_route)
        for cb, attr in ((mw.cb_main, "main_device"), (mw.cb_mon, "mon_device"),
                         (mw.cb_mic, "mic_device"), (mw.cb_route, "route")):
            cb.activated.connect(lambda _i, cb=cb, attr=attr: mw.routectl.on_device(cb, attr))
        ref = QPushButton(_("Re-scan devices"))
        icons.set_icon(ref, "reload")
        ref.clicked.connect(lambda: mw.devctl.rescan_with_feedback(ref))
        av.addWidget(ref, 0, Qt.AlignmentFlag.AlignLeft)

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
        for lay in (cv, av, ev):   # as tall as the card beside it: the room goes at the bottom
            lay.addStretch(1)
        # side by side, in pairs that share a grid row (the same height, so their tops
        # and bottoms line up): your mic and who's listening, then devices and the EQ;
        # connect your chat under the devices. All open: they fit the screen, so
        # nothing folds away. One column when narrow: what you check every day first
        mw._setup_top = (howcard, destcard)
        mw._setup_pairs = (mw._setup_top, (devcard, eqcard))
        mw._setup_wide = ((howcard, devcard, helpcard), (destcard, eqcard))
        mw._setup_narrow = (howcard, destcard, devcard, helpcard, eqcard)
        # Onion Pocket, once it's installed: a card on the left, in Connect your chat's
        # place (that moves to the right, under the EQ). fitctl._place_pocket
        from soundboard.ui.setup.pocketcard import PocketCard
        mw.pocket_card = PocketCard(mw)
        mw._setup_cards = (howcard, devcard, helpcard, destcard, eqcard)
        mw._setup_stacked = None
        mw.fitctl._stack_setup(False)
        mw.on_eq(*mw.eq.state())   # push the saved EQ into the engine
        destination.apply(mw.cfg, mw.engine)   # ...and the destination mode (Who's listening)
        from soundboard.ui.setup.destpanel import apply_send
        apply_send(mw.cfg, mw.engine)          # ...and mono / ducking
        return page

    def _guide_button(self) -> QPushButton:
        mw = self.mw
        guide = QPushButton(_("Step-by-step guide"))
        guide.setToolTip(_("Walks you through mic, headphones, where your sounds go (your mic, "
                           "the cable, another device or nowhere) and Discord"))
        icons.set_icon(guide, "check")
        guide.clicked.connect(lambda: (usage.used("setup-guide-opened"), mw.run_setup()))
        return guide
