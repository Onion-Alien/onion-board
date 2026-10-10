"""The Voice tab's status bar: one strip at the top that always shows your mic level
and everything that's changing what others hear from it (the voice changer, the AI
voice, the computer voice, the language you speak in), whichever cards are folded.

Each thing that's on is a chip; clicking it opens its card. With nothing on, one
quiet chip says others hear your real voice."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QBoxLayout, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QWidget)

from soundboard.i18n import _
from soundboard.ui import icons
from soundboard.ui.panel import Flow, icon_label
from soundboard.ui.widgets import Meter

GAP = 16            # between the mic half and the chips, side by side


class Chip(QPushButton):
    """One thing that's on: a rounded label with a picture, the accent colour while
    it's on, the warning colour when it went wrong, muted for "your real voice"."""

    def __init__(self, key: str):
        super().__init__()
        self.key = key
        self.setObjectName("vchip")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setIconSize(QSize(16, 16))
        self._look = ("", "", None)

    def show_as(self, text: str, state: str, icon: str = "", picture=None, tip: str = ""):
        """`state`: "on", "warn" or "off". `picture`: a ready QIcon (a voice's art),
        else the line icon `icon` in the state's colour."""
        look = (text, state, icon, id(picture), tip)
        if look == self._look:
            return               # the panel refreshes often: only restyle on a change
        self._look = look
        self.setText(text)
        self.setToolTip(tip)
        if picture is not None:
            self.setIcon(picture)
        elif icon:
            icons.set_icon(self, icon, {"on": "live_text", "warn": "warn_text"}.get(
                state, "muted"), size=16)
        else:
            self.setIcon(QIcon())
        if self.property("state") != state:
            self.setProperty("state", state)
            self.style().unpolish(self)
            self.style().polish(self)


class VoiceStatusBar(QFrame):
    """`set_items([(key, text, state, icon, picture, tip), ...])` shows the chips;
    `open_card(key)` is emitted when one is clicked. `set_level` feeds the meter."""
    open_card = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("voicebar")
        # never what holds the window wide (below ~520 px it became the mini player):
        # narrow, it goes to two rows and the chips wrap (_fit)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        box = self._box = QBoxLayout(QBoxLayout.LeftToRight, self)
        box.setContentsMargins(14, 10, 14, 10)
        box.setSpacing(GAP)

        mic = self._mic = QWidget()
        mic.setObjectName("voicebarpart")      # no fill of its own: the bar's shows
        mh = QHBoxLayout(mic)
        mh.setContentsMargins(0, 0, 0, 0)
        mh.setSpacing(8)
        self.mic_icon = icon_label("mic", _("Your mic level"))
        mh.addWidget(self.mic_icon)
        self.lbl_mic = QLabel(_("No mic open"))   # only then: the icon says the rest
        self.lbl_mic.setObjectName("voicebarlabel")
        self.lbl_mic.hide()
        mh.addWidget(self.lbl_mic)
        self.meter = Meter()
        self.meter.setMinimumWidth(80)
        self.meter.setMaximumWidth(420)    # a level, not a stripe across a wide window
        mh.addWidget(self.meter, 1)
        mh.addStretch(0)
        box.addWidget(mic, 1)

        right = self._right = QWidget()
        right.setObjectName("voicebarpart")
        # wraps onto more lines rather than holding the window wide (the mini player)
        rh = self._chips_row = Flow(right)
        self.lbl_heard = icon_label("ear", _("What others hear from your mic"))
        rh.addWidget(self.lbl_heard)
        box.addWidget(right, 0)
        self.chips: dict[str, Chip] = {}
        self._no_mic = None

    # ---- what's on
    def set_items(self, items: list[tuple]):
        keys = [it[0] for it in items]
        row = self._chips_row
        for k in [k for k in self.chips if k not in keys]:
            gone = self.chips.pop(k)
            row.removeWidget(gone)
            gone.hide()
            gone.deleteLater()
        for key, text, state, icon, picture, tip in items:
            chip = self.chips.get(key)
            if chip is None:
                chip = self.chips[key] = Chip(key)
                chip.clicked.connect(lambda _=False, k=key: self.open_card.emit(k))
            chip.show_as(text, state, icon, picture, tip)
        order = [self.chips[k] for k in keys]
        if [w for w in self._row_widgets() if isinstance(w, Chip)] != order:
            for w in order:                       # after "Others hear", in order
                row.removeWidget(w)
            for w in order:
                row.addWidget(w)
                w.show()
        row.invalidate()
        self._fit()

    def texts(self) -> list[str]:
        """The chips' words, in order (tests, the tab's accessible summary)."""
        return [w.text() for w in self._row_widgets() if isinstance(w, Chip)]

    def _row_widgets(self) -> list:
        row = self._chips_row
        return [row.itemAt(i).widget() for i in range(row.count())]

    # ---- the mic
    def set_level(self, level: float | None):
        """None: there's no mic open (the meter can't move; the label says so)."""
        no_mic = level is None
        self.meter.set_level(0.0 if no_mic else level)
        if no_mic != self._no_mic:
            self._no_mic = no_mic
            self.lbl_mic.setVisible(no_mic)
            icons.set_label_icon(self.mic_icon, "mic", "warn_text" if no_mic else "muted")

    # ---- one row, or two when it's narrow
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def _fit(self):
        m = self._box.contentsMargins()
        room = self.width() - m.left() - m.right()
        line = sum(w.sizeHint().width() + 6 for w in self._row_widgets())   # one line
        need = 160 + GAP + line
        d = QBoxLayout.LeftToRight if room >= need else QBoxLayout.TopToBottom
        # beside the meter the chips keep to one line; under it they wrap
        self._right.setMinimumWidth(line if d == QBoxLayout.LeftToRight else 0)
        # Flow's hint remembers its last width. Without a cap it takes the spare
        # room on the next layout pass and squeezes the mic meter to its minimum.
        self._right.setMaximumWidth(line if d == QBoxLayout.LeftToRight else 16777215)
        if self._box.direction() != d:
            self._box.setDirection(d)
            self._box.setSpacing(GAP if d == QBoxLayout.LeftToRight else 8)
