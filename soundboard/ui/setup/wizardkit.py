"""The setup guide's shared sizes and small builders: every step's page is laid out
from these (ui/setup/setupwizard.py and its steps), and WizardStep, the steps' base."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from soundboard.ui.kit import theme
from soundboard.ui.bun.bunnywidget import BunnyWidget
from soundboard.ui.kit.choicetile import ChoiceTile
from soundboard.ui.kit.modalframe import BADGE, GAP, SHADOW, ModalDialog, ModalFrame
from soundboard.i18n import _


# step 3's "I don't use the cable" list: this choice sends nowhere (Config.route "off")
NOWHERE = _("Nobody: only I hear them")
SETTLE_MS = 60          # after a step change, the window settles to what the steps need

TILE_W = 138                  # a device tile; TILE_COLS of them fill the page's width
TILE_MIN_H = 72               # a tile's least height (as tall as its names need: tile_h)
TILE_COLS, TILE_GAP = 4, 12
CONTENT_W = TILE_COLS * TILE_W + (TILE_COLS - 1) * TILE_GAP   # a page's width: one row
# the first launch's look step: 3 x 3 looks as wide as the page, then the switches step:
# 2 x 2 cards as wide as the page
LOOK_CARD_GAP = 12
LOOK_CARD_W, LOOK_CARD_H = (CONTENT_W - 2 * LOOK_CARD_GAP) // 3, 124
SWITCH_CARD_W = (CONTENT_W - LOOK_CARD_GAP) // 2
SWITCH_ROW_H = 30   # every switch's row on those cards
MARGIN = 24                   # the dialog's sides: the step bar, pages and Back / Next
HEADER_GAP = 20               # every step: between the title + words and what's below
SECTION_GAP = 16              # between a step's parts (a card, a list, the footer line)
# Bun beside each step's title, top-aligned with it and no taller than the title and
# two lines of words: the header ends where its text does, so the gap under every
# step's words is HEADER_GAP and nothing more (a taller Bun left a band under them)
BUN_H, BUN_PAD = 74, 5
# the guide's motion (only with Windows' Animation effects on: toast.animations_on)
PAGE_MS = 220                                    # a new step fades in
STEP_MS = 260                                    # the step bar fills to the new step
TITLE_CSS = "font-size:17pt; font-weight:800;"   # DESIGN.md Standard kit: Display
BODY_CSS = "font-size:11pt;"                      # ... Large (a full-page guide's body)


def _ok() -> str:    # status colours readable on the current theme (theme.status)
    return theme.status("ok")


def _bad() -> str:
    return theme.status("warn")


def _nav_words(text: str) -> str:
    """Back / Next's words without their text arrow or tick: the buttons carry painted
    ones (a font's arrow glyph is a hairline next to the bold words)."""
    return re.sub(r"[←→✓]", "", text).strip()


NAV_GAP = " "   # a thin space (U+2009) between Back / Next's words and their arrow


def _cable_text(text: str) -> str:
    """A cable button's words without their ⬇ (the button has the cable picture)."""
    return text.replace("⬇", "").strip()


def _test_title() -> str:
    return _("Play a test sound")


# the generic first words of Windows' device names ("Microphone (Product)"), English
# and a few common Windows languages: only these get split (_split_name)
_KINDS = ("mic", "headphone", "headset", "speaker", "earphone", "line", "cable", "input",
          "output", "digital", "mikrofon", "lautsprecher", "kopfh", "micro", "haut-parleur",
          "casque", "altavoz", "auricular", "altoparlant", "cuffie", "fone")


def _split_name(name: str) -> tuple[str, str]:
    """A tile's words for a device: Windows names most of them "Kind (Product)", so
    "Microphone (Logitech G733 Gaming Headset)" shows the product big and "Microphone"
    small under it. Short brackets ("Headset Mic (USB)") and names whose first part
    isn't a kind ("LG ULTRAGEAR (NVIDIA High Definition Audio)") stay whole."""
    m = re.match(r"^([^()]+?)\s*\((.{6,})\)( #\d+)?$", name)
    if m and any(k in m.group(1).lower() for k in _KINDS):   # (a second copy: "... #2")
        return m.group(2) + (m.group(3) or ""), m.group(1)
    return "", ""


def _choice_icon(name: str, kind: str) -> str:
    """A device's picture in the pick lists: a mic, headphones or a speaker."""
    if kind == "input":
        return "mic"
    low = name.lower()
    return "headphones" if any(w in low for w in ("headphone", "headset", "earbud",
                                                 "airpods", "buds")) else "volume"


def tile_h(tiles: list[ChoiceTile]) -> int:
    """One height for a list's tiles: what the tallest name needs (at least
    TILE_MIN_H), set on each of them."""
    h = max([TILE_MIN_H, *(t.needed_height() for t in tiles)])
    for t in tiles:
        t.setFixedHeight(h)
    return h


def _card(margins: int = 16, spacing: int = 12,
          roomy: bool = True) -> tuple[QFrame, QVBoxLayout]:
    """A rounded panel (the theme's card) to group a page's buttons; `roomy` gives
    them the theme's bigger padding."""
    card = QFrame()
    card.setObjectName("card")
    theme.vary_texture(card)
    card.setProperty("roomy", roomy)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(margins, margins, margins, margins)
    lay.setSpacing(spacing)
    return card, lay


def scrolled(inner: QWidget) -> QScrollArea:
    """`inner` in a frameless scroll area that only scrolls down (a guide's long steps)."""
    body = QWidget()
    bl = QVBoxLayout(body)
    bl.setContentsMargins(0, 0, 8, 0)
    bl.addWidget(inner)
    bl.addStretch(1)
    scroll = QScrollArea()
    scroll.setWidget(body)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setMinimumHeight(300)
    return scroll


def _label(text: str, css: str = BODY_CSS) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setTextFormat(Qt.TextFormat.RichText)
    lbl.setStyleSheet(css)
    return lbl


def _section(text: str) -> QLabel:
    """A part of a step's title ("Microphone"): one line, never wrapped."""
    lbl = QLabel(f"<b>{text}</b>")
    lbl.setTextFormat(Qt.TextFormat.RichText)
    lbl.setStyleSheet(BODY_CSS)
    return lbl


def _header(title: str | QLabel, body: QLabel, bun: BunnyWidget) -> QHBoxLayout:
    """A page's title and intro, with Bun (holding something that fits the page)
    beside both, top-aligned with the title. He's no taller than the words, so the
    header ends where they do (BUN_H)."""
    row = QHBoxLayout()
    row.setSpacing(16)
    col = QVBoxLayout()
    col.setSpacing(10)
    col.addWidget(_label(title, TITLE_CSS) if isinstance(title, str) else title)
    col.addWidget(body)
    col.addStretch(1)
    row.addLayout(col, 1)
    row.addWidget(bun, 0, Qt.AlignmentFlag.AlignTop)
    return row


GUIDE_W = 620   # a chat / stream guide on the frame: the widest a dialog gets (DESIGN.md)
SMALL_W = 520   # a short question or note on the frame
MAX_W = 620     # the widest a dialog gets (DESIGN.md *Dialog anatomy*)


def small_ask(dlg: ModalDialog, subtitle: str = "") -> ModalFrame:
    """A short question on kit's small modal (`ModalDialog`, the look `confirm()` has):
    the subtitle under its title, and wider than its panel only when a row of buttons
    needs it (German is 30% longer), up to a dialog's widest. Returns its frame."""
    frame = dlg.frame
    if subtitle:
        frame.subtitle.setText(subtitle)
        frame.subtitle.setVisible(True)   # (in the dialog's layout already: no window of its own)
    _FitButtons(dlg)
    return frame


class _FitButtons(QObject):
    """Before a small modal shows: as wide as its footer's buttons need (styled first, so
    their padding counts), never past MAX_W; ModalDialog then sizes its height."""

    def __init__(self, dlg: ModalDialog):
        super().__init__(dlg)
        dlg.installEventFilter(self)

    def eventFilter(self, obj, ev):   # noqa: N802 - Qt API
        if ev.type() == QEvent.Type.Show and isinstance(obj, ModalDialog):
            for w in obj.findChildren(QWidget):
                w.ensurePolished()
            lay = obj.frame.layout()
            if lay is not None:
                lay.invalidate()
                lay.activate()
                need = min(lay.totalMinimumSize().width(), MAX_W) + 2 * SHADOW   # (its margins)
                if need > obj.width():
                    obj.setFixedWidth(need)
        return False


def framed(dlg: QDialog, title: str, subtitle: str = "", *, mascot: str = "bun",
           close: bool = True, scroll: bool = False) -> ModalFrame:
    """`dlg`'s whole face on the shared frame (kit/modalframe.py, DESIGN.md *Modal frame*):
    Bun, the title and ✕ in the header, then whatever goes in `frame.body` and the
    buttons in its footer. The ✕ is Cancel / Done (`dlg.reject`). `scroll`: a long
    guide's body scrolls when the screen is too short for it (the header and the buttons
    stay put); otherwise it is as tall as its words, as without."""
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(0, 0, 0, 0)
    frame = ModalFrame(title, subtitle, mascot=mascot, close=close, docked=True)
    frame.close_btn.clicked.connect(dlg.reject)
    if scroll:
        page = QWidget()
        page.setObjectName("modalpoint")   # (see-through: the frame's own surface)
        inner = QVBoxLayout(page)
        inner.setSpacing(frame.body.spacing())
        frame.body.addWidget(_GuideScroll(page))
        frame.body = inner   # what goes in the body (add_point too) goes in the scroll
    lay.addWidget(frame)
    # as narrow as its own width (SMALL_W / GUIDE_W), wider only for a row of buttons
    # that needs it (German is 30% longer), never past a dialog's widest (DESIGN.md)
    dlg.setMaximumWidth(max(dlg.minimumWidth(), MAX_W))
    _TrueHeight(dlg)
    return frame


def _GuideScroll(page: QWidget):   # noqa: N802 - a class, made on first use
    """The setup guide's step scroll (wizardparts._StepScroll: as tall as the page, a
    scroll bar only when the screen is too short), growing the dialog it is in."""
    from soundboard.ui.kit import fit
    from soundboard.ui.setup.wizardparts import _StepScroll

    class GuideScroll(_StepScroll):
        def eventFilter(self, obj, ev):   # noqa: N802 - Qt API
            if obj is self._page and ev.type() == QEvent.Type.LayoutRequest:
                self.updateGeometry()
                if self.window().isVisible():
                    fit.fit(self.window())   # the dialog, not the frame (a card) it's in
            return QScrollArea.eventFilter(self, obj, ev)

    return GuideScroll(page)


class _TrueHeight(QObject):
    """When a framed dialog shows: as tall as its words are at its width (no taller than
    the screen). Qt's first guess wraps them narrower, which left an empty band under the
    header (fit.watch only grows)."""

    def __init__(self, dlg: QDialog):
        super().__init__(dlg)
        dlg.installEventFilter(self)

    def eventFilter(self, obj, ev):   # noqa: N802 - Qt API
        if ev.type() == QEvent.Type.Show:
            from soundboard.ui.kit import fit
            lay = obj.layout()
            lay.activate()
            width = min(max(obj.minimumWidth(), lay.totalMinimumSize().width()),
                        obj.maximumWidth())
            room = obj.screen().availableGeometry().height() - (
                obj.frameGeometry().height() - obj.height())
            obj.resize(width, min(fit.needed_height(obj, width), room))
        return False


def indent(frame: ModalFrame) -> int:
    """How far in the frame's words start: the title's edge (past the mascot)."""
    return frame.lead + GAP if frame.mascot is not None else 0


def aligned(frame: ModalFrame, w: QWidget | QHBoxLayout) -> QHBoxLayout:
    """`w` in the frame's body, starting on the title's edge like the points' words."""
    row = QHBoxLayout()
    row.setContentsMargins(indent(frame), 0, 0, 0)
    row.setSpacing(8)
    if isinstance(w, QHBoxLayout):
        row.addLayout(w, 1)
    else:
        row.addWidget(w, 1)
    frame.body.addLayout(row)
    return row


def actions(frame: ModalFrame, *buttons: QWidget) -> QWidget:
    """A guide's other actions (Copy the mic name, Open Discord, ...): default buttons at
    their own width on the title's edge, wrapping when the words are long, above the
    footer's main button."""
    from soundboard.ui.kit.panellayouts import Flow
    holder = QWidget()
    holder.setObjectName("modalpoint")   # (see-through, like the points)
    row = Flow(holder, gap=8)
    for b in buttons:
        if isinstance(b, QPushButton):
            b.setAutoDefault(False)   # Enter is the footer's main button, not these
        row.addWidget(b)
    frame.body.addSpacing(4)
    aligned(frame, holder)
    return holder


def rich(frame: ModalFrame, text: str, hint: bool = False) -> QLabel:
    """A paragraph with bold words in the frame's body, on the title's edge."""
    lbl = QLabel(text)
    lbl.setObjectName("hint" if hint else "helpbody")
    lbl.setTextFormat(Qt.TextFormat.RichText)
    lbl.setWordWrap(True)
    aligned(frame, lbl)
    return lbl


class StepRow(QWidget):
    """One numbered step of a guide: the number on the frame's point square, under the
    mascot, and the step's words on the title's edge (the same lines as a point)."""

    def __init__(self, n: int, text: str, lead: int, parent=None):
        super().__init__(parent)
        self.setObjectName("modalpoint")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(GAP)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        self.num = QLabel(str(n))
        self.num.setObjectName("modalpointicon")
        self.num.setFixedSize(BADGE, BADGE)
        self.num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = self.num.font()
        f.setBold(True)
        self.num.setFont(f)
        col.addWidget(self.num, 0, Qt.AlignmentFlag.AlignHCenter)
        col.addStretch(1)
        holder = QWidget()
        holder.setObjectName("modalpoint")
        holder.setFixedWidth(max(lead, BADGE))
        holder.setLayout(col)
        row.addWidget(holder)
        self.text = QLabel(text)
        self.text.setObjectName("helpbody")
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.text.setWordWrap(True)   # (a link in it: the guide connects linkActivated)
        # the first line's middle level with the number's (a line of body text is ~20 px)
        self.text.setContentsMargins(0, (BADGE - 20) // 2, 0, 0)
        row.addWidget(self.text, 1)


def steps(frame: ModalFrame, *items: str, layout: QVBoxLayout | None = None) -> list[StepRow]:
    """A guide's numbered steps (each translated whole) in the frame's body, or in
    `layout` (a scrolled part of it)."""
    rows = [StepRow(i + 1, t, frame.lead) for i, t in enumerate(items)]
    for r in rows:
        (layout if layout is not None else frame.body).addWidget(r)
    return rows


def scrolled_steps(frame: ModalFrame, *items: str) -> tuple[list[StepRow], QVBoxLayout]:
    """A long guide's numbered steps in a scroll area that takes the frame's spare
    height (the intro above and the buttons below stay put). Returns the rows and the
    scrolled column (for a line after them)."""
    inner = QWidget()
    inner.setObjectName("modalpoint")
    col = QVBoxLayout(inner)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(14)
    rows = steps(frame, *items, layout=col)
    frame.body.addWidget(scrolled(inner), 1)
    return rows, col


def _working_title() -> str:   # (a call: translated in the language picked by then)
    return _("Working: your sounds go into your mic")


# what a step's mixin gets from SetupWizard, for the type checker only: at run time
# WizardStep is a plain, empty class (SetupWizard itself is the QDialog)
_Dialog = QDialog if TYPE_CHECKING else object


class WizardStep(_Dialog):
    """The base of each step's mixin (devicestep, cablestep, discordstep, lookstep)."""
    if TYPE_CHECKING:
        from PySide6.QtCore import Signal
        from PySide6.QtWidgets import QButtonGroup, QWidget
        win: Any
        _user_picked: set[str]
        _no_mics: bool
        _no_outs: bool
        chk_discord: Any
        _discord_read: Signal

        def _update_next(self) -> None: ...
        def _settle_size(self) -> None: ...
        def _discord_heading(self) -> str: ...
        def _choice_list(self, names: list[str], current: str | None, on_pick,
                         kind: str = "output") -> tuple[QWidget, QButtonGroup]: ...
