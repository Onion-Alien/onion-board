"""The voice changer's small controls: the on/off `Switch` and `ParamSlider`, an effect
setting's slider with its name and value."""
from __future__ import annotations

import functools

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QSlider, QStyle, QStyleOptionSlider,
                               QVBoxLayout, QWidget)

from soundboard.ui.kit import theme
from soundboard import voicefx
from soundboard.ui.kit.wheelguard import no_wheel
from soundboard.ui.kit.pixels import snap_to_pixels


# =========================================================================== voice changer

class Switch(QCheckBox):
    """An on/off switch (a pill with a knob) that behaves like a checkbox."""

    def __init__(self, tip: str = "", *, hover: bool = True):
        """`tip` is its screen-reader name, and its tooltip too unless `hover` is off
        (a switch beside words that already say what it does needs no tooltip)."""
        super().__init__()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if hover:
            self.setToolTip(tip)
        if tip:
            self.setAccessibleName(tip)
        self.setFixedSize(38, 22)

    def sizeHint(self):
        return QSize(38, 22)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, _e):
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        offset = self.property("glyphoffset") or 0
        r = QRectF(self.rect()).adjusted(1, 3 + offset, -1, -3 + offset)
        track = QColor(theme.T["accent"] if on else theme.T["groove"])
        if not self.isEnabled():
            track.setAlpha(110)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 4
        x = r.right() - d - 2 if on else r.left() + 2
        p.setBrush(QColor(theme.T["on_accent"] if on else theme.T["text"]))
        p.drawEllipse(QRectF(x, r.top() + 2, d, d))
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QColor(theme.T["accent_hi"]))
            p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), r.height() / 2 + 1, r.height() / 2 + 1)


def param_text(q: voicefx.Param, v: float) -> str:
    """How a setting's value reads next to its slider."""
    v = round(v, 3)
    if q.unit:
        return f"{v:+g}{q.unit}" if q.lo < 0 else f"{v:g}{q.unit}"
    if q.hi <= 1 and q.lo >= 0:
        return f"{round(v * 100)}%"
    return f"{v:+g}" if q.lo < 0 else f"{v:g}"


_DIGITS = str.maketrans("0123456789", "0000000000")


@functools.lru_cache(maxsize=256)
def _value_shapes(lo: float, hi: float, unit: str, steps: int) -> tuple[str, ...]:
    """Every different shape a slider's value takes (digits as 0: "-00.0 st"), so its
    label can be as wide as the widest of them. Once per kind of setting."""
    q = voicefx.Param("", "", lo, hi, lo, unit)
    return tuple(sorted({param_text(q, lo + (hi - lo) * i / steps).translate(_DIGITS)
                         for i in range(steps + 1)}))


class _ValueLabel(QLabel):
    """An effect card's value. As wide as the widest value its slider can show, and a
    new value only repaints it: QLabel.setText asks for a new layout every time, and a
    value that changed width (9 dB -> 10 dB) laid out its card, the cards around it
    and the page again (7-8 layout passes a slider step)."""

    def __init__(self, shapes: tuple[str, ...]):
        super().__init__()
        self._text = ""
        self.shapes = shapes
        self._hint = QSize()   # measured on use: the style sheet sets the font

    def set_shapes(self, shapes: tuple[str, ...]):
        self.shapes = shapes
        self._hint = QSize()
        self.updateGeometry()

    def setText(self, text: str):
        if text != self._text:
            self._text = text
            self.update()

    def text(self) -> str:
        return self._text

    def sizeHint(self):
        if not self._hint.isValid():
            fm = self.fontMetrics()
            zero = max("0123456789", key=fm.horizontalAdvance)   # the widest digit stands in
            w = max((fm.horizontalAdvance(s.replace("0", zero)) for s in self.shapes),
                    default=0)
            m = self.contentsMargins()
            pad = 2 * self.margin()
            self._hint = QSize(w + m.left() + m.right() + pad,
                               fm.height() + m.top() + m.bottom() + pad)
        return QSize(self._hint)

    def minimumSizeHint(self):
        return self.sizeHint()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._hint = QSize()
            self.updateGeometry()

    def paintEvent(self, _e):
        p = QPainter(self)
        snap_to_pixels(p)
        p.setPen(self.palette().color(self.foregroundRole()))
        p.drawText(self.contentsRect(), int(self.alignment()), self._text)


def _is_switch(q: voicefx.Param) -> bool:
    """A 0/1 parameter with a step of 1 is an on/off choice, shown as a switch."""
    return q.lo == 0 and q.hi == 1 and q.step == 1


class _NotchSlider(QSlider):
    """A slider with a small notch across its groove at `notch` (a position), where
    the "no change" value sits; hidden while the handle covers it."""

    def __init__(self):
        super().__init__(Qt.Orientation.Horizontal)
        self.notch: int | None = None

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.notch is None:
            return
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        st = self.style()
        handle = st.subControlRect(QStyle.ComplexControl.CC_Slider, opt,
                                   QStyle.SubControl.SC_SliderHandle, self)
        x = handle.width() / 2 + QStyle.sliderPositionFromValue(
            self.minimum(), self.maximum(), self.notch, self.width() - handle.width())
        if handle.left() - 2 <= x <= handle.right() + 2:
            return
        p = QPainter(self)
        p.setPen(QColor(theme.tokens()["muted"]))
        y = self.height() / 2
        p.drawLine(QPointF(x, y - 5), QPointF(x, y + 5))


class ParamSlider(QWidget):
    """One effect setting. Compact (the speed & pitch popup, a sound's effects): name,
    slider and value on one row. Otherwise (the Voice tab's effect cards): name and
    value on top, the slider, and (when the parameter names them) what its two ends
    mean underneath. A 0/1 setting is a switch instead (`slider` is then None).

    `centred`: the default ("no change": 1x, 0 st, +0 dB) sits in the middle of the
    slider even when the range is lopsided (0.25x to 2x), with a notch there; each
    half spreads its own side of the range."""
    changed = Signal()

    def __init__(self, q: voicefx.Param, value: float, compact: bool = True,
                 centred: bool = False):
        super().__init__()
        self.q = q
        self.centred = centred
        self.steps = self._steps(q)
        self.slider: QSlider | None = None
        self.switch: Switch | None = None
        self.name = QLabel(voicefx.shown(q.label))
        self.name.setObjectName("fxparam")
        # the effect cards' value, a slider's: as wide as its widest value
        self.val = (_ValueLabel(_value_shapes(q.lo, q.hi, q.unit, self.steps))
                    if not compact and not _is_switch(q) else QLabel())
        self.val.setObjectName("fxvalue")
        self.val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if compact:
            self.setMinimumHeight(26)
            h = QHBoxLayout(self)
            h.setContentsMargins(22, 0, 0, 0)
            self.name.setObjectName("")
            self.name.setFixedWidth(78)
            self.slider = _NotchSlider()
            self._set_range()
            self.val.setFixedWidth(64)
            self.val.setObjectName("eqlabel")
            h.addWidget(self.name)
            h.addWidget(self.slider, 1)
            h.addWidget(self.val)
            no_wheel(self.slider)
            self.set_value(value)
            self.slider.valueChanged.connect(self._moved)
            return
        if _is_switch(q):
            h = QHBoxLayout(self)
            h.setContentsMargins(0, 2, 0, 2)
            self.switch = Switch(voicefx.shown(q.label), hover=False)
            h.addWidget(self.name)
            h.addStretch(1)
            h.addWidget(self.switch)
            self.val.setParent(self)   # (unused, but never a window of its own)
            self.val.hide()
            self.set_value(value)
            self.switch.toggled.connect(self._moved)
            return
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 2, 0, 2)
        v.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(self.name)
        top.addStretch(1)
        top.addWidget(self.val)
        v.addLayout(top)
        self.slider = _NotchSlider()
        self._set_range()
        self.slider.setMinimumWidth(90)
        no_wheel(self.slider)
        v.addWidget(self.slider)
        if any(q.ends):
            ends = QHBoxLayout()
            for i, word in enumerate(q.ends):
                lbl = QLabel(voicefx.shown(word))
                lbl.setObjectName("fxend")
                ends.addWidget(lbl)
                if i == 0:
                    ends.addStretch(1)
            v.addLayout(ends)
        self.set_value(value)
        self.slider.valueChanged.connect(self._moved)

    def set_param(self, q: voicefx.Param):
        """Swap the range (keeps the value, clamped into the new one)."""
        v = self.value()
        self.q = q
        self.steps = self._steps(q)
        if self.slider is not None:
            self.slider.blockSignals(True)
            self._set_range()
            self.slider.blockSignals(False)
        if isinstance(self.val, _ValueLabel):
            self.val.set_shapes(_value_shapes(q.lo, q.hi, q.unit, self.steps))
        self.set_value(v)

    @staticmethod
    def _steps(q: voicefx.Param) -> int:
        return max(1, int(round((q.hi - q.lo) / q.step))) if q.step else 200

    def _half(self) -> int:
        """Centred: positions in each half (the busier side's steps), else 0."""
        q = self.q
        if not (self.centred and q.lo < q.default < q.hi):
            return 0
        if not q.step:
            return 100
        return max(int(round((q.default - q.lo) / q.step)),
                   int(round((q.hi - q.default) / q.step)))

    def _set_range(self):
        assert isinstance(self.slider, _NotchSlider)
        half = self._half()
        self.slider.setRange(0, 2 * half if half else self.steps)
        self.slider.notch = half or None

    def value(self) -> float:
        if self.switch is not None:
            return 1.0 if self.switch.isChecked() else 0.0
        assert self.slider is not None   # a switch or a slider
        q, pos, half = self.q, self.slider.value(), self._half()
        if not half:
            return q.lo + (q.hi - q.lo) * pos / self.steps
        if pos <= half:
            v = q.lo + (q.default - q.lo) * pos / half
        else:
            v = q.default + (q.hi - q.default) * (pos - half) / half
        if q.step:   # a half with fewer steps than positions: snap to a real step
            v = q.default + round((v - q.default) / q.step) * q.step
        return q.clamp(round(v, 9))

    def set_value(self, v: float):
        q = self.q
        v = q.clamp(v)
        if self.switch is not None:
            self.switch.blockSignals(True)
            self.switch.setChecked(v >= 0.5)
            self.switch.blockSignals(False)
            return
        assert self.slider is not None   # a switch or a slider
        half = self._half()
        if not half:
            pos = (v - q.lo) / ((q.hi - q.lo) or 1.0) * self.steps
        elif v <= q.default:
            pos = (v - q.lo) / (q.default - q.lo) * half
        else:
            pos = half + (v - q.default) / (q.hi - q.default) * half
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(pos)))
        self.slider.blockSignals(False)
        self._label()

    def text(self) -> str:
        return param_text(self.q, self.value())

    def _label(self):
        self.val.setText(self.text())
        if self.slider is not None:   # a screen reader said only "slider, 40"
            self.slider.setAccessibleName(voicefx.shown(self.q.label))
            self.slider.setAccessibleDescription(self.text())

    def _moved(self, _v):
        self._label()
        self.changed.emit()


def _enable(w, on: bool, why: str = ""):
    """setEnabled, and while it's off a tooltip saying why (a greyed control with no
    reason looked broken); its own tooltip comes back once it's on again."""
    if w.property("_tip") is None:
        w.setProperty("_tip", w.toolTip())
    w.setEnabled(on)
    w.setToolTip(w.property("_tip") if on or not why else why)
