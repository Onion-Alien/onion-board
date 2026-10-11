"""The offer to update Onion Board's part of the mic (MicUpdateOffer): a small card
over the middle of the window, shown a moment after it opens when the mic part is an
older version. Nothing is installed until *Install update* is clicked: *Not now*,
Escape and closing only put it away (the Setup tab keeps the update on offer).

Not a dialog: sounds and hotkeys keep working while it's up, and it never steals
the screen from another app (the main window shows it only while it's open)."""
from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import (QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
                               QPushButton, QStyle, QVBoxLayout, QWidget)

from soundboard import michelper, theme
from soundboard.i18n import _
from soundboard.ui import icons
from soundboard.ui.bunnywidget import BunnyWidget

WIDTH = 460
RADIUS = 12      # a card's corners (DESIGN.md: radius.card)


def prompt_note(frozen: bool | None = None) -> str:
    """What the next Windows prompt will name: Python when running from source (it
    asks for python.exe), else the app itself."""
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        return _("Next: Windows will ask permission for OnionBoard.exe.")
    return _("The Windows prompt names Python because you're running from source.")


def _shield(btn: QPushButton):
    """Windows' admin shield on the button, like Windows' own buttons that ask for
    permission; the app's painted shield where the style has none (offscreen)."""
    ic = btn.style().standardIcon(QStyle.StandardPixmap.SP_VistaShield)
    if ic.isNull() or not ic.availableSizes():
        icons.set_icon(btn, "shield", "on_accent")
    else:
        btn.setIcon(ic)


class MicUpdateOffer(QFrame):
    accepted = Signal()    # Install update: the caller checks again, then asks Windows
    finished = Signal()    # put away, either way (Install, Not now, Escape, closed)

    def __init__(self, parent: QWidget, frozen: bool | None = None):
        super().__init__(parent)
        self.setObjectName("micupdate")
        self.setFixedWidth(WIDTH)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # the tinted header: what it is and what it gets them, Bun with his mic
        self.head = QWidget()
        self.head.setStyleSheet("background:transparent;")   # the tint is painted below
        h = QHBoxLayout(self.head)
        h.setContentsMargins(18, 12, 12, 12)
        h.setSpacing(12)
        words = QVBoxLayout()
        words.setSpacing(4)
        words.addStretch(1)
        self.title = QLabel(_("Your mic, upgraded"))
        self.title.setWordWrap(True)
        self.title.setObjectName("helptitle")   # the Title role (DESIGN.md: Standard kit)
        words.addWidget(self.title)
        self.benefit = QLabel(_("Compatibility fixes for games, calls and browsers."))
        self.benefit.setWordWrap(True)
        words.addWidget(self.benefit)
        words.addStretch(1)
        h.addLayout(words, 1)
        self.bun = BunnyWidget("mic", height=80, pad=6)
        h.addWidget(self.bun, 0, Qt.AlignmentFlag.AlignVCenter)
        v.addWidget(self.head)

        body = QVBoxLayout()
        body.setContentsMargins(18, 12, 18, 18)
        body.setSpacing(8)
        ask = michelper.will_ask()   # the mic helper with this part: no prompt
        self.body = QLabel(_("Windows asks for permission. Audio pauses briefly during "
                             "the update.") if ask else
                           _("Audio pauses briefly during the update."))
        self.body.setWordWrap(True)
        body.addWidget(self.body)
        self.note = QLabel(prompt_note(frozen))
        self.note.setObjectName("hint")
        self.note.setWordWrap(True)
        self.note.setVisible(ask)
        body.addWidget(self.note)
        body.addSpacing(4)
        # the footer: where to find it later, then the actions (main one first)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.later_note = QLabel(_("You can update later in Setup."))
        self.later_note.setObjectName("hint")
        self.later_note.setWordWrap(True)
        row.addWidget(self.later_note, 1)
        self.btn_install = QPushButton(_("Install update"))
        self.btn_install.setObjectName("primary")
        if ask:
            _shield(self.btn_install)
        self.btn_install.clicked.connect(self._install)
        row.addWidget(self.btn_install)
        self.btn_later = QPushButton(_("Not now"))
        self.btn_later.clicked.connect(self.dismiss)
        row.addWidget(self.btn_later)
        body.addLayout(row)
        v.addLayout(body)


        shadow = QGraphicsDropShadowEffect(self)   # floats above the window (a layer)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 110))
        self.setGraphicsEffect(shadow)
        parent.installEventFilter(self)
        self._done = False

    # ------------------------------------------------------------------ showing
    def popup(self):
        """Show it in the middle of the window, Install focused (Enter installs,
        Escape puts it away)."""
        self.adjustSize()
        self._centre()
        self.show()
        self.raise_()
        self.btn_install.setFocus(Qt.FocusReason.PopupFocusReason)

    def _centre(self):
        p = self.parentWidget()
        if p is not None:
            self.move(max(0, (p.width() - self.width()) // 2),
                      max(0, (p.height() - self.height()) // 2))

    def eventFilter(self, obj, ev):
        if obj is self.parentWidget() and ev.type() == QEvent.Type.Resize:
            self._centre()
        return False

    def keyPressEvent(self, ev):
        # Escape on its buttons comes up to here (they don't use it)
        if ev.key() == Qt.Key.Key_Escape:
            self.dismiss()
        else:
            super().keyPressEvent(ev)

    # ------------------------------------------------------------------ answers
    def _install(self):
        if self._done:
            return
        self._close()
        self.accepted.emit()

    def dismiss(self):
        """Not now, Escape or closed: put away, nothing installed."""
        if not self._done:
            self._close()

    def _close(self):
        self._done = True
        p = self.parentWidget()
        if p is not None:
            p.removeEventFilter(self)
        self.hide()
        self.finished.emit()
        self.deleteLater()

    # ------------------------------------------------------------------ painting
    def paintEvent(self, ev):
        """A card with a header tinted from the accent colours (theme tokens, so it
        follows every theme)."""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = theme.T
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), RADIUS, RADIUS)
        p.setClipPath(clip)
        p.fillRect(self.rect(), QColor(t["panel"]))
        hh = self.head.height()
        grad = QLinearGradient(0, 0, self.width(), hh)
        a, b = QColor(t["accent"]), QColor(t["accent2"])
        a.setAlpha(95)
        b.setAlpha(45)
        grad.setColorAt(0, a)
        grad.setColorAt(1, b)
        p.fillRect(0, 0, self.width(), hh, grad)
