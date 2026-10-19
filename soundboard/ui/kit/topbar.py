"""The one look for a bar across the top of the window: an urgent fix, "Set up for it?",
FFmpeg, the language offer, *Enjoying Onion Board?* (DESIGN.md *Top bars*).

The panel's surface with a stripe on the left in the bar's tone, an icon in that colour,
a bold heading and then the rest in a quieter colour, the buttons and a ✕. However many
lines the words wrap to, the icon, the buttons and the ✕ stay centred on the bar."""
from __future__ import annotations

import html
import re

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from soundboard.i18n import _
from soundboard.ui.kit import icons, theme

# tone -> the theme colour of its stripe and icon
TONES = {"info": "accent_text", "warn": "warn_text", "ok": "ok_text"}
ICON = 18             # the icon's size
CLOSE = 26            # the ✕ button's side
# heading to the rest: ~16 px (Qt squeezes other spaces); a line may still break there
GAP = "&nbsp;" * 4 + " "
# a heading ends at the first sentence's end: ". " "! " "? " ": " (or a full-width one,
# which needs no space after it)
_HEAD_END = re.compile(r"[.!?:](?=\s)|[。！？：]")


def split_heading(text: str) -> tuple[str, str]:
    """("Heading.", "the rest") from one message: its first sentence is the heading. One
    sentence only: no heading, all of it is the rest."""
    m = _HEAD_END.search(text)
    if m is None or not text[m.end():].strip():
        return "", text.strip()
    return text[:m.end()].strip(), text[m.end():].strip()


class TopBar(QFrame):
    """A bar across the top of the window. Fill it with ``set_message`` (or
    ``set_text``), ``add_button`` and, for anything under the words (a progress bar, a
    text box), ``add_row``. ``close_btn`` is its ✕: connect what closing means."""

    def __init__(self, icon: str = "info", tone: str = "info", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("topbar")
        self._icon_name, self._tone = icon, tone
        self._head, self._body, self._rich = "", "", False
        h = self._row = QHBoxLayout(self)
        h.setContentsMargins(14, 7, 8, 7)
        h.setSpacing(10)
        self.icon = QLabel()
        self.icon.setObjectName("topbaricon")
        self.icon.setFixedSize(ICON, ICON)
        h.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignVCenter)
        col = self.col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)
        self.words = QLabel()
        self.words.setObjectName("topbarwords")
        self.words.setTextFormat(Qt.TextFormat.RichText)
        self.words.setWordWrap(True)   # never makes the window wider
        col.addWidget(self.words)
        h.addLayout(col, 1)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(6)
        h.addLayout(self.buttons)
        self.close_btn = QPushButton()
        self.close_btn.setObjectName("topbarclose")
        self.close_btn.setAccessibleName(_("Close"))
        self.close_btn.setToolTip(_("Close"))
        icons.close_button(self.close_btn, CLOSE)
        h.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self.set_tone(tone, icon)

    # ---- filling it
    def set_tone(self, tone: str, icon: str | None = None):
        """"info", "warn" or "ok": the stripe's and the icon's colour."""
        self._tone = tone if tone in TONES else "info"
        if icon:
            self._icon_name = icon
        if self.property("tone") != self._tone:
            self.setProperty("tone", self._tone)
            self.style().unpolish(self)
            self.style().polish(self)
        self._paint()

    def set_message(self, text: str, rich: bool = False):
        """One message: its first sentence becomes the heading (split_heading)."""
        head, body = split_heading(text)
        self.set_text(head, body, rich)

    def set_text(self, heading: str, body: str = "", rich: bool = False):
        """The bold heading and the quieter words after it (either may be empty).
        `rich`: they're already HTML (a name in <b>), not plain text."""
        self._head, self._body, self._rich = heading, body, rich
        self._paint()

    def text(self) -> str:
        """The words as plain text: heading and the rest."""
        return " ".join(t for t in (self._head, self._body) if t)

    def add_button(self, text: str = "", primary: bool = False) -> QPushButton:
        """A button before the ✕. At most one primary (DESIGN.md: one per bar)."""
        b = QPushButton(text)
        b.setObjectName("primary" if primary else "topbarbtn")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.buttons.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
        return b

    def add_row(self, widget: QWidget):
        """Something under the words: a progress bar, a text box."""
        self.col.addWidget(widget)

    # ---- drawing
    def _paint(self):
        t = theme.tokens()
        colour = t[TONES[self._tone]]
        self.icon.setPixmap(icons.pixmap(self._icon_name, ICON, colour))
        esc = (lambda s: s) if self._rich else (lambda s: html.escape(s, quote=False))
        parts = []
        if self._head:
            parts.append(f"<span style='color:{t['text_hi']}; font-weight:700'>"
                         f"{esc(self._head)}</span>")
        if self._body:
            parts.append(f"<span style='color:{t['muted'] if self._head else t['text']}'>"
                         f"{esc(self._body)}</span>")
        self.words.setText(GAP.join(parts))

    def changeEvent(self, e):   # noqa: N802 - Qt
        super().changeEvent(e)
        if e.type() == QEvent.Type.StyleChange:   # a theme change: its colours again
            self._paint()
