"""+ More tabs' dropdown: each tab that's switched off as a card (its picture, name,
what it's good for and an Add button), so the extras read as things worth having
rather than a list of lines."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu, QPushButton,
                               QVBoxLayout, QWidget, QWidgetAction)

from soundboard import theme
from soundboard.i18n import _
from soundboard.ui import icons

CARD_W = 400
ICON = 40

# what each tab is good for, said to sell it (the tab's own tooltip is the plain one)
PITCH = {
    "radio": _("Thousands of live stations from all over the world. Listen yourself, or "
               "send one into the call for everyone."),
    "apps": _("Share Spotify, a video or a game's sound with your friends, kept apart "
              "from your own."),
    "triggers": _("Plays a sound by itself when something shows up in your game: a YOU "
                  "DIED, a kill, a queue popping."),
    "voice": _("Change your voice live: robots, monsters, other languages, or let it "
               "speak what you type."),
}


class TabCard(QFrame):
    """One switched-off tab: click anywhere on it (or its Add) to add it."""
    picked = Signal()

    def __init__(self, key: str, name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("tabcard")
        self.setAttribute(Qt.WA_Hover)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedWidth(CARD_W)
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 10, 12, 10)
        h.setSpacing(12)
        pic = QLabel()
        pic.setObjectName("tabcardpic")
        pic.setFixedSize(ICON + 16, ICON + 16)
        pic.setAlignment(Qt.AlignCenter)
        pm = icons.pixmap(key, int(ICON * self.devicePixelRatio()), theme.T["accent_hi"])
        pm.setDevicePixelRatio(self.devicePixelRatio())
        pic.setPixmap(pm)
        h.addWidget(pic, 0, Qt.AlignTop)
        words = QVBoxLayout()
        words.setSpacing(3)
        title = QLabel(name)
        title.setObjectName("tabcardtitle")
        words.addWidget(title)
        blurb = QLabel(PITCH.get(key, ""))
        blurb.setObjectName("tabcardblurb")
        blurb.setWordWrap(True)
        words.addWidget(blurb)
        h.addLayout(words, 1)
        add = QPushButton(_("Add"))
        add.setObjectName("primary")
        icons.set_icon(add, "plus", "on_accent")
        add.setCursor(Qt.PointingHandCursor)
        add.setFocusPolicy(Qt.NoFocus)
        add.clicked.connect(self.picked)
        h.addWidget(add, 0, Qt.AlignVCenter)
        # a wrapped label's height follows its width, which a menu doesn't settle
        # before measuring: fixed, so no line is cut off
        blurb.setFixedWidth(CARD_W - 24 - (ICON + 16) - 2 * 12 - add.sizeHint().width() - 4)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.rect().contains(ev.position().toPoint()):
            self.picked.emit()
        super().mouseReleaseEvent(ev)


def fill(menu: QMenu, tabs: list[tuple[str, str, str]], add, settings):
    """Fill `menu` with a header, a card per (key, name, tip) in `tabs` (`add(key)`
    on a pick) and the Settings > Tabs line."""
    menu.clear()
    head = QWidget()
    head.setObjectName("tabcardtop")
    hv = QVBoxLayout(head)
    hv.setContentsMargins(12, 8, 12, 4)
    hv.setSpacing(2)
    t = QLabel(_("Add more to Onion Board"))
    t.setObjectName("tabcardhead")
    hv.addWidget(t)
    sub = QLabel(_("Free, and each one only loads once you add it."))
    sub.setObjectName("tabcardblurb")
    hv.addWidget(sub)
    ha = QWidgetAction(menu)
    ha.setDefaultWidget(head)
    ha.setEnabled(False)
    menu.addAction(ha)
    for key, name, tip in tabs:
        card = TabCard(key, name)
        act = QWidgetAction(menu)
        act.setDefaultWidget(card)
        act.setText(_("{tab}: {tip}", tab=name, tip=tip))   # screen readers, keyboard
        act.triggered.connect(lambda _c=False, k=key: add(k))
        card.picked.connect(lambda a=act: (a.trigger(), menu.close()))
        menu.addAction(act)
    menu.addSeparator()
    menu.addAction(icons.icon("settings"), _("Choose tabs in Settings…"), settings)
