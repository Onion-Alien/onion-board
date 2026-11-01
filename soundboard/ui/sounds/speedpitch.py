"""Live speed / pitch / effects: a small button on a transport bar ("1x") that opens
a pop-up with the sliders (a click outside closes it). It changes what's playing
right now and isn't saved; to keep a version of a sound, use its Edit → Effects tab instead.

Two columns: speed & pitch (and the volume) on the left, the live effects
(soundboard.audio.livefx: bass, treble, muffle, reverb, echo, distortion, and presets
that set several) on the right.

The sane range (0.25–2x, ±12 st) is always there. The greyed-out **Redline**
section under it unlocks the silly range (up to 10x, ±36 st) and shows a rev
meter whose red zone starts at 8x. A live stream (Radio, Apps) has no speed: its
meter shows the pitch instead, red past ±24 st."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QGridLayout, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox,
                               QProgressBar, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

from soundboard.audio import livefx, mypresets
from soundboard.core import achievements, usage
from soundboard.ui.kit import theme
from soundboard import voicefx
from soundboard.ui.bun import bunskits
from soundboard.ui.kit import fit, icons
from soundboard.ui.bun.bunnywidget import BunnyWidget
from soundboard.ui.kit.panel import Flow, hint_label, reset_button, section_label
from soundboard.ui.kit.plaintext import plain_tip
from soundboard.i18n import _, ngettext
from soundboard.ui.kit.pixels import snap_to_pixels
from soundboard.ui.sounds.soundpanel import (QUICK, SoundPanel, ValueBox,  # noqa: F401
                                             quick_row)   # (QUICK, ValueBox: still here too)

SPEED = voicefx.Param("speed", _("Speed"), 0.25, 2.0, 1.0, "x", 0.05)
PITCH = voicefx.Param("pitch", _("Pitch"), -12, 12, 0, " st", 1)
VOLUME = voicefx.Param("volume", _("Volume"), livefx.VOLUME.lo, livefx.VOLUME.hi,
                       livefx.VOLUME.default, livefx.VOLUME.unit, livefx.VOLUME.step)
VOLUME_QUICK = (50, 100, 150, 200, 300, 400)
REDLINE_AT = 8.0                        # the meter's red zone starts here
REDLINE_SPEED = (0.1, 10.0)             # sounds
REDLINE_PITCH = voicefx.Param("pitch", _("Pitch"), -36, 36, 0, " st", 1)
REDLINE_QUICK = (3.0, 4.0, 6.0, 8.0, 10.0)
PITCH_RED_AT = 24.0                     # a stream's pitch meter: red past ±24 st
PITCH_QUICK = (-24.0, -12.0, 12.0, 24.0, 36.0)
RED = "#ff4d4f"
COL_W = 340                             # each column


def redline_speed(lo: float, hi: float) -> voicefx.Param:
    return voicefx.Param("speed", _("Speed"), lo, hi, 1.0, "x", 0.05)


class RevMeter(QWidget):
    """A tachometer for the speed: 0..top, the arc turns orange then red past
    REDLINE_AT, and the needle shows where you are. `pitch=True`: the same dial
    for a stream's pitch, -top..top st, orange past ±12 and red past ±24."""
    SWEEP = 240.0                       # degrees, from lower-left round to lower-right

    def __init__(self, top: float, pitch: bool = False):
        super().__init__()
        self.pitch = pitch
        self.top = top
        self.lo = -top if pitch else 0.0
        self.speed = 0.0 if pitch else 1.0     # the value shown (st on a pitch meter)
        self.setFixedHeight(132)
        self.setMinimumWidth(200)

    def set_value(self, speed: float):
        if abs(speed - self.speed) > 1e-6:
            self.speed = speed
            self.update()

    def _angle(self, v: float) -> float:
        """Qt angle (degrees, counter-clockwise from 3 o'clock) of value v."""
        f = min(max((v - self.lo) / (self.top - self.lo), 0.0), 1.0)
        return 90 + self.SWEEP / 2 - self.SWEEP * f

    def _hot(self, v: float) -> bool:
        if self.pitch:
            return abs(v) >= PITCH_RED_AT - 1e-6
        return v >= REDLINE_AT - 1e-6

    def _zones(self, t) -> list[tuple[float, float, str]]:
        """(from, to, colour) of the dial's coloured bands."""
        if self.pitch:
            warn, red = PITCH.hi, min(self.top, PITCH_RED_AT)
            return [(self.lo, -red, RED), (-red, -warn, t["warn_text"]),
                    (-warn, warn, t["accent"]), (warn, red, t["warn_text"]),
                    (red, self.top, RED)]
        warn_at = min(self.top, max(0.0, REDLINE_AT - 2))
        red_at = min(self.top, REDLINE_AT)
        return [(0, warn_at, t["accent"]), (warn_at, red_at, t["warn_text"]),
                (red_at, self.top, RED)]

    def _ticks(self) -> list[tuple[float, str]]:
        """(value, label) per tick: every 1x, or every 12 st on a pitch meter."""
        if self.pitch:
            return [(float(v), f"{v:+d}" if v else "0")
                    for v in range(int(self.lo), int(self.top) + 1, 12)]
        return [(float(i), str(i)) for i in range(int(self.top) + 1)]

    def _text(self) -> str:
        if self.pitch:
            return f"{self.speed:+g} st" if self.speed else "0 st"
        return f"{self.speed:g}x"

    def paintEvent(self, _e):
        t = theme.T
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = min(self.width() / 2 - 12, self.height() * 0.62)
        c = QPointF(self.width() / 2, r + 10)
        box = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)

        def arc(v0, v1, color, width):
            a0, a1 = self._angle(v0), self._angle(v1)
            p.setPen(QPen(QColor(color), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
            p.drawArc(box, int(a0 * 16), int((a1 - a0) * 16))

        def point(v, rad):
            a = math.radians(self._angle(v))
            return QPointF(c.x() + rad * math.cos(a), c.y() - rad * math.sin(a))

        arc(self.lo, self.top, t["faint"], 3)            # the whole dial, dim
        for v0, v1, colour in self._zones(t):
            if v0 < v1:
                arc(v0, v1, colour, 7)

        f = QFont(self.font())
        f.setPointSizeF(7)
        p.setFont(f)
        for v, label in self._ticks():                  # a tick + number each step
            p.setPen(QPen(QColor(RED if self._hot(v) else t["muted"]), 1.5))
            p.drawLine(point(v, r - 6), point(v, r - 13))
            q = point(v, r - (26 if self.pitch else 22))   # "+12" is wider than "1"
            p.drawText(QRectF(q.x() - 12, q.y() - 7, 24, 14), Qt.AlignmentFlag.AlignCenter,
                       label)

        hot = self._hot(self.speed)
        needle = QColor(RED if hot else t["text_hi"])
        p.setPen(QPen(needle, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(c, point(self.speed, r - 4))
        p.setBrush(needle)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(c, 4.5, 4.5)

        f.setPointSizeF(11)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(RED if hot else t["text"]))
        p.drawText(QRectF(c.x() - 60, c.y() + 6, 120, 20), Qt.AlignmentFlag.AlignCenter,
                   self._text())
        if hot:
            f.setPointSizeF(7)
            p.setFont(f)
            p.drawText(QRectF(c.x() - 60, c.y() + 25, 120, 14), Qt.AlignmentFlag.AlignCenter,
                       _("Redline"))
        p.end()


class DjBunny(BunnyWidget):
    """Bun left of the Live controls title, mixing sound pads and scratching a record round
    and round (bunskits.mixing) while the pop-up is open. His own fidgets and his
    theme's skit stay off: he's busy. Hidden, his timer stops (BunnyWidget)."""

    def __init__(self, parent=None):
        super().__init__(height=DJ_H, pad=4, parent=parent)

    def _step_fidget(self, now: float):
        if self._skit is None:
            self._skit, self._skit_at = (bunskits.MIX_LOOP, bunskits.mixing), now


DJ_H = 72   # Bun's height, left of the Live controls title


def short(name: str, most: int = 14) -> str:
    """A setup's name on the transport bar's button: long ones cut with "…"."""
    return name if len(name) <= most else name[:most - 1].rstrip() + "…"


class _MoreMenu(QMenu):
    """My presets' More list: a right-click on one opens its Rename / Delete menu.
    A long list scrolls (a hundred presets, on a small screen)."""

    def __init__(self, parent, menu_for):
        super().__init__(parent)
        self._menu_for = menu_for
        self.setStyleSheet("QMenu { menu-scrollable: 1; }")

    def contextMenuEvent(self, e):
        try:   # nothing in a Qt override may raise (PySide keeps it for later)
            a = self.actionAt(e.pos())
            if a is not None and a.data():
                self.close()
                self._menu_for(str(a.data()), e.globalPos())
        except Exception:  # noqa: BLE001
            pass


class SpeedPitchButton(QPushButton):
    """`changed(speed, semitones, keep_pitch)` fires on every speed / pitch edit,
    `fx_changed(amounts)` on every effects edit (livefx.clean: only knobs off 0)."""
    changed = Signal(float, float, bool)
    fx_changed = Signal(dict)
    setup_picked = Signal(str)   # a voice setup's name, "" = none (ui.livesetups)
    setup_cancelled = Signal()   # Cancel while its AI voice gets ready
    opening = Signal()           # about to pop up: the setups list is brought up to date
    save_new = Signal()          # Save as new pad: the playing sound, these on it (sounds)
    closed = Signal()            # the pop-up went away

    def __init__(self, what: str = "sounds", hint: str = "",
                 redline: tuple[float, float] = REDLINE_SPEED):
        """`what`: "sounds", or a live stream, "radio" / "apps" (the Radio and Apps
        tabs): those have no speed, only the pitch and the effects.
        `redline`: the (slowest, fastest) speed once Redline is unlocked."""
        super().__init__()
        self.has_speed = what == "sounds"
        self._what = what if what in usage.LIVE_TABS else "sounds"   # (usage.py's word)
        self._seen = (1.0, 0.0, True)   # speed, pitch, keep: what a change is told by
        self._seen_fx: dict[str, float] = {}
        self.setObjectName("small")
        self.setProperty("speedpitch", True)
        self.setToolTip({"radio": _("Pitch and effects of the radio"),
                         "apps": _("Pitch and effects of the programs you send")}.get(
            what, _("Speed, pitch and effects of the sounds playing now")))
        # its text is the speed ("1x"): a screen reader said only that
        self.setAccessibleName(_("Live controls"))
        self.setAccessibleDescription(self.toolTip())
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if not self.has_speed:   # "Effects" on its own reads as a label: show it's a control
            icons.set_icon(self, "wave", size=14)
        self._speed_hi = redline_speed(*redline)
        top = redline[1]

        # A pop-up over the board, beside its button: a click outside, Escape or the
        # button again closes it (the settings stay, it's only hidden)
        self.pop = QDialog(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        fit.watch(self.pop)
        self.pop.setWindowTitle(_("Live controls"))
        self.pop.setProperty("popover", True)   # its edge (theme.py)
        self.pop.installEventFilter(self)
        self._hidden_at = 0.0
        self.pop.setObjectName("transport")
        v = QVBoxLayout(self.pop)
        v.setContentsMargins(16, 12, 16, 14)
        v.setSpacing(8)

        # header: Bun mixing, the title, Reset where it's easy to find
        head = self._head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel(_("Live controls"))
        title.setStyleSheet("font-weight:700; font-size:10.5pt;")
        sub = QLabel({"radio": _("The radio"), "apps": _("All programs")}.get(
            what, _("All sounds")))
        sub.setObjectName("muted")
        sub.setMinimumWidth(1)   # the first to give way when a language's buttons are long
        self._sub = sub
        self._sub_all = sub.text()
        sub.setTextFormat(Qt.TextFormat.PlainText)   # (a pad's name: set_target)
        reset = reset_button(_("Back to 1x, no pitch change, no effects and 100 % volume")
                             if self.has_speed else
                             _("Back to no pitch change, no effects and 100 % volume"))
        reset.setObjectName("liveReset")
        icons.set_icon(reset, "reload", size=18)
        # whole buttons, never squeezed: the title's words give way first
        reset.setMinimumSize(max(96, reset.sizeHint().width()), 36)
        reset.clicked.connect(self.reset)
        self.dj = DjBunny()   # Bun mixing, left of the title
        head.addWidget(self.dj)
        head.addWidget(title)
        head.addWidget(sub)
        head.addStretch(1)
        # what's on now, kept as a preset of your own (the My presets row under this)
        self.save_preset_btn = QPushButton(_("Save preset"))
        self.save_preset_btn.setAccessibleName(_("Save preset"))   # (its words can go)
        self.save_preset_btn.setMinimumHeight(36)
        self.save_preset_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.save_preset_btn.setToolTip(_("Keep the speed, pitch, effects and volume you "
                                          "have now as a preset of your own"))
        self.save_preset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        icons.set_icon(self.save_preset_btn, "plus", size=18)
        self.save_preset_btn.clicked.connect(self._save_or_update)
        # your preset picked and then changed: Save preset says Update "name", and the
        # ▾ right beside it holds Update, Reset (back to how it was saved) and Save as new
        self.preset_menu_btn = QPushButton()
        self.preset_menu_btn.setObjectName("primary")
        self.preset_menu_btn.setFixedSize(30, 36)
        icons.set_icon(self.preset_menu_btn, "fold_open", "on_accent", size=16)
        self.preset_menu_btn.setToolTip(_("Update, reset or save as a new preset"))
        self.preset_menu_btn.setAccessibleName(self.preset_menu_btn.toolTip())
        self.preset_menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.preset_menu_btn.clicked.connect(self._preset_menu)
        self.preset_menu_btn.hide()
        self._mine_on = ""   # the preset of yours picked last (Update / Reset are for it)
        pair = QHBoxLayout()
        pair.setSpacing(2)
        pair.addWidget(self.save_preset_btn)
        pair.addWidget(self.preset_menu_btn)
        head.addLayout(pair)
        if self.has_speed:   # a stream has no pad to copy
            self.save_btn = QPushButton(_("Save as new pad"))
            self.save_btn.setMinimumHeight(36)
            self.save_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self.save_btn.setToolTip(_("A copy of the sound playing now with this speed, "
                                       "pitch and these effects on it, as a pad of its own"))
            self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            icons.set_icon(self.save_btn, "copy", size=18)
            self.save_btn.clicked.connect(self._save_new)
            head.addWidget(self.save_btn)
        head.addWidget(reset)
        self._head_btns = [b for b in (self.save_preset_btn, getattr(self, "save_btn", None),
                                       reset) if b]
        v.addLayout(head)
        v.addWidget(self._rule())

        # --- your own presets (audio/mypresets.py), then a voice setup (the Voice tab's
        # My voice combos) on everything here: one grid, the names in one column
        self.setup_name = ""
        self._setup_chips: dict[str, QPushButton] = {}
        srow = QGridLayout()   # the name, then its chips with the progress under them
        srow.setHorizontalSpacing(12)
        srow.setVerticalSpacing(6)
        self._srow = srow

        # your presets: one line of chips whatever the count, the rest under More
        self.my_presets: dict[str, dict] = {}
        self.my_chips: dict[str, QPushButton] = {}
        self._mine_stale = True   # the row's chips not made for what's saved yet
        self._mine_lab = self._row_name(_("My presets"))
        srow.addWidget(self._mine_lab, 0, 0, Qt.AlignmentFlag.AlignTop)
        self.mine_box = QWidget()
        self.mine_box.setObjectName("spcol")
        self.mine_box.setStyleSheet("QWidget#spcol { background:transparent; }")
        self.mine_line = QHBoxLayout(self.mine_box)
        self.mine_line.setContentsMargins(0, 0, 0, 0)
        self.mine_line.setSpacing(4)
        self.more_btn = QPushButton()
        self.more_btn.setObjectName("small")
        self.more_btn.setCheckable(True)   # lit when the preset that's on is in there
        self.more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more_btn.clicked.connect(self._more_menu)
        srow.addWidget(self.mine_box, 0, 1)
        # a deleted preset can come back while the pop-up is open
        self.undo_row = QWidget()
        self.undo_row.setObjectName("spcol")
        self.undo_row.setStyleSheet("QWidget#spcol { background:transparent; }")
        u = QHBoxLayout(self.undo_row)
        u.setContentsMargins(0, 0, 0, 0)
        u.setSpacing(8)
        self.undo_text = QLabel()
        self.undo_text.setObjectName("hint")
        self.undo_btn = QPushButton(_("Undo"))
        self.undo_btn.setObjectName("small")
        self.undo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.undo_btn.clicked.connect(self._undo_delete)
        u.addWidget(self.undo_text)
        u.addWidget(self.undo_btn)
        u.addStretch(1)
        self.undo_row.hide()
        self._deleted: tuple[str, int, dict] | None = None
        srow.addWidget(self.undo_row, 1, 1)

        srow.addWidget(self._rule(), 2, 0, 1, 2)   # presets above, combos below
        lab = self._setups_lab = self._row_name(_("My voice combos"))
        srow.addWidget(lab, 3, 0, Qt.AlignmentFlag.AlignTop)
        self.setups_box = QWidget()
        self.setups_box.setObjectName("spcol")
        self.setups_box.setStyleSheet("QWidget#spcol { background:transparent; }")
        self.setups_flow = Flow(self.setups_box, gap=4)
        srow.addWidget(self.setups_box, 3, 1)
        srow.setColumnStretch(1, 1)
        self.busy_row = QWidget()
        self.busy_row.setObjectName("spcol")
        self.busy_row.setStyleSheet("QWidget#spcol { background:transparent; }")
        b = QHBoxLayout(self.busy_row)
        b.setContentsMargins(0, 0, 0, 0)
        b.setSpacing(8)
        self.busy_text = QLabel()
        self.busy_text.setObjectName("hint")
        self.busy_bar = QProgressBar()
        self.busy_bar.setTextVisible(False)
        self.busy_bar.setFixedHeight(6)
        self.busy_cancel = QPushButton(_("Cancel"))
        self.busy_cancel.setObjectName("small")
        self.busy_cancel.clicked.connect(self.setup_cancelled)
        b.addWidget(self.busy_text)
        b.addWidget(self.busy_bar, 1)
        b.addWidget(self.busy_cancel)
        self.busy_row.hide()
        srow.addWidget(self.busy_row, 4, 1)
        v.addLayout(srow)
        v.addWidget(self._rule())

        cols = QHBoxLayout()
        cols.setSpacing(16)
        left_w, right_w = QWidget(), QWidget()
        for w in (left_w, right_w):
            w.setObjectName("spcol")    # sits on the popup, no box of its own
            w.setStyleSheet("QWidget#spcol { background:transparent; }")
            w.setFixedWidth(COL_W)
        cols.addWidget(left_w, 0, Qt.AlignmentFlag.AlignTop)
        divider = QFrame()
        divider.setObjectName("vsep")
        divider.setFixedWidth(1)
        cols.addWidget(divider)
        cols.addWidget(right_w, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(cols)
        # the sliders, knobs and presets: the same widgets as Edit sound's (soundpanel)
        p = self.panel = SoundPanel(SPEED, PITCH, VOLUME, VOLUME_QUICK, has_speed=self.has_speed)
        self.speed, self.pitch, self.volume, self.keep = p.speed, p.pitch, p.volume, p.keep
        self.pitch_note, self.fx, self.fx_presets, self.fx_note = (p.pitch_note, p.knobs,
                                                                   p.presets, p.fx_note)
        self._name_w, self._quick_x = p.name_w, p.quick_x
        self._effects(right_w)

        outer, v = v, QVBoxLayout(left_w)     # the speed & pitch column
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        v.addWidget(section_label(_("Speed & pitch") if self.has_speed else _("Pitch")))
        v.addWidget(self.speed)
        v.addWidget(p.speed_quick)
        v.addSpacing(2)
        v.addWidget(self.pitch)
        v.addWidget(self.pitch_note)
        v.addWidget(self.keep)
        if not self.has_speed:    # a live stream can't be sped up or slowed down
            for w in (self.speed, p.speed_quick, self.keep):
                w.hide()

        # --- the volume of everything here, 100 % = as it is (livefx.VOLUME)
        v.addSpacing(2)
        v.addWidget(self._rule())
        self.volume.setToolTip(_("How loud they are, up to 4 times as loud. Over 100 % "
                                 "the loudest bits are rounded off so it doesn't crackle"))
        v.addWidget(self.volume)
        v.addWidget(p.volume_quick)

        # --- Redline: its own section, locked until you ask for it
        v.addSpacing(2)
        v.addWidget(self._rule())
        red_row = QHBoxLayout()
        red_row.setSpacing(8)
        red_text = QVBoxLayout()
        red_text.setSpacing(0)
        red_name = QLabel(_("Redline"))
        red_name.setStyleSheet("font-weight:700;")
        red_sub = QLabel(_("Up to {redline:g}x speed and ±{hi:g} st pitch",
                           redline=top, hi=REDLINE_PITCH.hi) if self.has_speed
                         else _("Up to ±{hi:g} st pitch", hi=REDLINE_PITCH.hi))
        red_sub.setObjectName("hint")
        red_text.addWidget(red_name)
        red_text.addWidget(red_sub)
        red_row.addLayout(red_text, 1)
        self.redline = QPushButton(_("Unlock"))
        icons.set_icon(self.redline, "shield", size=14)
        self.redline.setObjectName("small")
        self.redline.setCheckable(True)
        self.redline.setCursor(Qt.CursorShape.PointingHandCursor)
        self.redline.setMinimumWidth(84)
        self.redline.setToolTip(_("Unlock silly speeds (up to {redline:g}x) and pitch (±{hi:g} "
                                  "st)", redline=top, hi=REDLINE_PITCH.hi) if self.has_speed
                                else _("Unlock silly pitch (±{hi:g} st)", hi=REDLINE_PITCH.hi))
        self.redline.toggled.connect(self.set_redline)
        red_row.addWidget(self.redline, 0, Qt.AlignmentFlag.AlignVCenter)
        v.addLayout(red_row)
        self.red_box = QWidget()
        self.red_box.setObjectName("redbox")    # sits on the popup, no box of its own
        self.red_box.setStyleSheet("QWidget#redbox { background:transparent; }")
        rv = QVBoxLayout(self.red_box)
        rv.setContentsMargins(0, 4, 0, 0)
        rv.setSpacing(6)
        self.meter = RevMeter(top if self.has_speed else REDLINE_PITCH.hi,
                              pitch=not self.has_speed)
        rv.addWidget(self.meter)
        rv.addLayout(self._quick_row(tuple(s for s in REDLINE_QUICK if s <= top))
                     if self.has_speed else self._pitch_row(PITCH_QUICK))
        self.red_box.hide()
        v.addWidget(self.red_box)

        v = outer
        if hint:
            v.addSpacing(2)
            v.addWidget(self._rule())
            v.addWidget(hint_label(hint))

        p.tuning_edited.connect(self._edited)
        p.knobs_edited.connect(self._fx_edited)
        p.volume_edited.connect(self._fx_edited)
        p.preset_clicked.connect(self._preset_clicked)
        self.clicked.connect(self._toggle)
        self.fill_my_presets()
        self._label()

    def _effects(self, box: QWidget):
        """The right column: one slider per live effect, then presets that set them."""
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        v.addWidget(section_label(_("Effects")))
        for s in self.fx.values():
            v.addWidget(s)
        v.addWidget(self.panel.preset_box)
        v.addWidget(self.fx_note)

    @staticmethod
    def _rule() -> QFrame:
        line = QFrame()
        line.setObjectName("vsep")       # the bar divider's colour, laid flat
        line.setFixedHeight(1)
        return line

    def _quick_row(self, speeds) -> QHBoxLayout:
        """Preset speeds, under the slider track so they read as part of it."""
        return quick_row([(f"{s:g}x", s) for s in speeds], self._quick_x,
                         lambda s: self.speed.set_value(s) or self._edited())

    def _pitch_row(self, steps) -> QHBoxLayout:
        """A stream's Redline pitches, under its meter like the speeds are."""
        return quick_row([(f"{st:+g}", st) for st in steps], self._quick_x,
                         lambda st: self.pitch.set_value(st) or self._edited())

    def set_redline(self, on: bool):
        """Unlock (or lock again) the silly range. Locking pulls the values back in."""
        if self.redline.isChecked() != on:
            self.redline.setChecked(on)   # comes back here through toggled
            return
        if on:
            self._count("redline")
        icons.set_icon(self.redline, "wave" if on else "shield", size=14)
        self.redline.setText(_("On") if on else _("Unlock"))
        self.speed.set_param(self._speed_hi if on else SPEED)
        self.pitch.set_param(REDLINE_PITCH if on else PITCH)
        self.red_box.setVisible(on)        # the rev meter: the speed, or a stream's pitch
        if self.pop.isVisible():
            self._open()                  # resize / re-place it for the new height
        self._edited()

    def values(self) -> tuple[float, float, bool]:
        return self.speed.value(), self.pitch.value(), self.keep.isChecked()

    def is_default(self) -> bool:
        s, p, _k = self.values()
        return abs(s - 1) < 1e-3 and abs(p) < 1e-3

    def set_values(self, speed: float, pitch: float, keep: bool):
        if not SPEED.lo <= speed <= SPEED.hi or not PITCH.lo <= pitch <= PITCH.hi:
            self.redline.setChecked(True)     # a value only the Redline range holds
        self.speed.set_value(speed)
        self.pitch.set_value(pitch)
        self.keep.blockSignals(True)
        self.keep.setChecked(keep)
        self.keep.blockSignals(False)
        self._edited()

    def load(self, speed: float, pitch: float, keep: bool, amounts: dict):
        """Show these values without sending them anywhere (`changed` and `fx_changed`
        stay quiet): a pad's own effects with these on top, or these alone again."""
        self._mine_on = ""   # another sound's knobs: not the preset picked before
        self.blockSignals(True)
        try:
            self.set_values(speed, pitch, keep)
            self.set_fx(amounts)
        finally:
            self.blockSignals(False)

    def set_target(self, name: str | None):
        """The knobs show the sound `name` plays with (its own effects with these on
        top: its name in the header), or every sound's layer alone again (None)."""
        self._sub.setText(short(name, 20) if name else self._sub_all)
        if self.pop.isVisible():
            self._open()

    def _save_new(self):
        self.pop.hide()   # a name box comes up next: the pop-up would sit over it
        self.save_new.emit()

    def reset(self):
        self._count("reset")
        self._mine_on = ""
        self.set_values(1.0, 0.0, self.keep.isChecked())
        self.set_fx({})
        if self.setup_name:
            self.setup_picked.emit("")

    # ---- voice setups (ui.livesetups fills them in and applies them)
    def set_setups(self, items, current: str):
        """items: [(name, icon or None, tip)]: a chip each, after "No voice"."""
        while self.setups_flow.count():
            it = self.setups_flow.takeAt(0)
            w = it.widget() if it is not None else None
            if w is not None:
                w.deleteLater()
        self._setup_chips = {}
        for name, icon, tip in [("", None, "")] + list(items):
            c = QPushButton(name or _("No voice"))
            c.setObjectName("small")
            c.setCheckable(True)
            c.setCursor(Qt.CursorShape.PointingHandCursor)
            if icon is not None:
                c.setIcon(icon)
            if tip:
                c.setToolTip(tip)
            c.clicked.connect(lambda _on=False, n=name: self._chip(n))
            self._setup_chips[name] = c
            self.setups_flow.addWidget(c)
        c.ensurePolished()
        self._setups_lab.setFixedHeight(c.sizeHint().height())
        self.set_setup(current if current in self._setup_chips else "")

    def _chip(self, name: str):
        self.set_setup(self.setup_name)   # stays as it is until it's applied
        self.setup_picked.emit(name)

    def set_setup(self, name: str):
        """The setup that's on now ("" = none): its chip lit, its name on the button."""
        self.setup_name = name
        for n, c in self._setup_chips.items():
            c.setChecked(n == name)
        self._label()

    def set_busy(self, text: str = "", frac: float | None = None):
        """A setup's AI voice getting ready: `text` with a bar (frac 0..1, None: no
        idea how long) and Cancel; "" hides it."""
        self.busy_row.setVisible(bool(text))
        self.busy_text.setText(text)
        if frac is None:
            self.busy_bar.setRange(0, 0)
        else:
            self.busy_bar.setRange(0, 100)
            self.busy_bar.setValue(int(round(frac * 100)))
        if self.pop.isVisible():
            self._open()   # grows or shrinks for the row

    def fx_values(self) -> dict[str, float]:
        """The effect knobs off 0 and the volume off 100 % (livefx.clean)."""
        amounts = {k: s.value() for k, s in self.fx.items()}
        if hasattr(self, "volume"):   # (the effects column is built before it)
            amounts[VOLUME.key] = self.volume.value()
        return livefx.clean(amounts)

    def set_fx(self, amounts: dict):
        """Set every effect knob and the volume (missing ones go to 0, and 100 %)."""
        for k, s in self.fx.items():
            s.set_value(amounts.get(k, 0.0))
        self.volume.set_value(amounts.get(VOLUME.key, VOLUME.default))
        self._fx_edited()

    def _keep_volume(self, amounts: dict) -> dict:
        """`amounts` with the volume as it is now: a preset never changes it."""
        return {**amounts, VOLUME.key: self.volume.value()}

    def _preset(self, name: str) -> dict:
        """A built-in preset, or one of yours."""
        return livefx.PRESETS.get(name) or self.my_presets.get(name, {})

    def apply_preset(self, name: str):
        """Set a preset's knobs, and its speed and pitch when it has them (Nightcore).
        One of yours sets the volume too: it was saved with it."""
        p = self._preset(name)
        t = livefx.tuning(p, self.has_speed)
        if t is not None:
            self.set_values(t[0], t[1], t[2] if self.has_speed else self.keep.isChecked())
        self.set_fx(p if name in self.my_presets else self._keep_volume(p))

    def preset_on(self, name: str) -> bool:
        """The knobs (and the speed and pitch, if it sets them) are the preset's, at
        any volume (one of yours: at its own)."""
        p = self._preset(name)
        mine = name in self.my_presets
        knobs = {k: v for k, v in self.fx_values().items() if mine or k != VOLUME.key}
        want = livefx.clean(p)
        if not mine:
            want.pop(VOLUME.key, None)
        if knobs != want:
            return False
        t = livefx.tuning(p, self.has_speed)
        if t is None:
            return True
        s, pitch, keep = self.values()
        return (abs(s - t[0]) < 1e-3 and abs(pitch - t[1]) < 1e-3
                and (keep == t[2] or not self.has_speed))

    def _preset_clicked(self, name: str, on: bool):
        """A preset sets its knobs; clicked again (lit) they go back to how they were
        before it, not all off: a tweak made before picking it isn't lost."""
        if on:
            self._count(f"preset-{usage.live_preset_tag(name)}")
            before = (self.fx_values(), self.values())
            self._mine_on = name if name in self.my_presets else ""
            self.apply_preset(name)
            self._before_preset = (name, before)
            return
        if name == self._mine_on:
            self._mine_on = ""
        was = getattr(self, "_before_preset", None)
        fx, (speed, pitch, keep) = (was[1] if was and was[0] == name
                                    else ({}, (1.0, 0.0, self.keep.isChecked())))
        mine = name in self.my_presets
        if livefx.tuning(self._preset(name)) is not None:
            self.set_values(speed, pitch, bool(keep))
        self.set_fx(fx if mine else self._keep_volume(fx))

    def _light_presets(self):
        if hasattr(self, "volume"):   # (the effects column is built before the sliders)
            for name, b in (*self.fx_presets.items(), *self.my_chips.items()):
                b.setChecked(self.preset_on(name))
            self.more_btn.setChecked(any(self.preset_on(n) for n in self._more_names()))
            edited = self.edited_preset()
            for name, b in self.my_chips.items():   # changed since it was picked: still
                b.setText(short(name, 18) + (" •" if name == edited else ""))   # lit, a dot
                b.setChecked(b.isChecked() or name == edited)
            self._show_update()

    def edited_preset(self) -> str:
        """The preset of yours picked last, when the knobs have moved off it since; or ""."""
        name = self._mine_on
        return name if name in self.my_presets and not self.preset_on(name) else ""

    def _show_update(self):
        """Save preset, or Update "name" with its ▾ while your preset is changed."""
        name = self.edited_preset()
        b = self.save_preset_btn
        was = b.objectName() == "primary"
        if name:
            b.setText(_("Update “{name}”", name=short(name, 18)))
            b.setToolTip(_("Save what you have now into “{name}”", name=name))
            b.setObjectName("primary")
        else:
            b.setText(_("Save preset"))
            b.setToolTip(_("Keep the speed, pitch, effects and volume you "
                           "have now as a preset of your own"))
            b.setObjectName("")
        b.setAccessibleName(b.text())
        icons.set_icon(b, "check" if name else "plus", "on_accent" if name else None,
                       size=18)
        self.preset_menu_btn.setVisible(bool(name))
        if was != bool(name):
            b.style().unpolish(b)
            b.style().polish(b)
            if self.pop.isVisible():
                self._open()   # the header's buttons are measured again

    def _save_or_update(self):
        if name := self.edited_preset():
            self.update_preset(name)
        else:
            self.save_preset()

    def update_preset(self, name: str):
        """Update "name": what's on now saved into your preset, in its place."""
        speed, pitch, keep = self.values()
        mypresets.put("live", name, {"speed": speed, "pitch": pitch, "keep": keep,
                                     **self.fx_values()})
        self.fill_my_presets()
        self._light_presets()   # (a closed pop-up fills its row when it opens)

    def _preset_menu(self):
        name = self.edited_preset()
        if not name:
            return
        m = QMenu(self.pop)
        m.addAction(icons.icon("check"), _("Update “{name}”", name=short(name, 24)),
                    lambda: self.update_preset(name))
        m.addAction(icons.icon("history"), _("Reset “{name}”", name=short(name, 24)),
                    lambda: self.apply_preset(name))
        m.addSeparator()
        m.addAction(icons.icon("plus"), _("Save as a new preset"), self.save_preset)
        m.exec(self.save_preset_btn.mapToGlobal(QPoint(0, self.save_preset_btn.height())))

    # ---- your own presets (audio/mypresets.py): the My presets row
    @staticmethod
    def _row_name(text: str) -> QLabel:
        """A row's name (My presets, My voice combos) on its chips' line: as tall as a
        chip, its text centred in that (no padding above, which pushed it below the
        chips' words)."""
        lab = section_label(text)
        lab.setProperty("head", True)
        lab.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return lab

    def _more_names(self) -> list[str]:
        return [n for n in self.my_presets if n not in self.my_chips]

    def _row_width(self) -> int:
        """What the row's chips have: the two columns under it, less the names' column."""
        names = max(self._mine_lab.sizeHint().width(), self._setups_lab.sizeHint().width())
        return 2 * COL_W + 2 * 16 + 1 - names - self._srow.horizontalSpacing()

    def fill_my_presets(self):
        """Your presets as chips on one line, as many as fit; the rest under More (N).
        A hundred of them never make the pop-up taller.
        The chips are measured only while the pop-up is open (_open makes them right
        after showing it): after a theme switch a closed one is restyled when shown
        (theme._style_when_shown), and measured before that it kept a stale style."""
        self.my_presets = mypresets.load("live")
        self._mine_stale = not self.pop.isVisible()
        if self._mine_stale:
            return
        while self.mine_line.count():
            it = self.mine_line.takeAt(0)
            w = it.widget() if it is not None else None
            if w is not None and w is not self.more_btn:
                w.hide()   # (deleteLater waits for the event loop: it stayed drawn)
                w.deleteLater()
        self.my_chips = {}
        if not self.my_presets:
            empty = QLabel(_("None saved yet"))
            empty.setObjectName("hint")
            self.mine_line.addWidget(empty)
        room, gap = self._row_width(), self.mine_line.spacing()
        names = list(self.my_presets)
        # the More button as wide as it can get, so the line never overflows
        self.more_btn.setText(_("More ({n})", n=len(names)) + "  ▾")
        self.more_btn.ensurePolished()
        for i, name in enumerate(names):
            b = QPushButton(short(name, 18) + " •")   # room for the changed dot
            b.setObjectName("small")
            b.ensurePolished()
            more = gap + self.more_btn.sizeHint().width() if i < len(names) - 1 else 0
            if b.sizeHint().width() + gap + more > room:
                b.deleteLater()
                break
            room -= b.sizeHint().width() + gap
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(_("{name}: your preset. Right-click to rename or delete it",
                           name=name))
            b.setAccessibleName(name)
            b.clicked.connect(lambda on, n=name: self._preset_clicked(n, on))
            b.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            b.customContextMenuRequested.connect(
                lambda at, n=name, b=b: self._my_menu(n, b.mapToGlobal(at)))
            self.my_chips[name] = b
            self.mine_line.addWidget(b)
        rest = len(self._more_names())
        self.more_btn.setText(_("More ({n})", n=rest) + "  ▾")
        self.more_btn.setToolTip(ngettext("{n} more of your presets",
                                          "{n} more of your presets", rest))
        self.more_btn.setVisible(rest > 0)
        if rest:
            self.mine_line.addWidget(self.more_btn)
        self.mine_line.addStretch(1)
        self._mine_lab.setFixedHeight(self.more_btn.sizeHint().height())   # a chip's
        self._light_presets()

    def _more_menu(self):
        """The presets that don't fit on the line: pick one (again: off, as a chip
        does); right-click one to rename or delete it."""
        self._light_presets()   # (the click toggled it)
        m = _MoreMenu(self.pop, self._my_menu)
        for name in self._more_names():
            a = m.addAction(name)
            a.setData(name)
            a.setCheckable(True)
            a.setChecked(self.preset_on(name))
            a.triggered.connect(lambda on, n=name: self._preset_clicked(n, on))
        m.exec(self.more_btn.mapToGlobal(QPoint(0, self.more_btn.height())))

    def _ask_preset_name(self, title: str, text: str, keep: str = "") -> str:
        """A name for one of your presets, or "" if cancelled. A built-in preset's name
        is taken; so is another of yours, unless you agree to replace it."""
        builtin = {n.casefold() for n in livefx.PRESETS}
        parent = self.window()
        while True:
            name, ok = QInputDialog.getText(parent, title, _("Name:"),
                                            QLineEdit.EchoMode.Normal, text)
            name = mypresets.clean_name(name) if ok else ""
            if not name:
                return ""
            if name.casefold() in builtin:
                QMessageBox.information(parent, title, plain_tip(_(
                    "“{name}” is a built-in preset's name. Pick another one.", name=name)))
                text = name
                continue
            other = mypresets.find("live", name)
            if other is None or other == keep:
                return name
            if QMessageBox.question(parent, title, plain_tip(_(
                    "You already have a preset called “{name}”. Replace it?", name=other))
                    ) == QMessageBox.StandardButton.Yes:
                return other
            text = name

    def save_preset(self):
        """+ Save preset: what's on now, under a name, in My presets."""
        self.pop.hide()   # a name box comes up next: the pop-up would sit over it
        if mypresets.full("live"):
            QMessageBox.information(self.window(), _("Save preset"), ngettext(
                "You have {n} preset, the most there can be. Delete one first.",
                "You have {n} presets, the most there can be. Delete one first.",
                mypresets.MAX_PRESETS))
        else:
            n, base = 1, _("My preset")
            while mypresets.find("live", f"{base} {n}"):
                n += 1
            name = self._ask_preset_name(_("Save preset"), f"{base} {n}")
            if name:
                speed, pitch, keep = self.values()
                mypresets.put("live", name, {"speed": speed, "pitch": pitch,
                                             "keep": keep, **self.fx_values()})
                self._mine_on = name   # changed again later: Update is for this one
        self.fill_my_presets()
        self._open()

    def _my_menu(self, name: str, at):
        m = QMenu(self.pop)
        m.addAction(icons.icon("edit"), _("Rename"), lambda: self._rename_preset(name))
        m.addAction(icons.icon("trash", "danger_text"), _("Delete"),
                    lambda: self.delete_preset(name))
        m.exec(at)

    def _rename_preset(self, old: str):
        self.pop.hide()
        new = self._ask_preset_name(_("Rename preset"), old, keep=old)
        if new and new != old and mypresets.rename("live", old, new):
            if self._mine_on == old:
                self._mine_on = new
        self.fill_my_presets()
        self._open()

    def delete_preset(self, name: str):
        """Take one of your presets out; Undo (under the row) puts it back while the
        pop-up is open."""
        got = mypresets.remove("live", name)
        if got is None:
            return
        self._deleted = (name, *got)
        if self._mine_on == name:
            self._mine_on = ""
        self.undo_text.setText(_("Deleted “{name}”", name=name))
        self.undo_row.show()
        self.fill_my_presets()
        if self.pop.isVisible():
            self._open()   # grows for the Undo line

    def _undo_delete(self):
        if self._deleted is not None:
            name, at, p = self._deleted
            mypresets.put("live", name, p, at)
        self._deleted = None
        self.undo_row.hide()
        self.fill_my_presets()
        if self.pop.isVisible():
            self._open()

    def _fx_edited(self):
        now = self.fx_values()
        was, self._seen_fx = self._seen_fx, now
        self._count(*(f"fx-{k}" for k in sorted(set(was) | set(now))
                      if was.get(k) != now.get(k)))
        self._light_presets()
        self._label()
        self.fx_changed.emit(now)

    def eventFilter(self, obj, ev):
        if obj is self.pop and ev.type() == QEvent.Type.Hide:
            self._hidden_at = time.monotonic()
            self.closed.emit()
            if self._deleted is not None:   # Undo is for while it's open
                self._deleted = None
                self.undo_row.hide()
        return super().eventFilter(obj, ev)

    def _toggle(self):
        # a click on this button while it's open closes the pop-up first (Qt does that
        # on the press): don't open it again on the release
        if time.monotonic() - self._hidden_at < 0.3:
            return
        self._open()

    def _open(self):
        if not self.pop.isVisible():
            usage.used(f"live-opened-{self._what}")   # the tab's name only (usage.py)
            self.opening.emit()
            self.my_presets = mypresets.load("live")   # (saved from another tab's too)
            self._mine_stale = True
        self._fit_head()
        # settle the layouts first: right after Redline hides its box, the column's
        # and the popup's size hint (and the popup's minimum) still hold the old,
        # taller height, so adjustSize alone would never shrink it back
        for w in (self.red_box.parentWidget(), self.pop):
            lay = w.layout() if w is not None else None
            if lay is not None:
                lay.activate()
        self.pop.adjustSize()
        pos = self.mapToGlobal(QPoint(0, 0))
        # kept on the screen the button is on (a second monitor can sit left of or
        # above the primary one, at negative coordinates)
        area = (QApplication.screenAt(pos) or self.screen()).availableGeometry()
        y = pos.y() - self.pop.height() - 4     # above the bar, unless there's no room
        if y < area.top():
            y = pos.y() + self.height() + 4
        y = max(area.top(), min(y, area.bottom() - self.pop.height() + 1))
        x = pos.x() + self.width() - self.pop.width()   # its right edge on the button's
        if x < self.window().mapToGlobal(QPoint(0, 0)).x():
            x = pos.x()   # a button near the window's left (Apps): it opens to the right
        x = max(area.left(), min(x, area.right() - self.pop.width() + 1))
        self.pop.move(x, y)
        self.pop.show()
        if self._mine_stale:   # the My presets row, now it's styled: fits and places it
            self.fill_my_presets()
            self._open()

    def _fit_head(self):
        """Measure the header's buttons on the screen the pop-up opens on. A button
        keeps the size it measured first: built on one monitor and opened on one with
        other scaling, its words came out wider than it ("Save as new pa")."""
        self.pop.setScreen(self.screen())
        self.save_preset_btn.setMinimumWidth(0)
        self.save_preset_btn.setMaximumWidth(16777215)
        self._show_update()   # its words (Save preset, or Update "name") and icon
        for b in self._head_btns:
            text = b.text()   # new words: the button forgets the size it kept
            b.setText("")
            b.setText(text)
            if b.objectName() == "liveReset":   # whole, never squeezed (see __init__)
                b.setMinimumWidth(max(96, b.sizeHint().width()))
        # three buttons wider than the two columns under them (a long language, big
        # fonts): Save preset gives way to its + alone (the tooltip says it), so the
        # pop-up never grows for it
        cols = 2 * COL_W + 2 * 16 + 1
        self._sub.show()
        self._head.invalidate()
        if self._head.minimumSize().width() > cols:
            self.save_preset_btn.setText("")
            icons.text_gap(self.save_preset_btn)   # no gap: centred
            self.save_preset_btn.setFixedWidth(36)   # square, as tall as it is
        # "All sounds" whole or not at all: squeezed it lost its last letters
        self._head.invalidate()
        self._sub.setVisible(self._head.sizeHint().width() <= cols)

    def _label(self):
        s, p, _k = self.values()
        fx = bool(self.fx_values())
        if self.has_speed:
            txt = f"{s:g}x"
            if abs(p) >= 1e-3:
                txt += f" {p:+g}"
            if fx:
                txt += " · FX"
            if self.setup_name:
                txt += f" · {short(self.setup_name)}"
        else:   # no speed to show: "Effects" until something's on
            parts = [f"{p:+g} st"] if abs(p) >= 1e-3 else []
            if fx:
                parts.append("FX")
            if self.setup_name:
                parts.append(short(self.setup_name))
            txt = " · ".join(parts) or _("Effects")
        fx = fx or bool(self.setup_name)
        self.setText(txt)
        hot = s >= REDLINE_AT - 1e-6 or abs(p) > PITCH.hi
        # scoped to this button: unscoped, it would cascade into the popup (a child).
        # Only when the look changes: each set re-polishes the popup's ~90 widgets too
        # (6-9 ms a slider step)
        sheet = ("" if self.is_default() and not fx else
                 f"QPushButton[speedpitch=\"true\"] {{ font-weight:700; "
                 f"color:{RED if hot else theme.status('warn')}; }}")
        if sheet != self.styleSheet():
            self.setStyleSheet(sheet)

    def _count(self, *names: str):
        """Something changed while the pop-up is open, by hand (not the values put back
        at start): for the usage count, which tab's and which controls, by name only."""
        if names and self.pop.isVisible():
            if "pitch" in names:   # Chipmunk / Demon Mode
                achievements.pitched(self.pitch.value())
            if "speed" in names:   # Fast Forward / Slow Mo
                achievements.speed(self.speed.value(), SPEED.lo, SPEED.hi)
            usage.used(f"live-changed-{self._what}")
            for n in names:
                usage.used(f"live-{n}")

    def _edited(self):
        now = self.values()
        was, self._seen = self._seen, now
        self._count(*(n for n, a, b in zip(("speed", "pitch", "keep-pitch"), was, now)
                      if a != b))
        self._light_presets()
        self._label()
        self.meter.set_value(self.speed.value() if self.has_speed else self.pitch.value())
        self._pitch_note()
        self.changed.emit(*self.values())

    def _pitch_note(self):
        self.panel.show_pitch_note()
