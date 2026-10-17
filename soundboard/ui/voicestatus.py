"""The Voice tab's status bar: one strip at the top that always shows your mic level
and everything that's changing what others hear from it (the voice changer, the AI
voice, the computer voice, the language you speak in), whichever cards are folded.

Each thing that's on is a chip; clicking it opens its card, and its ✕ turns just
that one off (Stop turns them all off). With nothing on, one plain label explains
that the mic voice is unchanged."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QBoxLayout, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QToolButton, QWidget)

from soundboard.i18n import _
from soundboard.ui import icons
from soundboard.ui.panel import Flow, icon_label
from soundboard.ui.widgets import Meter, widget_at

GAP = 16            # between the mic half and the chips, side by side
ROW_H = 28          # every chip, label and the mic row: the bar never changes height
STOP_H = 36         # the Stop button, bigger than the chips beside it
X_SIDE = 18         # a chip's ✕, inside its right end


class Chip(QPushButton):
    """One thing that's on: a rounded label with a picture, the accent colour while
    it's on, the warning colour when it went wrong."""

    def __init__(self, key: str):
        super().__init__()
        self.key = key
        self.setObjectName("vchip")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setIconSize(QSize(16, 16))
        self.setFixedHeight(ROW_H)
        self._look = ("", "", None)
        # its own ✕: turns just this one off, the others stay on
        self.off = QToolButton(self)
        self.off.setObjectName("vchipx")
        self.off.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        icons.close_button(self.off, X_SIDE)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.off.move(self.width() - X_SIDE - 3, (self.height() - X_SIDE) // 2)

    def show_as(self, text: str, state: str, icon: str = "", picture=None, tip: str = ""):
        """`state`: "on", "warn" or "off". `picture`: a ready QIcon (a voice's art),
        else the line icon `icon` in the state's colour."""
        look = (text, state, icon, id(picture), tip)
        if look == self._look:
            return               # the panel refreshes often: only restyle on a change
        self._look = look
        self.setText(text)
        self.setToolTip(tip)
        self.off.setToolTip(_("Turn off {thing}", thing=text))
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
    `open_card(key)` is emitted when one is clicked, `turn_off(key)` when its ✕ is.
    `set_level` feeds the meter."""
    open_card = Signal(str)
    turn_off = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("voicebar")
        # never what holds the window wide (below ~520 px it became the mini player):
        # narrow, it goes to two rows and the chips wrap (_fit)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        box = self._box = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        box.setContentsMargins(14, 10, 14, 10)
        box.setSpacing(GAP)

        mic = self._mic = QWidget()
        mic.setObjectName("voicebarpart")      # no fill of its own: the bar's shows
        mic.setFixedHeight(STOP_H)
        mh = self._mic_row = QHBoxLayout(mic)
        mh.setContentsMargins(0, 0, 0, 0)
        mh.setSpacing(8)
        # a big red Stop with its word: the one way out of every voice at once, it
        # has to be found at a glance (a lone 28 px square was easy to miss)
        self.stop_button = QPushButton(_("Stop"))
        self.stop_button.setObjectName("danger")
        self.stop_button.setAccessibleName(_("Stop voice effects"))
        self.stop_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_button.setFixedHeight(STOP_H)
        self.stop_button.setMinimumWidth(STOP_H * 2)
        icons.set_icon(self.stop_button, "stop", "danger_text", size=18)
        mh.addWidget(self.stop_button)
        # quick record: opens Record a sound already recording your voice (as others
        # hear it while the voice changer is on); Save keeps it in the tab's Recordings
        self.record_button = QPushButton(_("Record"))
        self.record_button.setToolTip(_("Record your voice as others hear it. It goes in "
                                        "Recordings, above"))
        self.record_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.record_button.setFixedHeight(STOP_H)
        icons.set_icon(self.record_button, "record", "danger_text", size=16)
        mh.addWidget(self.record_button)
        self.mic_icon = icon_label("mic", _("Your mic level"))
        mh.addWidget(self.mic_icon)
        self.lbl_mic = QLabel(_("No mic open"))   # only then: the icon says the rest
        self.lbl_mic.setObjectName("voicebarlabel")
        self.lbl_mic.hide()
        mh.addWidget(self.lbl_mic)
        self.meter = Meter()
        self.meter.setMinimumWidth(80)
        mh.addWidget(self.meter, 1)
        box.addWidget(mic, 1)

        right = self._right = QWidget()
        right.setObjectName("voicebarpart")
        # wraps onto more lines rather than holding the window wide (the mini player)
        rh = self._chips_row = Flow(right)
        self.lbl_heard = icon_label("ear", _("What others hear from your mic"))
        self.lbl_heard.setFixedHeight(ROW_H)
        rh.addWidget(self.lbl_heard)
        # centred on the mic row: Stop is taller than the chips, which sat high
        box.addWidget(right, 0, Qt.AlignmentFlag.AlignVCenter)
        self.chips: dict[str, Chip | QLabel] = {}
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
                if key == "none":
                    chip = QLabel()
                    chip.setObjectName("voicebarlabel")
                    chip.setFixedHeight(ROW_H)
                    chip.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                else:
                    chip = Chip(key)
                    chip.clicked.connect(lambda _=False, k=key: self.open_card.emit(k))
                    chip.off.clicked.connect(lambda _=False, k=key: self.turn_off.emit(k))
                self.chips[key] = chip
            if isinstance(chip, Chip):
                chip.show_as(text, state, icon, picture, tip)
            else:
                chip.setText(text)
                chip.setToolTip(tip)
        order = [self.chips[k] for k in keys]
        if [w for w in self._row_widgets() if w in self.chips.values()] != order:
            for w in order:                       # after "Others hear", in order
                row.removeWidget(w)
            for w in order:
                row.addWidget(w)
                w.show()
        row.invalidate()
        self._fit()

    def texts(self) -> list[str]:
        """The chips' words, in order (tests, the tab's accessible summary)."""
        return [w.text() for w in self._row_widgets() if w in self.chips.values()]

    def _row_widgets(self) -> list:
        row = self._chips_row
        return [w for i in range(row.count()) if (w := widget_at(row, i)) is not None]

    # ---- the mic
    def set_level(self, level: float | None):
        """None: there's no mic open (the meter can't move; the label says so)."""
        no_mic = level is None
        self.meter.set_level(0.0 if no_mic else level)
        if no_mic != self._no_mic:
            self._no_mic = no_mic
            self.lbl_mic.setVisible(no_mic)
            icons.set_label_icon(self.mic_icon, "mic", "warn_text" if no_mic else "muted")
            self._fit()

    # ---- one row, or two when it's narrow
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def _fit(self):
        m = self._box.contentsMargins()
        room = self.width() - m.left() - m.right()
        line = sum(w.sizeHint().width() + 6 for w in self._row_widgets())   # one line
        # Keep at least half the bar beside Stop for the meter. If the status chips
        # would squeeze it below that, put them underneath instead. (Half the whole
        # bar, Stop included, sent two chips with their close buttons under the meter
        # on a window that had room for them.)
        mic_labels = (self._mic_row.sizeHint().width()
                      - self.meter.sizeHint().width())
        meter = (self.width() - self.stop_button.width() - self.record_button.width() + 1) // 2
        need = max(160, meter + mic_labels) + GAP + line
        d = QBoxLayout.Direction.LeftToRight if room >= need else QBoxLayout.Direction.TopToBottom
        # beside the meter the chips keep to one line; under it they wrap
        self._right.setMinimumWidth(line if d == QBoxLayout.Direction.LeftToRight else 0)
        # Flow's hint remembers its last width. Without a cap it takes the spare
        # room on the next layout pass and squeezes the mic meter to its minimum.
        self._right.setMaximumWidth(line if d == QBoxLayout.Direction.LeftToRight else 16777215)
        if self._box.direction() != d:
            self._box.setDirection(d)
            self._box.setSpacing(GAP if d == QBoxLayout.Direction.LeftToRight else 8)
