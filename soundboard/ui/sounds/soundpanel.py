"""Live controls' speed, pitch, volume and effect knobs, with their typed values, quick
buttons and presets: one set of widgets that the Live controls pop-up
(ui/sounds/speedpitch.py) and Edit sound (ui/sounds/dialogs.py, both its views) lay out
their own way, so the two can't drift apart again.

`SoundPanel` holds no settings of its own: it says what was moved (`tuning_edited`,
`knobs_edited`, `volume_edited`, `preset_clicked`) and its owner keeps them, as live
amounts (Live controls) or a sound's settings (Edit sound, soundfx)."""
from __future__ import annotations

import math

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import (QAbstractSpinBox, QCheckBox, QDoubleSpinBox, QGridLayout,
                               QHBoxLayout, QLabel, QPushButton, QWidget)

from soundboard import voicefx
from soundboard.audio import livefx
from soundboard.i18n import _
from soundboard.ui.kit.panel import hint_label
from soundboard.ui.kit.widgets import widget_at
from soundboard.ui.voice.voicefxpanel import ParamSlider

NAME_W, VAL_W, GAP = 48, 52, 10         # slider columns: name | track | value
FX_NAME_W = 70                          # the effects: longer names
QUICK_SLACK = 6                         # how much a long name may push the quick rows in
QUICK = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)   # the speeds' quick buttons (the remote's steps too)


class ValueBox(QDoubleSpinBox):
    """A popup slider's value you can also type (2.5 dB, 1.3x, 40 %): the slider only
    had its positions. It stands in for ParamSlider's value label (``setText`` is how
    the slider tells it its value)."""

    def __init__(self, s: ParamSlider):
        super().__init__()
        self.s = s
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.setKeyboardTracking(False)   # typed: counts on a pause, Enter, a click away
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)   # (Tab stays on the sliders)
        self.setAccessibleName(voicefx.shown(s.q.label))
        self._q = None
        self.valueChanged.connect(self._typed)

    def _fit(self):
        q = self._q = self.s.q
        pct = not q.unit and q.lo >= 0 and q.hi <= 1
        self.scale = 100.0 if pct else 1.0
        step = (q.step or (0.01 if pct else 0.05)) * self.scale
        self.setDecimals(0 if step >= 1 else 2)
        self.setSingleStep(step)
        self.setRange(q.lo * self.scale, q.hi * self.scale)
        self.setSuffix("%" if pct else q.unit)

    def textFromValue(self, v: float) -> str:
        text = super().textFromValue(v)
        return "+" + text if v > 0 and self.minimum() < 0 else text   # +7 dB, as before

    def valueFromText(self, text: str) -> float:
        return super().valueFromText(text.lstrip("+"))

    def _number(self, text: str):
        """The number typed in `text` (sign, suffix and spaces off), or None."""
        t = text.strip()
        if self.suffix() and t.endswith(self.suffix().strip()):
            t = t[:-len(self.suffix().strip())]
        v, ok = self.locale().toDouble(t.strip().lstrip("+"))
        return v if ok else None

    def _bare_minus(self, text: str) -> bool:
        """Just "-" so far: Speed's range has no minus, but -999 still means as slow as it
        goes (dropping the key made it 999, the fastest)."""
        t = text.strip()
        if self.suffix() and t.endswith(self.suffix().strip()):
            t = t[:-len(self.suffix().strip())]
        return t.strip() == "-"

    def validate(self, text: str, pos: int):
        if text.startswith("+"):
            state, t, p = self.validate(text[1:], max(pos - 1, 0))
            return state, "+" + t, p + 1
        state, t, p = super().validate(text, pos)
        if state == QValidator.State.Invalid and (self._number(text) is not None
                                                  or self._bare_minus(text)):
            state = QValidator.State.Intermediate   # 20 past +18 dB, 1.5 with no decimals,
        return state, t, p                          # a minus on Speed: kept, fixup() caps it

    def fixup(self, text: str) -> str:
        v = self._number(text)
        if v is None and self._bare_minus(text):
            v = self.value()   # a minus and nothing else: no change
        if v is None:
            return super().fixup(text)
        v = round(min(max(v, self.minimum()), self.maximum()), self.decimals())
        return self.textFromValue(v) + self.suffix()

    def wheelEvent(self, e):
        e.ignore()   # the popup scrolls, the value doesn't change under the mouse

    def keyPressEvent(self, e):
        super().keyPressEvent(e)
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            e.accept()   # the value is in: Enter went on to the popup's Reset and undid it

    def setText(self, _text: str):
        if self._q is not self.s.q:
            self.blockSignals(True)
            self._fit()
            self.blockSignals(False)
        self.blockSignals(True)
        self.setValue(self.s.value() * self.scale)
        self.blockSignals(False)

    def _typed(self, v: float):
        self.s.set_value(v / self.scale)
        self.s.changed.emit()
        self.setText("")   # snapped to a step the slider has


def name_of(s: ParamSlider) -> QWidget:
    """A popup slider's name label (the first in its row)."""
    h = s.layout()
    w = widget_at(h, 0) if h is not None else None
    assert w is not None
    return w


def popup_slider(q: voicefx.Param, value: float, name_w: int = NAME_W) -> ParamSlider:
    """A ParamSlider laid out for the popup: no effect-row indent, a fixed name column
    so the sliders (and the quick buttons) line up, a value you can type (ValueBox).
    Edit sound's Advanced view uses the same ones (ui/sounds/dialogs.py)."""
    s = ParamSlider(q, value, centred=True)
    h = s.layout()
    assert h is not None   # name, slider, value
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(GAP)
    name_label = widget_at(h, 0)
    assert name_label is not None
    name_label.setFixedWidth(name_w)
    box = ValueBox(s)
    box.setFixedWidth(VAL_W)
    h.replaceWidget(s.val, box)
    s.val.deleteLater()
    s.val = box  # pyright: ignore[reportAttributeAccessIssue] - it stands in for the label (setText)
    s._label()
    return s


def quick_row(items, indent: int, pick, narrow: bool = False) -> QHBoxLayout:
    """Small buttons under a slider's track, so they read as part of it: `items` are
    (text, value) pairs, `pick(value)` runs on a click. `narrow`: each as wide as its
    words (a wide column), not spread across the track."""
    q = QHBoxLayout()
    q.setContentsMargins(indent, 0, 0, 0)
    q.setSpacing(4)
    for text, val in items:
        b = QPushButton(text)
        b.setObjectName("small")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(lambda __=False, val=val: pick(val))
        q.addWidget(b)
    if narrow:
        q.addStretch(1)
    return q


def preset_name(name: str) -> str:
    """A built-in live effects preset's name (livefx.PRESETS), as shown."""
    return {"Nightcore": _("Nightcore"), "Slowed + reverb": _("Slowed + reverb"),
            "Bass boosted": _("Bass boosted"), "Chipmunk": _("Chipmunk"),
            "Deep voice": _("Deep voice"), "Underwater": _("Underwater")}.get(name, name)


def _clear(w: QWidget) -> QWidget:
    w.setObjectName("spcol")    # sits on what's under it, no box of its own
    w.setStyleSheet("QWidget#spcol { background:transparent; }")
    return w


class SoundPanel(QObject):
    """The widgets (see the module doc). `speed_q`, `pitch_q`, `volume_q`: their ranges
    (Live controls' and a saved sound's differ); `volume_quick`: the volume's quick
    buttons; `narrow`: quick buttons as wide as their words (a wide column) instead of
    spread under the track; `has_speed`: False for a live stream (no speed)."""
    tuning_edited = Signal()        # speed, pitch or keep pitch moved
    knobs_edited = Signal()         # an effect knob moved
    volume_edited = Signal()
    preset_clicked = Signal(str, bool)   # a livefx.PRESETS button: (name, lit now)

    def __init__(self, speed_q: voicefx.Param, pitch_q: voicefx.Param,
                 volume_q: voicefx.Param, volume_quick, narrow: bool = False,
                 has_speed: bool = True):
        super().__init__()
        self.has_speed = has_speed
        self.speed = popup_slider(speed_q, speed_q.default)
        self.pitch = popup_slider(pitch_q, pitch_q.default)
        self.volume = popup_slider(volume_q, volume_q.default)
        # the names' column fits the longest (Lautstärke), the quick rows under it too
        self.name_w = max(NAME_W, *(name_of(s).sizeHint().width()
                                    for s in (self.speed, self.pitch, self.volume)))
        # the quick rows start under the track, but never so far in that six buttons
        # stop fitting (Äänenvoimakkuus): then a little left of it
        self.quick_x = min(self.name_w, NAME_W + QUICK_SLACK) + GAP
        self.speed_quick = _clear(QWidget())
        self.speed_quick.setLayout(quick_row(
            [(f"{x:g}x", x) for x in QUICK], self.quick_x,
            lambda x: self.speed.set_value(x) or self.tuning_edited.emit(), narrow))
        # with keep pitch off the speed moves the pitch too (Nightcore's +4.5 st): said
        # under the slider, which only holds the shift on top. Its line is kept while
        # hidden, so nothing jumps under a speed drag
        self.pitch_note = QLabel()
        self.pitch_note.setObjectName("hint")
        keep_line = self.pitch_note.sizePolicy()
        keep_line.setRetainSizeWhenHidden(has_speed)
        self.pitch_note.setSizePolicy(keep_line)
        self.pitch_note.hide()
        self.keep = QCheckBox(_("Keep pitch when changing speed"))
        self.keep.setChecked(True)
        self.keep.setToolTip(_("Off: slower is also deeper and faster is higher, like a tape"))
        self.volume_quick = _clear(QWidget())
        self.volume_quick.setLayout(quick_row(
            [(f"{lv:g}%", lv) for lv in volume_quick], self.quick_x,
            lambda lv: self.volume.set_value(lv) or self.volume_edited.emit(), narrow))
        self.set_name_width(self.name_w)
        for s in (self.speed, self.pitch):
            s.changed.connect(self.tuning_edited)
        self.keep.toggled.connect(lambda _b: self.tuning_edited.emit())
        self.volume.changed.connect(self.volume_edited)

        # the effects: one knob each, then presets that set several
        self.knobs: dict[str, ParamSlider] = {}
        for q in livefx.PARAMS:
            k = self.knobs[q.key] = popup_slider(q, q.default)
            k.changed.connect(self.knobs_edited)
        knob_w = max(FX_NAME_W, *(name_of(k).sizeHint().width() for k in self.knobs.values()))
        for k in self.knobs.values():
            name_of(k).setFixedWidth(knob_w)
        self.preset_box = _clear(QWidget())
        grid = QGridLayout(self.preset_box)
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)
        self.presets: dict[str, QPushButton] = {}
        for i, name in enumerate(livefx.PRESETS):
            b = QPushButton(preset_name(name))
            b.setObjectName("small")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda on, n=name: self.preset_clicked.emit(n, on))
            self.presets[name] = b
            grid.addWidget(b, i // 3, i % 3)
        if narrow:
            grid.setColumnStretch(3, 1)   # as wide as their words, on the left
        # what the far side does to them: a voice chat's noise removal and its cut of
        # the lowest bass took a +12 dB bass boost down to nothing for the friend
        self.fx_note = hint_label(_("A voice chat's noise suppression can wipe these out, "
                                    "deep bass too. Discord: Input Profile → Studio."))

    def set_name_width(self, w: int):
        """The speed, pitch and volume names' column (an owner lining up more sliders)."""
        self.name_w = w
        for s in (self.speed, self.pitch, self.volume):
            name_of(s).setFixedWidth(w)
        self.pitch_note.setContentsMargins(w + GAP, 0, 0, 0)

    # ------------------------------------------------------------------ values
    def values(self) -> tuple[float, float, bool]:
        return self.speed.value(), self.pitch.value(), self.keep.isChecked()

    def set_tuning(self, speed: float, pitch: float, keep: bool):
        """Speed, pitch and keep pitch, without telling (the owner set them)."""
        self.speed.set_value(speed)
        self.pitch.set_value(pitch)
        self.keep.blockSignals(True)
        self.keep.setChecked(keep)
        self.keep.blockSignals(False)

    def knob_values(self) -> dict[str, float]:
        """The knobs off 0 (livefx.clean), without the volume."""
        return livefx.clean({k: s.value() for k, s in self.knobs.items()})

    def set_knobs(self, amounts: dict):
        """Every knob (missing ones to 0), without telling."""
        for k, s in self.knobs.items():
            s.set_value(amounts.get(k, 0.0))

    def light(self, on):
        """Each preset button lit when `on(name)`."""
        for name, b in self.presets.items():
            b.setChecked(bool(on(name)))

    def show_pitch_note(self):
        """How far the speed moves the pitch while keep pitch is off, and the total with
        the slider's shift: shown only then."""
        speed, shift, keep = self.values()
        st = round(12 * math.log2(speed), 1) if self.has_speed and not keep else 0.0
        if abs(st) < 0.05:
            self.pitch_note.hide()
            return
        if abs(shift) < 1e-3:
            text = _("{st} st from the speed", st=f"{st:+g}")
        else:
            text = _("{st} st from the speed, {total} st in all", st=f"{st:+g}",
                     total=f"{round(st + shift, 1):+g}")
        self.pitch_note.setText(text)
        self.pitch_note.show()
