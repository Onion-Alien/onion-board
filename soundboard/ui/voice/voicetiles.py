"""The voice changer's voice cards: `VoiceTile`, the groups they're shown in, and
`BigSwitch`, a card's main on/off."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter
from PySide6.QtWidgets import QBoxLayout, QSizePolicy, QToolButton

from soundboard.ui.kit import theme
from soundboard import voicefx
from soundboard.ui.kit import icons
from soundboard.i18n import _
from soundboard.ui.kit.pixels import snap_to_pixels
from soundboard.ui.voice.fxcontrols import Switch


CUSTOM = "Custom"
TILE_ART = 48     # px: a voice card's picture (when there is one, see ui/voice/art.py)
TILE_MIN_W = 124  # px: a voice card at its narrowest (the row holds as many as fit)
TILE_GAP = 8      # px: between voice cards
LIST_MIN_W = 190  # px: a voice row at its narrowest (the list view)
LIST_ART = 30     # px: a voice row's picture
MAX_COLS = 12     # voice cards a row, at most
PICKED_ART = 32   # px: the picked voice's picture, under the cards


def place_bar_controls(bar):
    """A voice bar's pause and ✕ (VoicePanel._make_bar_controls): at the right end of
    its one line, or, when its buttons fold under the name, at the end of the name's
    line. (On a line of their own they made the bar a tall, mostly empty third row.)"""
    ctl, top = getattr(bar, "bar_controls", None), getattr(bar, "bar_top", None)
    if ctl is None or top is None:
        return
    box = bar.picked_box
    folded = box.direction() == QBoxLayout.Direction.TopToBottom
    if (top.indexOf(ctl) >= 0) == folded:
        return
    box.removeWidget(ctl)
    top.removeWidget(ctl)
    if folded:
        top.addWidget(ctl, 0, Qt.AlignmentFlag.AlignVCenter)   # (after its stretch)
    else:
        box.addWidget(ctl, 0, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)


VOICE_ICONS = {"Walkie-talkie": "radio", "Old telephone": "speech",
               "Megaphone": "volume", "Stadium announcer": "volume",
               "Podcast voice": "mic", "Demon": "voice", "Ghost": "voice",
               "Alien": "voice", CUSTOM: "sliders"}


# the voice cards in groups, each voice in one ("All" shows them under these headings;
# a chip shows one group). Your own mix and saved voices are "Mine"; a voice not
# listed here (a new preset) lands in Funny until it's given a group.
VOICE_GROUPS = (
    ("funny", _("Funny"), ("Chipmunk", "High voice", "Hothead", "Singing monk",
                           "Underwater", "Drunk", "Choir", "Goblin", "Fairy",
                           "Nightcore", "Slowed + reverb", "Cat", "Dog",
                           "Goat", "Duck", "Pig", "Sheep", "Cow", "Farm",
                           "Ear destroyer", "Critter chatter", "Fart", "Drum kit",
                           "Whistle", "Kazoo")),
    ("scary", _("Scary"), ("Demon", "Dark lord", "Ghost", "Masked caller",
                           "Haunted radio", "Zombie", "Evil twin", "Giant")),
    ("scifi", _("Robots & sci-fi"), ("Robot", "Dalek", "Alien", "Talkbox", "Autotune",
                                     "Mecha", "Ship computer", "Glitch", "8-bit",
                                     "Virtual idol", "80s robot")),
    ("disguise", _("Disguise"), ("Deep voice", "Male voice", "Anonymous",
                                 "Secret detective")),
    ("places", _("Radio & places"), ("Walkie-talkie", "Old telephone", "Megaphone",
                                     "Stadium announcer", "Cave", "Podcast voice", "Pilot",
                                     "Drive-thru speaker", "Old film", "Cathedral")),
)
MINE = "mine"
# the group dropdown's pictures
GROUP_ICONS = {"funny": "laugh", "scary": "ghost", "scifi": "robot", "disguise": "voice",
               "places": "radio"}
FAVS = "favs"
ALL = ""
STAR = 22   # px: the favorite star in a voice card's corner


class BigSwitch(Switch):
    """A card's main on/off: a big switch with ON or OFF written in it, next to the
    card's name (the small one there was easy to miss). Its words are setText()'s,
    drawn in capitals."""
    PAD, H = 14, 34

    def __init__(self, tip: str = ""):
        super().__init__(tip, hover=False)
        f = QFont(self.font())
        f.setBold(True)
        f.setPointSizeF(max(f.pointSizeF(), 9.0) + 1.5)
        self.setFont(f)
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self._fit()

    def _fit(self):
        fm = self.fontMetrics()
        words = max(fm.horizontalAdvance(t.upper()) for t in (_("On"), _("Off")))
        self.setFixedSize(words + 2 * self.PAD + self.H, self.H)

    def sizeHint(self):
        return self.size()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.Type.FontChange:
            self._fit()

    def paintEvent(self, _e):
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        rad = r.height() / 2
        track = QColor(theme.T["accent"] if on else theme.T["groove"])
        if not self.isEnabled():
            track.setAlpha(110)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, rad, rad)
        d = r.height() - 8
        x = r.right() - d - 4 if on else r.left() + 4
        knob = QColor(theme.T["on_accent"] if on else theme.T["text"])
        if not self.isEnabled():
            knob.setAlpha(110)
        p.setBrush(knob)
        p.drawEllipse(QRectF(x, r.top() + 4, d, d))
        # the word on the side the knob isn't
        words = (QRectF(r.left() + self.PAD, r.top(), r.width() - d - 8 - self.PAD, r.height())
                 if on else QRectF(r.left() + d + 8, r.top(), r.width() - d - 8 - self.PAD,
                                   r.height()))
        text = QColor(theme.T["on_accent"] if on else theme.T["text"])
        if not self.isEnabled():
            text.setAlpha(140)
        p.setPen(text)
        p.drawText(words, Qt.AlignmentFlag.AlignCenter, self.text().upper())
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QColor(theme.T["accent_hi"]))
            p.drawRoundedRect(r, rad, rad)


def voice_group(name: str) -> str:
    """The group a voice card goes under."""
    if name == CUSTOM or name not in voicefx.PRESETS:
        return MINE
    return next((k for k, _t, names in VOICE_GROUPS if name in names), VOICE_GROUPS[0][0])


class VoiceTile(QToolButton):
    """A voice card: picture over name. A name too long for the card ends in "…" (a
    saved voice's can be 32 characters), the whole name in its tip; an "&" in it
    shows as itself (Qt reads one as a shortcut marker)."""

    def __init__(self, title: str):
        super().__init__()
        self.title = title
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setObjectName("voicetile")
        self.setCheckable(True)
        self.setMinimumWidth(TILE_MIN_W)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(title)
        self._tip = ""          # its own tip; a cut-short name shows the whole name
        self.listed = False     # the list view: a small picture beside the name
        self._cut = False
        # a favorite? the star in its top-right corner (always shown: never on hover only)
        self.star = QToolButton(self)
        self.star.setObjectName("voicestar")
        self.star.setCheckable(True)
        self.star.setFixedSize(STAR, STAR)
        self.star.setCursor(Qt.CursorShape.PointingHandCursor)
        self.star.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.star.toggled.connect(self._show_star)
        self.toggled.connect(self._show_star)   # on the picked (accent) card: white
        self.toggled.connect(self._show_tip)    # the lit card says a click turns it off
        self._show_star()
        self._fit_name(TILE_MIN_W)

    def _show_star(self, *_a):
        on, picked = self.star.isChecked(), self.isChecked()
        # its hover circle: the hovered card itself is btn_hover, so a lighter one there
        if self.star.property("picked") != picked:
            self.star.setProperty("picked", picked)
            self.star.style().unpolish(self.star)
            self.star.style().polish(self.star)
        icons.set_icon(self.star, "star_filled" if on else "star",
                       "on_accent" if picked else "muted",
                       "on_accent" if picked else "accent", size=16)
        tip = (_("Remove “{name}” from Favorites", name=self.title) if on
               else _("Add “{name}” to Favorites", name=self.title))
        self.star.setToolTip(tip)
        self.star.setAccessibleName(tip)

    def setToolTip(self, tip: str):
        self._tip = tip
        self._show_tip()

    def _show_tip(self, *_a):
        """Its own tip; the lit card's says a second click turns the voice changer off
        (the same on every card: clicking the voice that's on is the off switch)."""
        if self.isCheckable() and self.isChecked():
            tip = _("“{name}” is on. Click it again to turn the voice changer off.",
                    name=self.title)
        else:
            tip = self._tip or (self.title if self._cut else "")
        super().setToolTip(tip)

    def set_listed(self, on: bool):
        self.listed = on
        self.setProperty("listed", on)
        self.setMinimumWidth(LIST_MIN_W if on else TILE_MIN_W)
        self.style().unpolish(self)
        self.style().polish(self)
        self.updateGeometry()
        self._fit_name(self.width())

    def sizeHint(self):
        s = super().sizeHint()
        return QSize(s.width(), LIST_ART + 14) if self.listed else s

    def minimumSizeHint(self):
        s = super().minimumSizeHint()
        return QSize(LIST_MIN_W, LIST_ART + 14) if self.listed else s

    def paintEvent(self, e):
        if not self.listed:
            return super().paintEvent(e)
        from PySide6.QtWidgets import QStyle, QStyleOptionToolButton, QStylePainter
        p = QStylePainter(self)
        opt = QStyleOptionToolButton()
        self.initStyleOption(opt)
        opt.text, opt.icon = "", QIcon()
        p.drawComplexControl(QStyle.ComplexControl.CC_ToolButton, opt)
        h = self.height()
        pic = self.icon().pixmap(QSize(LIST_ART, LIST_ART))
        p.drawPixmap(10, (h - LIST_ART) // 2, pic)
        p.setPen(self.palette().color(self.foregroundRole()))
        x = 10 + LIST_ART + 10
        p.drawText(QRectF(x, 0, self.width() - x - STAR - 8, h),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self.text().replace("&&", "&"))

    def _fit_name(self, width: int):
        room = width - (LIST_ART + 20 + STAR + 8) if self.listed else width - 16
        shown = self.fontMetrics().elidedText(self.title, Qt.TextElideMode.ElideRight,
                                              max(0, room))
        self.setText(shown.replace("&", "&&"))
        self._cut = shown != self.title
        self.setToolTip(self._tip)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_name(self.width())
        self.star.move(self.width() - STAR - (8 if self.listed else 4),
                       (self.height() - STAR) // 2 if self.listed else 4)
