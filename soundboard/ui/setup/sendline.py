"""Setup -> Devices -> Send my sounds into: one line that says where your sounds go, as
the Send your sounds switch left it, with a tick to turn them off. Only a choice the
switch can't make gets a control: two cables to pick between, the way back to the mic
from another device. Built into a device grid (the Setup tab's, and Settings -> Audio's
copy of it); RouteControl._show_route keeps them up to date."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QWidget)

from soundboard.audio import engine as eng
from soundboard.i18n import _
from soundboard.ui.kit.wheelguard import AppStyle, no_wheel

LABEL = _("Send my sounds into")


class _Words(QLabel):
    """The tick's words: wrapped (a long device name scrolled the page sideways as a
    QCheckBox's own text), and clicking them clicks the tick."""
    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and self.rect().contains(event.position().toPoint())):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class SendLine(QWidget):
    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)   # (the tick's words sit right by it)
        self.tick = QCheckBox()
        self.tick.setAccessibleName(LABEL)
        self.tick.setToolTip(_("Untick to keep your sounds to yourself: Discord and games won't "
                               "hear them. The Send your sounds card picks where they go."))
        self.tick.clicked.connect(mw.routectl.set_sending)
        h.addWidget(self.tick)
        self.words = _Words()
        self.words.setWordWrap(True)
        self.words.clicked.connect(self.tick.click)
        h.addWidget(self.words, 100)   # all the room their words need, then the stretch
        self.pick = QComboBox()   # two cables (or a cable and a mixer): which one
        self.pick.setAccessibleName(LABEL)
        self.pick.setMinimumWidth(120)
        self.pick.setProperty("snug", False)   # (wheelguard.snug_combo: sized here)
        self.pick.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.pick.setMaximumWidth(AppStyle.COMBO_CAP)
        no_wheel(self.pick)
        self.pick.activated.connect(self._picked)
        h.addWidget(self.pick, 100)
        h.addSpacing(8)
        self.back = QPushButton(_("Use my mic"))   # (the switch isn't there on another device)
        self.back.clicked.connect(mw.routectl.use_mic)
        h.addWidget(self.back)
        h.addStretch(1)
        self.sync()

    def sync(self):
        """Show what the route box (mw.cb_route, which holds the route's choices) says."""
        mw = self.mw
        box = mw.cb_route
        key = box.currentData()
        route = mw.cfg.route
        on = key != "off"
        self.tick.setChecked(on)
        items = [(box.itemText(i), box.itemData(i)) for i in range(box.count())
                 if (box.itemData(i) or "").startswith("device:")]
        several = on and key != "mic" and len(items) > 1
        if not on:
            self.words.setText(_("Off: only you hear them"))
        elif key == "mic":
            self.words.setText(mw.cfg.mic_device or _("My mic"))
        else:
            self.words.setText(box.currentText())
        words = self.words
        words.setMaximumWidth(words.fontMetrics().horizontalAdvance(words.text()) + 8)
        self.words.setVisible(not several)
        pick = self.pick
        if items != [(pick.itemText(i), pick.itemData(i)) for i in range(pick.count())]:
            pick.clear()
            for text, data in items:
                pick.addItem(text, data)
            pick.view().setMinimumWidth(pick.view().sizeHintForColumn(0) + 32)   # whole names
        pick.setCurrentIndex(max(0, pick.findData(key)))
        pick.setVisible(several)
        self.back.setVisible(on and key != "mic" and (
            route == "device" or not eng.virtual_outputs()))

    def _picked(self, _i: int):
        box = self.mw.cb_route
        box.setCurrentIndex(max(0, box.findData(self.pick.currentData())))
        self.mw.routectl.on_device(box, "route")


def build(mw, grid: QGridLayout, row: int, first: int) -> SendLine:
    """The line in `grid`'s `row`: its label in column `first`, the rest to the grid's edge."""
    line = SendLine(mw)
    label = QLabel(LABEL)
    label.setBuddy(line.tick)
    label.setProperty("keepline", True)   # (wrapped in Settings with room to spare)
    grid.addWidget(label, row, first)
    grid.addWidget(line, row, first + 1, 1, -1)
    mw.send_lines.append(line)
    line.destroyed.connect(lambda *__: mw.send_lines.remove(line)
                           if line in mw.send_lines else None)
    return line
