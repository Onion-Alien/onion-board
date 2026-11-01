"""The On Air card at the rail's foot (ui/window/sidebar.py): the Live switch, who's
listening, Stop all, and the status lines under them (Line: offline, Tor, proxy,
remote control...), with its dots and the muted-a-long-time ring."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QEvent, QObject, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (QBoxLayout, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QSpacerItem, QVBoxLayout, QWidget)

from soundboard.ui.kit import theme
from soundboard.core import usage
from soundboard.i18n import _, ngettext
from soundboard.ui.kit import icons
from soundboard.ui.kit.pixels import snap_to_pixels
from soundboard.ui.window.railsizes import BUTTON_W, OPEN_W, SIDE_OPEN


class _Dot(QWidget):
    """A small status dot, over the corner of an icon (it never takes clicks): a
    warning, or with `ok` set, all good."""

    SIZE = 8

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.ok = False
        self.hide()

    def set_ok(self, ok: bool):
        if ok != self.ok:
            self.ok = ok
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.T["ok_text" if self.ok else "warn_text"]))
        p.drawEllipse(QRectF(self.rect()))
        p.end()


class _Ring(QWidget):
    """OutputBlock's yellow "muted a long time" ring, drawn over the card (never
    takes clicks)."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, _e):
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(theme.T["warn_text"]), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 14, 14)
        p.end()


class OutputBlock(QFrame):
    """Named output switch and connection help for the expanded rail.

    Built on keylines (docs/DESIGN.md *Icon and text alignment*): its icons sit in
    the same column as the tab icons above and the buttons below, every line of
    words starts at the same x after them, and each icon is centred on the cap
    height of its label's first line. The status line is the setup action too:
    "Not configured ›" is one click to Setup, "Connected" is only words. Under it,
    a line for each thing worth knowing about the network (set_lines): the app
    going online through a proxy or Tor or not at all, a phone remote listening.
    Each is one click to its Settings page; the small card keeps their icons under
    the switch."""

    lineClicked = Signal(str)   # a line's Settings page
    groupToggled = Signal(str, bool)   # a group (Line.group) folded shut (True) or open

    LEAD = 11             # card edge to the icon column: the tab icons' centre line
    TOP = 12              # card padding over the title row (the 12 of settings cards)
    PAD = 8               # the card's other padding
    GLYPH = 16            # the icon column
    GAP = 6               # icon to words (8 wraps longer titles on the 190 px rail)
    TEXT_X = LEAD + GLYPH + GAP   # the keyline: where every line of words starts
    SWITCH_GAP = 8        # words to the switch
    SWITCH = (38, 22)     # the switch's size
    ICON_X = LEAD + GLYPH // 2   # the icon column's centre: the tab icons'
    MIN_SCALE = 0.85      # the card scales down to fit, never smaller than this (smaller
                          # looked out of place); past that, the small card instead
    ROW_PAD = 4           # the status line's hover fill past its icon
    HEAD_H = 24           # a group's header (Line.group): its name over its lines
    MINI = 12             # a shut group's icons in its header, one per line
    ROW_GAP = 6           # title row to the status line's fill
    ROW_H = 34            # the status line's height, fill and all: Mute's and Stop all's
    CHEVRON = 12          # the status line's chevron: lighter than the icons
    STOP = 28             # Stop all after the switch, open: a normal icon button
    PAIR_H = 34           # open: Mute and Stop all, two halves of one row...
    PAIR_GAP = 8          # ...this far apart, and from the lines under them
    LINE_GAP = 4          # between the lines (set_lines), so their fills never touch
    PAIR_ICON = 18        # their icons
    INK_DOWN = 1          # the switch's and Stop all's ink this far under their box's
                          # centre: on the title's cap-height centre (measured)
    MUTED_LONG_S = 60     # muted this long: a yellow ring round the card and how long
                          # it's been, so a forgotten mute isn't taken for a broken app
    RING_OUT = 4          # the ring this far outside the card (the shut card is only
                          # as wide as its switch)

    def __init__(self, power: QPushButton, connection: QPushButton,
                 stop: QPushButton | None = None):
        super().__init__()
        from soundboard.ui.voice.voicefxpanel import Switch

        self.setObjectName("railoutput")
        # as tall as its rows: spare room in the rail's column never pads the card (the
        # row would sit off its centre line)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.power, self.connection, self.rail_stop = power, connection, stop
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        box = self.box = QVBoxLayout()
        box.setSpacing(0)
        outer.addLayout(box)
        top = self.top = QHBoxLayout()
        top.setSpacing(0)   # icon GAP words, 8 to the switch right after them
        mark = self.mark = self._glyph()
        self._scale = 1.0
        # the small card (the status line hidden): a dot on the On Air icon says
        # whether sending is set up (yellow: not yet, and the icon is the way to
        # Setup; green: working)
        self.dot = _Dot(self)
        mark.installEventFilter(self)
        # hugs its word: the switch right after "On" as after "Muted"
        self.title = _HugLabel("")
        self.title.setObjectName("railoutputtitle")
        self.title.setWordWrap(True)
        self.title.setAlignment(Qt.AlignmentFlag.AlignLeading | Qt.AlignmentFlag.AlignTop)
        self.title.setMinimumWidth(0)
        self.switch = Switch()
        self.switch.setProperty("glyphoffset", self.INK_DOWN)
        self.title.setBuddy(self.switch)
        self.switch.setChecked(power.isChecked())
        self.switch.toggled.connect(power.setChecked)
        power.toggled.connect(self.switch.setChecked)
        self._muted_at: float | None = None if power.isChecked() else time.monotonic()
        self._ring: _Ring | None = None
        self._muted_clock = QTimer(self)
        self._muted_clock.setInterval(5000)
        self._muted_clock.timeout.connect(self._muted_tick)
        if self._muted_at is not None:
            self._muted_clock.start()
        power.toggled.connect(self._muted_changed)   # (before the words: they show it)
        power.toggled.connect(self._name)
        self._name(power.isChecked())
        top.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
        self._title_gap = QSpacerItem(self.GAP, 0, QSizePolicy.Policy.Fixed,
                                      QSizePolicy.Policy.Minimum)
        top.addSpacerItem(self._title_gap)
        top.addWidget(self.title, 0, Qt.AlignmentFlag.AlignTop)
        self.caption = QLabel(self.title.text())
        self.caption.setObjectName("hint")
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setWordWrap(True)
        self.caption.setFixedWidth(BUTTON_W)
        self.caption.setBuddy(self.switch)
        top.addWidget(self.caption)
        self._switch_gap = QSpacerItem(self.SWITCH_GAP, 0, QSizePolicy.Policy.Fixed,
                                       QSizePolicy.Policy.Minimum)
        top.addSpacerItem(self._switch_gap)
        top.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignTop)
        # shut: under the column
        self._tail = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        top.addSpacerItem(self._tail)
        box.addLayout(top)
        # open: two halves of one row instead of the icon, word and switch: Mute (red,
        # struck through while muted) and Stop all (shut, the rail's own Stop all)
        self.pair = QWidget()
        self.pair.setObjectName("railpairrow")
        pair = self.pair_lay = QHBoxLayout(self.pair)
        pair.setSpacing(self.PAIR_GAP)
        self.mute = QPushButton()
        self.mute.setObjectName("railpair")
        # checked: live, as the switch and every other on/off control (named "On" or
        # "Muted", so a screen reader says "Others hear, pressed", never "Others hear, not pressed")
        self.mute.setCheckable(True)
        self.mute.setChecked(power.isChecked())
        self.mute.toggled.connect(power.setChecked)
        power.toggled.connect(self.mute.setChecked)
        self.stop = None
        if stop is not None:
            self.stop = QPushButton()
            self.stop.setObjectName("railpair")
            self.stop.clicked.connect(stop.click)
            icons.set_icon(self.stop, "stop", "danger_text", gap=False)
        for b in filter(None, (self.mute, self.stop)):
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            pair.addWidget(b, 1)
        outer.insertWidget(0, self.pair)
        power.toggled.connect(self._mute_look)
        self._mute_look(power.isChecked())
        self._status_gap = QSpacerItem(0, self.ROW_GAP, QSizePolicy.Policy.Minimum,
                                       QSizePolicy.Policy.Fixed)
        box.addSpacerItem(self._status_gap)
        # the status line is the button: its fill starts ROW_PAD before the icon (the
        # card's padding is that much less there, the title row that much in), so the
        # icon and words stay on their keylines
        self.setup = QPushButton()
        self.setup.setObjectName("railoutputsetup")
        self.setup.setProperty("quiet", True)
        self.setup.setMinimumHeight(self.ROW_H)
        # grows with a wrapped (translated) status instead of clipping it
        self.setup.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        row = self.row = QHBoxLayout(self.setup)
        row.setSpacing(0)
        row.addStretch(1)   # centred in the strip
        self.status_icon = self._glyph()
        self.status_text = _HugLabel("")
        self.status_text.setWordWrap(True)
        self.status_text.setAlignment(Qt.AlignmentFlag.AlignLeading | Qt.AlignmentFlag.AlignTop)
        self.arrow = self._glyph(self.CHEVRON)
        for w in (self.status_icon, self.status_text, self.arrow):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(self.status_icon, 0, Qt.AlignmentFlag.AlignTop)
        self._icon_gap = QSpacerItem(self.GAP, 0, QSizePolicy.Policy.Fixed,
                                     QSizePolicy.Policy.Minimum)
        row.addSpacerItem(self._icon_gap)
        row.addWidget(self.status_text, 0, Qt.AlignmentFlag.AlignTop)
        # (the chevron's glyph has ~2 px of air)
        self._arrow_gap = QSpacerItem(self.GAP - 2, 0, QSizePolicy.Policy.Fixed,
                                      QSizePolicy.Policy.Minimum)
        row.addSpacerItem(self._arrow_gap)
        row.addWidget(self.arrow, 0, Qt.AlignmentFlag.AlignTop)
        row.addStretch(1)   # the chevron stays beside its words
        self.setup.clicked.connect(self._setup_clicked)
        # the status strip along the card's foot: only while something needs a click
        self.strip = QFrame()
        self.strip.setObjectName("railoutputstrip")
        strip = QHBoxLayout(self.strip)
        strip.setContentsMargins(0, 0, 0, 0)
        strip.setSpacing(0)
        strip.addWidget(self.setup, 1)
        # its own rounded button inside the card, padded like Mute and Stop all over it
        self.strip_row = QWidget()
        self.strip_row.setObjectName("railpairrow")
        self.strip_lay = QHBoxLayout(self.strip_row)
        self.strip_lay.addWidget(self.strip, 1)
        outer.addWidget(self.strip_row)
        # the network lines (set_lines), made as they're needed
        self._lines: list[Line] = []
        self.net: list[_NetLine] = []
        # the groups' headers, made as they're needed; `shut`: the groups folded down to
        # their header (the window keeps them: groupToggled)
        self.heads: dict[str, _GroupHead] = {}
        self.shut: set[str] = set()
        self._order: list[QWidget] = []
        self.tight = False   # a short window: less room round the lines (_line_room)
        self.refresh()

    def _muted_changed(self, on: bool):
        self._muted_at = None if on else time.monotonic()
        if on:
            self._muted_clock.stop()
        else:
            self._muted_clock.start()
        self._follow_ring()

    def _muted_tick(self):
        self._name(self.power.isChecked())
        self._words()
        self._follow_ring()

    def muted_for(self) -> str:
        """How long others have heard nothing ("3 min"), once it's past MUTED_LONG_S;
        "" before that and while live."""
        if self._muted_at is None or self.power.isChecked():
            return ""
        s = time.monotonic() - self._muted_at
        if s < self.MUTED_LONG_S:
            return ""
        n = int(s // 60)
        return ngettext("{n} min", "{n} min", n)

    def _follow_ring(self):
        """The ring round the card while muted_for() says something: a sibling over the
        card, so it's drawn over the switch, RING_OUT outside the card's edge."""
        parent = self.parentWidget()
        if not (self.muted_for() and self.isVisible() and parent is not None):
            if self._ring is not None:
                self._ring.hide()
            return
        if self._ring is None or self._ring.parentWidget() is not parent:
            if self._ring is not None:
                self._ring.deleteLater()
            self._ring = _Ring(parent)
        usage.used("muted-ring")   # a name in a set: cheap on every move
        out = self.RING_OUT
        self._ring.setGeometry(self.geometry().adjusted(-out, -out, out, out)
                               & parent.rect())
        self._ring.raise_()
        self._ring.show()
        self._ring.update()

    def moveEvent(self, e):
        super().moveEvent(e)
        self._follow_ring()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._follow_ring()

    def showEvent(self, e):
        super().showEvent(e)
        self._follow_ring()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._follow_ring()

    def _glyph(self, size: int = 0) -> QLabel:
        g = QLabel()
        g.setFixedWidth(size or self.GLYPH)
        g.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        return g

    def _good(self) -> bool:
        return self.connection.property("state") == "ok"

    def _setup_clicked(self):
        if not self._good():   # "Connected" is only words
            self.connection.click()

    def _pin(self, glyph: QLabel, label: QLabel, lead: int = 0, mid: str = "cap",
             move: bool = True):
        """Centre `glyph` on `label`'s first line (not on the label's box: a wrapped
        label's box centre falls between its lines): on its cap height, or (`mid`
        "x") its x-height, for the chevron after lowercase words. `lead`: how far
        the label's first line is pushed down."""
        label.ensurePolished()
        fm = label.fontMetrics()
        centre = lead + fm.ascent() - (fm.xHeight() if mid == "x" else fm.capHeight()) / 2
        size = glyph.width()
        top = math.floor(centre - size / 2)   # (a half pixel up: the overshoot)
        if move:
            # an icon taller than the line can't go up to it: the words come down to it
            down = max(0, -top)
            label.setContentsMargins(0, lead + down, 0, 0)
            top += down
        top = max(0, top)
        glyph.setContentsMargins(0, top, 0, 0)
        glyph.setFixedHeight(max(fm.height() + label.contentsMargins().top(), top + size))

    @staticmethod
    def _air(glyph: QLabel) -> tuple[int, int]:
        """The empty columns left and right of an icon's ink in its box."""
        pm = glyph.pixmap()
        if pm.isNull():
            return 0, 0
        img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        w, h = img.width(), img.height()
        alpha = np.frombuffer(img.constBits(), np.uint32, w * h).reshape(h, w) >> 24
        cols = np.flatnonzero((alpha > 40).any(axis=0))
        if not cols.size:
            return 0, 0
        ratio = pm.devicePixelRatio() or 1
        return round(int(cols[0]) / ratio), round((w - 1 - int(cols[-1])) / ratio)

    def _balance(self, row: QHBoxLayout, glyph: QLabel, label: QLabel, tail: QLabel | None,
                 top: int, bottom: int):
        """Centre a line (icon, words, maybe a chevron) on its ink, not its boxes: a
        narrow icon (the phone, the shield) or chevron left it a few px off."""
        left = glyph.contentsMargins().left() + self._air(glyph)[0]
        if tail is not None and tail.isVisible():
            right = self._air(tail)[1]
        else:
            # the widest of the lines it's sized for (_HugLabel's widest): every line the
            # same shift, so their icons stay in one column
            fm = label.fontMetrics()
            ink = max(fm.tightBoundingRect(t).right() + 1
                      for t in (label.text(), *getattr(label, "_widest", ())))
            right = max(0, label.sizeHint().width() - ink)
        d, pad = left - right, self._px(self.PAD)
        row.setContentsMargins(pad + max(0, -d), top, pad + max(0, d), bottom)

    def _pin_all(self):
        # the title's first line is centred on the row's controls (the switch, Stop all),
        # and the mark on that line
        self.title.ensurePolished()
        high = self.switch.height()
        lead = max(0, -(-(high - self.title.fontMetrics().height()) // 2))
        self.title.setContentsMargins(0, lead, 0, 0)
        self._pin(self.mark, self.title, lead)
        # one line of status: centred in its ROW_H; wrapped, the icon and chevron stay
        # on the first line
        self.status_text.ensurePolished()
        row_h = self._px(self.ROW_H)
        pad = max(self._px(4), (row_h - self.status_text.fontMetrics().height()) // 2)
        self.row.setContentsMargins(self._px(self.PAD), pad, self._px(self.PAD), pad)
        self._pin(self.status_icon, self.status_text)
        # (on the icon's line, not the x-height; the words stay where the icon put them)
        self._pin(self.arrow, self.status_text, self.status_text.contentsMargins().top(),
                  move=False)
        self._balance(self.row, self.status_icon, self.status_text, self.arrow, pad, pad)
        for n in self.net:
            if self.property("expanded"):
                self._pin(n.glyph, n.label)
                self._balance(n.row, n.glyph, n.label, None, pad, pad)
            else:   # the icon alone, centred under the switch
                n.row.setContentsMargins(0, 8, 0, 0)
                n.glyph.setContentsMargins(0, 0, 0, 0)
                n.glyph.setFixedHeight(self.GLYPH)

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() in (QEvent.Type.StyleChange, QEvent.Type.FontChange):
            self._pin_all()

    def _px(self, n: float) -> int:
        """A length at the card's scale."""
        return max(1, round(n * self._scale))

    def _base_pt(self) -> float:
        """The app's text size (the card's words at full size)."""
        self.ensurePolished()
        return self.font().pointSizeF() if self.font().pointSizeF() > 0 else 10.0

    def _metrics(self, scale: float, bold: bool = False) -> QFontMetrics:
        font = QFont(self.font())
        font.setPointSizeF(self._base_pt() * scale)
        font.setBold(bold)
        return QFontMetrics(font)

    def text_x(self) -> int:
        """The keyline at the card's scale: where every line of words starts."""
        glyph = self._px(self.GLYPH)
        return round(self.ICON_X - glyph / 2) + glyph + self._px(self.GAP)

    def need(self, scale: float) -> int:
        """The card's width at `scale` with every line on one line: Mute and Stop all,
        and the status line, chevron and all."""
        def px(n: float) -> int:
            return max(1, round(n * scale))
        text_x = round(self.ICON_X - px(self.GLYPH) / 2) + px(self.GLYPH) + px(self.GAP)
        # the status line: in its own button, the card's padding round it and its own
        # inside it
        status_x = 2 * px(self.PAD) + px(self.GLYPH) + px(self.GAP)
        fm = self._metrics(scale)
        status = fm.horizontalAdvance(self.status_text.text())
        network = max((fm.horizontalAdvance(line.words) for line in self._lines), default=0)
        halves = 2 if self.stop is not None else 1
        # a group's header: its arrow, name and (shut) an icon per line
        small = QFont(self.font())
        small.setPointSizeF(_GroupHead.PT * scale)
        head = max((2 * px(self.PAD) + 2 * px(_GroupHead.SIDE) + px(self.CHEVRON) + px(self.GAP)
                    + QFontMetrics(small).horizontalAdvance(group_name(g)) + 1 + px(self.GAP)
                    + (n * (px(self.MINI) + px(_GroupHead.MINI_GAP))
                       if g in self.shut and n > 1 else 0)
                    for g, n in self._groups().items()), default=0)
        return max(2 * px(self.PAD) + halves * px(self.PAIR_H) + (halves - 1) * px(self.PAIR_GAP),
                   status_x + status + 1 + px(self.GAP - 2) + px(self.CHEVRON)
                   + 2 * px(self.PAD),
                   text_x + network + 1 + 2 * px(self.PAD), head)

    def scale_for(self, width: int) -> float:
        """The biggest scale (up to 1) the card fits `width` at, or 0: not even at
        MIN_SCALE (the rail shows the small card then)."""
        scale = 1.0
        while scale >= self.MIN_SCALE - 1e-9:
            if self.need(scale) <= width:
                return scale
            scale = round(scale - 0.01, 2)
        return 0.0

    def set_scale(self, scale: float):
        """The same card with every part (words, icons, switch, gaps) `scale` times
        its size: dragged narrower than it fits, it shrinks instead of wrapping."""
        if scale == self._scale:
            return
        self._scale = scale
        size = "" if scale == 1 else f"font-size:{self._base_pt() * scale:.2f}pt;"
        for label in (self.title, self.status_text, *(n.label for n in self.net)):
            label.setStyleSheet(size)
        self.set_expanded(bool(self.property("expanded")))
        self.refresh()

    def set_expanded(self, expanded: bool):
        self.setProperty("expanded", expanded)
        px = self._px
        glyph = px(self.GLYPH) if expanded else self.GLYPH
        # open: Mute and Stop all, the same padding all round them; the network lines
        # under them centred in the card
        pad = px(self.PAD)
        self.pair_lay.setContentsMargins(pad, pad, pad, pad)
        halves = [b for b in (self.mute, self.stop) if b is not None]
        inner = OPEN_W - 2 * SIDE_OPEN - 1 - 2 * pad
        half = (inner - px(self.PAIR_GAP) * (len(halves) - 1)) // len(halves)
        # (the odd pixel goes to the gap: the halves stay the same width)
        self.pair_lay.setSpacing(inner - half * len(halves) if len(halves) > 1 else 0)
        for b in halves:
            b.setFixedSize(half, px(self.PAIR_H))
        self._mute_look(self.power.isChecked())
        if self.stop is not None:
            icons.set_icon(self.stop, "stop", "danger_text", gap=False,
                           size=px(self.PAIR_ICON))
        self._words()
        self.pair.setVisible(expanded)
        self._line_room()
        self.top.setContentsMargins(0, 0, 0, 0)
        self.top.setDirection(QBoxLayout.Direction.TopToBottom)
        self.title.hide()   # open, Mute says it (its tip: Live or Muted, in full)
        self.caption.setVisible(not expanded)
        for w in (self.mark, self.switch):
            w.setVisible(not expanded)
        for g in (self.mark, self.status_icon):
            g.setFixedWidth(glyph)
        for n in self.net:
            n.lay_out(expanded, glyph, px)
        self.arrow.setFixedWidth(px(self.CHEVRON))
        self._name(self.power.isChecked())
        self.switch.setFixedSize(*((px(self.SWITCH[0]), px(self.SWITCH[1])) if expanded
                                   else (34, 22)))
        self._tail.changeSize(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding
                              if not expanded else QSizePolicy.Policy.Fixed)
        for gap, n in ((self._title_gap, self.GAP), (self._switch_gap, self.SWITCH_GAP),
                       (self._icon_gap, self.GAP), (self._arrow_gap, self.GAP - 2)):
            gap.changeSize(px(n), 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        if expanded:   # (the hidden row takes no room)
            for gap in (self._title_gap, self._switch_gap):
                gap.changeSize(0, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        else:
            self._title_gap.changeSize(0, 4, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            # Keep the caption with its switch; Stop all is a separate action below.
            self._switch_gap.changeSize(0, 4, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setup.setMinimumHeight(px(self.ROW_H))
        self._status_gap.changeSize(0, 0,
                                    QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.row.invalidate()
        self.box.invalidate()
        layout = self.layout()
        if layout is not None:   # (the card's own height follows a rescale at once)
            layout.invalidate()
        self.updateGeometry()
        self.top.setAlignment(self.mark, Qt.AlignmentFlag.AlignHCenter)
        self.top.setAlignment(self.caption, Qt.AlignmentFlag.AlignHCenter)
        self.top.setAlignment(self.switch, Qt.AlignmentFlag.AlignHCenter)
        self.setFixedWidth(OPEN_W - 2 * SIDE_OPEN - 1 if expanded else BUTTON_W)
        self.style().unpolish(self)
        self.style().polish(self)
        self._pin_all()
        if not expanded:   # shut: just the icon, centred over the switch
            self.mark.setContentsMargins(0, 0, 0, 0)
            self.mark.setFixedHeight(self.GLYPH)

    def _place_dot(self):
        """On the icon's top corner (the far one from the words' side)."""
        if not self.dot.isVisible():
            return
        g = self.mark.geometry()
        top = g.top() + self.mark.contentsMargins().top()
        size = self.GLYPH
        x = g.center().x() + (-size // 2 - 3 if self.isRightToLeft() else size // 2 - 5)
        self.dot.move(round(x), top - 4)
        self.dot.raise_()

    def eventFilter(self, obj: QObject, e: QEvent) -> bool:
        if obj is self.mark:
            if e.type() in (QEvent.Type.Move, QEvent.Type.Resize):
                self._place_dot()
            elif (isinstance(e, QMouseEvent) and e.type() == QEvent.Type.MouseButtonRelease
                  and self.dot.isVisible() and e.button() == Qt.MouseButton.LeftButton):
                self.connection.click()   # (Setup)
                return True
        return False

    def set_lines(self, lines: list[Line]):
        """The network lines under the status, in order (none: a direct connection
        and nothing listening)."""
        lines = list(lines)
        if lines == self._lines:
            return
        self._lines = lines
        expanded = bool(self.property("expanded"))
        while len(self.net) < len(lines):
            n = _NetLine(self)
            n.clicked.connect(lambda _c=False, n=n: self.lineClicked.emit(n.page))
            self.net.append(n)   # (in the card in its group's place: _arrange)
            n.lay_out(expanded, self._px(self.GLYPH) if expanded else self.GLYPH, self._px)
            n.label.setStyleSheet(self.title.styleSheet())   # (the card's scale)
        self.refresh()

    def names(self) -> tuple[str, str]:
        """On and off. Off with your plain voice still going out (the window sets
        "voiceonly" on the switch: engine.mic_only) says so, never "Muted"."""
        return _("On"), (_("Only your mic") if self.power.property("voiceonly")
                           else _("Muted"))

    def _words(self):
        """Mute's and Stop all's words beside their icons ("On" / "Muted", "Stop
        all"): what each does, without a hover. A word too long for its half (a
        long translation) leaves that button its icon alone, as the tip says it. Mute
        keeps its words only if both of them fit: never "On" with a bare muted icon."""
        on = self.power.isChecked()
        # (a plain space after the waves; none after the stop square, whose ink has
        # more air round it: the same gap to the eye)
        stop = self.rail_stop.property("railtext") if self.rail_stop is not None else ""
        for b, words, lead in ((self.mute, self.names(), " "), (self.stop, (stop,), "")):
            if b is None:
                continue
            # (Qt's 4 px after the icon, the border and a little air each side)
            room = b.width() - self._px(self.PAIR_ICON) - self._px(10)
            if (b is self.mute and self.power.property("voiceonly")
                    and b.fontMetrics().horizontalAdvance(lead + words[-1]) > room):
                # "Only your mic" too long for it: the short word, not none at all
                # (muted with the mic on, the button had no word left)
                words = (words[0], _("Mic only"))
            fits = all(w and b.fontMetrics().horizontalAdvance(lead + w) <= room
                       for w in words)
            word = words[0 if on or len(words) == 1 else 1]
            long = self.muted_for() if b is self.mute else ""
            if fits and long:   # both if they fit, or the time beside the struck-out icon
                both = f"{word} · {long}"
                word = both if b.fontMetrics().horizontalAdvance(lead + both) <= room else long
            b.setText(lead + word if fits else "")

    def _mute_look(self, on: bool):
        """Mute: the live waves while others hear you, struck through on red while
        they don't."""
        self.mute.setAccessibleName(self.names()[0 if on else 1])
        self.mute.setProperty("muted", not on)   # red while muted (theme.py)
        self.mute.style().unpolish(self.mute)
        self.mute.style().polish(self.mute)
        tone = "accent" if on else "danger_text"
        icons.set_icon(self.mute, "live" if on else "live_off", tone, tone, gap=False,
                       size=self._px(self.PAIR_ICON))
        self._words()

    def _name(self, on: bool):
        """"On" while others hear you, "Muted" while they don't."""
        text = self.names()[0 if on else 1]
        self.title.setText(text)
        if hasattr(self, "caption"):
            self.caption.setText(text)   # (shut: the ring alone, a time read badly there)
        self.switch.setAccessibleName(text)
        icons.set_label_icon(self.mark, "live" if on else "live_off",
                             "accent" if on else "danger_text", size=self.mark.width())

    def refresh(self):
        # the off word follows what still goes out (a voice changer or the mic switched
        # on or off while muted), not only the switch
        on = self.power.isChecked()
        self._name(on)
        self.mute.setAccessibleName(self.names()[0 if on else 1])
        self._words()
        self.switch.setToolTip(self.power.toolTip())
        self.mute.setToolTip(self.power.toolTip())
        self.mute.setAccessibleDescription(self.power.property("railfull") or "")
        self.switch.setAccessibleDescription(self.power.property("railfull") or "")
        self.status_text.setText(self.connection.property("railtext") or "")
        self.status_text.setToolTip(self.connection.property("railfull") or "")
        good = self._good()
        # "Not configured ›" takes you to Setup; "Connected" is words only: no hover, no
        # hand, out of the Tab order (never disabled: that would throw the focus)
        self.setup.setProperty("action", not good)
        self.setup.setCursor(Qt.CursorShape.ArrowCursor if good
                             else Qt.CursorShape.PointingHandCursor)
        self.setup.setFocusPolicy(Qt.FocusPolicy.NoFocus if good else Qt.FocusPolicy.TabFocus)
        self.setup.setToolTip("" if good else self.connection.toolTip())
        self.setup.setAccessibleName(self.status_text.text() if good else _("Set up output"))
        self.setup.setAccessibleDescription(self.connection.property("railfull") or "")
        self.arrow.setVisible(not good)
        small = not self.property("expanded")
        # all good: no strip, the switch says it
        self.strip.setVisible(not small and not good)
        self.strip_row.setVisible(not small and not good)
        if self.stop is not None and self.rail_stop is not None:
            self.stop.setToolTip(self.rail_stop.toolTip())
            self.stop.setAccessibleName(self.rail_stop.property("railtext") or "")
        # the small card's status line: yellow until it's set up, then green
        self.dot.set_ok(good)
        self.dot.setVisible(small)
        self.mark.setCursor(Qt.CursorShape.PointingHandCursor if small and not good
                            else Qt.CursorShape.ArrowCursor)
        self.mark.setToolTip(self.connection.toolTip() if small and not good else "")
        self._place_dot()
        self.setup.style().unpolish(self.setup)
        self.setup.style().polish(self.setup)
        theme.set_tone(self.status_text, "ok" if good else "warn")
        glyph = self._px(self.GLYPH)
        self.status_icon.setPixmap(self.connection.icon().pixmap(glyph, glyph))
        icons.set_label_icon(self.arrow, "fold_back" if self.isRightToLeft() else "fold",
                             "warn_text", size=self._px(self.CHEVRON))
        # every line as wide as the widest, so centred they share one icon column and one
        # text keyline (several lines each centred on its own zigzagged)
        words = tuple(line.words for line in self._lines)
        for i, n in enumerate(self.net[:len(self._lines)]):
            n.label._widest = words
            n.show_line(self._lines[i], self._px(self.GLYPH) if not small else self.GLYPH)
            n.label.updateGeometry()
        self._arrange(not small)
        self._line_room()
        if self.stop is not None and self.rail_stop is not None:
            self._words()
        self._pin_all()

    def _groups(self) -> dict[str, int]:
        """The groups (GROUPS order) with lines now, and how many lines each has."""
        count = {g: sum(line.group == g for line in self._lines) for g in GROUPS}
        return {g: n for g, n in count.items() if n}

    def folds(self, group: str) -> bool:
        """The group has an open / shut arrow: two lines or more (one line under its
        header would fold to the same height)."""
        return self._groups().get(group, 0) > 1

    def toggle(self, group: str):
        """Fold a group down to its header, or open it again."""
        if not self.folds(group):
            return
        self.shut ^= {group}
        self.refresh()
        self.groupToggled.emit(group, group in self.shut)

    def _arrange(self, expanded: bool):
        """The lines in their groups' order, each group under its header (open), the
        rest after them; a shut group shows its header alone. Shut (the small card):
        every line's icon, no headers."""
        groups = self._groups()
        for g in groups:
            if g not in self.heads:
                head = self.heads[g] = _GroupHead(self, g)
                head.clicked.connect(lambda _c=False, g=g: self.toggle(g))
        lines = list(zip(self._lines, self.net))
        order: list[QWidget] = []
        for g in (*GROUPS, ""):
            if g in groups:
                order.append(self.heads[g])
            order.extend(n for line, n in lines
                         if line.group == g or (not g and line.group not in GROUPS))
        if order != self._order:   # (a refresh every few seconds: re-add only on a change)
            for w in self._order:
                self.box.removeWidget(w)
            for w in order:
                self.box.addWidget(w)
            self._order = order
        for g, head in self.heads.items():
            head.setVisible(expanded and g in groups)
            if g in groups:
                head.show_head([line for line in self._lines if line.group == g],
                               self.folds(g), g in self.shut, self._px)
        for i, n in enumerate(self.net):
            line = self._lines[i] if i < len(self._lines) else None
            n.setVisible(line is not None and not (
                expanded and line.group in self.shut and self.folds(line.group)))

    def _line_room(self):
        """Open, room round the lines' hover fill and focus ring: PAIR_GAP under Mute and
        Stop all (as between them), LINE_GAP between lines, the card's padding under the
        last (the fills ran into Mute, Stop all and the card's edge). A short window
        (`tight`, the rail's compact step) keeps half of it over and under them and none
        between, so a full card still fits where it did."""
        pad = self._px(self.PAD)
        half = self._px(self.PAD // 2)
        self.pair_lay.setContentsMargins(pad, pad, pad, pad if not self._lines else half
                                         if self.tight else self._px(self.PAIR_GAP))
        expanded = bool(self.property("expanded"))
        self.box.setSpacing(self._px(self.LINE_GAP) if expanded and not self.tight else 0)
        under = (half if self.tight else pad) if expanded and self._lines else 0
        self.box.setContentsMargins(*(pad, 0, pad, under) if expanded else (0, 4, 0, 0))
        self.strip_lay.setContentsMargins(pad, 0, pad, pad)


@dataclass(frozen=True)
class Line:
    """A line in the On Air card under its status (OutputBlock.set_lines)."""
    icon: str
    words: str
    tone: str = ""   # "ok", "warn" or "" (plain)
    full: str = ""   # the tip: what it says in full
    page: str = ""   # the Settings page a click opens
    group: str = ""  # a GROUPS key: under that group's header, else after the groups


# the On Air card's groups, in order: each under a header with its name, folded down to
# it by a click once it has two lines or more
GROUPS = ("voice", "connection")


def group_name(group: str) -> str:
    return {"voice": _("Voice"), "connection": _("Connection")}.get(group, group)


class _GroupHead(QPushButton):
    """A group's header: its name, small and quiet, over its lines; with two lines or
    more, an arrow before it and a click folds the group down to it (its lines' icons
    after the name then, so what's on still shows)."""

    PT = 8.5        # the name's size (the hint text's)
    SIDE = 4        # padding inside the hover fill
    MINI_GAP = 3    # between the shut group's icons

    def __init__(self, card: OutputBlock, group: str):
        super().__init__()
        self.card, self.key = card, group
        self.setObjectName("railoutputsetup")
        self.setProperty("quiet", True)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        row = self.row = QHBoxLayout(self)
        row.setSpacing(0)
        self.arrow = card._glyph(OutputBlock.CHEVRON)
        self.name = QLabel(group_name(group))
        self.name.setObjectName("hint")
        for w in (self.arrow, self.name):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(self.arrow, 0, Qt.AlignmentFlag.AlignVCenter)
        self.gap = QSpacerItem(0, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        row.addSpacerItem(self.gap)
        row.addWidget(self.name, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)
        self.minis_box = QHBoxLayout()
        self.minis: list[QLabel] = []
        row.addLayout(self.minis_box)
        self.hide()

    def show_head(self, lines: list[Line], folds: bool, shut: bool, px):
        self.name.setText(group_name(self.key))
        self.name.setStyleSheet(f"font-size:{self.PT * self.card._scale:.2f}pt;")
        self.setFixedHeight(px(OutputBlock.HEAD_H))
        self.row.setContentsMargins(px(self.SIDE), 0, px(self.SIDE), 0)
        self.minis_box.setSpacing(px(self.MINI_GAP))
        self.arrow.setVisible(folds)
        self.arrow.setFixedWidth(px(OutputBlock.CHEVRON))
        self.gap.changeSize(px(OutputBlock.GAP) if folds else 0, 0,
                            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        if folds:
            icons.set_label_icon(self.arrow, "fold_open" if not shut else
                                 "fold_back" if self.isRightToLeft() else "fold",
                                 "muted", size=px(OutputBlock.CHEVRON))
        # shut: an icon per line after the name, in its line's colour
        shown = lines if folds and shut else []
        while len(self.minis) < len(shown):
            mini = QLabel()
            mini.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self.minis_box.addWidget(mini, 0, Qt.AlignmentFlag.AlignVCenter)
            self.minis.append(mini)
        for i, mini in enumerate(self.minis):
            mini.setVisible(i < len(shown))
            if i < len(shown):
                icons.set_label_icon(mini, shown[i].icon, {"ok": "ok_text", "warn": "warn_text"}
                                     .get(shown[i].tone, "muted"), size=px(OutputBlock.MINI))
        # only a header that folds is a button: the hover, the hand, the Tab order
        self.setProperty("action", folds)
        self.setCursor(Qt.CursorShape.PointingHandCursor if folds
                       else Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus if folds else Qt.FocusPolicy.NoFocus)
        self.setAccessibleName(group_name(self.key))
        self.setAccessibleDescription((_("Show") if shut else _("Hide")) if folds else "")
        self.setToolTip(", ".join(line.words for line in shown))
        self.style().unpolish(self)
        self.style().polish(self)


class _NetLine(QPushButton):
    """One Line: its glyph and words on the status line's keylines, the whole line
    the button (shut: the icon alone, centred under the switch)."""

    def __init__(self, card: OutputBlock):
        super().__init__()
        self.page = ""
        self.setObjectName("railoutputsetup")
        self.setProperty("quiet", True)
        self.setProperty("action", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.row = QHBoxLayout(self)
        self.row.setSpacing(0)
        self.row.addStretch(1)   # centred in the card, as the status strip's line
        self.glyph = card._glyph()
        self.label = _HugLabel("")
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignLeading | Qt.AlignmentFlag.AlignTop)
        for w in (self.glyph, self.label):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.row.addWidget(self.glyph, 0, Qt.AlignmentFlag.AlignTop)
        self.gap = QSpacerItem(OutputBlock.GAP, 0, QSizePolicy.Policy.Fixed,
                               QSizePolicy.Policy.Minimum)
        self.row.addSpacerItem(self.gap)
        self.row.addWidget(self.label, 0, Qt.AlignmentFlag.AlignTop)
        self.row.addStretch(1)
        self.hide()

    def lay_out(self, expanded: bool, glyph: int, px):
        # shut: the icon's box is the card's width, so it sits centred under the switch
        self.glyph.setFixedWidth(glyph if expanded else BUTTON_W)
        self.label.setVisible(expanded)
        self.setMinimumHeight(px(OutputBlock.ROW_H) if expanded else OutputBlock.GLYPH + 12)
        self.gap.changeSize(px(OutputBlock.GAP) if expanded else 0, 0,
                            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        self.row.invalidate()

    def show_line(self, line: Line, size: int):
        self.page = line.page
        self.label.setText(line.words)
        theme.set_tone(self.label, line.tone)
        self.setToolTip(line.full)
        self.setAccessibleName(line.words)
        self.setAccessibleDescription(line.full)
        icons.set_label_icon(self.glyph, line.icon, {"ok": "ok_text", "warn": "warn_text"}
                             .get(line.tone, "muted"), size=size)
        self.style().unpolish(self)
        self.style().polish(self)


class _HugLabel(QLabel):
    """A wrapping label that asks only for its words' width, so whatever follows it
    (a chevron) sits right after the words; short of room, it wraps. `widest`: texts
    it swaps between, sized for the widest so what follows never jumps."""

    def __init__(self, text: str, widest: tuple[str, ...] = ()):
        super().__init__(text)
        self._widest = widest

    def sizeHint(self):
        fm = self.fontMetrics()
        width = max(fm.horizontalAdvance(t) for t in (self.text(), *self._widest)) + 1
        return QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())
