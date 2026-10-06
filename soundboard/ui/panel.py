"""Shared UI building blocks: the bar / card / divider helpers every tab is built
from, the compact volume control (slider + typed %), and the equalizer. They own
their widgets and emit plain values; the main window maps those onto the config
and the engine."""
from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLayout, QSlider, QSpinBox, QVBoxLayout, QWidget)

from soundboard import theme
from soundboard.eq import BAND_LABELS as EQ_LABELS
from soundboard.eq import MAX_DB as EQ_MAX_DB
from soundboard.eq import PRESETS as EQ_PRESETS
from soundboard.ui import icons
from soundboard.ui.widgets import EqCurve, Meter
from soundboard.wheelguard import no_wheel
from soundboard.i18n import _


def section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("section")
    return lbl


def hint_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setObjectName("hint")
    return lbl


def vsep() -> QFrame:
    """A thin vertical divider between groups in a bar."""
    f = QFrame()
    f.setObjectName("vsep")
    f.setFixedWidth(1)
    return f


def bar(margins=(10, 8, 12, 8)) -> tuple[QFrame, QHBoxLayout]:
    """The rounded control bar every tab has along its bottom (and the mixer strip)."""
    f = QFrame()
    f.setObjectName("transport")
    h = QHBoxLayout(f)
    h.setContentsMargins(*margins)
    h.setSpacing(10)
    return f, h


class Flow(QLayout):
    """Lays its widgets out left to right, wrapping onto new lines (the Radio tab's
    genre chips, the Triggers tab's settings)."""

    def __init__(self, parent=None, gap: int = 6):
        super().__init__(parent)
        self._items, self._gap = [], gap
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._place(QRect(0, 0, w, 0), move=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, move=True)

    def sizeHint(self):
        # its lines at the width it has (all on one line before it's been laid out).
        # Not the narrowest width: Qt sizes a widget holding this at the height for
        # its hint's width, and a box whose height can't shrink (the Radio tab's genre
        # chips) then asked for every chip on its own line. That made the Radio tab
        # need ~300 px more whenever the window was big enough to show the chips, so
        # a maximized window restored to an ordinary size became the mini player.
        w = self.geometry().width()
        if w <= 0:
            w = sum(it.sizeHint().width() + self._gap for it in self._items
                    if not it.isEmpty()) - self._gap
        w = max(w, self.minimumSize().width())
        return QSize(w, self.heightForWidth(w))

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        return size

    def _place(self, rect: QRect, move: bool) -> int:
        """Each item is centred on its line's height: a label beside taller chips
        ("Now playing" before the sounds' ■ chips) sat at their top edge instead."""
        x, y, line = rect.x(), rect.y(), 0
        row: list = []   # (item, x, hint) of the line being filled

        def put():
            if move:
                for it, ix, hint in row:
                    it.setGeometry(QRect(QPoint(ix, y + (line - hint.height()) // 2), hint))
            row.clear()

        for it in self._items:
            if it.isEmpty():
                continue
            hint = it.sizeHint()
            if hint.width() > rect.width() > 0:   # wider than the whole row: as narrow
                hint.setWidth(max(rect.width(), it.minimumSize().width()))   # as it goes
            if line and x + hint.width() > rect.right() + 1:
                put()
                x, y, line = rect.x(), y + line + self._gap, 0
            row.append((it, x, hint))
            x += hint.width() + self._gap
            line = max(line, hint.height())
        put()
        return y + line - rect.y()


class CardGrid(QLayout):
    """Lays its widgets out as a grid of equal-width cards, as many across as fit
    at `min_w` each (at most `max_cols`), stretched to fill the row. Each row is as
    tall as its tallest card; the cards in it too, unless `even` is off (the Apps
    tab: one card's open clip editor mustn't stretch its neighbours)."""

    def __init__(self, parent=None, min_w: int = 240, gap: int = 10, max_cols: int = 0,
                 even: bool = True):
        super().__init__(parent)
        self._items, self._gap = [], gap
        self.min_w, self.max_cols = min_w, max_cols
        self.even = even   # False: each card keeps its own height, top-aligned in its row
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._place(QRect(0, 0, w, 0), move=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, move=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        return QSize(self.min_w, 0)

    def columns(self, width: int) -> int:
        """How many cards fit across `width`."""
        n = max(1, (width + self._gap) // (self.min_w + self._gap))
        return min(n, self.max_cols) if self.max_cols else n

    def _place(self, rect: QRect, move: bool) -> int:
        shown = [it for it in self._items if not it.isEmpty()]
        if not shown:
            return 0
        cols = self.columns(rect.width())
        cw = max(1, (rect.width() - self._gap * (cols - 1)) // cols)
        y = rect.y()
        for i in range(0, len(shown), cols):
            line = shown[i:i + cols]
            hs = [max(it.heightForWidth(cw) if it.hasHeightForWidth() else it.sizeHint().height(),
                      it.minimumSize().height()) for it in line]
            h = max(hs)
            if move:
                for j, it in enumerate(line):
                    it.setGeometry(QRect(rect.x() + j * (cw + self._gap), y, cw,
                                         h if self.even else hs[j]))
            y += h + self._gap
        return y - self._gap - rect.y()


class HoverCard(QFrame):
    """A card whose hover surface stays active over its child labels and controls."""

    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        self.setProperty("interactive", True)
        self.setProperty("hovered", False)

    def _hover(self, on: bool):
        if self.property("hovered") != on:
            self.setProperty("hovered", on)
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()

    def enterEvent(self, event):
        self._hover(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover(False)
        super().leaveEvent(event)


def card(title: str = "", hint: str = "", *, roomy: bool = False) -> tuple[QFrame, QVBoxLayout]:
    """A titled card, the building block of the Voice and Setup pages."""
    f = QFrame()
    f.setObjectName("card")
    v = QVBoxLayout(f)
    f.setProperty("roomy", roomy)
    v.setContentsMargins(*((18, 18, 18, 18) if roomy else (14, 8, 14, 14)))
    v.setSpacing(12 if roomy else 6)
    if title:
        v.addWidget(section_label(title))
    if hint:
        v.addWidget(hint_label(hint))
    return f, v


def icon_label(name: str, tip: str = "", color: str = "muted") -> QLabel:
    """A small painted icon used as a label in the bars."""
    lbl = QLabel()
    icons.set_label_icon(lbl, name, color)
    lbl.setToolTip(tip)
    lbl.setObjectName("iconlabel")
    return lbl


class _LevelDot(Meter):
    """Audio activity beside a volume control, without a second slider-like track."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(6, 6)
        self.setAccessibleName(_("Audio activity"))
        self.setToolTip(_("Audio activity: green is signal, amber is loud, red is near clipping"))

    def paintEvent(self, e):
        frac, color = self._bar()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color if frac > 0 else theme.T["groove"]))
        p.drawEllipse(self.rect())
        p.end()


class _Pct(QSpinBox):
    """The typeable %: as wide as its longest value in the font the theme gives it
    (known only once styled: "1000 %" in Retro 98's Tahoma didn't fit a fixed 58 px).
    Typing sets the volume once, on Enter or leaving it: as each digit came in,
    "150" went 1 %, 15 %, 150 % (a dip on a live mic) and saved three times."""

    def __init__(self):
        super().__init__()
        self.setKeyboardTracking(False)

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() in (QEvent.FontChange, QEvent.StyleChange):
            text = f"{self.maximum()}{self.suffix()}"
            self.setFixedWidth(max(58, self.fontMetrics().horizontalAdvance(text) + 14))


class VolumeControl(QWidget):
    """Slider to `slider_max` %, plus a % you can click and type an exact value into
    (up to `typed_max`). `changed` carries the gain as a factor (1.0 = 100 %).
    With `meter`, a small audio-activity dot (`.meter`) sits beside the slider."""
    changed = Signal(float)

    def __init__(self, value: float, slider_max: int = 300, typed_max: int = 1000,
                 tip: str = "", meter: bool = False):
        super().__init__()
        self.slider_max = slider_max
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        self.slider = QSlider(Qt.Horizontal)
        self.meter = _LevelDot() if meter else None
        if self.meter is not None:
            h.addWidget(self.meter)
        self.slider.setRange(0, slider_max)
        self.slider.setMinimumWidth(70)
        self.slider.setMaximumWidth(150)
        self.spin = _Pct()
        self.spin.setObjectName("pct")   # reads as plain text until hovered / typed in
        self.spin.setRange(0, typed_max)
        self.spin.setSuffix(" %")
        self.spin.setFixedWidth(58)   # until it's styled (_Pct)
        self.spin.setAlignment(Qt.AlignRight)
        self.spin.setToolTip(_("Type an exact volume (0–{typed_max}%)", typed_max=typed_max))
        if tip:
            self.slider.setToolTip(tip)
        h.addWidget(self.slider, 1)
        h.addWidget(self.spin)
        no_wheel(self.slider, self.spin)

        pct0 = int(round(value * 100))
        self.slider.setValue(min(pct0, slider_max))
        self.spin.setValue(pct0)
        self._paint(pct0)
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)

    def value(self) -> float:
        return self.spin.value() / 100

    def _paint(self, pct):
        col = ("" if pct <= 100 else f"color:{theme.status('warn' if pct <= 300 else 'error')};")
        sheet = f"{col} font-weight:600;"   # normal: the theme's text colour
        if sheet != self.spin.styleSheet():   # each set re-polishes it: only on a change
            self.spin.setStyleSheet(sheet)

    def _from_slider(self, pct):
        self.spin.blockSignals(True)
        self.spin.setValue(pct)
        self.spin.blockSignals(False)
        self._paint(pct)
        self.changed.emit(pct / 100)

    def _from_spin(self, pct):
        self.slider.blockSignals(True)
        self.slider.setValue(min(pct, self.slider_max))
        self.slider.blockSignals(False)
        self._paint(pct)
        self.changed.emit(pct / 100)


class EqPanel(QWidget):
    """On/off, target, preset, curve and the seven band sliders.
    `changed(gains, enabled, target, preset)` fires on any change."""
    changed = Signal(list, bool, str, str)

    def __init__(self, enabled: bool, target: str, preset: str, gains: list[float]):
        super().__init__()
        pv = QVBoxLayout(self)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(8)
        pv.addWidget(section_label("EQUALIZER"))
        row = QHBoxLayout()
        self.chk_on = QCheckBox(_("EQ on"))
        self.chk_on.setChecked(enabled)
        row.addWidget(self.chk_on)
        self.lbl_for = QLabel("for")
        row.addWidget(self.lbl_for)
        self.cb_target = QComboBox()
        for label, key in (("My voice", "voice"), ("My sounds", "sounds"), ("Both", "all")):
            self.cb_target.addItem(label, key)
        icons.set_item_icons(self.cb_target, ["mic", "volume", "wave"])
        self.cb_target.setCurrentIndex(max(0, self.cb_target.findData(target)))
        row.addWidget(self.cb_target, 1)
        pv.addLayout(row)

        self.cb_preset = QComboBox()
        self.cb_preset.addItems(list(EQ_PRESETS))
        self.cb_preset.addItem(_("Custom"))
        pv.addWidget(self.cb_preset)
        no_wheel(self.cb_target, self.cb_preset)

        self.curve = EqCurve()
        pv.addWidget(self.curve)

        grid = QGridLayout()
        grid.setHorizontalSpacing(2)
        grid.setVerticalSpacing(2)
        self.sliders, self.vals = [], []
        for i, lab in enumerate(EQ_LABELS):
            val = QLabel("0")
            val.setAlignment(Qt.AlignCenter)
            val.setObjectName("eqlabel")
            s = QSlider(Qt.Vertical)
            s.setRange(-EQ_MAX_DB * 2, EQ_MAX_DB * 2)   # half-dB steps
            s.setFixedHeight(96)
            s.setToolTip(_("{lab} Hz", lab=lab))
            f = QLabel(lab)
            f.setAlignment(Qt.AlignCenter)
            f.setObjectName("eqlabel")
            grid.addWidget(val, 0, i)
            grid.addWidget(s, 1, i, Qt.AlignHCenter)
            grid.addWidget(f, 2, i)
            s.valueChanged.connect(self._on_slider)
            self.sliders.append(s)
            self.vals.append(val)
        no_wheel(*self.sliders)
        pv.addLayout(grid)
        pv.addWidget(hint_label(_("Low = bass (left) · high = treble (right). Drag up to boost, "
                                  "down to cut. Double-click the curve to reset.")))

        self._set_sliders(gains)
        self.cb_preset.setCurrentText(preset if preset in EQ_PRESETS else "Custom")
        self.chk_on.toggled.connect(lambda _on: self._emit())
        self.cb_target.currentIndexChanged.connect(lambda _i: self._emit())
        self.cb_preset.currentTextChanged.connect(self._on_preset)
        self.curve.reset.connect(self._reset)
        self._refresh(emit=False)

    # ---- state
    def gains(self) -> list[float]:
        return [s.value() / 2 for s in self.sliders]

    def set_gains(self, gains: list[float], preset: str = "Custom"):
        """Load gains, turning the EQ on unless they're flat. Emits `changed`."""
        self._set_sliders(gains)
        self.cb_preset.blockSignals(True)
        self.cb_preset.setCurrentText(preset if preset in EQ_PRESETS else "Custom")
        self.cb_preset.blockSignals(False)
        self.chk_on.blockSignals(True)
        self.chk_on.setChecked(any(abs(g) >= 0.05 for g in self.gains()))
        self.chk_on.blockSignals(False)
        self._emit()

    def state(self) -> tuple[list[float], bool, str, str]:
        return (self.gains(), self.chk_on.isChecked(), self.cb_target.currentData(),
                self.cb_preset.currentText())

    # ---- internals
    def _set_sliders(self, gains):
        # a damaged config can hand us anything: a band that isn't a finite number, or
        # a list of the wrong length, is flat (0 dB) instead of an error
        if not isinstance(gains, (list, tuple)) or len(gains) != len(self.sliders):
            gains = [0.0] * len(self.sliders)
        for s, g in zip(self.sliders, gains):
            ok = isinstance(g, (int, float)) and not isinstance(g, bool) and math.isfinite(g)
            s.blockSignals(True)
            s.setValue(int(round(min(max(g, -EQ_MAX_DB), EQ_MAX_DB) * 2)) if ok else 0)
            s.blockSignals(False)
        self._refresh_labels()

    def _refresh_labels(self):
        for s, lab in zip(self.sliders, self.vals):
            g = s.value() / 2
            lab.setText(f"{g:+g}" if g else "0")

    def _on_slider(self, _v):
        self._refresh_labels()
        self.cb_preset.blockSignals(True)
        self.cb_preset.setCurrentText("Custom")
        self.cb_preset.blockSignals(False)
        if not self.chk_on.isChecked():
            self.chk_on.setChecked(True)   # touching the EQ means you want it on (emits)
            return
        self._emit()

    def _reset(self):
        """Double-click on the curve: flat and off, even if it already says Flat."""
        self.cb_preset.blockSignals(True)
        self.cb_preset.setCurrentText("Flat (off)")
        self.cb_preset.blockSignals(False)
        self._on_preset("Flat (off)")

    def _on_preset(self, name):
        if name in EQ_PRESETS:
            self._set_sliders(EQ_PRESETS[name])
            # "Flat (off)" means off, like set_gains with flat gains; any other turns it on
            on = name != "Flat (off)"
            if self.chk_on.isChecked() != on:
                self.chk_on.setChecked(on)   # emits
                return
        self._emit()

    def _refresh(self, emit=True):
        gains, on, _target, _preset = self.state()
        self.curve.set_gains(gains, on)
        for w in self.sliders + [self.cb_target]:
            if bool(w.property("dim")) != (not on):
                w.setProperty("dim", not on)
                w.style().unpolish(w)   # a property change alone doesn't restyle it
                w.style().polish(w)
                w.update()
        if emit:
            self.changed.emit(*self.state())

    def _emit(self):
        self._refresh(emit=True)


class UndoBar(QFrame):
    """"Deleted X · Undo" for a few seconds after something is thrown away.
    show_for(text, undo, done): Undo calls `undo`; the bar timing out, being
    dismissed, or showing something else calls `done` (if given) instead."""
    SECONDS = 10

    def __init__(self, tip: str = "Put it back, exactly as it was"):
        super().__init__()
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QPushButton
        self.setObjectName("chip")
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 4, 4, 4)
        self.label = QLabel()
        self.label.setTextFormat(Qt.PlainText)   # names are user / web text
        h.addWidget(self.label, 1)
        self.btn_undo = QPushButton(_("Undo"))
        self.btn_undo.setObjectName("primary")
        self.btn_undo.setToolTip(tip)
        self.btn_undo.clicked.connect(self.undo)
        h.addWidget(self.btn_undo)
        dismiss = QPushButton()
        dismiss.setObjectName("chipstop")
        dismiss.setToolTip(_("Dismiss"))
        dismiss.setFixedSize(24, 24)
        icons.set_icon(dismiss, "stop", size=10)
        dismiss.clicked.connect(self.finish)
        h.addWidget(dismiss)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.finish)
        self._undo = self._done = None
        self.hide()

    def show_for(self, text: str, undo, done=None):
        self.finish()
        self.label.setText(self.label.fontMetrics().elidedText(text, Qt.ElideRight, 320))
        self._undo, self._done = undo, done
        self.show()
        self._timer.start(self.SECONDS * 1000)

    def undo(self):
        cb, self._undo, self._done = self._undo, None, None
        self._timer.stop()
        self.hide()
        if cb is not None:
            cb()

    def finish(self):
        cb, self._undo, self._done = self._done, None, None
        self._timer.stop()
        self.hide()
        if cb is not None:
            cb()
