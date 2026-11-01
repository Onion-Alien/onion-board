"""The setup guide's shared sizes and small builders: every step's page is laid out
from these (ui/setup/setupwizard.py and its steps), and WizardStep, the steps' base."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout,
                               QWidget)

from soundboard.ui.kit import theme
from soundboard.ui.bun.bunnywidget import BunnyWidget
from soundboard.ui.kit.choicetile import ChoiceTile
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
    m = re.match(r"^([^()]+?)\s*\((.{6,})\)$", name)
    if m and any(k in m.group(1).lower() for k in _KINDS):
        return m.group(2), m.group(1)
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
        _discord_read: Signal

        def _update_next(self) -> None: ...
        def _settle_size(self) -> None: ...
        def _discord_heading(self) -> str: ...
        def _choice_list(self, names: list[str], current: str | None, on_pick,
                         kind: str = "output") -> tuple[QWidget, QButtonGroup]: ...
