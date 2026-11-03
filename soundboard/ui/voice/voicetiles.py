"""The voice changer's voice cards: `VoiceTile`, the groups they're shown in, and
`BigSwitch`, a card's main on/off."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter
from PySide6.QtWidgets import QSizePolicy, QToolButton

from soundboard.ui.kit import theme
from soundboard import voicefx
from soundboard.ui.kit import icons
from soundboard.i18n import _, ngettext
from soundboard.ui.kit.pixels import snap_to_pixels
from soundboard.ui.voice.fxcontrols import Switch


CUSTOM = "Custom"
TILE_ART = 48     # px: a voice card's picture (when there is one, see ui/voice/art.py)
TILE_MIN_W = 124  # px: a voice card at its narrowest (the row holds as many as fit)
TILE_GAP = 8      # px: between voice cards
DETAIL_MIN_W = 148  # px: an Advanced voice card at its narrowest
DETAIL_LINES = 3  # the lines under an Advanced card's name, at most
DETAIL_TOP = 9    # px: an Advanced card's picture from its top (as a Simple card's)
DETAIL_FOOT = 10  # px: under an Advanced card's last line
LIST_ART = 30     # px: a small voice picture (a voice chat server's row)
MAX_COLS = 12     # voice cards a row, at most
PICKED_ART = 32   # px: the picked voice's picture, under the cards


# the Voice tab's switch over its voice cards: Simple (picture and name) or Advanced
# (a bigger card that says what the voice does). An older version's "list" is Advanced.
SIMPLE, ADVANCED = "simple", "advanced"


def view_choices() -> tuple[tuple[str, str, str, str], ...]:
    """The Simple / Advanced switch's two buttons (ViewToggle's `choices`)."""
    return ((SIMPLE, "", _("Simple"), _("Pictures and names")),
            (ADVANCED, "", _("Advanced"), _("Bigger cards that say what each voice does")))


def is_advanced(view: str) -> bool:
    return view in (ADVANCED, "list")


# what each effect does, in a few plain words, for an Advanced card ("Meows instead of
# words"); built when asked, in the app's language. An add-on's effect shows its name.
def _fx_words() -> dict[str, str]:
    return {"harmony": _("Harmony voices"), "growl": _("Monster growl"),
            "robot": _("Robot buzz"), "monk": _("Monk chant"), "ringmod": _("Metal ring"),
            "cat": _("Meows instead of words"), "dog": _("Barks instead of words"),
            "goat": _("Bleats instead of words"), "sheep": _("Baas instead of words"),
            "cow": _("Moos instead of words"), "duck": _("Quacks instead of words"),
            "pig": _("Oinks instead of words"), "farm": _("Farm animals instead of words"),
            "chatter": _("Gibberish blips"), "fart": _("Farts instead of words"),
            "drums": _("Drum hits instead of words"), "whistle": _("Whistled words"),
            "kazoo": _("Kazoo buzz"), "radio": _("Radio sound"), "distortion": _("Crunchy"),
            "shout": _("Blows out when you shout"), "helmet": _("In a helmet"),
            "glitch": _("Glitchy cuts"), "bitcrush": _("8-bit crunch"),
            "chorus": _("Shimmery double"), "flanger": _("Jet swirl"), "wobble": _("Wobbly"),
            "echo": _("Echoes"), "polish": _("Studio polish")}


# an Advanced card's order: the voice itself (pitch, then what it turns you into), then
# the room it's in, then the clean-up. The compressor isn't named: nearly every voice
# has one, so it said the same on every card.
_SPACE = ("echo", "reverb")
_CLEANUP = ("tone", "polish")
_UNNAMED = ("compressor",)


def _fx_phrase(etype: str, cfg: dict, words: dict[str, str]) -> list[str]:
    if etype == "pitch":
        out = [_("Auto-tuned")] if cfg.get("tune") else []
        st = round(float(cfg.get("semitones", 0) or 0))
        if st:
            out.append(ngettext("{n} note higher", "{n} notes higher", st) if st > 0 else
                       ngettext("{n} note lower", "{n} notes lower", -st))
        return out
    if etype == "reverb":
        size = float(cfg.get("size", 0.5) or 0)
        return [_("Small room") if size < 0.35 else _("Big room") if size < 0.65
                else _("Big hall")]
    if etype == "tone":
        bass = float(cfg.get("bass", 0) or 0)
        return [_("Extra bass") if bass >= 2 else _("Less bass") if bass <= -2
                else _("Tone tweaked")]
    if etype in words:
        return [words[etype]]
    cls = voicefx.REGISTRY.get(etype)
    return [voicefx.shown(cls.name) if cls is not None else etype]


def fx_detail(effects: dict) -> str:
    """What a voice changer voice does, for its Advanced card, every effect in plain
    words: "6 notes lower · Monster growl · Crunchy · Big hall"."""
    words = _fx_words()
    rank = {t: 2 if t in _SPACE else 3 if t in _CLEANUP else 1 for t in effects}
    rank["pitch"] = 0
    parts: list[str] = []
    for etype in sorted((t for t in effects if t not in _UNNAMED), key=lambda t: rank[t]):
        cfg = effects[etype]
        parts += _fx_phrase(etype, cfg if isinstance(cfg, dict) else {}, words)
    return " · ".join(dict.fromkeys(parts)) if parts else _("No effects")


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
        self.detailed = False   # Advanced: a line under the name saying what it does
        self.detail = ""
        self._cut = False
        self._detail_cut = False   # Advanced: its detail ends in "…" (the tip has it all)
        self._lines = -1           # Advanced: the lines its detail took last
        self.progress: float | None = None   # its download, 0 to 1, while it waits for it
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

    def set_progress(self, done: float | None):
        """Downloading its recordings (0 to 1): a bar along its foot, and its tip says
        so; None: done (or dropped)."""
        if done == self.progress:
            return
        self.progress = done
        self._show_tip()
        self.update()

    def _show_tip(self, *_a):
        """Its own tip; the lit card's says a second click turns the voice changer off
        (the same on every card: clicking the voice that's on is the off switch)."""
        if self.progress is not None:
            tip = _("Downloading “{name}”: {percent}%. It goes on once it's in; click "
                    "again to cancel.", name=self.title, percent=round(self.progress * 100))
        elif self.isCheckable() and self.isChecked():
            tip = _("“{name}” is on. Click it again to turn the voice changer off.",
                    name=self.title)
        else:
            tip = self._tip or (self.title if self._cut else "")
            if self.detailed and self._detail_cut:   # its line in full
                tip = f"{tip or self.title}\n{self.detail}"
        super().setToolTip(tip)

    def set_detailed(self, on: bool):
        """Advanced (on): a bigger card, with its `detail` under the name. It's as tall
        as its lines need; a shorter card grows to its row's tallest (Minimum), so a row
        stays level with no empty foot on every card."""
        self.detailed = on
        self.setMinimumWidth(DETAIL_MIN_W if on else TILE_MIN_W)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Minimum if on else QSizePolicy.Policy.Fixed)
        self.updateGeometry()
        self._fit_name(self.width())
        self.update()

    def set_detail(self, text: str):
        """What the voice does, in a few words (shown on the Advanced card)."""
        if text != self.detail:
            self.detail = text
            self._fit_name(self.width())
            self.update()

    def _detail_font(self) -> QFont:
        f = QFont(self.font())
        f.setBold(False)
        f.setPointSizeF(max(f.pointSizeF() - 0.5, 7.0))
        return f

    def _detail_lines(self, width: int) -> list[str]:
        """Its detail on the lines it takes at `width` (none without one)."""
        if not self.detail:
            return []
        return wrap_lines(QFontMetrics(self._detail_font()), self.detail, width - 16,
                          DETAIL_LINES)

    def _detailed_h(self) -> int:
        """An Advanced card's height: picture, name and the lines its detail takes now
        (a card left room for three, so most had an empty foot)."""
        lines = len(self._detail_lines(max(self.width(), DETAIL_MIN_W)))
        return (DETAIL_TOP + self.iconSize().height() + 4 + self.fontMetrics().height() + 2
                + lines * QFontMetrics(self._detail_font()).lineSpacing() + DETAIL_FOOT)

    def sizeHint(self):
        s = super().sizeHint()
        return QSize(s.width(), self._detailed_h()) if self.detailed else s

    def minimumSizeHint(self):
        # (QToolButton's is its sizeHint: the detail's room is in it already)
        s = super().minimumSizeHint()
        return QSize(DETAIL_MIN_W, s.height()) if self.detailed else s

    def paintEvent(self, e):
        if not self.detailed:
            super().paintEvent(e)
        else:
            self._paint_detailed()
        if self.progress is not None:
            self._paint_progress(self.progress)

    def _paint_progress(self, got: float):
        """The download's bar: a track along the card's foot, filled as far as it got."""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        h = 4
        track = QRectF(10, self.height() - h - 5, self.width() - 20, h)
        p.setBrush(QColor(theme.T["border_hi"]))
        p.drawRoundedRect(track, h / 2, h / 2)
        done = QRectF(track)
        done.setWidth(max(h, track.width() * got))
        p.setBrush(QColor(theme.T["accent"]))
        p.drawRoundedRect(done, h / 2, h / 2)
        p.end()

    def _paint_detailed(self):
        """Advanced: the card as Simple draws it (picture over name), and what the voice
        does under the name, on up to DETAIL_LINES lines."""
        from PySide6.QtWidgets import QStyle, QStyleOptionToolButton, QStylePainter
        p = QStylePainter(self)
        opt = QStyleOptionToolButton()
        self.initStyleOption(opt)
        opt.text, opt.icon = "", QIcon()
        p.drawComplexControl(QStyle.ComplexControl.CC_ToolButton, opt)   # its card
        w, art = self.width(), self.iconSize()
        y = DETAIL_TOP
        p.drawPixmap((w - art.width()) // 2, y, self.icon().pixmap(art))
        y += art.height() + 4
        on = self.isChecked()
        name = QFont(self.font())
        name.setBold(on)   # (as the stylesheet's lit card)
        p.setFont(name)
        p.setPen(QColor(theme.T["on_accent" if on else
                                 "muted" if self.property("missing") else "text"]))
        fm = QFontMetrics(name)
        p.drawText(QRect(8, y, w - 16, fm.height()), Qt.AlignmentFlag.AlignCenter,
                   self.text().replace("&&", "&"))
        y += fm.height() + 2
        if self.detail:
            font = self._detail_font()
            p.setFont(font)
            fm = QFontMetrics(font)
            p.setPen(QColor(theme.T["on_accent" if on else "muted"]))
            for line in self._detail_lines(w):
                p.drawText(QRect(8, y, w - 16, fm.lineSpacing()),
                           Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                           line)
                y += fm.lineSpacing()
        p.end()   # (before the download bar's painter)

    def _fit_name(self, width: int):
        room = width - 16
        shown = self.fontMetrics().elidedText(self.title, Qt.TextElideMode.ElideRight,
                                              max(0, room))
        self.setText(shown.replace("&", "&&"))
        self._cut = shown != self.title
        lines = self._detail_lines(width) if self.detailed else []
        self._detail_cut = bool(lines) and " ".join(lines) != self.detail
        self.setToolTip(self._tip)
        if self.detailed and len(lines) != self._lines:
            self._lines = len(lines)   # a line more or less: its row's height changes
            self.updateGeometry()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_name(self.width())
        self.star.move(self.width() - STAR - 4, 4)


def wrap_lines(fm: QFontMetrics, text: str, width: int, most: int) -> list[str]:
    """`text` on lines `width` px wide, `most` of them, the last ending in "…" if it
    doesn't all fit. A line breaks after a " · " where it can ("deeper 0.5" stays
    together), else between words."""
    words: list[str] = []
    for i, part in enumerate(text.split(" · ")):
        if i:
            words[-1] += " ·"
        words += [part] if fm.horizontalAdvance(part) <= width else part.split(" ")
    lines: list[str] = []
    line = ""
    for i, w in enumerate(words):
        if not line or fm.horizontalAdvance(f"{line} {w}") <= width:
            line = f"{line} {w}" if line else w
            continue
        lines.append(line.removesuffix(" ·"))
        if len(lines) == most - 1:
            line = " ".join(words[i:])
            break
        line = w
    lines.append(fm.elidedText(line, Qt.TextElideMode.ElideRight, width))
    return lines[:most]
