"""The Voice tab's status bar: one strip at the top that always shows your mic level
and everything that's changing what others hear from it (the voice changer, the AI
voice, the computer voice, the language you speak in), whichever cards are folded.

Each thing that's on is a lit chip, and each thing the Voices switch would bring back
is a grey one. Clicking a chip turns that one off, or back on; right-clicking opens its
card; its ✕ turns it off for good (Voices ON won't bring it back). The big Voices
ON / OFF switch pauses all of them at once and brings back exactly what was on."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QBoxLayout, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QToolButton, QWidget)

from soundboard.i18n import _
from soundboard.ui.kit import icons
from soundboard.ui.kit.panel import Flow, icon_label
from soundboard.ui.voice.voicefxpanel import BigSwitch
from soundboard.ui.kit.widgets import Meter, widget_at

GAP = 16            # between the mic half and the chips, side by side
ROW_H = 28          # every chip, label and the mic row: the bar never changes height
STOP_H = 36         # the Voices switch and Record, bigger than the chips beside them
METER_MIN = 80      # the mic meter's narrowest, unless the bar is too tight for it
X_SIDE = 18         # a chip's ✕, inside its right end


class Chip(QPushButton):
    """One voice thing: a rounded label with a picture, the accent colour while it's
    on, the warning colour when it went wrong, grey while it's off (Voices ON or a
    click brings it back). A right-click asks for its card (`menu_asked`)."""
    menu_asked = Signal()

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

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            self.menu_asked.emit()
            e.accept()
            return
        super().mousePressEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.off.move(self.width() - X_SIDE - 3, (self.height() - X_SIDE) // 2)

    def show_as(self, text: str, state: str, icon: str = "", picture=None, tip: str = "",
                closable: bool = True):
        """`state`: "on", "warn" or "off". `picture`: a ready QIcon (a voice's art),
        else the line icon `icon` in the state's colour. `closable`: shows its ✕."""
        look = (text, state, icon, id(picture), tip, closable)
        if look == self._look:
            return               # the panel refreshes often: only restyle on a change
        self._look = look
        self.setText(text)
        self.setToolTip(tip)
        self.off.setVisible(closable)
        self.off.setToolTip(_("Turn off {thing}", thing=text) if state != "off" else
                            _("Forget {thing}: Voices ON won't bring it back", thing=text))
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
    """`set_items([(key, text, state, icon, picture, tip[, closable]), ...])` shows the
    chips; `toggle(key)` is emitted when one is clicked, `turn_off(key)` when its ✕ is,
    `open_card(key)` when it's right-clicked. `master` is the Voices ON / OFF switch:
    `master_toggled(on)` when it's flipped, `set_master(on)` to show the state.
    `set_level` feeds the meter."""
    open_card = Signal(str)
    turn_off = Signal(str)
    toggle = Signal(str)
    master_toggled = Signal(bool)
    reset_asked = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("voicebar")
        # never what holds the window wide (below ~520 px it became the mini player):
        # narrow, it goes to two rows (the chips above) and they wrap (_fit)
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
        # one big Voices ON / OFF, the cards' own switch: OFF pauses every voice at once
        # and ON brings exactly those back (a red Stop forgot what was on)
        self.master_label = QLabel(_("Voices"))
        self.master_label.setObjectName("voicemaster")
        self.master_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        mh.addWidget(self.master_label)
        self.master = BigSwitch()
        self.master.setAccessibleName(_("Voices on or off"))
        self.master.setCursor(Qt.CursorShape.PointingHandCursor)
        self.master.clicked.connect(lambda: self.master_toggled.emit(self.master.isChecked()))
        self.master_label.setBuddy(self.master)
        mh.addWidget(self.master)
        # quick record: opens Record a sound already recording your voice (as others
        # hear it while the voice changer is on); Save keeps it in the tab's Recordings
        self.record_button = QPushButton(_("Record"))
        self.record_button.setToolTip(_("Record your voice as others hear it. It goes in "
                                        "Recordings, above"))
        self.record_button.setAccessibleName(_("Record"))
        self.record_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.record_button.setFixedHeight(STOP_H)
        icons.set_icon(self.record_button, "record", "danger_text", size=16)
        mh.addWidget(self.record_button)
        # a fresh start: every voice off and forgotten, so Voices ON brings none of them back
        self.reset_button = QPushButton(_("Reset"))
        self.reset_button.setToolTip(_("Turn every voice off and forget them, for a fresh "
                                       "start. Voices ON won't bring them back"))
        self.reset_button.setAccessibleName(_("Reset"))
        self.reset_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_button.setFixedHeight(STOP_H)
        icons.set_icon(self.reset_button, "reload", "muted", size=16)
        self.reset_button.clicked.connect(self.reset_asked)
        mh.addWidget(self.reset_button)
        self.mic_icon = icon_label("mic", _("Your mic level"))
        mh.addWidget(self.mic_icon)
        self.lbl_mic = QLabel(_("No mic open"))   # only then: the icon says the rest
        self.lbl_mic.setObjectName("voicebarlabel")
        self.lbl_mic.hide()
        # never squeezed (its words would be cut): the meter beside it gives way
        self.lbl_mic.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        mh.addWidget(self.lbl_mic)
        self.meter = Meter()
        self.meter.setMinimumWidth(METER_MIN)
        mh.addWidget(self.meter, 1)
        box.addWidget(mic, 1)

        right = self._right = QWidget()
        right.setObjectName("voicebarpart")
        # wraps onto more lines rather than holding the window wide (the mini player)
        rh = self._chips_row = Flow(right)
        self.lbl_heard = icon_label("ear", _("What others hear from your mic"))
        self.lbl_heard.setFixedHeight(ROW_H)
        rh.addWidget(self.lbl_heard)
        # centred on the mic row: the switch is taller than the chips, which sat high
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
        for key, text, state, icon, picture, tip, *more in items:
            closable = more[0] if more else True
            chip = self.chips.get(key)
            if chip is None:
                if key == "none":
                    chip = QLabel()
                    chip.setObjectName("voicebarlabel")
                    chip.setFixedHeight(ROW_H)
                    chip.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                else:
                    chip = Chip(key)
                    chip.clicked.connect(lambda _=False, k=key: self.toggle.emit(k))
                    chip.menu_asked.connect(lambda k=key: self.open_card.emit(k))
                    chip.off.clicked.connect(lambda _=False, k=key: self.turn_off.emit(k))
                self.chips[key] = chip
            if isinstance(chip, Chip):
                chip.show_as(text, state, icon, picture, tip, closable)
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
        # the ear says "what others hear:" before the chips; with none, it said nothing
        self.lbl_heard.setVisible(bool(items))
        self._right.setVisible(bool(items))
        row.invalidate()
        self._fit()

    def texts(self) -> list[str]:
        """The chips' words, in order (tests, the tab's accessible summary)."""
        return [w.text() for w in self._row_widgets() if w in self.chips.values()]

    def _row_widgets(self) -> list:
        row = self._chips_row
        return [w for i in range(row.count()) if (w := widget_at(row, i)) is not None]

    def set_master(self, on: bool, tip: str = ""):
        """The Voices switch shows `on` (something's changing your mic); `tip` says what
        flipping it does."""
        if self.master.isChecked() != on:
            self.master.blockSignals(True)
            self.master.setChecked(on)
            self.master.blockSignals(False)
            self.master.update()
        self.master.setToolTip(tip)
        self.master_label.setToolTip(tip)

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

    def _mic_min(self) -> int:
        """The mic row's narrowest: the Voices switch, Record, Reset, the icon and label
        whole, the meter at its minimum."""
        parts = [w for i in range(self._mic_row.count())
                 if (w := widget_at(self._mic_row, i)) is not None and not w.isHidden()]
        return (sum(max(w.sizeHint().width(), w.minimumWidth()) for w in parts
                    if w is not self.meter)
                + self.meter.minimumWidth() + self._mic_row.spacing() * (len(parts) - 1))

    def _fit(self):
        m = self._box.contentsMargins()
        room = self.width() - m.left() - m.right()
        # "No mic open" whole, its padding included (a label's size hint can miss the
        # theme's padding right after a theme change, and the words got cut)
        lbl = self.lbl_mic
        pad = lbl.contentsMargins()
        lbl.setMinimumWidth(lbl.fontMetrics().horizontalAdvance(lbl.text()) + pad.left()
                            + pad.right() + 2 * lbl.margin() + 1)
        # Record and Reset go down to their icons when the switch, they and the mic row
        # can't all fit (a long "No mic open" in some languages was cut off)
        words = ((self.record_button, _("Record")), (self.reset_button, _("Reset")))
        shown = [b.text() for b, _w in words]
        for b, word in words:
            b.setText(word)                # measured with their words...
        fits = self._mic_min() <= room
        for (b, word), was in zip(words, shown):
            b.setText(was)
            if (word if fits else "") != was:   # ...changed only when it must (no loop)
                b.setText(word if fits else "")
        # still too tight (a wide theme font, a long language): the meter gives way
        # before the "No mic open" words get cut
        self.meter.setMinimumWidth(METER_MIN)
        over = self._mic_min() - room
        if over > 0:
            self.meter.setMinimumWidth(max(METER_MIN // 3, METER_MIN - over))
        line = sum(w.sizeHint().width() + 6 for w in self._row_widgets())   # one line
        # Keep at least half the bar beside the switch for the meter. If the status chips
        # would squeeze it below that, put them underneath instead. (Half the whole
        # bar, the switch included, sent two chips with their close buttons under the meter
        # on a window that had room for them.)
        mic_labels = (self._mic_row.sizeHint().width()
                      - self.meter.sizeHint().width())
        meter = (self.width() - self.master.width() - self.master_label.width()
                 - self.record_button.width() - self.reset_button.width() + 1) // 2
        need = max(160, meter + mic_labels) + GAP + line
        need = max(need, self._mic_min() + GAP + line)   # never squeeze the mic row
        # Stacked, the chips go above the switch row: the bar sits at the bottom of the
        # tab, so the switch stays put when a click takes the chips' second row away.
        d = QBoxLayout.Direction.LeftToRight if room >= need else QBoxLayout.Direction.BottomToTop
        # beside the meter the chips keep to one line; above it they wrap
        self._right.setMinimumWidth(line if d == QBoxLayout.Direction.LeftToRight else 0)
        # Flow's hint remembers its last width. Without a cap it takes the spare
        # room on the next layout pass and squeezes the mic meter to its minimum.
        self._right.setMaximumWidth(line if d == QBoxLayout.Direction.LeftToRight else 16777215)
        if self._box.direction() != d:
            self._box.setDirection(d)
            self._box.setSpacing(GAP if d == QBoxLayout.Direction.LeftToRight else 8)
