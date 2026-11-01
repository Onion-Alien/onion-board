"""A voice's bar for a voice without a cards panel of its own to carry one (the
computer voice): the same as the voice changer's and the AI voice's bars, pinned under
the Voice tab's cards while it's on. Its picture, its name and what kind of voice it
is, Effects (the voice changer's pop-up: one list for every bar) and Edit voice; the
Voice tab adds the pause and ✕ (VoicePanel._make_bar_controls).

It has what VoicePanel reads from a barred panel (`picked`, `picked_box`,
`picked_pic`, `picked_name`, `show_picked_row`, `set_paused`, `layout()`: the card it
goes back into when the window is short)."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QBoxLayout, QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from soundboard.i18n import _
from soundboard.ui.kit import icons
from soundboard.ui.kit.panel import Flow
from soundboard.ui.voice.voicefxpanel import PICKED_ART


class VoiceBar(QObject):
    effects_wanted = Signal()
    edit_wanted = Signal()

    def __init__(self, home: QWidget, is_on: Callable[[], bool]):
        super().__init__(home)
        self.home, self._is_on = home, is_on
        self._paused = False
        self.picked = QFrame()
        self.picked.setObjectName("picked")
        self.picked_box = QBoxLayout(QBoxLayout.Direction.LeftToRight, self.picked)
        self.picked_box.setContentsMargins(12, 8, 12, 8)
        self.picked_box.setSpacing(10)
        ph = QHBoxLayout()
        ph.setSpacing(10)
        self.picked_box.addLayout(ph)
        self.picked_pic = QLabel()
        self.picked_pic.setFixedSize(PICKED_ART, PICKED_ART)
        self.picked_pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph.addWidget(self.picked_pic)
        self.picked_name = QLabel()
        self.picked_name.setObjectName("pickedname")
        self.picked_name.setTextFormat(Qt.TextFormat.PlainText)
        self.picked_name.setMinimumWidth(40)   # a long name gives way in a narrow window
        ph.addWidget(self.picked_name)
        self.picked_kind = QLabel()
        self.picked_kind.setObjectName("pickedkind")
        ph.addWidget(self.picked_kind)
        # picture, name and kind kept together on the left, on a line of their own too
        self.picked_box.setAlignment(ph, Qt.AlignmentFlag.AlignLeft)
        self._picked_btns = QWidget()
        bflow = Flow(self._picked_btns, gap=10)
        self.picked_box.addWidget(self._picked_btns, 1)   # right after the name
        self.btn_effects = QPushButton(_("Effects"))
        icons.set_icon(self.btn_effects, "sounds")
        self.btn_effects.setToolTip(_("Rain, a crowd, an echo or sounds from your board, on "
                                      "top of any voice"))
        self.btn_effects.clicked.connect(lambda: self.effects_wanted.emit())
        bflow.addWidget(self.btn_effects)
        self.btn_tweak = QPushButton(_("Edit voice"))
        icons.set_icon(self.btn_tweak, "sliders")
        self.btn_tweak.clicked.connect(lambda: self.edit_wanted.emit())
        bflow.addWidget(self.btn_tweak)
        self.picked.installEventFilter(self)
        self.picked.hide()                     # (only while it's on: show_picked_row)

    def layout(self):
        """The card the bar goes to the end of when the window is short."""
        return self.home.layout()

    def show_voice(self, name: str, kind: str, pic: QPixmap):
        self.picked_name.setText(name)
        self.picked_kind.setText(kind)
        self.picked_pic.setPixmap(pic)
        self._fit_picked()

    def show_picked_row(self, room: bool | None = None):
        """Shown while the voice is on (or paused from its bar). `room`: whether the
        Voice tab has a place for it now."""
        if room is not None:
            self._picked_room = room
        self.picked.setVisible(getattr(self, "_picked_room", True)
                               and (self._is_on() or self._paused))

    def set_paused(self, paused: bool):
        """Paused from its bar (or by the Voices switch): the bar stays, dimmed."""
        self._paused = paused
        self.show_picked_row()

    def _bar_extra(self) -> int:
        """The width of the bar's pause and ✕ (the Voice tab adds them), and a gap."""
        ctl = getattr(self, "bar_controls", None)
        return ctl.sizeHint().width() + self.picked_box.spacing() if ctl is not None else 0

    def _fit_picked(self):
        """The buttons beside the voice's name while they fit there, else on a line of
        their own under it, as on the AI voice's bar."""
        box = self.picked_box
        btns = [b for b in self._picked_btns.findChildren(QPushButton) if not b.isHidden()]
        need = (sum(b.sizeHint().width() for b in btns) + 10 * max(0, len(btns) - 1))
        m = box.contentsMargins()
        line = self.picked.width() - m.left() - m.right() - self._bar_extra()
        beside = (line - PICKED_ART - min(self.picked_name.sizeHint().width(), 140)
                  - self.picked_kind.sizeHint().width() - 3 * box.spacing())
        want = (QBoxLayout.Direction.LeftToRight if need <= beside
                else QBoxLayout.Direction.TopToBottom)
        if box.direction() != want:
            box.setDirection(want)
        self._picked_btns.setMinimumWidth(
            need if want == QBoxLayout.Direction.LeftToRight else 0)

    def eventFilter(self, obj, e):
        if obj is self.picked and e.type() == QEvent.Type.Resize:
            self._fit_picked()
        return super().eventFilter(obj, e)
