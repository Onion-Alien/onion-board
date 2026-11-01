"""The player in Edit sound: the main window's player bar again (▶ ■ ⏭, the name and its
seek line, the time, Sounds for others, Hear it myself), plus the Now playing chips and
Stop all. A big Edit sound window covers the board's own bar, and a song had to be
paused or found by moving the window. The main window drives every copy (``players``):
nothing here plays or keeps state of its own."""
from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from soundboard.core import usage
from soundboard.i18n import _
from soundboard.ui.kit import icons
from soundboard.ui.kit.panel import CONTROL_H, Flow, VolumeControl, vsep
from soundboard.ui.kit.playbutton import PlayButton
from soundboard.ui.kit.wheelguard import no_wheel
from soundboard.ui.kit.widgets import NameAndSeek, SeekSlider

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

log = logging.getLogger(__name__)

CHIPS_GAP = 6   # as the main window's Now playing row
NAME_MIN = 60   # the name, at the least: cut short before the window is made wider


def _count(*_a):
    """This player was used, not the board's own bar (usage.py: the name only)."""
    usage.used("edit-player")


class _NameAndSeek(NameAndSeek):
    """The board's name + seek line, but a long name doesn't make the window wider:
    Edit sound's Simple view stays as narrow as it was (relayout cuts the name)."""

    full = ""   # the whole name: cut with … to the room it gets

    def minimumSizeHint(self):
        return QSize(self.SEEK_MIN + self.GAP + NAME_MIN, super().minimumSizeHint().height())

    def relayout(self):
        fm = self.name.fontMetrics()
        room = min(self.max_name, fm.horizontalAdvance(self.full) + 4,
                   max(0, self.width() - self.SEEK_MIN - self.GAP))
        self.name.setText(fm.elidedText(self.full, Qt.TextElideMode.ElideRight, room - 4))
        super().relayout()


class _ChipsRow(QWidget):
    """The chips wrap onto more lines rather than ask for one long one: Edit sound grows
    to fit what its parts ask for (ui/kit/fit.py), and a sound starting made it wider."""

    def sizeHint(self):
        return QSize(self.minimumSizeHint().width(), super().sizeHint().height())


class EditPlayer(QFrame):
    """One Edit sound window's player. Made by the main window (editcontrol), which
    sets it from its own player on every change (set_name, set_time, set_icon, ...)."""

    def __init__(self, mw: MainWindow, parent=None):
        super().__init__(parent)
        self.setObjectName("transport")
        playctl = mw.playctl
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 5, 12, 6)
        v.setSpacing(6)

        # Now playing / Paused chips, the same as over the board's player
        self.chips_row = _ChipsRow()
        self.chips_row.setObjectName("editplayerpart")   # see-through (themesheet)
        self._chips_hl = Flow(self.chips_row, gap=CHIPS_GAP)
        self._chips: dict[str, QFrame] = {}
        self.chips_row.hide()
        v.addWidget(self.chips_row)

        # the player on the left, its volume and Stop all on the right: one row when
        # the window is wide enough (Advanced), two in a narrow one (_fit_rows)
        self._rows = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._rows.setSpacing(10)
        v.addLayout(self._rows)
        left = self._left = QWidget()
        left.setObjectName("editplayerpart")
        lh = QHBoxLayout(left)
        lh.setContentsMargins(0, 0, 0, 0)
        lh.setSpacing(10)
        self.btn_pp = PlayButton()
        self.btn_pp.setObjectName("transport_play")
        self.btn_pp.setAccessibleName(_("Play / pause"))
        self.btn_pp.clicked.connect(playctl.toggle_play_pause)
        self.btn_st = QPushButton()
        self.btn_st.setObjectName("transport_stop")
        self.btn_st.setAccessibleName(_("Stop"))
        self.btn_st.clicked.connect(playctl.stop_current)
        icons.set_icon(self.btn_st, "stop", size=16)
        self.btn_skip = QPushButton()
        self.btn_skip.setObjectName("transport_stop")   # the same quiet square as ■
        self.btn_skip.setAccessibleName(_("Skip to the next sound in Up next"))
        self.btn_skip.clicked.connect(playctl.skip_next)
        icons.set_icon(self.btn_skip, "next", size=16)
        for b in (self.btn_pp, self.btn_st, self.btn_skip):
            b.clicked.connect(_count)
            b.setFixedSize(CONTROL_H, CONTROL_H)
            lh.addWidget(b)
        self.name = QLabel()
        self.name.setTextFormat(Qt.TextFormat.PlainText)   # sound names are user / web text
        self.name.setFixedHeight(CONTROL_H)
        self.name.setStyleSheet("font-weight:600;")
        self.seek = SeekSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 1000)
        self.seek.setObjectName("seek")
        self.seek.sliderPressed.connect(lambda: setattr(playctl, "_seeking", True))
        self.seek.sliderReleased.connect(lambda: playctl.do_seek(self.seek))
        self.seek.sliderReleased.connect(_count)
        self.seek.valueChanged.connect(playctl._seek_preview)
        no_wheel(self.seek)
        self._name_seek = _NameAndSeek(self.name, self.seek, 190)
        lh.addWidget(self._name_seek, 1)
        self.time = QLabel()
        self.time.setFixedWidth(self.time.fontMetrics().horizontalAdvance("888:88 / 888:88") + 4)
        self.time.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.time.setObjectName("muted")
        self.time.hide()   # until there is a time to show (set_time)
        lh.addWidget(self.time)
        self._rows.addWidget(left, 1)

        right = self._right = QWidget()
        right.setObjectName("editplayerpart")
        rh = QHBoxLayout(right)
        rh.setContentsMargins(0, 0, 0, 0)
        rh.setSpacing(10)
        self._sep = vsep()
        rh.addWidget(self._sep)
        vol_tip = mw.vol_sound.slider.toolTip()
        vol_lbl = QLabel(_("Sounds for others"))
        vol_lbl.setObjectName("decktitle")
        vol_lbl.setToolTip(vol_tip)
        rh.addWidget(vol_lbl)
        self.vol = VolumeControl(mw.vol_sound.value(), tip=vol_tip)
        # through the board's own control: it saves it and says what it changed
        self.vol.changed.connect(lambda f: mw.vol_sound.spin.setValue(round(f * 100)))
        rh.addWidget(self.vol)
        self.chk_monitor = QCheckBox(_("Hear it myself"))
        self.chk_monitor.setChecked(mw.chk_monitor.isChecked())
        self.chk_monitor.toggled.connect(mw.chk_monitor.setChecked)
        rh.addWidget(self.chk_monitor)
        rh.addStretch(1)
        self.btn_stop_all = QPushButton(_("Stop all"))
        self.btn_stop_all.setObjectName("danger")
        self.btn_stop_all.setProperty("quiet", True)
        self.btn_stop_all.setToolTip(mw.stop_btn.toolTip())
        self.btn_stop_all.clicked.connect(playctl._stop_all_clicked)
        self.btn_stop_all.clicked.connect(_count)
        icons.set_icon(self.btn_stop_all, "stop", "danger_text", size=14)
        rh.addWidget(self.btn_stop_all)
        self._rows.addWidget(right)

    # ---- set by the main window's player, as it sets its own
    def set_name(self, text: str, tip: str):
        self._name_seek.full = text
        self.name.setToolTip(tip)
        self._name_seek.relayout()

    def set_time(self, text: str):
        """Blank (nothing picked) it hides: the seek line runs to the edge, no gap."""
        self.time.setText(text)
        self.time.setVisible(bool(text))

    def set_icon(self, name: str):
        icons.set_icon(self.btn_pp, name, "on_accent", size=16)

    def set_enabled(self, on: bool):
        for w in (self.btn_pp, self.btn_st, self.seek):
            w.setEnabled(on)

    def set_seek(self, value: int):
        self.seek.blockSignals(True)
        self.seek.setValue(value)
        self.seek.blockSignals(False)

    def set_volume(self, factor: float):
        pct = round(factor * 100)
        for w in (self.vol.slider, self.vol.spin):
            w.blockSignals(True)
        self.vol.slider.setValue(min(pct, self.vol.slider_max))
        self.vol.spin.setValue(pct)
        self.vol._paint(pct)
        for w in (self.vol.slider, self.vol.spin):
            w.blockSignals(False)

    def set_monitor(self, on: bool):
        self.chk_monitor.blockSignals(True)
        self.chk_monitor.setChecked(on)
        self.chk_monitor.blockSignals(False)

    def set_chips(self, groups: Sequence[tuple[str, list[str]]],
                  make_chip: Callable[[str], QFrame]):
        """`groups`: (Now playing / Paused, their sounds); make_chip(sid) one chip."""
        while self._chips_hl.count():
            item = self._chips_hl.takeAt(0)
            w = item.widget() if item else None
            if w:
                w.deleteLater()
        self._chips = {}
        for title, group in groups:
            if not group:
                continue
            lbl = QLabel(title)
            lbl.setObjectName("muted")
            self._chips_hl.addWidget(lbl)
            for sid in group:
                chip = make_chip(sid)
                self._chips_hl.addWidget(chip)
                self._chips[sid] = chip
        self.chips_row.setVisible(bool(self._chips))

    def mark_chip(self, current: str | None):
        for sid, chip in self._chips.items():
            sel = "true" if sid == current else "false"
            if chip.property("sel") != sel:
                chip.setProperty("sel", sel)
                chip.style().unpolish(chip)
                chip.style().polish(chip)

    def _fit_rows(self, width: int):
        need = (self._left.minimumSizeHint().width() + 120   # the seek line, aimable
                + self._right.sizeHint().width() + self._rows.spacing() + 22)
        one = width >= need
        want = QBoxLayout.Direction.LeftToRight if one else QBoxLayout.Direction.TopToBottom
        if self._rows.direction() != want:
            self._rows.setDirection(want)
            self._sep.setVisible(one)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        try:   # (nothing in an override may raise: overridepin.py)
            self._fit_rows(e.size().width())
        except Exception:  # noqa: BLE001
            log.debug("Edit sound player re-layout failed", exc_info=True)
